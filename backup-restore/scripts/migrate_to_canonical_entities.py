#!/usr/bin/env python3
"""
One-shot migration: rewrite legacy entity names on existing mapping rules
to canonical names per ``canonical-entities.yaml``.

For each rule whose ``virtualEntity`` matches a legacy alias:
  - delete the old target-link row at ``VDLENTITY#{legacy}`` / ``MAPPING#{rule_id}``
  - update the canonical META row at ``MAPPINGRULE#{rule_id}`` / ``META``
    (virtualEntity, targetVdlEntity, GSI1SK)
  - update the source-link row at ``DATAPLANE#{source_dp}`` / ``MAPPING#{rule_id}``
    (denormalized virtualEntity / targetVdlEntity fields)
  - insert the new target-link row at ``VDLENTITY#{canonical}`` / ``MAPPING#{rule_id}``

All 4 operations are issued in a single ``TransactWriteItems`` call so a
failure either reverts the whole rule or completes it. ``--dry-run`` prints
the change set without writing.

Usage:
    AWS_PROFILE=promode2 AWS_REGION=us-east-1 \\
        DYNAMODB_FOUNDRY_WORKSPACE_TABLE=nexus-ai-prod-foundry-workspace \\
        python3 nexus-deployer/backup-restore/scripts/migrate_to_canonical_entities.py [--dry-run]

Runs from the cluster's tooling host. One run per cluster.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
import yaml
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# Alias-table loader
# ---------------------------------------------------------------------------

def _candidate_canonical_yaml_paths() -> List[Path]:
    """Order the candidates from most-specific (env override) to repo-relative."""
    out: List[Path] = []
    env_path = os.environ.get("CANONICAL_ENTITIES_YAML")
    if env_path:
        out.append(Path(env_path))
    # Repo-relative (assuming the script lives at nexus-deployer/backup-restore/scripts/)
    here = Path(__file__).resolve()
    out.append(here.parent.parent.parent.parent / "nexus-backend" / "enterprise-knowledge" / "canonical-entities.yaml")
    # Container path
    out.append(Path("/app/enterprise-knowledge/canonical-entities.yaml"))
    return out


def load_alias_map() -> Dict[str, str]:
    """Return {legacy_name: canonical_name} from canonical-entities.yaml."""
    for path in _candidate_canonical_yaml_paths():
        if path.is_file():
            data = yaml.safe_load(path.read_text())
            break
    else:
        print("ERROR: canonical-entities.yaml not found in any candidate path", file=sys.stderr)
        sys.exit(2)

    if not data or data.get("schema_kind") != "canonical-entity-catalog":
        print(f"ERROR: {path} has unexpected schema_kind", file=sys.stderr)
        sys.exit(2)

    alias_map: Dict[str, str] = {}
    for domain in data.get("domains", []) or []:
        for ent in domain.get("entities", []) or []:
            canonical = ent.get("name")
            if not canonical:
                continue
            for alias in ent.get("aliases", []) or []:
                if alias and alias != canonical:
                    alias_map[alias] = canonical
    return alias_map


# ---------------------------------------------------------------------------
# DDB helpers
# ---------------------------------------------------------------------------

def resolve_table_name() -> str:
    name = os.environ.get("DYNAMODB_FOUNDRY_WORKSPACE_TABLE") or os.environ.get("FOUNDRY_WORKSPACE_TABLE")
    if name:
        return name
    cap = os.environ.get("CAPABILITY_NAME", "nexus-ai")
    env = os.environ.get("ENVIRONMENT", "dev")
    return f"{cap}-{env}-foundry-workspace"


def _build_ddb_client() -> Tuple[Any, Any]:
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    resource = boto3.resource("dynamodb", region_name=region)
    client = boto3.client("dynamodb", region_name=region)
    return resource, client


def fetch_canonical_rules(resource, table_name: str) -> List[Dict[str, Any]]:
    """GSI1 query on GSI1PK='MAPPINGRULE' returns all canonical META rows."""
    table = resource.Table(table_name)
    items: List[Dict[str, Any]] = []
    last_key = None
    while True:
        kwargs = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq("MAPPINGRULE"),
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return items


def _to_attr(value: Any) -> Dict[str, Any]:
    """Minimal Python -> DynamoDB low-level attribute conversion for transact ops.
    Mirrors FoundryWorkspaceRepository._to_attr so the rewritten items match the
    runtime shape exactly."""
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, (int, float)):
        return {"N": str(value)}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, list):
        if not value:
            return {"L": []}
        return {"L": [_to_attr(v) for v in value]}
    if isinstance(value, dict):
        return {"M": {k: _to_attr(v) for k, v in value.items()}}
    return {"S": str(value)}


def _decimal_to_native(v: Any) -> Any:
    """boto3 returns Decimal for numerics; collapse back to int/float for re-encode."""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return int(v) if v == int(v) else float(v)
    if isinstance(v, dict):
        return {k: _decimal_to_native(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_decimal_to_native(x) for x in v]
    return v


# ---------------------------------------------------------------------------
# Per-rule rewrite
# ---------------------------------------------------------------------------

def plan_rewrite(rule: Dict[str, Any], alias_map: Dict[str, str], table_name: str) -> Optional[List[Dict[str, Any]]]:
    """
    Build the TransactWriteItems ops list for one rule, or None when no
    rewrite is needed (already-canonical entity name).
    """
    rule_id = rule.get("ruleId") or rule.get("id")
    legacy_entity = rule.get("virtualEntity") or rule.get("targetVdlEntity")
    source_dp_id = rule.get("sourceDataPlaneId")
    if not (rule_id and legacy_entity):
        return None
    canonical = alias_map.get(legacy_entity)
    if not canonical:
        return None  # already canonical or unknown

    # Re-encode rule attrs with the new canonical entity + GSI1SK + targetVdlEntity.
    new_attrs = _decimal_to_native(dict(rule))
    new_attrs["virtualEntity"] = canonical
    new_attrs["targetVdlEntity"] = canonical

    # GSI1SK on the canonical row is "{source_dp_id}#{target_vdl}". Recompute.
    new_attrs["GSI1SK"] = f"{source_dp_id}#{canonical}"

    # Canonical META row (overwrite at MAPPINGRULE#{rule_id} / META).
    canonical_pk = f"MAPPINGRULE#{rule_id}"
    sk_meta = "META"
    canonical_item = {**new_attrs, "PK": canonical_pk, "SK": sk_meta, "GSI1PK": "MAPPINGRULE"}

    # Source-link row (overwrite at DATAPLANE#{source}).
    source_link_pk = f"DATAPLANE#{source_dp_id}"
    sk_link = f"MAPPING#{rule_id}"
    # Source-link rows on the runtime path don't carry GSI1PK/GSI1SK — strip them.
    source_link_item = {k: v for k, v in new_attrs.items() if k not in ("GSI1PK", "GSI1SK")}
    source_link_item.update({"PK": source_link_pk, "SK": sk_link})

    # New target-link row (under canonical VDLENTITY#).
    new_target_link_pk = f"VDLENTITY#{canonical}"
    new_target_link_item = {k: v for k, v in new_attrs.items() if k not in ("GSI1PK", "GSI1SK")}
    new_target_link_item.update({"PK": new_target_link_pk, "SK": sk_link})

    # Old target-link row (under legacy VDLENTITY#) — DELETE.
    old_target_link_pk = f"VDLENTITY#{legacy_entity}"

    ops = [
        {"Delete": {"TableName": table_name,
                    "Key": {"PK": {"S": old_target_link_pk}, "SK": {"S": sk_link}}}},
        {"Put": {"TableName": table_name,
                 "Item": {k: _to_attr(v) for k, v in canonical_item.items() if v is not None}}},
        {"Put": {"TableName": table_name,
                 "Item": {k: _to_attr(v) for k, v in source_link_item.items() if v is not None}}},
        {"Put": {"TableName": table_name,
                 "Item": {k: _to_attr(v) for k, v in new_target_link_item.items() if v is not None}}},
    ]
    return ops


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Print the change set without writing.")
    ap.add_argument("--table", help="Explicit DDB table name override.")
    ap.add_argument("--rule-id", help="Restrict the rewrite to a single rule_id (debugging).")
    args = ap.parse_args()

    alias_map = load_alias_map()
    if not alias_map:
        print("ERROR: empty alias map — canonical-entities.yaml has no aliases", file=sys.stderr)
        return 2

    table_name = args.table or resolve_table_name()
    resource, client = _build_ddb_client()

    print(f"  table:      {table_name}")
    print(f"  alias map:  {len(alias_map)} legacy -> canonical mappings")
    print(f"  mode:       {'DRY RUN' if args.dry_run else 'WRITE'}")
    print()

    rules = fetch_canonical_rules(resource, table_name)
    print(f"  scanned {len(rules)} canonical MAPPINGRULE# rows")

    rewritten = 0
    skipped = 0
    errors = 0

    for rule in rules:
        rule_id = rule.get("ruleId") or rule.get("id")
        if args.rule_id and rule_id != args.rule_id:
            continue
        ops = plan_rewrite(rule, alias_map, table_name)
        legacy = rule.get("virtualEntity") or rule.get("targetVdlEntity")
        if not ops:
            skipped += 1
            continue

        canonical = alias_map[legacy]
        print(f"    rule {rule_id}: {legacy!r:30} -> {canonical!r}")
        if args.dry_run:
            rewritten += 1
            continue

        try:
            client.transact_write_items(TransactItems=ops)
            rewritten += 1
        except ClientError as e:
            errors += 1
            reasons = getattr(e, "response", {}).get("CancellationReasons", "")
            print(f"      FAILED: {e} | reasons={reasons}", file=sys.stderr)

    print()
    print(f"  Summary: scanned={len(rules)}  rewritten={rewritten}  skipped={skipped}  errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
