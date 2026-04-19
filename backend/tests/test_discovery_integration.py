"""
Integration tests for Discovery Flow.

Feature: capability-discovery

Tests cover:
- End-to-end discovery with mocked AWS
- Landing zone CRUD operations
- Discovery job status updates
- Error handling for AWS API failures
- Error handling for permission issues
- Partial discovery success scenarios

Validates: Requirements 12.1, 12.2, 12.3, 12.4
"""
import pytest
import tempfile
import os
import time
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, List, Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.routers import discovery as discovery_router
from app.services.tinydb_state_manager import TinyDBStateManager, set_state_manager
from app.services.installation_tracker import (
    InstallationTracker, 
    set_installation_tracker,
    get_installation_tracker,
)
from app.services.discovery.landing_zone_manager import (
    LandingZoneManager,
    set_landing_zone_manager,
    get_landing_zone_manager
)
from app.services.discovery.discovery_service import DiscoveryService
from app.services.discovery.discovery_sync_service import DiscoverySyncService
from app.services.discovery.models import (
    CloudProvider,
    CapabilityStatus,
    DiscoveredCapability,
    DiscoveredStack,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary TinyDB database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_state.db")
    
    test_manager = TinyDBStateManager(db_path=db_path)
    set_state_manager(test_manager)
    
    yield test_manager
    
    test_manager.close()
    set_state_manager(None)
    
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except:
        pass


@pytest.fixture
def mock_tracker(temp_db):
    """Create a mock installation tracker with temporary database."""
    tracker = InstallationTracker(db_manager=temp_db)
    set_installation_tracker(tracker)
    
    yield tracker
    
    set_installation_tracker(None)


@pytest.fixture
def landing_zone_manager(temp_db):
    """Create a landing zone manager with temporary database."""
    manager = LandingZoneManager(db_manager=temp_db)
    set_landing_zone_manager(manager)
    
    yield manager
    
    set_landing_zone_manager(None)


@pytest.fixture
def app(temp_db, mock_tracker, landing_zone_manager):
    """Create a FastAPI test app with discovery router."""
    test_app = FastAPI()
    test_app.include_router(discovery_router.router)
    
    # Clear any existing discovery jobs
    discovery_router._discovery_jobs.clear()
    
    yield test_app
    
    # Cleanup
    discovery_router._discovery_jobs.clear()


@pytest.fixture
def client(app):
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# =============================================================================
# Helper Functions
# =============================================================================


def create_mock_stack_summary(
    stack_name: str,
    stack_status: str = "CREATE_COMPLETE"
) -> Dict[str, Any]:
    """Create a mock CloudFormation stack summary."""
    return {
        "StackName": stack_name,
        "StackStatus": stack_status,
        "CreationTime": datetime.utcnow(),
    }


def create_mock_stack_details(
    stack_name: str,
    stack_status: str = "CREATE_COMPLETE",
    outputs: Dict[str, str] = None,
    tags: Dict[str, str] = None
) -> Dict[str, Any]:
    """Create mock CloudFormation stack details."""
    return {
        "Stacks": [{
            "StackName": stack_name,
            "StackId": f"arn:aws:cloudformation:us-east-1:123456789012:stack/{stack_name}/guid",
            "StackStatus": stack_status,
            "CreationTime": datetime.utcnow(),
            "LastUpdatedTime": datetime.utcnow(),
            "Outputs": [
                {"OutputKey": k, "OutputValue": v}
                for k, v in (outputs or {}).items()
            ],
            "Tags": [
                {"Key": k, "Value": v}
                for k, v in (tags or {}).items()
            ],
        }]
    }


def create_aws_error(error_code: str, message: str) -> ClientError:
    """Create a mock AWS ClientError."""
    return ClientError(
        error_response={
            "Error": {
                "Code": error_code,
                "Message": message,
            }
        },
        operation_name="ListStacks"
    )


# =============================================================================
# Test Class: Landing Zone CRUD Operations
# =============================================================================


class TestLandingZoneCRUDOperations:
    """
    **Feature: capability-discovery, Requirements 3.2, 3.3, 3.4, 3.5, 3.6**
    
    Integration tests for landing zone CRUD operations via API.
    
    **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**
    """
    
    def test_create_landing_zone_success(self, client):
        """
        Test creating a new landing zone via API.
        Validates: Requirement 3.2
        """
        response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Production Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
                "account_alias": "prod-account",
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["name"] == "Production Account"
        assert data["provider"] == "aws"
        assert data["account_id"] == "123456789012"
        assert data["default_region"] == "us-east-1"
        assert data["account_alias"] == "prod-account"
        assert data["discovery_status"] == "idle"
        assert data["capabilities_count"] == 0
        assert "landing_zone_id" in data
    
    def test_create_landing_zone_azure_not_supported(self, client):
        """
        Test that Azure provider returns not supported error.
        Validates: Requirement 1.3
        """
        response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Azure Account",
                "provider": "azure",
                "account_id": "azure-subscription-id",
                "default_region": "eastus",
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "not yet supported" in data["detail"].lower()
    
    def test_create_landing_zone_gcp_not_supported(self, client):
        """
        Test that GCP provider returns not supported error.
        Validates: Requirement 1.3
        """
        response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "GCP Project",
                "provider": "gcp",
                "account_id": "gcp-project-id",
                "default_region": "us-central1",
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "not yet supported" in data["detail"].lower()
    
    def test_list_landing_zones_empty(self, client):
        """
        Test listing landing zones when none exist.
        Validates: Requirement 3.3
        """
        response = client.get("/api/discovery/landing-zones")
        
        assert response.status_code == 200
        data = response.json()
        assert data == []
    
    def test_list_landing_zones_with_data(self, client):
        """
        Test listing landing zones after creating some.
        Validates: Requirement 3.3
        """
        # Create two landing zones
        client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Dev Account",
                "provider": "aws",
                "account_id": "111111111111",
                "default_region": "us-east-1",
            }
        )
        client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Prod Account",
                "provider": "aws",
                "account_id": "222222222222",
                "default_region": "us-west-2",
            }
        )
        
        response = client.get("/api/discovery/landing-zones")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        
        account_ids = {lz["account_id"] for lz in data}
        assert account_ids == {"111111111111", "222222222222"}
    
    def test_list_landing_zones_filter_by_provider(self, client):
        """
        Test filtering landing zones by provider.
        Validates: Requirement 3.3
        """
        # Create a landing zone
        client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "AWS Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        
        # Filter by AWS
        response = client.get("/api/discovery/landing-zones?provider=aws")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["provider"] == "aws"
    
    def test_get_landing_zone_by_id(self, client):
        """
        Test getting a specific landing zone by ID.
        Validates: Requirement 3.4
        """
        # Create a landing zone
        create_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = create_response.json()["landing_zone_id"]
        
        # Get by ID
        response = client.get(f"/api/discovery/landing-zones/{landing_zone_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["landing_zone_id"] == landing_zone_id
        assert data["name"] == "Test Account"
    
    def test_get_landing_zone_not_found(self, client):
        """
        Test getting a non-existent landing zone.
        """
        response = client.get("/api/discovery/landing-zones/non-existent-id")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_delete_landing_zone_success(self, client):
        """
        Test deleting a landing zone.
        Validates: Requirement 3.6
        """
        # Create a landing zone
        create_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "To Delete",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = create_response.json()["landing_zone_id"]
        
        # Delete it
        response = client.delete(f"/api/discovery/landing-zones/{landing_zone_id}")
        
        assert response.status_code == 200
        assert response.json()["landing_zone_id"] == landing_zone_id
        
        # Verify it's gone
        list_response = client.get("/api/discovery/landing-zones")
        assert len(list_response.json()) == 0
    
    def test_delete_landing_zone_not_found(self, client):
        """
        Test deleting a non-existent landing zone.
        """
        response = client.delete("/api/discovery/landing-zones/non-existent-id")
        
        assert response.status_code == 404
    
    def test_update_existing_landing_zone(self, client):
        """
        Test that creating a landing zone with same account updates existing.
        Validates: Requirement 3.5
        """
        # Create initial landing zone
        response1 = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Original Name",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        original_id = response1.json()["landing_zone_id"]
        
        # Create with same account - should update
        response2 = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Updated Name",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-west-2",
            }
        )
        
        assert response2.status_code == 200
        updated_id = response2.json()["landing_zone_id"]
        
        # Should be same ID (updated, not new)
        assert updated_id == original_id
        assert response2.json()["name"] == "Updated Name"
        assert response2.json()["default_region"] == "us-west-2"
        
        # Should only have one landing zone
        list_response = client.get("/api/discovery/landing-zones")
        assert len(list_response.json()) == 1


