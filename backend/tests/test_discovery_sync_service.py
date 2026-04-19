"""
Unit tests for DiscoverySyncService TinyDB synchronization.

Feature: capability-discovery

Tests cover:
- New capabilities are created in TinyDB
- Existing capabilities are updated
- Missing capabilities are marked as not found in AWS
- Sync is idempotent (running twice produces same result)
- Unique key is (capability_name, environment, account_id)

Validates: Requirements 7.1, 7.2, 7.3, 7.4
"""
import pytest
import tempfile
import os
from datetime import datetime
from typing import List, Dict

from tinydb import TinyDB, Query

from app.services.discovery.discovery_sync_service import DiscoverySyncService
from app.services.discovery.models import (
    DiscoveredCapability,
    DiscoveredStack,
    CapabilityStatus,
)
from app.services.installation_tracker import InstallationTracker
from app.services.tinydb_state_manager import TinyDBStateManager


class MockTinyDBStateManager:
    """Mock TinyDB state manager for testing."""
    
    def __init__(self, db_path: str):
        """Initialize with a temporary database."""
        self.db = TinyDB(db_path)
        self._tables = {}
    
    def get_table(self, name: str):
        """Get or create a table."""
        if name not in self._tables:
            self._tables[name] = self.db.table(name)
        return self._tables[name]
    
    def close(self):
        """Close the database."""
        self.db.close()


class MockInstallationTracker:
    """Mock InstallationTracker for testing with a real TinyDB table."""
    
    def __init__(self, db_manager: MockTinyDBStateManager):
        """Initialize with mock database manager."""
        self.db_manager = db_manager
        self.installations_table = db_manager.get_table("installations")
        self.logs_table = db_manager.get_table("installation_logs")


