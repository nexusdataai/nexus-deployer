#!/usr/bin/env python3
"""
Infrastructure Diagnostics CLI

Run infrastructure health checks from inside the backend pod.

Modes:
  --api    Hit the running gateway at localhost:8000 (default)
  --direct Import the service and run checks in-process (no server needed)

Usage:
    # Run all checks via the API (backend must be running)
    python scripts/infra-diagnostics/diagnose.py

    # Run a specific category
    python scripts/infra-diagnostics/diagnose.py --category backend
    python scripts/infra-diagnostics/diagnose.py --category dynamodb
    python scripts/infra-diagnostics/diagnose.py --category s3
    python scripts/infra-diagnostics/diagnose.py --category glue-athena
    python scripts/infra-diagnostics/diagnose.py --category bssmagic
    python scripts/infra-diagnostics/diagnose.py --category frontend

    # Run checks directly (in-process, no running server needed)
    python scripts/infra-diagnostics/diagnose.py --direct

    # JSON output for scripting
    python scripts/infra-diagnostics/diagnose.py --json

    # Custom backend URL (e.g. from another pod)
    python scripts/infra-diagnostics/diagnose.py --url http://call-processing-dev-backend-svc:8000
"""

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

_env_local = Path(__file__).resolve().parent / ".env.local"
if _env_local.is_file():
    for _line in _env_local.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

CATEGORIES = ["frontend", "backend", "dynamodb", "s3", "glue-athena", "bssmagic"]

STATUS_SYMBOLS = {
    "pass": "\033[32m✓\033[0m",
    "fail": "\033[31m✗\033[0m",
    "warning": "\033[33m⚠\033[0m",
    "skipped": "\033[90m⏭\033[0m",
}

OVERALL_COLORS = {
    "healthy": "\033[32m",
    "degraded": "\033[33m",
    "unhealthy": "\033[31m",
}

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def run_via_api(base_url: str, category: str | None) -> dict:
    path = "/api/v1/diagnostics/infrastructure"
    if category:
        path += f"/{category}"
    url = f"{base_url}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        return {"error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"error": str(e)}


def run_direct(category: str | None) -> dict:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'call-scripts'))
    os.environ.setdefault("USE_AWS_SECRETS", "true")

    from services.diagnostics_service import InfrastructureDiagnosticsService
    svc = InfrastructureDiagnosticsService()

    dispatch = {
        None: svc.run_all,
        "frontend": svc.run_frontend,
        "backend": svc.run_backend,
        "dynamodb": svc.run_dynamodb,
        "s3": svc.run_s3,
        "glue-athena": svc.run_glue_athena,
        "bssmagic": svc.run_bssmagic,
    }
    fn = dispatch.get(category, svc.run_all)
    result = asyncio.run(fn())
    return result.to_dict()


def print_result(data: dict, use_json: bool):
    if use_json:
        print(json.dumps(data, indent=2))
        return

    if "error" in data:
        print(f"\n{STATUS_SYMBOLS['fail']} Error: {data['error']}\n")
        return

    overall = data.get("status", "unknown")
    color = OVERALL_COLORS.get(overall, "")
    print(f"\n{BOLD}Infrastructure Diagnostics{RESET}")
    print(f"Timestamp: {data.get('timestamp', 'N/A')}")
    print(f"Overall:   {color}{BOLD}{overall.upper()}{RESET}\n")

    checks = data.get("checks", {})
    if not checks:
        print("  No checks returned.\n")
        return

    max_key = max(len(k) for k in checks)

    for key, check in checks.items():
        status = check.get("status", "unknown")
        sym = STATUS_SYMBOLS.get(status, "?")
        latency = check.get("latency_ms", 0)
        msg = check.get("message", "")
        print(f"  {sym} {key:<{max_key}}  {DIM}{latency:>8.0f}ms{RESET}  {msg}")

        details = check.get("details", {})
        if "tables" in details:
            for tbl_key, tbl in details["tables"].items():
                tbl_st = STATUS_SYMBOLS.get(tbl.get("status", "fail"), "?")
                r = "R:OK" if tbl.get("readable") else "R:NO"
                w = "W:OK" if tbl.get("writable") else "W:NO"
                print(f"      {tbl_st} {tbl_key}: {tbl.get('table_name', '?')}  {r}  {w}")
        if "buckets" in details:
            for bkt_key, bkt in details["buckets"].items():
                bkt_st = STATUS_SYMBOLS.get(bkt.get("status", "fail"), "?")
                r = "R:OK" if bkt.get("read_access") else "R:NO"
                w = "W:OK" if bkt.get("write_access") else "W:NO"
                print(f"      {bkt_st} {bkt_key}: {bkt.get('bucket', '?')}  {r}  {w}")

    fail_count = sum(1 for c in checks.values() if c.get("status") == "fail")
    pass_count = sum(1 for c in checks.values() if c.get("status") == "pass")
    print(f"\n  {pass_count} passed, {fail_count} failed, {len(checks)} total\n")


def main():
    parser = argparse.ArgumentParser(
        description="Infrastructure Diagnostics CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Categories: {', '.join(CATEGORIES)}")
    parser.add_argument("--category", "-c", choices=CATEGORIES,
                        help="Run checks for a specific category only")
    parser.add_argument("--direct", "-d", action="store_true",
                        help="Run checks in-process (no running server needed)")
    parser.add_argument("--api", "-a", action="store_true", default=True,
                        help="Hit the gateway API (default)")
    parser.add_argument("--url", default="http://localhost:8000",
                        help="Backend gateway URL (default: http://localhost:8000)")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output raw JSON")
    args = parser.parse_args()

    if args.direct:
        data = run_direct(args.category)
    else:
        data = run_via_api(args.url, args.category)

    print_result(data, args.json)

    if data.get("status") == "unhealthy" or "error" in data:
        sys.exit(1)
    elif data.get("status") == "degraded":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
