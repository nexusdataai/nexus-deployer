"""
PodDisruptionBudget reconciler.

Manages `policy/v1 PodDisruptionBudget` objects for a TotogiCapability's
workloads. Driven by `spec.pdb` on the CR.

Spec shape (from manifests/crd.yaml):
    pdb:
      enabled: bool
      minAvailable:    int          # mutually exclusive with maxUnavailable
      maxUnavailable:  int

Idempotent: create-or-patch when enabled, delete when disabled. Rejects
configs that set both minAvailable and maxUnavailable; the upstream API
server would do the same with a less helpful error.
"""
import logging
from typing import Any, Dict, List, Optional

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class PDBReconciler:
    """Reconcile PDB objects for a TotogiCapability's workloads."""

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.policy_api = client.PolicyV1Api()

    def reconcile(
        self,
        naming: ResourceNaming,
        pdb_spec: Optional[Dict[str, Any]],
        targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Apply the PDB spec to each target Deployment.

        Args:
            naming: ResourceNaming helper.
            pdb_spec: spec.pdb dict from the CR. None or {enabled: False}
                triggers cleanup.
            targets: list of deployment kinds to protect. Defaults to
                ["backend", "frontend"]; both are user-facing and we want
                them shielded during voluntary evictions.

        Returns:
            Dict summarising actions taken.
        """
        targets = targets or ["backend", "frontend"]
        spec = pdb_spec or {}
        enabled = bool(spec.get("enabled", False))

        result: Dict[str, Any] = {"created": [], "patched": [], "deleted": [], "skipped": []}

        if not enabled:
            for target in targets:
                pdb_name = self._pdb_name(naming, target)
                if self._delete_if_exists(pdb_name):
                    result["deleted"].append(pdb_name)
                else:
                    result["skipped"].append(pdb_name)
            return result

        min_available = spec.get("minAvailable")
        max_unavailable = spec.get("maxUnavailable")
        if min_available is not None and max_unavailable is not None:
            raise ValueError(
                "pdb.minAvailable and pdb.maxUnavailable are mutually exclusive; set only one"
            )
        if min_available is None and max_unavailable is None:
            # Sensible default - protect at least one pod
            min_available = 1

        for target in targets:
            pdb_name = self._pdb_name(naming, target)
            body = self._build_pdb(
                pdb_name=pdb_name,
                deployment_name=naming.kubernetes_deployment(target),
                min_available=min_available,
                max_unavailable=max_unavailable,
            )
            try:
                self.policy_api.create_namespaced_pod_disruption_budget(
                    namespace=self.namespace, body=body
                )
                logger.info(f"Created PDB {pdb_name}")
                result["created"].append(pdb_name)
            except ApiException as e:
                if e.status != 409:
                    raise
                self.policy_api.patch_namespaced_pod_disruption_budget(
                    name=pdb_name, namespace=self.namespace, body=body
                )
                logger.info(f"Patched PDB {pdb_name}")
                result["patched"].append(pdb_name)
        return result

    @staticmethod
    def _pdb_name(naming: ResourceNaming, target: str) -> str:
        return f"{naming.kubernetes_deployment(target)}-pdb"

    def _delete_if_exists(self, name: str) -> bool:
        try:
            self.policy_api.delete_namespaced_pod_disruption_budget(
                name=name, namespace=self.namespace
            )
            logger.info(f"Deleted PDB {name}")
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

    @staticmethod
    def _build_pdb(
        pdb_name: str,
        deployment_name: str,
        min_available: Optional[int],
        max_unavailable: Optional[int],
    ) -> client.V1PodDisruptionBudget:
        # Match labels follow the operator's convention - the deployment's
        # selector uses the same labels (see KubernetesResourceCreator).
        spec_kwargs: Dict[str, Any] = {
            "selector": client.V1LabelSelector(
                match_labels={"app": deployment_name},
            ),
        }
        if min_available is not None:
            spec_kwargs["min_available"] = min_available
        if max_unavailable is not None:
            spec_kwargs["max_unavailable"] = max_unavailable
        return client.V1PodDisruptionBudget(
            metadata=client.V1ObjectMeta(name=pdb_name),
            spec=client.V1PodDisruptionBudgetSpec(**spec_kwargs),
        )
