"""
Tests for OperatorDeploymentService.create_capability_cr.

Ensures the CR body shape matches the NexusCapability CRD: required spec
keys are present, optional keys round-trip when supplied, unknown config
keys are not blindly forwarded.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.operator_deployment_service import OperatorDeploymentService


@pytest.fixture
def service():
    # Bypass __init__ so we don't hit AWS or kubeconfig
    svc = OperatorDeploymentService.__new__(OperatorDeploymentService)
    svc.region = "us-east-1"
    svc.aws_session_id = None
    return svc


@pytest.mark.asyncio
async def test_create_capability_cr_builds_full_spec(service):
    captured = {}

    custom = MagicMock()

    def fake_create(group, version, namespace, plural, body):
        captured["body"] = body
        return body

    custom.create_namespaced_custom_object.side_effect = fake_create

    async def fake_clients(_cluster):
        return MagicMock(), MagicMock(), custom

    service._get_k8s_clients = fake_clients  # type: ignore

    result = await service.create_capability_cr(
        cluster_name="my-cluster",
        capability_name="nexus-ai",
        capability_version="1.2.0",
        environment="dev",
        namespace="myapp-dev",
        config={
            "region": "us-east-1",
            "deletionPolicy": "Retain",
            "frontend": {"image": "front:1", "replicas": 3},
            "backend": {"image": "back:1", "replicas": 2},
            "dataServices": {
                "dynamodb": {"enabled": True},
                "s3": {"enabled": False},
                "glue": {"enabled": True},
            },
            "enableCognito": True,
            "adminEmail": "ops@example.com",
            "cognito": {
                "frontendUrl": "https://app.example.com",
                "callbackUrls": ["https://app.example.com/cb"],
            },
            "ingress": {"enabled": True, "scheme": "internet-facing"},
            "internalIngress": {"enabled": True, "httpsOnly": True},
            "hpa": {"enabled": True, "minReplicas": 2, "maxReplicas": 10, "targetCPUUtilization": 70},
            "pdb": {"enabled": True, "minAvailable": 1},
            "bssmagic": {"enabled": False},
            # Unknown key - must NOT be forwarded into spec
            "totallyMadeUpKnob": "ignore-me",
        },
    )

    assert result["success"] is True
    body = captured["body"]
    assert body["apiVersion"] == "nexus.ai/v1"
    assert body["kind"] == "NexusCapability"
    assert body["metadata"]["name"] == "nexus-ai-dev"
    assert body["metadata"]["namespace"] == "myapp-dev"

    spec = body["spec"]
    assert spec["capabilityName"] == "nexus-ai"
    assert spec["version"] == "1.2.0"
    assert spec["environment"] == "dev"
    assert spec["region"] == "us-east-1"
    assert spec["deletionPolicy"] == "Retain"
    assert spec["frontend"] == {"image": "front:1", "replicas": 3}
    assert spec["backend"] == {"image": "back:1", "replicas": 2}
    assert spec["dataServices"]["s3"] == {"enabled": False}
    assert spec["enableCognito"] is True
    assert spec["adminEmail"] == "ops@example.com"
    assert spec["cognito"]["callbackUrls"] == ["https://app.example.com/cb"]
    assert spec["ingress"]["scheme"] == "internet-facing"
    assert spec["internalIngress"]["httpsOnly"] is True
    assert spec["hpa"]["maxReplicas"] == 10
    assert spec["pdb"]["minAvailable"] == 1
    assert spec["bssmagic"] == {"enabled": False}
    assert "totallyMadeUpKnob" not in spec


@pytest.mark.asyncio
async def test_create_capability_cr_minimal(service):
    """Minimal config should still produce a valid spec with required keys."""
    custom = MagicMock()
    captured = {}

    def fake_create(group, version, namespace, plural, body):
        captured["body"] = body
        return body

    custom.create_namespaced_custom_object.side_effect = fake_create

    async def fake_clients(_cluster):
        return MagicMock(), MagicMock(), custom

    service._get_k8s_clients = fake_clients  # type: ignore

    await service.create_capability_cr(
        cluster_name="c",
        capability_name="bare",
        capability_version="0.1.0",
        environment="test",
        namespace="default",
        config={},
    )

    spec = captured["body"]["spec"]
    # Required CRD fields present
    for key in ("capabilityName", "version", "environment", "region", "deletionPolicy", "frontend", "backend", "dataServices"):
        assert key in spec, f"Missing required spec key: {key}"
    # Default region falls back to service region
    assert spec["region"] == "us-east-1"
    # Optional blocks not present when caller did not supply them
    for key in ("enableCognito", "adminEmail", "cognito", "bssmagic", "ingress", "internalIngress", "hpa", "pdb"):
        assert key not in spec, f"Optional spec key {key} should be omitted"
