"""
Nexus Operator Main Entry Point

Feature: pure-eks-deployment
Requirements: 12.8
"""
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import kopf

from .utils.aws_vpc_endpoints import vpc_boto3_client
from aiohttp import web
from kubernetes.client.rest import ApiException

# Configure logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("nexus-operator")

# Health check state
_health_state = {
    "ready": False,
    "live": True,
    "last_reconcile": None,
    "error": None
}


# ==================== Health Check Server ====================

async def healthz_handler(request: web.Request) -> web.Response:
    """Liveness probe endpoint."""
    if _health_state["live"]:
        return web.Response(text="OK", status=200)
    return web.Response(text="NOT OK", status=503)


async def readyz_handler(request: web.Request) -> web.Response:
    """Readiness probe endpoint."""
    if _health_state["ready"]:
        return web.Response(text="OK", status=200)
    return web.Response(text="NOT READY", status=503)


async def metrics_handler(request: web.Request) -> web.Response:
    """Prometheus metrics endpoint (placeholder)."""
    metrics = [
        "# HELP nexus_operator_reconciliations_total Total number of reconciliations",
        "# TYPE nexus_operator_reconciliations_total counter",
        "nexus_operator_reconciliations_total 0",
        "",
        "# HELP nexus_operator_ready Operator readiness status",
        "# TYPE nexus_operator_ready gauge",
        f"nexus_operator_ready {1 if _health_state['ready'] else 0}",
    ]
    return web.Response(text="\n".join(metrics), content_type="text/plain")


