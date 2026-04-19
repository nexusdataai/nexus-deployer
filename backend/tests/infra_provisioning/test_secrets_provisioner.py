"""
Property-based tests for Secrets Manager Provisioner.

Feature: call-processing-infra-provisioning
Property 4: Secrets Creation Completeness

*For any* valid environment, when secrets provisioning completes successfully, 
all six required secrets (api-keys, wxcc, openai, license, anthropic, github) 
SHALL exist following the `call-processing/{env}/{name}` convention, with 
placeholder values indicating they need to be updated.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8**
"""

import json
import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.secrets_provisioner import SecretsProvisioner
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming


class TestSecretsProvisionerProperties:
    """Property-based tests for Secrets provisioner."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_secrets_creation_completeness(self, environment: str):
        """
        Property 4: Secrets Creation Completeness
        
        For any valid environment, when secrets provisioning completes successfully,
        all six required secrets SHALL exist with placeholder values.
        
        **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8**
        """
        # Arrange
        region = "ap-southeast-1"
        provisioner = SecretsProvisioner(environment, region)
        naming = ResourceNaming(environment)
        secrets_client = boto3.client("secretsmanager", region_name=region)
        
        # Act
        results = provisioner.provision_all()
        
        # Assert - All six secrets should be created
        assert len(results) == 6, "Should create exactly 6 secrets"
        
        # All results should be CREATED (not FAILED)
        for result in results:
            assert result.status in (ResourceStatusType.CREATED, ResourceStatusType.ALREADY_EXISTS), \
                f"Secret {result.resource_name} should be created, got {result.status}"
        
        # Verify all secrets exist
        expected_secrets = [
            naming.secret("api-keys"),
            naming.secret("wxcc"),
            naming.secret("openai"),
            naming.secret("license"),
            naming.secret("anthropic"),
            naming.secret("github"),
        ]
        
        for secret_name in expected_secrets:
            # This should not raise an exception
            response = secrets_client.describe_secret(SecretId=secret_name)
            assert response["Name"] == secret_name
            
            # Verify secret follows naming convention
            assert secret_name.startswith(f"call-processing/{environment}/"), \
                f"Secret {secret_name} should follow naming convention"
        
        # Verify secrets contain placeholder values
        for secret_name in expected_secrets:
            response = secrets_client.get_secret_value(SecretId=secret_name)
            secret_value = json.loads(response["SecretString"])
            
            # All values should be placeholders
            for key, value in secret_value.items():
                assert "PLACEHOLDER" in value, \
                    f"Secret {secret_name}.{key} should contain placeholder value"
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_secrets_idempotency(self, environment: str):
        """
        Test that secrets provisioning is idempotent.
        
        Running provisioning twice should result in the second run
        reporting all secrets as ALREADY_EXISTS.
        
        **Validates: Requirements 4.7**
        """
        # Arrange
        region = "ap-southeast-1"
        provisioner = SecretsProvisioner(environment, region)
        
        # Act - First run
        results1 = provisioner.provision_all()
        
        # Assert - First run should create all secrets
        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"
        
        # Act - Second run
        results2 = provisioner.provision_all()
        
        # Assert - Second run should report all as ALREADY_EXISTS
        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestSecretsProvisionerUnit:
    """Unit tests for Secrets provisioner."""
    
    @mock_aws
    def test_secret_exists_returns_false_for_nonexistent_secret(self):
        """Test secret_exists returns False for non-existent secret."""
        provisioner = SecretsProvisioner("dev", "ap-southeast-1")
        assert provisioner.secret_exists("nonexistent-secret") is False
    
    @mock_aws
    def test_secret_exists_returns_true_for_existing_secret(self):
        """Test secret_exists returns True for existing secret."""
        provisioner = SecretsProvisioner("dev", "ap-southeast-1")
        
        # Create a secret first
        secret_name = provisioner.naming.secret("api-keys")
        provisioner.create_secret(secret_name, {"API_KEY": "test"}, "Test")
        
        # Check it exists
        assert provisioner.secret_exists(secret_name) is True
    
    @mock_aws
    def test_secret_names_follow_naming_convention(self):
        """Test that all secret names follow the naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = SecretsProvisioner(env, "ap-southeast-1")
            names = provisioner.get_all_secret_names()
            
            for name in names:
                assert name.startswith(f"call-processing/{env}/"), \
                    f"Secret {name} should start with call-processing/{env}/"
    
    @mock_aws
    def test_all_required_secrets_are_defined(self):
        """Test that all required secrets are defined."""
        provisioner = SecretsProvisioner("dev", "ap-southeast-1")
        names = provisioner.get_all_secret_names()
        
        required = ["api-keys", "wxcc", "openai", "license", "anthropic", "github"]
        for req in required:
            expected = f"call-processing/dev/{req}"
            assert expected in names, f"Secret {expected} should be defined"
    
    @mock_aws
    def test_license_secret_has_both_keys(self):
        """Test that license secret contains both public and private keys."""
        provisioner = SecretsProvisioner("dev", "ap-southeast-1")
        secrets = provisioner.get_placeholder_secrets()
        
        license_name = provisioner.naming.secret("license")
        license_value, _ = secrets[license_name]
        
        assert "LICENSE_PUBLIC_KEY" in license_value
        assert "LICENSE_PRIVATE_KEY" in license_value
    
    @mock_aws
    def test_anthropic_secret_has_both_keys(self):
        """Test that anthropic secret contains both API keys."""
        provisioner = SecretsProvisioner("dev", "ap-southeast-1")
        secrets = provisioner.get_placeholder_secrets()
        
        anthropic_name = provisioner.naming.secret("anthropic")
        anthropic_value, _ = secrets[anthropic_name]
        
        assert "CLAUDE_API_KEY" in anthropic_value
        assert "ANTHROPIC_API_KEY" in anthropic_value
