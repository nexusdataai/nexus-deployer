"""
IAM permissions audit (pipeline step 4).

Two modes:

  managed mode: probe whether the deployer principal can perform the
    IAM mutating operations the pipeline needs (CreateRole,
    PutRolePolicy, AttachRolePolicy, PassRole). Uses
    iam:SimulatePrincipalPolicy to check without actually trying the
    create.

  preprovisioned mode: confirm the four expected roles already exist
    with the correct trust + attached policies (delegating to
    IrsaMappingVerifier for the per-role checks). Failures point at
    the canonical JSON snippets in kube-operator/permissions/.
"""
import logging
from typing import Any, Dict, List, Optional

from app.models.eks_pipeline import IAMAuditReport, PipelineCheck

logger = logging.getLogger(__name__)


# IAM actions the deployer principal needs in managed-IAM mode.
MANAGED_REQUIRED_ACTIONS = [
    "iam:CreateRole",
    "iam:GetRole",
    "iam:UpdateAssumeRolePolicy",
    "iam:PutRolePolicy",
    "iam:AttachRolePolicy",
    "iam:PassRole",
    "iam:CreateOpenIDConnectProvider",
    "iam:GetOpenIDConnectProvider",
    "eks:CreateAccessEntry",
    "eks:DescribeAccessEntry",
    "eks:AssociateAccessPolicy",
    "eks:CreateAddon",
    "eks:DescribeAddon",
]


