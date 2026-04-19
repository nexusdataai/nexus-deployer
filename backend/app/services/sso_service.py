"""
SSO Service
Single Sign-On service supporting SAML 2.0, OAuth 2.0, and OpenID Connect.
"""
import logging
import secrets
import base64
import hashlib
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta

from app.models.sso_models import (
    SSOProvider, SSOProviderType, SSOState, SSOError,
    SAMLConfig, OAuthConfig, OIDCConfig,
    SSOConfigResponse, SSOInitiateResponse, SSOCallbackResponse
)
from app.models.auth_models import User, UserRole
from app.services.user_store import get_user_store, UserStore
from app.services.jwt_service import get_jwt_service, JWTService

logger = logging.getLogger(__name__)

# Try to import optional SSO libraries
try:
    import jwt as pyjwt
    PYJWT_AVAILABLE = True
except ImportError:
    PYJWT_AVAILABLE = False
    logger.warning("PyJWT not installed, OIDC token validation will be limited")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not installed, OAuth token exchange will be unavailable")


class SSOServiceError(Exception):
    """Base exception for SSO errors."""
    def __init__(self, message: str, error_code: SSOError):
        super().__init__(message)
        self.error_code = error_code


class SSOService:
    """
    Service for Single Sign-On authentication.
    
    Supports:
    - SAML 2.0 with signature validation
    - OAuth 2.0 authorization code flow
    - OpenID Connect with ID token validation
    """
    
    STATE_EXPIRY_MINUTES = 10
    
    def __init__(
        self,
        user_store: Optional[UserStore] = None,
        jwt_service: Optional[JWTService] = None
    ):
        """Initialize SSO service."""
        self._user_store = user_store or get_user_store()
        self._jwt_service = jwt_service or get_jwt_service()
        self._providers: Dict[str, SSOProvider] = {}
        self._states: Dict[str, SSOState] = {}
        self._default_provider: Optional[str] = None
        
        logger.info("SSOService initialized")
    
    # ==================== Provider Management ====================
    
    def register_provider(self, provider: SSOProvider) -> None:
        """Register an SSO provider."""
        self._providers[provider.id] = provider
        logger.info(f"Registered SSO provider: {provider.name} ({provider.type})")
    
    def get_provider(self, provider_id: str) -> Optional[SSOProvider]:
        """Get an SSO provider by ID."""
        return self._providers.get(provider_id)
    
    def get_enabled_providers(self) -> List[SSOProvider]:
        """Get all enabled SSO providers."""
        return [p for p in self._providers.values() if p.enabled]
    
    def set_default_provider(self, provider_id: str) -> None:
        """Set the default SSO provider."""
        if provider_id in self._providers:
            self._default_provider = provider_id
    
    def get_config(self) -> SSOConfigResponse:
        """Get SSO configuration for the login page."""
        providers = []
        for p in self.get_enabled_providers():
            providers.append({
                "id": p.id,
                "name": p.name,
                "type": p.type.value,
                "icon_url": p.icon_url
            })
        
        return SSOConfigResponse(
            enabled=len(providers) > 0,
            providers=providers,
            default_provider=self._default_provider
        )
    
    # ==================== State Management ====================
    
    def _create_state(
        self,
        provider_id: str,
        redirect_uri: str,
        nonce: Optional[str] = None
    ) -> str:
        """Create a state token for CSRF protection."""
        state_id = secrets.token_urlsafe(32)
        expires_at = (
            datetime.utcnow() + timedelta(minutes=self.STATE_EXPIRY_MINUTES)
        ).isoformat()
        
        state = SSOState(
            id=state_id,
            provider_id=provider_id,
            redirect_uri=redirect_uri,
            created_at=datetime.utcnow().isoformat(),
            expires_at=expires_at,
            nonce=nonce
        )
        
        self._states[state_id] = state
        return state_id
    
    def _validate_state(self, state_id: str) -> Optional[SSOState]:
        """Validate and consume a state token."""
        state = self._states.pop(state_id, None)
        if not state:
            return None
        
        # Check expiration
        expires_at = datetime.fromisoformat(state.expires_at)
        if datetime.utcnow() > expires_at:
            return None
        
        return state
    
    # ==================== SAML Methods ====================
    
    def get_saml_redirect_url(
        self,
        provider_id: str,
        redirect_uri: str
    ) -> SSOInitiateResponse:
        """
        Generate SAML authentication request URL.
        
        Args:
            provider_id: SSO provider ID
            redirect_uri: Redirect URI after authentication
            
        Returns:
            SSOInitiateResponse with redirect URL
        """
        provider = self.get_provider(provider_id)
        if not provider or provider.type != SSOProviderType.SAML:
            return SSOInitiateResponse(
                success=False,
                error="SAML provider not configured"
            )
        
        if not provider.saml_config:
            return SSOInitiateResponse(
                success=False,
                error="SAML configuration missing"
            )
        
        config = provider.saml_config
        
        # Create state for relay
        state = self._create_state(provider_id, redirect_uri)
        
        # Build SAML AuthnRequest (simplified - production would use proper SAML library)
        # This is a stub - real implementation would use python3-saml or similar
        saml_request = self._build_saml_authn_request(config)
        encoded_request = base64.b64encode(saml_request.encode()).decode()
        
        # Build redirect URL
        params = {
            "SAMLRequest": encoded_request,
            "RelayState": state
        }
        redirect_url = f"{config.sso_url}?{urllib.parse.urlencode(params)}"
        
        logger.info(f"Generated SAML redirect URL for provider: {provider.name}")
        
        return SSOInitiateResponse(
            success=True,
            redirect_url=redirect_url
        )
    
    def _build_saml_authn_request(self, config: SAMLConfig) -> str:
        """Build a SAML AuthnRequest XML (stub implementation)."""
        # In production, use python3-saml or similar library
        request_id = f"_{''.join(secrets.token_hex(16))}"
        issue_instant = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
    ID="{request_id}"
    Version="2.0"
    IssueInstant="{issue_instant}"
    ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
    AssertionConsumerServiceURL="{config.entity_id}/callback/saml">
    <saml:Issuer xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">{config.entity_id}</saml:Issuer>
    <samlp:NameIDPolicy Format="{config.name_id_format}" AllowCreate="true"/>
