"""
API router for EKS cluster discovery and operator management.

Feature: pure-eks-deployment
Requirements: 2.2, 2.3, 3.1, 3.9, 4.1
"""
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.eks_service import get_eks_service


router = APIRouter(prefix="/api/eks", tags=["eks"])


# Pydantic models for API responses
class EKSClusterModel(BaseModel):
    """Pydantic model for EKS cluster information."""
    name: str
    arn: str
    version: str
    status: str
    endpoint: str
    role_arn: str
    vpc_id: str
    subnet_ids: List[str]
    security_group_ids: List[str]
    created_at: str
    platform_version: str
    tags: Dict[str, str] = Field(default_factory=dict)
    node_count: Optional[int] = None
    operator_status: Optional[str] = None
    operator_version: Optional[str] = None
    
    class Config:
        from_attributes = True


class EKSNamespaceModel(BaseModel):
    """Pydantic model for Kubernetes namespace information."""
    name: str
    status: str
    created_at: str
    labels: Dict[str, str] = Field(default_factory=dict)
    
    class Config:
        from_attributes = True


# Request/Response Models
class EKSClusterListResponse(BaseModel):
    """Response for listing EKS clusters."""
    clusters: List[EKSClusterModel]
    region: str


class EKSClusterDetailResponse(BaseModel):
    """Response for cluster details."""
    cluster: EKSClusterModel


class OperatorStatusResponse(BaseModel):
    """Response for operator status check."""
    cluster_name: str
    operator_installed: bool
    operator_status: str  # not_installed, installing, installed, failed, unknown
    operator_version: Optional[str] = None
    namespace: str = "nexus-system"


class EKSNamespaceListResponse(BaseModel):
    """Response for listing namespaces."""
    namespaces: List[EKSNamespaceModel]
    cluster_name: str


class DeployOperatorRequest(BaseModel):
    """Request to deploy the Totogi Operator."""
    cluster_name: str
    operator_version: Optional[str] = None


class DeployOperatorResponse(BaseModel):
    """Response for operator deployment."""
    success: bool
    message: str
    operator_version: str
    namespace: str


class DeployCapabilityRequest(BaseModel):
    """Request to deploy a capability via TotogiCapability CR."""
    cluster_name: str
    capability_name: str
    capability_version: str
    environment: str
    namespace: str
    config: dict = Field(default_factory=dict)


class DeployCapabilityResponse(BaseModel):
    """Response for capability deployment."""
    success: bool
    cr_name: str
    namespace: str
    message: str


class ResourceStatus(BaseModel):
    """Status of a provisioned resource."""
    type: str
    name: str
    status: str


class CapabilityStatusResponse(BaseModel):
    """Response for capability status."""
    cr_name: str
    namespace: str
    phase: str
    message: str
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None
    resources: List[ResourceStatus] = Field(default_factory=list)
    last_reconcile_time: Optional[str] = None


# API Endpoints
@router.get("/clusters", response_model=EKSClusterListResponse)
async def list_clusters(
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication"),
    region: Optional[str] = Query(None, description="AWS region override")
):
    """
    List all EKS clusters in the configured region.
    
    Returns cluster name, version, status, node count, and operator installation status.
    
    Requirements: 2.2, 2.3
    """
    try:
        import logging
        from dataclasses import asdict
        logger = logging.getLogger(__name__)
        logger.info(f"Listing EKS clusters with session_id={aws_session_id}, region={region}")
        
        service = get_eks_service(aws_session_id, region)
        clusters = await service.list_clusters()
        
        logger.info(f"Found {len(clusters)} EKS clusters in region {service.region}")
        
        # Convert dataclasses to dicts for Pydantic serialization
        cluster_dicts = [asdict(c) for c in clusters]
        
        return EKSClusterListResponse(
            clusters=cluster_dicts,
            region=service.region
        )
    except Exception as e:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to list EKS clusters: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list EKS clusters: {str(e)}"
        )


@router.get("/clusters/{cluster_name}", response_model=EKSClusterDetailResponse)
async def get_cluster_details(
    cluster_name: str,
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication")
):
    """
    Get detailed information about a specific EKS cluster.
    
    Requirements: 2.2, 2.3
    """
    try:
        from dataclasses import asdict
        service = get_eks_service(aws_session_id)
        cluster = await service.get_cluster_details(cluster_name)
        if not cluster:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cluster '{cluster_name}' not found"
            )
        return EKSClusterDetailResponse(cluster=asdict(cluster))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cluster details: {str(e)}"
        )


