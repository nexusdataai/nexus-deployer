"""
Tests for EksPipelineOrchestrator.step1_cluster_readiness.

Stubs out boto3 + the K8s clients via the OperatorDeploymentService
attribute, then asserts the report aggregates the 10 checks correctly
and the overall verdict reflects the worst severity.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_orchestrator(tmp_session: MagicMock):
    """Construct an orchestrator whose operator_service is a MagicMock."""
    from app.services.eks_pipeline_orchestrator import EksPipelineOrchestrator

    orch = EksPipelineOrchestrator(aws_session_id=None, region="us-east-1")
    orch._op_service = tmp_session  # type: ignore[assignment]
    return orch


def _ok_cluster_describe(version: str = "1.29", oidc: bool = True):
    cluster = {
        "status": "ACTIVE",
        "version": version,
        "endpoint": "https://example.eks.amazonaws.com",
        "identity": {"oidc": {"issuer": "https://oidc.eks.us-east-1.amazonaws.com/id/ABC123"}}
        if oidc
        else {},
        "accessConfig": {"authenticationMode": "API"},
    }
    return {"cluster": cluster}


@pytest.mark.asyncio
async def test_step1_happy_path_returns_pass():
    ops = MagicMock()
    ops.region = "us-east-1"
    ops.aws_session_id = None

    ops.eks_client = MagicMock()
    ops.eks_client.describe_cluster.return_value = _ok_cluster_describe()
    ops.eks_client.describe_access_entry.return_value = {"accessEntry": {"type": "STANDARD"}}
    ops.eks_client.list_associated_access_policies.return_value = {
        "associatedAccessPolicies": [{"policyArn": "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"}]
    }
    ops.eks_client.list_nodegroups.return_value = {"nodegroups": ["ng-1"]}
    ops.eks_client.describe_nodegroup.return_value = {
        "nodegroup": {
            "status": "ACTIVE",
            "scalingConfig": {"desiredSize": 2},
            "nodeRole": "arn:aws:iam::1:role/ng-role",
        }
    }

    ops.iam_client = MagicMock()
    ops.iam_client.get_open_id_connect_provider.return_value = {
        "ThumbprintList": ["abc"],
        "ClientIDList": ["sts.amazonaws.com"],
    }
    ops.iam_client.list_attached_role_policies.return_value = {
        "AttachedPolicies": [
            {"PolicyArn": "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"},
            {"PolicyArn": "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"},
            {"PolicyArn": "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"},
        ]
    }

    ops.sts_client = MagicMock()
    ops.sts_client.get_caller_identity.return_value = {
        "Account": "111122223333",
        "Arn": "arn:aws:iam::111122223333:role/Deployer",
    }

    # K8s checks return success
    ops._get_k8s_clients = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    ops.check_alb_controller_installed = AsyncMock(return_value={
        "installed": True, "ready_replicas": 2, "version": "v2.7.2",
        "message": "aws-load-balancer-controller ready",
    })
    ops.check_operator_status = AsyncMock(return_value={
        "installed": True, "status": "installed",
        "version": "1.0.0", "namespace": "totogi-system",
        "ready_replicas": 1, "desired_replicas": 1,
        "detail": "Operator running",
    })

    orch = _make_orchestrator(ops)
    report = await orch.step1_cluster_readiness("nexus-test1", iam_mode="managed")

    names = {c.name for c in report.checks}
    assert {
        "cluster_active", "oidc_provider", "operator_iam_role",
        "auth_mode", "access_entry", "node_groups",
        "ecr_operator_image", "k8s_api_access",
        "alb_controller", "operator_status",
    }.issubset(names)
    assert report.overall in ("pass", "warn")
    assert report.can_proceed is True


@pytest.mark.asyncio
async def test_step1_missing_oidc_provider_fails_fast():
    ops = MagicMock()
    ops.region = "us-east-1"
    ops.aws_session_id = None

    ops.eks_client = MagicMock()
    ops.eks_client.describe_cluster.return_value = _ok_cluster_describe(oidc=False)
    ops.iam_client = MagicMock()
    ops.sts_client = MagicMock()
    ops.sts_client.get_caller_identity.return_value = {
        "Account": "111", "Arn": "arn:aws:iam::111:role/Deployer",
    }
    ops._get_k8s_clients = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    ops.check_alb_controller_installed = AsyncMock(return_value={"installed": False, "message": ""})
    ops.check_operator_status = AsyncMock(return_value={"installed": False, "status": "not_installed", "namespace": "totogi-system"})

    orch = _make_orchestrator(ops)
    report = await orch.step1_cluster_readiness("nexus-test1", iam_mode="managed")
    oidc = next(c for c in report.checks if c.name == "oidc_provider")
    assert oidc.status == "fail"
    assert report.can_proceed is False


@pytest.mark.asyncio
async def test_step1_preprovisioned_missing_operator_role_is_fail():
    from botocore.exceptions import ClientError

    ops = MagicMock()
    ops.region = "us-east-1"
    ops.aws_session_id = None
    ops.eks_client = MagicMock()
    ops.eks_client.describe_cluster.return_value = _ok_cluster_describe()
    ops.eks_client.describe_access_entry.return_value = {"accessEntry": {"type": "STANDARD"}}
    ops.eks_client.list_associated_access_policies.return_value = {"associatedAccessPolicies": []}
    ops.eks_client.list_nodegroups.return_value = {"nodegroups": []}
    ops.iam_client = MagicMock()
    ops.iam_client.get_open_id_connect_provider.return_value = {
        "ThumbprintList": ["abc"], "ClientIDList": ["sts.amazonaws.com"],
    }
    ops.iam_client.get_role.side_effect = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "not found"}}, "GetRole",
    )
    ops.sts_client = MagicMock()
    ops.sts_client.get_caller_identity.return_value = {
        "Account": "111", "Arn": "arn:aws:iam::111:role/Deployer",
    }
    ops._get_k8s_clients = AsyncMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    ops.check_alb_controller_installed = AsyncMock(return_value={"installed": True, "message": ""})
    ops.check_operator_status = AsyncMock(return_value={"installed": False, "status": "not_installed", "namespace": "totogi-system"})

    orch = _make_orchestrator(ops)
    report = await orch.step1_cluster_readiness("nexus-test1", iam_mode="preprovisioned")
    op_role = next(c for c in report.checks if c.name == "operator_iam_role")
    assert op_role.status == "fail"
    assert report.can_proceed is False
