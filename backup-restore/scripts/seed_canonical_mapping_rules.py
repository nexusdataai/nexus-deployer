#!/usr/bin/env python3
"""
Seed mapping rules for canonical VDL entities.

Background
----------
The Virtual Data Layer schema was refactored to canonical-entities.yaml
(68 source-agnostic business entities across 12 domains: Customer,
AccountingPeriod, Invoice, Purchase_Order, etc.). The mapping-rule
layer was NOT updated alongside, so the only active rules in
foundry-workspace point at the OLD solution-result entities
(O2C_KPI_Trend, PA_Forecast_Result, ESG_Action_Log, ...).

Result: when the UI's Virtual Data tab queries a canonical entity, the
backend's VirtualQueryService finds no active mapping rule and the data
preview comes back empty -- even though the simulator data IS present
and queryable.

What this script does
---------------------
For each canonical entity in /api/v1/control-plane/entities:

  1. Decide which simulator hosts it via DOMAIN_TO_SIM.
  2. Search the simulator's known tables for one matching the canonical
     name OR any of its aliases (with optional Oracle_/SAP_ prefix
     tolerance).
  3. POST /api/v1/mapping-rules with identity field_maps (source_field ==
     target_field) for every field in the canonical's field list.
  4. PUT /api/v1/mapping-rules/{id}  status=active.

Idempotent: re-runs skip canonicals that already have an active rule
(regardless of who wrote it). Use --force to override.

Operation: all backend interactions happen via ``kubectl exec`` against
a Running backend pod, the same pattern as ``simulator_backup.py
hydrate``. The script itself doesn't talk to AWS.

Usage
-----
  # Dry-run first (mandatory before first execute on a new cluster)
  python3 seed_canonical_mapping_rules.py \\
      --capability nexus-ai --env prod --dry-run

  # Execute
  python3 seed_canonical_mapping_rules.py \\
      --capability nexus-ai --env prod

  # Subset (good for iterating during testing)
  python3 seed_canonical_mapping_rules.py \\
      --capability nexus-ai --env dev \\
      --only-domain "Finance - General Ledger" --dry-run

Make sure your kubectl context points at the target cluster:
  aws eks update-kubeconfig --name {cluster} --profile {profile}
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------------------------------------------------------
# Domain -> simulator routing
# ----------------------------------------------------------------------------

# Each domain in canonical-entities.yaml maps to one PRIMARY simulator
# where its tables live. When a domain has overlapping coverage between
# simulators (e.g. Customer & Sales lives in both SFDC and Oracle as
# Account / AR_Customer), the primary is listed first and the fallback
# second. We prefer the primary's match; only fall back when the
# canonical's aliases don't match anything in the primary.
DOMAIN_TO_SIM: Dict[str, List[str]] = {
    # Oracle ERP (Finance + procurement master)
    "Finance - General Ledger":   ["oracle"],
    "Finance - Receivables":      ["oracle"],
    "Finance - Payables":         ["oracle"],
    "Procurement":                ["oracle", "sap"],

    # SFDC primary, Oracle as Customer fallback (Account ⇄ AR_Customer)
    "Customer & Sales":           ["sfdc", "oracle"],

    # SAP S/4HANA — supply chain + production master / movements
    "Inventory":                  ["sap"],
    "Product Master":             ["sap", "oracle"],
    "Production & Quality":       ["sap"],
    "Logistics":                  ["sap"],

    # Synthetic CPQ simulators
    "Commercial CPQ":             ["tpm"],
    "Strategic Sourcing":         ["sourcing"],

    # External-source simulator (single bucket, multiple sub-systems)
    "Document Management":        ["external"],
    "External Signals":           ["external"],
    "File Capture":               ["external"],

    # Solution-result entities — already have Auto Sim rules; the script
    # will skip them as "already mapped" via the idempotency check.
    "Order-to-Cash Results":      ["external"],
}

# Per-simulator API path used to enumerate tables, and the
# DB schema name VirtualQueryService routes to.
SIM_INFO: Dict[str, Dict[str, str]] = {
    "sfdc":     {"api": "sfdc-simulator",       "schema": "sfdc_itxp2dev"},
    "oracle":   {"api": "oracle-erp-simulator", "schema": "oracle_erp"},
    "sap":      {"api": "sap-simulator",        "schema": "sap_s4hana"},
    "external": {"api": "external-simulator",   "schema": "external_sources"},
    "tpm":      {"api": "tpm-simulator",        "schema": "tpm_cpq"},
    "sourcing": {"api": "sourcing-simulator",   "schema": "sourcing_cpq"},
}

# Simulators where seed_data() prefixes tables with the system name
# (e.g. Oracle's seed_data produces Oracle_GL_Period rather than
# GL_Period). We try both prefixed and bare forms when resolving.
PREFIX_BY_SIM: Dict[str, str] = {
    "oracle": "Oracle_",
}


# ----------------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------------

@dataclass
class Match:
    sim_key: str            # "sfdc" / "oracle" / ...
    sim_schema: str         # "sfdc_itxp2dev" / "oracle_erp" / ...
    sim_table: str          # actual simulator table name (with prefix if any)
    via_alias: str          # which canonical alias or name produced the match


@dataclass
class SeedResult:
    canonical: str
    status: str             # "created" | "skipped_existing" | "no_source_table" | "error"
    detail: Optional[str] = None
    match: Optional[Match] = None
    rule_id: Optional[str] = None


# ----------------------------------------------------------------------------
# kubectl-exec helpers (mirrors simulator_backup.py hydrate)
# ----------------------------------------------------------------------------

def _run_subprocess(cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s running: {' '.join(cmd)}"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _find_pod(namespace: str, label_selector: str) -> Optional[str]:
    cmd = [
        "kubectl", "-n", namespace, "get", "pods",
        "-l", label_selector,
        "--field-selector=status.phase=Running",
        "-o", "jsonpath={.items[0].metadata.name}",
    ]
    rc, out, err = _run_subprocess(cmd)
    if rc != 0 or not out.strip():
        return None
    return out.strip()


def _exec_curl(
    namespace: str, pod: str, url: str,
    *, method: str = "GET", body: Optional[Any] = None, timeout: int = 60,
) -> Tuple[int, Dict[str, Any], str]:
    """
    Run `curl` inside `pod`. Returns (http_status_code, parsed_json_body,
    raw_text). http_status_code is the curl-reported response code
    (or 0 if curl itself failed).
    """
    cmd = [
        "kubectl", "-n", namespace, "exec", pod, "--",
        "curl", "-s", "-S",
        "-X", method,
        "-H", "Content-Type: application/json",
        "-w", "\n__HTTP_STATUS=%{http_code}",
    ]
    if body is not None:
        cmd.extend(["--data-binary", json.dumps(body)])
    cmd.append(url)
    rc, out, err = _run_subprocess(cmd, timeout)
    if rc != 0:
        return 0, {}, (out + "\n" + err).strip()

    text = out
    status = 0
    if "\n__HTTP_STATUS=" in text:
        body_text, status_text = text.rsplit("\n__HTTP_STATUS=", 1)
        try:
            status = int(status_text.strip())
        except ValueError:
            status = 0
    else:
        body_text = text

    parsed: Dict[str, Any] = {}
    if body_text.strip():
        try:
            parsed = json.loads(body_text)
        except json.JSONDecodeError:
            parsed = {"_raw": body_text}
    return status, parsed, body_text


# ----------------------------------------------------------------------------
# Resolution
# ----------------------------------------------------------------------------

def _candidate_names(canonical: Dict[str, Any]) -> List[str]:
    """Names to try matching against simulator tables: canonical name + aliases."""
    out = [canonical.get("name", "")]
    out.extend(canonical.get("aliases") or [])
    return [c for c in out if c]


def resolve_match(
    canonical: Dict[str, Any],
    sim_tables: Dict[str, Dict[str, set]],
) -> Optional[Match]:
    """
    Given a canonical entity dict and a {sim_key: {schema: set(table_names)}}
    inventory, return the best simulator+table match, or None.
    """
    domain = (canonical.get("domain") or "").strip()
    sim_keys = DOMAIN_TO_SIM.get(domain, [])
    if not sim_keys:
        # Unknown domain — fall back to searching every simulator.
        sim_keys = list(SIM_INFO.keys())

    candidates = _candidate_names(canonical)

    for sim_key in sim_keys:
        info = SIM_INFO.get(sim_key)
        if not info:
            continue
        schema = info["schema"]
        tables = sim_tables.get(sim_key, {}).get(schema) or set()
        if not tables:
            continue
        prefix = PREFIX_BY_SIM.get(sim_key, "")
        for cand in candidates:
            # Try bare name first.
            if cand in tables:
                return Match(sim_key, schema, cand, via_alias=cand)
            # Then prefixed (e.g. Oracle_GL_Period).
            if prefix and f"{prefix}{cand}" in tables:
                return Match(sim_key, schema, f"{prefix}{cand}",
                             via_alias=cand)
    return None


# ----------------------------------------------------------------------------
# Main flow
# ----------------------------------------------------------------------------

def fetch_canonicals(namespace: str, pod: str) -> List[Dict[str, Any]]:
    code, data, raw = _exec_curl(
        namespace, pod, "http://localhost:8000/api/v1/control-plane/entities",
    )
    if code != 200:
        raise SystemExit(f"  ERROR: GET /entities returned HTTP {code}\n  body: {raw[:500]}")
    if not isinstance(data, list):
        raise SystemExit(f"  ERROR: /entities did not return a list (got {type(data).__name__})")
    return data


def fetch_existing_rules(namespace: str, pod: str) -> Dict[str, Dict[str, Any]]:
    """Returns {virtual_entity: rule_dict} for ALL existing rules."""
    code, data, raw = _exec_curl(
        namespace, pod, "http://localhost:8000/api/v1/mapping-rules",
    )
    if code != 200:
        raise SystemExit(f"  ERROR: GET /mapping-rules returned HTTP {code}")
    rules = data if isinstance(data, list) else []
    by_ve: Dict[str, Dict[str, Any]] = {}
    for r in rules:
        ve = r.get("virtualEntity") or r.get("virtual_entity")
        if ve:
            by_ve[ve] = r
    return by_ve


def fetch_simulator_tables(
    namespace: str, pod: str,
) -> Dict[str, Dict[str, set]]:
    """Returns {sim_key: {schema: set(table_names)}} for all 6 simulators."""
    out: Dict[str, Dict[str, set]] = {}
    for sim_key, info in SIM_INFO.items():
        url = f"http://localhost:8000/api/v1/{info['api']}/objects"
        code, data, _ = _exec_curl(namespace, pod, url)
        if code != 200:
            print(f"  WARN: {sim_key} simulator /objects returned HTTP {code}; "
                  f"treating as empty (it may not be loaded yet)")
            out[sim_key] = {}
            continue
        objs = data.get("objects", []) if isinstance(data, dict) else []
        by_schema: Dict[str, set] = {}
        for o in objs:
            sch = o.get("schemaName") or o.get("schema_name") or ""
            tn = o.get("tableName") or o.get("table_name") or ""
            if sch and tn:
                by_schema.setdefault(sch, set()).add(tn)
        out[sim_key] = by_schema
    return out


def build_create_request(
    canonical: Dict[str, Any], match: Match,
) -> Dict[str, Any]:
    """Build the JSON body for POST /api/v1/mapping-rules."""
    name = canonical["name"]
    fields = canonical.get("fields") or []
    field_maps = [
        {"sourceField": f["name"], "targetField": f["name"]}
        for f in fields if f.get("name")
    ]
    # Some canonicals have zero typed fields. The MappingRuleResponse
    # expects a list (possibly empty) — the server will accept it.
    return {
        "name": f"Canonical: {name}",
        "virtualEntity": name,
        "sourceType": "FDW",
        "sourceSystem": match.sim_key,
        "sourceSchema": match.sim_schema,
        "sourceTable": match.sim_table,
        "fieldMaps": field_maps,
    }


def create_and_activate_rule(
    namespace: str, pod: str, payload: Dict[str, Any], dry_run: bool,
) -> Tuple[bool, Optional[str], str]:
    """Returns (ok, rule_id, detail)."""
    if dry_run:
        return True, None, "[dry-run] would POST + activate"

    # POST /api/v1/mapping-rules
    code, resp, raw = _exec_curl(
        namespace, pod, "http://localhost:8000/api/v1/mapping-rules",
        method="POST", body=payload,
    )
    if code not in (200, 201):
        return False, None, f"POST /mapping-rules HTTP {code}: {raw[:300]}"
    rule_id = resp.get("id") if isinstance(resp, dict) else None
    if not rule_id:
        return False, None, f"POST returned 201 but no id in body: {raw[:200]}"

    # PUT /api/v1/mapping-rules/{id}  status=active
    code, resp, raw = _exec_curl(
        namespace, pod,
        f"http://localhost:8000/api/v1/mapping-rules/{rule_id}",
        method="PUT", body={"status": "active"},
    )
    if code != 200:
        return False, rule_id, f"created but PUT to activate failed HTTP {code}: {raw[:300]}"
    return True, rule_id, "created + activated"


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="seed_canonical_mapping_rules.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--capability", default="nexus-ai")
    p.add_argument("--env", required=True)
    p.add_argument("--namespace", default=None,
                   help="Override the {capability}-{env} namespace default.")
    p.add_argument("--label-selector", default=None,
                   help="Override the app={capability}-{env}-backend label.")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only. Print what would be created without making changes.")
    p.add_argument("--only-domain", default=None,
                   help="Limit to canonical entities in this domain "
                        "(e.g. 'Finance - General Ledger').")
    p.add_argument("--force", action="store_true",
                   help="Overwrite even if a canonical already has an "
                        "active rule. Default is to skip.")
    args = p.parse_args(argv)

    if shutil.which("kubectl") is None:
        raise SystemExit("  ERROR: kubectl not found on PATH.")

    namespace = args.namespace or f"{args.capability}-{args.env}"
    label = args.label_selector or f"app={args.capability}-{args.env}-backend"

    print(f"  capability: {args.capability}")
    print(f"  env:        {args.env}")
    print(f"  namespace:  {namespace}")
    print(f"  selector:   {label}")
    print(f"  mode:       {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    if args.only_domain:
        print(f"  filter:     domain == {args.only_domain!r}")
    if args.force:
        print(f"  force:      yes (overwrite existing rules)")
    print()

    pod = _find_pod(namespace, label)
    if not pod:
        raise SystemExit(
            f"  ERROR: no Running pod in {namespace} matching {label}. "
            f"Check --namespace / --label-selector."
        )
    print(f"  pod: {pod}")
    print()

    print("  Fetching canonical entities ...")
    canonicals = fetch_canonicals(namespace, pod)
    print(f"    {len(canonicals)} canonical entities loaded")
    if args.only_domain:
        canonicals = [c for c in canonicals if (c.get("domain") or "") == args.only_domain]
        print(f"    {len(canonicals)} after domain filter")

    print("  Fetching existing mapping rules ...")
    existing = fetch_existing_rules(namespace, pod)
    print(f"    {len(existing)} existing rules")

    print("  Fetching simulator table inventories ...")
    sim_tables = fetch_simulator_tables(namespace, pod)
    total = sum(sum(len(v) for v in d.values()) for d in sim_tables.values())
    print(f"    {total} simulator tables visible across "
          f"{sum(1 for v in sim_tables.values() if v)} loaded simulators")
    print()

    results: List[SeedResult] = []
    for canon in canonicals:
        name = canon.get("name") or ""
        domain = canon.get("domain") or "?"
        if not name:
            continue

        # Idempotency: skip if a rule already exists for this canonical
        # (unless --force).
        if name in existing and not args.force:
            results.append(SeedResult(
                canonical=name, status="skipped_existing",
                detail=f"active rule {existing[name].get('id')!r} already maps "
                       f"to {existing[name].get('sourceSchema')}.{existing[name].get('sourceTable')}",
            ))
            continue

        # Resolve a simulator + table.
        match = resolve_match(canon, sim_tables)
        if match is None:
            results.append(SeedResult(
                canonical=name, status="no_source_table",
                detail=f"no simulator table matched (domain={domain!r}, "
                       f"tried names: {_candidate_names(canon)})",
            ))
            continue

        payload = build_create_request(canon, match)
        ok, rule_id, detail = create_and_activate_rule(
            namespace, pod, payload, args.dry_run,
        )
        results.append(SeedResult(
            canonical=name,
            status="created" if ok else "error",
            detail=detail,
            match=match,
            rule_id=rule_id,
        ))

    # Summary.
    print()
    print("  " + "=" * 70)
    print("  Per-entity result:")
    print("  " + "=" * 70)
    by_status: Dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.match:
            via = f"  via_alias={r.match.via_alias!r}" if r.match.via_alias != r.canonical else ""
            print(f"    [{r.status:18s}] {r.canonical:28s} "
                  f"-> {r.match.sim_schema}.{r.match.sim_table}{via}")
        else:
            print(f"    [{r.status:18s}] {r.canonical:28s}  {r.detail or ''}")
    print()
    print(f"  Summary: {dict(by_status)}")
    if "error" in by_status:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
