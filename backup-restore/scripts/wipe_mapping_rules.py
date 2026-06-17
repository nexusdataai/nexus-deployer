#!/usr/bin/env python3
"""
Wipe all mapping-rule rows from the foundry-workspace DynamoDB table.

Targets exactly three categories of rows (all written by the
MappingRuleService.put_mapping_rule transactional 3-row pattern):

    1. canonical:    PK begins_with "MAPPINGRULE#"
    2. source-link:  PK begins_with "DATAPLANE#"  AND  SK begins_with "MAPPING#"
    3. target-link:  PK begins_with "VDLENTITY#"  AND  SK begins_with "MAPPING#"

Leaves untouched:
    - SOLUTION#, VIEW#, DASHBOARD#, TOOL#, CONNECTOR#, CONNECTORSETTING#, JOURNEY#
    - Any DATAPLANE# / VDLENTITY# row whose SK is NOT "MAPPING#..." (e.g. SK=META)

Usage:
    # Dry-run (count + sample, no writes)
    python3 wipe_mapping_rules.py --table nexus-ai-prod-foundry-workspace --dry-run

    # Execute (requires --yes to confirm)
    python3 wipe_mapping_rules.py --table nexus-ai-prod-foundry-workspace --yes

Reads AWS credentials from the standard boto3 chain (AWS_PROFILE,
AWS_REGION, env vars, etc.). Region defaults to us-east-1.

Rationale: after the foundry_workspace_repository / mapping_rule_service
fix shipped in backend 0.0.3, all *new* mapping rule writes are correct.
This script clears the legacy corrupted writes so that:
  - GET /api/v1/control-plane/virtual/entities stops 500-ing
  - solution_entity_catalogue.ensure_solution_entities() re-seeds rules
    cleanly the next time the backend boots (or when result_sink writes
    a new entity)
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from typing import Any, Dict, Iterator, List, Tuple

import boto3
from boto3.dynamodb.conditions import Attr


CATEGORIES = (
    ("canonical",   lambda pk, sk: pk.startswith("MAPPINGRULE#")),
    ("source-link", lambda pk, sk: pk.startswith("DATAPLANE#")  and sk.startswith("MAPPING#")),
    ("target-link", lambda pk, sk: pk.startswith("VDLENTITY#")  and sk.startswith("MAPPING#")),
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--table", required=True, help="DynamoDB table name (foundry-workspace)")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--dry-run", action="store_true", help="Count + sample only, no writes")
    p.add_argument("--yes", action="store_true", help="Confirm destructive delete (required without --dry-run)")
    p.add_argument("--sample", type=int, default=5, help="How many sample rows per category to print (default 5)")
    return p.parse_args()


def classify(item: Dict[str, Any]) -> str:
    pk = item.get("PK", "")
    sk = item.get("SK", "")
    for name, predicate in CATEGORIES:
        if predicate(pk, sk):
            return name
    return ""


def iter_table(table) -> Iterator[Dict[str, Any]]:
    """Yield every item in the table, page by page."""
    kwargs: Dict[str, Any] = {"ProjectionExpression": "PK, SK, ruleId, createdAt, #nm",
                              "ExpressionAttributeNames": {"#nm": "name"}}
    last_key = None
    while True:
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            yield item
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break


def collect_targets(table) -> Tuple[List[Tuple[str, str]], Counter, Dict[str, List[Dict[str, Any]]]]:
    """Return (keys_to_delete, per-category counts, samples)."""
    keys: List[Tuple[str, str]] = []
    counts: Counter = Counter()
    samples: Dict[str, List[Dict[str, Any]]] = {n: [] for n, _ in CATEGORIES}
    scanned = 0
    for item in iter_table(table):
        scanned += 1
        cat = classify(item)
        if not cat:
            continue
        counts[cat] += 1
        keys.append((item["PK"], item["SK"]))
        if len(samples[cat]) < SAMPLE_LIMIT:
            samples[cat].append(item)
    counts["__scanned"] = scanned
    return keys, counts, samples


def report(counts: Counter, samples: Dict[str, List[Dict[str, Any]]]) -> None:
    scanned = counts.get("__scanned", 0)
    print(f"  scanned: {scanned} rows total")
    for name, _ in CATEGORIES:
        print(f"  {name:13s}: {counts.get(name, 0)} marked for delete")
    total = sum(counts[c] for c, _ in [(n, p) for n, p in CATEGORIES])
    print(f"  TOTAL DELETE: {total} rows  ({scanned - total} preserved)")
    print()
    for name, _ in CATEGORIES:
        if not samples[name]:
            continue
        print(f"  --- sample {name} (first {len(samples[name])}) ---")
        for it in samples[name]:
            print(f"    PK={it['PK']!r:80s}  SK={it.get('SK','')!r:30s}  "
                  f"rule={it.get('ruleId','')!r:42s}  name={it.get('name','')!r}")
        print()


def batch_delete(table, keys: List[Tuple[str, str]]) -> int:
    """Batch-delete (PK, SK) pairs. Returns count deleted."""
    deleted = 0
    t0 = time.time()
    with table.batch_writer() as batch:
        for pk, sk in keys:
            batch.delete_item(Key={"PK": pk, "SK": sk})
            deleted += 1
            if deleted % 100 == 0:
                rate = deleted / max(1e-3, time.time() - t0)
                print(f"    progress: {deleted}/{len(keys)}  ({rate:.0f} rows/s)")
    return deleted


SAMPLE_LIMIT = 5


def main() -> int:
    args = parse_args()
    global SAMPLE_LIMIT
    SAMPLE_LIMIT = max(0, args.sample)

    if not args.dry_run and not args.yes:
        print("ERROR: refusing to delete without --yes (or use --dry-run)", file=sys.stderr)
        return 2

    print(f"  table:  {args.table}")
    print(f"  region: {args.region}")
    print(f"  mode:   {'DRY-RUN' if args.dry_run else 'EXECUTE (--yes given)'}")
    print()

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)

    print("  Scanning table for mapping-rule rows...")
    keys, counts, samples = collect_targets(table)
    report(counts, samples)

    if args.dry_run:
        print("  (dry-run — no rows deleted)")
        return 0

    if not keys:
        print("  Nothing to delete.")
        return 0

    print(f"  Deleting {len(keys)} rows...")
    deleted = batch_delete(table, keys)
    print(f"  Done. {deleted} rows deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
