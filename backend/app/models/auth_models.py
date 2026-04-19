"""Authentication data models for user authentication, MFA, and sessions."""
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


class UserRole(str, Enum):
    """User roles for role-based access control."""
    ADMINISTRATOR = "Administrator"
    OPERATOR = "Operator"
    VIEWER = "Viewer"


class MFAMethod(str, Enum):
    """Multi-factor authentication methods."""
    TOTP = "totp"
    SMS = "sms"
    EMAIL = "email"


class User(BaseModel):
    """User account model."""
    id: str = Field(..., description="Unique user identifier")
    username: str = Field(..., description="Username for login")
    email: str = Field(..., description="User email address")
    password_hash: str = Field(..., description="Argon2 hashed password")
    roles: List[UserRole] = Field(default_factory=lambda: [UserRole.VIEWER], description="User roles")
    mfa_enabled: bool = Field(default=False, description="Whether MFA is enabled")
    mfa_method: Optional[MFAMethod] = Field(None, description="MFA method if enabled")
    mfa_secret: Optional[str] = Field(None, description="Encrypted TOTP secret")
    mfa_verified: bool = Field(default=False, description="Whether MFA enrollment is verified")
    phone_number: Optional[str] = Field(None, description="Phone number for SMS MFA")
    failed_login_count: int = Field(default=0, description="Consecutive failed login attempts")
    last_failed_login: Optional[str] = Field(None, description="ISO timestamp of last failed login")
    created_at: str = Field(..., description="ISO timestamp of account creation")
    updated_at: str = Field(..., description="ISO timestamp of last update")
    sso_provider: Optional[str] = Field(None, description="SSO provider ID if SSO user")
    sso_subject: Optional[str] = Field(None, description="SSO subject identifier")
    is_active: bool = Field(default=True, description="Whether account is active")
    password_changed_at: Optional[str] = Field(None, description="ISO timestamp of last password change")
    require_password_change: bool = Field(default=False, description="Whether password change is required")


class UserCreate(BaseModel):
    """Request model for creating a new user."""
    username: str = Field(..., min_length=3, max_length=50, description="Username")
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=12, description="Password (min 12 chars)")
    roles: List[UserRole] = Field(default_factory=lambda: [UserRole.VIEWER], description="User roles")


class UserUpdate(BaseModel):
    """Request model for updating a user."""
    email: Optional[str] = Field(None, description="Email address")
    roles: Optional[List[UserRole]] = Field(None, description="User roles")
    is_active: Optional[bool] = Field(None, description="Whether account is active")
    phone_number: Optional[str] = Field(None, description="Phone number for SMS MFA")


class Session(BaseModel):
    """User session model."""
    id: str = Field(..., description="Unique session identifier")
    user_id: str = Field(..., description="Associated user ID")
    token_hash: str = Field(..., description="Hash of the JWT token")
    refresh_token_hash: Optional[str] = Field(None, description="Hash of the refresh token")
    created_at: str = Field(..., description="ISO timestamp of session creation")
    expires_at: str = Field(..., description="ISO timestamp of session expiration")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")
    is_valid: bool = Field(default=True, description="Whether session is still valid")


class MFAEnrollment(BaseModel):
    """MFA enrollment record."""
    id: str = Field(..., description="Unique enrollment identifier")
    user_id: str = Field(..., description="Associated user ID")
    method: MFAMethod = Field(..., description="MFA method")
    secret: str = Field(..., description="Encrypted secret/code")
    verified: bool = Field(default=False, description="Whether enrollment is verified")
    created_at: str = Field(..., description="ISO timestamp of enrollment")


class MFASession(BaseModel):
    """Temporary MFA verification session."""
    id: str = Field(..., description="Unique MFA session identifier")
    user_id: str = Field(..., description="Associated user ID")
    created_at: str = Field(..., description="ISO timestamp of session creation")
    expires_at: str = Field(..., description="ISO timestamp of session expiration")
    retries_remaining: int = Field(default=3, description="Remaining verification attempts")
    code_hash: Optional[str] = Field(None, description="Hash of SMS/email code if applicable")
    is_valid: bool = Field(default=True, description="Whether session is still valid")


# Request/Response models for API endpoints

class LoginRequest(BaseModel):
    """Login request model."""
    username: str = Field(..., description="Username")
    password: str = Field(..., description="Password")


