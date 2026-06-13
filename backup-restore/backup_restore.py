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
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from config import (
    CAPABILITY,
    COMPONENTS,
    DEFAULT_COMPONENTS,
    DYNAMODB_SOURCES,
    GROUPS,
    LOGICAL_ENTITIES,
    MANIFEST_SCHEMA_VERSION,
    NOOP_ENTITIES,
    PRESETS,
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
# Logical entity helpers
# ---------------------------------------------------------------------------

def _filter_key(filter_spec: Optional[Dict[str, Any]]) -> Optional[str]:
    """Stable, hashable identity for a filter_spec (used as dict key for de-dup)."""
    if filter_spec is None:
        return None
    if "gsi1pk" in filter_spec:
        return f"gsi1pk={filter_spec['gsi1pk']}"
    if "gsi1pk_in" in filter_spec:
        return "gsi1pk_in=" + ",".join(sorted(filter_spec["gsi1pk_in"]))
    return repr(sorted(filter_spec.items()))


def _resolve_entities(entities_arg: Optional[str],
                      preset_arg: Optional[str]) -> List[str]:
    """Normalise --entities / --preset to a flat list of entity names.

    Returns [] if neither flag was provided. Validates against
    LOGICAL_ENTITIES + NOOP_ENTITIES; exits the process on unknown values.
    """
    if not entities_arg and not preset_arg:
        return []

    valid = set(LOGICAL_ENTITIES.keys()) | NOOP_ENTITIES
    out: List[str] = []
    seen: Set[str] = set()

    if preset_arg:
        if preset_arg not in PRESETS:
            _log(f"ERROR: unknown preset '{preset_arg}'. Valid: {sorted(PRESETS)}")
            sys.exit(1)
        for ent in PRESETS[preset_arg]:
            if ent not in seen:
                out.append(ent)
                seen.add(ent)

    if entities_arg:
        req = {v.strip() for v in entities_arg.split(",") if v.strip()}
        if "all" in req:
            req = (req - {"all"}) | set(LOGICAL_ENTITIES.keys())
        bad = req - valid
        if bad:
            _log(f"ERROR: unknown entities {sorted(bad)}. "
                 f"Valid: {sorted(valid)}")
            sys.exit(1)
        for ent in sorted(req):
            if ent not in seen:
                out.append(ent)
                seen.add(ent)

    return out


def _s3_src_by_name(name: str) -> Optional[Dict[str, Any]]:
    return next((s for s in S3_SOURCES if s["name"] == name), None)


def _ddb_src_by_name(name: str) -> Optional[Dict[str, Any]]:
    return next((s for s in DYNAMODB_SOURCES if s["name"] == name), None)


# ---------------------------------------------------------------------------
# S3 Backup
# ---------------------------------------------------------------------------

def backup_s3_source(s3, src, capability, env, account_id, output_dir, workers: int = 32):
    """Bulk-parallel download of an S3 prefix into ``output_dir/s3/<name>/``.

    Mirrors the restore-side pattern (ThreadPoolExecutor). Each worker
    issues a single ``GetObject`` per file; concurrency is at the file
    level, not via multipart. The S3 client passed in should already be
    configured with ``max_pool_connections >= workers`` so the HTTPS
    connection pool isn't the bottleneck.
    """
    bucket = resolve_bucket_name(src, capability, env, account_id, s3)
    prefix = resolve_prefix(src)
    name = src["name"]
    dest = output_dir / "s3" / name
    dest.mkdir(parents=True, exist_ok=True)
    include_prefixes = src.get("include_prefixes")

    _log(f"  S3 [{name}] bucket={bucket} prefix={prefix or '(root)'} workers={workers}")

    paginator = s3.get_paginator("list_objects_v2")
    kw: Dict[str, Any] = {"Bucket": bucket}
    if prefix:
        kw["Prefix"] = prefix

    counters_lock = threading.Lock()
    total_objects = 0
    total_bytes = 0
    errors = 0
    warn_emitted = 0

    def _download_one(key: str, size: int):
        nonlocal total_objects, total_bytes, errors, warn_emitted
        rel = key[len(prefix):].lstrip("/") if prefix else key
        if not rel:
            return
        local = dest / rel
        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            with open(local, "wb") as f:
                for chunk in resp["Body"].iter_chunks(65536):
                    f.write(chunk)
        except Exception as dl_err:  # noqa: BLE001
            with counters_lock:
                errors += 1
                if warn_emitted < 5:
                    _log(f"    WARN: skip {key}: {dl_err}")
                    warn_emitted += 1
                elif warn_emitted == 5:
                    _log(f"    WARN: suppressing further per-object warnings...")
                    warn_emitted += 1
            return
        with counters_lock:
            total_objects += 1
            total_bytes += size
            if total_objects % 500 == 0:
                _log(f"    ... {total_objects} objects, {total_bytes:,} bytes")

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            inflight: List = []
            for page in paginator.paginate(**kw):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if include_prefixes and not any(key.startswith(p) for p in include_prefixes):
                        continue
                    inflight.append(pool.submit(_download_one, key, obj.get("Size", 0)))
                # Drain periodically so memory doesn't blow up for huge buckets
                if len(inflight) >= 10_000:
                    for fut in as_completed(inflight):
                        fut.result()
                    inflight = []
            for fut in as_completed(inflight):
                fut.result()
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
    """Legacy entry-point: full-table scan, no entity tag.

    Kept so existing cmd_backup paths (when --entities is not set) keep
    using their current behaviour and manifest shape. New code paths go
    through backup_ddb_filtered() directly.
    """
    return backup_ddb_filtered(dynamodb, src, capability, env, output_dir,
                               entity=None, filter_spec=None)


def backup_ddb_filtered(dynamodb, src, capability, env, output_dir, *,
                        entity: Optional[str] = None,
                        filter_spec: Optional[Dict[str, Any]] = None):
    """Backup a DynamoDB table, optionally filtered by GSI1 partition key.

    filter_spec shapes:
      None                          -> full table scan (legacy behaviour)
      {"gsi1pk": "<value>"}         -> Query(IndexName="GSI1", GSI1PK eq <value>)
      {"gsi1pk_in": [<v>, ...]}     -> one Query per value, results concatenated

    If GSI1 is not present on the table, falls back to Scan + in-process
    filter on the GSI1PK attribute. JSONL filename:
      filter_spec is None              -> dynamodb/{name}.jsonl  (legacy)
      filter_spec is non-None + entity -> dynamodb/{name}.{entity}.jsonl
    """
    from boto3.dynamodb.conditions import Key

    table_name = resolve_table_name(src, capability, env)
    name = src["name"]
    dest = output_dir / "dynamodb"
    dest.mkdir(parents=True, exist_ok=True)

    if filter_spec is not None and entity:
        rel_file = f"{name}.{entity}.jsonl"
    else:
        rel_file = f"{name}.jsonl"
    jsonl_path = dest / rel_file

    if filter_spec and "gsi1pk" in filter_spec:
        filter_desc = f" gsi1pk={filter_spec['gsi1pk']}"
    elif filter_spec and "gsi1pk_in" in filter_spec:
        filter_desc = f" gsi1pk_in={filter_spec['gsi1pk_in']}"
    else:
        filter_desc = ""

    label = f"[{entity}/{name}]" if (entity and filter_spec is not None) else f"[{name}]"
    _log(f"  DDB {label} table={table_name}{filter_desc}")

    try:
        table = dynamodb.Table(table_name)
        table.load()
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        _log(f"  DDB {label} SKIP ({code}): {table_name}")
        result: Dict[str, Any] = {"name": name, "table": table_name,
                                  "items": 0, "skipped": True}
        if entity:
            result["entity"] = entity
            if filter_spec is not None:
                result["filter"] = filter_spec
            result["file"] = f"dynamodb/{rel_file}"
        return result

    def _scan_all():
        scan_kw: Dict[str, Any] = {}
        while True:
            resp = table.scan(**scan_kw)
            for item in resp.get("Items", []):
                yield item
            if "LastEvaluatedKey" not in resp:
                break
            scan_kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def _gsi1_query(values: List[str]):
        try:
            gsis = table.global_secondary_indexes or []
        except Exception:
            gsis = []
        gsi1_available = any(idx.get("IndexName") == "GSI1" for idx in gsis)

        if gsi1_available:
            for v in values:
                query_kw: Dict[str, Any] = {
                    "IndexName": "GSI1",
                    "KeyConditionExpression": Key("GSI1PK").eq(v),
                }
                while True:
                    resp = table.query(**query_kw)
                    for item in resp.get("Items", []):
                        yield item
                    if "LastEvaluatedKey" not in resp:
                        break
                    query_kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        else:
            _log(f"    GSI1 not present on {table_name}; "
                 f"falling back to Scan + filter on GSI1PK in {values}")
            value_set = set(values)
            for item in _scan_all():
                if item.get("GSI1PK") in value_set:
                    yield item

    if filter_spec is None:
        item_iter = _scan_all()
    elif "gsi1pk" in filter_spec:
        item_iter = _gsi1_query([filter_spec["gsi1pk"]])
    elif "gsi1pk_in" in filter_spec:
        item_iter = _gsi1_query(list(filter_spec["gsi1pk_in"]))
    else:
        raise ValueError(f"Unknown filter_spec shape: {filter_spec!r}")

    count = 0
    with open(jsonl_path, "w") as fh:
        for item in item_iter:
            fh.write(json.dumps(item, cls=DecimalEncoder, ensure_ascii=False) + "\n")
            count += 1
            if count % 200 == 0:
                _log(f"    ... {count} items")

    _log(f"  DDB {label} done: {count} items")
    result = {"name": name, "table": table_name, "items": count}
    if entity:
        result["entity"] = entity
        if filter_spec is not None:
            result["filter"] = filter_spec
        result["file"] = f"dynamodb/{rel_file}"
    return result


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
    # Manifest 2.1 entity-tagged entries carry an explicit "file" path;
    # 2.0 entries default to dynamodb/{name}.jsonl.
    rel_file = meta.get("file", f"dynamodb/{name}.jsonl")
    jsonl = local_dir / rel_file
    entity = meta.get("entity")
    label = f"[{entity}/{name}]" if entity else f"[{name}]"

    if not jsonl.exists():
        _log(f"  DDB {label} SKIP: not in backup ({rel_file})")
        return {"name": name, "written": 0, "skipped": True}

    src_def = next((s for s in DYNAMODB_SOURCES if s["name"] == name), None)
    if not src_def:
        return {"name": name, "written": 0, "skipped": True}

    target_table = resolve_table_name(src_def, target_cap, target_env)
    _log(f"  DDB {label} -> {target_table}")

    try:
        table = dynamodb.Table(target_table)
        table.load()
    except ClientError as e:
        _log(f"  DDB {label} SKIP ({e.response['Error']['Code']}): {target_table}")
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

    _log(f"  DDB {label} done: {written} items")
    result = {"name": name, "target_table": target_table, "written": written}
    if entity:
        result["entity"] = entity
    return result


# ---------------------------------------------------------------------------
# Backup command
# ---------------------------------------------------------------------------

def cmd_backup(args):
    cap, env, region = args.capability, args.env, args.region

    # --entities/--preset is mutually exclusive with --only (group filter);
    # the logical-entity model already picks specific tables+filters.
    entities = _resolve_entities(args.entities, args.preset)
    if entities and args.only:
        _log("ERROR: --only cannot be combined with --entities or --preset")
        sys.exit(1)

    groups = _parse_csv(args.only, GROUPS, "group")
    # When --entities is set the s3/dynamodb components are the implicit
    # base (so the entity recipes actually run); --include then composes
    # *additively* on top of that base for opt-in infra components
    # (ssm/secrets/glue/cognito/k8s/postgres). Without --entities,
    # behaviour is unchanged: --include either replaces or, if absent,
    # falls back to DEFAULT_COMPONENTS.
    user_include = _parse_csv(args.include, COMPONENTS, "component")
    if entities:
        components: Set[str] = {"s3", "dynamodb"} | (user_include or set())
    else:
        components = user_include if user_include is not None else DEFAULT_COMPONENTS.copy()
    excluded = _parse_csv(args.exclude, COMPONENTS, "component") or set()
    components = components - excluded

    session = _make_session(profile=args.profile, region=region, role_arn=args.role_arn)
    account_id = _get_account_id(session)
    # Connection pool must be >= worker count, otherwise threads contend
    # for HTTPS connections and the parallelism is wasted.
    s3_cfg = BotoConfig(max_pool_connections=max(args.s3_workers, 10),
                        retries={"max_attempts": 10, "mode": "adaptive"})
    s3 = session.client("s3", config=s3_cfg)
    ddb = session.resource("dynamodb")

    # Build the per-component source lists. With --entities the lists are
    # derived from the logical-entity recipes; otherwise from groups.
    ddb_jobs: List[Dict[str, Any]] = []  # [{src, entity, filter}, ...] de-duped
    s3_srcs: List[Dict[str, Any]] = []

    if entities:
        # Skip noop entities at runtime, log them so users know they were
        # accepted but not backed up here.
        noops = [e for e in entities if e in NOOP_ENTITIES]
        active = [e for e in entities if e not in NOOP_ENTITIES]
        for e in noops:
            _log(f"  (noop) entity '{e}' source-of-truth is repo YAML / image; "
                 f"skipping DR-level backup")

        ddb_seen: Dict[tuple, Dict[str, Any]] = {}
        s3_seen: Set[str] = set()
        for ent in active:
            spec = LOGICAL_ENTITIES[ent]
            for tbl_name, flt in spec.get("tables", []):
                src = _ddb_src_by_name(tbl_name)
                if not src:
                    _log(f"  WARN: entity '{ent}' references unknown DDB "
                         f"source '{tbl_name}'; skipping")
                    continue
                key = (tbl_name, _filter_key(flt))
                if key not in ddb_seen:
                    ddb_seen[key] = {"src": src, "entity": ent, "filter": flt}
            for bkt_name in spec.get("buckets", []):
                if bkt_name in s3_seen:
                    continue
                src = _s3_src_by_name(bkt_name)
                if not src:
                    _log(f"  WARN: entity '{ent}' references unknown S3 "
                         f"source '{bkt_name}'; skipping")
                    continue
                s3_seen.add(bkt_name)
                s3_srcs.append(src)
        ddb_jobs = list(ddb_seen.values())
    else:
        s3_srcs = _filter_sources(S3_SOURCES, groups)
        ddb_srcs = _filter_sources(DYNAMODB_SOURCES, groups)
        ddb_jobs = [{"src": s, "entity": None, "filter": None} for s in ddb_srcs]

    _log(f"Backup: env={env} cap={cap} region={region} account={account_id}")
    _log(f"  Components: {sorted(components)}")
    if entities:
        _log(f"  Logical entities: {entities}")
    _log(f"  S3 sources: {len(s3_srcs)}, DDB jobs: {len(ddb_jobs)}")

    if args.dry_run:
        _log("DRY RUN:")
        if "s3" in components:
            for src in s3_srcs:
                bkt = resolve_bucket_name(src, cap, env, account_id, s3)
                _log(f"  S3: {src['name']} -> {bkt}")
        if "dynamodb" in components:
            for job in ddb_jobs:
                fdesc = ""
                if job["filter"]:
                    fdesc = f" filter={job['filter']}"
                tag = f"{job['entity']}/" if job["entity"] else ""
                _log(f"  DDB: {tag}{job['src']['name']} -> "
                     f"{resolve_table_name(job['src'], cap, env)}{fdesc}")
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
            results["s3"] = [
                backup_s3_source(s3, src, cap, env, account_id, root, workers=args.s3_workers)
                for src in s3_srcs
            ]

        if "dynamodb" in components:
            _log("--- DynamoDB Backup ---")
            results["dynamodb"] = [
                backup_ddb_filtered(ddb, job["src"], cap, env, root,
                                    entity=job["entity"], filter_spec=job["filter"])
                for job in ddb_jobs
            ]

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
            "logical_entities": entities if entities else [],
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

    entities = _resolve_entities(args.entities, args.preset)
    if entities and args.only:
        _log("ERROR: --only cannot be combined with --entities or --preset")
        sys.exit(1)

    groups = _parse_csv(args.only, GROUPS, "group")
    # Additive --include composition when --entities/--preset is set;
    # see matching block in cmd_backup for rationale.
    user_include = _parse_csv(args.include, COMPONENTS, "component")
    if entities:
        components: Set[str] = {"s3", "dynamodb"} | (user_include or set())
    else:
        components = user_include if user_include is not None else DEFAULT_COMPONENTS.copy()
    excluded = _parse_csv(args.exclude, COMPONENTS, "component") or set()
    components = components - excluded

    # When --entities/--preset is set, derive the allow-lists used to
    # filter the manifest's dynamodb[] and s3[] entries. Each entity
    # contributes (table_name, filter_key) pairs and bucket names.
    entity_ddb_keys: Optional[Set[tuple]] = None
    entity_bucket_names: Optional[Set[str]] = None
    if entities:
        entity_ddb_keys = set()
        entity_bucket_names = set()
        for ent in entities:
            if ent in NOOP_ENTITIES:
                _log(f"  (noop) entity '{ent}' is repo YAML / image-baked; "
                     f"no DR-level restore performed")
                continue
            spec = LOGICAL_ENTITIES[ent]
            for tbl_name, flt in spec.get("tables", []):
                entity_ddb_keys.add((tbl_name, _filter_key(flt)))
            for bkt in spec.get("buckets", []):
                entity_bucket_names.add(bkt)

    session = _make_session(
        profile=args.target_profile, region=args.target_region,
        role_arn=args.target_role_arn,
    )
    target_account_id = _get_account_id(session)

    _log(f"Restore: target_env={target_env} cap={target_cap} account={target_account_id}")
    _log(f"  Components: {sorted(components)}")
    if entities:
        _log(f"  Logical entities: {entities}")

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
            if entity_ddb_keys is not None:
                ddb_metas = [
                    m for m in ddb_metas
                    if (m["name"], _filter_key(m.get("filter"))) in entity_ddb_keys
                ]
            for m in ddb_metas:
                if m.get("skipped"):
                    continue
                if args.dry_run:
                    sd = next((s for s in DYNAMODB_SOURCES if s["name"] == m["name"]), None)
                    if sd:
                        tag = f"{m['entity']}/" if m.get("entity") else ""
                        _log(f"  DRY DDB: {tag}{m['name']} ({m.get('items','?')} items) "
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
            if entity_bucket_names is not None:
                s3_metas = [m for m in s3_metas if m["name"] in entity_bucket_names]
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

  # Logical-entity backup: business data only (S3 + DDB, no bssmagic/mimir)
  python3 backup_restore.py backup --env dev --preset business \\
      -o business.tar.gz --profile ptr-tech

  # Logical-entity backup: just workflows + solutions
  python3 backup_restore.py backup --env dev \\
      --entities workflows,solutions \\
      -o subset.tar.gz --profile ptr-tech

  # Restore only the workflows out of a business backup
  python3 backup_restore.py restore -i business.tar.gz \\
      --target-env test --target-profile new-account \\
      --entities workflows

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
    bp.add_argument("--entities",
                    help="Logical entities (CSV): "
                         + ",".join(sorted(set(LOGICAL_ENTITIES) | NOOP_ENTITIES))
                         + ",all. Mutually exclusive with --only.")
    bp.add_argument("--preset",
                    help=f"Curated entity bundle: {','.join(sorted(PRESETS))}")
    bp.add_argument("--profile", help="AWS profile")
    bp.add_argument("--role-arn", help="IAM role ARN to assume")
    bp.add_argument("--cluster", help="EKS cluster name (recorded in manifest)")
    bp.add_argument("--velero-bucket", help="Source velero S3 bucket (e.g. nexus-velero-backups-ACCTID)")
    bp.add_argument("--s3-workers", type=int, default=32,
                    help="Parallel GetObject workers per S3 source (default: 32). "
                         "Crank to 64-128 for buckets with millions of small objects.")
    bp.add_argument("--dry-run", action="store_true")

    rp = sub.add_parser("restore", help="Restore tarball into target account/cluster")
    rp.add_argument("-i", "--input", required=True, help="Input .tar.gz path")
    rp.add_argument("--target-env", required=True)
    rp.add_argument("--target-capability", default=CAPABILITY)
    rp.add_argument("--target-region", default="us-east-1")
    rp.add_argument("--include", help="Components: " + ",".join(sorted(COMPONENTS)))
    rp.add_argument("--exclude", help="Components to skip")
    rp.add_argument("--only", help=f"S3/DDB groups: {','.join(sorted(GROUPS))},all")
    rp.add_argument("--entities",
                    help="Logical entities (CSV) to restore. Mutually exclusive with --only.")
    rp.add_argument("--preset",
                    help=f"Curated entity bundle: {','.join(sorted(PRESETS))}")
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
