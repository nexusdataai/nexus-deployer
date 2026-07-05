#!/usr/bin/env python3
"""
Nexus Foundry-Workspace DynamoDB Backup & Restore  (Stage 2 of the DR rewrite)

Single-purpose CLI for backing up and restoring the entire
``foundry-workspace`` DynamoDB table — the home of the Supply Chain
Foundry: canonical entities, policies, workflow definitions, integration
mappings, mapping rules, plus the workspace UI entities (solutions,
views, dashboards, journeys, tools, connectors, data planes,
connector settings).

The output is one ``.tar.gz`` containing ``manifest.json`` plus a
per-entity-type JSONL file (e.g. ``dynamodb/MAPPINGRULE.jsonl``,
``dynamodb/POLICY.jsonl``). Restore reads each JSONL and ``PutItem``s
every row into the target table verbatim. Mapping rules are stored as
three rows on disk; all three are re-put, preserving the canonical
META + two denormalized link rows without needing a transactional
rebuild step.

Scope: the foundry-workspace DDB table only. Simulator S3 data
(``simulator_backup.py``), pgvector / Apache AGE indexes (rebuilt by
the Knowledge Processor), and operator-managed infrastructure (SSM,
Secrets, Glue, Cognito, Velero, Postgres) are out of scope and have
their own tooling.

Usage:

    # Backup
    python3 foundry_backup.py backup \\
        --capability nexus-ai --env prod \\
        --profile promode2 \\
        -o foundry-prod-$(date +%Y%m%d).tar.gz

    # Inspect what's in a tarball
    python3 foundry_backup.py inspect -i foundry-prod-20260624.tar.gz

    # Restore (dry-run first, always)
    python3 foundry_backup.py restore \\
        -i foundry-prod-20260624.tar.gz \\
        --target-capability nexus-ai --target-env stage \\
        --target-profile new-account \\
        --dry-run

    # Re-run without --dry-run to apply. Add --prune to delete target
    # rows whose PKs are not present in the bundle (otherwise restore is
    # additive merge: existing rows stay, bundle rows are written).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import boto3
from botocore.exceptions import ClientError


CAPABILITY_DEFAULT = "nexus-ai"
MANIFEST_SCHEMA_VERSION = "stage2.foundry.v1"

# Logical entity prefixes (extracted from the PK by reading the segment
# before the first ``#``). Anything matching a prefix groups into the
# named JSONL; anything else falls into ``OTHER.jsonl``. This makes the
# tool forward-compatible with new PK prefixes added in future releases:
# unknown prefixes round-trip unchanged.
KNOWN_PREFIXES = (
    "VDLENTITY",
    "POLICY",
    "WORKFLOWDEF",
    "INTEGRATIONDEF",
    "MAPPINGRULE",
    "SOLUTION",
    "VIEW",
    "DASHBOARD",
    "JOURNEY",
    "TOOL",
    "CONNECTOR",
    "CONNECTORSETTING",
    "DATAPLANE",
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _resolve_table_name(capability: str, env: str) -> str:
    """Reproduce the kube-operator naming convention."""
    return f"{capability}-{env}-foundry-workspace"


def _make_client(profile: Optional[str], region: str) -> Any:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.resource("dynamodb", region_name=region)


def _classify(pk: str) -> str:
    """Map a PK to one of the KNOWN_PREFIXES (or ``OTHER``)."""
    if not pk:
        return "OTHER"
    prefix = pk.split("#", 1)[0]
    return prefix if prefix in KNOWN_PREFIXES else "OTHER"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except UnicodeDecodeError:
            return obj.decode("latin-1")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable: {obj!r}")


def _scan_full_table(table) -> Iterable[Dict[str, Any]]:
    last_key = None
    while True:
        kwargs: Dict[str, Any] = {}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            yield item
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break


# ----------------------------------------------------------------------------
# Backup
# ----------------------------------------------------------------------------

def cmd_backup(args: argparse.Namespace) -> int:
    table_name = args.table or _resolve_table_name(args.capability, args.env)
    print(f"  capability:  {args.capability}")
    print(f"  env:         {args.env}")
    print(f"  profile:     {args.profile or '(default)'}")
    print(f"  region:      {args.region}")
    print(f"  table:       {table_name}")
    print(f"  output:      {args.out}")
    print()

    try:
        resource = _make_client(args.profile, args.region)
        table = resource.Table(table_name)
        table.load()
    except ClientError as e:
        print(f"  ERROR: cannot access table: {e}")
        return 2

    tmpdir = tempfile.mkdtemp(prefix="foundry-bk-")
    try:
        ddb_dir = os.path.join(tmpdir, "dynamodb")
        os.makedirs(ddb_dir, exist_ok=True)

        # Group items by classified prefix and stream-write to per-prefix JSONL.
        counts: Counter = Counter()
        file_handles: Dict[str, Any] = {}
        try:
            for item in _scan_full_table(table):
                pk = str(item.get("PK", ""))
                bucket = _classify(pk)
                fh = file_handles.get(bucket)
                if fh is None:
                    fh = open(os.path.join(ddb_dir, f"{bucket}.jsonl"), "w", encoding="utf-8")
                    file_handles[bucket] = fh
                fh.write(json.dumps(item, default=_json_default) + "\n")
                counts[bucket] += 1
        finally:
            for fh in file_handles.values():
                fh.close()

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "capability": args.capability,
                "env": args.env,
                "region": args.region,
                "table": table_name,
            },
            "counts": dict(counts),
            "total": sum(counts.values()),
            "entity_files": sorted([f"dynamodb/{k}.jsonl" for k in counts.keys()]),
        }
        with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=_json_default)

        # Pack tarball
        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(os.path.join(tmpdir, "manifest.json"), arcname="manifest.json")
            for fname in sorted(os.listdir(ddb_dir)):
                tar.add(os.path.join(ddb_dir, fname), arcname=f"dynamodb/{fname}")

        size_mb = os.path.getsize(out_path) / 1024 / 1024
        print("  " + "=" * 70)
        print(f"  Backup complete: {out_path}  ({size_mb:.2f} MB)")
        print("  " + "=" * 70)
        for prefix in sorted(counts.keys()):
            print(f"    {prefix:18s} {counts[prefix]:6d} rows")
        print(f"    {'TOTAL':18s} {sum(counts.values()):6d} rows")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
# Inspect
# ----------------------------------------------------------------------------

def cmd_inspect(args: argparse.Namespace) -> int:
    in_path = os.path.abspath(args.input)
    if not os.path.isfile(in_path):
        print(f"  ERROR: not a file: {in_path}")
        return 2

    with tarfile.open(in_path, "r:gz") as tar:
        try:
            mf_member = tar.getmember("manifest.json")
        except KeyError:
            print("  ERROR: tarball missing manifest.json")
            return 2
        mf_text = tar.extractfile(mf_member).read().decode("utf-8")

    manifest = json.loads(mf_text)
    print(f"  schema_version : {manifest.get('schema_version')}")
    print(f"  created_at     : {manifest.get('created_at')}")
    src = manifest.get("source") or {}
    print(f"  source cluster : {src.get('capability')}-{src.get('env')} ({src.get('region')})")
    print(f"  source table   : {src.get('table')}")
    print(f"  total rows     : {manifest.get('total')}")
    print()
    print(f"  Per-entity counts:")
    for prefix, n in sorted((manifest.get("counts") or {}).items()):
        print(f"    {prefix:18s} {n:6d} rows")
    return 0


# ----------------------------------------------------------------------------
# Restore
# ----------------------------------------------------------------------------

def _iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _decimalize(value: Any) -> Any:
    """Convert numeric primitives back into Decimal for DDB writes (boto3
    resource layer rejects floats/ints in nested structures)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _decimalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimalize(v) for v in value]
    return value


