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
    assert cfg["skip_cognito"] is True
    assert cfg["skip_iam"] is True
