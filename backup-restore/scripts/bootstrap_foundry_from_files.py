#!/usr/bin/env python3
"""
Bootstrap the Supply Chain Foundry DDB content from baked-in files.

Background
----------
As part of the Foundry DDB Consolidation (Stage 2) refactor, four content
types moved from filesystem/S3 to the ``foundry-workspace`` DynamoDB
table:

  - Canonical entities     (``VDLENTITY#`` rows, ``GSI1PK=VDLENTITY``)
  - Policy documents       (``POLICY#`` rows,     ``GSI1PK=POLICY``)
  - Workflow definitions   (``WORKFLOWDEF#``,     ``GSI1PK=WORKFLOWDEF``)
  - Integration mappings   (``INTEGRATIONDEF#``,  ``GSI1PK=INTEGRATIONDEF``)

This script seeds those rows for a freshly-provisioned cluster by reading
the baked-in ``enterprise-knowledge/`` directory inside a Running backend
pod and POSTing to ``/api/v1/control-plane/onto-data/foundry/bootstrap``.

Idempotent: re-runs skip rows that already exist (use ``--force`` to
overwrite). Equivalent to ``seed_canonical_mapping_rules.py`` for
mapping rules — typically run **once** per cluster, in this order:

    1. bootstrap_foundry_from_files.py      (canonical/policies/workflows/integrations)
    2. seed_canonical_mapping_rules.py      (mapping rules over the new VDL entities)

Operation: all backend interactions happen via ``kubectl exec`` against
a Running backend pod, the same pattern as ``simulator_backup.py``
hydrate and the existing mapping-rule scripts. The script itself does
not talk to AWS / DDB directly.

Usage
-----
    # Dry-run first (mandatory before first execute on a new cluster)
    python3 bootstrap_foundry_from_files.py --capability nexus-ai --env prod --dry-run

    # Execute everything
    python3 bootstrap_foundry_from_files.py --capability nexus-ai --env prod

    # Just one category (useful when adding a new policy file mid-cycle)
    python3 bootstrap_foundry_from_files.py --capability nexus-ai --env prod --only policies

    # Force overwrite existing rows (use with care)
    python3 bootstrap_foundry_from_files.py --capability nexus-ai --env prod --force

Make sure your kubectl context points at the target cluster:
    aws eks update-kubeconfig --name {cluster} --profile {profile}
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


VALID_CATEGORIES = ("canonical", "policies", "workflows", "integrations")


# ----------------------------------------------------------------------------
# kubectl-exec helpers (mirrors seed_canonical_mapping_rules.py)
# ----------------------------------------------------------------------------

def _run_subprocess(cmd: List[str], timeout: int = 120) -> Tuple[int, str, str]:
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
    rc, out, _err = _run_subprocess(cmd)
    if rc != 0 or not out.strip():
        return None
    return out.strip()


def _exec_curl_post(
    namespace: str,
    pod: str,
    url: str,
    timeout: int = 120,
) -> Tuple[int, Dict[str, Any], str]:
    cmd = [
        "kubectl", "-n", namespace, "exec", pod, "--",
        "curl", "-s", "-S",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-w", "\n__HTTP_STATUS=%{http_code}",
        url,
    ]
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
# Reporting
# ----------------------------------------------------------------------------

def _print_canonical(stats: Dict[str, Any]) -> None:
    if not stats:
        return
    print("  Canonical entities (VDLENTITY#)")
    if "error" in stats:
        print(f"    ERROR: {stats['error']}")
        return
    print(f"    created          : {stats.get('created', 0)}")
    print(f"    skipped_existing : {stats.get('skipped_existing', 0)}")
    print(f"    errors           : {stats.get('errors', 0)}")
    print(f"    total            : {stats.get('total', 0)}")


def _print_files(stats: Dict[str, Any]) -> None:
    if not stats:
        return
    by_cat = stats.get("by_category", {})
    print("  Knowledge files (POLICY# / WORKFLOWDEF# / INTEGRATIONDEF#)")
    for cat in ("policies", "workflows", "integrations"):
        if cat not in by_cat:
            continue
        s = by_cat[cat]
        print(
            f"    {cat:14s} created={s.get('created', 0):3d}"
            f"  skipped_existing={s.get('skipped_existing', 0):3d}"
            f"  errors={s.get('errors', 0):3d}"
            f"  total={s.get('total', 0):3d}"
        )
    print(
        f"    TOTAL          created={stats.get('created', 0)}"
        f"  skipped_existing={stats.get('skipped_existing', 0)}"
        f"  errors={stats.get('errors', 0)}"
    )


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="bootstrap_foundry_from_files.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--capability", default="nexus-ai")
    p.add_argument("--env", required=True)
    p.add_argument("--namespace", default=None,
                   help="Override the {capability}-{env} namespace default.")
    p.add_argument("--label-selector", default=None,
                   help="Override the app={capability}-{env}-backend label.")
    p.add_argument("--only", default=None,
                   help=(
                       f"Comma-separated subset of categories to bootstrap "
                       f"(default: all). Valid values: "
                       f"{', '.join(VALID_CATEGORIES)}."
                   ))
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only; do not write to DDB.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing DDB rows (default: skip).")
    args = p.parse_args(argv)

    if shutil.which("kubectl") is None:
        raise SystemExit("  ERROR: kubectl not found on PATH.")

    namespace = args.namespace or f"{args.capability}-{args.env}"
    label = args.label_selector or f"app={args.capability}-{args.env}-backend"

    # Validate --only against the known set up-front so the user gets a
    # clear error before we even resolve the pod.
    if args.only:
        requested = [c.strip() for c in args.only.split(",") if c.strip()]
        unknown = [c for c in requested if c not in VALID_CATEGORIES]
        if unknown:
            raise SystemExit(
                f"  ERROR: unknown --only categories: {unknown}. "
                f"Valid: {', '.join(VALID_CATEGORIES)}."
            )

    print(f"  capability: {args.capability}")
    print(f"  env:        {args.env}")
    print(f"  namespace:  {namespace}")
    print(f"  selector:   {label}")
    print(f"  mode:       {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    if args.only:
        print(f"  filter:     only={args.only}")
    if args.force:
        print(f"  force:      yes (overwrite existing rows)")
    print()

    pod = _find_pod(namespace, label)
    if not pod:
        raise SystemExit(
            f"  ERROR: no Running pod in {namespace} matching {label}. "
            f"Check --namespace / --label-selector."
        )
    print(f"  pod: {pod}")
    print()

    qs = []
    if args.only:
        qs.append(f"only={args.only}")
    if args.force:
        qs.append("force=true")
    if args.dry_run:
        qs.append("dry_run=true")
    qstr = ("?" + "&".join(qs)) if qs else ""
    url = f"http://localhost:8000/api/v1/control-plane/onto-data/foundry/bootstrap{qstr}"
    print(f"  POST {url}")
    print()

    code, payload, raw = _exec_curl_post(namespace, pod, url, timeout=300)
    if code != 200:
        print(f"  ERROR: HTTP {code}")
        print(f"  body: {raw[:1500]}")
        return 2

    print("  " + "=" * 70)
    print("  Bootstrap result")
    print("  " + "=" * 70)
    _print_canonical(payload.get("canonical") or {})
    print()
    _print_files(payload.get("files") or {})
    print()
    print(f"  Summary: {json.dumps({k: v for k, v in payload.items() if k in ('force', 'dry_run', 'requested')})}")

    has_errors = (
        (payload.get("canonical") or {}).get("errors")
        or (payload.get("files") or {}).get("errors")
    )
    return 0 if not has_errors else 2


if __name__ == "__main__":
    sys.exit(main())