async def start_health_server(port: int = 8080) -> web.AppRunner:
    """Start the health check HTTP server."""
    app = web.Application()
    app.router.add_get("/healthz", healthz_handler)
    app.router.add_get("/readyz", readyz_handler)
    app.router.add_get("/metrics", metrics_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server started on port {port}")
    return runner


# ==================== Kopf Handlers ====================

@kopf.on.startup()
async def startup_handler(settings: kopf.OperatorSettings, **kwargs):
    """
    Operator startup handler.
    
    Configures kopf settings and marks operator as ready.
    """
    logger.info("Nexus Operator starting up...")
    
    # Configure kopf settings
    settings.posting.level = logging.WARNING
    settings.watching.server_timeout = 600
    settings.persistence.finalizer = "nexus.ai/finalizer"
    
    # Mark as ready
    _health_state["ready"] = True
    logger.info("Nexus Operator is ready")


@kopf.on.cleanup()
async def cleanup_handler(**kwargs):
    """
    Operator cleanup handler.
    
    Called when the operator is shutting down.
    """
    logger.info("Nexus Operator shutting down...")
    _health_state["ready"] = False
    _health_state["live"] = False


@kopf.on.login()
async def login_handler(**kwargs):
    """
    Custom login handler for Kubernetes authentication.
    
    Uses the default service account credentials.
    """
    return kopf.login_via_client(**kwargs)


# ==================== NexusCapability Handlers ====================

def _now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _update_step(steps: List[Dict], step_name: str, status: str,
                 resources: List[str] = None, error: str = None) -> List[Dict]:
    """Update or append a step in the steps list."""
    for s in steps:
        if s["name"] == step_name:
            s["status"] = status
            if status == "in_progress" and "startTime" not in s:
                s["startTime"] = _now_iso()
            if status in ("done", "failed", "skipped"):
                s["endTime"] = _now_iso()
            if resources is not None:
                s["resources"] = resources
            if error is not None:
                s["error"] = error
            return steps
    # Not found, append
    entry: Dict[str, Any] = {"name": step_name, "status": status, "startTime": _now_iso()}
    if resources is not None:
        entry["resources"] = resources
    if status in ("done", "failed", "skipped"):
        entry["endTime"] = _now_iso()
    if error is not None:
        entry["error"] = error
    steps.append(entry)
    return steps


def _data_services_flags(spec: dict) -> Dict[str, bool]:
    """Return which data services are enabled in the CR spec."""
    data_services = spec.get("dataServices", {})
    return {
        "dynamodb": data_services.get("dynamodb", {}).get("enabled", True),
        "s3": data_services.get("s3", {}).get("enabled", True),
        "glue": data_services.get("glue", {}).get("enabled", True),
    }


def _needs_data_services_reconcile(spec: dict, status: Optional[dict]) -> bool:
    """True when data services are enabled in spec but missing from status.resources."""
    flags = _data_services_flags(spec)
    resources = (status or {}).get("resources") or {}
    if flags["dynamodb"] and not resources.get("dynamodbTables"):
        return True
    if flags["s3"] and not resources.get("s3Buckets"):
        return True
    if flags["glue"] and not resources.get("glueDatabase"):
        return True
    return False


def _restart_deployments(
    k8s: Any,
    naming: Any,
    namespace: str,
    components: List[str],
    logger_: logging.Logger,
) -> None:
    """Rolling restart of named deployments (e.g. after SSM / IRSA changes)."""
    restart_annotation = {"kubectl.kubernetes.io/restartedAt": _now_iso()}
    for dep_component in components:
        dep_name = naming.kubernetes_deployment(dep_component)
        try:
            dep = k8s.apps_api.read_namespaced_deployment(name=dep_name, namespace=namespace)
            if dep.spec.template.metadata.annotations is None:
                dep.spec.template.metadata.annotations = {}
            dep.spec.template.metadata.annotations.update(restart_annotation)
            k8s.apps_api.patch_namespaced_deployment(name=dep_name, namespace=namespace, body=dep)
            logger_.info(f"Restarted Deployment {dep_name}")
        except ApiException as restart_err:
            if restart_err.status != 404:
                logger_.warning(f"Failed to restart {dep_name}: {restart_err}")


async def _provision_data_services(
    spec: dict,
    naming: Any,
    region: str,
    resources: dict,
    steps: List[Dict],
    patch: kopf.Patch,
    logger_: logging.Logger,
) -> bool:
    """Provision DynamoDB, S3, and Glue when enabled. Returns True if anything was provisioned."""
    from .resources import DynamoDBProvisioner, S3Provisioner, GlueProvisioner

    flags = _data_services_flags(spec)
    provisioned = False

    if flags["dynamodb"]:
        patch.status["phase"] = "ProvisioningDataServices"
        patch.status["message"] = "Creating DynamoDB tables..."
        _update_step(steps, "DynamoDB", "in_progress")
        patch.status["steps"] = list(steps)

        logger_.info("Provisioning DynamoDB tables...")
        dynamodb = DynamoDBProvisioner(naming, region)
        results = await dynamodb.provision_all()
        resources["dynamodbTables"] = [r["name"] for r in results if r["status"] in ["created", "exists"]]

        _update_step(steps, "DynamoDB", "done", resources=resources["dynamodbTables"])
        patch.status["steps"] = list(steps)
        logger_.info(f"DynamoDB done: {resources['dynamodbTables']}")
        provisioned = True
    else:
        _update_step(steps, "DynamoDB", "skipped")
        patch.status["steps"] = list(steps)

    if flags["s3"]:
        patch.status["message"] = "Creating S3 buckets..."
        _update_step(steps, "S3", "in_progress")
        patch.status["steps"] = list(steps)

        logger_.info("Provisioning S3 buckets...")
        s3 = S3Provisioner(naming, region)
        results = await s3.provision_all()
        resources["s3Buckets"] = [r["name"] for r in results if r["status"] in ["created", "exists"]]

        _update_step(steps, "S3", "done", resources=resources["s3Buckets"])
        patch.status["steps"] = list(steps)
        logger_.info(f"S3 done: {resources['s3Buckets']}")
        provisioned = True
    else:
        _update_step(steps, "S3", "skipped")
        patch.status["steps"] = list(steps)

    if flags["glue"]:
        patch.status["message"] = "Creating Glue database..."
        _update_step(steps, "Glue", "in_progress")
        patch.status["steps"] = list(steps)

        logger_.info("Provisioning Glue database...")
        glue = GlueProvisioner(naming, region)
        results = await glue.provision_all()
        glue_resources = []
        for r in results:
            if r["status"] in ["created", "exists"]:
                glue_resources.append(r["name"])
            if r["type"] == "GlueDatabase" and r["status"] in ["created", "exists"]:
                resources["glueDatabase"] = r["name"]

        _update_step(steps, "Glue", "done", resources=glue_resources)
        patch.status["steps"] = list(steps)
        logger_.info(f"Glue done: {glue_resources}")
        provisioned = True
    else:
        _update_step(steps, "Glue", "skipped")
        patch.status["steps"] = list(steps)

    if provisioned:
        patch.status["resources"] = resources

    return provisioned


async def _provision_ssm_parameters(
    naming: Any,
    region: str,
    resources: dict,
    steps: List[Dict],
    patch: kopf.Patch,
    logger_: logging.Logger,
) -> None:
    """Write SSM parameters that reference provisioned AWS resource names."""
    from .resources import SSMProvisioner

    patch.status["phase"] = "ProvisioningSSM"
    patch.status["message"] = "Creating SSM parameters..."
    _update_step(steps, "SSM", "in_progress")
    patch.status["steps"] = list(steps)

    logger_.info("Provisioning SSM parameters...")
    ssm = SSMProvisioner(naming, region)
    ssm_results = await ssm.provision_all(resources)
    resources["ssmParameters"] = [r["name"] for r in ssm_results if r["status"] in ["created", "exists"]]

    _update_step(steps, "SSM", "done", resources=resources["ssmParameters"])
    patch.status["steps"] = list(steps)
    patch.status["resources"] = resources
    logger_.info(f"SSM done: {len(resources['ssmParameters'])} parameters")


# ══════════════════════════════════════════════════════════════════════
# NexusNetworkConfig handlers -- topology validation / projection
# ══════════════════════════════════════════════════════════════════════
#
# The cluster provisioning script in nexus-deployer/deploy/eks/ owns the VPC,
# subnet, NAT-instance, and VPC-endpoint lifecycle. The operator no longer
# provisions; it only validates that the cluster topology matches
# ``spec.awsAccessMode`` and writes the result to status. Legacy provisioning
# is still available behind OPERATOR_PROVISION_LEGACY=true for clusters that
# pre-date the script.

VALID_AWS_ACCESS_MODES = ("higher-cost", "moderate", "lowest-cost", "public-nodes")


def _resolve_aws_access_mode(crd_api: Any = None) -> str:
    """Return the cluster-wide awsAccessMode.

    Resolution priority:
      1. ``spec.awsAccessMode`` on the singleton ``NexusNetworkConfig`` CR
         named ``vpc-endpoints`` (the usual production path)
      2. ``nexus:network-profile`` tag on the cluster's VPC (stamped by
         ``aws-eks/create-hardened-eks-cluster.sh``) — lets brand-new
         clusters work before any CR is applied
      3. ``AWS_ACCESS_MODE_DEFAULT`` env (or hardcoded ``higher-cost``)
    """
    default = os.getenv("AWS_ACCESS_MODE_DEFAULT", "higher-cost")
    if default not in VALID_AWS_ACCESS_MODES:
        default = "higher-cost"

    # 1. NexusNetworkConfig CR
    try:
        if crd_api is None:
            from .utils.k8s_client import authed_custom_objects_api
            crd_api = authed_custom_objects_api()
        cr = crd_api.get_cluster_custom_object(
            "nexus.ai", "v1", "nexusnetworkconfigs", "vpc-endpoints",
        )
        mode = cr.get("spec", {}).get("awsAccessMode")
        if mode in VALID_AWS_ACCESS_MODES:
            return mode
    except ApiException:
        # CR not present — fall through to VPC tag.
        pass
    except Exception as e:
        logger.warning(f"_resolve_aws_access_mode CR read failed: {e}")

    # 2. VPC tag fallback
    try:
        region = os.getenv("AWS_REGION") or os.getenv("CLUSTER_REGION") or "us-east-1"
        cluster_name = os.getenv("CLUSTER_NAME", "")
        if cluster_name:
            from .resources import read_vpc_profile_tag
            tag = read_vpc_profile_tag(region, cluster_name)
            if tag in VALID_AWS_ACCESS_MODES:
                logger.info(
                    f"_resolve_aws_access_mode: NexusNetworkConfig CR not found; "
                    f"using VPC tag nexus:network-profile={tag}"
                )
                return tag
    except Exception as e:
        logger.debug(f"_resolve_aws_access_mode VPC tag fallback unavailable: {e}")

    # 3. Hardcoded default
    return default


async def _reconcile_network_config(spec: dict, name: str, patch: kopf.Patch, logger_: logging.Logger) -> None:
    """Validate the cluster topology against spec.awsAccessMode and write status.

    Shared by ``@kopf.on.create``, ``@kopf.on.update``, and ``@kopf.on.timer``
    so all three paths produce identical status writes.
    """
    from .resources import (
        VPCEndpointProvisioner,
        NetworkTopologyValidator,
        is_legacy_provisioning_enabled,
    )

    region = spec.get("region", "us-east-1")
    cluster_name = spec.get("clusterName", os.getenv("CLUSTER_NAME", ""))
    mode = spec.get("awsAccessMode") or os.getenv("AWS_ACCESS_MODE_DEFAULT", "higher-cost")
    if mode not in VALID_AWS_ACCESS_MODES:
        mode = "higher-cost"

    # Legacy provisioning path — only used for the one pre-existing cluster
    # whose VPC topology is still operator-owned. Gated by env var.
    if is_legacy_provisioning_enabled():
        logger_.warning(f"NexusNetworkConfig '{name}': legacy provisioning enabled (OPERATOR_PROVISION_LEGACY=true)")
        try:
            vpc_ep = VPCEndpointProvisioner(region, cluster_name=cluster_name)
            results = await vpc_ep.provision_all()
            endpoints = [
                {
                    "service": r["name"],
                    "endpointId": r.get("endpoint_id", ""),
                    "type": r["type"],
                    "state": r["status"],
                }
                for r in results
            ]
            healthy = sum(1 for e in endpoints if e["state"] in ("exists", "created"))
            patch.status["endpoints"] = endpoints
            patch.status["totalEndpoints"] = len(endpoints)
            patch.status["healthyEndpoints"] = healthy
            patch.status["activeMode"] = mode
            patch.status["lastChecked"] = datetime.now(timezone.utc).isoformat()
            if healthy == len(endpoints):
                patch.status["phase"] = "Ready"
                patch.status["message"] = f"Legacy provisioning OK ({healthy}/{len(endpoints)} endpoints)"
            else:
                patch.status["phase"] = "Error"
                patch.status["message"] = f"{len(endpoints) - healthy} endpoint(s) unhealthy"
        except Exception as e:
            patch.status["phase"] = "Error"
            patch.status["message"] = f"Legacy provisioning failed: {str(e)[:180]}"
            logger_.error(f"NexusNetworkConfig '{name}' legacy provisioning failed: {e}")
        return

    # Default path: validate-only.
    logger_.info(f"NexusNetworkConfig '{name}': validating topology for awsAccessMode={mode}")
    try:
        validator = NetworkTopologyValidator(region, cluster_name=cluster_name, mode=mode)
        result = await validator.validate()
    except Exception as e:
        patch.status["phase"] = "Error"
        patch.status["activeMode"] = mode
        patch.status["validation"] = {
            "ok": False, "expected": mode, "actual": "unknown",
            "missing": [f"validator-error: {str(e)[:120]}"],
        }
        patch.status["lastChecked"] = datetime.now(timezone.utc).isoformat()
        patch.status["message"] = f"Topology validation failed: {str(e)[:160]}"
        logger_.error(f"NexusNetworkConfig '{name}' validation failed: {e}")
        return

    endpoints = result["endpoints"]
    healthy = sum(1 for e in endpoints if e["state"] in ("exists", "created", "available", "Available"))
    validation = result["validation"]

    patch.status["activeMode"] = mode
    patch.status["validation"] = validation
    patch.status["endpoints"] = endpoints
    patch.status["totalEndpoints"] = len(endpoints)
    patch.status["healthyEndpoints"] = healthy
    patch.status["lastChecked"] = datetime.now(timezone.utc).isoformat()

    actual_tag = result.get("actualProfileTag")
    if actual_tag and actual_tag != mode:
        patch.status["phase"] = "Error"
        patch.status["message"] = (
            f"VPC tag nexus:network-profile={actual_tag} but spec.awsAccessMode={mode}. "
            "Re-run deploy/eks/create-hardened-eks-cluster.sh with matching --network-profile."
        )
        logger_.warning(f"NexusNetworkConfig '{name}': profile drift {actual_tag} vs {mode}")
    elif validation["ok"]:
        patch.status["phase"] = "Ready"
        patch.status["message"] = f"Topology matches awsAccessMode={mode}"
        logger_.info(f"NexusNetworkConfig '{name}': Ready (mode={mode})")
    else:
        patch.status["phase"] = "Error"
        missing_preview = ", ".join(validation.get("missing", [])[:3])
        patch.status["message"] = f"Topology missing for mode={mode}: {missing_preview}"
        logger_.warning(f"NexusNetworkConfig '{name}': topology incomplete: {validation.get('missing')}")


@kopf.on.create("nexus.ai", "v1", "nexusnetworkconfigs")
async def create_network_config(spec: dict, name: str, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """Validate topology and write status on CR creation."""
    patch.status["phase"] = "Validating"
    patch.status["message"] = "Validating cluster topology..."
    await _reconcile_network_config(spec, name, patch, logger)


@kopf.on.update("nexus.ai", "v1", "nexusnetworkconfigs")
async def update_network_config(spec: dict, name: str, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """Re-validate on spec changes (e.g., flipping awsAccessMode)."""
    patch.status["phase"] = "Validating"
    patch.status["message"] = "Re-validating cluster topology..."
    await _reconcile_network_config(spec, name, patch, logger)


@kopf.on.timer("nexus.ai", "v1", "nexusnetworkconfigs", interval=300, initial_delay=60)
async def check_network_health(spec: dict, name: str, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """Periodic re-validation -- every 5 minutes."""
    await _reconcile_network_config(spec, name, patch, logger)


# ══════════════════════════════════════════════════════════════════════
# NexusCapability handlers
# ══════════════════════════════════════════════════════════════════════

@kopf.on.create("nexus.ai", "v1", "nexuscapabilities")
async def create_capability(spec: dict, name: str, namespace: str, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """
    Handle NexusCapability creation.
    
    Provisions AWS resources and deploys Kubernetes workloads.
    
    Requirements: 4.3, 4.9, 12.4
    """
    from .utils.naming import ResourceNaming
    from .resources import (
        VPCEndpointProvisioner,
        SecretsProvisioner,
        KubernetesResourceCreator,
        CognitoProvisioner,
        MimirProvisioner,
    )
    
    logger.info(f"Creating NexusCapability: {name} in namespace {namespace}")
    
    capability_name = spec.get("capabilityName", "")
    version = spec.get("version", "")
    environment = spec.get("environment", "")
    region = spec.get("region", "us-east-1")

    aws_access_mode = _resolve_aws_access_mode()
    logger.info(f"Capability: {capability_name} v{version} ({environment}) in {region} [awsAccessMode={aws_access_mode}]")
    
    # Resolve account ID for globally unique resource names (S3 buckets)
    sts_client = vpc_boto3_client("sts", region_name=region)
    account_id = sts_client.get_caller_identity()["Account"]
    
    # Initialize naming utility
    naming = ResourceNaming(capability_name, environment, account_id=account_id)
    
    # Track all created resources
    resources = {
        "dynamodbTables": [],
        "s3Buckets": [],
        "glueDatabase": None,
        "ssmParameters": [],
        "secrets": [],
        "iamRoles": [],
    }
    
    # Granular step tracking
    steps: List[Dict[str, Any]] = []
    
    try:
        # ── Step 0: Verify VPC Endpoints (reads NexusNetworkConfig status) ──
        _update_step(steps, "VPCEndpoints", "in_progress")
        patch.status["steps"] = list(steps)

        try:
            from .utils.k8s_client import authed_custom_objects_api
            crd_api = authed_custom_objects_api()
            nc = crd_api.get_cluster_custom_object("nexus.ai", "v1", "nexusnetworkconfigs", "vpc-endpoints")
            nc_status = nc.get("status", {})
            nc_phase = nc_status.get("phase", "Unknown")
            nc_healthy = nc_status.get("healthyEndpoints", 0)
            nc_total = nc_status.get("totalEndpoints", 0)

            if nc_phase == "Ready":
                logger.info(f"VPC Endpoints verified via NexusNetworkConfig: {nc_healthy}/{nc_total} healthy")
                for ep in nc_status.get("endpoints", []):
                    state_str = "OK" if ep.get("state") in ("exists", "created") else ep.get("state", "unknown")
                    logger.info(f"  [{ep.get('type', '?')}] {ep.get('service', '?')}: {state_str}")
                _update_step(steps, "VPCEndpoints", "done", resources=[f"{nc_healthy}/{nc_total} healthy"])
            else:
                logger.warning(f"VPC Endpoints not ready (phase={nc_phase}). Some services may be unreachable.")
                for ep in nc_status.get("endpoints", []):
                    if ep.get("state") not in ("exists", "created", "available"):
                        logger.warning(f"  [{ep.get('type', '?')}] {ep.get('service', '?')}: {ep.get('state', 'unknown')}")
                _update_step(steps, "VPCEndpoints", "done", resources=[f"phase={nc_phase}"])

        except Exception as nc_err:
            logger.warning(f"NexusNetworkConfig 'vpc-endpoints' not found — skipping endpoint verification ({nc_err})")
            logger.warning("Apply examples/network-config.yaml to enable VPC endpoint management")
            _update_step(steps, "VPCEndpoints", "skipped")

        patch.status["steps"] = list(steps)

        # ── Step 1–3: DynamoDB, S3, Glue ──
        data_services = spec.get("dataServices", {})
        resources.setdefault("dynamodbTables", [])
        resources.setdefault("s3Buckets", [])
        resources.setdefault("glueDatabase", None)
        resources.setdefault("ssmParameters", [])

        await _provision_data_services(
            spec, naming, region, resources, steps, patch, logger,
        )

        # ── Step 4: Cognito (optional) ──
        if spec.get("enableCognito", False) or spec.get("cognito"):
            patch.status["message"] = "Provisioning Cognito User Pool..."
            _update_step(steps, "Cognito", "in_progress")
            patch.status["steps"] = list(steps)
            
            logger.info("Provisioning Cognito User Pool...")
            cognito = CognitoProvisioner(naming, region)
            
            if spec.get("cognito"):
                logger.info("Using Cognito configuration from spec")
                resources["cognito"] = spec["cognito"]
                _update_step(steps, "Cognito", "done", resources=[
                    spec["cognito"].get("user_pool_id", "provided-in-spec")
                ])
            else:
                from .resources.cognito import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
                admin_email = spec.get("adminEmail") or DEFAULT_ADMIN_EMAIL
                admin_password = spec.get("adminPassword") or DEFAULT_ADMIN_PASSWORD
                frontend_url = spec.get("frontendUrl", "")
                callback_urls = spec.get("cognitoCallbackUrls", [])
                cognito_results = await cognito.provision_all(
                    admin_email=admin_email,
                    admin_password=admin_password,
                    frontend_url=frontend_url,
                    callback_urls=callback_urls,
                )
                cognito_config = cognito_results.get("cognito_config", {})
                cognito_error = cognito_results.get("error")
                
                if cognito_config and cognito_config.get("user_pool_id"):
                    resources["cognito"] = cognito_config
                    _update_step(steps, "Cognito", "done", resources=[
                        cognito_config.get("user_pool_id", ""),
                        cognito_config.get("client_id", ""),
                    ])
                    logger.info(f"Cognito done: pool={cognito_config.get('user_pool_id')}")
                    
                    # Store admin credentials in a K8s Secret (persists across pod restarts)
                    admin_result = cognito_results.get("admin_user", {})
                    admin_email_val = admin_result.get("email", "") or spec.get("adminEmail", "")
                    if admin_email_val:
                        try:
                            from kubernetes import client as k8s_client
                            import base64
                            core_api = k8s_client.CoreV1Api()
                            secret_name = f"{naming.capability_name}-{naming.environment}-admin-credentials"
                            # For new users, store temp password; for existing, store status
                            admin_pw = (
                                admin_result.get("password")
                                or admin_result.get("temporary_password")
                                or spec.get("adminPassword")
                                or ""
                            )
                            admin_status = admin_result.get("user_status", admin_result.get("status", ""))
                            secret_data = {
                                "admin-email": base64.b64encode(admin_email_val.encode()).decode(),
                                "admin-password": base64.b64encode((admin_pw or f"(user {admin_status} - password already set)").encode()).decode(),
                            }
                            secret = k8s_client.V1Secret(
                                metadata=k8s_client.V1ObjectMeta(
                                    name=secret_name,
                                    namespace=namespace,
                                    labels={"app.kubernetes.io/managed-by": "nexus-operator", "nexus.ai/type": "admin-credentials"}
                                ),
                                data=secret_data,
                                type="Opaque"
                            )
                            try:
                                core_api.create_namespaced_secret(namespace, secret)
                            except Exception:
                                core_api.replace_namespaced_secret(secret_name, namespace, secret)
                            logger.info(f"Admin credentials stored in Secret: {secret_name}")
                        except Exception as e:
                            logger.warning(f"Could not store admin credentials in Secret: {e}")
                else:
                    error_msg = cognito_error or "Failed to create User Pool (check operator IAM permissions for cognito-idp:*)"
                    _update_step(steps, "Cognito", "failed", error=error_msg)
                    logger.error(f"Cognito provisioning failed: {error_msg}")
            
            patch.status["steps"] = list(steps)
        
        # ── Step 5: SSM Parameters ──
        await _provision_ssm_parameters(naming, region, resources, steps, patch, logger)
        
        # ── Step 6: Secrets ──
        patch.status["phase"] = "ProvisioningSecrets"
        patch.status["message"] = "Creating Secrets Manager secrets..."
        _update_step(steps, "Secrets", "in_progress")
        patch.status["steps"] = list(steps)
        
        logger.info("Provisioning Secrets Manager secrets...")
        secrets = SecretsProvisioner(naming, region)
        secrets_results = await secrets.provision_all()
        resources["secrets"] = [r["name"] for r in secrets_results if r["status"] in ["created", "exists"]]
        
        _update_step(steps, "Secrets", "done", resources=resources["secrets"])
        patch.status["steps"] = list(steps)
        logger.info(f"Secrets done: {len(resources['secrets'])} secrets")
        
        # ── Step 7: IAM Role ──
        patch.status["phase"] = "ProvisioningIAM"
        patch.status["message"] = "Creating IAM role with IRSA..."
        _update_step(steps, "IAM", "in_progress")
        patch.status["steps"] = list(steps)
        
        logger.info("Creating application IAM role...")
        
        from .utils.eks_utils import get_oidc_provider_for_irsa, verify_oidc_provider_exists
        oidc_provider, cluster_name = get_oidc_provider_for_irsa(region)
        
        if oidc_provider:
            if verify_oidc_provider_exists(oidc_provider, account_id, region):
                logger.info(f"IRSA enabled with OIDC provider: {oidc_provider}")
            else:
                logger.warning("OIDC provider not configured on cluster - IRSA may not work")
        else:
            logger.warning("No OIDC provider found - IRSA may not work")

        role_arn = f"arn:aws:iam::{account_id}:role/{naming.application_role()}"
        resources["iamRoles"] = [role_arn]
        logger.info(f"Using pre-created app role: {role_arn}")

        _update_step(steps, "IAM", "done", resources=resources["iamRoles"])
        patch.status["steps"] = list(steps)
        logger.info(f"IAM done: {resources['iamRoles']}")
        
        # ── Step 8: Namespace ──
        patch.status["phase"] = "Deploying"
        patch.status["message"] = "Creating Kubernetes namespace..."
        patch.status["resources"] = resources
        _update_step(steps, "Namespace", "in_progress")
        patch.status["steps"] = list(steps)
        
        k8s = KubernetesResourceCreator(namespace)
        await k8s.create_namespace_if_needed(naming)
        
        _update_step(steps, "Namespace", "done", resources=[namespace])
        patch.status["steps"] = list(steps)
        
        # ── Step 9: ServiceAccount ──
        patch.status["message"] = "Creating ServiceAccount with IRSA..."
        _update_step(steps, "ServiceAccount", "in_progress")
        patch.status["steps"] = list(steps)
        
        role_arn = resources["iamRoles"][0] if resources["iamRoles"] else ""
        if not role_arn:
            role_arn = f"arn:aws:iam::{account_id}:role/{naming.application_role()}"
            logger.warning(f"IAM role ARN not available from provisioning, using convention: {role_arn}")
        sa_result = await k8s.create_service_account(naming, role_arn)
        sa_was_updated = sa_result.get("status") == "updated"
        
        _update_step(steps, "ServiceAccount", "done", resources=[naming.kubernetes_service_account("app")])
        patch.status["steps"] = list(steps)
        
        # ── Step 10a: Redis Cache (optional; skipped for lightweight capabilities) ──
        redis_spec = spec.get("redis", {})
        data_services = spec.get("dataServices", {})
        _lightweight = (
            not data_services.get("dynamodb", {}).get("enabled", True)
            and not data_services.get("s3", {}).get("enabled", True)
            and not data_services.get("glue", {}).get("enabled", True)
            and not spec.get("bssmagic", {}).get("enabled", False)
        )
        redis_enabled = False if _lightweight else redis_spec.get("enabled", True)
        redis_service_name = None
        if redis_enabled:
            patch.status["phase"] = "DeployingRedis"
            patch.status["message"] = "Deploying Redis cache for simulator data..."
            _update_step(steps, "Redis", "in_progress")
            patch.status["steps"] = list(steps)

            logger.info("Deploying Redis cache...")
            redis_service_name = await k8s.deploy_redis(
                naming=naming,
                maxmemory=redis_spec.get("maxmemory", "2gb"),
                storage_size=redis_spec.get("storageSize", "2Gi"),
                storage_class=redis_spec.get("storageClass", "gp2"),
            )

            _update_step(steps, "Redis", "done", resources=["redis", "redis-svc"])
            patch.status["steps"] = list(steps)
            logger.info(f"Redis done: {redis_service_name}")
        else:
            _update_step(steps, "Redis", "skipped")
            patch.status["steps"] = list(steps)

        # ── Step 10b: Grafana Mimir (optional; skipped for lightweight capabilities) ──
        mimir_spec = spec.get("mimir", {})
        mimir_enabled = False if _lightweight else mimir_spec.get("enabled", True)
        if mimir_enabled:
            patch.status["phase"] = "DeployingMimir"
            patch.status["message"] = "Deploying Grafana Mimir (monolithic) for solution KPI history..."
            _update_step(steps, "Mimir", "in_progress")
            patch.status["steps"] = list(steps)

            try:
                logger.info("Deploying Grafana Mimir...")
                mimir = MimirProvisioner(namespace=namespace, naming=naming, region=region)
                mimir_result = await mimir.provision(
                    retention_days=mimir_spec.get("retentionDays", 90),
                    storage_size=mimir_spec.get("storageSize", "5Gi"),
                    storage_class=mimir_spec.get("storageClass"),
                    service_account=naming.kubernetes_service_account(),
                )
                mimir_status = mimir_result.get("status", "unknown")
                mimir_components = [c.get("name") for c in mimir_result.get("components", [])]
                if mimir_status == "failed":
                    logger.warning(f"Mimir deploy failed (non-fatal): {mimir_result.get('error')}")
                    _update_step(steps, "Mimir", "done", resources=[f"failed: {mimir_result.get('error', '')[:80]}"])
                else:
                    _update_step(steps, "Mimir", "done", resources=mimir_components)
                    logger.info(f"Mimir done: url={mimir_result.get('url')}")
            except Exception as me:
                logger.warning(f"Mimir provisioning failed (non-fatal, dashboards still work without TSDB): {me}")
                _update_step(steps, "Mimir", "done", resources=[f"error: {str(me)[:80]}"])
            patch.status["steps"] = list(steps)
        else:
            _update_step(steps, "Mimir", "skipped")
            patch.status["steps"] = list(steps)

        # ── Step 10c: Backend ──
        ingress_config = spec.get("ingress", {})
        use_ingress = ingress_config.get("enabled", False)
        internal_ingress_config = spec.get("internalIngress", {})
        use_internal_ingress = internal_ingress_config.get("enabled", False)
        
        backend_spec = spec.get("backend", {})
        backend_image = backend_spec.get("image", "")
        backend_service_name = naming.kubernetes_service("backend")
        
        # Pre-compute BSS Magic service name so backend can get FDW env vars
        bssmagic_spec = spec.get("bssmagic", {})
        bssmagic_svc_for_backend = (
            naming.kubernetes_service("bssmagic")
            if bssmagic_spec.get("enabled", False) and bssmagic_spec.get("image")
            else None
        )
        
        if backend_image:
            patch.status["phase"] = "DeployingBackend"
            patch.status["message"] = "Deploying backend pods and service..."
            _update_step(steps, "Backend", "in_progress")
            patch.status["steps"] = list(steps)
            
            logger.info("Deploying backend...")
            backend_url = await k8s.deploy_backend(
                naming=naming,
                image=backend_image,
                replicas=backend_spec.get("replicas", 2),
                resources=backend_spec.get("resources", {}),
                environment=environment,
                region=region,
                use_clusterip=use_ingress,
                bssmagic_service=bssmagic_svc_for_backend,
                redis_service=redis_service_name,
                aws_access_mode=aws_access_mode,
            )
            
            _update_step(steps, "Backend", "done", resources=[
                naming.kubernetes_deployment("backend"),
                naming.kubernetes_service("backend"),
            ])
            patch.status["steps"] = list(steps)
            logger.info(f"Backend done: {backend_url}")
        else:
            backend_url = ""
            _update_step(steps, "Backend", "skipped")
            patch.status["steps"] = list(steps)
        
        # ── Step 11: BSS Magic (optional) ──
        bssmagic_service_name = None
        if bssmagic_spec.get("enabled", False) and bssmagic_spec.get("image"):
            patch.status["phase"] = "DeployingBssMagic"
            patch.status["message"] = "Deploying BSS Magic runtime (StatefulSet with embedded PostgreSQL)..."
            _update_step(steps, "BssMagic", "in_progress")
            patch.status["steps"] = list(steps)

            logger.info("Deploying BSS Magic...")
            bssmagic_service_name = await k8s.deploy_bssmagic(
                naming=naming,
                image=bssmagic_spec["image"],
                replicas=bssmagic_spec.get("replicas", 1),
                resources=bssmagic_spec.get("resources", {}),
                credentials_secret_name=bssmagic_spec.get("credentialsSecretName", ""),
                axway_secret_name=bssmagic_spec.get("axwaySecretName", ""),
                dump_s3_bucket=bssmagic_spec.get("dumpS3Bucket", ""),
                dump_s3_key=bssmagic_spec.get("dumpS3Key", "bssmagic-dump.sql.gz"),
                storage_size=bssmagic_spec.get("storageSize", "10Gi"),
                storage_class=bssmagic_spec.get("storageClass"),
                region=region,
                extra_env=bssmagic_spec.get("env"),
                aws_access_mode=aws_access_mode,
            )

            _update_step(steps, "BssMagic", "done", resources=[
                naming.kubernetes_deployment("bssmagic"),
                naming.kubernetes_service("bssmagic"),
            ])
            patch.status["steps"] = list(steps)
            logger.info(f"BSS Magic done: {bssmagic_service_name}")
        else:
            _update_step(steps, "BssMagic", "skipped")
            patch.status["steps"] = list(steps)

        # ── Step 12: Frontend ──
        frontend_spec = spec.get("frontend", {})
        frontend_image = frontend_spec.get("image", "")
        if frontend_image:
            patch.status["phase"] = "DeployingFrontend"
            patch.status["message"] = "Deploying frontend pods and service..."
            _update_step(steps, "Frontend", "in_progress")
            patch.status["steps"] = list(steps)
            
            logger.info("Deploying frontend...")
            frontend_url = await k8s.deploy_frontend(
                naming=naming,
                image=frontend_image,
                replicas=frontend_spec.get("replicas", 2),
                resources=frontend_spec.get("resources", {}),
                ingress_config=ingress_config if use_ingress else None,
                backend_service=backend_service_name if (use_ingress or use_internal_ingress) else None,
                bssmagic_service=bssmagic_service_name if (use_ingress or use_internal_ingress) else None,
                internal_ingress_config=internal_ingress_config if use_internal_ingress else None,
            )
            
            frontend_resources = [
                naming.kubernetes_deployment("frontend"),
                naming.kubernetes_service("frontend"),
            ]
            if use_ingress:
                frontend_resources.append(naming.kubernetes_ingress("app"))
            if use_internal_ingress:
                frontend_resources.append(naming.kubernetes_ingress("internal"))
            _update_step(steps, "Frontend", "done", resources=frontend_resources)
            patch.status["steps"] = list(steps)
            logger.info(f"Frontend done: {frontend_url}")
        else:
            frontend_url = ""
            _update_step(steps, "Frontend", "skipped")
            patch.status["steps"] = list(steps)
        
        # ── Step 13: Ingress (if applicable) ──
        if use_ingress and frontend_image:
            _update_step(steps, "Ingress", "done", resources=[naming.kubernetes_ingress("app")])
            patch.status["steps"] = list(steps)
        
        # ── Step 14: Restart workloads if SA annotation was updated ──
        if sa_was_updated:
            logger.info("ServiceAccount IRSA annotation was updated — restarting workloads for IRSA token injection")
            _restart_deployments(k8s, naming, namespace, ["backend", "frontend"], logger)
            _update_step(steps, "IRSARestart", "done", resources=["Workloads restarted for IRSA token injection"])
            patch.status["steps"] = list(steps)
        
        # ── Complete ──
        logger.info(f"NexusCapability {name} deployment complete")
        
        kopf.event(
            kwargs["body"],
            type="Normal",
            reason="DeploymentComplete",
            message=f"Successfully deployed {capability_name} v{version} to {environment}"
        )
        
        # BSS Magic is internal-only: backend calls it via K8s service DNS
        bssmagic_url = ""
        if bssmagic_service_name:
            bssmagic_url = f"{bssmagic_service_name}.{namespace}.svc.cluster.local:8000"

        patch.status["phase"] = "Running"
        patch.status["message"] = "Deployment complete"
        patch.status["frontendUrl"] = frontend_url
        patch.status["backendUrl"] = backend_url
        patch.status["bssmagicUrl"] = bssmagic_url
        patch.status["resources"] = resources
        patch.status["steps"] = list(steps)

        return {
            "phase": "Running",
            "message": "Deployment complete",
            "frontendUrl": frontend_url,
            "backendUrl": backend_url,
            "bssmagicUrl": bssmagic_url,
            "resources": resources,
            "steps": steps,
        }
        
    except Exception as e:
        logger.error(f"Failed to create capability {name}: {e}")
        
        # Mark current in_progress step as failed
        for s in steps:
            if s.get("status") == "in_progress":
                _update_step(steps, s["name"], "failed", error=str(e))
                break
        
        kopf.event(
            kwargs["body"],
            type="Warning",
            reason="DeploymentFailed",
            message=str(e)
        )
        
        return {
            "phase": "Failed",
            "message": str(e),
            "resources": resources,
            "steps": steps,
        }


@kopf.on.update("nexus.ai", "v1", "nexuscapabilities")
async def update_capability(spec: dict, name: str, namespace: str, status: dict, diff: kopf.Diff, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """
    Handle NexusCapability updates.
    
    Performs rolling updates for configuration changes.
    Provisions data services (DynamoDB/S3/Glue/SSM) when enabled or missing from status.
    
    Requirements: 4.10
    """
    from .utils.naming import ResourceNaming
    from .resources import KubernetesResourceCreator
    
    logger.info(f"Updating NexusCapability: {name} in namespace {namespace}")
    
    capability_name = spec.get("capabilityName", "")
    environment = spec.get("environment", "")
    region = spec.get("region", "us-east-1")

    aws_access_mode = _resolve_aws_access_mode()

    sts_client = vpc_boto3_client("sts", region_name=region)
    account_id = sts_client.get_caller_identity()["Account"]
    naming = ResourceNaming(capability_name, environment, account_id=account_id)
    k8s = KubernetesResourceCreator(namespace)
    
    # Get ingress configuration
    ingress_config = spec.get("ingress", {})
    use_ingress = ingress_config.get("enabled", False)
    internal_ingress_config = spec.get("internalIngress", {})
    use_internal_ingress = internal_ingress_config.get("enabled", False)
    backend_service_name = naming.kubernetes_service("backend")
    
    # Check what changed
    changed_fields = [change[1] for change in diff]
    logger.info(f"Changed fields: {changed_fields}")
    
    steps: List[Dict[str, Any]] = list((status or {}).get("steps") or [])
    resources: Dict[str, Any] = dict((status or {}).get("resources") or {})
    resources.setdefault("dynamodbTables", [])
    resources.setdefault("s3Buckets", [])
    resources.setdefault("glueDatabase", None)
    resources.setdefault("ssmParameters", [])
    resources.setdefault("secrets", resources.get("secrets") or [])
    resources.setdefault("iamRoles", resources.get("iamRoles") or [])

    data_services_changed = any("dataServices" in str(f) for f in changed_fields)
    needs_data_reconcile = _needs_data_services_reconcile(spec, status)
    data_services_updated = False
    
    # Pre-compute BSS Magic service name for FDW env var injection
    bssmagic_spec = spec.get("bssmagic", {})
    bssmagic_svc = (
        naming.kubernetes_service("bssmagic")
        if bssmagic_spec.get("enabled", False) and bssmagic_spec.get("image")
        else None
    )
    
    # Pre-compute Redis service name
    redis_spec = spec.get("redis", {})
    redis_svc = "redis-svc" if redis_spec.get("enabled", True) else None
    
    try:
        if data_services_changed or needs_data_reconcile:
            reason = "spec change" if data_services_changed else "missing resources in status"
            logger.info(f"Provisioning data services ({reason})...")
            patch.status["phase"] = "ProvisioningDataServices"
            patch.status["message"] = f"Provisioning data services ({reason})..."
            data_services_updated = await _provision_data_services(
                spec, naming, region, resources, steps, patch, logger,
            )
            if data_services_updated or needs_data_reconcile:
                await _provision_ssm_parameters(naming, region, resources, steps, patch, logger)
                _restart_deployments(k8s, naming, namespace, ["backend"], logger)
                _update_step(steps, "DataServicesRestart", "done", resources=["backend restarted after data plane update"])
                patch.status["steps"] = list(steps)

        # If redis config changed, update Redis deployment
        if any("redis" in str(f) for f in changed_fields):
            if redis_spec.get("enabled", True):
                logger.info("Updating Redis deployment...")
                await k8s.deploy_redis(
                    naming=naming,
                    maxmemory=redis_spec.get("maxmemory", "2gb"),
                    storage_size=redis_spec.get("storageSize", "2Gi"),
                    storage_class=redis_spec.get("storageClass", "gp2"),
                )

        # If backend config changed, update backend deployment
        if any("backend" in str(f) for f in changed_fields):
            backend_spec = spec.get("backend", {})
            backend_image = backend_spec.get("image", "")
            if backend_image:
                logger.info("Updating backend deployment...")
                await k8s.deploy_backend(
                    naming=naming,
                    image=backend_image,
                    replicas=backend_spec.get("replicas", 2),
                    resources=backend_spec.get("resources", {}),
                    environment=environment,
                    region=region,
                    use_clusterip=use_ingress,
                    bssmagic_service=bssmagic_svc,
                    redis_service=redis_svc,
                    aws_access_mode=aws_access_mode,
                )

        # If bssmagic config changed, update bssmagic deployment
        if any("bssmagic" in str(f) for f in changed_fields):
            if bssmagic_spec.get("enabled", False) and bssmagic_spec.get("image"):
                logger.info("Updating BSS Magic deployment...")
                await k8s.deploy_bssmagic(
                    naming=naming,
                    image=bssmagic_spec["image"],
                    replicas=bssmagic_spec.get("replicas", 1),
                    resources=bssmagic_spec.get("resources", {}),
                    credentials_secret_name=bssmagic_spec.get("credentialsSecretName", ""),
                    axway_secret_name=bssmagic_spec.get("axwaySecretName", ""),
                    dump_s3_bucket=bssmagic_spec.get("dumpS3Bucket", ""),
                    dump_s3_key=bssmagic_spec.get("dumpS3Key", "bssmagic-dump.sql.gz"),
                    storage_size=bssmagic_spec.get("storageSize", "10Gi"),
                    storage_class=bssmagic_spec.get("storageClass"),
                    region=region,
                    extra_env=bssmagic_spec.get("env"),
                    aws_access_mode=aws_access_mode,
                )

        # If frontend or ingress config changed, update frontend deployment
        if any("frontend" in str(f) or "ingress" in str(f) or "internalIngress" in str(f) for f in changed_fields):
            frontend_spec = spec.get("frontend", {})
            frontend_image = frontend_spec.get("image", "")
            if frontend_image:
                logger.info("Updating frontend deployment...")
                await k8s.deploy_frontend(
                    naming=naming,
                    image=frontend_image,
                    replicas=frontend_spec.get("replicas", 2),
                    resources=frontend_spec.get("resources", {}),
                    ingress_config=ingress_config if use_ingress else None,
                    backend_service=backend_service_name if (use_ingress or use_internal_ingress) else None,
                    bssmagic_service=bssmagic_svc if (use_ingress or use_internal_ingress) else None,
                    internal_ingress_config=internal_ingress_config if use_internal_ingress else None,
                )
        
        kopf.event(
            kwargs["body"],
            type="Normal",
            reason="UpdateComplete",
            message=f"Successfully updated {capability_name}"
        )
        
        result: Dict[str, Any] = {"phase": "Running", "message": "Update completed"}
        if data_services_updated or needs_data_reconcile:
            result["resources"] = resources
            result["steps"] = steps
        return result
        
    except Exception as e:
        logger.error(f"Failed to update capability {name}: {e}")
        kopf.event(
            kwargs["body"],
            type="Warning",
            reason="UpdateFailed",
            message=str(e)
        )
        return {"phase": "Failed", "message": str(e)}


@kopf.on.timer("nexus.ai", "v1", "nexuscapabilities", interval=300, initial_delay=120)
async def reconcile_capability_data_services(
    spec: dict,
    name: str,
    namespace: str,
    status: dict,
    logger: logging.Logger,
    patch: kopf.Patch,
    **kwargs,
):
    """Re-provision data services when enabled in spec but absent from status (e.g. after cr-lite patch)."""
    if not _needs_data_services_reconcile(spec, status):
        return

    phase = (status or {}).get("phase", "")
    if phase == "Failed":
        return

    from .utils.naming import ResourceNaming
    from .resources import KubernetesResourceCreator

    capability_name = spec.get("capabilityName", "")
    environment = spec.get("environment", "")
    region = spec.get("region", "us-east-1")

    sts_client = vpc_boto3_client("sts", region_name=region)
    account_id = sts_client.get_caller_identity()["Account"]
    naming = ResourceNaming(capability_name, environment, account_id=account_id)
    k8s = KubernetesResourceCreator(namespace)

    steps: List[Dict[str, Any]] = list((status or {}).get("steps") or [])
    resources: Dict[str, Any] = dict((status or {}).get("resources") or {})
    resources.setdefault("dynamodbTables", [])
    resources.setdefault("s3Buckets", [])
    resources.setdefault("glueDatabase", None)
    resources.setdefault("ssmParameters", [])

    logger.info(f"Timer reconcile: provisioning missing data services for {name}")
    patch.status["message"] = "Reconciling missing data services..."

    try:
        updated = await _provision_data_services(
            spec, naming, region, resources, steps, patch, logger,
        )
        if updated:
            await _provision_ssm_parameters(naming, region, resources, steps, patch, logger)
            _restart_deployments(k8s, naming, namespace, ["backend"], logger)
            _update_step(steps, "DataServicesReconcile", "done", resources=["data plane reconciled"])
            patch.status["steps"] = list(steps)
            patch.status["phase"] = "Running"
            patch.status["message"] = "Data services reconciled"
            return {"resources": resources, "steps": steps, "phase": "Running"}
    except Exception as e:
        logger.error(f"Data services reconcile failed for {name}: {e}")
        patch.status["message"] = f"Data services reconcile failed: {e}"


@kopf.on.delete("nexus.ai", "v1", "nexuscapabilities")
async def delete_capability(spec: dict, name: str, namespace: str, status: dict, logger: logging.Logger, **kwargs):
    """
    Handle NexusCapability deletion.
    
    Cleans up AWS resources based on deletionPolicy.
    
    Requirements: 4.11, 12.6
    """
    from .utils.naming import ResourceNaming
    from .resources import (
        DynamoDBProvisioner,
        S3Provisioner,
        GlueProvisioner,
        SSMProvisioner,
        SecretsProvisioner,
        KubernetesResourceCreator,
        CognitoProvisioner,
    )
    
    logger.info(f"Deleting NexusCapability: {name} in namespace {namespace}")
    
    capability_name = spec.get("capabilityName", "")
    environment = spec.get("environment", "")
    region = spec.get("region", "us-east-1")
    deletion_policy = spec.get("deletionPolicy", "Delete")
    
    sts_client = vpc_boto3_client("sts", region_name=region)
    account_id = sts_client.get_caller_identity()["Account"]
    naming = ResourceNaming(capability_name, environment, account_id=account_id)
    
    # Always delete Kubernetes resources
    logger.info("Cleaning up Kubernetes resources...")
    k8s = KubernetesResourceCreator(namespace)
    await k8s.delete_all(naming)
    
    # Delete admin credentials Secret
    try:
        from kubernetes import client as k8s_client
        core_api = k8s_client.CoreV1Api()
        secret_name = f"{capability_name}-{environment}-admin-credentials"
        core_api.delete_namespaced_secret(secret_name, namespace)
        logger.info(f"Deleted admin credentials Secret: {secret_name}")
    except Exception:
        pass  # Secret may not exist
    
    if deletion_policy == "Retain":
        logger.info("Deletion policy is Retain - keeping AWS resources")
        kopf.event(
            kwargs["body"],
            type="Normal",
            reason="DeletionComplete",
            message=f"Kubernetes resources deleted. AWS resources retained per deletionPolicy."
        )
        return
    
    logger.info("Deletion policy is Delete - cleaning up AWS resources")
    
    try:
        # Delete in reverse order of creation
        
        # Cognito User Pool (if enabled)
        if spec.get("enableCognito", False) or spec.get("cognito"):
            logger.info("Deleting Cognito User Pool...")
            cognito = CognitoProvisioner(naming, region)
            await cognito.delete_all()
        
        logger.info("IAM role lifecycle is admin-managed — skipping IAM deletion")
        
        # Secrets
        logger.info("Deleting Secrets Manager secrets...")
        secrets = SecretsProvisioner(naming, region)
        await secrets.delete_all()
        
        # SSM Parameters
        logger.info("Deleting SSM parameters...")
        ssm = SSMProvisioner(naming, region)
        await ssm.delete_all()
        
        # Glue
        logger.info("Deleting Glue resources...")
        glue = GlueProvisioner(naming, region)
        await glue.delete_all()
        
        # S3 (note: buckets must be empty)
        logger.info("Deleting S3 buckets...")
        s3 = S3Provisioner(naming, region)
        await s3.delete_all()
        
        # DynamoDB
        logger.info("Deleting DynamoDB tables...")
        dynamodb = DynamoDBProvisioner(naming, region)
        await dynamodb.delete_all()
        
        logger.info(f"NexusCapability {name} cleanup complete")
        
        kopf.event(
            kwargs["body"],
            type="Normal",
            reason="DeletionComplete",
            message=f"All resources for {capability_name} ({environment}) deleted"
        )
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        kopf.event(
            kwargs["body"],
            type="Warning",
            reason="DeletionError",
            message=f"Cleanup error: {e}"
        )


# ==================== Event Handlers ====================

@kopf.on.event("nexus.ai", "v1", "nexuscapabilities")
async def capability_event(event: dict, logger: logging.Logger, **kwargs):
    """
    Handle all NexusCapability events for logging.
    
    Requirements: 12.7
    """
    event_type = event.get("type", "UNKNOWN")
    obj = event.get("object", {})
    name = obj.get("metadata", {}).get("name", "unknown")
    
    if event_type != "MODIFIED":  # Reduce noise from frequent updates
        logger.debug(f"Event {event_type} for NexusCapability {name}")


# ==================== Main Entry Point ====================

async def run_operator():
    """Run the kopf operator."""
    await kopf.operator(
        clusterwide=True,
        standalone=True,
        priority=100,
        registry=None,
        liveness_endpoint=None,  # We handle this ourselves
    )


async def main_async():
    """Main async entry point."""
    # Start health check server
    health_runner = await start_health_server()
    
    try:
        # Run operator
        await run_operator()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await health_runner.cleanup()


def main():
    """Main entry point for the operator."""
    logger.info("=" * 60)
    logger.info("Nexus Kubernetes Operator")
    logger.info("=" * 60)
    logger.info(f"Log level: {LOG_LEVEL}")
    logger.info(f"Namespace: {os.environ.get('OPERATOR_NAMESPACE', 'default')}")
    
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")


if __name__ == "__main__":
    main()
