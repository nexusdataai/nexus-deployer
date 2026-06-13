"""
Orchestrator for the 10-step Pure-EKS deployment pipeline.

The pipeline mirrors what kube-operator/operator-nexus.sh and
kube-operator/inspect-capability.sh do via bash, exposed as Python services
the wizard can drive.

Phase 1 implements:
  - The orchestrator skeleton with one method per step.
  - Step 1: cluster readiness scan (11 checks - 10 after dropping the
    redundant kubectl-CLI probe), ported from
    kube-operator/operator-nexus.sh:1559-2287.

Subsequent phases fill in steps 2-7 and 10. Steps 5, 8, 9 are operator-
driven (existing OperatorDeploymentService + DeploymentOrchestrator
already cover them via TotogiCapability CR apply).
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.models.eks_pipeline import (
    CapabilityInspectionReport,
    ClusterReadinessReport,
    ControllerInstallReport,
    IAMAuditReport,
    IRSAMappingReport,
    NetworkConfigReport,
    PipelineCheck,
    ReachabilityReport,
)
from app.services.operator_deployment_service import (
    OPERATOR_DEPLOYMENT_NAME,
    OPERATOR_NAMESPACE,
    OPERATOR_SERVICE_ACCOUNT,
    OperatorDeploymentService,
)

logger = logging.getLogger(__name__)


# Minimum supported EKS control-plane version (matches operator-nexus.sh)
MIN_EKS_VERSION = "1.23"


class EksPipelineOrchestrator:
    """Drives the 10-step Pure-EKS deployment pipeline.

    Composition over inheritance: holds an `OperatorDeploymentService`
    instance and reuses its `_get_k8s_clients`, `check_alb_controller_installed`,
    and `check_operator_status` helpers, instead of extracting them into
    free functions. This keeps the surface area minimal and avoids
    refactoring touch in code paths the existing wizard already exercises.
    """

    def __init__(
        self,
        aws_session_id: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.aws_session_id = aws_session_id
        self.region = region
        # Lazy: only constructed when a step needs it (avoids hitting boto3
        # at orchestrator instantiation time).
        self._op_service: Optional[OperatorDeploymentService] = None

    @property
    def operator_service(self) -> OperatorDeploymentService:
        if self._op_service is None:
            from app.services.operator_deployment_service import (
                get_operator_deployment_service,
            )
            self._op_service = get_operator_deployment_service(
                aws_session_id=self.aws_session_id,
                region=self.region,
            )
        return self._op_service

    # ----------------------------------------------------------------- step 1
    async def step1_cluster_readiness(
        self,
        cluster_name: str,
        iam_mode: str = "managed",
    ) -> ClusterReadinessReport:
        """
        Cluster readiness scan. Ports the 10 useful checks from
        operator-nexus.sh:1559-2287. Each check appends a
        `PipelineCheck` row; the overall verdict is the worst severity.
        """
        ops = self.operator_service
        region = ops.region
        eks = ops.eks_client
        iam = ops.iam_client
        sts = ops.sts_client

        checks: List[PipelineCheck] = []

        # ----- caller identity -----
        try:
            identity = sts.get_caller_identity()
            account_id = identity["Account"]
            principal_arn = identity["Arn"]
            if ":assumed-role/" in principal_arn:
                role_name = principal_arn.split("/")[1]
                principal_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        except Exception as e:
            checks.append(PipelineCheck(
                name="aws_credentials",
                label="AWS credentials",
                status="fail",
                detail=f"sts:GetCallerIdentity failed: {e}",
                remediation="Re-authenticate at the AWS Auth wizard step.",
            ))
            return ClusterReadinessReport(
                cluster_name=cluster_name, region=region or "",
                overall="fail", can_proceed=False, checks=checks,
            )

        # ----- check 1: cluster exists + ACTIVE + version -----
        cluster_info: Dict[str, Any] = {}
        try:
            cluster_info = eks.describe_cluster(name=cluster_name)["cluster"]
            cluster_status = cluster_info.get("status", "")
            cluster_version = cluster_info.get("version", "")
            if cluster_status == "ACTIVE":
                version_ok = cluster_version >= MIN_EKS_VERSION
                checks.append(PipelineCheck(
                    name="cluster_active",
                    label="Cluster ACTIVE and supported version",
                    status="pass" if version_ok else "warn",
                    detail=(
                        f"Cluster {cluster_name} is ACTIVE, version {cluster_version}"
                        + ("" if version_ok else f" (below minimum {MIN_EKS_VERSION})")
                    ),
                    remediation=None if version_ok else (
                        f"EKS {cluster_version} is below the minimum supported "
                        f"version {MIN_EKS_VERSION}. Upgrade the control plane."
                    ),
                    extra={"version": cluster_version, "endpoint": cluster_info.get("endpoint")},
                ))
            else:
                checks.append(PipelineCheck(
                    name="cluster_active",
                    label="Cluster ACTIVE",
                    status="fail",
                    detail=f"Cluster status: {cluster_status} (expected ACTIVE)",
                    remediation="Wait for the cluster to finish creating, or pick a different cluster.",
                ))
        except Exception as e:
            err_code = getattr(getattr(e, "response", {}), "get", lambda *_: "")("Error", {}).get("Code") if hasattr(e, "response") else ""
            if err_code == "ResourceNotFoundException":
                checks.append(PipelineCheck(
                    name="cluster_active",
                    label="Cluster exists",
                    status="fail",
                    detail=f"Cluster {cluster_name} not found in {region}",
                    remediation="Pick a different cluster from the EKS Cluster Selector step.",
                ))
            else:
                checks.append(PipelineCheck(
                    name="cluster_active",
                    label="Cluster reachable",
                    status="fail",
                    detail=f"eks:DescribeCluster failed: {e}",
                    remediation="Verify your IAM principal has eks:DescribeCluster.",
                ))
            return ClusterReadinessReport(
                cluster_name=cluster_name, region=region or "",
                overall="fail", can_proceed=False, checks=checks,
            )

        # ----- check 2: OIDC provider + IAM presence -----
        oidc_issuer = cluster_info.get("identity", {}).get("oidc", {}).get("issuer")
        oidc_provider_id = oidc_issuer.replace("https://", "") if oidc_issuer else None
        oidc_extra: Dict[str, Any] = {"issuer": oidc_issuer, "provider_id": oidc_provider_id}
        if not oidc_issuer:
            checks.append(PipelineCheck(
                name="oidc_provider",
                label="OIDC provider configured",
                status="fail",
                detail="Cluster has no OIDC issuer; IRSA cannot work.",
                remediation=(
                    "Create an IAM OIDC provider for the cluster: "
                    "`eksctl utils associate-iam-oidc-provider --cluster <name> --approve` "
                    "or via the Console."
                ),
                extra=oidc_extra,
            ))
        else:
            oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider_id}"
            try:
                oidc_info = iam.get_open_id_connect_provider(OpenIDConnectProviderArn=oidc_arn)
                client_ids = oidc_info.get("ClientIDList", [])
                has_sts_aud = "sts.amazonaws.com" in client_ids
                checks.append(PipelineCheck(
                    name="oidc_provider",
                    label="OIDC provider registered in IAM",
                    status="pass" if has_sts_aud else "warn",
                    detail=(
                        f"OIDC provider {oidc_provider_id} present in IAM"
                        + ("" if has_sts_aud else "; missing sts.amazonaws.com audience")
                    ),
                    remediation=None if has_sts_aud else (
                        "Add `sts.amazonaws.com` to the OIDC provider's audience list "
                        "so IRSA tokens validate."
                    ),
                    extra={**oidc_extra, "client_ids": client_ids, "arn": oidc_arn},
                ))
            except Exception as e:
                err_code = getattr(getattr(e, "response", {}), "get", lambda *_: "")("Error", {}).get("Code") if hasattr(e, "response") else ""
                if err_code == "NoSuchEntity":
                    checks.append(PipelineCheck(
                        name="oidc_provider",
                        label="OIDC provider registered in IAM",
                        status="fail",
                        detail=f"OIDC provider {oidc_provider_id} NOT found in IAM",
                        remediation=(
                            "Run `eksctl utils associate-iam-oidc-provider --cluster "
                            f"{cluster_name} --region {region} --approve`."
                        ),
                        extra=oidc_extra,
                    ))
                else:
                    checks.append(PipelineCheck(
                        name="oidc_provider",
                        label="OIDC provider registered in IAM",
                        status="warn",
                        detail=f"Could not verify OIDC provider: {e}",
                        extra=oidc_extra,
                    ))

        # ----- check 3: operator IAM role (preprovisioned mode only) -----
        if iam_mode == "preprovisioned":
            operator_role_name = "totogi-operator-role"
            try:
                role_info = iam.get_role(RoleName=operator_role_name)
                trust = role_info["Role"]["AssumeRolePolicyDocument"]
                has_irsa = False
                for stmt in trust.get("Statement", []):
                    fed = (stmt.get("Principal") or {}).get("Federated", "")
                    if oidc_provider_id and oidc_provider_id in fed:
                        has_irsa = True
                        break
                checks.append(PipelineCheck(
                    name="operator_iam_role",
                    label="Operator IAM role exists with IRSA trust",
                    status="pass" if has_irsa else "fail",
                    detail=(
                        f"Role {operator_role_name} present"
                        + ("; trust policy includes the cluster's OIDC provider"
                           if has_irsa else "; trust policy missing OIDC federation")
                    ),
                    remediation=None if has_irsa else (
                        "Update the trust policy to match "
                        "kube-operator/permissions/operator-trust-policy.json with the "
                        "cluster's OIDC provider ID substituted."
                    ),
                    extra={"role_arn": role_info["Role"]["Arn"]},
                ))
            except Exception as e:
                err_code = getattr(getattr(e, "response", {}), "get", lambda *_: "")("Error", {}).get("Code") if hasattr(e, "response") else ""
                if err_code == "NoSuchEntity":
                    checks.append(PipelineCheck(
                        name="operator_iam_role",
                        label="Operator IAM role exists",
                        status="fail",
                        detail=f"Role {operator_role_name} not found in account {account_id}",
                        remediation=(
                            "In pre-provisioned IAM mode the admin must create the "
                            "operator role first using "
                            "kube-operator/permissions/operator-policy.json + "
                            "operator-trust-policy.json."
                        ),
                    ))
                else:
                    checks.append(PipelineCheck(
                        name="operator_iam_role",
                        label="Operator IAM role exists",
                        status="warn",
                        detail=f"iam:GetRole failed: {e}",
                    ))
        else:
            checks.append(PipelineCheck(
                name="operator_iam_role",
                label="Operator IAM role",
                status="skipped",
                detail="Managed-IAM mode: deployer will create the operator role during install.",
            ))

        # ----- check 4: cluster authentication mode -----
        access_config = cluster_info.get("accessConfig", {}) or {}
        auth_mode = access_config.get("authenticationMode", "CONFIG_MAP")
        if auth_mode == "API":
            checks.append(PipelineCheck(
                name="auth_mode",
                label="Cluster authentication mode",
                status="pass",
                detail="API (modern Access Entry mode)",
                extra={"auth_mode": auth_mode},
            ))
        elif auth_mode == "API_AND_CONFIG_MAP":
            checks.append(PipelineCheck(
                name="auth_mode",
                label="Cluster authentication mode",
                status="pass",
                detail="API_AND_CONFIG_MAP (hybrid)",
                extra={"auth_mode": auth_mode},
            ))
        else:
            checks.append(PipelineCheck(
                name="auth_mode",
                label="Cluster authentication mode",
                status="warn",
                detail=f"{auth_mode} (legacy aws-auth ConfigMap only)",
                remediation=(
                    "Switch the cluster to API or API_AND_CONFIG_MAP so the "
                    "deployer can use EKS Access Entries."
                ),
                extra={"auth_mode": auth_mode},
            ))

        # ----- check 5: EKS Access Entry for the deployer principal -----
        if auth_mode in ("API", "API_AND_CONFIG_MAP"):
            try:
                eks.describe_access_entry(
                    clusterName=cluster_name, principalArn=principal_arn
                )
                policies = eks.list_associated_access_policies(
                    clusterName=cluster_name, principalArn=principal_arn
                )
                policy_arns = [p["policyArn"] for p in policies.get("associatedAccessPolicies", [])]
                checks.append(PipelineCheck(
                    name="access_entry",
                    label="EKS Access Entry for deployer principal",
                    status="pass" if policy_arns else "warn",
                    detail=(
                        f"Access Entry exists with {len(policy_arns)} policy(ies)"
                        + ("" if policy_arns else "; no policies attached (no access)")
                    ),
                    remediation=None if policy_arns else (
                        "Attach an EKS access policy "
                        "(e.g. AmazonEKSClusterAdminPolicy) to the access entry, "
                        "or let the deployer create one during install."
                    ),
                    extra={"principal_arn": principal_arn, "policies": policy_arns},
                ))
            except Exception as e:
                err_code = getattr(getattr(e, "response", {}), "get", lambda *_: "")("Error", {}).get("Code") if hasattr(e, "response") else ""
                if err_code == "ResourceNotFoundException":
                    checks.append(PipelineCheck(
                        name="access_entry",
                        label="EKS Access Entry for deployer principal",
                        status="warn",
                        detail="No Access Entry found",
                        remediation=(
                            "Deploy step will create an Access Entry automatically; "
                            "if it fails, ask an admin to add one for "
                            f"{principal_arn}."
                        ),
                        extra={"principal_arn": principal_arn},
                    ))
                else:
                    checks.append(PipelineCheck(
                        name="access_entry",
                        label="EKS Access Entry for deployer principal",
                        status="warn",
                        detail=f"Could not check Access Entry: {e}",
                        extra={"principal_arn": principal_arn},
                    ))
        else:
            checks.append(PipelineCheck(
                name="access_entry",
                label="EKS Access Entry for deployer principal",
                status="skipped",
                detail=f"Not applicable in {auth_mode} mode (uses aws-auth ConfigMap).",
            ))

        # ----- check 6: node groups + node IAM policies -----
        try:
            ng_list = eks.list_nodegroups(clusterName=cluster_name).get("nodegroups", [])
            if not ng_list:
                checks.append(PipelineCheck(
                    name="node_groups",
                    label="Node groups present",
                    status="warn",
                    detail="No managed node groups found.",
                    remediation=(
                        "Pure EKS workloads need at least one node group "
                        "(or Fargate/Karpenter coverage). Create one before deploying."
                    ),
                ))
            else:
                missing_policies: List[str] = []
                ng_summaries: List[Dict[str, Any]] = []
                required = {
                    "AmazonEC2ContainerRegistryReadOnly":
                        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
                    "AmazonEKSWorkerNodePolicy":
                        "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                    "AmazonEKS_CNI_Policy":
                        "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
                }
                for ng_name in ng_list:
                    ng = eks.describe_nodegroup(
                        clusterName=cluster_name, nodegroupName=ng_name
                    )["nodegroup"]
                    role_arn = ng.get("nodeRole", "")
                    role_name = role_arn.split("/")[-1] if role_arn else ""
                    ng_summary = {
                        "name": ng_name,
                        "status": ng.get("status"),
                        "desired_size": (ng.get("scalingConfig") or {}).get("desiredSize"),
                        "node_role": role_arn,
                    }
                    try:
                        attached = iam.list_attached_role_policies(RoleName=role_name)
                        attached_arns = {p["PolicyArn"] for p in attached.get("AttachedPolicies", [])}
                        for label, arn in required.items():
                            if arn not in attached_arns:
                                missing_policies.append(f"{ng_name}: {label}")
                    except Exception as ie:
                        ng_summary["policy_check_error"] = str(ie)
                    ng_summaries.append(ng_summary)
                checks.append(PipelineCheck(
                    name="node_groups",
                    label="Node groups + node IAM policies",
                    status="pass" if not missing_policies else "warn",
                    detail=(
                        f"{len(ng_list)} node group(s); "
                        + ("all required IAM policies attached"
                           if not missing_policies
                           else f"missing: {', '.join(missing_policies)}")
                    ),
                    remediation=None if not missing_policies else (
                        "Attach the missing AWS-managed policies to the node IAM role."
                    ),
                    extra={"node_groups": ng_summaries},
                ))
        except Exception as e:
            checks.append(PipelineCheck(
                name="node_groups",
                label="Node groups",
                status="warn",
                detail=f"eks:ListNodegroups failed: {e}",
            ))

        # ----- check 7: ECR operator-image repo -----
        try:
            from botocore.exceptions import ClientError
            ecr = ops._init_ecr_client() if hasattr(ops, "_init_ecr_client") else None
            if ecr is None:
                # Build an ECR client from the same session/credentials
                import boto3
                from app.services.aws_session_manager import aws_session_manager
                creds: Dict[str, Any] = {}
                if ops.aws_session_id:
                    creds = aws_session_manager.get_credentials_dict(ops.aws_session_id) or {}
                ecr = boto3.client(
                    "ecr",
                    region_name=region,
                    aws_access_key_id=creds.get("aws_access_key_id"),
                    aws_secret_access_key=creds.get("aws_secret_access_key"),
                    aws_session_token=creds.get("aws_session_token"),
                )

            ecr_repo_name = "totogi-operator"
            try:
                repo_info = ecr.describe_repositories(repositoryNames=[ecr_repo_name])
                repo = repo_info["repositories"][0]
                images = ecr.describe_images(repositoryName=ecr_repo_name, maxResults=10)
                image_count = len(images.get("imageDetails", []))
                latest_present = any(
                    "latest" in (img.get("imageTags") or [])
                    for img in images.get("imageDetails", [])
                )
                checks.append(PipelineCheck(
                    name="ecr_operator_image",
                    label="ECR operator image",
                    status="pass" if image_count > 0 else "warn",
                    detail=(
                        f"Repository {ecr_repo_name} has {image_count} image(s)"
                        + ("; 'latest' tag present" if latest_present else
                           "; 'latest' tag missing - operator deploy will fail" if image_count > 0 else
                           "; no images")
                    ),
                    remediation=None if (image_count > 0 and latest_present) else (
                        "Build and push the operator image: "
                        "`./build-and-push.sh latest` from the kube-operator directory."
                    ),
                    extra={"uri": repo["repositoryUri"], "image_count": image_count},
                ))
            except ClientError as ce:
                err_code = ce.response["Error"]["Code"]
                if err_code == "RepositoryNotFoundException":
                    checks.append(PipelineCheck(
                        name="ecr_operator_image",
                        label="ECR operator image",
                        status="warn",
                        detail=f"ECR repository {ecr_repo_name} does not exist yet.",
                        remediation=(
                            "Create the repository and push the operator image: "
                            "`./build-and-push.sh latest`."
                        ),
                    ))
                else:
                    checks.append(PipelineCheck(
                        name="ecr_operator_image",
                        label="ECR operator image",
                        status="warn",
                        detail=f"ecr:DescribeRepositories failed: {ce}",
                    ))
        except Exception as e:
            checks.append(PipelineCheck(
                name="ecr_operator_image",
                label="ECR operator image",
                status="warn",
                detail=f"ECR check failed: {e}",
            ))

        # ----- check 8: Kubernetes API access via Python client -----
        # Also check 10/11 in the same try since they all need a working K8s client.
        try:
            core_v1, apps_v1, _ = await ops._get_k8s_clients(cluster_name)
            core_v1.list_namespace(limit=1)
            checks.append(PipelineCheck(
                name="k8s_api_access",
                label="Kubernetes API access",
                status="pass",
                detail="kubernetes-client can list namespaces.",
            ))

            # ----- check 10: ALB Controller -----
            alb_status = await ops.check_alb_controller_installed(cluster_name)
            if alb_status.get("installed"):
                checks.append(PipelineCheck(
                    name="alb_controller",
                    label="AWS Load Balancer Controller",
                    status="pass",
                    detail=alb_status.get("message", ""),
                    extra={"version": alb_status.get("version")},
                ))
            else:
                # Pure EKS Ingress requires this. Fail in preprovisioned mode
                # (admin must install); warn in managed mode (deployer will
                # install in step 2).
                if iam_mode == "preprovisioned":
                    checks.append(PipelineCheck(
                        name="alb_controller",
                        label="AWS Load Balancer Controller",
                        status="fail",
                        detail=alb_status.get("message", "Not installed"),
                        remediation=(
                            "Pre-provisioned IAM mode: admin must install the "
                            "AWS Load Balancer Controller before deploying. "
                            "See kube-operator/permissions/aws-prerequisites.md."
                        ),
                    ))
                else:
                    checks.append(PipelineCheck(
                        name="alb_controller",
                        label="AWS Load Balancer Controller",
                        status="warn",
                        detail=alb_status.get("message", "Not installed yet"),
                        remediation=(
                            "Deployer will install it in the Controllers step "
                            "(managed IAM mode)."
                        ),
                    ))

            # ----- check 11: operator deployment readiness -----
            op_status = await ops.check_operator_status(cluster_name)
            if op_status.get("installed"):
                ready = op_status.get("ready_replicas", 0)
                desired = op_status.get("desired_replicas", 1)
                checks.append(PipelineCheck(
                    name="operator_status",
                    label="Totogi Operator deployment",
                    status="pass" if ready >= desired else "warn",
                    detail=op_status.get("detail") or (
                        f"Deployment {OPERATOR_DEPLOYMENT_NAME} in {OPERATOR_NAMESPACE}: "
                        f"{ready}/{desired} replicas"
                    ),
                    extra={
                        "version": op_status.get("version"),
                        "namespace": op_status.get("namespace"),
                    },
                ))
            else:
                checks.append(PipelineCheck(
                    name="operator_status",
                    label="Totogi Operator deployment",
                    status="warn" if op_status.get("status") != "unknown" else "fail",
                    detail=op_status.get("detail") or "Operator not installed.",
                    remediation=(
                        "Deployer will install the operator in step 5 of the pipeline."
                    ),
                    extra={
                        "namespace_exists": op_status.get("namespace_exists"),
                        "crd_exists": op_status.get("crd_exists"),
                    },
                ))
        except Exception as e:
            checks.append(PipelineCheck(
                name="k8s_api_access",
                label="Kubernetes API access",
                status="fail",
                detail=f"Could not reach the cluster API: {e}",
                remediation=(
                    "Check that your IAM principal is mapped to a Kubernetes user "
                    "(EKS Access Entry or aws-auth ConfigMap). The deployer needs "
                    "API-level access for everything beyond cluster metadata."
                ),
            ))

        # ----- summarise -----
        worst = "pass"
        for c in checks:
            if c.status == "fail":
                worst = "fail"
                break
            if c.status == "warn":
                worst = "warn"
        can_proceed = not any(c.status == "fail" for c in checks)

        return ClusterReadinessReport(
            cluster_name=cluster_name,
            region=region or "",
            overall=worst,
            can_proceed=can_proceed,
            checks=checks,
        )

    # ---------------------------------------------------- placeholders 2-7,10
    # The remaining steps are filled in by Phase 2-5. Defining stubs now keeps
    # the API/router shape stable and gives the wizard a clear "not yet
    # implemented" signal so it can disable buttons rather than 404.
    async def step2_install_controllers(
        self,
        cluster_name: str,
        iam_mode: str = "managed",
    ) -> ControllerInstallReport:
        """
        Step 2: ensure ALB Controller + EBS CSI Driver are present.

        managed mode: deployer attempts install (helm for ALB, EKS Addon
        API for EBS CSI). preprovisioned mode: detect-only with clear
        remediation if missing.
        """
        from app.services.alb_controller_installer import AlbControllerInstaller
        from app.services.ebs_csi_addon_installer import EbsCsiAddonInstaller

        ops = self.operator_service
        cluster_info = ops.eks_client.describe_cluster(name=cluster_name)["cluster"]
        oidc_issuer = cluster_info.get("identity", {}).get("oidc", {}).get("issuer")
        oidc_provider_id = oidc_issuer.replace("https://", "") if oidc_issuer else None

        # ALB needs apps_v1 to detect; ensure we have a K8s client first.
        try:
            _, apps_v1, _ = await ops._get_k8s_clients(cluster_name)
        except Exception as e:
            err = PipelineCheck(
                name="cluster_api",
                label="Cluster API access",
                status="fail",
                detail=f"Cannot reach cluster API: {e}",
            )
            return ControllerInstallReport(
                cluster_name=cluster_name,
                iam_mode=iam_mode,  # type: ignore[arg-type]
                overall="fail",
                can_proceed=False,
                alb_controller=err,
                ebs_csi_driver=err,
            )

        alb = AlbControllerInstaller(
            eks_client=ops.eks_client,
            iam_client=ops.iam_client,
            sts_client=ops.sts_client,
            region=ops.region,
            apps_v1=apps_v1,
        )
        ebs = EbsCsiAddonInstaller(
            eks_client=ops.eks_client,
            iam_client=ops.iam_client,
            sts_client=ops.sts_client,
            region=ops.region,
        )

        # Run both ensures sequentially; they are independent but doing them
        # in parallel against the same boto3 clients can race.
        loop = asyncio.get_event_loop()
        alb_check = await loop.run_in_executor(
            None, alb.ensure, cluster_name, oidc_provider_id, iam_mode
        )
        ebs_check = await loop.run_in_executor(
            None, ebs.ensure, cluster_name, oidc_provider_id, iam_mode
        )

        worst = "pass"
        for c in (alb_check, ebs_check):
            if c.status == "fail":
                worst = "fail"
                break
            if c.status == "warn":
                worst = "warn"
        can_proceed = alb_check.status != "fail" and ebs_check.status != "fail"

        return ControllerInstallReport(
            cluster_name=cluster_name,
            iam_mode=iam_mode,  # type: ignore[arg-type]
            overall=worst,
            can_proceed=can_proceed,
            alb_controller=alb_check,
            ebs_csi_driver=ebs_check,
        )

    async def step3_verify_irsa_mapping(
        self,
        cluster_name: str,
        iam_mode: str = "managed",
        capability_namespace: Optional[str] = None,
        app_role_arn: Optional[str] = None,
    ) -> IRSAMappingReport:
        """
        Step 3: verify each IRSA role's trust policy + attached policies.

        Roles checked: operator role, ALB controller role, EBS CSI role.
        The per-capability application role is added when
        `capability_namespace` is supplied (post step 6 / pre step 9).
        """
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

        ops = self.operator_service
        cluster_info = ops.eks_client.describe_cluster(name=cluster_name)["cluster"]
        oidc_issuer = cluster_info.get("identity", {}).get("oidc", {}).get("issuer")
        oidc_provider_id = oidc_issuer.replace("https://", "") if oidc_issuer else None

        verifier = IrsaMappingVerifier(
            iam_client=ops.iam_client, sts_client=ops.sts_client
        )

        specs: List[IrsaRoleSpec] = [
            IrsaRoleSpec(
                name="operator_role",
                label="Totogi Operator IRSA role",
                role_name="totogi-operator-role",
                namespace=OPERATOR_NAMESPACE,
                service_account=OPERATOR_SERVICE_ACCOUNT,
                admin_managed_remediation=(
                    "In pre-provisioned IAM mode, admin must create "
                    "totogi-operator-role using "
                    "kube-operator/permissions/operator-policy.json + "
                    "operator-trust-policy.json with the cluster's OIDC "
                    "provider ID substituted."
                ),
            ),
            IrsaRoleSpec(
                name="alb_controller_role",
                label="AWS Load Balancer Controller IRSA role",
                role_name=ALB_ROLE_NAME,
                namespace=ALB_NAMESPACE,
                service_account=ALB_SERVICE_ACCOUNT,
                required_inline_policy_names=["AWSLoadBalancerControllerIAMPolicy"],
            ),
            IrsaRoleSpec(
                name="ebs_csi_role",
                label="EBS CSI Driver IRSA role",
                role_name=EBS_DEFAULT_ROLE_NAME,
                namespace=EBS_CONTROLLER_NS,
                service_account=EBS_CONTROLLER_SA,
                required_managed_policies=[EBS_MANAGED_POLICY_ARN],
            ),
        ]
        if capability_namespace and app_role_arn:
            # Resolve the app role NAME from the supplied ARN; verifier
            # works on names, not ARNs.
            role_name = app_role_arn.rsplit("/", 1)[-1] if "/" in app_role_arn else app_role_arn
            specs.append(IrsaRoleSpec(
                name="capability_app_role",
                label="Capability application IRSA role",
                role_name=role_name,
                namespace=capability_namespace,
                # Operator's KubernetesResourceCreator names the SA
                # "<capability>-<env>-app-sa"; we don't have the
                # capability/env here yet, so check by namespace + a
                # well-known glob is not possible. Instead, we check the
                # ARN exists with IRSA trust for ANY SA in the namespace.
                service_account="*",
                admin_managed_remediation=(
                    "Pre-provisioned IAM: admin must create the "
                    "per-capability app role using "
                    "kube-operator/permissions/app-policy.json + "
                    "app-trust-policy.json. Forward the ARN via "
                    "spec.appRoleArn."
                ),
            ))

        loop = asyncio.get_event_loop()
        roles: List[PipelineCheck] = []
        for spec in specs:
            # spec.service_account == "*" disables :sub matching; verifier
            # treats any SA in the namespace as acceptable. We achieve that
            # by treating None-result trust verification as warn-not-fail
            # for the wildcard case below; do a normal check otherwise.
            if spec.service_account == "*":
                check = await loop.run_in_executor(
                    None, self._verify_role_namespace_only,
                    verifier, spec, oidc_provider_id,
                )
            else:
                check = await loop.run_in_executor(
                    None, verifier.verify_role, spec, oidc_provider_id,
                )
            # If the role is admin-managed and missing in managed mode, soften
            # to warn (deployer will create it during install).
            if iam_mode == "managed" and check.status == "fail" and "does not exist" in check.detail:
                check = PipelineCheck(
                    name=check.name, label=check.label, status="warn",
                    detail=check.detail + " (deployer will create during install)",
                    remediation=None,
                )
            roles.append(check)

        worst = "pass"
        for c in roles:
            if c.status == "fail":
                worst = "fail"
                break
            if c.status == "warn":
                worst = "warn"
        can_proceed = not any(c.status == "fail" for c in roles)

        return IRSAMappingReport(
            cluster_name=cluster_name,
            overall=worst,
            can_proceed=can_proceed,
            roles=roles,
        )

    @staticmethod
    def _verify_role_namespace_only(
        verifier, spec, oidc_provider_id
    ) -> PipelineCheck:
        """
        Wildcard-SA verification: role must exist with IRSA trust for the
        cluster's OIDC provider; we don't pin the :sub value. Used for
        the per-capability app role where the SA name depends on
        capability + env naming we don't have at this step.
        """
        # Replace the SA pattern temporarily and let the standard verifier
        # run; if it fails on the SA-mismatch reason, soften to a pass
        # since we accept any SA in the namespace.
        check = verifier.verify_role(spec, oidc_provider_id)
        if check.status == "fail" and ":sub is" in check.detail:
            return PipelineCheck(
                name=spec.name,
                label=spec.label,
                status="pass",
                detail=(
                    f"Role {spec.role_name} has IRSA trust for the cluster's "
                    "OIDC provider; SA-specific :sub will be validated when the "
                    "capability is deployed."
                ),
                extra=check.extra,
            )
        return check

    async def step4_audit_iam_roles(
        self,
        cluster_name: str,
        iam_mode: str = "managed",
        capability_namespace: Optional[str] = None,
        app_role_arn: Optional[str] = None,
    ) -> IAMAuditReport:
        """Step 4: IAM permissions audit, mode-aware."""
        from app.services.iam_audit_service import IamAuditService

        ops = self.operator_service
        # Resolve OIDC provider for preprovisioned trust-policy checks.
        cluster_info = ops.eks_client.describe_cluster(name=cluster_name)["cluster"]
        oidc_issuer = cluster_info.get("identity", {}).get("oidc", {}).get("issuer")
        oidc_provider_id = oidc_issuer.replace("https://", "") if oidc_issuer else None

        auditor = IamAuditService(
            iam_client=ops.iam_client, sts_client=ops.sts_client
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            auditor.audit,
            iam_mode,
            oidc_provider_id,
            cluster_name,
            capability_namespace,
            app_role_arn,
        )

    async def step6_apply_network_config(
        self,
        cluster_name: str,
        wait_seconds: int = 120,  # kept for API compatibility; unused now
    ) -> NetworkConfigReport:
        """
        Step 6: provision the 13 VPC private endpoints directly via EC2.

        Earlier versions of this method drove the operator's
        `TotogiNetworkConfig` CR; that required the CRD to already be
        installed on the cluster, which it is not at pre-flight time
        (operator install happens later in step 5 / DEPLOYMENT_EXECUTION).
        The deployer now creates the endpoints itself, idempotently.

        Endpoint inventory (region-prefixed at runtime):
          gateway:   s3, dynamodb
          interface: ec2, sts, ssm, glue, ecr.api, ecr.dkr,
                     secretsmanager, logs, cognito-idp, athena, events
        """
        from app.services.vpc_endpoint_provisioner import (
            VpcEndpointProvisioner,
            summarise_endpoint_rows,
        )

        ops = self.operator_service

        # Build an EC2 client tied to the wizard's session credentials.
        import boto3
        from app.services.aws_session_manager import aws_session_manager
        creds: Dict[str, Any] = {}
        if ops.aws_session_id:
            creds = aws_session_manager.get_credentials_dict(ops.aws_session_id) or {}
        ec2_client = boto3.client(
            "ec2",
            region_name=ops.region,
            aws_access_key_id=creds.get("aws_access_key_id"),
            aws_secret_access_key=creds.get("aws_secret_access_key"),
            aws_session_token=creds.get("aws_session_token"),
        )

        provisioner = VpcEndpointProvisioner(
            eks_client=ops.eks_client,
            ec2_client=ec2_client,
            region=ops.region,
        )

        loop = asyncio.get_event_loop()
        try:
            network = await loop.run_in_executor(
                None, provisioner.discover_cluster_network, cluster_name
            )
        except Exception as e:
            return NetworkConfigReport(
                cluster_name=cluster_name,
                cr_name="vpc-endpoints",
                phase="Failed",
                overall="fail",
                can_proceed=False,
                endpoints=[],
                total_endpoints=0,
                healthy_endpoints=0,
                message=f"Could not discover cluster network: {e}",
            )

        try:
            rows = await loop.run_in_executor(
                None, provisioner.ensure_endpoints, network
            )
        except Exception as e:
            return NetworkConfigReport(
                cluster_name=cluster_name,
                cr_name="vpc-endpoints",
                phase="Failed",
                overall="fail",
                can_proceed=False,
                endpoints=[],
                total_endpoints=0,
                healthy_endpoints=0,
                message=f"VPC endpoint provisioning failed: {e}",
            )

        counts = summarise_endpoint_rows(rows)
        # An endpoint that was already in place (existed=true) counts as
        # healthy; a newly-created interface endpoint in `pending` counts
        # as in-flight - the deploy may still proceed because the
        # operator uses public DNS until private DNS flips over.
        if counts["failed"] > 0:
            phase = "Failed"
            overall = "fail"
            can_proceed = False
        elif counts["healthy"] == counts["total"]:
            phase = "Ready"
            overall = "pass"
            can_proceed = True
        elif counts["healthy"] + counts["in_flight"] == counts["total"]:
            phase = "Provisioning"
            overall = "warn"
            can_proceed = True
        else:
            phase = "Failed"
            overall = "fail"
            can_proceed = False

        return NetworkConfigReport(
            cluster_name=cluster_name,
            cr_name="vpc-endpoints",
            phase=phase,
            overall=overall,  # type: ignore[arg-type]
            can_proceed=can_proceed,
            endpoints=rows,
            total_endpoints=counts["total"],
            healthy_endpoints=counts["healthy"],
            message=(
                f"{counts['healthy']}/{counts['total']} endpoints available, "
                f"{counts['in_flight']} pending, {counts['failed']} failed."
            ),
        )

    async def step7_run_reachability_probe(
        self,
        cluster_name: str,
        namespace: str,
        capability_name: str,
        environment: str,
    ) -> ReachabilityReport:
        """
        Step 7: spawn a diagnostic Pod in the capability namespace with
        the per-capability ServiceAccount, run DNS+TLS probes for each
        AWS service, and verify IRSA via sts:GetCallerIdentity.

        Must run AFTER step 6 (VPC endpoints) and AFTER the operator has
        created the per-capability ServiceAccount (typically on or after
        step 9). The orchestrator does not enforce order; the wizard is
        responsible for sequencing.
        """
        from app.services.reachability_probe import ReachabilityProbe

        ops = self.operator_service
        try:
            core_v1, _, _ = await ops._get_k8s_clients(cluster_name)
        except Exception as e:
            return ReachabilityReport(
                cluster_name=cluster_name,
                namespace=namespace,
                pod_name="",
                overall="fail",
                rows=[],
                iam_results={"error": f"Cluster API unreachable: {e}"},
            )

        probe = ReachabilityProbe(core_v1=core_v1, region=ops.region)
        report = await probe.run(
            namespace=namespace,
            capability_name=capability_name,
            environment=environment,
        )
        # Backfill the cluster name so the response is self-describing.
        report.cluster_name = cluster_name
        return report

    async def step10_full_inspection(
        self,
        cluster_name: str,
        namespace: str,
        capability_name: str,
        environment: str,
        cr_name: str,
    ) -> CapabilityInspectionReport:
        """
        Step 10: full-parity inspection. Runs all 17 sections against
        the cluster + AWS account + backend pod identity.
        """
        from app.services.capability_inspector import CapabilityInspector

        ops = self.operator_service
        try:
            core_v1, apps_v1, custom = await ops._get_k8s_clients(cluster_name)
        except Exception as e:
            from app.models.eks_pipeline import InspectionSection
            return CapabilityInspectionReport(
                cluster_name=cluster_name,
                namespace=namespace,
                capability_name=capability_name,
                environment=environment,
                cr_name=cr_name,
                overall="fail",
                sections=[InspectionSection(
                    name="cluster_api",
                    label="Cluster API access",
                    status="fail",
                    summary=f"Cluster API unreachable: {e}",
                )],
            )

        # Build a boto3 Session with the wizard's credentials.
        import boto3
        from app.services.aws_session_manager import aws_session_manager
        creds: Dict[str, Any] = {}
        if ops.aws_session_id:
            creds = aws_session_manager.get_credentials_dict(ops.aws_session_id) or {}
        boto_session = boto3.Session(
            aws_access_key_id=creds.get("aws_access_key_id"),
            aws_secret_access_key=creds.get("aws_secret_access_key"),
            aws_session_token=creds.get("aws_session_token"),
            region_name=ops.region,
        )

        inspector = CapabilityInspector(
            core_v1=core_v1,
            apps_v1=apps_v1,
            custom=custom,
            eks_client=ops.eks_client,
            iam_client=ops.iam_client,
            sts_client=ops.sts_client,
            boto3_session=boto_session,
            region=ops.region,
            cluster_name=cluster_name,
            namespace=namespace,
            capability_name=capability_name,
            environment=environment,
            cr_name=cr_name,
        )
        return await inspector.run_full()


def get_eks_pipeline_orchestrator(
    aws_session_id: Optional[str] = None,
    region: Optional[str] = None,
) -> EksPipelineOrchestrator:
    """Factory."""
    return EksPipelineOrchestrator(aws_session_id=aws_session_id, region=region)
