"""
Tests for the Pure-EKS branch of DeploymentOrchestrator.deploy_capability.

The Pure-EKS path must NEVER reach the CloudFormation STACK_ORDER loop.
We assert that by mocking cfn_service and checking it was never called,
and by asserting the operator_deployment_service was driven instead.
"""
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.models.deployment import DeploymentTarget
from app.services.deployment_orchestrator import DeploymentOrchestrator


def _make_orchestrator():
    # Avoid hitting AWS during construction. PreDeploymentValidator is
    # imported lazily inside __init__, so we patch it at its source module.
    with patch("app.services.deployment_orchestrator.CloudFormationDeploymentService"), \
         patch("app.services.deployment_orchestrator.S3UploadService"), \
         patch("app.services.deployment_orchestrator.CleanupService"), \
         patch("app.services.pre_deployment_validator.PreDeploymentValidator"):
        return DeploymentOrchestrator(credentials={})


def test_pure_eks_skips_cloudformation_stack_loop():
    """deploy_capability(target=PURE_EKS) must not iterate STACK_ORDER."""
    orchestrator = _make_orchestrator()

    config = {
        "capability": {"name": "nexus-ai", "version": "1.2.0"},
        "target": {"environment": "dev", "region": "us-east-1"},
        "frontend": {"image": "f:1"},
        "backend": {"image": "b:1"},
    }

    fake_create_cr = AsyncMock(return_value={
        "success": True,
        "cr_name": "nexus-ai-dev",
        "namespace": "default",
        "message": "ok",
    })
    fake_status = AsyncMock(return_value={
        "phase": "Ready",
        "message": "operator says ready",
        "frontend_url": "https://frontend",
        "backend_url": "https://backend",
        "resources": [{"type": "Deployment", "name": "x", "status": "created"}],
    })
    fake_operator = MagicMock()
    fake_operator.create_capability_cr = fake_create_cr
    fake_operator.get_capability_status = fake_status

    with patch(
        "app.services.operator_deployment_service.get_operator_deployment_service",
        return_value=fake_operator,
    ):
        result = orchestrator.deploy_capability(
            config,
            deploy_frontend=True,
            deploy_backend=True,
            callback=None,
            deployment_target=DeploymentTarget.PURE_EKS,
            eks_cluster_name="my-cluster",
            eks_namespace="myapp-dev",
        )

    assert result["success"] is True
    assert result["deployment_target"] == "pure_eks"
    assert result["eks_cluster_name"] == "my-cluster"
    assert result["eks_namespace"] == "myapp-dev"
    assert result["frontend_url"] == "https://frontend"
    assert result["backend_url"] == "https://backend"

    # The cfn_service mock was created during __init__; assert nothing was
    # invoked on it during the Pure-EKS branch.
    assert not orchestrator.cfn_service.create_or_update_stack.called

    # The operator path was used.
    fake_create_cr.assert_awaited_once()
    fake_status.assert_awaited()


def test_pure_eks_requires_cluster_name():
    orchestrator = _make_orchestrator()
    result = orchestrator.deploy_capability(
        {"capability": {"name": "x", "version": "1"}, "target": {"environment": "dev", "region": "us-east-1"}},
        deployment_target=DeploymentTarget.PURE_EKS,
        eks_cluster_name=None,
    )
    assert result["success"] is False
    assert "eks_cluster_name" in result["error"]


def test_default_target_uses_cloudformation_path():
    """Without an explicit target, deploy_capability must NOT enter the
    Pure-EKS branch; it should fall through to the (mocked) CFN logic."""
    orchestrator = _make_orchestrator()
    orchestrator.cfn_service.STACK_ORDER = []  # short-circuit the loop
    orchestrator.cfn_service.create_or_update_stack = MagicMock(return_value=(True, None))
    orchestrator.cfn_service.get_stack_outputs = MagicMock(return_value={})
    orchestrator.template_validator.validate_templates = MagicMock(
        return_value=MagicMock(success=True, missing_templates=[], integrity_issues=[], to_dict=lambda: {})
    )

    config = {
        "capability": {"name": "nexus-ai", "version": "1.2.0"},
        "target": {"environment": "dev", "region": "us-east-1"},
    }
    # We don't care about completion; we only want to assert the early
    # branch did not fire (so the function did real CFN-side work, even
    # if subsequent steps fail). Catch and ignore errors past the branch.
    try:
        orchestrator.deploy_capability(config, skip_validation=True)
    except Exception:
        pass

    # The orchestrator should have at least touched template_validator,
    # which is exclusive to the CFN path.
    assert orchestrator.template_validator.validate_templates.called
