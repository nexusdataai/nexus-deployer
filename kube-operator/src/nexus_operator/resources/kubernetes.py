"""
Kubernetes Resource Creator for deploying application components.

Feature: pure-eks-deployment
Requirements: 4.5, 4.8, 5.5
"""
import logging
from typing import Dict, Any, Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class KubernetesResourceCreator:
    """Creates Kubernetes resources for Nexus capability deployments."""
    
    def __init__(self, namespace: str):
        self.namespace = namespace
        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()

    def _read_backend_api_key(self, naming: ResourceNaming) -> str:
        """Read API_KEY from the existing backend deployment's env vars."""
        deploy_name = naming.kubernetes_deployment("backend")
        try:
            deploy = self.apps_api.read_namespaced_deployment(deploy_name, self.namespace)
            for container in deploy.spec.template.spec.containers:
                for env in (container.env or []):
                    if env.name == "API_KEY" and env.value:
                        logger.info(f"Read API_KEY from existing deployment {deploy_name}")
                        return env.value
        except Exception as e:
            logger.warning(f"Could not read API_KEY from {deploy_name}: {e}")
        return ''

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

    async def deploy_backend(
        self,
        naming: ResourceNaming,
        image: str,
        replicas: int = 2,
        resources: Optional[Dict[str, str]] = None,
        environment: str = "dev",
        region: str = "us-east-1",
        use_clusterip: bool = False,
        bssmagic_service: Optional[str] = None,
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
        deployment_name = naming.kubernetes_deployment("backend")
        service_name = naming.kubernetes_service("backend")
        sa_name = naming.kubernetes_service_account()
        
        resources = resources or {}
        cpu_request = resources.get("cpu", "250m")
        memory_request = resources.get("memory", "512Mi")
        cpu_limit = resources.get("cpuLimit", "500m")
        memory_limit = resources.get("memoryLimit", "2Gi")
        
        # Generate a stable API key for gateway authentication
        import secrets as secrets_module
        api_key = secrets_module.token_urlsafe(24)
        
        # Store API key on the instance so frontend config can use it
        self._api_key = api_key
        
        # Environment variables for SSM/Secrets access
        env_vars = [
            client.V1EnvVar(name="ENVIRONMENT", value=environment),
            client.V1EnvVar(name="AWS_REGION", value=region),
            client.V1EnvVar(name="AWS_DEFAULT_REGION", value=region),
            client.V1EnvVar(
                name="AWS_CA_BUNDLE",
                value="/etc/ssl/certs/ca-certificates.crt",
            ),
            client.V1EnvVar(name="CAPABILITY_NAME", value=naming.capability_name),
            client.V1EnvVar(name="SSM_PARAMETER_PREFIX", value=naming.ssm_parameter_prefix()),
            client.V1EnvVar(name="SECRETS_PREFIX", value=naming.secret_name_prefix()),
            client.V1EnvVar(name="API_KEY", value=api_key),
            # WXCC Simulator - base URL points to self (backend serves simulator API)
            client.V1EnvVar(name="WXCC_SIMULATOR_BASE_URL", value="http://localhost:8000/api/v1/simulator"),
            client.V1EnvVar(name="WXCC_SIMULATOR_ENABLED", value="true"),
            # SFDC Simulator
            client.V1EnvVar(name="SFDC_SIMULATOR_ENABLED", value="true"),
            client.V1EnvVar(name="SFDC_SIMULATOR_BUCKET", value=naming.sfdc_simulator_bucket()),
        ]
        
        # FDW + BSSMagic integration env vars (enables Ontos page and CRM service)
        if bssmagic_service:
            env_vars.extend([
                client.V1EnvVar(name="BSSMAGIC_BASE_URL", value=f"http://{bssmagic_service}:8000"),
                client.V1EnvVar(name="FDW_PG_HOST", value=bssmagic_service),
                client.V1EnvVar(name="FDW_PG_PORT", value="5432"),
                client.V1EnvVar(name="FDW_PG_DATABASE", value="bssmagic"),
                client.V1EnvVar(name="FDW_PG_USER", value="postgres"),
                client.V1EnvVar(name="FDW_PG_PASSWORD", value="admin"),
                client.V1EnvVar(name="FDW_PG_SCHEMA", value="public"),
                client.V1EnvVar(name="FDW_TMF_SPECS_DIR", value="/opt/tmf-specs"),
            ])
            logger.info(f"FDW integration enabled: {bssmagic_service}:5432/bssmagic")
        
        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=deployment_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "backend"),
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                selector=client.V1LabelSelector(
                    match_labels={"app": deployment_name}
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={"app": deployment_name, **self._common_labels(naming, "backend")}
                    ),
                    spec=client.V1PodSpec(
                        service_account_name=sa_name,
                        containers=[
                            client.V1Container(
                                name="backend",
                                image=image,
                                ports=[client.V1ContainerPort(container_port=8000)],
                                env=env_vars,
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": cpu_request, "memory": memory_request},
                                    limits={"cpu": cpu_limit, "memory": memory_limit},
                                ),
                                liveness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/health", port=8000),
                                    initial_delay_seconds=90,
                                    period_seconds=15,
                                    timeout_seconds=5,
                                    failure_threshold=5,
                                ),
                                readiness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/health", port=8000),
                                    initial_delay_seconds=60,
                                    period_seconds=10,
                                    timeout_seconds=5,
                                    failure_threshold=5,
                                ),
                            )
                        ],
                    ),
                ),
            ),
        )
        
        await self._apply_deployment(deployment_name, deployment)
        
        # Determine service type: ClusterIP for ALB Ingress, LoadBalancer otherwise
        service_type = "ClusterIP" if use_clusterip else "LoadBalancer"
        
        # Create Service
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "backend"),
            ),
            spec=client.V1ServiceSpec(
                type=service_type,
                selector={"app": deployment_name},
                ports=[client.V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
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
        ]

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
        
        # Create ConfigMap with config.json and nginx.conf for frontend
        # api.baseUrl is empty so all calls use nginx proxy (same origin)
        # nginx proxies /api/* and /health,/stats,/tools to the backend
        import json as json_module
        api_key = getattr(self, '_api_key', '')
        if not api_key:
            api_key = self._read_backend_api_key(naming)
        config_json = json_module.dumps({
            "version": "1.0.0",
            "deploymentMode": "eks",
            "api": {"baseUrl": "", "timeout": 30000},
            "gateway": {"apiKey": api_key},
            "dataSource": "api",
            "enableFallback": True
        }, indent=2)
        
        backend_internal_svc = f"{naming.kubernetes_service('backend')}-internal"
        nginx_conf = self._generate_nginx_conf(backend_internal_svc)
        
        configmap_name = f"{deployment_name}-config"
        configmap = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=configmap_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "frontend"),
            ),
            data={"config.json": config_json, "nginx.conf": nginx_conf}
        )
        try:
            self.core_api.create_namespaced_config_map(self.namespace, configmap)
        except Exception:
            self.core_api.replace_namespaced_config_map(configmap_name, self.namespace, configmap)
        logger.info(f"Created ConfigMap {configmap_name} with config.json for frontend")
        
        # Create Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=deployment_name,
                namespace=self.namespace,
                labels=self._common_labels(naming, "frontend"),
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
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
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name="config-volume",
                                        mount_path="/usr/share/nginx/html/config.json",
                                        sub_path="config.json"
                                    ),
                                    client.V1VolumeMount(
                                        name="config-volume",
                                        mount_path="/etc/nginx/nginx.conf",
                                        sub_path="nginx.conf"
                                    ),
                                ],
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
        service_type = "ClusterIP" if (use_ingress or use_internal) else "LoadBalancer"
        
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
                ports=[client.V1ServicePort(port=8080, target_port=8080, protocol="TCP")],
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

        location ^~ /docs/ {{
            alias /usr/share/nginx/docs/;
            index index.html;
            try_files $uri $uri/ =404;
        }}

        location /api/ {{
            proxy_pass http://{backend_svc}:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
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
        networking_api = client.NetworkingV1Api()
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
        networking_api = client.NetworkingV1Api()
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
