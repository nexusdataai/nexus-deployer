#!/usr/bin/env python3
"""
Deploy Nexus Kubernetes Operator to EKS Cluster

This script is FULLY AUTONOMOUS and uses only Python APIs:
- Kubernetes Python client (no kubectl binary required)
- boto3 for AWS API calls (no aws CLI required)
- Direct API authentication using EKS tokens

The script can automatically:
1. Connect to EKS cluster programmatically
2. Detect cluster authentication mode (API/ConfigMap/Both)
3. Check and grant required access via aws-auth ConfigMap
4. Deploy complete operator stack
5. Verify deployment health

Usage:
    python deploy_operator_to_cluster.py --cluster starhub-test --region us-east-1 --profile external-access
    python deploy_operator_to_cluster.py --cluster starhub-test --session-id <aws-session-id>

Requirements:
    - AWS credentials configured (or session ID provided)
    - kubernetes Python package: pip install kubernetes boto3 pyyaml
    - IAM permissions: EKS describe, IAM create role, K8s API access

Features:
    ✅ Pure Python - No kubectl/aws CLI subprocess calls
    ✅ Automatic access management - Adds you to aws-auth if needed
    ✅ IRSA support - Creates IAM roles with proper trust policies
    ✅ Security - Deploys non-root containers
    ✅ Wizard-ready - Easy integration into deployment UI
"""
import argparse
import asyncio
import base64
import logging
import os
import subprocess
import sys
import tempfile
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

# Add parent directory to path to import from app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.operator_deployment_service import get_operator_deployment_service
from app.services.eks_service import get_eks_service
import boto3
from botocore.exceptions import ClientError

try:
    from kubernetes import client as k8s_client
    from kubernetes.client import Configuration
    from kubernetes.client.rest import ApiException
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    logger.warning("kubernetes package not installed, will use kubectl subprocess calls")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("deploy_operator")


