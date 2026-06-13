"""
Property-based tests for Glue Provisioner.

Feature: call-processing-infra-provisioning
Property 5: Glue Resource Creation Completeness

*For any* valid environment, when Glue provisioning completes successfully,
the analytics database SHALL exist.

(The historical wxcc_calls table provisioning was removed when call
processing was retired as a feature.)
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
    def test_glue_database_creation_completeness(self, environment: str):
        """
        Property 5 (reduced): Glue Database Creation Completeness

        For any valid environment, when Glue provisioning completes
        successfully, the analytics database SHALL exist.

        **Validates: Requirements 5.1, 5.2**
        """
        region = "us-east-1"
        provisioner = GlueProvisioner(environment, region)
        naming = ResourceNaming(environment)
        glue = boto3.client("glue", region_name=region)

        results = provisioner.provision_all()

        # Only the database should be created (wxcc_calls table retired)
        assert len(results) == 1, "Should create exactly 1 Glue database"

        for result in results:
            assert result.status in (ResourceStatusType.CREATED, ResourceStatusType.ALREADY_EXISTS), \
                f"Resource {result.resource_name} should be created, got {result.status}"

        database_name = naming.glue_database()
        response = glue.get_database(Name=database_name)
        assert response["Database"]["Name"] == database_name
        assert database_name == f"call-processing-{environment}-analytics"

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
        region = "us-east-1"
        provisioner = GlueProvisioner(environment, region)

        results1 = provisioner.provision_all()

        for result in results1:
            assert result.status == ResourceStatusType.CREATED, \
                f"First run: {result.resource_name} should be CREATED"

        results2 = provisioner.provision_all()

        for result in results2:
            assert result.status == ResourceStatusType.ALREADY_EXISTS, \
                f"Second run: {result.resource_name} should be ALREADY_EXISTS"


class TestGlueProvisionerUnit:
    """Unit tests for Glue provisioner."""

    @mock_aws
    def test_database_exists_returns_false_for_nonexistent_database(self):
        """Test database_exists returns False for non-existent database."""
        provisioner = GlueProvisioner("dev", "us-east-1")
        assert provisioner.database_exists("nonexistent-database") is False

    @mock_aws
    def test_database_exists_returns_true_for_existing_database(self):
        """Test database_exists returns True for existing database."""
        provisioner = GlueProvisioner("dev", "us-east-1")

        provisioner.create_database()

        database_name = provisioner.naming.glue_database()
        assert provisioner.database_exists(database_name) is True

    @mock_aws
    def test_database_name_follows_naming_convention(self):
        """Test that database name follows naming convention."""
        for env in ["dev", "stage", "test", "prod"]:
            provisioner = GlueProvisioner(env, "us-east-1")
            result = provisioner.create_database()

            expected_name = f"call-processing-{env}-analytics"
            assert result.resource_name == expected_name
