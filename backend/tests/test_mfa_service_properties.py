"""
Property-based tests for MFA Service.
Feature: user-authentication
Validates: Requirements 2.1, 2.3, 2.4, 2.7, 2.8
"""
import pytest
import tempfile
import os
import re
import base64
from hypothesis import given, strategies as st, settings, assume
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.models.auth_models import UserCreate, UserRole, MFAMethod
from app.services.tinydb_state_manager import TinyDBStateManager, set_state_manager
from app.services.user_store import get_user_store, reset_user_store
from app.services.jwt_service import JWTService, reset_jwt_service
from app.services.mfa_service import (
    MFAService, get_mfa_service, reset_mfa_service,
    PYOTP_AVAILABLE, QRCODE_AVAILABLE
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
    reset_mfa_service()
    
    yield
    
    test_manager.close()
    set_state_manager(None)
    reset_user_store()
    reset_jwt_service()
    reset_mfa_service()
    
    try:
        os.remove(db_path)
        os.rmdir(temp_dir)
    except:
        pass


def create_test_user(username: str = "testuser") -> "User":
    """Helper to create a test user."""
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
    return user_store.create_user(user_data)


@pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
class TestMFAServiceProperties:
    """Property-based tests for MFAService."""
    
    @settings(max_examples=50)
    @given(username=st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('L', 'N'))))
    def test_property_8_mfa_enrollment_produces_valid_totp_secret(self, username: str):
        """
        Feature: user-authentication, Property 8: MFA enrollment produces valid TOTP secret
        
        For any MFA enrollment request, the MFA service SHALL generate a valid
        TOTP secret (base32 encoded, minimum 16 characters) AND a QR code that
        encodes the correct provisioning URI.
        
        Validates: Requirements 2.1
        """
        assume(len(username.strip()) >= 3)
        
        user = create_test_user(username)
        mfa_service = MFAService()
        
        # Enroll in TOTP
        result = mfa_service.enroll_totp(user)
        
        assert result.success is True
        assert result.secret is not None
        
        # Secret should be base32 encoded (only A-Z and 2-7)
        assert re.match(r'^[A-Z2-7]+$', result.secret)
        
        # Secret should be at least 16 characters
        assert len(result.secret) >= 16
        
        # QR code should be present if qrcode is available
        if QRCODE_AVAILABLE:
            assert result.qr_code is not None
            
            # QR code should be valid base64
            try:
                decoded = base64.b64decode(result.qr_code)
                # Should be a PNG image (starts with PNG signature)
                assert decoded[:8] == b'\x89PNG\r\n\x1a\n'
            except Exception:
                pytest.fail("QR code is not valid base64-encoded PNG")
    
    @settings(max_examples=100)
    @given(st.data())
    def test_property_10_totp_verification_round_trip(self, data):
        """
        Feature: user-authentication, Property 10: TOTP verification round-trip
        
        For any valid TOTP secret, generating a code using the TOTP algorithm
        and immediately verifying it SHALL succeed.
        
        Validates: Requirements 2.3
        """
        mfa_service = MFAService()
        
        # Generate a secret
        secret = mfa_service.generate_totp_secret()
        
        # Get current code
        current_code = mfa_service.get_current_totp(secret)
        
        # Verify the code
        is_valid = mfa_service.verify_totp(secret, current_code)
        
        assert is_valid is True
    
    @settings(max_examples=50)
    @given(
        wrong_code=st.text(
            alphabet=st.characters(whitelist_categories=('N',)),
            min_size=6,
            max_size=6
        )
    )
    def test_property_11_invalid_mfa_codes_rejected(self, wrong_code: str):
        """
        Feature: user-authentication, Property 11: Invalid MFA codes are rejected
        
        For any MFA verification attempt with an invalid code, the attempt
        SHALL be rejected.
        
        Validates: Requirements 2.4
        """
        mfa_service = MFAService()
        
        # Generate a secret
        secret = mfa_service.generate_totp_secret()
        
        # Get current valid code
        valid_code = mfa_service.get_current_totp(secret)
        
        # Skip if randomly generated code happens to be valid
        assume(wrong_code != valid_code)
        
        # Verify wrong code is rejected
        is_valid = mfa_service.verify_totp(secret, wrong_code)
        
        assert is_valid is False
    
    def test_property_13_mfa_enrollment_requires_verification(self):
        """
        Feature: user-authentication, Property 13: MFA enrollment requires verification
        
        For any TOTP MFA enrollment, the MFA SHALL NOT be enabled on the user
        account until a valid TOTP code is verified.
        
        Validates: Requirements 2.8
        """
        user = create_test_user("verifytest")
        user_store = get_user_store()
        mfa_service = MFAService()
        
        # Enroll in TOTP
        result = mfa_service.enroll_totp(user)
        assert result.success is True
        
        # Check user - MFA should NOT be enabled yet
        user = user_store.get_user_by_id(user.id)
        assert user.mfa_enabled is False
        assert user.mfa_verified is False
        assert user.mfa_secret is not None
        
        # Verify with correct code
        current_code = mfa_service.get_current_totp(user.mfa_secret)
        verify_result = mfa_service.verify_enrollment(user, current_code)
        
        assert verify_result.success is True
        
        # Now MFA should be enabled
        user = user_store.get_user_by_id(user.id)
        assert user.mfa_enabled is True
        assert user.mfa_verified is True