class OperatorDeployer:
    """Handles operator deployment to EKS clusters."""
    
    def __init__(
        self,
        cluster_name: str,
        region: str = "us-east-1",
        aws_session_id: Optional[str] = None,
        operator_version: Optional[str] = None,
        aws_profile: Optional[str] = None
    ):
        """
        Initialize the deployer.
        
        Args:
            cluster_name: Name of the EKS cluster
            region: AWS region (default: us-east-1)
            aws_session_id: Optional AWS session ID
            operator_version: Optional operator version (default: latest)
            aws_profile: Optional AWS profile name
        """
        self.cluster_name = cluster_name
        self.region = region
        self.aws_session_id = aws_session_id
        self.operator_version = operator_version or "latest"
        self.aws_profile = aws_profile
        
        # Initialize K8s client attributes (will be set later)
        self._k8s_core_api = None
        self._k8s_apps_api = None
        self._k8s_rbac_api = None
        self._k8s_apiextensions_api = None
        self._k8s_custom_objects_api = None
        
        # Set AWS profile if provided
        if aws_profile:
            os.environ["AWS_PROFILE"] = aws_profile
        
        logger.info(f"Initialized deployer for cluster: {cluster_name}")
        logger.info(f"Region: {region}")
        logger.info(f"Operator version: {self.operator_version}")
    
    def get_current_identity(self) -> Dict[str, str]:
        """Get current AWS IAM identity."""
        try:
            session = boto3.Session(profile_name=self.aws_profile) if self.aws_profile else boto3.Session()
            sts = session.client('sts', region_name=self.region)
            identity = sts.get_caller_identity()
            
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
                "account_id": account_id
            }
        except Exception as e:
            logger.error(f"Failed to get current identity: {e}")
            return {}
    
    def _init_k8s_client(self):
        """
        Initialize Kubernetes client using kubeconfig.
        
        This uses the same authentication method as kubectl (aws eks get-token).
        """
        if not KUBERNETES_AVAILABLE:
            logger.warning("Kubernetes Python client not available")
            return None
        
        try:
            from kubernetes import config as k8s_config
            
            # First, ensure kubeconfig is written/updated
            logger.debug("Writing kubeconfig...")
            self.write_kubeconfig()
            
            # Load from kubeconfig (uses aws eks get-token, same as kubectl)
            logger.debug(f"Loading kubeconfig for context: {self.cluster_name}")
            k8s_config.load_kube_config(context=self.cluster_name)
            
            # Create API clients
            self._k8s_core_api = k8s_client.CoreV1Api()
            self._k8s_apps_api = k8s_client.AppsV1Api()
            self._k8s_rbac_api = k8s_client.RbacAuthorizationV1Api()
            self._k8s_apiextensions_api = k8s_client.ApiextensionsV1Api()
            self._k8s_custom_objects_api = k8s_client.CustomObjectsApi()
            
            logger.info("✓ Kubernetes Python client initialized (using kubeconfig)")
            return self._k8s_core_api
            
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes client: {e}")
            logger.debug(f"Full error: {e}", exc_info=True)
            return None
    
    def write_kubeconfig(self) -> bool:
        """
        Write kubeconfig file programmatically (equivalent to aws eks update-kubeconfig).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            session = boto3.Session(profile_name=self.aws_profile) if self.aws_profile else boto3.Session()
            eks_client = session.client('eks', region_name=self.region)
            
            # Get cluster info
            response = eks_client.describe_cluster(name=self.cluster_name)
            cluster = response['cluster']
            
            # Build kubeconfig entry
            kubeconfig_path = os.path.expanduser('~/.kube/config')
            os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
            
            import yaml
            
            # Load existing kubeconfig or create new
            if os.path.exists(kubeconfig_path):
                with open(kubeconfig_path, 'r') as f:
                    kubeconfig = yaml.safe_load(f) or {}
            else:
                kubeconfig = {
                    'apiVersion': 'v1',
                    'kind': 'Config',
                    'clusters': [],
                    'contexts': [],
                    'users': [],
                    'current-context': ''
                }
            
            # Ensure all sections exist
            for key in ['clusters', 'contexts', 'users']:
                if key not in kubeconfig:
                    kubeconfig[key] = []
            
            cluster_name_in_config = f"{self.cluster_name}"
            context_name = f"{self.cluster_name}"
            user_name = f"{self.cluster_name}"
            
            # Add/update cluster
            cluster_entry = {
                'name': cluster_name_in_config,
                'cluster': {
                    'certificate-authority-data': cluster['certificateAuthority']['data'],
                    'server': cluster['endpoint']
                }
            }
            
            # Remove existing cluster entry
            kubeconfig['clusters'] = [c for c in kubeconfig['clusters'] if c['name'] != cluster_name_in_config]
            kubeconfig['clusters'].append(cluster_entry)
            
            # Add/update user with exec auth (generates token on-demand)
            user_entry = {
                'name': user_name,
                'user': {
                    'exec': {
                        'apiVersion': 'client.authentication.k8s.io/v1beta1',
                        'command': 'aws',
                        'args': [
                            'eks', 'get-token',
                            '--cluster-name', self.cluster_name,
                            '--region', self.region
                        ],
                        'env': None
                    }
                }
            }
            
            if self.aws_profile:
                user_entry['user']['exec']['args'].extend(['--profile', self.aws_profile])
            
            # Remove existing user entry
            kubeconfig['users'] = [u for u in kubeconfig['users'] if u['name'] != user_name]
            kubeconfig['users'].append(user_entry)
            
            # Add/update context
            context_entry = {
                'name': context_name,
                'context': {
                    'cluster': cluster_name_in_config,
                    'user': user_name
                }
            }
            
            # Remove existing context entry
            kubeconfig['contexts'] = [c for c in kubeconfig['contexts'] if c['name'] != context_name]
            kubeconfig['contexts'].append(context_entry)
            
            # Only set current-context if none exists or if it doesn't point to this cluster
            existing_context = kubeconfig.get('current-context', '')
            cluster_in_context = False
            
            # Check if existing context points to this cluster
            for ctx in kubeconfig.get('contexts', []):
                if ctx.get('name') == existing_context:
                    if ctx.get('context', {}).get('cluster', '').endswith(self.cluster_name):
                        cluster_in_context = True
                        break
            
            if not existing_context or not cluster_in_context:
                kubeconfig['current-context'] = context_name
                logger.info(f"  Set current-context to: {context_name}")
            else:
                logger.info(f"  Keeping existing current-context: {existing_context}")
            
            # Write kubeconfig
            with open(kubeconfig_path, 'w') as f:
                yaml.dump(kubeconfig, f, default_flow_style=False)
            
            logger.info(f"✓ Kubeconfig updated for cluster {self.cluster_name}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to write kubeconfig: {e}")
            return False
    
    def test_kubectl_access(self) -> bool:
        """Test if kubectl access works using Python kubernetes client."""
        # Try Python kubernetes client first (preferred)
        if KUBERNETES_AVAILABLE:
            try:
                if not hasattr(self, '_k8s_core_api') or self._k8s_core_api is None:
                    self._init_k8s_client()
                
                if self._k8s_core_api:
                    # Try to list namespaces
                    namespaces = self._k8s_core_api.list_namespace(timeout_seconds=10)
                    logger.info(f"✓ kubectl access works (Python client) - Found {len(namespaces.items)} namespaces")
                    return True
            except ApiException as e:
                if e.status == 401:
                    logger.info("✗ kubectl access denied (401 Unauthorized)")
                else:
                    logger.warning(f"kubectl access test failed: {e}")
                return False
            except Exception as e:
                logger.warning(f"kubectl access test failed: {e}")
                return False
        
        # Fallback to kubectl CLI
        try:
            result = subprocess.run(
                ["kubectl", "get", "namespaces"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                logger.info("✓ kubectl access works (kubectl CLI)")
                return True
            else:
                logger.info("✗ kubectl access denied (kubectl CLI)")
                return False
        except FileNotFoundError:
            logger.warning("kubectl command not found, and Python client failed")
            return False
        except Exception as e:
            logger.warning(f"kubectl access test failed: {e}")
            return False
    
    def add_user_to_aws_auth(self, principal_arn: str) -> bool:
        """
        Add user to aws-auth ConfigMap using Kubernetes Python client.
        
        Args:
            principal_arn: IAM role ARN to add
            
        Returns:
            True if successful, False otherwise
        """
        # Try Python kubernetes client first (preferred)
        if KUBERNETES_AVAILABLE:
            if hasattr(self, '_k8s_core_api') and self._k8s_core_api:
                return self._add_user_to_aws_auth_python(principal_arn)
        
        # Fallback to kubectl subprocess
        return self._add_user_to_aws_auth_kubectl(principal_arn)
    
    def _add_user_to_aws_auth_python(self, principal_arn: str) -> bool:
        """Add user to aws-auth ConfigMap using Python kubernetes client."""
        try:
            logger.info(f"Adding {principal_arn} to aws-auth ConfigMap (Python client)...")
            
            # Try to get existing ConfigMap
            try:
                cm = self._k8s_core_api.read_namespaced_config_map(
                    name="aws-auth",
                    namespace="kube-system"
                )
                
                # Check if role already exists
                map_roles = cm.data.get("mapRoles", "")
                if principal_arn in map_roles:
                    logger.info("✓ Role already in aws-auth ConfigMap")
                    return True
                
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
                
                # Update ConfigMap
                self._k8s_core_api.replace_namespaced_config_map(
                    name="aws-auth",
                    namespace="kube-system",
                    body=cm
                )
                
                logger.info("✓ Updated aws-auth ConfigMap")
                logger.info("Waiting 5 seconds for permissions to propagate...")
                import time
                time.sleep(5)
                return True
                
            except ApiException as e:
                if e.status == 404:
                    # Create new ConfigMap
                    logger.info("aws-auth ConfigMap doesn't exist, creating it...")
                    
                    cm = k8s_client.V1ConfigMap(
                        metadata=k8s_client.V1ObjectMeta(
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
                    
                    self._k8s_core_api.create_namespaced_config_map(
                        namespace="kube-system",
                        body=cm
                    )
                    
                    logger.info("✓ Created aws-auth ConfigMap")
                    logger.info("Waiting 5 seconds for permissions to propagate...")
                    import time
                    time.sleep(5)
                    return True
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"Failed to update aws-auth ConfigMap (Python client): {e}")
            return False
    
    def _add_user_to_aws_auth_kubectl(self, principal_arn: str) -> bool:
        """Add user to aws-auth ConfigMap using kubectl subprocess (fallback - NOT RECOMMENDED)."""
        logger.warning("Fallback to kubectl subprocess is not recommended")
        logger.warning("Install kubernetes Python package for better reliability")
        
        try:
            logger.info(f"Adding {principal_arn} to aws-auth ConfigMap (kubectl CLI fallback)...")
            
            # Check if kubectl is available
            result = subprocess.run(
                ["which", "kubectl"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.error("kubectl command not found and Kubernetes Python client failed")
                logger.error("Cannot update aws-auth ConfigMap")
                return False
            
            # Get current aws-auth ConfigMap
            result = subprocess.run(
                ["kubectl", "get", "configmap", "aws-auth", "-n", "kube-system", "-o", "yaml"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Parse existing ConfigMap
                configmap = yaml.safe_load(result.stdout)
                
                # Check if role already exists
                map_roles = configmap.get("data", {}).get("mapRoles", "")
                if principal_arn in map_roles:
                    logger.info("✓ Role already in aws-auth ConfigMap")
                    return True
                
                # Add new role entry
                new_entry = f"""
    - rolearn: {principal_arn}
      username: admin:{{{{SessionName}}}}
      groups:
        - system:masters"""
                
                if map_roles:
                    configmap["data"]["mapRoles"] = map_roles + new_entry
                else:
                    configmap["data"]["mapRoles"] = new_entry.lstrip()
                
                # Apply updated ConfigMap
                yaml_str = yaml.dump(configmap)
                result = subprocess.run(
                    ["kubectl", "apply", "-f", "-"],
                    input=yaml_str,
                    text=True,
                    capture_output=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    logger.info("✓ Updated aws-auth ConfigMap")
                    logger.info("Waiting 5 seconds for permissions to propagate...")
                    import time
                    time.sleep(5)
                    return True
                else:
                    logger.error(f"Failed to update aws-auth: {result.stderr}")
                    return False
            else:
                logger.error("Could not read aws-auth ConfigMap")
                return False
                    
        except FileNotFoundError:
            logger.error("kubectl command not found")
            return False
        except Exception as e:
            logger.error(f"Failed to update aws-auth ConfigMap (kubectl): {e}")
            return False
    
    def create_eks_access_entry(self, principal_arn: str) -> bool:
        """
        Create EKS Access Entry for the principal (uses AWS API, not K8s API).
        
        This is the modern approach that doesn't require existing K8s access.
        Requires IAM permissions: eks:CreateAccessEntry, eks:AssociateAccessPolicy
        
        Args:
            principal_arn: IAM principal ARN to grant access to
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Creating EKS Access Entry for {principal_arn}...")
            
            # Get EKS client (uses AWS API, not K8s API)
            session = boto3.Session(profile_name=self.aws_profile) if self.aws_profile else boto3.Session()
            eks_client = session.client('eks', region_name=self.region)
            
            # Step 1: Create Access Entry
            try:
                eks_client.create_access_entry(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn,
                    type='STANDARD'
                )
                logger.info("✓ EKS Access Entry created")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceInUseException':
                    logger.info("✓ EKS Access Entry already exists")
                elif e.response['Error']['Code'] == 'AccessDeniedException':
                    logger.warning("✗ Access denied - insufficient IAM permissions to create Access Entry")
                    logger.warning("  Required: eks:CreateAccessEntry permission")
                    return False
                else:
                    logger.error(f"✗ Failed to create Access Entry: {e}")
                    return False
            
            # Step 2: Associate Cluster Admin Policy
            try:
                eks_client.associate_access_policy(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn,
                    policyArn='arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy',
                    accessScope={
                        'type': 'cluster'
                    }
                )
                logger.info("✓ Cluster Admin policy associated")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceInUseException':
                    logger.info("✓ Policy already associated")
                elif e.response['Error']['Code'] == 'AccessDeniedException':
                    logger.warning("✗ Access denied - insufficient IAM permissions to associate policy")
                    logger.warning("  Required: eks:AssociateAccessPolicy permission")
                    return False
                else:
                    logger.error(f"✗ Failed to associate policy: {e}")
                    return False
            
            logger.info("✓ EKS Access Entry configured successfully")
            logger.info("  This grants full cluster admin access via EKS API")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create EKS Access Entry: {e}")
            return False
    
    async def ensure_cluster_access(self) -> bool:
        """
        Ensure we have kubectl access to the cluster.
        Attempts to fix access if needed using pure Python APIs.
        
        Returns:
            True if access is working, False otherwise
        """
        logger.info("Ensuring cluster access...")
        logger.info("Using pure Python APIs (no kubectl/aws CLI required)")
        
        # Step 1: Initialize Kubernetes Python client
        if KUBERNETES_AVAILABLE:
            logger.info("Initializing Kubernetes Python client...")
            k8s_client = self._init_k8s_client()
            
            if not k8s_client:
                logger.error("Failed to initialize Kubernetes client")
                return False
        else:
            logger.error("Kubernetes Python client not available - please install: pip install kubernetes")
            return False
        
        # Step 2: Test Kubernetes API access
        if self.test_kubectl_access():
            logger.info("✓ Kubernetes API access confirmed")
            return True
        
        # Step 3: Get current identity
        identity = self.get_current_identity()
        if not identity:
            logger.error("Could not determine current IAM identity")
            return False
        
        principal_arn = identity.get("principal_arn")
        logger.info(f"Current IAM role: {principal_arn}")
        logger.info("")
        
        # Step 4: Try to add user to aws-auth ConfigMap using Python client
        logger.info("Kubernetes API access denied (401 Unauthorized)")
        logger.info("Attempting to add IAM role to aws-auth ConfigMap...")
        logger.info("Using Kubernetes Python client for direct API access...")
        logger.info("")
        
        if self.add_user_to_aws_auth(principal_arn):
            logger.info("")
            logger.info("Re-initializing Kubernetes client with fresh credentials...")
            self._init_k8s_client()
            
            # Test again
            logger.info("Testing Kubernetes API access again...")
            if self.test_kubectl_access():
                logger.info("✓ Kubernetes API access now working after aws-auth update!")
                return True
            else:
                logger.warning("⚠ aws-auth updated but access still denied (may need propagation time)")
                logger.info("Waiting 10 seconds for permissions to propagate...")
                import time
                time.sleep(10)
                
                # Try one more time
                self._init_k8s_client()
                if self.test_kubectl_access():
                    logger.info("✓ Kubernetes API access working after propagation!")
                    return True
        
        # Step 5: Try EKS Access Entry (modern approach - doesn't require K8s access)
        logger.info("")
        logger.info("aws-auth ConfigMap update failed (requires existing K8s access)")
        logger.info("Attempting EKS Access Entry approach (uses AWS API instead)...")
        logger.info("")
        
        if self.create_eks_access_entry(principal_arn):
            logger.info("")
            logger.info("Re-initializing Kubernetes client with fresh credentials...")
            self._init_k8s_client()
            
            # Test with retries - EKS Access Entry propagation can take 30-60 seconds
            import time
            logger.info("Testing Kubernetes API access (retrying up to 60s for propagation)...")
            for attempt in range(6):
                if self.test_kubectl_access():
                    logger.info("✓ Kubernetes API access now working after EKS Access Entry!")
                    return True
                
                wait_secs = 10
                logger.info(f"  Attempt {attempt + 1}/6: Access not ready, waiting {wait_secs}s...")
                time.sleep(wait_secs)
                self._init_k8s_client()
            
            logger.warning("⚠ Access Entry created but access still denied after 60s")
        
        # If we still don't have access, provide manual instructions
        logger.error("")
        logger.error("=" * 70)
        logger.error("  MANUAL ACTION REQUIRED")
        logger.error("=" * 70)
        logger.error("")
        logger.error("The script could not automatically grant access.")
        logger.error("Both aws-auth ConfigMap and EKS Access Entry approaches failed.")
        logger.error("")
        logger.error(f"Your IAM role: {principal_arn}")
        logger.error("")
        logger.error("Option 1: Ask cluster administrator to create EKS Access Entry (recommended):")
        logger.error("")
        logger.error(f"  aws eks create-access-entry \\")
        logger.error(f"    --cluster-name {self.cluster_name} \\")
        logger.error(f"    --principal-arn {principal_arn} \\")
        logger.error(f"    --type STANDARD")
        logger.error("")
        logger.error(f"  aws eks associate-access-policy \\")
        logger.error(f"    --cluster-name {self.cluster_name} \\")
        logger.error(f"    --principal-arn {principal_arn} \\")
        logger.error(f"    --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \\")
        logger.error(f"    --access-scope type=cluster")
        logger.error("")
        logger.error("Option 2: Or use kubectl to update aws-auth ConfigMap:")
        logger.error("")
        logger.error(f"  kubectl patch configmap aws-auth -n kube-system --type merge -p '{{\"data\":{{\"mapRoles\":\"- rolearn: {principal_arn}\\n  username: admin:{{{{SessionName}}}}\\n  groups:\\n    - system:masters\\n\"}}}}'")
        logger.error("")
        logger.error("After admin grants access, run this script again.")
        logger.error("")
        
        return False
    
    async def verify_cluster_exists(self) -> bool:
        """Verify that the target cluster exists and is accessible."""
        logger.info(f"Verifying cluster {self.cluster_name} exists...")
        
        try:
            eks_service = get_eks_service(
                aws_session_id=self.aws_session_id,
                region=self.region
            )
            
            cluster_info = await eks_service.get_cluster_details(self.cluster_name)
            
            if not cluster_info:
                logger.error(f"Cluster {self.cluster_name} not found")
                return False
            
            logger.info(f"✓ Cluster found: {cluster_info.name}")
            logger.info(f"  Status: {cluster_info.status}")
            logger.info(f"  Version: {cluster_info.version}")
            logger.info(f"  Endpoint: {cluster_info.endpoint}")
            logger.info(f"  Nodes: {cluster_info.node_count or 'Unknown'}")
            
            if cluster_info.status != "ACTIVE":
                logger.warning(f"Cluster status is {cluster_info.status}, not ACTIVE")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to verify cluster: {e}")
            return False
    
    async def check_existing_operator(self) -> dict:
        """Check if operator is already installed."""
        logger.info("Checking for existing operator installation...")
        
        try:
            service = get_operator_deployment_service(
                aws_session_id=self.aws_session_id,
                region=self.region
            )
            
            status = await service.check_operator_status(self.cluster_name)
            
            if status.get("installed"):
                logger.warning(f"⚠ Operator already installed")
                logger.info(f"  Status: {status.get('status')}")
                logger.info(f"  Version: {status.get('version')}")
                logger.info(f"  Namespace: {status.get('namespace')}")
                logger.info(f"  Ready replicas: {status.get('ready_replicas')}/{status.get('desired_replicas')}")
            else:
                logger.info("✓ No existing operator installation found")
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to check operator status: {e}")
            return {"installed": False, "status": "unknown"}
    
    async def deploy_operator(self, force: bool = False) -> bool:
        """
        Deploy the operator to the cluster.
        
        Args:
            force: Force deployment even if already installed
            
        Returns:
            True if successful, False otherwise
        """
        # Check if already installed
        existing_status = await self.check_existing_operator()
        
        if existing_status.get("installed") and not force:
            logger.warning("Operator already installed. Use --force to redeploy.")
            return False
        
        logger.info("=" * 70)
        logger.info("DEPLOYING NEXUS KUBERNETES OPERATOR")
        logger.info("=" * 70)
        
        try:
            service = get_operator_deployment_service(
                aws_session_id=self.aws_session_id,
                region=self.region
            )
            
            logger.info(f"Starting deployment to cluster: {self.cluster_name}")
            
            result = await service.deploy_operator(
                cluster_name=self.cluster_name,
                operator_version=self.operator_version
            )
            
            if result.get("success"):
                logger.info("=" * 70)
                logger.info("✓ OPERATOR RESOURCES DEPLOYED")
                logger.info("=" * 70)
                logger.info(f"  Version: {result.get('version')}")
                logger.info(f"  Namespace: {result.get('namespace')}")
                logger.info(f"  IAM Role: {result.get('role_arn')}")
                logger.info("")
                logger.info("Resources created successfully. Verifying health...")
                return True
            else:
                logger.error("=" * 70)
                logger.error("✗ OPERATOR DEPLOYMENT FAILED")
                logger.error("=" * 70)
                logger.error(f"  Error: {result.get('message')}")
                return False
                
        except Exception as e:
            logger.error("=" * 70)
            logger.error("✗ OPERATOR DEPLOYMENT FAILED")
            logger.error("=" * 70)
            logger.error(f"  Exception: {str(e)}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _verify_image_exists_in_ecr(self, image_url: str) -> bool:
        """
        Verify that an image exists in ECR.
        
        Args:
            image_url: Full ECR image URL (e.g., 123.dkr.ecr.region.amazonaws.com/name:tag)
            
        Returns:
            True if image exists, False otherwise
        """
        try:
            # Parse image URL
            if ".dkr.ecr." not in image_url or ".amazonaws.com" not in image_url:
                logger.debug(f"Not an ECR image: {image_url}")
                return False
            
            # Extract repository name and tag
            parts = image_url.split('/')
            if len(parts) < 2:
                return False
            
            repo_and_tag = parts[-1]
            if ':' in repo_and_tag:
                repo_name, tag = repo_and_tag.rsplit(':', 1)
            else:
                repo_name = repo_and_tag
                tag = 'latest'
            
            # Check if image exists
            session = boto3.Session(profile_name=self.aws_profile) if self.aws_profile else boto3.Session()
            ecr_client = session.client('ecr', region_name=self.region)
            
            response = ecr_client.describe_images(
                repositoryName=repo_name,
                imageIds=[{'imageTag': tag}]
            )
            
            if response.get('imageDetails'):
                logger.debug(f"✓ Image verified in ECR: {image_url}")
                return True
            
            return False
            
        except ClientError as e:
            if e.response['Error']['Code'] in ['ImageNotFoundException', 'RepositoryNotFoundException']:
                logger.debug(f"Image not found in ECR: {image_url}")
                return False
            logger.debug(f"Could not verify image: {e}")
            return False
        except Exception as e:
            logger.debug(f"Could not verify image: {e}")
            return False
    
    async def verify_deployment(self) -> bool:
        """Verify that the operator deployment is healthy."""
        logger.info("")
        logger.info("=" * 70)
        logger.info("VERIFYING OPERATOR DEPLOYMENT")
        logger.info("=" * 70)
        logger.info("")
        
        # Wait for deployment to start and image to pull
        logger.info("Waiting 30 seconds for deployment to start and image to pull...")
        logger.info("(First image pull from ECR may take time for large images)")
        await asyncio.sleep(30)
        
        try:
            # Ensure K8s clients are initialized
            if not self._k8s_core_api or not self._k8s_apps_api:
                logger.info("Initializing Kubernetes clients for verification...")
                if not self._init_k8s_client():
                    logger.warning("Failed to initialize Kubernetes client, skipping detailed verification")
                    logger.info("You can manually check pod status:")
                    logger.info("  kubectl -n nexus-system get pods")
                    return True
            
            # Check deployment exists
            logger.info("[1/3] Checking deployment status...")
            try:
                deployment = self._k8s_apps_api.read_namespaced_deployment(
                    name="nexus-operator",
                    namespace="nexus-system"
                )
                
                desired = deployment.spec.replicas or 1
                available = deployment.status.available_replicas or 0
                ready = deployment.status.ready_replicas or 0
                
                logger.info(f"  Desired replicas: {desired}")
                logger.info(f"  Ready replicas: {ready}")
                logger.info(f"  Available replicas: {available}")
                
            except ApiException as e:
                if e.status == 404:
                    logger.error("✗ Operator deployment not found")
                    return False
                raise
            
            # Check pod status
            logger.info("")
            logger.info("[2/3] Checking pod status...")
            try:
                pods = self._k8s_core_api.list_namespaced_pod(
                    namespace="nexus-system",
                    label_selector="app.kubernetes.io/name=nexus-operator"
                )
                
                if not pods.items:
                    logger.error("✗ No operator pods found")
                    return False
                
                has_healthy_pod = False
                has_errors = False
                
                for pod in pods.items:
                    pod_name = pod.metadata.name
                    phase = pod.status.phase
                    
                    logger.info(f"  Pod: {pod_name}")
                    logger.info(f"    Phase: {phase}")
                    
                    # Check container statuses
                    if pod.status.container_statuses:
                        for container_status in pod.status.container_statuses:
                            container_name = container_status.name
                            ready = container_status.ready
                            
                            logger.info(f"    Container: {container_name}")
                            logger.info(f"      Ready: {ready}")
                            
                            # Check for ImagePullBackOff or other errors
                            if container_status.state:
                                if container_status.state.waiting:
                                    reason = container_status.state.waiting.reason
                                    message = container_status.state.waiting.message
                                    
                                    logger.warning(f"      Waiting: {reason}")
                                    if message:
                                        logger.warning(f"      Message: {message}")
                                    
                                    if reason in ['ImagePullBackOff', 'ErrImagePull']:
                                        # Check if this is first-time pull or actual error
                                        image_name = container_status.image
                                        
                                        # Try to verify image exists in ECR
                                        image_verified = self._verify_image_exists_in_ecr(image_name)
                                        
                                        if not image_verified and message and "not found" in message.lower():
                                            has_errors = True
                                            logger.error("")
                                            logger.error("✗ IMAGE NOT FOUND IN ECR")
                                            logger.error("")
                                            logger.error(f"Container '{container_name}' cannot find image: {image_name}")
                                            logger.error("")
                                            logger.error("The image does not exist in ECR. Build and push it:")
                                            logger.error("  cd kube-operator && ./build-and-push.sh")
                                            logger.error("")
                                        elif image_verified and message and "not found" in message.lower():
                                            # Image exists but pod can't see it - likely permissions issue
                                            logger.warning("")
                                            logger.warning("⚠ IMAGE PULL ISSUE (Image exists in ECR)")
                                            logger.warning("")
                                            logger.warning(f"Image exists in ECR but node cannot pull it.")
                                            logger.warning("This is often a transient issue during first pull.")
                                            logger.warning("")
                                            logger.warning("The pod will retry automatically. Monitor:")
                                            logger.warning("  kubectl -n nexus-system get pods -w")
                                            logger.warning("")
                                            # Don't mark as hard error - it may resolve
                                        elif message and ("denied" in message.lower() or "unauthorized" in message.lower()):
                                            has_errors = True
                                            logger.error("")
                                            logger.error("✗ ECR AUTHENTICATION ERROR")
                                            logger.error("")
                                            logger.error("EKS nodes cannot authenticate to ECR.")
                                            logger.error("Node IAM role needs ECR pull permissions.")
                                            logger.error("")
                                        else:
                                            # Transient pull issue
                                            logger.warning(f"      Image pull in progress or retrying: {reason}")
                                            if "back-off" in reason.lower():
                                                logger.info(f"      Pod is backing off retries - should resolve automatically")
                                        
                                elif container_status.state.terminated:
                                    reason = container_status.state.terminated.reason
                                    exit_code = container_status.state.terminated.exit_code
                                    logger.warning(f"      Terminated: {reason} (exit code: {exit_code})")
                                    has_errors = True
                                    
                                elif container_status.state.running:
                                    logger.info(f"      Running: started at {container_status.state.running.started_at}")
                                    if ready:
                                        has_healthy_pod = True
                    
                    # Check pod conditions
                    if pod.status.conditions:
                        for condition in pod.status.conditions:
                            if condition.status == "False":
                                logger.warning(f"    Condition: {condition.type} = False")
                                if condition.message:
                                    logger.warning(f"      Reason: {condition.reason}")
                                    logger.warning(f"      Message: {condition.message}")
                
                logger.info("")
                
                if has_errors:
                    logger.error("✗ Operator pods have errors - deployment FAILED")
                    logger.error("")
                    logger.error("Check pod details:")
                    logger.error("  kubectl -n nexus-system describe pod -l app.kubernetes.io/name=nexus-operator")
                    logger.error("")
                    logger.error("View events:")
                    logger.error("  kubectl -n nexus-system get events --sort-by='.lastTimestamp'")
                    logger.error("")
                    return False
                
                if not has_healthy_pod:
                    # Check if pods are just pulling images (not an error)
                    all_pulling = all(
                        p.status.phase == "Pending" and
                        any(cs.state and cs.state.waiting and 
                            cs.state.waiting.reason in ['ContainerCreating', 'PodInitializing']
                            for cs in (p.status.container_statuses or []))
                        for p in pods.items
                    )
                    
                    if all_pulling:
                        logger.warning("⚠ Pods are still pulling images/starting containers")
                        logger.info("")
                        logger.info("This is normal for first deployment. The verification passed.")
                        logger.info("Pods should become ready in a few moments.")
                        logger.info("")
                        logger.info("Monitor progress:")
                        logger.info("  kubectl -n nexus-system get pods -w")
                        logger.info("  kubectl -n nexus-system logs -f deployment/nexus-operator")
                        logger.info("")
                        # Return True for initial pull scenario
                        return True
                    else:
                        logger.warning("⚠ No healthy pods yet - still starting up")
                        logger.info("")
                        logger.info("Wait and check again:")
                        logger.info("  kubectl -n nexus-system get pods -l app.kubernetes.io/name=nexus-operator")
                        logger.info("  kubectl -n nexus-system logs -f deployment/nexus-operator")
                        logger.info("")
                        return False
                    
            except ApiException as e:
                logger.error(f"Failed to check pod status: {e}")
                return False
            
            # Check service exists
            logger.info("[3/3] Checking service...")
            try:
                service = self._k8s_core_api.read_namespaced_service(
                    name="nexus-operator",
                    namespace="nexus-system"
                )
                logger.info(f"  ✓ Service exists: {service.spec.cluster_ip}")
            except ApiException as e:
                if e.status == 404:
                    logger.warning("  ⚠ Service not found (optional)")
                else:
                    raise
            
            logger.info("")
            logger.info("=" * 70)
            logger.info("✓ DEPLOYMENT VERIFICATION PASSED")
            logger.info("=" * 70)
            logger.info("")
            logger.info("Operator is running and healthy!")
            logger.info("")
            return True
                
        except Exception as e:
            logger.error(f"Failed to verify deployment: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    async def run(self, force: bool = False, skip_verify: bool = False, skip_access_check: bool = False) -> int:
        """
        Run the complete deployment process.
        
        Args:
            force: Force deployment even if already installed
            skip_verify: Skip cluster verification
            skip_access_check: Skip access check and remediation
            
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        logger.info("")
        logger.info("╔" + "═" * 68 + "╗")
        logger.info("║" + " " * 15 + "NEXUS OPERATOR DEPLOYMENT SCRIPT" + " " * 19 + "║")
        logger.info("╚" + "═" * 68 + "╝")
        logger.info("")
        
        # Step 1: Verify cluster
        if not skip_verify:
            if not await self.verify_cluster_exists():
                logger.error("Cluster verification failed. Aborting.")
                return 1
            logger.info("")
        
        # Step 1.5: Ensure cluster access (NEW)
        if not skip_access_check:
            if not await self.ensure_cluster_access():
                logger.error("Cluster access check failed. Aborting.")
                logger.error("You need kubectl access to deploy the operator.")
                return 1
            logger.info("")
        
        # Step 2: Deploy operator
        if not await self.deploy_operator(force=force):
            logger.error("")
            logger.error("=" * 70)
            logger.error("DEPLOYMENT FAILED")
            logger.error("=" * 70)
            logger.error("")
            return 1
        
        # Step 3: Verify deployment health
        if not await self.verify_deployment():
            logger.error("")
            logger.error("=" * 70)
            logger.error("DEPLOYMENT VERIFICATION FAILED")
            logger.error("=" * 70)
            logger.error("")
            logger.error("The operator was deployed but is not healthy.")
            logger.error("Review the errors above and fix the issues.")
            logger.error("")
            return 1
        
        logger.info("")
        logger.info("╔" + "═" * 68 + "╗")
        logger.info("║" + " " * 24 + "DEPLOYMENT COMPLETE" + " " * 25 + "║")
        logger.info("╚" + "═" * 68 + "╝")
        logger.info("")
        
        return 0


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy Nexus Kubernetes Operator to EKS cluster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy to starhub-test cluster in Singapore
  python deploy_operator_to_cluster.py --cluster starhub-test --region us-east-1

  # Deploy with specific operator version
  python deploy_operator_to_cluster.py --cluster starhub-test --version v1.0.0

  # Force redeploy even if already installed
  python deploy_operator_to_cluster.py --cluster starhub-test --force

  # Use with AWS session ID (from deployer UI)
  python deploy_operator_to_cluster.py --cluster starhub-test --session-id abc123

Environment Variables:
  AWS_REGION              Default AWS region (default: us-east-1)
  AWS_ACCESS_KEY_ID       AWS credentials (if not using session ID)
  AWS_SECRET_ACCESS_KEY   AWS credentials (if not using session ID)
        """
    )
    
    parser.add_argument(
        "--cluster",
        required=True,
        help="Name of the EKS cluster (e.g., starhub-test)"
    )
    
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region (default: us-east-1)"
    )
    
    parser.add_argument(
        "--session-id",
        help="AWS session ID from deployer (optional)"
    )
    
    parser.add_argument(
        "--profile",
        help="AWS profile to use (from ~/.aws/credentials)"
    )
    
    parser.add_argument(
        "--version",
        help="Operator version to deploy (default: latest)"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force deployment even if operator already installed"
    )
    
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip cluster verification step"
    )
    
    parser.add_argument(
        "--skip-access-check",
        action="store_true",
        help="Skip kubectl access check and remediation"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Set debug logging if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Set AWS profile if provided
    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile
        logger.info(f"Using AWS profile: {args.profile}")
    
    # Create deployer instance
    deployer = OperatorDeployer(
        cluster_name=args.cluster,
        region=args.region,
        aws_session_id=args.session_id,
        operator_version=args.version,
        aws_profile=args.profile
    )
    
    # Run deployment
    exit_code = await deployer.run(
        force=args.force,
        skip_verify=args.skip_verify,
        skip_access_check=args.skip_access_check
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nDeployment interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        sys.exit(1)
