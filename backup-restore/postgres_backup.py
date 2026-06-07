"""
BSSMagic Postgres backup/restore module.

Backup:  shells out via `kubectl exec` into the bssmagic-0 pod to run
         `pg_dump -Fc bssmagic`, then `kubectl cp` the result to the local
         tarball under postgres/bssmagic.dump.

Restore: streams postgres/bssmagic.dump into a fresh `pg_restore` invocation
         on the target cluster's bssmagic-0 pod. Should run AFTER Velero
         has restored the BSSMagic PVC (so the target pod is up). If the
         target Postgres already has data (because Velero copied the PV
         contents), pg_restore is run with --clean --if-exists to overwrite.

Why both Velero PV snapshot AND a separate pg_dump? Velero with kopia/restic
takes a filesystem snapshot of an OPEN Postgres data directory; on restore,
Postgres recovers from WAL and is usually consistent, but `pg_dump` is the
canonical, guaranteed-consistent backup. For dev clones the Velero PV
restore alone is usually enough; the pg_dump is the belt-and-suspenders.

Requirements on operator workstation:
  - kubectl pointed at source (backup) or target (restore) cluster
  - access to bssmagic-0 pod
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import (
    BSSMAGIC_PG_DATABASE,
    BSSMAGIC_PG_PORT,
    BSSMAGIC_PG_USER,
    bssmagic_statefulset_pod,
    k8s_namespace,
)


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sys.stdout.write(f"[{ts}] {msg}\n")
    sys.stdout.flush()


def _run(cmd, check: bool = True, capture: bool = True, input_bytes: Optional[bytes] = None):
    return subprocess.run(
        cmd, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        input=input_bytes,
    )


def _ensure_kubectl() -> None:
    if not shutil.which("kubectl"):
        raise RuntimeError("kubectl not in PATH")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(session, capability: str, env: str, output_dir: Path) -> Dict[str, Any]:
    _ensure_kubectl()
    namespace = k8s_namespace(capability, env)
    pod = bssmagic_statefulset_pod(capability, env)
    dest = output_dir / "postgres"
    dest.mkdir(parents=True, exist_ok=True)
    out_file = dest / "bssmagic.dump"

    _log(f"  Postgres pod={namespace}/{pod} db={BSSMAGIC_PG_DATABASE}")

    # Check pod is reachable and in Running phase
    r = _run(
        ["kubectl", "-n", namespace, "get", "pod", pod, "-o", "jsonpath={.status.phase}"],
        check=False,
    )
    phase = r.stdout.decode(errors="replace").strip() if r.stdout else ""
    if r.returncode != 0 or phase != "Running":
        _log(f"  Postgres SKIP: pod {pod} phase={phase or 'not-found'}")
        return {"pod": pod, "skipped": True, "reason": phase or "not-found"}

    # Stream pg_dump output to local file via kubectl exec
    cmd = [
        "kubectl", "-n", namespace, "exec", pod, "--",
        "pg_dump",
        "-h", "127.0.0.1",
        "-p", str(BSSMAGIC_PG_PORT),
        "-U", BSSMAGIC_PG_USER,
        "-d", BSSMAGIC_PG_DATABASE,
        "-Fc",            # custom (compressed binary) format
        "--no-owner",     # makes restore portable across users
        "--no-privileges",
    ]
    _log(f"    Running pg_dump...")
    with out_file.open("wb") as fh:
        try:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.PIPE)
            _, stderr = proc.communicate(timeout=3600)  # 1h ceiling
        except subprocess.TimeoutExpired:
            proc.kill()
            _log("  Postgres ERROR: pg_dump timeout (1h)")
            return {"pod": pod, "skipped": True, "reason": "timeout"}

    if proc.returncode != 0:
        err = stderr.decode(errors="replace") if stderr else ""
        _log(f"  Postgres ERROR: pg_dump exit {proc.returncode}: {err[:200]}")
        return {"pod": pod, "skipped": True, "reason": f"pg_dump-exit-{proc.returncode}"}

    size = out_file.stat().st_size
    _log(f"  Postgres done: {size:,} bytes -> postgres/bssmagic.dump")
    return {"pod": pod, "dump_bytes": size, "database": BSSMAGIC_PG_DATABASE}


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore(
    session,
    target_capability: str,
    target_env: str,
    target_account_id: str,
    local_dir: Path,
    source_capability: Optional[str] = None,
    source_env: Optional[str] = None,
    source_account_id: Optional[str] = None,
    target_namespace: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    _ensure_kubectl()
    dump_file = local_dir / "postgres" / "bssmagic.dump"
    if not dump_file.exists():
        _log("  Postgres SKIP: not in backup")
        return {"skipped": True}

    namespace = target_namespace or k8s_namespace(target_capability, target_env)
    pod = bssmagic_statefulset_pod(target_capability, target_env)
    _log(f"  Postgres restoring to {namespace}/{pod}  ({dump_file.stat().st_size:,} bytes)")

    if dry_run:
        _log("    DRY: would pg_restore --clean --if-exists into bssmagic")
        return {"target_pod": pod, "dry_run": True}

    # Stream the local dump into pg_restore via kubectl exec stdin
    cmd = [
        "kubectl", "-n", namespace, "exec", "-i", pod, "--",
        "pg_restore",
        "-h", "127.0.0.1",
        "-p", str(BSSMAGIC_PG_PORT),
        "-U", BSSMAGIC_PG_USER,
        "-d", BSSMAGIC_PG_DATABASE,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
    ]
    _log(f"    Running pg_restore...")
    with dump_file.open("rb") as fh:
        proc = subprocess.Popen(cmd, stdin=fh, stderr=subprocess.PIPE)
        _, stderr = proc.communicate(timeout=3600)

    if proc.returncode != 0:
        err = stderr.decode(errors="replace") if stderr else ""
        _log(f"  Postgres ERROR: pg_restore exit {proc.returncode}: {err[:300]}")
        return {"target_pod": pod, "skipped": True, "reason": f"pg_restore-exit-{proc.returncode}"}

    _log(f"  Postgres done: restored into {namespace}/{pod}")
    return {"target_pod": pod, "target_namespace": namespace}
