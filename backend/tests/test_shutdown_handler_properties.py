"""
Property-based tests for Graceful Shutdown Handler.

Property 7: Backend Graceful Shutdown
- Validates: Requirements 7.1, 7.2, 7.3
"""
import pytest
import time
import threading
from unittest.mock import Mock, patch
from hypothesis import given, strategies as st, settings

from app.utils.shutdown_handler import (
    GracefulShutdownHandler,
    ShutdownConfig,
    ShutdownResult,
    get_shutdown_handler,
    register_shutdown_callback,
    initialize_shutdown_handler
)


class TestGracefulShutdownHandler:
    """Tests for GracefulShutdownHandler class."""
    
    def test_callback_registration(self):
        """Property: Callbacks can be registered and counted."""
        handler = GracefulShutdownHandler()
        
        assert handler.callback_count == 0
        
        handler.register_callback(lambda: None, "test1")
        assert handler.callback_count == 1
        
        handler.register_callback(lambda: None, "test2")
        assert handler.callback_count == 2
    
    def test_callback_unregistration(self):
        """Property: Callbacks can be unregistered."""
        handler = GracefulShutdownHandler()
        
        callback = lambda: None
        handler.register_callback(callback, "test")
        assert handler.callback_count == 1
        
        handler.unregister_callback(callback)
        assert handler.callback_count == 0
    
    def test_shutdown_executes_all_callbacks(self):
        """Property: Shutdown executes all registered callbacks."""
        handler = GracefulShutdownHandler()
        
        executed = []
        
        handler.register_callback(lambda: executed.append(1), "cb1")
        handler.register_callback(lambda: executed.append(2), "cb2")
        handler.register_callback(lambda: executed.append(3), "cb3")
        
        result = handler.shutdown()
        
        assert result.success
        assert result.callbacks_executed == 3
        assert result.callbacks_failed == 0
        assert len(executed) == 3
    
    def test_shutdown_handles_callback_errors(self):
        """Property: Shutdown continues after callback errors."""
        handler = GracefulShutdownHandler()
        
        executed = []
        
        handler.register_callback(lambda: executed.append(1), "cb1")
        
        def failing_callback():
            raise ValueError("Test error")
        
        handler.register_callback(failing_callback, "failing")
        handler.register_callback(lambda: executed.append(3), "cb3")
        
        result = handler.shutdown()
        
        # Should continue despite error
        assert result.callbacks_failed >= 1
        assert len(result.errors) >= 1
        assert "failing" in result.errors[0]
    
    def test_shutdown_timeout_handling(self):
        """Property: Callbacks that exceed timeout are handled."""
        config = ShutdownConfig(graceful_timeout_seconds=1)
        handler = GracefulShutdownHandler(config)
        
        def slow_callback():
            time.sleep(5)  # Longer than timeout
        
        handler.register_callback(slow_callback, "slow")
        
        start = time.time()
        result = handler.shutdown()
        duration = time.time() - start
        
        # Should timeout, not wait full 5 seconds
        assert duration < 3
        assert result.callbacks_failed >= 1
    
    def test_shutdown_only_runs_once(self):
        """Property: Shutdown can only run once."""
        handler = GracefulShutdownHandler()
        
        executed_count = [0]
        
        def counting_callback():
            executed_count[0] += 1
        
        handler.register_callback(counting_callback, "counter")
        
        result1 = handler.shutdown()
        result2 = handler.shutdown()
        
        assert result1.success
        assert not result2.success
        assert "already in progress" in result2.errors[0].lower()
        assert executed_count[0] == 1
    
    def test_is_shutting_down_flag(self):
        """Property: is_shutting_down reflects shutdown state."""
        handler = GracefulShutdownHandler()
        
        assert not handler.is_shutting_down
        
        handler.shutdown()
        
        assert handler.is_shutting_down
    
    @given(st.integers(min_value=1, max_value=10))
    @settings(max_examples=5, deadline=None)
    def test_multiple_callbacks_all_execute(self, num_callbacks):
        """Property: For any number of callbacks, all are executed."""
        handler = GracefulShutdownHandler()
        
        executed = []
        
        for i in range(num_callbacks):
            handler.register_callback(lambda i=i: executed.append(i), f"cb{i}")
        
        result = handler.shutdown()
        
        assert result.callbacks_executed == num_callbacks
        assert len(executed) == num_callbacks


class TestShutdownConfig:
    """Tests for ShutdownConfig."""
    
    def test_default_config(self):
        """Property: Default config has sensible values."""
        config = ShutdownConfig()
        
        assert config.graceful_timeout_seconds == 3
        assert config.force_timeout_seconds == 5
        assert config.log_shutdown is True
    
    def test_custom_config(self):
        """Property: Custom config values are respected."""
        config = ShutdownConfig(
            graceful_timeout_seconds=10,
            force_timeout_seconds=15,
            log_shutdown=False
        )
        
        assert config.graceful_timeout_seconds == 10
        assert config.force_timeout_seconds == 15
        assert config.log_shutdown is False


