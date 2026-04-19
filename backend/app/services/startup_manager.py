"""
Startup Manager for Totogi Capability Installer Backend
Manages ordered initialization of backend components with health tracking.
"""
import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Callable, Dict, Any, Awaitable, Union

logger = logging.getLogger(__name__)


class InitializationPhase(Enum):
    """Phases of backend initialization."""
    PENDING = "pending"
    LOGGING = "logging"
    DATABASE = "database"
    TEMPLATES = "templates"
    ROUTES = "routes"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class ComponentStatus:
    """Status of a single initialization component."""
    name: str
    status: str = "pending"  # pending, initializing, ready, failed, degraded
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    is_critical: bool = True
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class StartupState:
    """Overall startup state of the backend."""
    phase: InitializationPhase = InitializationPhase.PENDING
    started_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    total_duration_ms: Optional[int] = None
    components: Dict[str, ComponentStatus] = field(default_factory=dict)
    is_ready: bool = False
    is_degraded: bool = False
    degraded_features: List[str] = field(default_factory=list)
    error: Optional[str] = None


# Type alias for initializer functions
InitializerFunc = Union[Callable[[], Any], Callable[[], Awaitable[Any]]]


class StartupManager:
    """
    Manages backend service initialization sequence.
    
    Ensures components are initialized in the correct order with proper
    error handling, retry logic, and health status tracking.
    """
    
    # Singleton instance
    _instance: Optional['StartupManager'] = None
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the startup manager.
        
        Args:
            config: Optional configuration dictionary with:
                - component_timeout_ms: Timeout per component (default: 10000)
                - max_retries: Max retries for failed components (default: 3)
                - retry_delay_ms: Delay between retries (default: 1000)
        """
        self.state = StartupState()
        self.config = config or {}
        self._components: List[tuple[str, InitializerFunc, bool]] = []
        self._initialized = False
        
        # Configuration with defaults
        self.component_timeout_ms = self.config.get('component_timeout_ms', 10000)
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delay_ms = self.config.get('retry_delay_ms', 1000)
    
    @classmethod
    def get_instance(cls, config: Optional[Dict[str, Any]] = None) -> 'StartupManager':
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._instance = None
    
    def register_component(
        self,
        name: str,
        initializer: InitializerFunc,
        is_critical: bool = True
    ) -> None:
        """
        Register a component for initialization.
        
        Args:
            name: Unique name for the component
            initializer: Callable that initializes the component
            is_critical: If True, failure prevents ready state
        """
        if self._initialized:
            logger.warning(f"Cannot register component '{name}' after initialization")
            return
        
        self._components.append((name, initializer, is_critical))
        self.state.components[name] = ComponentStatus(
            name=name,
            is_critical=is_critical,
            max_retries=self.max_retries
        )
        logger.debug(f"Registered component: {name} (critical={is_critical})")
    
    async def initialize_all(self) -> StartupState:
        """
        Initialize all registered components in order.
        
        Returns:
            StartupState with final initialization status
        """
        if self._initialized:
            logger.warning("Startup manager already initialized")
            return self.state
        
        self.state.started_at = datetime.utcnow()
        self.state.phase = InitializationPhase.PENDING
        
        logger.info("Starting backend initialization sequence...")
        logger.info(f"Components to initialize: {[c[0] for c in self._components]}")
        
        critical_failed = False
        
        for name, initializer, is_critical in self._components:
            # Update phase based on component name
            self._update_phase(name)
            
            success = await self._initialize_component(name, initializer, is_critical)
            
            if not success and is_critical:
                critical_failed = True
                self.state.error = f"Critical component '{name}' failed to initialize"
                logger.error(self.state.error)
                break
        
        # Determine final state
        self._finalize_state(critical_failed)
        self._initialized = True
        
        return self.state
    
    async def _initialize_component(
        self,
        name: str,
        initializer: InitializerFunc,
        is_critical: bool
    ) -> bool:
        """
        Initialize a single component with retry logic.
        
        Returns:
            True if initialization succeeded, False otherwise
        """
        component = self.state.components[name]
        component.started_at = datetime.utcnow()
        component.status = "initializing"
        
        logger.info(f"Initializing component: {name}")
        
        while component.retry_count <= component.max_retries:
            try:
                # Call initializer (handle both sync and async)
                if asyncio.iscoroutinefunction(initializer):
                    await asyncio.wait_for(
                        initializer(),
                        timeout=self.component_timeout_ms / 1000
                    )
                else:
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, initializer),
                        timeout=self.component_timeout_ms / 1000
                    )
                
                # Success
                component.completed_at = datetime.utcnow()
                component.duration_ms = int(
                    (component.completed_at - component.started_at).total_seconds() * 1000
                )
                component.status = "ready"
                
                logger.info(
                    f"Component '{name}' initialized successfully "
                    f"(duration: {component.duration_ms}ms)"
                )
                return True
                
            except asyncio.TimeoutError:
                component.error = f"Initialization timed out after {self.component_timeout_ms}ms"
                logger.warning(f"Component '{name}' timed out")
                
            except Exception as e:
                component.error = str(e)
                logger.warning(f"Component '{name}' failed: {e}")
            
            # Retry logic
            component.retry_count += 1
            if component.retry_count <= component.max_retries:
                logger.info(
                    f"Retrying component '{name}' "
                    f"(attempt {component.retry_count}/{component.max_retries})"
                )
                await asyncio.sleep(self.retry_delay_ms / 1000)
        
        # All retries exhausted
        component.completed_at = datetime.utcnow()
        component.duration_ms = int(
            (component.completed_at - component.started_at).total_seconds() * 1000
        )
        
        if is_critical:
            component.status = "failed"
            logger.error(f"Critical component '{name}' failed after {component.max_retries} retries")
        else:
            component.status = "degraded"
            self.state.is_degraded = True
            self.state.degraded_features.append(name)
            logger.warning(f"Non-critical component '{name}' failed, continuing in degraded mode")
        
        return False
    
    def _update_phase(self, component_name: str) -> None:
        """Update the initialization phase based on component name."""
        phase_mapping = {
            "logging": InitializationPhase.LOGGING,
            "database": InitializationPhase.DATABASE,
            "templates": InitializationPhase.TEMPLATES,
            "routes": InitializationPhase.ROUTES,
        }
        
        for key, phase in phase_mapping.items():
            if key in component_name.lower():
                self.state.phase = phase
                break
    
    def _finalize_state(self, critical_failed: bool) -> None:
        """Finalize the startup state after all components are processed."""
        self.state.ready_at = datetime.utcnow()
        self.state.total_duration_ms = int(
            (self.state.ready_at - self.state.started_at).total_seconds() * 1000
        )
        
        if critical_failed:
            self.state.phase = InitializationPhase.FAILED
            self.state.is_ready = False
        elif self.state.is_degraded:
            self.state.phase = InitializationPhase.DEGRADED
            self.state.is_ready = True  # Still ready, but degraded
        else:
            self.state.phase = InitializationPhase.READY
            self.state.is_ready = True
        
        logger.info(
            f"Initialization complete: phase={self.state.phase.value}, "
            f"ready={self.state.is_ready}, degraded={self.state.is_degraded}, "
            f"duration={self.state.total_duration_ms}ms"
        )
    
    def get_readiness(self) -> Dict[str, Any]:
        """
        Get current readiness status for health endpoint.
        
        Returns:
            Dictionary with readiness information
        """
        components_status = {}
        for name, component in self.state.components.items():
            components_status[name] = {
                "status": component.status,
                "duration_ms": component.duration_ms,
                "error": component.error,
                "is_critical": component.is_critical,
            }
        
        return {
            "ready": self.state.is_ready,
            "phase": self.state.phase.value,
            "started_at": self.state.started_at.isoformat() if self.state.started_at else None,
            "ready_at": self.state.ready_at.isoformat() if self.state.ready_at else None,
            "startup_duration_ms": self.state.total_duration_ms,
            "is_degraded": self.state.is_degraded,
            "degraded_features": self.state.degraded_features,
            "components": components_status,
            "reason": self._get_not_ready_reason() if not self.state.is_ready else None,
        }
    
    def _get_not_ready_reason(self) -> Optional[str]:
        """Get the reason why the service is not ready."""
        if self.state.error:
            return self.state.error
        
        # Find the component that's currently initializing or failed
        for name, component in self.state.components.items():
            if component.status == "initializing":
                return f"Initializing {name}"
            if component.status == "failed":
                return f"Component '{name}' failed: {component.error}"
        
        if self.state.phase == InitializationPhase.PENDING:
            return "Initialization not started"
        
        return "Unknown"
    
    def get_timing_report(self) -> Dict[str, Any]:
        """
        Get detailed timing report for diagnostics.
        
        Returns:
            Dictionary with timing information for each component
            
        Requirements: 8.2, 5.5
        """
        report = {
            "total_duration_ms": self.state.total_duration_ms,
            "started_at": self.state.started_at.isoformat() if self.state.started_at else None,
            "ready_at": self.state.ready_at.isoformat() if self.state.ready_at else None,
            "components": [],
        }
        
        for name, component in self.state.components.items():
            component_timing = {
                "name": name,
                "status": component.status,
                "duration_ms": component.duration_ms,
                "started_at": component.started_at.isoformat() if component.started_at else None,
                "completed_at": component.completed_at.isoformat() if component.completed_at else None,
                "retry_count": component.retry_count,
                "is_critical": component.is_critical,
            }
            
            if component.error:
                component_timing["error"] = component.error
            
            report["components"].append(component_timing)
        
        # Calculate percentage of time spent in each component
        if self.state.total_duration_ms and self.state.total_duration_ms > 0:
            for comp in report["components"]:
                if comp["duration_ms"]:
                    comp["percentage"] = round(
                        (comp["duration_ms"] / self.state.total_duration_ms) * 100, 1
                    )
        
        # Log timing report
        logger.info("=== Startup Timing Report ===")
        logger.info(f"Total Duration: {self.state.total_duration_ms}ms")
        for comp in report["components"]:
            pct = comp.get("percentage", 0)
            logger.info(
                f"  {comp['name']}: {comp['duration_ms']}ms ({pct}%) - {comp['status']}"
            )
        logger.info("=============================")
        
        return report
    
    def mark_component_ready(self, name: str) -> None:
        """Mark a component as ready (for external updates)."""
        if name in self.state.components:
            self.state.components[name].status = "ready"
            self.state.components[name].completed_at = datetime.utcnow()
    
    def mark_component_failed(self, name: str, error: str) -> None:
        """Mark a component as failed (for external updates)."""
        if name in self.state.components:
            component = self.state.components[name]
            component.status = "failed" if component.is_critical else "degraded"
            component.error = error
            component.completed_at = datetime.utcnow()
            
            if not component.is_critical:
                self.state.is_degraded = True
                if name not in self.state.degraded_features:
                    self.state.degraded_features.append(name)


# Global instance getter
def get_startup_manager(config: Optional[Dict[str, Any]] = None) -> StartupManager:
    """Get the global startup manager instance."""
    return StartupManager.get_instance(config)
