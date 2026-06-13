"""
Unit tests for the AWS access mode resolver, NetworkTopologyValidator, and
deploy_backend / deploy_bssmagic env-var injection.

These cover the AWS Access Dual Mode plan (Phase 1, operator side).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── _resolve_aws_access_mode ────────────────────────────────────────────


def test_resolve_returns_spec_value_when_cr_exists(monkeypatch):
    from nexus_operator.main import _resolve_aws_access_mode

    fake_api = MagicMock()
    fake_api.get_cluster_custom_object.return_value = {
        "spec": {"awsAccessMode": "lowest-cost"},
    }

    assert _resolve_aws_access_mode(fake_api) == "lowest-cost"


def test_resolve_falls_back_to_default_on_api_exception(monkeypatch):
    from kubernetes.client.rest import ApiException

    from nexus_operator.main import _resolve_aws_access_mode

    fake_api = MagicMock()
    fake_api.get_cluster_custom_object.side_effect = ApiException(status=404)

    monkeypatch.setenv("AWS_ACCESS_MODE_DEFAULT", "moderate")
    assert _resolve_aws_access_mode(fake_api) == "moderate"


def test_resolve_falls_back_when_default_env_missing(monkeypatch):
    from kubernetes.client.rest import ApiException

    from nexus_operator.main import _resolve_aws_access_mode

    fake_api = MagicMock()
    fake_api.get_cluster_custom_object.side_effect = ApiException(status=404)
    monkeypatch.delenv("AWS_ACCESS_MODE_DEFAULT", raising=False)

    assert _resolve_aws_access_mode(fake_api) == "higher-cost"


def test_resolve_rejects_invalid_mode(monkeypatch):
    from nexus_operator.main import _resolve_aws_access_mode

    fake_api = MagicMock()
    fake_api.get_cluster_custom_object.return_value = {
        "spec": {"awsAccessMode": "garbage"},
    }
    monkeypatch.delenv("AWS_ACCESS_MODE_DEFAULT", raising=False)

    # Invalid mode falls back to the default.
    assert _resolve_aws_access_mode(fake_api) == "higher-cost"


# ── NetworkTopologyValidator ────────────────────────────────────────────


def _make_validator(mode: str):
    """Builds a NetworkTopologyValidator with stubbed EC2/EKS clients."""
    from nexus_operator.resources.vpc_endpoints import NetworkTopologyValidator

    with patch("nexus_operator.resources.vpc_endpoints.vpc_boto3_client") as mk:
        validator = NetworkTopologyValidator(
            region="us-east-1", cluster_name="nexus-dev", mode=mode,
        )

    validator.ec2 = MagicMock()
    validator.eks = MagicMock()
    return validator


def _ep(svc_suffix: str, ep_type: str = "Interface", state: str = "available") -> Dict[str, Any]:
    return {
        "ServiceName": f"com.amazonaws.us-east-1.{svc_suffix}",
        "VpcEndpointId": f"vpce-{svc_suffix}",
        "VpcEndpointType": ep_type,
        "State": state,
    }


@pytest.mark.asyncio
async def test_validator_higher_cost_ok_when_all_endpoints_present():
    from nexus_operator.resources.vpc_endpoints import GATEWAY_SERVICES, INTERFACE_SERVICES

    validator = _make_validator("higher-cost")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1"]}}
    }
    validator.ec2.describe_vpcs.return_value = {
        "Vpcs": [{"Tags": [{"Key": "nexus:network-profile", "Value": "higher-cost"}]}]
    }
    paginator = MagicMock()
    paginator.paginate.return_value = [{
        "VpcEndpoints": [_ep(s, "Gateway") for s in GATEWAY_SERVICES] +
                        [_ep(s, "Interface") for s in INTERFACE_SERVICES],
    }]
    validator.ec2.get_paginator.return_value = paginator

    result = await validator.validate()
    assert result["validation"]["ok"] is True
    assert result["validation"]["expected"] == "higher-cost"
    assert result["validation"]["missing"] == []


@pytest.mark.asyncio
async def test_validator_higher_cost_reports_missing_interface_endpoint():
    from nexus_operator.resources.vpc_endpoints import GATEWAY_SERVICES

    validator = _make_validator("higher-cost")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1"]}}
    }
    validator.ec2.describe_vpcs.return_value = {"Vpcs": [{"Tags": []}]}
    paginator = MagicMock()
    # Only gateway endpoints present, no interface endpoints.
    paginator.paginate.return_value = [{
        "VpcEndpoints": [_ep(s, "Gateway") for s in GATEWAY_SERVICES],
    }]
    validator.ec2.get_paginator.return_value = paginator

    result = await validator.validate()
    assert result["validation"]["ok"] is False
    # Each missing interface service shows up in the missing list.
    assert any(m.startswith("interface:") for m in result["validation"]["missing"])


@pytest.mark.asyncio
async def test_validator_lowest_cost_ok_with_single_nat_and_gateway():
    from nexus_operator.resources.vpc_endpoints import GATEWAY_SERVICES

    validator = _make_validator("lowest-cost")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1"]}}
    }
    validator.ec2.describe_vpcs.return_value = {
        "Vpcs": [{"Tags": [{"Key": "nexus:network-profile", "Value": "lowest-cost"}]}]
    }
    paginator = MagicMock()
    paginator.paginate.return_value = [{
        "VpcEndpoints": [_ep(s, "Gateway") for s in GATEWAY_SERVICES],
    }]
    validator.ec2.get_paginator.return_value = paginator
    validator.ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": "i-nat-1"}]}],
    }
    # One private RT with default route through a NAT-tagged ENI.
    validator.ec2.describe_route_tables.return_value = {
        "RouteTables": [{
            "Routes": [{
                "DestinationCidrBlock": "0.0.0.0/0",
                "NetworkInterfaceId": "eni-nat-1",
            }],
        }],
    }
    validator.ec2.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [{
            "TagSet": [{"Key": "nexus:nat-instance", "Value": "true"}],
        }],
    }

    result = await validator.validate()
    assert result["validation"]["ok"] is True
    assert result["validation"]["missing"] == []


@pytest.mark.asyncio
async def test_validator_moderate_requires_two_nats():
    from nexus_operator.resources.vpc_endpoints import GATEWAY_SERVICES

    validator = _make_validator("moderate")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1"]}}
    }
    validator.ec2.describe_vpcs.return_value = {"Vpcs": [{"Tags": []}]}
    paginator = MagicMock()
    paginator.paginate.return_value = [{
        "VpcEndpoints": [_ep(s, "Gateway") for s in GATEWAY_SERVICES],
    }]
    validator.ec2.get_paginator.return_value = paginator
    # Only one NAT instance found, but moderate requires two.
    validator.ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": "i-nat-1"}]}],
    }
    validator.ec2.describe_route_tables.return_value = {
        "RouteTables": [{
            "Routes": [{
                "DestinationCidrBlock": "0.0.0.0/0",
                "NetworkInterfaceId": "eni-nat-1",
            }],
        }],
    }
    validator.ec2.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [{
            "TagSet": [{"Key": "nexus:nat-instance", "Value": "true"}],
        }],
    }

    result = await validator.validate()
    missing = result["validation"]["missing"]
    assert result["validation"]["ok"] is False
    assert any(m.startswith("nat-instance:expected=2") for m in missing)


@pytest.mark.asyncio
async def test_validator_public_nodes_requires_public_subnets():
    validator = _make_validator("public-nodes")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1", "sn-2"]}}
    }
    validator.ec2.describe_vpcs.return_value = {"Vpcs": [{"Tags": []}]}
    paginator = MagicMock()
    paginator.paginate.return_value = [{"VpcEndpoints": []}]
    validator.ec2.get_paginator.return_value = paginator
    # One subnet does NOT map public IPs on launch.
    validator.ec2.describe_subnets.return_value = {
        "Subnets": [
            {"SubnetId": "sn-1", "MapPublicIpOnLaunch": True},
            {"SubnetId": "sn-2", "MapPublicIpOnLaunch": False},
        ],
    }

    result = await validator.validate()
    assert result["validation"]["ok"] is False
    assert "subnets:not-all-public" in result["validation"]["missing"]


# ── B4 additions: positive public-nodes, drift detection, VPC-tag fallback ──


@pytest.mark.asyncio
async def test_validator_public_nodes_ok_when_all_subnets_public():
    """public-nodes profile: validator must accept absence of endpoints/NAT
    as the expected configuration, requiring only public subnets."""
    validator = _make_validator("public-nodes")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1", "sn-2"]}}
    }
    validator.ec2.describe_vpcs.return_value = {
        "Vpcs": [{"Tags": [{"Key": "nexus:network-profile", "Value": "public-nodes"}]}]
    }
    # No endpoints, no NAT — the expected public-nodes topology.
    paginator = MagicMock()
    paginator.paginate.return_value = [{"VpcEndpoints": []}]
    validator.ec2.get_paginator.return_value = paginator
    validator.ec2.describe_subnets.return_value = {
        "Subnets": [
            {"SubnetId": "sn-1", "MapPublicIpOnLaunch": True},
            {"SubnetId": "sn-2", "MapPublicIpOnLaunch": True},
        ],
    }

    result = await validator.validate()
    assert result["validation"]["ok"] is True
    assert result["validation"]["missing"] == []
    assert result["validation"]["expected"] == "public-nodes"
    assert result["actualProfileTag"] == "public-nodes"


@pytest.mark.asyncio
async def test_validator_drift_spec_says_moderate_but_tag_says_lowest_cost():
    """When the VPC tag disagrees with spec.awsAccessMode, the validator
    must surface the actual tag so the reconciler can report drift."""
    from nexus_operator.resources.vpc_endpoints import GATEWAY_SERVICES

    # spec mode is 'moderate'; cluster was actually built as 'lowest-cost'.
    validator = _make_validator("moderate")
    validator.eks.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1", "subnetIds": ["sn-1"]}}
    }
    validator.ec2.describe_vpcs.return_value = {
        "Vpcs": [{"Tags": [{"Key": "nexus:network-profile", "Value": "lowest-cost"}]}]
    }
    paginator = MagicMock()
    paginator.paginate.return_value = [{
        "VpcEndpoints": [_ep(s, "Gateway") for s in GATEWAY_SERVICES],
    }]
    validator.ec2.get_paginator.return_value = paginator
    # Only 1 NAT (matching lowest-cost), but spec says moderate -> drift.
    validator.ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": "i-nat-1"}]}],
    }
    validator.ec2.describe_route_tables.return_value = {
        "RouteTables": [{
            "Routes": [{
                "DestinationCidrBlock": "0.0.0.0/0",
                "NetworkInterfaceId": "eni-nat-1",
            }],
        }],
    }
    validator.ec2.describe_network_interfaces.return_value = {
        "NetworkInterfaces": [{"TagSet": [{"Key": "nexus:nat-instance", "Value": "true"}]}],
    }

    result = await validator.validate()
    # The validator surfaces the actual VPC tag so main.py can compare.
    assert result["actualProfileTag"] == "lowest-cost"
    # And it flags moderate's missing 2nd NAT.
    assert any(m.startswith("nat-instance:expected=2") for m in result["validation"]["missing"])


# ── read_vpc_profile_tag (the new B3 fallback helper) ────────────────────


def test_read_vpc_profile_tag_returns_value_when_tag_present(monkeypatch):
    from nexus_operator.resources.vpc_endpoints import read_vpc_profile_tag

    eks_client = MagicMock()
    eks_client.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1"}}
    }
    ec2_client = MagicMock()
    ec2_client.describe_vpcs.return_value = {
        "Vpcs": [{"Tags": [
            {"Key": "Name", "Value": "nexus-vpc"},
            {"Key": "nexus:network-profile", "Value": "moderate"},
        ]}]
    }

    def fake_client(service, region_name=None):
        return eks_client if service == "eks" else ec2_client

    monkeypatch.setattr(
        "nexus_operator.resources.vpc_endpoints.vpc_boto3_client", fake_client
    )

    assert read_vpc_profile_tag("us-east-1", "nexus-dev") == "moderate"


def test_read_vpc_profile_tag_returns_none_when_tag_absent(monkeypatch):
    from nexus_operator.resources.vpc_endpoints import read_vpc_profile_tag

    eks_client = MagicMock()
    eks_client.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1"}}
    }
    ec2_client = MagicMock()
    ec2_client.describe_vpcs.return_value = {"Vpcs": [{"Tags": []}]}

    def fake_client(service, region_name=None):
        return eks_client if service == "eks" else ec2_client

    monkeypatch.setattr(
        "nexus_operator.resources.vpc_endpoints.vpc_boto3_client", fake_client
    )

    assert read_vpc_profile_tag("us-east-1", "nexus-dev") is None


def test_read_vpc_profile_tag_rejects_unknown_value(monkeypatch):
    """If the VPC tag is set to a non-recognised mode (e.g. user typo),
    the helper returns None so callers fall through to their default."""
    from nexus_operator.resources.vpc_endpoints import read_vpc_profile_tag

    eks_client = MagicMock()
    eks_client.describe_cluster.return_value = {
        "cluster": {"resourcesVpcConfig": {"vpcId": "vpc-1"}}
    }
    ec2_client = MagicMock()
    ec2_client.describe_vpcs.return_value = {
        "Vpcs": [{"Tags": [{"Key": "nexus:network-profile", "Value": "bogus-mode"}]}]
    }

    def fake_client(service, region_name=None):
        return eks_client if service == "eks" else ec2_client

    monkeypatch.setattr(
        "nexus_operator.resources.vpc_endpoints.vpc_boto3_client", fake_client
    )

    assert read_vpc_profile_tag("us-east-1", "nexus-dev") is None


def test_read_vpc_profile_tag_empty_cluster_name_returns_none():
    """Defensive: empty cluster name short-circuits without an AWS call."""
    from nexus_operator.resources.vpc_endpoints import read_vpc_profile_tag

    assert read_vpc_profile_tag("us-east-1", "") is None
    assert read_vpc_profile_tag("us-east-1", None) is None  # type: ignore[arg-type]


def test_resolve_aws_access_mode_falls_back_to_vpc_tag(monkeypatch):
    """When the NexusNetworkConfig CR is missing, _resolve_aws_access_mode
    must use the VPC tag (the B3 fallback) before falling back to env default."""
    from kubernetes.client.rest import ApiException
    from nexus_operator.main import _resolve_aws_access_mode

    fake_api = MagicMock()
    fake_api.get_cluster_custom_object.side_effect = ApiException(status=404)

    monkeypatch.setenv("CLUSTER_NAME", "nexus-dev")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_MODE_DEFAULT", "higher-cost")
    monkeypatch.setattr(
        "nexus_operator.resources.read_vpc_profile_tag",
        lambda region, cluster_name: "lowest-cost",
    )

    # CR missing + VPC tag says lowest-cost -> resolver returns lowest-cost.
    assert _resolve_aws_access_mode(fake_api) == "lowest-cost"


def test_resolve_aws_access_mode_falls_back_to_env_when_no_cr_and_no_tag(monkeypatch):
    """Both CR and VPC tag missing -> use env default."""
    from kubernetes.client.rest import ApiException
    from nexus_operator.main import _resolve_aws_access_mode

    fake_api = MagicMock()
    fake_api.get_cluster_custom_object.side_effect = ApiException(status=404)

    monkeypatch.setenv("CLUSTER_NAME", "nexus-dev")
    monkeypatch.setenv("AWS_ACCESS_MODE_DEFAULT", "moderate")
    monkeypatch.setattr(
        "nexus_operator.resources.read_vpc_profile_tag",
        lambda region, cluster_name: None,
    )

    assert _resolve_aws_access_mode(fake_api) == "moderate"


# ── deploy_backend env var injection ────────────────────────────────────


def _make_k8s_creator():
    """Builds a KubernetesResourceCreator with stubbed kubernetes clients."""
    with patch("nexus_operator.resources.kubernetes.client.AppsV1Api"), \
         patch("nexus_operator.resources.kubernetes.client.CoreV1Api"):
        from nexus_operator.resources.kubernetes import KubernetesResourceCreator
        creator = KubernetesResourceCreator(namespace="nexus")
    return creator


def _extract_env_names(deployment) -> Dict[str, str]:
    container = deployment.spec.template.spec.containers[0]
    return {ev.name: ev.value for ev in container.env}


@pytest.mark.asyncio
async def test_deploy_backend_injects_higher_cost_env_only_mode():
    creator = _make_k8s_creator()
    captured = {}

    async def _capture_apply(_name, deployment):
        captured["env"] = _extract_env_names(deployment)
        return {"url": "ok"}

    async def _async_url(*a, **k):
        return {"url": "ok"}

    creator._apply_deployment = _capture_apply
    creator._apply_service = _async_url

    from nexus_operator.utils.naming import ResourceNaming
    naming = ResourceNaming("nexus", "dev", account_id="111111111111")

    await creator.deploy_backend(
        naming=naming, image="nexus/backend:latest",
        replicas=1, environment="dev", region="us-east-1",
        aws_access_mode="higher-cost",
    )

    env = captured["env"]
    assert env.get("AWS_ACCESS_MODE") == "higher-cost"
    # higher-cost MUST NOT set AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS
    assert "AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS" not in env


@pytest.mark.parametrize("mode", ["moderate", "lowest-cost", "public-nodes"])
@pytest.mark.asyncio
async def test_deploy_backend_disables_explicit_endpoints_for_non_higher_cost(mode):
    creator = _make_k8s_creator()
    captured = {}

    async def _capture_apply(_name, deployment):
        captured["env"] = _extract_env_names(deployment)
        return {"url": "ok"}

    async def _async_url(*a, **k):
        return {"url": "ok"}

    creator._apply_deployment = _capture_apply
    creator._apply_service = _async_url

    from nexus_operator.utils.naming import ResourceNaming
    naming = ResourceNaming("nexus", "dev", account_id="111111111111")

    await creator.deploy_backend(
        naming=naming, image="nexus/backend:latest",
        replicas=1, environment="dev", region="us-east-1",
        aws_access_mode=mode,
    )

    env = captured["env"]
    assert env.get("AWS_ACCESS_MODE") == mode
    assert env.get("AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS") == "true"
