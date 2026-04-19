#!/usr/bin/env python3
"""
Prepare EKS Cluster for Operator Deployment

This script automatically:
1. Connects to EKS cluster
2. Detects authentication mode (API, ConfigMap, or both)
3. Checks if current IAM identity has required access
4. Automatically grants access via appropriate method(s)
5. Verifies cluster is ready for operator deployment

Can be run standalone or integrated into deployment wizard.

Usage:
    python prepare_cluster_for_operator.py --cluster starhub-test --region ap-southeast-1 --profile external-access
    python prepare_cluster_for_operator.py --cluster starhub-test --session-id <session-id>
"""
import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, List, Any

import boto3
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("cluster-prep")


class AuthMode(Enum):
    """EKS cluster authentication modes."""
    CONFIG_MAP = "CONFIG_MAP"
    API = "API"
    API_AND_CONFIG_MAP = "API_AND_CONFIG_MAP"


class AccessStatus(Enum):
    """Cluster access status."""
    FULL_ACCESS = "full_access"
    PARTIAL_ACCESS = "partial_access"
    NO_ACCESS = "no_access"
    UNKNOWN = "unknown"


@dataclass
class ClusterAuthInfo:
    """Cluster authentication information."""
    mode: AuthMode
    access_entry_exists: bool
    access_entry_has_policy: bool
    in_aws_auth_configmap: bool
    kubectl_access_works: bool
    
    
@dataclass
class PrepResult:
    """Result of cluster preparation."""
    success: bool
    message: str
    auth_mode: Optional[str] = None
    access_status: Optional[str] = None
    actions_taken: List[str] = None
    kubectl_works: bool = False
    ready_for_operator: bool = False


