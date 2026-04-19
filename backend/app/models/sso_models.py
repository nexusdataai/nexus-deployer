"""SSO configuration models for SAML 2.0, OAuth 2.0, and OpenID Connect."""
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class SSOProviderType(str, Enum):
    """SSO provider types."""
    SAML = "saml"
    OAUTH = "oauth"
    OIDC = "oidc"


class SAMLConfig(BaseModel):
    """SAML 2.0 provider configuration."""
    entity_id: str = Field(..., description="Service Provider entity ID")
    sso_url: str = Field(..., description="IdP Single Sign-On URL")
    slo_url: Optional[str] = Field(None, description="IdP Single Logout URL")
    certificate: str = Field(..., description="IdP X.509 certificate for signature validation")
    name_id_format: str = Field(
        default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        description="NameID format"
    )
    sign_requests: bool = Field(default=False, description="Whether to sign auth requests")
    want_assertions_signed: bool = Field(default=True, description="Require signed assertions")
    want_response_signed: bool = Field(default=False, description="Require signed response")


class OAuthConfig(BaseModel):
    """OAuth 2.0 provider configuration."""
    client_id: str = Field(..., description="OAuth client ID")
    client_secret: str = Field(..., description="OAuth client secret")
    authorization_url: str = Field(..., description="Authorization endpoint URL")
    token_url: str = Field(..., description="Token endpoint URL")
    userinfo_url: Optional[str] = Field(None, description="UserInfo endpoint URL")
    scopes: List[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        description="OAuth scopes to request"
    )
    redirect_uri: Optional[str] = Field(None, description="Callback redirect URI")


class OIDCConfig(OAuthConfig):
    """OpenID Connect provider configuration (extends OAuth)."""
    issuer: str = Field(..., description="OIDC issuer URL")
    jwks_uri: str = Field(..., description="JSON Web Key Set URI")
    id_token_signing_alg: str = Field(default="RS256", description="ID token signing algorithm")
    claims_mapping: Dict[str, str] = Field(
        default_factory=lambda: {
            "sub": "sub",
            "email": "email",
            "name": "name",
            "roles": "roles"
        },
        description="Mapping of OIDC claims to user attributes"
    )


class RoleMapping(BaseModel):
    """Role mapping configuration for SSO providers."""
    external_role: str = Field(..., description="External role name from IdP")
    internal_role: str = Field(..., description="Internal Toolkit role (Administrator, Operator, Viewer)")


class SSOProvider(BaseModel):
    """SSO provider configuration."""
    id: str = Field(..., description="Unique provider identifier")
    name: str = Field(..., description="Display name for the provider")
    type: SSOProviderType = Field(..., description="Provider type (saml, oauth, oidc)")
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    
    # Provider-specific configuration (one of these will be set)
    saml_config: Optional[SAMLConfig] = Field(None, description="SAML configuration")
    oauth_config: Optional[OAuthConfig] = Field(None, description="OAuth configuration")
    oidc_config: Optional[OIDCConfig] = Field(None, description="OIDC configuration")
    
    # Role mapping
    role_mappings: List[RoleMapping] = Field(
        default_factory=list,
        description="Role mappings from external to internal roles"
    )
    default_role: str = Field(default="Viewer", description="Default role if no mapping matches")
    
    # Additional settings
    auto_create_users: bool = Field(default=True, description="Auto-create users on first SSO login")
    update_user_on_login: bool = Field(default=True, description="Update user attributes on each login")
    icon_url: Optional[str] = Field(None, description="URL to provider icon for UI")


class SSOState(BaseModel):
    """SSO state for CSRF protection."""
    id: str = Field(..., description="Unique state identifier")
    provider_id: str = Field(..., description="SSO provider ID")
    redirect_uri: str = Field(..., description="Redirect URI after authentication")
    created_at: str = Field(..., description="ISO timestamp of state creation")
    expires_at: str = Field(..., description="ISO timestamp of state expiration")
    nonce: Optional[str] = Field(None, description="OIDC nonce for replay protection")


# Request/Response models for SSO API endpoints

class SSOConfigResponse(BaseModel):
    """Response for SSO configuration endpoint."""
    enabled: bool = Field(..., description="Whether SSO is enabled")
    providers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of configured SSO providers (public info only)"
    )
    default_provider: Optional[str] = Field(None, description="Default SSO provider ID")


class SSOInitiateRequest(BaseModel):
    """Request to initiate SSO flow."""
    provider_id: str = Field(..., description="SSO provider ID")
    redirect_uri: Optional[str] = Field(None, description="Redirect URI after authentication")


class SSOInitiateResponse(BaseModel):
    """Response for SSO initiation."""
    success: bool = Field(..., description="Whether initiation was successful")
    redirect_url: Optional[str] = Field(None, description="URL to redirect user to")
    error: Optional[str] = Field(None, description="Error message if initiation failed")


class SAMLCallbackRequest(BaseModel):
    """SAML assertion callback request."""
    saml_response: str = Field(..., description="Base64-encoded SAML response")
    relay_state: Optional[str] = Field(None, description="Relay state from initiation")


class OAuthCallbackRequest(BaseModel):
    """OAuth/OIDC callback request."""
    code: str = Field(..., description="Authorization code")
    state: str = Field(..., description="State parameter for CSRF validation")


class SSOCallbackResponse(BaseModel):
    """Response for SSO callback."""
    success: bool = Field(..., description="Whether authentication was successful")
    token: Optional[str] = Field(None, description="JWT access token")
    refresh_token: Optional[str] = Field(None, description="JWT refresh token")
    expires_in: Optional[int] = Field(None, description="Token expiration in seconds")
    user: Optional[Dict[str, Any]] = Field(None, description="User info")
    error: Optional[str] = Field(None, description="Error message if authentication failed")
    error_code: Optional[str] = Field(None, description="Error code for client handling")
    fallback_available: bool = Field(default=True, description="Whether local login is available")


class SSOError(str, Enum):
    """SSO error codes."""
    SSO_001 = "SSO_001"  # Provider not configured
    SSO_002 = "SSO_002"  # Invalid SAML assertion
    SSO_003 = "SSO_003"  # Invalid OAuth token
    SSO_004 = "SSO_004"  # Signature validation failed
    SSO_005 = "SSO_005"  # Claims extraction failed
    SSO_006 = "SSO_006"  # Provider unreachable
    SSO_007 = "SSO_007"  # Invalid state (CSRF)
    SSO_008 = "SSO_008"  # User creation failed
