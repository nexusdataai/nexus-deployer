"""moto-based unit tests for ssm_backup.

Covers:
  - backup() exports the full /{capability}/{env}/ tree
  - restore() rewrites parameter names AND values for an env / account rename
  - rewrite is value-substring-safe (touches SSM paths, bucket names, ARNs,
    Glue DB names, secret prefixes, account IDs)
"""
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import ssm_backup


@mock_aws
def test_backup_exports_parameter_tree(tmp_path: Path):
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(Name="/nexus-ai/dev/aws/region",
                      Value="us-east-1", Type="String")
    ssm.put_parameter(Name="/nexus-ai/dev/dynamodb/transformation-table",
                      Value="nexus-ai-dev-transformation-system", Type="String")
    ssm.put_parameter(Name="/nexus-ai/dev/s3/recordings-bucket",
                      Value="nexus-ai-dev-call-data-111111111111", Type="String")
    # Sibling env must NOT be exported.
    ssm.put_parameter(Name="/nexus-ai/prod/aws/region",
                      Value="us-east-1", Type="String")

    session = boto3.Session(region_name="us-east-1")
    result = ssm_backup.backup(session, "nexus-ai", "dev", tmp_path)

    assert result["parameter_count"] == 3
    params = json.loads((tmp_path / "ssm" / "parameters.json").read_text())
    names = sorted(p["Name"] for p in params)
    assert names == sorted([
        "/nexus-ai/dev/aws/region",
        "/nexus-ai/dev/dynamodb/transformation-table",
        "/nexus-ai/dev/s3/recordings-bucket",
    ])


@mock_aws
def test_restore_rewrites_paths_and_values_for_env_and_account(tmp_path: Path):
    # Pre-seed source params, back them up.
    ssm_src = boto3.client("ssm", region_name="us-east-1")
    for name, value in [
        ("/nexus-ai/dev/aws/region", "us-east-1"),
        ("/nexus-ai/dev/dynamodb/foundry-workspace-table",
         "nexus-ai-dev-foundry-workspace"),
        ("/nexus-ai/dev/s3/recordings-bucket",
         "nexus-ai-dev-call-data-111111111111"),
        ("/nexus-ai/dev/glue/database", "nexus_ai_dev_db"),
        ("/nexus-ai/dev/secrets-prefix", "nexus-ai/dev/"),
    ]:
        ssm_src.put_parameter(Name=name, Value=value, Type="String")

    session = boto3.Session(region_name="us-east-1")
    ssm_backup.backup(session, "nexus-ai", "dev", tmp_path)

    # Now restore — same moto SSM service stands in for the target.
    result = ssm_backup.restore(
        session, "nexus-ai", "test", "222222222222", tmp_path,
        source_capability="nexus-ai", source_env="dev",
        source_account_id="111111111111",
    )
    assert result["restored"] == 5
    assert not result["errors"]

    # Read back the rewritten target params.
    def _read(name):
        return ssm_src.get_parameter(Name=name)["Parameter"]["Value"]

    assert _read("/nexus-ai/test/aws/region") == "us-east-1"
    assert _read("/nexus-ai/test/dynamodb/foundry-workspace-table") \
        == "nexus-ai-test-foundry-workspace"
    assert _read("/nexus-ai/test/s3/recordings-bucket") \
        == "nexus-ai-test-call-data-222222222222"
    assert _read("/nexus-ai/test/glue/database") == "nexus_ai_test_db"
    assert _read("/nexus-ai/test/secrets-prefix") == "nexus-ai/test/"


@mock_aws
def test_backup_empty_prefix_skipped_cleanly(tmp_path: Path):
    session = boto3.Session(region_name="us-east-1")
    result = ssm_backup.backup(session, "nexus-ai", "dev", tmp_path)
    # Empty tree returns parameter_count=0, no error.
    assert result["parameter_count"] == 0
    assert (tmp_path / "ssm" / "parameters.json").exists()


def test_rewrite_path_leaves_non_matching_alone():
    assert ssm_backup._rewrite_path(
        "/other/dev/foo", "/nexus-ai/dev/", "/nexus-ai/test/"
    ) == "/other/dev/foo"


def test_rewrite_value_no_change_when_envs_match():
    v = ssm_backup._rewrite_value(
        "nexus-ai-dev-call-data-111",
        "nexus-ai", "dev", "nexus-ai", "dev", "111", "111",
    )
    assert v == "nexus-ai-dev-call-data-111"
