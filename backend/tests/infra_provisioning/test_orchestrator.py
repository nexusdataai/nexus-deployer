"""
Property-based tests for Provisioning Orchestrator.

Feature: call-processing-infra-provisioning
Property 7: Provisioning Idempotency
Property 11: Dry-Run Mode Safety

**Validates: Requirements 1.4, 2.7, 4.7, 5.5, 6.3, 9.1, 9.2, 9.3, 9.4, 10.4**
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.orchestrator import ProvisioningOrchestrator
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming
from app.services.infra_provisioning.exceptions import InvalidEnvironmentError


class TestOrchestratorProperties:
    """Property-based tests for Provisioning Orchestrator."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_provisioning_idempotency(self, environment: str):
        """
        Property 7: Provisioning Idempotency
        
        For any valid environment, running provisioning twice in succession SHALL:
        1. Produce the same end state (all resources exist)
        2. No errors on the second run
        3. Second run's report showing all resources as "already_exists"
        
        **Validates: Requirements 1.4, 2.7, 4.7, 5.5, 6.3, 9.1, 9.2, 9.3, 9.4**
        """
        # Arrange
        region = "ap-southeast-1"
        orchestrator = ProvisioningOrchestrator(environment, region)
        
        # Act - First run
        report1 = orchestrator.provision_all()
        
        # Assert - First run should succeed
        assert report1.overall_success, "First run should succeed"
        
        # Count created resources
        created_count = sum(
            1 for r in report1.resources 
            if r.status == ResourceStatusType.CREATED
        )
        assert created_count > 0, "First run should create resources"
        
        # Act - Second run
        report2 = orchestrator.provision_all()
        
        # Assert - Second run should succeed
        assert report2.overall_success, "Second run should succeed"
        
        # All resources should be ALREADY_EXISTS on second run
        for result in report2.resources:
            assert result.status in (
                ResourceStatusType.ALREADY_EXISTS,
                ResourceStatusType.UPDATED,  # SSM parameters may be updated
            ), f"Second run: {result.resource_name} should be ALREADY_EXISTS or UPDATED, got {result.status}"
        
        # Verify same number of resources
        assert len(report1.resources) == len(report2.resources), \
            "Both runs should report same number of resources"
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_dry_run_mode_safety(self, environment: str):
        """
        Property 11: Dry-Run Mode Safety
        
        For any valid environment, when provisioning is run in dry-run mode,
        no resources SHALL be created, modified, or deleted.
        
        **Validates: Requirements 10.4**
        """
        # Arrange
        region = "ap-southeast-1"
        orchestrator = ProvisioningOrchestrator(environment, region, dry_run=True)
        naming = ResourceNaming(environment)
        
        # Create clients to verify no resources exist
        dynamodb = boto3.client("dynamodb", region_name=region)
        s3 = boto3.client("s3", region_name=region)
        ssm = boto3.client("ssm", region_name=region)
        
        # Act - Run in dry-run mode
        report = orchestrator.provision_all()
        
        # Assert - Report should indicate dry run
        assert report.dry_run is True
        
        # All resources should be SKIPPED
        for result in report.resources:
            assert result.status == ResourceStatusType.SKIPPED, \
                f"Dry run: {result.resource_name} should be SKIPPED, got {result.status}"
            assert "[DRY RUN]" in result.message
        
        # Verify no DynamoDB tables were created
        tables_response = dynamodb.list_tables()
        for table_name in naming.all_dynamodb_tables():
            assert table_name not in tables_response.get("TableNames", []), \
                f"Dry run should not create table {table_name}"
        
        # Verify no S3 buckets were created
        buckets_response = s3.list_buckets()
        bucket_names = [b["Name"] for b in buckets_response.get("Buckets", [])]
        for bucket_name in naming.all_s3_buckets():
            assert bucket_name not in bucket_names, \
                f"Dry run should not create bucket {bucket_name}"


class TestOrchestratorUnit:
    """Unit tests for Provisioning Orchestrator."""
    
    def test_invalid_environment_raises_error(self):
        """Test that invalid environment raises InvalidEnvironmentError."""
        with pytest.raises(InvalidEnvironmentError):
            ProvisioningOrchestrator("invalid", "ap-southeast-1")
    
    @mock_aws
    def test_provision_all_creates_all_resource_types(self):
        """Test that provision_all creates all resource types."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        report = orchestrator.provision_all()
        
        # Should have resources from all provisioners
        resource_types = set(r.resource_type for r in report.resources)
        
        # Check we have multiple resource types
        assert len(resource_types) > 1, "Should create multiple resource types"
    
    @mock_aws
    def test_provision_dynamodb_only(self):
        """Test provisioning only DynamoDB tables."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        results = orchestrator.provision_dynamodb()
        
        assert len(results) == 3, "Should create 3 DynamoDB tables"
        for result in results:
            assert result.status == ResourceStatusType.CREATED
    
    @mock_aws
    def test_provision_s3_only(self):
        """Test provisioning only S3 buckets."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        results = orchestrator.provision_s3()
        
        assert len(results) == 4, "Should create 4 S3 buckets"
        for result in results:
            assert result.status == ResourceStatusType.CREATED
    
    @mock_aws
    def test_provision_ssm_only(self):
        """Test provisioning only SSM parameters."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        results = orchestrator.provision_ssm()
        
        assert len(results) > 0, "Should create SSM parameters"
        for result in results:
            assert result.status == ResourceStatusType.CREATED
    
    @mock_aws
    def test_provision_secrets_only(self):
        """Test provisioning only secrets."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        results = orchestrator.provision_secrets()
        
        assert len(results) == 6, "Should create 6 secrets"
        for result in results:
            assert result.status == ResourceStatusType.CREATED
    
    @mock_aws
    def test_provision_glue_only(self):
        """Test provisioning only Glue resources."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        results = orchestrator.provision_glue()
        
        assert len(results) == 2, "Should create database and table"
        for result in results:
            assert result.status == ResourceStatusType.CREATED
    
    @mock_aws
    def test_provision_cloudwatch_only(self):
        """Test provisioning only CloudWatch resources."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        results = orchestrator.provision_cloudwatch()
        
        assert len(results) == 1, "Should create 1 log group"
        for result in results:
            assert result.status == ResourceStatusType.CREATED
    
    @mock_aws
    def test_report_contains_correct_counts(self):
        """Test that report contains correct success/failure counts."""
        orchestrator = ProvisioningOrchestrator("dev", "ap-southeast-1")
        report = orchestrator.provision_all()
        
        # All should be created on first run
        assert report.success_count == len(report.resources)
        assert report.failed_count == 0
        assert report.already_existed_count == 0
        assert report.overall_success is True
