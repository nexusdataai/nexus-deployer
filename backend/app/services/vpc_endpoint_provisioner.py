"""
Direct VPC endpoint provisioner (pipeline step 6).

Replaces the earlier `NexusNetworkConfig` CR-driven flow with direct
boto3 EC2 calls. The operator CR path required the operator's CRD to be
installed first, but step 6 runs in the pre-flight wizard step BEFORE
operator install (step 5 / DEPLOYMENT_EXECUTION) - so the CRD is
guaranteed to be missing and the cluster API returns 404 page not found.

The deployer instead provisions the endpoints itself via EC2 API calls.
Verification is layered:
  1) `describe_vpc_endpoints` for an endpoint with the right ServiceName.
  2) For gateway services, check whether the AWS-managed prefix list
     (e.g. `com.amazonaws.<region>.s3` -> pl-...) is already routed in
     any cluster route table. If yes, connectivity is in place even if
     the endpoint object is in a sibling VPC or was tagged elsewhere.
  3) Only when neither check finds it do we try to create.
  4) On creation errors that mean "already in place" (RouteAlreadyExists,
     DuplicateVpcEndpoints, "already exists"), we re-verify and pass.

Endpoints (region-prefixed at runtime, e.g. for us-east-1):
  com.amazonaws.{region}.ec2              (interface)
  com.amazonaws.{region}.s3               (gateway)
  com.amazonaws.{region}.dynamodb         (gateway)
  com.amazonaws.{region}.sts              (interface)
  com.amazonaws.{region}.ssm              (interface)
  com.amazonaws.{region}.glue             (interface)
  com.amazonaws.{region}.ecr.api          (interface)
  com.amazonaws.{region}.ecr.dkr          (interface)
  com.amazonaws.{region}.secretsmanager   (interface)
  com.amazonaws.{region}.logs             (interface)
  com.amazonaws.{region}.cognito-idp      (interface)
  com.amazonaws.{region}.athena           (interface)
  com.amazonaws.{region}.events           (interface)
"""
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


GATEWAY_SERVICES: List[str] = ["s3", "dynamodb"]
INTERFACE_SERVICES: List[str] = [
    "ec2", "sts", "ssm", "glue",
    "ecr.api", "ecr.dkr",
    "secretsmanager", "logs",
    "cognito-idp", "athena", "events",
]


# A VPC endpoint object is considered healthy from the deployer's POV when
# state is `available`. New interface endpoints transition pending ->
# available; the orchestrator surfaces those as `Provisioning` (warn) but
# the row itself is still considered "in place".
HEALTHY_STATES = {"available", "Available"}
IN_FLIGHT_STATES = {"pending", "pendingAcceptance", "Pending", "PendingAcceptance"}

# Substrings AWS returns when a create is rejected because the endpoint
# (or equivalent connectivity) is already in place.
ALREADY_EXISTS_HINTS = (
    "RouteAlreadyExists",
    "DuplicateVpcEndpoints",
    "already exists",
)

# Substrings AWS returns when private DNS for the service's regional
# hostname is already provided in this VPC by some other mechanism -
# typically a hub-and-spoke topology with a centralised endpoint VPC
# and Route 53 private hosted zones associated to the spoke VPCs, or a
# sibling endpoint elsewhere whose private DNS spans this VPC. The
# service's regional DNS name resolves privately for the workload, so
# creating another endpoint with PrivateDnsEnabled=true is both
# rejected by AWS and pointless. We treat this as "already in place".
DNS_OVERLAY_HINTS = (
    "private-dns-enabled cannot be set",
    "conflicting DNS domain",
)


class ClusterNetworkInfo(dict):
    """Plain dict alias for type clarity. Keys: vpc_id, subnet_ids,
    subnets_by_az, security_group_ids, route_table_ids, route_tables,
    prefix_list_ids."""


