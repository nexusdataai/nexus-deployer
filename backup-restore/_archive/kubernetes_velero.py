"""
Kubernetes (via Velero) backup/restore module.

Backup:  triggers a Velero backup of the {capability}-{env} namespace, waits
         for it to complete, then downloads the resulting backup tarball +
         metadata + logs into kubernetes/ inside the DR tarball. Also
         captures the NexusCapability CR spec so the target operator has
         something to apply BEFORE Velero restore runs.

Restore: uploads the backed-up Velero tarball into the TARGET cluster's
         Velero S3 bucket (the operator/admin must have already installed
         Velero on the target — see deploy/eks/USAGE.md), then triggers
         a Velero restore with --namespace-mappings to rename
         {src-cap}-{src-env} -> {tgt-cap}-{tgt-env}. PVCs are restored from
         the kopia/restic snapshots in the Velero bucket.

Requirements on operator workstation:
  - kubectl pointed at the source cluster (backup) or target cluster (restore)
  - velero CLI v1.14+ in $PATH
  - boto3 (for S3 cross-account transfer of the backup files)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from config import k8s_namespace, nexus_capability_name


VELERO_NS = "velero"
WAIT_TIMEOUT_S = 1800   # 30 min upper bound for backup/restore phases
POLL_INTERVAL_S = 10


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sys.stdout.write(f"[{ts}] {msg}\n")
    sys.stdout.flush()


def _run(cmd: List[str], check: bool = True, capture: bool = True,
         input_text: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a shell command; return CompletedProcess."""
    return subprocess.run(
        cmd, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True, input=input_text,
    )


def _ensure_tool(name: str) -> None:
    if not shutil.which(name):
        raise RuntimeError(
            f"{name} not found in PATH. Install it first (see deploy/eks/USAGE.md)."
        )