class LoginResponse(BaseModel):
    """Login response model."""
    success: bool = Field(..., description="Whether login was successful")
    requires_mfa: bool = Field(default=False, description="Whether MFA verification is required")
    mfa_methods: Optional[List[str]] = Field(None, description="Available MFA methods")
    mfa_session_token: Optional[str] = Field(None, description="Temporary token for MFA verification")
    token: Optional[str] = Field(None, description="JWT access token")
    refresh_token: Optional[str] = Field(None, description="JWT refresh token")
    expires_in: Optional[int] = Field(None, description="Token expiration in seconds")
    user: Optional[Dict[str, Any]] = Field(None, description="User info (without sensitive data)")
    error: Optional[str] = Field(None, description="Error message if login failed")
    error_code: Optional[str] = Field(None, description="Error code for client handling")
    lockout_remaining: Optional[int] = Field(None, description="Seconds remaining in lockout")


class TokenRefreshRequest(BaseModel):
    """Token refresh request model."""
    refresh_token: str = Field(..., description="Refresh token")


class TokenRefreshResponse(BaseModel):
    """Token refresh response model."""
    success: bool = Field(..., description="Whether refresh was successful")
    token: Optional[str] = Field(None, description="New JWT access token")
    refresh_token: Optional[str] = Field(None, description="New refresh token")
    expires_in: Optional[int] = Field(None, description="Token expiration in seconds")
    error: Optional[str] = Field(None, description="Error message if refresh failed")


class MFAEnrollRequest(BaseModel):
    """MFA enrollment request model."""
    method: MFAMethod = Field(..., description="MFA method to enroll")
    phone_number: Optional[str] = Field(None, description="Phone number for SMS MFA")


class MFAEnrollResponse(BaseModel):
    """MFA enrollment response model."""
    success: bool = Field(..., description="Whether enrollment was initiated")
    qr_code: Optional[str] = Field(None, description="Base64 encoded QR code for TOTP")
    secret: Optional[str] = Field(None, description="TOTP secret for manual entry")
    message: Optional[str] = Field(None, description="Status message")
    error: Optional[str] = Field(None, description="Error message if enrollment failed")


class MFAVerifyRequest(BaseModel):
    """MFA verification request model."""
    code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")
    mfa_session_token: str = Field(..., description="MFA session token from login")


class MFAVerifyResponse(BaseModel):
    """MFA verification response model."""
    success: bool = Field(..., description="Whether verification was successful")
    token: Optional[str] = Field(None, description="JWT access token")
    refresh_token: Optional[str] = Field(None, description="JWT refresh token")
    expires_in: Optional[int] = Field(None, description="Token expiration in seconds")
    user: Optional[Dict[str, Any]] = Field(None, description="User info")
    error: Optional[str] = Field(None, description="Error message if verification failed")
    error_code: Optional[str] = Field(None, description="Error code for client handling")
    retries_remaining: Optional[int] = Field(None, description="Remaining verification attempts")


class MFASendCodeRequest(BaseModel):
    """Request to send MFA code via SMS/email."""
    mfa_session_token: str = Field(..., description="MFA session token")
    method: MFAMethod = Field(..., description="Delivery method (sms or email)")


class MFASendCodeResponse(BaseModel):
    """Response for MFA code send request."""
    success: bool = Field(..., description="Whether code was sent")
    message: Optional[str] = Field(None, description="Status message")
    error: Optional[str] = Field(None, description="Error message if send failed")


class LogoutRequest(BaseModel):
    """Logout request model."""
    refresh_token: Optional[str] = Field(None, description="Refresh token to invalidate")


class LogoutResponse(BaseModel):
    """Logout response model."""
    success: bool = Field(..., description="Whether logout was successful")
    message: Optional[str] = Field(None, description="Status message")


class ChangePasswordRequest(BaseModel):
    """Password change request model."""
    current_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=12, description="New password (min 12 chars)")


class ChangePasswordResponse(BaseModel):
    """Password change response model."""
    success: bool = Field(..., description="Whether password change was successful")
    message: Optional[str] = Field(None, description="Status message")
    error: Optional[str] = Field(None, description="Error message if change failed")
    error_code: Optional[str] = Field(None, description="Error code for client handling")


class AuthError(str, Enum):
    """Authentication error codes."""
    AUTH_001 = "AUTH_001"  # Invalid credentials
    AUTH_002 = "AUTH_002"  # Account locked
    AUTH_003 = "AUTH_003"  # Token expired
    AUTH_004 = "AUTH_004"  # Token invalid
    AUTH_005 = "AUTH_005"  # User not found
    MFA_001 = "MFA_001"    # Invalid MFA code
    MFA_002 = "MFA_002"    # MFA retries exhausted
    MFA_003 = "MFA_003"    # MFA not enabled
    MFA_004 = "MFA_004"    # MFA already enabled
    MFA_005 = "MFA_005"    # Invalid MFA method
    MFA_006 = "MFA_006"    # Code delivery failed
