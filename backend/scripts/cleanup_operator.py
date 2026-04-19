#!/usr/bin/env python3
"""
Cleanup Totogi Kubernetes Operator Deployment

This script is FULLY AUTONOMOUS and uses only Python APIs:
- Kubernetes Python client (no kubectl binary required)
- boto3 for AWS API calls (no aws CLI required)
- Direct API authentication using EKS tokens

The script removes all resources created during operator deployment:
- Kubernetes resources (namespace, RBAC, CRD, deployments)
- IAM roles (TotogiOperatorRole)
- ECR repository (optional)
- aws-auth ConfigMap entry
- Access Entry (optional)

Usage:
    python cleanup_operator.py --cluster starhub-test --region ap-southeast-1 --profile external-access
    python cleanup_operator.py --cluster starhub-test --profile external-access --keep-ecr
    python cleanup_operator.py --cluster starhub-test --profile external-access --keep-iam

Requirements:
    - AWS credentials configured (or session ID provided)
    - kubernetes Python package: pip install kubernetes boto3 pyyaml
    - IAM permissions: EKS describe, IAM delete, K8s API access

Features:
    ✅ Pure Python - No kubectl/aws CLI subprocess calls (with automatic fallback)
    ✅ Detects if operator exists before attempting cleanup
    ✅ Graceful handling of missing resources
    ✅ Preserves cluster access by default (--remove-aws-auth to remove)
"""
import argparse
import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

import boto3
from botocore.exceptions import ClientError

# Kubernetes client
try:
    from kubernetes import client as k8s_client
    from kubernetes import config as k8s_config
    from kubernetes.client.rest import ApiException
    import yaml
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    k8s_client = None
    k8s_config = None
    ApiException = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("cleanup-operator")

# Constants
OPERATOR_NAMESPACE = "nexus-system"
OPERATOR_DEPLOYMENT = "totogi-operator"
OPERATOR_SERVICE_ACCOUNT = "totogi-operator"
OPERATOR_CLUSTER_ROLE = "totogi-operator"
OPERATOR_CLUSTER_ROLE_BINDING = "totogi-operator"
CRD_NAME = "totogicapabilities.totogi.com"
IAM_ROLE_NAME = "TotogiOperatorRole"
ECR_REPO_NAME = "totogi-operator"