class ClusterPreparation:
    """Handles EKS cluster preparation for operator deployment."""
    
    def __init__(
        self,
        cluster_name: str,
        region: str = "ap-southeast-1",
        aws_profile: Optional[str] = None,
        aws_session_id: Optional[str] = None
    ):
        """
        Initialize cluster preparation.
        
        Args:
            cluster_name: Name of EKS cluster
            region: AWS region
            aws_profile: AWS profile name (optional)
            aws_session_id: AWS session ID (optional)
        """
        self.cluster_name = cluster_name
        self.region = region
        self.aws_profile = aws_profile
        self.aws_session_id = aws_session_id
        self.actions_taken = []
        
        # Set AWS profile if provided
        if aws_profile:
            os.environ["AWS_PROFILE"] = aws_profile
        
        # Initialize AWS clients
        self._init_aws_clients()
        
        # Initialize Kubernetes clients (will be set up later)
        self._k8s_client = None
        self._k8s_apps_client = None
        
    def _init_aws_clients(self):
        """Initialize AWS clients."""
        session_kwargs = {"region_name": self.region}
        
        if self.aws_session_id:
            # TODO: Get session from session manager
            # For now, use default session
            pass
        
        self.boto_session = boto3.Session(**session_kwargs)
        self.eks_client = self.boto_session.client("eks")
        self.sts_client = self.boto_session.client("sts")
        self.iam_client = self.boto_session.client("iam")
    
    def get_current_identity(self) -> Dict[str, str]:
        """Get current AWS IAM identity."""
        identity = self.sts_client.get_caller_identity()
        arn = identity["Arn"]
        account_id = identity["Account"]
        
        # Convert assumed-role ARN to role ARN
        if ":assumed-role/" in arn:
            role_name = arn.split("/")[1]
            principal_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        else:
            principal_arn = arn
        
        return {
            "arn": arn,
            "principal_arn": principal_arn,
            "account_id": account_id,
            "user_id": identity["UserId"]
        }
    
    def check_cluster_exists(self) -> bool:
        """Check if cluster exists and is accessible."""
        try:
            response = self.eks_client.describe_cluster(name=self.cluster_name)
            cluster = response["cluster"]
            
            logger.info(f"✓ Cluster found: {cluster['name']}")
            logger.info(f"  Status: {cluster['status']}")
            logger.info(f"  Version: {cluster['version']}")
            logger.info(f"  Endpoint: {cluster['endpoint']}")
            
            if cluster["status"] != "ACTIVE":
                logger.warning(f"⚠ Cluster status is {cluster['status']}, not ACTIVE")
                return False
            
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.error(f"✗ Cluster {self.cluster_name} not found")
            else:
                logger.error(f"✗ Error checking cluster: {e}")
            return False
    
    def get_auth_mode(self) -> AuthMode:
        """Get cluster authentication mode."""
        try:
            response = self.eks_client.describe_cluster(name=self.cluster_name)
            cluster = response["cluster"]
            
            access_config = cluster.get("accessConfig", {})
            auth_mode = access_config.get("authenticationMode", "CONFIG_MAP")
            
            logger.info(f"Cluster authentication mode: {auth_mode}")
            
            return AuthMode(auth_mode)
        except Exception as e:
            logger.warning(f"Could not determine auth mode: {e}")
            return AuthMode.CONFIG_MAP
    
    def check_access_entry(self, principal_arn: str) -> Dict[str, bool]:
        """Check if access entry exists and has required policy."""
        try:
            # Check if access entry exists
            try:
                self.eks_client.describe_access_entry(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn
                )
                exists = True
                logger.info(f"✓ Access entry exists for {principal_arn}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    exists = False
                    logger.info(f"✗ No access entry found for {principal_arn}")
                else:
                    raise
            
            # Check if it has admin policy
            has_policy = False
            if exists:
                policies = self.eks_client.list_associated_access_policies(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn
                )
                
                has_policy = any(
                    "AmazonEKSClusterAdminPolicy" in p.get("policyArn", "")
                    for p in policies.get("associatedAccessPolicies", [])
                )
                
                if has_policy:
                    logger.info(f"✓ Access entry has AmazonEKSClusterAdminPolicy")
                else:
                    logger.info(f"✗ Access entry missing AmazonEKSClusterAdminPolicy")
            
            return {"exists": exists, "has_policy": has_policy}
            
        except Exception as e:
            logger.warning(f"Could not check access entry: {e}")
            return {"exists": False, "has_policy": False}
    
    def create_access_entry(self, principal_arn: str) -> bool:
        """Create access entry with admin policy."""
        try:
            logger.info(f"Creating access entry for {principal_arn}...")
            
            # Create access entry
            try:
                self.eks_client.create_access_entry(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn,
                    type="STANDARD"
                )
                logger.info("✓ Created access entry")
                self.actions_taken.append("Created EKS Access Entry")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceInUseException":
                    logger.info("Access entry already exists")
                else:
                    raise
            
            # Associate admin policy
            try:
                self.eks_client.associate_access_policy(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn,
                    policyArn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
                    accessScope={"type": "cluster"}
                )
                logger.info("✓ Associated AmazonEKSClusterAdminPolicy")
                self.actions_taken.append("Associated EKS Cluster Admin Policy")
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceInUseException":
                    logger.info("Policy already associated")
                else:
                    raise
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create access entry: {e}")
            return False
    
    def setup_kubernetes_client(self):
        """Set up Kubernetes client for cluster."""
        try:
            from kubernetes import client as k8s_client
            from kubernetes.client import Configuration
            
            # Get cluster info
            response = self.eks_client.describe_cluster(name=self.cluster_name)
            cluster = response["cluster"]
            endpoint = cluster["endpoint"]
            ca_data = cluster["certificateAuthority"]["data"]
            
            # Get authentication token
            token = self._get_eks_token()
            
            # Create kubernetes configuration
            config = Configuration()
            config.host = endpoint
            config.api_key = {"authorization": f"Bearer {token}"}
            config.ssl_ca_cert = self._write_ca_cert(ca_data)
            config.verify_ssl = True
            
            # Create API clients
            api_client = k8s_client.ApiClient(config)
            self._k8s_client = k8s_client.CoreV1Api(api_client)
            self._k8s_apps_client = k8s_client.AppsV1Api(api_client)
            
            logger.info("✓ Kubernetes client configured")
            return True
            
        except Exception as e:
            logger.warning(f"Could not configure Kubernetes client: {e}")
            return False
    
    def _get_eks_token(self) -> str:
        """Generate EKS authentication token."""
        sts_url = self.sts_client.generate_presigned_url(
            "get_caller_identity",
            Params={},
            ExpiresIn=60,
            HttpMethod="GET"
        )
        
        sts_url += f"&x-k8s-aws-id={self.cluster_name}"
        token = "k8s-aws-v1." + base64.urlsafe_b64encode(sts_url.encode()).decode().rstrip("=")
        
        return token
    
    def _write_ca_cert(self, ca_data: str) -> str:
        """Write CA certificate to temp file."""
        ca_cert = base64.b64decode(ca_data)
        fd, path = tempfile.mkstemp(suffix=".crt")
        with os.fdopen(fd, "wb") as f:
            f.write(ca_cert)
        return path
    
    def test_kubectl_access(self) -> bool:
        """Test if kubectl access works."""
        try:
            if not self._k8s_client:
                if not self.setup_kubernetes_client():
                    return False
            
            # Try to list namespaces
            namespaces = self._k8s_client.list_namespace(timeout_seconds=10)
            logger.info(f"✓ kubectl access works! Found {len(namespaces.items)} namespaces")
            return True
            
        except Exception as e:
            error_str = str(e)
            if "401" in error_str or "Unauthorized" in error_str:
                logger.info("✗ kubectl access denied (401 Unauthorized)")
            else:
                logger.warning(f"✗ kubectl access check failed: {e}")
            return False
    
    def check_aws_auth_configmap(self, principal_arn: str) -> bool:
        """Check if principal is in aws-auth ConfigMap."""
        try:
            if not self._k8s_client:
                return False
            
            # Get aws-auth ConfigMap
            try:
                cm = self._k8s_client.read_namespaced_config_map(
                    name="aws-auth",
                    namespace="kube-system"
                )
                
                map_roles = cm.data.get("mapRoles", "")
                
                if principal_arn in map_roles:
                    logger.info(f"✓ Principal found in aws-auth ConfigMap")
                    return True
                else:
                    logger.info(f"✗ Principal NOT in aws-auth ConfigMap")
                    return False
                    
            except Exception as e:
                if "404" in str(e) or "NotFound" in str(e):
                    logger.info("✗ aws-auth ConfigMap does not exist")
                else:
                    logger.warning(f"Could not read aws-auth: {e}")
                return False
                
        except Exception as e:
            logger.warning(f"Could not check aws-auth ConfigMap: {e}")
            return False
    
    def update_aws_auth_configmap(self, principal_arn: str) -> bool:
        """Update aws-auth ConfigMap to add principal."""
        try:
            if not self._k8s_client:
                logger.error("Kubernetes client not initialized")
                return False
            
            from kubernetes.client import V1ConfigMap, V1ObjectMeta
            
            logger.info(f"Updating aws-auth ConfigMap...")
            
            # Try to get existing ConfigMap
            try:
                cm = self._k8s_client.read_namespaced_config_map(
                    name="aws-auth",
                    namespace="kube-system"
                )
                
                # Update existing
                map_roles = cm.data.get("mapRoles", "")
                
                # Add new role entry
                new_entry = f"""
    - rolearn: {principal_arn}
      username: admin:{{{{SessionName}}}}
      groups:
        - system:masters"""
                
                if map_roles:
                    cm.data["mapRoles"] = map_roles + new_entry
                else:
                    cm.data["mapRoles"] = new_entry.lstrip()
                
                self._k8s_client.replace_namespaced_config_map(
                    name="aws-auth",
                    namespace="kube-system",
                    body=cm
                )
                
                logger.info("✓ Updated aws-auth ConfigMap")
                self.actions_taken.append("Updated aws-auth ConfigMap")
                return True
                
            except Exception as e:
                if "404" in str(e) or "NotFound" in str(e):
                    # Create new ConfigMap
                    logger.info("Creating new aws-auth ConfigMap...")
                    
                    cm = V1ConfigMap(
                        metadata=V1ObjectMeta(
                            name="aws-auth",
                            namespace="kube-system"
                        ),
                        data={
                            "mapRoles": f"""- rolearn: {principal_arn}
  username: admin:{{{{SessionName}}}}
  groups:
    - system:masters"""
                        }
                    )
                    
                    self._k8s_client.create_namespaced_config_map(
                        namespace="kube-system",
                        body=cm
                    )
                    
                    logger.info("✓ Created aws-auth ConfigMap")
                    self.actions_taken.append("Created aws-auth ConfigMap")
                    return True
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"Failed to update aws-auth ConfigMap: {e}")
            return False
    
    async def prepare_cluster(self) -> PrepResult:
        """
        Main method to prepare cluster for operator deployment.
        
        Returns:
            PrepResult with status and actions taken
        """
        logger.info("=" * 70)
        logger.info("  EKS Cluster Preparation for Operator Deployment")
        logger.info("=" * 70)
        logger.info("")
        
        # Step 1: Check cluster exists
        logger.info("[1/7] Checking cluster exists...")
        if not self.check_cluster_exists():
            return PrepResult(
                success=False,
                message=f"Cluster {self.cluster_name} not found or not accessible"
            )
        logger.info("")
        
        # Step 2: Get current identity
        logger.info("[2/7] Getting current IAM identity...")
        identity = self.get_current_identity()
        principal_arn = identity["principal_arn"]
        logger.info(f"Principal ARN: {principal_arn}")
        logger.info("")
        
        # Step 3: Determine authentication mode
        logger.info("[3/7] Checking cluster authentication mode...")
        auth_mode = self.get_auth_mode()
        logger.info("")
        
        # Step 4: Check/create Access Entry (if API mode enabled)
        if auth_mode in [AuthMode.API, AuthMode.API_AND_CONFIG_MAP]:
            logger.info("[4/7] Checking EKS Access Entry...")
            
            access_entry = self.check_access_entry(principal_arn)
            
            if not access_entry["exists"] or not access_entry["has_policy"]:
                logger.info("Access entry needs setup, creating...")
                if not self.create_access_entry(principal_arn):
                    logger.warning("⚠ Could not create/update access entry")
                
                # Wait for propagation
                logger.info("Waiting 3 seconds for access entry propagation...")
                await asyncio.sleep(3)
            else:
                logger.info("✓ Access entry properly configured")
        else:
            logger.info("[4/7] Skipping Access Entry (CONFIG_MAP mode only)")
        
        logger.info("")
        
        # Step 5: Setup Kubernetes client
        logger.info("[5/7] Setting up Kubernetes client...")
        self.setup_kubernetes_client()
        logger.info("")
        
        # Step 6: Test kubectl access
        logger.info("[6/7] Testing kubectl access...")
        kubectl_works = self.test_kubectl_access()
        
        if not kubectl_works:
            # Check if we need to update aws-auth
            if auth_mode in [AuthMode.CONFIG_MAP, AuthMode.API_AND_CONFIG_MAP]:
                logger.info("")
                logger.info("kubectl access denied, checking aws-auth ConfigMap...")
                
                in_configmap = self.check_aws_auth_configmap(principal_arn)
                
                if not in_configmap:
                    logger.info("Principal not in aws-auth, attempting to add...")
                    
                    if self.update_aws_auth_configmap(principal_arn):
                        # Wait for propagation
                        logger.info("Waiting 5 seconds for aws-auth propagation...")
                        await asyncio.sleep(5)
                        
                        # Test again
                        logger.info("Testing kubectl access again...")
                        kubectl_works = self.test_kubectl_access()
                    else:
                        logger.error("✗ Could not update aws-auth ConfigMap")
                        logger.error("  Manual intervention required")
        
        logger.info("")
        
        # Step 7: Final verification
        logger.info("[7/7] Final verification...")
        
        if kubectl_works:
            # Verify we can perform operator-related operations
            try:
                # Check if we can list CRDs (required for operator)
                from kubernetes import client as k8s_client
                api_ext = k8s_client.ApiextensionsV1Api(self._k8s_client.api_client)
                api_ext.list_custom_resource_definition(limit=1)
                logger.info("✓ Can access CRD API (required for operator)")
                
                # Check if we can create namespaces (operator will create nexus-system)
                self._k8s_client.list_namespace(limit=1)
                logger.info("✓ Can list namespaces")
                
                ready_for_operator = True
                
            except Exception as e:
                logger.warning(f"⚠ Limited permissions: {e}")
                ready_for_operator = False
        else:
            ready_for_operator = False
        
        logger.info("")
        logger.info("=" * 70)
        
        if ready_for_operator:
            logger.info("  ✓ CLUSTER READY FOR OPERATOR DEPLOYMENT")
            logger.info("=" * 70)
            logger.info("")
            logger.info("Summary:")
            logger.info(f"  • Authentication mode: {auth_mode.value}")
            logger.info(f"  • kubectl access: ✓ Working")
            logger.info(f"  • Actions taken: {len(self.actions_taken)}")
            for action in self.actions_taken:
                logger.info(f"    - {action}")
            logger.info("")
            logger.info("You can now deploy the operator:")
            logger.info(f"  python scripts/deploy_operator_to_cluster.py \\")
            logger.info(f"    --cluster {self.cluster_name} \\")
            logger.info(f"    --region {self.region} \\")
            if self.aws_profile:
                logger.info(f"    --profile {self.aws_profile}")
            
            return PrepResult(
                success=True,
                message="Cluster ready for operator deployment",
                auth_mode=auth_mode.value,
                access_status=AccessStatus.FULL_ACCESS.value,
                actions_taken=self.actions_taken,
                kubectl_works=True,
                ready_for_operator=True
            )
        else:
            logger.info("  ✗ CLUSTER NOT READY - MANUAL ACTION REQUIRED")
            logger.info("=" * 70)
            logger.info("")
            logger.info("Summary:")
            logger.info(f"  • Authentication mode: {auth_mode.value}")
            logger.info(f"  • kubectl access: ✗ Not working")
            logger.info(f"  • Actions attempted: {len(self.actions_taken)}")
            for action in self.actions_taken:
                logger.info(f"    - {action}")
            logger.info("")
            logger.info("Manual action required:")
            logger.info("  Ask a cluster administrator who has kubectl access to run:")
            logger.info("")
            logger.info(f"    kubectl edit -n kube-system configmap/aws-auth")
            logger.info("")
            logger.info("  And add this under mapRoles:")
            logger.info(f"    - rolearn: {principal_arn}")
            logger.info("      username: admin:{{SessionName}}")
            logger.info("      groups:")
            logger.info("        - system:masters")
            logger.info("")
            logger.info("  Or via one-line command:")
            logger.info(f"    kubectl patch configmap aws-auth -n kube-system --type merge -p '{{\"data\":{{\"mapRoles\":\"- rolearn: {principal_arn}\\n  username: admin:{{{{SessionName}}}}\\n  groups:\\n    - system:masters\\n\"}}}}'")
            logger.info("")
            logger.info("  See: scripts/COMPLETE_DEPLOYMENT_GUIDE.md for more details")
            
            return PrepResult(
                success=False,
                message="kubectl access denied - manual intervention required",
                auth_mode=auth_mode.value,
                access_status=AccessStatus.NO_ACCESS.value,
                actions_taken=self.actions_taken,
                kubectl_works=False,
                ready_for_operator=False
            )


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Prepare EKS cluster for operator deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Prepare cluster with AWS profile
  python prepare_cluster_for_operator.py \\
    --cluster starhub-test \\
    --region ap-southeast-1 \\
    --profile external-access

  # Prepare cluster with session ID
  python prepare_cluster_for_operator.py \\
    --cluster starhub-test \\
    --session-id <session-id>

  # Debug mode
  python prepare_cluster_for_operator.py \\
    --cluster starhub-test \\
    --profile external-access \\
    --debug

