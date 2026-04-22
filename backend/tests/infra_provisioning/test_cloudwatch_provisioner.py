"""
Property-based tests for CloudWatch Provisioner.

Feature: call-processing-infra-provisioning
Property 6: CloudWatch Log Group Creation with Correct Retention

*For any* valid environment, when CloudWatch provisioning completes successfully, 
the log group SHALL exist with retention policy matching the environment 
(30 days for dev/test, 90 days for stage, 365 days for prod).

**Validates: Requirements 6.1, 6.2**
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.cloudwatch_provisioner import CloudWatchProvisioner
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming


class TestCloudWatchProvisionerProperties:
    """Property-based tests for CloudWatch provisioner."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_cloudwatch_log_group_creation_with_correct_retention(self, environment: str):
        """
        Property 6: CloudWatch Log Group Creation with Correct Retention
        
        For any valid environment, when CloudWatch provisioning completes,
        the log group SHALL exist with correct retention policy.
        
        **Validates: Requirements 6.1, 6.2**
        """
        # Arrange
        region = "us-east-1"
        provisioner = CloudWatchProvisioner(environment, region)
        naming = ResourceNaming(environment)
        logs = boto3.client("logs", region_name=region)
        
        # Expected retention by environment
        expected_retention = {
            "dev": 30,
            "test": 30,
            "stage": 90,
            "prod": 365,
        }
        
        # Act
        results = provisioner.provision_all()
        
        # Assert - Log group should be created
        assert len(results) == 1, "Should create exactly 1 log group"
        
        result = results[0]
        assert result.status in (ResourceStatusType.CREATED, ResourceStatusType.ALREADY_EXISTS), \
            f"Log group should be created, got {result.status}"
        
        # Verify log group exists
        log_group_name = naming.log_group()
        response = logs.describe_log_groups(logGroupNamePrefix=log_group_name)
        
        matching_groups = [g for g in response["logGroups"] if g["logGroupName"] == log_group_name]
        assert len(matching_groups) == 1, f"Log group {log_group_name} should exist"
        
        # Verify log group follows naming convention
        assert log_group_name == f"/aws/call-processing/{environment}"
        
        # Verify retention policy matches environment
        actual_retention = matching_groups[0].get("retentionInDays")
        assert actual_retention == expected_retention[environment], \
            f"Retention should be {expected_retention[environment]} days for {environment}, got {actual_retention}"
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_cloudwatch_idempotency(self, environment: str):
        """
        Test that CloudWatch provisioning is idempotent.
        
        Running provisioning twice should result in the second run
        reporting all resources as ALREADY_EXISTS.
        
        **Validates: Requirements 6.3**
        """
        # Arrange
        region = "us-east-1"
        provisioner = CloudWatchProvisioner(environment, region)
        
        # Act - First run
        results1 = provisioner.provision_all()
        
        # Assert - First run should create log group
        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"
        
        # Act - Second run
        results2 = provisioner.provision_all()
        
        # Assert - Second run should report as ALREADY_EXISTS
        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestCloudWatchProvisionerUnit:
    """Unit tests for CloudWatch provisioner."""
    
    @mock_aws
    def test_log_group_exists_returns_false_for_nonexistent_group(self):
        """Test log_group_exists returns False for non-existent group."""
        provisioner = CloudWatchProvisioner("dev", "us-east-1")
        assert provisioner.log_group_exists("/nonexistent/log/group") is False
    
    @mock_aws
    def test_log_group_exists_returns_true_for_existing_group(self):
        """Test log_group_exists returns True for existing group."""
        provisioner = CloudWatchProvisioner("dev", "us-east-1")
        
        # Create log group first
        provisioner.create_log_group()
        
        # Check it exists
        log_group_name = provisioner.naming.log_group()
        assert provisioner.log_group_exists(log_group_name) is True
    
    @mock_aws
    def test_get_retention_days_returns_correct_values(self):
        """Test get_retention_days returns correct values for each environment."""
        expected = {
            "dev": 30,
            "test": 30,
            "stage": 90,
            "prod": 365,
        }
        
        for env, expected_days in expected.items():
            provisioner = CloudWatchProvisioner(env, "us-east-1")
            assert provisioner.get_retention_days() == expected_days
    
    @mock_aws
    def test_log_group_name_follows_naming_convention(self):
        """Test that log group name follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = CloudWatchProvisioner(env, "us-east-1")
            result = provisioner.create_log_group()
            
            expected_name = f"/aws/call-processing/{env}"
            assert result.resource_name == expected_name
