"""
Property-based tests for Glue Provisioner.

Feature: call-processing-infra-provisioning
Property 5: Glue Resource Creation Completeness

*For any* valid environment, when Glue provisioning completes successfully, 
the analytics database SHALL exist, and the wxcc_calls table SHALL exist with 
correct schema, S3 location pointing to the call-data bucket, and year/month/day 
partitioning configured.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.glue_provisioner import GlueProvisioner
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming


class TestGlueProvisionerProperties:
    """Property-based tests for Glue provisioner."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_glue_resource_creation_completeness(self, environment: str):
        """
        Property 5: Glue Resource Creation Completeness
        
        For any valid environment, when Glue provisioning completes successfully,
        the analytics database SHALL exist, and the wxcc_calls table SHALL exist
        with correct schema and partitioning.
        
        **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
        """
        # Arrange
        region = "ap-southeast-1"
        provisioner = GlueProvisioner(environment, region)
        naming = ResourceNaming(environment)
        glue = boto3.client("glue", region_name=region)
        
        # Act
        results = provisioner.provision_all()
        
        # Assert - Database and table should be created
        assert len(results) == 2, "Should create database and table"
        
        # All results should be CREATED (not FAILED)
        for result in results:
            assert result.status in (ResourceStatusType.CREATED, ResourceStatusType.ALREADY_EXISTS), \
                f"Resource {result.resource_name} should be created, got {result.status}"
        
        # Verify database exists
        database_name = naming.glue_database()
        response = glue.get_database(Name=database_name)
        assert response["Database"]["Name"] == database_name
        
        # Verify database follows naming convention
        assert database_name == f"call-processing-{environment}-analytics"
        
        # Verify table exists
        table_name = naming.glue_table()
        response = glue.get_table(DatabaseName=database_name, Name=table_name)
        table = response["Table"]
        
        assert table["Name"] == table_name
        
        # Verify S3 location points to call-data bucket
        expected_location = f"s3://call-processing-{environment}-call-data/call-data/"
        assert table["StorageDescriptor"]["Location"] == expected_location
        
        # Verify partitioning by year, month, day
        partition_keys = [p["Name"] for p in table["PartitionKeys"]]
        assert "year" in partition_keys
        assert "month" in partition_keys
        assert "day" in partition_keys
        
        # Verify Parquet format
        assert "parquet" in table["StorageDescriptor"]["InputFormat"].lower()
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_glue_idempotency(self, environment: str):
        """
        Test that Glue provisioning is idempotent.
        
        Running provisioning twice should result in the second run
        reporting all resources as ALREADY_EXISTS.
        
        **Validates: Requirements 5.5**
        """
        # Arrange
        region = "ap-southeast-1"
        provisioner = GlueProvisioner(environment, region)
        
        # Act - First run
        results1 = provisioner.provision_all()
        
        # Assert - First run should create all resources
        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"
        
        # Act - Second run
        results2 = provisioner.provision_all()
        
        # Assert - Second run should report all as ALREADY_EXISTS
        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestGlueProvisionerUnit:
    """Unit tests for Glue provisioner."""
    
    @mock_aws
    def test_database_exists_returns_false_for_nonexistent_database(self):
        """Test database_exists returns False for non-existent database."""
        provisioner = GlueProvisioner("dev", "ap-southeast-1")
        assert provisioner.database_exists("nonexistent-database") is False
    
    @mock_aws
    def test_database_exists_returns_true_for_existing_database(self):
        """Test database_exists returns True for existing database."""
        provisioner = GlueProvisioner("dev", "ap-southeast-1")
        
        # Create database first
        provisioner.create_database()
        
        # Check it exists
        database_name = provisioner.naming.glue_database()
        assert provisioner.database_exists(database_name) is True
    
    @mock_aws
    def test_table_exists_returns_false_for_nonexistent_table(self):
        """Test table_exists returns False for non-existent table."""
        provisioner = GlueProvisioner("dev", "ap-southeast-1")
        
        # Create database first
        provisioner.create_database()
        
        database_name = provisioner.naming.glue_database()
        assert provisioner.table_exists(database_name, "nonexistent-table") is False
    
    @mock_aws
    def test_table_exists_returns_true_for_existing_table(self):
        """Test table_exists returns True for existing table."""
        provisioner = GlueProvisioner("dev", "ap-southeast-1")
        
        # Create database and table
        provisioner.create_database()
        provisioner.create_wxcc_calls_table()
        
        database_name = provisioner.naming.glue_database()
        table_name = provisioner.naming.glue_table()
        assert provisioner.table_exists(database_name, table_name) is True
    
    @mock_aws
    def test_database_name_follows_naming_convention(self):
        """Test that database name follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = GlueProvisioner(env, "ap-southeast-1")
            result = provisioner.create_database()
            
            expected_name = f"call-processing-{env}-analytics"
            assert result.resource_name == expected_name
    
    @mock_aws
    def test_wxcc_calls_table_has_required_columns(self):
        """Test that wxcc_calls table has required columns."""
        provisioner = GlueProvisioner("dev", "ap-southeast-1")
        glue = boto3.client("glue", region_name="ap-southeast-1")
        
        # Create database and table
        provisioner.create_database()
        provisioner.create_wxcc_calls_table()
        
        # Get table
        database_name = provisioner.naming.glue_database()
        table_name = provisioner.naming.glue_table()
        response = glue.get_table(DatabaseName=database_name, Name=table_name)
        
        columns = [c["Name"] for c in response["Table"]["StorageDescriptor"]["Columns"]]
        
        # Verify required columns exist
        required_columns = ["task_id", "call_id", "agent_id", "start_time", "end_time", "status"]
        for col in required_columns:
            assert col in columns, f"Column {col} should exist"
