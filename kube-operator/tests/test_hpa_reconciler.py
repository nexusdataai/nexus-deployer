"""
Tests for the HPA reconciler.

Run from kube-operator/ with `pytest` (the existing tests/ dir adds src/
to sys.path the same way).
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def naming():
    from nexus_operator.utils.naming import ResourceNaming
    return ResourceNaming(capability_name="myapp", environment="dev", account_id="123")


def _make_reconciler():
    from nexus_operator.resources.hpa import HPAReconciler
    with patch("nexus_operator.resources.hpa.client.AutoscalingV2Api") as api_cls:
        rec = HPAReconciler(namespace="myapp-dev")
        rec.autoscaling_api = api_cls.return_value
    return rec


def test_disabled_hpa_deletes_existing(naming):
    rec = _make_reconciler()
    rec.autoscaling_api.delete_namespaced_horizontal_pod_autoscaler.return_value = MagicMock()

    result = rec.reconcile(naming, hpa_spec={"enabled": False}, targets=["backend"])

    assert result["deleted"] or result["skipped"]
    rec.autoscaling_api.delete_namespaced_horizontal_pod_autoscaler.assert_called_once()


def test_enabled_hpa_creates_resource(naming):
    rec = _make_reconciler()
    rec.autoscaling_api.create_namespaced_horizontal_pod_autoscaler.return_value = MagicMock()

    result = rec.reconcile(
        naming,
        hpa_spec={
            "enabled": True,
            "minReplicas": 2,
            "maxReplicas": 10,
            "targetCPUUtilization": 65,
        },
        targets=["backend"],
    )

    assert len(result["created"]) == 1
    rec.autoscaling_api.create_namespaced_horizontal_pod_autoscaler.assert_called_once()
    body = rec.autoscaling_api.create_namespaced_horizontal_pod_autoscaler.call_args.kwargs["body"]
    assert body.spec.min_replicas == 2
    assert body.spec.max_replicas == 10
    cpu_metric = body.spec.metrics[0]
    assert cpu_metric.resource.target.average_utilization == 65


def test_hpa_min_gt_max_raises(naming):
    rec = _make_reconciler()
    with pytest.raises(ValueError, match="minReplicas"):
        rec.reconcile(
            naming,
            hpa_spec={"enabled": True, "minReplicas": 10, "maxReplicas": 2},
            targets=["backend"],
        )


def test_hpa_existing_object_is_patched(naming):
    rec = _make_reconciler()
    from kubernetes.client.rest import ApiException

    rec.autoscaling_api.create_namespaced_horizontal_pod_autoscaler.side_effect = ApiException(status=409)
    rec.autoscaling_api.patch_namespaced_horizontal_pod_autoscaler.return_value = MagicMock()

    result = rec.reconcile(
        naming,
        hpa_spec={"enabled": True, "minReplicas": 1, "maxReplicas": 3, "targetCPUUtilization": 70},
        targets=["backend"],
    )
    assert len(result["patched"]) == 1
    rec.autoscaling_api.patch_namespaced_horizontal_pod_autoscaler.assert_called_once()
