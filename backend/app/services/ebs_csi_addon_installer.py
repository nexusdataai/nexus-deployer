"""
EBS CSI Driver installer for the Pure-EKS pipeline (step 2).

In `managed` IAM mode, ensures the EKS managed Addon `aws-ebs-csi-driver`
is installed and bound to a `kube-system:ebs-csi-controller-sa`-trusting
IRSA role. In `preprovisioned` IAM mode, only verifies presence and
reports a clear remediation when missing.

The IAM role policy is the AWS-managed
`arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy`. Trust
policy targets the cluster's OIDC provider for the well-known
`system:serviceaccount:kube-system:ebs-csi-controller-sa` subject.
"""
import json
import logging
from typing import Any, Dict, Optional

from app.models.eks_pipeline import PipelineCheck

logger = logging.getLogger(__name__)


EBS_ADDON_NAME = "aws-ebs-csi-driver"
EBS_CONTROLLER_SA = "ebs-csi-controller-sa"
EBS_CONTROLLER_NS = "kube-system"
EBS_DEFAULT_ROLE_NAME = "AmazonEKS_EBS_CSI_DriverRole"
EBS_MANAGED_POLICY_ARN = (
    "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
)


class EbsCsiAddonInstaller:
    """Detect and (in managed mode) install the EBS CSI Driver addon."""

    def __init__(self, eks_client, iam_client, sts_client, region: str):
        self.eks = eks_client
        self.iam = iam_client
        self.sts = sts_client
        self.region = region

    def detect(self, cluster_name: str) -> Dict[str, Any]:
        """Return the addon's status, or {'installed': False} if not found."""
        try:
            resp = self.eks.describe_addon(
                clusterName=cluster_name, addonName=EBS_ADDON_NAME
            )
            addon = resp.get("addon", {})
            return {
                "installed": True,
                "status": addon.get("status"),
                "addon_version": addon.get("addonVersion"),
                "service_account_role_arn": addon.get("serviceAccountRoleArn"),
            }
        except Exception as e:
            err_code = (
                getattr(e, "response", {})
                .get("Error", {})
                .get("Code", "")
            )
            if err_code == "ResourceNotFoundException":
                return {"installed": False}
            return {"installed": False, "error": str(e)}

    def ensure(
        self,
        cluster_name: str,
        oidc_provider_id: Optional[str],
        iam_mode: str,
    ) -> PipelineCheck:
        """Install (managed) or verify (preprovisioned) the addon."""
        det = self.detect(cluster_name)

        if det.get("installed") and det.get("status") in {"ACTIVE", "CREATING", "UPDATING"}:
            return PipelineCheck(
                name="ebs_csi_driver",
                label="EBS CSI Driver",
                status="pass" if det.get("status") == "ACTIVE" else "warn",
                detail=(
                    f"Addon {EBS_ADDON_NAME} present "
                    f"(status={det.get('status')}, "
                    f"version={det.get('addon_version')})"
                ),
                extra={
                    "addon_status": det.get("status"),
                    "addon_version": det.get("addon_version"),
                    "service_account_role_arn": det.get("service_account_role_arn"),
                },
            )

        if iam_mode == "preprovisioned":
            return PipelineCheck(
                name="ebs_csi_driver",
                label="EBS CSI Driver",
                status="fail",
                detail=(
                    "EBS CSI Driver addon not installed. In pre-provisioned "
                    "IAM mode the deployer does not install controllers."
                ),
                remediation=(
                    "Ask cluster admin to install the aws-ebs-csi-driver EKS "
                    "addon and bind it to a role with "
                    f"{EBS_MANAGED_POLICY_ARN}, trusting "
                    f"{EBS_CONTROLLER_NS}:{EBS_CONTROLLER_SA}."
                ),
            )

        # Managed mode: install via EKS Addon API.
        if not oidc_provider_id:
            return PipelineCheck(
                name="ebs_csi_driver",
                label="EBS CSI Driver",
                status="fail",
                detail="Cannot install EBS CSI without an IAM OIDC provider (IRSA required).",
                remediation=(
                    "Run `eksctl utils associate-iam-oidc-provider --cluster "
                    f"{cluster_name} --region {self.region} --approve` first."
                ),
            )

        # Step a: ensure the IAM role exists with IRSA trust policy.
        try:
            account_id = self.sts.get_caller_identity()["Account"]
            role_arn = self._ensure_role(account_id, oidc_provider_id)
        except Exception as e:
            return PipelineCheck(
                name="ebs_csi_driver",
                label="EBS CSI Driver",
                status="fail",
                detail=f"Could not create EBS CSI IAM role: {e}",
                remediation=(
                    "Confirm the deployer principal has iam:CreateRole, "
                    "iam:AttachRolePolicy, iam:GetRole. Or switch to "
                    "pre-provisioned IAM mode and let admin create the role."
                ),
            )

        # Step b: create the addon.
        try:
            self.eks.create_addon(
                clusterName=cluster_name,
                addonName=EBS_ADDON_NAME,
                serviceAccountRoleArn=role_arn,
                resolveConflicts="OVERWRITE",
            )
        except Exception as e:
            err_code = (
                getattr(e, "response", {})
                .get("Error", {})
                .get("Code", "")
            )
            # Race with another deploy attempt: addon already exists
            if err_code != "ResourceInUseException":
                return PipelineCheck(
                    name="ebs_csi_driver",
                    label="EBS CSI Driver",
                    status="fail",
                    detail=f"eks:CreateAddon failed: {e}",
                    remediation=(
                        "Check that the IAM principal has eks:CreateAddon, and "
                        "that the cluster supports the addon."
                    ),
                )

        # Re-detect and report whatever the cluster reports now.
        det = self.detect(cluster_name)
        return PipelineCheck(
            name="ebs_csi_driver",
            label="EBS CSI Driver",
            status="warn" if det.get("status") in {"CREATING", "UPDATING"} else "pass",
            detail=(
                f"Installed addon {EBS_ADDON_NAME} "
                f"(status={det.get('status')}); cluster will become ACTIVE shortly."
            ),
            extra={
                "addon_status": det.get("status"),
                "addon_version": det.get("addon_version"),
                "service_account_role_arn": role_arn,
            },
        )

    # ----- helpers --------------------------------------------------------
    def _ensure_role(self, account_id: str, oidc_provider_id: str) -> str:
        """Create or update the EBS CSI IAM role with IRSA trust + policy."""
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "Federated": f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{oidc_provider_id}:aud": "sts.amazonaws.com",
                        f"{oidc_provider_id}:sub": (
                            f"system:serviceaccount:{EBS_CONTROLLER_NS}:{EBS_CONTROLLER_SA}"
                        ),
                    }
                },
            }],
        }
        try:
            self.iam.get_role(RoleName=EBS_DEFAULT_ROLE_NAME)
            # Update the trust policy in case the OIDC provider changed.
            self.iam.update_assume_role_policy(
                RoleName=EBS_DEFAULT_ROLE_NAME,
                PolicyDocument=json.dumps(trust_policy),
            )
        except Exception as e:
            err_code = (
                getattr(e, "response", {})
                .get("Error", {})
                .get("Code", "")
            )
            if err_code == "NoSuchEntity":
                self.iam.create_role(
                    RoleName=EBS_DEFAULT_ROLE_NAME,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="EKS EBS CSI Driver IRSA role (managed by Nexus AI deployer)",
                )
            else:
                raise

        # Idempotent attach.
        try:
            self.iam.attach_role_policy(
                RoleName=EBS_DEFAULT_ROLE_NAME,
                PolicyArn=EBS_MANAGED_POLICY_ARN,
            )
        except Exception as e:
            err_code = (
                getattr(e, "response", {})
                .get("Error", {})
                .get("Code", "")
            )
            # EntityAlreadyExists / "already attached" semantics differ across SDKs;
            # tolerate the noop case.
            if err_code not in {"EntityAlreadyExists", "LimitExceeded"}:
                logger.warning(f"AttachRolePolicy may have failed: {e}")
        return f"arn:aws:iam::{account_id}:role/{EBS_DEFAULT_ROLE_NAME}"
