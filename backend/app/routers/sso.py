"""
SSO Router
API endpoints for Single Sign-On authentication (SAML 2.0, OAuth 2.0, OIDC).
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import RedirectResponse

from app.models.sso_models import (
    SSOConfigResponse, SSOInitiateRequest, SSOInitiateResponse,
    SAMLCallbackRequest, OAuthCallbackRequest, SSOCallbackResponse,
    SSOProviderType, SSOError
)
from app.services.sso_service import get_sso_service, SSOService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sso", tags=["sso"])


def get_sso_service_dep() -> SSOService:
    """Dependency to get SSO service."""
    return get_sso_service()


@router.get("/config", response_model=SSOConfigResponse)
async def get_sso_config(
    sso_service: SSOService = Depends(get_sso_service_dep)
) -> SSOConfigResponse:
    """
    Get SSO configuration for the login page.
    
    Returns list of enabled SSO providers with their display information.
    Does not include sensitive configuration like client secrets.
    
    Returns:
    - **enabled**: Whether SSO is enabled (any providers configured)
    - **providers**: List of provider info (id, name, type, icon_url)
    - **default_provider**: ID of the default SSO provider
    """
    return sso_service.get_config()


@router.get("/initiate/{provider_id}")
async def initiate_sso(
    provider_id: str,
    redirect_uri: str = Query(..., description="Redirect URI after authentication"),
    sso_service: SSOService = Depends(get_sso_service_dep)
):
    """
    Initiate SSO flow by redirecting to identity provider.
    
    - **provider_id**: SSO provider ID
    - **redirect_uri**: Where to redirect after successful authentication
    
    Returns redirect to the identity provider's login page.
    """
    logger.info(f"SSO initiation request for provider: {provider_id}")
    
    provider = sso_service.get_provider(provider_id)
    if not provider:
        raise HTTPException(
            status_code=404,
            detail=f"SSO provider not found: {provider_id}"
        )
    
    if not provider.enabled:
        raise HTTPException(
            status_code=400,
            detail=f"SSO provider is disabled: {provider_id}"
        )
    
    # Generate redirect URL based on provider type
    if provider.type == SSOProviderType.SAML:
        result = sso_service.get_saml_redirect_url(provider_id, redirect_uri)
    else:
        result = sso_service.get_oauth_redirect_url(provider_id, redirect_uri)
    
    if not result.success:
        raise HTTPException(
            status_code=500,
            detail=result.error or "Failed to initiate SSO"
        )
    
    logger.info(f"Redirecting to SSO provider: {provider.name}")
    
    # Return redirect response
    return RedirectResponse(url=result.redirect_url, status_code=302)


@router.post("/initiate", response_model=SSOInitiateResponse)
async def initiate_sso_post(
    request: SSOInitiateRequest,
    sso_service: SSOService = Depends(get_sso_service_dep)
) -> SSOInitiateResponse:
    """
    Initiate SSO flow (POST version).
    
    Returns the redirect URL instead of redirecting directly.
    Useful for SPAs that need to handle the redirect themselves.
    
    - **provider_id**: SSO provider ID
    - **redirect_uri**: Where to redirect after successful authentication
    
    Returns:
    - **success**: Whether initiation was successful
    - **redirect_url**: URL to redirect user to
    - **error**: Error message if initiation failed
    """
    logger.info(f"SSO initiation request for provider: {request.provider_id}")
    
    provider = sso_service.get_provider(request.provider_id)
    if not provider:
        return SSOInitiateResponse(
            success=False,
            error=f"SSO provider not found: {request.provider_id}"
        )
    
    if not provider.enabled:
        return SSOInitiateResponse(
            success=False,
            error=f"SSO provider is disabled: {request.provider_id}"
        )
    
    redirect_uri = request.redirect_uri or "/"
    
    if provider.type == SSOProviderType.SAML:
        return sso_service.get_saml_redirect_url(request.provider_id, redirect_uri)
    else:
        return sso_service.get_oauth_redirect_url(request.provider_id, redirect_uri)


@router.post("/callback/saml", response_model=SSOCallbackResponse)
async def saml_callback(
    request: SAMLCallbackRequest,
    sso_service: SSOService = Depends(get_sso_service_dep)
) -> SSOCallbackResponse:
    """
    Handle SAML assertion callback.
    
    This endpoint receives the SAML response from the identity provider
    after successful authentication.
    
    - **saml_response**: Base64-encoded SAML response
    - **relay_state**: Relay state from initiation (for CSRF protection)
    
    Returns:
    - **success**: Whether authentication was successful
    - **token**: JWT access token
    - **refresh_token**: JWT refresh token
    - **expires_in**: Token expiration in seconds
    - **user**: User information
    - **error**: Error message if authentication failed
    - **error_code**: Error code for client handling
    - **fallback_available**: Whether local login is available as fallback
    """
    logger.info("SAML callback received")
    
    result = sso_service.validate_saml_assertion(
        request.saml_response,
        request.relay_state
    )
    
    if result.success:
        logger.info("SAML authentication successful")
    else:
        logger.info(f"SAML authentication failed: {result.error_code}")
    
    return result


@router.get("/callback/oauth", response_model=SSOCallbackResponse)
async def oauth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter for CSRF validation"),
    error: Optional[str] = Query(None, description="Error from provider"),
    error_description: Optional[str] = Query(None, description="Error description"),
    sso_service: SSOService = Depends(get_sso_service_dep)
) -> SSOCallbackResponse:
    """
    Handle OAuth/OIDC callback.
    
    This endpoint receives the authorization code from the OAuth provider
    after successful authentication.
    
    - **code**: Authorization code from provider
    - **state**: State parameter for CSRF validation
    - **error**: Error code if authentication failed at provider
    - **error_description**: Human-readable error description
    
    Returns:
    - **success**: Whether authentication was successful
    - **token**: JWT access token
    - **refresh_token**: JWT refresh token
    - **expires_in**: Token expiration in seconds
    - **user**: User information
    - **error**: Error message if authentication failed
    - **error_code**: Error code for client handling
    - **fallback_available**: Whether local login is available as fallback
    """
    logger.info("OAuth callback received")
    
    # Check for error from provider
    if error:
        logger.info(f"OAuth provider returned error: {error}")
        return SSOCallbackResponse(
            success=False,
            error=error_description or error,
            error_code=SSOError.SSO_003.value,
            fallback_available=True
        )
    
    result = await sso_service.exchange_oauth_code(code, state)
    
    if result.success:
        logger.info("OAuth authentication successful")
    else:
        logger.info(f"OAuth authentication failed: {result.error_code}")
    
    return result


@router.post("/callback/oauth", response_model=SSOCallbackResponse)
async def oauth_callback_post(
    request: OAuthCallbackRequest,
    sso_service: SSOService = Depends(get_sso_service_dep)
) -> SSOCallbackResponse:
    """
    Handle OAuth/OIDC callback (POST version).
    
    Alternative endpoint for OAuth callbacks that use POST method.
    
    - **code**: Authorization code from provider
    - **state**: State parameter for CSRF validation
    
    Returns:
    - **success**: Whether authentication was successful
    - **token**: JWT access token
    - **refresh_token**: JWT refresh token
    - **expires_in**: Token expiration in seconds
    - **user**: User information
    - **error**: Error message if authentication failed
    - **error_code**: Error code for client handling
    - **fallback_available**: Whether local login is available as fallback
    """
    logger.info("OAuth callback (POST) received")
    
    result = await sso_service.exchange_oauth_code(request.code, request.state)
    
    if result.success:
        logger.info("OAuth authentication successful")
    else:
        logger.info(f"OAuth authentication failed: {result.error_code}")
    
    return result


@router.get("/providers")
async def list_providers(
    sso_service: SSOService = Depends(get_sso_service_dep)
):
    """
    List all configured SSO providers.
    
    Returns detailed information about each provider (admin endpoint).
    
    Returns:
    - List of provider configurations (without secrets)
    """
    providers = sso_service.get_enabled_providers()
    
    return [
        {
            "id": p.id,
            "name": p.name,
            "type": p.type.value,
            "enabled": p.enabled,
            "auto_create_users": p.auto_create_users,
            "default_role": p.default_role,
            "role_mappings": [
                {"external": m.external_role, "internal": m.internal_role}
                for m in p.role_mappings
            ]
        }
        for p in providers
    ]


@router.get("/test/{provider_id}")
async def test_provider(
    provider_id: str,
    sso_service: SSOService = Depends(get_sso_service_dep)
):
    """
    Test SSO provider configuration.
    
    Validates that the provider is properly configured without
    actually initiating authentication.
    
    - **provider_id**: SSO provider ID to test
    
    Returns:
    - **valid**: Whether configuration is valid
    - **provider**: Provider information
    - **issues**: List of configuration issues (if any)
    """
    provider = sso_service.get_provider(provider_id)
    
    if not provider:
        return {
            "valid": False,
            "issues": [f"Provider not found: {provider_id}"]
        }
    
    issues = []
    
    # Check provider-specific configuration
    if provider.type == SSOProviderType.SAML:
        if not provider.saml_config:
            issues.append("SAML configuration missing")
        else:
            if not provider.saml_config.sso_url:
                issues.append("SAML SSO URL not configured")
            if not provider.saml_config.certificate:
                issues.append("SAML certificate not configured")
    
    elif provider.type in (SSOProviderType.OAUTH, SSOProviderType.OIDC):
        config = provider.oauth_config or provider.oidc_config
        if not config:
            issues.append("OAuth/OIDC configuration missing")
        else:
            if not config.client_id:
                issues.append("Client ID not configured")
            if not config.client_secret:
                issues.append("Client secret not configured")
            if not config.authorization_url:
                issues.append("Authorization URL not configured")
            if not config.token_url:
                issues.append("Token URL not configured")
        
        if provider.type == SSOProviderType.OIDC and provider.oidc_config:
            if not provider.oidc_config.issuer:
                issues.append("OIDC issuer not configured")
            if not provider.oidc_config.jwks_uri:
                issues.append("OIDC JWKS URI not configured")
    
    return {
        "valid": len(issues) == 0,
        "provider": {
            "id": provider.id,
            "name": provider.name,
            "type": provider.type.value,
            "enabled": provider.enabled
        },
        "issues": issues
    }
