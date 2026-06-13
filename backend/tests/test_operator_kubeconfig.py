"""
Tests for OperatorDeploymentService._write_kubeconfig.

The kubeconfig the deployer writes points at `aws eks get-token`. Without
an explicit env block on the exec plugin, the subprocess inherits the
backend process's environment, which on a typical deployer host has no
AWS credentials (or stale developer-scoped ones). The result is HTTP 401
from the cluster API even though the wizard authenticated successfully,
because the wizard's credentials live only in `aws_session_manager`.

This test asserts the env block is populated from the live session.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml

from app.services.operator_deployment_service import OperatorDeploymentService


@pytest.mark.asyncio
async def test_kubeconfig_exec_env_carries_session_credentials(tmp_path, monkeypatch):
    # Redirect ~/.kube/config to a temp file
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows

    # Build a service without going through __init__ (which hits boto3)
    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = "test-session"
    svc.eks_client = MagicMock()
    svc.eks_client.describe_cluster.return_value = {
        "cluster": {
            "certificateAuthority": {"data": "BASE64=="},
            "endpoint": "https://example.eks.amazonaws.com",
        }
    }

    fake_session = {
        "access_key_id": "AKIAFAKE",
        "secret_access_key": "secret",
        "session_token": "tok",
        "region": "us-east-1",
    }
    with patch(
        "app.services.operator_deployment_service.aws_session_manager.get_session",
        return_value=fake_session,
    ):
        await svc._write_kubeconfig("my-cluster")

    kubeconfig_path = os.path.expanduser("~/.kube/config")
    with open(kubeconfig_path) as f:
        cfg = yaml.safe_load(f)

    # Find the user entry we just wrote
    users = {u["name"]: u["user"] for u in cfg["users"]}
    assert "my-cluster" in users
    exec_block = users["my-cluster"]["exec"]
    assert exec_block["command"] == "aws"
    env = {e["name"]: e["value"] for e in exec_block["env"] or []}
    assert env["AWS_ACCESS_KEY_ID"] == "AKIAFAKE"
    assert env["AWS_SECRET_ACCESS_KEY"] == "secret"
    assert env["AWS_SESSION_TOKEN"] == "tok"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["AWS_DEFAULT_REGION"] == "us-east-1"


@pytest.mark.asyncio
async def test_kubeconfig_exec_env_omitted_when_no_session(tmp_path, monkeypatch):
    """When the deployer is running with ambient AWS creds (no session id),
    the exec env block must remain None so the subprocess inherits the
    parent's environment (IRSA / instance profile / AWS_PROFILE)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None
    svc.eks_client = MagicMock()
    svc.eks_client.describe_cluster.return_value = {
        "cluster": {
            "certificateAuthority": {"data": "BASE64=="},
            "endpoint": "https://example.eks.amazonaws.com",
        }
    }

    await svc._write_kubeconfig("my-cluster")

    kubeconfig_path = os.path.expanduser("~/.kube/config")
    with open(kubeconfig_path) as f:
        cfg = yaml.safe_load(f)
    users = {u["name"]: u["user"] for u in cfg["users"]}
    assert users["my-cluster"]["exec"]["env"] is None
