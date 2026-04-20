"""
EKS Utility Functions for OIDC Provider Discovery.

Feature: pure-eks-deployment
Requirements: 5.2, 5.3
"""
import logging
import os
from typing import Optional, Tuple

from botocore.exceptions import ClientError

from .aws_vpc_endpoints import vpc_boto3_client

logger = logging.getLogger(__name__)


def discover_oidc_provider(cluster_name: str, region: str) -> Optional[str]:
    """
    Discover the OIDC provider from an EKS cluster.
    
    This is essential for creating IRSA (IAM Roles for Service Accounts).
    
    Args:
        cluster_name: Name of the EKS cluster
        region: AWS region where the cluster is located
        
    Returns:
        OIDC provider identifier (e.g., "oidc.eks.ap-southeast-1.amazonaws.com/id/XXXXX")
        or None if discovery fails
    """
    try:
        eks_client = vpc_boto3_client("eks", region_name=region)
        cluster_info = eks_client.describe_cluster(name=cluster_name)
        
        oidc_issuer = cluster_info["cluster"]["identity"]["oidc"]["issuer"]
        # Remove 'https://' prefix to get the provider identifier
        oidc_provider = oidc_issuer.replace("https://", "")
        
        logger.info(f"Discovered OIDC provider for cluster {cluster_name}: {oidc_provider}")
        return oidc_provider
        
    except ClientError as e:
        logger.warning(f"Failed to discover OIDC provider: {e}")
        return None
    except KeyError:
        logger.warning(f"Cluster {cluster_name} does not have OIDC configured")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error discovering OIDC provider: {e}")
        return None


def verify_oidc_provider_exists(oidc_provider: str, account_id: str, region: str) -> bool:
    """
    Verify that the OIDC provider is registered in IAM.
    
    The OIDC provider must be registered in IAM before IRSA can work.
    
    Args:
        oidc_provider: OIDC provider identifier
        account_id: AWS account ID
        region: AWS region
        
    Returns:
        True if the OIDC provider exists in IAM, False otherwise
    """
    try:
        iam_client = vpc_boto3_client("iam", region_name=region)
        oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider}"
        
        iam_client.get_open_id_connect_provider(OpenIDConnectProviderArn=oidc_arn)
        logger.info(f"Verified OIDC provider exists in IAM: {oidc_arn}")
        return True
        
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            logger.warning(f"OIDC provider not found in IAM: {oidc_provider}")
            logger.warning("Run: eksctl utils associate-iam-oidc-provider --cluster <cluster-name> --approve")
            return False
        logger.warning(f"Error checking OIDC provider: {e}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error verifying OIDC provider: {e}")
        return False


