"""
AWS Load Balancer Controller installer for the Pure-EKS pipeline (step 2).

In `managed` IAM mode, attempts to install the controller via `helm`
(matching kube-operator/operator-nexus.sh:1150-1187 behavior).
In `preprovisioned` IAM mode, only verifies presence and returns clear
remediation when missing.

We deliberately do not vendor upstream manifests in v1: the upstream
manifest set is large and version-sensitive (ServiceAccount, Deployment,
ClusterRole+Bindings, Service, two Webhook configurations). Bundling
them inside `nexus-installer-backend.exe` makes maintenance painful. The helm
path mirrors what the existing operator script does.

If `helm` is unavailable on PATH, we surface a fail-with-remediation
with the exact commands the user can run.
"""
import json
import logging
import shutil
import subprocess
from typing import Any, Dict, Optional

from app.models.eks_pipeline import PipelineCheck

logger = logging.getLogger(__name__)


ALB_NAMESPACE = "kube-system"
ALB_DEPLOYMENT_NAME = "aws-load-balancer-controller"
ALB_SERVICE_ACCOUNT = "aws-load-balancer-controller"
ALB_ROLE_NAME = "AmazonEKSLoadBalancerControllerRole"
# Upstream-published policy JSON URL that we reference in remediation copy
ALB_POLICY_URL = (
    "https://raw.githubusercontent.com/kubernetes-sigs/"
    "aws-load-balancer-controller/v2.7.2/docs/install/iam_policy.json"
)


