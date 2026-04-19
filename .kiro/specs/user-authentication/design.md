# Design Document: User Authentication

## Overview

This design document describes the implementation of a comprehensive user authentication system for the Totogi Customer Toolkit. The system provides three authentication mechanisms: username/password authentication with JWT session management, multi-factor authentication (MFA) using TOTP/SMS/email, and enterprise SSO integration supporting SAML 2.0, OAuth 2.0, and OpenID Connect.

The authentication system is designed as a layered architecture with clear separation between the API layer (FastAPI routers), service layer (authentication logic), and data layer (TinyDB for user storage). This design enables secure, scalable authentication while maintaining compatibility with the existing toolkit architecture.

## Architecture

```mermaid
graph TB
    subgraph "Frontend (React/TypeScript)"
        UI[Login UI]
        MFA_UI[MFA Verification UI]
        SSO_UI[SSO Redirect Handler]
    end
    
    subgraph "API Layer (FastAPI)"
        AUTH_ROUTER[/api/auth Router]
        MFA_ROUTER[/api/mfa Router]
        SSO_ROUTER[/api/sso Router]
    end
    
    subgraph "Service Layer"
        AUTH_SVC[Authentication Service]
        MFA_SVC[MFA Service]
        SSO_SVC[SSO Service]
        JWT_SVC[JWT Service]
        LOCKOUT_SVC[Account Lockout Service]
    end
    
    subgraph "Data Layer"
        USER_STORE[(User Store - TinyDB)]
        MFA_STORE[(MFA Secrets Store)]
        SESSION_STORE[(Session Store)]
    end
    
    subgraph "External Services"
        SMS_PROVIDER[SMS Provider]
        EMAIL_PROVIDER[Email Provider]
        IDP[Identity Provider]
    end
    
    UI --> AUTH_ROUTER
    MFA_UI --> MFA_ROUTER
    SSO_UI --> SSO_ROUTER
    
    AUTH_ROUTER --> AUTH_SVC
    MFA_ROUTER --> MFA_SVC
    SSO_ROUTER --> SSO_SVC
    
    AUTH_SVC --> JWT_SVC
    AUTH_SVC --> LOCKOUT_SVC
    AUTH_SVC --> USER_STORE
    
    MFA_SVC --> MFA_STORE
    MFA_SVC --> SMS_PROVIDER
    MFA_SVC --> EMAIL_PROVIDER
    
    SSO_SVC --> IDP
    SSO_SVC --> JWT_SVC
    SSO_SVC --> SESSION_STORE
```

## Components and Interfaces

### 1. Authentication Router (`/api/auth`)

Handles username/password authentication endpoints.

```python
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/auth", tags=["authentication"])

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    requires_mfa: bool
    mfa_methods: Optional[list[str]] = None
    token: Optional[str] = None
    expires_in: Optional[int] = None
    error: Optional[str] = None

class TokenRefreshRequest(BaseModel):
    refresh_token: str

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """Authenticate user with username and password."""
    pass

@router.post("/logout")
async def logout(token: str = Depends(get_current_token)) -> dict:
    """Invalidate current session."""
    pass

@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(request: TokenRefreshRequest) -> LoginResponse:
    """Refresh an expired JWT token."""
    pass
```

### 2. MFA Router (`/api/mfa`)

Handles multi-factor authentication operations.

```python
router = APIRouter(prefix="/api/mfa", tags=["mfa"])

class MFAEnrollRequest(BaseModel):
    method: str  # "totp", "sms", "email"
    phone_number: Optional[str] = None
    email: Optional[str] = None

class MFAEnrollResponse(BaseModel):
    success: bool
    qr_code: Optional[str] = None  # Base64 encoded QR code for TOTP
    secret: Optional[str] = None   # TOTP secret for manual entry
    message: Optional[str] = None

class MFAVerifyRequest(BaseModel):
    code: str
    session_token: str  # Temporary token from initial login

class MFAVerifyResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    expires_in: Optional[int] = None
    error: Optional[str] = None
    retries_remaining: Optional[int] = None

@router.post("/enroll", response_model=MFAEnrollResponse)
async def enroll_mfa(request: MFAEnrollRequest, user=Depends(get_current_user)):
    """Enroll user in MFA."""
    pass

@router.post("/verify", response_model=MFAVerifyResponse)
async def verify_mfa(request: MFAVerifyRequest):
    """Verify MFA code and complete authentication."""
    pass

@router.post("/send-code")
async def send_mfa_code(session_token: str, method: str):
    """Send MFA code via SMS or email."""
    pass
```

### 3. SSO Router (`/api/sso`)

