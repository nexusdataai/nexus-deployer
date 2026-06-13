"""
IRSA mapping verifier (pipeline step 3).

For each role the deployer/operator/controllers expect to find, verify:
  1. The role exists.
  2. Its trust policy federates the cluster's OIDC provider.
  3. The trust policy's `:sub` condition points at the right
     `system:serviceaccount:NAMESPACE:NAME`.
  4. Required AWS-managed or inline policies are attached.

Returns a `PipelineCheck` per role that the wizard surfaces in the
ClusterPreflight UI.
"""
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.models.eks_pipeline import PipelineCheck

logger = logging.getLogger(__name__)


class IrsaRoleSpec:
    """One role to verify, with the SA + required attached/inline policies."""

    def __init__(
        self,
        name: str,
        label: str,
        role_name: str,
        namespace: str,
        service_account: str,
        required_managed_policies: Optional[Iterable[str]] = None,
        required_inline_policy_names: Optional[Iterable[str]] = None,
        admin_managed_remediation: Optional[str] = None,
    ):
        self.name = name
        self.label = label
        self.role_name = role_name
        self.namespace = namespace
        self.service_account = service_account
        self.required_managed = list(required_managed_policies or [])
        self.required_inline = list(required_inline_policy_names or [])
        self.admin_managed_remediation = admin_managed_remediation


class IrsaMappingVerifier:
    """Verify IRSA roles for the operator + per-component controllers."""

    def __init__(self, iam_client, sts_client):
        self.iam = iam_client
        self.sts = sts_client

    def verify_role(
        self,
        spec: IrsaRoleSpec,
        oidc_provider_id: Optional[str],
    ) -> PipelineCheck:
        """Run the four-part verification for a single role."""
        if not oidc_provider_id:
            return PipelineCheck(
                name=spec.name,
                label=spec.label,
                status="fail",
                detail="Cluster has no OIDC provider; IRSA cannot be verified.",
                remediation=(
                    "Associate an IAM OIDC provider with the cluster first "
                    "(see step 1 cluster readiness)."
                ),
            )

        # Step 1: role exists
        try:
            role = self.iam.get_role(RoleName=spec.role_name)["Role"]
        except Exception as e:
            err_code = (
                getattr(e, "response", {})
                .get("Error", {})
                .get("Code", "")
            )
            if err_code == "NoSuchEntity":
                return PipelineCheck(
                    name=spec.name,
                    label=spec.label,
                    status="fail",
                    detail=f"IAM role {spec.role_name} does not exist.",
                    remediation=spec.admin_managed_remediation or (
                        f"Create role {spec.role_name} with an IRSA trust "
                        f"policy targeting "
                        f"system:serviceaccount:{spec.namespace}:{spec.service_account}."
                    ),
                )
            return PipelineCheck(
                name=spec.name,
                label=spec.label,
                status="warn",
                detail=f"iam:GetRole failed: {e}",
            )

        role_arn = role["Arn"]

        # Step 2 + 3: trust policy + :sub
        trust = role.get("AssumeRolePolicyDocument") or {}
        trust_ok, trust_detail = self._verify_trust(
            trust, oidc_provider_id, spec.namespace, spec.service_account
        )
        if not trust_ok:
            return PipelineCheck(
                name=spec.name,
                label=spec.label,
                status="fail",
                detail=f"{role_arn}: {trust_detail}",
                remediation=(
                    "Update the trust policy: Federated must be the cluster's "
                    "OIDC provider, Action must be sts:AssumeRoleWithWebIdentity, "
                    f"and StringEquals must include "
                    f'"{oidc_provider_id}:sub": "system:serviceaccount:'
                    f'{spec.namespace}:{spec.service_account}".'
                ),
                extra={"role_arn": role_arn},
            )

        # Step 4: attached / inline policies
        missing = self._verify_policies(spec)
        if missing:
            return PipelineCheck(
                name=spec.name,
                label=spec.label,
                status="warn",
                detail=(
                    f"{role_arn}: trust OK; missing required policies: "
                    f"{', '.join(missing)}"
                ),
                remediation=(
                    "Attach the missing policies to the role. See "
                    "kube-operator/permissions/ for the canonical JSON files."
                ),
                extra={"role_arn": role_arn, "missing_policies": missing},
            )

        return PipelineCheck(
            name=spec.name,
            label=spec.label,
            status="pass",
            detail=(
                f"{role_arn}: trust policy targets "
                f"system:serviceaccount:{spec.namespace}:{spec.service_account}; "
                "all required policies attached."
            ),
            extra={"role_arn": role_arn},
        )

    # ----- helpers --------------------------------------------------------
    def _verify_trust(
        self,
        trust_policy: Dict[str, Any],
        oidc_provider_id: str,
        namespace: str,
        service_account: str,
    ) -> Tuple[bool, str]:
        """Return (ok, detail)."""
        statements = trust_policy.get("Statement") or []
        expected_sub = f"system:serviceaccount:{namespace}:{service_account}"
        for stmt in statements:
            if stmt.get("Action") not in (
                "sts:AssumeRoleWithWebIdentity",
                ["sts:AssumeRoleWithWebIdentity"],
            ):
                continue
            principal = stmt.get("Principal") or {}
            federated = principal.get("Federated") if isinstance(principal, dict) else None
            if not isinstance(federated, str) or oidc_provider_id not in federated:
                continue
            cond = stmt.get("Condition") or {}
            string_equals = cond.get("StringEquals") or {}
            sub_key = f"{oidc_provider_id}:sub"
            sub_val = string_equals.get(sub_key)
            # Sub may be a string or a list; normalise.
            sub_values = [sub_val] if isinstance(sub_val, str) else (sub_val or [])
            if expected_sub in sub_values:
                return True, "trust policy OK"
            return (
                False,
                f"trust policy federates OIDC but :sub is "
                f"{sub_values!r}, expected '{expected_sub}'",
            )
        return False, "no AssumeRoleWithWebIdentity statement federating the cluster's OIDC provider"

    def _verify_policies(self, spec: IrsaRoleSpec) -> List[str]:
        """Return the list of missing policies (empty if all present)."""
        missing: List[str] = []
        if spec.required_managed:
            try:
                attached = self.iam.list_attached_role_policies(RoleName=spec.role_name)
                attached_arns = {p["PolicyArn"] for p in attached.get("AttachedPolicies", [])}
                for needed in spec.required_managed:
                    if needed not in attached_arns:
                        missing.append(needed)
            except Exception as e:
                logger.warning(f"list_attached_role_policies failed for {spec.role_name}: {e}")
        if spec.required_inline:
            try:
                inline = self.iam.list_role_policies(RoleName=spec.role_name)
                inline_names = set(inline.get("PolicyNames", []))
                for needed in spec.required_inline:
                    if needed not in inline_names:
                        missing.append(f"inline:{needed}")
            except Exception as e:
                logger.warning(f"list_role_policies failed for {spec.role_name}: {e}")
        return missing
