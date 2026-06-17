#!/usr/bin/env python3
"""
Read-only auditor for legacy VDL entity names in foundry-workspace.

Scans every row under the SOLUTION#, VIEW#, DASHBOARD#, JOURNEY#,
MAPPINGRULE# PK prefixes in the cluster's foundry-workspace DynamoDB
table and reports any value (string or nested dict/list) that contains
a legacy entity name from canonical-entities.yaml's aliases lists.

Also reports per-canonical-entity health: for each canonical entity,
how many ACTIVE mapping rules exist (expected: exactly one per cluster).

Outputs a human-actionable migration-report.md so dashboard / journey
authors can find every legacy reference that needs a rewrite via the
UI.

Usage:
    AWS_PROFILE=promode2 AWS_REGION=us-east-1 \\
        DYNAMODB_FOUNDRY_WORKSPACE_TABLE=nexus-ai-prod-foundry-workspace \\
        python3 nexus-deployer/backup-restore/scripts/audit_legacy_entity_refs.py [--output PATH]

No writes are issued. Safe to run any time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import boto3
import yaml
from boto3.dynamodb.conditions import Key


# ---------------------------------------------------------------------------
# Alias-table loader (duplicated lightly from migrate_to_canonical_entities.py
# so the auditor stays single-file and runnable without import gymnastics)
# ---------------------------------------------------------------------------

def _candidate_canonical_yaml_paths() -> List[Path]:
    out: List[Path] = []
    env_path = os.environ.get("CANONICAL_ENTITIES_YAML")
    if env_path:
        out.append(Path(env_path))
    here = Path(__file__).resolve()
    out.append(here.parent.parent.parent.parent / "nexus-backend" / "enterprise-knowledge" / "canonical-entities.yaml")
    out.append(Path("/app/enterprise-knowledge/canonical-entities.yaml"))
    return out


def load_alias_map() -> Tuple[Dict[str, str], List[str]]:
    """Return ({legacy -> canonical}, [list of canonical names])."""
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
    canonical: List[str] = []
    for domain in data.get("domains", []) or []:
        for ent in domain.get("entities", []) or []:
            cn = ent.get("name")
            if not cn:
                continue
            canonical.append(cn)
            for alias in ent.get("aliases", []) or []:
                if alias and alias != cn:
                    alias_map[alias] = cn
    return alias_map, canonical


# ---------------------------------------------------------------------------
# DDB scanning
# ---------------------------------------------------------------------------

def resolve_table_name(override: str | None = None) -> str:
    if override:
        return override
    name = os.environ.get("DYNAMODB_FOUNDRY_WORKSPACE_TABLE") or os.environ.get("FOUNDRY_WORKSPACE_TABLE")
    if name:
        return name
    cap = os.environ.get("CAPABILITY_NAME", "nexus-ai")
    env = os.environ.get("ENVIRONMENT", "dev")
    return f"{cap}-{env}-foundry-workspace"


SCANNED_PK_PREFIXES = ("SOLUTION#", "VIEW#", "DASHBOARD#", "JOURNEY#")


def _walk_strings(value: Any, out: List[str]) -> None:
    """Collect every string somewhere inside a (possibly nested) dict/list/etc."""
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _walk_strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _walk_strings(v, out)


def _row_legacy_hits(row: Dict[str, Any], alias_map: Dict[str, str]) -> Dict[str, str]:
    """Return {legacy_name: canonical_name} for every legacy name that appears
    as a complete token in any string value of the row.
    """
    strings: List[str] = []
    _walk_strings(row, strings)
    blob = "\n".join(strings)
    hits: Dict[str, str] = {}
    for legacy, canonical in alias_map.items():
        # Whole-word match: surround the legacy name with non-word boundaries
        # so e.g. "Account" doesn't match inside "AccountID". This is the same
        # heuristic the migration script's caller would apply.
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(legacy)}(?![A-Za-z0-9_])", blob):
            hits[legacy] = canonical
    return hits


def scan_for_legacy_refs(resource, table_name: str, alias_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Walk SOLUTION/VIEW/DASHBOARD/JOURNEY PKs; return rows with legacy hits."""
    table = resource.Table(table_name)
    findings: List[Dict[str, Any]] = []

    for prefix in SCANNED_PK_PREFIXES:
        last_key = None
        while True:
            kwargs: Dict[str, Any] = {
                "FilterExpression": Key("PK").begins_with(prefix),
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = table.scan(**kwargs)
            for row in resp.get("Items", []):
                hits = _row_legacy_hits(row, alias_map)
                if hits:
                    findings.append({
                        "pk": row.get("PK"),
                        "sk": row.get("SK"),
                        "hits": hits,
                    })
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
    return findings


def per_entity_rule_health(resource, table_name: str, canonical_names: List[str]) -> List[Dict[str, Any]]:
    """For each canonical entity, count ACTIVE mapping rules under VDLENTITY#{name}."""
    table = resource.Table(table_name)
    out: List[Dict[str, Any]] = []
    for name in canonical_names:
        pk = f"VDLENTITY#{name}"
        last_key = None
        active = 0
        inactive = 0
        rule_ids: List[str] = []
        while True:
            kwargs: Dict[str, Any] = {
                "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with("MAPPING#"),
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = table.query(**kwargs)
            for row in resp.get("Items", []):
                status = (row.get("status") or "").lower()
                rid = row.get("ruleId") or row.get("id") or ""
                rule_ids.append(rid)
                if status == "active":
                    active += 1
                else:
                    inactive += 1
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        out.append({
            "entity": name,
            "active": active,
            "inactive": inactive,
            "rule_ids": rule_ids,
        })
    return out


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def write_report(
    out_path: Path,
    table_name: str,
    findings: List[Dict[str, Any]],
    health: List[Dict[str, Any]],
) -> None:
    lines: List[str] = []
    lines.append("# Canonical-entity migration audit\n")
    lines.append(f"- table: `{table_name}`\n")
    lines.append("- generated by `audit_legacy_entity_refs.py` (read-only)\n\n")

    lines.append("## Per-canonical-entity rule health\n\n")
    lines.append("Each canonical entity should have **exactly one** active mapping rule per cluster. ")
    lines.append("Zero means the entity is defined but not bound to a source in this cluster (queries against it will fail). ")
    lines.append("More than one is a misconfiguration to clean up via the Mapping Editor UI.\n\n")
    lines.append("| Entity | Active | Inactive | Rule IDs |\n")
    lines.append("|---|---|---|---|\n")
    bound = unbound = ambiguous = 0
    for h in health:
        ids = ", ".join(f"`{r}`" for r in h["rule_ids"]) if h["rule_ids"] else "-"
        active_cell = f"**{h['active']}**" if h["active"] != 1 else str(h["active"])
        lines.append(f"| `{h['entity']}` | {active_cell} | {h['inactive']} | {ids} |\n")
        if h["active"] == 0:
            unbound += 1
        elif h["active"] == 1:
            bound += 1
        else:
            ambiguous += 1
    lines.append("\n")
    lines.append(f"Summary: **{bound}** correctly bound, **{unbound}** unbound, **{ambiguous}** ambiguous (>1 active).\n\n")

    lines.append("## Legacy entity references in dashboards / solutions / journeys\n\n")
    if not findings:
        lines.append("None. All scanned rows are clean.\n")
    else:
        lines.append(f"{len(findings)} row(s) reference one or more legacy entity names. ")
        lines.append("Rewrite via the UI (dashboard / journey editor) using the canonical names listed in the `→` column.\n\n")
        lines.append("| PK | SK | Legacy hits |\n")
        lines.append("|---|---|---|\n")
        for f in findings:
            hits = "; ".join(f"`{k}` → `{v}`" for k, v in sorted(f["hits"].items()))
            lines.append(f"| `{f['pk']}` | `{f['sk']}` | {hits} |\n")

    out_path.write_text("".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--table", help="Explicit DDB table name override.")
    ap.add_argument("--output", default="migration-report.md", help="Output report path (default: migration-report.md).")
    args = ap.parse_args()

    alias_map, canonical_names = load_alias_map()
    table_name = resolve_table_name(args.table)
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    resource = boto3.resource("dynamodb", region_name=region)

    print(f"  table:           {table_name}")
    print(f"  legacy aliases:  {len(alias_map)}")
    print(f"  canonical names: {len(canonical_names)}")
    print()

    print("  Scanning for legacy entity references in SOLUTION/VIEW/DASHBOARD/JOURNEY rows ...")
    findings = scan_for_legacy_refs(resource, table_name, alias_map)
    print(f"    {len(findings)} legacy references found")

    print("  Probing per-canonical-entity rule health ...")
    health = per_entity_rule_health(resource, table_name, canonical_names)
    bound = sum(1 for h in health if h["active"] == 1)
    unbound = sum(1 for h in health if h["active"] == 0)
    ambiguous = sum(1 for h in health if h["active"] > 1)
    print(f"    bound:     {bound}  /  {len(canonical_names)}")
    print(f"    unbound:   {unbound}")
    print(f"    ambiguous: {ambiguous}")

    out_path = Path(args.output)
    write_report(out_path, table_name, findings, health)
    print()
    print(f"  Report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
