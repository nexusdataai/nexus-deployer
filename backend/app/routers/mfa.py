"""
MFA Router
API endpoints for multi-factor authentication enrollment and verification.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.auth_models import (
    MFAMethod, MFAEnrollRequest, MFAEnrollResponse,
    MFAVerifyRequest, MFAVerifyResponse, MFASendCodeRequest,
    AuthError
)
from app.services.mfa_service import get_mfa_service, MFAService
from app.services.authentication_service import get_auth_service, AuthenticationService
from app.services.jwt_service import get_jwt_service, JWTService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mfa", tags=["mfa"])

# Security scheme for JWT bearer tokens
security = HTTPBearer(auto_error=False)


def get_mfa_service_dep() -> MFAService:
    """Dependency to get MFA service."""
    return get_mfa_service()


def get_auth_service_dep() -> AuthenticationService:
    """Dependency to get authentication service."""
    return get_auth_service()


def get_jwt_service_dep() -> JWTService:
    """Dependency to get JWT service."""
    return get_jwt_service()


async def get_current_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """Extract JWT token from Authorization header."""
    if credentials:
        return credentials.credentials
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


@router.post("/enroll", response_model=MFAEnrollResponse)
async def enroll_mfa(
    request: MFAEnrollRequest,
    token: Optional[str] = Depends(get_current_token),
    mfa_service: MFAService = Depends(get_mfa_service_dep),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
) -> MFAEnrollResponse:
    """
    Enroll user in MFA.
    
    Requires valid JWT token in Authorization header.
    
    - **method**: MFA method to enroll ("totp", "sms", "email")
    - **phone_number**: Required for SMS method
    - **email**: Required for email method (uses account email if not provided)
    
    Returns:
    - **success**: Whether enrollment was initiated
    - **qr_code**: Base64 encoded QR code for TOTP enrollment
    - **secret**: TOTP secret for manual entry
    - **message**: Status message
    - **error**: Error message if enrollment failed
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Validate token and get user
    user = auth_service.validate_session(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    logger.info(f"MFA enrollment request for user: {user.username}, method: {request.method}")
    
    # Handle different MFA methods
    if request.method == MFAMethod.TOTP:
        result = mfa_service.enroll_totp(user)
        return result
    
    elif request.method == MFAMethod.SMS:
        if not request.phone_number and not user.phone_number:
            return MFAEnrollResponse(
                success=False,
                error="Phone number is required for SMS MFA"
            )
        # Store phone number if provided
        # TODO: Implement SMS enrollment
        return MFAEnrollResponse(
            success=False,
            error="SMS MFA enrollment is not yet implemented"
        )
    
    elif request.method == MFAMethod.EMAIL:
        # Use provided email or account email
        # TODO: Implement email enrollment
        return MFAEnrollResponse(
            success=False,
            error="Email MFA enrollment is not yet implemented"
        )
    
    return MFAEnrollResponse(
        success=False,
        error=f"Unsupported MFA method: {request.method}"
    )


@router.post("/verify-enrollment", response_model=MFAEnrollResponse)
async def verify_enrollment(
    request: MFAVerifyRequest,
    token: Optional[str] = Depends(get_current_token),
    mfa_service: MFAService = Depends(get_mfa_service_dep),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
) -> MFAEnrollResponse:
    """
    Verify MFA enrollment with first code.
    
    This endpoint is used to complete MFA enrollment by verifying
    the first code from the authenticator app.
    
    Requires valid JWT token in Authorization header.
    
    - **code**: 6-digit verification code from authenticator
    
    Returns:
    - **success**: Whether verification was successful
    - **message**: Status message
    - **error**: Error message if verification failed
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Validate token and get user
    user = auth_service.validate_session(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    logger.info(f"MFA enrollment verification for user: {user.username}")
    
    result = mfa_service.verify_enrollment(user, request.code)
    return result


@router.post("/verify", response_model=MFAVerifyResponse)
async def verify_mfa(
    request: MFAVerifyRequest,
    mfa_service: MFAService = Depends(get_mfa_service_dep),
    auth_service: AuthenticationService = Depends(get_auth_service_dep),
    jwt_service: JWTService = Depends(get_jwt_service_dep)
) -> MFAVerifyResponse:
    """
    Verify MFA code and complete authentication.
    
    This endpoint is used during login when MFA is required.
    
    - **code**: 6-digit verification code
    - **mfa_session_token**: MFA session token from login response
    
    Returns:
    - **success**: Whether verification was successful
    - **token**: JWT access token (if successful)
    - **refresh_token**: JWT refresh token (if successful)
    - **expires_in**: Token expiration in seconds
    - **error**: Error message if verification failed
    - **error_code**: Error code for client handling
    - **retries_remaining**: Number of retries left (if failed)
    """
    if not request.mfa_session_token:
        return MFAVerifyResponse(
            success=False,
            error="MFA session token is required",
            error_code=AuthError.MFA_002.value
        )
    
    logger.info("MFA verification attempt")
    
    # Verify the MFA code
    result = mfa_service.verify_mfa_code(request.mfa_session_token, request.code)
    
    if not result.success:
        logger.info(f"MFA verification failed: {result.error}")
        return result
    
    # MFA verification successful - create full session
    # Extract user_id from MFA session token
    user_id = jwt_service.validate_mfa_session_token(request.mfa_session_token)
    if not user_id:
        return MFAVerifyResponse(
            success=False,
            error="Invalid MFA session",
            error_code=AuthError.MFA_002.value
        )
    
    # Get user and create session
    from app.services.user_store import get_user_store
    user_store = get_user_store()
    user = user_store.get_user_by_id(user_id)
    
    if not user:
        return MFAVerifyResponse(
            success=False,
            error="User not found"
        )
    
    # Create full session tokens
    access_token = jwt_service.create_access_token(user.id, user.roles)
    refresh_token = jwt_service.create_refresh_token(user.id)
    
    logger.info(f"MFA verification successful for user: {user.username}")
    
    return MFAVerifyResponse(
        success=True,
        token=access_token,
        refresh_token=refresh_token,
        expires_in=1800  # 30 minutes
    )


@router.post("/send-code")
async def send_mfa_code(
    request: MFASendCodeRequest,
    mfa_service: MFAService = Depends(get_mfa_service_dep),
    jwt_service: JWTService = Depends(get_jwt_service_dep)
):
    """
    Send MFA code via SMS or email.
    
    This endpoint is used to send/resend verification codes
    for SMS or email MFA methods.
    
    - **mfa_session_token**: MFA session token from login response
    - **method**: MFA method ("sms" or "email")
    
    Returns:
    - **success**: Whether code was sent
    - **message**: Status message
    - **error**: Error message if sending failed
    """
    if not request.mfa_session_token:
        return {
            "success": False,
            "error": "MFA session token is required"
        }
    
    # Validate MFA session token
    user_id = jwt_service.validate_mfa_session_token(request.mfa_session_token)
    if not user_id:
        return {
            "success": False,
            "error": "Invalid or expired MFA session"
        }
    
    # Get user
    from app.services.user_store import get_user_store
    user_store = get_user_store()
    user = user_store.get_user_by_id(user_id)
    
    if not user:
        return {
            "success": False,
            "error": "User not found"
        }
    
    logger.info(f"MFA code send request for user: {user.username}, method: {request.method}")
    
    # Generate and send code based on method
    if request.method == MFAMethod.SMS:
        if not user.phone_number:
            return {
                "success": False,
                "error": "No phone number configured for this account"
            }
        
        code = mfa_service.generate_numeric_code()
        success = await mfa_service.send_sms_code(user.phone_number, code)
        
        if success:
            # Store code hash for verification
            # TODO: Store code hash in MFA session
            return {
                "success": True,
                "message": f"Code sent to phone ending in {user.phone_number[-4:]}"
            }
        else:
            return {
                "success": False,
                "error": "Failed to send SMS code"
            }
    
    elif request.method == MFAMethod.EMAIL:
        code = mfa_service.generate_numeric_code()
        success = await mfa_service.send_email_code(user.email, code)
        
        if success:
            # Store code hash for verification
            # TODO: Store code hash in MFA session
            return {
                "success": True,
                "message": f"Code sent to {user.email}"
            }
        else:
            return {
                "success": False,
                "error": "Failed to send email code"
            }
    
    return {
        "success": False,
        "error": f"Unsupported MFA method: {request.method}"
    }


@router.post("/disable")
async def disable_mfa(
    token: Optional[str] = Depends(get_current_token),
    mfa_service: MFAService = Depends(get_mfa_service_dep),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
):
    """
    Disable MFA for the current user.
    
    Requires valid JWT token in Authorization header.
    
    Returns:
    - **success**: Whether MFA was disabled
    - **message**: Status message
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Validate token and get user
    user = auth_service.validate_session(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    logger.info(f"MFA disable request for user: {user.username}")
    
    success = mfa_service.disable_mfa(user)
    
    if success:
        return {
            "success": True,
            "message": "MFA has been disabled"
        }
    else:
        return {
            "success": False,
            "message": "MFA is not enabled for this account"
        }


@router.get("/status")
async def get_mfa_status(
    token: Optional[str] = Depends(get_current_token),
    auth_service: AuthenticationService = Depends(get_auth_service_dep)
):
    """
    Get MFA status for the current user.
    
    Requires valid JWT token in Authorization header.
    
    Returns:
    - **enabled**: Whether MFA is enabled
    - **verified**: Whether MFA enrollment is verified
    - **method**: Current MFA method (if enabled)
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Validate token and get user
    user = auth_service.validate_session(token)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return {
        "enabled": user.mfa_enabled,
        "verified": user.mfa_verified,
        "method": user.mfa_method.value if user.mfa_method else None
    }
