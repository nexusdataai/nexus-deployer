"""
VPC Endpoint Provisioner + NetworkTopologyValidator for private EKS clusters.

The provisioner (legacy path) discovers the cluster VPC from EKS and ensures
Gateway/Interface VPC endpoints exist for the AWS services the capability needs.
It is kept for backwards compatibility but is no longer wired into the default
reconcile flow — the cluster provisioning script in nexus-deployer/deploy/eks/
now owns VPC + endpoint + NAT lifecycle. Set ``OPERATOR_PROVISION_LEGACY=true``
to re-enable provisioning for clusters that pre-date the script.

The validator (default path) inspects the VPC and confirms its topology
matches ``spec.awsAccessMode`` on NexusNetworkConfig. It never creates or
modifies AWS resources; on drift it reports the missing pieces via status.
"""
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from botocore.exceptions import ClientError

from ..utils.aws_vpc_endpoints import vpc_boto3_client

logger = logging.getLogger(__name__)

GATEWAY_SERVICES = [
    "dynamodb",
    "s3",
]

INTERFACE_SERVICES = [
    "ssm",
    "secretsmanager",
    "sts",
    "ecr.api",
    "ecr.dkr",
    "glue",
    "logs",
    "cognito-idp",
    "athena",
    "events",
]

SG_TAG_KEY = "nexus-operator"
SG_TAG_VALUE = "vpc-endpoints"
SG_NAME = "nexus-vpc-endpoints"

VPC_PROFILE_TAG = "nexus:network-profile"
NAT_INSTANCE_TAG = "nexus:nat-instance"

VALID_MODES = ("higher-cost", "moderate", "lowest-cost", "public-nodes")


