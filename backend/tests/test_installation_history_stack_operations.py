"""
Property-based tests for installation history stack operations.

These tests verify correctness properties for the installation_id propagation,
installation log persistence, and stacks summary accuracy.

**Feature: installation-history-stack-operations**
"""
import pytest
import tempfile
import shutil
import time
import gc
from pathlib import Path
from datetime import datetime
from hypothesis import given, strategies as st, settings


def safe_cleanup(temp_dir: str, db_manager=None):
    """Safely cleanup temp directory, handling Windows file locking."""
    if db_manager:
        try:
            db_manager.close()
        except Exception:
            pass
    
    gc.collect()
    time.sleep(0.1)
    
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


# Custom strategies
capability_name_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-"),
    min_size=1,
    max_size=50
).filter(lambda x: x and not x.startswith('-') and not x.endswith('-'))

region_strategy = st.sampled_from(["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"])
log_level_strategy = st.sampled_from(["INFO", "WARNING", "ERROR", "DEBUG"])
log_message_strategy = st.text(min_size=1, max_size=200).filter(
    lambda x: x.strip() and '\r' not in x and '\n' not in x
)


class TestInstallationIDPropagation:
    """
    **Feature: installation-history-stack-operations, Property 1: Installation ID Propagation**
    
    For any deployment with a valid installation_id, the DeploymentOrchestrator
    SHALL receive and store the installation_id, enabling stack operation logging.
    
    **Validates: Requirements 1.1**
    """
    
    def test_orchestrator_receives_installation_id(self):
        """
        Property: DeploymentOrchestrator stores installation_id when provided.
        """
        from app.services.deployment_orchestrator import DeploymentOrchestrator
        
        installation_id = "test-installation-id-12345"
        orchestrator = DeploymentOrchestrator(
            credentials={},
            installation_id=installation_id
        )
        
        assert orchestrator.installation_id == installation_id, \
            "Orchestrator should store the installation_id"
    
    def test_orchestrator_without_installation_id(self):
        """
        Property: DeploymentOrchestrator handles missing installation_id gracefully.
        """
        from app.services.deployment_orchestrator import DeploymentOrchestrator
        
        orchestrator = DeploymentOrchestrator(credentials={})
        
        assert orchestrator.installation_id is None, \
            "Orchestrator should have None installation_id when not provided"
    
    @given(st.uuids())
    @settings(max_examples=50)
    def test_orchestrator_stores_any_valid_uuid(self, uuid_val):
        """
        Property: For any valid UUID, orchestrator stores it correctly.
        """
        from app.services.deployment_orchestrator import DeploymentOrchestrator
        
        installation_id = str(uuid_val)
        orchestrator = DeploymentOrchestrator(
            credentials={},
            installation_id=installation_id
        )
        
        assert orchestrator.installation_id == installation_id