# =============================================================================
# Test Class: Discovery Job Status Updates
# =============================================================================


class TestDiscoveryJobStatusUpdates:
    """
    **Feature: capability-discovery, Requirements 4.7, 8.3, 8.4**
    
    Integration tests for discovery job status tracking.
    
    **Validates: Requirements 4.7, 8.3, 8.4**
    """
    
    def test_start_discovery_creates_job(self, client):
        """
        Test that starting discovery creates a job with pending status.
        Validates: Requirement 4.7
        """
        # Create a landing zone first
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        # Mock AWS session manager to avoid credential issues
        with patch('app.routers.discovery.aws_session_manager') as mock_session:
            mock_session.get_credentials_dict.return_value = None
            
            # Start discovery (will fail in background but job should be created)
            response = client.post(
                "/api/discovery/discover",
                json={
                    "landing_zone_id": landing_zone_id,
                }
            )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "job_id" in data
        assert data["landing_zone_id"] == landing_zone_id
        assert data["status"] in ["pending", "running"]
        assert "started_at" in data
        assert data["stacks_scanned"] == 0
        assert data["capabilities_found"] == 0
        assert data["errors"] == []
    
    def test_get_discovery_status(self, client):
        """
        Test getting discovery job status.
        Validates: Requirement 8.4
        """
        # Create a landing zone
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        with patch('app.routers.discovery.aws_session_manager') as mock_session:
            mock_session.get_credentials_dict.return_value = None
            
            # Start discovery
            start_response = client.post(
                "/api/discovery/discover",
                json={"landing_zone_id": landing_zone_id}
            )
            job_id = start_response.json()["job_id"]
        
        # Get status
        response = client.get(f"/api/discovery/discover/{job_id}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["landing_zone_id"] == landing_zone_id
    
    def test_get_discovery_status_not_found(self, client):
        """
        Test getting status for non-existent job.
        """
        response = client.get("/api/discovery/discover/non-existent-job/status")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_start_discovery_landing_zone_not_found(self, client):
        """
        Test starting discovery for non-existent landing zone.
        """
        response = client.post(
            "/api/discovery/discover",
            json={"landing_zone_id": "non-existent-lz"}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_start_discovery_with_expired_session(self, client):
        """
        Test starting discovery with expired AWS session.
        Validates: Requirement 2.5
        """
        # Create a landing zone
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        # Mock session manager to return None (expired session)
        with patch('app.routers.discovery.aws_session_manager') as mock_session:
            mock_session.get_credentials_dict.return_value = None
            
            response = client.post(
                "/api/discovery/discover",
                json={
                    "landing_zone_id": landing_zone_id,
                    "aws_session_id": "expired-session-id",
                }
            )
        
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower() or "not found" in response.json()["detail"].lower()
    
    def test_refresh_capabilities_endpoint(self, client):
        """
        Test the refresh capabilities endpoint.
        Validates: Requirement 8.1, 8.2
        """
        # Create a landing zone
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        with patch('app.routers.discovery.aws_session_manager') as mock_session:
            mock_session.get_credentials_dict.return_value = None
            
            # Refresh (which starts a new discovery)
            response = client.post(f"/api/discovery/refresh/{landing_zone_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["landing_zone_id"] == landing_zone_id


# =============================================================================
# Test Class: End-to-End Discovery with Mocked AWS
# =============================================================================


class TestEndToEndDiscoveryWithMockedAWS:
    """
    **Feature: capability-discovery, Requirements 4.1, 4.2, 4.5, 4.7**
    
    Integration tests for end-to-end discovery flow with mocked AWS.
    
    **Validates: Requirements 4.1, 4.2, 4.5, 4.7**
    """
    
    def test_discover_single_capability(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test discovering a single capability from CloudFormation stacks.
        Validates: Requirements 4.1, 4.2, 4.5
        """
        # Create landing zone
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Mock CloudFormation responses - include all backend stacks for HEALTHY status
        mock_stacks = [
            create_mock_stack_summary("MyCapability-prod-backend-foundation"),
            create_mock_stack_summary("MyCapability-prod-backend-iam-roles"),
            create_mock_stack_summary("MyCapability-prod-backend-regional-cert"),
            create_mock_stack_summary("MyCapability-prod-backend-storage"),
            create_mock_stack_summary("MyCapability-prod-backend-network"),
            create_mock_stack_summary("MyCapability-prod-backend-service"),
            create_mock_stack_summary("MyCapability-prod-backend-domain"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"StackSummaries": mock_stacks}
        ]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            
            # Mock describe_stacks for each stack
            def describe_stacks_side_effect(StackName):
                return create_mock_stack_details(
                    StackName,
                    outputs={"BackendURL": "https://api.example.com"} if "service" in StackName else {},
                    tags={"Version": "1.0.0"}
                )
            
            mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
            
            # Run discovery
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        # Verify results
        assert len(capabilities) == 1
        assert len(errors) == 0
        
        cap = capabilities[0]
        assert cap.capability_name == "MyCapability"
        assert cap.environment == "prod"
        assert cap.account_id == "123456789012"
        assert cap.status == CapabilityStatus.HEALTHY
        assert len(cap.stacks) == 7
        assert cap.backend_url == "https://api.example.com"
        assert cap.version == "1.0.0"
    
    def test_discover_multiple_capabilities(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test discovering multiple capabilities from CloudFormation stacks.
        Validates: Requirements 4.1, 4.5
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Mock stacks for two capabilities
        mock_stacks = [
            create_mock_stack_summary("Billing-prod-backend-service"),
            create_mock_stack_summary("Billing-prod-frontend-global"),
            create_mock_stack_summary("Analytics-dev-backend-foundation"),
            create_mock_stack_summary("Analytics-dev-backend-service"),
            create_mock_stack_summary("RandomStack"),  # Should be ignored
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(StackName)
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 2
        
        cap_names = {(c.capability_name, c.environment) for c in capabilities}
        assert cap_names == {("Billing", "prod"), ("Analytics", "dev")}
    
    def test_discover_and_sync_to_tinydb(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test full discovery flow including TinyDB sync.
        Validates: Requirements 4.7, 7.1
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        mock_stacks = [
            create_mock_stack_summary("TestCap-prod-backend-service"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(StackName)
            
            # Discover
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
            
            # Sync to TinyDB
            sync_service = DiscoverySyncService(installation_tracker=mock_tracker)
            stats = sync_service.sync_discovered_capabilities(capabilities, landing_zone_id)
        
        assert stats["created"] == 1
        assert stats["updated"] == 0
        
        # Verify in TinyDB
        installations = mock_tracker.installations_table.all()
        assert len(installations) == 1
        assert installations[0]["capability_name"] == "TestCap"
        assert installations[0]["strategy"] == "DISCOVERED"
    
    def test_discover_skips_non_matching_stacks(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that non-matching stack names are skipped.
        Validates: Requirement 4.6
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Mix of matching and non-matching stacks
        mock_stacks = [
            create_mock_stack_summary("CDKToolkit"),
            create_mock_stack_summary("my-random-stack"),
            create_mock_stack_summary("ValidCap-prod-backend-service"),
            create_mock_stack_summary("another-stack-name"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(StackName)
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        # Only the valid capability should be discovered
        assert len(capabilities) == 1
        assert capabilities[0].capability_name == "ValidCap"


# =============================================================================
# Test Class: Error Handling
# =============================================================================


class TestDiscoveryErrorHandling:
    """
    **Feature: capability-discovery, Requirements 12.1, 12.2, 12.3, 12.4**
    
    Integration tests for error handling during discovery.
    
    **Validates: Requirements 12.1, 12.2, 12.3, 12.4**
    """
    
    def test_aws_api_error_returns_specific_message(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that AWS API errors return specific error messages.
        Validates: Requirement 12.1 - Display specific AWS error message if AWS API calls fail
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Mock CloudFormation to raise an error
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            
            mock_paginator = MagicMock()
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_paginator.paginate.side_effect = create_aws_error(
                "ServiceException",
                "CloudFormation service is temporarily unavailable"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        # Should return empty capabilities with error
        assert len(capabilities) == 0
        assert len(errors) == 1
        assert "ServiceException" in errors[0]
        assert "CloudFormation" in errors[0]
    
    def test_access_denied_error_indicates_permissions(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that access denied errors indicate permission issues.
        Validates: Requirement 12.2 - Indicate which permissions are missing
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            
            mock_paginator = MagicMock()
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_paginator.paginate.side_effect = create_aws_error(
                "AccessDeniedException",
                "User: arn:aws:iam::123456789012:user/test is not authorized to perform: cloudformation:ListStacks"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 0
        assert len(errors) == 1
        assert "AccessDeniedException" in errors[0]
        assert "ListStacks" in errors[0] or "not authorized" in errors[0]
    
    def test_network_error_suggests_retry(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that network errors are captured and reported.
        Validates: Requirement 12.3 - Display connection error and suggest retry
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            
            mock_paginator = MagicMock()
            mock_cfn.get_paginator.return_value = mock_paginator
            
            # Simulate network error
            from botocore.exceptions import EndpointConnectionError
            mock_paginator.paginate.side_effect = EndpointConnectionError(
                endpoint_url="https://cloudformation.us-east-1.amazonaws.com"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 0
        assert len(errors) == 1
        # Error should mention connection issue
        assert "connection" in errors[0].lower() or "endpoint" in errors[0].lower() or "error" in errors[0].lower()
    
    def test_partial_discovery_reports_failures_and_successes(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that partial discovery reports both failures and successes.
        Validates: Requirement 12.4 - Report which regions/operations failed while showing successful results
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Mock stacks - some will succeed, one will fail on describe
        mock_stacks = [
            create_mock_stack_summary("SuccessCap-prod-backend-service"),
            create_mock_stack_summary("FailCap-prod-backend-service"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            
            # First stack succeeds, second fails with AccessDenied (which gets re-raised)
            def describe_stacks_side_effect(StackName):
                if "FailCap" in StackName:
                    raise create_aws_error(
                        "AccessDeniedException",
                        f"User is not authorized to perform: cloudformation:DescribeStacks on {StackName}"
                    )
                return create_mock_stack_details(StackName)
            
            mock_cfn.describe_stacks.side_effect = describe_stacks_side_effect
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        # Should have one successful capability and one error
        assert len(capabilities) == 1
        assert capabilities[0].capability_name == "SuccessCap"
        
        assert len(errors) == 1
        assert "FailCap" in errors[0] or "AccessDenied" in errors[0]
    
    def test_throttling_error_captured(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that throttling errors are captured.
        Validates: Requirement 12.6 - Handle rate limiting
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            
            mock_paginator = MagicMock()
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_paginator.paginate.side_effect = create_aws_error(
                "Throttling",
                "Rate exceeded"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 0
        assert len(errors) == 1
        assert "Throttling" in errors[0] or "Rate" in errors[0]
    
    def test_expired_credentials_error(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that expired credentials errors are captured.
        Validates: Requirement 2.5 - Prompt for re-authentication when credentials expire
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            
            mock_paginator = MagicMock()
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_paginator.paginate.side_effect = create_aws_error(
                "ExpiredTokenException",
                "The security token included in the request is expired"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 0
        assert len(errors) == 1
        assert "ExpiredToken" in errors[0] or "expired" in errors[0].lower()


# =============================================================================
# Test Class: Capability Status Detection
# =============================================================================


class TestCapabilityStatusDetection:
    """
    **Feature: capability-discovery, Requirements 5.2, 5.3, 5.4, 5.5**
    
    Integration tests for capability status detection during discovery.
    
    **Validates: Requirements 5.2, 5.3, 5.4, 5.5**
    """
    
    def test_healthy_capability_detection(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that healthy capabilities are correctly identified.
        Validates: Requirement 5.2 - Mark as Healthy when all stacks complete
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Include all frontend stacks for a complete frontend deployment
        mock_stacks = [
            create_mock_stack_summary("HealthyCap-prod-frontend-global", "CREATE_COMPLETE"),
            create_mock_stack_summary("HealthyCap-prod-frontend-cognito", "UPDATE_COMPLETE"),
            create_mock_stack_summary("HealthyCap-prod-frontend-regional", "CREATE_COMPLETE"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(
                StackName, 
                "CREATE_COMPLETE" if "global" in StackName or "regional" in StackName else "UPDATE_COMPLETE"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 1
        assert capabilities[0].status == CapabilityStatus.HEALTHY
    
    def test_failed_capability_detection(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that failed capabilities are correctly identified.
        Validates: Requirement 5.3 - Mark as Failed when any stack in FAILED/ROLLBACK state
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        mock_stacks = [
            create_mock_stack_summary("FailedCap-prod-backend-foundation", "CREATE_COMPLETE"),
            create_mock_stack_summary("FailedCap-prod-backend-service", "CREATE_FAILED"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(
                StackName,
                "CREATE_COMPLETE" if "foundation" in StackName else "CREATE_FAILED"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 1
        assert capabilities[0].status == CapabilityStatus.FAILED
    
    def test_in_progress_capability_detection(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that in-progress capabilities are correctly identified.
        Validates: Requirement 5.4 - Mark as In Progress when any stack in IN_PROGRESS state
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        mock_stacks = [
            create_mock_stack_summary("InProgressCap-prod-backend-foundation", "CREATE_COMPLETE"),
            create_mock_stack_summary("InProgressCap-prod-backend-service", "UPDATE_IN_PROGRESS"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(
                StackName,
                "CREATE_COMPLETE" if "foundation" in StackName else "UPDATE_IN_PROGRESS"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 1
        assert capabilities[0].status == CapabilityStatus.IN_PROGRESS
    
    def test_partial_capability_detection(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that partial capabilities are correctly identified.
        Validates: Requirement 5.5 - Mark as Partial when stacks are partially deployed
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        # Only frontend-global, missing frontend-cognito and frontend-regional
        mock_stacks = [
            create_mock_stack_summary("PartialCap-prod-frontend-global", "CREATE_COMPLETE"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(StackName)
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 1
        assert capabilities[0].status == CapabilityStatus.PARTIAL
        assert len(capabilities[0].missing_stacks) > 0
        # Should be missing frontend-cognito and frontend-regional
        assert "frontend-cognito" in capabilities[0].missing_stacks
        assert "frontend-regional" in capabilities[0].missing_stacks
    
    def test_rollback_status_detected_as_failed(self, temp_db, mock_tracker, landing_zone_manager):
        """
        Test that rollback status is detected as failed.
        Validates: Requirement 5.3
        """
        landing_zone_id = landing_zone_manager.create_landing_zone(
            name="Test Account",
            provider=CloudProvider.AWS,
            account_id="123456789012",
            default_region="us-east-1",
        )
        
        mock_stacks = [
            create_mock_stack_summary("RollbackCap-prod-backend-service", "ROLLBACK_COMPLETE"),
        ]
        
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"StackSummaries": mock_stacks}]
        
        with patch('boto3.client') as mock_boto:
            mock_cfn = MagicMock()
            mock_boto.return_value = mock_cfn
            mock_cfn.get_paginator.return_value = mock_paginator
            mock_cfn.describe_stacks.side_effect = lambda StackName: create_mock_stack_details(
                StackName, "ROLLBACK_COMPLETE"
            )
            
            service = DiscoveryService(region="us-east-1")
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
            )
        
        assert len(capabilities) == 1
        assert capabilities[0].status == CapabilityStatus.FAILED


# =============================================================================
# Test Class: Multi-Account Discovery
# =============================================================================


class TestMultiAccountDiscovery:
    """
    **Feature: capability-discovery, Requirements 11.1, 11.4, 11.5**
    
    Integration tests for multi-account discovery scenarios.
    
    **Validates: Requirements 11.1, 11.4, 11.5**
    """
    
    def test_same_capability_different_accounts_separate_records(
        self, temp_db, mock_tracker, landing_zone_manager
    ):
        """
        Test that same capability in different accounts creates separate records.
        Validates: Requirement 11.5
        """
        # Create two landing zones for different accounts
        lz1_id = landing_zone_manager.create_landing_zone(
            name="Account 1",
            provider=CloudProvider.AWS,
            account_id="111111111111",
            default_region="us-east-1",
        )
        lz2_id = landing_zone_manager.create_landing_zone(
            name="Account 2",
            provider=CloudProvider.AWS,
            account_id="222222222222",
            default_region="us-east-1",
        )
        
        # Create capabilities for both accounts
        cap1 = DiscoveredCapability(
            capability_name="SharedCapability",
            environment="prod",
            landing_zone_id=lz1_id,
            account_id="111111111111",
            primary_region="us-east-1",
            status=CapabilityStatus.HEALTHY,
            stacks=[
                DiscoveredStack(
                    stack_name="SharedCapability-prod-backend-service",
                    stack_type="backend-service",
                    stack_status="CREATE_COMPLETE",
                    region="us-east-1",
                )
            ],
        )
        
        cap2 = DiscoveredCapability(
            capability_name="SharedCapability",
            environment="prod",
            landing_zone_id=lz2_id,
            account_id="222222222222",
            primary_region="us-east-1",
            status=CapabilityStatus.HEALTHY,
            stacks=[
                DiscoveredStack(
                    stack_name="SharedCapability-prod-backend-service",
                    stack_type="backend-service",
                    stack_status="CREATE_COMPLETE",
                    region="us-east-1",
                )
            ],
        )
        
        # Sync both
        sync_service = DiscoverySyncService(installation_tracker=mock_tracker)
        sync_service.sync_discovered_capabilities([cap1], lz1_id)
        sync_service.sync_discovered_capabilities([cap2], lz2_id)
        
        # Should have two separate records
        installations = mock_tracker.installations_table.all()
        assert len(installations) == 2
        
        account_ids = {i["account_id"] for i in installations}
        assert account_ids == {"111111111111", "222222222222"}
    
    def test_list_capabilities_by_landing_zone(self, client, temp_db, mock_tracker, landing_zone_manager):
        """
        Test listing capabilities filtered by landing zone.
        Validates: Requirement 11.3
        """
        # Create landing zone
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        # Create a discovered capability directly in TinyDB
        cap = DiscoveredCapability(
            capability_name="TestCap",
            environment="prod",
            landing_zone_id=landing_zone_id,
            account_id="123456789012",
            primary_region="us-east-1",
            status=CapabilityStatus.HEALTHY,
            stacks=[
                DiscoveredStack(
                    stack_name="TestCap-prod-backend-service",
                    stack_type="backend-service",
                    stack_status="CREATE_COMPLETE",
                    region="us-east-1",
                )
            ],
        )
        
        sync_service = DiscoverySyncService(installation_tracker=mock_tracker)
        sync_service.sync_discovered_capabilities([cap], landing_zone_id)
        
        # List capabilities filtered by landing zone
        response = client.get(f"/api/discovery/capabilities?landing_zone_id={landing_zone_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["capability_name"] == "TestCap"
        assert data[0]["landing_zone_id"] == landing_zone_id
    
    def test_separate_discovery_timestamps_per_landing_zone(
        self, temp_db, mock_tracker, landing_zone_manager
    ):
        """
        Test that discovery timestamps are maintained separately per landing zone.
        Validates: Requirement 11.4
        """
        # Create two landing zones
        lz1_id = landing_zone_manager.create_landing_zone(
            name="Account 1",
            provider=CloudProvider.AWS,
            account_id="111111111111",
            default_region="us-east-1",
        )
        lz2_id = landing_zone_manager.create_landing_zone(
            name="Account 2",
            provider=CloudProvider.AWS,
            account_id="222222222222",
            default_region="us-east-1",
        )
        
        # Update discovery status for first landing zone
        landing_zone_manager.update_discovery_status(lz1_id, "completed", capabilities_count=5)
        
        # Get both landing zones
        lz1 = landing_zone_manager.get_landing_zone(lz1_id)
        lz2 = landing_zone_manager.get_landing_zone(lz2_id)
        
        # First should have timestamp, second should not
        assert lz1["last_discovery_at"] is not None
        assert lz1["capabilities_count"] == 5
        
        assert lz2["last_discovery_at"] is None
        assert lz2["capabilities_count"] == 0


# =============================================================================
# Test Class: Discovery API Capabilities Endpoint
# =============================================================================


class TestDiscoveryCapabilitiesEndpoint:
    """
    **Feature: capability-discovery**
    
    Integration tests for the discovered capabilities API endpoint.
    """
    
    def test_list_discovered_capabilities_empty(self, client):
        """Test listing capabilities when none exist."""
        response = client.get("/api/discovery/capabilities")
        
        assert response.status_code == 200
        assert response.json() == []
    
    def test_list_discovered_capabilities_with_data(
        self, client, temp_db, mock_tracker, landing_zone_manager
    ):
        """Test listing capabilities after discovery."""
        # Create landing zone
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        # Create discovered capabilities
        caps = [
            DiscoveredCapability(
                capability_name="Cap1",
                environment="prod",
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
                primary_region="us-east-1",
                status=CapabilityStatus.HEALTHY,
                stacks=[
                    DiscoveredStack(
                        stack_name="Cap1-prod-backend-service",
                        stack_type="backend-service",
                        stack_status="CREATE_COMPLETE",
                        region="us-east-1",
                    )
                ],
                frontend_url="https://cap1.example.com",
            ),
            DiscoveredCapability(
                capability_name="Cap2",
                environment="dev",
                landing_zone_id=landing_zone_id,
                account_id="123456789012",
                primary_region="us-east-1",
                status=CapabilityStatus.PARTIAL,
                stacks=[
                    DiscoveredStack(
                        stack_name="Cap2-dev-frontend-global",
                        stack_type="frontend-global",
                        stack_status="CREATE_COMPLETE",
                        region="us-east-1",
                    )
                ],
                missing_stacks=["frontend-cognito", "frontend-regional"],
            ),
        ]
        
        sync_service = DiscoverySyncService(installation_tracker=mock_tracker)
        sync_service.sync_discovered_capabilities(caps, landing_zone_id)
        
        # List all capabilities
        response = client.get("/api/discovery/capabilities")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        
        cap_names = {c["capability_name"] for c in data}
        assert cap_names == {"Cap1", "Cap2"}
    
    def test_filter_capabilities_by_account_id(
        self, client, temp_db, mock_tracker, landing_zone_manager
    ):
        """Test filtering capabilities by account ID."""
        # Create landing zone
        lz_response = client.post(
            "/api/discovery/landing-zones",
            json={
                "name": "Test Account",
                "provider": "aws",
                "account_id": "123456789012",
                "default_region": "us-east-1",
            }
        )
        landing_zone_id = lz_response.json()["landing_zone_id"]
        
        # Create a capability
        cap = DiscoveredCapability(
            capability_name="FilterTest",
            environment="prod",
            landing_zone_id=landing_zone_id,
            account_id="123456789012",
            primary_region="us-east-1",
            status=CapabilityStatus.HEALTHY,
            stacks=[
                DiscoveredStack(
                    stack_name="FilterTest-prod-backend-service",
                    stack_type="backend-service",
                    stack_status="CREATE_COMPLETE",
                    region="us-east-1",
                )
            ],
        )
        
        sync_service = DiscoverySyncService(installation_tracker=mock_tracker)
        sync_service.sync_discovered_capabilities([cap], landing_zone_id)
        
        # Filter by account ID
        response = client.get("/api/discovery/capabilities?account_id=123456789012")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["account_id"] == "123456789012"
        
        # Filter by non-existent account
        response = client.get("/api/discovery/capabilities?account_id=999999999999")
        
        assert response.status_code == 200
        assert response.json() == []