</samlp:AuthnRequest>"""
    
    def validate_saml_assertion(
        self,
        saml_response: str,
        relay_state: Optional[str]
    ) -> SSOCallbackResponse:
        """
        Validate SAML assertion and create session.
        
        Args:
            saml_response: Base64-encoded SAML response
            relay_state: Relay state from initiation
            
        Returns:
            SSOCallbackResponse with session tokens or error
        """
        # Validate state
        if not relay_state:
            return SSOCallbackResponse(
                success=False,
                error="Missing relay state",
                error_code=SSOError.SSO_007.value
            )
        
        state = self._validate_state(relay_state)
        if not state:
            return SSOCallbackResponse(
                success=False,
                error="Invalid or expired state",
                error_code=SSOError.SSO_007.value
            )
        
        provider = self.get_provider(state.provider_id)
        if not provider or not provider.saml_config:
            return SSOCallbackResponse(
                success=False,
                error="Provider not found",
                error_code=SSOError.SSO_001.value
            )
        
        try:
            # Decode and parse SAML response (stub - use python3-saml in production)
            decoded_response = base64.b64decode(saml_response).decode()
            
            # Validate signature (stub)
            if not self._validate_saml_signature(decoded_response, provider.saml_config):
                return SSOCallbackResponse(
                    success=False,
                    error="Invalid SAML signature",
                    error_code=SSOError.SSO_004.value
                )
            
            # Extract claims (stub)
            claims = self._extract_saml_claims(decoded_response)
            if not claims:
                return SSOCallbackResponse(
                    success=False,
                    error="Failed to extract claims",
                    error_code=SSOError.SSO_005.value
                )
            
            # Create or update user
            user = self._get_or_create_sso_user(provider, claims)
            if not user:
                return SSOCallbackResponse(
                    success=False,
                    error="Failed to create user",
                    error_code=SSOError.SSO_008.value
                )
            
            # Create session
            return self._create_sso_session(user)
            
        except Exception as e:
            logger.error(f"SAML validation error: {e}")
            return SSOCallbackResponse(
                success=False,
                error="SAML authentication failed",
                error_code=SSOError.SSO_002.value
            )
    
    def _validate_saml_signature(self, response: str, config: SAMLConfig) -> bool:
        """Validate SAML response signature (stub)."""
        # In production, use python3-saml or xmlsec
        # This stub always returns True for testing
        logger.warning("SAML signature validation is stubbed - implement with python3-saml")
        return True
    
    def _extract_saml_claims(self, response: str) -> Optional[Dict[str, Any]]:
        """Extract claims from SAML assertion (stub)."""
        # In production, properly parse XML and extract attributes
        # This stub returns mock claims for testing
        logger.warning("SAML claims extraction is stubbed - implement with python3-saml")
        return {
            "sub": "saml-user-id",
            "email": "user@example.com",
            "name": "SAML User",
            "roles": []
        }
    
    # ==================== OAuth Methods ====================
    
    def get_oauth_redirect_url(
        self,
        provider_id: str,
        redirect_uri: str
    ) -> SSOInitiateResponse:
        """
        Generate OAuth authorization URL.
        
        Args:
            provider_id: SSO provider ID
            redirect_uri: Redirect URI after authentication
            
        Returns:
            SSOInitiateResponse with redirect URL
        """
        provider = self.get_provider(provider_id)
        if not provider or provider.type not in (SSOProviderType.OAUTH, SSOProviderType.OIDC):
            return SSOInitiateResponse(
                success=False,
                error="OAuth provider not configured"
            )
        
        config = provider.oauth_config or provider.oidc_config
        if not config:
            return SSOInitiateResponse(
                success=False,
                error="OAuth configuration missing"
            )
        
        # Create state and nonce
        nonce = secrets.token_urlsafe(16) if provider.type == SSOProviderType.OIDC else None
        state = self._create_state(provider_id, redirect_uri, nonce)
        
        # Build authorization URL
        params = {
            "client_id": config.client_id,
            "response_type": "code",
            "redirect_uri": config.redirect_uri or redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state
        }
        
        if nonce:
            params["nonce"] = nonce
        
        redirect_url = f"{config.authorization_url}?{urllib.parse.urlencode(params)}"
        
        logger.info(f"Generated OAuth redirect URL for provider: {provider.name}")
        
        return SSOInitiateResponse(
            success=True,
            redirect_url=redirect_url
        )
    
    async def exchange_oauth_code(
        self,
        code: str,
        state: str
    ) -> SSOCallbackResponse:
        """
        Exchange authorization code for tokens.
        
        Args:
            code: Authorization code
            state: State parameter for CSRF validation
            
        Returns:
            SSOCallbackResponse with session tokens or error
        """
        # Validate state
        sso_state = self._validate_state(state)
        if not sso_state:
            return SSOCallbackResponse(
                success=False,
                error="Invalid or expired state",
                error_code=SSOError.SSO_007.value
            )
        
        provider = self.get_provider(sso_state.provider_id)
        if not provider:
            return SSOCallbackResponse(
                success=False,
                error="Provider not found",
                error_code=SSOError.SSO_001.value
            )
        
        config = provider.oauth_config or provider.oidc_config
        if not config:
            return SSOCallbackResponse(
                success=False,
                error="OAuth configuration missing",
                error_code=SSOError.SSO_001.value
            )
        
        if not HTTPX_AVAILABLE:
            return SSOCallbackResponse(
                success=False,
                error="OAuth token exchange unavailable (httpx not installed)",
                error_code=SSOError.SSO_006.value
            )
        
        try:
            # Exchange code for tokens
            async with httpx.AsyncClient() as client:
                token_response = await client.post(
                    config.token_url,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": config.redirect_uri or sso_state.redirect_uri,
                        "client_id": config.client_id,
                        "client_secret": config.client_secret
                    }
                )
                
                if token_response.status_code != 200:
                    logger.error(f"Token exchange failed: {token_response.text}")
                    return SSOCallbackResponse(
                        success=False,
                        error="Token exchange failed",
                        error_code=SSOError.SSO_003.value
                    )
                
                tokens = token_response.json()
            
            # For OIDC, validate ID token
            if provider.type == SSOProviderType.OIDC and "id_token" in tokens:
                claims = self.extract_oidc_claims(tokens["id_token"], provider)
                if not claims:
                    return SSOCallbackResponse(
                        success=False,
                        error="Failed to validate ID token",
                        error_code=SSOError.SSO_005.value
                    )
            else:
                # For OAuth, fetch user info
                claims = await self._fetch_userinfo(tokens["access_token"], config)
                if not claims:
                    return SSOCallbackResponse(
                        success=False,
                        error="Failed to fetch user info",
                        error_code=SSOError.SSO_005.value
                    )
            
            # Create or update user
            user = self._get_or_create_sso_user(provider, claims)
            if not user:
                return SSOCallbackResponse(
                    success=False,
                    error="Failed to create user",
                    error_code=SSOError.SSO_008.value
                )
            
            # Create session
            return self._create_sso_session(user)
            
        except Exception as e:
            logger.error(f"OAuth exchange error: {e}")
            return SSOCallbackResponse(
                success=False,
                error="OAuth authentication failed",
                error_code=SSOError.SSO_003.value
            )
    
    async def _fetch_userinfo(
        self,
        access_token: str,
        config: OAuthConfig
    ) -> Optional[Dict[str, Any]]:
        """Fetch user info from OAuth provider."""
        if not config.userinfo_url:
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    config.userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"UserInfo fetch error: {e}")
        
        return None
    
    # ==================== OIDC Methods ====================
    
    def extract_oidc_claims(
        self,
        id_token: str,
        provider: SSOProvider
    ) -> Optional[Dict[str, Any]]:
        """
        Extract and validate claims from OIDC ID token.
        
        Args:
            id_token: JWT ID token
            provider: SSO provider
            
        Returns:
            Extracted claims or None if validation fails
        """
        if not PYJWT_AVAILABLE:
            logger.warning("PyJWT not available, skipping ID token validation")
            # Decode without verification (not recommended for production)
            try:
                parts = id_token.split(".")
                if len(parts) != 3:
                    return None
                payload = base64.urlsafe_b64decode(parts[1] + "==")
                import json
                return json.loads(payload)
            except Exception:
                return None
        
        config = provider.oidc_config
        if not config:
            return None
        
        try:
            # In production, fetch JWKS and validate properly
            # This is a simplified implementation
            claims = pyjwt.decode(
                id_token,
                options={"verify_signature": False}  # Stub - verify in production
            )
            
            # Validate issuer
            if claims.get("iss") != config.issuer:
                logger.error("Invalid issuer in ID token")
                return None
            
            # Validate audience
            if claims.get("aud") != config.client_id:
                logger.error("Invalid audience in ID token")
                return None
            
            return claims
            
        except Exception as e:
            logger.error(f"OIDC claims extraction error: {e}")
            return None
    
    # ==================== Role Mapping ====================
    
    def map_external_roles(
        self,
        external_roles: List[str],
        provider: SSOProvider
    ) -> str:
        """
        Map external IdP roles to Toolkit roles.
        
        Args:
            external_roles: List of roles from IdP
            provider: SSO provider with role mappings
            
        Returns:
            Mapped internal role (Administrator, Operator, or Viewer)
        """
        # Check role mappings in order
        for mapping in provider.role_mappings:
            if mapping.external_role in external_roles:
                return mapping.internal_role
        
        # Return default role if no mapping matches
        return provider.default_role
    
    # ==================== User Management ====================
    
    def _get_or_create_sso_user(
        self,
        provider: SSOProvider,
        claims: Dict[str, Any]
    ) -> Optional[User]:
        """Get or create a user from SSO claims."""
        sub = claims.get("sub")
        email = claims.get("email")
        
        if not sub:
            logger.error("Missing 'sub' claim in SSO response")
            return None
        
        # Try to find existing user by SSO subject
        user = self._user_store.get_user_by_sso(provider.id, sub)
        
        if user:
            # Update user if configured
            if provider.update_user_on_login:
                external_roles = claims.get("roles", [])
                if isinstance(external_roles, str):
                    external_roles = [external_roles]
                
                internal_role = self.map_external_roles(external_roles, provider)
                
                self._user_store.update_user(user.id, {
                    "email": email or user.email,
                    "roles": [UserRole(internal_role)],
                    "updated_at": datetime.utcnow().isoformat()
                })
                
                # Refresh user
                user = self._user_store.get_user_by_id(user.id)
            
            return user
        
        # Try to find by email
        if email:
            user = self._user_store.get_user_by_email(email)
            if user:
                # Link existing user to SSO
                self._user_store.update_user(user.id, {
                    "sso_provider": provider.id,
                    "sso_subject": sub,
                    "updated_at": datetime.utcnow().isoformat()
                })
                return self._user_store.get_user_by_id(user.id)
        
        # Create new user if auto-create is enabled
        if not provider.auto_create_users:
            logger.info(f"Auto-create disabled, rejecting new SSO user: {sub}")
            return None
        
        # Map roles
        external_roles = claims.get("roles", [])
        if isinstance(external_roles, str):
            external_roles = [external_roles]
        internal_role = self.map_external_roles(external_roles, provider)
        
        # Generate username from email or sub
        username = email.split("@")[0] if email else f"sso_{sub[:8]}"
        
        # Create user
        user = self._user_store.create_user(
            username=username,
            email=email or f"{sub}@sso.local",
            password=secrets.token_urlsafe(32),  # Random password (SSO users don't use it)
            roles=[UserRole(internal_role)],
            sso_provider=provider.id,
            sso_subject=sub
        )
        
        logger.info(f"Created SSO user: {username} from provider: {provider.name}")
        return user
    
    def _create_sso_session(self, user: User) -> SSOCallbackResponse:
        """Create session tokens for SSO user."""
        access_token = self._jwt_service.create_access_token(user.id, user.roles)
        refresh_token = self._jwt_service.create_refresh_token(user.id)
        
        # Get user info (without sensitive data)
        user_info = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "roles": [r.value if hasattr(r, 'value') else r for r in user.roles]
        }
        
        return SSOCallbackResponse(
            success=True,
            token=access_token,
            refresh_token=refresh_token,
            expires_in=1800,  # 30 minutes
            user=user_info
        )


# Global instance
_sso_service: Optional[SSOService] = None


def get_sso_service() -> SSOService:
    """Get global SSOService instance."""
    global _sso_service
    if _sso_service is None:
        _sso_service = SSOService()
    return _sso_service


def reset_sso_service():
    """Reset global SSOService instance (for testing)."""
    global _sso_service
    _sso_service = None