@pytest.fixture
def temp_db():
    """Create a temporary TinyDB database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        db_path = f.name
    
    db_manager = MockTinyDBStateManager(db_path)
    yield db_manager
    
    db_manager.close()
    os.unlink(db_path)


@pytest.fixture
def mock_tracker(temp_db):
    """Create a mock installation tracker with temporary database."""
    return MockInstallationTracker(temp_db)


@pytest.fixture
def sync_service(mock_tracker):
    """Create a DiscoverySyncService with mock tracker."""
    return DiscoverySyncService(installation_tracker=mock_tracker)


def create_discovered_capability(
    capability_name: str = "TestCapability",
    environment: str = "prod",
    account_id: str = "123456789012",
    landing_zone_id: str = "lz-test-001",
    status: CapabilityStatus = CapabilityStatus.HEALTHY,
    stacks: List[DiscoveredStack] = None,
    version: str = "1.0.0",
    frontend_url: str = None,
    backend_url: str = None,
) -> DiscoveredCapability:
    """Helper to create a DiscoveredCapability for testing."""
    if stacks is None:
        stacks = [
            DiscoveredStack(
                stack_name=f"{capability_name}-{environment}-backend-service",
                stack_type="backend-service",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            )
        ]
    
    return DiscoveredCapability(
        capability_name=capability_name,
        environment=environment,
        landing_zone_id=landing_zone_id,
        account_id=account_id,
        primary_region="us-east-1",
        status=status,
        stacks=stacks,
        missing_stacks=[],
        discovered_at=datetime.utcnow(),
        version=version,
        frontend_url=frontend_url,
        backend_url=backend_url,
    )


# =============================================================================
# Test Class: New Capabilities Are Created
# =============================================================================


class TestNewCapabilitiesCreated:
    """
    **Feature: capability-discovery, Requirement 7.1: Create Installation Records**
    
    Tests that new capabilities discovered in AWS are created in TinyDB.
    
    **Validates: Requirement 7.1**
    """
    
    def test_single_new_capability_is_created(self, sync_service, mock_tracker):
        """Test that a single new capability is created in TinyDB."""
        capability = create_discovered_capability(
            capability_name="NewCapability",
            environment="prod",
            account_id="123456789012",
        )
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 1
        assert stats["updated"] == 0
        assert stats["marked_not_found"] == 0
        
        # Verify record exists in TinyDB
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["capability_name"] == "NewCapability"
        assert records[0]["environment"] == "prod"
        assert records[0]["account_id"] == "123456789012"
        assert records[0]["strategy"] == "DISCOVERED"

    
    def test_multiple_new_capabilities_are_created(self, sync_service, mock_tracker):
        """Test that multiple new capabilities are all created in TinyDB."""
        capabilities = [
            create_discovered_capability(
                capability_name="Capability1",
                environment="prod",
            ),
            create_discovered_capability(
                capability_name="Capability2",
                environment="dev",
            ),
            create_discovered_capability(
                capability_name="Capability3",
                environment="stage",
            ),
        ]
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 3
        assert stats["updated"] == 0
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 3
        
        capability_names = {r["capability_name"] for r in records}
        assert capability_names == {"Capability1", "Capability2", "Capability3"}
    
    def test_created_capability_has_correct_status_mapping(self, sync_service, mock_tracker):
        """Test that capability status is correctly mapped to installation status."""
        capability = create_discovered_capability(
            capability_name="HealthyCapability",
            status=CapabilityStatus.HEALTHY,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["status"] == "completed"

    
    def test_created_capability_has_failed_status(self, sync_service, mock_tracker):
        """Test that failed capability status is correctly mapped."""
        capability = create_discovered_capability(
            capability_name="FailedCapability",
            status=CapabilityStatus.FAILED,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["status"] == "failed"
    
    def test_created_capability_has_in_progress_status(self, sync_service, mock_tracker):
        """Test that in-progress capability status is correctly mapped."""
        capability = create_discovered_capability(
            capability_name="InProgressCapability",
            status=CapabilityStatus.IN_PROGRESS,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["status"] == "running"
    
    def test_created_capability_has_partial_status(self, sync_service, mock_tracker):
        """Test that partial capability status is correctly mapped."""
        capability = create_discovered_capability(
            capability_name="PartialCapability",
            status=CapabilityStatus.PARTIAL,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["status"] == "partial"

    
    def test_created_capability_has_stacks_summary(self, sync_service, mock_tracker):
        """Test that created capability has correct stacks summary."""
        stacks = [
            DiscoveredStack(
                stack_name="Test-prod-backend-foundation",
                stack_type="backend-foundation",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            ),
            DiscoveredStack(
                stack_name="Test-prod-backend-service",
                stack_type="backend-service",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            ),
        ]
        
        capability = create_discovered_capability(
            capability_name="TestCapability",
            stacks=stacks,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["stacks_summary"]["total"] == 2
        assert records[0]["stacks_summary"]["healthy"] == 2
    
    def test_created_capability_has_urls(self, sync_service, mock_tracker):
        """Test that created capability has frontend and backend URLs."""
        capability = create_discovered_capability(
            capability_name="TestCapability",
            frontend_url="https://frontend.example.com",
            backend_url="https://backend.example.com",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["frontend_url"] == "https://frontend.example.com"
        assert records[0]["backend_url"] == "https://backend.example.com"


# =============================================================================
# Test Class: Existing Capabilities Are Updated
# =============================================================================


class TestExistingCapabilitiesUpdated:
    """
    **Feature: capability-discovery, Requirement 7.2: Update Existing Records**
    
    Tests that existing capabilities in TinyDB are updated rather than duplicated.
    
    **Validates: Requirement 7.2**
    """
    
    def test_existing_capability_is_updated_not_duplicated(self, sync_service, mock_tracker):
        """Test that existing capability is updated, not duplicated."""
        # First sync - create the capability
        capability_v1 = create_discovered_capability(
            capability_name="ExistingCapability",
            environment="prod",
            account_id="123456789012",
            version="1.0.0",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_v1],
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - update the capability
        capability_v2 = create_discovered_capability(
            capability_name="ExistingCapability",
            environment="prod",
            account_id="123456789012",
            version="2.0.0",
        )
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=[capability_v2],
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 0
        assert stats["updated"] == 1
        
        # Verify only one record exists
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["capability_version"] == "2.0.0"

    
    def test_existing_capability_status_is_updated(self, sync_service, mock_tracker):
        """Test that existing capability status is updated."""
        # First sync - healthy capability
        capability_healthy = create_discovered_capability(
            capability_name="StatusCapability",
            status=CapabilityStatus.HEALTHY,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_healthy],
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - now failed
        capability_failed = create_discovered_capability(
            capability_name="StatusCapability",
            status=CapabilityStatus.FAILED,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_failed],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["status"] == "failed"
    
    def test_existing_capability_urls_are_updated(self, sync_service, mock_tracker):
        """Test that existing capability URLs are updated."""
        # First sync - no URLs
        capability_no_urls = create_discovered_capability(
            capability_name="UrlCapability",
            frontend_url=None,
            backend_url=None,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_no_urls],
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - with URLs
        capability_with_urls = create_discovered_capability(
            capability_name="UrlCapability",
            frontend_url="https://new-frontend.example.com",
            backend_url="https://new-backend.example.com",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_with_urls],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["frontend_url"] == "https://new-frontend.example.com"
        assert records[0]["backend_url"] == "https://new-backend.example.com"

    
    def test_existing_capability_stacks_summary_is_updated(self, sync_service, mock_tracker):
        """Test that existing capability stacks summary is updated."""
        # First sync - one stack
        stacks_v1 = [
            DiscoveredStack(
                stack_name="Test-prod-backend-service",
                stack_type="backend-service",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            ),
        ]
        capability_v1 = create_discovered_capability(
            capability_name="StacksCapability",
            stacks=stacks_v1,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_v1],
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - more stacks
        stacks_v2 = [
            DiscoveredStack(
                stack_name="Test-prod-backend-foundation",
                stack_type="backend-foundation",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            ),
            DiscoveredStack(
                stack_name="Test-prod-backend-service",
                stack_type="backend-service",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            ),
            DiscoveredStack(
                stack_name="Test-prod-backend-storage",
                stack_type="backend-storage",
                stack_status="CREATE_COMPLETE",
                region="us-east-1",
            ),
        ]
        capability_v2 = create_discovered_capability(
            capability_name="StacksCapability",
            stacks=stacks_v2,
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability_v2],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["stacks_summary"]["total"] == 3


# =============================================================================
# Test Class: Missing Capabilities Are Marked Not Found
# =============================================================================


class TestMissingCapabilitiesMarkedNotFound:
    """
    **Feature: capability-discovery, Requirement 7.4: Mark Not Found**
    
    Tests that capabilities existing in TinyDB but not in AWS are marked as not found.
    
    **Validates: Requirement 7.4**
    """
    
    def test_missing_capability_is_marked_not_found(self, sync_service, mock_tracker):
        """Test that capability not in AWS is marked as not_found_in_aws."""
        # First sync - create capability
        capability = create_discovered_capability(
            capability_name="DisappearingCapability",
            environment="prod",
            account_id="123456789012",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - capability no longer in AWS (empty list)
        stats = sync_service.sync_discovered_capabilities(
            capabilities=[],
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 0
        assert stats["updated"] == 0
        assert stats["marked_not_found"] == 1
        
        # Verify record is marked as not found but preserved
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["status"] == "not_found_in_aws"
        assert records[0]["capability_name"] == "DisappearingCapability"

    
    def test_multiple_missing_capabilities_are_marked(self, sync_service, mock_tracker):
        """Test that multiple missing capabilities are all marked as not found."""
        # First sync - create multiple capabilities
        capabilities = [
            create_discovered_capability(capability_name="Cap1"),
            create_discovered_capability(capability_name="Cap2"),
            create_discovered_capability(capability_name="Cap3"),
        ]
        
        sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - only Cap2 remains
        remaining = [create_discovered_capability(capability_name="Cap2")]
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=remaining,
            landing_zone_id="lz-test-001",
        )
        
        assert stats["updated"] == 1  # Cap2 updated
        assert stats["marked_not_found"] == 2  # Cap1 and Cap3 marked
        
        # Verify statuses
        records = mock_tracker.installations_table.all()
        assert len(records) == 3
        
        not_found_count = sum(1 for r in records if r["status"] == "not_found_in_aws")
        assert not_found_count == 2
    
    def test_not_found_capability_record_is_preserved(self, sync_service, mock_tracker):
        """Test that not found capability record is preserved, not deleted."""
        capability = create_discovered_capability(
            capability_name="PreservedCapability",
            version="1.0.0",
            frontend_url="https://preserved.example.com",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        # Sync with empty list
        sync_service.sync_discovered_capabilities(
            capabilities=[],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        # Original data should be preserved
        assert records[0]["capability_name"] == "PreservedCapability"
        assert records[0]["capability_version"] == "1.0.0"

    
    def test_not_found_capability_can_be_rediscovered(self, sync_service, mock_tracker):
        """Test that a not found capability can be rediscovered and updated."""
        capability = create_discovered_capability(
            capability_name="RediscoveredCapability",
            status=CapabilityStatus.HEALTHY,
        )
        
        # First sync - create
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        # Second sync - mark not found
        sync_service.sync_discovered_capabilities(
            capabilities=[],
            landing_zone_id="lz-test-001",
        )
        
        records = mock_tracker.installations_table.all()
        assert records[0]["status"] == "not_found_in_aws"
        
        # Third sync - rediscover
        capability_rediscovered = create_discovered_capability(
            capability_name="RediscoveredCapability",
            status=CapabilityStatus.HEALTHY,
        )
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=[capability_rediscovered],
            landing_zone_id="lz-test-001",
        )
        
        assert stats["updated"] == 1
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["status"] == "completed"


# =============================================================================
# Test Class: Sync Is Idempotent
# =============================================================================


class TestSyncIsIdempotent:
    """
    **Feature: capability-discovery, Requirement 7.2: Idempotent Sync**
    
    Tests that running sync multiple times with the same data produces the same result.
    
    **Validates: Requirement 7.2**
    """
    
    def test_sync_same_capabilities_twice_is_idempotent(self, sync_service, mock_tracker):
        """Test that syncing same capabilities twice produces same result."""
        capabilities = [
            create_discovered_capability(
                capability_name="IdempotentCap1",
                environment="prod",
            ),
            create_discovered_capability(
                capability_name="IdempotentCap2",
                environment="dev",
            ),
        ]
        
        # First sync
        stats1 = sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        assert stats1["created"] == 2
        
        records_after_first = mock_tracker.installations_table.all()
        
        # Second sync with same data
        stats2 = sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        assert stats2["created"] == 0
        assert stats2["updated"] == 2
        assert stats2["marked_not_found"] == 0
        
        records_after_second = mock_tracker.installations_table.all()
        
        # Same number of records
        assert len(records_after_first) == len(records_after_second)

    
    def test_sync_three_times_produces_consistent_state(self, sync_service, mock_tracker):
        """Test that syncing three times produces consistent state."""
        capability = create_discovered_capability(
            capability_name="ConsistentCapability",
            version="1.0.0",
        )
        
        # Sync three times
        for i in range(3):
            sync_service.sync_discovered_capabilities(
                capabilities=[capability],
                landing_zone_id="lz-test-001",
            )
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["capability_name"] == "ConsistentCapability"
    
    def test_empty_sync_is_idempotent(self, sync_service, mock_tracker):
        """Test that syncing empty list multiple times is idempotent."""
        # Sync empty list three times
        for i in range(3):
            stats = sync_service.sync_discovered_capabilities(
                capabilities=[],
                landing_zone_id="lz-test-001",
            )
            
            assert stats["created"] == 0
            assert stats["updated"] == 0
            assert stats["marked_not_found"] == 0
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 0


# =============================================================================
# Test Class: Unique Key Is (capability_name, environment, account_id)
# =============================================================================


class TestUniqueKeyIdentification:
    """
    **Feature: capability-discovery, Requirement 7.3: Unique Identifier**
    
    Tests that (capability_name, environment, account_id) is used as unique key.
    
    **Validates: Requirement 7.3**
    """
    
    def test_same_capability_different_environments_are_separate(
        self, sync_service, mock_tracker
    ):
        """Test that same capability in different environments creates separate records."""
        capabilities = [
            create_discovered_capability(
                capability_name="MultiEnvCapability",
                environment="dev",
                account_id="123456789012",
            ),
            create_discovered_capability(
                capability_name="MultiEnvCapability",
                environment="prod",
                account_id="123456789012",
            ),
        ]
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 2
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 2
        
        environments = {r["environment"] for r in records}
        assert environments == {"dev", "prod"}

    
    def test_same_capability_different_accounts_are_separate(
        self, sync_service, mock_tracker
    ):
        """Test that same capability in different accounts creates separate records."""
        capabilities = [
            create_discovered_capability(
                capability_name="MultiAccountCapability",
                environment="prod",
                account_id="111111111111",
            ),
            create_discovered_capability(
                capability_name="MultiAccountCapability",
                environment="prod",
                account_id="222222222222",
            ),
        ]
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 2
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 2
        
        account_ids = {r["account_id"] for r in records}
        assert account_ids == {"111111111111", "222222222222"}
    
    def test_different_capabilities_same_env_account_are_separate(
        self, sync_service, mock_tracker
    ):
        """Test that different capabilities in same env/account create separate records."""
        capabilities = [
            create_discovered_capability(
                capability_name="CapabilityA",
                environment="prod",
                account_id="123456789012",
            ),
            create_discovered_capability(
                capability_name="CapabilityB",
                environment="prod",
                account_id="123456789012",
            ),
        ]
        
        stats = sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        assert stats["created"] == 2
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 2

    
    def test_exact_match_updates_correct_record(self, sync_service, mock_tracker):
        """Test that exact key match updates the correct record."""
        # Create multiple capabilities with overlapping names
        capabilities = [
            create_discovered_capability(
                capability_name="SharedName",
                environment="dev",
                account_id="111111111111",
                version="1.0.0",
            ),
            create_discovered_capability(
                capability_name="SharedName",
                environment="prod",
                account_id="111111111111",
                version="1.0.0",
            ),
            create_discovered_capability(
                capability_name="SharedName",
                environment="prod",
                account_id="222222222222",
                version="1.0.0",
            ),
        ]
        
        sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        # Update only one specific capability
        updated_capability = create_discovered_capability(
            capability_name="SharedName",
            environment="prod",
            account_id="111111111111",
            version="2.0.0",  # Updated version
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[updated_capability],
            landing_zone_id="lz-test-001",
        )
        
        # Find the updated record
        records = mock_tracker.installations_table.all()
        
        for record in records:
            if (record["capability_name"] == "SharedName" and
                record["environment"] == "prod" and
                record["account_id"] == "111111111111"):
                assert record["capability_version"] == "2.0.0"
            else:
                # Other records should be marked not found or have original version
                pass


# =============================================================================
# Test Class: Get Discovered Capabilities
# =============================================================================


class TestGetDiscoveredCapabilities:
    """
    **Feature: capability-discovery, Requirement 7.1: Query Discovered Capabilities**
    
    Tests the get_discovered_capabilities method.
    
    **Validates: Requirement 7.1**
    """
    
    def test_get_all_discovered_capabilities(self, sync_service, mock_tracker):
        """Test getting all discovered capabilities."""
        capabilities = [
            create_discovered_capability(capability_name="Cap1"),
            create_discovered_capability(capability_name="Cap2"),
        ]
        
        sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        result = sync_service.get_discovered_capabilities()
        assert len(result) == 2
    
    def test_get_discovered_capabilities_by_landing_zone(self, sync_service, mock_tracker):
        """Test filtering discovered capabilities by landing zone."""
        # Create capabilities in different landing zones
        cap1 = create_discovered_capability(
            capability_name="Cap1",
            landing_zone_id="lz-001",
        )
        cap2 = create_discovered_capability(
            capability_name="Cap2",
            landing_zone_id="lz-002",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[cap1],
            landing_zone_id="lz-001",
        )
        sync_service.sync_discovered_capabilities(
            capabilities=[cap2],
            landing_zone_id="lz-002",
        )
        
        result = sync_service.get_discovered_capabilities(landing_zone_id="lz-001")
        assert len(result) == 1
        assert result[0]["capability_name"] == "Cap1"

    
    def test_get_discovered_capabilities_by_account_id(self, sync_service, mock_tracker):
        """Test filtering discovered capabilities by account ID."""
        capabilities = [
            create_discovered_capability(
                capability_name="Cap1",
                account_id="111111111111",
            ),
            create_discovered_capability(
                capability_name="Cap2",
                account_id="222222222222",
            ),
        ]
        
        sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        result = sync_service.get_discovered_capabilities(account_id="111111111111")
        assert len(result) == 1
        assert result[0]["capability_name"] == "Cap1"
    
    def test_get_discovered_capabilities_excludes_non_discovered(
        self, sync_service, mock_tracker
    ):
        """Test that non-discovered (manually deployed) capabilities are excluded."""
        # Add a discovered capability
        capability = create_discovered_capability(capability_name="DiscoveredCap")
        sync_service.sync_discovered_capabilities(
            capabilities=[capability],
            landing_zone_id="lz-test-001",
        )
        
        # Manually add a non-discovered capability
        mock_tracker.installations_table.insert({
            "installation_id": "manual-123",
            "capability_name": "ManualCap",
            "environment": "prod",
            "account_id": "123456789012",
            "strategy": "CLEAN_DEPLOY",  # Not DISCOVERED
            "status": "completed",
        })
        
        result = sync_service.get_discovered_capabilities()
        assert len(result) == 1
        assert result[0]["capability_name"] == "DiscoveredCap"


# =============================================================================
# Test Class: Landing Zone Isolation
# =============================================================================


class TestLandingZoneIsolation:
    """
    **Feature: capability-discovery, Requirement 7.3, 7.4: Landing Zone Isolation**
    
    Tests that sync operations are isolated to specific landing zones.
    
    **Validates: Requirements 7.3, 7.4**
    """
    
    def test_sync_only_affects_same_landing_zone(self, sync_service, mock_tracker):
        """Test that sync only affects capabilities in the same landing zone."""
        # Create capability in landing zone 1
        cap_lz1 = create_discovered_capability(
            capability_name="CapLZ1",
            landing_zone_id="lz-001",
        )
        sync_service.sync_discovered_capabilities(
            capabilities=[cap_lz1],
            landing_zone_id="lz-001",
        )
        
        # Create capability in landing zone 2
        cap_lz2 = create_discovered_capability(
            capability_name="CapLZ2",
            landing_zone_id="lz-002",
        )
        sync_service.sync_discovered_capabilities(
            capabilities=[cap_lz2],
            landing_zone_id="lz-002",
        )
        
        # Sync empty list for landing zone 1 - should only mark LZ1 caps as not found
        stats = sync_service.sync_discovered_capabilities(
            capabilities=[],
            landing_zone_id="lz-001",
        )
        
        assert stats["marked_not_found"] == 1
        
        # LZ2 capability should be unaffected
        records = mock_tracker.installations_table.all()
        lz2_records = [r for r in records if r["landing_zone_id"] == "lz-002"]
        assert len(lz2_records) == 1
        assert lz2_records[0]["status"] != "not_found_in_aws"

    
    def test_mark_not_found_respects_landing_zone(self, sync_service, mock_tracker):
        """Test that mark not found only affects the specified landing zone."""
        # Create same capability name in two landing zones
        cap_lz1 = create_discovered_capability(
            capability_name="SharedCapability",
            landing_zone_id="lz-001",
            account_id="111111111111",
        )
        cap_lz2 = create_discovered_capability(
            capability_name="SharedCapability",
            landing_zone_id="lz-002",
            account_id="222222222222",
        )
        
        sync_service.sync_discovered_capabilities(
            capabilities=[cap_lz1],
            landing_zone_id="lz-001",
        )
        sync_service.sync_discovered_capabilities(
            capabilities=[cap_lz2],
            landing_zone_id="lz-002",
        )
        
        # Remove from LZ1 only
        sync_service.sync_discovered_capabilities(
            capabilities=[],
            landing_zone_id="lz-001",
        )
        
        records = mock_tracker.installations_table.all()
        
        lz1_record = next(r for r in records if r["landing_zone_id"] == "lz-001")
        lz2_record = next(r for r in records if r["landing_zone_id"] == "lz-002")
        
        assert lz1_record["status"] == "not_found_in_aws"
        assert lz2_record["status"] == "completed"


# =============================================================================
# Test Class: Delete Discovered Capabilities
# =============================================================================


class TestDeleteDiscoveredCapabilities:
    """
    **Feature: capability-discovery, Requirement 7.1: Delete Discovered Capabilities**
    
    Tests the delete_discovered_capabilities method.
    
    **Validates: Requirement 7.1**
    """
    
    def test_delete_all_capabilities_for_landing_zone(self, sync_service, mock_tracker):
        """Test deleting all discovered capabilities for a landing zone."""
        capabilities = [
            create_discovered_capability(capability_name="Cap1"),
            create_discovered_capability(capability_name="Cap2"),
        ]
        
        sync_service.sync_discovered_capabilities(
            capabilities=capabilities,
            landing_zone_id="lz-test-001",
        )
        
        deleted_count = sync_service.delete_discovered_capabilities("lz-test-001")
        
        assert deleted_count == 2
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 0
    
    def test_delete_only_affects_specified_landing_zone(self, sync_service, mock_tracker):
        """Test that delete only affects the specified landing zone."""
        cap_lz1 = create_discovered_capability(capability_name="CapLZ1")
        cap_lz2 = create_discovered_capability(capability_name="CapLZ2")
        
        sync_service.sync_discovered_capabilities(
            capabilities=[cap_lz1],
            landing_zone_id="lz-001",
        )
        sync_service.sync_discovered_capabilities(
            capabilities=[cap_lz2],
            landing_zone_id="lz-002",
        )
        
        deleted_count = sync_service.delete_discovered_capabilities("lz-001")
        
        assert deleted_count == 1
        
        records = mock_tracker.installations_table.all()
        assert len(records) == 1
        assert records[0]["capability_name"] == "CapLZ2"
