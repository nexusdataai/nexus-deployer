"""moto-based unit tests for secrets_backup."""
import base64
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

import secrets_backup


@mock_aws
def test_backup_string_and_binary_secrets(tmp_path: Path):
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    sm.create_secret(Name="nexus-ai/dev/api-keys",
                     SecretString=json.dumps({"k": "abc"}))
    sm.create_secret(Name="nexus-ai/dev/openai",
                     SecretString="sk-totally-opaque")
    sm.create_secret(Name="nexus-ai/dev/bssmagic-credentials",
                     SecretBinary=b"\x00\x01ZIP_CONTENT")
    # Unknown type — should be skipped (not in SECRET_TYPES).
    sm.create_secret(Name="nexus-ai/dev/some-other-secret",
                     SecretString="ignored")
    # Sibling env — must NOT be backed up.
    sm.create_secret(Name="nexus-ai/prod/api-keys",
                     SecretString=json.dumps({"k": "prod"}))

    session = boto3.Session(region_name="us-east-1")
    result = secrets_backup.backup(session, "nexus-ai", "dev", tmp_path)
    assert result["secret_count"] >= 3
    assert "api-keys" in result["secret_types"]
    assert "bssmagic-credentials" in result["secret_types"]

    secrets = json.loads((tmp_path / "secrets" / "secrets.json").read_text())
    by_type = {s["SecretType"]: s for s in secrets}
    assert by_type["bssmagic-credentials"]["SecretBinary_b64"] \
        == base64.b64encode(b"\x00\x01ZIP_CONTENT").decode()
    assert by_type["openai"]["SecretString"] == "sk-totally-opaque"


@mock_aws
def test_restore_renames_and_rewrites_json_secrets(tmp_path: Path):
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    # JSON secret with env-bearing fields gets rewritten.
    sm.create_secret(Name="nexus-ai/dev/api-keys", SecretString=json.dumps({
        "bucket": "nexus-ai-dev-call-data-111",
        "role": "arn:aws:iam::111:role/nexus-ai-dev-app-role",
    }))
    # Opaque secret stays verbatim (no rewrite even if substring matches).
    sm.create_secret(Name="nexus-ai/dev/openai",
                     SecretString="sk-totally-opaque-with-nexus-ai-dev-substring")
    # Binary secret round-trips unchanged.
    sm.create_secret(Name="nexus-ai/dev/bssmagic-credentials",
                     SecretBinary=b"BINARY")

    session = boto3.Session(region_name="us-east-1")
    secrets_backup.backup(session, "nexus-ai", "dev", tmp_path)

    # Pre-create target placeholders (operator behavior).
    sm.create_secret(Name="nexus-ai/test/api-keys", SecretString="{}")
    sm.create_secret(Name="nexus-ai/test/openai", SecretString="placeholder")
    sm.create_secret(Name="nexus-ai/test/bssmagic-credentials", SecretBinary=b"placeholder")

    result = secrets_backup.restore(
        session, "nexus-ai", "test", "222", tmp_path,
        source_capability="nexus-ai", source_env="dev",
        source_account_id="111",
    )
    assert result["restored"] >= 3

    target = sm.get_secret_value(SecretId="nexus-ai/test/api-keys")
    parsed = json.loads(target["SecretString"])
    assert parsed["bucket"] == "nexus-ai-test-call-data-222"
    assert parsed["role"] == "arn:aws:iam::222:role/nexus-ai-test-app-role"

    # Opaque secret unchanged — string-rewrite refuses non-JSON values.
    assert sm.get_secret_value(SecretId="nexus-ai/test/openai")["SecretString"] \
        == "sk-totally-opaque-with-nexus-ai-dev-substring"

    # Binary round-trip.
    assert sm.get_secret_value(SecretId="nexus-ai/test/bssmagic-credentials")["SecretBinary"] == b"BINARY"


@mock_aws
def test_restore_creates_missing_secrets(tmp_path: Path):
    sm = boto3.client("secretsmanager", region_name="us-east-1")
    sm.create_secret(Name="nexus-ai/dev/license", SecretString="lic-xyz")

    session = boto3.Session(region_name="us-east-1")
    secrets_backup.backup(session, "nexus-ai", "dev", tmp_path)

    # Target has NO secret — restore must create it.
    result = secrets_backup.restore(
        session, "nexus-ai", "test", "222", tmp_path,
        source_account_id="111",
    )
    assert result["created"] == 1
    val = sm.get_secret_value(SecretId="nexus-ai/test/license")["SecretString"]
    assert val == "lic-xyz"
