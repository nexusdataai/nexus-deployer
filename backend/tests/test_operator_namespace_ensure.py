"""
Tests for the namespace-ensure step in
OperatorDeploymentService.create_capability_cr.

Covers:
- Existing namespace: skip creation, proceed to CR.
- Missing namespace + create_namespace_if_missing=True: create then CR.
- Missing namespace + create_namespace_if_missing=False: fail fast with
  a user-actionable error mentioning the wizard toggle.
- read_namespace returns a non-404 error: surface verbatim.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.operator_deployment_service import OperatorDeploymentService


def _service():
    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None
    return svc


def _api_exception(status_code: int):
    """Construct a kubernetes ApiException with the given status code."""
    from kubernetes.client.rest import ApiException
    return ApiException(status=status_code, reason="Not Found" if status_code == 404 else "Forbidden")


@pytest.mark.asyncio
async def test_existing_namespace_skips_creation():
    svc = _service()
    core = MagicMock()
    core.read_namespace.return_value = MagicMock()  # exists
    custom = MagicMock()

    async def fake_clients(_):
        return core, MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.create_capability_cr(
        cluster_name="c", capability_name="x", capability_version="1",
        environment="dev", namespace="my-ns", config={},
    )
    assert result["success"] is True
    core.create_namespace.assert_not_called()
    custom.create_namespaced_custom_object.assert_called_once()


@pytest.mark.asyncio
async def test_missing_namespace_is_created_when_flag_set():
    svc = _service()
    core = MagicMock()
    core.read_namespace.side_effect = _api_exception(404)
    custom = MagicMock()

    async def fake_clients(_):
        return core, MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.create_capability_cr(
        cluster_name="c", capability_name="x", capability_version="1",
        environment="dev", namespace="my-ns", config={},
        create_namespace_if_missing=True,
    )
    assert result["success"] is True
    core.create_namespace.assert_called_once()
    body = core.create_namespace.call_args.args[0]
    assert body.metadata.name == "my-ns"
    assert body.metadata.labels["nexus.ai/capability"] == "x"
    assert body.metadata.labels["nexus.ai/environment"] == "dev"
    custom.create_namespaced_custom_object.assert_called_once()


@pytest.mark.asyncio
async def test_missing_namespace_fails_fast_when_flag_off():
    svc = _service()
    core = MagicMock()
    core.read_namespace.side_effect = _api_exception(404)
    custom = MagicMock()

    async def fake_clients(_):
        return core, MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.create_capability_cr(
        cluster_name="c", capability_name="x", capability_version="1",
        environment="dev", namespace="my-ns", config={},
        create_namespace_if_missing=False,
    )
    assert result["success"] is False
    assert "my-ns" in result["message"]
    assert "does not exist" in result["message"]
    core.create_namespace.assert_not_called()
    custom.create_namespaced_custom_object.assert_not_called()


@pytest.mark.asyncio
async def test_read_namespace_non_404_surfaces_error():
    """RBAC/permission errors during read_namespace must abort the deploy."""
    svc = _service()
    core = MagicMock()
    core.read_namespace.side_effect = _api_exception(403)  # Forbidden
    custom = MagicMock()

    async def fake_clients(_):
        return core, MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.create_capability_cr(
        cluster_name="c", capability_name="x", capability_version="1",
        environment="dev", namespace="my-ns", config={},
    )
    assert result["success"] is False
    assert "could not verify namespace" in result["message"].lower()
    core.create_namespace.assert_not_called()
    custom.create_namespaced_custom_object.assert_not_called()
