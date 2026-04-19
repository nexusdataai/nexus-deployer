"""
Authentication Router
API endpoints for user authentication, login, logout, and token refresh.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.auth_models import (
    LoginRequest, LoginResponse,
    TokenRefreshRequest, TokenRefreshResponse,
    LogoutRequest, LogoutResponse,
    ChangePasswordRequest, ChangePasswordResponse,
    AuthError
)
from app.services.authentication_service import get_auth_service, AuthenticationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Security scheme for JWT bearer tokens
security = HTTPBearer(auto_error=False)


def get_auth_service_dep() -> AuthenticationService:
    """Dependency to get authentication service."""
    return get_auth_service()


async def get_current_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Extract JWT token from Authorization header.
    
    Supports both:
    - Bearer token in Authorization header
    - Direct token in custom header
    """
    if credentials:
        return credentials.credentials
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    req: Request,
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
) -> LoginResponse:
    """
    Authenticate user with username and password.
    
    Returns JWT tokens on success, or MFA session token if MFA is required.
    
    - **username**: User's username
    - **password**: User's password
    
    Returns:
    - **success**: Whether authentication was successful
    - **requires_mfa**: Whether MFA verification is needed
    - **mfa_session_token**: Token for MFA verification (if MFA required)
    - **token**: JWT access token (if no MFA required)
    - **refresh_token**: JWT refresh token (if no MFA required)
    - **expires_in**: Token expiration in seconds
    - **user**: User information (without sensitive data)
    - **error**: Error message if authentication failed
    - **error_code**: Error code for client handling
    - **lockout_remaining**: Seconds remaining in lockout (if locked)
    """
    logger.info(f"Login attempt for user: {request.username}")
    
    result = auth_service.authenticate(request.username, request.password)
    
    if not result.success and not result.requires_mfa:
        logger.info(f"Login failed for user: {request.username} - {result.error_code}")
        return LoginResponse(
            success=False,
            requires_mfa=False,
            error=result.error,
            error_code=result.error_code,
            lockout_remaining=result.lockout_remaining
        )
    
    if result.requires_mfa:
        logger.info(f"MFA required for user: {request.username}")
        return LoginResponse(
            success=True,
            requires_mfa=True,
            mfa_methods=result.mfa_methods,
            mfa_session_token=result.mfa_session_token
        )
    
    # Full authentication success
    user_info = auth_service.get_user_info(result.user) if result.user else None
    
    logger.info(f"Login successful for user: {request.username}")
    return LoginResponse(
        success=True,
        requires_mfa=False,
        token=result.token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
        user=user_info
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Optional[LogoutRequest] = None,
    token: Optional[str] = Depends(get_current_token),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
) -> LogoutResponse:
    """
    Logout and invalidate current session.
    
    Requires valid JWT token in Authorization header.
    
    Returns:
    - **success**: Whether logout was successful
    - **message**: Status message
    """
    if not token:
        return LogoutResponse(
            success=False,
            message="No token provided"
        )
    
    success = auth_service.logout(token)
    
    if success:
        logger.info("User logged out successfully")
        return LogoutResponse(
            success=True,
            message="Logged out successfully"
        )
    else:
        return LogoutResponse(
            success=False,
            message="Logout failed"
        )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    request: TokenRefreshRequest,
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
) -> TokenRefreshResponse:
    """
    Refresh access token using refresh token.
    
    - **refresh_token**: Valid refresh token
    
    Returns:
    - **success**: Whether refresh was successful
    - **token**: New JWT access token
    - **refresh_token**: New refresh token
    - **expires_in**: Token expiration in seconds
    - **error**: Error message if refresh failed
    """
    logger.info("Token refresh attempt")
    
    result = auth_service.refresh_session(request.refresh_token)
    
    if not result.success:
        logger.info(f"Token refresh failed: {result.error_code}")
        return TokenRefreshResponse(
            success=False,
            error=result.error
        )
    
    logger.info("Token refresh successful")
    return TokenRefreshResponse(
        success=True,
        token=result.token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in
    )


@router.get("/me")
async def get_current_user(
    token: Optional[str] = Depends(get_current_token),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
):
    """
    Get current authenticated user information.
    
    Requires valid JWT token in Authorization header.
    
    Returns:
    - User information (without sensitive data)
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user = auth_service.validate_session(token)
    
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return auth_service.get_user_info(user)


@router.post("/validate")
async def validate_token(
    token: Optional[str] = Depends(get_current_token),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
):
    """
    Validate a JWT token.
    
    Requires valid JWT token in Authorization header.
    
    Returns:
    - **valid**: Whether token is valid
    - **user_id**: User ID if valid
    """
    if not token:
        return {"valid": False, "error": "No token provided"}
    
    user = auth_service.validate_session(token)
    
    if user:
        return {"valid": True, "user_id": user.id}
    else:
        return {"valid": False, "error": "Invalid or expired token"}


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    request: ChangePasswordRequest,
    token: Optional[str] = Depends(get_current_token),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
) -> ChangePasswordResponse:
    """
    Change the current user's password.
    
    Requires valid JWT token in Authorization header.
    
    - **current_password**: User's current password
    - **new_password**: New password (min 12 characters)
    
    Returns:
    - **success**: Whether password change was successful
    - **message**: Status message
    - **error**: Error message if change failed
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user = auth_service.validate_session(token)
    
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Verify current password
    verify_result = auth_service._user_store.verify_user_password(
        user.id, request.current_password
    )
    
    if not verify_result:
        logger.info(f"Password change failed for user {user.username}: incorrect current password")
        return ChangePasswordResponse(
            success=False,
            error="Current password is incorrect",
            error_code="AUTH_001"
        )
    
    # Validate new password is different
    if request.current_password == request.new_password:
        return ChangePasswordResponse(
            success=False,
            error="New password must be different from current password",
            error_code="AUTH_006"
        )
    
    # Update password
    try:
        auth_service._user_store.update_password(user.id, request.new_password)
        
        logger.info(f"Password changed successfully for user: {user.username}")
        return ChangePasswordResponse(
            success=True,
            message="Password changed successfully"
        )
    except Exception as e:
        logger.error(f"Password change failed for user {user.username}: {e}")
        return ChangePasswordResponse(
            success=False,
            error="Failed to change password",
            error_code="AUTH_007"
        )
