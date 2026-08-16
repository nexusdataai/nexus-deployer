#!/usr/bin/env python3
"""
Tiered post-restore verification for context-dr.sh.

Tier 1: DynamoDB (delegated to foundry/transformation verify + prefix check)
Tier 2: REST entity APIs
Tier 3: Knowledge index (/onto/stats)
Tier 4: Simulator health
Tier 5: RAG validation metrics (from semantic_rag result)

Exit 0 when all required checks through --max-tier pass; exit 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class Check:
    name: str
    method: str
    path: str
    manifest_key: Optional[str] = None
    transform_key: Optional[str] = None
    min_count: int = 1
    optional: bool = False
    count_fn: Optional[Callable[[Any], int]] = None
    tier: int = 2


def _load_foundry_manifest(path: str) -> Dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        mf = tar.extractfile(tar.getmember("manifest.json"))
        return json.loads(mf.read().decode("utf-8"))


def _load_transform_manifest(path: str) -> Dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        mf = tar.extractfile(tar.getmember("manifest.json"))
        return json.loads(mf.read().decode("utf-8"))


def _load_sim_manifest(path: str) -> Dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        member = None
        for m in tar.getmembers():
            if m.name.endswith("manifest.json") and m.isfile():
                member = m
                break
        if member is None:
            member = tar.getmember("manifest.json")
        mf = tar.extractfile(member)
        return json.loads(mf.read().decode("utf-8"))


def _kubectl_curl(namespace: str, deployment: str, method: str, path: str) -> Tuple[int, str]:
    url = f"http://127.0.0.1:8000{path}"
    cmd = [
        "kubectl", "exec", "-n", namespace, f"deploy/{deployment}", "--",
        "curl", "-sS", "-X", method, "-w", "\n%{http_code}",
        "--max-time", "30", url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 0, proc.stderr.strip() or proc.stdout.strip()
    lines = proc.stdout.rsplit("\n", 1)
    if len(lines) == 2:
        body, code_str = lines[0], lines[1].strip()
    else:
        body, code_str = proc.stdout, "0"
    try:
        code = int(code_str)
    except ValueError:
        code = 0
        body = proc.stdout
    return code, body


def _count_array(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    return 0


def _count_total_field(data: Any) -> int:
    if isinstance(data, dict):
        if "total" in data:
            return int(data["total"])
        if "data" in data and isinstance(data["data"], list):
            return len(data["data"])
        if "items" in data and isinstance(data["items"], list):
            return len(data["items"])
    return _count_array(data)


def _count_entities(data: Any) -> int:
    if isinstance(data, dict):
        if "entities" in data and isinstance(data["entities"], list):
            return len(data["entities"])
        if "total" in data:
            return int(data["total"])
    return _count_array(data)


TIER2_CHECKS: List[Check] = [
    Check("health", "GET", "/health", min_count=0,
          count_fn=lambda _: 0, optional=False, tier=2),
    Check("solution-catalog", "GET", "/api/v1/solution-catalog",
          manifest_key="SOLUTIONYAML", count_fn=_count_total_field, tier=2),
    Check("solutions", "GET", "/api/v1/solutions",
          manifest_key="SOLUTION", count_fn=_count_array, tier=2),
    Check("dashboards", "GET", "/api/v1/dashboards",
          manifest_key="DASHBOARD", count_fn=_count_array, tier=2),
    Check("views", "GET", "/api/v1/views",
          manifest_key="VIEW", count_fn=_count_array, tier=2),
    Check("data-planes", "GET", "/api/data-planes",
          manifest_key="DATAPLANE", count_fn=_count_array, optional=True, tier=2),
    Check("mapping-rules", "GET", "/api/v1/mapping-rules",
          manifest_key="MAPPINGRULE", count_fn=_count_array, tier=2),
    Check("journeys", "GET", "/api/v1/journeys/?limit=1000",
          transform_key="journey_gsi_count", count_fn=_count_total_field, tier=2),
    Check("knowledge-pipelines", "GET", "/api/v1/knowledge-pipelines",
          min_count=1, count_fn=_count_total_field, tier=2),
    Check("kp-runs", "GET", "/api/v1/knowledge-pipelines/semantic_rag/runs",
          min_count=1, count_fn=_count_total_field, tier=2),
    Check("entities", "GET", "/api/v1/control-plane/entities",
          manifest_key="VDLENTITY", count_fn=_count_entities, tier=2),
    Check("connectors", "GET", "/api/v1/connectors",
          manifest_key="CONNECTOR", count_fn=_count_array, optional=True, tier=2),
]

SIM_STATUS_ENDPOINTS = [
    ("sfdc-simulator", "/api/v1/sfdc-simulator/status"),
    ("oracle-erp-simulator", "/api/v1/oracle-erp-simulator/status"),
    ("sap-simulator", "/api/v1/sap-simulator/status"),
    ("external-simulator", "/api/v1/external-simulator/status"),
]


def _expected_count(
    check: Check,
    foundry_counts: Dict[str, int],
    foundry_total: int,
    transform_manifest: Dict[str, Any],
) -> int:
    if check.manifest_key:
        return int(foundry_counts.get(check.manifest_key, 0))
    if check.transform_key:
        return int(transform_manifest.get(check.transform_key) or 0)
    return check.min_count


def _run_tier2(
    args: argparse.Namespace,
    foundry_counts: Dict[str, int],
    foundry_total: int,
    transform_mf: Dict[str, Any],
) -> Tuple[int, int, int]:
    passed = failed = warned = 0
    print("── Tier 2: REST entity APIs ──")
    for check in TIER2_CHECKS:
        expected = _expected_count(check, foundry_counts, foundry_total, transform_mf)
        if expected == 0 and check.name not in ("health", "knowledge-pipelines", "kp-runs"):
            if check.transform_key and not transform_mf:
                print(f"  SKIP  {check.name:22s} (no transformation backup)")
                continue
            if check.manifest_key and check.manifest_key not in foundry_counts:
                if check.name == "solution-catalog":
                    expected = 1
                elif check.optional:
                    print(f"  SKIP  {check.name:22s} (not in backup manifest)")
                    continue
                else:
                    print(f"  SKIP  {check.name:22s} (not in backup manifest)")
                    continue

        min_required = max(check.min_count, expected) if expected > 0 else check.min_count
        if check.name in ("knowledge-pipelines", "kp-runs") and args.skip_semantic_rag:
            if check.name == "kp-runs":
                print(f"  SKIP  {check.name:22s} (--skip-semantic-rag)")
                continue

        code, body = _kubectl_curl(args.namespace, args.deployment, check.method, check.path)

        if check.name == "health":
            if code == 200:
                print(f"  OK    {check.name:22s} HTTP {code}")
                passed += 1
            else:
                print(f"  FAIL  {check.name:22s} HTTP {code}")
                failed += 1
            continue

        if code == 404:
            msg = "HTTP 404"
            if check.optional:
                print(f"  WARN  {check.name:22s} {msg}")
                warned += 1
            else:
                print(f"  FAIL  {check.name:22s} {msg}  expected>={min_required}")
                failed += 1
            continue

        if code >= 500 or code == 0:
            print(f"  FAIL  {check.name:22s} HTTP {code}  expected>={min_required}")
            failed += 1
            continue

        try:
            data = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            print(f"  FAIL  {check.name:22s} invalid JSON  HTTP {code}")
            failed += 1
            continue

        if check.name == "knowledge-pipelines":
            items = data.get("items") or []
            has_sr = any(
                (i.get("pipelineId") or i.get("id")) == "semantic_rag"
                for i in items
            )
            if has_sr:
                print(f"  OK    {check.name:22s} semantic_rag pipeline present")
                passed += 1
            else:
                print(f"  FAIL  {check.name:22s} semantic_rag pipeline missing")
                failed += 1
            continue

        actual = check.count_fn(data) if check.count_fn else 0
        if actual >= min_required:
            print(f"  OK    {check.name:22s} count={actual}  expected>={min_required}")
            passed += 1
        elif check.optional:
            print(f"  WARN  {check.name:22s} count={actual}  expected>={min_required}")
            warned += 1
        else:
            print(f"  FAIL  {check.name:22s} count={actual}  expected>={min_required}")
            failed += 1

    print()
    return passed, failed, warned


def _run_tier3(args: argparse.Namespace) -> Tuple[int, int, int]:
    passed = failed = warned = 0
    print("── Tier 3: Knowledge index (/onto/stats) ──")
    code, body = _kubectl_curl(args.namespace, args.deployment, "GET", "/onto/stats")
    if code != 200:
        print(f"  FAIL  onto-stats          HTTP {code}")
        print()
        return 0, 1, 0

    try:
        data = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        print("  FAIL  onto-stats          invalid JSON")
        print()
        return 0, 1, 0

    status = data.get("status", "")
    total = int(data.get("total_embeddings") or 0)
    by_type = data.get("by_content_type") or {}
    schema_count = int(by_type.get("onto_schema") or 0) if isinstance(by_type, dict) else 0

    min_emb = args.min_embeddings
    if status == "table_not_created" or total == 0:
        if args.skip_semantic_rag:
            print(f"  WARN  onto-stats          total_embeddings=0 (--skip-semantic-rag)")
            warned += 1
        else:
            print(f"  FAIL  onto-stats          total_embeddings=0 (run semantic_rag first)")
            failed += 1
    elif total < min_emb:
        print(f"  WARN  onto-stats          total_embeddings={total} < {min_emb}")
        warned += 1
        passed += 1
    else:
        print(f"  OK    onto-stats          total_embeddings={total}  onto_schema={schema_count}")
        passed += 1

    print()
    return passed, failed, warned


def _run_tier4(args: argparse.Namespace, sim_manifest: Optional[Dict[str, Any]]) -> Tuple[int, int, int]:
    passed = failed = warned = 0
    print("── Tier 4: Simulator health ──")
    if not sim_manifest:
        print("  SKIP  (no simulator backup)")
        print()
        return 0, 0, 0

    expected_by_name: Dict[str, int] = {}
    for ent in sim_manifest.get("simulators") or []:
        expected_by_name[ent.get("name", "")] = int(ent.get("key_count") or 0)

    for name, path in SIM_STATUS_ENDPOINTS:
        code, body = _kubectl_curl(args.namespace, args.deployment, "GET", path)
        if code != 200:
            exp_keys = expected_by_name.get(name.replace("external-simulator", "external-sources"), 0)
            if exp_keys == 0:
                print(f"  WARN  {name:22s} HTTP {code} (source had 0 keys)")
                warned += 1
            else:
                print(f"  FAIL  {name:22s} HTTP {code}")
                failed += 1
            continue
        try:
            data = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            print(f"  FAIL  {name:22s} invalid JSON")
            failed += 1
            continue

        loaded = data.get("loaded") is True
        tables = data.get("tables_with_data") or (data.get("result") or {}).get("tables_with_data") or 0
        logical = name.replace("external-simulator", "external-sources")
        exp_keys = expected_by_name.get(logical, 0)

        if exp_keys == 0:
            print(f"  OK    {name:22s} loaded={loaded} (source empty)")
            passed += 1
        elif loaded and int(tables or 0) > 0:
            print(f"  OK    {name:22s} loaded={loaded} tables_with_data={tables}")
            passed += 1
        elif loaded:
            print(f"  WARN  {name:22s} loaded={loaded} tables_with_data={tables}")
            warned += 1
        else:
            print(f"  FAIL  {name:22s} not loaded")
            failed += 1

    print()
    return passed, failed, warned


def _run_tier5(args: argparse.Namespace) -> Tuple[int, int, int]:
    passed = failed = warned = 0
    print("── Tier 5: RAG validation metrics ──")
    if args.skip_semantic_rag:
        print("  SKIP  (--skip-semantic-rag)")
        print()
        return 0, 0, 0

    if not args.semantic_rag_result:
        print("  WARN  no semantic_rag result file")
        print()
        return 0, 0, 1

    try:
        with open(args.semantic_rag_result, "r", encoding="utf-8") as f:
            result = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  FAIL  could not read result: {e}")
        print()
        return 0, 1, 0

    if not result.get("success"):
        print(f"  FAIL  semantic_rag status={result.get('status')}")
        print()
        return 0, 1, 0

    score = result.get("validation_avg_score")
    if score is None:
        metrics = result.get("metrics") or {}
        score = metrics.get("validation_avg_score")

    if score is not None:
        score_f = float(score)
        if score_f >= 4.0:
            print(f"  OK    validation_avg_score={score_f}")
            passed += 1
        else:
            print(f"  FAIL  validation_avg_score={score_f} < 4.0")
            failed += 1
        if score_f < 5.0:
            print(f"  WARN  below production target 5.0")
            warned += 1
    else:
        print("  WARN  validation_avg_score not in result (job completed)")
        warned += 1
        passed += 1

    print()
    return passed, failed, warned


def run_verify(args: argparse.Namespace) -> int:
    foundry_mf = _load_foundry_manifest(args.foundry_tar)
    foundry_counts = foundry_mf.get("counts") or {}
    foundry_total = int(foundry_mf.get("total") or sum(foundry_counts.values()))

    transform_mf: Dict[str, Any] = {}
    if args.transform_tar:
        transform_mf = _load_transform_manifest(args.transform_tar)

    sim_mf: Optional[Dict[str, Any]] = None
    if args.sim_tar:
        sim_mf = _load_sim_manifest(args.sim_tar)

    print(f"  namespace:     {args.namespace}")
    print(f"  deployment:    {args.deployment}")
    print(f"  max_tier:      {args.max_tier}")
    print(f"  foundry rows:  {foundry_total}")
    print()

    total_passed = total_failed = total_warned = 0

    if args.max_tier >= 2:
        p, f, w = _run_tier2(args, foundry_counts, foundry_total, transform_mf)
        total_passed += p
        total_failed += f
        total_warned += w

    if args.max_tier >= 3:
        p, f, w = _run_tier3(args)
        total_passed += p
        total_failed += f
        total_warned += w

    if args.max_tier >= 4:
        p, f, w = _run_tier4(args, sim_mf)
        total_passed += p
        total_failed += f
        total_warned += w

    if args.max_tier >= 5:
        p, f, w = _run_tier5(args)
        total_passed += p
        total_failed += f
        total_warned += w

    print(f"  Verification: {total_passed} passed, {total_failed} failed, {total_warned} warnings")
    return 1 if total_failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Tiered DR verification")
    p.add_argument("--namespace", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--foundry-tar", required=True)
    p.add_argument("--transform-tar", default=None)
    p.add_argument("--sim-tar", default=None)
    p.add_argument("--semantic-rag-result", default=None)
    p.add_argument("--max-tier", type=int, default=5, choices=[2, 3, 4, 5])
    p.add_argument("--min-embeddings", type=int, default=100)
    p.add_argument("--skip-semantic-rag", action="store_true")
    return run_verify(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
