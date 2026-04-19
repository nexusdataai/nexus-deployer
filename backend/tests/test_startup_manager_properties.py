"""
Property-based tests for StartupManager.
Feature: startup-health-check
Property 2: Startup Sequence Ordering
Validates: Requirements 5.1, 5.3
"""
import pytest
import asyncio
from datetime import datetime
from hypothesis import given, strategies as st, settings
from typing import List, Tuple

from app.services.startup_manager import (
    StartupManager,
    StartupState,
    ComponentStatus,
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
# Strategies for Property-Based Testing
# ============================================

# Strategy for component names
component_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='_-'),
    min_size=1,
    max_size=20
).filter(lambda x: x.strip() != '')

# Strategy for list of unique component names
component_list_strategy = st.lists(
    component_name_strategy,
    min_size=1,
    max_size=10,
    unique=True
)


# ============================================
# Property 2: Startup Sequence Ordering
# Validates: Requirements 5.1, 5.3
# ============================================

class TestStartupSequenceOrdering:
    """
    Property 2: Startup Sequence Ordering
    
    For any backend initialization, components SHALL be initialized in the 
    defined order (logging → database → templates → routes), and no component 
    SHALL start before its dependencies are ready.
    """
    
    @given(component_list_strategy)
    @settings(max_examples=100, deadline=5000)
    def test_components_initialized_in_registration_order(self, component_names: List[str]):
        """
        For any list of components, they should be initialized in the order
        they were registered.
        """
        manager = StartupManager()
        initialization_order = []
        
        # Create initializers that record their execution order
        def make_initializer(name: str):
            def initializer():
                initialization_order.append(name)
            return initializer
        
        # Register components
        for name in component_names:
            manager.register_component(name, make_initializer(name))
        
        # Run initialization
        asyncio.run(manager.initialize_all())
        
        # Verify order matches registration order
        assert initialization_order == component_names, \
            f"Expected order {component_names}, got {initialization_order}"
    
    @given(st.integers(min_value=1, max_value=5))
    @settings(max_examples=100, deadline=5000)
    def test_component_started_at_before_completed_at(self, num_components: int):
        """
        For any component, started_at should always be before completed_at.
        """
        manager = StartupManager()
        
        for i in range(num_components):
            manager.register_component(f"component_{i}", lambda: None)
        
        asyncio.run(manager.initialize_all())
        
        for name, component in manager.state.components.items():
            if component.started_at and component.completed_at:
                assert component.started_at <= component.completed_at, \
                    f"Component {name}: started_at should be <= completed_at"
    
    @given(st.integers(min_value=2, max_value=5))
    @settings(max_examples=100, deadline=5000)
    def test_sequential_component_timing(self, num_components: int):
        """
        For any sequence of components, each component should start after
        the previous one completes (sequential initialization).
        """
        manager = StartupManager()
        
        for i in range(num_components):
            manager.register_component(f"component_{i}", lambda: None)
        
        asyncio.run(manager.initialize_all())
        
        components = list(manager.state.components.values())
        for i in range(1, len(components)):
            prev = components[i - 1]
            curr = components[i]
            
            if prev.completed_at and curr.started_at:
                assert prev.completed_at <= curr.started_at, \
                    f"Component {curr.name} started before {prev.name} completed"
    
    def test_standard_initialization_order(self):
        """
        Test the standard initialization order: logging → database → templates → routes.
        """
        manager = StartupManager()
        order = []
        
        def make_init(name):
            def init():
                order.append(name)
            return init
        
        # Register in standard order
        manager.register_component("logging", make_init("logging"))
        manager.register_component("database", make_init("database"))
        manager.register_component("templates", make_init("templates"))
        manager.register_component("routes", make_init("routes"))
        
        asyncio.run(manager.initialize_all())
        
        assert order == ["logging", "database", "templates", "routes"]
    
    @given(st.booleans(), st.booleans())
    @settings(max_examples=100, deadline=5000)
    def test_phase_updates_during_initialization(self, fail_db: bool, fail_templates: bool):
        """
        For any initialization sequence, the phase should update correctly
        as components are initialized.
        """
        manager = StartupManager({'max_retries': 0})  # No retries for faster tests
        phases_seen = []
        
        def logging_init():
            phases_seen.append(manager.state.phase)
        
        def database_init():
            phases_seen.append(manager.state.phase)
            if fail_db:
                raise Exception("DB failed")
        
        def templates_init():
            phases_seen.append(manager.state.phase)
            if fail_templates:
                raise Exception("Templates failed")
        
        manager.register_component("logging", logging_init)
        manager.register_component("database", database_init)
        manager.register_component("templates", templates_init, is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        # Verify phases progressed correctly
        if len(phases_seen) >= 1:
            assert phases_seen[0] == InitializationPhase.LOGGING
        if len(phases_seen) >= 2:
            assert phases_seen[1] == InitializationPhase.DATABASE
        if len(phases_seen) >= 3:
            assert phases_seen[2] == InitializationPhase.TEMPLATES


class TestStartupStateTracking:
    """Tests for startup state tracking (Requirements 5.3, 5.5)."""
    
    @given(st.integers(min_value=1, max_value=5))
    @settings(max_examples=100, deadline=5000)
    def test_all_components_have_duration(self, num_components: int):
        """
        For any successful initialization, all components should have
        duration_ms recorded.
        """
        manager = StartupManager()
        
        for i in range(num_components):
            manager.register_component(f"component_{i}", lambda: None)
        
        asyncio.run(manager.initialize_all())
        
        for name, component in manager.state.components.items():
            assert component.duration_ms is not None, \
                f"Component {name} should have duration_ms"
            assert component.duration_ms >= 0, \
                f"Component {name} duration should be non-negative"
    
    @given(st.integers(min_value=1, max_value=5))
    @settings(max_examples=100, deadline=5000)
    def test_total_duration_is_sum_of_components(self, num_components: int):
        """
        For any initialization, total duration should be approximately
        the sum of component durations (allowing for overhead).
        """
        manager = StartupManager()
        
        for i in range(num_components):
            manager.register_component(f"component_{i}", lambda: None)
        
        asyncio.run(manager.initialize_all())
        
        component_sum = sum(
            c.duration_ms for c in manager.state.components.values()
            if c.duration_ms is not None
        )
        
        # Total should be at least the sum of components
        # (may be slightly more due to overhead)
        assert manager.state.total_duration_ms >= component_sum * 0.9, \
            "Total duration should be approximately sum of component durations"
    
    def test_readiness_exposes_all_component_status(self):
        """
        The get_readiness() method should expose status for all components.
        """
        manager = StartupManager()
        
        manager.register_component("comp1", lambda: None)
        manager.register_component("comp2", lambda: None)
        manager.register_component("comp3", lambda: None)
        
        asyncio.run(manager.initialize_all())
        
        readiness = manager.get_readiness()
        
        assert "components" in readiness
        assert "comp1" in readiness["components"]
        assert "comp2" in readiness["components"]
        assert "comp3" in readiness["components"]
        
        for comp_status in readiness["components"].values():
            assert "status" in comp_status
            assert "duration_ms" in comp_status


class TestCriticalVsNonCriticalComponents:
    """Tests for critical vs non-critical component handling."""
    
    def test_critical_failure_prevents_ready_state(self):
        """
        If a critical component fails, is_ready should be False.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=True)
        
        asyncio.run(manager.initialize_all())
        
        assert not manager.state.is_ready
        assert manager.state.phase == InitializationPhase.FAILED
    
    def test_non_critical_failure_allows_degraded_mode(self):
        """
        If a non-critical component fails, is_ready should be True but is_degraded should be True.
        """
        manager = StartupManager({'max_retries': 0})
        
        manager.register_component("critical", lambda: None, is_critical=True)
        manager.register_component("optional", lambda: (_ for _ in ()).throw(Exception("fail")), is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        assert manager.state.is_ready
        assert manager.state.is_degraded
        assert "optional" in manager.state.degraded_features
        assert manager.state.phase == InitializationPhase.DEGRADED
    
    @given(st.lists(st.booleans(), min_size=1, max_size=5))
    @settings(max_examples=100, deadline=5000)
    def test_degraded_features_list_accuracy(self, fail_flags: List[bool]):
        """
        For any combination of non-critical component failures,
        degraded_features should list exactly the failed components.
        """
        manager = StartupManager({'max_retries': 0})
        expected_degraded = []
        
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


class TestRetryBehavior:
    """Tests for component retry behavior."""
    
    @given(st.integers(min_value=0, max_value=3))
    @settings(max_examples=100, deadline=10000)
    def test_retry_count_respected(self, max_retries: int):
        """
        For any max_retries setting, the component should be retried
        exactly that many times before failing.
        """
        manager = StartupManager({'max_retries': max_retries, 'retry_delay_ms': 10})
        attempt_count = [0]
        
        def failing_init():
            attempt_count[0] += 1
            raise Exception("Always fails")
        
        manager.register_component("failing", failing_init, is_critical=False)
        
        asyncio.run(manager.initialize_all())
        
        # Initial attempt + retries
        expected_attempts = 1 + max_retries
        assert attempt_count[0] == expected_attempts, \
            f"Expected {expected_attempts} attempts, got {attempt_count[0]}"


class TestSingletonBehavior:
    """Tests for singleton pattern."""
    
    def test_get_instance_returns_same_instance(self):
        """get_instance should return the same instance."""
        instance1 = StartupManager.get_instance()
        instance2 = StartupManager.get_instance()
        
        assert instance1 is instance2
    
    def test_reset_instance_creates_new_instance(self):
        """reset_instance should allow creating a new instance."""
        instance1 = StartupManager.get_instance()
        StartupManager.reset_instance()
        instance2 = StartupManager.get_instance()
        
        assert instance1 is not instance2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
