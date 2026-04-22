"""
Property-based tests for DynamoDB Provisioner.

Feature: call-processing-infra-provisioning
Property 1: DynamoDB Table Creation Completeness

*For any* valid environment (dev, stage, test, prod), when DynamoDB provisioning 
completes successfully, all three required tables (transformation-system, license, 
wxcc-task-tracking) SHALL exist with correct key schemas and GSIs, and all tables 
SHALL be in ACTIVE status.

**Validates: Requirements 1.1, 1.2, 1.3, 1.5**
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.dynamodb_provisioner import DynamoDBProvisioner
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming


class TestDynamoDBProvisionerProperties:
    """Property-based tests for DynamoDB provisioner."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_dynamodb_table_creation_completeness(self, environment: str):
        """
        Property 1: DynamoDB Table Creation Completeness
        
        For any valid environment, when DynamoDB provisioning completes successfully,
        all three required tables SHALL exist with correct key schemas and GSIs,
        and all tables SHALL be in ACTIVE status.
        
        **Validates: Requirements 1.1, 1.2, 1.3, 1.5**
        """
        # Arrange
        region = "us-east-1"
        provisioner = DynamoDBProvisioner(environment, region)
        naming = ResourceNaming(environment)
        dynamodb = boto3.client("dynamodb", region_name=region)
        
        # Act
        results = provisioner.provision_all()
        
        # Assert - All three tables should be created
        assert len(results) == 3, "Should create exactly 3 tables"
        
        # All results should be CREATED (not FAILED)
        for result in results:
            assert result.status in (ResourceStatusType.CREATED, ResourceStatusType.ALREADY_EXISTS), \
                f"Table {result.resource_name} should be created or already exist, got {result.status}"
        
        # Verify transformation-system table exists and is ACTIVE
        table_name = naming.transformation_system_table()
        response = dynamodb.describe_table(TableName=table_name)
        assert response["Table"]["TableStatus"] == "ACTIVE"
        
        # Verify key schema
        key_schema = {k["AttributeName"]: k["KeyType"] for k in response["Table"]["KeySchema"]}
        assert key_schema == {"PK": "HASH", "SK": "RANGE"}
        
        # Verify GSI1 exists
        gsi_names = [gsi["IndexName"] for gsi in response["Table"].get("GlobalSecondaryIndexes", [])]
        assert "GSI1" in gsi_names
        
        # Verify license table exists and is ACTIVE
        table_name = naming.license_table()
        response = dynamodb.describe_table(TableName=table_name)
        assert response["Table"]["TableStatus"] == "ACTIVE"
        
        # Verify key schema
        key_schema = {k["AttributeName"]: k["KeyType"] for k in response["Table"]["KeySchema"]}
        assert key_schema == {"PK": "HASH", "SK": "RANGE"}
        
        # Verify GSIs exist
        gsi_names = [gsi["IndexName"] for gsi in response["Table"].get("GlobalSecondaryIndexes", [])]
        assert "status-index" in gsi_names
        assert "holder-index" in gsi_names
        assert "license-index" in gsi_names
        
        # Verify wxcc-task-tracking table exists and is ACTIVE
        table_name = naming.wxcc_task_tracking_table()
        response = dynamodb.describe_table(TableName=table_name)
        assert response["Table"]["TableStatus"] == "ACTIVE"
        
        # Verify key schema
        key_schema = {k["AttributeName"]: k["KeyType"] for k in response["Table"]["KeySchema"]}
        assert key_schema == {"task_id": "HASH"}


    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_dynamodb_idempotency(self, environment: str):
        """
        Test that DynamoDB provisioning is idempotent.
        
        Running provisioning twice should result in the second run
        reporting all tables as ALREADY_EXISTS.
        
        **Validates: Requirements 1.4**
        """
        # Arrange
        region = "us-east-1"
        provisioner = DynamoDBProvisioner(environment, region)
        
        # Act - First run
        results1 = provisioner.provision_all()
        
        # Assert - First run should create all tables
        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"
        
        # Act - Second run
        results2 = provisioner.provision_all()
        
        # Assert - Second run should report all as ALREADY_EXISTS
        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestDynamoDBProvisionerUnit:
    """Unit tests for DynamoDB provisioner."""
    
    @mock_aws
    def test_table_exists_returns_false_for_nonexistent_table(self):
        """Test table_exists returns False for non-existent table."""
        provisioner = DynamoDBProvisioner("dev", "us-east-1")
        assert provisioner.table_exists("nonexistent-table") is False
    
    @mock_aws
    def test_table_exists_returns_true_for_existing_table(self):
        """Test table_exists returns True for existing table."""
        provisioner = DynamoDBProvisioner("dev", "us-east-1")
        
        # Create a table first
        provisioner.create_transformation_system_table()
        
        # Check it exists
        table_name = provisioner.naming.transformation_system_table()
        assert provisioner.table_exists(table_name) is True
    
    @mock_aws
    def test_get_table_status_returns_none_for_nonexistent_table(self):
        """Test get_table_status returns None for non-existent table."""
        provisioner = DynamoDBProvisioner("dev", "us-east-1")
        assert provisioner.get_table_status("nonexistent-table") is None
    
    @mock_aws
    def test_get_table_status_returns_active_for_existing_table(self):
        """Test get_table_status returns ACTIVE for existing table."""
        provisioner = DynamoDBProvisioner("dev", "us-east-1")
        
        # Create a table first
        provisioner.create_transformation_system_table()
        
        # Check status
        table_name = provisioner.naming.transformation_system_table()
        assert provisioner.get_table_status(table_name) == "ACTIVE"
    
    @mock_aws
    def test_transformation_system_table_has_correct_name(self):
        """Test transformation-system table follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = DynamoDBProvisioner(env, "us-east-1")
            result = provisioner.create_transformation_system_table()
            
            expected_name = f"call-processing-{env}-transformation-system"
            assert result.resource_name == expected_name
    
    @mock_aws
    def test_license_table_has_correct_name(self):
        """Test license table follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = DynamoDBProvisioner(env, "us-east-1")
            result = provisioner.create_license_table()
            
            expected_name = f"call-processing-{env}-license"
            assert result.resource_name == expected_name
    
    @mock_aws
    def test_wxcc_task_tracking_table_has_correct_name(self):
        """Test wxcc-task-tracking table follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = DynamoDBProvisioner(env, "us-east-1")
            result = provisioner.create_wxcc_task_tracking_table()
            
            expected_name = f"call-processing-{env}-wxcc-task-tracking"
            assert result.resource_name == expected_name
