"""
Property-based tests for Degraded Mode.
Feature: startup-health-check
Property 5: Degraded Mode Consistency
Validates: Requirements 5.4, 6.1, 6.2, 6.5
"""
import pytest
import asyncio
from hypothesis import given, strategies as st, settings
from typing import List, Tuple

from app.services.startup_manager import (
    StartupManager,
    InitializationPhase,
    get_startup_manager,
)


# ============================================
# Test Fixtures
# ============================================

@pytest.fixture(autouse=True)
def reset_startup_manager():
    """Reset the singleton before each test."""
    StartupManager.reset_instance()
    yield
    StartupManager.reset_instance()


# ============================================
# Property 5: Degraded Mode Consistency
# Validates: Requirements 5.4, 6.1, 6.2, 6.5
# ============================================

class TestDegradedModeConsistency:
    """
    Property 5: Degraded Mode Consistency
    
    For any backend in degraded mode, the health endpoint SHALL report 
    `is_degraded: true` with a non-empty `degraded_features` list, and 
    the frontend SHALL display a warning banner.
    """
    
    def test_non_critical_failure_sets_degraded_mode(self):
        """
        When a non-critical component fails, is_degraded should be True.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("optional", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.is_ready == True
        assert manager.state.is_degraded == True
        assert manager.state.phase == InitializationPhase.DEGRADED
    
    def test_degraded_features_list_populated(self):
        """
        When in degraded mode, degraded_features should list failed components.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("feature_a", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=False)
        manager.register_component("feature_b", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert "feature_a" in manager.state.degraded_features
        assert "feature_b" in manager.state.degraded_features
        assert len(manager.state.degraded_features) == 2
    
    def test_readiness_reports_degraded_status(self):
        """
        get_readiness() should report is_degraded and degraded_features.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("optional", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        readiness = manager.get_readiness()
        
        assert readiness["ready"] == True
        assert readiness["is_degraded"] == True
        assert "optional" in readiness["degraded_features"]
    
    @given(st.lists(st.booleans(), min_size=1, max_size=5))
    @settings(max_examples=100, deadline=5000)
    def test_degraded_features_matches_failed_non_critical(self, fail_flags: List[bool]):
        """
        For any combination of non-critical failures, degraded_features
        should exactly match the failed non-critical components.
        """
        StartupManager.reset_instance()
        manager = StartupManager({'max_retries': 0})
        
        expected_degraded = []
        
        # Always have one critical component that succeeds
        manager.register_component("critical", lambda: None, is_critical=True)
        
        for i, should_fail in enumerate(fail_flags):
            name = f"optional_{i}"
            if should_fail:
                manager.register_component(
                    name,
                    lambda: (_ for _ in ()).throw(Exception("fail")),
                    is_critical=False
                )
                expected_degraded.append(name)
            else:
                manager.register_component(name, lambda: None, is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert set(manager.state.degraded_features) == set(expected_degraded)
        
        if expected_degraded:
            assert manager.state.is_degraded == True
        else:
            assert manager.state.is_degraded == False
    
    def test_critical_failure_not_degraded_but_failed(self):
        """
        When a critical component fails, state should be FAILED not DEGRADED.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=True)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.is_ready == False
        assert manager.state.phase == InitializationPhase.FAILED
        # is_degraded should be False because we're in FAILED state
        assert manager.state.is_degraded == False
    
    def test_all_success_not_degraded(self):
        """
        When all components succeed, is_degraded should be False.
        """
        manager = StartupManager()
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("optional", lambda: None, is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.is_ready == True
        assert manager.state.is_degraded == False
        assert manager.state.phase == InitializationPhase.READY
        assert len(manager.state.degraded_features) == 0


class TestDegradedModeComponentStatus:
    """Tests for component status in degraded mode."""
    
    def test_failed_non_critical_has_degraded_status(self):
        """
        Failed non-critical components should have status 'degraded'.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("optional", lambda: (_ for _ in ()).throw(Exception("test error")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.components["optional"].status == "degraded"
        assert manager.state.components["optional"].error == "test error"
    
    def test_failed_critical_has_failed_status(self):
        """
        Failed critical components should have status 'failed'.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: (_ for _ in ()).throw(Exception("critical error")), is_critical=True)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.components["critical"].status == "failed"
        assert manager.state.components["critical"].error == "critical error"
    
    def test_successful_components_have_ready_status(self):
        """
        Successful components should have status 'ready'.
        """
        manager = StartupManager()
        
        manager.register_component("comp1", lambda: None, is_critical=True)
        manager.register_component("comp2", lambda: None, is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.components["comp1"].status == "ready"
        assert manager.state.components["comp2"].status == "ready"


class TestDegradedModeRecovery:
    """Tests for degraded mode recovery scenarios."""
    
    def test_mark_component_failed_updates_degraded_state(self):
        """
        Marking a non-critical component as failed should update degraded state.
        """
        manager = StartupManager()
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("optional", lambda: None, is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        # Initially not degraded
        assert manager.state.is_degraded == False
        
        # Mark optional as failed
        manager.mark_component_failed("optional", "Runtime failure")
        
        assert manager.state.is_degraded == True
        assert "optional" in manager.state.degraded_features
        assert manager.state.components["optional"].status == "degraded"
    
    def test_mark_component_ready_after_failure(self):
        """
        Marking a component as ready should update its status.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("optional", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.components["optional"].status == "degraded"
        
        # Mark as ready (simulating recovery)
        manager.mark_component_ready("optional")
        
        assert manager.state.components["optional"].status == "ready"


class TestTemplateValidationDegradedMode:
    """Tests specific to template validation degraded mode (Requirement 6.1)."""
    
    def test_template_failure_allows_degraded_mode(self):
        """
        Template validation failure should result in degraded mode, not failure.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("database", lambda: None, is_critical=True)
        manager.register_component("templates", lambda: (_ for _ in ()).throw(Exception("Template not found")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.is_ready == True
        assert manager.state.is_degraded == True
        assert "templates" in manager.state.degraded_features


class TestAWSCleanupDegradedMode:
    """Tests specific to AWS cleanup degraded mode (Requirement 6.2)."""
    
    def test_aws_cleanup_failure_allows_degraded_mode(self):
        """
        AWS credential cleanup failure should result in degraded mode, not failure.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("database", lambda: None, is_critical=True)
        manager.register_component("aws_cleanup", lambda: (_ for _ in ()).throw(Exception("Cleanup failed")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.is_ready == True
        assert manager.state.is_degraded == True
        assert "aws_cleanup" in manager.state.degraded_features


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
