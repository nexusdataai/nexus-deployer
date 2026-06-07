"""
AWS Secrets Manager backup/restore module.

Backup:  for each operator-provisioned secret name {capability}/{env}/{type},
         fetch the current value (string or binary) and write it to
         secrets/secrets.json. Binary values (e.g. bssmagic-credentials.zip)
         are base64-encoded so the JSON tarball survives the trip.

Restore: writes to {target-cap}/{target-env}/{type}, using PutSecretValue
         (or CreateSecret if the target doesn't exist yet). The operator
         pre-creates these names with empty placeholder values when the
         NexusCapability CR is applied, so PutSecretValue is the common
         path; we fall back to CreateSecret for any that are missing.

The value-rewrite is intentionally conservative: most secrets are opaque
(API keys, OAuth tokens, signed JWT-like blobs) and rewriting bytes inside
them would corrupt them. We only rewrite if SecretString parses as JSON
AND contains string fields that match env-bearing substrings.
"""

from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from config import (
    BINARY_SECRET_TYPES,
    SECRET_TYPES,
    secret_name,
    secrets_prefix,
)


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sys.stdout.write(f"[{ts}] {msg}\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(session, capability: str, env: str, output_dir: Path) -> Dict[str, Any]:
    """Fetch every operator-provisioned secret under {capability}/{env}/."""
    sm = session.client("secretsmanager")
    dest = output_dir / "secrets"
    dest.mkdir(parents=True, exist_ok=True)

    _log(f"  Secrets prefix={secrets_prefix(capability, env)}")

    items: List[Dict[str, Any]] = []
    skipped: List[str] = []

    for secret_type in SECRET_TYPES:
        name = secret_name(capability, env, secret_type)
        try:
            resp = sm.get_secret_value(SecretId=name)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("ResourceNotFoundException", "DecryptionFailure"):
                _log(f"    SKIP {name} ({code})")
                skipped.append(secret_type)
                continue
            raise

        entry: Dict[str, Any] = {
            "SecretType": secret_type,
            "Name": name,
            "ARN": resp.get("ARN"),
            "VersionId": resp.get("VersionId"),
            "CreatedDate": resp["CreatedDate"].isoformat() if resp.get("CreatedDate") else None,
        }
        # Either SecretString or SecretBinary will be present.
        if "SecretString" in resp:
            entry["SecretString"] = resp["SecretString"]
        if "SecretBinary" in resp:
            entry["SecretBinary_b64"] = base64.b64encode(resp["SecretBinary"]).decode("ascii")
        items.append(entry)

    out = dest / "secrets.json"
    out.write_text(json.dumps(items, indent=2))

    _log(f"  Secrets done: {len(items)} secret(s) backed up, {len(skipped)} not present")
    return {
        "secret_count": len(items),
        "secret_types": [it["SecretType"] for it in items],
        "skipped_types": skipped,
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _rewrite_secret_string(
    value: str,
    src_capability: str,
    src_env: str,
    tgt_capability: str,
    tgt_env: str,
    src_account_id: Optional[str],
    tgt_account_id: Optional[str],
) -> str:
    """Only rewrite if the SecretString parses as JSON. Opaque/JWT-ish blobs
    are passed through verbatim — replacing bytes inside them would corrupt
    signatures or otherwise break downstream callers."""
    if not value:
        return value
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value

    if not isinstance(parsed, (dict, list)):
        return value

    src_hyphen = f"{src_capability}-{src_env}-"
    tgt_hyphen = f"{tgt_capability}-{tgt_env}-"
    src_slash = f"{src_capability}/{src_env}/"
    tgt_slash = f"{tgt_capability}/{tgt_env}/"

    def _rewrite_str(s: str) -> str:
        if not isinstance(s, str):
            return s
        new = s
        if src_hyphen in new:
            new = new.replace(src_hyphen, tgt_hyphen)
        if src_slash in new:
            new = new.replace(src_slash, tgt_slash)
        if src_account_id and tgt_account_id and src_account_id != tgt_account_id:
            new = new.replace(src_account_id, tgt_account_id)
        return new

    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        if isinstance(obj, str):
            return _rewrite_str(obj)
        return obj

    return json.dumps(_walk(parsed))


def restore(
    session,
    target_capability: str,
    target_env: str,
    target_account_id: str,
    local_dir: Path,
    source_capability: Optional[str] = None,
    source_env: Optional[str] = None,
    source_account_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Write each secret to {target_cap}/{target_env}/{type}."""
    src_file = local_dir / "secrets" / "secrets.json"
    if not src_file.exists():
        _log("  Secrets SKIP: not in backup")
        return {"restored": 0, "skipped": True}

    items = json.loads(src_file.read_text())
    if not items:
        _log("  Secrets SKIP: backup is empty")
        return {"restored": 0, "skipped": True}

    # Infer source capability/env from first secret name if not provided.
    sample = items[0]["Name"]
    if source_capability is None or source_env is None:
        parts = sample.split("/", 2)
        if len(parts) < 2:
            _log(f"  Secrets ERROR: cannot infer source from {sample}")
            return {"restored": 0, "skipped": True}
        source_capability = source_capability or parts[0]
        source_env = source_env or parts[1]

    sm = session.client("secretsmanager")
    restored = 0
    created = 0
    errors: List[str] = []

    for item in items:
        secret_type = item["SecretType"]
        target_name = secret_name(target_capability, target_env, secret_type)

        # Build the new value
        if "SecretBinary_b64" in item:
            new_binary = base64.b64decode(item["SecretBinary_b64"])
            new_string = None
        else:
            new_binary = None
            new_string = item.get("SecretString", "")
            new_string = _rewrite_secret_string(
                new_string,
                source_capability, source_env,
                target_capability, target_env,
                source_account_id, target_account_id,
            )

        if dry_run:
            kind = "binary" if new_binary else "string"
            _log(f"    DRY: {item['Name']} -> {target_name} ({kind})")
            restored += 1
            continue

        kwargs: Dict[str, Any] = {"SecretId": target_name}
        if new_binary is not None:
            kwargs["SecretBinary"] = new_binary
        else:
            kwargs["SecretString"] = new_string

        try:
            sm.put_secret_value(**kwargs)
            restored += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ResourceNotFoundException":
                # Target secret doesn't exist yet — create it.
                create_kwargs: Dict[str, Any] = {"Name": target_name}
                if new_binary is not None:
                    create_kwargs["SecretBinary"] = new_binary
                else:
                    create_kwargs["SecretString"] = new_string
                try:
                    sm.create_secret(**create_kwargs)
                    restored += 1
                    created += 1
                except ClientError as ce:
                    ce_code = ce.response.get("Error", {}).get("Code", "")
                    _log(f"    WARN: create_secret {target_name} failed ({ce_code})")
                    errors.append(f"{target_name}: {ce_code}")
            else:
                _log(f"    WARN: put_secret_value {target_name} failed ({code})")
                errors.append(f"{target_name}: {code}")

    _log(f"  Secrets done: {restored} restored ({created} newly created), {len(errors)} error(s)")
    return {
        "restored": restored,
        "created": created,
        "errors": errors,
    }
