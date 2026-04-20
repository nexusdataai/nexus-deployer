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


# ══════════════════════════════════════════════════════════════════════
# NexusNetworkConfig handlers -- VPC Endpoint lifecycle
# ══════════════════════════════════════════════════════════════════════

@kopf.on.create("nexus.ai", "v1", "nexusnetworkconfigs")
async def create_network_config(spec: dict, name: str, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """Provision VPC Gateway and Interface endpoints for the cluster."""
    from .resources import VPCEndpointProvisioner

    region = spec.get("region", "ap-southeast-1")
    cluster_name = spec.get("clusterName", os.getenv("CLUSTER_NAME", ""))

    logger.info(f"NexusNetworkConfig '{name}': provisioning VPC endpoints for cluster {cluster_name}")
    patch.status["phase"] = "Provisioning"
    patch.status["message"] = "Creating VPC endpoints..."

    try:
        vpc_ep = VPCEndpointProvisioner(region, cluster_name=cluster_name)
        results = await vpc_ep.provision_all()

        endpoints = []
        for r in results:
            endpoints.append({
                "service": r["name"],
                "endpointId": r.get("endpoint_id", ""),
                "type": r["type"],
                "state": r["status"],
            })

        healthy = sum(1 for e in endpoints if e["state"] in ("exists", "created"))
        patch.status["endpoints"] = endpoints
        patch.status["totalEndpoints"] = len(endpoints)
        patch.status["healthyEndpoints"] = healthy
        patch.status["lastChecked"] = datetime.now(timezone.utc).isoformat()

        if healthy == len(endpoints):
            patch.status["phase"] = "Ready"
            patch.status["message"] = f"All {healthy} endpoints healthy"
            logger.info(f"NexusNetworkConfig '{name}': Ready ({healthy}/{len(endpoints)} endpoints)")
        else:
            failed = [e["service"] for e in endpoints if e["state"] not in ("exists", "created")]
            patch.status["phase"] = "Error"
            patch.status["message"] = f"{len(failed)} endpoint(s) unhealthy: {', '.join(failed[:3])}"
            logger.warning(f"NexusNetworkConfig '{name}': {len(failed)} unhealthy endpoints")

    except Exception as e:
        patch.status["phase"] = "Error"
        patch.status["message"] = str(e)[:200]
        logger.error(f"NexusNetworkConfig '{name}': provisioning failed: {e}")


@kopf.on.timer("nexus.ai", "v1", "nexusnetworkconfigs", interval=300, initial_delay=60)
async def check_network_health(spec: dict, name: str, logger: logging.Logger, patch: kopf.Patch, **kwargs):
    """Periodic health check -- re-verify all VPC endpoints every 5 minutes."""
    from .resources import VPCEndpointProvisioner

    region = spec.get("region", "ap-southeast-1")
    cluster_name = spec.get("clusterName", os.getenv("CLUSTER_NAME", ""))

    try:
        vpc_ep = VPCEndpointProvisioner(region, cluster_name=cluster_name)
        results = await vpc_ep.provision_all()

        endpoints = []
        for r in results:
            endpoints.append({
                "service": r["name"],
                "endpointId": r.get("endpoint_id", ""),
                "type": r["type"],
                "state": r["status"],
            })

        healthy = sum(1 for e in endpoints if e["state"] in ("exists", "created"))
        patch.status["endpoints"] = endpoints
        patch.status["totalEndpoints"] = len(endpoints)
        patch.status["healthyEndpoints"] = healthy
        patch.status["lastChecked"] = datetime.now(timezone.utc).isoformat()
        patch.status["phase"] = "Ready" if healthy == len(endpoints) else "Error"

        if healthy < len(endpoints):
            failed = [e["service"] for e in endpoints if e["state"] not in ("exists", "created")]
            patch.status["message"] = f"{len(failed)} endpoint(s) unhealthy"
            logger.warning(f"NexusNetworkConfig '{name}' health check: {len(failed)} unhealthy")
        else:
            patch.status["message"] = f"All {healthy} endpoints healthy"

    except Exception as e:
        logger.warning(f"NexusNetworkConfig '{name}' health check failed: {e}")


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
        DynamoDBProvisioner,
        S3Provisioner,
        GlueProvisioner,
        SSMProvisioner,
        SecretsProvisioner,
        IAMProvisioner,
        KubernetesResourceCreator,
        CognitoProvisioner,
    )
    
    logger.info(f"Creating NexusCapability: {name} in namespace {namespace}")
    
    capability_name = spec.get("capabilityName", "")
    version = spec.get("version", "")
    environment = spec.get("environment", "")
    region = spec.get("region", "us-east-1")
    
    logger.info(f"Capability: {capability_name} v{version} ({environment}) in {region}")
    
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
            from kubernetes import client as k8s_client, config as k8s_config
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            crd_api = k8s_client.CustomObjectsApi()
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

        # ── Step 1: DynamoDB ──
        data_services = spec.get("dataServices", {})
        
        if data_services.get("dynamodb", {}).get("enabled", True):
            patch.status["phase"] = "ProvisioningDataServices"
            patch.status["message"] = "Creating DynamoDB tables..."
            _update_step(steps, "DynamoDB", "in_progress")
            patch.status["steps"] = list(steps)
            
            logger.info("Provisioning DynamoDB tables...")
            dynamodb = DynamoDBProvisioner(naming, region)
            results = await dynamodb.provision_all()
            resources["dynamodbTables"] = [r["name"] for r in results if r["status"] in ["created", "exists"]]
            
            _update_step(steps, "DynamoDB", "done", resources=resources["dynamodbTables"])
            patch.status["steps"] = list(steps)
            logger.info(f"DynamoDB done: {resources['dynamodbTables']}")
        else:
            _update_step(steps, "DynamoDB", "skipped")
            patch.status["steps"] = list(steps)
        
        # ── Step 2: S3 ──
        if data_services.get("s3", {}).get("enabled", True):
            patch.status["message"] = "Creating S3 buckets..."
            _update_step(steps, "S3", "in_progress")
            patch.status["steps"] = list(steps)
            
            logger.info("Provisioning S3 buckets...")
            s3 = S3Provisioner(naming, region)
            results = await s3.provision_all()
            resources["s3Buckets"] = [r["name"] for r in results if r["status"] in ["created", "exists"]]
            
            _update_step(steps, "S3", "done", resources=resources["s3Buckets"])
            patch.status["steps"] = list(steps)
            logger.info(f"S3 done: {resources['s3Buckets']}")
        else:
            _update_step(steps, "S3", "skipped")
            patch.status["steps"] = list(steps)
        
        # ── Step 3: Glue ──
        if data_services.get("glue", {}).get("enabled", True):
            patch.status["message"] = "Creating Glue database..."
            _update_step(steps, "Glue", "in_progress")
            patch.status["steps"] = list(steps)
            
            logger.info("Provisioning Glue database...")
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
            logger.info(f"Glue done: {glue_resources}")
        else:
            _update_step(steps, "Glue", "skipped")
            patch.status["steps"] = list(steps)
        
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
                admin_email = spec.get("adminEmail", "")
                frontend_url = spec.get("frontendUrl", "")
                callback_urls = spec.get("cognitoCallbackUrls", [])
                cognito_results = await cognito.provision_all(
                    admin_email=admin_email, frontend_url=frontend_url, callback_urls=callback_urls
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
                            admin_pw = admin_result.get("temporary_password", "")
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
        patch.status["phase"] = "ProvisioningSSM"
        patch.status["message"] = "Creating SSM parameters..."
        _update_step(steps, "SSM", "in_progress")
        patch.status["steps"] = list(steps)
        
        logger.info("Provisioning SSM parameters...")
        ssm = SSMProvisioner(naming, region)
        ssm_results = await ssm.provision_all(resources)
        resources["ssmParameters"] = [r["name"] for r in ssm_results if r["status"] in ["created", "exists"]]
        
        _update_step(steps, "SSM", "done", resources=resources["ssmParameters"])
        patch.status["steps"] = list(steps)
        logger.info(f"SSM done: {len(resources['ssmParameters'])} parameters")
        
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
            sts_client = vpc_boto3_client("sts", region_name=region)
            account_id = sts_client.get_caller_identity()["Account"]
            if verify_oidc_provider_exists(oidc_provider, account_id, region):
                logger.info(f"IRSA enabled with OIDC provider: {oidc_provider}")
            else:
                logger.warning("OIDC provider not registered in IAM - IRSA may not work")
        else:
            logger.warning("No OIDC provider found - falling back to EC2 trust policy")
        
        iam = IAMProvisioner(naming, region, oidc_provider=oidc_provider)
        iam_result = await iam.create_application_role(resources)
        if iam_result["status"] in ["created", "exists", "updated"]:
            resources["iamRoles"] = [iam_result["arn"]]
        
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
        sa_result = await k8s.create_service_account(naming, role_arn)
        sa_was_updated = sa_result.get("status") == "updated"
        
        _update_step(steps, "ServiceAccount", "done", resources=[naming.kubernetes_service_account("app")])
        patch.status["steps"] = list(steps)
        
        # ── Step 10: Backend ──
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
            restart_annotation = {"kubectl.kubernetes.io/restartedAt": _now_iso()}
            for dep_component in ["backend", "frontend"]:
                dep_name = naming.kubernetes_deployment(dep_component)
                try:
                    dep = k8s.apps_api.read_namespaced_deployment(name=dep_name, namespace=namespace)
                    if dep.spec.template.metadata.annotations is None:
                        dep.spec.template.metadata.annotations = {}
                    dep.spec.template.metadata.annotations.update(restart_annotation)
                    k8s.apps_api.patch_namespaced_deployment(name=dep_name, namespace=namespace, body=dep)
                    logger.info(f"Restarted Deployment {dep_name} for IRSA injection")
                except ApiException as restart_err:
                    if restart_err.status != 404:
                        logger.warning(f"Failed to restart {dep_name}: {restart_err}")
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
async def update_capability(spec: dict, name: str, namespace: str, status: dict, diff: kopf.Diff, logger: logging.Logger, **kwargs):
    """
    Handle NexusCapability updates.
    
    Performs rolling updates for configuration changes.
    
    Requirements: 4.10
    """
    from .utils.naming import ResourceNaming
    from .resources import KubernetesResourceCreator
    
    logger.info(f"Updating NexusCapability: {name} in namespace {namespace}")
    
    capability_name = spec.get("capabilityName", "")
    environment = spec.get("environment", "")
    region = spec.get("region", "us-east-1")
    
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
    
    # Pre-compute BSS Magic service name for FDW env var injection
    bssmagic_spec = spec.get("bssmagic", {})
    bssmagic_svc = (
        naming.kubernetes_service("bssmagic")
        if bssmagic_spec.get("enabled", False) and bssmagic_spec.get("image")
        else None
    )
    
    try:
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
        
        return {"phase": "Running", "message": "Update completed"}
        
    except Exception as e:
        logger.error(f"Failed to update capability {name}: {e}")
        kopf.event(
            kwargs["body"],
            type="Warning",
            reason="UpdateFailed",
            message=str(e)
        )
        return {"phase": "Failed", "message": str(e)}


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
        IAMProvisioner,
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
        
        # IAM roles (with OIDC provider for proper cleanup)
        logger.info("Deleting IAM roles...")
        from .utils.eks_utils import get_oidc_provider_for_irsa
        oidc_provider, _ = get_oidc_provider_for_irsa(region)
        iam = IAMProvisioner(naming, region, oidc_provider=oidc_provider)
        await iam.delete_application_role()
        
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
