"""
User Store Service
Manages user data persistence using TinyDB with Argon2 password hashing.
"""
import uuid
import logging
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime
from tinydb import Query

from app.services.tinydb_state_manager import get_state_manager
from app.models.auth_models import (
    User, UserCreate, UserUpdate, UserRole,
    Session, MFAEnrollment, MFASession, MFAMethod
)

logger = logging.getLogger(__name__)

# Try to import argon2, fall back to hashlib if not available
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHash
    ARGON2_AVAILABLE = True
    ph = PasswordHasher()
except ImportError:
    ARGON2_AVAILABLE = False
    logger.warning("argon2-cffi not installed, using SHA-256 fallback (not recommended for production)")


class UserStoreError(Exception):
    """Base exception for user store errors."""
    pass


class UserNotFoundError(UserStoreError):
    """Exception raised when user is not found."""
    pass


class UserAlreadyExistsError(UserStoreError):
    """Exception raised when user already exists."""
    pass


class UserStore:
    """
    Service for managing user data in TinyDB.
    Provides CRUD operations with Argon2 password hashing.
    """
    
    TABLE_NAME = "users"
    SESSIONS_TABLE = "sessions"
    MFA_ENROLLMENTS_TABLE = "mfa_enrollments"
    MFA_SESSIONS_TABLE = "mfa_sessions"
    
    def __init__(self):
        """Initialize user store with TinyDB connection."""
        self._db_manager = get_state_manager()
        self._users_table = self._db_manager.get_table(self.TABLE_NAME)
        self._sessions_table = self._db_manager.get_table(self.SESSIONS_TABLE)
        self._mfa_enrollments_table = self._db_manager.get_table(self.MFA_ENROLLMENTS_TABLE)
        self._mfa_sessions_table = self._db_manager.get_table(self.MFA_SESSIONS_TABLE)
        logger.info("UserStore initialized")
    
    # ==================== Password Hashing ====================
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using Argon2 (or SHA-256 fallback).
        
        Args:
            password: Plain text password
            
        Returns:
            Hashed password string
        """
        if ARGON2_AVAILABLE:
            return ph.hash(password)
        else:
            # Fallback to SHA-256 with salt (not recommended for production)
            salt = uuid.uuid4().hex
            hashed = hashlib.sha256((password + salt).encode()).hexdigest()
            return f"sha256${salt}${hashed}"
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash.
        
        Args:
            password: Plain text password to verify
            password_hash: Stored password hash
            
        Returns:
            True if password matches, False otherwise
        """
        if ARGON2_AVAILABLE:
            try:
                ph.verify(password_hash, password)
                return True
            except (VerifyMismatchError, InvalidHash):
                return False
        else:
            # Fallback verification for SHA-256
            if not password_hash.startswith("sha256$"):
                return False
            parts = password_hash.split("$")
            if len(parts) != 3:
                return False
            salt = parts[1]
            stored_hash = parts[2]
            computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
            return computed_hash == stored_hash
    
    @staticmethod
    def needs_rehash(password_hash: str) -> bool:
        """
        Check if password hash needs to be rehashed (e.g., algorithm upgrade).
        
        Args:
            password_hash: Stored password hash
            
        Returns:
            True if rehash is needed
        """
        if ARGON2_AVAILABLE:
            try:
                return ph.check_needs_rehash(password_hash)
            except:
                return True  # Non-Argon2 hash needs rehash
        return False
    
    # ==================== User CRUD Operations ====================
    
    def create_user(self, user_data: UserCreate) -> User:
        """
        Create a new user.
        
        Args:
            user_data: User creation data
            
        Returns:
            Created User object
            
        Raises:
            UserAlreadyExistsError: If username or email already exists
        """
        UserQuery = Query()
        
        # Check if username exists
        existing = self._users_table.get(UserQuery.username == user_data.username)
        if existing:
            raise UserAlreadyExistsError(f"Username '{user_data.username}' already exists")
        
        # Check if email exists
        existing = self._users_table.get(UserQuery.email == user_data.email)
        if existing:
            raise UserAlreadyExistsError(f"Email '{user_data.email}' already exists")
        
        now = datetime.utcnow().isoformat()
        user = User(
            id=str(uuid.uuid4()),
            username=user_data.username,
            email=user_data.email,
            password_hash=self.hash_password(user_data.password),
            roles=user_data.roles,
            created_at=now,
            updated_at=now,
            require_password_change=True  # Require password change on first login
        )
        
        self._users_table.insert(user.model_dump())
        logger.info(f"Created user: {user.username} (id: {user.id})")
        return user
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get user by ID.
        
        Args:
            user_id: User ID
            
        Returns:
            User object or None if not found
        """
        UserQuery = Query()
        doc = self._users_table.get(UserQuery.id == user_id)
        if doc:
            return User(**doc)
        return None
    
    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        Get user by username.
        
        Args:
            username: Username
            
        Returns:
            User object or None if not found
        """
        UserQuery = Query()
        doc = self._users_table.get(UserQuery.username == username)
        if doc:
            return User(**doc)
        return None
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email.
        
        Args:
            email: Email address
            
        Returns:
            User object or None if not found
        """
        UserQuery = Query()
        doc = self._users_table.get(UserQuery.email == email)
        if doc:
            return User(**doc)
        return None
    
    def get_user_by_sso(self, provider: str, subject: str) -> Optional[User]:
        """
        Get user by SSO provider and subject.
        
        Args:
            provider: SSO provider ID
            subject: SSO subject identifier
            
        Returns:
            User object or None if not found
        """
        UserQuery = Query()
        doc = self._users_table.get(
            (UserQuery.sso_provider == provider) & 
            (UserQuery.sso_subject == subject)
        )
        if doc:
            return User(**doc)
        return None
    
    def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[User]:
        """
        Update user fields.
        
        Args:
            user_id: User ID
            updates: Dictionary of fields to update
            
        Returns:
            Updated User object or None if not found
        """
        UserQuery = Query()
        
        # Add updated_at timestamp
        updates["updated_at"] = datetime.utcnow().isoformat()
        
        # Update in database
        result = self._users_table.update(updates, UserQuery.id == user_id)
        
        if result:
            return self.get_user_by_id(user_id)
        return None
    
    def delete_user(self, user_id: str) -> bool:
        """
        Delete a user.
        
        Args:
            user_id: User ID
            
        Returns:
            True if deleted, False if not found
        """
        UserQuery = Query()
        result = self._users_table.remove(UserQuery.id == user_id)
        if result:
            logger.info(f"Deleted user: {user_id}")
            return True
        return False
    
    def list_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """
        List all users with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            List of User objects
        """
        all_docs = self._users_table.all()
        paginated = all_docs[skip:skip + limit]
        return [User(**doc) for doc in paginated]
    
    # ==================== Failed Login Tracking ====================
    
    def increment_failed_login(self, username: str) -> int:
        """
        Increment failed login counter for a user.
        
        Args:
            username: Username
            
        Returns:
            New failed login count
        """
        user = self.get_user_by_username(username)
        if not user:
            return 0
        
        new_count = user.failed_login_count + 1
        self.update_user(user.id, {
            "failed_login_count": new_count,
            "last_failed_login": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Failed login count for {username}: {new_count}")
        return new_count
    
    def reset_failed_login(self, username: str) -> None:
        """
        Reset failed login counter for a user.
        
        Args:
            username: Username
        """
        user = self.get_user_by_username(username)
        if user:
            self.update_user(user.id, {
                "failed_login_count": 0,
                "last_failed_login": None
            })
            logger.info(f"Reset failed login count for {username}")
    
    def verify_user_password(self, user_id: str, password: str) -> bool:
        """
        Verify a user's password.
        
        Args:
            user_id: User ID
            password: Plain text password to verify
            
        Returns:
            True if password matches, False otherwise
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        return self.verify_password(password, user.password_hash)
    
    def update_password(self, user_id: str, new_password: str) -> bool:
        """
        Update a user's password.
        
        Args:
            user_id: User ID
            new_password: New plain text password
            
        Returns:
            True if updated, False if user not found
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        
        new_hash = self.hash_password(new_password)
        result = self.update_user(user_id, {
            "password_hash": new_hash,
            "password_changed_at": datetime.utcnow().isoformat(),
            "require_password_change": False
        })
        
        if result:
            logger.info(f"Password updated for user: {user.username}")
            return True
        return False
    
    # ==================== Session Management ====================
    
    def create_session(
        self,
        user_id: str,
        token_hash: str,
        refresh_token_hash: Optional[str] = None,
        expires_at: str = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Session:
        """
        Create a new session.
        
        Args:
            user_id: User ID
            token_hash: Hash of the JWT token
            refresh_token_hash: Hash of the refresh token
            expires_at: Session expiration timestamp
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Created Session object
        """
        now = datetime.utcnow().isoformat()
        session = Session(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            refresh_token_hash=refresh_token_hash,
            created_at=now,
            expires_at=expires_at or now,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        self._sessions_table.insert(session.model_dump())
        logger.info(f"Created session for user: {user_id}")
        return session
    
    def get_session_by_token_hash(self, token_hash: str) -> Optional[Session]:
        """
        Get session by token hash.
        
        Args:
            token_hash: Hash of the JWT token
            
        Returns:
            Session object or None if not found
        """
        SessionQuery = Query()
        doc = self._sessions_table.get(
            (SessionQuery.token_hash == token_hash) & 
            (SessionQuery.is_valid == True)
        )
        if doc:
            return Session(**doc)
        return None
    
    def invalidate_session(self, session_id: str) -> bool:
        """
        Invalidate a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if invalidated, False if not found
        """
        SessionQuery = Query()
        result = self._sessions_table.update(
            {"is_valid": False},
            SessionQuery.id == session_id
        )
        return bool(result)
    
    def invalidate_user_sessions(self, user_id: str) -> int:
        """
        Invalidate all sessions for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Number of sessions invalidated
        """
        SessionQuery = Query()
        result = self._sessions_table.update(
            {"is_valid": False},
            SessionQuery.user_id == user_id
        )
        return len(result) if result else 0
    
    # ==================== MFA Enrollment ====================
    
    def create_mfa_enrollment(
        self,
        user_id: str,
        method: MFAMethod,
        secret: str
    ) -> MFAEnrollment:
        """
        Create MFA enrollment record.
        
        Args:
            user_id: User ID
            method: MFA method
            secret: Encrypted secret
            
        Returns:
            Created MFAEnrollment object
        """
        enrollment = MFAEnrollment(
            id=str(uuid.uuid4()),
            user_id=user_id,
            method=method,
            secret=secret,
            created_at=datetime.utcnow().isoformat()
        )
        
        self._mfa_enrollments_table.insert(enrollment.model_dump())
        logger.info(f"Created MFA enrollment for user: {user_id}, method: {method}")
        return enrollment
    
    def get_mfa_enrollment(self, user_id: str) -> Optional[MFAEnrollment]:
        """
        Get MFA enrollment for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            MFAEnrollment object or None if not found
        """
        EnrollmentQuery = Query()
        doc = self._mfa_enrollments_table.get(EnrollmentQuery.user_id == user_id)
        if doc:
            return MFAEnrollment(**doc)
        return None
    
    def verify_mfa_enrollment(self, user_id: str) -> bool:
        """
        Mark MFA enrollment as verified.
        
        Args:
            user_id: User ID
            
        Returns:
            True if updated, False if not found
        """
        EnrollmentQuery = Query()
        result = self._mfa_enrollments_table.update(
            {"verified": True},
            EnrollmentQuery.user_id == user_id
        )
        return bool(result)
    
    def delete_mfa_enrollment(self, user_id: str) -> bool:
        """
        Delete MFA enrollment for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            True if deleted, False if not found
        """
        EnrollmentQuery = Query()
        result = self._mfa_enrollments_table.remove(EnrollmentQuery.user_id == user_id)
        return bool(result)
    
    # ==================== MFA Sessions ====================
    
    def create_mfa_session(
        self,
        user_id: str,
        expires_at: str,
        code_hash: Optional[str] = None
    ) -> MFASession:
        """
        Create temporary MFA verification session.
        
        Args:
            user_id: User ID
            expires_at: Session expiration timestamp
            code_hash: Hash of SMS/email code if applicable
            
        Returns:
            Created MFASession object
        """
        session = MFASession(
            id=str(uuid.uuid4()),
            user_id=user_id,
            created_at=datetime.utcnow().isoformat(),
            expires_at=expires_at,
            code_hash=code_hash
        )
        
        self._mfa_sessions_table.insert(session.model_dump())
        logger.info(f"Created MFA session for user: {user_id}")
        return session
    
    def get_mfa_session(self, session_id: str) -> Optional[MFASession]:
        """
        Get MFA session by ID.
        
        Args:
            session_id: MFA session ID
            
        Returns:
            MFASession object or None if not found
        """
        SessionQuery = Query()
        doc = self._mfa_sessions_table.get(
            (SessionQuery.id == session_id) & 
            (SessionQuery.is_valid == True)
        )
        if doc:
            return MFASession(**doc)
        return None
    
    def decrement_mfa_retries(self, session_id: str) -> int:
        """
        Decrement MFA retry counter.
        
        Args:
            session_id: MFA session ID
            
        Returns:
            Remaining retries
        """
        session = self.get_mfa_session(session_id)
        if not session:
            return 0
        
        new_retries = max(0, session.retries_remaining - 1)
        
        SessionQuery = Query()
        self._mfa_sessions_table.update(
            {"retries_remaining": new_retries},
            SessionQuery.id == session_id
        )
        
        return new_retries
    
    def invalidate_mfa_session(self, session_id: str) -> bool:
        """
        Invalidate MFA session.
        
        Args:
            session_id: MFA session ID
            
        Returns:
            True if invalidated, False if not found
        """
        SessionQuery = Query()
        result = self._mfa_sessions_table.update(
            {"is_valid": False},
            SessionQuery.id == session_id
        )
        return bool(result)


# Global instance
_user_store: Optional[UserStore] = None


def get_user_store() -> UserStore:
    """
    Get global UserStore instance.
    
    Returns:
        UserStore instance
    """
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store


def reset_user_store():
    """Reset global UserStore instance (for testing)."""
    global _user_store
    _user_store = None