class IamAuditService:
    """Audit IAM readiness for the pipeline's needs."""

    def __init__(self, iam_client, sts_client):
        self.iam = iam_client
        self.sts = sts_client

    def audit(
        self,
        iam_mode: str,
        oidc_provider_id: Optional[str],
        cluster_name: str,
        capability_namespace: Optional[str] = None,
        app_role_arn: Optional[str] = None,
    ) -> IAMAuditReport:
        if iam_mode == "managed":
            return self._audit_managed(cluster_name)
        return self._audit_preprovisioned(
            cluster_name=cluster_name,
            oidc_provider_id=oidc_provider_id,
            capability_namespace=capability_namespace,
            app_role_arn=app_role_arn,
        )

    # ----- managed --------------------------------------------------------
    def _audit_managed(self, cluster_name: str) -> IAMAuditReport:
        """Run iam:SimulatePrincipalPolicy for each required action."""
        checks: List[PipelineCheck] = []
        try:
            principal = self.sts.get_caller_identity()["Arn"]
            # SimulatePrincipalPolicy needs the role ARN, not assumed-role.
            if ":assumed-role/" in principal:
                parts = principal.split(":")
                account_id = parts[4]
                role_part = parts[5]  # assumed-role/MyRole/session
                role_name = role_part.split("/")[1]
                principal = f"arn:aws:iam::{account_id}:role/{role_name}"
        except Exception as e:
            checks.append(PipelineCheck(
                name="caller_identity",
                label="Caller identity",
                status="fail",
                detail=f"sts:GetCallerIdentity failed: {e}",
            ))
            return IAMAuditReport(
                cluster_name=cluster_name,
                iam_mode="managed",
                overall="fail",
                can_proceed=False,
                checks=checks,
            )

        try:
            sim = self.iam.simulate_principal_policy(
                PolicySourceArn=principal,
                ActionNames=MANAGED_REQUIRED_ACTIONS,
            )
        except Exception as e:
            err_code = (
                getattr(e, "response", {}).get("Error", {}).get("Code", "")
            )
            # Some accounts deny SimulatePrincipalPolicy. Soften to warn.
            checks.append(PipelineCheck(
                name="iam_simulation",
                label="IAM SimulatePrincipalPolicy",
                status="warn",
                detail=(
                    f"Cannot run iam:SimulatePrincipalPolicy ({err_code or e}); "
                    "skipping deep audit. Pipeline will surface real failures "
                    "during install if permissions are insufficient."
                ),
            ))
            return IAMAuditReport(
                cluster_name=cluster_name,
                iam_mode="managed",
                overall="warn",
                can_proceed=True,
                checks=checks,
            )

        denied: List[str] = []
        for evaluation in sim.get("EvaluationResults", []):
            action = evaluation.get("EvalActionName", "")
            decision = evaluation.get("EvalDecision", "")
            if decision != "allowed":
                denied.append(f"{action} ({decision})")

        if denied:
            checks.append(PipelineCheck(
                name="iam_simulation",
                label="IAM permissions for managed-IAM mode",
                status="fail",
                detail=(
                    f"{len(denied)}/{len(MANAGED_REQUIRED_ACTIONS)} required "
                    f"actions are denied for {principal}: {', '.join(denied[:5])}"
                    + ("..." if len(denied) > 5 else "")
                ),
                remediation=(
                    "Either grant the missing actions to the deployer principal, "
                    "or switch to pre-provisioned IAM mode where the admin owns "
                    "the IAM roles."
                ),
                extra={"denied_actions": denied, "principal_arn": principal},
            ))
        else:
            checks.append(PipelineCheck(
                name="iam_simulation",
                label="IAM permissions for managed-IAM mode",
                status="pass",
                detail=(
                    f"All {len(MANAGED_REQUIRED_ACTIONS)} required actions "
                    f"are allowed for {principal}"
                ),
                extra={"principal_arn": principal},
            ))

        worst = next(("fail" for c in checks if c.status == "fail"), None) or \
                next(("warn" for c in checks if c.status == "warn"), None) or "pass"
        can_proceed = not any(c.status == "fail" for c in checks)
        return IAMAuditReport(
            cluster_name=cluster_name,
            iam_mode="managed",
            overall=worst,  # type: ignore[arg-type]
            can_proceed=can_proceed,
            checks=checks,
        )

    # ----- preprovisioned -------------------------------------------------
    def _audit_preprovisioned(
        self,
        cluster_name: str,
        oidc_provider_id: Optional[str],
        capability_namespace: Optional[str],
        app_role_arn: Optional[str],
    ) -> IAMAuditReport:
        """Verify each pre-provisioned role exists with the right trust."""
        from app.services.alb_controller_installer import (
            ALB_NAMESPACE, ALB_ROLE_NAME, ALB_SERVICE_ACCOUNT,
        )
        from app.services.ebs_csi_addon_installer import (
            EBS_CONTROLLER_NS, EBS_CONTROLLER_SA, EBS_DEFAULT_ROLE_NAME,
            EBS_MANAGED_POLICY_ARN,
        )
        from app.services.irsa_mapping_verifier import (
            IrsaMappingVerifier, IrsaRoleSpec,
        )
        from app.services.operator_deployment_service import (
            OPERATOR_NAMESPACE, OPERATOR_SERVICE_ACCOUNT,
        )

        verifier = IrsaMappingVerifier(iam_client=self.iam, sts_client=self.sts)
        specs: List[IrsaRoleSpec] = [
            IrsaRoleSpec(
                name="operator_role",
                label="Operator role (admin-managed)",
                role_name="totogi-operator-role",
                namespace=OPERATOR_NAMESPACE,
                service_account=OPERATOR_SERVICE_ACCOUNT,
                admin_managed_remediation=(
                    "Create totogi-operator-role using "
                    "kube-operator/permissions/operator-policy.json + "
                    "operator-trust-policy.json with the cluster's OIDC "
                    "provider ID substituted."
                ),
            ),
            IrsaRoleSpec(
                name="alb_controller_role",
                label="AWS Load Balancer Controller role",
                role_name=ALB_ROLE_NAME,
                namespace=ALB_NAMESPACE,
                service_account=ALB_SERVICE_ACCOUNT,
                required_inline_policy_names=["AWSLoadBalancerControllerIAMPolicy"],
                admin_managed_remediation=(
                    "Create the ALB Controller role and attach the upstream "
                    "AWSLoadBalancerControllerIAMPolicy. Reference: "
                    "https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html"
                ),
            ),
            IrsaRoleSpec(
                name="ebs_csi_role",
                label="EBS CSI Driver role",
                role_name=EBS_DEFAULT_ROLE_NAME,
                namespace=EBS_CONTROLLER_NS,
                service_account=EBS_CONTROLLER_SA,
                required_managed_policies=[EBS_MANAGED_POLICY_ARN],
                admin_managed_remediation=(
                    "Create AmazonEKS_EBS_CSI_DriverRole with "
                    f"{EBS_MANAGED_POLICY_ARN}, trusting "
                    f"{EBS_CONTROLLER_NS}:{EBS_CONTROLLER_SA}."
                ),
            ),
        ]

        if capability_namespace and app_role_arn:
            role_name = (
                app_role_arn.rsplit("/", 1)[-1] if "/" in app_role_arn else app_role_arn
            )
            specs.append(IrsaRoleSpec(
                name="capability_app_role",
                label="Per-capability application role",
                role_name=role_name,
                namespace=capability_namespace,
                service_account="*",
                admin_managed_remediation=(
                    "Create the per-capability app role using "
                    "kube-operator/permissions/app-policy.json + "
                    "app-trust-policy.json. Forward the ARN via "
                    "spec.appRoleArn on the TotogiCapability CR."
                ),
            ))

        checks: List[PipelineCheck] = []
        for spec in specs:
            if spec.service_account == "*":
                # Soft-match on namespace; reuse the orchestrator helper.
                from app.services.eks_pipeline_orchestrator import (
                    EksPipelineOrchestrator,
                )
                check = EksPipelineOrchestrator._verify_role_namespace_only(
                    verifier, spec, oidc_provider_id
                )
            else:
                check = verifier.verify_role(spec, oidc_provider_id)
            checks.append(check)

        worst = "pass"
        for c in checks:
            if c.status == "fail":
                worst = "fail"
                break
            if c.status == "warn":
                worst = "warn"
        can_proceed = not any(c.status == "fail" for c in checks)
        return IAMAuditReport(
            cluster_name=cluster_name,
            iam_mode="preprovisioned",
            overall=worst,  # type: ignore[arg-type]
            can_proceed=can_proceed,
            checks=checks,
        )