Handles SSO authentication flows.

```python
router = APIRouter(prefix="/api/sso", tags=["sso"])

class SSOConfigResponse(BaseModel):
    enabled: bool
    providers: list[dict]
    default_provider: Optional[str] = None

class SAMLCallbackRequest(BaseModel):
    saml_response: str
    relay_state: Optional[str] = None

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str

@router.get("/config", response_model=SSOConfigResponse)
async def get_sso_config():
    """Get SSO configuration for the login page."""
    pass

@router.get("/initiate/{provider}")
async def initiate_sso(provider: str, redirect_uri: str):
    """Initiate SSO flow by redirecting to identity provider."""
    pass

@router.post("/callback/saml")
async def saml_callback(request: SAMLCallbackRequest):
    """Handle SAML assertion callback."""
    pass

@router.get("/callback/oauth")
async def oauth_callback(code: str, state: str):
    """Handle OAuth/OIDC callback."""
    pass
```

### 4. Authentication Service

Core authentication logic.

```python
class AuthenticationService:
    def __init__(
        self,
        user_store: UserStore,
        jwt_service: JWTService,
        lockout_service: AccountLockoutService
    ):
        self.user_store = user_store
        self.jwt_service = jwt_service
        self.lockout_service = lockout_service
    
    async def authenticate(
        self, 
        username: str, 
        password: str
    ) -> AuthResult:
        """
        Authenticate user with username and password.
        
        Returns AuthResult with:
        - success: bool
        - requires_mfa: bool
        - session_token: str (temporary if MFA required)
        - error: Optional[str]
        """
        pass
    
    async def create_session(self, user_id: str) -> SessionInfo:
        """Create a new authenticated session with JWT."""
        pass
    
    async def validate_session(self, token: str) -> Optional[User]:
        """Validate JWT token and return user if valid."""
        pass
    
    async def invalidate_session(self, token: str) -> bool:
        """Invalidate a session token."""
        pass
```

### 5. MFA Service

Multi-factor authentication logic.

```python
import pyotp
import qrcode
import io
import base64

class MFAService:
    def __init__(
        self,
        mfa_store: MFAStore,
        sms_provider: SMSProvider,
        email_provider: EmailProvider
    ):
        self.mfa_store = mfa_store
        self.sms_provider = sms_provider
        self.email_provider = email_provider
        self.max_retries = 3
        self.totp_window = 1  # Allow 1 step before/after for clock drift
    
    def generate_totp_secret(self) -> str:
        """Generate a new TOTP secret."""
        return pyotp.random_base32()
    
    def generate_qr_code(
        self, 
        secret: str, 
        username: str, 
        issuer: str = "Totogi Toolkit"
    ) -> str:
        """Generate QR code for TOTP enrollment."""
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=username, issuer_name=issuer)
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
    
    def verify_totp(self, secret: str, code: str) -> bool:
        """Verify TOTP code within time window."""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=self.totp_window)
    
    async def send_sms_code(self, phone_number: str) -> str:
        """Generate and send SMS verification code."""
        code = self._generate_numeric_code(6)
        await self.sms_provider.send(
            phone_number, 
            f"Your Totogi verification code is: {code}"
        )
        return code
    
    async def send_email_code(self, email: str) -> str:
        """Generate and send email verification code."""
        code = self._generate_numeric_code(6)
        await self.email_provider.send(
            email,
            "Totogi Verification Code",
            f"Your verification code is: {code}"
        )
        return code
    
    def _generate_numeric_code(self, length: int) -> str:
        """Generate a random numeric code."""
        import secrets
        return ''.join(str(secrets.randbelow(10)) for _ in range(length))
```

### 6. SSO Service

SSO integration logic.

