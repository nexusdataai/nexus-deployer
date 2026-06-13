"""
Tests for label-value sanitization in OperatorDeploymentService.

The wizard observed an HTTP 422 from kube-apiserver when the deployer was
fed `capability_name="Call Processing"` (with a space) - Kubernetes label
values reject anything outside `[A-Za-z0-9._-]` and must be alphanumeric
at start/end. The fix is twofold: the frontend now sends `capability.id`
(DNS-safe) instead of `capability.name`, AND the backend defensively
sanitizes anything it puts into label values or object names.

These tests exercise the backend defense.
"""
from unittest.mock import MagicMock

import pytest

from app.services.operator_deployment_service import (
    OperatorDeploymentService,
    _sanitize_label_value,
)


def test_sanitize_label_value_replaces_spaces():
    assert _sanitize_label_value("Call Processing") == "nexus-ai"


def test_sanitize_label_value_strips_leading_trailing_dashes():
    assert _sanitize_label_value("  Foo Bar  ") == "foo-bar"


def test_sanitize_label_value_truncates_to_63():
    long = "x" * 100
    out = _sanitize_label_value(long)
    assert len(out) <= 63
    assert out == "x" * 63


def test_sanitize_label_value_falls_back_when_empty():
    assert _sanitize_label_value("", "fallback") == "fallback"
    assert _sanitize_label_value("   ", "fallback") == "fallback"
    assert _sanitize_label_value("...", "fallback") == "fallback"


def test_sanitize_label_value_keeps_valid_chars():
    assert _sanitize_label_value("nexus-ai-v2.5_beta") == "nexus-ai-v2.5_beta"


@pytest.mark.asyncio
async def test_namespace_creation_uses_sanitized_labels(monkeypatch, tmp_path):
    """When a stale client passes the raw display name, the deployer
    must still produce a valid V1Namespace body with sanitized labels."""
    from kubernetes.client.rest import ApiException

    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None

    core = MagicMock()
    # Pretend the namespace doesn't exist
    core.read_namespace.side_effect = ApiException(status=404, reason="Not Found")
    custom = MagicMock()

    async def fake_clients(_):
        return core, MagicMock(), custom

    svc._get_k8s_clients = fake_clients  # type: ignore

    result = await svc.create_capability_cr(
        cluster_name="c",
        capability_name="Call Processing",  # the failing input
        capability_version="1.2.0",
        environment="test",
        namespace="nexus-ai-test",
        config={},
    )
    assert result["success"] is True

    body = core.create_namespace.call_args.args[0]
    assert body.metadata.labels["totogi.com/capability"] == "nexus-ai"
    assert body.metadata.labels["totogi.com/environment"] == "test"

    # The CR body should also use sanitized values for spec and labels.
    cr_body = custom.create_namespaced_custom_object.call_args.kwargs["body"]
    assert cr_body["spec"]["capabilityName"] == "nexus-ai"
    assert cr_body["metadata"]["labels"]["app.kubernetes.io/name"] == "nexus-ai"
    # CR object name is also sanitized (DNS-1123 subdomain rules)
    assert cr_body["metadata"]["name"] == "nexus-ai-test"
