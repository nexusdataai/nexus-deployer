"""
Initial Setup Router
API endpoints for first-time application setup.
"""
import logging
from fastapi import APIRouter, Depends

from app.services.initial_setup_service import get_setup_service, InitialSetupService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])


def get_setup_service_dep() -> InitialSetupService:
    """Dependency to get setup service."""
    return get_setup_service()


@router.get("/status")
async def get_setup_status(
    setup_service: InitialSetupService = Depends(get_setup_service_dep)
):
    """
    Get current setup status.
    
    Returns:
    - **setup_complete**: Whether initial setup is complete
    - **user_count**: Number of users in the system
    - **admin_exists**: Whether an admin user exists
    - **requires_initial_setup**: Whether setup wizard should be shown
    """
    return setup_service.get_setup_status()


@router.post("/initialize")
async def initialize_setup(
    setup_service: InitialSetupService = Depends(get_setup_service_dep)
):
    """
    Run initial setup (creates default admin if no users exist).
    
    This endpoint is idempotent - calling it multiple times is safe.
    
    Returns:
    - **setup_required**: Whether setup was needed
    - **setup_complete**: Whether setup completed successfully
    - **created**: Whether admin was created
    - **username**: Default admin username
    - **default_password**: Default admin password (only shown once)
    """
    return setup_service.run_initial_setup()
