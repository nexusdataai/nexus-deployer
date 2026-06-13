"""
Tests for OperatorDeploymentService.get_capability_status auth handling.

When the wizard's STS session expires mid-deploy, kube-apiserver starts
returning HTTP 401 to the deployer's status polls. Before this fix the
backend mapped that to phase="Unknown" and the wizard polling loop kept
spamming identical 401s for the full 15-minute timeout. The mapping is
now explicit so the wizard can abort with an actionable message.
"""
from unittest.mock import MagicMock

import pytest

from app.services.operator_deployment_service import OperatorDeploymentService


def _service():
    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None
    return svc


def _api_exception(status_code: int, reason: str = ""):
    from kubernetes.client.rest import ApiException
    return ApiException(status=status_code, reason=reason or "")


@pytest.mark.asyncio
async def test_status_401_maps_to_unauthorized_phase():
    svc = _service()
    custom = MagicMock()
    custom.get_namespaced_custom_object.side_effect = _api_exception(401, "Unauthorized")

    async def fake_clients(_):
        return MagicMock(), MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_status(
        cluster_name="c", cr_name="nexus-ai-test", namespace="nexus-ai-test"
    )
    assert result["phase"] == "Unauthorized"
    assert "401" in result["message"]
    assert "session" in result["message"].lower()


@pytest.mark.asyncio
async def test_status_403_also_maps_to_unauthorized_phase():
    svc = _service()
    custom = MagicMock()
    custom.get_namespaced_custom_object.side_effect = _api_exception(403, "Forbidden")

    async def fake_clients(_):
        return MagicMock(), MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_status(
        cluster_name="c", cr_name="x", namespace="ns"
    )
    assert result["phase"] == "Unauthorized"
    assert "403" in result["message"]


@pytest.mark.asyncio
async def test_status_404_maps_to_notfound_phase():
    """If the CR is deleted while the wizard is polling, surface that
    distinctly so the wizard does not treat it as 'still in progress'."""
    svc = _service()
    custom = MagicMock()
    custom.get_namespaced_custom_object.side_effect = _api_exception(404, "Not Found")

    async def fake_clients(_):
        return MagicMock(), MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_status(
        cluster_name="c", cr_name="gone", namespace="ns"
    )
    assert result["phase"] == "NotFound"
    assert "gone" in result["message"]


@pytest.mark.asyncio
async def test_other_api_errors_remain_unknown():
    """A 500 from the API server should remain Unknown so the wizard
    treats it as a transient blip and keeps polling."""
    svc = _service()
    custom = MagicMock()
    custom.get_namespaced_custom_object.side_effect = _api_exception(500, "Internal")

    async def fake_clients(_):
        return MagicMock(), MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_status(cluster_name="c", cr_name="x", namespace="n")
    assert result["phase"] == "Unknown"