class TestMFAServiceUnit:
    """Unit tests for MFAService."""
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_generate_totp_secret(self):
        """Test TOTP secret generation."""
        mfa_service = MFAService()
        
        secret = mfa_service.generate_totp_secret()
        
        assert secret is not None
        assert len(secret) >= 16
        assert re.match(r'^[A-Z2-7]+$', secret)
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_verify_totp_valid_code(self):
        """Test TOTP verification with valid code."""
        mfa_service = MFAService()
        
        secret = mfa_service.generate_totp_secret()
        code = mfa_service.get_current_totp(secret)
        
        assert mfa_service.verify_totp(secret, code) is True
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_verify_totp_invalid_code(self):
        """Test TOTP verification with invalid code."""
        mfa_service = MFAService()
        
        secret = mfa_service.generate_totp_secret()
        
        # Use obviously wrong code
        assert mfa_service.verify_totp(secret, "000000") is False
    
    def test_generate_numeric_code(self):
        """Test numeric code generation."""
        mfa_service = MFAService()
        
        code = mfa_service.generate_numeric_code()
        
        assert len(code) == 6
        assert code.isdigit()
    
    def test_generate_numeric_code_custom_length(self):
        """Test numeric code generation with custom length."""
        mfa_service = MFAService()
        
        code = mfa_service.generate_numeric_code(length=8)
        
        assert len(code) == 8
        assert code.isdigit()
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_enroll_totp_success(self):
        """Test successful TOTP enrollment."""
        user = create_test_user("enrolltest")
        mfa_service = MFAService()
        
        result = mfa_service.enroll_totp(user)
        
        assert result.success is True
        assert result.secret is not None
        assert result.message is not None
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_enroll_totp_already_enabled(self):
        """Test TOTP enrollment when already enabled."""
        user = create_test_user("alreadyenabled")
        user_store = get_user_store()
        mfa_service = MFAService()
        
        # First enrollment
        result1 = mfa_service.enroll_totp(user)
        assert result1.success is True
        
        # Verify enrollment
        code = mfa_service.get_current_totp(result1.secret)
        user = user_store.get_user_by_id(user.id)
        mfa_service.verify_enrollment(user, code)
        
        # Try to enroll again
        user = user_store.get_user_by_id(user.id)
        result2 = mfa_service.enroll_totp(user)
        
        assert result2.success is False
        assert "already enabled" in result2.error.lower()
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_verify_enrollment_wrong_code(self):
        """Test enrollment verification with wrong code."""
        user = create_test_user("wrongcode")
        mfa_service = MFAService()
        
        # Enroll
        result = mfa_service.enroll_totp(user)
        assert result.success is True
        
        # Try to verify with wrong code
        verify_result = mfa_service.verify_enrollment(user, "000000")
        
        assert verify_result.success is False
        assert "invalid" in verify_result.error.lower()
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE, reason="pyotp not installed")
    def test_disable_mfa(self):
        """Test disabling MFA."""
        user = create_test_user("disabletest")
        user_store = get_user_store()
        mfa_service = MFAService()
        
        # Enroll and verify
        result = mfa_service.enroll_totp(user)
        code = mfa_service.get_current_totp(result.secret)
        user = user_store.get_user_by_id(user.id)
        mfa_service.verify_enrollment(user, code)
        
        # Verify MFA is enabled
        user = user_store.get_user_by_id(user.id)
        assert user.mfa_enabled is True
        
        # Disable MFA
        success = mfa_service.disable_mfa(user)
        assert success is True
        
        # Verify MFA is disabled
        user = user_store.get_user_by_id(user.id)
        assert user.mfa_enabled is False
        assert user.mfa_secret is None
    
    @pytest.mark.skipif(not PYOTP_AVAILABLE or not QRCODE_AVAILABLE, reason="pyotp or qrcode not installed")
    def test_generate_qr_code(self):
        """Test QR code generation."""
        mfa_service = MFAService()
        
        secret = mfa_service.generate_totp_secret()
        qr_code = mfa_service.generate_qr_code(secret, "testuser")
        
        assert qr_code is not None
        
        # Should be valid base64
        decoded = base64.b64decode(qr_code)
        
        # Should be PNG
        assert decoded[:8] == b'\x89PNG\r\n\x1a\n'
