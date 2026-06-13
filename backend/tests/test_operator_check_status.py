"""
Tests for OperatorDeploymentService.check_operator_status.

The check has three classes of outcome the wizard cares about:
  1. Deployment present  -> installed/installing/degraded with replica counts.
  2. Deployment 404, namespace and CRD also 404 -> fresh cluster.
  3. Deployment 404 but namespace OR CRD exists -> partial cleanup.
The wizard surfaces the `detail` string verbatim so the user can tell
those apart without leaving the UI.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.operator_deployment_service import OperatorDeploymentService


def _service():
    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None
    return svc


def _api_404():
    from kubernetes.client.rest import ApiException
    return ApiException(status=404, reason="Not Found")


def _fake_deployment(ready: int, desired: int, image: str):
    return SimpleNamespace(
        status=SimpleNamespace(ready_replicas=ready, available_replicas=ready),
        spec=SimpleNamespace(
            replicas=desired,
            template=SimpleNamespace(spec=SimpleNamespace(containers=[SimpleNamespace(image=image)])),
        ),
    )


@pytest.mark.asyncio
async def test_check_operator_status_installed_with_replicas():
    svc = _service()
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.return_value = _fake_deployment(
        ready=2, desired=2, image="123.dkr.ecr.us-east-1.amazonaws.com/nexus-operator:1.0.0"
    )
    core_v1 = MagicMock()

    async def fake_clients(_):
        return core_v1, apps_v1, MagicMock()

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.check_operator_status("nexus-test1")
    assert result["installed"] is True
    assert result["status"] == "installed"
    assert result["version"] == "1.0.0"
    assert "nexus-test1" in result["detail"]
    assert "2/2 replicas" in result["detail"]


@pytest.mark.asyncio
async def test_check_operator_status_fresh_cluster():
    """No Deployment, no namespace, no CRD = brand-new cluster."""
    svc = _service()
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = _api_404()

    core_v1 = MagicMock()
    core_v1.read_namespace.side_effect = _api_404()

    async def fake_clients(_):
        return core_v1, apps_v1, MagicMock()

    svc._get_k8s_clients = fake_clients  # type: ignore

    # Patch CRD probe to return 404 too
    with patch("app.services.operator_deployment_service.k8s_client", create=True), \
         patch("kubernetes.client.ApiextensionsV1Api") as ext_cls:
        ext_cls.return_value.read_custom_resource_definition.side_effect = _api_404()

        result = await svc.check_operator_status("nexus-test1")

    assert result["installed"] is False
    assert result["status"] == "not_installed"
    assert result["namespace_exists"] is False
    assert result["crd_exists"] is False
    assert "fresh cluster" in result["detail"].lower()


@pytest.mark.asyncio
async def test_check_operator_status_partial_cleanup():
    """Deployment 404 but namespace + CRD still on the cluster."""
    svc = _service()
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = _api_404()

    core_v1 = MagicMock()
    core_v1.read_namespace.return_value = MagicMock()  # namespace EXISTS

    async def fake_clients(_):
        return core_v1, apps_v1, MagicMock()

    svc._get_k8s_clients = fake_clients  # type: ignore

    with patch("kubernetes.client.ApiextensionsV1Api") as ext_cls:
        ext_cls.return_value.read_custom_resource_definition.return_value = MagicMock()  # CRD exists

        result = await svc.check_operator_status("nexus-test1")

    assert result["installed"] is False
    assert result["status"] == "not_installed"
    assert result["namespace_exists"] is True
    assert result["crd_exists"] is True
    assert "partial cleanup" in result["detail"].lower()


@pytest.mark.asyncio
async def test_check_operator_status_unknown_when_cluster_unreachable():
    svc = _service()

    async def fake_clients(_):
        raise RuntimeError("kubeconfig invalid")

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.check_operator_status("nexus-test1")
    assert result["installed"] is False
    assert result["status"] == "unknown"
    assert "kubeconfig invalid" in result["detail"]


@pytest.mark.asyncio
async def test_check_operator_status_403_returns_unknown_with_detail():
    """A 403 from the cluster API must NOT be misreported as not_installed."""
    from kubernetes.client.rest import ApiException

    svc = _service()
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = ApiException(status=403, reason="Forbidden")

    async def fake_clients(_):
        return MagicMock(), apps_v1, MagicMock()

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.check_operator_status("nexus-test1")
    assert result["installed"] is False
    assert result["status"] == "unknown"
    assert "403" in result["detail"]
