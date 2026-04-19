"""
Property-based tests for JWT Service.
Feature: user-authentication
Validates: Requirements 1.4, 1.5
"""
import pytest
import time
from hypothesis import given, strategies as st, settings, assume
from datetime import datetime, timedelta
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.jwt_service import (
    JWTService, get_jwt_service, reset_jwt_service,
    TokenExpiredError, TokenInvalidError
)


@pytest.fixture(autouse=True)
def setup_jwt_service():
    """Set up JWT service with a fixed secret for testing."""
    reset_jwt_service()
    yield
    reset_jwt_service()


# Strategies for generating test data
user_id_strategy = st.uuids().map(str)
username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='_-'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)
roles_strategy = st.lists(
    st.sampled_from(["Administrator", "Operator", "Viewer"]),
    min_size=1,
    max_size=3,
    unique=True
)


class TestJWTServiceProperties:
    """Property-based tests for JWTService."""
    
    @settings(max_examples=100)
    @given(
        user_id=user_id_strategy,
        username=username_strategy,
        roles=roles_strategy
    )
    def test_property_4_jwt_token_expiration_is_thirty_minutes(
        self,
        user_id: str,
        username: str,
        roles: list
    ):
        """
        Feature: user-authentication, Property 4: JWT token expiration is thirty minutes
        
        For any JWT token created by the authentication service,
        the token's expiration time SHALL be exactly thirty minutes from creation.
        
        Validates: Requirements 1.4
        """
        jwt_service = JWTService(secret_key="test-secret-key-for-testing")
        
        # Record time before token creation
        before_creation = datetime.utcnow()
        
        # Create access token
        token = jwt_service.create_access_token(user_id, username, roles)
        
        # Record time after token creation
        after_creation = datetime.utcnow()
        
        # Get token expiry
        expiry = jwt_service.get_token_expiry(token)
        
        assert expiry is not None
        
        # Calculate expected expiry range (30 minutes from creation)
        expected_expiry_min = before_creation + timedelta(minutes=30)
        expected_expiry_max = after_creation + timedelta(minutes=30)
        
        # Allow 1 second tolerance for timing
        tolerance = timedelta(seconds=1)
        
        assert expiry >= expected_expiry_min - tolerance
        assert expiry <= expected_expiry_max + tolerance
    
    @settings(max_examples=100)
    @given(
        user_id=user_id_strategy,
        username=username_strategy,
        roles=roles_strategy
    )
    def test_property_5_expired_tokens_are_rejected(
        self,
        user_id: str,
        username: str,
        roles: list
    ):
        """
        Feature: user-authentication, Property 5: Expired tokens are rejected
        
        For any JWT token that has passed its expiration time,
        the authentication service SHALL reject the token.
        
        Validates: Requirements 1.5
        """
        jwt_service = JWTService(secret_key="test-secret-key-for-testing")
        
        # Create a token with very short expiry for testing
        # We'll mock the time to simulate expiration
        token = jwt_service.create_access_token(user_id, username, roles)
        
        # Token should be valid immediately after creation
        payload = jwt_service.validate_token(token)
        assert payload is not None
        assert payload["sub"] == user_id
        
        # Simulate token expiration by creating an already-expired token
        import jwt as pyjwt
        
        expired_payload = {
            "sub": user_id,
            "username": username,
            "roles": roles,
            "type": "access",
            "jti": "test-jti",
            "iat": datetime.utcnow() - timedelta(hours=1),
            "exp": datetime.utcnow() - timedelta(minutes=1)  # Expired 1 minute ago
        }
        
        expired_token = pyjwt.encode(
            expired_payload,
            "test-secret-key-for-testing",
            algorithm="HS256"
        )
        
        # Expired token should be rejected
        with pytest.raises(TokenExpiredError):
            jwt_service.validate_token(expired_token)
        
        # is_token_expired should return True
        assert jwt_service.is_token_expired(expired_token) is True
    
    @settings(max_examples=50)
    @given(
        user_id=user_id_strategy,
        username=username_strategy,
        roles=roles_strategy
    )
    def test_token_contains_correct_claims(
        self,
        user_id: str,
        username: str,
        roles: list
    ):
        """
        Verify that created tokens contain all expected claims.
        """
        jwt_service = JWTService(secret_key="test-secret-key-for-testing")
        
        token = jwt_service.create_access_token(user_id, username, roles)
        payload = jwt_service.validate_token(token)
        
        assert payload is not None
        assert payload["sub"] == user_id
        assert payload["username"] == username
        assert payload["roles"] == roles
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload
    
    @settings(max_examples=50)
    @given(user_id=user_id_strategy)
    def test_refresh_token_has_longer_expiry(self, user_id: str):
        """
        Verify that refresh tokens have longer expiry than access tokens.
        """
        jwt_service = JWTService(secret_key="test-secret-key-for-testing")
        
        access_token = jwt_service.create_access_token(user_id, "testuser", ["Viewer"])
        refresh_token = jwt_service.create_refresh_token(user_id)
        
        access_expiry = jwt_service.get_token_expiry(access_token)
        refresh_expiry = jwt_service.get_token_expiry(refresh_token)
        
        assert access_expiry is not None
        assert refresh_expiry is not None
        
        # Refresh token should expire later than access token
        assert refresh_expiry > access_expiry
        
        # Refresh token should be valid for at least 1 day
        assert refresh_expiry > datetime.utcnow() + timedelta(days=1)
    
    @settings(max_examples=50)
    @given(
        user_id=user_id_strategy,
        username=username_strategy,
        roles=roles_strategy
    )
    def test_token_hash_is_deterministic(
        self,
        user_id: str,
        username: str,
        roles: list
    ):
        """
        Verify that token hashing is deterministic.
        """
        jwt_service = JWTService(secret_key="test-secret-key-for-testing")
        
        token = jwt_service.create_access_token(user_id, username, roles)
        
        hash1 = jwt_service.hash_token(token)
        hash2 = jwt_service.hash_token(token)
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64 hex characters