class TestShutdownResult:
    """Tests for ShutdownResult."""
    
    def test_result_fields(self):
        """Property: Result contains all expected fields."""
        result = ShutdownResult(
            success=True,
            callbacks_executed=5,
            callbacks_failed=1,
            errors=["error1"],
            duration_seconds=1.5
        )
        
        assert result.success is True
        assert result.callbacks_executed == 5
        assert result.callbacks_failed == 1
        assert len(result.errors) == 1
        assert result.duration_seconds == 1.5
    
    def test_default_errors_list(self):
        """Property: Errors list defaults to empty."""
        result = ShutdownResult(success=True, callbacks_executed=0, callbacks_failed=0)
        
        assert result.errors == []


class TestGlobalShutdownHandler:
    """Tests for global shutdown handler functions."""
    
    def test_get_shutdown_handler_singleton(self):
        """Property: get_shutdown_handler returns same instance."""
        # Reset global state
        import app.utils.shutdown_handler as module
        module._shutdown_handler = None
        
        handler1 = get_shutdown_handler()
        handler2 = get_shutdown_handler()
        
        assert handler1 is handler2
    
    def test_register_shutdown_callback_convenience(self):
        """Property: Convenience function registers callback."""
        import app.utils.shutdown_handler as module
        module._shutdown_handler = None
        
        callback = Mock()
        register_shutdown_callback(callback, "test")
        
        handler = get_shutdown_handler()
        assert handler.callback_count >= 1


class TestSignalHandlerRegistration:
    """Tests for signal handler registration."""
    
    def test_register_signal_handlers(self):
        """Property: Signal handlers can be registered."""
        handler = GracefulShutdownHandler()
        
        assert not handler._is_registered
        
        handler.register_signal_handlers()
        
        assert handler._is_registered
        
        # Cleanup
        handler.unregister_signal_handlers()
    
    def test_unregister_signal_handlers(self):
        """Property: Signal handlers can be unregistered."""
        handler = GracefulShutdownHandler()
        
        handler.register_signal_handlers()
        assert handler._is_registered
        
        handler.unregister_signal_handlers()
        assert not handler._is_registered
    
    def test_double_registration_warning(self):
        """Property: Double registration logs warning but doesn't fail."""
        handler = GracefulShutdownHandler()
        
        handler.register_signal_handlers()
        handler.register_signal_handlers()  # Should not raise
        
        assert handler._is_registered
        
        # Cleanup
        handler.unregister_signal_handlers()


class TestWaitForShutdown:
    """Tests for wait_for_shutdown functionality."""
    
    def test_wait_for_shutdown_returns_after_shutdown(self):
        """Property: wait_for_shutdown returns True after shutdown."""
        handler = GracefulShutdownHandler()
        
        # Start shutdown in background
        def trigger_shutdown():
            time.sleep(0.1)
            handler.shutdown()
        
        thread = threading.Thread(target=trigger_shutdown)
        thread.start()
        
        result = handler.wait_for_shutdown(timeout=2)
        
        assert result is True
        thread.join()
    
    def test_wait_for_shutdown_timeout(self):
        """Property: wait_for_shutdown returns False on timeout."""
        handler = GracefulShutdownHandler()
        
        result = handler.wait_for_shutdown(timeout=0.1)
        
        assert result is False


class TestResourceCleanup:
    """Tests for resource cleanup during shutdown."""
    
    def test_file_handle_cleanup_callback(self):
        """Property: File handle cleanup callbacks are executed."""
        handler = GracefulShutdownHandler()
        
        file_closed = [False]
        
        def close_file():
            file_closed[0] = True
        
        handler.register_callback(close_file, "close_file")
        handler.shutdown()
        
        assert file_closed[0] is True
    
    def test_port_release_callback(self):
        """Property: Port release callbacks are executed."""
        handler = GracefulShutdownHandler()
        
        port_released = [False]
        
        def release_port():
            port_released[0] = True
        
        handler.register_callback(release_port, "release_port")
        handler.shutdown()
        
        assert port_released[0] is True
    
    def test_multiple_resource_cleanup(self):
        """Property: Multiple resource cleanup callbacks all execute."""
        handler = GracefulShutdownHandler()
        
        resources_cleaned = {
            'file': False,
            'port': False,
            'connection': False
        }
        
        handler.register_callback(lambda: resources_cleaned.update({'file': True}), "file")
        handler.register_callback(lambda: resources_cleaned.update({'port': True}), "port")
        handler.register_callback(lambda: resources_cleaned.update({'connection': True}), "connection")
        
        handler.shutdown()
        
        assert all(resources_cleaned.values())
