"""
Property-based tests for SSM Parameter Provisioner.

Feature: call-processing-infra-provisioning
Property 3: SSM Parameter Creation Completeness

*For any* valid environment, when SSM provisioning completes successfully, 
all required parameters across all categories (aws, server, cognito, wxcc, s3, 
dynamodb, glue, cloudwatch) SHALL exist with correct paths following the 
`/call-processing/{env}/{category}/{name}` convention.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.ssm_provisioner import SSMProvisioner
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming


class TestSSMProvisionerProperties:
    """Property-based tests for SSM provisioner."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_ssm_parameter_creation_completeness(self, environment: str):
        """
        Property 3: SSM Parameter Creation Completeness
        
        For any valid environment, when SSM provisioning completes successfully,
        all required parameters across all categories SHALL exist with correct paths.
        
        **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**
        """
        # Arrange
        region = "ap-southeast-1"
        provisioner = SSMProvisioner(environment, region)
        naming = ResourceNaming(environment)
        ssm = boto3.client("ssm", region_name=region)
        
        # Act
        results = provisioner.provision_all()
        
        # Assert - All parameters should be created
        expected_paths = provisioner.get_all_parameter_paths()
        assert len(results) == len(expected_paths), \
            f"Should create {len(expected_paths)} parameters"
        
        # All results should be CREATED (not FAILED)
        for result in results:
            assert result.status in (
                ResourceStatusType.CREATED, 
                ResourceStatusType.ALREADY_EXISTS,
                ResourceStatusType.UPDATED,
            ), f"Parameter {result.resource_name} should be created, got {result.status}"
        
        # Verify all parameters exist with correct paths
        for path in expected_paths:
            response = ssm.get_parameter(Name=path)
            assert response["Parameter"]["Name"] == path
            
            # Verify path follows naming convention
            assert path.startswith(f"/call-processing/{environment}/"), \
                f"Parameter {path} should follow naming convention"
        
        # Verify specific categories exist
        categories = ["aws", "server", "cognito", "wxcc", "s3", "dynamodb", "glue", "cloudwatch"]
        for category in categories:
            prefix = f"/call-processing/{environment}/{category}/"
            matching = [p for p in expected_paths if p.startswith(prefix)]
            assert len(matching) > 0, f"Should have parameters in category {category}"
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_ssm_idempotency(self, environment: str):
        """
        Test that SSM provisioning is idempotent.
        
        Running provisioning twice should result in the second run
        reporting all parameters as ALREADY_EXISTS.
        """
        # Arrange
        region = "ap-southeast-1"
        provisioner = SSMProvisioner(environment, region)
        
        # Act - First run
        results1 = provisioner.provision_all()
        
        # Assert - First run should create all parameters
        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"
        
        # Act - Second run
        results2 = provisioner.provision_all()
        
        # Assert - Second run should report all as ALREADY_EXISTS
        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestSSMProvisionerUnit:
    """Unit tests for SSM provisioner."""
    
    @mock_aws
    def test_parameter_exists_returns_false_for_nonexistent_parameter(self):
        """Test parameter_exists returns False for non-existent parameter."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        assert provisioner.parameter_exists("/nonexistent/parameter") is False
    
    @mock_aws
    def test_parameter_exists_returns_true_for_existing_parameter(self):
        """Test parameter_exists returns True for existing parameter."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        
        # Create a parameter first
        path = provisioner.naming.ssm_parameter("aws", "region")
        provisioner.create_parameter(path, "ap-southeast-1", "Test")
        
        # Check it exists
        assert provisioner.parameter_exists(path) is True
    
    @mock_aws
    def test_parameter_update_when_value_differs(self):
        """Test that parameter is updated when value differs."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        ssm = boto3.client("ssm", region_name="ap-southeast-1")
        
        path = provisioner.naming.ssm_parameter("server", "log-level")
        
        # Create with initial value
        result1 = provisioner.create_parameter(path, "INFO", "Log level")
        assert result1.status == ResourceStatusType.CREATED
        
        # Update with different value
        result2 = provisioner.create_parameter(path, "DEBUG", "Log level")
        assert result2.status == ResourceStatusType.UPDATED
        
        # Verify value was updated
        response = ssm.get_parameter(Name=path)
        assert response["Parameter"]["Value"] == "DEBUG"
    
    @mock_aws
    def test_all_categories_have_parameters(self):
        """Test that all categories have at least one parameter."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        
        categories = {
            "aws": provisioner.get_aws_parameters(),
            "server": provisioner.get_server_parameters(),
            "cognito": provisioner.get_cognito_parameters(),
            "wxcc": provisioner.get_wxcc_parameters(),
            "s3": provisioner.get_s3_parameters(),
            "dynamodb": provisioner.get_dynamodb_parameters(),
            "glue": provisioner.get_glue_parameters(),
            "cloudwatch": provisioner.get_cloudwatch_parameters(),
        }
        
        for category, params in categories.items():
            assert len(params) > 0, f"Category {category} should have parameters"
    
    @mock_aws
    def test_parameter_paths_follow_naming_convention(self):
        """Test that all parameter paths follow the naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = SSMProvisioner(env, "ap-southeast-1")
            paths = provisioner.get_all_parameter_paths()
            
            for path in paths:
                assert path.startswith(f"/call-processing/{env}/"), \
                    f"Path {path} should start with /call-processing/{env}/"
