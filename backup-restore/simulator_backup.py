#!/usr/bin/env python3
"""
Nexus Simulator Data Backup & Restore  (Stage 1 of the DR rewrite)

Single-purpose CLI for backing up and restoring the seven simulator S3
buckets that back the FDW source data in a Nexus installation:

    sfdc-simulator, oracle-erp-simulator, sap-simulator,
    wxcc-simulator, external-sources, tpm-simulator,
    sourcing-simulator

The output is one .tar.gz containing a manifest.json plus per-bucket
sub-directories that mirror the original S3 key layout. Restore uploads
into operator-provisioned target buckets, resolving bucket names per
target capability/env/account at runtime.

Scope: simulator S3 data only. Business entities (mapping rules,
connectors, workflows, solutions, etc.) live in DynamoDB and are not
handled here — they will be the Stage 2 deliverable. Infrastructure
(SSM, Secrets, Glue, Cognito, Velero, Postgres) is the operator's
responsibility and is intentionally out of scope for this tool.

Usage:

    # Backup
    python3 simulator_backup.py backup \\
        --capability nexus-ai --env prod \\
        --profile promode2 \\
        -o sim-backup-prod-$(date +%Y%m%d).tar.gz

    # Restore (dry-run first, always)
    python3 simulator_backup.py restore \\
        -i sim-backup-prod-20260615.tar.gz \\
        --target-capability nexus-ai --target-env test \\
        --target-profile new-account \\
        --dry-run
    # Re-run without --dry-run to apply.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

CAPABILITY_DEFAULT = "nexus-ai"
MANIFEST_SCHEMA_VERSION = "stage1.simulator.v1"

# Simulator inventory. `name` is the logical identifier that appears
# inside the tarball (and in the manifest); `suffix` is the capability-
# relative bucket-name suffix the operator uses when it provisions the
# real S3 bucket — see kube-operator/src/nexus_operator/resources/s3.py
# (BUCKET_PURPOSES) for the authoritative provisioning list.
#
# The 8 UI-visible data sources map onto 5 actual S3 buckets here, plus
# 2 synthetic simulators that never have S3 data:
#
#   Category 1 — S3-backed (real exported data, must be backed up):
#     sfdc-simulator, oracle-erp-simulator, sap-simulator, wxcc-simulator
#
#   Category 2 — S3-backed but typically lightweight (user uploads,
#                drive/social ingestion). One bucket serves three UI
#                source kinds (file_uploads / google_drive /
#                social_listening) all writing into the same
#                external-simulator bucket under different prefixes:
#     external-sources  (bucket suffix = external-simulator)
#
#   Category 3 — Redis-only synthetic (NEVER provisioned in S3; data is
#                regenerated deterministically from random.seed(42) on
#                every pod boot — see tpm_simulator_service.py and
#                sourcing_simulator_service.py). Listed here so the
#                manifest enumerates all known simulators, but they will
#                always show "not provisioned, skipping" at backup time:
#     tpm-simulator, sourcing-simulator
SIMULATORS: List[Dict[str, str]] = [
    {"name": "sfdc-simulator",       "suffix": "sfdc-simulator"},
    {"name": "oracle-erp-simulator", "suffix": "oracle-erp-simulator"},
    {"name": "sap-simulator",        "suffix": "sap-simulator"},
    {"name": "wxcc-simulator",       "suffix": "wxcc-simulator"},
    {"name": "external-sources",     "suffix": "external-simulator"},
    {"name": "tpm-simulator",        "suffix": "tpm-simulator"},        # always synthetic/Redis-only
    {"name": "sourcing-simulator",   "suffix": "sourcing-simulator"},   # always synthetic/Redis-only
]

# After a `restore`, the simulator services need an explicit Redis hydration
# from the freshly populated S3 buckets — the in-memory _loaded flag on each
# service is sticky and won't auto re-check S3 once it's been initialized.
# The `hydrate` subcommand POSTs to these admin endpoints via `kubectl exec`
# to fire that hydration on a target cluster.
#
# Mount points correspond to nexus-backend/mcp_http_gateway.py:1891-1923.
# Only the simulators whose data was actually backed up appear here:
#   - wxcc-simulator has no /load endpoint (legacy concept)
#   - tpm-simulator and sourcing-simulator are synthetic-Redis-only and have
#     no S3 data to hydrate from
HYDRATE_ENDPOINTS: Dict[str, str] = {
    "sfdc-simulator":       "sfdc-simulator",
    "oracle-erp-simulator": "oracle-erp-simulator",
    "sap-simulator":        "sap-simulator",
    "external-sources":     "external-simulator",
}


# ----------------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------------

@dataclass
class SimulatorEntry:
    name: str                 # logical simulator name (key under s3/ in the tarball)
    bucket: Optional[str]     # actual S3 bucket name at backup time; None if not provisioned
    key_count: int
    bytes: int


@dataclass
class Manifest:
    schema_version: str
    created_at: str
    source_capability: str
    source_env: str
    source_account_id: str
    source_region: str
    simulators: List[Dict[str, Any]] = field(default_factory=list)


# ----------------------------------------------------------------------------
# AWS helpers
# ----------------------------------------------------------------------------

def make_session(profile: Optional[str], region: Optional[str]) -> boto3.Session:
    kwargs: Dict[str, Any] = {}
    if profile:
        kwargs["profile_name"] = profile
    if region:
        kwargs["region_name"] = region
    return boto3.Session(**kwargs)


def resolve_bucket_name(
    s3,
    capability: str,
    env: str,
    suffix: str,
    account_id: str,
) -> Optional[str]:
    """
    Probe `{cap}-{env}-{suffix}-{account_id}` then `{cap}-{env}-{suffix}` and
    return the first that exists. Returns None when neither exists (the
    simulator is not provisioned on this installation — caller should skip).

    Distinguishes 404 (bucket genuinely missing, try next candidate) from
    other errors (403 forbidden, region mismatch, network) which are
    propagated so misconfiguration doesn't silently masquerade as "absent".
    """
    candidates = [
        f"{capability}-{env}-{suffix}-{account_id}",
        f"{capability}-{env}-{suffix}",
    ]
    for b in candidates:
        try:
            s3.head_bucket(Bucket=b)
            return b
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("404", "NoSuchBucket", "NotFound") or status == 404:
                continue
            raise
    return None


def list_all_keys(s3, bucket: str) -> List[Dict[str, Any]]:
    """ListObjectsV2 with full pagination."""
    out: List[Dict[str, Any]] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []) or []:
            out.append({"key": obj["Key"], "size": obj["Size"]})
    return out


def download_keys_parallel(
    s3, bucket: str, keys: List[Dict[str, Any]],
    target_dir: Path, max_workers: int,
) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)

    def _dl(o: Dict[str, Any]) -> None:
        rel = o["key"].lstrip("/")
        local = target_dir / rel
        local.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, o["key"], str(local))

    if not keys:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_dl, o) for o in keys]
        for f in as_completed(futures):
            f.result()


def list_keys_under_prefix(s3, bucket: str, prefix: str) -> List[str]:
    """ListObjectsV2 across all keys under `prefix/`, fully paginated.

    Used by `clean_target_prefix` to enumerate what needs to be deleted
    before a fresh restore.
    """
    out: List[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    norm = prefix.rstrip("/") + "/" if prefix else ""
    for page in paginator.paginate(Bucket=bucket, Prefix=norm):
        for obj in page.get("Contents", []) or []:
            out.append(obj["Key"])
    return out


def clean_target_prefix(
    s3, bucket: str, prefix: str, max_workers: int, dry_run: bool,
) -> int:
    """
    Delete every key under `prefix/` in `bucket`. Idempotent. Returns
    the count of keys deleted (or that would be deleted under dry-run).

    Used before a restore upload so stale legacy artifacts (from a
    prior tenant, a partial earlier restore, etc.) cannot survive
    alongside the new dump. A previous prod cluster had a 1661-table
    `starhub_itxp2dev` dump that survived a restore of a 245-table
    `sfdc_itxp2dev` dev backup; the simulator pods loaded the old
    `tables.json` and never saw the new data.
    """
    keys = list_keys_under_prefix(s3, bucket, prefix)
    if not keys:
        return 0
    if dry_run:
        return len(keys)
    # boto3 DeleteObjects supports up to 1000 keys per call.
    deleted = 0
    chunks = [keys[i:i + 1000] for i in range(0, len(keys), 1000)]

    def _del(chunk: List[str]) -> int:
        resp = s3.delete_objects(
            Bucket=bucket,
            Delete={
                "Objects": [{"Key": k} for k in chunk],
                "Quiet": True,
            },
        )
        errors = resp.get("Errors") or []
        if errors:
            # Best-effort: log via raise so caller sees the first failure.
            raise RuntimeError(
                f"delete_objects on {bucket!r} returned {len(errors)} errors; "
                f"first: {errors[0]}"
            )
        return len(chunk)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_del, c) for c in chunks]
        for f in as_completed(futures):
            deleted += f.result()
    return deleted


def upload_dir_parallel(
    s3, bucket: str, source_dir: Path, max_workers: int, dry_run: bool,
) -> int:
    """
    Upload every regular file under source_dir into the bucket, preserving
    the relative path as the S3 key. Returns the count of keys uploaded
    (or that would be uploaded under --dry-run).
    """
    files = [p for p in source_dir.rglob("*") if p.is_file()]
    if not files:
        return 0

    def _up(p: Path) -> None:
        if dry_run:
            return
        key = p.relative_to(source_dir).as_posix()
        s3.upload_file(str(p), bucket, key)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_up, p) for p in files]
        for f in as_completed(futures):
            f.result()
    return len(files)




# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------

def cmd_backup(args: argparse.Namespace) -> int:
    session = make_session(args.profile, args.region)
    s3 = session.client("s3")
    sts = session.client("sts")

    account_id = sts.get_caller_identity()["Account"]
    region = args.region or session.region_name or "us-east-1"

    out = Path(args.output).resolve()
    if out.exists() and not args.force:
        raise SystemExit(f"  ERROR: {out} already exists. Use --force to overwrite.")

    print(f"  capability: {args.capability}")
    print(f"  env:        {args.env}")
    print(f"  account:    {account_id}")
    print(f"  region:     {region}")
    print(f"  output:     {out}")
    print()

    with tempfile.TemporaryDirectory(prefix="nexus-sim-backup-") as tmp:
        tmp_path = Path(tmp)
        stage = tmp_path / out.stem.replace(".tar", "")
        stage.mkdir()

        entries: List[SimulatorEntry] = []
        total_keys = 0
        total_bytes = 0

        for sim in SIMULATORS:
            bucket = resolve_bucket_name(s3, args.capability, args.env, sim["suffix"], account_id)
            if bucket is None:
                # Simulator not provisioned on this installation (e.g. tpm,
                # sourcing, external-sources commonly absent on dev clusters).
                # Record an empty entry so the manifest still enumerates all
                # known simulators and restore is symmetric.
                print(f"  -- {sim['name']:24s}  not provisioned (no bucket), skipping")
                entries.append(SimulatorEntry(
                    name=sim["name"], bucket=None, key_count=0, bytes=0,
                ))
                continue

            keys = list_all_keys(s3, bucket)
            size = sum(k["size"] for k in keys)
            print(f"  -> {sim['name']:24s}  bucket={bucket}  keys={len(keys):>5d}  bytes={size:>14,d}")

            if keys:
                sim_dir = stage / "s3" / sim["name"]
                download_keys_parallel(s3, bucket, keys, sim_dir, args.max_workers)

            entries.append(SimulatorEntry(
                name=sim["name"],
                bucket=bucket,
                key_count=len(keys),
                bytes=size,
            ))
            total_keys += len(keys)
            total_bytes += size

        manifest = Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
            source_capability=args.capability,
            source_env=args.env,
            source_account_id=account_id,
            source_region=region,
            simulators=[asdict(e) for e in entries],
        )
        (stage / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2))

        # Pack
        print()
        print(f"  Packing {total_keys:,} keys ({total_bytes:,} bytes) into {out.name} ...")
        with tarfile.open(out, "w:gz") as tar:
            tar.add(stage, arcname=stage.name)

    print(f"  OK: {out}  ({out.stat().st_size:,} bytes)")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    session = make_session(args.target_profile, args.region)
    s3 = session.client("s3")
    sts = session.client("sts")

    target_account_id = sts.get_caller_identity()["Account"]
    region = args.region or session.region_name or "us-east-1"

    inp = Path(args.input).resolve()
    if not inp.exists():
        raise SystemExit(f"  ERROR: input file {inp} does not exist.")

    with tempfile.TemporaryDirectory(prefix="nexus-sim-restore-") as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(inp, "r:gz") as tar:
            tar.extractall(tmp_path)

        inner_dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        if len(inner_dirs) != 1:
            raise SystemExit(
                f"  ERROR: expected one top-level directory in {inp.name}, found {len(inner_dirs)}."
            )
        root = inner_dirs[0]
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit(f"  ERROR: manifest.json missing from {inp.name}.")
        manifest = json.loads(manifest_path.read_text())

        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise SystemExit(
                f"  ERROR: manifest schema_version={manifest.get('schema_version')!r} "
                f"is not supported by this tool (expected {MANIFEST_SCHEMA_VERSION!r})."
            )

        target_capability = args.target_capability or manifest["source_capability"]
        target_env = args.target_env or manifest["source_env"]

        clean_enabled = not args.no_clean
        hydrate_enabled = not args.no_hydrate

        print(f"  source: {manifest['source_capability']}/{manifest['source_env']} "
              f"on account {manifest['source_account_id']}")
        print(f"  target: {target_capability}/{target_env} on account {target_account_id} ({region})")
        print(f"  mode:   {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
        print(f"  clean target prefix before upload: {clean_enabled}")
        print(f"  hydrate target simulators after:   {hydrate_enabled}")
        print()

        suffix_by_name = {s["name"]: s["suffix"] for s in SIMULATORS}

        total_keys = 0
        total_deleted = 0
        for sim_meta in manifest.get("simulators", []):
            name = sim_meta["name"]
            suffix = suffix_by_name.get(name)
            if not suffix:
                print(f"  WARN: unknown simulator {name!r} in manifest, skipping.")
                continue

            sim_dir = root / "s3" / name
            if not sim_dir.exists():
                # Backup had no data for this simulator (either not provisioned
                # at source time or the source bucket was empty). Whether or
                # not a target bucket exists is irrelevant — nothing to upload.
                print(f"  -- {name:24s} (empty in backup, skipped)")
                continue

            target_bucket = resolve_bucket_name(
                s3, target_capability, target_env, suffix, target_account_id,
            )
            if target_bucket is None:
                raise SystemExit(
                    f"  ERROR: target bucket for simulator {name!r} (suffix={suffix}) "
                    f"does not exist on {target_capability}/{target_env}@{target_account_id}. "
                    f"Operator must provision it before restore."
                )

            # 1. Clean stale legacy keys under the simulator's prefix so the
            #    target bucket can't end up with two overlapping dumps.
            #    The simulator's S3 prefix is the simulator's logical name
            #    (e.g. `sfdc-simulator/`) per BaseSimulatorService.
            target_prefix = name
            if clean_enabled:
                deleted = clean_target_prefix(
                    s3, target_bucket, target_prefix, args.max_workers, args.dry_run,
                )
                total_deleted += deleted
                if deleted:
                    tag = "  [dry-run]" if args.dry_run else ""
                    print(f"  -- {name:24s}  cleaned {target_bucket}/{target_prefix}/  "
                          f"deleted={deleted}{tag}")

            # 2. Upload the fresh dump.
            n = upload_dir_parallel(s3, target_bucket, sim_dir, args.max_workers, args.dry_run)
            tag = "  [dry-run]" if args.dry_run else ""
            print(f"  -> {name:24s}  -> {target_bucket}  uploaded={n}{tag}")
            total_keys += n

        print()
        verb = "would" if args.dry_run else ""
        if clean_enabled:
            print(f"  OK: {verb + ' delete' if args.dry_run else 'deleted'} "
                  f"{total_deleted:,} stale keys.")
        print(f"  OK: {verb + ' upload' if args.dry_run else 'uploaded'} "
              f"{total_keys:,} keys total.")

        # 3. Hydrate the target simulators so the backend pods reload
        #    Redis from the freshly-restored S3 data. Without this step,
        #    pods that were running before the restore keep their stale
        #    in-memory catalogue and ignore the new S3 state until they
        #    are restarted — the exact failure mode that motivated this
        #    auto-hydrate behaviour.
        if hydrate_enabled and not args.dry_run and total_keys > 0:
            print()
            print(f"  Hydrating target simulators via kubectl exec ...")
            if shutil.which("kubectl") is None:
                print(f"  WARN: kubectl not found on PATH; skipping hydrate.")
                print(f"        Run manually once kubectl is configured:")
                print(f"          python3 simulator_backup.py hydrate "
                      f"--capability {target_capability} --env {target_env}")
            else:
                try:
                    _hydrate_inline(
                        target_capability, target_env,
                        timeout_per_sim=args.hydrate_timeout,
                    )
                except SystemExit as e:
                    # Surface the hydrate failure without propagating
                    # exit so the restore-upload success isn't lost.
                    print(f"  WARN: hydrate step reported failure: {e}")
                    print(f"        S3 upload succeeded; re-run hydrate manually.")
        elif hydrate_enabled and args.dry_run and total_keys > 0:
            print()
            print(f"  [dry-run] would hydrate simulators on "
                  f"{target_capability}/{target_env} via kubectl exec.")

    return 0


def _hydrate_inline(
    target_capability: str, target_env: str, timeout_per_sim: int = 300,
) -> None:
    """
    Inline equivalent of `simulator_backup.py hydrate ...`. Factored out
    so `cmd_restore` can call it without forking a child process or
    re-parsing argv.
    """
    namespace = f"{target_capability}-{target_env}"
    label_selector = f"app={target_capability}-{target_env}-backend"

    pod = _find_backend_pod(namespace, label_selector)
    if not pod:
        raise SystemExit(
            f"  ERROR: no Running pod found in namespace {namespace!r} "
            f"matching {label_selector!r}."
        )
    print(f"    pod: {pod}")

    failed: List[str] = []
    for name, api_path in HYDRATE_ENDPOINTS.items():
        print(f"    -> {name:24s} POST /api/v1/{api_path}/load", flush=True)
        rc, out = _exec_curl(
            namespace, pod,
            f"http://localhost:8000/api/v1/{api_path}/load",
            method="POST",
        )
        if rc != 0:
            print(f"       FAILED rc={rc} body={out[:200]!r}")
            failed.append(name)
            continue
        ok, status = _wait_for_load(namespace, pod, api_path, timeout_per_sim)
        if not ok:
            failed.append(name)
            print(f"       did NOT complete within {timeout_per_sim}s")
        else:
            rows = status.get("total_rows") or (status.get("result") or {}).get("total_rows")
            tables = status.get("tables_with_data") or (status.get("result") or {}).get("tables_with_data")
            extras = []
            if tables is not None: extras.append(f"tables_with_data={tables}")
            if rows is not None:   extras.append(f"total_rows={rows}")
            tail = ("  (" + ", ".join(extras) + ")") if extras else ""
            print(f"       OK{tail}")

    if failed:
        raise SystemExit(
            f"  ERROR: hydration failed for: {', '.join(failed)}. "
            f"S3 upload succeeded; re-run `simulator_backup.py hydrate` later."
        )


# ----------------------------------------------------------------------------
# Hydrate (post-restore Redis warmup via kubectl exec)
# ----------------------------------------------------------------------------

# Indirection so tests can monkeypatch.
def _run_subprocess(cmd: List[str], timeout: int) -> Tuple[int, str, str]:
    """Run a subprocess; return (returncode, stdout, stderr). Empty strings on timeout."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s running: {' '.join(cmd)}"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _find_backend_pod(namespace: str, label_selector: str, timeout: int = 30) -> Optional[str]:
    """
    Return the name of a Running backend pod that matches `label_selector`, or
    None if no such pod exists.
    """
    cmd = [
        "kubectl", "-n", namespace, "get", "pods",
        "-l", label_selector,
        "--field-selector=status.phase=Running",
        "-o", "jsonpath={.items[0].metadata.name}",
    ]
    rc, out, err = _run_subprocess(cmd, timeout)
    if rc != 0 or not out.strip():
        return None
    return out.strip()