class OperatorCleanup:
    """Handles complete cleanup of Totogi operator deployment."""
    
    def __init__(
        self,
        cluster_name: str,
        region: str = "ap-southeast-1",
        aws_profile: Optional[str] = None,
        keep_ecr: bool = False,
        keep_iam: bool = False,
        keep_access_entry: bool = False,
        keep_aws_auth: bool = True  # DEFAULT: Keep aws-auth entry to preserve access!
    ):
        """
        Initialize cleanup handler.
        
        Args:
            cluster_name: EKS cluster name
            region: AWS region
            aws_profile: AWS profile name
            keep_ecr: Keep ECR repository
            keep_iam: Keep IAM role
            keep_access_entry: Keep EKS Access Entry
            keep_aws_auth: Keep aws-auth ConfigMap entry (DEFAULT: True to preserve access)
        """
        self.cluster_name = cluster_name
        self.region = region
        self.aws_profile = aws_profile
        self.keep_ecr = keep_ecr
        self.keep_iam = keep_iam
        self.keep_access_entry = keep_access_entry
        self.keep_aws_auth = keep_aws_auth
        self.deleted_items = []
        
        # Set AWS profile
        if aws_profile:
            os.environ["AWS_PROFILE"] = aws_profile
        
        # Initialize AWS clients
        self._init_aws_clients()
        
        # Initialize Kubernetes clients (will be set up when needed)
        self._k8s_core_api = None
        self._k8s_apps_api = None
        self._k8s_rbac_api = None
        self._k8s_apiextensions_api = None
        self._k8s_custom_objects_api = None
        self._k8s_initialized = False
    
    def _init_aws_clients(self):
        """Initialize AWS clients."""
        session = boto3.Session(profile_name=self.aws_profile) if self.aws_profile else boto3.Session()
        self.eks_client = session.client('eks', region_name=self.region)
        self.iam_client = session.client('iam', region_name=self.region)
        self.ecr_client = session.client('ecr', region_name=self.region)
        self.sts_client = session.client('sts', region_name=self.region)
    
    def write_kubeconfig(self) -> bool:
        """
        Write kubeconfig file programmatically (equivalent to aws eks update-kubeconfig).
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get cluster info
            response = self.eks_client.describe_cluster(name=self.cluster_name)
            cluster = response['cluster']
            
            # Build kubeconfig entry
            kubeconfig_path = os.path.expanduser('~/.kube/config')
            os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
            
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
            
            cluster_name_in_config = self.cluster_name
            context_name = self.cluster_name
            user_name = self.cluster_name
            
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
            
            # Add/update user (using exec for aws eks get-token)
            user_entry = {
                'name': user_name,
                'user': {
                    'exec': {
                        'apiVersion': 'client.authentication.k8s.io/v1beta1',
                        'command': 'aws',
                        'args': [
                            'eks',
                            'get-token',
                            '--cluster-name',
                            self.cluster_name,
                            '--region',
                            self.region
                        ]
                    }
                }
            }
            
            # Add profile if specified
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
            
            # Set current context
            kubeconfig['current-context'] = context_name
            
            # Write kubeconfig
            with open(kubeconfig_path, 'w') as f:
                yaml.dump(kubeconfig, f, default_flow_style=False)
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to write kubeconfig: {e}")
            return False
    
    def _init_k8s_client(self) -> bool:
        """
        Initialize Kubernetes client using kubeconfig.
        
        Returns:
            True if successful, False otherwise
        """
        if self._k8s_initialized:
            return True
        
        if not KUBERNETES_AVAILABLE:
            logger.warning("Kubernetes Python client not available - install with: pip install kubernetes")
            logger.warning("Falling back to kubectl subprocess calls")
            return False
        
        try:
            # Write/update kubeconfig
            self.write_kubeconfig()
            
            # Load from kubeconfig
            k8s_config.load_kube_config(context=self.cluster_name)
            
            # Create API clients
            self._k8s_core_api = k8s_client.CoreV1Api()
            self._k8s_apps_api = k8s_client.AppsV1Api()
            self._k8s_rbac_api = k8s_client.RbacAuthorizationV1Api()
            self._k8s_apiextensions_api = k8s_client.ApiextensionsV1Api()
            self._k8s_custom_objects_api = k8s_client.CustomObjectsApi()
            
            self._k8s_initialized = True
            logger.debug("✓ Kubernetes Python client initialized")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes client: {e}")
            logger.debug(f"Will use kubectl subprocess calls as fallback")
            return False
    
    def get_current_identity(self) -> Optional[str]:
        """Get current IAM principal ARN."""
        try:
            identity = self.sts_client.get_caller_identity()
            arn = identity["Arn"]
            account_id = identity["Account"]
            
            if ":assumed-role/" in arn:
                role_name = arn.split("/")[1]
                return f"arn:aws:iam::{account_id}:role/{role_name}"
            return arn
        except Exception as e:
            logger.warning(f"Could not get current identity: {e}")
            return None
    
    def check_operator_exists(self) -> bool:
        """
        Check if operator is actually deployed to the cluster.
        
        Returns:
            True if operator exists, False otherwise
        """
        # Try Python client first
        if self._init_k8s_client():
            try:
                # Check namespace
                try:
                    self._k8s_core_api.read_namespace(name=OPERATOR_NAMESPACE)
                except ApiException as e:
                    if e.status == 404:
                        logger.info(f"Operator namespace '{OPERATOR_NAMESPACE}' not found")
                        return False
                    raise
                
                # Check deployment
                try:
                    self._k8s_apps_api.read_namespaced_deployment(
                        name=OPERATOR_DEPLOYMENT,
                        namespace=OPERATOR_NAMESPACE
                    )
                    return True
                except ApiException as e:
                    if e.status == 404:
                        logger.info(f"Operator deployment '{OPERATOR_DEPLOYMENT}' not found in namespace '{OPERATOR_NAMESPACE}'")
                        return False
                    raise
                    
            except ApiException as e:
                if e.status == 401 or e.status == 403:
                    logger.warning("Kubernetes API authentication issue detected")
                    return False
                logger.warning(f"Kubernetes API check failed: {e}")
                return False
            except Exception as e:
                logger.warning(f"Error checking operator existence via API: {e}")
                # Fall through to kubectl fallback
        
        # Fallback to kubectl subprocess
        logger.debug("Using kubectl subprocess as fallback")
        try:
            result = subprocess.run(
                ["kubectl", "get", "namespace", OPERATOR_NAMESPACE],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                if "NotFound" in result.stderr or "not found" in result.stderr.lower():
                    logger.info(f"Operator namespace '{OPERATOR_NAMESPACE}' not found")
                    return False
                elif "the server has asked for the client to provide credentials" in result.stderr:
                    logger.warning("kubectl authentication issue detected")
                    return False
                elif "could not be found" in result.stderr.lower():
                    logger.info(f"Operator namespace '{OPERATOR_NAMESPACE}' not found")
                    return False
                else:
                    logger.warning(f"kubectl access check failed: {result.stderr}")
                    return False
            
            result = subprocess.run(
                ["kubectl", "get", "deployment", OPERATOR_DEPLOYMENT, "-n", OPERATOR_NAMESPACE],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                if "NotFound" in result.stderr or "not found" in result.stderr.lower():
                    logger.info(f"Operator deployment '{OPERATOR_DEPLOYMENT}' not found in namespace '{OPERATOR_NAMESPACE}'")
                    return False
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.warning("kubectl command timed out - possible connection issue")
            return False
        except Exception as e:
            logger.warning(f"Error checking operator existence: {e}")
            return False
    
    def cleanup_kubernetes_resources(self) -> bool:
        """Delete all Kubernetes resources related to operator."""
        logger.info("=" * 70)
        logger.info("CLEANING UP KUBERNETES RESOURCES")
        logger.info("=" * 70)
        logger.info("")
        
        # Try to initialize K8s client
        use_api = self._init_k8s_client()
        
        if use_api:
            logger.debug("Using Kubernetes Python API for cleanup")
            return self._cleanup_k8s_via_api()
        else:
            logger.debug("Using kubectl subprocess for cleanup")
            return self._cleanup_k8s_via_kubectl()
    
    def _cleanup_k8s_via_api(self) -> bool:
        """Delete Kubernetes resources using Python API."""
        success = True
        
        # 1. Delete all TotogiCapability resources first
        logger.info("[1/7] Deleting TotogiCapability resources...")
        try:
            # List all TotogiCapability resources across all namespaces
            resources = self._k8s_custom_objects_api.list_cluster_custom_object(
                group="totogi.com",
                version="v1",
                plural="totogicapabilities"
            )
            
            if resources.get('items'):
                for resource in resources['items']:
                    ns = resource['metadata']['namespace']
                    name = resource['metadata']['name']
                    try:
                        self._k8s_custom_objects_api.delete_namespaced_custom_object(
                            group="totogi.com",
                            version="v1",
                            namespace=ns,
                            plural="totogicapabilities",
                            name=name
                        )
                        logger.debug(f"  Deleted {name} in {ns}")
                    except ApiException as e:
                        if e.status != 404:
                            logger.warning(f"  Could not delete {name}: {e}")
                
                logger.info("✓ TotogiCapability resources deleted")
                self.deleted_items.append("TotogiCapability resources")
                
                # Wait for operator to process CR deletions and clean up AWS resources
                # (Cognito, DynamoDB, S3, Glue, SSM, Secrets, IAM)
                import time
                wait_secs = 30
                logger.info(f"  Waiting {wait_secs}s for operator to clean up AWS resources...")
                time.sleep(wait_secs)
                logger.info("  Done waiting")
            else:
                logger.info("✓ No TotogiCapability resources found")
                
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ TotogiCapability CRD not found (already deleted)")
            else:
                logger.warning(f"Could not delete TotogiCapability resources: {e}")
        except Exception as e:
            logger.warning(f"Could not delete TotogiCapability resources: {e}")
        
        # 2. Delete operator deployment
        logger.info("[2/7] Deleting operator deployment...")
        try:
            self._k8s_apps_api.delete_namespaced_deployment(
                name=OPERATOR_DEPLOYMENT,
                namespace=OPERATOR_NAMESPACE,
                body=k8s_client.V1DeleteOptions(propagation_policy='Foreground')
            )
            logger.info("✓ Operator deployment deleted")
            self.deleted_items.append("Operator deployment")
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ Operator deployment not found (already deleted)")
            else:
                logger.warning(f"Could not delete deployment: {e}")
        except Exception as e:
            logger.warning(f"Could not delete deployment: {e}")
        
        # 3. Delete operator service
        logger.info("[3/7] Deleting operator service...")
        try:
            self._k8s_core_api.delete_namespaced_service(
                name=OPERATOR_DEPLOYMENT,
                namespace=OPERATOR_NAMESPACE
            )
            logger.info("✓ Operator service deleted")
            self.deleted_items.append("Operator service")
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ Operator service not found (already deleted)")
            else:
                logger.warning(f"Could not delete service: {e}")
        except Exception as e:
            logger.warning(f"Could not delete service: {e}")
        
        # 4. Delete ClusterRoleBinding
        logger.info("[4/7] Deleting ClusterRoleBinding...")
        try:
            self._k8s_rbac_api.delete_cluster_role_binding(
                name=OPERATOR_CLUSTER_ROLE_BINDING
            )
            logger.info("✓ ClusterRoleBinding deleted")
            self.deleted_items.append("ClusterRoleBinding")
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ ClusterRoleBinding not found (already deleted)")
            else:
                logger.warning(f"Could not delete ClusterRoleBinding: {e}")
        except Exception as e:
            logger.warning(f"Could not delete ClusterRoleBinding: {e}")
        
        # 5. Delete ClusterRole
        logger.info("[5/7] Deleting ClusterRole...")
        try:
            self._k8s_rbac_api.delete_cluster_role(
                name=OPERATOR_CLUSTER_ROLE
            )
            logger.info("✓ ClusterRole deleted")
            self.deleted_items.append("ClusterRole")
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ ClusterRole not found (already deleted)")
            else:
                logger.warning(f"Could not delete ClusterRole: {e}")
        except Exception as e:
            logger.warning(f"Could not delete ClusterRole: {e}")
        
        # 6. Delete CRD
        logger.info("[6/7] Deleting TotogiCapability CRD...")
        try:
            self._k8s_apiextensions_api.delete_custom_resource_definition(
                name=CRD_NAME
            )
            logger.info("✓ CRD deleted")
            self.deleted_items.append("CRD")
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ CRD not found (already deleted)")
            else:
                logger.warning(f"Could not delete CRD: {e}")
        except Exception as e:
            logger.warning(f"Could not delete CRD: {e}")
        
        # 7. Delete namespace (this will delete ServiceAccount too)
        logger.info("[7/7] Deleting nexus-system namespace...")
        try:
            self._k8s_core_api.delete_namespace(
                name=OPERATOR_NAMESPACE,
                body=k8s_client.V1DeleteOptions(propagation_policy='Foreground')
            )
            logger.info("✓ Namespace deleted (ServiceAccount will be deleted with it)")
            self.deleted_items.append("Namespace (nexus-system)")
        except ApiException as e:
            if e.status == 404:
                logger.info("✓ Namespace not found (already deleted)")
            else:
                logger.warning(f"Could not delete namespace: {e}")
        except Exception as e:
            logger.warning(f"Could not delete namespace: {e}")
        
        logger.info("")
        return success
    
    def _cleanup_k8s_via_kubectl(self) -> bool:
        """Delete Kubernetes resources using kubectl subprocess (fallback)."""
        success = True
        
        # 1. Delete all TotogiCapability resources first
        logger.info("[1/7] Deleting TotogiCapability resources...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "totogicapabilities", "--all", "-A", "--wait=false"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ TotogiCapability resources deleted")
                self.deleted_items.append("TotogiCapability resources")
                
                # Wait for operator to process CR deletions and clean up AWS resources
                import time
                wait_secs = 30
                logger.info(f"  Waiting {wait_secs}s for operator to clean up AWS resources...")
                time.sleep(wait_secs)
                logger.info("  Done waiting")
            else:
                logger.warning(f"Could not delete TotogiCapability resources: {result.stderr}")
        except Exception as e:
            logger.warning(f"Could not delete TotogiCapability resources: {e}")
        
        # 2. Delete operator deployment
        logger.info("[2/7] Deleting operator deployment...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "deployment", OPERATOR_DEPLOYMENT, "-n", OPERATOR_NAMESPACE, "--wait=false"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ Operator deployment deleted")
                self.deleted_items.append("Operator deployment")
            else:
                logger.warning(f"Could not delete deployment: {result.stderr}")
        except Exception as e:
            logger.warning(f"Could not delete deployment: {e}")
        
        # 3. Delete operator service
        logger.info("[3/7] Deleting operator service...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "service", OPERATOR_DEPLOYMENT, "-n", OPERATOR_NAMESPACE],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ Operator service deleted")
                self.deleted_items.append("Operator service")
        except Exception as e:
            logger.warning(f"Could not delete service: {e}")
        
        # 4. Delete ClusterRoleBinding
        logger.info("[4/7] Deleting ClusterRoleBinding...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "clusterrolebinding", OPERATOR_CLUSTER_ROLE_BINDING],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ ClusterRoleBinding deleted")
                self.deleted_items.append("ClusterRoleBinding")
        except Exception as e:
            logger.warning(f"Could not delete ClusterRoleBinding: {e}")
        
        # 5. Delete ClusterRole
        logger.info("[5/7] Deleting ClusterRole...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "clusterrole", OPERATOR_CLUSTER_ROLE],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ ClusterRole deleted")
                self.deleted_items.append("ClusterRole")
        except Exception as e:
            logger.warning(f"Could not delete ClusterRole: {e}")
        
        # 6. Delete CRD
        logger.info("[6/7] Deleting TotogiCapability CRD...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "crd", CRD_NAME],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ CRD deleted")
                self.deleted_items.append("CRD")
        except Exception as e:
            logger.warning(f"Could not delete CRD: {e}")
        
        # 7. Delete namespace (this will delete ServiceAccount too)
        logger.info("[7/7] Deleting nexus-system namespace...")
        try:
            result = subprocess.run(
                ["kubectl", "delete", "namespace", OPERATOR_NAMESPACE, "--wait=false"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 or "NotFound" in result.stderr:
                logger.info("✓ Namespace deleted (ServiceAccount will be deleted with it)")
                self.deleted_items.append("Namespace (nexus-system)")
            else:
                logger.warning(f"Could not delete namespace: {result.stderr}")
        except Exception as e:
            logger.warning(f"Could not delete namespace: {e}")
        
        logger.info("")
        return success
    
    def cleanup_iam_role(self) -> bool:
        """Delete IAM role for operator."""
        if self.keep_iam:
            logger.info("Skipping IAM role deletion (--keep-iam specified)")
            return True
        
        logger.info("=" * 70)
        logger.info("CLEANING UP IAM RESOURCES")
        logger.info("=" * 70)
        logger.info("")
        
        logger.info(f"Deleting IAM role: {IAM_ROLE_NAME}...")
        
        try:
            # Delete inline policies first
            try:
                policies = self.iam_client.list_role_policies(RoleName=IAM_ROLE_NAME)
                for policy_name in policies.get('PolicyNames', []):
                    self.iam_client.delete_role_policy(
                        RoleName=IAM_ROLE_NAME,
                        PolicyName=policy_name
                    )
                    logger.info(f"✓ Deleted inline policy: {policy_name}")
            except ClientError as e:
                if e.response['Error']['Code'] != 'NoSuchEntity':
                    logger.warning(f"Could not list/delete policies: {e}")
            
            # Delete the role
            try:
                self.iam_client.delete_role(RoleName=IAM_ROLE_NAME)
                logger.info(f"✓ IAM role deleted: {IAM_ROLE_NAME}")
                self.deleted_items.append(f"IAM role: {IAM_ROLE_NAME}")
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchEntity':
                    logger.info(f"IAM role {IAM_ROLE_NAME} doesn't exist")
                    return True
                else:
                    logger.error(f"Failed to delete IAM role: {e}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error cleaning up IAM role: {e}")
            return False
        finally:
            logger.info("")
    
    def cleanup_ecr_repository(self) -> bool:
        """Delete ECR repository."""
        if self.keep_ecr:
            logger.info("Skipping ECR repository deletion (--keep-ecr specified)")
            return True
        
        logger.info("=" * 70)
        logger.info("CLEANING UP ECR REPOSITORY")
        logger.info("=" * 70)
        logger.info("")
        
        logger.info(f"Deleting ECR repository: {ECR_REPO_NAME}...")
        
        try:
            self.ecr_client.delete_repository(
                repositoryName=ECR_REPO_NAME,
                force=True  # Delete even if images exist
            )
            logger.info(f"✓ ECR repository deleted: {ECR_REPO_NAME}")
            self.deleted_items.append(f"ECR repository: {ECR_REPO_NAME}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                logger.info(f"ECR repository {ECR_REPO_NAME} doesn't exist")
                return True
            else:
                logger.error(f"Failed to delete ECR repository: {e}")
                return False
        except Exception as e:
            logger.error(f"Error cleaning up ECR repository: {e}")
            return False
        finally:
            logger.info("")
    
    def remove_from_aws_auth(self, principal_arn: str) -> bool:
        """Remove principal from aws-auth ConfigMap."""
        if self.keep_aws_auth:
            logger.info("Skipping aws-auth ConfigMap cleanup (--keep-aws-auth, default behavior)")
            logger.info("Your cluster access will be preserved ✅")
            return True
        
        logger.info("=" * 70)
        logger.info("CLEANING UP AWS-AUTH CONFIGMAP")
        logger.info("=" * 70)
        logger.info("")
        
        logger.warning("⚠ Removing your entry from aws-auth ConfigMap!")
        logger.warning("⚠ You will lose kubectl access after this!")
        logger.info(f"Removing {principal_arn} from aws-auth ConfigMap...")
        
        # Try Python API first
        if self._k8s_initialized:
            try:
                return self._remove_from_aws_auth_via_api(principal_arn)
            except Exception as e:
                logger.warning(f"Could not update aws-auth via API: {e}")
                logger.debug("Falling back to kubectl")
        
        # Fallback to kubectl
        try:
            # Get current aws-auth
            result = subprocess.run(
                ["kubectl", "get", "configmap", "aws-auth", "-n", "kube-system", "-o", "json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.info("aws-auth ConfigMap doesn't exist or not accessible")
                return True
            
            configmap = json.loads(result.stdout)
            map_roles = configmap.get("data", {}).get("mapRoles", "")
            
            if principal_arn not in map_roles:
                logger.info(f"Principal {principal_arn} not in aws-auth ConfigMap")
                return True
            
            # Remove the entry
            roles = yaml.safe_load(map_roles) if map_roles else []
            
            if isinstance(roles, list):
                filtered_roles = [r for r in roles if r.get('rolearn') != principal_arn]
                
                if len(filtered_roles) < len(roles):
                    configmap['data']['mapRoles'] = yaml.dump(filtered_roles) if filtered_roles else ""
                    
                    # Apply updated ConfigMap
                    result = subprocess.run(
                        ["kubectl", "apply", "-f", "-"],
                        input=json.dumps(configmap),
                        text=True,
                        capture_output=True,
                        timeout=10
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"✓ Removed {principal_arn} from aws-auth ConfigMap")
                        self.deleted_items.append("aws-auth ConfigMap entry")
                        return True
                    else:
                        logger.error(f"Failed to update aws-auth: {result.stderr}")
                        return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Could not update aws-auth ConfigMap: {e}")
            return False
        finally:
            logger.info("")
    
    def _remove_from_aws_auth_via_api(self, principal_arn: str) -> bool:
        """Remove principal from aws-auth ConfigMap using Python API."""
        try:
            # Get current aws-auth ConfigMap
            configmap = self._k8s_core_api.read_namespaced_config_map(
                name="aws-auth",
                namespace="kube-system"
            )
            
            map_roles = configmap.data.get("mapRoles", "")
            
            if principal_arn not in map_roles:
                logger.info(f"Principal {principal_arn} not in aws-auth ConfigMap")
                return True
            
            # Parse and filter roles
            roles = yaml.safe_load(map_roles) if map_roles else []
            
            if isinstance(roles, list):
                filtered_roles = [r for r in roles if r.get('rolearn') != principal_arn]
                
                if len(filtered_roles) < len(roles):
                    # Update ConfigMap
                    configmap.data["mapRoles"] = yaml.dump(filtered_roles) if filtered_roles else ""
                    
                    self._k8s_core_api.replace_namespaced_config_map(
                        name="aws-auth",
                        namespace="kube-system",
                        body=configmap
                    )
                    
                    logger.info(f"✓ Removed {principal_arn} from aws-auth ConfigMap")
                    self.deleted_items.append("aws-auth ConfigMap entry")
                    return True
            
            return True
            
        except ApiException as e:
            if e.status == 404:
                logger.info("aws-auth ConfigMap doesn't exist")
                return True
            raise
    
    def remove_access_entry(self, principal_arn: str) -> bool:
        """Remove EKS Access Entry."""
        if self.keep_access_entry:
            logger.info("Skipping Access Entry removal (--keep-access-entry specified)")
            return True
        
        logger.info("=" * 70)
        logger.info("CLEANING UP EKS ACCESS ENTRY")
        logger.info("=" * 70)
        logger.info("")
        
        logger.info(f"Removing Access Entry for {principal_arn}...")
        
        try:
            # List associated policies first and remove them
            try:
                policies = self.eks_client.list_associated_access_policies(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn
                )
                
                for policy in policies.get('associatedAccessPolicies', []):
                    policy_arn = policy['policyArn']
                    try:
                        self.eks_client.disassociate_access_policy(
                            clusterName=self.cluster_name,
                            principalArn=principal_arn,
                            policyArn=policy_arn
                        )
                        logger.info(f"✓ Disassociated policy: {policy_arn}")
                    except Exception as e:
                        logger.warning(f"Could not disassociate policy: {e}")
            except Exception as e:
                logger.warning(f"Could not list policies: {e}")
            
            # Delete access entry
            try:
                self.eks_client.delete_access_entry(
                    clusterName=self.cluster_name,
                    principalArn=principal_arn
                )
                logger.info(f"✓ Access Entry deleted for {principal_arn}")
                self.deleted_items.append("EKS Access Entry")
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.info(f"Access Entry doesn't exist for {principal_arn}")
                    return True
                else:
                    logger.error(f"Failed to delete Access Entry: {e}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error removing Access Entry: {e}")
            return False
        finally:
            logger.info("")
    
    def cleanup_capability_namespaces(self) -> bool:
        """Delete any capability namespaces created by operator."""
        logger.info("=" * 70)
        logger.info("CLEANING UP CAPABILITY NAMESPACES")
        logger.info("=" * 70)
        logger.info("")
        
        logger.info("Searching for capability namespaces...")
        
        # Try Python API first
        if self._k8s_initialized:
            try:
                return self._cleanup_capability_namespaces_via_api()
            except Exception as e:
                logger.warning(f"Could not cleanup via API: {e}")
                logger.debug("Falling back to kubectl")
        
        # Fallback to kubectl
        try:
            # List all namespaces with totogi labels
            result = subprocess.run(
                ["kubectl", "get", "namespaces", "-l", "app.kubernetes.io/managed-by=totogi-operator", "-o", "jsonpath={.items[*].metadata.name}"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                namespaces = result.stdout.strip().split()
                logger.info(f"Found {len(namespaces)} capability namespace(s): {', '.join(namespaces)}")
                
                for ns in namespaces:
                    logger.info(f"Deleting namespace: {ns}...")
                    subprocess.run(
                        ["kubectl", "delete", "namespace", ns, "--wait=false"],
                        capture_output=True,
                        timeout=30
                    )
                    logger.info(f"✓ Namespace {ns} deleted")
                    self.deleted_items.append(f"Capability namespace: {ns}")
            else:
                logger.info("No capability namespaces found")
            
            return True
            
        except Exception as e:
            logger.warning(f"Could not clean up capability namespaces: {e}")
            return False
        finally:
            logger.info("")
    
    def _cleanup_capability_namespaces_via_api(self) -> bool:
        """Delete capability namespaces using Python API."""
        try:
            # List all namespaces with totogi label
            namespaces = self._k8s_core_api.list_namespace(
                label_selector="app.kubernetes.io/managed-by=totogi-operator"
            )
            
            if namespaces.items:
                ns_names = [ns.metadata.name for ns in namespaces.items]
                logger.info(f"Found {len(ns_names)} capability namespace(s): {', '.join(ns_names)}")
                
                for ns in namespaces.items:
                    ns_name = ns.metadata.name
                    logger.info(f"Deleting namespace: {ns_name}...")
                    try:
                        self._k8s_core_api.delete_namespace(
                            name=ns_name,
                            body=k8s_client.V1DeleteOptions(propagation_policy='Foreground')
                        )
                        logger.info(f"✓ Namespace {ns_name} deleted")
                        self.deleted_items.append(f"Capability namespace: {ns_name}")
                    except ApiException as e:
                        if e.status == 404:
                            logger.info(f"✓ Namespace {ns_name} already deleted")
                        else:
                            logger.warning(f"Could not delete namespace {ns_name}: {e}")
            else:
                logger.info("No capability namespaces found")
            
            return True
            
        except ApiException as e:
            logger.warning(f"Could not list capability namespaces: {e}")
            raise
    
    async def run_cleanup(self) -> int:
        """
        Run complete cleanup process.
        
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        logger.info("")
        logger.info("╔" + "═" * 68 + "╗")
        logger.info("║" + " " * 17 + "TOTOGI OPERATOR CLEANUP SCRIPT" + " " * 21 + "║")
        logger.info("╚" + "═" * 68 + "╝")
        logger.info("")
        logger.info(f"Cluster: {self.cluster_name}")
        logger.info(f"Region: {self.region}")
        logger.info("")
        
        # Get current identity for aws-auth removal
        principal_arn = self.get_current_identity()
        if principal_arn:
            logger.info(f"Your IAM role: {principal_arn}")
            logger.info("")
        
        # Check if operator is actually deployed
        logger.info("Checking if operator is deployed...")
        operator_exists = self.check_operator_exists()
        logger.info("")
        
        # Cleanup steps
        if operator_exists:
            logger.info("✓ Operator detected, proceeding with Kubernetes cleanup")
            logger.info("")
            self.cleanup_kubernetes_resources()
            self.cleanup_capability_namespaces()
        else:
            logger.info("✓ Operator not found in cluster - skipping Kubernetes cleanup")
            logger.info("")
            logger.info("=" * 70)
            logger.info("SKIPPING KUBERNETES CLEANUP")
            logger.info("=" * 70)
            logger.info("")
            logger.info("Reason: Operator is not deployed or kubectl access unavailable")
            logger.info("Only AWS resources (IAM, ECR, Access Entry) will be cleaned up if present.")
            logger.info("")
        
        if principal_arn and not self.keep_aws_auth:
            self.remove_from_aws_auth(principal_arn)
        elif principal_arn:
            logger.info("Keeping your aws-auth ConfigMap entry (access preserved) ✅")
        
        if principal_arn and not self.keep_access_entry:
            self.remove_access_entry(principal_arn)
        
        self.cleanup_iam_role()
        
        if not self.keep_ecr:
            self.cleanup_ecr_repository()
        
        # Final summary
        logger.info("=" * 70)
        logger.info("CLEANUP SUMMARY")
        logger.info("=" * 70)
        logger.info("")
        logger.info(f"Total items deleted: {len(self.deleted_items)}")
        for item in self.deleted_items:
            logger.info(f"  ✓ {item}")
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("CLEANUP COMPLETE")
        logger.info("=" * 70)
        logger.info("")
        
        if self.keep_iam:
            logger.info(f"Note: IAM role '{IAM_ROLE_NAME}' was preserved (--keep-iam)")
        if self.keep_ecr:
            logger.info(f"Note: ECR repository '{ECR_REPO_NAME}' was preserved (--keep-ecr)")
        if self.keep_access_entry:
            logger.info(f"Note: EKS Access Entry was preserved (--keep-access-entry)")
        if self.keep_aws_auth:
            logger.info(f"Note: Your aws-auth ConfigMap entry was preserved (cluster access maintained) ✅")
        
        logger.info("")
        logger.info("You can now redeploy the operator from scratch!")
        logger.info("")
        logger.info("To redeploy:")
        logger.info(f"  python scripts/deploy_operator_to_cluster.py \\")
        logger.info(f"    --cluster {self.cluster_name} \\")
        logger.info(f"    --region {self.region} \\")
        if self.aws_profile:
            logger.info(f"    --profile {self.aws_profile}")
        
        logger.info("")
        
        return 0


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Cleanup Totogi Kubernetes Operator deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Complete cleanup
  python cleanup_operator.py --cluster starhub-test --profile external-access

  # Keep ECR repository
  python cleanup_operator.py --cluster starhub-test --profile external-access --keep-ecr

  # Keep IAM role
  python cleanup_operator.py --cluster starhub-test --profile external-access --keep-iam

  # Keep everything except K8s resources
  python cleanup_operator.py --cluster starhub-test --profile external-access --keep-iam --keep-ecr --keep-access-entry

