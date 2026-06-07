"""moto-based unit tests for cognito_backup.

Cognito moto coverage in v5.x requires the optional `joserfc` dependency
(used to mock JWT signing). The rewrite-logic tests don't need moto and
always run; the moto-backed integration tests skip cleanly when joserfc
isn't installed.
"""
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import cognito_backup

try:
    import joserfc  # noqa: F401
    _HAS_JOSERFC = True
except ImportError:
    _HAS_JOSERFC = False

_needs_joserfc = pytest.mark.skipif(
    not _HAS_JOSERFC,
    reason="moto cognitoidp backend requires joserfc",
)


@_needs_joserfc
@mock_aws
def test_backup_pool_groups_and_users(tmp_path: Path):
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    pool = cognito.create_user_pool(PoolName="nexus-ai-dev")
    pool_id = pool["UserPool"]["Id"]
    cognito.create_group(UserPoolId=pool_id, GroupName="Admin", Precedence=1)
    cognito.create_group(UserPoolId=pool_id, GroupName="SalesRep", Precedence=10)
    cognito.admin_create_user(
        UserPoolId=pool_id, Username="alice@example.com",
        UserAttributes=[{"Name": "email", "Value": "alice@example.com"}],
        TemporaryPassword="Temp!1234",
    )

    session = boto3.Session(region_name="us-east-1")
    result = cognito_backup.backup(session, "nexus-ai", "dev", tmp_path)

    assert result["pool_name"] == "nexus-ai-dev"
    assert result["group_count"] == 2
    assert result["user_count"] == 1

    groups = json.loads((tmp_path / "cognito" / "groups.json").read_text())
    assert sorted(g["GroupName"] for g in groups) == ["Admin", "SalesRep"]

    users_jsonl = (tmp_path / "cognito" / "users.jsonl").read_text()
    assert "alice@example.com" in users_jsonl


@_needs_joserfc
@mock_aws
def test_backup_skips_when_pool_missing(tmp_path: Path):
    session = boto3.Session(region_name="us-east-1")
    result = cognito_backup.backup(session, "nexus-ai", "dev", tmp_path)
    assert result["skipped"] is True
    assert result["reason"] == "pool-not-found"


def test_rewrite_callback_url():
    u = cognito_backup._rewrite_callback_url(
        "https://nexus-ai-dev-app.example.com/cb",
        "nexus-ai", "dev", "nexus-ai", "test", "111", "222",
    )
    assert u == "https://nexus-ai-test-app.example.com/cb"


def test_rewrite_callback_url_account_id():
    u = cognito_backup._rewrite_callback_url(
        "https://example.com/?acct=111",
        "nexus-ai", "dev", "nexus-ai", "test", "111", "222",
    )
    assert u == "https://example.com/?acct=222"


@_needs_joserfc
@mock_aws
def test_restore_creates_missing_groups(tmp_path: Path):
    cognito = boto3.client("cognito-idp", region_name="us-east-1")
    src_pool = cognito.create_user_pool(PoolName="nexus-ai-dev")["UserPool"]
    cognito.create_group(UserPoolId=src_pool["Id"], GroupName="Admin", Precedence=1)

    session = boto3.Session(region_name="us-east-1")
    cognito_backup.backup(session, "nexus-ai", "dev", tmp_path)

    # Pre-create the target pool (operator behavior).
    cognito.create_user_pool(PoolName="nexus-ai-test")

    result = cognito_backup.restore(
        session, "nexus-ai", "test", "222", tmp_path,
        source_account_id="111",
    )
    assert result["restored_groups"] == 1
