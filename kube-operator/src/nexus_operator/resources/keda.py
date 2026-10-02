"""
KEDA ScaledObject reconciler for ai-engine job workers.

Scales the job-worker Deployment based on Redis Streams lag for the
ai-engine jobs consumer group.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)

KEDA_GROUP = "keda.sh"
KEDA_VERSION = "v1alpha1"
KEDA_PLURAL = "scaledobjects"


class KedaReconciler:
    """Reconcile KEDA ScaledObject for job-worker queue autoscaling."""

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.custom_api = client.CustomObjectsApi()

    @staticmethod
    def _scaled_object_name(naming: ResourceNaming) -> str:
        return f"{naming.kubernetes_deployment('job-worker')}-scaler"

    def reconcile(
        self,
        naming: ResourceNaming,
        job_worker_spec: Optional[Dict[str, Any]],
        *,
        redis_service: str,
        redis_port: int = 6379,
        stream_key: str = "ai-engine:jobs",
        consumer_group: str = "ai-engine-workers",
    ) -> Dict[str, Any]:
        spec = job_worker_spec or {}
        autoscaling = spec.get("autoscaling") or {}
        enabled = bool(autoscaling.get("enabled", False))
        name = self._scaled_object_name(naming)
        deployment_name = naming.kubernetes_deployment("job-worker")

        if not enabled or not spec.get("enabled", False):
            if self._delete_if_exists(name):
                return {"deleted": [name]}
            return {"skipped": [name]}

        min_replicas = int(autoscaling.get("minReplicas", spec.get("replicas", 1)))
        max_replicas = int(autoscaling.get("maxReplicas", 10))
        lag_threshold = int(autoscaling.get("lagThreshold", 6))
        if max_replicas < min_replicas:
            raise ValueError(
                f"jobWorker.autoscaling.maxReplicas ({max_replicas}) must be >= minReplicas ({min_replicas})"
            )

        redis_address = f"{redis_service}.{self.namespace}.svc.cluster.local:{redis_port}"
        body = {
            "apiVersion": f"{KEDA_GROUP}/{KEDA_VERSION}",
            "kind": "ScaledObject",
            "metadata": {
                "name": name,
                "namespace": self.namespace,
            },
            "spec": {
                "scaleTargetRef": {"name": deployment_name},
                "minReplicaCount": min_replicas,
                "maxReplicaCount": max_replicas,
                "pollingInterval": 15,
                "cooldownPeriod": 60,
                "advanced": {
                    "horizontalPodAutoscalerConfig": {
                        "behavior": {
                            "scaleUp": {
                                "stabilizationWindowSeconds": 30,
                                "selectPolicy": "Max",
                                "policies": [{"type": "Pods", "value": 2, "periodSeconds": 30}],
                            },
                            "scaleDown": {
                                "stabilizationWindowSeconds": 180,
                                "selectPolicy": "Min",
                                "policies": [{"type": "Pods", "value": 1, "periodSeconds": 60}],
                            },
                        }
                    }
                },
                "triggers": [
                    {
                        "type": "redis-streams",
                        "metadata": {
                            "address": redis_address,
                            "stream": stream_key,
                            "consumerGroup": consumer_group,
                            "lagCount": str(lag_threshold),
                        },
                    }
                ],
            },
        }

        try:
            self.custom_api.create_namespaced_custom_object(
                group=KEDA_GROUP,
                version=KEDA_VERSION,
                namespace=self.namespace,
                plural=KEDA_PLURAL,
                body=body,
            )
            logger.info("Created ScaledObject %s for %s", name, deployment_name)
            return {"created": [name]}
        except ApiException as exc:
            if exc.status != 409:
                raise
            self.custom_api.patch_namespaced_custom_object(
                group=KEDA_GROUP,
                version=KEDA_VERSION,
                namespace=self.namespace,
                plural=KEDA_PLURAL,
                name=name,
                body=body,
            )
            logger.info("Patched ScaledObject %s for %s", name, deployment_name)
            return {"patched": [name]}

    def _delete_if_exists(self, name: str) -> bool:
        try:
            self.custom_api.delete_namespaced_custom_object(
                group=KEDA_GROUP,
                version=KEDA_VERSION,
                namespace=self.namespace,
                plural=KEDA_PLURAL,
                name=name,
            )
            logger.info("Deleted ScaledObject %s", name)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