def _wait_for_phase(
    resource: str, name: str, target_phases: List[str],
    fail_phases: List[str], timeout_s: int = WAIT_TIMEOUT_S,
) -> str:
    """Poll `velero <resource> describe <name>` until phase matches."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            out = _run(
                ["kubectl", "-n", VELERO_NS, "get", resource, name,
                 "-o", "jsonpath={.status.phase}"]
            ).stdout.strip()
        except subprocess.CalledProcessError:
            out = ""
        if out in target_phases:
            return out
        if out in fail_phases:
            return out
        _log(f"    velero {resource}/{name}: phase={out or 'Pending'} (elapsed {int(time.monotonic()-start)}s)")
        time.sleep(POLL_INTERVAL_S)
    return "Timeout"


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(
    session,
    capability: str,
    env: str,
    output_dir: Path,
    backup_name: Optional[str] = None,
    velero_bucket: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a velero backup of the capability namespace and embed it locally."""
    _ensure_tool("velero")
    _ensure_tool("kubectl")

    namespace = k8s_namespace(capability, env)
    cr_name = nexus_capability_name(capability, env)
    backup_name = backup_name or f"{namespace}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    dest = output_dir / "kubernetes"
    dest.mkdir(parents=True, exist_ok=True)

    _log(f"  K8s namespace={namespace}  velero backup={backup_name}")

    # --- Capture the NexusCapability CR ahead of the Velero run so the
    # target operator can rehydrate the operator-provisioned AWS resources
    # before Velero restore touches anything.
    try:
        cr_yaml = _run(
            ["kubectl", "get", "nexuscapability", cr_name,
             "-n", namespace, "-o", "yaml"]
        ).stdout
        (dest / "nexuscapability.yaml").write_text(cr_yaml)
        _log(f"    Captured NexusCapability CR ({cr_name})")
    except subprocess.CalledProcessError as e:
        _log(f"    WARN: cannot get NexusCapability {cr_name}: {e.stderr or e}")

    # --- Trigger Velero backup
    cmd = [
        "velero", "backup", "create", backup_name,
        "--include-namespaces", namespace,
        "--include-cluster-resources=false",
        "--default-volumes-to-fs-backup",
    ]
    _log(f"    Running: {' '.join(cmd)}")
    _run(cmd)

    # --- Wait for completion
    phase = _wait_for_phase(
        "backup", backup_name,
        target_phases=["Completed"],
        fail_phases=["Failed", "PartiallyFailed", "FailedValidation"],
    )
    if phase != "Completed":
        _log(f"    Velero backup {backup_name} ended with phase={phase}")
        # Capture describe output for debugging
        describe = _run(["velero", "backup", "describe", backup_name,
                         "--details"], check=False).stdout
        (dest / f"{backup_name}-describe.txt").write_text(describe or "")
        return {"backup_name": backup_name, "phase": phase, "skipped": True}

    # --- Download the backup tarball + metadata
    download_dir = dest / "download"
    download_dir.mkdir(exist_ok=True)
    _log(f"    Downloading velero backup files to {download_dir}")
    _run(
        ["velero", "backup", "download", backup_name,
         "--output", str(download_dir / f"{backup_name}.tar.gz")]
    )

    # Velero stores files in S3 at <bucket>/backups/<name>/ — also pull the
    # raw metadata files so we can re-upload them on restore.
    if velero_bucket:
        s3 = session.client("s3")
        s3_prefix = f"backups/{backup_name}/"
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=velero_bucket, Prefix=s3_prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    rel = key[len(s3_prefix):]
                    if not rel:
                        continue
                    local = download_dir / rel
                    local.parent.mkdir(parents=True, exist_ok=True)
                    s3.download_file(velero_bucket, key, str(local))
            # Also grab restic/kopia data
            data_prefix = f"kopia/{namespace}/" if True else f"restic/{namespace}/"
            for prefix in (f"kopia/{namespace}/", f"restic/{namespace}/"):
                try:
                    for page in paginator.paginate(Bucket=velero_bucket, Prefix=prefix):
                        for obj in page.get("Contents", []):
                            key = obj["Key"]
                            local = download_dir / "volume-data" / key
                            local.parent.mkdir(parents=True, exist_ok=True)
                            s3.download_file(velero_bucket, key, str(local))
                except ClientError:
                    pass
        except ClientError as e:
            _log(f"    WARN: could not list velero S3 prefix: {e}")

    _log(f"  K8s/Velero done: backup={backup_name}, phase={phase}")
    return {
        "backup_name": backup_name,
        "phase": phase,
        "namespace": namespace,
        "velero_bucket": velero_bucket,
    }


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
    target_velero_bucket: Optional[str] = None,
    target_namespace: Optional[str] = None,
    restore_volumes: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Upload the backed-up Velero artifacts to the target bucket and trigger restore."""
    _ensure_tool("velero")
    _ensure_tool("kubectl")

    src_dir = local_dir / "kubernetes"
    if not src_dir.exists():
        _log("  K8s/Velero SKIP: not in backup")
        return {"skipped": True}

    # Find the embedded velero backup
    download_dir = src_dir / "download"
    if not download_dir.exists():
        _log("  K8s/Velero SKIP: no velero download bundle")
        return {"skipped": True}

    # Velero metadata files include velero-backup.json
    meta_files = list(download_dir.glob("velero-backup.json"))
    if not meta_files:
        # Fall back to scanning subdirectories
        meta_files = list(download_dir.rglob("velero-backup.json"))

    if not meta_files:
        _log("  K8s/Velero SKIP: velero-backup.json not found in download")
        return {"skipped": True}

    meta = json.loads(meta_files[0].read_text())
    backup_name = meta.get("metadata", {}).get("name") or meta.get("name", "")
    if not backup_name:
        _log("  K8s/Velero SKIP: backup name missing from metadata")
        return {"skipped": True}

    source_ns = meta.get("spec", {}).get("includedNamespaces", [None])[0]
    if not source_ns:
        source_ns = k8s_namespace(source_capability or "nexus-ai", source_env or "dev")
    target_ns = target_namespace or k8s_namespace(target_capability, target_env)

    _log(f"  K8s/Velero {source_ns} -> {target_ns}  (backup={backup_name})")

    if dry_run:
        _log(f"    DRY: would upload {download_dir} to s3://{target_velero_bucket}/backups/{backup_name}/")
        _log(f"    DRY: velero restore create --from-backup {backup_name} "
             f"--namespace-mappings {source_ns}:{target_ns}")
        return {"backup_name": backup_name, "dry_run": True}

    if not target_velero_bucket:
        _log("  K8s/Velero ERROR: --target-velero-bucket required for restore")
        return {"skipped": True, "error": "missing-velero-bucket"}

    # --- Upload backup artifacts into target velero bucket
    s3 = session.client("s3")
    _log(f"    Uploading velero artifacts to s3://{target_velero_bucket}/backups/{backup_name}/")

    uploaded = 0
    for p in download_dir.rglob("*"):
        if not p.is_file():
            continue
        # The volume-data/ subdir was placed by backup() to mirror kopia/<ns>/...
        # Strip volume-data/ to put files at their original prefix.
        rel = p.relative_to(download_dir)
        if str(rel).startswith("volume-data/"):
            key = str(rel.relative_to("volume-data"))
        else:
            key = f"backups/{backup_name}/{rel}"
        s3.upload_file(str(p), target_velero_bucket, key)
        uploaded += 1
    _log(f"    Uploaded {uploaded} velero artifact file(s)")

    # --- Sync velero BackupStorageLocation on the cluster
    _log("    velero backup-location get / sync")
    _run(["velero", "backup-location", "get"], check=False)
    # The Velero controller polls the bucket every 1 min by default; force a
    # sync now so the new backup is visible immediately.
    try:
        _run(["velero", "backup", "get", backup_name], check=False)
        # If the backup is not yet visible, wait for sync
        for _ in range(12):  # 2 min max
            r = _run(["kubectl", "-n", VELERO_NS, "get", "backup",
                      backup_name, "-o", "name"], check=False)
            if r.returncode == 0 and r.stdout.strip():
                break
            time.sleep(10)
    except Exception:
        pass

    # --- Trigger velero restore
    restore_name = f"{backup_name}-restore-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    cmd = [
        "velero", "restore", "create", restore_name,
        "--from-backup", backup_name,
        "--namespace-mappings", f"{source_ns}:{target_ns}",
    ]
    if restore_volumes:
        cmd.append("--restore-volumes")
    _log(f"    Running: {' '.join(cmd)}")
    _run(cmd)

    phase = _wait_for_phase(
        "restore", restore_name,
        target_phases=["Completed"],
        fail_phases=["Failed", "PartiallyFailed", "FailedValidation"],
    )
    _log(f"  K8s/Velero done: restore={restore_name} phase={phase}")

    # Save a describe for the operator log
    describe = _run(["velero", "restore", "describe", restore_name,
                     "--details"], check=False).stdout
    audit = local_dir / "kubernetes" / f"{restore_name}-describe.txt"
    audit.write_text(describe or "")

    return {
        "backup_name": backup_name,
        "restore_name": restore_name,
        "phase": phase,
        "target_namespace": target_ns,
    }


# ---------------------------------------------------------------------------
# Helper: re-apply NexusCapability CR with env rewrite (called by orchestrator
# BEFORE velero restore so operator pre-creates the AWS resources)
# ---------------------------------------------------------------------------

def apply_capability_cr(
    local_dir: Path,
    target_capability: str,
    target_env: str,
    target_namespace: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Edit the captured NexusCapability CR and apply it to the current kube context."""
    cr_file = local_dir / "kubernetes" / "nexuscapability.yaml"
    if not cr_file.exists():
        _log("  NexusCapability CR not in backup, skipping")
        return {"skipped": True}

    try:
        import yaml
    except ImportError:
        _log("  WARN: PyYAML not installed; cannot patch CR. Apply manually after restore.")
        return {"skipped": True, "error": "no-yaml"}

    docs = list(yaml.safe_load_all(cr_file.read_text()))
    new_docs = []
    for doc in docs:
        if not doc:
            continue
        if doc.get("kind") == "NexusCapability":
            # Strip status + server-side fields
            md = doc.setdefault("metadata", {})
            for f in ("uid", "resourceVersion", "creationTimestamp",
                      "generation", "managedFields", "finalizers"):
                md.pop(f, None)
            doc.pop("status", None)

            md["name"] = nexus_capability_name(target_capability, target_env)
            md["namespace"] = target_namespace or k8s_namespace(target_capability, target_env)
            spec = doc.setdefault("spec", {})
            spec["capabilityName"] = target_capability
            spec["environment"] = target_env
        new_docs.append(doc)

    patched_yaml = yaml.safe_dump_all(new_docs)

    if dry_run:
        _log("    DRY: would kubectl apply patched NexusCapability:")
        _log("    " + patched_yaml.replace("\n", "\n    "))
        return {"dry_run": True}

    # Ensure the target namespace exists
    ns = target_namespace or k8s_namespace(target_capability, target_env)
    _run(["kubectl", "create", "namespace", ns], check=False)

    _log(f"    kubectl apply NexusCapability  -> {ns}/{nexus_capability_name(target_capability, target_env)}")
    _run(["kubectl", "apply", "-f", "-"], input_text=patched_yaml)
    return {"applied": True}
