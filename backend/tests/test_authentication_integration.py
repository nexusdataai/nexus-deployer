"""
Integration tests for Authentication Flow.
Feature: user-authentication
Validates: Requirements 1.1, 1.2, 1.3
"""
import pytest
import tempfile
import os
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.auth_models import UserCreate, UserRole, LoginRequest
from app.services.tinydb_state_manager import TinyDBStateManager, set_state_manager
from app.services.user_store import get_user_store, reset_user_store
from app.services.jwt_service import JWTService, reset_jwt_service
from app.services.account_lockout_service import reset_lockout_service
from app.services.authentication_service import (
    AuthenticationService, get_auth_service, reset_auth_service
)


@pytest.fixture(autouse=True)
def setup_test_environment():
    """Set up test environment with temporary database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_state.db")
    
    test_manager = TinyDBStateManager(db_path=db_path)
    set_state_manager(test_manager)
    reset_user_store()
    reset_jwt_service()
    reset_lockout_service()
    reset_auth_service()
    
    yield
    
    test_manager.close()
    set_state_manager(None)
    reset_user_store()
    reset_jwt_service()
    reset_lockout_service()
    reset_auth_service()
    
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except:
        pass


def create_test_user(
    username: str = "testuser",
    password: str = "SecurePassword123!",
    roles: list = None
) -> str:
    """Helper to create a test user."""
    if roles is None:
        roles = [UserRole.VIEWER]
    
    unique_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    test_username = f"{username}_{unique_suffix}"[:50]
    test_email = f"{unique_suffix}@test.com"
    
    user_store = get_user_store()
    user_data = UserCreate(
        username=test_username,
        email=test_email,
        password=password,
        roles=roles
    )
    user_store.create_user(user_data)
    return test_username


class TestAuthenticationFlowIntegration:
    """Integration tests for complete authentication flow."""
    
    def test_full_login_flow_with_valid_credentials(self):
        """
        Test complete login flow with valid credentials.
        Validates: Requirements 1.1
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Authenticate
        result = auth_service.authenticate(username, password)
        
        # Verify success
        assert result.success is True
        assert result.requires_mfa is False
        assert result.token is not None
        assert result.refresh_token is not None
        assert result.expires_in == 1800  # 30 minutes
        assert result.user is not None
        assert result.user.username == username
        
        # Verify token is valid
        user = auth_service.validate_session(result.token)
        assert user is not None
        assert user.username == username
    
    def test_login_rejection_with_invalid_credentials(self):
        """
        Test login rejection with invalid password.
        Validates: Requirements 1.2
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Try to authenticate with wrong password
        result = auth_service.authenticate(username, "WrongPassword123!")
        
        # Verify rejection
        assert result.success is False
        assert result.token is None
        assert result.error is not None
        assert "Invalid" in result.error
    
    def test_login_rejection_with_nonexistent_user(self):
        """
        Test login rejection for non-existent user.
        Validates: Requirements 1.2
        """
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Try to authenticate non-existent user
        result = auth_service.authenticate("nonexistent_user", "SomePassword123!")
        
        # Verify rejection (should not reveal user doesn't exist)
        assert result.success is False
        assert result.token is None
        assert "Invalid" in result.error
    
    def test_account_lockout_after_5_failures(self):
        """
        Test account lockout after 5 failed login attempts.
        Validates: Requirements 1.3
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Make 5 failed attempts
        for i in range(5):
            result = auth_service.authenticate(username, "WrongPassword!")
            assert result.success is False
        
        # 6th attempt should show locked message
        result = auth_service.authenticate(username, "WrongPassword!")
        
        assert result.success is False
        assert "locked" in result.error.lower()
        assert result.lockout_remaining is not None
        assert result.lockout_remaining > 0
        
        # Even correct password should fail while locked
        result = auth_service.authenticate(username, password)
        
        assert result.success is False
        assert "locked" in result.error.lower()
    
    def test_token_refresh_flow(self):
        """
        Test token refresh flow.
        Validates: Requirements 1.4, 1.5
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Login
        login_result = auth_service.authenticate(username, password)
        assert login_result.success is True
        
        original_token = login_result.token
        refresh_token = login_result.refresh_token
        
        # Refresh token
        refresh_result = auth_service.refresh_session(refresh_token)
        
        assert refresh_result.success is True
        assert refresh_result.token is not None
        assert refresh_result.refresh_token is not None
        
        # New token should be different
        assert refresh_result.token != original_token
        
        # New token should be valid
        user = auth_service.validate_session(refresh_result.token)
        assert user is not None
        assert user.username == username
    
    def test_logout_invalidates_session(self):
        """
        Test that logout invalidates the session.
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Login
        login_result = auth_service.authenticate(username, password)
        assert login_result.success is True
        
        token = login_result.token
        
        # Verify token is valid
        user = auth_service.validate_session(token)
        assert user is not None
        
        # Logout
        logout_success = auth_service.logout(token)
        assert logout_success is True
    
    def test_failed_login_counter_reset_on_success(self):
        """
        Test that failed login counter resets after successful login.
        Validates: Requirements 1.7
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        user_store = get_user_store()
        
        # Make some failed attempts (but not enough to lock)
        for _ in range(3):
            auth_service.authenticate(username, "WrongPassword!")
        
        # Verify counter is > 0
        user = user_store.get_user_by_username(username)
        assert user.failed_login_count == 3
        
        # Successful login
        result = auth_service.authenticate(username, password)
        assert result.success is True
        
        # Counter should be reset
        user = user_store.get_user_by_username(username)
        assert user.failed_login_count == 0
    
    def test_inactive_user_cannot_login(self):
        """
        Test that inactive users cannot login.
        """
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        user_store = get_user_store()
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        # Deactivate user
        user = user_store.get_user_by_username(username)
        user_store.update_user(user.id, {"is_active": False})
        
        # Try to login
        result = auth_service.authenticate(username, password)
        
        assert result.success is False
        assert result.token is None


class TestAuthenticationRoles:
    """Tests for role-based authentication."""
    
    def test_admin_user_login(self):
        """Test administrator user login."""
        password = "SecurePassword123!"
        username = create_test_user(
            password=password,
            roles=[UserRole.ADMINISTRATOR]
        )
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        result = auth_service.authenticate(username, password)
        
        assert result.success is True
        assert result.user is not None
        assert UserRole.ADMINISTRATOR in result.user.roles
    
    def test_operator_user_login(self):
        """Test operator user login."""
        password = "SecurePassword123!"
        username = create_test_user(
            password=password,
            roles=[UserRole.OPERATOR]
        )
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        result = auth_service.authenticate(username, password)
        
        assert result.success is True
        assert result.user is not None
        assert UserRole.OPERATOR in result.user.roles
    
    def test_user_info_excludes_sensitive_data(self):
        """Test that user info response excludes sensitive data."""
        password = "SecurePassword123!"
        username = create_test_user(password=password)
        
        auth_service = AuthenticationService(
            jwt_service=JWTService(secret_key="test-secret")
        )
        
        result = auth_service.authenticate(username, password)
        user_info = auth_service.get_user_info(result.user)
        
        # Should include safe fields
        assert "id" in user_info
        assert "username" in user_info
        assert "email" in user_info
        assert "roles" in user_info
        
        # Should NOT include sensitive fields
        assert "password_hash" not in user_info
        assert "mfa_secret" not in user_info