class VPCEndpointProvisioner:
    """Ensures required VPC endpoints exist for private EKS clusters."""

    def __init__(self, region: str, cluster_name: str):
        self.region = region
        self.cluster_name = cluster_name
        self.ec2 = vpc_boto3_client("ec2", region_name=region)
        self.eks = vpc_boto3_client("eks", region_name=region)

    # ── public entry point ───────────────────────────────────────────────

    async def provision_all(self) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []

        logger.info(f"VPC Endpoint check starting for cluster: {self.cluster_name}")

        try:
            vpc_id, vpc_cidr, subnet_ids, route_table_ids = self._discover_vpc_from_eks()
        except Exception as e:
            logger.error(f"Failed to discover VPC from EKS cluster: {e}")
            return results

        existing = self._get_existing_endpoints(vpc_id)
        logger.info(f"Found {len(existing)} existing VPC endpoint(s) in {vpc_id}")

        sg_id = self._ensure_endpoint_security_group(vpc_id, vpc_cidr)

        for svc_suffix in GATEWAY_SERVICES:
            svc_name = f"com.amazonaws.{self.region}.{svc_suffix}"
            if svc_name in existing:
                ep_id = existing[svc_name].get("id", "")
                logger.info(f"[Gateway] {svc_name}: already exists ({ep_id})")
                results.append({"name": svc_name, "status": "exists", "type": "Gateway", "endpoint_id": ep_id})
            else:
                result = self._create_gateway_endpoint(vpc_id, svc_name, route_table_ids)
                results.append(result)

        for svc_suffix in INTERFACE_SERVICES:
            svc_name = f"com.amazonaws.{self.region}.{svc_suffix}"
            if svc_name in existing:
                ep_info = existing[svc_name]
                ep_id = ep_info.get("id", "")
                state = ep_info.get("state", "unknown")
                if state != "available":
                    logger.warning(f"[Interface] {svc_name}: exists but state={state} ({ep_id})")
                    results.append({"name": svc_name, "status": "unhealthy", "type": "Interface", "endpoint_id": ep_id})
                else:
                    logger.info(f"[Interface] {svc_name}: already exists ({ep_id}), state={state}")
                    results.append({"name": svc_name, "status": "exists", "type": "Interface", "endpoint_id": ep_id})
            else:
                result = self._create_interface_endpoint(vpc_id, svc_name, subnet_ids, sg_id)
                results.append(result)

        gw_exists = sum(1 for r in results if r["type"] == "Gateway" and r["status"] == "exists")
        gw_created = sum(1 for r in results if r["type"] == "Gateway" and r["status"] == "created")
        if_exists = sum(1 for r in results if r["type"] == "Interface" and r["status"] == "exists")
        if_created = sum(1 for r in results if r["type"] == "Interface" and r["status"] == "created")
        if_unhealthy = sum(1 for r in results if r["type"] == "Interface" and r["status"] == "unhealthy")

        logger.info("VPC Endpoint provisioning complete:")
        logger.info(f"  Gateway:   {gw_exists} exists, {gw_created} created")
        logger.info(f"  Interface: {if_exists} exists, {if_created} created, {if_unhealthy} unhealthy")
        logger.info(f"  Total:     {len(results)} endpoints checked, {gw_created + if_created} newly created")

        return results

    # ── discovery ────────────────────────────────────────────────────────

    def _discover_vpc_from_eks(self) -> Tuple[str, str, List[str], List[str]]:
        cluster = self.eks.describe_cluster(name=self.cluster_name)["cluster"]
        vpc_config = cluster["resourcesVpcConfig"]
        vpc_id = vpc_config["vpcId"]
        subnet_ids = vpc_config.get("subnetIds", [])

        vpcs = self.ec2.describe_vpcs(VpcIds=[vpc_id])["Vpcs"]
        vpc_cidr = vpcs[0]["CidrBlock"] if vpcs else "10.0.0.0/16"
        logger.info(f"Discovered VPC: {vpc_id} (CIDR: {vpc_cidr})")
        logger.info(f"Discovered {len(subnet_ids)} subnets: {', '.join(subnet_ids[:6])}")

        rts = self.ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["RouteTables"]
        route_table_ids = [rt["RouteTableId"] for rt in rts]
        logger.info(f"Discovered {len(route_table_ids)} route table(s): {', '.join(route_table_ids[:6])}")

        return vpc_id, vpc_cidr, subnet_ids, route_table_ids

    def _get_existing_endpoints(self, vpc_id: str) -> Dict[str, Dict[str, str]]:
        endpoints: Dict[str, Dict[str, str]] = {}
        paginator = self.ec2.get_paginator("describe_vpc_endpoints")
        for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
            for ep in page.get("VpcEndpoints", []):
                svc = ep.get("ServiceName", "")
                endpoints[svc] = {
                    "id": ep.get("VpcEndpointId", ""),
                    "state": ep.get("State", "unknown"),
                    "type": ep.get("VpcEndpointType", ""),
                }
        return endpoints

    # ── security group ───────────────────────────────────────────────────

    def _ensure_endpoint_security_group(self, vpc_id: str, vpc_cidr: str) -> str:
        logger.info(f"Looking for existing endpoint security group (tag: {SG_TAG_KEY}={SG_TAG_VALUE})...")
        try:
            resp = self.ec2.describe_security_groups(Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": f"tag:{SG_TAG_KEY}", "Values": [SG_TAG_VALUE]},
            ])
            groups = resp.get("SecurityGroups", [])
            if groups:
                sg_id = groups[0]["GroupId"]
                logger.info(f"Endpoint security group found: {sg_id}")
                return sg_id
        except ClientError as e:
            logger.warning(f"Error looking up security group: {e}")

        logger.info("No endpoint security group found, creating...")
        try:
            resp = self.ec2.create_security_group(
                GroupName=SG_NAME,
                Description="Allow HTTPS for VPC Interface Endpoints (managed by nexus-operator)",
                VpcId=vpc_id,
                TagSpecifications=[{
                    "ResourceType": "security-group",
                    "Tags": [
                        {"Key": SG_TAG_KEY, "Value": SG_TAG_VALUE},
                        {"Key": "Name", "Value": SG_NAME},
                    ],
                }],
            )
            sg_id = resp["GroupId"]

            self.ec2.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[{
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpRanges": [{"CidrIp": vpc_cidr, "Description": "HTTPS from VPC"}],
                }],
            )
            logger.info(f"Created security group {sg_id} with inbound TCP 443 from {vpc_cidr}")
            return sg_id
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
                resp = self.ec2.describe_security_groups(Filters=[
                    {"Name": "vpc-id", "Values": [vpc_id]},
                    {"Name": "group-name", "Values": [SG_NAME]},
                ])
                sg_id = resp["SecurityGroups"][0]["GroupId"]
                logger.info(f"Security group already exists (race condition): {sg_id}")
                return sg_id
            raise

    # ── gateway endpoints ────────────────────────────────────────────────

    def _create_gateway_endpoint(self, vpc_id: str, service_name: str, route_table_ids: List[str]) -> Dict[str, str]:
        logger.info(f"[Gateway] {service_name}: CREATING...")
        try:
            resp = self.ec2.create_vpc_endpoint(
                VpcEndpointType="Gateway",
                VpcId=vpc_id,
                ServiceName=service_name,
                RouteTableIds=route_table_ids,
                TagSpecifications=[{
                    "ResourceType": "vpc-endpoint",
                    "Tags": [
                        {"Key": "Name", "Value": f"nexus-{service_name.split('.')[-1]}"},
                        {"Key": SG_TAG_KEY, "Value": SG_TAG_VALUE},
                    ],
                }],
            )
            ep_id = resp["VpcEndpoint"]["VpcEndpointId"]
            logger.info(f"[Gateway] {service_name}: created ({ep_id})")
            return {"name": service_name, "status": "created", "type": "Gateway", "endpoint_id": ep_id}
        except ClientError as e:
            if "RouteAlreadyExists" in str(e) or "already exists" in str(e).lower():
                logger.info(f"[Gateway] {service_name}: already exists (detected during create)")
                return {"name": service_name, "status": "exists", "type": "Gateway", "endpoint_id": ""}
            logger.error(f"Failed to create VPC endpoint for {service_name}: {e}")
            return {"name": service_name, "status": "failed", "type": "Gateway", "endpoint_id": ""}

    # ── interface endpoints ──────────────────────────────────────────────

    def _create_interface_endpoint(self, vpc_id: str, service_name: str, subnet_ids: List[str], sg_id: str) -> Dict[str, str]:
        logger.info(f"[Interface] {service_name}: CREATING...")
        try:
            resp = self.ec2.create_vpc_endpoint(
                VpcEndpointType="Interface",
                VpcId=vpc_id,
                ServiceName=service_name,
                SubnetIds=subnet_ids,
                SecurityGroupIds=[sg_id],
                PrivateDnsEnabled=True,
                TagSpecifications=[{
                    "ResourceType": "vpc-endpoint",
                    "Tags": [
                        {"Key": "Name", "Value": f"nexus-{service_name.split('.')[-1]}"},
                        {"Key": SG_TAG_KEY, "Value": SG_TAG_VALUE},
                    ],
                }],
            )
            ep_id = resp["VpcEndpoint"]["VpcEndpointId"]
            state = resp["VpcEndpoint"].get("State", "pending")
            logger.info(f"[Interface] {service_name}: created ({ep_id}), state={state}")
            return {"name": service_name, "status": "created", "type": "Interface", "endpoint_id": ep_id}
        except ClientError as e:
            if "already exists" in str(e).lower() or "DuplicateVpcEndpoints" in str(e):
                logger.info(f"[Interface] {service_name}: already exists (detected during create)")
                return {"name": service_name, "status": "exists", "type": "Interface", "endpoint_id": ""}
            logger.error(f"Failed to create VPC endpoint for {service_name}: {e}")
            return {"name": service_name, "status": "failed", "type": "Interface", "endpoint_id": ""}


