"""
Tests for OperatorDeploymentService.get_capability_diagnostics.

When the operator's CR phase is stuck on something like `DeployingBackend`
the user needs pod-level visibility (ImagePullBackOff, CrashLoopBackOff,
Pending) without leaving the wizard. These tests assert the diagnostics
method returns the right shape so the frontend can render it.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.operator_deployment_service import OperatorDeploymentService


def _service():
    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None
    return svc


def _fake_deployment(name: str, ready: int, desired: int, image: str, conditions=None):
    cond_objs = []
    for cond in (conditions or []):
        cond_objs.append(SimpleNamespace(
            type=cond.get("type", "Available"),
            status=cond.get("status", "False"),
            reason=cond.get("reason", ""),
            message=cond.get("message", ""),
        ))
    return SimpleNamespace(
        spec=SimpleNamespace(
            replicas=desired,
            selector=SimpleNamespace(match_labels={"app": name}),
            template=SimpleNamespace(spec=SimpleNamespace(
                containers=[SimpleNamespace(image=image)],
            )),
        ),
        status=SimpleNamespace(
            ready_replicas=ready,
            available_replicas=ready,
            updated_replicas=desired,
            conditions=cond_objs,
        ),
    )


def _fake_pod(name: str, phase: str, waiting_reason: str = "", waiting_message: str = "", restart_count: int = 0):
    waiting = None
    if waiting_reason:
        waiting = SimpleNamespace(reason=waiting_reason, message=waiting_message)
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        status=SimpleNamespace(
            phase=phase,
            container_statuses=[SimpleNamespace(
                state=SimpleNamespace(waiting=waiting),
                restart_count=restart_count,
            )],
        ),
    )


def _fake_event(reason: str, msg: str, etype: str = "Warning", kind: str = "Pod", name: str = "x"):
    import datetime as dt
    return SimpleNamespace(
        reason=reason,
        message=msg,
        type=etype,
        last_timestamp=dt.datetime.utcnow(),
        event_time=None,
        metadata=SimpleNamespace(creation_timestamp=dt.datetime.utcnow()),
        involved_object=SimpleNamespace(kind=kind, name=name),
    )


@pytest.mark.asyncio
async def test_diagnostics_reports_image_pull_backoff():
    svc = _service()

    backend_dep = _fake_deployment(
        name="nexus-ai-test-backend",
        ready=0, desired=2,
        image="123.dkr.ecr.us-east-1.amazonaws.com/ai-job-engine:dev",
        conditions=[{"type": "Available", "status": "False", "reason": "MinimumReplicasUnavailable",
                     "message": "Deployment does not have minimum availability."}],
    )

    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = lambda name, namespace: (
        backend_dep if name == "nexus-ai-test-backend"
        else (_ for _ in ()).throw(_api_404())
    )

    pod = _fake_pod(
        name="nexus-ai-test-backend-abc",
        phase="Pending",
        waiting_reason="ImagePullBackOff",
        waiting_message="Back-off pulling image",
    )
    core_v1 = MagicMock()
    core_v1.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])
    core_v1.list_namespaced_event.return_value = SimpleNamespace(items=[
        _fake_event("Failed", "Failed to pull image \"...:dev\": access denied"),
    ])

    async def fake_clients(_):
        return core_v1, apps_v1, MagicMock()

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_diagnostics(
        cluster_name="c",
        namespace="nexus-ai-test",
        capability_name="nexus-ai",
        environment="test",
    )

    assert "deployments" in result and len(result["deployments"]) == 1
    dep = result["deployments"][0]
    assert dep["name"] == "nexus-ai-test-backend"
    assert dep["ready_replicas"] == 0
    assert dep["desired_replicas"] == 2
    assert any("Available=False" in c for c in dep["conditions"])
    assert dep["pods"][0]["waiting_reason"] == "ImagePullBackOff"
    assert any("Failed to pull image" in e for e in result["events"])


@pytest.mark.asyncio
async def test_diagnostics_skips_missing_components():
    """Frontend / bssmagic deployments may legitimately not exist for
    capabilities that don't deploy them. They must be silently skipped,
    not surfaced as an error."""
    svc = _service()

    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment.side_effect = _api_404()
    core_v1 = MagicMock()
    core_v1.list_namespaced_event.return_value = SimpleNamespace(items=[])

    async def fake_clients(_):
        return core_v1, apps_v1, MagicMock()

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_diagnostics(
        cluster_name="c",
        namespace="nexus-ai-test",
        capability_name="nexus-ai",
        environment="test",
    )

    assert result == {"deployments": [], "events": []}


@pytest.mark.asyncio
async def test_diagnostics_returns_error_when_cluster_unreachable():
    svc = _service()

    async def fake_clients(_):
        raise RuntimeError("Cluster API unreachable: 401")

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.get_capability_diagnostics(
        cluster_name="c",
        namespace="ns",
        capability_name="nexus-ai",
        environment="test",
    )
    assert "Cluster API unreachable" in result.get("error", "")


# ------- helpers ------------------------------------------------------------

def _api_404():
    from kubernetes.client.rest import ApiException
    return ApiException(status=404, reason="Not Found")
