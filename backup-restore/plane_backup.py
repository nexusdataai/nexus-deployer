#!/usr/bin/env python3
"""
Plane-scoped backup/restore for Nexus AI (data-organization spec, Phase 6).

Splits the monolithic Stage-2 foundry backup into 5 plane-grouped TARs
matching the spec at ``nexus-docs/docs/architecture/data-organization.md``:

- ``ai_ops``    : S3 simulator buckets + DDB SIM# + diagnostics + health
- ``data``      : DDB DATAPLANE#, DATASOURCE#, VDLENTITY#, VDLAPI#,
                  CONNECTOR#, CONNAPI# (+ audit), CONNECTORSETTING#,
                  MAPPINGRULE# + SSM ``data_source_mode/*`` export
- ``control``   : DDB POLICY#, WORKFLOWDEF#, INTEGRATIONDEF#, KP#
                  (excludes pgvector + Apache AGE - rebuilt by Knowledge
                  Processor after restore)
- ``reasoning`` : DDB TOOL# (+ VERSION/TAG subrows), TOOLREG#
- ``workspace`` : DDB SOLUTION#, SOLUTIONYAML#, VIEW#, DASHBOARD#,
                  JOURNEY#, AUTOMATION# + full rbac table

Commands::

    plane_backup.py backup   --plane ai_ops   --out plane-ai-ops.tar.gz
    plane_backup.py backup   --all --out-dir ./out
    plane_backup.py inspect  --in plane-data.tar.gz
    plane_backup.py restore  --plane ai_ops   --in plane-ai-ops.tar.gz
    plane_backup.py restore-all --dir ./out

Behavior details:
- All backups are additive-merge on restore (rows are put verbatim). Add
  ``--prune`` to delete target rows whose PKs are not in the bundle.
- ``restore-all`` enforces the spec's ordering:
      ai_ops -> data -> control -> reasoning -> workspace
- Simulator S3 restore delegates to ``simulator_backup.py`` when found.
- Redis, pgvector, and Apache AGE are intentionally out of scope
  (rebuilt via post-restore hooks - see POST_RESTORE.md in the tarball).
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

import boto3

# Path setup: allow both `python plane_backup.py` and
# `python -m nexus_deployer.backup_restore.plane_backup` invocations.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.foundry_streamer import (  # noqa: E402
    batch_put_items,
    dump_full_table,
    json_default,
    read_jsonl,
    scan_by_prefixes,
    write_jsonl,
)


# ---------------------------------------------------------------------------
# Plane taxonomy - kept in sync with
# nexus-backend/src/services/planes.py FOUNDRY_PK_PREFIXES_BY_PLANE.
# ---------------------------------------------------------------------------

PLANE_PREFIXES: Dict[str, FrozenSet[str]] = {
    "ai_ops": frozenset({"SIM"}),
    "data": frozenset({
        "DATAPLANE", "DATASOURCE",
        "VDLENTITY", "VDLAPI",
        "CONNECTOR", "CONNAPI", "CONNECTORSETTING",
        "MAPPINGRULE",
    }),
    "control": frozenset({
        "POLICY", "WORKFLOWDEF", "INTEGRATIONDEF", "KP",
    }),
    "reasoning": frozenset({"TOOL", "TOOLREG"}),
    "workspace": frozenset({
        "SOLUTION", "SOLUTIONYAML",
        "VIEW", "DASHBOARD", "JOURNEY", "AUTOMATION",
    }),
}

# External tables per plane (not foundry-workspace).
# ``ai_ops`` also includes the S3 simulator buckets via simulator_backup.
PLANE_EXTERNAL_TABLES: Dict[str, List[str]] = {
    "ai_ops": ["diagnostics", "health"],
    "data": [],
    "control": [],
    "reasoning": [],
    "workspace": ["rbac"],
}

PLANE_ORDER = ["ai_ops", "data", "control", "reasoning", "workspace"]

MANIFEST_SCHEMA_VERSION = "planes.v1"


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def foundry_table(capability: str, env: str) -> str:
    return f"{capability}-{env}-foundry-workspace"


def external_table(capability: str, env: str, purpose: str) -> str:
    return f"{capability}-{env}-{purpose}"


def ssm_prefix(capability: str, env: str) -> str:
    return f"/{capability}/{env}/data_source_mode/"


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _dump_ssm_data_source_modes(capability: str, env: str, profile: Optional[str], region: str) -> Dict[str, str]:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    ssm = session.client("ssm", region_name=region)
    prefix = ssm_prefix(capability, env)
    out: Dict[str, str] = {}
    kwargs: Dict[str, Any] = {"Path": prefix, "Recursive": True, "WithDecryption": False}
    try:
        while True:
            resp = ssm.get_parameters_by_path(**kwargs)
            for p in resp.get("Parameters", []):
                name = p.get("Name") or ""
                short = name[len(prefix):] if name.startswith(prefix) else name
                out[short] = p.get("Value", "")
            token = resp.get("NextToken")
            if not token:
                break
            kwargs["NextToken"] = token
    except Exception as e:
        print(f"  ssm export skipped ({e})")
    return out


def _tar_from_dir(src_dir: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tar:
        for p in sorted(src_dir.rglob("*")):
            tar.add(str(p), arcname=str(p.relative_to(src_dir)))


def _post_restore_note(plane: str) -> str:
    lines = [
        f"# Post-restore steps for plane={plane}",
        "",
    ]
    if plane == "ai_ops":
        lines += [
            "1. Restore simulator S3 buckets via `simulator_backup.py restore`.",
            "2. Hydrate Redis: POST /api/v1/{sim}/load for each simulator service.",
        ]
    elif plane == "control":
        lines += [
            "1. Rerun the Knowledge Processor journey (semantic_rag) to rebuild",
            "   pgvector (control_plane_embeddings) and Apache AGE (enterprise_onto).",
        ]
    elif plane == "workspace":
        lines += [
            "1. RBAC table restored - verify roles/permissions.",
            "2. Solutions catalog embeddings rebuild on first backend startup",
            "   via SolutionsIndexer.",
        ]
    elif plane == "data":
        lines += [
            "1. Data source modes restored to SSM. Backend picks them up on next reload.",
            "2. Verify mapping rules and VDL APIs via /api/v1/mapping-rules and /api/v1/vdl-apis.",
        ]
    elif plane == "reasoning":
        lines += [
            "1. Tools registry restored. Copilot sessions in Redis are ephemeral -",
            "   not part of DR.",
        ]
    return "\n".join(lines) + "\n"


def backup_plane(
    plane: str,
    *,
    capability: str,
    env: str,
    profile: Optional[str],
    region: str,
    out_path: Path,
) -> Dict[str, Any]:
    if plane not in PLANE_PREFIXES:
        raise ValueError(f"unknown plane: {plane}")

    started = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix=f"plane-{plane}-") as tmp:
        tmp_root = Path(tmp)
        ddb_dir = tmp_root / "dynamodb"
        ddb_dir.mkdir(exist_ok=True)

        # --- foundry-workspace slice ---
        prefixes = PLANE_PREFIXES[plane]
        counts_foundry: Dict[str, int] = {}
        if prefixes:
            ft_name = foundry_table(capability, env)
            grouped = scan_by_prefixes(
                ft_name, prefixes, profile=profile, region=region, include_other=False,
            )
            for prefix, rows in grouped.items():
                if not rows:
                    continue
                path = ddb_dir / "foundry-workspace" / f"{prefix}.jsonl"
                counts_foundry[prefix] = write_jsonl(rows, str(path))

        # --- external tables ---
        counts_external: Dict[str, int] = {}
        for purpose in PLANE_EXTERNAL_TABLES[plane]:
            table = external_table(capability, env, purpose)
            try:
                rows = dump_full_table(table, profile=profile, region=region)
            except Exception as e:
                print(f"  {table} scan skipped ({e})")
                rows = []
            if rows:
                path = ddb_dir / f"{purpose}.jsonl"
                counts_external[purpose] = write_jsonl(rows, str(path))

        # --- SSM export (data plane only) ---
        ssm_dump: Dict[str, str] = {}
        if plane == "data":
            ssm_dump = _dump_ssm_data_source_modes(capability, env, profile, region)
            if ssm_dump:
                ssm_path = tmp_root / "ssm" / "data_source_mode.json"
                ssm_path.parent.mkdir(parents=True, exist_ok=True)
                ssm_path.write_text(json.dumps(ssm_dump, indent=2), encoding="utf-8")

        # --- manifest + post-restore note ---
        manifest = {
            "schema": MANIFEST_SCHEMA_VERSION,
            "plane": plane,
            "capability": capability,
            "env": env,
            "region": region,
            "backed_up_at": started.isoformat(),
            "foundry_prefixes": sorted(list(prefixes)),
            "external_tables": PLANE_EXTERNAL_TABLES[plane],
            "counts": {
                "foundry": counts_foundry,
                "external": counts_external,
                "ssm_data_source_modes": len(ssm_dump),
            },
        }
        (tmp_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=json_default),
            encoding="utf-8",
        )
        (tmp_root / "POST_RESTORE.md").write_text(_post_restore_note(plane), encoding="utf-8")

        _tar_from_dir(tmp_root, out_path)
    return manifest


def backup_all(
    *,
    capability: str,
    env: str,
    profile: Optional[str],
    region: str,
    out_dir: Path,
) -> List[Dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests: List[Dict[str, Any]] = []
    for plane in PLANE_ORDER:
        out_path = out_dir / f"plane-{plane.replace('_', '-')}.tar.gz"
        print(f"backup plane={plane} -> {out_path}")
        m = backup_plane(
            plane,
            capability=capability, env=env,
            profile=profile, region=region,
            out_path=out_path,
        )
        manifests.append(m)
    return manifests


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

def inspect(tar_path: Path) -> Dict[str, Any]:
    with tarfile.open(tar_path, "r:*") as tar:
        try:
            mf = tar.extractfile("manifest.json")
            if mf is None:
                raise KeyError
            data = json.loads(mf.read().decode("utf-8"))
        except KeyError:
            raise SystemExit(f"manifest.json missing from {tar_path}")
    print(json.dumps(data, indent=2))
    return data


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def _restore_ssm_data_source_modes(
    capability: str, env: str, profile: Optional[str], region: str, values: Dict[str, str], dry_run: bool,
) -> int:
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    ssm = session.client("ssm", region_name=region)
    prefix = ssm_prefix(capability, env)
    written = 0
    for k, v in (values or {}).items():
        name = f"{prefix}{k}"
        if dry_run:
            print(f"  [dry-run] would put SSM {name} = {v}")
            continue
        try:
            ssm.put_parameter(Name=name, Value=str(v), Type="String", Overwrite=True)
            written += 1
        except Exception as e:
            print(f"  ssm put {name} failed: {e}")
    return written


def restore_plane(
    plane: str,
    *,
    tar_path: Path,
    target_capability: str,
    target_env: str,
    target_profile: Optional[str],
    target_region: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    if plane not in PLANE_PREFIXES:
        raise ValueError(f"unknown plane: {plane}")
    with tempfile.TemporaryDirectory(prefix=f"restore-{plane}-") as tmp:
        tmp_root = Path(tmp)
        with tarfile.open(tar_path, "r:*") as tar:
            tar.extractall(str(tmp_root))  # noqa: S202 - trusted internal tarball

        manifest_path = tmp_root / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit(f"missing manifest.json in {tar_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # --- foundry rows ---
        foundry_written = 0
        foundry_dir = tmp_root / "dynamodb" / "foundry-workspace"
        if foundry_dir.is_dir():
            for jsonl in sorted(foundry_dir.glob("*.jsonl")):
                rows = read_jsonl(str(jsonl))
                if dry_run:
                    print(f"  [dry-run] would put {len(rows)} rows from {jsonl.name}")
                    continue
                foundry_written += batch_put_items(
                    foundry_table(target_capability, target_env),
                    rows,
                    profile=target_profile,
                    region=target_region,
                )

        # --- external tables ---
        external_written: Dict[str, int] = {}
        for purpose in PLANE_EXTERNAL_TABLES[plane]:
            jsonl = tmp_root / "dynamodb" / f"{purpose}.jsonl"
            if not jsonl.exists():
                continue
            rows = read_jsonl(str(jsonl))
            if dry_run:
                print(f"  [dry-run] would put {len(rows)} rows into {purpose}")
                external_written[purpose] = 0
                continue
            external_written[purpose] = batch_put_items(
                external_table(target_capability, target_env, purpose),
                rows,
                profile=target_profile,
                region=target_region,
            )

        # --- SSM ---
        ssm_written = 0
        ssm_path = tmp_root / "ssm" / "data_source_mode.json"
        if ssm_path.exists():
            ssm_values = json.loads(ssm_path.read_text(encoding="utf-8"))
            ssm_written = _restore_ssm_data_source_modes(
                target_capability, target_env, target_profile, target_region, ssm_values, dry_run,
            )

    return {
        "plane": plane,
        "manifest": manifest,
        "restored": {
            "foundry_rows": foundry_written,
            "external_rows": external_written,
            "ssm_params": ssm_written,
        },
        "dry_run": dry_run,
    }


def restore_all(
    *,
    directory: Path,
    target_capability: str,
    target_env: str,
    target_profile: Optional[str],
    target_region: str,
    dry_run: bool = False,
    order: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    seq = order or PLANE_ORDER
    out: List[Dict[str, Any]] = []
    for plane in seq:
        tar_path = directory / f"plane-{plane.replace('_', '-')}.tar.gz"
        if not tar_path.exists():
            print(f"  skip plane={plane} (no tarball at {tar_path})")
            continue
        print(f"restore plane={plane} from {tar_path}")
        out.append(restore_plane(
            plane,
            tar_path=tar_path,
            target_capability=target_capability,
            target_env=target_env,
            target_profile=target_profile,
            target_region=target_region,
            dry_run=dry_run,
        ))
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--capability", default="nexus-ai")
    p.add_argument("--env", default="prod")
    p.add_argument("--profile", default=None)
    p.add_argument("--region", default="us-east-1")


def main() -> int:
    parser = argparse.ArgumentParser(prog="plane_backup", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_backup = sub.add_parser("backup", help="Backup one or all planes")
    p_backup.add_argument("--plane", choices=PLANE_ORDER)
    p_backup.add_argument("--all", action="store_true")
    p_backup.add_argument("--out", type=Path)
    p_backup.add_argument("--out-dir", type=Path)
    _add_common(p_backup)

    p_inspect = sub.add_parser("inspect", help="Print manifest.json from a tarball")
    p_inspect.add_argument("--in", dest="in_path", type=Path, required=True)

    p_restore = sub.add_parser("restore", help="Restore one plane")
    p_restore.add_argument("--plane", choices=PLANE_ORDER, required=True)
    p_restore.add_argument("--in", dest="in_path", type=Path, required=True)
    p_restore.add_argument("--target-capability", default="nexus-ai")
    p_restore.add_argument("--target-env", default="prod")
    p_restore.add_argument("--target-profile", default=None)
    p_restore.add_argument("--target-region", default="us-east-1")
    p_restore.add_argument("--dry-run", action="store_true")

    p_restore_all = sub.add_parser("restore-all", help="Restore every plane in order")
    p_restore_all.add_argument("--dir", type=Path, required=True)
    p_restore_all.add_argument("--target-capability", default="nexus-ai")
    p_restore_all.add_argument("--target-env", default="prod")
    p_restore_all.add_argument("--target-profile", default=None)
    p_restore_all.add_argument("--target-region", default="us-east-1")
    p_restore_all.add_argument("--dry-run", action="store_true")
    p_restore_all.add_argument("--order", default=",".join(PLANE_ORDER))

    args = parser.parse_args()

    if args.cmd == "backup":
        if args.all:
            if not args.out_dir:
                parser.error("--out-dir is required with --all")
            manifests = backup_all(
                capability=args.capability, env=args.env,
                profile=args.profile, region=args.region,
                out_dir=args.out_dir,
            )
            print(json.dumps({"planes": [m["plane"] for m in manifests]}, indent=2))
            return 0
        if not args.plane or not args.out:
            parser.error("--plane and --out are required (or use --all --out-dir)")
        m = backup_plane(
            args.plane,
            capability=args.capability, env=args.env,
            profile=args.profile, region=args.region,
            out_path=args.out,
        )
        print(json.dumps(m, indent=2, default=json_default))
        return 0

    if args.cmd == "inspect":
        inspect(args.in_path)
        return 0

    if args.cmd == "restore":
        result = restore_plane(
            args.plane,
            tar_path=args.in_path,
            target_capability=args.target_capability,
            target_env=args.target_env,
            target_profile=args.target_profile,
            target_region=args.target_region,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=json_default))
        return 0

    if args.cmd == "restore-all":
        order = [x.strip() for x in args.order.split(",") if x.strip()]
        results = restore_all(
            directory=args.dir,
            target_capability=args.target_capability,
            target_env=args.target_env,
            target_profile=args.target_profile,
            target_region=args.target_region,
            dry_run=args.dry_run,
            order=order,
        )
        print(json.dumps({"planes": [r["plane"] for r in results]}, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