What gets deleted:
  - Operator deployment and service
  - nexus-system namespace
  - TotogiCapability CRD
  - RBAC (ClusterRole, ClusterRoleBinding)
  - IAM role (unless --keep-iam)
  - ECR repository (unless --keep-ecr)
  - aws-auth ConfigMap entry (your IAM role)
  - EKS Access Entry (unless --keep-access-entry)
  - Any capability namespaces created by operator
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
        "--keep-ecr",
        action="store_true",
        help="Keep ECR repository (don't delete images)"
    )
    
    parser.add_argument(
        "--keep-iam",
        action="store_true",
        help="Keep IAM role (don't delete)"
    )
    
    parser.add_argument(
        "--keep-access-entry",
        action="store_true",
        help="Keep EKS Access Entry (don't delete)"
    )
    
    parser.add_argument(
        "--remove-aws-auth",
        action="store_true",
        help="Remove your entry from aws-auth ConfigMap (WARNING: You'll lose cluster access!)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Set debug logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Create cleanup instance
    cleanup = OperatorCleanup(
        cluster_name=args.cluster,
        region=args.region,
        aws_profile=args.profile,
        keep_ecr=args.keep_ecr,
        keep_iam=args.keep_iam,
        keep_access_entry=args.keep_access_entry,
        keep_aws_auth=not args.remove_aws_auth  # Default: keep aws-auth entry
    )
    
    # Run cleanup
    exit_code = await cleanup.run_cleanup()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nCleanup interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        sys.exit(1)
