"""
IAM Provisioner for IRSA roles.

Feature: pure-eks-deployment
Requirements: 5.2, 5.3, 5.4
"""
import json
import logging
import os
from typing import Dict, List, Any, Optional

import boto3
from botocore.exceptions import ClientError

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class IAMProvisioner:
    """Provisions IAM roles with IRSA for EKS workloads."""
    
    def __init__(self, naming: ResourceNaming, region: str, account_id: Optional[str] = None, oidc_provider: Optional[str] = None):
        self.naming = naming
        self.region = region
        self.client = boto3.client("iam", region_name=region)
        self.sts_client = boto3.client("sts", region_name=region)
        
        # Get account ID if not provided
        if account_id:
            self.account_id = account_id
        else:
            try:
                self.account_id = self.sts_client.get_caller_identity()["Account"]
            except Exception:
                self.account_id = os.environ.get("AWS_ACCOUNT_ID", "000000000000")
        
        # OIDC provider (e.g., oidc.eks.us-east-1.amazonaws.com/id/XXXXX)
        self.oidc_provider = oidc_provider or os.environ.get("OIDC_PROVIDER", "")
    
    def _get_trust_policy(self, namespace: str, service_account: str) -> Dict:
        """Generate IRSA trust policy."""
        if not self.oidc_provider:
            # Fallback to EC2 trust if no OIDC provider
            return {
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            }
        
        return {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Federated": f"arn:aws:iam::{self.account_id}:oidc-provider/{self.oidc_provider}"},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{self.oidc_provider}:sub": f"system:serviceaccount:{namespace}:{service_account}",
                        f"{self.oidc_provider}:aud": "sts.amazonaws.com"
                    }
                }
            }]
        }
    
    @staticmethod
    def _merge_trust_policy(existing: Dict, incoming: Dict) -> Dict:
        """Merge an incoming trust policy into an existing one without removing other clusters' OIDC entries."""
        existing_stmts = existing.get("Statement", [])
        incoming_stmts = incoming.get("Statement", [])

        existing_principals = {
            stmt.get("Principal", {}).get("Federated")
            for stmt in existing_stmts
            if isinstance(stmt.get("Principal", {}).get("Federated"), str)
        }

        for stmt in incoming_stmts:
            principal = stmt.get("Principal", {}).get("Federated")
            if principal and principal not in existing_principals:
                existing_stmts.append(stmt)
                logger.info(f"Added OIDC trust for {principal}")

        return {"Version": "2012-10-17", "Statement": existing_stmts}

    def _get_app_policy(self) -> Dict:
        """Generate least-privilege policy for application."""
        return {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan",
                        "dynamodb:UpdateItem", "dynamodb:DeleteItem",
                        "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem",
                        "dynamodb:DescribeTable"
                    ],
                    "Resource": [
                        f"arn:aws:dynamodb:*:{self.account_id}:table/{self.naming.capability_name}-{self.naming.environment}-*",
                        f"arn:aws:dynamodb:*:{self.account_id}:table/{self.naming.capability_name}-{self.naming.environment}-*/index/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject", "s3:GetBucketLocation"],
                    "Resource": [
                        f"arn:aws:s3:::{self.naming.capability_name}-{self.naming.environment}-*",
                        f"arn:aws:s3:::{self.naming.capability_name}-{self.naming.environment}-*/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "ssm:PutParameter"],
                    "Resource": f"arn:aws:ssm:{self.region}:{self.account_id}:parameter/{self.naming.capability_name}/{self.naming.environment}/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "secretsmanager:GetSecretValue",
                        "secretsmanager:DescribeSecret",
                        "secretsmanager:PutSecretValue",
                        "secretsmanager:UpdateSecret",
                        "secretsmanager:CreateSecret",
                        "secretsmanager:DeleteSecret",
                        "secretsmanager:TagResource"
                    ],
                    "Resource": [
                        f"arn:aws:secretsmanager:{self.region}:{self.account_id}:secret:{self.naming.capability_name}/{self.naming.environment}/*",
                        f"arn:aws:secretsmanager:{self.region}:{self.account_id}:secret:{self.naming.capability_name}-{self.naming.environment}-*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "glue:GetDatabase",
                        "glue:GetDatabases",
                        "glue:CreateDatabase",
                        "glue:DeleteDatabase",
                        "glue:GetTable",
                        "glue:GetTables",
                        "glue:CreateTable",
                        "glue:UpdateTable",
                        "glue:DeleteTable",
                        "glue:GetPartition",
                        "glue:GetPartitions",
                        "glue:BatchGetPartition",
                        "glue:CreatePartition",
                        "glue:BatchCreatePartition",
                        "glue:UpdatePartition",
                        "glue:DeletePartition"
                    ],
                    "Resource": [
                        f"arn:aws:glue:{self.region}:{self.account_id}:catalog",
                        f"arn:aws:glue:{self.region}:{self.account_id}:database/{self.naming.capability_name}*",
                        f"arn:aws:glue:{self.region}:{self.account_id}:database/{self.naming.capability_name.replace('-', '_')}*",
                        f"arn:aws:glue:{self.region}:{self.account_id}:table/{self.naming.capability_name}*/*",
                        f"arn:aws:glue:{self.region}:{self.account_id}:table/{self.naming.capability_name.replace('-', '_')}*/*"
                    ]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "athena:StartQueryExecution",
                        "athena:GetQueryExecution",
                        "athena:GetQueryResults",
                        "athena:StopQueryExecution",
                        "athena:GetWorkGroup"
                    ],
                    "Resource": f"arn:aws:athena:{self.region}:{self.account_id}:workgroup/*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "cognito-idp:AdminInitiateAuth",
                        "cognito-idp:AdminRespondToAuthChallenge",
                        "cognito-idp:AdminGetUser",
                        "cognito-idp:AdminSetUserPassword",
                        "cognito-idp:AdminCreateUser",
                        "cognito-idp:AdminDeleteUser",
                        "cognito-idp:AdminAddUserToGroup",
                        "cognito-idp:AdminRemoveUserFromGroup",
                        "cognito-idp:AdminDisableUser",
                        "cognito-idp:AdminEnableUser",
                        "cognito-idp:AdminUpdateUserAttributes",
                        "cognito-idp:AdminResetUserPassword",
                        "cognito-idp:AdminUserGlobalSignOut",
                        "cognito-idp:AdminSetUserMFAPreference",
                        "cognito-idp:AssociateSoftwareToken",
                        "cognito-idp:VerifySoftwareToken",
                        "cognito-idp:ListUsers",
                        "cognito-idp:ListUsersInGroup",
                        "cognito-idp:AdminListGroupsForUser",
                        "cognito-idp:DescribeUserPool",
                        "cognito-idp:DescribeUserPoolClient"
                    ],
                    "Resource": f"arn:aws:cognito-idp:{self.region}:{self.account_id}:userpool/*"
                }
            ]
        }
    
    async def create_application_role(self, resources: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Create IAM role for application with IRSA.
        
        Args:
            resources: Optional dict of provisioned resources (for reference)
        """
        role_name = self.naming.application_role()
        namespace = self.naming.kubernetes_namespace()
        sa_name = self.naming.kubernetes_service_account("app")
        trust_policy = self._get_trust_policy(namespace, sa_name)
        
        try:
            # Check if role exists
            try:
                existing = self.client.get_role(RoleName=role_name)
                role_arn = existing["Role"]["Arn"]
                logger.info(f"IAM role {role_name} already exists, merging trust policy...")
                
                merged_trust = self._merge_trust_policy(
                    existing["Role"]["AssumeRolePolicyDocument"],
                    trust_policy,
                )
                self.client.update_assume_role_policy(
                    RoleName=role_name,
                    PolicyDocument=json.dumps(merged_trust)
                )
                logger.info(f"Merged trust policy for role {role_name}")
                
                # Also update the inline policy to ensure permissions are current
                self.client.put_role_policy(
                    RoleName=role_name,
                    PolicyName=f"{role_name}-policy",
                    PolicyDocument=json.dumps(self._get_app_policy())
                )
                logger.info(f"Updated inline policy for role {role_name}")
                
                return {"name": role_name, "status": "updated", "type": "IAM", "arn": role_arn}
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchEntity":
                    raise
            
            # Create role with trust policy
            response = self.client.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(self._get_trust_policy(namespace, sa_name)),
                Description=f"IRSA role for {self.naming.capability_name} application",
                Tags=self.naming.aws_tags()
            )
            role_arn = response["Role"]["Arn"]
            
            # Attach inline policy
            self.client.put_role_policy(
                RoleName=role_name,
                PolicyName=f"{role_name}-policy",
                PolicyDocument=json.dumps(self._get_app_policy())
            )
            
            logger.info(f"Created IAM role: {role_name}")
            return {"name": role_name, "status": "created", "type": "IAM", "arn": role_arn}
            
        except Exception as e:
            logger.error(f"Failed to create role {role_name}: {e}")
            return {"name": role_name, "status": "failed", "error": str(e), "type": "IAM"}
    
    async def delete_application_role(self) -> Dict[str, Any]:
        """Delete the application IAM role."""
        role_name = self.naming.application_role()
        try:
            # Delete inline policies first
            try:
                self.client.delete_role_policy(RoleName=role_name, PolicyName=f"{role_name}-policy")
            except ClientError:
                pass
            
            self.client.delete_role(RoleName=role_name)
            logger.info(f"Deleted IAM role: {role_name}")
            return {"name": role_name, "status": "deleted", "type": "IAM"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                return {"name": role_name, "status": "not_found", "type": "IAM"}
            return {"name": role_name, "status": "failed", "error": str(e), "type": "IAM"}