```python
from typing import Dict, Any
import xml.etree.ElementTree as ET

class SSOService:
    def __init__(
        self,
        config: SSOConfig,
        jwt_service: JWTService,
        user_store: UserStore
    ):
        self.config = config
        self.jwt_service = jwt_service
        self.user_store = user_store
    
    def get_saml_redirect_url(self, provider_id: str, relay_state: str) -> str:
        """Generate SAML authentication request URL."""
        pass
    
    def validate_saml_assertion(
        self, 
        saml_response: str, 
        provider_id: str
    ) -> SAMLValidationResult:
        """
        Validate SAML assertion and extract user claims.
        
        Validates:
        - Signature against provider certificate
        - Assertion timestamps (NotBefore, NotOnOrAfter)
        - Audience restriction
        """
        pass
    
    def get_oauth_redirect_url(
        self, 
        provider_id: str, 
        redirect_uri: str,
        state: str
    ) -> str:
        """Generate OAuth authorization URL."""
        pass
    
    async def exchange_oauth_code(
        self, 
        code: str, 
        provider_id: str,
        redirect_uri: str
    ) -> OAuthTokenResult:
        """Exchange authorization code for tokens."""
        pass
    
    async def validate_oauth_token(
        self, 
        token: str, 
        provider_id: str
    ) -> TokenValidationResult:
        """Validate OAuth token with provider's introspection endpoint."""
        pass
    
    def extract_oidc_claims(self, id_token: str) -> Dict[str, Any]:
        """Extract and validate claims from OIDC ID token."""
        pass
    
    def map_external_roles(
        self, 
        external_roles: list[str], 
        provider_id: str
    ) -> str:
        """Map external IdP roles to Toolkit roles."""
        role_mapping = self.config.get_role_mapping(provider_id)
        
        for external_role in external_roles:
            if external_role in role_mapping:
                return role_mapping[external_role]
        
        return "Viewer"  # Default role
```

### 7. JWT Service

JWT token management.

```python
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class JWTService:
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expiry = timedelta(minutes=30)
        self.refresh_token_expiry = timedelta(days=7)
    
    def create_access_token(
        self, 
        user_id: str, 
        roles: list[str],
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a JWT access token with 30-minute expiration."""
        payload = {
            "sub": user_id,
            "roles": roles,
            "type": "access",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + self.access_token_expiry
        }
        if additional_claims:
            payload.update(additional_claims)
        
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def create_refresh_token(self, user_id: str) -> str:
        """Create a refresh token for session renewal."""
        payload = {
            "sub": user_id,
            "type": "refresh",
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + self.refresh_token_expiry
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate and decode a JWT token."""
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm]
            )
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def is_token_expired(self, token: str) -> bool:
        """Check if a token is expired."""
        try:
            jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return False
        except jwt.ExpiredSignatureError:
            return True
        except jwt.InvalidTokenError:
            return True
```

### 8. Account Lockout Service

Account lockout protection.

```python
from datetime import datetime, timedelta
from typing import Optional

class AccountLockoutService:
    def __init__(self, user_store: UserStore):
        self.user_store = user_store
        self.max_attempts = 5
        self.lockout_duration = timedelta(minutes=15)
    
    def record_failed_attempt(self, username: str) -> int:
        """
        Record a failed login attempt.
        Returns the current failed attempt count.
        """
        user = self.user_store.get_by_username(username)
        if not user:
            return 0
        
        failed_count = user.failed_login_count + 1
        self.user_store.update(user.id, {
            "failed_login_count": failed_count,
            "last_failed_login": datetime.utcnow().isoformat()
        })
        
        return failed_count
    
    def is_account_locked(self, username: str) -> tuple[bool, Optional[int]]:
        """
        Check if account is locked.
        Returns (is_locked, seconds_remaining).
        """
        user = self.user_store.get_by_username(username)
        if not user:
            return False, None
        
        if user.failed_login_count < self.max_attempts:
            return False, None
        
        if not user.last_failed_login:
            return False, None
        
        last_failed = datetime.fromisoformat(user.last_failed_login)
        lockout_end = last_failed + self.lockout_duration
        
        if datetime.utcnow() >= lockout_end:
            # Lockout expired, reset counter
            self.reset_failed_attempts(username)
            return False, None
        
        remaining = (lockout_end - datetime.utcnow()).total_seconds()
        return True, int(remaining)
    
    def reset_failed_attempts(self, username: str) -> None:
        """Reset failed login counter after successful login."""
        user = self.user_store.get_by_username(username)
        if user:
            self.user_store.update(user.id, {
                "failed_login_count": 0,
                "last_failed_login": None
            })
```

## Data Models

### User Model

```python
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class User(BaseModel):
    id: str
    username: str
    email: str
    password_hash: str
    roles: List[str]  # ["Administrator", "Operator", "Viewer"]
    mfa_enabled: bool = False
    mfa_method: Optional[str] = None  # "totp", "sms", "email"
    mfa_secret: Optional[str] = None  # Encrypted TOTP secret
    phone_number: Optional[str] = None
    failed_login_count: int = 0
    last_failed_login: Optional[str] = None
    created_at: str
    updated_at: str
    sso_provider: Optional[str] = None
    sso_subject: Optional[str] = None

class MFAEnrollment(BaseModel):
    user_id: str
    method: str
    secret: str  # Encrypted
    verified: bool = False
    created_at: str

class Session(BaseModel):
    id: str
    user_id: str
    token_hash: str
    created_at: str
    expires_at: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

class SSOProvider(BaseModel):
    id: str
    name: str
    type: str  # "saml", "oauth", "oidc"
    enabled: bool
    config: dict  # Provider-specific configuration
    role_mapping: dict  # External role -> Toolkit role
    certificate: Optional[str] = None  # For SAML signature validation
```