class TestJWTServiceUnit:
    """Unit tests for JWTService."""
    
    def test_create_access_token(self):
        """Test access token creation."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_access_token(
            user_id="user-123",
            username="testuser",
            roles=["Viewer"]
        )
        
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0
    
    def test_create_refresh_token(self):
        """Test refresh token creation."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_refresh_token(user_id="user-123")
        
        assert token is not None
        assert isinstance(token, str)
        
        # Verify it's a refresh token
        token_type = jwt_service.get_token_type(token)
        assert token_type == "refresh"
    
    def test_validate_valid_token(self):
        """Test validation of valid token."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_access_token(
            user_id="user-123",
            username="testuser",
            roles=["Viewer"]
        )
        
        payload = jwt_service.validate_token(token)
        
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["username"] == "testuser"
    
    def test_validate_invalid_token(self):
        """Test validation of invalid token."""
        jwt_service = JWTService(secret_key="test-secret")
        
        with pytest.raises(TokenInvalidError):
            jwt_service.validate_token("invalid-token")
    
    def test_validate_token_wrong_secret(self):
        """Test validation fails with wrong secret."""
        jwt_service1 = JWTService(secret_key="secret-1")
        jwt_service2 = JWTService(secret_key="secret-2")
        
        token = jwt_service1.create_access_token(
            user_id="user-123",
            username="testuser",
            roles=["Viewer"]
        )
        
        with pytest.raises(TokenInvalidError):
            jwt_service2.validate_token(token)
    
    def test_validate_token_safe_returns_none_on_error(self):
        """Test validate_token_safe returns None instead of raising."""
        jwt_service = JWTService(secret_key="test-secret")
        
        result = jwt_service.validate_token_safe("invalid-token")
        assert result is None
    
    def test_get_token_user_id(self):
        """Test extracting user ID from token."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_access_token(
            user_id="user-456",
            username="testuser",
            roles=["Viewer"]
        )
        
        user_id = jwt_service.get_token_user_id(token)
        assert user_id == "user-456"
    
    def test_create_mfa_session_token(self):
        """Test MFA session token creation."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_mfa_session_token(user_id="user-123")
        
        assert token is not None
        
        # Validate MFA session token
        user_id = jwt_service.validate_mfa_session_token(token)
        assert user_id == "user-123"
    
    def test_mfa_session_token_type(self):
        """Test MFA session token has correct type."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_mfa_session_token(user_id="user-123")
        token_type = jwt_service.get_token_type(token)
        
        assert token_type == "mfa_session"
    
    def test_access_token_expiry_seconds(self):
        """Test getting access token expiry in seconds."""
        jwt_service = JWTService(secret_key="test-secret")
        
        expiry_seconds = jwt_service.get_access_token_expiry_seconds()
        
        # Should be 30 minutes = 1800 seconds
        assert expiry_seconds == 1800
    
    def test_additional_claims(self):
        """Test adding additional claims to token."""
        jwt_service = JWTService(secret_key="test-secret")
        
        token = jwt_service.create_access_token(
            user_id="user-123",
            username="testuser",
            roles=["Viewer"],
            additional_claims={"custom_field": "custom_value"}
        )
        
        payload = jwt_service.validate_token(token)
        
        assert payload["custom_field"] == "custom_value"
