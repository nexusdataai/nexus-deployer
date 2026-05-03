"""
Grafana Mimir Provisioner.

Deploys Grafana Mimir in monolithic mode (single binary, all components in one
process) backed by S3 for blocks-storage. Used as the time-series store for
solution KPI trend data, daily snapshots, anomaly score series, and other
metric-shaped history. See the Solution Four Views Expansion plan, section 3.6.

Storage:
  - Blocks (TSDB chunks + index): S3 bucket `mimir-blocks-...`
  - Alertmanager state, Ruler: same bucket

Multi-tenancy: enabled. Callers send X-Scope-OrgID header (default tenant
`nexus-default` written to SSM at /capability/env/mimir/tenant-id).

Deploys:
  - ConfigMap: `mimir-config` containing config.yaml
  - StatefulSet: `mimir` (1 replica, 5Gi PVC for WAL)
  - Service: `mimir-svc` (ClusterIP, port 8080)
"""
import logging
from typing import Dict, Any, Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


MIMIR_IMAGE = "grafana/mimir:2.13.0"
MIMIR_HTTP_PORT = 8080
MIMIR_GRPC_PORT = 9095


def _build_config_yaml(bucket: str, region: str, retention_days: int) -> str:
    return f"""# Grafana Mimir monolithic configuration (managed by nexus-operator)
target: all
multitenancy_enabled: true

server:
  http_listen_port: {MIMIR_HTTP_PORT}
  grpc_listen_port: {MIMIR_GRPC_PORT}
  log_level: info

common:
  storage:
    backend: s3
    s3:
      bucket_name: {bucket}
      region: {region}

blocks_storage:
  backend: s3
  s3:
    bucket_name: {bucket}
    region: {region}
  bucket_store:
    sync_dir: /data/tsdb-sync
  tsdb:
    dir: /data/tsdb
    retention_period: 24h

alertmanager_storage:
  backend: s3
  s3:
    bucket_name: {bucket}
    region: {region}

ruler_storage:
  backend: s3
  s3:
    bucket_name: {bucket}
    region: {region}

ingester:
  ring:
    replication_factor: 1
    instance_addr: 127.0.0.1
    kvstore:
      store: memberlist

distributor:
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: memberlist

store_gateway:
  sharding_ring:
    replication_factor: 1
    kvstore:
      store: memberlist

compactor:
  data_dir: /data/compactor
  sharding_ring:
    kvstore:
      store: memberlist
  compaction_interval: 30m
  retention_delete_delay: 2h
  blocks_retention_period: {retention_days}d

ruler:
  rule_path: /data/ruler
  ring:
    kvstore:
      store: memberlist

memberlist:
  bind_port: 7946

limits:
  ingestion_rate: 10000
  ingestion_burst_size: 200000
  max_global_series_per_user: 50000
  max_global_series_per_metric: 10000
  max_label_names_per_series: 30
  max_label_value_length: 2048
"""


