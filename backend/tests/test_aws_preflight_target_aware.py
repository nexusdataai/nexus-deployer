"""
Tests for /api/aws/verify-permissions-detailed deployment-target gating.

When `deployment_target == "pure_eks"`, the response service matrix must
exclude the ECS / ALB / Application Auto Scaling / CloudFront / WAF /
CloudFormation entries; the operator owns those resources and the user's
IAM principal does not need them.
"""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Defer app import so test collection does not pull every router on
    # environments that lack runtime deps (e.g. AWS SDK extras).
    from app.main import app
    return TestClient(app)


def _patch_session(account_id="123456789012", region="us-east-1"):
    """Stub out the AWS session lookup so the endpoint passes auth."""
    fake_creds = {
        "aws_access_key_id": "x",
        "aws_secret_access_key": "y",
        "aws_session_token": "z",
    }
    return patch(
        "app.services.aws_session_manager.aws_session_manager.get_credentials_dict",
        return_value=fake_creds,
    )


@pytest.mark.parametrize(
    "deployment_target,excluded",
    [
        (
            "pure_eks",
            {
                "CloudFormation",
                "CloudFront",
                "WAF",
                "ECS",
                "ALB",
                "Application Auto Scaling",
            },
        ),
        ("ecs_cloudformation", set()),
    ],
)
def test_verify_permissions_filters_by_deployment_target(client, deployment_target, excluded):
    # The endpoint runs every probe; stub them all to "OK" so the response
    # is deterministic and we only assert on the service catalogue shape.
    fake_client = MagicMock()
    fake_client.list_stacks.return_value = {"StackSummaries": []}
    fake_client.list_buckets.return_value = {"Buckets": []}
    fake_client.list_distributions.return_value = {"DistributionList": {}}
    fake_client.list_web_acls.return_value = {"WebACLs": []}
    fake_client.list_certificates.return_value = {"CertificateSummaryList": []}
    fake_client.list_hosted_zones.return_value = {"HostedZones": []}
    fake_client.describe_vpcs.return_value = {"Vpcs": []}
    fake_client.describe_security_groups.return_value = {"SecurityGroups": []}
    fake_client.list_clusters.return_value = {"clusterArns": []}
    fake_client.describe_repositories.return_value = {"repositories": []}
    fake_client.describe_load_balancers.return_value = {"LoadBalancers": []}
    fake_client.list_roles.return_value = {"Roles": []}
    fake_client.list_tables.return_value = {"TableNames": []}
    fake_client.list_secrets.return_value = {"SecretList": []}
    fake_client.list_keys.return_value = {"Keys": []}
    fake_client.describe_log_groups.return_value = {"logGroups": []}
    fake_client.describe_scalable_targets.return_value = {"ScalableTargets": []}

    with _patch_session(), patch("boto3.client", return_value=fake_client):
        body = {
            "aws_session_id": "session-id",
            "region": "us-east-1",
            "account_id": "123456789012",
            "deployment_target": deployment_target,
        }
        res = client.post("/api/aws/verify-permissions-detailed", json=body)

    assert res.status_code == 200, res.text
    services = {s["service"] for s in res.json()["services"]}
    for forbidden in excluded:
        assert forbidden not in services, f"{forbidden} should be excluded for {deployment_target}"
    if deployment_target == "ecs_cloudformation":
        assert {"ECS", "ALB", "CloudFormation"}.issubset(services)


def test_verify_limits_rejects_pure_eks(client):
    """verify-limits is ECS-only; reject pure_eks loudly."""
    with _patch_session():
        res = client.post(
            "/api/aws/verify-limits",
            json={
                "aws_session_id": "session-id",
                "region": "us-east-1",
                "deployment_target": "pure_eks",
            },
        )
    assert res.status_code == 400
    assert "Pure EKS" in res.json()["detail"]
