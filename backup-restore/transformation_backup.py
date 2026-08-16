#!/usr/bin/env python3
"""
Backup and restore the transformation-system DynamoDB table.

This table holds operational journeys (AI Automation → Journeys tab),
stages, jobs, and LIVELOG rows. It is separate from foundry-workspace
(which context-dr already migrates via foundry_backup.py).

Table naming (kube-operator convention):
  {capability}-{env}-transformation-system
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import boto3
from botocore.exceptions import ClientError

MANIFEST_SCHEMA_VERSION = "stage1.transformation.v1"
CAPABILITY_DEFAULT = "nexus-ai"


def _resolve_table_name(capability: str, env: str) -> str:
    return f"{capability}-{env}-transformation-system"


def _make_client(profile: Optional[str], region: str):
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.resource("dynamodb", region_name=region)


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
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _decimalize(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _decimalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimalize(v) for v in value]
    return value


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


def _count_journeys_gsi(table) -> int:
    """Count rows the UI lists (GSI1PK = JOURNEYS)."""
    total = 0
    kwargs: Dict[str, Any] = {
        "IndexName": "GSI1",
        "KeyConditionExpression": "GSI1PK = :pk",
        "ExpressionAttributeValues": {":pk": "JOURNEYS"},
        "Select": "COUNT",
    }
    while True:
        resp = table.query(**kwargs)
        total += int(resp.get("Count", 0))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return total


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

    tmpdir = tempfile.mkdtemp(prefix="transform-bk-")
    try:
        items_path = os.path.join(tmpdir, "items.jsonl")
        total = 0
        journey_gsi = _count_journeys_gsi(table)
        with open(items_path, "w", encoding="utf-8") as fh:
            for item in _scan_full_table(table):
                fh.write(json.dumps(item, default=_json_default) + "\n")
                total += 1

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "capability": args.capability,
                "env": args.env,
                "region": args.region,
                "table": table_name,
            },
            "total": total,
            "journey_gsi_count": journey_gsi,
        }
        with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=_json_default)

        out_path = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(os.path.join(tmpdir, "manifest.json"), arcname="manifest.json")
            tar.add(items_path, arcname="items.jsonl")

        size_mb = os.path.getsize(out_path) / 1024 / 1024
        print("  " + "=" * 70)
        print(f"  Backup complete: {out_path}  ({size_mb:.2f} MB)")
        print("  " + "=" * 70)
        print(f"    TOTAL rows:           {total:6d}")
        print(f"    JOURNEYS (GSI1 list): {journey_gsi:6d}")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd_inspect(args: argparse.Namespace) -> int:
    in_path = os.path.abspath(args.input)
    if not os.path.isfile(in_path):
        print(f"  ERROR: not a file: {in_path}")
        return 2
    with tarfile.open(in_path, "r:gz") as tar:
        mf_text = tar.extractfile(tar.getmember("manifest.json")).read().decode("utf-8")
    manifest = json.loads(mf_text)
    src = manifest.get("source") or {}
    print(f"  schema_version : {manifest.get('schema_version')}")
    print(f"  created_at     : {manifest.get('created_at')}")
    print(f"  source table   : {src.get('table')}")
    print(f"  total rows     : {manifest.get('total')}")
    print(f"  journeys (GSI) : {manifest.get('journey_gsi_count')}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    in_path = os.path.abspath(args.input)
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

    tmpdir = tempfile.mkdtemp(prefix="transform-rs-")
    try:
        with tarfile.open(in_path, "r:gz") as tar:
            tar.extractall(tmpdir)
        manifest = json.load(open(os.path.join(tmpdir, "manifest.json"), "r", encoding="utf-8"))
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            print(f"  ERROR: unsupported schema {manifest.get('schema_version')!r}")
            return 2

        items: List[Dict[str, Any]] = []
        with open(os.path.join(tmpdir, "items.jsonl"), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    items.append(json.loads(line))

        print(f"  bundle rows: {len(items)}  (journeys GSI in manifest: {manifest.get('journey_gsi_count')})")

        if args.dry_run:
            print()
            print("  DRY-RUN summary:")
            print(f"    Target table:   {table_name}")
            print(f"    PutItem ops:    {len(items)}")
            return 0

        resource = _make_client(profile, region)
        table_exists = True
        try:
            table = resource.Table(table_name)
            table.load()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                table_exists = False
                table = None
            else:
                raise
        if not table_exists or table is None:
            print(f"  ERROR: target table not found: {table_name}")
            return 2

        written = 0
        with table.batch_writer() as batch:
            for item in items:
                clean = {k: _decimalize(v) for k, v in item.items() if v is not None}
                batch.put_item(Item=clean)
                written += 1
                if written % 50 == 0:
                    print(f"    progress: {written}/{len(items)} put")
        print(f"  put {written} rows")
        print()
        print("  Restore complete.")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd_verify(args: argparse.Namespace) -> int:
    in_path = os.path.abspath(args.input)
    capability = args.target_capability or args.capability
    env = args.target_env or args.env
    profile = args.target_profile or args.profile
    region = args.target_region or args.region
    table_name = args.target_table or _resolve_table_name(capability, env)

    tmpdir = tempfile.mkdtemp(prefix="transform-vf-")
    try:
        with tarfile.open(in_path, "r:gz") as tar:
            tar.extractall(tmpdir)
        manifest = json.load(open(os.path.join(tmpdir, "manifest.json"), "r", encoding="utf-8"))
        expected_total = int(manifest.get("total") or 0)
        expected_journeys = int(manifest.get("journey_gsi_count") or 0)

        print(f"  tarball:              {in_path}")
        print(f"  target table:         {table_name}")
        print(f"  expected total rows:  {expected_total}")
        print(f"  expected journeys:    {expected_journeys} (GSI1 JOURNEYS)")
        print()

        table = _make_client(profile, region).Table(table_name)
        table.load()
        actual_total = sum(1 for _ in _scan_full_table(table))
        actual_journeys = _count_journeys_gsi(table)
        print(f"  actual total rows:    {actual_total}")
        print(f"  actual journeys:      {actual_journeys}")

        ok = True
        if actual_total < expected_total:
            print(f"  FAIL: total rows {actual_total} < expected {expected_total}")
            ok = False
        if actual_journeys < expected_journeys:
            print(f"  FAIL: journeys {actual_journeys} < expected {expected_journeys}")
            ok = False
        if ok:
            print("  OK: transformation-system restore verified")
            return 0
        return 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="transformation_backup.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp = p.add_subparsers(dest="cmd")
    sp.required = True

    pb = sp.add_parser("backup", help="Dump transformation-system table to .tar.gz")
    pb.add_argument("--capability", default=CAPABILITY_DEFAULT)
    pb.add_argument("--env", required=True)
    pb.add_argument("--profile", default=None)
    pb.add_argument("--region", default="us-east-1")
    pb.add_argument("--table", default=None)
    pb.add_argument("-o", "--out", required=True)
    pb.set_defaults(func=cmd_backup)

    pi = sp.add_parser("inspect", help="Print tarball manifest")
    pi.add_argument("-i", "--input", required=True)
    pi.set_defaults(func=cmd_inspect)

    pr = sp.add_parser("restore", help="Restore transformation-system tarball")
    pr.add_argument("-i", "--input", required=True)
    pr.add_argument("--capability", default=CAPABILITY_DEFAULT)
    pr.add_argument("--env", default=None)
    pr.add_argument("--profile", default=None)
    pr.add_argument("--region", default="us-east-1")
    pr.add_argument("--target-capability", default=None)
    pr.add_argument("--target-env", default=None)
    pr.add_argument("--target-profile", default=None)
    pr.add_argument("--target-region", default=None)
    pr.add_argument("--target-table", default=None)
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--prune", action="store_true")
    pr.set_defaults(func=cmd_restore)

    pv = sp.add_parser("verify", help="Verify target table row + journey counts")
    pv.add_argument("-i", "--input", required=True)
    pv.add_argument("--capability", default=CAPABILITY_DEFAULT)
    pv.add_argument("--env", default=None)
    pv.add_argument("--profile", default=None)
    pv.add_argument("--region", default="us-east-1")
    pv.add_argument("--target-capability", default=None)
    pv.add_argument("--target-env", default=None)
    pv.add_argument("--target-profile", default=None)
    pv.add_argument("--target-region", default=None)
    pv.add_argument("--target-table", default=None)
    pv.set_defaults(func=cmd_verify)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
