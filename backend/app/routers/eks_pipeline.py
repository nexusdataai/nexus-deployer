"""
HTTP surface for the 10-step Pure-EKS deployment pipeline.

One endpoint per step under /api/eks/pipeline/. Phase 1 wires step 1
(cluster readiness); subsequent phases add the remaining endpoints.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.models.eks_pipeline import (
    CapabilityInspectionReport,
    ClusterReadinessReport,
    ControllerInstallReport,
    IAMAuditReport,
    IRSAMappingReport,
    NetworkConfigReport,
    ReachabilityReport,
)
from app.services.eks_pipeline_orchestrator import get_eks_pipeline_orchestrator


router = APIRouter(prefix="/api/eks/pipeline", tags=["eks-pipeline"])


@router.get(
    "/clusters/{cluster_name}/readiness",
    response_model=ClusterReadinessReport,
)
async def cluster_readiness(
    cluster_name: str,
    iam_mode: str = Query(
        "managed",
        description="'managed' (deployer creates IAM) or 'preprovisioned' (admin owns IAM).",
        pattern="^(managed|preprovisioned)$",
    ),
    aws_session_id: Optional[str] = Query(
        None, description="AWS session ID for authentication"
    ),
):
    """
    Step 1 of the pipeline: scan the target cluster for readiness.

    Ports the 10 useful checks from
    kube-operator/operator-nexus.sh:1559-2287:
    cluster ACTIVE + version, OIDC provider, operator IAM role
    (preprovisioned mode), authentication mode, EKS Access Entry,
    node groups + node IAM policies, ECR operator image, K8s API access,
    AWS Load Balancer Controller, Nexus AI Operator readiness.
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step1_cluster_readiness(
            cluster_name=cluster_name, iam_mode=iam_mode
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cluster readiness check failed: {e}",
        )


@router.post(
    "/clusters/{cluster_name}/controllers",
    response_model=ControllerInstallReport,
)
async def install_controllers(
    cluster_name: str,
    iam_mode: str = Query("managed", pattern="^(managed|preprovisioned)$"),
    aws_session_id: Optional[str] = Query(None),
):
    """
    Step 2: ensure ALB Controller + EBS CSI Driver are installed.

    `managed` mode: deployer attempts install via helm (ALB) and the EKS
    managed Addon API (EBS CSI). `preprovisioned` mode: detect-only with
    actionable remediation when missing.
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step2_install_controllers(
            cluster_name=cluster_name, iam_mode=iam_mode
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Controller install failed: {e}",
        )


@router.get(
    "/clusters/{cluster_name}/irsa",
    response_model=IRSAMappingReport,
)
async def verify_irsa_mapping(
    cluster_name: str,
    iam_mode: str = Query("managed", pattern="^(managed|preprovisioned)$"),
    capability_namespace: Optional[str] = Query(
        None,
        description="If supplied, the per-capability app role is also verified.",
    ),
    app_role_arn: Optional[str] = Query(
        None,
        description="Pre-provisioned application role ARN (for verification).",
    ),
    aws_session_id: Optional[str] = Query(None),
):
    """
    Step 3: verify each IRSA role's trust policy + attached policies.
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step3_verify_irsa_mapping(
            cluster_name=cluster_name,
            iam_mode=iam_mode,
            capability_namespace=capability_namespace,
            app_role_arn=app_role_arn,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"IRSA mapping verification failed: {e}",
        )


@router.get(
    "/clusters/{cluster_name}/iam-audit",
    response_model=IAMAuditReport,
)
async def audit_iam(
    cluster_name: str,
    iam_mode: str = Query("managed", pattern="^(managed|preprovisioned)$"),
    capability_namespace: Optional[str] = Query(None),
    app_role_arn: Optional[str] = Query(None),
    aws_session_id: Optional[str] = Query(None),
):
    """
    Step 4: IAM permissions audit.

    `managed` mode: probes whether the deployer principal has the IAM /
    EKS mutating actions the pipeline needs (via SimulatePrincipalPolicy).
    `preprovisioned` mode: confirms the four expected roles exist with
    correct trust + attached policies.
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step4_audit_iam_roles(
            cluster_name=cluster_name,
            iam_mode=iam_mode,
            capability_namespace=capability_namespace,
            app_role_arn=app_role_arn,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"IAM audit failed: {e}",
        )


@router.post(
    "/clusters/{cluster_name}/network-config",
    response_model=NetworkConfigReport,
)
async def apply_network_config(
    cluster_name: str,
    wait_seconds: int = Query(120, ge=0, le=900),
    aws_session_id: Optional[str] = Query(None),
):
    """
    Step 6: provision VPC private endpoints by applying the cluster-scoped
    NexusNetworkConfig CR named 'vpc-endpoints'. The operator's existing
    VPCEndpointProvisioner does the EC2 work.
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step6_apply_network_config(
            cluster_name=cluster_name, wait_seconds=wait_seconds
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Network config apply failed: {e}",
        )


@router.post(
    "/clusters/{cluster_name}/reachability",
    response_model=ReachabilityReport,
)
async def run_reachability_probe(
    cluster_name: str,
    namespace: str = Query(..., description="Capability namespace"),
    capability_name: str = Query(..., description="Canonical (DNS-safe) capability id"),
    environment: str = Query(..., description="dev/test/stage/prod"),
    aws_session_id: Optional[str] = Query(None),
):
    """
    Step 7: in-cluster DNS + TLS probe per AWS service, executed inside
    a one-shot Pod in the capability namespace using the per-capability
    ServiceAccount (so IRSA reflects what real workloads see).
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step7_run_reachability_probe(
            cluster_name=cluster_name,
            namespace=namespace,
            capability_name=capability_name,
            environment=environment,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reachability probe failed: {e}",
        )


@router.get(
    "/clusters/{cluster_name}/capability/{cr_name}/inspect",
    response_model=CapabilityInspectionReport,
)
async def inspect_capability(
    cluster_name: str,
    cr_name: str,
    namespace: str = Query(...),
    capability_name: str = Query(..., description="Canonical (DNS-safe) capability id"),
    environment: str = Query(...),
    aws_session_id: Optional[str] = Query(None),
):
    """
    Step 10: full-parity capability inspection (17 sections, mirroring
    kube-operator/inspect-capability.sh). Returns a single aggregated
    report; the wizard's InspectCapability tab renders one collapsible
    pane per section.
    """
    try:
        orchestrator = get_eks_pipeline_orchestrator(aws_session_id=aws_session_id)
        return await orchestrator.step10_full_inspection(
            cluster_name=cluster_name,
            namespace=namespace,
            capability_name=capability_name,
            environment=environment,
            cr_name=cr_name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Capability inspection failed: {e}",
        )
