"""
Kubernetes Resource Creator for deploying application components.

Feature: pure-eks-deployment
Requirements: 4.5, 4.8, 5.5
"""
import json
import logging
from typing import Dict, Any, Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.k8s_client import authed_api_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class KubernetesResourceCreator:
    """Creates Kubernetes resources for Nexus capability deployments."""

    def __init__(self, namespace: str):
        self.namespace = namespace
        api_client = authed_api_client()
        self.core_api = client.CoreV1Api(api_client=api_client)
        self.apps_api = client.AppsV1Api(api_client=api_client)
        self.networking_api = client.NetworkingV1Api(api_client=api_client)

    async def create_namespace_if_needed(self, naming: ResourceNaming) -> Dict[str, Any]:
        """Create namespace if it doesn't exist."""
        try:
            self.core_api.read_namespace(name=self.namespace)
            logger.info(f"Namespace {self.namespace} already exists")
            return {"name": self.namespace, "status": "exists", "type": "Namespace"}
        except ApiException as e:
            if e.status != 404:
                raise
        
        # Create namespace with labels
        namespace_body = client.V1Namespace(
            metadata=client.V1ObjectMeta(
                name=self.namespace,
                labels={
                    "app.kubernetes.io/managed-by": "nexus-operator",
                    "nexus.ai/capability": naming.capability_name,
                    "nexus.ai/environment": naming.environment,
                }
            )
        )
        
        try:
            self.core_api.create_namespace(body=namespace_body)
            logger.info(f"Created namespace: {self.namespace}")
            return {"name": self.namespace, "status": "created", "type": "Namespace"}
        except Exception as e:
            logger.error(f"Failed to create namespace {self.namespace}: {e}")
            return {"name": self.namespace, "status": "failed", "error": str(e), "type": "Namespace"}
    
    async def create_service_account(
        self, 
        naming: ResourceNaming, 
        iam_role_arn: str
    ) -> Dict[str, Any]:
        """Create or update ServiceAccount with IRSA annotation."""
        sa_name = naming.kubernetes_service_account()
        
        try:
            existing_sa = self.core_api.read_namespaced_service_account(name=sa_name, namespace=self.namespace)
            existing_annotations = existing_sa.metadata.annotations or {}
            current_role_arn = existing_annotations.get("eks.amazonaws.com/role-arn", "")
            
            if current_role_arn == iam_role_arn:
                logger.info(f"ServiceAccount {sa_name} already exists with correct IRSA annotation")
                return {"name": sa_name, "status": "exists", "type": "ServiceAccount"}
            
            logger.warning(
                f"ServiceAccount {sa_name} has stale/missing IRSA annotation "
                f"(current={current_role_arn!r}, expected={iam_role_arn!r}), patching..."
            )
            existing_annotations["eks.amazonaws.com/role-arn"] = iam_role_arn
            existing_sa.metadata.annotations = existing_annotations
            existing_sa.metadata.labels = existing_sa.metadata.labels or {}
            existing_sa.metadata.labels["app.kubernetes.io/managed-by"] = "nexus-operator"
            existing_sa.metadata.labels["nexus.ai/capability"] = naming.capability_name
            self.core_api.replace_namespaced_service_account(name=sa_name, namespace=self.namespace, body=existing_sa)
            logger.info(f"Patched ServiceAccount {sa_name} with role ARN: {iam_role_arn}")
            return {"name": sa_name, "status": "updated", "type": "ServiceAccount"}
        except ApiException as e:
            if e.status != 404:
                raise
        
        sa_body = client.V1ServiceAccount(
            metadata=client.V1ObjectMeta(
                name=sa_name,
                namespace=self.namespace,
                annotations={
                    "eks.amazonaws.com/role-arn": iam_role_arn,
                },
                labels={
                    "app.kubernetes.io/managed-by": "nexus-operator",
                    "nexus.ai/capability": naming.capability_name,
                }
            )
        )
        
        try:
            self.core_api.create_namespaced_service_account(namespace=self.namespace, body=sa_body)
            logger.info(f"Created ServiceAccount: {sa_name}")
            return {"name": sa_name, "status": "created", "type": "ServiceAccount"}
        except Exception as e:
            logger.error(f"Failed to create ServiceAccount {sa_name}: {e}")
            return {"name": sa_name, "status": "failed", "error": str(e), "type": "ServiceAccount"}

    async def ensure_worker_management_rbac(self, naming: ResourceNaming) -> Dict[str, Any]:
        """Grant backend SA permission to patch NexusCapability and read worker pods."""
        from kubernetes import client as k8s_client

        rbac_api = k8s_client.RbacAuthorizationV1Api(api_client=self.core_api.api_client)
        sa_name = naming.kubernetes_service_account()
        role_name = f"{naming.capability_name}-{naming.environment}-worker-manager"
        binding_name = role_name

        role = k8s_client.V1Role(
            metadata=k8s_client.V1ObjectMeta(name=role_name, namespace=self.namespace),
            rules=[
                k8s_client.V1PolicyRule(
                    api_groups=["nexus.ai"],
                    resources=["nexuscapabilities"],
                    verbs=["get", "list", "patch"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["apps"],
                    resources=["deployments"],
                    verbs=["get", "list", "patch"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=["pods"],
                    verbs=["get", "list"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["keda.sh"],
                    resources=["scaledobjects"],
                    verbs=["get", "list", "create", "patch", "delete"],
                ),
            ],
        )
        binding = k8s_client.V1RoleBinding(
            metadata=k8s_client.V1ObjectMeta(name=binding_name, namespace=self.namespace),
            role_ref=k8s_client.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="Role",
                name=role_name,
            ),
            subjects=[
                k8s_client.V1Subject(
                    kind="ServiceAccount",
                    name=sa_name,
                    namespace=self.namespace,
                )
            ],
        )

        try:
            rbac_api.create_namespaced_role(namespace=self.namespace, body=role)
        except ApiException as exc:
            if exc.status != 409:
                raise
            rbac_api.replace_namespaced_role(name=role_name, namespace=self.namespace, body=role)

        try:
            rbac_api.create_namespaced_role_binding(namespace=self.namespace, body=binding)
        except ApiException as exc:
            if exc.status != 409:
                raise
            rbac_api.replace_namespaced_role_binding(
                name=binding_name, namespace=self.namespace, body=binding
            )

        cluster_role_name = f"{naming.capability_name}-{naming.environment}-resource-reader"
        cluster_role = k8s_client.V1ClusterRole(
            metadata=k8s_client.V1ObjectMeta(name=cluster_role_name),
            rules=[
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=["nodes"],
                    verbs=["get", "list"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=["nodes/proxy"],
                    verbs=["get"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["metrics.k8s.io"],
                    resources=["nodes", "pods"],
                    verbs=["get", "list"],
                ),
            ],
        )
        cluster_binding = k8s_client.V1ClusterRoleBinding(
            metadata=k8s_client.V1ObjectMeta(name=cluster_role_name),
            role_ref=k8s_client.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="ClusterRole",
                name=cluster_role_name,
            ),
            subjects=[
                k8s_client.V1Subject(
                    kind="ServiceAccount",
                    name=sa_name,
                    namespace=self.namespace,
                )
            ],
        )
        try:
            rbac_api.create_cluster_role(body=cluster_role)
        except ApiException as exc:
            if exc.status != 409:
                raise
            rbac_api.replace_cluster_role(name=cluster_role_name, body=cluster_role)
        try:
            rbac_api.create_cluster_role_binding(body=cluster_binding)
        except ApiException as exc:
            if exc.status != 409:
                raise
            rbac_api.replace_cluster_role_binding(name=cluster_role_name, body=cluster_binding)

        return {"role": role_name, "binding": binding_name, "cluster_role": cluster_role_name, "status": "ready"}

    async def delete_job_worker_deployment(self, naming: ResourceNaming) -> Dict[str, Any]:
        dep_name = naming.kubernetes_deployment("job-worker")
        try:
            self.apps_api.delete_namespaced_deployment(name=dep_name, namespace=self.namespace)
            logger.info("Deleted job worker deployment %s", dep_name)
            return {"name": dep_name, "status": "deleted"}
        except ApiException as exc:
            if exc.status == 404:
                return {"name": dep_name, "status": "not_found"}
            raise

    async def deploy_backend(
        self,
        naming: ResourceNaming,
        image: str,
        replicas: int = 2,
        resources: Optional[Dict[str, str]] = None,
        environment: str = "dev",
        region: str = "us-east-1",
        use_clusterip: bool = False,
        use_nodeport: bool = False,
        bssmagic_service: Optional[str] = None,
        postgres_service: Optional[str] = None,
        postgres_database: str = "ontology_cp",
        postgres_user: str = "nexus",
        postgres_password: str = "nexus",
        redis_service: Optional[str] = None,
        aws_access_mode: str = "higher-cost",
        local_emulation: Optional[Dict[str, str]] = None,
        queue_mode: bool = False,
        component: str = "backend",
    ) -> str:
        """
        Deploy backend Deployment and Service.
        
        Args:
            naming: Resource naming utility
            image: Container image
            replicas: Number of replicas
            resources: Resource requests/limits
            environment: Environment name
            region: AWS region
            use_clusterip: If True, create ClusterIP service instead of LoadBalancer
                          (used when ALB Ingress handles external exposure)
            bssmagic_service: BSS Magic service name — when provided, injects FDW_PG_*
                             and BSSMAGIC_BASE_URL env vars for Ontos FDW integration
        
        Returns the backend service URL.
        """
        deployment_name = naming.kubernetes_deployment(component)
        service_name = naming.kubernetes_service("backend")
        sa_name = naming.kubernetes_service_account()
        is_worker = component == "job-worker"
        
        resources = resources or {}
        cpu_request = resources.get("cpu", "250m")
        memory_request = resources.get("memory", "512Mi")
        cpu_limit = resources.get("cpuLimit", "500m")
        memory_limit = resources.get("memoryLimit", "2Gi")
        
        # Generate a stable API key for gateway authentication
        import secrets as secrets_module
        api_key = secrets_module.token_urlsafe(24)

        skip_ssm = bool(local_emulation and local_emulation.get("skip_ssm_secrets", False))

        if naming.capability_name == "ai-engine":
            # Remote EKS uses legacy CloudFormation names (ai-engine-{purpose}-{env}).
            # Local K3s init uses {capability}-{environment}-{purpose} (same as ontology).
            if local_emulation:
                journeys_table = naming.dynamodb_table("journeys")
                executions_table = naming.dynamodb_table("executions")
                prompts_table = naming.dynamodb_table("prompts")
                logs_bucket = naming.journey_logs_bucket()
                reports_bucket = naming.journey_reports_bucket()
            else:
                journeys_table = naming.ai_engine_journeys_table()
                executions_table = naming.ai_engine_executions_table()
                prompts_table = naming.ai_engine_prompts_table()
                logs_bucket = naming.ai_engine_journey_logs_bucket()
                reports_bucket = naming.ai_engine_journey_reports_bucket()

            # Same bootstrap contract as remote EKS: SSM prefix (+ Secrets prefix for tool creds).
            env_vars = [
                client.V1EnvVar(name="ENVIRONMENT", value=environment),
                client.V1EnvVar(name="AWS_REGION", value=region),
                client.V1EnvVar(name="AWS_DEFAULT_REGION", value=region),
                client.V1EnvVar(
                    name="AWS_CA_BUNDLE",
                    value="/etc/ssl/certs/ca-certificates.crt",
                ),
                client.V1EnvVar(name="CAPABILITY_NAME", value=naming.capability_name),
                client.V1EnvVar(
                    name="SSM_PARAMETER_PREFIX",
                    value=naming.ssm_parameter_prefix(),
                ),
                client.V1EnvVar(
                    name="SECRETS_PREFIX",
                    value=naming.secret_name_prefix(),
                ),
                client.V1EnvVar(name="API_PORT", value="8000"),
                client.V1EnvVar(name="REGISTER_DEMO_STAGES", value="true"),
                client.V1EnvVar(
                    name="DYNAMODB_TRANSFORMATION_TABLE",
                    value=journeys_table,
                ),
                client.V1EnvVar(
                    name="DYNAMODB_EXECUTIONS_TABLE",
                    value=executions_table,
                ),
                client.V1EnvVar(
                    name="DYNAMODB_PROMPTS_TABLE",
                    value=prompts_table,
                ),
                client.V1EnvVar(
                    name="DYNAMODB_DLQ_TABLE",
                    value=naming.dynamodb_table("dlq"),
                ),
                client.V1EnvVar(
                    name="S3_JOURNEY_LOGS_BUCKET",
                    value=logs_bucket,
                ),
                client.V1EnvVar(
                    name="S3_JOURNEY_REPORTS_BUCKET",
                    value=reports_bucket,
                ),
                client.V1EnvVar(
                    name="GLUE_DATABASE_NAME",
                    value=naming.glue_database(),
                ),
            ]
        else:
            # Environment variables for SSM/Secrets access (ontology / nexus-ai)
            env_vars = [
                client.V1EnvVar(name="ENVIRONMENT", value=environment),
                client.V1EnvVar(name="AWS_REGION", value=region),
                client.V1EnvVar(name="AWS_DEFAULT_REGION", value=region),
                client.V1EnvVar(
                    name="AWS_CA_BUNDLE",
                    value="/etc/ssl/certs/ca-certificates.crt",
                ),
                client.V1EnvVar(name="CAPABILITY_NAME", value=naming.capability_name),
                client.V1EnvVar(name="SECRETS_PREFIX", value=naming.secret_name_prefix()),
                client.V1EnvVar(name="API_KEY", value=api_key),
                client.V1EnvVar(
                    name="DYNAMODB_TABLE",
                    value=naming.dynamodb_table("transformation-system"),
                ),
                client.V1EnvVar(
                    name="DYNAMODB_TRANSFORMATION_TABLE",
                    value=naming.dynamodb_table("transformation-system"),
                ),
                client.V1EnvVar(
                    name="DYNAMODB_LICENSE_TABLE",
                    value=naming.dynamodb_table("license"),
                ),
                client.V1EnvVar(
                    name="DYNAMODB_FOUNDRY_WORKSPACE_TABLE",
                    value=naming.dynamodb_table("foundry-workspace"),
                ),
                client.V1EnvVar(
                    name="FOUNDRY_WORKSPACE_TABLE",
                    value=naming.dynamodb_table("foundry-workspace"),
                ),
                client.V1EnvVar(
                    name="DYNAMODB_DIAGNOSTICS_TABLE",
                    value=naming.dynamodb_table("diagnostics"),
                ),
                client.V1EnvVar(
                    name="DIAGNOSTICS_TABLE",
                    value=naming.dynamodb_table("diagnostics"),
                ),
                client.V1EnvVar(
                    name="DYNAMODB_HEALTH_TABLE",
                    value=naming.dynamodb_table("health"),
                ),
                client.V1EnvVar(
                    name="HEALTH_TABLE",
                    value=naming.dynamodb_table("health"),
                ),
                client.V1EnvVar(
                    name="CONTROL_PLANE_AUDIT_TABLE",
                    value=naming.dynamodb_table("control-plane-audit"),
                ),
                client.V1EnvVar(
                    name="RBAC_TABLE",
                    value=naming.dynamodb_table("rbac"),
                ),
                client.V1EnvVar(
                    name="GLUE_DATABASE",
                    value=naming.glue_database(),
                ),
                client.V1EnvVar(
                    name="GLUE_DATABASE_NAME",
                    value=naming.glue_database(),
                ),
                client.V1EnvVar(name="WXCC_SIMULATOR_BASE_URL", value="http://localhost:8000/api/v1/simulator"),
                client.V1EnvVar(name="WXCC_SIMULATOR_ENABLED", value="true"),
            ]
            if not skip_ssm:
                env_vars.insert(
                    6,
                    client.V1EnvVar(
                        name="SSM_PARAMETER_PREFIX",
                        value=naming.ssm_parameter_prefix(),
                    ),
                )

        # AWS access mode — drives whether boto3 picks an explicit interface
        # endpoint URL (higher-cost) or relies on default public hostnames
        # routed via NAT instance / public IP (moderate, lowest-cost,
        # public-nodes).
        env_vars.append(client.V1EnvVar(name="AWS_ACCESS_MODE", value=aws_access_mode))
        if aws_access_mode in ("moderate", "lowest-cost", "public-nodes"):
            env_vars.append(client.V1EnvVar(
                name="AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS", value="true",
            ))
        
        # FDW + BSSMagic integration env vars (enables Ontos page and CRM service)
        if bssmagic_service:
            # The upstream BSS-Magic Postgres image still exposes its SFDC
            # foreign server / schema under a legacy capability-prefixed
            # name. The backend rewrites it to capability-neutral names
            # before any UI / API surfaces it -- supplied here so the
            # backend source can stay free of the legacy literal.
            legacy_fdw_server = "starhub_itxp2dev"
            legacy_fdw_schema = "starhub_itxp2dev"
            env_vars.extend([
                client.V1EnvVar(name="BSSMAGIC_BASE_URL", value=f"http://{bssmagic_service}:8000"),
                client.V1EnvVar(name="FDW_PG_HOST", value=bssmagic_service),
                client.V1EnvVar(name="FDW_PG_PORT", value="5432"),
                client.V1EnvVar(name="FDW_PG_DATABASE", value="bssmagic"),
                client.V1EnvVar(name="FDW_PG_USER", value="postgres"),
                client.V1EnvVar(name="FDW_PG_PASSWORD", value="admin"),
                client.V1EnvVar(name="FDW_PG_SCHEMA", value="public"),
                client.V1EnvVar(name="FDW_TMF_SPECS_DIR", value="/opt/tmf-specs"),
                client.V1EnvVar(name="LEGACY_FDW_SERVER", value=legacy_fdw_server),
                client.V1EnvVar(name="LEGACY_FDW_SCHEMA", value=legacy_fdw_schema),
            ])
            logger.info(f"FDW integration enabled: {bssmagic_service}:5432/bssmagic")

        if postgres_service and not bssmagic_service:
            env_vars.extend([
                client.V1EnvVar(name="FDW_PG_HOST", value=postgres_service),
                client.V1EnvVar(name="FDW_PG_PORT", value="5432"),
                client.V1EnvVar(name="FDW_PG_DATABASE", value=postgres_database),
                client.V1EnvVar(name="FDW_PG_USER", value=postgres_user),
                client.V1EnvVar(name="FDW_PG_PASSWORD", value=postgres_password),
                client.V1EnvVar(name="FDW_PG_SCHEMA", value="public"),
            ])
            logger.info(f"pgvector integration enabled: {postgres_service}:5432/{postgres_database}")
        
        if redis_service:
            env_vars.append(client.V1EnvVar(name="REDIS_URL", value=f"redis://{redis_service}:6379/0"))
            logger.info(f"Redis cache enabled: {redis_service}:6379")

        if queue_mode and redis_service:
            env_vars.extend([
                client.V1EnvVar(name="JOB_EXECUTION_MODE", value="queue"),
                client.V1EnvVar(name="SSE_REDIS_ENABLED", value="true"),
                client.V1EnvVar(name="MAX_GLOBAL_JOBS", value="50"),
                client.V1EnvVar(name="MAX_CONCURRENT_JOBS", value="50"),
            ])
            logger.info("Queue execution mode enabled (Redis Streams job pipeline)")

        if local_emulation:
            env_vars.extend([
                client.V1EnvVar(name="USE_LOCALSTACK", value="true"),
                client.V1EnvVar(name="LOCALSTACK_HOST", value=local_emulation["ministack_host"]),
                client.V1EnvVar(name="LOCALSTACK_PORT", value="4566"),
                client.V1EnvVar(name="AWS_ACCESS_KEY_ID", value=local_emulation.get("minio_access_key", "minioadmin")),
                client.V1EnvVar(name="AWS_SECRET_ACCESS_KEY", value=local_emulation.get("minio_secret_key", "minioadmin")),
                client.V1EnvVar(name="AWS_ENDPOINT_URL_DYNAMODB", value=local_emulation["scylla_url"]),
                client.V1EnvVar(name="AWS_ENDPOINT_URL_S3", value=local_emulation["minio_url"]),
                client.V1EnvVar(
                    name="AWS_ENDPOINT_URL_SSM",
                    value=local_emulation.get(
                        "ministack_url",
                        f"http://{local_emulation['ministack_host']}:4566",
                    ),
                ),
                client.V1EnvVar(
                    name="AWS_ENDPOINT_URL_SECRETSMANAGER",
                    value=local_emulation.get(
                        "ministack_url",
                        f"http://{local_emulation['ministack_host']}:4566",
                    ),
                ),
                client.V1EnvVar(name="AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS", value="false"),
            ])
            logger.info(
                "Local emulation enabled: MiniStack=%s Scylla=%s MinIO=%s",
                local_emulation["ministack_host"],
                local_emulation["scylla_url"],
                local_emulation["minio_url"],
            )

        # Grafana Mimir - ontology / nexus-ai only (not used by ai-engine core)
        if naming.capability_name != "ai-engine":
            mimir_url = (
                local_emulation.get("mimir_url")
                if local_emulation and local_emulation.get("mimir_url")
                else f"http://mimir-svc.{self.namespace}.svc.cluster.local:8080"
            )
            env_vars.extend([
                client.V1EnvVar(name="MIMIR_ENABLED", value="true"),
                client.V1EnvVar(name="MIMIR_URL", value=mimir_url),
                client.V1EnvVar(name="MIMIR_TENANT_ID", value="nexus-default"),
                client.V1EnvVar(name="SOLUTION_RESULTS_BUCKET", value=naming.solution_results_bucket()),
            ])

        if naming.capability_name == "ontology":
            sim_ns = f"simulator-{naming.environment}"
            sim_ui = (
                "http://localhost:8082"
                if naming.environment == "local"
                else f"http://simulator-{naming.environment}-frontend-svc.{sim_ns}.svc.cluster.local:8080"
            )
            env_vars.extend([
                client.V1EnvVar(name="SIMULATOR_ENABLED", value="true"),
                client.V1EnvVar(
                    name="SIMULATOR_BASE_URL",
                    value=f"http://simulator-{naming.environment}-backend-svc-internal.{sim_ns}.svc.cluster.local:8000",
                ),
                client.V1EnvVar(name="SIMULATOR_UI_URL", value=sim_ui),
            ])
        
        # Backend health probes: ontology cold-start vs ai-engine / local fast path
        if is_worker:
            worker_port = 8081
            backend_startup_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/live", port=worker_port),
                initial_delay_seconds=5,
                period_seconds=5,
                timeout_seconds=3,
                failure_threshold=12,
            )
            backend_liveness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/live", port=worker_port),
                initial_delay_seconds=15,
                period_seconds=10,
                timeout_seconds=5,
                failure_threshold=3,
            )
            backend_readiness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/ready", port=worker_port),
                initial_delay_seconds=5,
                period_seconds=5,
                timeout_seconds=3,
                failure_threshold=3,
            )
        elif naming.capability_name == "ai-engine":
            backend_startup_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=5,
                period_seconds=5,
                timeout_seconds=3,
                failure_threshold=12,
            )
            backend_liveness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=15,
                period_seconds=10,
                timeout_seconds=5,
                failure_threshold=3,
            )
            backend_readiness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=5,
                period_seconds=5,
                timeout_seconds=3,
                failure_threshold=3,
            )
        else:
            backend_startup_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=30,
                period_seconds=10,
                timeout_seconds=5,
                failure_threshold=60,
            )
            backend_liveness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=240,
                period_seconds=15,
                timeout_seconds=5,
                failure_threshold=5,
            )
            backend_readiness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=60,
                period_seconds=10,
                timeout_seconds=5,
                failure_threshold=5,
            )

        worker_container_kwargs: Dict[str, Any] = {}
        if is_worker:
            worker_container_kwargs = {
                "command": ["nexus-ai-engine", "worker"],
                "ports": [client.V1ContainerPort(container_port=8081, name="health")],
            }
        else:
            worker_container_kwargs = {
                "ports": [client.V1ContainerPort(container_port=8000)],
            }

        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=deployment_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, component),
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                # Explicit RollingUpdate strategy: never surge above ``replicas``
                # (maxSurge=0) but allow one pod to be temporarily unavailable
                # (maxUnavailable=1). Prevents the slow-start backend cold-start
                # from stacking a 3rd pod that gets stuck for resources when
                # replicas=2. Steady-state pod count stays at ``replicas``.
                strategy=client.V1DeploymentStrategy(
                    type="RollingUpdate",
                    rolling_update=client.V1RollingUpdateDeployment(
                        max_surge=0,
                        max_unavailable=1,
                    ),
                ),
                selector=client.V1LabelSelector(
                    match_labels={"app": deployment_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": deployment_name, **self._common_labels(naming, component)}
                    ),
                    spec=client.V1PodSpec(
                        service_account_name=sa_name,
                        containers=[
                            client.V1Container(
                                name=component,
                                image=image,
                                env=env_vars,
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": cpu_request, "memory": memory_request},
                                    limits={"cpu": cpu_limit, "memory": memory_limit},
                                ),
                                startup_probe=backend_startup_probe,
                                liveness_probe=backend_liveness_probe,
                                readiness_probe=backend_readiness_probe,
                                **worker_container_kwargs,
                            )
                        ],
                    ),
                ),
            ),
        )
        
        await self._apply_deployment(deployment_name, deployment)

        if queue_mode and not is_worker:
            try:
                await self.ensure_worker_management_rbac(naming)
            except Exception as exc:
                logger.warning("Worker management RBAC setup failed: %s", exc)

        if is_worker:
            logger.info(f"Deployed job worker: {deployment_name} ({replicas} replicas)")
            return deployment_name
        
        # Determine service type: ClusterIP for ALB Ingress, NodePort for local K3s, LoadBalancer otherwise
        if use_clusterip:
            service_type = "ClusterIP"
        elif use_nodeport:
            service_type = "NodePort"
        else:
            service_type = "LoadBalancer"

        service_ports = [client.V1ServicePort(port=8000, target_port=8000, protocol="TCP", name="http")]
        if use_nodeport:
            service_ports[0].node_port = self._nodeport_for_capability(naming, "backend")

        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "backend"),
            ),
            spec=client.V1ServiceSpec(
                type=service_type,
                selector={"app": deployment_name},
                ports=service_ports,
            ),
        )
        
        svc_result = await self._apply_service(service_name, service)
        
        # Also create an internal ClusterIP service for frontend-to-backend communication
        # Frontend Nginx proxies to backend using this internal service name
        internal_service_name = f"{service_name}-internal"
        internal_service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=internal_service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "backend"),
                annotations={
                    "nexus.ai/purpose": "internal-backend-communication",
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": deployment_name},
                ports=[client.V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
            ),
        )
        await self._apply_service(internal_service_name, internal_service)
        logger.info(f"Created internal backend service: {internal_service_name}")
        
        return svc_result.get("url", f"{service_name}.{self.namespace}.svc.cluster.local:8000")

    async def deploy_job_worker(
        self,
        naming: ResourceNaming,
        image: str,
        replicas: int = 1,
        resources: Optional[Dict[str, str]] = None,
        environment: str = "dev",
        region: str = "us-east-1",
        redis_service: Optional[str] = None,
        aws_access_mode: str = "higher-cost",
        local_emulation: Optional[Dict[str, str]] = None,
    ) -> str:
        """Deploy Redis Streams job worker (ai-engine only, same image as backend)."""
        worker_resources = resources or {
            "cpu": "500m",
            "memory": "1Gi",
            "cpuLimit": "2",
            "memoryLimit": "4Gi",
        }
        return await self.deploy_backend(
            naming=naming,
            image=image,
            replicas=replicas,
            resources=worker_resources,
            environment=environment,
            region=region,
            use_clusterip=True,
            redis_service=redis_service,
            aws_access_mode=aws_access_mode,
            local_emulation=local_emulation,
            queue_mode=True,
            component="job-worker",
        )

    async def deploy_bssmagic(
        self,
        naming: ResourceNaming,
        image: str,
        replicas: int = 1,
        resources: Optional[Dict[str, str]] = None,
        credentials_secret_name: str = "",
        axway_secret_name: str = "",
        dump_s3_bucket: str = "",
        dump_s3_key: str = "bssmagic-dump.sql.gz",
        storage_size: str = "10Gi",
        storage_class: Optional[str] = None,
        region: str = "us-east-1",
        extra_env: Optional[list] = None,
        aws_access_mode: str = "higher-cost",
    ) -> str:
        """
        Deploy BSS Magic runtime as a single StatefulSet with embedded PostgreSQL.

        The Phase 2 all-in-one image includes PostgreSQL, TMF Server, Controller,
        FDW (Axway proxy), and baked-in pg_dump. No separate PostgreSQL pod needed.

        Creates:
        - StatefulSet with PVC for PostgreSQL data persistence
        - Init container 1: Fetch pg_dump from S3 (if bucket configured)
        - Init container 2: Fetch credentials.zip from Secrets Manager (if secret configured)
        - Axway config injected as env vars (fetched from Secrets Manager by operator)
        - ClusterIP Service (also exposed at /bssmagic via ALB for future product UI)

        Ports:
        - 5432: PostgreSQL (internal FDW access for Ontos page)
        - 8000: TMF API proxy (handles /query and writes locally, proxies GETs to internal TMF Server on 8001)
        - 3000: Controller health/metrics

        Returns the bssmagic service name for internal backend communication.
        """
        sa_name = naming.kubernetes_service_account()

        resources = resources or {}
        cpu_request = resources.get("cpu", "250m")
        memory_request = resources.get("memory", "512Mi")
        cpu_limit = resources.get("cpuLimit", "1000m")
        memory_limit = resources.get("memoryLimit", "4Gi")

        bssmagic_sts_name = naming.kubernetes_deployment("bssmagic")
        bssmagic_service_name = naming.kubernetes_service("bssmagic")

        # ── Environment variables ──
        bssmagic_env = [
            client.V1EnvVar(name="POSTGRES_PASSWORD", value="admin"),
            client.V1EnvVar(name="POSTGRES_DB", value="bssmagic"),
            # PGDATA must be a subdirectory of the PVC mount to avoid ext4 lost+found conflict
            client.V1EnvVar(name="PGDATA", value="/var/lib/postgresql/data/pgdata"),
            # AWS access mode — propagated so any embedded boto3 / awscli
            # init-container respects the cluster's network profile.
            client.V1EnvVar(name="AWS_ACCESS_MODE", value=aws_access_mode),
        ]
        if aws_access_mode in ("moderate", "lowest-cost", "public-nodes"):
            bssmagic_env.append(client.V1EnvVar(
                name="AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS", value="true",
            ))

        # S3 dump config (used by restore-if-needed.sh to upload snapshots)
        if dump_s3_bucket:
            bssmagic_env.append(client.V1EnvVar(name="DUMP_S3_BUCKET", value=dump_s3_bucket))
            bssmagic_env.append(client.V1EnvVar(name="DUMP_S3_KEY", value=dump_s3_key))

        # Axway config: operator fetches JSON from Secrets Manager and injects as env vars.
        # If axway_secret_name is provided, the operator reads the secret at deploy time
        # and adds each key as an env var. This keeps Axway config out of the image.
        if axway_secret_name:
            axway_env = self._fetch_axway_env_from_secret(axway_secret_name, region)
            bssmagic_env.extend(axway_env)

        # User-specified env overrides (e.g., MYSALESFORCE_USERNAME)
        if extra_env:
            for ev in extra_env:
                bssmagic_env.append(client.V1EnvVar(name=ev.get("name", ""), value=ev.get("value", "")))

        # ── Init containers ──
        init_containers = []
        volumes = []
        volume_mounts = []

        # Init 1: Fetch pg_dump from S3
        if dump_s3_bucket:
            s3_fetch_script = (
                f'echo "Fetching dump from s3://{dump_s3_bucket}/{dump_s3_key}..." && '
                f'aws s3 cp "s3://{dump_s3_bucket}/{dump_s3_key}" /mnt/dump/bssmagic-dump.sql.gz'
                f' --region "{region}" --quiet 2>/dev/null'
                ' && echo "S3 dump fetched ($(wc -c < /mnt/dump/bssmagic-dump.sql.gz) bytes)"'
                ' || echo "WARN: S3 dump not found -- will use baked-in dump"'
            )
            init_containers.append(
                client.V1Container(
                    name="fetch-dump",
                    image="amazon/aws-cli:latest",
                    command=["sh", "-c", s3_fetch_script],
                    volume_mounts=[
                        client.V1VolumeMount(name="dump-volume", mount_path="/mnt/dump")
                    ],
                )
            )
            volumes.append(
                client.V1Volume(name="dump-volume", empty_dir=client.V1EmptyDirVolumeSource())
            )
            volume_mounts.append(
                client.V1VolumeMount(name="dump-volume", mount_path="/mnt/dump")
            )

        # Init 2: Fetch credentials.zip from Secrets Manager
        # Retries with backoff to handle IAM propagation delay after role creation
        if credentials_secret_name:
            creds_fetch_script = (
                'set -e; '
                'MAX_ATTEMPTS=6; DELAY=5; '
                'for i in $(seq 1 $MAX_ATTEMPTS); do '
                '  echo "Attempt $i/$MAX_ATTEMPTS: fetching credentials.zip from Secrets Manager..."; '
                '  if aws secretsmanager get-secret-value'
                '    --secret-id "$CREDENTIALS_SECRET_NAME"'
                '    --query SecretBinary --output text'
                f'    --region "{region}"'
                '    > /tmp/creds_b64 2>/tmp/creds_err; then '
                '    base64 -d < /tmp/creds_b64 > /credentials/credentials.zip; '
                '    SIZE=$(wc -c < /credentials/credentials.zip); '
                '    if [ "$SIZE" -gt 100 ]; then '
                '      echo "credentials.zip fetched ($SIZE bytes)"; '
                '      exit 0; '
                '    else '
                '      echo "WARNING: credentials.zip too small ($SIZE bytes), retrying..."; '
                '    fi; '
                '  else '
                '    echo "ERROR: $(cat /tmp/creds_err)"; '
                '  fi; '
                '  if [ "$i" -lt "$MAX_ATTEMPTS" ]; then '
                '    echo "Waiting ${DELAY}s before retry (IAM propagation)..."; '
                '    sleep $DELAY; DELAY=$((DELAY * 2)); '
                '  fi; '
                'done; '
                'echo "FATAL: Failed to fetch credentials.zip after $MAX_ATTEMPTS attempts"; '
                'exit 1'
            )
            init_containers.append(
                client.V1Container(
                    name="fetch-credentials",
                    image="amazon/aws-cli:latest",
                    command=["sh", "-c", creds_fetch_script],
                    env=[
                        client.V1EnvVar(name="CREDENTIALS_SECRET_NAME", value=credentials_secret_name),
                    ],
                    volume_mounts=[
                        client.V1VolumeMount(name="credentials-volume", mount_path="/credentials")
                    ],
                )
            )
            volumes.append(
                client.V1Volume(name="credentials-volume", empty_dir=client.V1EmptyDirVolumeSource())
            )
            volume_mounts.append(
                client.V1VolumeMount(
                    name="credentials-volume",
                    mount_path="/credentials.zip",
                    sub_path="credentials.zip",
                    read_only=True,
                )
            )

        # ── PVC for PostgreSQL data persistence ──
        volume_claim_templates = [
            client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(name="postgres-data"),
                spec=client.V1PersistentVolumeClaimSpec(
                    access_modes=["ReadWriteOnce"],
                    resources=client.V1VolumeResourceRequirements(
                        requests={"storage": storage_size}
                    ),
                    **({"storage_class_name": storage_class} if storage_class else {}),
                ),
            )
        ]

        # Add PVC mount
        volume_mounts.append(
            client.V1VolumeMount(
                name="postgres-data",
                mount_path="/var/lib/postgresql/data",
            )
        )

        # ── StatefulSet (all-in-one: PG + TMF Server + Controller + FDW + TMF REST API) ──
        bssmagic_sts = client.V1StatefulSet(
            metadata=client.V1ObjectMeta(
                name=bssmagic_sts_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "bssmagic"),
            ),
            spec=client.V1StatefulSetSpec(
                replicas=replicas,
                service_name=bssmagic_service_name,
                selector=client.V1LabelSelector(
                    match_labels={"app": bssmagic_sts_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": bssmagic_sts_name, **self._common_labels(naming, "bssmagic")}
                    ),
                    spec=client.V1PodSpec(
                        service_account_name=sa_name,
                        init_containers=init_containers if init_containers else None,
                        volumes=volumes if volumes else None,
                        containers=[
                            client.V1Container(
                                name="bssmagic-runtime",
                                image=image,
                                ports=[
                                    client.V1ContainerPort(container_port=5432, name="postgres"),
                                    client.V1ContainerPort(container_port=8000, name="tmf-api"),
                                    client.V1ContainerPort(container_port=3000, name="health"),
                                ],
                                env=bssmagic_env,
                                volume_mounts=volume_mounts if volume_mounts else None,
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": cpu_request, "memory": memory_request},
                                    limits={"cpu": cpu_limit, "memory": memory_limit},
                                ),
                                liveness_probe=client.V1Probe(
                                    tcp_socket=client.V1TCPSocketAction(port=5432),
                                    initial_delay_seconds=120,
                                    period_seconds=30,
                                    timeout_seconds=5,
                                    failure_threshold=10,
                                ),
                                readiness_probe=client.V1Probe(
                                    tcp_socket=client.V1TCPSocketAction(port=5432),
                                    initial_delay_seconds=90,
                                    period_seconds=10,
                                    timeout_seconds=5,
                                    failure_threshold=10,
                                ),
                            )
                        ],
                    ),
                ),
                volume_claim_templates=volume_claim_templates,
            ),
        )

        await self._apply_statefulset(bssmagic_sts_name, bssmagic_sts)

        # ── ClusterIP Service ──
        # Backend connects via: {svc}.{ns}.svc.cluster.local
        #   :8000 — TMF API proxy (also exposed via ALB at /bssmagic)
        #   :5432 — PostgreSQL (FDW access for Ontos page, internal only)
        #   :3000 — Controller health/metrics
        bssmagic_service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=bssmagic_service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "bssmagic"),
                annotations={
                    "nexus.ai/purpose": "internal-bssmagic-runtime",
                },
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": bssmagic_sts_name},
                ports=[
                    client.V1ServicePort(port=5432, target_port=5432, protocol="TCP", name="postgres"),
                    client.V1ServicePort(port=8000, target_port=8000, protocol="TCP", name="tmf-api"),
                    client.V1ServicePort(port=3000, target_port=3000, protocol="TCP", name="health"),
                ],
            ),
        )
        await self._apply_service(bssmagic_service_name, bssmagic_service)

        logger.info(f"Deployed bssmagic-runtime StatefulSet: {bssmagic_sts_name}")
        return bssmagic_service_name

    async def deploy_redis(
        self,
        naming: ResourceNaming,
        maxmemory: str = "2gb",
        storage_size: str = "2Gi",
        storage_class: Optional[str] = None,
    ) -> str:
        """
        Deploy Redis as a StatefulSet with ClusterIP Service for simulator data caching.

        Returns the Redis service name for REDIS_URL injection.
        """
        redis_sts_name = "redis"
        redis_service_name = "redis-svc"

        statefulset = client.V1StatefulSet(
            metadata=client.V1ObjectMeta(
                name=redis_sts_name,
                namespace=self.namespace,
                labels={**self._common_labels(naming, "redis")},
            ),
            spec=client.V1StatefulSetSpec(
                replicas=1,
                service_name=redis_service_name,
                selector=client.V1LabelSelector(
                    match_labels={"app": "redis"}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": "redis", **self._common_labels(naming, "redis")}
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="redis",
                                image="redis:7-alpine",
                                ports=[client.V1ContainerPort(container_port=6379, name="redis")],
                                command=["redis-server", "--maxmemory", maxmemory,
                                         "--maxmemory-policy", "allkeys-lru",
                                         "--appendonly", "yes", "--appendfsync", "everysec"],
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": "100m", "memory": "256Mi"},
                                    limits={"cpu": "500m", "memory": "2560Mi"},
                                ),
                                readiness_probe=client.V1Probe(
                                    _exec=client.V1ExecAction(command=["redis-cli", "ping"]),
                                    initial_delay_seconds=5, period_seconds=10,
                                ),
                                liveness_probe=client.V1Probe(
                                    _exec=client.V1ExecAction(command=["redis-cli", "ping"]),
                                    initial_delay_seconds=15, period_seconds=20,
                                ),
                                volume_mounts=[
                                    client.V1VolumeMount(name="redis-data", mount_path="/data")
                                ],
                            )
                        ],
                    ),
                ),
                volume_claim_templates=[
                    client.V1PersistentVolumeClaim(
                        metadata=client.V1ObjectMeta(name="redis-data"),
                        spec=client.V1PersistentVolumeClaimSpec(
                            access_modes=["ReadWriteOnce"],
                            resources=client.V1VolumeResourceRequirements(
                                requests={"storage": storage_size}
                            ),
                            **({"storage_class_name": storage_class} if storage_class else {}),
                        ),
                    )
                ],
            ),
        )
        await self._apply_statefulset(redis_sts_name, statefulset)

        redis_service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=redis_service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "redis"),
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": "redis"},
                ports=[client.V1ServicePort(port=6379, target_port=6379, protocol="TCP", name="redis")],
            ),
        )
        await self._apply_service(redis_service_name, redis_service)

        logger.info(f"Deployed Redis StatefulSet: {redis_sts_name}, service: {redis_service_name}")
        return redis_service_name

    async def deploy_postgres(
        self,
        naming: ResourceNaming,
        image: str,
        storage_size: str = "5Gi",
        storage_class: Optional[str] = "gp2",
        database: str = "ontology_cp",
        user: str = "nexus",
        password: str = "nexus",
    ) -> str:
        """
        Deploy pgvector Postgres for AI Control Plane embeddings (semantic_rag).

        Returns the Postgres service name for FDW_PG_* injection.
        """
        pg_sts_name = "pgvector"
        pg_service_name = "pgvector-svc"

        statefulset = client.V1StatefulSet(
            metadata=client.V1ObjectMeta(
                name=pg_sts_name,
                namespace=self.namespace,
                labels={**self._common_labels(naming, "pgvector")},
            ),
            spec=client.V1StatefulSetSpec(
                replicas=1,
                service_name=pg_service_name,
                selector=client.V1LabelSelector(match_labels={"app": pg_sts_name}),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": pg_sts_name, **self._common_labels(naming, "pgvector")}
                    ),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name="postgres",
                                image=image,
                                ports=[client.V1ContainerPort(container_port=5432, name="postgres")],
                                env=[
                                    client.V1EnvVar(name="POSTGRES_USER", value=user),
                                    client.V1EnvVar(name="POSTGRES_PASSWORD", value=password),
                                    client.V1EnvVar(name="POSTGRES_DB", value=database),
                                    client.V1EnvVar(name="PGDATA", value="/var/lib/postgresql/data/pgdata"),
                                ],
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": "100m", "memory": "256Mi"},
                                    limits={"cpu": "500m", "memory": "1Gi"},
                                ),
                                readiness_probe=client.V1Probe(
                                    _exec=client.V1ExecAction(
                                        command=["pg_isready", "-U", user, "-d", database]
                                    ),
                                    initial_delay_seconds=5,
                                    period_seconds=10,
                                ),
                                liveness_probe=client.V1Probe(
                                    _exec=client.V1ExecAction(
                                        command=["pg_isready", "-U", user, "-d", database]
                                    ),
                                    initial_delay_seconds=15,
                                    period_seconds=20,
                                ),
                                volume_mounts=[
                                    client.V1VolumeMount(name="pgvector-data", mount_path="/var/lib/postgresql/data")
                                ],
                            )
                        ],
                    ),
                ),
                volume_claim_templates=[
                    client.V1PersistentVolumeClaim(
                        metadata=client.V1ObjectMeta(name="pgvector-data"),
                        spec=client.V1PersistentVolumeClaimSpec(
                            access_modes=["ReadWriteOnce"],
                            resources=client.V1VolumeResourceRequirements(
                                requests={"storage": storage_size}
                            ),
                            **({"storage_class_name": storage_class} if storage_class else {}),
                        ),
                    )
                ],
            ),
        )
        await self._apply_statefulset(pg_sts_name, statefulset)

        pg_service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=pg_service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "pgvector"),
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": pg_sts_name},
                ports=[client.V1ServicePort(port=5432, target_port=5432, protocol="TCP", name="postgres")],
            ),
        )
        await self._apply_service(pg_service_name, pg_service)

        logger.info(f"Deployed pgvector StatefulSet: {pg_sts_name}, service: {pg_service_name}")
        return pg_service_name

    def _fetch_axway_env_from_secret(self, secret_name: str, region: str) -> list:
        """
        Fetch Axway config from Secrets Manager and return as K8s env vars.

        The secret is expected to be a JSON object with keys like:
        AXWAY_TOKEN_URL, AXWAY_QUERY_URL, AXWAY_CLIENT_ID, AXWAY_CLIENT_SECRET,
        AXWAY_KEY_ID, AXWAY_PROVIDER_ORG, AXWAY_LEAD_CREATE_URL,
        AXWAY_CONTENT_VERSION_URL, AXWAY_CONTENT_DOCUMENT_LINK_URL,
        AXWAY_ATTACHMENT_URL
        """
        import json as json_module
        try:
            sm_client = vpc_boto3_client("secretsmanager", region_name=region)
            response = sm_client.get_secret_value(SecretId=secret_name)
            secret_data = json_module.loads(response["SecretString"])

            env_vars = []
            for key, value in secret_data.items():
                if key.startswith("AXWAY_") and value:
                    env_vars.append(client.V1EnvVar(name=key, value=str(value)))

            logger.info(f"Loaded {len(env_vars)} Axway env vars from secret: {secret_name}")
            return env_vars
        except Exception as e:
            logger.warning(f"Could not fetch Axway config from secret {secret_name}: {e}")
            logger.warning("BSS Magic will use default UAT Axway endpoints from image")
            return []

    async def deploy_frontend(
        self,
        naming: ResourceNaming,
        image: str,
        replicas: int = 2,
        resources: Optional[Dict[str, str]] = None,
        ingress_config: Optional[Dict[str, Any]] = None,
        backend_service: Optional[str] = None,
        bssmagic_service: Optional[str] = None,
        internal_ingress_config: Optional[Dict[str, Any]] = None,
        use_nodeport: bool = False,
    ) -> str:
        """
        Deploy frontend Deployment and Service.
        
        When ingress_config is provided, creates a ClusterIP service and ALB Ingress
        instead of a LoadBalancer service.
        
        Args:
            naming: Resource naming utility
            image: Container image
            replicas: Number of replicas
            resources: Resource requests/limits
            ingress_config: Optional ALB ingress configuration (public)
            backend_service: Backend service name (required if ingress_config is provided)
            bssmagic_service: BSS Magic service name (optional, exposed at /bssmagic for future product UI)
            internal_ingress_config: Optional internal ALB ingress configuration (VPC-only)
        
        Returns the frontend URL (LoadBalancer URL or ALB Ingress URL).
        """
        deployment_name = naming.kubernetes_deployment("frontend")
        service_name = naming.kubernetes_service("frontend")
        sa_name = naming.kubernetes_service_account()
        
        resources = resources or {}
        cpu_request = resources.get("cpu", "250m")
        memory_request = resources.get("memory", "256Mi")
        cpu_limit = resources.get("cpuLimit", "500m")
        memory_limit = resources.get("memoryLimit", "512Mi")
        
        # Create ConfigMap with nginx.conf for the frontend nginx sidecar.
        #
        # The previous-generation runtime config.json (with api.baseUrl,
        # gateway.apiKey, cognito settings, etc.) has been removed: all
        # authentication and API routing is now managed by the backend
        # service, called same-origin via nginx (/api/* proxied to the
        # backend-internal service below). The frontend SPA no longer
        # fetches /config.json at boot.
        backend_internal_svc = f"{naming.kubernetes_service('backend')}-internal"
        nginx_conf = self._generate_nginx_conf(backend_internal_svc)

        configmap_name = f"{deployment_name}-config"
        configmap_data: Dict[str, str] = {"nginx.conf": nginx_conf}
        volume_mounts = [
            client.V1VolumeMount(
                name="config-volume",
                mount_path="/etc/nginx/nginx.conf",
                sub_path="nginx.conf",
            ),
        ]
        if use_nodeport:
            # Local K3s skips Cognito — serve runtime config so the SPA bypasses auth.
            configmap_data["config.json"] = json.dumps({
                "deploymentMode": "eks",
                "bypassAuth": True,
                "environment": naming.environment,
                "api": {"baseUrl": "", "timeout": 30000},
                "dataSource": "api",
                "enableFallback": True,
            })
            volume_mounts.append(
                client.V1VolumeMount(
                    name="config-volume",
                    mount_path="/usr/share/nginx/html/config.json",
                    sub_path="config.json",
                )
            )

        configmap = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=configmap_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "frontend"),
            ),
            data=configmap_data,
        )
        try:
            self.core_api.create_namespaced_config_map(self.namespace, configmap)
        except Exception:
            self.core_api.replace_namespaced_config_map(configmap_name, self.namespace, configmap)
        logger.info(f"Created ConfigMap {configmap_name} with nginx.conf for frontend")
        
        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=deployment_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "frontend"),
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                # Match backend: maxSurge=0 so rolling updates never exceed
                # ``replicas`` running pods; maxUnavailable=1 keeps at least
                # one replica serving traffic at all times.
                strategy=client.V1DeploymentStrategy(
                    type="RollingUpdate",
                    rolling_update=client.V1RollingUpdateDeployment(
                        max_surge=0,
                        max_unavailable=1,
                    ),
                ),
                selector=client.V1LabelSelector(
                    match_labels={"app": deployment_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": deployment_name, **self._common_labels(naming, "frontend")}
                    ),
                    spec=client.V1PodSpec(
                        service_account_name=sa_name,
                        volumes=[
                            client.V1Volume(
                                name="config-volume",
                                config_map=client.V1ConfigMapVolumeSource(name=configmap_name)
                            )
                        ],
                        containers=[
                            client.V1Container(
                                name="frontend",
                                image=image,
                                ports=[client.V1ContainerPort(container_port=8080)],
                                volume_mounts=volume_mounts,
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": cpu_request, "memory": memory_request},
                                    limits={"cpu": cpu_limit, "memory": memory_limit},
                                ),
                                liveness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/", port=8080),
                                    initial_delay_seconds=15,
                                    period_seconds=10,
                                    timeout_seconds=5,
                                    failure_threshold=3,
                                ),
                                readiness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/", port=8080),
                                    initial_delay_seconds=5,
                                    period_seconds=5,
                                    timeout_seconds=3,
                                    failure_threshold=3,
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )
        
        await self._apply_deployment(deployment_name, deployment)
        
        # Determine service type based on ingress config
        use_ingress = ingress_config and ingress_config.get("enabled", False)
        use_internal = internal_ingress_config and internal_ingress_config.get("enabled", False)
        if use_ingress or use_internal:
            service_type = "ClusterIP"
        elif use_nodeport:
            service_type = "NodePort"
        else:
            service_type = "LoadBalancer"

        frontend_ports = [client.V1ServicePort(port=8080, target_port=8080, protocol="TCP", name="http")]
        if use_nodeport:
            frontend_ports[0].node_port = self._nodeport_for_capability(naming, "frontend")
        
        # Create Service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "frontend"),
            ),
            spec=client.V1ServiceSpec(
                type=service_type,
                selector={"app": deployment_name},
                ports=frontend_ports,
            ),
        )
        
        await self._apply_service(service_name, service)
        
        ingress_url = ""
        
        # Create public ALB Ingress if enabled
        if use_ingress and backend_service:
            logger.info("Creating ALB Ingress for frontend exposure...")
            ingress_url = await self._create_alb_ingress(
                naming=naming,
                ingress_config=ingress_config,
                frontend_service=service_name,
                backend_service=backend_service,
                bssmagic_service=bssmagic_service,
            )
        elif use_ingress:
            logger.warning("Ingress enabled but backend_service not provided, skipping Ingress creation")
        
        # Create internal ALB Ingress if enabled (VPC-only access, independent of public ingress)
        if use_internal and backend_service:
            logger.info("Creating internal ALB Ingress for VPC-only access...")
            internal_url = await self._create_alb_ingress(
                naming=naming,
                ingress_config=internal_ingress_config,
                frontend_service=service_name,
                backend_service=backend_service,
                bssmagic_service=bssmagic_service,
                component="internal",
                scheme_override="internal",
            )
            if not ingress_url:
                ingress_url = internal_url
        
        if ingress_url:
            return ingress_url
        
        # Return LoadBalancer URL for non-ingress deployments
        return f"{service_name}.{self.namespace}.svc.cluster.local:8080"
    
    @staticmethod
    def _generate_nginx_conf(backend_svc: str) -> str:
        """Generate nginx.conf with the correct backend service name for this environment."""
        return f"""worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /tmp/nginx.pid;

events {{
    worker_connections 1024;
    use epoll;
    multi_accept on;
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 20M;

    gzip on;
    gzip_vary on;
    gzip_min_length 1000;
    gzip_comp_level 6;
    gzip_types
        text/plain text/css text/xml text/javascript
        application/json application/javascript application/xml+rss
        application/rss+xml font/truetype font/opentype
        application/vnd.ms-fontobject image/svg+xml;
    gzip_disable "msie6";

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    map $http_upgrade $connection_upgrade {{
        default upgrade;
        '' close;
    }}

    map $http_x_forwarded_proto $forwarded_proto_from_client {{
        default $http_x_forwarded_proto;
        ''      $scheme;
    }}
    map $http_cf_connecting_ip $proxy_forwarded_proto {{
        ""      $forwarded_proto_from_client;
        default https;
    }}

    server {{
        listen 8080;
        listen [::]:8080;
        server_name _;

        root /usr/share/nginx/html;
        index index.html;

        server_tokens off;

        location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {{
            expires 1y;
            add_header Cache-Control "public, immutable";
            access_log off;
        }}

        location ~* \\.(html)$ {{
            expires -1;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
            add_header Pragma "no-cache";
        }}

        location /health {{
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }}

        location ~ ^/(health|stats|tools|docs\\.html)$ {{
            proxy_pass http://{backend_svc}:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_http_version 1.1;
            proxy_connect_timeout 10s;
            proxy_read_timeout 30s;
        }}

        location = /version {{
            proxy_pass http://{backend_svc}:8000/version;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_http_version 1.1;
            proxy_connect_timeout 10s;
            proxy_read_timeout 30s;
        }}

        location ^~ /docs/ {{
            alias /usr/share/nginx/docs/;
            index index.html;
            try_files $uri $uri/ =404;
        }}

        location = /ui {{
            return 302 /journeys;
        }}

        location ^~ /ui/ {{
            return 302 /journeys;
        }}

        location /services/ {{
            proxy_pass http://{backend_svc}:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_http_version 1.1;
            proxy_read_timeout 60s;
        }}

        location /fscmRestApi/ {{
            proxy_pass http://{backend_svc}:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_http_version 1.1;
            proxy_read_timeout 60s;
        }}

        location /sap/ {{
            proxy_pass http://{backend_svc}:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_http_version 1.1;
            proxy_read_timeout 60s;
        }}

        location /api/ {{
            proxy_pass http://{backend_svc}:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $proxy_forwarded_proto;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
            proxy_redirect http:// https://;
            proxy_connect_timeout 10s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
            proxy_buffering off;
            proxy_request_buffering off;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            add_header Access-Control-Allow-Origin $http_origin always;
            add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
            add_header Access-Control-Allow-Headers "Authorization, Content-Type, Accept" always;
            add_header Access-Control-Allow-Credentials "true" always;
            if ($request_method = OPTIONS) {{
                return 204;
            }}
        }}

        location / {{
            try_files $uri $uri/ /index.html;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
            add_header Pragma "no-cache";
            add_header Expires "0";
        }}

        location ~ /\\. {{
            deny all;
            access_log off;
            log_not_found off;
        }}

        error_page 404 /index.html;
        error_page 500 502 503 504 /50x.html;
        location = /50x.html {{
            root /usr/share/nginx/html;
        }}
    }}
}}
"""

    def _nodeport_for_capability(self, naming: ResourceNaming, component: str) -> int:
        """Return a stable NodePort per capability to avoid collisions on local K3s."""
        ports_by_capability = {
            "ai-engine": {"backend": 30800, "frontend": 30808},
            "ontology": {"backend": 30801, "frontend": 30809},
            "simulator": {"backend": 30802, "frontend": 30810},
        }
        capability_ports = ports_by_capability.get(naming.capability_name, {})
        if component in capability_ports:
            return capability_ports[component]
        base = 30810 + (hash(naming.capability_name) % 80)
        return base if component == "backend" else base + 1

    def _common_labels(self, naming: ResourceNaming, component: str) -> Dict[str, str]:
        """Generate common labels for resources."""
        return {
            "app.kubernetes.io/managed-by": "nexus-operator",
            "app.kubernetes.io/component": component,
            "nexus.ai/capability": naming.capability_name,
            "nexus.ai/environment": naming.environment,
        }
    
    async def _apply_statefulset(self, name: str, statefulset: client.V1StatefulSet) -> Dict[str, Any]:
        """Create or update a StatefulSet."""
        try:
            self.apps_api.read_namespaced_stateful_set(name=name, namespace=self.namespace)
            # Update existing (note: VCT updates are not allowed, only pod template changes)
            self.apps_api.replace_namespaced_stateful_set(name=name, namespace=self.namespace, body=statefulset)
            logger.info(f"Updated StatefulSet: {name}")
            return {"name": name, "status": "updated", "type": "StatefulSet"}
        except ApiException as e:
            if e.status != 404:
                raise
            self.apps_api.create_namespaced_stateful_set(namespace=self.namespace, body=statefulset)
            logger.info(f"Created StatefulSet: {name}")
            return {"name": name, "status": "created", "type": "StatefulSet"}

    async def _apply_deployment(self, name: str, deployment: client.V1Deployment) -> Dict[str, Any]:
        """Create or update a Deployment."""
        try:
            self.apps_api.read_namespaced_deployment(name=name, namespace=self.namespace)
            # Update existing
            self.apps_api.replace_namespaced_deployment(name=name, namespace=self.namespace, body=deployment)
            logger.info(f"Updated Deployment: {name}")
            return {"name": name, "status": "updated", "type": "Deployment"}
        except ApiException as e:
            if e.status != 404:
                raise
            # Create new
            self.apps_api.create_namespaced_deployment(namespace=self.namespace, body=deployment)
            logger.info(f"Created Deployment: {name}")
            return {"name": name, "status": "created", "type": "Deployment"}
    
    async def _apply_service(self, name: str, service: client.V1Service) -> Dict[str, Any]:
        """Create or update a Service."""
        try:
            existing = self.core_api.read_namespaced_service(name=name, namespace=self.namespace)
            # Preserve clusterIP for updates
            service.spec.cluster_ip = existing.spec.cluster_ip
            self.core_api.replace_namespaced_service(name=name, namespace=self.namespace, body=service)
            logger.info(f"Updated Service: {name}")
            url = self._get_service_url(existing)
            return {"name": name, "status": "updated", "type": "Service", "url": url}
        except ApiException as e:
            if e.status != 404:
                raise
            # Create new
            created = self.core_api.create_namespaced_service(namespace=self.namespace, body=service)
            logger.info(f"Created Service: {name}")
            url = self._get_service_url(created)
            return {"name": name, "status": "created", "type": "Service", "url": url}
    
    def _get_service_url(self, service: client.V1Service) -> str:
        """Extract URL from LoadBalancer service."""
        if service.status and service.status.load_balancer and service.status.load_balancer.ingress:
            ingress = service.status.load_balancer.ingress[0]
            host = ingress.hostname or ingress.ip
            port = service.spec.ports[0].port if service.spec.ports else 8080
            # Always include port in URL since we use non-standard ports (8080, 8000)
            return f"http://{host}:{port}"
        return f"{service.metadata.name}.{service.metadata.namespace}.svc.cluster.local"
    
    async def _create_alb_ingress(
        self,
        naming: ResourceNaming,
        ingress_config: Dict[str, Any],
        frontend_service: str,
        backend_service: str,
        bssmagic_service: Optional[str] = None,
        component: str = "app",
        scheme_override: Optional[str] = None,
    ) -> str:
        """
        Create ALB Ingress for frontend, backend, and optionally BSS Magic exposure.
        
        BSS Magic is exposed at /bssmagic when service name is provided,
        enabling future product Design Studio UI integration.
        
        Args:
            naming: Resource naming utility
            ingress_config: Ingress configuration from spec
            frontend_service: Frontend service name
            backend_service: Backend service name
            bssmagic_service: Optional BSS Magic service name (exposed at /bssmagic)
            component: Ingress component name ("app" for public, "internal" for VPC-only)
            scheme_override: Force ALB scheme (overrides ingress_config value)
            
        Returns:
            ALB URL (or placeholder if not yet provisioned)
        """
        networking_api = self.networking_api
        ingress_name = naming.kubernetes_ingress(component)
        
        # Build ALB annotations
        base_alb_name = f"{naming.capability_name}-{naming.environment}"
        alb_name = base_alb_name if component == "app" else f"{base_alb_name}-{component}"
        scheme = scheme_override or ingress_config.get("scheme", "internet-facing")
        annotations = {
            "kubernetes.io/ingress.class": "alb",
            "alb.ingress.kubernetes.io/load-balancer-name": alb_name,
            "alb.ingress.kubernetes.io/scheme": scheme,
            "alb.ingress.kubernetes.io/target-type": "ip",
            "alb.ingress.kubernetes.io/tags": f"Environment={naming.environment},Capability={naming.capability_name}",
            "alb.ingress.kubernetes.io/healthcheck-path": ingress_config.get("healthCheckPath", "/"),
            "alb.ingress.kubernetes.io/healthcheck-interval-seconds": "30",
            "alb.ingress.kubernetes.io/healthcheck-timeout-seconds": "5",
            "alb.ingress.kubernetes.io/healthy-threshold-count": "2",
            "alb.ingress.kubernetes.io/unhealthy-threshold-count": "3",
        }
        
        # Helper function to validate subnet IDs
        def is_valid_subnet(subnet_id: str) -> bool:
            """Check if subnet ID looks like a real AWS subnet ID."""
            if not subnet_id or not isinstance(subnet_id, str):
                return False
            # Valid subnet IDs: subnet-{8 or 17 hex chars}
            import re
            return bool(re.match(r'^subnet-[0-9a-f]{8,17}$', subnet_id))
        
        # Helper function to validate certificate ARN
        def is_valid_cert_arn(cert_arn: str) -> bool:
            """Check if certificate ARN looks like a real ACM ARN."""
            if not cert_arn or not isinstance(cert_arn, str):
                return False
            # Skip placeholder values
            if 'your-cert' in cert_arn or 'example' in cert_arn or 'placeholder' in cert_arn:
                return False
            # Valid ACM ARN: arn:aws:acm:region:account:certificate/uuid
            import re
            return bool(re.match(r'^arn:aws:acm:[a-z0-9-]+:\d+:certificate/[a-f0-9-]+$', cert_arn))
        
        # Add subnets if specified and valid (skip placeholders)
        if ingress_config.get("subnets"):
            subnets = ingress_config["subnets"]
            if isinstance(subnets, list):
                valid_subnets = [s for s in subnets if is_valid_subnet(s)]
                if valid_subnets:
                    annotations["alb.ingress.kubernetes.io/subnets"] = ",".join(valid_subnets)
                else:
                    logger.info("No valid subnet IDs provided - ALB Controller will auto-discover")
            elif isinstance(subnets, str) and is_valid_subnet(subnets):
                annotations["alb.ingress.kubernetes.io/subnets"] = subnets
        
        # Configure listeners (HTTP by default, HTTPS if valid certificate provided)
        cert_arn = ingress_config.get("certificateArn", "")
        https_only = bool(ingress_config.get("httpsOnly"))
        if cert_arn and is_valid_cert_arn(cert_arn):
            annotations["alb.ingress.kubernetes.io/certificate-arn"] = cert_arn
            if https_only:
                annotations["alb.ingress.kubernetes.io/listen-ports"] = '[{"HTTPS": 443}]'
                logger.info(f"HTTPS-only listener (443) with certificate: {cert_arn}")
            else:
                annotations["alb.ingress.kubernetes.io/listen-ports"] = '[{"HTTP": 80}, {"HTTPS": 443}]'
                annotations["alb.ingress.kubernetes.io/ssl-redirect"] = "443"
                logger.info(f"HTTPS enabled with certificate: {cert_arn}")
        else:
            if https_only and cert_arn:
                logger.warning("httpsOnly ignored: no valid certificateArn")
            annotations["alb.ingress.kubernetes.io/listen-ports"] = '[{"HTTP": 80}]'
            if cert_arn:
                logger.warning(f"Invalid or placeholder certificate ARN ignored: {cert_arn}")
        
        # Merge spec.ingress.annotations / spec.internalIngress.annotations (applied last; can override defaults)
        user_ann = ingress_config.get("annotations")
        if isinstance(user_ann, dict) and user_ann:
            for key, val in user_ann.items():
                if key and val is not None:
                    annotations[str(key)] = str(val)
            logger.info(f"Merged {len(user_ann)} custom Ingress annotation(s) for {ingress_name}")
        
        # Build path rules: /api -> backend, /bssmagic -> bssmagic (optional), / -> frontend
        paths = [
            client.V1HTTPIngressPath(
                path="/api",
                path_type="Prefix",
                backend=client.V1IngressBackend(
                    service=client.V1IngressServiceBackend(
                        name=backend_service,
                        port=client.V1ServiceBackendPort(number=8000)
                    )
                )
            ),
        ]
        
        if bssmagic_service:
            paths.append(
                client.V1HTTPIngressPath(
                    path="/bssmagic",
                    path_type="Prefix",
                    backend=client.V1IngressBackend(
                        service=client.V1IngressServiceBackend(
                            name=bssmagic_service,
                            port=client.V1ServiceBackendPort(number=8000)
                        )
                    )
                )
            )
            logger.info(f"BSS Magic exposed at /bssmagic via {bssmagic_service}:8000")
        
        # Frontend catch-all must be last
        paths.append(
            client.V1HTTPIngressPath(
                path="/",
                path_type="Prefix",
                backend=client.V1IngressBackend(
                    service=client.V1IngressServiceBackend(
                        name=frontend_service,
                        port=client.V1ServiceBackendPort(number=8080)
                    )
                )
            ),
        )
        
        # Create Ingress resource
        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=ingress_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "ingress"),
                annotations=annotations,
            ),
            spec=client.V1IngressSpec(
                ingress_class_name="alb",
                rules=[
                    client.V1IngressRule(
                        http=client.V1HTTPIngressRuleValue(paths=paths)
                    )
                ]
            ),
        )
        
        # Apply ingress (create or update)
        try:
            existing = networking_api.read_namespaced_ingress(name=ingress_name, namespace=self.namespace)
            networking_api.replace_namespaced_ingress(name=ingress_name, namespace=self.namespace, body=ingress)
            logger.info(f"Updated Ingress: {ingress_name}")
            return self._get_ingress_url(existing)
        except ApiException as e:
            if e.status != 404:
                raise
            created = networking_api.create_namespaced_ingress(namespace=self.namespace, body=ingress)
            logger.info(f"Created Ingress: {ingress_name}")
            return self._get_ingress_url(created)
    
    def _get_ingress_url(self, ingress: client.V1Ingress) -> str:
        """Extract URL from ALB Ingress, using https:// when a certificate is configured."""
        if ingress.status and ingress.status.load_balancer and ingress.status.load_balancer.ingress:
            lb_ingress = ingress.status.load_balancer.ingress[0]
            host = lb_ingress.hostname or lb_ingress.ip
            if host:
                annotations = ingress.metadata.annotations or {}
                scheme = "https" if "alb.ingress.kubernetes.io/certificate-arn" in annotations else "http"
                return f"{scheme}://{host}"
        return f"{ingress.metadata.name}.{self.namespace}.alb.pending"
    
    async def _delete_ingress(self, naming: ResourceNaming) -> Dict[str, Any]:
        """Delete ALB Ingress resource."""
        networking_api = self.networking_api
        ingress_name = naming.kubernetes_ingress("app")
        
        try:
            networking_api.delete_namespaced_ingress(name=ingress_name, namespace=self.namespace)
            logger.info(f"Deleted Ingress: {ingress_name}")
            return {"name": ingress_name, "status": "deleted", "type": "Ingress"}
        except ApiException as e:
            if e.status == 404:
                return {"name": ingress_name, "status": "not_found", "type": "Ingress"}
            else:
                logger.error(f"Failed to delete Ingress {ingress_name}: {e}")
                return {"name": ingress_name, "status": "failed", "error": str(e), "type": "Ingress"}
    
    async def delete_all(self, naming: ResourceNaming) -> list[Dict[str, Any]]:
        """Delete all Kubernetes resources for a capability."""
        results = []
        
        # Delete ingress first (if exists)
        ingress_result = await self._delete_ingress(naming)
        results.append(ingress_result)
        
        # Delete bssmagic StatefulSet (single all-in-one StatefulSet, no separate PG)
        bssmagic_sts_name = naming.kubernetes_deployment("bssmagic")
        try:
            self.apps_api.delete_namespaced_stateful_set(name=bssmagic_sts_name, namespace=self.namespace)
            results.append({"name": bssmagic_sts_name, "status": "deleted", "type": "StatefulSet"})
            logger.info(f"Deleted BSS Magic StatefulSet: {bssmagic_sts_name}")
        except ApiException as e:
            if e.status == 404:
                results.append({"name": bssmagic_sts_name, "status": "not_found", "type": "StatefulSet"})
            else:
                results.append({"name": bssmagic_sts_name, "status": "failed", "error": str(e), "type": "StatefulSet"})

        # Also try to clean up legacy resources (old separate PG StatefulSet + Deployment)
        for legacy_name in [naming.kubernetes_deployment("bssmagic-pg")]:
            try:
                self.apps_api.delete_namespaced_stateful_set(name=legacy_name, namespace=self.namespace)
                results.append({"name": legacy_name, "status": "deleted", "type": "StatefulSet"})
            except ApiException:
                pass  # Not found is fine for legacy cleanup

        # Delete bssmagic service (and legacy bssmagic-pg service)
        for bssmagic_svc in [naming.kubernetes_service("bssmagic"), naming.kubernetes_service("bssmagic-pg")]:
            try:
                self.core_api.delete_namespaced_service(name=bssmagic_svc, namespace=self.namespace)
                results.append({"name": bssmagic_svc, "status": "deleted", "type": "Service"})
            except ApiException as e:
                if e.status == 404:
                    results.append({"name": bssmagic_svc, "status": "not_found", "type": "Service"})
                else:
                    results.append({"name": bssmagic_svc, "status": "failed", "error": str(e), "type": "Service"})

        # Delete deployments
        for component in ["frontend", "backend"]:
            dep_name = naming.kubernetes_deployment(component)
            try:
                self.apps_api.delete_namespaced_deployment(name=dep_name, namespace=self.namespace)
                results.append({"name": dep_name, "status": "deleted", "type": "Deployment"})
            except ApiException as e:
                if e.status == 404:
                    results.append({"name": dep_name, "status": "not_found", "type": "Deployment"})
                else:
                    results.append({"name": dep_name, "status": "failed", "error": str(e), "type": "Deployment"})
        
        # Delete services (including internal backend service)
        for component in ["frontend", "backend"]:
            svc_name = naming.kubernetes_service(component)
            try:
                self.core_api.delete_namespaced_service(name=svc_name, namespace=self.namespace)
                results.append({"name": svc_name, "status": "deleted", "type": "Service"})
            except ApiException as e:
                if e.status == 404:
                    results.append({"name": svc_name, "status": "not_found", "type": "Service"})
                else:
                    results.append({"name": svc_name, "status": "failed", "error": str(e), "type": "Service"})
        
        # Delete internal backend service (used for frontend-to-backend communication)
        internal_svc_name = f"{naming.kubernetes_service('backend')}-internal"
        try:
            self.core_api.delete_namespaced_service(name=internal_svc_name, namespace=self.namespace)
            results.append({"name": internal_svc_name, "status": "deleted", "type": "Service"})
            logger.info(f"Deleted internal backend service: {internal_svc_name}")
        except ApiException as e:
            if e.status == 404:
                results.append({"name": internal_svc_name, "status": "not_found", "type": "Service"})
            else:
                results.append({"name": internal_svc_name, "status": "failed", "error": str(e), "type": "Service"})
        
        # Delete service account
        sa_name = naming.kubernetes_service_account()
        try:
            self.core_api.delete_namespaced_service_account(name=sa_name, namespace=self.namespace)
            results.append({"name": sa_name, "status": "deleted", "type": "ServiceAccount"})
        except ApiException as e:
            if e.status == 404:
                results.append({"name": sa_name, "status": "not_found", "type": "ServiceAccount"})
            else:
                results.append({"name": sa_name, "status": "failed", "error": str(e), "type": "ServiceAccount"})
        
        return results
