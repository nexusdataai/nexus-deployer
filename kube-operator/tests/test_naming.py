"""
Property tests for resource naming conventions.

Feature: pure-eks-deployment
Requirements: 4.6, 4.7
Properties: 7, 8
"""
import re
import sys
import os
import pytest
from hypothesis import given, strategies as st, assume

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nexus_operator.utils.naming import ResourceNaming


# Strategies for generating valid inputs
capability_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=30
).filter(lambda x: not x.startswith("-") and not x.endswith("-") and "--" not in x)

environment_strategy = st.sampled_from(["dev", "staging", "prod", "test"])

category_strategy = st.sampled_from(["aws", "server", "cognito", "wxcc", "s3", "dynamodb", "glue", "cloudwatch"])

resource_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=20
).filter(lambda x: not x.startswith("-") and not x.endswith("-"))

secret_type_strategy = st.sampled_from(["api-keys", "wxcc", "openai", "license", "anthropic", "github"])


class TestSSMNamingConvention:
    """
    Property 7: SSM Parameter Naming Convention
    
    For any capability name C, environment E, category CAT, and resource R:
    - SSM parameter path follows pattern: /{C}/{E}/{CAT}/{R}
    - Path starts with /
    - Path contains exactly 4 segments after splitting by /
    - All segments are non-empty
    """
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        category=category_strategy,
        resource=resource_strategy
    )
    def test_ssm_parameter_follows_pattern(self, capability, environment, category, resource):
        """SSM parameters follow the /{capability}/{env}/{category}/{resource} pattern."""
        naming = ResourceNaming(capability, environment)
        path = naming.ssm_parameter(category, resource)
        
        # Must start with /
        assert path.startswith("/"), f"Path must start with /: {path}"
        
        # Split and validate segments
        segments = path.split("/")
        # First segment is empty due to leading /
        assert segments[0] == "", f"First segment should be empty: {segments}"
        assert len(segments) == 5, f"Should have 5 segments (including empty first): {segments}"
        
        # All non-empty segments should be non-empty
        for i, seg in enumerate(segments[1:], 1):
            assert seg, f"Segment {i} should not be empty: {segments}"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        category=category_strategy,
        resource=resource_strategy
    )
    def test_ssm_parameter_contains_capability_and_env(self, capability, environment, category, resource):
        """SSM parameter path contains the capability name and environment."""
        naming = ResourceNaming(capability, environment)
        path = naming.ssm_parameter(category, resource)
        
        # Path should contain sanitized capability and environment
        sanitized_cap = naming._sanitize_name(capability)
        sanitized_env = naming._sanitize_name(environment)
        
        assert sanitized_cap in path, f"Path should contain capability: {path}"
        assert sanitized_env in path, f"Path should contain environment: {path}"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy
    )
    def test_ssm_prefix_is_valid_prefix(self, capability, environment):
        """SSM parameter prefix is a valid prefix for all parameters."""
        naming = ResourceNaming(capability, environment)
        prefix = naming.ssm_parameter_prefix()
        
        # Generate some parameters and verify prefix
        for category in ["aws", "server", "dynamodb"]:
            for resource in ["region", "table", "bucket"]:
                path = naming.ssm_parameter(category, resource)
                assert path.startswith(prefix.rstrip("/")), f"Path {path} should start with prefix {prefix}"


class TestSecretsNamingConvention:
    """
    Property 8: Secrets Manager Naming Convention
    
    For any capability name C, environment E, and secret type T:
    - Secret name follows pattern: {C}/{E}/{T}
    - Name contains exactly 2 forward slashes
    - All segments are non-empty
    """
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        secret_type=secret_type_strategy
    )
    def test_secret_name_follows_pattern(self, capability, environment, secret_type):
        """Secret names follow the {capability}/{env}/{secret-type} pattern."""
        naming = ResourceNaming(capability, environment)
        name = naming.secret_name(secret_type)
        
        # Should not start with /
        assert not name.startswith("/"), f"Secret name should not start with /: {name}"
        
        # Split and validate segments
        segments = name.split("/")
        assert len(segments) == 3, f"Should have exactly 3 segments: {segments}"
        
        # All segments should be non-empty
        for i, seg in enumerate(segments):
            assert seg, f"Segment {i} should not be empty: {segments}"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy,
        secret_type=secret_type_strategy
    )
    def test_secret_name_contains_capability_and_env(self, capability, environment, secret_type):
        """Secret name contains the capability name and environment."""
        naming = ResourceNaming(capability, environment)
        name = naming.secret_name(secret_type)
        
        sanitized_cap = naming._sanitize_name(capability)
        sanitized_env = naming._sanitize_name(environment)
        
        assert sanitized_cap in name, f"Name should contain capability: {name}"
        assert sanitized_env in name, f"Name should contain environment: {name}"


class TestKubernetesNaming:
    """
    Property 11: Namespace Naming Validation
    
    Kubernetes namespace names must:
    - Be lowercase
    - Contain only alphanumeric characters and hyphens
    - Not start or end with a hyphen
    - Be at most 63 characters
    """
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy
    )
    def test_namespace_is_valid_kubernetes_name(self, capability, environment):
        """Generated namespace names are valid Kubernetes names."""
        naming = ResourceNaming(capability, environment)
        namespace = naming.kubernetes_namespace()
        
        # Must be lowercase
        assert namespace == namespace.lower(), f"Namespace must be lowercase: {namespace}"
        
        # Must match Kubernetes naming pattern
        pattern = r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
        assert re.match(pattern, namespace), f"Namespace must match K8s pattern: {namespace}"
        
        # Must be at most 63 characters
        assert len(namespace) <= 63, f"Namespace must be <= 63 chars: {namespace}"
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy
    )
    def test_service_account_is_valid_kubernetes_name(self, capability, environment):
        """Generated service account names are valid Kubernetes names."""
        naming = ResourceNaming(capability, environment)
        sa_name = naming.kubernetes_service_account("app")
        
        # Must be lowercase
        assert sa_name == sa_name.lower(), f"SA name must be lowercase: {sa_name}"
        
        # Must match Kubernetes naming pattern
        pattern = r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
        assert re.match(pattern, sa_name), f"SA name must match K8s pattern: {sa_name}"


class TestArchitectureCoupling:
    """
    Property 1: Pure EKS Architecture Coupling
    
    This is tested in the frontend, but we verify the naming utility
    generates consistent names for both frontend and backend components.
    """
    
    @given(
        capability=capability_name_strategy,
        environment=environment_strategy
    )
    def test_frontend_backend_share_namespace(self, capability, environment):
        """Frontend and backend deployments use the same namespace."""
        naming = ResourceNaming(capability, environment)
        
        frontend_deploy = naming.kubernetes_deployment("frontend")
        backend_deploy = naming.kubernetes_deployment("backend")
        
        # Both should be in the same namespace (derived from capability-env)
        namespace = naming.kubernetes_namespace()
        
        # Deployment names should contain the namespace prefix
        assert frontend_deploy.startswith(f"{naming.capability_name}-{naming.environment}")
        assert backend_deploy.startswith(f"{naming.capability_name}-{naming.environment}")
