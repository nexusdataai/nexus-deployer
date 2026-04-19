"""
Property-based tests for Health Endpoint.
Feature: startup-health-check
Property 1: Readiness Endpoint Consistency
Validates: Requirements 1.2, 1.3, 5.6
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock
from hypothesis import given, strategies as st, settings
from fastapi.testclient import TestClient
from fastapi import FastAPI

from app.routers.health import router, set_service_start_time
from app.services.startup_manager import (
    StartupManager,
    InitializationPhase,
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


@pytest.fixture
def app():
    """Create a test FastAPI app with health router."""
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


# ============================================
# Property 1: Readiness Endpoint Consistency
# Validates: Requirements 1.2, 1.3, 5.6
# ============================================

class TestReadinessEndpointConsistency:
    """
    Property 1: Readiness Endpoint Consistency
    
    For any backend startup sequence, the `/api/health/ready` endpoint SHALL 
    return `ready: false` until all critical components are initialized, and 
    `ready: true` only after successful initialization.
    """
    
    def test_returns_not_ready_before_initialization(self, client):
        """
        Before initialization, ready should be false with HTTP 503.
        """
        # Manager exists but not initialized
        manager = StartupManager.get_instance()
        
        response = client.get("/api/health/ready")
        
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] == False
        assert data["phase"] == "pending"
        assert data["reason"] is not None
    
    def test_returns_ready_after_successful_initialization(self, client):
        """
        After successful initialization, ready should be true with HTTP 200.
        """
        manager = StartupManager.get_instance()
        manager.register_component("test", lambda: None)
        asyncio.run(manager.initialize_all())
        
        response = client.get("/api/health/ready")
        
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] == True
        assert data["phase"] == "ready"
    
    def test_returns_not_ready_during_initialization(self, client):
        """
        During initialization, ready should be false.
        """
        manager = StartupManager.get_instance()
        
        # Simulate initialization in progress
        manager.state.phase = InitializationPhase.DATABASE
        manager.state.is_ready = False
        
        response = client.get("/api/health/ready")
        
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] == False
    
    @given(st.booleans())
    @settings(max_examples=100, deadline=5000)
    def test_ready_matches_is_ready_state(self, is_ready: bool, client):
        """
        For any state, the ready field should match the manager's is_ready state.
        """
        manager = StartupManager.get_instance()
        manager.state.is_ready = is_ready
        manager.state.phase = InitializationPhase.READY if is_ready else InitializationPhase.PENDING
        
        response = client.get("/api/health/ready")
        data = response.json()
        
        assert data["ready"] == is_ready
    
    def test_http_status_matches_readiness(self, client):
        """
        HTTP status should be 200 when ready, 503 when not ready.
        """
        manager = StartupManager.get_instance()
        
        # Not ready
        manager.state.is_ready = False
        response = client.get("/api/health/ready")
        assert response.status_code == 503
        
        # Ready
        manager.state.is_ready = True
        manager.state.phase = InitializationPhase.READY
        response = client.get("/api/health/ready")
        assert response.status_code == 200
    
    def test_degraded_mode_still_returns_ready(self, client):
        """
        In degraded mode, ready should be true but is_degraded should be true.
        """
        manager = StartupManager.get_instance()
        manager.state.is_ready = True
        manager.state.is_degraded = True
        manager.state.phase = InitializationPhase.DEGRADED
        manager.state.degraded_features = ["optional_feature"]
        
        response = client.get("/api/health/ready")
        
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] == True
        assert data["is_degraded"] == True
        assert "optional_feature" in data["degraded_features"]
    
    def test_failed_state_returns_not_ready(self, client):
        """
        In failed state, ready should be false.
        """
        manager = StartupManager.get_instance()
        manager.state.is_ready = False
        manager.state.phase = InitializationPhase.FAILED
        manager.state.error = "Critical component failed"
        
        response = client.get("/api/health/ready")
        
        assert response.status_code == 503
        data = response.json()
        assert data["ready"] == False
        assert data["phase"] == "failed"


class TestReadinessResponseStructure:
    """Tests for readiness response structure."""
    
    def test_response_contains_required_fields(self, client):
        """
        Response should contain all required fields.
        """
        response = client.get("/api/health/ready")
        data = response.json()
        
        required_fields = [
            "ready", "phase", "started_at", "ready_at",
            "startup_duration_ms", "is_degraded", "degraded_features",
            "components", "reason"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_components_have_required_fields(self, client):
        """
        Each component in the response should have required fields.
        """
        manager = StartupManager.get_instance()
        manager.register_component("test_comp", lambda: None)
        asyncio.run(manager.initialize_all())
        
        response = client.get("/api/health/ready")
        data = response.json()
        
        assert "test_comp" in data["components"]
        comp = data["components"]["test_comp"]
        
        assert "status" in comp
        assert "duration_ms" in comp
        assert "is_critical" in comp
    
    @given(st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5, unique=True))
    @settings(max_examples=50, deadline=5000)
    def test_all_registered_components_in_response(self, component_names, client):
        """
        For any set of registered components, all should appear in the response.
        """
        StartupManager.reset_instance()
        manager = StartupManager.get_instance()
        
        for name in component_names:
            if name.strip():  # Skip empty names
                manager.register_component(name.strip(), lambda: None)
        
        asyncio.run(manager.initialize_all())
        
        response = client.get("/api/health/ready")
        data = response.json()
        
        for name in component_names:
            if name.strip():
                assert name.strip() in data["components"], \
                    f"Component {name} not in response"


class TestLivenessEndpoint:
    """Tests for liveness endpoint."""
    
    def test_liveness_always_returns_alive(self, client):
        """
        Liveness endpoint should always return alive=true.
        """
        response = client.get("/api/health/live")
        
        assert response.status_code == 200
        data = response.json()
        assert data["alive"] == True
    
    def test_liveness_independent_of_readiness(self, client):
        """
        Liveness should return 200 even when not ready.
        """
        manager = StartupManager.get_instance()
        manager.state.is_ready = False
        manager.state.phase = InitializationPhase.FAILED
        
        response = client.get("/api/health/live")
        
        assert response.status_code == 200
        assert response.json()["alive"] == True


class TestDetailedHealthEndpoint:
    """Tests for detailed health endpoint."""
    
    def test_detailed_health_returns_required_fields(self, client):
        """
        Detailed health should return all required fields.
        """
        set_service_start_time()
        manager = StartupManager.get_instance()
        manager.state.is_ready = True
        manager.state.phase = InitializationPhase.READY
        
        response = client.get("/api/health/")
        data = response.json()
        
        required_fields = [
            "status", "service", "version", "uptime_seconds",
            "response_time_ms", "database", "is_degraded", "degraded_features"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
    
    def test_status_reflects_readiness(self, client):
        """
        Status should be 'healthy' when ready, 'unhealthy' when not.
        """
        set_service_start_time()
        manager = StartupManager.get_instance()
        
        # Not ready
        manager.state.is_ready = False
        response = client.get("/api/health/")
        assert response.json()["status"] == "unhealthy"
        
        # Ready
        manager.state.is_ready = True
        manager.state.phase = InitializationPhase.READY
        response = client.get("/api/health/")
        assert response.json()["status"] in ["healthy", "degraded"]
    
    def test_response_time_is_recorded(self, client):
        """
        Response time should be recorded and reasonable.
        """
        set_service_start_time()
        manager = StartupManager.get_instance()
        manager.state.is_ready = True
        manager.state.phase = InitializationPhase.READY
        
        response = client.get("/api/health/")
        data = response.json()
        
        assert "response_time_ms" in data
        assert data["response_time_ms"] >= 0
        assert data["response_time_ms"] < 5000  # Should be fast


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