class AlbControllerInstaller:
    """Detect and (in managed mode) install the AWS Load Balancer Controller."""

    def __init__(
        self,
        eks_client,
        iam_client,
        sts_client,
        region: str,
        apps_v1=None,
    ):
        self.eks = eks_client
        self.iam = iam_client
        self.sts = sts_client
        self.region = region
        self.apps_v1 = apps_v1  # injected from operator_deployment_service._get_k8s_clients

    def detect(self) -> Dict[str, Any]:
        """Return ALB controller readiness state via apps/v1 API."""
        if self.apps_v1 is None:
            return {"installed": False, "error": "apps_v1 client not available"}
        try:
            from kubernetes.client.rest import ApiException
            try:
                dep = self.apps_v1.read_namespaced_deployment(
                    name=ALB_DEPLOYMENT_NAME, namespace=ALB_NAMESPACE
                )
            except ApiException as e:
                if e.status == 404:
                    return {"installed": False}
                raise
            ready = (dep.status.ready_replicas or 0) if dep.status else 0
            desired = (dep.spec.replicas or 1) if dep.spec else 1
            image = ""
            if dep.spec and dep.spec.template and dep.spec.template.spec:
                for c in dep.spec.template.spec.containers or []:
                    if c.name == ALB_DEPLOYMENT_NAME:
                        image = c.image or ""
                        break
            return {
                "installed": ready > 0,
                "ready_replicas": ready,
                "desired_replicas": desired,
                "image": image,
            }
        except Exception as e:
            return {"installed": False, "error": str(e)}

    def ensure(
        self,
        cluster_name: str,
        oidc_provider_id: Optional[str],
        iam_mode: str,
    ) -> PipelineCheck:
        det = self.detect()

        if det.get("installed"):
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="pass",
                detail=(
                    f"Deployment {ALB_DEPLOYMENT_NAME} ready "
                    f"({det.get('ready_replicas')}/{det.get('desired_replicas')}, "
                    f"image: {det.get('image')})"
                ),
                extra={"image": det.get("image")},
            )

        if iam_mode == "preprovisioned":
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="fail",
                detail=(
                    "AWS Load Balancer Controller not installed. In "
                    "pre-provisioned IAM mode the deployer does not install "
                    "controllers."
                ),
                remediation=(
                    "Ask cluster admin to install the controller. Reference: "
                    "https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html"
                ),
            )

        # Managed mode: attempt helm install.
        if shutil.which("helm") is None:
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="fail",
                detail="helm not found on PATH; deployer cannot install the controller automatically.",
                remediation=(
                    f"Install helm (https://helm.sh/docs/intro/install/) and run:\n"
                    f"  helm repo add eks https://aws.github.io/eks-charts\n"
                    f"  helm repo update\n"
                    f"  helm install aws-load-balancer-controller eks/aws-load-balancer-controller \\\n"
                    f"    -n {ALB_NAMESPACE} \\\n"
                    f"    --set clusterName={cluster_name} \\\n"
                    f"    --set serviceAccount.create=false \\\n"
                    f"    --set serviceAccount.name={ALB_SERVICE_ACCOUNT}\n"
                    "After install, re-run the cluster pre-flight check."
                ),
            )

        if not oidc_provider_id:
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="fail",
                detail="Cannot install ALB Controller without an IAM OIDC provider (IRSA required).",
                remediation=(
                    "Run `eksctl utils associate-iam-oidc-provider --cluster "
                    f"{cluster_name} --region {self.region} --approve` first."
                ),
            )

        # Step a: ensure IAM role + attach inline policy fetched from upstream.
        try:
            account_id = self.sts.get_caller_identity()["Account"]
            role_arn = self._ensure_role(account_id, oidc_provider_id)
        except Exception as e:
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="fail",
                detail=f"Could not create ALB Controller IAM role: {e}",
                remediation=(
                    "Confirm the deployer principal has iam:CreateRole / "
                    "iam:PutRolePolicy / iam:CreatePolicy."
                ),
            )

        # Step b: create the ServiceAccount with IRSA annotation. Helm chart
        # is configured (below) with `serviceAccount.create=false` so we
        # control SA creation here.
        try:
            self._ensure_service_account(role_arn)
        except Exception as e:
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="fail",
                detail=f"Could not create ServiceAccount {ALB_NAMESPACE}/{ALB_SERVICE_ACCOUNT}: {e}",
            )

        # Step c: helm install. Block on completion; helm waits for the
        # release; we then re-detect.
        try:
            self._helm_install(cluster_name)
        except subprocess.CalledProcessError as e:
            return PipelineCheck(
                name="alb_controller",
                label="AWS Load Balancer Controller",
                status="fail",
                detail=f"helm install failed (exit {e.returncode}): {e.output or e.stderr}",
                remediation=(
                    "Re-run `helm repo update`, then retry the install. "
                    "If the failure persists, inspect the controller pod logs "
                    "after manual install."
                ),
            )

        det = self.detect()
        return PipelineCheck(
            name="alb_controller",
            label="AWS Load Balancer Controller",
            status="pass" if det.get("installed") else "warn",
            detail=(
                f"Installed via helm; ready={det.get('ready_replicas')}/"
                f"{det.get('desired_replicas')}"
                if det.get("installed")
                else "helm install completed; controller is starting up."
            ),
            extra={"image": det.get("image"), "role_arn": role_arn},
        )

    # ----- helpers --------------------------------------------------------
    def _ensure_role(self, account_id: str, oidc_provider_id: str) -> str:
        """Create the IAM role + attach the upstream IAM policy."""
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
                            f"system:serviceaccount:{ALB_NAMESPACE}:{ALB_SERVICE_ACCOUNT}"
                        ),
                    }
                },
            }],
        }
        try:
            self.iam.get_role(RoleName=ALB_ROLE_NAME)
            self.iam.update_assume_role_policy(
                RoleName=ALB_ROLE_NAME,
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
                    RoleName=ALB_ROLE_NAME,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description="AWS Load Balancer Controller IRSA role (Nexus AI deployer)",
                )
            else:
                raise

        # Attach inline policy from upstream JSON.
        policy_doc = self._fetch_upstream_policy()
        if policy_doc:
            try:
                self.iam.put_role_policy(
                    RoleName=ALB_ROLE_NAME,
                    PolicyName="AWSLoadBalancerControllerIAMPolicy",
                    PolicyDocument=policy_doc,
                )
            except Exception as e:
                logger.warning(f"PutRolePolicy may have failed: {e}")
        return f"arn:aws:iam::{account_id}:role/{ALB_ROLE_NAME}"

    def _fetch_upstream_policy(self) -> Optional[str]:
        """Fetch the upstream IAM policy JSON. Returns None on failure."""
        try:
            import urllib.request
            with urllib.request.urlopen(ALB_POLICY_URL, timeout=10) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not fetch ALB IAM policy: {e}")
            return None

    def _ensure_service_account(self, role_arn: str):
        """Create or annotate kube-system:aws-load-balancer-controller SA."""
        from kubernetes import client as k8s_client
        from kubernetes.client.rest import ApiException

        core_v1 = k8s_client.CoreV1Api()
        annotations = {"eks.amazonaws.com/role-arn": role_arn}
        try:
            existing = core_v1.read_namespaced_service_account(
                name=ALB_SERVICE_ACCOUNT, namespace=ALB_NAMESPACE
            )
            existing.metadata.annotations = (existing.metadata.annotations or {})
            existing.metadata.annotations.update(annotations)
            core_v1.patch_namespaced_service_account(
                name=ALB_SERVICE_ACCOUNT,
                namespace=ALB_NAMESPACE,
                body=existing,
            )
        except ApiException as e:
            if e.status != 404:
                raise
            sa = k8s_client.V1ServiceAccount(
                metadata=k8s_client.V1ObjectMeta(
                    name=ALB_SERVICE_ACCOUNT,
                    namespace=ALB_NAMESPACE,
                    annotations=annotations,
                    labels={
                        "app.kubernetes.io/name": ALB_DEPLOYMENT_NAME,
                        "app.kubernetes.io/managed-by": "nexus-deployer",
                    },
                ),
            )
            core_v1.create_namespaced_service_account(
                namespace=ALB_NAMESPACE, body=sa
            )

    def _helm_install(self, cluster_name: str):
        """Run `helm` to install the controller. Adds repo if needed."""
        # Idempotent repo add - helm exits 0 when it's already there.
        subprocess.run(
            ["helm", "repo", "add", "eks", "https://aws.github.io/eks-charts"],
            check=False, capture_output=True, text=True,
        )
        subprocess.run(
            ["helm", "repo", "update", "eks"],
            check=True, capture_output=True, text=True,
        )
        # Use `upgrade --install` for idempotency.
        result = subprocess.run(
            [
                "helm", "upgrade", "--install",
                ALB_DEPLOYMENT_NAME, "eks/aws-load-balancer-controller",
                "-n", ALB_NAMESPACE,
                "--set", f"clusterName={cluster_name}",
                "--set", "serviceAccount.create=false",
                "--set", f"serviceAccount.name={ALB_SERVICE_ACCOUNT}",
                "--set", f"region={self.region}",
                "--wait",
                "--timeout", "5m",
            ],
            check=True, capture_output=True, text=True,
        )
        logger.info(f"helm install OK: {result.stdout[:400]}")
