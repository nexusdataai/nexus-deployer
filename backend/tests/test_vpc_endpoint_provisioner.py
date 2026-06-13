"""
Tests for VpcEndpointProvisioner.

Verifies:
  - Cluster network discovery returns vpc/subnets-by-az/SG/route tables.
  - All 13 expected endpoints are inspected (2 gateway + 11 interface).
  - Existing endpoints are reused (existed=True, no recreate).
  - Existing prefix-list routes count as "in place" for gateway services
    even when describe_vpc_endpoints returns nothing.
  - RouteAlreadyExists / DuplicateVpcEndpoints / "already exists" errors
    on create are treated as "in place" (existed=True) rather than fail.
  - Interface endpoints get one subnet per AZ.
  - Per-endpoint creation failures surface as `error` rows without
    aborting the rest.
"""
from unittest.mock import MagicMock

import pytest

from app.services.vpc_endpoint_provisioner import (
    GATEWAY_SERVICES,
    INTERFACE_SERVICES,
    VpcEndpointProvisioner,
    summarise_endpoint_rows,
)


# ----- helpers ------------------------------------------------------------
def _eks_describe_cluster(
    vpc_id="vpc-abc",
    subnet_ids=("subnet-a1", "subnet-a2", "subnet-b1"),
    cluster_sg="sg-cluster",
):
    return {
        "cluster": {
            "resourcesVpcConfig": {
                "vpcId": vpc_id,
                "subnetIds": list(subnet_ids),
                "clusterSecurityGroupId": cluster_sg,
                "securityGroupIds": [],
            }
        }
    }


def _ec2_describe_subnets():
    """Two subnets in apse1-a (one public, one private), one in apse1-b."""
    return {
        "Subnets": [
            {"SubnetId": "subnet-a1", "AvailabilityZone": "us-east-1a", "AvailabilityZoneId": "apse1-az1"},
            {"SubnetId": "subnet-a2", "AvailabilityZone": "us-east-1a", "AvailabilityZoneId": "apse1-az1"},
            {"SubnetId": "subnet-b1", "AvailabilityZone": "us-east-1b", "AvailabilityZoneId": "apse1-az2"},
        ]
    }


def _ec2_describe_route_tables(rt_ids=("rt-1",), routes=()):
    return {
        "RouteTables": [
            {"RouteTableId": rt_id, "Routes": list(routes)} for rt_id in rt_ids
        ]
    }


def _empty_describe_endpoints_paginator():
    paginator = MagicMock()
    paginator.paginate.return_value = [{"VpcEndpoints": []}]
    return paginator


def _wire_ec2(ec2, *, subnets=None, route_tables=None, prefix_lists=None,
              services_supported_azs=None, paginator=None):
    """Common ec2 client wiring."""
    ec2.describe_subnets.return_value = subnets or _ec2_describe_subnets()
    ec2.describe_route_tables.return_value = route_tables or _ec2_describe_route_tables()
    ec2.describe_prefix_lists.return_value = prefix_lists or {"PrefixLists": []}
    ec2.describe_vpc_endpoint_services.return_value = {
        "ServiceDetails": [{"AvailabilityZones": services_supported_azs or [
            "us-east-1a", "us-east-1b", "us-east-1c",
        ]}]
    }
    ec2.get_paginator.return_value = paginator or _empty_describe_endpoints_paginator()


# ===== discovery ==========================================================
def test_discover_cluster_network_uses_cluster_security_group():
    eks = MagicMock()
    eks.describe_cluster.return_value = _eks_describe_cluster()
    ec2 = MagicMock()
    _wire_ec2(ec2)

    p = VpcEndpointProvisioner(eks_client=eks, ec2_client=ec2, region="us-east-1")
    info = p.discover_cluster_network("nexus-test1")
    assert info["vpc_id"] == "vpc-abc"
    assert info["security_group_ids"] == ["sg-cluster"]
    assert info["route_table_ids"] == ["rt-1"]
    # subnets_by_az dedupes to one subnet per AZ
    assert set(info["subnets_by_az"].keys()) == {"us-east-1a", "us-east-1b"}


