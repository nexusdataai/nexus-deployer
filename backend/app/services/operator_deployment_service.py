"""
Operator Deployment Service for EKS clusters.

Feature: pure-eks-deployment
Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2

Handles:
- Deploying the Totogi Operator to EKS clusters
- Creating TotogiCapability Custom Resources
- Monitoring operator and capability status
"""
import base64
import json
import logging
import os
import tempfile
import yaml
from typing import Any, Dict, List, Optional
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from app.services.aws_session_manager import aws_session_manager
from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

logger = logging.getLogger(__name__)

# Operator configuration
OPERATOR_NAMESPACE = "totogi-system"
OPERATOR_DEPLOYMENT_NAME = "totogi-operator"
OPERATOR_SERVICE_ACCOUNT = "totogi-operator"
OPERATOR_IMAGE_NAME = os.environ.get("OPERATOR_IMAGE_NAME", "totogi-operator")
CRD_GROUP = "totogi.com"
CRD_VERSION = "v1"
CRD_PLURAL = "totogicapabilities"
# VPC endpoint CRD — kopf watches cluster-scoped TotogiNetworkConfig
NETWORK_CONFIG_PLURAL = "totoginetworkconfigs"


class OperatorDeploymentService:
    """
    Service for deploying and managing the Totogi Operator on EKS clusters.
    
    The operator is deployed with IRSA (IAM Roles for Service Accounts) to
    securely access AWS resources without embedding credentials.
    """
    
    def __init__(
        self,
        region: str,
        aws_session_id: Optional[str] = None,
        endpoint_url: Optional[str] = None
    ):
        self.region = region
        self.aws_session_id = aws_session_id
        self.endpoint_url = endpoint_url
        self._k8s_client = None
        self._k8s_apps_client = None
        self._k8s_custom_client = None
        self._init_aws_clients()
    
    def _init_aws_clients(self):
        """Initialize AWS clients."""
        client_kwargs = {"region_name": self.region}
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url
        
        if self.aws_session_id:
            session = aws_session_manager.get_session(self.aws_session_id)
            if session:
                boto_session = boto3.Session(
                    aws_access_key_id=session["access_key_id"],
                    aws_secret_access_key=session["secret_access_key"],
                    aws_session_token=session.get("session_token"),
                    region_name=self.region
                )
                self.eks_client = boto_session.client(
                    "eks", **merge_vpc_boto3_kwargs("eks", self.region, dict(client_kwargs))
                )
                self.iam_client = boto_session.client(
                    "iam", **merge_vpc_boto3_kwargs("iam", self.region, dict(client_kwargs))
                )
                self.sts_client = boto_session.client(
                    "sts", **merge_vpc_boto3_kwargs("sts", self.region, dict(client_kwargs))
                )
            else:
                self._use_default_clients(client_kwargs)
        else:
            self._use_default_clients(client_kwargs)
    
    def _use_default_clients(self, client_kwargs: Dict):
        """Use default boto3 clients."""
        r = self.region
        self.eks_client = boto3.client("eks", **merge_vpc_boto3_kwargs("eks", r, dict(client_kwargs)))
        self.iam_client = boto3.client("iam", **merge_vpc_boto3_kwargs("iam", r, dict(client_kwargs)))
        self.sts_client = boto3.client("sts", **merge_vpc_boto3_kwargs("sts", r, dict(client_kwargs)))
    
    async def _get_k8s_clients(self, cluster_name: str):
        """
        Initialize Kubernetes clients for the specified EKS cluster.
        
        Uses kubeconfig for authentication (same as kubectl) to avoid token expiry issues.
        Automatically ensures the current IAM identity has cluster access.
        """
        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config
        except ImportError:
            raise RuntimeError("kubernetes package not installed")
        
        # Ensure current IAM identity has EKS access before attempting K8s operations
        await self._ensure_eks_access(cluster_name)
        
        # Write kubeconfig if it doesn't exist
        await self._write_kubeconfig(cluster_name)
        
        try:
            # Load from kubeconfig (uses aws eks get-token, same as kubectl)
            k8s_config.load_kube_config(context=cluster_name)
            
            # Create API clients
            self._k8s_client = k8s_client.CoreV1Api()
            self._k8s_apps_client = k8s_client.AppsV1Api()
            self._k8s_custom_client = k8s_client.CustomObjectsApi()
            
            return self._k8s_client, self._k8s_apps_client, self._k8s_custom_client
            
        except Exception as e:
            logger.error(f"Failed to load kubeconfig: {e}")
            raise
    
    async def _ensure_eks_access(self, cluster_name: str):
        """
        Ensure the current IAM identity has access to the EKS cluster.
        
        Uses EKS Access Entry API (available in EKS 1.23+) to grant cluster access
        without needing to modify the aws-auth ConfigMap directly.
        
        This solves the chicken-and-egg problem where you need K8s access to update
        aws-auth, but need to be in aws-auth to get K8s access.
        """
        try:
            # Get current IAM identity
            caller_identity = self.sts_client.get_caller_identity()
            principal_arn = caller_identity["Arn"]
            
            # Normalize the ARN - convert assumed-role ARNs to role ARNs
            # e.g., arn:aws:sts::123456789012:assumed-role/MyRole/session-name
            # becomes arn:aws:iam::123456789012:role/MyRole
            if ":assumed-role/" in principal_arn:
                parts = principal_arn.split(":")
                account_id = parts[4]
                role_part = parts[5]  # assumed-role/MyRole/session-name
                role_name = role_part.split("/")[1]
                principal_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
            
            logger.info(f"Ensuring EKS access for principal: {principal_arn}")
            
            # First, check the cluster's authentication mode
            cluster_info = self.eks_client.describe_cluster(name=cluster_name)["cluster"]
            access_config = cluster_info.get("accessConfig", {})
            auth_mode = access_config.get("authenticationMode", "CONFIG_MAP")
            
            logger.info(f"Cluster {cluster_name} authentication mode: {auth_mode}")
            
            # If cluster only uses CONFIG_MAP mode, we can't use Access Entry API
            if auth_mode == "CONFIG_MAP":
                logger.warning(f"Cluster uses CONFIG_MAP authentication mode only. "
                             f"Access Entry API not available. "
                             f"Please ensure your IAM identity is in the aws-auth ConfigMap.")
                # Don't try to update aws-auth as we likely don't have access
                # Just return and let the K8s operation fail with a clear error
                return
            
            # Check if access entry already exists
            try:
                existing = self.eks_client.describe_access_entry(
                    clusterName=cluster_name,
                    principalArn=principal_arn
                )
                logger.info(f"Access entry already exists for {principal_arn}")
                
                # Check if it has the right access policy
                policies = self.eks_client.list_associated_access_policies(
                    clusterName=cluster_name,
                    principalArn=principal_arn
                )
                
                has_admin = any(
                    "AmazonEKSClusterAdminPolicy" in p.get("policyArn", "")
                    for p in policies.get("associatedAccessPolicies", [])
                )
                
                if not has_admin:
                    # Associate admin policy
                    logger.info(f"Access entry exists but missing admin policy, associating now...")
                    self._associate_admin_policy(cluster_name, principal_arn)
                    # Give EKS a moment to propagate the policy association
                    import asyncio
                    await asyncio.sleep(3)
                else:
                    logger.info(f"Access entry already has admin policy")
                
                return
                
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                error_msg = str(e)
                logger.info(f"describe_access_entry error: {error_code} - {error_msg}")
                
                if error_code == "ResourceNotFoundException":
                    # Access entry doesn't exist, we'll create it below
                    pass
                elif error_code in ["InvalidParameterException", "AccessDeniedException"]:
                    logger.warning(f"Cannot use Access Entry API: {error_msg}")
                    return
                else:
                    logger.warning(f"Unexpected error checking access entry: {error_msg}")
                    return
            
            # Create access entry with cluster admin permissions
            logger.info(f"Creating EKS access entry for {principal_arn}")
            
            try:
                self.eks_client.create_access_entry(
                    clusterName=cluster_name,
                    principalArn=principal_arn,
                    type="STANDARD"
                )
                logger.info(f"Created access entry for {principal_arn}")
                
                # Associate the cluster admin policy
                self._associate_admin_policy(cluster_name, principal_arn)
                
                # Give EKS a moment to propagate the access entry
                import asyncio
                await asyncio.sleep(2)
                
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                error_msg = str(e)
                
                if error_code == "ResourceInUseException":
                    # Entry already exists (race condition)
                    logger.info(f"Access entry already exists for {principal_arn}")
                elif error_code == "AccessDeniedException":
                    logger.warning(f"No permission to create access entry: {error_msg}")
                else:
                    logger.warning(f"Failed to create access entry: {error_code} - {error_msg}")
                    
        except Exception as e:
            logger.warning(f"Failed to ensure EKS access: {e}")
    
    def _associate_admin_policy(self, cluster_name: str, principal_arn: str):
        """Associate the EKS cluster admin policy with an access entry."""
        try:
            self.eks_client.associate_access_policy(
                clusterName=cluster_name,
                principalArn=principal_arn,
                policyArn="arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy",
                accessScope={
                    "type": "cluster"
                }
            )
            logger.info(f"Associated AmazonEKSClusterAdminPolicy with {principal_arn}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceInUseException":
                logger.info(f"Policy already associated with {principal_arn}")
            else:
                raise

    async def _write_kubeconfig(self, cluster_name: str):
        """
        Write kubeconfig file for the cluster.
        
        This creates a kubeconfig that uses 'aws eks get-token' for authentication,
        which is more reliable than manually generated tokens.
        """
        try:
            import yaml
            
            cluster_info = self.eks_client.describe_cluster(name=cluster_name)["cluster"]
            
            kubeconfig_path = os.path.expanduser('~/.kube/config')
            os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
            
            # Load existing or create new
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
            
            for key in ['clusters', 'contexts', 'users']:
                if key not in kubeconfig:
                    kubeconfig[key] = []
            
            # Add cluster
            cluster_entry = {
                'name': cluster_name,
                'cluster': {
                    'certificate-authority-data': cluster_info['certificateAuthority']['data'],
                    'server': cluster_info['endpoint']
                }
            }
            kubeconfig['clusters'] = [c for c in kubeconfig['clusters'] if c['name'] != cluster_name]
            kubeconfig['clusters'].append(cluster_entry)
            
            # Add user with exec (calls aws eks get-token)
            user_entry = {
                'name': cluster_name,
                'user': {
                    'exec': {
                        'apiVersion': 'client.authentication.k8s.io/v1beta1',
                        'command': 'aws',
                        'args': ['eks', 'get-token', '--cluster-name', cluster_name, '--region', self.region],
                        'env': None,
                        'provideClusterInfo': False
                    }
                }
            }
            kubeconfig['users'] = [u for u in kubeconfig['users'] if u['name'] != cluster_name]
            kubeconfig['users'].append(user_entry)
            
            # Add context
            context_entry = {
                'name': cluster_name,
                'context': {
                    'cluster': cluster_name,
                    'user': cluster_name
                }
            }
            kubeconfig['contexts'] = [c for c in kubeconfig['contexts'] if c['name'] != cluster_name]
            kubeconfig['contexts'].append(context_entry)
            
            # Set current context
            kubeconfig['current-context'] = cluster_name
            
            # Write
            with open(kubeconfig_path, 'w') as f:
                yaml.dump(kubeconfig, f, default_flow_style=False)
            
            logger.info(f"✓ Kubeconfig written: {kubeconfig_path}")
            
        except Exception as e:
            logger.warning(f"Could not write kubeconfig: {e}")
    
    async def get_account_id(self) -> str:
        """Get the AWS account ID."""
        try:
            return self.sts_client.get_caller_identity()["Account"]
        except Exception:
            return os.environ.get("AWS_ACCOUNT_ID", "000000000000")
    
    async def get_oidc_provider(self, cluster_name: str) -> Optional[str]:
        """
        Get the OIDC provider URL for the EKS cluster.
        
        Returns the provider ID without the https:// prefix.
        """
        try:
            cluster_info = self.eks_client.describe_cluster(name=cluster_name)["cluster"]
            oidc_url = cluster_info.get("identity", {}).get("oidc", {}).get("issuer", "")
            
            if oidc_url:
                # Remove https:// prefix
                return oidc_url.replace("https://", "")
            return None
        except Exception as e:
            logger.warning(f"Failed to get OIDC provider: {e}")
            return None
    
    def get_operator_image_url(self, account_id: str, operator_version: Optional[str] = None) -> str:
        """
        Construct the full ECR image URL for the operator.
        
        Args:
            account_id: AWS account ID
            operator_version: Operator version tag (default: latest)
            
        Returns:
            Full ECR image URL: {account}.dkr.ecr.{region}.amazonaws.com/totogi-operator:{version}
        """
        # Check if OPERATOR_IMAGE env var is set with a full URL (backwards compatibility)
        env_image = os.environ.get("OPERATOR_IMAGE")
        if env_image and ("dkr.ecr." in env_image or "amazonaws.com" in env_image):
            # Full ECR URL provided, use as-is but update version if specified
            if operator_version and operator_version != "latest":
                base_image = env_image.rsplit(':', 1)[0]
                return f"{base_image}:{operator_version}"
            return env_image
        
        # Construct ECR URL
        version = operator_version or "latest"
        ecr_registry = f"{account_id}.dkr.ecr.{self.region}.amazonaws.com"
        return f"{ecr_registry}/{OPERATOR_IMAGE_NAME}:{version}"
    
    async def deploy_operator(
        self,
        cluster_name: str,
        operator_version: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Deploy the Totogi Operator to an EKS cluster.
        
        Steps:
        1. Create totogi-system namespace
        2. Create IAM role with IRSA trust policy
        3. Create ServiceAccount with IAM role annotation
        4. Apply CRD
        5. Create RBAC (ClusterRole, ClusterRoleBinding)
        6. Deploy operator Deployment
        
        Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
        """
        logger.info(f"Deploying Totogi Operator to cluster {cluster_name}")
        
        try:
            # Initialize K8s clients
            core_v1, apps_v1, custom = await self._get_k8s_clients(cluster_name)
            
            account_id = await self.get_account_id()
            oidc_provider = await self.get_oidc_provider(cluster_name)
            
            # Step 1: Create namespace
            await self._create_namespace(core_v1)
            
            # Step 2: Create IAM role
            role_arn = await self._create_operator_iam_role(account_id, oidc_provider)
            
            # Step 3: Create ServiceAccount
            await self._create_service_account(core_v1, role_arn)
            
            # Step 4: Apply CRD
            await self._apply_crd(custom)
            
            # Step 5: Create RBAC
            await self._create_rbac(core_v1)
            
            # Step 6: Deploy operator with cluster name for IRSA
            image = self.get_operator_image_url(account_id, operator_version)
            logger.info(f"Using operator image: {image}")
            await self._deploy_operator(apps_v1, image, cluster_name=cluster_name)
            
            logger.info(f"Operator deployed successfully to {cluster_name}")
            
            return {
                "success": True,
                "message": "Operator deployed successfully",
                "version": operator_version or "latest",
                "namespace": OPERATOR_NAMESPACE,
                "role_arn": role_arn
            }
            
        except Exception as e:
            logger.error(f"Failed to deploy operator: {e}")
            return {
                "success": False,
                "message": str(e),
                "version": operator_version or "latest",
                "namespace": OPERATOR_NAMESPACE
            }
    
    async def _create_namespace(self, core_v1):
        """Create the totogi-system namespace if it doesn't exist."""
        from kubernetes.client import V1Namespace, V1ObjectMeta
        from kubernetes.client.rest import ApiException
        
        namespace = V1Namespace(
            metadata=V1ObjectMeta(
                name=OPERATOR_NAMESPACE,
                labels={
                    "app.kubernetes.io/name": "totogi-operator",
                    "app.kubernetes.io/managed-by": "totogi-deployer"
                }
            )
        )
        
        try:
            core_v1.create_namespace(namespace)
            logger.info(f"Created namespace {OPERATOR_NAMESPACE}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.info(f"Namespace {OPERATOR_NAMESPACE} already exists")
            else:
                raise

    async def _create_operator_iam_role(
        self,
        account_id: str,
        oidc_provider: Optional[str]
    ) -> str:
        """
        Create IAM role for the operator with IRSA trust policy.
        
        Requirements: 3.5, 3.6
        """
        role_name = "totogi-operator-role"
        
        # Build trust policy
        if oidc_provider:
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {
                        "Federated": f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider}"
                    },
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            f"{oidc_provider}:sub": f"system:serviceaccount:{OPERATOR_NAMESPACE}:{OPERATOR_SERVICE_ACCOUNT}",
                            f"{oidc_provider}:aud": "sts.amazonaws.com"
                        }
                    }
                }]
            }
        else:
            # Fallback for clusters without OIDC
            trust_policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            }
        
        # Operator policy - needs broad permissions to provision resources
        operator_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:CreateTable", "dynamodb:DeleteTable", "dynamodb:DescribeTable",
                        "dynamodb:UpdateTable", "dynamodb:TagResource", "dynamodb:ListTables"
                    ],
                    "Resource": f"arn:aws:dynamodb:{self.region}:{account_id}:table/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketPolicy",
                        "s3:PutBucketTagging", "s3:PutLifecycleConfiguration",
                        "s3:PutBucketVersioning", "s3:GetBucketVersioning",
                        "s3:PutBucketEncryption", "s3:GetBucketEncryption",
                        "s3:PutBucketPublicAccessBlock", "s3:GetBucketPublicAccessBlock",
                        "s3:GetBucketLocation", "s3:ListBucket", "s3:ListAllMyBuckets"
                    ],
                    "Resource": "arn:aws:s3:::*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ssm:PutParameter", "ssm:DeleteParameter", "ssm:GetParameter",
                        "ssm:GetParameters", "ssm:GetParametersByPath", "ssm:AddTagsToResource"
                    ],
                    "Resource": f"arn:aws:ssm:{self.region}:{account_id}:parameter/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "secretsmanager:CreateSecret", "secretsmanager:DeleteSecret",
                        "secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue",
                        "secretsmanager:UpdateSecret", "secretsmanager:TagResource",
                        "secretsmanager:DescribeSecret", "secretsmanager:ListSecrets"
                    ],
                    "Resource": f"arn:aws:secretsmanager:{self.region}:{account_id}:secret:*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "glue:CreateDatabase", "glue:DeleteDatabase", "glue:GetDatabase", "glue:GetDatabases",
                        "glue:CreateTable", "glue:DeleteTable", "glue:UpdateTable", "glue:GetTable", "glue:GetTables",
                        "glue:CreatePartition", "glue:BatchCreatePartition", "glue:UpdatePartition", "glue:DeletePartition",
                        "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition",
                        "glue:DeleteUserDefinedFunction", "glue:GetUserDefinedFunction", "glue:GetUserDefinedFunctions"
                    ],
                    "Resource": [
                        f"arn:aws:glue:{self.region}:{account_id}:catalog",
                        f"arn:aws:glue:{self.region}:{account_id}:database/*",
                        f"arn:aws:glue:{self.region}:{account_id}:table/*",
                        f"arn:aws:glue:{self.region}:{account_id}:userDefinedFunction/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole",
                        "iam:PutRolePolicy", "iam:DeleteRolePolicy",
                        "iam:UpdateAssumeRolePolicy",
                        "iam:GetOpenIDConnectProvider",
                        "iam:TagRole", "iam:PassRole"
                    ],
                    "Resource": f"arn:aws:iam::{account_id}:role/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "eks:DescribeCluster",
                        "eks:ListClusters"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "cognito-idp:CreateUserPool", "cognito-idp:DeleteUserPool",
                        "cognito-idp:DescribeUserPool", "cognito-idp:ListUserPools",
                        "cognito-idp:CreateGroup", "cognito-idp:GetGroup",
                        "cognito-idp:CreateUserPoolClient", "cognito-idp:DeleteUserPoolClient",
                        "cognito-idp:DescribeUserPoolClient", "cognito-idp:ListUserPoolClients",
                        "cognito-idp:CreateUserPoolDomain", "cognito-idp:DeleteUserPoolDomain",
                        "cognito-idp:DescribeUserPoolDomain",
                        "cognito-idp:ListUsersInGroup",
                        "cognito-idp:AdminCreateUser", "cognito-idp:AdminGetUser",
                        "cognito-idp:AdminAddUserToGroup", "cognito-idp:AdminSetUserPassword",
                        "cognito-idp:TagResource", "cognito-idp:UntagResource"
                    ],
                    "Resource": "*"
                }
            ]
        }
        
        try:
            # Check if role exists
            try:
                existing = self.iam_client.get_role(RoleName=role_name)
                role_arn = existing["Role"]["Arn"]
                logger.info(f"IAM role {role_name} already exists, updating policies...")
                
                # Always update trust policy to ensure IRSA is properly configured
                self.iam_client.update_assume_role_policy(
                    RoleName=role_name,
                    PolicyDocument=json.dumps(trust_policy)
                )
                logger.info(f"Updated trust policy for {role_name}")
                
                # Always update inline policy to ensure all permissions are present
                self.iam_client.put_role_policy(
                    RoleName=role_name,
                    PolicyName="totogi-operator-policy",
                    PolicyDocument=json.dumps(operator_policy)
                )
                logger.info(f"Updated inline policy for {role_name}")
                
                return role_arn
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchEntity":
                    raise
            
            # Create role
            response = self.iam_client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="IAM role for Totogi Operator with IRSA",
                Tags=[
                    {"Key": "managed-by", "Value": "totogi-deployer"},
                    {"Key": "component", "Value": "totogi-operator"}
                ]
            )
            role_arn = response["Role"]["Arn"]
            
            # Attach inline policy
            self.iam_client.put_role_policy(
                RoleName=role_name,
                PolicyName="totogi-operator-policy",
                PolicyDocument=json.dumps(operator_policy)
            )
            
            logger.info(f"Created IAM role: {role_name}")
            return role_arn
            
        except Exception as e:
            logger.error(f"Failed to create operator IAM role: {e}")
            raise

    async def _create_service_account(self, core_v1, role_arn: str):
        """Create ServiceAccount with IRSA annotation."""
        from kubernetes.client import V1ServiceAccount, V1ObjectMeta
        from kubernetes.client.rest import ApiException
        
        sa = V1ServiceAccount(
            metadata=V1ObjectMeta(
                name=OPERATOR_SERVICE_ACCOUNT,
                namespace=OPERATOR_NAMESPACE,
                annotations={
                    "eks.amazonaws.com/role-arn": role_arn
                },
                labels={
                    "app.kubernetes.io/name": "totogi-operator",
                    "app.kubernetes.io/component": "operator"
                }
            )
        )
        
        try:
            core_v1.create_namespaced_service_account(OPERATOR_NAMESPACE, sa)
            logger.info(f"Created ServiceAccount {OPERATOR_SERVICE_ACCOUNT}")
        except ApiException as e:
            if e.status == 409:
                # Update existing
                core_v1.patch_namespaced_service_account(
                    OPERATOR_SERVICE_ACCOUNT, OPERATOR_NAMESPACE, sa
                )
                logger.info(f"Updated ServiceAccount {OPERATOR_SERVICE_ACCOUNT}")
            else:
                raise
    
    async def _apply_crd(self, custom):
        """Apply the TotogiCapability CRD from manifests/crd.yaml."""
        from kubernetes.client.rest import ApiException
        from kubernetes import client as k8s_client
        import yaml
        import os
        
        # Try to load CRD from manifest file
        crd = None
        crd_paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'kube-operator', 'manifests', 'crd.yaml'),
            '/opt/mycode/trilogy/starhub-deployer/kube-operator/manifests/crd.yaml',
            os.path.join(os.path.dirname(__file__), '..', '..', 'kube-operator', 'manifests', 'crd.yaml'),
        ]
        
        for crd_path in crd_paths:
            try:
                if os.path.exists(crd_path):
                    with open(crd_path, 'r') as f:
                        crd = yaml.safe_load(f)
                    logger.info(f"Loaded CRD from {crd_path}")
                    break
            except Exception as e:
                logger.warning(f"Could not load CRD from {crd_path}: {e}")
        
        # Fallback to minimal hardcoded CRD if file not found
        if not crd:
            logger.warning("CRD manifest file not found, using minimal hardcoded CRD")
            crd = {
                "apiVersion": "apiextensions.k8s.io/v1",
                "kind": "CustomResourceDefinition",
                "metadata": {
                    "name": f"{CRD_PLURAL}.{CRD_GROUP}"
                },
                "spec": {
                    "group": CRD_GROUP,
                    "versions": [{
                        "name": CRD_VERSION,
                        "served": True,
                        "storage": True,
                        "schema": {
                            "openAPIV3Schema": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "required": ["capabilityName", "version", "environment"],
                                        "properties": {
                                            "capabilityName": {"type": "string"},
                                            "version": {"type": "string"},
                                            "environment": {"type": "string", "enum": ["dev", "staging", "prod", "test"]},
                                            "region": {"type": "string"},
                                            "enableCognito": {"type": "boolean", "default": False},
                                            "deletionPolicy": {"type": "string", "enum": ["Delete", "Retain"], "default": "Delete"},
                                            "frontend": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                            "backend": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                            "dataServices": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                            "ingress": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                            "hpa": {"type": "object", "x-kubernetes-preserve-unknown-fields": True},
                                            "pdb": {"type": "object", "x-kubernetes-preserve-unknown-fields": True}
                                        }
                                    },
                                    "status": {
                                        "type": "object",
                                        "x-kubernetes-preserve-unknown-fields": True
                                    }
                                }
                            }
                        },
                        "subresources": {"status": {}},
                        "additionalPrinterColumns": [
                            {"name": "Capability", "type": "string", "jsonPath": ".spec.capabilityName"},
                            {"name": "Version", "type": "string", "jsonPath": ".spec.version"},
                            {"name": "Environment", "type": "string", "jsonPath": ".spec.environment"},
                            {"name": "Phase", "type": "string", "jsonPath": ".status.phase"},
                            {"name": "Age", "type": "date", "jsonPath": ".metadata.creationTimestamp"}
                        ]
                    }],
                    "scope": "Namespaced",
                    "names": {
                        "plural": CRD_PLURAL,
                        "singular": "totogicapability",
                        "kind": "TotogiCapability",
                        "shortNames": ["tc", "tcap"]
                    }
                }
            }
        
        try:
            # Use apiextensions API to create or update CRD
            api_ext = k8s_client.ApiextensionsV1Api(custom.api_client)
            crd_name = f"{CRD_PLURAL}.{CRD_GROUP}"
            
            try:
                # Try to create first
                api_ext.create_custom_resource_definition(crd)
                logger.info("Created TotogiCapability CRD")
            except ApiException as e:
                if e.status == 409:
                    # CRD exists, update it (patch to preserve existing CRs)
                    api_ext.patch_custom_resource_definition(crd_name, crd)
                    logger.info("Updated TotogiCapability CRD")
                else:
                    raise
        except ApiException as e:
            logger.error(f"Failed to apply CRD: {e}")
            raise

    async def _create_rbac(self, core_v1):
        """Create RBAC resources for the operator."""
        from kubernetes import client as k8s_client
        from kubernetes.client.rest import ApiException
        
        rbac_v1 = k8s_client.RbacAuthorizationV1Api(core_v1.api_client)
        
        # ClusterRole
        cluster_role = k8s_client.V1ClusterRole(
            metadata=k8s_client.V1ObjectMeta(name="totogi-operator-role"),
            rules=[
                k8s_client.V1PolicyRule(
                    api_groups=[CRD_GROUP],
                    resources=[
                        CRD_PLURAL,
                        f"{CRD_PLURAL}/status",
                        f"{CRD_PLURAL}/finalizers",
                        NETWORK_CONFIG_PLURAL,
                        f"{NETWORK_CONFIG_PLURAL}/status",
                        f"{NETWORK_CONFIG_PLURAL}/finalizers",
                    ],
                    verbs=["*"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=["namespaces", "serviceaccounts", "services", "configmaps", "secrets", "events"],
                    verbs=["*"]
                ),
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=["pods", "pods/exec"],
                    verbs=["get", "list", "watch", "create"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=[""],
                    resources=["pods/log"],
                    verbs=["get"],
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["apps"],
                    resources=["deployments", "replicasets", "statefulsets"],
                    verbs=["*"]
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["coordination.k8s.io"],
                    resources=["leases"],
                    verbs=["*"]
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["apiextensions.k8s.io"],
                    resources=["customresourcedefinitions"],
                    verbs=["get", "list", "watch"]
                ),
                k8s_client.V1PolicyRule(
                    api_groups=["networking.k8s.io"],
                    resources=["ingresses"],
                    verbs=["get", "list", "watch", "create", "update", "patch", "delete"]
                )
            ]
        )
        
        try:
            rbac_v1.create_cluster_role(cluster_role)
            logger.info("Created ClusterRole totogi-operator-role")
        except ApiException as e:
            if e.status == 409:
                rbac_v1.replace_cluster_role("totogi-operator-role", cluster_role)
                logger.info("Updated ClusterRole totogi-operator-role")
            else:
                raise
        
        # ClusterRoleBinding
        cluster_role_binding = k8s_client.V1ClusterRoleBinding(
            metadata=k8s_client.V1ObjectMeta(name="totogi-operator-binding"),
            role_ref=k8s_client.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="ClusterRole",
                name="totogi-operator-role"
            ),
            subjects=[
                k8s_client.RbacV1Subject(
                    kind="ServiceAccount",
                    name=OPERATOR_SERVICE_ACCOUNT,
                    namespace=OPERATOR_NAMESPACE
                )
            ]
        )
        
        try:
            rbac_v1.create_cluster_role_binding(cluster_role_binding)
            logger.info("Created ClusterRoleBinding totogi-operator-binding")
        except ApiException as e:
            if e.status == 409:
                rbac_v1.patch_cluster_role_binding("totogi-operator-binding", cluster_role_binding)
                logger.info("Updated ClusterRoleBinding totogi-operator-binding")
            else:
                raise
    
    async def _deploy_operator(self, apps_v1, image: str, cluster_name: str = None):
        """Deploy the operator Deployment."""
        from kubernetes import client as k8s_client
        from kubernetes.client.rest import ApiException
        
        # Build environment variables
        env_vars = [
            k8s_client.V1EnvVar(
                name="LOG_LEVEL",
                value="INFO"
            ),
            k8s_client.V1EnvVar(
                name="OPERATOR_NAMESPACE",
                value_from=k8s_client.V1EnvVarSource(
                    field_ref=k8s_client.V1ObjectFieldSelector(
                        field_path="metadata.namespace"
                    )
                )
            ),
            k8s_client.V1EnvVar(
                name="POD_NAME",
                value_from=k8s_client.V1EnvVarSource(
                    field_ref=k8s_client.V1ObjectFieldSelector(
                        field_path="metadata.name"
                    )
                )
            ),
            k8s_client.V1EnvVar(
                name="AWS_REGION",
                value=self.region
            ),
            k8s_client.V1EnvVar(
                name="AWS_CA_BUNDLE",
                value="/etc/ssl/certs/ca-certificates.crt",
            ),
        ]
        
        # Add cluster name for IRSA OIDC provider discovery
        if cluster_name:
            env_vars.append(k8s_client.V1EnvVar(
                name="EKS_CLUSTER_NAME",
                value=cluster_name
            ))
        
        deployment = k8s_client.V1Deployment(
            metadata=k8s_client.V1ObjectMeta(
                name=OPERATOR_DEPLOYMENT_NAME,
                namespace=OPERATOR_NAMESPACE,
                labels={"app.kubernetes.io/name": "totogi-operator"}
            ),
            spec=k8s_client.V1DeploymentSpec(
                replicas=1,
                selector=k8s_client.V1LabelSelector(
                    match_labels={"app.kubernetes.io/name": "totogi-operator"}
                ),
                template=k8s_client.V1PodTemplateSpec(
                    metadata=k8s_client.V1ObjectMeta(
                        labels={"app.kubernetes.io/name": "totogi-operator"}
                    ),
                    spec=k8s_client.V1PodSpec(
                        service_account_name=OPERATOR_SERVICE_ACCOUNT,
                        containers=[
                            k8s_client.V1Container(
                                name="operator",
                                image=image,
                                env=env_vars,
                                ports=[
                                    k8s_client.V1ContainerPort(container_port=8080, name="health")
                                ],
                                liveness_probe=k8s_client.V1Probe(
                                    http_get=k8s_client.V1HTTPGetAction(path="/healthz", port=8080),
                                    initial_delay_seconds=10,
                                    period_seconds=30
                                ),
                                readiness_probe=k8s_client.V1Probe(
                                    http_get=k8s_client.V1HTTPGetAction(path="/readyz", port=8080),
                                    initial_delay_seconds=5,
                                    period_seconds=10
                                ),
                                resources=k8s_client.V1ResourceRequirements(
                                    requests={"cpu": "100m", "memory": "256Mi"},
                                    limits={"cpu": "500m", "memory": "512Mi"}
                                )
                            )
                        ]
                    )
                )
            )
        )
        
        try:
            apps_v1.create_namespaced_deployment(OPERATOR_NAMESPACE, deployment)
            logger.info(f"Created Deployment {OPERATOR_DEPLOYMENT_NAME}")
        except ApiException as e:
            if e.status == 409:
                apps_v1.patch_namespaced_deployment(
                    OPERATOR_DEPLOYMENT_NAME, OPERATOR_NAMESPACE, deployment
                )
                logger.info(f"Updated Deployment {OPERATOR_DEPLOYMENT_NAME}")
            else:
                raise

    async def check_operator_status(self, cluster_name: str) -> Dict[str, Any]:
        """
        Check the status of the Totogi Operator on a cluster.
        
        Returns:
            Dict with installed, status, version, namespace
        """
        try:
            core_v1, apps_v1, _ = await self._get_k8s_clients(cluster_name)
            
            # Check if deployment exists
            from kubernetes.client.rest import ApiException
            
            try:
                deployment = apps_v1.read_namespaced_deployment(
                    OPERATOR_DEPLOYMENT_NAME, OPERATOR_NAMESPACE
                )
                
                # Get status
                ready_replicas = deployment.status.ready_replicas or 0
                replicas = deployment.spec.replicas or 1
                
                if ready_replicas >= replicas:
                    status = "installed"
                elif ready_replicas > 0:
                    status = "degraded"
                else:
                    status = "installing"
                
                # Get version from image tag
                image = deployment.spec.template.spec.containers[0].image
                version = image.split(":")[-1] if ":" in image else "latest"
                
                return {
                    "installed": True,
                    "status": status,
                    "version": version,
                    "namespace": OPERATOR_NAMESPACE,
                    "ready_replicas": ready_replicas,
                    "desired_replicas": replicas
                }
                
            except ApiException as e:
                if e.status == 404:
                    return {
                        "installed": False,
                        "status": "not_installed",
                        "version": None,
                        "namespace": OPERATOR_NAMESPACE
                    }
                raise
                
        except Exception as e:
            logger.error(f"Failed to check operator status: {e}")
            return {
                "installed": False,
                "status": "unknown",
                "version": None,
                "namespace": OPERATOR_NAMESPACE,
                "error": str(e)
            }
    
    async def create_capability_cr(
        self,
        cluster_name: str,
        capability_name: str,
        capability_version: str,
        environment: str,
        namespace: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a TotogiCapability Custom Resource.
        
        Requirements: 4.1, 4.2
        """
        try:
            _, _, custom = await self._get_k8s_clients(cluster_name)
            
            # Generate CR name
            cr_name = f"{capability_name}-{environment}".lower().replace("_", "-")
            
            # Build CR spec
            cr = {
                "apiVersion": f"{CRD_GROUP}/{CRD_VERSION}",
                "kind": "TotogiCapability",
                "metadata": {
                    "name": cr_name,
                    "namespace": namespace,
                    "labels": {
                        "app.kubernetes.io/name": capability_name,
                        "app.kubernetes.io/version": capability_version,
                        "totogi.com/environment": environment
                    }
                },
                "spec": {
                    "capabilityName": capability_name,
                    "version": capability_version,
                    "environment": environment,
                    "region": config.get("region", self.region),
                    "deletionPolicy": config.get("deletionPolicy", "Delete"),
                    "frontend": config.get("frontend", {}),
                    "backend": config.get("backend", {}),
                    "dataServices": config.get("dataServices", {
                        "dynamodb": {"enabled": True},
                        "s3": {"enabled": True},
                        "glue": {"enabled": True}
                    })
                }
            }
            
            # Create the CR
            from kubernetes.client.rest import ApiException
            
            try:
                result = custom.create_namespaced_custom_object(
                    group=CRD_GROUP,
                    version=CRD_VERSION,
                    namespace=namespace,
                    plural=CRD_PLURAL,
                    body=cr
                )
                
                logger.info(f"Created TotogiCapability CR: {cr_name}")
                
                return {
                    "success": True,
                    "cr_name": cr_name,
                    "namespace": namespace,
                    "message": f"TotogiCapability '{cr_name}' created successfully"
                }
                
            except ApiException as e:
                if e.status == 409:
                    # Update existing
                    result = custom.patch_namespaced_custom_object(
                        group=CRD_GROUP,
                        version=CRD_VERSION,
                        namespace=namespace,
                        plural=CRD_PLURAL,
                        name=cr_name,
                        body=cr
                    )
                    return {
                        "success": True,
                        "cr_name": cr_name,
                        "namespace": namespace,
                        "message": f"TotogiCapability '{cr_name}' updated"
                    }
                raise
                
        except Exception as e:
            logger.error(f"Failed to create capability CR: {e}")
            return {
                "success": False,
                "cr_name": "",
                "namespace": namespace,
                "message": str(e)
            }
    
    async def get_capability_status(
        self,
        cluster_name: str,
        cr_name: str,
        namespace: str
    ) -> Dict[str, Any]:
        """
        Get the status of a TotogiCapability CR.
        
        Requirements: 8.1, 8.2
        """
        try:
            _, _, custom = await self._get_k8s_clients(cluster_name)
            
            cr = custom.get_namespaced_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=namespace,
                plural=CRD_PLURAL,
                name=cr_name
            )
            
            status = cr.get("status", {})
            
            return {
                "phase": status.get("phase", "Unknown"),
                "message": status.get("message", ""),
                "frontend_url": status.get("frontendUrl"),
                "backend_url": status.get("backendUrl"),
                "resources": self._format_resources(status.get("resources", {})),
                "last_reconcile_time": status.get("lastReconcileTime")
            }
            
        except Exception as e:
            logger.error(f"Failed to get capability status: {e}")
            return {
                "phase": "Unknown",
                "message": str(e),
                "frontend_url": None,
                "backend_url": None,
                "resources": [],
                "last_reconcile_time": None
            }
    
    def _format_resources(self, resources: Dict) -> List[Dict]:
        """Format resources dict into list for API response."""
        result = []
        
        for resource_type, items in resources.items():
            if isinstance(items, list):
                for item in items:
                    result.append({
                        "type": resource_type,
                        "name": item,
                        "status": "created"
                    })
            elif items:
                result.append({
                    "type": resource_type,
                    "name": str(items),
                    "status": "created"
                })
        
        return result
    
    async def delete_capability(
        self,
        cluster_name: str,
        cr_name: str,
        namespace: str
    ) -> Dict[str, Any]:
        """Delete a TotogiCapability CR."""
        try:
            _, _, custom = await self._get_k8s_clients(cluster_name)
            
            custom.delete_namespaced_custom_object(
                group=CRD_GROUP,
                version=CRD_VERSION,
                namespace=namespace,
                plural=CRD_PLURAL,
                name=cr_name
            )
            
            logger.info(f"Deleted TotogiCapability CR: {cr_name}")
            
            return {
                "success": True,
                "message": f"TotogiCapability '{cr_name}' deletion initiated"
            }
            
        except Exception as e:
            logger.error(f"Failed to delete capability CR: {e}")
            return {
                "success": False,
                "message": str(e)
            }


# Factory function
def get_operator_deployment_service(
    aws_session_id: Optional[str] = None,
    region: Optional[str] = None
) -> OperatorDeploymentService:
    """Get an OperatorDeploymentService instance."""
    import os
    
    if not region:
        if aws_session_id:
            session_info = aws_session_manager.get_session(aws_session_id)
            region = session_info.get("region") if session_info else None
        if not region:
            region = os.environ.get("AWS_REGION", "us-east-1")
    
    return OperatorDeploymentService(
        region=region,
        aws_session_id=aws_session_id
    )