def cmd_restore(args: argparse.Namespace) -> int:
    in_path = os.path.abspath(args.input)
    if not os.path.isfile(in_path):
        print(f"  ERROR: not a file: {in_path}")
        return 2

    capability = args.target_capability or args.capability
    env = args.target_env or args.env
    profile = args.target_profile or args.profile
    region = args.target_region or args.region
    table_name = args.target_table or _resolve_table_name(capability, env)

    print(f"  input:        {in_path}")
    print(f"  target table: {table_name}")
    print(f"  capability:   {capability}")
    print(f"  env:          {env}")
    print(f"  profile:      {profile or '(default)'}")
    print(f"  region:       {region}")
    print(f"  mode:         {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    print(f"  prune:        {'yes' if args.prune else 'no (additive merge)'}")
    print()

    # Extract to temp dir
    tmpdir = tempfile.mkdtemp(prefix="foundry-rs-")
    try:
        with tarfile.open(in_path, "r:gz") as tar:
            tar.extractall(tmpdir)

        manifest_path = os.path.join(tmpdir, "manifest.json")
        if not os.path.isfile(manifest_path):
            print("  ERROR: tarball missing manifest.json")
            return 2
        manifest = json.load(open(manifest_path, "r", encoding="utf-8"))
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            print(
                f"  ERROR: unsupported schema_version "
                f"{manifest.get('schema_version')!r} (expected {MANIFEST_SCHEMA_VERSION!r})"
            )
            return 2

        ddb_dir = os.path.join(tmpdir, "dynamodb")
        if not os.path.isdir(ddb_dir):
            print("  ERROR: tarball missing dynamodb/ directory")
            return 2

        # Collect bundle items
        bundle_items: List[Dict[str, Any]] = []
        bundle_counts: Counter = Counter()
        for fname in sorted(os.listdir(ddb_dir)):
            prefix = fname.rsplit(".jsonl", 1)[0]
            for item in _iter_jsonl(os.path.join(ddb_dir, fname)):
                bundle_items.append(item)
                bundle_counts[prefix] += 1
        bundle_keys: Set[Tuple[str, str]] = {(str(it.get("PK", "")), str(it.get("SK", ""))) for it in bundle_items}

        print(f"  bundle rows: {len(bundle_items)}  ({dict(bundle_counts)})")
        print()

        # Connect to target table
        try:
            resource = _make_client(profile, region)
            table = resource.Table(table_name)
            table.load()
        except ClientError as e:
            print(f"  ERROR: cannot access target table: {e}")
            return 2

        # Compute prune set (rows present in target but not in bundle)
        prune_keys: List[Tuple[str, str]] = []
        if args.prune:
            for item in _scan_full_table(table):
                key = (str(item.get("PK", "")), str(item.get("SK", "")))
                if key not in bundle_keys:
                    prune_keys.append(key)
            print(f"  rows to prune (in target, absent from bundle): {len(prune_keys)}")

        if args.dry_run:
            print()
            print("  DRY-RUN summary:")
            print(f"    PutItem ops:    {len(bundle_items)}")
            print(f"    DeleteItem ops: {len(prune_keys)} (only if --prune)")
            return 0

        # Apply writes
        written = 0
        with table.batch_writer() as batch:
            for item in bundle_items:
                # Strip None values; convert numerics to Decimal.
                clean = {k: _decimalize(v) for k, v in item.items() if v is not None}
                batch.put_item(Item=clean)
                written += 1
                if written % 200 == 0:
                    print(f"    progress: {written}/{len(bundle_items)} put")
        print(f"  put {written} rows")

        if args.prune and prune_keys:
            deleted = 0
            with table.batch_writer() as batch:
                for pk, sk in prune_keys:
                    batch.delete_item(Key={"PK": pk, "SK": sk})
                    deleted += 1
                    if deleted % 200 == 0:
                        print(f"    progress: {deleted}/{len(prune_keys)} deleted")
            print(f"  pruned {deleted} rows")

        print()
        print("  Restore complete.")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="foundry_backup.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp = p.add_subparsers(dest="cmd")
    sp.required = True

    # ---- backup ----
    pb = sp.add_parser("backup", help="Dump the foundry-workspace table to a .tar.gz")
    pb.add_argument("--capability", default=CAPABILITY_DEFAULT)
    pb.add_argument("--env", required=True)
    pb.add_argument("--profile", default=None)
    pb.add_argument("--region", default="us-east-1")
    pb.add_argument("--table", default=None,
                    help="Override the {capability}-{env}-foundry-workspace table name.")
    pb.add_argument("-o", "--out", required=True,
                    help="Output tarball path (e.g. foundry-prod-20260624.tar.gz)")
    pb.set_defaults(func=cmd_backup)

    # ---- inspect ----
    pi = sp.add_parser("inspect", help="Print the manifest of a backup tarball")
    pi.add_argument("-i", "--input", required=True)
    pi.set_defaults(func=cmd_inspect)

    # ---- restore ----
    pr = sp.add_parser("restore", help="Restore a foundry-workspace tarball into a target table")
    pr.add_argument("-i", "--input", required=True)
    pr.add_argument("--capability", default=CAPABILITY_DEFAULT)
    pr.add_argument("--env", required=False, default=None)
    pr.add_argument("--profile", default=None)
    pr.add_argument("--region", default="us-east-1")
    pr.add_argument("--target-capability", default=None,
                    help="Override capability for the target cluster (default: --capability).")
    pr.add_argument("--target-env", default=None,
                    help="Override env for the target cluster (default: --env).")
    pr.add_argument("--target-profile", default=None,
                    help="AWS profile to use against the target (default: --profile).")
    pr.add_argument("--target-region", default=None,
                    help="Region of the target table (default: --region).")
    pr.add_argument("--target-table", default=None,
                    help="Explicit target table name (overrides capability/env derivation).")
    pr.add_argument("--dry-run", action="store_true",
                    help="Plan only; do not write or delete.")
    pr.add_argument("--prune", action="store_true",
                    help="Delete target rows whose PK/SK is absent from the bundle "
                         "(default: additive merge).")
    pr.set_defaults(func=cmd_restore)

    args = p.parse_args(argv)

    # Restore requires either --target-env or --env so derive a table.
    if args.cmd == "restore" and not (args.target_env or args.env) and not args.target_table:
        p.error("restore requires --target-env (or --env) or --target-table")

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
