"""
MFA Service
Multi-factor authentication service supporting TOTP, SMS, and email verification.
"""
import io
import base64
import secrets
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta

from app.models.auth_models import (
    MFAMethod, MFAEnrollResponse, MFAVerifyResponse,
    User, AuthError
)
from app.services.user_store import get_user_store, UserStore
from app.services.jwt_service import get_jwt_service, JWTService

logger = logging.getLogger(__name__)

# Try to import TOTP libraries
try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False
    logger.warning("pyotp not installed, TOTP MFA will be unavailable")

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    logger.warning("qrcode not installed, QR code generation will be unavailable")


class MFAError(Exception):
    """Base exception for MFA errors."""
    pass


class MFANotEnabledError(MFAError):
    """Exception raised when MFA is not enabled."""
    pass


class MFAAlreadyEnabledError(MFAError):
    """Exception raised when MFA is already enabled."""
    pass


class MFAService:
    """
    Service for multi-factor authentication.
    
    Supports:
    - TOTP (Time-based One-Time Password) with authenticator apps
    - SMS verification codes (stub implementation)
    - Email verification codes (stub implementation)
    """
    
    # Configuration
    TOTP_ISSUER = "Totogi Toolkit"
    TOTP_WINDOW = 1  # Allow 1 step before/after for clock drift
    MAX_RETRIES = 3
    CODE_LENGTH = 6
    MFA_SESSION_EXPIRY_MINUTES = 5
    SMS_EMAIL_CODE_EXPIRY_MINUTES = 10
    
    def __init__(
        self,
        user_store: Optional[UserStore] = None,
        jwt_service: Optional[JWTService] = None
    ):
        """
        Initialize MFA service.
        
        Args:
            user_store: UserStore instance (uses global if not provided)
            jwt_service: JWTService instance (uses global if not provided)
        """
        self._user_store = user_store or get_user_store()
        self._jwt_service = jwt_service or get_jwt_service()
        
        logger.info("MFAService initialized")
    
    # ==================== TOTP Methods ====================
    
    def generate_totp_secret(self) -> str:
        """
        Generate a new TOTP secret.
        
        Returns:
            Base32-encoded TOTP secret
        """
        if not PYOTP_AVAILABLE:
            raise MFAError("TOTP is not available (pyotp not installed)")
        
        return pyotp.random_base32()
    
    def generate_qr_code(
        self,
        secret: str,
        username: str,
        issuer: Optional[str] = None
    ) -> str:
        """
        Generate QR code for TOTP enrollment.
        
        Args:
            secret: TOTP secret
            username: Username for the account
            issuer: Issuer name (default: Totogi Toolkit)
            
        Returns:
            Base64-encoded PNG image of QR code
        """
        if not PYOTP_AVAILABLE:
            raise MFAError("TOTP is not available (pyotp not installed)")
        
        if not QRCODE_AVAILABLE:
            raise MFAError("QR code generation is not available (qrcode not installed)")
        
        issuer = issuer or self.TOTP_ISSUER
        
        # Generate provisioning URI
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=username, issuer_name=issuer)
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4
        )
        qr.add_data(uri)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        return base64.b64encode(buffer.getvalue()).decode()
    
    def verify_totp(self, secret: str, code: str) -> bool:
        """
        Verify a TOTP code.
        
        Args:
            secret: TOTP secret
            code: 6-digit code to verify
            
        Returns:
            True if code is valid within the time window
        """
        if not PYOTP_AVAILABLE:
            raise MFAError("TOTP is not available (pyotp not installed)")
        
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=self.TOTP_WINDOW)
    
    def get_current_totp(self, secret: str) -> str:
        """
        Get current TOTP code (for testing).
        
        Args:
            secret: TOTP secret
            
        Returns:
            Current 6-digit TOTP code
        """
        if not PYOTP_AVAILABLE:
            raise MFAError("TOTP is not available (pyotp not installed)")
        
        totp = pyotp.TOTP(secret)
        return totp.now()
    
    # ==================== SMS/Email Code Methods ====================
    
    def generate_numeric_code(self, length: int = None) -> str:
        """
        Generate a random numeric verification code.
        
        Args:
            length: Code length (default: 6)
            
        Returns:
            Random numeric code
        """
        length = length or self.CODE_LENGTH
        return ''.join(str(secrets.randbelow(10)) for _ in range(length))
    
    async def send_sms_code(self, phone_number: str, code: str) -> bool:
        """
        Send verification code via SMS.
        
        Args:
            phone_number: Phone number to send to
            code: Verification code
            
        Returns:
            True if sent successfully
            
        Note: This is a stub implementation. In production, integrate with
        an SMS provider like Twilio, AWS SNS, etc.
        """
        logger.info(f"[STUB] Sending SMS code to {phone_number[-4:]}: {code}")
        # TODO: Implement actual SMS sending
        return True
    
    async def send_email_code(self, email: str, code: str) -> bool:
        """
        Send verification code via email.
        
        Args:
            email: Email address to send to
            code: Verification code
            
        Returns:
            True if sent successfully
            
        Note: This is a stub implementation. In production, integrate with
        an email provider like AWS SES, SendGrid, etc.
        """
        logger.info(f"[STUB] Sending email code to {email}: {code}")
        # TODO: Implement actual email sending
        return True
    
    # ==================== Enrollment Methods ====================
    
    def enroll_totp(self, user: User) -> MFAEnrollResponse:
        """
        Start TOTP MFA enrollment for a user.
        
        Args:
            user: User to enroll
            
        Returns:
            MFAEnrollResponse with QR code and secret
        """
        if user.mfa_enabled and user.mfa_verified:
            return MFAEnrollResponse(
                success=False,
                error="MFA is already enabled for this account"
            )
        
        # Generate secret
        secret = self.generate_totp_secret()
        
        # Generate QR code
        try:
            qr_code = self.generate_qr_code(secret, user.username)
        except MFAError as e:
            return MFAEnrollResponse(
                success=False,
                error=str(e)
            )
        
        # Store enrollment (not yet verified)
        self._user_store.create_mfa_enrollment(
            user_id=user.id,
            method=MFAMethod.TOTP,
            secret=secret
        )
        
        # Update user with MFA info (not enabled until verified)
        self._user_store.update_user(user.id, {
            "mfa_method": MFAMethod.TOTP.value,
            "mfa_secret": secret,
            "mfa_enabled": False,
            "mfa_verified": False
        })
        
        logger.info(f"TOTP enrollment started for user: {user.username}")
        
        return MFAEnrollResponse(
            success=True,
            qr_code=qr_code,
            secret=secret,
            message="Scan the QR code with your authenticator app, then verify with a code"
        )
    
    def verify_enrollment(self, user: User, code: str) -> MFAEnrollResponse:
        """
        Verify MFA enrollment with first code.
        
        Args:
            user: User verifying enrollment
            code: Verification code from authenticator
            
        Returns:
            MFAEnrollResponse indicating success/failure
        """
        if not user.mfa_secret:
            return MFAEnrollResponse(
                success=False,
                error="No MFA enrollment in progress"
            )
        
        if user.mfa_verified:
            return MFAEnrollResponse(
                success=False,
                error="MFA is already verified"
            )
        
        # Verify the code
        if not self.verify_totp(user.mfa_secret, code):
            return MFAEnrollResponse(
                success=False,
                error="Invalid verification code"
            )
        
        # Enable MFA
        self._user_store.update_user(user.id, {
            "mfa_enabled": True,
            "mfa_verified": True
        })
        
        # Mark enrollment as verified
        self._user_store.verify_mfa_enrollment(user.id)
        
        logger.info(f"MFA enrollment verified for user: {user.username}")
        
        return MFAEnrollResponse(
            success=True,
            message="MFA has been enabled successfully"
        )
    
    def disable_mfa(self, user: User) -> bool:
        """
        Disable MFA for a user.
        
        Args:
            user: User to disable MFA for
            
        Returns:
            True if disabled successfully
        """
        if not user.mfa_enabled:
            return False
        
        # Update user
        self._user_store.update_user(user.id, {
            "mfa_enabled": False,
            "mfa_verified": False,
            "mfa_secret": None,
            "mfa_method": None
        })
        
        # Delete enrollment
        self._user_store.delete_mfa_enrollment(user.id)
        
        logger.info(f"MFA disabled for user: {user.username}")
        return True
    
    # ==================== Verification Methods ====================
    
    def create_mfa_session(
        self,
        user: User,
        method: MFAMethod = None
    ) -> Tuple[str, Optional[str]]:
        """
        Create an MFA verification session.
        
        Args:
            user: User requiring MFA
            method: MFA method (uses user's default if not specified)
            
        Returns:
            Tuple of (session_token, code_if_sms_or_email)
        """
        method = method or user.mfa_method
        
        expires_at = (
            datetime.utcnow() + 
            timedelta(minutes=self.MFA_SESSION_EXPIRY_MINUTES)
        ).isoformat()
        
        code = None
        code_hash = None
        
        # For SMS/email, generate and store code
        if method in (MFAMethod.SMS, MFAMethod.EMAIL):
            code = self.generate_numeric_code()
            code_hash = self._jwt_service.hash_token(code)
        
        # Create MFA session
        mfa_session = self._user_store.create_mfa_session(
            user_id=user.id,
            expires_at=expires_at,
            code_hash=code_hash
        )
        
        logger.info(f"MFA session created for user: {user.username}")
        
        return mfa_session.id, code
    
    def verify_mfa_code(
        self,
        mfa_session_token: str,
        code: str
    ) -> MFAVerifyResponse:
        """
        Verify an MFA code.
        
        Args:
            mfa_session_token: MFA session token from JWT
            code: Verification code
            
        Returns:
            MFAVerifyResponse indicating success/failure
        """
        # Validate MFA session token
        user_id = self._jwt_service.validate_mfa_session_token(mfa_session_token)
        if not user_id:
            return MFAVerifyResponse(
                success=False,
                error="Invalid or expired MFA session",
                error_code=AuthError.MFA_002.value
            )
        
        # Get user
        user = self._user_store.get_user_by_id(user_id)
        if not user:
            return MFAVerifyResponse(
                success=False,
                error="User not found"
            )
        
        # Get MFA session from user store (for retry tracking)
        # Note: In a full implementation, we'd track retries per session
        
        # Verify based on method
        if user.mfa_method == MFAMethod.TOTP:
            if not user.mfa_secret:
                return MFAVerifyResponse(
                    success=False,
                    error="MFA not configured"
                )
            
            if self.verify_totp(user.mfa_secret, code):
                logger.info(f"MFA verification successful for user: {user.username}")
                return MFAVerifyResponse(
                    success=True
                )
            else:
                logger.info(f"MFA verification failed for user: {user.username}")
                return MFAVerifyResponse(
                    success=False,
                    error="Invalid verification code",
                    retries_remaining=2  # Simplified retry tracking
                )
        
        # For SMS/email, verify against stored code hash
        # This would require looking up the MFA session and comparing hashes
        
        return MFAVerifyResponse(
            success=False,
            error="Unsupported MFA method"
        )


# Global instance
_mfa_service: Optional[MFAService] = None


def get_mfa_service() -> MFAService:
    """
    Get global MFAService instance.
    
    Returns:
        MFAService instance
    """
    global _mfa_service
    if _mfa_service is None:
        _mfa_service = MFAService()
    return _mfa_service


def reset_mfa_service():
    """Reset global MFAService instance (for testing)."""
    global _mfa_service
    _mfa_service = None
