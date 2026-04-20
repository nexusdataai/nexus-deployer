"""
VPC Endpoint Provisioner for private EKS clusters.

Discovers the cluster VPC from EKS and ensures Gateway and Interface
VPC endpoints exist for all AWS services the capability needs.
Runs as Step 0 in the provisioning flow, before any AWS resource creation.
"""
import logging
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
SG_NAME = "totogi-vpc-endpoints"


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
                        {"Key": "Name", "Value": f"totogi-{service_name.split('.')[-1]}"},
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
                        {"Key": "Name", "Value": f"totogi-{service_name.split('.')[-1]}"},
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
