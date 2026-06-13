"""
Tests for the PDB reconciler.
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
    from nexus_operator.resources.pdb import PDBReconciler
    with patch("nexus_operator.resources.pdb.client.PolicyV1Api") as api_cls:
        rec = PDBReconciler(namespace="myapp-dev")
        rec.policy_api = api_cls.return_value
    return rec


def test_disabled_pdb_deletes_existing(naming):
    rec = _make_reconciler()
    rec.policy_api.delete_namespaced_pod_disruption_budget.return_value = MagicMock()
    result = rec.reconcile(naming, pdb_spec={"enabled": False}, targets=["backend"])
    assert result["deleted"] or result["skipped"]


def test_enabled_pdb_with_min_available_creates(naming):
    rec = _make_reconciler()
    rec.policy_api.create_namespaced_pod_disruption_budget.return_value = MagicMock()

    result = rec.reconcile(
        naming, pdb_spec={"enabled": True, "minAvailable": 2}, targets=["backend"],
    )
    assert len(result["created"]) == 1
    body = rec.policy_api.create_namespaced_pod_disruption_budget.call_args.kwargs["body"]
    assert body.spec.min_available == 2
    assert body.spec.max_unavailable is None


def test_pdb_mutual_exclusion_raises(naming):
    rec = _make_reconciler()
    with pytest.raises(ValueError, match="mutually exclusive"):
        rec.reconcile(
            naming,
            pdb_spec={"enabled": True, "minAvailable": 1, "maxUnavailable": 1},
            targets=["backend"],
        )


def test_pdb_default_min_available_when_neither_set(naming):
    rec = _make_reconciler()
    rec.policy_api.create_namespaced_pod_disruption_budget.return_value = MagicMock()
    rec.reconcile(naming, pdb_spec={"enabled": True}, targets=["backend"])
    body = rec.policy_api.create_namespaced_pod_disruption_budget.call_args.kwargs["body"]
    assert body.spec.min_available == 1
