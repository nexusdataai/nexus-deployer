"""
Property-based tests for Verification Service.

Feature: call-processing-infra-provisioning
Property 9: Verification Report Completeness

*For any* provisioned environment, the verification report SHALL contain entries 
for all resource types (DynamoDB tables, S3 buckets, SSM parameters, secrets, 
Glue resources, CloudWatch log groups) with accurate status.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8**
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.verification_service import VerificationService
from app.services.infra_provisioning.orchestrator import ProvisioningOrchestrator
from app.services.infra_provisioning.models import (
    ResourceType,
    VerificationStatusType,
)
from app.services.infra_provisioning.naming import ResourceNaming


class TestVerificationServiceProperties:
    """Property-based tests for Verification Service."""
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_verification_report_completeness(self, environment: str):
        """
        Property 9: Verification Report Completeness
        
        For any provisioned environment, the verification report SHALL contain
        entries for all resource types with accurate status.
        
        **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8**
        """
        # Arrange - First provision all resources
        region = "us-east-1"
        orchestrator = ProvisioningOrchestrator(environment, region)
        orchestrator.provision_all()
        
        # Act - Verify all resources
        verifier = VerificationService(environment, region)
        report = verifier.verify_all()
        
        # Assert - Report should be complete
        assert report.environment == environment
        assert report.region == region
        assert report.verified_at is not None
        
        # All resources should be verified
        assert report.overall_success is True
        assert report.failed_count == 0
        
        # Check all resource types are present
        resource_types = set(r.resource_type for r in report.results)
        
        expected_types = {
            ResourceType.DYNAMODB_TABLE,
            ResourceType.S3_BUCKET,
            ResourceType.SSM_PARAMETER,
            ResourceType.SECRET,
            ResourceType.GLUE_DATABASE,
            ResourceType.GLUE_TABLE,
            ResourceType.CLOUDWATCH_LOG_GROUP,
        }
        
        assert expected_types.issubset(resource_types), \
            f"Missing resource types: {expected_types - resource_types}"
        
        # All results should be VERIFIED
        for result in report.results:
            assert result.status == VerificationStatusType.VERIFIED, \
                f"Resource {result.resource_name} should be VERIFIED, got {result.status}"
    
    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_verification_detects_missing_resources(self, environment: str):
        """
        Test that verification correctly detects missing resources.
        
        **Validates: Requirements 7.8**
        """
        # Arrange - Don't provision anything
        region = "us-east-1"
        
        # Act - Verify without provisioning
        verifier = VerificationService(environment, region)
        report = verifier.verify_all()
        
        # Assert - All resources should be NOT_FOUND
        assert report.overall_success is False
        assert report.failed_count > 0
        
        for result in report.results:
            assert result.status == VerificationStatusType.NOT_FOUND, \
                f"Resource {result.resource_name} should be NOT_FOUND, got {result.status}"


class TestVerificationServiceUnit:
    """Unit tests for Verification Service."""
    
    @mock_aws
    def test_verify_dynamodb_tables_returns_correct_count(self):
        """Test that verify_dynamodb_tables returns results for all tables."""
        verifier = VerificationService("dev", "us-east-1")
        results = verifier.verify_dynamodb_tables()
        
        assert len(results) == 3, "Should verify 3 DynamoDB tables"
    
    @mock_aws
    def test_verify_s3_buckets_returns_correct_count(self):
        """Test that verify_s3_buckets returns results for all buckets."""
        verifier = VerificationService("dev", "us-east-1")
        results = verifier.verify_s3_buckets()
        
        assert len(results) == 4, "Should verify 4 S3 buckets"
    
    @mock_aws
    def test_verify_secrets_returns_correct_count(self):
        """Test that verify_secrets returns results for all secrets."""
        verifier = VerificationService("dev", "us-east-1")
        results = verifier.verify_secrets()
        
        assert len(results) == 6, "Should verify 6 secrets"
    
    @mock_aws
    def test_verify_glue_resources_returns_correct_count(self):
        """Test that verify_glue_resources returns results for database and table."""
        verifier = VerificationService("dev", "us-east-1")
        results = verifier.verify_glue_resources()
        
        assert len(results) == 2, "Should verify database and table"
    
    @mock_aws
    def test_verify_cloudwatch_returns_correct_count(self):
        """Test that verify_cloudwatch returns results for log group."""
        verifier = VerificationService("dev", "us-east-1")
        results = verifier.verify_cloudwatch()
        
        assert len(results) == 1, "Should verify 1 log group"
    
    @mock_aws
    def test_report_to_dict_serialization(self):
        """Test that report can be serialized to dict."""
        verifier = VerificationService("dev", "us-east-1")
        report = verifier.verify_all()
        
        report_dict = report.to_dict()
        
        assert "environment" in report_dict
        assert "region" in report_dict
        assert "verified_at" in report_dict
        assert "results" in report_dict
        assert "verified_count" in report_dict
        assert "failed_count" in report_dict
        assert "overall_success" in report_dict