def _exec_curl(
    namespace: str, pod: str, url: str, *,
    method: str = "GET", timeout: int = 30,
) -> Tuple[int, str]:
    """
    Run `curl` inside `pod` against `url`. Returns (rc, stdout). stderr from
    kubectl/curl is folded into stdout on failure so the caller has one
    place to look.
    """
    cmd = [
        "kubectl", "-n", namespace, "exec", pod, "--",
        "curl", "-s", "-S",
        "-X", method,
        "-H", "Content-Type: application/json",
        "-w", "\n__HTTP_STATUS=%{http_code}",
        url,
    ]
    rc, out, err = _run_subprocess(cmd, timeout)
    if rc != 0 and err:
        out = (out + "\n" + err).strip()
    return rc, out


def _parse_load_status(stdout: str) -> Dict[str, Any]:
    """Parse the JSON body from a /load/status response wrapped with __HTTP_STATUS."""
    body = stdout.split("\n__HTTP_STATUS=")[0].strip()
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {}


def _wait_for_load(
    namespace: str, pod: str, api_path: str, total_timeout: int,
    poll_interval: float = 2.0,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Poll /api/v1/{api_path}/load/status until it reports running=False or
    total_timeout elapses. Returns (completed_ok, final_status_dict).
    """
    deadline = time.monotonic() + total_timeout
    last: Dict[str, Any] = {}
    url = f"http://localhost:8000/api/v1/{api_path}/load/status"
    while time.monotonic() < deadline:
        rc, out = _exec_curl(namespace, pod, url, method="GET", timeout=15)
        if rc == 0:
            last = _parse_load_status(out) or last
            # The load endpoint families converge on `running=False` once
            # the asyncio task has finished (either successfully or with an
            # error captured in `result`).
            if last and last.get("running") is False:
                ok = bool(last.get("loaded") or (last.get("result") or {}).get("ok"))
                # Some simulators set `loaded=true` only on success; if neither
                # `loaded` nor `result.ok` is present but running=False and no
                # error string, treat as success.
                if not ok and last.get("error"):
                    return False, last
                return True, last
        time.sleep(poll_interval)
    return False, last


    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Compare live S3 key counts on target to tarball manifest."""
    in_path = os.path.abspath(args.input)
    capability = args.target_capability or args.capability
    env = args.target_env or args.env
    if not env:
        print("  ERROR: verify requires --target-env or --env")
        return 2
    profile = args.target_profile or args.profile
    region = args.region or "us-east-1"
    tolerance = args.tolerance

    with tempfile.TemporaryDirectory(prefix="nexus-sim-vf-") as tmp:
        with tarfile.open(in_path, "r:gz") as tar:
            manifest_member = None
            for m in tar.getmembers():
                if m.name.endswith("manifest.json") and m.isfile():
                    manifest_member = m
                    break
            if manifest_member is None:
                print("  ERROR: tarball missing manifest.json")
                return 2
            manifest = json.loads(tar.extractfile(manifest_member).read().decode("utf-8"))

    session = make_session(profile, region)
    s3 = session.client("s3")
    sts = session.client("sts")
    account_id = sts.get_caller_identity()["Account"]

    print(f"  tarball:   {in_path}")
    print(f"  target:    {capability}-{env} (account {account_id})")
    print()

    failed = 0
    warned = 0
    for ent in manifest.get("simulators") or []:
        name = ent.get("name", "")
        expected = int(ent.get("key_count") or 0)
        sim = next((s for s in SIMULATORS if s["name"] == name), None)
        if not sim:
            continue
        bucket = resolve_bucket_name(s3, capability, env, sim["suffix"], account_id)
        if bucket is None:
            if expected == 0:
                print(f"  OK    {name:24s} not provisioned (expected 0 keys)")
            else:
                print(f"  FAIL  {name:24s} bucket missing (expected {expected} keys)")
                failed += 1
            continue
        keys = list_all_keys(s3, bucket)
        actual = len(keys)
        if expected == 0:
            print(f"  OK    {name:24s} keys={actual} (source empty)")
            continue
        min_ok = int(expected * (1.0 - tolerance))
        if actual >= min_ok:
            print(f"  OK    {name:24s} keys={actual}  expected>={min_ok} (~{expected})")
        elif actual >= min_ok * 0.5:
            print(f"  WARN  {name:24s} keys={actual}  expected>={min_ok}")
            warned += 1
        else:
            print(f"  FAIL  {name:24s} keys={actual}  expected>={min_ok}")
            failed += 1

    if args.namespace and args.deployment:
        print()
        print("  Simulator API status (kubectl):")
        namespace = args.namespace
        deployment = args.deployment
        for name, api_path in HYDRATE_ENDPOINTS.items():
            pod = _find_backend_pod(namespace, f"app={capability}-{env}-backend")
            if not pod:
                print(f"  WARN  {name:24s} no running backend pod")
                warned += 1
                continue
            rc, out = _exec_curl(
                namespace, pod,
                f"http://localhost:8000/api/v1/{api_path}/status",
            )
            if rc != 0:
                print(f"  WARN  {name:24s} curl failed")
                warned += 1
                continue
            try:
                body = out.split("\n__HTTP_STATUS=")[0].strip()
                status = json.loads(body) if body else {}
            except json.JSONDecodeError:
                status = {}
            loaded = status.get("loaded")
            tables = status.get("tables_with_data") or 0
            if loaded:
                print(f"  OK    {name:24s} loaded=true tables_with_data={tables}")
            else:
                print(f"  WARN  {name:24s} loaded={loaded}")
                warned += 1

    print()
    if failed:
        print(f"  Simulator verify: FAILED ({failed} errors, {warned} warnings)")
        return 1
    print(f"  Simulator verify: PASSED ({warned} warnings)")
    return 0


def cmd_hydrate(args: argparse.Namespace) -> int:
    if shutil.which("kubectl") is None:
        raise SystemExit("  ERROR: kubectl not found on PATH. hydrate requires kubectl access to the target cluster.")

    namespace = args.namespace or f"{args.capability}-{args.env}"
    label_selector = args.label_selector or f"app={args.capability}-{args.env}-backend"
    timeout_per_sim = args.timeout

    print(f"  namespace:      {namespace}")
    print(f"  selector:       {label_selector}")
    print(f"  wait per sim:   {timeout_per_sim}s")
    print()

    pod = _find_backend_pod(namespace, label_selector)
    if not pod:
        raise SystemExit(
            f"  ERROR: no Running pod found in namespace {namespace!r} matching {label_selector!r}. "
            f"Pass --namespace or --label-selector if the defaults don't match this installation."
        )
    print(f"  pod:            {pod}")
    print()

    targets: List[str] = (
        [s.strip() for s in args.simulators.split(",") if s.strip()]
        if args.simulators else list(HYDRATE_ENDPOINTS.keys())
    )

    failed: List[str] = []
    for name in targets:
        api_path = HYDRATE_ENDPOINTS.get(name)
        if not api_path:
            print(f"  -- {name:24s} no /load endpoint (synthetic or legacy), skipping")
            continue

        print(f"  -> {name:24s} POST /api/v1/{api_path}/load", flush=True)
        rc, out = _exec_curl(
            namespace, pod,
            f"http://localhost:8000/api/v1/{api_path}/load",
            method="POST",
        )
        if rc != 0:
            print(f"     FAILED to fire load: rc={rc}  body={out[:200]!r}")
            failed.append(name)
            continue

        if args.no_wait:
            print(f"     fired (not waiting)")
            continue

        ok, status = _wait_for_load(namespace, pod, api_path, timeout_per_sim)
        if not ok:
            failed.append(name)
            print(f"     did NOT complete within {timeout_per_sim}s. last status: {status}")
        else:
            rows = status.get("total_rows") or (status.get("result") or {}).get("total_rows")
            tables = status.get("tables_with_data") or (status.get("result") or {}).get("tables_with_data")
            extras = []
            if tables is not None: extras.append(f"tables_with_data={tables}")
            if rows is not None:   extras.append(f"total_rows={rows}")
            tail = ("  (" + ", ".join(extras) + ")") if extras else ""
            print(f"     OK{tail}")

    print()
    if failed:
        raise SystemExit(f"  ERROR: hydration failed for: {', '.join(failed)}")
    print(f"  OK: hydrated {len([t for t in targets if t in HYDRATE_ENDPOINTS])} simulator(s).")
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="simulator_backup.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    pb = sub.add_parser("backup", help="Back up all simulator S3 buckets to a tarball.")
    pb.add_argument("--capability", default=CAPABILITY_DEFAULT,
                    help=f"Capability name (default: {CAPABILITY_DEFAULT})")
    pb.add_argument("--env", required=True, help="Source environment, e.g. dev, prod")
    pb.add_argument("--profile", default=None, help="AWS named profile (boto3 default if omitted)")
    pb.add_argument("--region", default=None, help="AWS region (boto3 default if omitted)")
    pb.add_argument("--max-workers", type=int, default=16, help="Parallel S3 transfer workers (default 16)")
    pb.add_argument("-o", "--output", required=True, help="Destination .tar.gz path")
    pb.add_argument("--force", action="store_true", help="Overwrite output if it exists")
    pb.set_defaults(func=cmd_backup)

    pr = sub.add_parser("restore", help="Restore simulator buckets from a tarball.")
    pr.add_argument("-i", "--input", required=True, help="Source .tar.gz produced by `backup`")
    pr.add_argument("--target-capability", default=None,
                    help="Target capability (default: same as source)")
    pr.add_argument("--target-env", default=None, help="Target environment (default: same as source)")
    pr.add_argument("--target-profile", default=None, help="AWS named profile for the target account")
    pr.add_argument("--region", default=None, help="AWS region for the target")
    pr.add_argument("--max-workers", type=int, default=16, help="Parallel S3 transfer workers (default 16)")
    pr.add_argument("--dry-run", action="store_true",
                    help="Print what would be uploaded without making any S3 writes")
    pr.add_argument(
        "--no-clean", action="store_true",
        help="Do NOT delete pre-existing keys under each target simulator's "
             "prefix before upload. Default is to clean so stale legacy "
             "artifacts (e.g. from a prior tenant) cannot survive alongside "
             "the new dump.",
    )
    pr.add_argument(
        "--no-hydrate", action="store_true",
        help="Do NOT trigger Redis hydration on the target cluster after the "
             "S3 upload completes. Default is to hydrate so the simulator "
             "pods immediately reflect the new data; use --no-hydrate when "
             "running from an environment without kubectl access to the "
             "target cluster.",
    )
    pr.add_argument(
        "--hydrate-timeout", type=int, default=300,
        help="Per-simulator status-poll timeout for the auto-hydrate step "
             "(default: 300 seconds).",
    )
    pr.set_defaults(func=cmd_restore)

    ph = sub.add_parser(
        "hydrate",
        help="Trigger Redis hydration on the target cluster's simulators (run after `restore`).",
    )
    ph.add_argument("--capability", default=CAPABILITY_DEFAULT,
                    help=f"Capability name used to derive defaults (default: {CAPABILITY_DEFAULT})")
    ph.add_argument("--env", required=True, help="Target environment, e.g. prod, test")
    ph.add_argument("--namespace", default=None,
                    help="K8s namespace (default: {capability}-{env})")
    ph.add_argument("--label-selector", default=None,
                    help="kubectl pod label selector (default: app={capability}-{env}-backend)")
    ph.add_argument("--simulators", default=None,
                    help="Comma-separated subset to hydrate (default: all 4 S3-backed)")
    ph.add_argument("--timeout", type=int, default=300,
                    help="Per-simulator wait timeout in seconds (default: 300)")
    ph.add_argument("--no-wait", action="store_true",
                    help="Fire POST /load and return immediately, do not poll status")
    ph.set_defaults(func=cmd_hydrate)

    pv = sub.add_parser(
        "verify",
        help="Compare target S3 key counts and optional API status to tarball manifest.",
    )
    pv.add_argument("-i", "--input", required=True, help="Source .tar.gz from backup")
    pv.add_argument("--capability", default=CAPABILITY_DEFAULT)
    pv.add_argument("--target-capability", default=None)
    pv.add_argument("--target-env", default=None)
    pv.add_argument("--env", default=None, help="Target env if --target-env omitted")
    pv.add_argument("--target-profile", default=None)
    pv.add_argument("--profile", default=None)
    pv.add_argument("--region", default=None)
    pv.add_argument("--namespace", default=None, help="K8s namespace for API status checks")
    pv.add_argument("--deployment", default=None, help="Backend deployment name")
    pv.add_argument(
        "--tolerance", type=float, default=0.10,
        help="Allowed key-count shortfall fraction (default 0.10)",
    )
    pv.set_defaults(func=cmd_verify)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    # Phase 6 (data-organization spec) notice: simulator_backup.py is
    # still the S3-slice tool but for a complete AI-Ops-plane backup
    # (S3 buckets + DDB SIM# metadata + diagnostics/health tables),
    # prefer ``plane_backup.py backup --plane ai_ops`` which composes
    # this tool with the DDB slices.
    if os.environ.get("SILENCE_SIMULATOR_BACKUP_HINT") != "1":
        print(
            "[hint] simulator_backup.py backs up S3 only. For a full "
            "AI-Ops plane backup (S3 + DDB simulator metadata + diagnostics/health), "
            "run plane_backup.py backup --plane ai_ops. Set "
            "SILENCE_SIMULATOR_BACKUP_HINT=1 to hide.",
            file=sys.stderr,
        )
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