def test_discover_falls_back_to_user_security_groups_when_no_cluster_sg():
    eks = MagicMock()
    eks.describe_cluster.return_value = {
        "cluster": {
            "resourcesVpcConfig": {
                "vpcId": "vpc-abc",
                "subnetIds": ["subnet-a1"],
                "clusterSecurityGroupId": "",
                "securityGroupIds": ["sg-user"],
            }
        }
    }
    ec2 = MagicMock()
    _wire_ec2(ec2, subnets={
        "Subnets": [{"SubnetId": "subnet-a1", "AvailabilityZone": "us-east-1a"}]
    })
    p = VpcEndpointProvisioner(eks_client=eks, ec2_client=ec2, region="us-east-1")
    info = p.discover_cluster_network("c")
    assert info["security_group_ids"] == ["sg-user"]


def test_discover_raises_when_no_security_groups():
    eks = MagicMock()
    eks.describe_cluster.return_value = {
        "cluster": {
            "resourcesVpcConfig": {
                "vpcId": "vpc-abc",
                "subnetIds": ["subnet-a1"],
                "clusterSecurityGroupId": "",
                "securityGroupIds": [],
            }
        }
    }
    ec2 = MagicMock()
    p = VpcEndpointProvisioner(eks_client=eks, ec2_client=ec2, region="us-east-1")
    with pytest.raises(RuntimeError, match="security group"):
        p.discover_cluster_network("c")


# ===== ensure_endpoints (creation paths) ==================================
def test_ensure_creates_all_13_when_nothing_exists():
    ec2 = MagicMock()
    _wire_ec2(ec2)
    counter = {"i": 0}

    def fake_create(**kwargs):
        counter["i"] += 1
        return {"VpcEndpoint": {
            "VpcEndpointId": f"vpce-{counter['i']:03d}",
            "ServiceName": kwargs["ServiceName"],
            "State": "pending",
        }}
    ec2.create_vpc_endpoint.side_effect = fake_create

    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": ["subnet-a1", "subnet-b1"],
        "subnets_by_az": {
            "us-east-1a": {"id": "subnet-a1", "az": "us-east-1a", "az_id": "apse1-az1"},
            "us-east-1b": {"id": "subnet-b1", "az": "us-east-1b", "az_id": "apse1-az2"},
        },
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    rows = p.ensure_endpoints(network)
    assert len(rows) == len(GATEWAY_SERVICES) + len(INTERFACE_SERVICES) == 13
    services = [r["service"] for r in rows]
    assert services[: len(GATEWAY_SERVICES)] == GATEWAY_SERVICES
    assert all(r["created"] and not r["existed"] for r in rows)


def test_interface_endpoints_pass_one_subnet_per_az():
    """The fix for `DuplicateSubnetsInSameZone`: one subnet per AZ."""
    ec2 = MagicMock()
    _wire_ec2(ec2)
    ec2.create_vpc_endpoint.return_value = {
        "VpcEndpoint": {"VpcEndpointId": "vpce-x", "ServiceName": "x", "State": "pending"}
    }
    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": ["subnet-a1", "subnet-a2", "subnet-b1"],
        "subnets_by_az": {
            "us-east-1a": {"id": "subnet-a1", "az": "us-east-1a", "az_id": "apse1-az1"},
            "us-east-1b": {"id": "subnet-b1", "az": "us-east-1b", "az_id": "apse1-az2"},
        },
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    p._ensure_interface("ec2", network, existing={})

    call = ec2.create_vpc_endpoint.call_args
    assert call.kwargs["VpcEndpointType"] == "Interface"
    sns = call.kwargs["SubnetIds"]
    # subnet-a2 must NOT appear (would dup AZ us-east-1a)
    assert "subnet-a2" not in sns
    assert sorted(sns) == ["subnet-a1", "subnet-b1"]


