"""moto-based unit tests for glue_backup."""
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import glue_backup


@mock_aws
def test_backup_and_restore_with_location_rewrite(tmp_path: Path):
    glue = boto3.client("glue", region_name="us-east-1")
    glue.create_database(DatabaseInput={"Name": "nexus_ai_dev_db"})
    glue.create_table(DatabaseName="nexus_ai_dev_db", TableInput={
        "Name": "call_records",
        "StorageDescriptor": {
            "Location": "s3://nexus-ai-dev-call-data-111/call-data/",
            "Columns": [{"Name": "call_id", "Type": "string"}],
        },
        "PartitionKeys": [{"Name": "year", "Type": "string"}],
    })

    session = boto3.Session(region_name="us-east-1")
    result = glue_backup.backup(session, "nexus-ai", "dev", tmp_path)
    assert result["table_count"] == 1
    assert result["database"] == "nexus_ai_dev_db"

    db_dump = json.loads((tmp_path / "glue" / "database.json").read_text())
    assert db_dump["Name"] == "nexus_ai_dev_db"
    tables = json.loads((tmp_path / "glue" / "tables.json").read_text())
    assert tables[0]["StorageDescriptor"]["Location"] \
        == "s3://nexus-ai-dev-call-data-111/call-data/"

    # Restore into "test" env in a different account.
    result = glue_backup.restore(
        session, "nexus-ai", "test", "222", tmp_path,
        source_capability="nexus-ai", source_env="dev",
        source_account_id="111",
    )
    assert result["restored_tables"] == 1
    assert result["target_database"] == "nexus_ai_test_db"

    # Read back from moto to confirm the Location was rewritten.
    restored = glue.get_table(DatabaseName="nexus_ai_test_db", Name="call_records")
    assert restored["Table"]["StorageDescriptor"]["Location"] \
        == "s3://nexus-ai-test-call-data-222/call-data/"


@mock_aws
def test_backup_skips_missing_database(tmp_path: Path):
    session = boto3.Session(region_name="us-east-1")
    result = glue_backup.backup(session, "nexus-ai", "dev", tmp_path)
    assert result["skipped"] is True


def test_strip_helpers_remove_readonly_fields():
    table = {"Name": "x", "CreateTime": "now", "DatabaseName": "y",
             "StorageDescriptor": {"Location": "s3://a/b/"}}
    stripped = glue_backup._strip(table, glue_backup._TABLE_STRIP_FIELDS)
    assert "CreateTime" not in stripped
    assert "DatabaseName" not in stripped
    assert stripped["Name"] == "x"
    assert stripped["StorageDescriptor"]["Location"] == "s3://a/b/"