def get_oidc_provider_for_irsa(region: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Get OIDC provider and cluster name for IRSA configuration.
    
    This function tries multiple methods to discover the OIDC provider:
    1. From OIDC_PROVIDER environment variable (explicit configuration)
    2. By querying EKS cluster (auto-discovery)
    
    Args:
        region: AWS region
        
    Returns:
        Tuple of (oidc_provider, cluster_name) or (None, None) if not found
    """
    # Method 1: Check for explicit OIDC_PROVIDER env var
    oidc_provider = os.environ.get("OIDC_PROVIDER", "")
    if oidc_provider:
        logger.info(f"Using OIDC provider from environment: {oidc_provider}")
        return oidc_provider, os.environ.get("EKS_CLUSTER_NAME", "")
    
    # Method 2: Auto-discover from EKS cluster
    cluster_name = os.environ.get("EKS_CLUSTER_NAME", "")
    if not cluster_name:
        # Try to detect cluster name from current context
        cluster_name = _detect_current_cluster_name()
    
    if cluster_name:
        oidc_provider = discover_oidc_provider(cluster_name, region)
        if oidc_provider:
            return oidc_provider, cluster_name
    
    logger.warning("Could not determine OIDC provider. IRSA will fall back to EC2 trust policy.")
    logger.warning("To enable IRSA, set EKS_CLUSTER_NAME environment variable or OIDC_PROVIDER directly.")
    return None, None


def _detect_current_cluster_name() -> Optional[str]:
    """
    Try to detect the current EKS cluster name from kubeconfig context.
    
    Returns:
        Cluster name or None if not detected
    """
    try:
        from kubernetes import config
        
        # Load kubeconfig
        try:
            config.load_incluster_config()
            # When running in-cluster, we can try to get the cluster name from environment
            # or from the kube-system configmap
            return None  # In-cluster detection requires EKS_CLUSTER_NAME env var
        except config.ConfigException:
            # Not in cluster, try loading from kubeconfig
            config.load_kube_config()
        
        # Get current context
        _, active_context = config.list_kube_config_contexts()
        if active_context:
            cluster_name = active_context.get("context", {}).get("cluster", "")
            if cluster_name:
                logger.info(f"Detected cluster from kubeconfig context: {cluster_name}")
                return cluster_name
                
    except Exception as e:
        logger.debug(f"Could not detect cluster name from kubeconfig: {e}")
    
    return None


def create_iam_oidc_provider(cluster_name: str, region: str) -> Optional[str]:
    """
    Create the IAM OIDC provider for an EKS cluster if it doesn't exist.
    
    This is required for IRSA to work. Usually done via eksctl, but can be done programmatically.
    
    Args:
        cluster_name: Name of the EKS cluster
        region: AWS region
        
    Returns:
        ARN of the created/existing OIDC provider, or None on failure
    """
    try:
        eks_client = vpc_boto3_client("eks", region_name=region)
        iam_client = vpc_boto3_client("iam", region_name=region)
        sts_client = vpc_boto3_client("sts", region_name=region)
        
        # Get account ID
        account_id = sts_client.get_caller_identity()["Account"]
        
        # Get OIDC issuer URL from cluster
        cluster_info = eks_client.describe_cluster(name=cluster_name)
        oidc_issuer = cluster_info["cluster"]["identity"]["oidc"]["issuer"]
        oidc_provider = oidc_issuer.replace("https://", "")
        oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider}"
        
        # Check if already exists
        try:
            iam_client.get_open_id_connect_provider(OpenIDConnectProviderArn=oidc_arn)
            logger.info(f"OIDC provider already exists: {oidc_arn}")
            return oidc_arn
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchEntity":
                raise
        
        # Get the OIDC thumbprint
        # For EKS, AWS manages the certificate, so we can use a known thumbprint
        # or fetch it dynamically. AWS recommends using the root CA thumbprint.
        thumbprint = _get_oidc_thumbprint(oidc_issuer)
        
        # Create the OIDC provider
        response = iam_client.create_open_id_connect_provider(
            Url=oidc_issuer,
            ClientIDList=["sts.amazonaws.com"],
            ThumbprintList=[thumbprint],
            Tags=[
                {"Key": "eks:cluster-name", "Value": cluster_name},
                {"Key": "managed-by", "Value": "nexus-operator"},
            ]
        )
        
        created_arn = response["OpenIDConnectProviderArn"]
        logger.info(f"Created OIDC provider: {created_arn}")
        return created_arn
        
    except Exception as e:
        logger.error(f"Failed to create OIDC provider: {e}")
        return None


def _get_oidc_thumbprint(oidc_issuer: str) -> str:
    """
    Get the thumbprint for the OIDC provider certificate.
    
    For EKS OIDC providers, AWS manages the certificate and the thumbprint
    can be obtained from the certificate chain.
    
    Args:
        oidc_issuer: OIDC issuer URL
        
    Returns:
        SHA-1 thumbprint of the certificate
    """
    import ssl
    import socket
    import hashlib
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(oidc_issuer)
        hostname = parsed.netloc or parsed.path.split("/")[0]
        
        # Get the certificate
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443)) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
        
        # Calculate SHA-1 thumbprint
        thumbprint = hashlib.sha1(cert_der).hexdigest()
        return thumbprint
        
    except Exception as e:
        logger.warning(f"Failed to get OIDC thumbprint, using AWS default: {e}")
        # AWS's recommended thumbprint for EKS OIDC (may need updating)
        return "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"
