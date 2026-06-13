"""
HorizontalPodAutoscaler reconciler.

Manages `autoscaling/v2 HorizontalPodAutoscaler` objects for the backend (and
optionally frontend) Deployment of a TotogiCapability. Driven entirely by
`spec.hpa` on the CR.

Spec shape (from manifests/crd.yaml):
    hpa:
      enabled: bool
      minReplicas: int
      maxReplicas: int
      targetCPUUtilization: int   # percentage 0-100

Idempotent: create on first reconcile, patch on subsequent ones, delete when
`enabled` flips to False.
"""
import logging
from typing import Any, Dict, List, Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class HPAReconciler:
    """Reconcile HPA objects for a TotogiCapability's workloads."""

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.autoscaling_api = client.AutoscalingV2Api()

    def reconcile(
        self,
        naming: ResourceNaming,
        hpa_spec: Optional[Dict[str, Any]],
        targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Apply the HPA spec to each target Deployment.

        Args:
            naming: ResourceNaming helper for the capability/environment.
            hpa_spec: spec.hpa dict from the CR. None or {enabled: False}
                triggers cleanup of any pre-existing HPAs.
            targets: list of deployment kinds to scale; defaults to ["backend"].
                "frontend" is supported but optional - frontends are usually
                stateless behind a CDN and do not benefit from HPA.

        Returns:
            A dict summarising actions taken, suitable for status.steps.
        """
        targets = targets or ["backend"]
        spec = hpa_spec or {}
        enabled = bool(spec.get("enabled", False))

        result: Dict[str, Any] = {"created": [], "patched": [], "deleted": [], "skipped": []}

        if not enabled:
            for target in targets:
                hpa_name = self._hpa_name(naming, target)
                if self._delete_if_exists(hpa_name):
                    result["deleted"].append(hpa_name)
                else:
                    result["skipped"].append(hpa_name)
            return result

        # Validate min/max relationship; the API server would reject a bad
        # spec but we surface the failure on the CR status earlier.
        min_replicas = int(spec.get("minReplicas", 1))
        max_replicas = int(spec.get("maxReplicas", min_replicas))
        if max_replicas < min_replicas:
            raise ValueError(
                f"hpa.maxReplicas ({max_replicas}) must be >= minReplicas ({min_replicas})"
            )
        target_cpu = int(spec.get("targetCPUUtilization", 70))

        for target in targets:
            hpa_name = self._hpa_name(naming, target)
            deployment_name = naming.kubernetes_deployment(target)
            body = self._build_hpa(
                hpa_name=hpa_name,
                deployment_name=deployment_name,
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                target_cpu=target_cpu,
            )
            try:
                self.autoscaling_api.create_namespaced_horizontal_pod_autoscaler(
                    namespace=self.namespace, body=body
                )
                logger.info(f"Created HPA {hpa_name} for {deployment_name}")
                result["created"].append(hpa_name)
            except ApiException as e:
                if e.status != 409:
                    raise
                self.autoscaling_api.patch_namespaced_horizontal_pod_autoscaler(
                    name=hpa_name, namespace=self.namespace, body=body
                )
                logger.info(f"Patched HPA {hpa_name} for {deployment_name}")
                result["patched"].append(hpa_name)
        return result

    @staticmethod
    def _hpa_name(naming: ResourceNaming, target: str) -> str:
        return f"{naming.kubernetes_deployment(target)}-hpa"

    def _delete_if_exists(self, name: str) -> bool:
        try:
            self.autoscaling_api.delete_namespaced_horizontal_pod_autoscaler(
                name=name, namespace=self.namespace
            )
            logger.info(f"Deleted HPA {name}")
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    @staticmethod
    def _build_hpa(
        hpa_name: str,
        deployment_name: str,
        min_replicas: int,
        max_replicas: int,
        target_cpu: int,
    ) -> client.V2HorizontalPodAutoscaler:
        return client.V2HorizontalPodAutoscaler(
            metadata=client.V1ObjectMeta(name=hpa_name),
            spec=client.V2HorizontalPodAutoscalerSpec(
                scale_target_ref=client.V2CrossVersionObjectReference(
                    api_version="apps/v1",
                    kind="Deployment",
                    name=deployment_name,
                ),
                min_replicas=min_replicas,
                max_replicas=max_replicas,
                metrics=[
                    client.V2MetricSpec(
                        type="Resource",
                        resource=client.V2ResourceMetricSource(
                            name="cpu",
                            target=client.V2MetricTarget(
                                type="Utilization",
                                average_utilization=target_cpu,
                            ),
                        ),
                    ),
                ],
            ),
        )
