"""Tests for localEmulation helper functions."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nexus_operator.main import _is_local_emulation, _local_emulation_config


def test_local_emulation_disabled_by_default():
    assert _is_local_emulation({}) is False


def test_local_emulation_enabled():
    spec = {"localEmulation": {"enabled": True}}
    assert _is_local_emulation(spec) is True


def test_local_emulation_config_defaults():
    cfg = _local_emulation_config({"localEmulation": {"enabled": True}})
    assert cfg["namespace"] == "nexus-local"
    assert "ministack-svc.nexus-local" in cfg["ministack_host"]
    assert cfg["minio_url"].startswith("http://minio-svc")
    assert "mimir-svc.nexus-local" in cfg["mimir_host"]
    assert cfg["mimir_url"].startswith("http://mimir-svc")
    assert "pgvector-svc.nexus-local" in cfg["postgres_host"]
    assert cfg["postgres_database"] == "ontology_cp"
    assert cfg["skip_cognito"] is True
    assert cfg["skip_iam"] is True


def test_ai_engine_local_ssm_uses_capability_env_purpose_naming():
    from nexus_operator.resources.ssm import SSMProvisioner
    from nexus_operator.utils.naming import ResourceNaming

    naming = ResourceNaming("ai-engine", "local", account_id="000000000000")
    prov = SSMProvisioner(naming, "us-east-1", endpoint_url="http://ministack", local_emulation=True)
    params = prov._get_ai_engine_parameters()
    assert params["/ai-engine/local/dynamodb_transformation_table"][0] == "ai-engine-local-journeys"
    assert params["/ai-engine/local/s3_journey_logs_bucket"][0] == "ai-engine-local-journey-logs-000000000000"