def is_legacy_provisioning_enabled() -> bool:
    """Whether the operator should provision the VPC topology (legacy mode)."""
    return os.environ.get("OPERATOR_PROVISION_LEGACY", "").strip().lower() in ("1", "true", "yes")


def read_vpc_profile_tag(region: str, cluster_name: str) -> Optional[str]:
    """Return the ``nexus:network-profile`` tag value of the cluster's VPC.

    Used as a fallback when the NexusNetworkConfig CR is missing — lets the
    operator pick up the cluster's intended profile straight from the VPC
    tag stamped by ``aws-eks/create-hardened-eks-cluster.sh``. Returns
    ``None`` on any error so callers can fall through to their own default.
    """
    if not cluster_name:
        return None
    try:
        eks = vpc_boto3_client("eks", region_name=region)
        ec2 = vpc_boto3_client("ec2", region_name=region)
        vpc_id = eks.describe_cluster(name=cluster_name)["cluster"]["resourcesVpcConfig"]["vpcId"]
        for tag in ec2.describe_vpcs(VpcIds=[vpc_id]).get("Vpcs", [{}])[0].get("Tags", []):
            if tag.get("Key") == VPC_PROFILE_TAG:
                value = tag.get("Value")
                if value in VALID_MODES:
                    return value
                logger.warning(
                    f"VPC tag {VPC_PROFILE_TAG}={value!r} on {vpc_id} is not a "
                    f"recognised mode; ignoring (valid: {VALID_MODES})"
                )
                return None
    except ClientError as e:
        logger.debug(f"read_vpc_profile_tag fallback unavailable: {e}")
    except Exception as e:
        logger.debug(f"read_vpc_profile_tag unexpected error: {e}")
    return None


