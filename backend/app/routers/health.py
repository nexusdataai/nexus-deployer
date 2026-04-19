"""
Health check endpoints for Totogi Capability Installer Backend.
Provides readiness, liveness, and detailed health information.
"""
import logging
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.services.startup_manager import get_startup_manager, StartupManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])

# Track service start time for uptime calculation
_service_start_time: Optional[datetime] = None


def set_service_start_time():
    """Set the service start time (called during startup)."""
    global _service_start_time
    _service_start_time = datetime.utcnow()


# ============================================
# Response Models
# ============================================

class ComponentHealthStatus(BaseModel):
    """Health status of a single component."""
    name: str  # Component name for array format
    status: str
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    is_critical: bool = True


class ReadinessResponse(BaseModel):
    """Response model for readiness check."""
    ready: bool
    phase: str
    started_at: Optional[str] = None
    ready_at: Optional[str] = None
    startup_duration_ms: Optional[int] = None
    is_degraded: bool = False
    degraded_features: List[str] = []
    components: List[ComponentHealthStatus] = []  # Array format for frontend compatibility
    reason: Optional[str] = None
    message: Optional[str] = None  # Added for frontend compatibility


class LivenessResponse(BaseModel):
    """Response model for liveness check."""
    alive: bool


class DatabaseHealth(BaseModel):
    """Database health information."""
    status: str
    schema_version: Optional[str] = None  # Schema version is a string like "1.0.0"
    capabilities_count: Optional[int] = None
    deployments_count: Optional[int] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Detailed health response."""
    status: str  # healthy, degraded, unhealthy
    service: str
    version: str
    uptime_seconds: int
    response_time_ms: int
    database: DatabaseHealth
    is_degraded: bool = False
    degraded_features: List[str] = []


# ============================================
# Endpoints
# ============================================

@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(response: Response) -> ReadinessResponse:
    """
    Readiness probe for startup orchestration.
    
    Returns HTTP 200 when the service is ready to accept requests.
    Returns HTTP 503 when the service is still initializing.
    
    This endpoint is designed to be fast (<500ms) to avoid blocking
    startup health checks from Electron.
    """
    start_time = time.time()
    
    try:
        manager = get_startup_manager()
        readiness = manager.get_readiness()
        
        # Convert components to array format for frontend compatibility
        components = []
        raw_components = readiness.get("components", {})
        
        # Handle both dict format (name -> data) and list format
        if isinstance(raw_components, dict):
            for name, comp_data in raw_components.items():
                # comp_data might be a dict or already have the right structure
                if isinstance(comp_data, dict):
                    components.append(ComponentHealthStatus(
                        name=name,
                        status=comp_data.get("status", "unknown"),
                        duration_ms=comp_data.get("duration_ms"),
                        error=comp_data.get("error"),
                        is_critical=comp_data.get("is_critical", True),
                    ))
                else:
                    # Fallback for unexpected format
                    components.append(ComponentHealthStatus(
                        name=name,
                        status="unknown",
                    ))
        elif isinstance(raw_components, list):
            for comp in raw_components:
                if isinstance(comp, dict):
                    components.append(ComponentHealthStatus(
                        name=comp.get("name", "unknown"),
                        status=comp.get("status", "unknown"),
                        duration_ms=comp.get("duration_ms"),
                        error=comp.get("error"),
                        is_critical=comp.get("is_critical", True),
                    ))
        
        result = ReadinessResponse(
            ready=readiness.get("ready", False),
            phase=readiness.get("phase", "pending"),
            started_at=readiness.get("started_at"),
            ready_at=readiness.get("ready_at"),
            startup_duration_ms=readiness.get("startup_duration_ms"),
            is_degraded=readiness.get("is_degraded", False),
            degraded_features=readiness.get("degraded_features", []),
            components=components,
            reason=readiness.get("reason"),
            message=readiness.get("message"),
        )
        
        # Set HTTP status based on readiness
        if not result.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.debug(f"Readiness check completed in {elapsed_ms}ms: ready={result.ready}")
        
        return result
        
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            ready=False,
            phase="error",
            reason=str(e),
        )


@router.get("/live", response_model=LivenessResponse)
async def liveness_check() -> LivenessResponse:
    """
    Liveness probe - returns 200 if the process is running.
    
    This is a simple check that the service process is alive.
    It does not check dependencies or initialization status.
    """
    return LivenessResponse(alive=True)


@router.get("/", response_model=HealthResponse)
async def detailed_health(response: Response) -> HealthResponse:
    """
    Detailed health check with metrics.
    
    Provides comprehensive health information including:
    - Service status (healthy, degraded, unhealthy)
    - Uptime
    - Database connectivity and stats
    - Response time
    """
    start_time = time.time()
    
    # Calculate uptime
    uptime_seconds = 0
    if _service_start_time:
        uptime_seconds = int((datetime.utcnow() - _service_start_time).total_seconds())
    
    # Check database health
    db_health = await _check_database_health()
    
    # Get startup manager state
    manager = get_startup_manager()
    readiness = manager.get_readiness()
    
    # Determine overall status
    if not readiness.get("ready", False):
        overall_status = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif readiness.get("is_degraded", False):
        overall_status = "degraded"
    elif db_health.status != "connected":
        overall_status = "degraded"
    else:
        overall_status = "healthy"
    
    response_time_ms = int((time.time() - start_time) * 1000)
    
    return HealthResponse(
        status=overall_status,
        service="totogi-installer-backend",
        version="1.0.0",
        uptime_seconds=uptime_seconds,
        response_time_ms=response_time_ms,
        database=db_health,
        is_degraded=readiness.get("is_degraded", False),
        degraded_features=readiness.get("degraded_features", []),
    )


async def _check_database_health() -> DatabaseHealth:
    """Check database connectivity and gather stats."""
    try:
        from app.services.tinydb_state_manager import get_state_manager
        from app.services.tinydb_capability_service import tinydb_capability_service
        from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service
        
        db_manager = get_state_manager()
        schema_version = db_manager.get_schema_version()
        
        capabilities_count = len(tinydb_capability_service.get_all_capabilities())
        deployments_count = len(tinydb_deployment_state_service.list_deployments())
        
        return DatabaseHealth(
            status="connected",
            schema_version=schema_version,
            capabilities_count=capabilities_count,
            deployments_count=deployments_count,
        )
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return DatabaseHealth(
            status="error",
            error=str(e),
        )


# ============================================
# Utility Functions
# ============================================

def get_health_summary() -> Dict[str, Any]:
    """
    Get a quick health summary for internal use.
    
    Returns:
        Dictionary with basic health information
    """
    manager = get_startup_manager()
    readiness = manager.get_readiness()
    
    return {
        "ready": readiness.get("ready", False),
        "phase": readiness.get("phase", "unknown"),
        "is_degraded": readiness.get("is_degraded", False),
    }
