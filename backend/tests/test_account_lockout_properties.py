"""
Property-based tests for Account Lockout Service.
Feature: user-authentication
Validates: Requirements 1.3, 1.6, 1.7
"""
import pytest
import tempfile
import os
from hypothesis import given, strategies as st, settings
from datetime import datetime, timedelta
from unittest.mock import patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.auth_models import UserCreate, UserRole
from app.services.tinydb_state_manager import TinyDBStateManager, set_state_manager
from app.services.user_store import UserStore, get_user_store, reset_user_store
from app.services.account_lockout_service import (
    AccountLockoutService, get_lockout_service, reset_lockout_service
)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Set up a temporary test database for each test."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_state.db")
    
    test_manager = TinyDBStateManager(db_path=db_path)
    set_state_manager(test_manager)
    reset_user_store()
    reset_lockout_service()
    
    yield
    
    test_manager.close()
    set_state_manager(None)
    reset_user_store()
    reset_lockout_service()
    
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except:
        pass


# Strategies for generating test data
username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='_-'),
    min_size=3,
    max_size=20
).filter(lambda x: len(x.strip()) >= 3)


def create_test_user(username: str) -> str:
    """Helper to create a test user and return username."""
    unique_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    test_username = f"{username}_{unique_suffix}"[:50]
    test_email = f"{unique_suffix}@test.com"
    
    user_store = get_user_store()
    user_data = UserCreate(
        username=test_username,
        email=test_email,
        password="SecurePassword123!",
        roles=[UserRole.VIEWER]
    )
    user_store.create_user(user_data)
    return test_username


class TestAccountLockoutProperties:
    """Property-based tests for AccountLockoutService."""
    
    @settings(max_examples=50)
    @given(username=username_strategy)
    def test_property_3_account_lockout_after_five_failures(self, username: str):
        """
        Feature: user-authentication, Property 3: Account lockout after five failures
        
        For any user account, after exactly five consecutive failed login attempts,
        the account SHALL be locked AND subsequent authentication attempts SHALL be rejected.
        
        Validates: Requirements 1.3
        """
        test_username = create_test_user(username)
        lockout_service = AccountLockoutService()
        
        # Initially not locked
        is_locked, _ = lockout_service.is_account_locked(test_username)
        assert is_locked is False
        
        # Record 4 failed attempts - should not be locked yet
        for i in range(4):
            count = lockout_service.record_failed_attempt(test_username)
            assert count == i + 1
            is_locked, _ = lockout_service.is_account_locked(test_username)
            assert is_locked is False
        
        # 5th failed attempt should trigger lockout
        count = lockout_service.record_failed_attempt(test_username)
        assert count == 5
        
        is_locked, remaining = lockout_service.is_account_locked(test_username)
        assert is_locked is True
        assert remaining is not None
        assert remaining > 0
        assert remaining <= 15 * 60  # Max 15 minutes
    
    @settings(max_examples=50)
    @given(username=username_strategy)
    def test_property_6_lockout_counter_reset_after_expiration(self, username: str):
        """
        Feature: user-authentication, Property 6: Lockout counter reset after expiration
        
        For any locked account, after the fifteen-minute lockout period expires,
        the failed login counter SHALL be reset to zero AND the account SHALL accept
        authentication attempts.
        
        Validates: Requirements 1.6
        """
        test_username = create_test_user(username)
        user_store = get_user_store()
        lockout_service = AccountLockoutService()
        
        # Lock the account
        for _ in range(5):
            lockout_service.record_failed_attempt(test_username)
        
        is_locked, _ = lockout_service.is_account_locked(test_username)
        assert is_locked is True
        
        # Simulate lockout expiration by setting last_failed_login to 16 minutes ago
        user = user_store.get_user_by_username(test_username)
        expired_time = (datetime.utcnow() - timedelta(minutes=16)).isoformat()
        user_store.update_user(user.id, {"last_failed_login": expired_time})
        
        # Check lockout status - should be unlocked and counter reset
        is_locked, remaining = lockout_service.is_account_locked(test_username)
        assert is_locked is False
        assert remaining is None
        
        # Counter should be reset
        user = user_store.get_user_by_username(test_username)
        assert user.failed_login_count == 0
    
    @settings(max_examples=50)
    @given(username=username_strategy)
    def test_property_7_successful_auth_resets_failure_counter(self, username: str):
        """
        Feature: user-authentication, Property 7: Successful authentication resets failure counter
        
        For any successful authentication, the user's failed login counter
        SHALL be reset to zero regardless of its previous value.
        
        Validates: Requirements 1.7
        """
        test_username = create_test_user(username)
        lockout_service = AccountLockoutService()
        user_store = get_user_store()
        
        # Record some failed attempts (but not enough to lock)
        for _ in range(3):
            lockout_service.record_failed_attempt(test_username)
        
        # Verify counter is > 0
        user = user_store.get_user_by_username(test_username)
        assert user.failed_login_count == 3
        
        # Simulate successful authentication by resetting counter
        lockout_service.reset_failed_attempts(test_username)
        
        # Counter should be 0
        user = user_store.get_user_by_username(test_username)
        assert user.failed_login_count == 0
    
    @settings(max_examples=30)
    @given(
        username=username_strategy,
        num_failures=st.integers(min_value=1, max_value=4)
    )
    def test_counter_increments_correctly(self, username: str, num_failures: int):
        """
        Verify that failed attempt counter increments by exactly 1 each time.
        """
        test_username = create_test_user(username)
        lockout_service = AccountLockoutService()
        
        for i in range(num_failures):
            count = lockout_service.record_failed_attempt(test_username)
            assert count == i + 1
        
        # Verify final count
        final_count = lockout_service.get_failed_attempt_count(test_username)
        assert final_count == num_failures