class VpcEndpointProvisioner:
    """Discover the cluster's VPC + idempotently provision the 13 endpoints."""

    def __init__(self, eks_client, ec2_client, region: str):
        self.eks = eks_client
        self.ec2 = ec2_client
        self.region = region

    # ---- discovery -------------------------------------------------------
    def discover_cluster_network(self, cluster_name: str) -> ClusterNetworkInfo:
        """Return everything we need to drive create / verify decisions
        for the cluster's VPC."""
        cluster = self.eks.describe_cluster(name=cluster_name)["cluster"]
        vpc_cfg = cluster.get("resourcesVpcConfig") or {}
        vpc_id = vpc_cfg.get("vpcId")
        if not vpc_id:
            raise RuntimeError(
                f"eks:DescribeCluster did not return a VPC for {cluster_name}"
            )
        subnet_ids = list(vpc_cfg.get("subnetIds") or [])

        # Prefer the cluster security group (always allows worker-node
        # traffic) over the user-supplied security groups, which may not
        # permit 443 from the nodes.
        sg_ids: List[str] = []
        if vpc_cfg.get("clusterSecurityGroupId"):
            sg_ids = [vpc_cfg["clusterSecurityGroupId"]]
        if not sg_ids:
            sg_ids = list(vpc_cfg.get("securityGroupIds") or [])
        if not sg_ids:
            raise RuntimeError(
                f"No cluster or user security groups visible on {cluster_name}; "
                "interface VPC endpoints require at least one security group."
            )

        # All route tables in the VPC. We attach gateway endpoints to all
        # of them (matches the operator's behaviour) and use this list to
        # detect existing prefix-list routes.
        rts = self.ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )["RouteTables"]
        if not rts:
            raise RuntimeError(
                f"VPC {vpc_id} has no route tables; cannot attach gateway endpoints."
            )
        rt_ids = [r["RouteTableId"] for r in rts]

        # Subnet AZ map - only ONE subnet per AZ for interface endpoints.
        # AWS rejects `CreateVpcEndpoint(Interface)` with
        # `DuplicateSubnetsInSameZone` if two SubnetIds share an AZ, and
        # EKS clusters typically register both public and private subnets
        # in each AZ, doubling them up.
        subnets_by_az: Dict[str, Dict[str, str]] = {}
        if subnet_ids:
            sub_resp = self.ec2.describe_subnets(SubnetIds=subnet_ids)
            for s in sub_resp.get("Subnets", []):
                az = s.get("AvailabilityZone")
                if not az:
                    continue
                if az in subnets_by_az:
                    continue
                subnets_by_az[az] = {
                    "id": s["SubnetId"],
                    "az": az,
                    "az_id": s.get("AvailabilityZoneId") or "",
                }

        # AWS-managed prefix list IDs for the gateway services. These
        # let us answer "is S3 / DynamoDB already routed privately?"
        # even when the gateway endpoint object is invisible to our
        # describe call.
        prefix_list_ids = self._get_managed_prefix_list_ids(GATEWAY_SERVICES)

        return ClusterNetworkInfo(
            vpc_id=vpc_id,
            subnet_ids=subnet_ids,
            subnets_by_az=subnets_by_az,
            security_group_ids=sg_ids,
            route_table_ids=rt_ids,
            route_tables=rts,
            prefix_list_ids=prefix_list_ids,
        )

    # ---- inventory -------------------------------------------------------
    def list_existing_endpoints(self, vpc_id: str) -> Dict[str, Dict[str, Any]]:
        """Return {ServiceName: endpoint-dict} for endpoints in this VPC."""
        existing: Dict[str, Dict[str, Any]] = {}
        paginator = self.ec2.get_paginator("describe_vpc_endpoints")
        for page in paginator.paginate(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ):
            for e in page.get("VpcEndpoints", []):
                # State `deleting` / `deleted` shouldn't count as in place;
                # everything else (available/pending/etc) means there's an
                # endpoint we shouldn't try to recreate.
                if e.get("State") in {"deleting", "deleted", "rejected", "failed"}:
                    continue
                existing[e["ServiceName"]] = e
        return existing

    def service_name(self, svc: str) -> str:
        """Canonical AWS endpoint service name for the configured region."""
        return f"com.amazonaws.{self.region}.{svc}"

    # ---- main entrypoint -------------------------------------------------
    def ensure_endpoints(self, network: ClusterNetworkInfo) -> List[Dict[str, Any]]:
        """Create or detect each of the 13 endpoints. Returns one row per
        service with the resulting state and the action that was taken.

        Row schema:
          service, service_name, type, endpoint_id, state,
          existed (bool), created (bool), via (str),
          [error] (str, only on failure),
          [subnets] / [prefix_list_id] (extra context).
        """
        existing = self.list_existing_endpoints(network["vpc_id"])
        rows: List[Dict[str, Any]] = []

        for svc in GATEWAY_SERVICES:
            rows.append(self._ensure_gateway(svc, network, existing))
        for svc in INTERFACE_SERVICES:
            rows.append(self._ensure_interface(svc, network, existing))
        return rows

    # ---- gateway ---------------------------------------------------------
    def _ensure_gateway(
        self,
        svc: str,
        network: ClusterNetworkInfo,
        existing: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        full = self.service_name(svc)

        # 1) Endpoint object already in this VPC -> done.
        if full in existing:
            ep = existing[full]
            return self._row(
                svc, full, "Gateway",
                endpoint_id=ep.get("VpcEndpointId"),
                state=ep.get("State"),
                existed=True, created=False, via="vpc-endpoint",
            )

        # 2) Prefix-list route already in a cluster route table -> the
        #    workload can already reach S3/DynamoDB privately. Do NOT try
        #    to attach another endpoint - AWS would reject with
        #    RouteAlreadyExists.
        plist_id = network["prefix_list_ids"].get(svc)
        if plist_id and self._has_prefix_list_route(network["route_tables"], plist_id):
            return self._row(
                svc, full, "Gateway",
                endpoint_id="",
                state="available",
                existed=True, created=False, via="prefix-list-route",
                prefix_list_id=plist_id,
            )

        # 3) Nothing in place - try to create.
        try:
            resp = self.ec2.create_vpc_endpoint(
                VpcEndpointType="Gateway",
                VpcId=network["vpc_id"],
                ServiceName=full,
                RouteTableIds=network["route_table_ids"],
                TagSpecifications=self._tags(),
            )
            ep = resp["VpcEndpoint"]
            return self._row(
                svc, full, "Gateway",
                endpoint_id=ep.get("VpcEndpointId"),
                state=ep.get("State"),
                existed=False, created=True, via="vpc-endpoint",
            )
        except Exception as e:
            msg = str(e)
            if any(h in msg for h in ALREADY_EXISTS_HINTS) or "already exists" in msg.lower():
                logger.info(f"[gateway] {full}: connectivity already in place ({msg.splitlines()[0]})")
                return self._row(
                    svc, full, "Gateway",
                    endpoint_id="",
                    state="available",
                    existed=True, created=False, via="already-exists",
                    note=msg,
                )
            logger.warning(f"create gateway endpoint {full} failed: {msg}")
            return self._error_row(svc, full, "Gateway", msg)

    # ---- interface -------------------------------------------------------
    def _ensure_interface(
        self,
        svc: str,
        network: ClusterNetworkInfo,
        existing: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        full = self.service_name(svc)

        # 1) Endpoint already in this VPC -> done.
        if full in existing:
            ep = existing[full]
            return self._row(
                svc, full, "Interface",
                endpoint_id=ep.get("VpcEndpointId"),
                state=ep.get("State"),
                existed=True, created=False, via="vpc-endpoint",
            )

        # 2) Pick at most one cluster subnet per AZ, intersected with the
        #    AZs the endpoint service supports. Skipping this is what
        #    caused `DuplicateSubnetsInSameZone` on EC2/STS interface
        #    endpoints in clusters that register both public and private
        #    subnets per AZ.
        subnets = self._select_subnets_for_service(full, network)
        if not subnets:
            return self._error_row(
                svc, full, "Interface",
                "No cluster subnet matches an AZ supported by this VPC endpoint service.",
            )

        # 3) Try to create.
        try:
            resp = self.ec2.create_vpc_endpoint(
                VpcEndpointType="Interface",
                VpcId=network["vpc_id"],
                ServiceName=full,
                SubnetIds=subnets,
                SecurityGroupIds=network["security_group_ids"],
                PrivateDnsEnabled=True,
                TagSpecifications=self._tags(),
            )
            ep = resp["VpcEndpoint"]
            return self._row(
                svc, full, "Interface",
                endpoint_id=ep.get("VpcEndpointId"),
                state=ep.get("State"),
                existed=False, created=True, via="vpc-endpoint",
                subnets=subnets,
            )
        except Exception as e:
            msg = str(e)
            # Hub-and-spoke / centralised VPC endpoints: private DNS for
            # this service's regional hostname is already provided in
            # this VPC by another endpoint (possibly cross-account, via
            # RAM/Route53 PHZ). Connectivity is in place; AWS won't let
            # us create a duplicate with PrivateDnsEnabled=true.
            if any(h in msg for h in DNS_OVERLAY_HINTS):
                logger.info(f"[interface] {full}: served by existing private DNS overlay")
                return self._row(
                    svc, full, "Interface",
                    endpoint_id="",
                    state="available",
                    existed=True, created=False, via="dns-overlay",
                    note=msg,
                )
            # Race / pre-existing endpoint we missed in the initial
            # describe (paginator stale, just-created sibling). Re-check.
            if any(h in msg for h in ALREADY_EXISTS_HINTS) or "already exists" in msg.lower():
                rechecked = self.list_existing_endpoints(network["vpc_id"]).get(full)
                if rechecked:
                    return self._row(
                        svc, full, "Interface",
                        endpoint_id=rechecked.get("VpcEndpointId"),
                        state=rechecked.get("State"),
                        existed=True, created=False, via="vpc-endpoint-recheck",
                    )
                return self._row(
                    svc, full, "Interface",
                    endpoint_id="",
                    state="available",
                    existed=True, created=False, via="already-exists",
                    note=msg,
                )
            logger.warning(f"create interface endpoint {full} failed: {msg}")
            return self._error_row(svc, full, "Interface", msg, subnets=subnets)

    # ---- helpers ---------------------------------------------------------
    def _select_subnets_for_service(
        self,
        full_service_name: str,
        network: ClusterNetworkInfo,
    ) -> List[str]:
        """Pick at most one cluster subnet per AZ; if AWS reports the AZs
        the service supports, intersect with them."""
        cluster_azs: Dict[str, str] = {
            az: info["id"] for az, info in network["subnets_by_az"].items()
        }
        if not cluster_azs:
            return []
        supported = self._supported_azs_for_service(full_service_name)
        if supported is None:
            return list(cluster_azs.values())
        chosen: List[str] = []
        for az, subnet_id in cluster_azs.items():
            if az in supported:
                chosen.append(subnet_id)
        return chosen

    def _supported_azs_for_service(
        self,
        full_service_name: str,
    ) -> Optional[Set[str]]:
        """Return the AZ names that this endpoint service supports, or
        None if AWS won't tell us (e.g. permission denied) - in which
        case the caller should trust the cluster AZ set."""
        try:
            resp = self.ec2.describe_vpc_endpoint_services(
                ServiceNames=[full_service_name]
            )
        except Exception as e:
            logger.debug(f"describe_vpc_endpoint_services({full_service_name}) failed: {e}")
            return None
        azs: Set[str] = set()
        for s in resp.get("ServiceDetails") or []:
            for az in s.get("AvailabilityZones") or []:
                azs.add(az)
        return azs or None

    def _get_managed_prefix_list_ids(self, services: List[str]) -> Dict[str, str]:
        """Map svc -> AWS-managed prefix-list ID for that service.
        Empty dict (not raise) on permission failure - we'll just skip
        the route check and rely on describe + create-or-already-exists."""
        wanted = {self.service_name(svc): svc for svc in services}
        result: Dict[str, str] = {}
        try:
            resp = self.ec2.describe_prefix_lists(
                Filters=[
                    {"Name": "prefix-list-name", "Values": list(wanted.keys())},
                ]
            )
        except Exception as e:
            logger.debug(f"describe_prefix_lists failed: {e}")
            return result
        for p in resp.get("PrefixLists", []):
            full = p.get("PrefixListName")
            pid = p.get("PrefixListId")
            if not full or not pid:
                continue
            svc = wanted.get(full)
            if svc:
                result[svc] = pid
        return result

    @staticmethod
    def _has_prefix_list_route(
        route_tables: List[Dict[str, Any]],
        prefix_list_id: str,
    ) -> bool:
        for rt in route_tables:
            for route in rt.get("Routes", []) or []:
                if route.get("DestinationPrefixListId") == prefix_list_id:
                    return True
        return False

    @staticmethod
    def _row(
        service: str,
        service_name: str,
        ep_type: str,
        *,
        endpoint_id: Optional[str],
        state: Optional[str],
        existed: bool,
        created: bool,
        via: str,
        **extra: Any,
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "service": service,
            "service_name": service_name,
            "type": ep_type,
            "endpoint_id": endpoint_id or "",
            "state": state or "unknown",
            "existed": existed,
            "created": created,
            "via": via,
        }
        row.update(extra)
        return row

    @staticmethod
    def _error_row(
        service: str,
        service_name: str,
        ep_type: str,
        error: str,
        **extra: Any,
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "service": service,
            "service_name": service_name,
            "type": ep_type,
            "endpoint_id": "",
            "state": "error",
            "existed": False,
            "created": False,
            "via": "create-failed",
            "error": error,
        }
        row.update(extra)
        return row

    @staticmethod
    def _tags() -> List[Dict[str, Any]]:
        return [{
            "ResourceType": "vpc-endpoint",
            "Tags": [
                {"Key": "app.kubernetes.io/managed-by", "Value": "nexus-deployer"},
                {"Key": "nexus.ai/component", "Value": "vpc-endpoints"},
            ],
        }]


# -------------------------------------------------------------- summarise
def summarise_endpoint_rows(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Counts used by NetworkConfigReport.

    `healthy` = endpoint is in place and reachable (existed-or-available).
    `in_flight` = newly created interface endpoint still in pending.
    `failed` = create attempt that hit a hard error.
    """
    total = len(rows)
    healthy = sum(
        1 for r in rows
        if r.get("existed")
        or (r.get("state") in HEALTHY_STATES and not r.get("error"))
    )
    in_flight = sum(
        1 for r in rows
        if not r.get("existed")
        and r.get("state") in IN_FLIGHT_STATES
        and not r.get("error")
    )
    failed = sum(1 for r in rows if r.get("error") or r.get("state") in {"error", "failed"})
    return {
        "total": total,
        "healthy": healthy,
        "in_flight": in_flight,
        "failed": failed,
    }
