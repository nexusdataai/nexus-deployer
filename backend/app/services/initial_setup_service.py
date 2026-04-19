"""
Initial Setup Service
Handles first-time setup including default admin creation.
"""
import os
import logging
from typing import Optional
from datetime import datetime

from app.models.auth_models import UserRole, UserCreate
from app.services.user_store import get_user_store, UserStore

logger = logging.getLogger(__name__)

# Default admin credentials (should be changed on first login)
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_EMAIL = "admin@localhost"
DEFAULT_ADMIN_PASSWORD = "CallSense2026!"  # Must be changed on first login


class InitialSetupService:
    """
    Service for handling initial application setup.
    
    On first launch:
    - Detects if any users exist
    - Creates default admin account if none exist
    - Marks admin to require password change
    """
    
    def __init__(self, user_store: Optional[UserStore] = None):
        self._user_store = user_store or get_user_store()
    
    def is_setup_required(self) -> bool:
        """
        Check if initial setup is required.
        
        Returns:
            True if no users exist and setup is needed
        """
        users = self._user_store.list_users()
        return len(users) == 0
    
    def get_setup_status(self) -> dict:
        """
        Get current setup status.
        
        Returns:
            Dict with setup status information
        """
        users = self._user_store.list_users()
        admin_exists = any(
            UserRole.ADMINISTRATOR in u.roles 
            for u in users
        )
        
        return {
            "setup_complete": len(users) > 0,
            "user_count": len(users),
            "admin_exists": admin_exists,
            "requires_initial_setup": len(users) == 0
        }
    
    def create_default_admin(self) -> dict:
        """
        Create the default admin account.
        
        Returns:
            Dict with admin credentials info
        """
        # Check if admin already exists
        existing = self._user_store.get_user_by_username(DEFAULT_ADMIN_USERNAME)
        if existing:
            logger.info("Default admin already exists")
            return {
                "created": False,
                "message": "Admin account already exists",
                "username": DEFAULT_ADMIN_USERNAME
            }
        
        # Create admin user with password change required
        user_data = UserCreate(
            username=DEFAULT_ADMIN_USERNAME,
            email=DEFAULT_ADMIN_EMAIL,
            password=DEFAULT_ADMIN_PASSWORD,
            roles=[UserRole.ADMINISTRATOR]
        )
        user = self._user_store.create_user(user_data)
        
        logger.info(f"Created default admin account: {DEFAULT_ADMIN_USERNAME}")
        
        return {
            "created": True,
            "message": "Default admin account created",
            "username": DEFAULT_ADMIN_USERNAME,
            "default_password": DEFAULT_ADMIN_PASSWORD,
            "require_password_change": True
        }
    
    def run_initial_setup(self) -> dict:
        """
        Run initial setup if required.
        
        Called on application startup.
        
        Returns:
            Setup result
        """
        if not self.is_setup_required():
            return {
                "setup_required": False,
                "message": "Setup already complete"
            }
        
        logger.info("Running initial setup - creating default admin account")
        
        result = self.create_default_admin()
        
        return {
            "setup_required": True,
            "setup_complete": True,
            **result
        }


# Global instance
_setup_service: Optional[InitialSetupService] = None


def get_setup_service() -> InitialSetupService:
    """Get global InitialSetupService instance."""
    global _setup_service
    if _setup_service is None:
        _setup_service = InitialSetupService()
    return _setup_service


def reset_setup_service():
    """Reset global instance (for testing)."""
    global _setup_service
    _setup_service = None