@router.get("/clusters/{cluster_name}/operator-status", response_model=OperatorStatusResponse)
async def check_operator_status(
    cluster_name: str,
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication")
):
    """
    Check if the Totogi Operator is installed on the cluster.
    
    Requirements: 3.9
    """
    try:
        service = get_eks_service(aws_session_id)
        status_info = await service.check_operator_status(cluster_name)
        return OperatorStatusResponse(
            cluster_name=cluster_name,
            operator_installed=status_info.get("installed", False),
            operator_status=status_info.get("status", "unknown"),
            operator_version=status_info.get("version"),
            namespace=status_info.get("namespace", "nexus-system")
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check operator status: {str(e)}"
        )


@router.get("/clusters/{cluster_name}/namespaces", response_model=EKSNamespaceListResponse)
async def list_namespaces(
    cluster_name: str,
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication")
):
    """
    List all namespaces in the EKS cluster.
    
    Requirements: 2.3
    """
    try:
        from dataclasses import asdict
        service = get_eks_service(aws_session_id)
        namespaces = await service.list_namespaces(cluster_name)
        namespace_dicts = [asdict(ns) for ns in namespaces]
        return EKSNamespaceListResponse(
            namespaces=namespace_dicts,
            cluster_name=cluster_name
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list namespaces: {str(e)}"
        )


@router.post("/clusters/{cluster_name}/deploy-operator", response_model=DeployOperatorResponse)
async def deploy_operator(
    cluster_name: str,
    request: DeployOperatorRequest,
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication")
):
    """
    Deploy the Totogi Operator to the EKS cluster.
    
    Creates the nexus-system namespace, IAM role with IRSA, and deploys the operator.
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
    """
    try:
        service = get_eks_service(aws_session_id)
        result = await service.deploy_operator(
            cluster_name=cluster_name,
            operator_version=request.operator_version
        )
        return DeployOperatorResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            operator_version=result.get("version", "latest"),
            namespace=result.get("namespace", "nexus-system")
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deploy operator: {str(e)}"
        )


@router.post("/clusters/{cluster_name}/deploy-capability", response_model=DeployCapabilityResponse)
async def deploy_capability(
    cluster_name: str,
    request: DeployCapabilityRequest,
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication")
):
    """
    Deploy a capability by creating a TotogiCapability Custom Resource.
    
    The operator will reconcile the CR and provision all required resources.
    
    Requirements: 4.1, 4.2
    """
    try:
        service = get_eks_service(aws_session_id)
        result = await service.deploy_capability(
            cluster_name=cluster_name,
            capability_name=request.capability_name,
            capability_version=request.capability_version,
            environment=request.environment,
            namespace=request.namespace,
            config=request.config
        )
        return DeployCapabilityResponse(
            success=result.get("success", False),
            cr_name=result.get("cr_name", ""),
            namespace=request.namespace,
            message=result.get("message", "")
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to deploy capability: {str(e)}"
        )


@router.get("/clusters/{cluster_name}/capability/{cr_name}/status", response_model=CapabilityStatusResponse)
async def get_capability_status(
    cluster_name: str,
    cr_name: str,
    namespace: str = Query(..., description="Namespace where the capability is deployed"),
    aws_session_id: Optional[str] = Query(None, description="AWS session ID for authentication")
):
    """
    Get the status of a deployed capability.
    
    Returns the CR status including phase, URLs, and provisioned resources.
    
    Requirements: 8.1, 8.2
    """
    try:
        service = get_eks_service(aws_session_id)
        status_info = await service.get_capability_status(
            cluster_name=cluster_name,
            cr_name=cr_name,
            namespace=namespace
        )
        return CapabilityStatusResponse(
            cr_name=cr_name,
            namespace=namespace,
            phase=status_info.get("phase", "Unknown"),
            message=status_info.get("message", ""),
            frontend_url=status_info.get("frontend_url"),
            backend_url=status_info.get("backend_url"),
            resources=[
                ResourceStatus(type=r["type"], name=r["name"], status=r["status"])
                for r in status_info.get("resources", [])
            ],
            last_reconcile_time=status_info.get("last_reconcile_time")
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get capability status: {str(e)}"
        )
