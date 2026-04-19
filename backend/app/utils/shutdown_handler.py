"""
Graceful Shutdown Handler for Backend Process.

Handles SIGTERM, SIGINT, and SIGBREAK signals for graceful shutdown.
Ensures all resources are properly released before process termination.
"""
import signal
import sys
import logging
import threading
import time
from typing import Callable, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ShutdownConfig:
    """Configuration for shutdown behavior."""
    graceful_timeout_seconds: int = 3
    force_timeout_seconds: int = 5
    log_shutdown: bool = True


@dataclass
class ShutdownResult:
    """Result of shutdown operation."""
    success: bool
    callbacks_executed: int
    callbacks_failed: int
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class GracefulShutdownHandler:
    """
    Handles graceful shutdown of the backend process.
    
    Registers signal handlers for SIGTERM, SIGINT, and SIGBREAK (Windows).
    Executes registered cleanup callbacks before process termination.
    """
    
    def __init__(self, config: Optional[ShutdownConfig] = None):
        """
        Initialize the shutdown handler.
        
        Args:
            config: Optional shutdown configuration
        """
        self.config = config or ShutdownConfig()
        self._shutdown_callbacks: List[Callable] = []
        self._shutdown_in_progress = False
        self._shutdown_complete = threading.Event()
        self._lock = threading.Lock()
        self._original_handlers = {}
        self._is_registered = False
    
    def register_signal_handlers(self):
        """Register signal handlers for graceful shutdown."""
        if self._is_registered:
            logger.warning("Signal handlers already registered")
            return
        
        # Store original handlers
        self._original_handlers[signal.SIGTERM] = signal.signal(signal.SIGTERM, self._handle_shutdown)
        self._original_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, self._handle_shutdown)
        
        # Windows-specific SIGBREAK
        if sys.platform == 'win32':
            try:
                self._original_handlers[signal.SIGBREAK] = signal.signal(signal.SIGBREAK, self._handle_shutdown)
            except (AttributeError, ValueError):
                logger.debug("SIGBREAK not available on this platform")
        
        self._is_registered = True
        logger.info("Graceful shutdown handlers registered")
    
    def unregister_signal_handlers(self):
        """Restore original signal handlers."""
        if not self._is_registered:
            return
        
        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        
        self._original_handlers.clear()
        self._is_registered = False
        logger.info("Signal handlers unregistered")
    
    def register_callback(self, callback: Callable, name: Optional[str] = None):
        """
        Register a callback to be called during shutdown.
        
        Args:
            callback: Function to call during shutdown
            name: Optional name for logging purposes
        """
        with self._lock:
            self._shutdown_callbacks.append((callback, name or callback.__name__))
            logger.debug(f"Registered shutdown callback: {name or callback.__name__}")
    
    def unregister_callback(self, callback: Callable):
        """
        Unregister a previously registered callback.
        
        Args:
            callback: The callback to remove
        """
        with self._lock:
            self._shutdown_callbacks = [
                (cb, name) for cb, name in self._shutdown_callbacks if cb != callback
            ]
    
    def _handle_shutdown(self, signum: int, frame):
        """
        Handle shutdown signal.
        
        Args:
            signum: Signal number received
            frame: Current stack frame
        """
        signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        
        if self._shutdown_in_progress:
            logger.warning(f"Shutdown already in progress, ignoring {signal_name}")
            return
        
        self._shutdown_in_progress = True
        logger.info(f"Received shutdown signal: {signal_name}")
        
        if self.config.log_shutdown:
            logger.info(f"Starting graceful shutdown (timeout: {self.config.graceful_timeout_seconds}s)")
        
        result = self._execute_shutdown()
        
        if self.config.log_shutdown:
            logger.info(f"Shutdown complete: {result.callbacks_executed} callbacks executed, "
                       f"{result.callbacks_failed} failed, duration: {result.duration_seconds:.2f}s")
        
        self._shutdown_complete.set()
        sys.exit(0)
    
    def _execute_shutdown(self) -> ShutdownResult:
        """
        Execute all shutdown callbacks with timeout.
        
        Returns:
            ShutdownResult with execution details
        """
        start_time = time.time()
        result = ShutdownResult(success=True, callbacks_executed=0, callbacks_failed=0)
        
        with self._lock:
            callbacks = list(self._shutdown_callbacks)
        
        for callback, name in callbacks:
            try:
                logger.debug(f"Executing shutdown callback: {name}")
                
                # Execute callback with timeout
                callback_thread = threading.Thread(target=callback)
                callback_thread.start()
                callback_thread.join(timeout=self.config.graceful_timeout_seconds)
                
                if callback_thread.is_alive():
                    logger.warning(f"Callback {name} timed out after {self.config.graceful_timeout_seconds}s")
                    result.errors.append(f"Callback {name} timed out")
                    result.callbacks_failed += 1
                else:
                    result.callbacks_executed += 1
                    logger.debug(f"Callback {name} completed successfully")
                    
            except Exception as e:
                logger.error(f"Error in shutdown callback {name}: {e}")
                result.errors.append(f"Callback {name} error: {str(e)}")
                result.callbacks_failed += 1
                result.success = False
        
        result.duration_seconds = time.time() - start_time
        return result
    
    def shutdown(self) -> ShutdownResult:
        """
        Manually trigger shutdown (for testing or programmatic shutdown).
        
        Returns:
            ShutdownResult with execution details
        """
        if self._shutdown_in_progress:
            logger.warning("Shutdown already in progress")
            return ShutdownResult(success=False, callbacks_executed=0, callbacks_failed=0,
                                 errors=["Shutdown already in progress"])
        
        self._shutdown_in_progress = True
        logger.info("Manual shutdown triggered")
        
        result = self._execute_shutdown()
        self._shutdown_complete.set()
        
        return result
    
    def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for shutdown to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if shutdown completed, False if timeout
        """
        return self._shutdown_complete.wait(timeout=timeout)
    
    @property
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self._shutdown_in_progress
    
    @property
    def callback_count(self) -> int:
        """Get the number of registered callbacks."""
        with self._lock:
            return len(self._shutdown_callbacks)


# Global shutdown handler instance
_shutdown_handler: Optional[GracefulShutdownHandler] = None


def get_shutdown_handler() -> GracefulShutdownHandler:
    """
    Get or create the global shutdown handler instance.
    
    Returns:
        The global GracefulShutdownHandler instance
    """
    global _shutdown_handler
    if _shutdown_handler is None:
        _shutdown_handler = GracefulShutdownHandler()
    return _shutdown_handler


def register_shutdown_callback(callback: Callable, name: Optional[str] = None):
    """
    Convenience function to register a shutdown callback.
    
    Args:
        callback: Function to call during shutdown
        name: Optional name for logging
    """
    get_shutdown_handler().register_callback(callback, name)


def initialize_shutdown_handler(config: Optional[ShutdownConfig] = None):
    """
    Initialize and register the global shutdown handler.
    
    Args:
        config: Optional shutdown configuration
    """
    global _shutdown_handler
    _shutdown_handler = GracefulShutdownHandler(config)
    _shutdown_handler.register_signal_handlers()
    logger.info("Shutdown handler initialized")
    return _shutdown_handler