class TestAccountLockoutUnit:
    """Unit tests for AccountLockoutService."""
    
    def test_initial_state_not_locked(self):
        """Test that new accounts are not locked."""
        test_username = create_test_user("newuser")
        lockout_service = AccountLockoutService()
        
        is_locked, remaining = lockout_service.is_account_locked(test_username)
        
        assert is_locked is False
        assert remaining is None
    
    def test_unknown_user_not_locked(self):
        """Test that unknown users are not considered locked."""
        lockout_service = AccountLockoutService()
        
        is_locked, remaining = lockout_service.is_account_locked("nonexistent_user")
        
        assert is_locked is False
        assert remaining is None
    
    def test_failed_attempt_unknown_user_returns_zero(self):
        """Test that recording failed attempt for unknown user returns 0."""
        lockout_service = AccountLockoutService()
        
        count = lockout_service.record_failed_attempt("nonexistent_user")
        
        assert count == 0
    
    def test_lockout_duration_is_fifteen_minutes(self):
        """Test that lockout duration is exactly 15 minutes."""
        test_username = create_test_user("lockduration")
        lockout_service = AccountLockoutService()
        
        # Lock the account
        for _ in range(5):
            lockout_service.record_failed_attempt(test_username)
        
        is_locked, remaining = lockout_service.is_account_locked(test_username)
        
        assert is_locked is True
        # Remaining should be close to 15 minutes (900 seconds)
        # Allow some tolerance for test execution time
        assert 890 <= remaining <= 900
    
    def test_get_remaining_attempts(self):
        """Test getting remaining attempts before lockout."""
        test_username = create_test_user("remaining")
        lockout_service = AccountLockoutService()
        
        # Initially should have 5 attempts
        remaining = lockout_service.get_remaining_attempts(test_username)
        assert remaining == 5
        
        # After 2 failures, should have 3 remaining
        lockout_service.record_failed_attempt(test_username)
        lockout_service.record_failed_attempt(test_username)
        
        remaining = lockout_service.get_remaining_attempts(test_username)
        assert remaining == 3
    
    def test_get_remaining_attempts_when_locked(self):
        """Test that remaining attempts is 0 when locked."""
        test_username = create_test_user("lockedremaining")
        lockout_service = AccountLockoutService()
        
        # Lock the account
        for _ in range(5):
            lockout_service.record_failed_attempt(test_username)
        
        remaining = lockout_service.get_remaining_attempts(test_username)
        assert remaining == 0
    
    def test_get_lockout_end_time(self):
        """Test getting lockout end time."""
        test_username = create_test_user("endtime")
        lockout_service = AccountLockoutService()
        
        # Not locked - should return None
        end_time = lockout_service.get_lockout_end_time(test_username)
        assert end_time is None
        
        # Lock the account
        for _ in range(5):
            lockout_service.record_failed_attempt(test_username)
        
        end_time = lockout_service.get_lockout_end_time(test_username)
        assert end_time is not None
        
        # End time should be approximately 15 minutes from now
        expected_end = datetime.utcnow() + timedelta(minutes=15)
        diff = abs((end_time - expected_end).total_seconds())
        assert diff < 5  # Within 5 seconds
    
    def test_counter_not_incremented_while_locked(self):
        """Test that counter doesn't increment while account is locked."""
        test_username = create_test_user("lockedincrement")
        lockout_service = AccountLockoutService()
        
        # Lock the account
        for _ in range(5):
            lockout_service.record_failed_attempt(test_username)
        
        # Try to record more failures
        count = lockout_service.record_failed_attempt(test_username)
        
        # Counter should still be 5
        assert count == 5
        
        final_count = lockout_service.get_failed_attempt_count(test_username)
        assert final_count == 5
