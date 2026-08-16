#!/usr/bin/env python3
"""
Post-restore API verification for context-dr.sh.

Probes the target backend (via kubectl exec) and compares entity counts
exposed by REST APIs against backup tarball manifests (foundry +
transformation-system).

Exit 0 when all required checks pass; exit 1 on any failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


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


def _load_foundry_manifest(path: str) -> Dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        mf = tar.extractfile(tar.getmember("manifest.json"))
        return json.loads(mf.read().decode("utf-8"))


def _load_transform_manifest(path: str) -> Dict[str, Any]:
    with tarfile.open(path, "r:gz") as tar:
        mf = tar.extractfile(tar.getmember("manifest.json"))
        return json.loads(mf.read().decode("utf-8"))


def _kubectl_curl(namespace: str, deployment: str, method: str, path: str) -> tuple[int, str]:
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
    return _count_array(data)


DEFAULT_CHECKS: List[Check] = [
    Check("health", "GET", "/health", min_count=0,
          count_fn=lambda _: 0, optional=False),
    Check("solution-catalog", "GET", "/api/v1/solution-catalog",
          manifest_key="SOLUTIONYAML", count_fn=_count_total_field),
    Check("solutions", "GET", "/api/v1/solutions",
          manifest_key="SOLUTION", count_fn=_count_array),
    Check("dashboards", "GET", "/api/v1/dashboards",
          manifest_key="DASHBOARD", count_fn=_count_array),
    Check("views", "GET", "/api/v1/views",
          manifest_key="VIEW", count_fn=_count_array),
    Check("data-planes", "GET", "/api/data-planes",
          manifest_key="DATAPLANE", count_fn=_count_array, optional=True),
    Check("mapping-rules", "GET", "/api/v1/mapping-rules",
          manifest_key="MAPPINGRULE", count_fn=_count_array),
    Check("journeys", "GET", "/api/v1/journeys/?limit=1000",
          transform_key="journey_gsi_count", count_fn=_count_total_field),
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


def run_verify(args: argparse.Namespace) -> int:
    foundry_mf = _load_foundry_manifest(args.foundry_tar)
    foundry_counts = foundry_mf.get("counts") or {}
    foundry_total = int(foundry_mf.get("total") or sum(foundry_counts.values()))

    transform_mf: Dict[str, Any] = {}
    if args.transform_tar:
        transform_mf = _load_transform_manifest(args.transform_tar)

    ns = args.namespace
    dep = args.deployment

    print(f"  namespace:     {ns}")
    print(f"  deployment:    {dep}")
    print(f"  foundry tar:   {args.foundry_tar}")
    print(f"  manifest rows: {foundry_total}")
    if args.transform_tar:
        print(f"  journeys tar:  {args.transform_tar}")
    print()

    if args.entity_refresh:
        code, body = _kubectl_curl(
            ns, dep, "POST", "/api/v1/control-plane/entities/refresh",
        )
        print(f"  entity-refresh: HTTP {code}")
        if code not in (200, 201, 202, 204):
            print(f"    body: {body[:300]}")
        print()

    passed = 0
    failed = 0
    warned = 0

    for check in DEFAULT_CHECKS:
        expected = _expected_count(check, foundry_counts, foundry_total, transform_mf)
        if expected == 0 and check.name not in ("health",):
            if check.transform_key and not transform_mf:
                print(f"  SKIP  {check.name:20s} (no transformation backup)")
                continue
            if check.manifest_key and check.manifest_key not in foundry_counts:
                if check.name == "solution-catalog":
                    expected = 1
                else:
                    print(f"  SKIP  {check.name:20s} (not in backup manifest)")
                    continue

        min_required = max(check.min_count, expected) if expected > 0 else check.min_count
        code, body = _kubectl_curl(ns, dep, check.method, check.path)

        if check.name == "health":
            if code == 200:
                print(f"  OK    {check.name:20s} HTTP {code}")
                passed += 1
            else:
                print(f"  FAIL  {check.name:20s} HTTP {code}")
                failed += 1
            continue

        if code == 404:
            msg = f"HTTP 404 (route not mounted — restart backend after code fix?)"
            if check.optional:
                print(f"  WARN  {check.name:20s} {msg}")
                warned += 1
            else:
                print(f"  FAIL  {check.name:20s} {msg}  expected>={min_required}")
                failed += 1
            continue

        if code >= 500 or code == 0:
            print(f"  FAIL  {check.name:20s} HTTP {code}  expected>={min_required}")
            if body:
                print(f"         {body[:200]}")
            failed += 1
            continue

        try:
            data = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            print(f"  FAIL  {check.name:20s} invalid JSON  HTTP {code}")
            failed += 1
            continue

        actual = check.count_fn(data) if check.count_fn else 0
        if actual >= min_required:
            print(f"  OK    {check.name:20s} count={actual}  expected>={min_required}")
            passed += 1
        elif check.optional:
            print(f"  WARN  {check.name:20s} count={actual}  expected>={min_required}  HTTP {code}")
            warned += 1
        else:
            print(f"  FAIL  {check.name:20s} count={actual}  expected>={min_required}  HTTP {code}")
            failed += 1

    print()
    print(f"  API verification: {passed} passed, {failed} failed, {warned} warnings")
    if failed:
        print()
        print("  Hint: solution-catalog 404 means the backend did not mount")
        print("        /api/v1/solution-catalog at startup (pgvector/indexer).")
        print("        Rebuild/restart backend after gateway fix, or check pod logs.")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Verify DR restore via backend APIs")
    p.add_argument("--namespace", required=True)
    p.add_argument("--deployment", required=True)
    p.add_argument("--foundry-tar", required=True)
    p.add_argument("--transform-tar", default=None)
    p.add_argument("--entity-refresh", action="store_true",
                   help="POST /api/v1/control-plane/entities/refresh before checks")
    return run_verify(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
