"""Tests for KEDA ScaledObject reconciler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from nexus_operator.resources.keda import KedaReconciler
from nexus_operator.utils.naming import ResourceNaming


@pytest.fixture
def naming() -> ResourceNaming:
    return ResourceNaming(capability_name="ai-engine", environment="local")


def test_keda_reconcile_disabled_deletes(naming: ResourceNaming) -> None:
    rec = KedaReconciler(namespace="ai-engine-local")
    rec.custom_api = MagicMock()
    rec.custom_api.delete_namespaced_custom_object.return_value = {}
    result = rec.reconcile(naming, {"enabled": False}, redis_service="redis-svc")
    assert "deleted" in result or "skipped" in result


def test_keda_reconcile_creates(naming: ResourceNaming) -> None:
    rec = KedaReconciler(namespace="ai-engine-local")
    rec.custom_api = MagicMock()
    rec.custom_api.create_namespaced_custom_object.return_value = {}
    result = rec.reconcile(
        naming,
        {
            "enabled": True,
            "replicas": 1,
            "autoscaling": {"enabled": True, "minReplicas": 1, "maxReplicas": 5, "lagThreshold": 3},
        },
        redis_service="redis-svc",
    )
    assert "created" in result
    body = rec.custom_api.create_namespaced_custom_object.call_args.kwargs["body"]
    assert body["spec"]["triggers"][0]["type"] == "redis-streams"
    assert body["spec"]["triggers"][0]["metadata"]["lagCount"] == "3"
    behavior = body["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]
    assert behavior["scaleUp"]["policies"][0] == {"type": "Pods", "value": 2, "periodSeconds": 30}
    assert behavior["scaleDown"]["policies"][0] == {"type": "Pods", "value": 1, "periodSeconds": 60}


def test_keda_reconcile_invalid_min_max(naming: ResourceNaming) -> None:
    rec = KedaReconciler(namespace="ai-engine-local")
    with pytest.raises(ValueError):
        rec.reconcile(
            naming,
            {
                "enabled": True,
                "autoscaling": {"enabled": True, "minReplicas": 5, "maxReplicas": 2},
            },
            redis_service="redis-svc",
        )
