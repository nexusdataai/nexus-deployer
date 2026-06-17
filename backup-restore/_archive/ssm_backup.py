"""
SSM Parameter Store backup/restore module.

Backup:  recursively dumps every parameter under /{capability}/{env}/ into
         ssm/parameters.json inside the DR tarball.
Restore: rewrites the path prefix to /{capability}/{target-env}/ and also
         performs a value-substring rewrite so any embedded references to
         old bucket/table names ({capability}-{src-env}-*) become
         {capability}-{tgt-env}-* (and source account_id becomes target).

Public API:
    backup(session, capability, env, output_dir) -> dict (manifest entry)
    restore(session, target_cap, target_env, target_account_id,
            local_dir, source_account_id=None, dry_run=False) -> dict
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from config import ssm_prefix


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sys.stdout.write(f"[{ts}] {msg}\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(session, capability: str, env: str, output_dir: Path) -> Dict[str, Any]:
    """Export the full /{capability}/{env}/ parameter tree."""
    ssm = session.client("ssm")
    prefix = ssm_prefix(capability, env)
    dest = output_dir / "ssm"
    dest.mkdir(parents=True, exist_ok=True)

    _log(f"  SSM prefix={prefix}")

    parameters: List[Dict[str, Any]] = []
    paginator = ssm.get_paginator("get_parameters_by_path")
    try:
        for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
            for p in page.get("Parameters", []):
                parameters.append({
                    "Name": p["Name"],
                    "Type": p.get("Type", "String"),
                    "Value": p.get("Value", ""),
                    "Version": p.get("Version"),
                    "LastModifiedDate": p["LastModifiedDate"].isoformat() if p.get("LastModifiedDate") else None,
                    "ARN": p.get("ARN"),
                    "DataType": p.get("DataType", "text"),
                })
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        _log(f"  SSM SKIP ({code}): {prefix}")
        return {"prefix": prefix, "parameter_count": 0, "skipped": True, "error": code}

    out = dest / "parameters.json"
    out.write_text(json.dumps(parameters, indent=2))

    _log(f"  SSM done: {len(parameters)} parameter(s) -> ssm/parameters.json")
    return {"prefix": prefix, "parameter_count": len(parameters)}


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _rewrite_path(name: str, src_prefix: str, tgt_prefix: str) -> str:
    if name.startswith(src_prefix):
        return tgt_prefix + name[len(src_prefix):]
    return name


def _rewrite_value(
    value: str,
    src_capability: str,
    src_env: str,
    tgt_capability: str,
    tgt_env: str,
    src_account_id: Optional[str] = None,
    tgt_account_id: Optional[str] = None,
) -> str:
    """Rewrite env- and account-bearing substrings in parameter values.

    Covers:
      - bucket / table names: {cap}-{src-env}-...  ->  {cap}-{tgt-env}-...
      - SSM paths:            /{cap}/{src-env}/... ->  /{cap}/{tgt-env}/...
      - secret names:         {cap}/{src-env}/...  ->  {cap}/{tgt-env}/...
      - account ID in bucket suffix (...-{src-account}) and ARNs
    """
    if not value:
        return value

    new = value
    # Bucket / table / IAM role names: {cap}-{src-env}-
    src_hyphen = f"{src_capability}-{src_env}-"
    tgt_hyphen = f"{tgt_capability}-{tgt_env}-"
    if src_hyphen in new:
        new = new.replace(src_hyphen, tgt_hyphen)

    # SSM paths and secret names share the {cap}/{src-env}/ prefix (with slash)
    src_slash = f"{src_capability}/{src_env}/"
    tgt_slash = f"{tgt_capability}/{tgt_env}/"
    if src_slash in new:
        new = new.replace(src_slash, tgt_slash)

    # /{cap}/{src-env}/ (leading slash, SSM paths inside string values)
    src_lslash = f"/{src_capability}/{src_env}/"
    tgt_lslash = f"/{tgt_capability}/{tgt_env}/"
    if src_lslash in new:
        new = new.replace(src_lslash, tgt_lslash)

    # Glue DB: nexus_ai_dev_db (underscores)
    src_under = f"{src_capability.replace('-', '_')}_{src_env}_"
    tgt_under = f"{tgt_capability.replace('-', '_')}_{tgt_env}_"
    if src_under in new:
        new = new.replace(src_under, tgt_under)

    # Account ID substitution (last so it applies to remaining ARNs/buckets)
    if src_account_id and tgt_account_id and src_account_id != tgt_account_id:
        new = new.replace(src_account_id, tgt_account_id)

    return new


def restore(
    session,
    target_capability: str,
    target_env: str,
    target_account_id: str,
    local_dir: Path,
    source_capability: Optional[str] = None,
    source_env: Optional[str] = None,
    source_account_id: Optional[str] = None,
    overwrite: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Restore SSM parameters with prefix + value rewrite."""
    src_file = local_dir / "ssm" / "parameters.json"
    if not src_file.exists():
        _log("  SSM SKIP: not in backup")
        return {"restored": 0, "skipped": True}

    parameters = json.loads(src_file.read_text())
    if not parameters:
        _log("  SSM SKIP: backup is empty")
        return {"restored": 0, "skipped": True}

    # Infer source prefix from the first parameter
    sample_name = parameters[0]["Name"]
    if source_capability is None or source_env is None:
        parts = sample_name.strip("/").split("/", 2)
        if len(parts) < 2:
            _log(f"  SSM ERROR: cannot infer source from {sample_name}")
            return {"restored": 0, "skipped": True, "error": "bad-prefix"}
        source_capability = source_capability or parts[0]
        source_env = source_env or parts[1]

    src_prefix = f"/{source_capability}/{source_env}/"
    tgt_prefix = ssm_prefix(target_capability, target_env)

    _log(f"  SSM {src_prefix} -> {tgt_prefix} ({len(parameters)} param(s))")

    ssm = session.client("ssm")
    restored = 0
    skipped = 0
    errors: List[str] = []

    for p in parameters:
        new_name = _rewrite_path(p["Name"], src_prefix, tgt_prefix)
        new_value = _rewrite_value(
            p.get("Value", ""),
            source_capability, source_env,
            target_capability, target_env,
            source_account_id, target_account_id,
        )

        if dry_run:
            _log(f"    DRY: {p['Name']} -> {new_name}")
            restored += 1
            continue

        try:
            kwargs: Dict[str, Any] = {
                "Name": new_name,
                "Value": new_value,
                "Type": p.get("Type", "String"),
                "Overwrite": overwrite,
            }
            # Some parameters carry an explicit DataType (e.g., aws:ec2:image)
            if p.get("DataType") and p["DataType"] != "text":
                kwargs["DataType"] = p["DataType"]
            ssm.put_parameter(**kwargs)
            restored += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ParameterAlreadyExists" and not overwrite:
                skipped += 1
                continue
            msg = f"    WARN: put_parameter {new_name} failed ({code})"
            _log(msg)
            errors.append(f"{new_name}: {code}")

    _log(f"  SSM done: {restored} restored, {skipped} skipped, {len(errors)} error(s)")
    return {
        "restored": restored,
        "skipped": skipped,
        "errors": errors,
        "target_prefix": tgt_prefix,
    }
