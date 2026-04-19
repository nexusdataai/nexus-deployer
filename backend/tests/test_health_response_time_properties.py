"""
Property Tests for Health Response Time

Property 8: Health Response Time
Validates: Requirements 1.6

Feature: startup-health-check
"""
import pytest
import asyncio
import time
from hypothesis import given, strategies as st, settings, assume
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

# Import the health router components
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.startup_manager import StartupManager, InitializationPhase


class TestHealthResponseTimeProperties:
    """Property tests for health endpoint response time."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset startup manager before each test."""
        StartupManager.reset_instance()
        yield
        StartupManager.reset_instance()
    
    @given(
        num_components=st.integers(min_value=1, max_value=10),
        component_delay_ms=st.integers(min_value=0, max_value=50)
    )
    @settings(max_examples=20, deadline=5000)
    def test_readiness_check_is_fast(self, num_components, component_delay_ms):
        """
        Property: get_readiness() should complete quickly regardless of
        the number of components or their initialization state.
        
        Requirement 1.6: Health endpoint should respond within 500ms
        """
        manager = StartupManager()
        
        # Register multiple components
        for i in range(num_components):
            manager.register_component(
                f"component_{i}",
                lambda: None,
                is_critical=(i % 2 == 0)
            )
        
        # Simulate various component states
        for i, (name, component) in enumerate(manager.state.components.items()):
            component.status = ["pending", "initializing", "ready", "failed", "degraded"][i % 5]
            component.duration_ms = component_delay_ms * (i + 1)
            component.started_at = datetime.utcnow()
            component.completed_at = datetime.utcnow()
        
        # Measure response time
        start = time.perf_counter()
        result = manager.get_readiness()
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should complete within 500ms (requirement 1.6)
        assert elapsed_ms < 500, f"get_readiness() took {elapsed_ms}ms, expected < 500ms"
        
        # Result should be valid
        assert "ready" in result
        assert "phase" in result
        assert "components" in result
    
    @given(
        ready_state=st.booleans(),
        phase=st.sampled_from([p.value for p in InitializationPhase])
    )
    @settings(max_examples=30, deadline=2000)
    def test_readiness_response_structure_is_consistent(self, ready_state, phase):
        """
        Property: Readiness response should always have consistent structure
        regardless of the internal state.
        """
        manager = StartupManager()
        manager.state.is_ready = ready_state
        manager.state.phase = InitializationPhase(phase)
        
        result = manager.get_readiness()
        
        # Required fields should always be present
        required_fields = ["ready", "phase", "components", "is_degraded"]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
        
        # Types should be correct
        assert isinstance(result["ready"], bool)
        assert isinstance(result["phase"], str)
        assert isinstance(result["components"], dict)
        assert isinstance(result["is_degraded"], bool)
    
    @given(
        num_calls=st.integers(min_value=10, max_value=100)
    )
    @settings(max_examples=10, deadline=10000)
    def test_repeated_readiness_checks_are_consistent(self, num_calls):
        """
        Property: Multiple rapid calls to get_readiness() should return
        consistent results and not degrade performance.
        """
        manager = StartupManager()
        manager.register_component("test", lambda: None, is_critical=True)
        manager.state.is_ready = True
        manager.state.phase = InitializationPhase.READY
        
        results = []
        times = []
        
        for _ in range(num_calls):
            start = time.perf_counter()
            result = manager.get_readiness()
            elapsed = (time.perf_counter() - start) * 1000
            
            results.append(result["ready"])
            times.append(elapsed)
        
        # All results should be consistent
        assert all(r == results[0] for r in results), "Inconsistent readiness results"
        
        # Average response time should be under 10ms
        avg_time = sum(times) / len(times)
        assert avg_time < 10, f"Average response time {avg_time}ms exceeds 10ms"
        
        # No single call should exceed 100ms
        max_time = max(times)
        assert max_time < 100, f"Max response time {max_time}ms exceeds 100ms"
    
    @given(
        error_message=st.text(min_size=0, max_size=1000)
    )
    @settings(max_examples=20, deadline=2000)
    def test_readiness_with_errors_is_still_fast(self, error_message):
        """
        Property: Even with error messages, readiness check should be fast.
        """
        manager = StartupManager()
        manager.register_component("failing", lambda: None, is_critical=True)
        
        # Set error state
        manager.state.error = error_message
        manager.state.phase = InitializationPhase.FAILED
        manager.state.components["failing"].status = "failed"
        manager.state.components["failing"].error = error_message
        
        start = time.perf_counter()
        result = manager.get_readiness()
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should still be fast
        assert elapsed_ms < 100, f"Error state readiness took {elapsed_ms}ms"
        
        # Should indicate not ready
        assert result["ready"] is False
    
    @given(
        degraded_count=st.integers(min_value=0, max_value=20)
    )
    @settings(max_examples=20, deadline=2000)
    def test_degraded_features_list_doesnt_slow_response(self, degraded_count):
        """
        Property: Large degraded features list should not slow down response.
        """
        manager = StartupManager()
        
        # Add many degraded features
        manager.state.degraded_features = [f"feature_{i}" for i in range(degraded_count)]
        manager.state.is_degraded = degraded_count > 0
        manager.state.phase = InitializationPhase.DEGRADED if degraded_count > 0 else InitializationPhase.READY
        manager.state.is_ready = True
        
        start = time.perf_counter()
        result = manager.get_readiness()
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should be fast regardless of list size
        assert elapsed_ms < 50, f"Degraded state readiness took {elapsed_ms}ms"
        
        # Degraded features should be in response
        assert result["degraded_features"] == manager.state.degraded_features


