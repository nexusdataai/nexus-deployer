"""
JWT Service
Manages JWT token creation, validation, and refresh for user authentication.
"""
import os
import uuid
import logging
import hashlib
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Try to import PyJWT
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logger.warning("PyJWT not installed, JWT functionality will be limited")


class JWTError(Exception):
    """Base exception for JWT errors."""
    pass


class TokenExpiredError(JWTError):
    """Exception raised when token is expired."""
    pass


class TokenInvalidError(JWTError):
    """Exception raised when token is invalid."""
    pass


class JWTService:
    """
    Service for JWT token management.
    Handles creation, validation, and refresh of access and refresh tokens.
    """
    
    # Token expiration times
    ACCESS_TOKEN_EXPIRY_MINUTES = 30
    REFRESH_TOKEN_EXPIRY_DAYS = 7
    
    # Algorithm for JWT signing
    ALGORITHM = "HS256"
    
    def __init__(self, secret_key: Optional[str] = None):
        """
        Initialize JWT service.
        
        Args:
            secret_key: Secret key for signing tokens. If not provided,
                       will use JWT_SECRET_KEY env var or generate a random one.
        """
        if secret_key:
            self._secret_key = secret_key
        else:
            self._secret_key = os.environ.get("JWT_SECRET_KEY")
            if not self._secret_key:
                # Generate a random secret key (not recommended for production)
                self._secret_key = secrets.token_hex(32)
                logger.warning(
                    "JWT_SECRET_KEY not set, using random key. "
                    "Sessions will not persist across restarts."
                )
        
        self._access_token_expiry = timedelta(minutes=self.ACCESS_TOKEN_EXPIRY_MINUTES)
        self._refresh_token_expiry = timedelta(days=self.REFRESH_TOKEN_EXPIRY_DAYS)
        
        logger.info(f"JWTService initialized (access token expiry: {self.ACCESS_TOKEN_EXPIRY_MINUTES} min)")
    
    def create_access_token(
        self,
        user_id: str,
        username: str,
        roles: List[str],
        additional_claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Create a JWT access token with 30-minute expiration.
        
        Args:
            user_id: User ID to include in token
            username: Username to include in token
            roles: List of user roles
            additional_claims: Optional additional claims to include
            
        Returns:
            JWT access token string
        """
        if not JWT_AVAILABLE:
            raise JWTError("PyJWT is not installed")
        
        now = datetime.utcnow()
        expires = now + self._access_token_expiry
        
        payload = {
            "sub": user_id,
            "username": username,
            "roles": roles,
            "type": "access",
            "jti": str(uuid.uuid4()),  # Unique token ID
            "iat": now,
            "exp": expires
        }
        
        if additional_claims:
            payload.update(additional_claims)
        
        token = jwt.encode(payload, self._secret_key, algorithm=self.ALGORITHM)
        
        logger.debug(f"Created access token for user: {username}")
        return token
    
    def create_refresh_token(self, user_id: str) -> str:
        """
        Create a JWT refresh token with 7-day expiration.
        
        Args:
            user_id: User ID to include in token
            
        Returns:
            JWT refresh token string
        """
        if not JWT_AVAILABLE:
            raise JWTError("PyJWT is not installed")
        
        now = datetime.utcnow()
        expires = now + self._refresh_token_expiry
        
        payload = {
            "sub": user_id,
            "type": "refresh",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": expires
        }
        
        token = jwt.encode(payload, self._secret_key, algorithm=self.ALGORITHM)
        
        logger.debug(f"Created refresh token for user: {user_id}")
        return token
    
    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate and decode a JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload if valid, None if invalid
            
        Raises:
            TokenExpiredError: If token is expired
            TokenInvalidError: If token is invalid
        """
        if not JWT_AVAILABLE:
            raise JWTError("PyJWT is not installed")
        
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM]
            )
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.debug("Token validation failed: expired")
            raise TokenExpiredError("Token has expired")
            
        except jwt.InvalidTokenError as e:
            logger.debug(f"Token validation failed: {str(e)}")
            raise TokenInvalidError(f"Invalid token: {str(e)}")
    
    def validate_token_safe(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate token without raising exceptions.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload if valid, None otherwise
        """
        try:
            return self.validate_token(token)
        except (TokenExpiredError, TokenInvalidError, JWTError):
            return None
    
    def is_token_expired(self, token: str) -> bool:
        """
        Check if a token is expired.
        
        Args:
            token: JWT token string
            
        Returns:
            True if token is expired, False otherwise
        """
        try:
            self.validate_token(token)
            return False
        except TokenExpiredError:
            return True
        except (TokenInvalidError, JWTError):
            return True  # Invalid tokens are considered expired
    
    def get_token_expiry(self, token: str) -> Optional[datetime]:
        """
        Get the expiration time of a token.
        
        Args:
            token: JWT token string
            
        Returns:
            Expiration datetime or None if token is invalid
        """
        if not JWT_AVAILABLE:
            return None
        
        try:
            # Decode without verification to get expiry even if expired
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM],
                options={"verify_exp": False}
            )
            exp = payload.get("exp")
            if exp:
                return datetime.utcfromtimestamp(exp)
            return None
        except jwt.InvalidTokenError:
            return None
    
    def get_token_user_id(self, token: str) -> Optional[str]:
        """
        Extract user ID from token without full validation.
        
        Args:
            token: JWT token string
            
        Returns:
            User ID or None if token is invalid
        """
        if not JWT_AVAILABLE:
            return None
        
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM],
                options={"verify_exp": False}
            )
            return payload.get("sub")
        except jwt.InvalidTokenError:
            return None
    
    def get_token_type(self, token: str) -> Optional[str]:
        """
        Get the type of token (access or refresh).
        
        Args:
            token: JWT token string
            
        Returns:
            Token type or None if invalid
        """
        if not JWT_AVAILABLE:
            return None
        
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM],
                options={"verify_exp": False}
            )
            return payload.get("type")
        except jwt.InvalidTokenError:
            return None
    
    def hash_token(self, token: str) -> str:
        """
        Create a hash of a token for storage.
        
        Args:
            token: JWT token string
            
        Returns:
            SHA-256 hash of the token
        """
        return hashlib.sha256(token.encode()).hexdigest()
    
    def get_access_token_expiry_seconds(self) -> int:
        """
        Get access token expiry in seconds.
        
        Returns:
            Expiry time in seconds
        """
        return int(self._access_token_expiry.total_seconds())
    
    def create_mfa_session_token(self, user_id: str, expiry_minutes: int = 5) -> str:
        """
        Create a temporary token for MFA verification.
        
        Args:
            user_id: User ID
            expiry_minutes: Token expiry in minutes (default 5)
            
        Returns:
            MFA session token
        """
        if not JWT_AVAILABLE:
            raise JWTError("PyJWT is not installed")
        
        now = datetime.utcnow()
        expires = now + timedelta(minutes=expiry_minutes)
        
        payload = {
            "sub": user_id,
            "type": "mfa_session",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": expires
        }
        
        token = jwt.encode(payload, self._secret_key, algorithm=self.ALGORITHM)
        
        logger.debug(f"Created MFA session token for user: {user_id}")
        return token
    
    def validate_mfa_session_token(self, token: str) -> Optional[str]:
        """
        Validate MFA session token and return user ID.
        
        Args:
            token: MFA session token
            
        Returns:
            User ID if valid, None otherwise
        """
        try:
            payload = self.validate_token(token)
            if payload and payload.get("type") == "mfa_session":
                return payload.get("sub")
            return None
        except (TokenExpiredError, TokenInvalidError):
            return None


# Global instance
_jwt_service: Optional[JWTService] = None


def get_jwt_service() -> JWTService:
    """
    Get global JWTService instance.
    
    Returns:
        JWTService instance
    """
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service


def reset_jwt_service():
    """Reset global JWTService instance (for testing)."""
    global _jwt_service
    _jwt_service = None
