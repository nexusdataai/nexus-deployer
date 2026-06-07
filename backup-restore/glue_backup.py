"""
AWS Glue catalog backup/restore module.

Backup:  exports the database descriptor + all tables + all partitions for
         the {capability}_{env}_db Glue database into glue/{database,tables,
         partitions}.json.

Restore: creates the target Glue DB if missing, then re-creates each table
         with its Location URI rewritten from
         s3://{cap}-{src-env}-... to s3://{cap}-{tgt-env}-...-{tgt-account},
         then re-creates partitions.

Glue does NOT carry the actual data — it's just metadata pointing at S3.
The data must be restored separately via the s3 component.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from config import glue_database_name


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sys.stdout.write(f"[{ts}] {msg}\n")
    sys.stdout.flush()


# Glue API returns datetime objects that aren't JSON-serializable.
def _serialize(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"Type {type(o)} not serializable")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def backup(session, capability: str, env: str, output_dir: Path) -> Dict[str, Any]:
    glue = session.client("glue")
    db_name = glue_database_name(capability, env)
    dest = output_dir / "glue"
    dest.mkdir(parents=True, exist_ok=True)

    _log(f"  Glue database={db_name}")

    # --- Database descriptor ---
    try:
        db = glue.get_database(Name=db_name)["Database"]
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        _log(f"  Glue SKIP ({code}): {db_name}")
        return {"database": db_name, "table_count": 0, "partition_count": 0,
                "skipped": True, "error": code}

    (dest / "database.json").write_text(json.dumps(db, indent=2, default=_serialize))

    # --- Tables ---
    tables: List[Dict[str, Any]] = []
    paginator = glue.get_paginator("get_tables")
    for page in paginator.paginate(DatabaseName=db_name):
        tables.extend(page.get("TableList", []))

    (dest / "tables.json").write_text(json.dumps(tables, indent=2, default=_serialize))

    # --- Partitions (one entry per partition) ---
    partitions: List[Dict[str, Any]] = []
    part_paginator = glue.get_paginator("get_partitions")
    for t in tables:
        tname = t["Name"]
        try:
            for page in part_paginator.paginate(DatabaseName=db_name, TableName=tname):
                for p in page.get("Partitions", []):
                    p["_TableName"] = tname
                    partitions.append(p)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            _log(f"    WARN: get_partitions({tname}) failed ({code})")

    (dest / "partitions.json").write_text(json.dumps(partitions, indent=2, default=_serialize))

    _log(f"  Glue done: {len(tables)} table(s), {len(partitions)} partition(s)")
    return {
        "database": db_name,
        "table_count": len(tables),
        "partition_count": len(partitions),
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

# Fields Glue rejects on create_table (read-only on the descriptor we backed up)
_TABLE_STRIP_FIELDS = {
    "CreatedBy", "CreateTime", "UpdateTime", "DatabaseName", "CatalogId",
    "IsRegisteredWithLakeFormation", "VersionId",
}

# Same for create_partition
_PARTITION_STRIP_FIELDS = {
    "CreationTime", "DatabaseName", "TableName", "CatalogId", "_TableName",
}

# Same for create_database
_DATABASE_STRIP_FIELDS = {
    "CreateTime", "CatalogId",
}


def _rewrite_s3_uri(
    uri: Optional[str],
    src_capability: str, src_env: str,
    tgt_capability: str, tgt_env: str,
    src_account_id: Optional[str], tgt_account_id: Optional[str],
) -> Optional[str]:
    if not uri or not uri.startswith("s3://"):
        return uri
    new = uri
    src_hyphen = f"{src_capability}-{src_env}-"
    tgt_hyphen = f"{tgt_capability}-{tgt_env}-"
    if src_hyphen in new:
        new = new.replace(src_hyphen, tgt_hyphen)
    if src_account_id and tgt_account_id and src_account_id != tgt_account_id:
        new = new.replace(src_account_id, tgt_account_id)
    return new


def _rewrite_table_locations(
    table: Dict[str, Any],
    src_capability: str, src_env: str,
    tgt_capability: str, tgt_env: str,
    src_account_id: Optional[str], tgt_account_id: Optional[str],
) -> Dict[str, Any]:
    t = copy.deepcopy(table)
    sd = t.get("StorageDescriptor")
    if sd and sd.get("Location"):
        sd["Location"] = _rewrite_s3_uri(
            sd["Location"], src_capability, src_env, tgt_capability, tgt_env,
            src_account_id, tgt_account_id,
        )
    return t


def _strip(d: Dict[str, Any], fields) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k not in fields}


def restore(
    session,
    target_capability: str,
    target_env: str,
    target_account_id: str,
    local_dir: Path,
    source_capability: Optional[str] = None,
    source_env: Optional[str] = None,
    source_account_id: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    src_dir = local_dir / "glue"
    db_file = src_dir / "database.json"
    if not db_file.exists():
        _log("  Glue SKIP: not in backup")
        return {"restored_tables": 0, "skipped": True}

    db = json.loads(db_file.read_text())
    tables = json.loads((src_dir / "tables.json").read_text()) if (src_dir / "tables.json").exists() else []
    partitions = json.loads((src_dir / "partitions.json").read_text()) if (src_dir / "partitions.json").exists() else []

    source_db_name = db["Name"]
    target_db_name = glue_database_name(target_capability, target_env)

    if source_capability is None or source_env is None:
        # Try to infer from db name: nexus_ai_dev_db
        parts = source_db_name.split("_")
        if source_capability is None and len(parts) >= 3:
            source_capability = "-".join(parts[:-2])
        if source_env is None and len(parts) >= 2:
            source_env = parts[-2]

    _log(f"  Glue {source_db_name} -> {target_db_name} ({len(tables)} table(s), {len(partitions)} partition(s))")

    if dry_run:
        for t in tables:
            new_loc = _rewrite_s3_uri(
                t.get("StorageDescriptor", {}).get("Location"),
                source_capability, source_env,
                target_capability, target_env,
                source_account_id, target_account_id,
            )
            _log(f"    DRY: table {t['Name']}  loc={new_loc}")
        return {"restored_tables": len(tables), "restored_partitions": len(partitions), "dry_run": True}

    glue = session.client("glue")
    errors: List[str] = []

    # --- Create target DB ---
    db_input = _strip(db, _DATABASE_STRIP_FIELDS)
    db_input["Name"] = target_db_name
    if db_input.get("LocationUri"):
        db_input["LocationUri"] = _rewrite_s3_uri(
            db_input["LocationUri"],
            source_capability, source_env, target_capability, target_env,
            source_account_id, target_account_id,
        )
    try:
        glue.create_database(DatabaseInput=db_input)
        _log(f"    Created database {target_db_name}")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "AlreadyExistsException":
            _log(f"    Database {target_db_name} already exists, reusing")
        else:
            _log(f"    WARN: create_database failed ({code})")
            errors.append(f"db: {code}")

    # --- Create tables ---
    restored_tables = 0
    for t in tables:
        rewritten = _rewrite_table_locations(
            t, source_capability, source_env, target_capability, target_env,
            source_account_id, target_account_id,
        )
        table_input = _strip(rewritten, _TABLE_STRIP_FIELDS)
        try:
            glue.create_table(DatabaseName=target_db_name, TableInput=table_input)
            restored_tables += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "AlreadyExistsException":
                # Update existing table to match
                try:
                    glue.update_table(DatabaseName=target_db_name, TableInput=table_input)
                    restored_tables += 1
                except ClientError as ue:
                    errors.append(f"table {t['Name']}: {ue.response.get('Error', {}).get('Code', '')}")
            else:
                errors.append(f"table {t['Name']}: {code}")

    # --- Create partitions ---
    restored_parts = 0
    for p in partitions:
        tname = p.get("_TableName") or p.get("TableName")
        if not tname:
            continue
        rewritten = copy.deepcopy(p)
        if rewritten.get("StorageDescriptor", {}).get("Location"):
            rewritten["StorageDescriptor"]["Location"] = _rewrite_s3_uri(
                rewritten["StorageDescriptor"]["Location"],
                source_capability, source_env, target_capability, target_env,
                source_account_id, target_account_id,
            )
        part_input = _strip(rewritten, _PARTITION_STRIP_FIELDS)
        try:
            glue.create_partition(
                DatabaseName=target_db_name, TableName=tname,
                PartitionInput=part_input,
            )
            restored_parts += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code != "AlreadyExistsException":
                errors.append(f"partition {tname}/{p.get('Values', [])}: {code}")

    _log(f"  Glue done: {restored_tables}/{len(tables)} tables, {restored_parts}/{len(partitions)} partitions, {len(errors)} error(s)")
    return {
        "restored_tables": restored_tables,
        "restored_partitions": restored_parts,
        "target_database": target_db_name,
        "errors": errors,
    }
