#!/usr/bin/env python3
"""
Nexus DR Backup & Restore CLI (v2.0)

Backs up everything needed to clone a Nexus capability into another AWS
account and EKS cluster:

  S3 buckets, DynamoDB tables, SSM parameters, AWS Secrets Manager,
  Glue catalog, Cognito user pool, Kubernetes state via Velero
  (including PVCs), and a separate pg_dump of the BSS Magic Postgres.

The output is a single .tar.gz containing a manifest.json plus one
sub-directory per component. The same CLI restores into the target
account, rewriting env-bearing resource names along the way
({capability}-{src-env}-... -> {capability}-{tgt-env}-...).

Usage:
    python3 backup_restore.py backup  --env dev --output backup.tar.gz \\
        --profile ptr-tech --cluster nexus-dev \\
        --include ssm,secrets,s3,dynamodb,glue,kubernetes,postgres

    python3 backup_restore.py restore --input backup.tar.gz \\
        --target-env test --target-profile new-account \\
        --target-cluster nexus-test \\
        --target-velero-bucket nexus-velero-backups-NEWACCT
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import boto3
from botocore.exceptions import ClientError

from config import (
    CAPABILITY,
    COMPONENTS,
    DEFAULT_COMPONENTS,
    DYNAMODB_SOURCES,
    GROUPS,
    MANIFEST_SCHEMA_VERSION,
    S3_SOURCES,
    resolve_bucket_name,
    resolve_prefix,
    resolve_table_name,
)

# New component modules
import cognito_backup
import glue_backup
import kubernetes_velero
import postgres_backup
import secrets_backup
import ssm_backup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o == int(o) else float(o)
        return super().default(o)


def _ts():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str):
    sys.stdout.write(f"[{_ts()}] {msg}\n")
    sys.stdout.flush()


def _make_session(profile=None, region=None, role_arn=None):
    if role_arn:
        base = boto3.Session(profile_name=profile, region_name=region)
        creds = base.client("sts").assume_role(
            RoleArn=role_arn, RoleSessionName="nexus-backup-restore"
        )["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
    return boto3.Session(profile_name=profile, region_name=region)


def _filter_sources(sources, groups):
    if not groups:
        return sources
    return [s for s in sources if s.get("group") in groups]


def _get_account_id(session):
    return session.client("sts").get_caller_identity()["Account"]


def _parse_csv(value: Optional[str], valid: Set[str], label: str) -> Optional[Set[str]]:
    if not value:
        return None
    req = {v.strip() for v in value.split(",") if v.strip()}
    bad = req - valid - {"all"}
    if bad:
        _log(f"ERROR: unknown {label} {bad}. Valid: {sorted(valid)}")
        sys.exit(1)
    return None if "all" in req else req


# ---------------------------------------------------------------------------
# S3 Backup
# ---------------------------------------------------------------------------

def backup_s3_source(s3, src, capability, env, account_id, output_dir):
    bucket = resolve_bucket_name(src, capability, env, account_id, s3)
    prefix = resolve_prefix(src)
    name = src["name"]
    dest = output_dir / "s3" / name
    dest.mkdir(parents=True, exist_ok=True)
    include_prefixes = src.get("include_prefixes")

    _log(f"  S3 [{name}] bucket={bucket} prefix={prefix or '(root)'}")

    total_objects = 0
    total_bytes = 0
    paginator = s3.get_paginator("list_objects_v2")
    kw: Dict[str, Any] = {"Bucket": bucket}
    if prefix:
        kw["Prefix"] = prefix

    errors = 0
    try:
        for page in paginator.paginate(**kw):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if include_prefixes and not any(key.startswith(p) for p in include_prefixes):
                    continue
                rel = key[len(prefix):].lstrip("/") if prefix else key
                if not rel:
                    continue
                local = dest / rel
                local.parent.mkdir(parents=True, exist_ok=True)
                try:
                    resp = s3.get_object(Bucket=bucket, Key=key)
                    with open(local, "wb") as f:
                        for chunk in resp["Body"].iter_chunks(65536):
                            f.write(chunk)
                except Exception as dl_err:
                    errors += 1
                    if errors <= 5:
                        _log(f"    WARN: skip {key}: {dl_err}")
                    elif errors == 6:
                        _log(f"    WARN: suppressing further per-object warnings...")
                    continue
                total_objects += 1
                total_bytes += obj.get("Size", 0)
                if total_objects % 50 == 0:
                    _log(f"    ... {total_objects} objects")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchBucket", "AccessDenied", "404"):
            _log(f"  S3 [{name}] SKIP ({code}): {bucket}")
            return {"name": name, "bucket": bucket, "objects": 0, "bytes": 0, "skipped": True}
        raise

    msg = f"  S3 [{name}] done: {total_objects} objects, {total_bytes:,} bytes"
    if errors:
        msg += f" ({errors} skipped)"
    _log(msg)
    return {"name": name, "bucket": bucket, "prefix": prefix,
            "objects": total_objects, "bytes": total_bytes, "errors": errors}


# ---------------------------------------------------------------------------
# DynamoDB Backup
# ---------------------------------------------------------------------------

def backup_ddb_source(dynamodb, src, capability, env, output_dir):
    table_name = resolve_table_name(src, capability, env)
    name = src["name"]
    dest = output_dir / "dynamodb"
    dest.mkdir(parents=True, exist_ok=True)
    jsonl_path = dest / f"{name}.jsonl"

    _log(f"  DDB [{name}] table={table_name}")
    count = 0

    try:
        table = dynamodb.Table(table_name)
        table.load()
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        _log(f"  DDB [{name}] SKIP ({code}): {table_name}")
        return {"name": name, "table": table_name, "items": 0, "skipped": True}

    with open(jsonl_path, "w") as fh:
        scan_kw: Dict[str, Any] = {}
        while True:
            resp = table.scan(**scan_kw)
            for item in resp.get("Items", []):
                fh.write(json.dumps(item, cls=DecimalEncoder, ensure_ascii=False) + "\n")
                count += 1
            if "LastEvaluatedKey" not in resp:
                break
            scan_kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            if count % 200 == 0:
                _log(f"    ... {count} items")

    _log(f"  DDB [{name}] done: {count} items")
    return {"name": name, "table": table_name, "items": count}


# ---------------------------------------------------------------------------
# DynamoDB Item value rewriting (for env rename on restore)
# ---------------------------------------------------------------------------

def _rewrite_ddb_value(
    v, src_cap, src_env, tgt_cap, tgt_env, src_acct, tgt_acct,
):
    """Recursively rewrite env-bearing substrings in DDB item values."""
    if isinstance(v, str):
        s = v
        sh = f"{src_cap}-{src_env}-"
        th = f"{tgt_cap}-{tgt_env}-"
        if sh in s:
            s = s.replace(sh, th)
        ss = f"/{src_cap}/{src_env}/"
        ts = f"/{tgt_cap}/{tgt_env}/"
        if ss in s:
            s = s.replace(ss, ts)
        slash = f"{src_cap}/{src_env}/"
        tslash = f"{tgt_cap}/{tgt_env}/"
        if slash in s:
            s = s.replace(slash, tslash)
        su = f"{src_cap.replace('-', '_')}_{src_env}_"
        tu = f"{tgt_cap.replace('-', '_')}_{tgt_env}_"
        if su in s:
            s = s.replace(su, tu)
        if src_acct and tgt_acct and src_acct != tgt_acct:
            s = s.replace(src_acct, tgt_acct)
        return s
    if isinstance(v, list):
        return [_rewrite_ddb_value(x, src_cap, src_env, tgt_cap, tgt_env, src_acct, tgt_acct) for x in v]
    if isinstance(v, dict):
        return {k: _rewrite_ddb_value(val, src_cap, src_env, tgt_cap, tgt_env, src_acct, tgt_acct) for k, val in v.items()}
    return v


# ---------------------------------------------------------------------------
# S3 Restore
# ---------------------------------------------------------------------------

def restore_s3_source(s3, meta, local_dir, target_cap, target_env, account_id):
    name = meta["name"]
    src_dir = local_dir / "s3" / name
    if not src_dir.exists():
        _log(f"  S3 [{name}] SKIP: not in backup")
        return {"name": name, "uploaded": 0, "skipped": True}

    src_def = next((s for s in S3_SOURCES if s["name"] == name), None)
    if not src_def:
        _log(f"  S3 [{name}] SKIP: unknown source")
        return {"name": name, "uploaded": 0, "skipped": True}

    target_bucket = resolve_bucket_name(src_def, target_cap, target_env, account_id, s3)
    target_prefix = resolve_prefix(src_def)

    _log(f"  S3 [{name}] -> {target_bucket} (prefix={target_prefix or 'root'})")

    files = []
    for root, _, fnames in os.walk(src_dir):
        for fn in fnames:
            lp = Path(root) / fn
            rel = lp.relative_to(src_dir).as_posix()
            key = f"{target_prefix}/{rel}" if target_prefix else rel
            files.append((str(lp), target_bucket, key.lstrip("/")))

    uploaded = 0
    def _up(args):
        s3.upload_file(args[0], args[1], args[2])
        return 1

    with ThreadPoolExecutor(max_workers=16) as pool:
        for f in as_completed([pool.submit(_up, a) for a in files]):
            uploaded += f.result()
            if uploaded % 50 == 0 and uploaded > 0:
                _log(f"    ... {uploaded}/{len(files)}")

    _log(f"  S3 [{name}] done: {uploaded} objects")
    return {"name": name, "target_bucket": target_bucket, "uploaded": uploaded}


# ---------------------------------------------------------------------------
# DynamoDB Restore (with item-value rewriting)
# ---------------------------------------------------------------------------

def restore_ddb_source(
    dynamodb, meta, local_dir, target_cap, target_env,
    src_cap, src_env, src_acct, tgt_acct,
):
    name = meta["name"]
    jsonl = local_dir / "dynamodb" / f"{name}.jsonl"
    if not jsonl.exists():
        _log(f"  DDB [{name}] SKIP: not in backup")
        return {"name": name, "written": 0, "skipped": True}

    src_def = next((s for s in DYNAMODB_SOURCES if s["name"] == name), None)
    if not src_def:
        return {"name": name, "written": 0, "skipped": True}

    target_table = resolve_table_name(src_def, target_cap, target_env)
    _log(f"  DDB [{name}] -> {target_table}")

    try:
        table = dynamodb.Table(target_table)
        table.load()
    except ClientError as e:
        _log(f"  DDB [{name}] SKIP ({e.response['Error']['Code']}): {target_table}")
        return {"name": name, "target_table": target_table, "written": 0, "skipped": True}

    written = 0
    batch = []
    rewrite_needed = (
        src_cap != target_cap or src_env != target_env
        or (src_acct and tgt_acct and src_acct != tgt_acct)
    )

    def _flush():
        nonlocal written
        if not batch:
            return
        with table.batch_writer() as w:
            for item in batch:
                w.put_item(Item=item)
        written += len(batch)
        batch.clear()

    with open(jsonl) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line, parse_float=Decimal)
            if rewrite_needed:
                item = _rewrite_ddb_value(
                    item, src_cap, src_env, target_cap, target_env,
                    src_acct, tgt_acct,
                )
            batch.append(item)
            if len(batch) >= 25:
                _flush()
                if written % 200 == 0 and written > 0:
                    _log(f"    ... {written} items")
    _flush()

    _log(f"  DDB [{name}] done: {written} items")
    return {"name": name, "target_table": target_table, "written": written}


# ---------------------------------------------------------------------------
# Backup command
# ---------------------------------------------------------------------------

def cmd_backup(args):
    cap, env, region = args.capability, args.env, args.region
    groups = _parse_csv(args.only, GROUPS, "group")
    components = _parse_csv(args.include, COMPONENTS, "component") or DEFAULT_COMPONENTS.copy()
    excluded = _parse_csv(args.exclude, COMPONENTS, "component") or set()
    components = components - excluded

    session = _make_session(profile=args.profile, region=region, role_arn=args.role_arn)
    account_id = _get_account_id(session)
    s3 = session.client("s3")
    ddb = session.resource("dynamodb")

    s3_srcs = _filter_sources(S3_SOURCES, groups)
    ddb_srcs = _filter_sources(DYNAMODB_SOURCES, groups)

    _log(f"Backup: env={env} cap={cap} region={region} account={account_id}")
    _log(f"  Components: {sorted(components)}")
    _log(f"  S3 sources: {len(s3_srcs)}, DDB sources: {len(ddb_srcs)}")

    if args.dry_run:
        _log("DRY RUN:")
        if "s3" in components:
            for src in s3_srcs:
                bkt = resolve_bucket_name(src, cap, env, account_id, s3)
                _log(f"  S3: {src['name']} -> {bkt}")
        if "dynamodb" in components:
            for src in ddb_srcs:
                _log(f"  DDB: {src['name']} -> {resolve_table_name(src, cap, env)}")
        for c in ("ssm", "secrets", "glue", "cognito", "kubernetes", "postgres"):
            if c in components:
                _log(f"  {c.upper()}: planned")
        return

    with tempfile.TemporaryDirectory(prefix="nexus-backup-") as tmpdir:
        root = Path(tmpdir) / f"nexus-backup-{cap}-{env}-{_ts()}"
        root.mkdir()

        results: Dict[str, Any] = {}

        if "s3" in components:
            _log("--- S3 Backup ---")
            results["s3"] = [backup_s3_source(s3, src, cap, env, account_id, root) for src in s3_srcs]

        if "dynamodb" in components:
            _log("--- DynamoDB Backup ---")
            results["dynamodb"] = [backup_ddb_source(ddb, src, cap, env, root) for src in ddb_srcs]

        if "ssm" in components:
            _log("--- SSM Backup ---")
            results["ssm"] = ssm_backup.backup(session, cap, env, root)

        if "secrets" in components:
            _log("--- Secrets Manager Backup ---")
            results["secrets"] = secrets_backup.backup(session, cap, env, root)

        if "glue" in components:
            _log("--- Glue Backup ---")
            results["glue"] = glue_backup.backup(session, cap, env, root)

        if "cognito" in components:
            _log("--- Cognito Backup ---")
            results["cognito"] = cognito_backup.backup(session, cap, env, root)

        if "kubernetes" in components:
            _log("--- Kubernetes (Velero) Backup ---")
            results["kubernetes"] = kubernetes_velero.backup(
                session, cap, env, root,
                velero_bucket=args.velero_bucket,
            )

        if "postgres" in components:
            _log("--- BSS Magic Postgres Backup ---")
            results["postgres"] = postgres_backup.backup(session, cap, env, root)

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "account_id": account_id,
                "region": region,
                "capability": cap,
                "env": env,
                "cluster_name": args.cluster or "",
                "velero_bucket": args.velero_bucket or "",
            },
            "components_included": sorted(components),
            "groups_included": sorted(groups) if groups else ["all"],
            **results,
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2, cls=DecimalEncoder))

        _log(f"Creating tarball: {args.output}")
        with tarfile.open(args.output, "w:gz") as tar:
            tar.add(str(root), arcname=root.name)

        _log("Backup complete:")
        if "s3" in components:
            ts3 = sum(r.get("objects", 0) for r in results.get("s3", []))
            _log(f"  S3: {ts3} objects across {len(results['s3'])} bucket(s)")
        if "dynamodb" in components:
            tddb = sum(r.get("items", 0) for r in results.get("dynamodb", []))
            _log(f"  DDB: {tddb} items across {len(results['dynamodb'])} table(s)")
        if "ssm" in components:
            _log(f"  SSM: {results['ssm'].get('parameter_count', 0)} parameter(s)")
        if "secrets" in components:
            _log(f"  Secrets: {results['secrets'].get('secret_count', 0)} secret(s)")
        if "glue" in components:
            _log(f"  Glue: {results['glue'].get('table_count', 0)} table(s), "
                 f"{results['glue'].get('partition_count', 0)} partition(s)")
        if "cognito" in components:
            _log(f"  Cognito: {results['cognito'].get('user_count', 0)} user(s)")
        if "kubernetes" in components:
            _log(f"  K8s: velero backup={results['kubernetes'].get('backup_name')}")
        if "postgres" in components:
            _log(f"  Postgres: {results['postgres'].get('dump_bytes', 0):,} bytes")
        _log(f"  -> {args.output}")


# ---------------------------------------------------------------------------
# Restore command
# ---------------------------------------------------------------------------

def cmd_restore(args):
    target_env = args.target_env
    target_cap = args.target_capability
    groups = _parse_csv(args.only, GROUPS, "group")
    components = _parse_csv(args.include, COMPONENTS, "component") or DEFAULT_COMPONENTS.copy()
    excluded = _parse_csv(args.exclude, COMPONENTS, "component") or set()
    components = components - excluded

    session = _make_session(
        profile=args.target_profile, region=args.target_region,
        role_arn=args.target_role_arn,
    )
    target_account_id = _get_account_id(session)

    _log(f"Restore: target_env={target_env} cap={target_cap} account={target_account_id}")
    _log(f"  Components: {sorted(components)}")

    with tempfile.TemporaryDirectory(prefix="nexus-restore-") as tmpdir:
        _log("Extracting tarball...")
        with tarfile.open(args.input, "r:gz") as tar:
            tar.extractall(tmpdir)

        entries = list(Path(tmpdir).iterdir())
        if len(entries) != 1 or not entries[0].is_dir():
            _log("ERROR: tarball must contain one top-level directory"); sys.exit(1)
        root = entries[0]

        manifest = json.loads((root / "manifest.json").read_text())
        src = manifest.get("source", {})
        src_cap = src.get("capability", "nexus-ai")
        src_env = src.get("env", "dev")
        src_acct = src.get("account_id")
        schema_v = manifest.get("schema_version", "1.0")
        _log(f"  Source: env={src_env} cap={src_cap} account={src_acct} schema={schema_v}")

        # ---- Restore execution order (see plan §7) ----

        # 1. SSM (operator may have written placeholders; backup wins)
        if "ssm" in components:
            _log("--- SSM Restore ---")
            ssm_backup.restore(
                session, target_cap, target_env, target_account_id, root,
                source_capability=src_cap, source_env=src_env,
                source_account_id=src_acct, dry_run=args.dry_run,
            )

        # 2. Secrets
        if "secrets" in components:
            _log("--- Secrets Manager Restore ---")
            secrets_backup.restore(
                session, target_cap, target_env, target_account_id, root,
                source_capability=src_cap, source_env=src_env,
                source_account_id=src_acct, dry_run=args.dry_run,
            )

        # 3. DynamoDB items
        if "dynamodb" in components:
            _log("--- DynamoDB Restore ---")
            ddb = session.resource("dynamodb")
            ddb_metas = manifest.get("dynamodb", [])
            if groups:
                ddb_names = {s["name"] for s in _filter_sources(DYNAMODB_SOURCES, groups)}
                ddb_metas = [m for m in ddb_metas if m["name"] in ddb_names]
            for m in ddb_metas:
                if m.get("skipped"):
                    continue
                if args.dry_run:
                    sd = next((s for s in DYNAMODB_SOURCES if s["name"] == m["name"]), None)
                    if sd:
                        _log(f"  DRY DDB: {m['name']} ({m.get('items','?')} items) "
                             f"-> {resolve_table_name(sd, target_cap, target_env)}")
                else:
                    restore_ddb_source(
                        ddb, m, root, target_cap, target_env,
                        src_cap, src_env, src_acct, target_account_id,
                    )

        # 4. S3 objects
        if "s3" in components:
            _log("--- S3 Restore ---")
            s3 = session.client("s3")
            s3_metas = manifest.get("s3", [])
            if groups:
                s3_names = {s["name"] for s in _filter_sources(S3_SOURCES, groups)}
                s3_metas = [m for m in s3_metas if m["name"] in s3_names]
            for m in s3_metas:
                if m.get("skipped"):
                    continue
                if args.dry_run:
                    sd = next((s for s in S3_SOURCES if s["name"] == m["name"]), None)
                    if sd:
                        _log(f"  DRY S3: {m['name']} ({m.get('objects','?')} objs) "
                             f"-> {resolve_bucket_name(sd, target_cap, target_env, target_account_id, s3)}")
                else:
                    restore_s3_source(s3, m, root, target_cap, target_env, target_account_id)

        # 5. Glue
        if "glue" in components:
            _log("--- Glue Restore ---")
            glue_backup.restore(
                session, target_cap, target_env, target_account_id, root,
                source_capability=src_cap, source_env=src_env,
                source_account_id=src_acct, dry_run=args.dry_run,
            )

        # 6. Cognito
        if "cognito" in components:
            _log("--- Cognito Restore ---")
            cognito_backup.restore(
                session, target_cap, target_env, target_account_id, root,
                source_capability=src_cap, source_env=src_env,
                source_account_id=src_acct, dry_run=args.dry_run,
            )

        # 7. (Re-)apply NexusCapability CR with target env  +  8. Velero
        if "kubernetes" in components:
            _log("--- Re-apply NexusCapability CR with target env ---")
            kubernetes_velero.apply_capability_cr(
                root, target_cap, target_env,
                target_namespace=args.target_namespace,
                dry_run=args.dry_run,
            )

            _log("--- Kubernetes (Velero) Restore ---")
            kubernetes_velero.restore(
                session, target_cap, target_env, target_account_id, root,
                source_capability=src_cap, source_env=src_env,
                source_account_id=src_acct,
                target_velero_bucket=args.target_velero_bucket,
                target_namespace=args.target_namespace,
                restore_volumes=not args.no_restore_volumes,
                dry_run=args.dry_run,
            )

        # 9. Postgres (after Velero brings the PVC + pod back)
        if "postgres" in components:
            _log("--- BSS Magic Postgres Restore ---")
            postgres_backup.restore(
                session, target_cap, target_env, target_account_id, root,
                source_capability=src_cap, source_env=src_env,
                source_account_id=src_acct,
                target_namespace=args.target_namespace,
                dry_run=args.dry_run,
            )

        _log("Restore complete.")
        _log("Next step: kubectl annotate nexuscapability "
             f"{target_cap}-{target_env} -n {args.target_namespace or target_cap + '-' + target_env} "
             "reconcile=$(date +%s) --overwrite")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        description="Nexus DR Backup & Restore (v2.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Components: {','.join(sorted(COMPONENTS))} (default: {','.join(sorted(DEFAULT_COMPONENTS))})
Groups (S3+DDB only): {','.join(sorted(GROUPS))}

Examples:
  # Full backup of nexus-dev
  python3 backup_restore.py backup --env dev -o backup.tar.gz \\
      --profile ptr-tech --cluster nexus-dev \\
      --velero-bucket nexus-velero-backups-654654554404

  # Partial backup (S3+DDB only, simulators group)
  python3 backup_restore.py backup --env dev --include s3,dynamodb \\
      --only simulators -o sims.tar.gz --profile ptr-tech

  # Cross-account restore, env rename dev -> test
  python3 backup_restore.py restore -i backup.tar.gz \\
      --target-env test --target-profile new-account \\
      --target-cluster nexus-test \\
      --target-velero-bucket nexus-velero-backups-NEWACCT \\
      --dry-run
""")
    sub = p.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("backup", help="Backup to portable tarball")
    bp.add_argument("--env", required=True)
    bp.add_argument("--capability", default=CAPABILITY)
    bp.add_argument("--region", default="us-east-1")
    bp.add_argument("-o", "--output", required=True, help="Output .tar.gz path")
    bp.add_argument("--include", help="Components: " + ",".join(sorted(COMPONENTS)))
    bp.add_argument("--exclude", help="Components to skip")
    bp.add_argument("--only", help=f"S3/DDB groups: {','.join(sorted(GROUPS))},all")
    bp.add_argument("--profile", help="AWS profile")
    bp.add_argument("--role-arn", help="IAM role ARN to assume")
    bp.add_argument("--cluster", help="EKS cluster name (recorded in manifest)")
    bp.add_argument("--velero-bucket", help="Source velero S3 bucket (e.g. nexus-velero-backups-ACCTID)")
    bp.add_argument("--dry-run", action="store_true")

    rp = sub.add_parser("restore", help="Restore tarball into target account/cluster")
    rp.add_argument("-i", "--input", required=True, help="Input .tar.gz path")
    rp.add_argument("--target-env", required=True)
    rp.add_argument("--target-capability", default=CAPABILITY)
    rp.add_argument("--target-region", default="us-east-1")
    rp.add_argument("--include", help="Components: " + ",".join(sorted(COMPONENTS)))
    rp.add_argument("--exclude", help="Components to skip")
    rp.add_argument("--only", help=f"S3/DDB groups: {','.join(sorted(GROUPS))},all")
    rp.add_argument("--target-profile", help="AWS profile for target")
    rp.add_argument("--target-role-arn", help="IAM role ARN for target")
    rp.add_argument("--target-cluster", help="Target EKS cluster name (informational)")
    rp.add_argument("--target-velero-bucket", help="Velero S3 bucket in TARGET account")
    rp.add_argument("--target-namespace", help="K8s namespace on target (default: {cap}-{env})")
    rp.add_argument("--no-restore-volumes", action="store_true",
                    help="Skip Velero PVC restore (faster; assumes you'll rebuild data from S3/DDB)")
    rp.add_argument("--dry-run", action="store_true")

    args = p.parse_args()
    {"backup": cmd_backup, "restore": cmd_restore}[args.command](args)


if __name__ == "__main__":
    main()