### SSO Configuration Model

```python
class SAMLConfig(BaseModel):
    entity_id: str
    sso_url: str
    slo_url: Optional[str] = None
    certificate: str
    name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"

class OAuthConfig(BaseModel):
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    userinfo_url: Optional[str] = None
    scopes: List[str] = ["openid", "profile", "email"]

class OIDCConfig(OAuthConfig):
    issuer: str
    jwks_uri: str
```



## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Valid credentials produce authenticated session

*For any* valid username and password combination in the user store, submitting these credentials to the authentication service SHALL result in a session being created with a valid JWT token.

**Validates: Requirements 1.1**

### Property 2: Invalid credentials increment failure counter

*For any* authentication attempt with invalid credentials (wrong password or non-existent user), the authentication service SHALL reject the attempt AND the user's failed login counter SHALL be incremented by exactly one.

**Validates: Requirements 1.2**

### Property 3: Account lockout after five failures

*For any* user account, after exactly five consecutive failed login attempts, the account SHALL be locked AND subsequent authentication attempts SHALL be rejected until the lockout period expires.

**Validates: Requirements 1.3**

### Property 4: JWT token expiration is thirty minutes

*For any* JWT token created by the authentication service, the token's expiration time SHALL be exactly thirty minutes from the creation time.

**Validates: Requirements 1.4**

### Property 5: Expired tokens are rejected

*For any* JWT token that has passed its expiration time, the authentication service SHALL reject the token and require re-authentication.

**Validates: Requirements 1.5**

### Property 6: Lockout counter reset after expiration

*For any* locked account, after the fifteen-minute lockout period expires, the failed login counter SHALL be reset to zero AND the account SHALL accept authentication attempts.

**Validates: Requirements 1.6**

### Property 7: Successful authentication resets failure counter

*For any* successful authentication, the user's failed login counter SHALL be reset to zero regardless of its previous value.

**Validates: Requirements 1.7**

### Property 8: MFA enrollment produces valid TOTP secret

*For any* MFA enrollment request, the MFA service SHALL generate a valid TOTP secret (base32 encoded, minimum 16 characters) AND a QR code that encodes the correct provisioning URI.

**Validates: Requirements 2.1**

### Property 9: MFA-enabled users require verification step

*For any* user with MFA enabled, submitting valid credentials SHALL NOT complete authentication but SHALL return a temporary session token requiring MFA verification.

**Validates: Requirements 2.2**

### Property 10: TOTP verification round-trip

*For any* valid TOTP secret, generating a code using the TOTP algorithm and immediately verifying it SHALL succeed.

**Validates: Requirements 2.3**

### Property 11: Invalid MFA codes are rejected with retry tracking

*For any* MFA verification attempt with an invalid code, the attempt SHALL be rejected AND the retry counter SHALL be decremented by one.

**Validates: Requirements 2.4**

### Property 12: MFA retry exhaustion invalidates session

*For any* MFA session, after three consecutive invalid code submissions, the temporary session SHALL be invalidated AND the user SHALL be required to restart authentication.

**Validates: Requirements 2.7**

### Property 13: MFA enrollment requires verification

*For any* TOTP MFA enrollment, the MFA SHALL NOT be enabled on the user account until a valid TOTP code is verified.

**Validates: Requirements 2.8**

### Property 14: SSO redirect URL generation

*For any* configured SSO provider, initiating SSO login SHALL generate a redirect URL that points to the provider's authorization endpoint with correct parameters.

**Validates: Requirements 3.1**

### Property 15: SAML assertion creates session with role mapping

*For any* valid SAML assertion with a valid signature, the SSO service SHALL create a user session AND map the assertion's role attributes to Toolkit roles.

**Validates: Requirements 3.2**

### Property 16: OAuth token validation creates session

*For any* valid OAuth token, the SSO service SHALL validate the token and create a user session with appropriate permissions.

**Validates: Requirements 3.3**

### Property 17: OIDC claims extraction

*For any* valid OIDC ID token, the SSO service SHALL extract user claims (sub, email, name, roles) and create a session with the extracted information.

**Validates: Requirements 3.4**

### Property 18: SSO failure provides fallback option

*For any* SSO authentication failure, the response SHALL include an error message AND indicate that local authentication is available as a fallback.