class MimirProvisioner:
    """Provisions Grafana Mimir in monolithic mode inside the capability namespace."""

    NAME = "mimir"
    SERVICE_NAME = "mimir-svc"
    CONFIGMAP_NAME = "mimir-config"

    def __init__(self, namespace: str, naming: ResourceNaming, region: str):
        self.namespace = namespace
        self.naming = naming
        self.region = region
        self.core_api = client.CoreV1Api()
        self.apps_api = client.AppsV1Api()

    def _common_labels(self) -> Dict[str, str]:
        return {
            "app": self.NAME,
            "app.kubernetes.io/name": self.NAME,
            "app.kubernetes.io/component": "tsdb",
            "app.kubernetes.io/managed-by": "nexus-operator",
            "nexus.ai/capability": self.naming.capability_name,
            "nexus.ai/environment": self.naming.environment,
        }

    async def provision(
        self,
        retention_days: int = 90,
        storage_size: str = "5Gi",
        storage_class: Optional[str] = None,
        service_account: Optional[str] = None,
    ) -> Dict[str, Any]:
        bucket = self.naming.mimir_blocks_bucket()
        sa = service_account or self.naming.kubernetes_service_account()
        results: Dict[str, Any] = {"name": self.NAME, "type": "Mimir", "components": []}
        try:
            results["components"].append(await self._apply_configmap(bucket, retention_days))
            results["components"].append(await self._apply_statefulset(sa, storage_size, storage_class))
            results["components"].append(await self._apply_service())
            results["status"] = "created"
            results["url"] = f"http://{self.SERVICE_NAME}.{self.namespace}.svc.cluster.local:{MIMIR_HTTP_PORT}"
            logger.info(f"Mimir provisioned at {results['url']}")
            return results
        except Exception as e:
            logger.error(f"Failed to provision Mimir: {e}")
            results["status"] = "failed"
            results["error"] = str(e)
            return results

    async def _apply_configmap(self, bucket: str, retention_days: int) -> Dict[str, Any]:
        config_yaml = _build_config_yaml(bucket, self.region, retention_days)
        cm = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=self.CONFIGMAP_NAME,
                namespace=self.namespace,
                labels=self._common_labels(),
            ),
            data={"config.yaml": config_yaml},
        )
        try:
            self.core_api.read_namespaced_config_map(self.CONFIGMAP_NAME, self.namespace)
            self.core_api.replace_namespaced_config_map(self.CONFIGMAP_NAME, self.namespace, cm)
            return {"name": self.CONFIGMAP_NAME, "status": "updated", "type": "ConfigMap"}
        except ApiException as e:
            if e.status != 404:
                raise
            self.core_api.create_namespaced_config_map(self.namespace, cm)
            return {"name": self.CONFIGMAP_NAME, "status": "created", "type": "ConfigMap"}

    async def _apply_statefulset(self, service_account: str, storage_size: str, storage_class: Optional[str]) -> Dict[str, Any]:
        labels = self._common_labels()
        pvc_spec_kwargs: Dict[str, Any] = {
            "access_modes": ["ReadWriteOnce"],
            "resources": client.V1VolumeResourceRequirements(requests={"storage": storage_size}),
        }
        if storage_class:
            pvc_spec_kwargs["storage_class_name"] = storage_class
        statefulset = client.V1StatefulSet(
            metadata=client.V1ObjectMeta(name=self.NAME, namespace=self.namespace, labels=labels),
            spec=client.V1StatefulSetSpec(
                replicas=1,
                service_name=self.SERVICE_NAME,
                selector=client.V1LabelSelector(match_labels={"app": self.NAME}),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=labels),
                    spec=client.V1PodSpec(
                        service_account_name=service_account,
                        containers=[
                            client.V1Container(
                                name=self.NAME,
                                image=MIMIR_IMAGE,
                                args=["-config.file=/etc/mimir/config.yaml"],
                                ports=[
                                    client.V1ContainerPort(container_port=MIMIR_HTTP_PORT, name="http"),
                                    client.V1ContainerPort(container_port=MIMIR_GRPC_PORT, name="grpc"),
                                    client.V1ContainerPort(container_port=7946, name="memberlist"),
                                ],
                                resources=client.V1ResourceRequirements(
                                    requests={"cpu": "200m", "memory": "512Mi"},
                                    limits={"cpu": "1", "memory": "1Gi"},
                                ),
                                readiness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/ready", port=MIMIR_HTTP_PORT),
                                    initial_delay_seconds=20, period_seconds=10,
                                ),
                                liveness_probe=client.V1Probe(
                                    http_get=client.V1HTTPGetAction(path="/ready", port=MIMIR_HTTP_PORT),
                                    initial_delay_seconds=60, period_seconds=30,
                                ),
                                volume_mounts=[
                                    client.V1VolumeMount(name="config", mount_path="/etc/mimir"),
                                    client.V1VolumeMount(name="data", mount_path="/data"),
                                ],
                            )
                        ],
                        volumes=[
                            client.V1Volume(
                                name="config",
                                config_map=client.V1ConfigMapVolumeSource(name=self.CONFIGMAP_NAME),
                            )
                        ],
                    ),
                ),
                volume_claim_templates=[
                    client.V1PersistentVolumeClaim(
                        metadata=client.V1ObjectMeta(name="data"),
                        spec=client.V1PersistentVolumeClaimSpec(**pvc_spec_kwargs),
                    )
                ],
            ),
        )
        try:
            self.apps_api.read_namespaced_stateful_set(name=self.NAME, namespace=self.namespace)
            self.apps_api.replace_namespaced_stateful_set(name=self.NAME, namespace=self.namespace, body=statefulset)
            return {"name": self.NAME, "status": "updated", "type": "StatefulSet"}
        except ApiException as e:
            if e.status != 404:
                raise
            self.apps_api.create_namespaced_stateful_set(namespace=self.namespace, body=statefulset)
            return {"name": self.NAME, "status": "created", "type": "StatefulSet"}

    async def _apply_service(self) -> Dict[str, Any]:
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=self.SERVICE_NAME, namespace=self.namespace, labels=self._common_labels(),
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": self.NAME},
                ports=[
                    client.V1ServicePort(port=MIMIR_HTTP_PORT, target_port=MIMIR_HTTP_PORT, name="http", protocol="TCP"),
                    client.V1ServicePort(port=MIMIR_GRPC_PORT, target_port=MIMIR_GRPC_PORT, name="grpc", protocol="TCP"),
                ],
            ),
        )
        try:
            existing = self.core_api.read_namespaced_service(name=self.SERVICE_NAME, namespace=self.namespace)
            service.spec.cluster_ip = existing.spec.cluster_ip
            self.core_api.replace_namespaced_service(name=self.SERVICE_NAME, namespace=self.namespace, body=service)
            return {"name": self.SERVICE_NAME, "status": "updated", "type": "Service"}
        except ApiException as e:
            if e.status != 404:
                raise
            self.core_api.create_namespaced_service(namespace=self.namespace, body=service)
            return {"name": self.SERVICE_NAME, "status": "created", "type": "Service"}

    async def delete(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {"name": self.NAME, "type": "Mimir", "components": []}
        for kind, deleter in (
            ("Service", lambda: self.core_api.delete_namespaced_service(self.SERVICE_NAME, self.namespace)),
            ("StatefulSet", lambda: self.apps_api.delete_namespaced_stateful_set(self.NAME, self.namespace)),
            ("ConfigMap", lambda: self.core_api.delete_namespaced_config_map(self.CONFIGMAP_NAME, self.namespace)),
        ):
            try:
                deleter()
                results["components"].append({"type": kind, "status": "deleted"})
            except ApiException as e:
                if e.status == 404:
                    results["components"].append({"type": kind, "status": "not_found"})
                else:
                    results["components"].append({"type": kind, "status": "failed", "error": str(e)})
        return results