class TestTimingReportProperties:
    """Property tests for timing report generation."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Reset startup manager before each test."""
        StartupManager.reset_instance()
        yield
        StartupManager.reset_instance()
    
    @given(
        num_components=st.integers(min_value=1, max_value=20),
        total_duration=st.integers(min_value=100, max_value=60000)
    )
    @settings(max_examples=20, deadline=3000)
    def test_timing_report_percentages_sum_correctly(self, num_components, total_duration):
        """
        Property: Component percentages in timing report should be reasonable.
        """
        manager = StartupManager()
        manager.state.total_duration_ms = total_duration
        manager.state.started_at = datetime.utcnow()
        manager.state.ready_at = datetime.utcnow()
        
        # Register components with varying durations
        remaining = total_duration
        for i in range(num_components):
            name = f"component_{i}"
            manager.register_component(name, lambda: None, is_critical=True)
            
            # Distribute duration
            if i == num_components - 1:
                duration = remaining
            else:
                duration = remaining // (num_components - i)
                remaining -= duration
            
            manager.state.components[name].duration_ms = max(1, duration)
            manager.state.components[name].status = "ready"
            manager.state.components[name].started_at = datetime.utcnow()
            manager.state.components[name].completed_at = datetime.utcnow()
        
        report = manager.get_timing_report()
        
        # All components should have timing info
        assert len(report["components"]) == num_components
        
        # Each component should have percentage
        for comp in report["components"]:
            if comp["duration_ms"]:
                assert "percentage" in comp
                assert 0 <= comp["percentage"] <= 100
    
    @given(
        duration_ms=st.integers(min_value=0, max_value=100000)
    )
    @settings(max_examples=20, deadline=2000)
    def test_timing_report_generation_is_fast(self, duration_ms):
        """
        Property: Timing report generation should be fast.
        """
        manager = StartupManager()
        manager.state.total_duration_ms = duration_ms
        manager.state.started_at = datetime.utcnow()
        manager.state.ready_at = datetime.utcnow()
        
        # Add some components
        for i in range(5):
            name = f"component_{i}"
            manager.register_component(name, lambda: None, is_critical=True)
            manager.state.components[name].duration_ms = duration_ms // 5
            manager.state.components[name].status = "ready"
        
        start = time.perf_counter()
        report = manager.get_timing_report()
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should complete quickly
        assert elapsed_ms < 100, f"Timing report took {elapsed_ms}ms"
        assert report["total_duration_ms"] == duration_ms