**Validates: Requirements 3.5**

### Property 19: SAML signature validation

*For any* SAML assertion, the SSO service SHALL validate the assertion's signature against the configured provider certificate AND reject assertions with invalid signatures.

**Validates: Requirements 3.6**

### Property 20: External role mapping consistency

*For any* set of external roles from an SSO provider, the role mapping SHALL produce exactly one Toolkit role (Administrator, Operator, or Viewer) based on the configured mapping rules.

**Validates: Requirements 3.8**

## Error Handling

### Authentication Errors

| Error Code | Description | HTTP Status | User Message |
|------------|-------------|-------------|--------------|
| AUTH_001 | Invalid credentials | 401 | Invalid username or password |
| AUTH_002 | Account locked | 423 | Account locked. Try again in X minutes |
| AUTH_003 | Token expired | 401 | Session expired. Please log in again |
| AUTH_004 | Token invalid | 401 | Invalid session. Please log in again |
| AUTH_005 | User not found | 401 | Invalid username or password |

### MFA Errors

| Error Code | Description | HTTP Status | User Message |
|------------|-------------|-------------|--------------|
| MFA_001 | Invalid MFA code | 401 | Invalid verification code. X attempts remaining |
| MFA_002 | MFA retries exhausted | 401 | Too many failed attempts. Please start over |
| MFA_003 | MFA not enabled | 400 | MFA is not enabled for this account |
| MFA_004 | MFA already enabled | 400 | MFA is already enabled |
| MFA_005 | Invalid MFA method | 400 | Unsupported MFA method |
| MFA_006 | Code delivery failed | 500 | Failed to send verification code |

### SSO Errors

| Error Code | Description | HTTP Status | User Message |
|------------|-------------|-------------|--------------|
| SSO_001 | Provider not configured | 400 | SSO provider not configured |
| SSO_002 | Invalid SAML assertion | 401 | SSO authentication failed |
| SSO_003 | Invalid OAuth token | 401 | SSO authentication failed |
| SSO_004 | Signature validation failed | 401 | SSO authentication failed - invalid signature |
| SSO_005 | Claims extraction failed | 401 | SSO authentication failed - invalid response |
| SSO_006 | Provider unreachable | 503 | SSO provider unavailable. Use local login |

## Testing Strategy

### Unit Tests

Unit tests will verify specific examples and edge cases:

1. **Authentication Service**
   - Test valid login with correct credentials
   - Test invalid login with wrong password
   - Test login with non-existent user
   - Test account lockout threshold (exactly 5 attempts)
   - Test lockout duration (exactly 15 minutes)

2. **JWT Service**
   - Test token creation with correct claims
   - Test token validation with valid token
   - Test token rejection with expired token
   - Test token rejection with tampered token

3. **MFA Service**
   - Test TOTP secret generation format
   - Test QR code generation
   - Test TOTP verification with valid code
   - Test TOTP verification with expired code
   - Test retry counter decrement

4. **SSO Service**
   - Test SAML redirect URL generation
   - Test OAuth redirect URL generation
   - Test role mapping with various external roles

### Property-Based Tests

Property-based tests will use the `hypothesis` library (Python) to verify universal properties:

**Configuration:**
- Minimum 100 iterations per property test
- Each test tagged with: `**Feature: user-authentication, Property N: {property_text}**`

**Test Files:**
- `tests/test_authentication_properties.py` - Properties 1-7
- `tests/test_mfa_properties.py` - Properties 8-13
- `tests/test_sso_properties.py` - Properties 14-20

**Example Property Test Structure:**

```python
from hypothesis import given, strategies as st, settings

@settings(max_examples=100)
@given(
    username=st.text(min_size=1, max_size=50),
    password=st.text(min_size=8, max_size=100)
)
def test_valid_credentials_produce_session(username: str, password: str):
    """
    Feature: user-authentication, Property 1: Valid credentials produce authenticated session
    Validates: Requirements 1.1
    """
    # Create user with credentials
    user = create_test_user(username, password)
    
    # Authenticate
    result = auth_service.authenticate(username, password)
    
    # Verify session created with valid JWT
    assert result.success is True
    assert result.token is not None
    assert jwt_service.validate_token(result.token) is not None
```

### Integration Tests

Integration tests will verify end-to-end flows:

1. **Full Authentication Flow**
   - Login → MFA → Session creation → Token refresh → Logout

2. **SSO Flow**
   - SSO initiate → IdP redirect → Callback → Session creation

3. **Lockout Recovery Flow**
   - 5 failed attempts → Lockout → Wait → Successful login
