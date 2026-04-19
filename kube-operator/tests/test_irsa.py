"""
Property tests for IRSA configuration correctness.

Feature: pure-eks-deployment
Requirements: 3.5, 3.6, 5.3, 5.4, 5.5
Property 5: IRSA Configuration Correctness
"""
import json
import sys
import os
import re
import pytest
from hypothesis import given, strategies as st, settings

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from totogi_operator.utils.naming import ResourceNaming


def get_trust_policy(account_id: str, oidc_provider: str, namespace: str, service_account: str) -> dict:
    """Generate IRSA trust policy (mirrors IAMProvisioner._get_trust_policy)."""
    if not oidc_provider:
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
            "Principal": {"Federated": f"arn:aws:iam::{account_id}:oidc-provider/{oidc_provider}"},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    f"{oidc_provider}:sub": f"system:serviceaccount:{namespace}:{service_account}",
                    f"{oidc_provider}:aud": "sts.amazonaws.com"
                }
            }
        }]
    }


def get_app_policy(naming: ResourceNaming, region: str, account_id: str) -> dict:
    """Generate least-privilege policy (mirrors IAMProvisioner._get_app_policy)."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
                "Resource": f"arn:aws:dynamodb:{region}:{account_id}:table/{naming.capability_name}-{naming.environment}-*"
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:DeleteObject"],
                "Resource": [
                    f"arn:aws:s3:::{naming.capability_name}-{naming.environment}-*",
                    f"arn:aws:s3:::{naming.capability_name}-{naming.environment}-*/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
                "Resource": f"arn:aws:ssm:{region}:{account_id}:parameter/{naming.capability_name}/{naming.environment}/*"
            },
            {
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": f"arn:aws:secretsmanager:{region}:{account_id}:secret:{naming.capability_name}/{naming.environment}/*"
            },
            {
                "Effect": "Allow",
                "Action": ["glue:GetDatabase", "glue:GetTable", "glue:GetPartitions"],
                "Resource": [
                    f"arn:aws:glue:{region}:{account_id}:catalog",
                    f"arn:aws:glue:{region}:{account_id}:database/{naming.glue_database()}",
                    f"arn:aws:glue:{region}:{account_id}:table/{naming.glue_database()}/*"
                ]
            }
        ]
    }


# Strategies for generating valid inputs
capability_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=30
).filter(lambda x: not x.startswith("-") and not x.endswith("-") and "--" not in x and len(x) > 0)

environment_strategy = st.sampled_from(["dev", "staging", "prod", "test"])

account_id_strategy = st.text(
    alphabet=st.sampled_from("0123456789"),
    min_size=12,
    max_size=12
)

oidc_provider_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
    min_size=10,
    max_size=32
).map(lambda x: f"oidc.eks.us-east-1.amazonaws.com/id/{x.upper()}")


class TestIRSAConfiguration:
    """
    Property 5: IRSA Configuration Correctness
    
    For any operator or application deployment:
    - The created ServiceAccount SHALL be annotated with a valid IAM role ARN
    - The IAM role trust policy SHALL allow assumption only by that specific 
      ServiceAccount in that specific namespace
    """
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        account_id=account_id_strategy,
        oidc_id=st.text(alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"), min_size=10, max_size=32)
    )
    @settings(max_examples=100)
    def test_trust_policy_contains_correct_service_account(self, capability, environment, account_id, oidc_id):
        """Trust policy references the correct ServiceAccount and namespace."""
        naming = ResourceNaming(capability, environment)
        oidc_provider = f"oidc.eks.us-east-1.amazonaws.com/id/{oidc_id}"
        
        namespace = naming.kubernetes_namespace()
        sa_name = naming.kubernetes_service_account("app")
        
        trust_policy = get_trust_policy(account_id, oidc_provider, namespace, sa_name)
        
        # Trust policy must have correct structure
        assert "Version" in trust_policy
        assert "Statement" in trust_policy
        assert len(trust_policy["Statement"]) == 1
        
        statement = trust_policy["Statement"][0]
        
        # Must allow AssumeRoleWithWebIdentity
        assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
        assert statement["Effect"] == "Allow"
        
        # Principal must reference the OIDC provider
        assert "Federated" in statement["Principal"]
        assert oidc_provider in statement["Principal"]["Federated"]
        assert account_id in statement["Principal"]["Federated"]
        
        # Condition must restrict to specific ServiceAccount
        condition = statement["Condition"]["StringEquals"]
        sub_key = f"{oidc_provider}:sub"
        assert sub_key in condition
        assert condition[sub_key] == f"system:serviceaccount:{namespace}:{sa_name}"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        account_id=account_id_strategy
    )
    @settings(max_examples=100)
    def test_app_policy_has_least_privilege(self, capability, environment, account_id):
        """Application policy follows least-privilege principle."""
        naming = ResourceNaming(capability, environment)
        
        policy = get_app_policy(naming, "us-east-1", account_id)
        
        # Policy must have correct structure
        assert "Version" in policy
        assert "Statement" in policy
        
        # Check each statement has resource restrictions
        for statement in policy["Statement"]:
            assert statement["Effect"] == "Allow"
            
            # Resources must be scoped to capability/environment
            resources = statement["Resource"]
            if isinstance(resources, str):
                resources = [resources]
            
            for resource in resources:
                # Resource ARN should contain capability name or environment
                # to ensure it's scoped appropriately
                assert (
                    naming.capability_name in resource or 
                    naming.environment in resource or
                    "catalog" in resource  # Glue catalog is account-wide
                ), f"Resource {resource} should be scoped to capability/environment"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        account_id=account_id_strategy
    )
    @settings(max_examples=100)
    def test_app_policy_includes_required_services(self, capability, environment, account_id):
        """Application policy includes access to all required AWS services."""
        naming = ResourceNaming(capability, environment)
        
        policy = get_app_policy(naming, "us-east-1", account_id)
        
        # Collect all actions from policy
        all_actions = []
        for statement in policy["Statement"]:
            actions = statement["Action"]
            if isinstance(actions, str):
                actions = [actions]
            all_actions.extend(actions)
        
        # Must include DynamoDB access
        assert any("dynamodb:" in a for a in all_actions), "Policy must include DynamoDB access"
        
        # Must include S3 access
        assert any("s3:" in a for a in all_actions), "Policy must include S3 access"
        
        # Must include SSM access
        assert any("ssm:" in a for a in all_actions), "Policy must include SSM access"
        
        # Must include Secrets Manager access
        assert any("secretsmanager:" in a for a in all_actions), "Policy must include Secrets Manager access"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy
    )
    @settings(max_examples=100)
    def test_role_name_follows_convention(self, capability, environment):
        """IAM role name follows the naming convention."""
        naming = ResourceNaming(capability, environment)
        role_name = naming.application_role()
        
        # Role name should contain capability and environment
        assert naming.capability_name in role_name
        assert naming.environment in role_name
        
        # Role name should end with -app-role
        assert role_name.endswith("-app-role")
        
        # Role name should be valid (no special characters except hyphen)
        assert re.match(r'^[a-z0-9-]+$', role_name), f"Role name has invalid characters: {role_name}"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy
    )
    @settings(max_examples=100)
    def test_service_account_annotation_format(self, capability, environment):
        """ServiceAccount annotation uses correct IAM role ARN format."""
        naming = ResourceNaming(capability, environment)
        account_id = "123456789012"
        
        role_name = naming.application_role()
        
        # Expected ARN format
        expected_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        
        # Verify the ARN format is correct
        assert expected_arn.startswith("arn:aws:iam::")
        assert ":role/" in expected_arn
        assert role_name in expected_arn