class TestStackOperationLoggingWithInstallationID:
    """
    **Feature: installation-history-stack-operations, Property 2: Stack Operation Logging Completeness**
    
    For any stack operation during deployment, a log entry SHALL be created
    containing stack_name, stack_type, operation, status, and region.
    
    **Validates: Requirements 1.2, 1.3**
    """
    
    @given(
        st.text(alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_"), min_size=1, max_size=50),
        st.sampled_from(["frontend-global", "frontend-cognito", "backend-service"]),
        st.sampled_from(["create", "update"]),
        region_strategy
    )
    @settings(max_examples=50)
    def test_stack_operation_logged_with_installation_id(
        self, stack_name, stack_type, operation, region
    ):
        """
        Property: Stack operations are logged when installation_id is present.
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
                capability_name="test-capability",
                capability_version="1.0.0",
                environment="dev",
                region=region,
                account_id="123456789012",
                strategy="UPDATE_EXISTING",
                deploy_frontend=True,
                deploy_backend=True
            )
            
            # Log stack operation
            log_id = tracker.log_stack_operation(
                installation_id=install_id,
                stack_name=stack_name,
                stack_type=stack_type,
                operation=operation,
                status="started",
                region=region
            )
            
            # Verify log was created with all required fields
            logs = tracker.get_stack_logs(install_id)
            assert len(logs) == 1
            log = logs[0]
            
            assert log["stack_name"] == stack_name
            assert log["stack_type"] == stack_type
            assert log["operation"] == operation
            assert log["status"] == "started"
            assert log["region"] == region
            assert log["installation_id"] == install_id
            assert "started_at" in log
            
        finally:
            safe_cleanup(temp_dir, db_manager)


class TestInstallationLogPersistence:
    """
    **Feature: installation-history-stack-operations, Property 3: Installation Log Persistence**
    
    For any log message added during deployment, the message SHALL be appended
    to the installation log file with timestamp and level.
    
    **Validates: Requirements 2.1, 2.2, 2.4**
    """
    
    @given(log_level_strategy, log_message_strategy)
    @settings(max_examples=50)
    def test_log_entry_format(self, level, message):
        """
        Property: Log entries contain timestamp and level.
        """
        from app.services.installation_log_writer import InstallationLogWriter
        
        temp_dir = tempfile.mkdtemp()
        try:
            logs_dir = Path(temp_dir)
            installation_id = "test-install-123"
            
            writer = InstallationLogWriter(installation_id, logs_dir)
            timestamp = datetime.utcnow()
            
            writer.write(level, message, timestamp)
            
            content = writer.read()
            
            # Verify log entry format
            assert timestamp.isoformat()[:19] in content, "Timestamp should be in log"
            assert f"[{level}]" in content, "Level should be in log"
            assert message in content, "Message should be in log"
            
        finally:
            safe_cleanup(temp_dir)
    
    @given(st.lists(log_message_strategy, min_size=1, max_size=10))
    @settings(max_examples=30)
    def test_multiple_log_entries_appended(self, messages):
        """
        Property: Multiple log entries are appended in order.
        """
        from app.services.installation_log_writer import InstallationLogWriter
        
        temp_dir = tempfile.mkdtemp()
        try:
            logs_dir = Path(temp_dir)
            installation_id = "test-install-456"
            
            writer = InstallationLogWriter(installation_id, logs_dir)
            
            for msg in messages:
                writer.write("INFO", msg, datetime.utcnow())
            
            content = writer.read()
            
            # All messages should be in the log
            for msg in messages:
                assert msg in content, f"Message '{msg}' should be in log"
            
            # Count lines should match number of messages
            lines = [l for l in content.strip().split('\n') if l]
            assert len(lines) == len(messages), \
                f"Expected {len(messages)} log lines, got {len(lines)}"
            
        finally:
            safe_cleanup(temp_dir)


class TestStacksSummaryAccuracy:
    """
    **Feature: installation-history-stack-operations, Property 4: Stacks Summary Accuracy**
    
    For any completed deployment, the stacks_summary counts SHALL equal the count
    of logged operations grouped by status (created, updated, failed, skipped).
    
    **Validates: Requirements 3.1, 3.3**
    """
    
    @given(
        st.lists(
            st.tuples(
                st.sampled_from(["create", "update", "skip"]),
                st.sampled_from(["completed", "failed", "skipped"])
            ),
            min_size=1,
            max_size=10
        )
    )
    @settings(max_examples=50)
    def test_stacks_summary_matches_logged_operations(self, operations):
        """
        Property: Stacks summary counts match logged operation statuses.
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
                capability_name="test-capability",
                capability_version="1.0.0",
                environment="dev",
                region="us-east-1",
                account_id="123456789012",
                strategy="UPDATE_EXISTING",
                deploy_frontend=True,
                deploy_backend=True
            )
            
            # Log operations with various statuses
            expected_summary = {"created": 0, "updated": 0, "failed": 0, "skipped": 0}
            
            for i, (operation, status) in enumerate(operations):
                log_id = tracker.log_stack_operation(
                    installation_id=install_id,
                    stack_name=f"stack-{i}",
                    stack_type="backend-service",
                    operation=operation,
                    status="started",
                    region="us-east-1"
                )
                
                # Update to final status
                tracker.update_stack_operation(log_id=log_id, status=status)
                
                # Calculate expected summary
                if status == "failed":
                    expected_summary["failed"] += 1
                elif status == "skipped" or operation == "skip":
                    expected_summary["skipped"] += 1
                elif operation == "create" and status == "completed":
                    expected_summary["created"] += 1
                elif operation == "update" and status == "completed":
                    expected_summary["updated"] += 1
            
            # Update stacks summary
            tracker.update_stacks_summary(install_id)
            
            # Verify summary matches
            installation = tracker.get_installation(install_id)
            actual_summary = installation.get("stacks_summary", {})
            
            assert actual_summary.get("created", 0) == expected_summary["created"], \
                f"Created count mismatch: {actual_summary.get('created')} != {expected_summary['created']}"
            assert actual_summary.get("updated", 0) == expected_summary["updated"], \
                f"Updated count mismatch: {actual_summary.get('updated')} != {expected_summary['updated']}"
            assert actual_summary.get("failed", 0) == expected_summary["failed"], \
                f"Failed count mismatch: {actual_summary.get('failed')} != {expected_summary['failed']}"
            assert actual_summary.get("skipped", 0) == expected_summary["skipped"], \
                f"Skipped count mismatch: {actual_summary.get('skipped')} != {expected_summary['skipped']}"
            
        finally:
            safe_cleanup(temp_dir, db_manager)