class NetworkTopologyValidator:
    """Validates that the cluster VPC topology matches ``spec.awsAccessMode``.

    Never creates or modifies AWS resources. Returns a dict the operator
    writes verbatim into ``status.validation`` plus a list of pseudo-endpoint
    descriptors so existing status fields (``endpoints``, ``totalEndpoints``,
    ``healthyEndpoints``) keep working.
    """

    def __init__(self, region: str, cluster_name: str, mode: str):
        self.region = region
        self.cluster_name = cluster_name
        self.mode = mode if mode in VALID_MODES else "higher-cost"
        self.ec2 = vpc_boto3_client("ec2", region_name=region)
        self.eks = vpc_boto3_client("eks", region_name=region)

    async def validate(self) -> Dict[str, Any]:
        """Returns ``{"validation": {...}, "endpoints": [...], "actualProfileTag": str}``."""
        try:
            cluster = self.eks.describe_cluster(name=self.cluster_name)["cluster"]
            vpc_id = cluster["resourcesVpcConfig"]["vpcId"]
            subnet_ids = cluster["resourcesVpcConfig"].get("subnetIds", [])
        except Exception as e:
            return self._fail("describe_cluster failed", [str(e)])

        # Read the VPC's nexus:network-profile tag — the script stamps this so
        # the operator can detect topology drift independently of spec.
        actual_profile = self._read_vpc_profile_tag(vpc_id)

        endpoints = self._list_vpc_endpoints(vpc_id)
        gateway_services = {e["service"] for e in endpoints if e["type"] == "Gateway"}
        interface_services = {e["service"] for e in endpoints if e["type"] == "Interface"}

        missing: List[str] = []
        if self.mode == "higher-cost":
            for svc in GATEWAY_SERVICES:
                full = f"com.amazonaws.{self.region}.{svc}"
                if full not in gateway_services:
                    missing.append(f"gateway:{svc}")
            for svc in INTERFACE_SERVICES:
                full = f"com.amazonaws.{self.region}.{svc}"
                if full not in interface_services:
                    missing.append(f"interface:{svc}")

        elif self.mode in ("moderate", "lowest-cost"):
            for svc in GATEWAY_SERVICES:
                full = f"com.amazonaws.{self.region}.{svc}"
                if full not in gateway_services:
                    missing.append(f"gateway:{svc}")
            nat_count = self._count_nat_instances(vpc_id)
            required_nats = 2 if self.mode == "moderate" else 1
            if nat_count < required_nats:
                missing.append(f"nat-instance:expected={required_nats},found={nat_count}")
            nat_routes = self._count_nat_default_routes(vpc_id, subnet_ids)
            if nat_routes == 0:
                missing.append("private-rt:no-default-route-to-nat")

        elif self.mode == "public-nodes":
            # Worker subnets must have MapPublicIpOnLaunch=true so node ENIs
            # get a public IP and reach AWS via the IGW directly.
            if not self._all_subnets_public(subnet_ids):
                missing.append("subnets:not-all-public")

        ok = len(missing) == 0
        validation = {
            "ok": ok,
            "expected": self.mode,
            "actual": actual_profile or "unknown",
            "missing": missing,
        }
        return {
            "validation": validation,
            "endpoints": endpoints,
            "actualProfileTag": actual_profile,
        }

    # ── helpers ─────────────────────────────────────────────────────────

    def _fail(self, reason: str, missing: List[str]) -> Dict[str, Any]:
        return {
            "validation": {
                "ok": False,
                "expected": self.mode,
                "actual": "unknown",
                "missing": [reason, *missing],
            },
            "endpoints": [],
            "actualProfileTag": None,
        }

    def _read_vpc_profile_tag(self, vpc_id: str) -> Optional[str]:
        try:
            resp = self.ec2.describe_vpcs(VpcIds=[vpc_id])
            for tag in resp.get("Vpcs", [{}])[0].get("Tags", []):
                if tag.get("Key") == VPC_PROFILE_TAG:
                    return tag.get("Value")
        except ClientError as e:
            logger.warning(f"Failed to read VPC tag: {e}")
        return None

    def _list_vpc_endpoints(self, vpc_id: str) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        try:
            paginator = self.ec2.get_paginator("describe_vpc_endpoints")
            for page in paginator.paginate(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]):
                for ep in page.get("VpcEndpoints", []):
                    out.append({
                        "service": ep.get("ServiceName", ""),
                        "endpointId": ep.get("VpcEndpointId", ""),
                        "type": ep.get("VpcEndpointType", ""),
                        "state": ep.get("State", "unknown"),
                    })
        except ClientError as e:
            logger.warning(f"describe_vpc_endpoints failed: {e}")
        return out

    def _count_nat_instances(self, vpc_id: str) -> int:
        try:
            resp = self.ec2.describe_instances(Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": f"tag:{NAT_INSTANCE_TAG}", "Values": ["true"]},
                {"Name": "instance-state-name", "Values": ["running", "pending"]},
            ])
            return sum(len(r.get("Instances", [])) for r in resp.get("Reservations", []))
        except ClientError as e:
            logger.warning(f"describe_instances (NAT) failed: {e}")
            return 0

    def _count_nat_default_routes(self, vpc_id: str, cluster_subnets: List[str]) -> int:
        """Count private route tables whose 0.0.0.0/0 route targets a NAT ENI."""
        try:
            rts = self.ec2.describe_route_tables(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            ).get("RouteTables", [])
        except ClientError as e:
            logger.warning(f"describe_route_tables failed: {e}")
            return 0

        count = 0
        for rt in rts:
            for route in rt.get("Routes", []):
                if route.get("DestinationCidrBlock") != "0.0.0.0/0":
                    continue
                eni_id = route.get("NetworkInterfaceId")
                if not eni_id:
                    continue
                try:
                    enis = self.ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
                    for eni in enis.get("NetworkInterfaces", []):
                        for tag in eni.get("TagSet", []):
                            if tag.get("Key") == NAT_INSTANCE_TAG and tag.get("Value") == "true":
                                count += 1
                                break
                except ClientError:
                    pass
        return count

    def _all_subnets_public(self, subnet_ids: List[str]) -> bool:
        if not subnet_ids:
            return False
        try:
            resp = self.ec2.describe_subnets(SubnetIds=subnet_ids)
            for sn in resp.get("Subnets", []):
                if not sn.get("MapPublicIpOnLaunch", False):
                    return False
            return True
        except ClientError as e:
            logger.warning(f"describe_subnets failed: {e}")
            return False
