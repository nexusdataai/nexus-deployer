"""
Authentication Service
Core authentication logic integrating user store, JWT, and lockout services.
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from app.models.auth_models import (
    User, UserRole, LoginResponse, AuthError,
    MFAMethod
)
from app.services.user_store import get_user_store, UserStore
from app.services.jwt_service import get_jwt_service, JWTService, TokenExpiredError, TokenInvalidError
from app.services.account_lockout_service import get_lockout_service, AccountLockoutService

logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of an authentication attempt."""
    success: bool
    user: Optional[User] = None
    requires_mfa: bool = False
    mfa_session_token: Optional[str] = None
    mfa_methods: Optional[list] = None
    token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    lockout_remaining: Optional[int] = None


class AuthenticationService:
    """
    Service for user authentication.
    
    Integrates:
    - User store for credential verification
    - JWT service for token management
    - Account lockout service for brute force protection
    """
    
    def __init__(
        self,
        user_store: Optional[UserStore] = None,
        jwt_service: Optional[JWTService] = None,
        lockout_service: Optional[AccountLockoutService] = None
    ):
        """
        Initialize authentication service.
        
        Args:
            user_store: UserStore instance (uses global if not provided)
            jwt_service: JWTService instance (uses global if not provided)
            lockout_service: AccountLockoutService instance (uses global if not provided)
        """
        self._user_store = user_store or get_user_store()
        self._jwt_service = jwt_service or get_jwt_service()
        self._lockout_service = lockout_service or get_lockout_service()
        
        logger.info("AuthenticationService initialized")
    
    def authenticate(self, username: str, password: str) -> AuthResult:
        """
        Authenticate a user with username and password.
        
        Args:
            username: Username
            password: Password
            
        Returns:
            AuthResult with authentication outcome
        """
        # Check if account is locked
        is_locked, remaining = self._lockout_service.is_account_locked(username)
        if is_locked:
            logger.warning(f"Authentication attempt for locked account: {username}")
            return AuthResult(
                success=False,
                error="Account is locked due to too many failed attempts",
                error_code=AuthError.AUTH_002.value,
                lockout_remaining=remaining
            )
        
        # Get user
        user = self._user_store.get_user_by_username(username)
        if not user:
            # Don't reveal whether user exists
            logger.info(f"Authentication failed: user not found - {username}")
            return AuthResult(
                success=False,
                error="Invalid username or password",
                error_code=AuthError.AUTH_001.value
            )
        
        # Check if user is active
        if not user.is_active:
            logger.info(f"Authentication failed: inactive account - {username}")
            return AuthResult(
                success=False,
                error="Account is disabled",
                error_code=AuthError.AUTH_001.value
            )
        
        # Verify password
        if not self._user_store.verify_password(password, user.password_hash):
            # Record failed attempt
            failed_count = self._lockout_service.record_failed_attempt(username)
            
            # Check if now locked
            is_locked, remaining = self._lockout_service.is_account_locked(username)
            if is_locked:
                logger.warning(f"Account locked after failed attempt: {username}")
                return AuthResult(
                    success=False,
                    error="Account is locked due to too many failed attempts",
                    error_code=AuthError.AUTH_002.value,
                    lockout_remaining=remaining
                )
            
            remaining_attempts = self._lockout_service.get_remaining_attempts(username)
            logger.info(
                f"Authentication failed: invalid password - {username} "
                f"({remaining_attempts} attempts remaining)"
            )
            return AuthResult(
                success=False,
                error="Invalid username or password",
                error_code=AuthError.AUTH_001.value
            )
        
        # Password verified - reset failed attempts
        self._lockout_service.reset_failed_attempts(username)
        
        # Check if MFA is required
        if user.mfa_enabled and user.mfa_verified:
            # Create MFA session token
            mfa_session_token = self._jwt_service.create_mfa_session_token(user.id)
            
            mfa_methods = []
            if user.mfa_method:
                mfa_methods.append(user.mfa_method.value)
            
            logger.info(f"MFA required for user: {username}")
            return AuthResult(
                success=True,
                user=user,
                requires_mfa=True,
                mfa_session_token=mfa_session_token,
                mfa_methods=mfa_methods
            )
        
        # Create session tokens
        return self._create_session(user)
    
    def _create_session(self, user: User) -> AuthResult:
        """
        Create session tokens for authenticated user.
        
        Args:
            user: Authenticated user
            
        Returns:
            AuthResult with tokens
        """
        # Convert roles to strings
        roles = [role.value if isinstance(role, UserRole) else role for role in user.roles]
        
        # Create tokens
        access_token = self._jwt_service.create_access_token(
            user_id=user.id,
            username=user.username,
            roles=roles
        )
        refresh_token = self._jwt_service.create_refresh_token(user.id)
        
        # Store session
        token_hash = self._jwt_service.hash_token(access_token)
        refresh_hash = self._jwt_service.hash_token(refresh_token)
        expiry = self._jwt_service.get_token_expiry(access_token)
        
        self._user_store.create_session(
            user_id=user.id,
            token_hash=token_hash,
            refresh_token_hash=refresh_hash,
            expires_at=expiry.isoformat() if expiry else None
        )
        
        logger.info(f"Session created for user: {user.username}")
        
        return AuthResult(
            success=True,
            user=user,
            token=access_token,
            refresh_token=refresh_token,
            expires_in=self._jwt_service.get_access_token_expiry_seconds()
        )
    
    def complete_mfa_authentication(
        self,
        mfa_session_token: str,
        user: User
    ) -> AuthResult:
        """
        Complete authentication after MFA verification.
        
        Args:
            mfa_session_token: MFA session token
            user: User who completed MFA
            
        Returns:
            AuthResult with session tokens
        """
        # Validate MFA session token
        user_id = self._jwt_service.validate_mfa_session_token(mfa_session_token)
        if not user_id or user_id != user.id:
            return AuthResult(
                success=False,
                error="Invalid MFA session",
                error_code=AuthError.MFA_002.value
            )
        
        return self._create_session(user)
    
    def validate_session(self, token: str) -> Optional[User]:
        """
        Validate a session token and return the user.
        
        Args:
            token: JWT access token
            
        Returns:
            User if token is valid, None otherwise
        """
        try:
            payload = self._jwt_service.validate_token(token)
            if not payload:
                return None
            
            # Verify token type
            if payload.get("type") != "access":
                return None
            
            # Get user
            user_id = payload.get("sub")
            if not user_id:
                return None
            
            user = self._user_store.get_user_by_id(user_id)
            if not user or not user.is_active:
                return None
            
            return user
            
        except (TokenExpiredError, TokenInvalidError):
            return None
    
    def refresh_session(self, refresh_token: str) -> AuthResult:
        """
        Refresh a session using a refresh token.
        
        Args:
            refresh_token: JWT refresh token
            
        Returns:
            AuthResult with new tokens
        """
        try:
            payload = self._jwt_service.validate_token(refresh_token)
            if not payload:
                return AuthResult(
                    success=False,
                    error="Invalid refresh token",
                    error_code=AuthError.AUTH_004.value
                )
            
            # Verify token type
            if payload.get("type") != "refresh":
                return AuthResult(
                    success=False,
                    error="Invalid token type",
                    error_code=AuthError.AUTH_004.value
                )
            
            # Get user
            user_id = payload.get("sub")
            user = self._user_store.get_user_by_id(user_id)
            
            if not user or not user.is_active:
                return AuthResult(
                    success=False,
                    error="User not found or inactive",
                    error_code=AuthError.AUTH_005.value
                )
            
            # Create new session
            return self._create_session(user)
            
        except TokenExpiredError:
            return AuthResult(
                success=False,
                error="Refresh token expired",
                error_code=AuthError.AUTH_003.value
            )
        except TokenInvalidError:
            return AuthResult(
                success=False,
                error="Invalid refresh token",
                error_code=AuthError.AUTH_004.value
            )
    
    def logout(self, token: str) -> bool:
        """
        Logout by invalidating the session.
        
        Args:
            token: JWT access token
            
        Returns:
            True if logout successful
        """
        try:
            # Get user ID from token (even if expired)
            user_id = self._jwt_service.get_token_user_id(token)
            if user_id:
                # Invalidate all sessions for user
                count = self._user_store.invalidate_user_sessions(user_id)
                logger.info(f"Logged out user {user_id}, invalidated {count} sessions")
                return True
            return False
        except Exception as e:
            logger.error(f"Logout error: {str(e)}")
            return False
    
    def get_user_info(self, user: User) -> Dict[str, Any]:
        """
        Get safe user info for API response (excludes sensitive data).
        
        Args:
            user: User object
            
        Returns:
            Dictionary with safe user info
        """
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "roles": [role.value if isinstance(role, UserRole) else role for role in user.roles],
            "mfa_enabled": user.mfa_enabled,
            "require_password_change": user.require_password_change
        }


# Global instance
_auth_service: Optional[AuthenticationService] = None


def get_auth_service() -> AuthenticationService:
    """
    Get global AuthenticationService instance.
    
    Returns:
        AuthenticationService instance
    """
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthenticationService()
    return _auth_service


def reset_auth_service():
    """Reset global AuthenticationService instance (for testing)."""
    global _auth_service
    _auth_service = None
