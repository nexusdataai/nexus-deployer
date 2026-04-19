"""
EKS Service for cluster discovery and Kubernetes API interactions.

Feature: pure-eks-deployment
Requirements: 2.2, 2.3, 3.1, 3.9
"""
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from app.services.aws_session_manager import aws_session_manager
from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

logger = logging.getLogger(__name__)


@dataclass
class EKSClusterInfo:
    """EKS cluster information."""
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
    tags: Dict[str, str] = field(default_factory=dict)
    node_count: Optional[int] = None
    operator_status: Optional[str] = None
    operator_version: Optional[str] = None


@dataclass
class EKSNamespaceInfo:
    """Kubernetes namespace information."""
    name: str
    status: str
    created_at: str
    labels: Dict[str, str] = field(default_factory=dict)


class EKSService:
    """Service for EKS cluster discovery and management."""
    
    OPERATOR_NAMESPACE = "totogi-system"
    OPERATOR_DEPLOYMENT_NAME = "totogi-operator"
    
    def __init__(
        self,
        region: str,
        aws_session_id: Optional[str] = None,
        endpoint_url: Optional[str] = None
    ):
        """
        Initialize the EKS service.
        
        Args:
            region: AWS region
            aws_session_id: Optional session ID for authenticated requests
            endpoint_url: Optional endpoint URL for LocalStack
        """
        self.region = region
        self.aws_session_id = aws_session_id
        self.endpoint_url = endpoint_url
        
        # Initialize boto3 clients
        self._init_clients()
    
    def _init_clients(self):
        """Initialize boto3 clients with session credentials if available."""
        client_kwargs = {"region_name": self.region}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url
        
        if self.aws_session_id:
            # Get credentials dict from session manager
            creds = aws_session_manager.get_credentials_dict(self.aws_session_id)
            if creds:
                # Create a boto3 session with the credentials
                boto_session = boto3.Session(
                    aws_access_key_id=creds.get("aws_access_key_id"),
                    aws_secret_access_key=creds.get("aws_secret_access_key"),
                    aws_session_token=creds.get("aws_session_token"),
                    region_name=creds.get("region_name") or self.region
                )
                self.eks_client = boto_session.client(
                    "eks", **merge_vpc_boto3_kwargs("eks", self.region, dict(client_kwargs))
                )
                self.sts_client = boto_session.client(
                    "sts", **merge_vpc_boto3_kwargs("sts", self.region, dict(client_kwargs))
                )
                logger.info(f"Initialized EKS client with session {self.aws_session_id} in region {self.region}")
            else:
                logger.warning(f"Session {self.aws_session_id} not found, using default credentials")
                self.eks_client = boto3.client(
                    "eks", **merge_vpc_boto3_kwargs("eks", self.region, dict(client_kwargs))
                )
                self.sts_client = boto3.client(
                    "sts", **merge_vpc_boto3_kwargs("sts", self.region, dict(client_kwargs))
                )
        else:
            logger.info(f"No session ID provided, using default credentials for region {self.region}")
            self.eks_client = boto3.client(
                "eks", **merge_vpc_boto3_kwargs("eks", self.region, dict(client_kwargs))
            )
            self.sts_client = boto3.client(
                "sts", **merge_vpc_boto3_kwargs("sts", self.region, dict(client_kwargs))
            )
    
    async def list_clusters(self) -> List[EKSClusterInfo]:
        """
        List all EKS clusters in the region.
        
        Returns:
            List of EKSClusterInfo objects
        """
        try:
            logger.info(f"Listing EKS clusters in region {self.region}")
            clusters = []
            paginator = self.eks_client.get_paginator("list_clusters")
            
            for page in paginator.paginate():
                cluster_names = page.get("clusters", [])
                logger.info(f"Found cluster names: {cluster_names}")
                for cluster_name in cluster_names:
                    try:
                        cluster_info = await self.get_cluster_details(cluster_name)
                        if cluster_info:
                            clusters.append(cluster_info)
                            logger.info(f"Added cluster: {cluster_name} (status: {cluster_info.status})")
                    except Exception as e:
                        logger.warning(f"Failed to get details for cluster {cluster_name}: {e}")
                        continue
            
            logger.info(f"Total clusters found: {len(clusters)}")
            return clusters
        except ClientError as e:
            logger.error(f"Failed to list EKS clusters: {e}")
            raise
    
    async def get_cluster_details(self, cluster_name: str) -> Optional[EKSClusterInfo]:
        """
        Get detailed information about a specific cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
            
        Returns:
            EKSClusterInfo or None if not found
        """
        try:
            response = self.eks_client.describe_cluster(name=cluster_name)
            cluster = response.get("cluster", {})
            
            # Get node count from nodegroups
            node_count = await self._get_node_count(cluster_name)
            
            # Check operator status
            operator_status = await self._check_operator_installed(cluster_name)
            
            return EKSClusterInfo(
                name=cluster.get("name", ""),
                arn=cluster.get("arn", ""),
                version=cluster.get("version", ""),
                status=cluster.get("status", ""),
                endpoint=cluster.get("endpoint", ""),
                role_arn=cluster.get("roleArn", ""),
                vpc_id=cluster.get("resourcesVpcConfig", {}).get("vpcId", ""),
                subnet_ids=cluster.get("resourcesVpcConfig", {}).get("subnetIds", []),
                security_group_ids=cluster.get("resourcesVpcConfig", {}).get("securityGroupIds", []),
                created_at=cluster.get("createdAt", datetime.utcnow()).isoformat() if cluster.get("createdAt") else "",
                platform_version=cluster.get("platformVersion", ""),
                tags=cluster.get("tags", {}),
                node_count=node_count,
                operator_status=operator_status.get("status", "unknown"),
                operator_version=operator_status.get("version")
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return None
            logger.error(f"Failed to get cluster details for {cluster_name}: {e}")
            raise

    async def _get_node_count(self, cluster_name: str) -> Optional[int]:
        """Get total node count across all nodegroups."""
        try:
            total_nodes = 0
            paginator = self.eks_client.get_paginator("list_nodegroups")
            
            for page in paginator.paginate(clusterName=cluster_name):
                for nodegroup_name in page.get("nodegroups", []):
                    try:
                        ng_response = self.eks_client.describe_nodegroup(
                            clusterName=cluster_name,
                            nodegroupName=nodegroup_name
                        )
                        scaling = ng_response.get("nodegroup", {}).get("scalingConfig", {})
                        total_nodes += scaling.get("desiredSize", 0)
                    except ClientError:
                        continue
            
            return total_nodes if total_nodes > 0 else None
        except ClientError as e:
            logger.warning(f"Failed to get node count for {cluster_name}: {e}")
            return None
    
    async def _check_operator_installed(self, cluster_name: str) -> Dict[str, Any]:
        """
        Check if the Totogi Operator is installed on the cluster.
        
        This is a placeholder that returns not_installed by default.
        Full implementation requires Kubernetes API access.
        """
        # TODO: Implement actual Kubernetes API check
        # For now, return not_installed as default
        return {
            "installed": False,
            "status": "not_installed",
            "version": None,
            "namespace": self.OPERATOR_NAMESPACE
        }
    
    async def check_operator_status(self, cluster_name: str) -> Dict[str, Any]:
        """
        Check the Totogi Operator installation status.
        
        Args:
            cluster_name: Name of the EKS cluster
            
        Returns:
            Dict with installed, status, version, namespace
        """
        return await self._check_operator_installed(cluster_name)
    
    async def list_namespaces(self, cluster_name: str) -> List[EKSNamespaceInfo]:
        """
        List all namespaces in the cluster.
        
        This is a placeholder that returns common namespaces.
        Full implementation requires Kubernetes API access.
        
        Args:
            cluster_name: Name of the EKS cluster
            
        Returns:
            List of EKSNamespaceInfo objects
        """
        # TODO: Implement actual Kubernetes API call
        # For now, return common default namespaces
        default_namespaces = [
            EKSNamespaceInfo(
                name="default",
                status="Active",
                created_at=datetime.utcnow().isoformat(),
                labels={}
            ),
            EKSNamespaceInfo(
                name="kube-system",
                status="Active",
                created_at=datetime.utcnow().isoformat(),
                labels={"kubernetes.io/metadata.name": "kube-system"}
            ),
            EKSNamespaceInfo(
                name="kube-public",
                status="Active",
                created_at=datetime.utcnow().isoformat(),
                labels={}
            ),
        ]
        return default_namespaces
    
    async def deploy_operator(
        self,
        cluster_name: str,
        operator_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Deploy the Totogi Operator to the cluster.
        
        Args:
            cluster_name: Name of the EKS cluster
            operator_version: Optional specific version to deploy
            
        Returns:
            Dict with success, message, version, namespace
        """
        from app.services.operator_deployment_service import get_operator_deployment_service
        
        service = get_operator_deployment_service(
            aws_session_id=self.aws_session_id,
            region=self.region
        )
        return await service.deploy_operator(cluster_name, operator_version)
    
    async def deploy_capability(
        self,
        cluster_name: str,
        capability_name: str,
        capability_version: str,
        environment: str,
        namespace: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Deploy a capability by creating a TotogiCapability CR.
        
        Args:
            cluster_name: Name of the EKS cluster
            capability_name: Name of the capability to deploy
            capability_version: Version of the capability
            environment: Target environment (dev, staging, prod)
            namespace: Kubernetes namespace for deployment
            config: Additional configuration options
            
        Returns:
            Dict with success, cr_name, message
        """
        from app.services.operator_deployment_service import get_operator_deployment_service
        
        service = get_operator_deployment_service(
            aws_session_id=self.aws_session_id,
            region=self.region
        )
        return await service.create_capability_cr(
            cluster_name=cluster_name,
            capability_name=capability_name,
            capability_version=capability_version,
            environment=environment,
            namespace=namespace,
            config=config
        )
    
    async def get_capability_status(
        self,
        cluster_name: str,
        cr_name: str,
        namespace: str
    ) -> Dict[str, Any]:
        """
        Get the status of a deployed capability.
        
        Args:
            cluster_name: Name of the EKS cluster
            cr_name: Name of the TotogiCapability CR
            namespace: Namespace where the CR is deployed
            
        Returns:
            Dict with phase, message, urls, resources
        """
        from app.services.operator_deployment_service import get_operator_deployment_service
        
        service = get_operator_deployment_service(
            aws_session_id=self.aws_session_id,
            region=self.region
        )
        return await service.get_capability_status(cluster_name, cr_name, namespace)


# Singleton instance cache
_eks_service_cache: Dict[str, EKSService] = {}


def get_eks_service(
    aws_session_id: Optional[str] = None,
    region: Optional[str] = None
) -> EKSService:
    """
    Get or create an EKS service instance.
    
    Args:
        aws_session_id: Optional AWS session ID
        region: Optional region override
        
    Returns:
        EKSService instance
    """
    import os
    
    # Determine region from session or environment
    if not region:
        if aws_session_id:
            # Get region from session credentials
            creds = aws_session_manager.get_credentials_dict(aws_session_id)
            if creds:
                region = creds.get("region_name")
            
            # Also check session info directly
            if not region:
                session_info = aws_session_manager.get_session(aws_session_id)
                if session_info:
                    region = session_info.get("region")
        
        if not region:
            region = os.environ.get("AWS_REGION", "us-east-1")
    
    logger.info(f"Creating EKS service for session={aws_session_id}, region={region}")
    
    # Create cache key
    cache_key = f"{aws_session_id or 'default'}:{region}"
    
    # Don't cache when using session credentials (credentials may change)
    if aws_session_id:
        return EKSService(
            region=region,
            aws_session_id=aws_session_id
        )
    
    if cache_key not in _eks_service_cache:
        _eks_service_cache[cache_key] = EKSService(
            region=region,
            aws_session_id=aws_session_id
        )
    
    return _eks_service_cache[cache_key]