# ===== detection paths ===================================================
def test_existing_endpoints_are_marked_existed_not_recreated():
    ec2 = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [{"VpcEndpoints": [
        {
            "VpcEndpointId": "vpce-already-there",
            "ServiceName": "com.amazonaws.us-east-1.s3",
            "State": "available",
        },
    ]}]
    _wire_ec2(ec2, paginator=paginator)
    ec2.create_vpc_endpoint.return_value = {
        "VpcEndpoint": {"VpcEndpointId": "vpce-new", "ServiceName": "x", "State": "pending"}
    }
    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": ["subnet-a1"],
        "subnets_by_az": {
            "us-east-1a": {"id": "subnet-a1", "az": "us-east-1a", "az_id": "apse1-az1"},
        },
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    rows = p.ensure_endpoints(network)
    s3_row = next(r for r in rows if r["service"] == "s3")
    assert s3_row["endpoint_id"] == "vpce-already-there"
    assert s3_row["existed"] is True
    assert s3_row["created"] is False
    # 12 attempted creates (1 gateway dynamodb + 11 interface)
    assert ec2.create_vpc_endpoint.call_count == 12


def test_gateway_short_circuits_when_prefix_list_already_routed():
    """The fix for `RouteAlreadyExists`: detect prefix-list route, skip create."""
    ec2 = MagicMock()
    _wire_ec2(
        ec2,
        route_tables={"RouteTables": [{
            "RouteTableId": "rt-1",
            "Routes": [{"DestinationPrefixListId": "pl-6fa54006"}],
        }]},
    )
    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": [],
        "subnets_by_az": {},
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{
            "RouteTableId": "rt-1",
            "Routes": [{"DestinationPrefixListId": "pl-6fa54006"}],
        }],
        "prefix_list_ids": {"s3": "pl-6fa54006"},
    }
    row = p._ensure_gateway("s3", network, existing={})
    assert row["existed"] is True
    assert row["created"] is False
    assert row["via"] == "prefix-list-route"
    assert row["state"] == "available"
    ec2.create_vpc_endpoint.assert_not_called()


def test_gateway_route_already_exists_error_treated_as_in_place():
    """Belt-and-suspenders: even if prefix-list discovery returns nothing,
    a RouteAlreadyExists from create is treated as in place."""
    ec2 = MagicMock()
    _wire_ec2(ec2)
    ec2.create_vpc_endpoint.side_effect = RuntimeError(
        "An error occurred (RouteAlreadyExists) when calling the CreateVpcEndpoint "
        "operation: route table rt-022a968beff6aa8a3 already has a route with "
        "destination-prefix-list-id pl-6fa54006"
    )
    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": [],
        "subnets_by_az": {},
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    row = p._ensure_gateway("s3", network, existing={})
    assert row["existed"] is True
    assert row["created"] is False
    assert row["state"] == "available"
    assert "error" not in row


def test_interface_already_exists_error_treated_as_in_place_and_re_described():
    """When create fails because the endpoint exists, re-describe surfaces it.

    `_ensure_interface` is called directly here with `existing={}`, so
    the only paginator invocation is the post-failure recheck inside
    `_ensure_interface`; that one must surface the racing endpoint.
    """
    ec2 = MagicMock()
    pag = MagicMock()
    pag.paginate.return_value = [{"VpcEndpoints": [{
        "VpcEndpointId": "vpce-race",
        "ServiceName": "com.amazonaws.us-east-1.ec2",
        "State": "available",
    }]}]
    ec2.get_paginator.return_value = pag
    ec2.describe_subnets.return_value = _ec2_describe_subnets()
    ec2.describe_route_tables.return_value = _ec2_describe_route_tables()
    ec2.describe_prefix_lists.return_value = {"PrefixLists": []}
    ec2.describe_vpc_endpoint_services.return_value = {
        "ServiceDetails": [{"AvailabilityZones": ["us-east-1a", "us-east-1b"]}]
    }
    ec2.create_vpc_endpoint.side_effect = RuntimeError(
        "An error occurred (DuplicateVpcEndpoints) ... already exists"
    )
    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": ["subnet-a1", "subnet-b1"],
        "subnets_by_az": {
            "us-east-1a": {"id": "subnet-a1", "az": "us-east-1a", "az_id": "apse1-az1"},
            "us-east-1b": {"id": "subnet-b1", "az": "us-east-1b", "az_id": "apse1-az2"},
        },
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    row = p._ensure_interface("ec2", network, existing={})
    assert row["existed"] is True
    assert row["created"] is False
    assert row["endpoint_id"] == "vpce-race"
    assert row["via"] == "vpc-endpoint-recheck"