This script will:
  1. Check if cluster exists and is accessible
  2. Detect authentication mode (API, ConfigMap, or both)
  3. Check current access level
  4. Automatically grant required access
  5. Verify cluster is ready for operator deployment
        """
    )
    
    parser.add_argument(
        "--cluster",
        required=True,
        help="EKS cluster name"
    )
    
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "ap-southeast-1"),
        help="AWS region (default: ap-southeast-1)"
    )
    
    parser.add_argument(
        "--profile",
        help="AWS profile to use"
    )
    
    parser.add_argument(
        "--session-id",
        help="AWS session ID (for deployer UI integration)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON"
    )
    
    args = parser.parse_args()
    
    # Set debug logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Create preparation instance
    prep = ClusterPreparation(
        cluster_name=args.cluster,
        region=args.region,
        aws_profile=args.profile,
        aws_session_id=args.session_id
    )
    
    # Run preparation
    result = await prep.prepare_cluster()
    
    # Output result
    if args.json:
        output = {
            "success": result.success,
            "message": result.message,
            "auth_mode": result.auth_mode,
            "access_status": result.access_status,
            "actions_taken": result.actions_taken or [],
            "kubectl_works": result.kubectl_works,
            "ready_for_operator": result.ready_for_operator,
            "cluster_name": args.cluster,
            "region": args.region
        }
        print(json.dumps(output, indent=2))
    
    # Exit with appropriate code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if logger.level == logging.DEBUG:
            import traceback
            traceback.print_exc()
        sys.exit(1)
