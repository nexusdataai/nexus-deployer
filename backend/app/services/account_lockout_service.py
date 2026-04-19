"""
Account Lockout Service
Manages account lockout protection against brute force attacks.
"""
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta

from app.services.user_store import get_user_store, UserStore

logger = logging.getLogger(__name__)


class AccountLockoutService:
    """
    Service for managing account lockout protection.
    
    Implements:
    - Failed login attempt tracking
    - Account lockout after 5 consecutive failures
    - 15-minute lockout duration
    - Automatic counter reset after lockout expires
    """
    
    # Lockout configuration
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_DURATION_MINUTES = 15
    
    def __init__(self, user_store: Optional[UserStore] = None):
        """
        Initialize account lockout service.
        
        Args:
            user_store: UserStore instance (uses global if not provided)
        """
        self._user_store = user_store or get_user_store()
        self._lockout_duration = timedelta(minutes=self.LOCKOUT_DURATION_MINUTES)
        
        logger.info(
            f"AccountLockoutService initialized "
            f"(max attempts: {self.MAX_FAILED_ATTEMPTS}, "
            f"lockout duration: {self.LOCKOUT_DURATION_MINUTES} min)"
        )
    
    def record_failed_attempt(self, username: str) -> int:
        """
        Record a failed login attempt for a user.
        
        Args:
            username: Username that failed to authenticate
            
        Returns:
            Current failed attempt count after increment
        """
        user = self._user_store.get_user_by_username(username)
        if not user:
            logger.debug(f"Failed attempt for unknown user: {username}")
            return 0
        
        # Check if account is currently locked
        is_locked, _ = self.is_account_locked(username)
        if is_locked:
            # Don't increment counter while locked
            logger.debug(f"Account {username} is locked, not incrementing counter")
            return user.failed_login_count
        
        # Increment counter
        new_count = self._user_store.increment_failed_login(username)
        
        if new_count >= self.MAX_FAILED_ATTEMPTS:
            logger.warning(
                f"Account {username} locked after {new_count} failed attempts"
            )
        else:
            logger.info(
                f"Failed login attempt for {username}: "
                f"{new_count}/{self.MAX_FAILED_ATTEMPTS}"
            )
        
        return new_count
    
    def is_account_locked(self, username: str) -> Tuple[bool, Optional[int]]:
        """
        Check if an account is currently locked.
        
        Args:
            username: Username to check
            
        Returns:
            Tuple of (is_locked, seconds_remaining)
            - is_locked: True if account is locked
            - seconds_remaining: Seconds until lockout expires (None if not locked)
        """
        user = self._user_store.get_user_by_username(username)
        if not user:
            return False, None
        
        # Check if failed attempts reached threshold
        if user.failed_login_count < self.MAX_FAILED_ATTEMPTS:
            return False, None
        
        # Check if lockout has expired
        if not user.last_failed_login:
            return False, None
        
        try:
            last_failed = datetime.fromisoformat(user.last_failed_login)
        except (ValueError, TypeError):
            logger.warning(f"Invalid last_failed_login timestamp for {username}")
            return False, None
        
        lockout_end = last_failed + self._lockout_duration
        now = datetime.utcnow()
        
        if now >= lockout_end:
            # Lockout has expired, reset counter
            logger.info(f"Lockout expired for {username}, resetting counter")
            self.reset_failed_attempts(username)
            return False, None
        
        # Account is still locked
        remaining_seconds = int((lockout_end - now).total_seconds())
        logger.debug(
            f"Account {username} is locked, {remaining_seconds}s remaining"
        )
        return True, remaining_seconds
    
    def reset_failed_attempts(self, username: str) -> None:
        """
        Reset failed login counter for a user.
        
        Called after successful authentication or when lockout expires.
        
        Args:
            username: Username to reset
        """
        self._user_store.reset_failed_login(username)
        logger.info(f"Reset failed login counter for {username}")
    
    def get_failed_attempt_count(self, username: str) -> int:
        """
        Get current failed attempt count for a user.
        
        Args:
            username: Username to check
            
        Returns:
            Current failed attempt count
        """
        user = self._user_store.get_user_by_username(username)
        if not user:
            return 0
        return user.failed_login_count
    
    def get_lockout_end_time(self, username: str) -> Optional[datetime]:
        """
        Get the time when lockout will end for a user.
        
        Args:
            username: Username to check
            
        Returns:
            Lockout end datetime or None if not locked
        """
        user = self._user_store.get_user_by_username(username)
        if not user:
            return None
        
        if user.failed_login_count < self.MAX_FAILED_ATTEMPTS:
            return None
        
        if not user.last_failed_login:
            return None
        
        try:
            last_failed = datetime.fromisoformat(user.last_failed_login)
            return last_failed + self._lockout_duration
        except (ValueError, TypeError):
            return None
    
    def get_remaining_attempts(self, username: str) -> int:
        """
        Get remaining login attempts before lockout.
        
        Args:
            username: Username to check
            
        Returns:
            Number of remaining attempts (0 if locked)
        """
        user = self._user_store.get_user_by_username(username)
        if not user:
            return self.MAX_FAILED_ATTEMPTS
        
        is_locked, _ = self.is_account_locked(username)
        if is_locked:
            return 0
        
        return max(0, self.MAX_FAILED_ATTEMPTS - user.failed_login_count)


# Global instance
_lockout_service: Optional[AccountLockoutService] = None


def get_lockout_service() -> AccountLockoutService:
    """
    Get global AccountLockoutService instance.
    
    Returns:
        AccountLockoutService instance
    """
    global _lockout_service
    if _lockout_service is None:
        _lockout_service = AccountLockoutService()
    return _lockout_service


def reset_lockout_service():
    """Reset global AccountLockoutService instance (for testing)."""
    global _lockout_service
    _lockout_service = None