def test_interface_dns_conflict_treated_as_in_place_via_dns_overlay():
    """Hub-and-spoke topology: another endpoint in this VPC (or a Route 53
    PHZ associated to it) already serves the service's regional DNS
    name. AWS rejects create with InvalidParameter; provisioner treats
    it as already in place via DNS overlay, not as a failure."""
    ec2 = MagicMock()
    _wire_ec2(ec2)
    ec2.create_vpc_endpoint.side_effect = RuntimeError(
        "An error occurred (InvalidParameter) when calling the CreateVpcEndpoint "
        "operation: private-dns-enabled cannot be set because there is already a "
        "conflicting DNS domain for sts.us-east-1.amazonaws.com in the VPC "
        "vpc-008408be32d5754e9"
    )
    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-008408be32d5754e9",
        "subnet_ids": ["subnet-a1", "subnet-b1"],
        "subnets_by_az": {
            "us-east-1a": {"id": "subnet-a1", "az": "us-east-1a", "az_id": "apse1-az1"},
            "us-east-1b": {"id": "subnet-b1", "az": "us-east-1b", "az_id": "apse1-az2"},
        },
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    row = p._ensure_interface("sts", network, existing={})
    assert row["existed"] is True
    assert row["created"] is False
    assert row["via"] == "dns-overlay"
    assert row["state"] == "available"
    assert "error" not in row


def test_per_endpoint_create_failure_does_not_abort_others():
    ec2 = MagicMock()
    _wire_ec2(ec2)

    def fake_create(**kwargs):
        if kwargs["ServiceName"].endswith(".cognito-idp"):
            raise RuntimeError("Some unexpected quota error")
        return {"VpcEndpoint": {
            "VpcEndpointId": "vpce-x",
            "ServiceName": kwargs["ServiceName"],
            "State": "pending",
        }}
    ec2.create_vpc_endpoint.side_effect = fake_create

    p = VpcEndpointProvisioner(MagicMock(), ec2, "us-east-1")
    network = {
        "vpc_id": "vpc-abc",
        "subnet_ids": ["subnet-a1", "subnet-b1"],
        "subnets_by_az": {
            "us-east-1a": {"id": "subnet-a1", "az": "us-east-1a", "az_id": "apse1-az1"},
            "us-east-1b": {"id": "subnet-b1", "az": "us-east-1b", "az_id": "apse1-az2"},
        },
        "security_group_ids": ["sg-1"],
        "route_table_ids": ["rt-1"],
        "route_tables": [{"RouteTableId": "rt-1", "Routes": []}],
        "prefix_list_ids": {},
    }
    rows = p.ensure_endpoints(network)
    bad = next(r for r in rows if r["service"] == "cognito-idp")
    assert bad.get("error")
    assert bad["state"] == "error"
    other_count = sum(1 for r in rows if r.get("state") == "pending")
    assert other_count == 12


def test_summarise_counts_treats_existed_as_healthy():
    rows = [
        {"existed": True, "created": False, "state": "available"},
        {"existed": True, "created": False, "state": "available"},
        {"existed": False, "created": True, "state": "pending"},
        {"existed": False, "created": False, "state": "error", "error": "x"},
    ]
    s = summarise_endpoint_rows(rows)
    assert s == {"total": 4, "healthy": 2, "in_flight": 1, "failed": 1}
