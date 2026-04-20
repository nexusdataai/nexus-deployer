"""
EKS Utility Functions for OIDC Provider Discovery.

No IAM API calls -- uses EKS API only (works via VPC endpoint in private clusters).
"""
import logging
import os
from typing import Optional, Tuple

from botocore.exceptions import ClientError

from .aws_vpc_endpoints import vpc_boto3_client

logger = logging.getLogger(__name__)


def discover_oidc_provider(cluster_name: str, region: str) -> Optional[str]:
    """
    Discover the OIDC provider from an EKS cluster using the EKS API.

    Returns:
        OIDC provider identifier (e.g., "oidc.eks.us-east-1.amazonaws.com/id/XXXXX")
        or None if discovery fails
    """
    try:
        eks_client = vpc_boto3_client("eks", region_name=region)
        cluster_info = eks_client.describe_cluster(name=cluster_name)

        oidc_issuer = cluster_info["cluster"]["identity"]["oidc"]["issuer"]
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
    Verify that the EKS cluster has an OIDC issuer configured.

    Uses EKS API only (no IAM call). The actual IAM registration of the OIDC
    provider is handled by create-hardened-eks-cluster.sh at cluster setup time.
    """
    if oidc_provider and oidc_provider.startswith("oidc.eks."):
        logger.info(f"OIDC provider configured on cluster: {oidc_provider}")
        return True
    logger.warning("OIDC provider not configured on cluster")
    return False


def get_oidc_provider_for_irsa(region: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Get OIDC provider and cluster name for IRSA configuration.

    Tries:
    1. OIDC_PROVIDER environment variable (explicit)
    2. EKS cluster auto-discovery (EKS API)
    """
    oidc_provider = os.environ.get("OIDC_PROVIDER", "")
    if oidc_provider:
        logger.info(f"Using OIDC provider from environment: {oidc_provider}")
        return oidc_provider, os.environ.get("EKS_CLUSTER_NAME", "")

    cluster_name = os.environ.get("EKS_CLUSTER_NAME", "")
    if not cluster_name:
        cluster_name = _detect_current_cluster_name()

    if cluster_name:
        oidc_provider = discover_oidc_provider(cluster_name, region)
        if oidc_provider:
            return oidc_provider, cluster_name

    logger.warning("Could not determine OIDC provider. Set EKS_CLUSTER_NAME or OIDC_PROVIDER env var.")
    return None, None


def _detect_current_cluster_name() -> Optional[str]:
    """Try to detect the current EKS cluster name from kubeconfig context."""
    try:
        from kubernetes import config

        try:
            config.load_incluster_config()
            return None
        except config.ConfigException:
            config.load_kube_config()

        _, active_context = config.list_kube_config_contexts()
        if active_context:
            cluster_name = active_context.get("context", {}).get("cluster", "")
            if cluster_name:
                logger.info(f"Detected cluster from kubeconfig context: {cluster_name}")
                return cluster_name

    except Exception as e:
        logger.debug(f"Could not detect cluster name from kubeconfig: {e}")

    return None
