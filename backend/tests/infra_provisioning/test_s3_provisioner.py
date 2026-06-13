"""
Property-based tests for S3 Provisioner.

Feature: call-processing-infra-provisioning
Property 2: S3 Bucket Creation Completeness

*For any* valid environment, when S3 provisioning completes successfully,
all required buckets (wxcc-simulator, sfdc-simulator, oracle-erp-simulator,
sap-simulator, journey-logs, journey-reports) SHALL exist and be
accessible, with the wxcc-simulator bucket containing its required
folder structure.

(The historical call-data bucket was retired along with call processing
as a feature.)
"""

import pytest
from hypothesis import given, settings, strategies as st
from moto import mock_aws
import boto3

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.infra_provisioning.s3_provisioner import S3Provisioner
from app.services.infra_provisioning.models import ResourceStatusType
from app.services.infra_provisioning.naming import ResourceNaming


class TestS3ProvisionerProperties:
    """Property-based tests for S3 provisioner."""

    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_s3_bucket_creation_completeness(self, environment: str):
        """
        Property 2: S3 Bucket Creation Completeness

        For any valid environment, when S3 provisioning completes
        successfully, all required buckets SHALL exist and be accessible,
        with the wxcc-simulator bucket containing its required folder
        structure.

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
        """
        region = "us-east-1"
        provisioner = S3Provisioner(environment, region)
        naming = ResourceNaming(environment)
        s3 = boto3.client("s3", region_name=region)

        results = provisioner.provision_all()

        # All six buckets (4 simulators + 2 journey) should be created
        assert len(results) == 6, "Should create exactly 6 buckets"

        for result in results:
            assert result.status in (ResourceStatusType.CREATED, ResourceStatusType.ALREADY_EXISTS), \
                f"Bucket {result.resource_name} should be created or already exist, got {result.status}"

        expected_buckets = [
            naming.wxcc_simulator_bucket(),
            naming.sfdc_simulator_bucket(),
            naming.oracle_erp_simulator_bucket(),
            naming.sap_simulator_bucket(),
            naming.journey_logs_bucket(),
            naming.journey_reports_bucket(),
        ]

        for bucket_name in expected_buckets:
            s3.head_bucket(Bucket=bucket_name)

        # Verify wxcc-simulator bucket folder structure
        wxcc_bucket = naming.wxcc_simulator_bucket()
        expected_folders = naming.wxcc_simulator_folders()
        for folder in expected_folders:
            response = s3.list_objects_v2(
                Bucket=wxcc_bucket,
                Prefix=folder,
                MaxKeys=1,
            )
            assert response.get("KeyCount", 0) > 0 or "Contents" in response, \
                f"Folder {folder} should exist in {wxcc_bucket}"

    @given(environment=st.sampled_from(["dev", "stage", "test", "prod"]))
    @settings(max_examples=100)
    @mock_aws
    def test_s3_idempotency(self, environment: str):
        """
        Test that S3 provisioning is idempotent.

        Running provisioning twice should result in the second run
        reporting all buckets as ALREADY_EXISTS.

        **Validates: Requirements 2.7**
        """
        region = "us-east-1"
        provisioner = S3Provisioner(environment, region)

        results1 = provisioner.provision_all()

        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"

        results2 = provisioner.provision_all()

        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestS3ProvisionerUnit:
    """Unit tests for S3 provisioner."""

    @mock_aws
    def test_bucket_exists_returns_false_for_nonexistent_bucket(self):
        """Test bucket_exists returns False for non-existent bucket."""
        provisioner = S3Provisioner("dev", "us-east-1")
        assert provisioner.bucket_exists("nonexistent-bucket-12345") is False

    @mock_aws
    def test_bucket_exists_returns_true_for_existing_bucket(self):
        """Test bucket_exists returns True for existing bucket."""
        provisioner = S3Provisioner("dev", "us-east-1")

        provisioner.create_wxcc_simulator_bucket()

        bucket_name = provisioner.naming.wxcc_simulator_bucket()
        assert provisioner.bucket_exists(bucket_name) is True

    @mock_aws
    def test_wxcc_simulator_bucket_has_correct_name(self):
        """Test wxcc-simulator bucket follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = S3Provisioner(env, "us-east-1")
            result = provisioner.create_wxcc_simulator_bucket()

            expected_name = f"call-processing-{env}-wxcc-simulator"
            assert result.resource_name == expected_name

    @mock_aws
    def test_journey_logs_bucket_has_correct_name(self):
        """Test journey-logs bucket follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = S3Provisioner(env, "us-east-1")
            result = provisioner.create_journey_logs_bucket()

            expected_name = f"call-processing-{env}-journey-logs"
            assert result.resource_name == expected_name

    @mock_aws
    def test_journey_reports_bucket_has_correct_name(self):
        """Test journey-reports bucket follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = S3Provisioner(env, "us-east-1")
            result = provisioner.create_journey_reports_bucket()

            expected_name = f"call-processing-{env}-journey-reports"
            assert result.resource_name == expected_name
