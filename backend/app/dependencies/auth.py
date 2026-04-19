"""
Authentication Dependencies
FastAPI dependencies for protecting routes with authentication and authorization.
"""
import logging
from typing import Optional, List
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.auth_models import User, UserRole
from app.services.authentication_service import get_auth_service, AuthenticationService

logger = logging.getLogger(__name__)

# Security scheme for JWT bearer tokens
security = HTTPBearer(auto_error=False)


async def get_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Extract JWT token from Authorization header.
    
    Supports both:
    - Bearer token via HTTPBearer security scheme
    - Direct Authorization header with "Bearer " prefix
    """
    if credentials:
        return credentials.credentials
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


async def get_current_user(
    token: Optional[str] = Depends(get_token),
    auth_service: AuthenticationService = Depends(lambda: get_auth_service())
) -> User:
    """
    Get the current authenticated user.
    
    Validates the JWT token and returns the associated user.
    Raises HTTPException 401 if not authenticated.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"message": f"Hello, {user.username}"}
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    user = auth_service.validate_session(token)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled"
        )
    
    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(get_token),
    auth_service: AuthenticationService = Depends(lambda: get_auth_service())
) -> Optional[User]:
    """
    Get the current user if authenticated, None otherwise.
    
    Does not raise an exception if not authenticated.
    Useful for routes that have different behavior for authenticated vs anonymous users.
    
    Usage:
        @router.get("/public")
        async def public_route(user: Optional[User] = Depends(get_current_user_optional)):
            if user:
                return {"message": f"Hello, {user.username}"}
            return {"message": "Hello, guest"}
    """
    if not token:
        return None
    
    user = auth_service.validate_session(token)
    
    if user and user.is_active:
        return user
    
    return None


def require_role(required_roles: List[UserRole]):
    """
    Create a dependency that requires specific roles.
    
    Args:
        required_roles: List of roles that are allowed access
        
    Returns:
        Dependency function that validates user has required role
        
    Usage:
        @router.post("/admin-only")
        async def admin_route(
            user: User = Depends(require_role([UserRole.ADMINISTRATOR]))
        ):
            return {"message": "Admin access granted"}
        
        @router.post("/operators")
        async def operator_route(
            user: User = Depends(require_role([UserRole.ADMINISTRATOR, UserRole.OPERATOR]))
        ):
            return {"message": "Operator access granted"}
    """
    async def role_checker(user: User = Depends(get_current_user)) -> User:
        # Check if user has any of the required roles
        user_roles = set(user.roles)
        required_set = set(required_roles)
        
        if not user_roles.intersection(required_set):
            role_names = [r.value for r in required_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {role_names}"
            )
        
        return user
    
    return role_checker


# Convenience dependencies for common role requirements

async def require_admin(
    user: User = Depends(require_role([UserRole.ADMINISTRATOR]))
) -> User:
    """
    Require Administrator role.
    
    Usage:
        @router.delete("/users/{user_id}")
        async def delete_user(user_id: str, admin: User = Depends(require_admin)):
            ...
    """
    return user


async def require_operator(
    user: User = Depends(require_role([UserRole.ADMINISTRATOR, UserRole.OPERATOR]))
) -> User:
    """
    Require Operator role or higher (Administrator).
    
    Usage:
        @router.post("/deployments")
        async def create_deployment(operator: User = Depends(require_operator)):
            ...
    """
    return user


async def require_viewer(
    user: User = Depends(require_role([
        UserRole.ADMINISTRATOR, 
        UserRole.OPERATOR, 
        UserRole.VIEWER
    ]))
) -> User:
    """
    Require any authenticated user (Viewer role or higher).
    
    This is effectively the same as get_current_user but makes
    the role requirement explicit.
    
    Usage:
        @router.get("/capabilities")
        async def list_capabilities(viewer: User = Depends(require_viewer)):
            ...
    """
    return user


class RoleChecker:
    """
    Class-based role checker for more complex authorization scenarios.
    
    Usage:
        role_checker = RoleChecker([UserRole.ADMINISTRATOR, UserRole.OPERATOR])
        
        @router.post("/deploy")
        async def deploy(user: User = Depends(role_checker)):
            ...
    """
    
    def __init__(self, required_roles: List[UserRole]):
        self.required_roles = required_roles
    
    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        user_roles = set(user.roles)
        required_set = set(self.required_roles)
        
        if not user_roles.intersection(required_set):
            role_names = [r.value for r in self.required_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {role_names}"
            )
        
        return user
