"""
Property-based tests for installation tracking.

These tests verify correctness properties using hypothesis for
randomized input generation.
"""
import pytest
import tempfile
import shutil
import time
import gc
from pathlib import Path
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, settings

from app.models.installation import (
    InstallationRecord,
    StackOperationLog,
    StoredCredentials,
    InstallationStatus,
    StackOperationStatus,
    StackOperationType,
)


def safe_cleanup(temp_dir: str, db_manager=None):
    """Safely cleanup temp directory, handling Windows file locking."""
    if db_manager:
        try:
            db_manager.close()
        except Exception:
            pass
    
    # Force garbage collection to release file handles
    gc.collect()
    time.sleep(0.1)
    
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass  # Ignore cleanup errors on Windows


# Custom strategies for generating test data
capability_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=50
).filter(lambda x: x and not x.startswith('-') and not x.endswith('-'))

environment_strategy = st.sampled_from(["dev", "stage", "prod", "test"])
region_strategy = st.sampled_from(["us-east-1", "us-west-2", "eu-west-1", "us-east-1"])
account_id_strategy = st.text(alphabet="0123456789", min_size=12, max_size=12)
strategy_strategy = st.sampled_from(["CLEAN_DEPLOY", "UPDATE_EXISTING"])


class TestInstallationIDUniqueness:
    """
    **Feature: deployment-session-persistence, Property 4: Installation ID Uniqueness and Association**
    
    For any set of deployments, all installation IDs must be unique and
    queries by installation_id must return exactly that deployment's data.
    
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    
    @given(st.lists(capability_name_strategy, min_size=2, max_size=20, unique=True))
    @settings(max_examples=100)
    def test_installation_ids_are_unique(self, capability_names):
        """
        Property: For any set of deployments, all installation IDs must be unique.
        """
        # Import here to avoid circular imports during test collection
        from app.services.installation_tracker import InstallationTracker
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        # Create temporary database for test isolation
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            tracker = InstallationTracker(db_manager)
            
            ids = []
            for name in capability_names:
                install_id = tracker.create_installation(
                    capability_name=name,
                    capability_version="1.0.0",
                    environment="dev",
                    region="us-east-1",
                    account_id="123456789012",
                    strategy="UPDATE_EXISTING",
                    deploy_frontend=True,
                    deploy_backend=True
                )
                ids.append(install_id)
            
            # All IDs must be unique
            assert len(ids) == len(set(ids)), "Installation IDs must be unique"
            
            # Each ID should be a valid UUID format
            import uuid
            for install_id in ids:
                try:
                    uuid.UUID(install_id)
                except ValueError:
                    pytest.fail(f"Installation ID {install_id} is not a valid UUID")
            
        finally:
            safe_cleanup(temp_dir, db_manager)
    
    @given(
        capability_name_strategy,
        environment_strategy,
        region_strategy,
        account_id_strategy,
        strategy_strategy
    )
    @settings(max_examples=50)
    def test_installation_query_returns_correct_data(
        self, capability_name, environment, region, account_id, strategy
    ):
        """
        Property: Queries by installation_id must return exactly that deployment's data.
        """
        from app.services.installation_tracker import InstallationTracker
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            tracker = InstallationTracker(db_manager)
            
            # Create installation
            install_id = tracker.create_installation(
                capability_name=capability_name,
                capability_version="1.0.0",
                environment=environment,
                region=region,
                account_id=account_id,
                strategy=strategy,
                deploy_frontend=True,
                deploy_backend=True
            )
            
            # Query by ID
            result = tracker.get_installation(install_id)
            
            # Verify returned data matches input
            assert result is not None, "Installation should be found"
            assert result["installation_id"] == install_id
            assert result["capability_name"] == capability_name
            assert result["environment"] == environment
            assert result["region"] == region
            assert result["account_id"] == account_id
            assert result["strategy"] == strategy
            
        finally:
            safe_cleanup(temp_dir, db_manager)


class TestStackOperationLogging:
    """
    **Feature: deployment-session-persistence, Property 5: Stack Operation Logging Completeness**
    
    For any stack operation, the log must contain operation type, stack name,
    timestamp at start, and status with error details at completion.
    
    **Validates: Requirements 3.1, 3.2, 3.5**
    """
    
    @given(
        st.text(alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_"), min_size=1, max_size=100),  # stack_name (ASCII only)
        st.sampled_from(["frontend-global", "frontend-cognito", "frontend-regional", 
                        "backend-foundation", "backend-storage", "backend-service"]),
        st.sampled_from(["create", "update", "delete", "skip"]),
        region_strategy
    )
    @settings(max_examples=50)
    def test_stack_operation_log_completeness(
        self, stack_name, stack_type, operation, region
    ):
        """
        Property: Stack operation logs must contain all required fields.
        """
        from app.services.installation_tracker import InstallationTracker
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            tracker = InstallationTracker(db_manager)
            
            # Create installation first
            install_id = tracker.create_installation(
                capability_name="test-capability",
                capability_version="1.0.0",
                environment="dev",
                region=region,
                account_id="123456789012",
                strategy="UPDATE_EXISTING",
                deploy_frontend=True,
                deploy_backend=True
            )
            
            # Log stack operation start
            log_id = tracker.log_stack_operation(
                installation_id=install_id,
                stack_name=stack_name,
                stack_type=stack_type,
                operation=operation,
                status="started",
                region=region
            )
            
            # Verify log contains required fields
            logs = tracker.get_stack_logs(install_id)
            assert len(logs) == 1
            log = logs[0]
            
            assert log["stack_name"] == stack_name
            assert log["stack_type"] == stack_type
            assert log["operation"] == operation
            assert log["status"] == "started"
            assert log["region"] == region
            assert "started_at" in log
            assert log["installation_id"] == install_id
            
            # Update with completion
            tracker.update_stack_operation(
                log_id=log_id,
                status="completed",
                stack_outputs={"OutputKey": "OutputValue"}
            )
            
            # Verify completion data
            logs = tracker.get_stack_logs(install_id)
            log = logs[0]
            assert log["status"] == "completed"
            assert "completed_at" in log
            assert log["stack_outputs"] == {"OutputKey": "OutputValue"}
            
        finally:
            safe_cleanup(temp_dir, db_manager)


class TestQueryFilteringAndSorting:
    """
    **Feature: deployment-session-persistence, Property 8: Query Filtering and Sorting**
    
    For any query to deployment history, results must be filterable by
    capability name, environment, date range, and status, and sorted by
    timestamp descending.
    
    **Validates: Requirements 5.1, 5.2, 5.3**
    """
    
    @given(st.lists(environment_strategy, min_size=3, max_size=10))
    @settings(max_examples=30)
    def test_filter_by_environment(self, environments):
        """
        Property: Filtering by environment returns only matching installations.
        """
        from app.services.installation_tracker import InstallationTracker
        from app.services.tinydb_state_manager import TinyDBStateManager
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            tracker = InstallationTracker(db_manager)
            
            # Create installations with different environments
            for i, env in enumerate(environments):
                tracker.create_installation(
                    capability_name=f"capability-{i}",
                    capability_version="1.0.0",
                    environment=env,
                    region="us-east-1",
                    account_id="123456789012",
                    strategy="UPDATE_EXISTING",
                    deploy_frontend=True,
                    deploy_backend=True
                )
            
            # Filter by each unique environment
            for env in set(environments):
                results = tracker.list_installations(environment=env)
                expected_count = environments.count(env)
                assert len(results) == expected_count, \
                    f"Expected {expected_count} results for env={env}, got {len(results)}"
                
                # All results should have the filtered environment
                for result in results:
                    assert result["environment"] == env
            
        finally:
            safe_cleanup(temp_dir, db_manager)
    
    def test_results_sorted_by_timestamp_descending(self):
        """
        Property: Results are sorted by timestamp in descending order.
        """
        from app.services.installation_tracker import InstallationTracker
        from app.services.tinydb_state_manager import TinyDBStateManager
        import time
        
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test_state.db"
            db_manager = TinyDBStateManager(str(db_path))
            tracker = InstallationTracker(db_manager)
            
            # Create installations with slight time gaps
            for i in range(5):
                tracker.create_installation(
                    capability_name=f"capability-{i}",
                    capability_version="1.0.0",
                    environment="dev",
                    region="us-east-1",
                    account_id="123456789012",
                    strategy="UPDATE_EXISTING",
                    deploy_frontend=True,
                    deploy_backend=True
                )
                time.sleep(0.01)  # Small delay to ensure different timestamps
            
            # List all installations
            results = tracker.list_installations()
            
            # Verify descending order by started_at
            timestamps = [r["started_at"] for r in results]
            assert timestamps == sorted(timestamps, reverse=True), \
                "Results should be sorted by timestamp descending"
            
        finally:
            safe_cleanup(temp_dir, db_manager)
