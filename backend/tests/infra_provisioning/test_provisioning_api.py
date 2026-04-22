"""
Integration tests for provisioning API endpoints.

Tests the REST API endpoints for infrastructure provisioning,
verification, and dry-run operations.

Validates: Requirements 11.2, 11.3, 11.4, 12.2
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Import the FastAPI app
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.main import app
from app.routers.provisioning import (
    ProvisioningRequest,
    ProvisioningStatus,
    _provisioning_jobs,
)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear provisioning jobs before each test."""
    _provisioning_jobs.clear()
    yield
    _provisioning_jobs.clear()


@pytest.fixture
def mock_orchestrator():
    """Mock the ProvisioningOrchestrator."""
    with patch('app.services.infra_provisioning.orchestrator.ProvisioningOrchestrator') as mock:
        # Create mock report
        mock_report = MagicMock()
        mock_report.resources = []
        mock_report.success_count = 0
        mock_report.already_existed_count = 0
        mock_report.failed_count = 0
        mock_report.overall_success = True
        
        mock_instance = MagicMock()
        mock_instance.provision_all.return_value = mock_report
        mock_instance.provision_dynamodb.return_value = []
        mock_instance.provision_s3.return_value = []
        mock_instance.provision_ssm.return_value = []
        mock_instance.provision_secrets.return_value = []
        mock_instance.provision_glue.return_value = []
        mock_instance.provision_cloudwatch.return_value = []
        
        mock.return_value = mock_instance
        yield mock


class TestProvisioningEndpoint:
    """Tests for POST /api/provisioning/provision endpoint."""
    
    def test_provision_returns_provisioning_id(self, client, aws_credentials, mock_orchestrator):
        """
        Test that provision endpoint returns a provisioning_id.
        
        Validates: Requirement 11.2 - API endpoint triggers provisioning
        """
        response = client.post(
            "/api/provisioning/provision",
            json={
                "environment": "dev",
                "region": "us-east-1"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "provisioning_id" in data
        assert data["status"] in ["pending", "running"]
        assert data["environment"] == "dev"
        assert data["region"] == "us-east-1"
    
    def test_provision_invalid_environment(self, client):
        """
        Test that invalid environment returns 400 error.
        
        Validates: Requirement 11.2 - Input validation
        """
        response = client.post(
            "/api/provisioning/provision",
            json={
                "environment": "invalid",
                "region": "us-east-1"
            }
        )
        
        assert response.status_code == 400
        assert "Invalid environment" in response.json()["detail"]
    
    def test_provision_with_specific_resource_types(self, client, aws_credentials, mock_orchestrator):
        """
        Test provisioning specific resource types only.
        
        Validates: Requirement 11.3 - Selective provisioning
        """
        response = client.post(
            "/api/provisioning/provision",
            json={
                "environment": "dev",
                "region": "us-east-1",
                "resource_types": ["dynamodb", "s3"]
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "provisioning_id" in data
        # Only dynamodb and s3 should be pending
        assert set(data["resources_pending"]) == {"dynamodb", "s3"}


class TestProvisioningStatusEndpoint:
    """Tests for GET /api/provisioning/{provisioning_id}/status endpoint."""
    
    def test_status_not_found(self, client):
        """
        Test that non-existent provisioning_id returns 404.
        
        Validates: Requirement 12.2 - Status endpoint error handling
        """
        response = client.get("/api/provisioning/nonexistent/status")
        assert response.status_code == 404
    
    def test_status_returns_progress(self, client, aws_credentials, mock_orchestrator):
        """
        Test that status endpoint returns progress information.
        
        Validates: Requirement 12.2 - Progress tracking
        """
        # Start provisioning
        provision_response = client.post(
            "/api/provisioning/provision",
            json={
                "environment": "dev",
                "region": "us-east-1"
            }
        )
        
        provisioning_id = provision_response.json()["provisioning_id"]
        
        # Get status
        status_response = client.get(f"/api/provisioning/{provisioning_id}/status")
        
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["provisioning_id"] == provisioning_id
        assert "progress" in data
        assert 0 <= data["progress"] <= 100
        assert "current_stage" in data
        assert "resources_completed" in data
        assert "resources_pending" in data


class TestVerifyEndpoint:
    """Tests for POST /api/provisioning/verify endpoint."""
    
    def test_verify_returns_verification_report(self, client, aws_credentials):
        """
        Test that verify endpoint returns verification report.
        
        Validates: Requirement 11.3 - Verification endpoint
        """
        with patch('app.services.infra_provisioning.verification_service.VerificationService') as mock_verifier:
            # Create mock verification report
            mock_report = MagicMock()
            mock_report.environment = "dev"
            mock_report.region = "us-east-1"
            mock_report.verified_at = "2024-01-01T00:00:00"
            mock_report.results = []
            mock_report.passed_count = 0
            mock_report.failed_count = 0
            mock_report.all_passed = True
            
            mock_verifier.return_value.verify_all.return_value = mock_report
            
            response = client.post(
                "/api/provisioning/verify",
                json={
                    "environment": "dev",
                    "region": "us-east-1"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["environment"] == "dev"
            assert data["region"] == "us-east-1"
            assert "results" in data
            assert "passed_count" in data
            assert "failed_count" in data
            assert "all_passed" in data
    
    def test_verify_invalid_environment(self, client):
        """
        Test that invalid environment returns 400 error.
        
        Validates: Requirement 11.3 - Input validation
        """
        response = client.post(
            "/api/provisioning/verify",
            json={
                "environment": "invalid",
                "region": "us-east-1"
            }
        )
        
        assert response.status_code == 400


class TestDryRunEndpoint:
    """Tests for POST /api/provisioning/dry-run endpoint."""
    
    def test_dry_run_returns_resources_list(self, client, aws_credentials):
        """
        Test that dry-run endpoint returns list of resources to create.
        
        Validates: Requirement 11.4 - Dry-run endpoint
        """
        with patch('app.services.infra_provisioning.orchestrator.ProvisioningOrchestrator') as mock_orch:
            # Create mock dry-run report
            mock_resource = MagicMock()
            mock_resource.resource_type = MagicMock(value="dynamodb_table")
            mock_resource.resource_name = "call-processing-dev-transformation-system"
            mock_resource.status = MagicMock(value="skipped")
            mock_resource.message = "[DRY RUN] Would create table"
            
            mock_report = MagicMock()
            mock_report.resources = [mock_resource]
            
            mock_orch.return_value.provision_all.return_value = mock_report
            
            response = client.post(
                "/api/provisioning/dry-run",
                json={
                    "environment": "dev",
                    "region": "us-east-1"
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["environment"] == "dev"
            assert data["region"] == "us-east-1"
            assert "resources_to_create" in data
            assert "total_count" in data
            assert data["total_count"] > 0
    
    def test_dry_run_invalid_environment(self, client):
        """
        Test that invalid environment returns 400 error.
        
        Validates: Requirement 11.4 - Input validation
        """
        response = client.post(
            "/api/provisioning/dry-run",
            json={
                "environment": "invalid",
                "region": "us-east-1"
            }
        )
        
        assert response.status_code == 400
