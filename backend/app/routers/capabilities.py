"""API router for capability endpoints."""
import sys
from typing import List
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from app.models.capability import Capability, CapabilityVersion
from app.services.capability_service import get_capability_service
from app.services.tinydb_capability_service import tinydb_capability_service


router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.post("/reload")
async def reload_capabilities():
    """Reload capabilities from JSON file.
    
    This will clear the capabilities table and reload from the JSON file.
    Useful when capabilities.json has been updated.
    
    Returns:
        Status message with count of loaded capabilities
    """
    try:
        # Find capabilities.json - handle both dev and packaged modes
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # Running as PyInstaller bundle
            backend_dir = Path(sys._MEIPASS)
        else:
            # Running in development mode
            backend_dir = Path(__file__).parent.parent.parent
        
        capabilities_json = backend_dir / "capabilities" / "capabilities.json"
        
        if not capabilities_json.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Capabilities JSON file not found: {capabilities_json}"
            )
        
        # Reload capabilities
        success = tinydb_capability_service.load_capabilities_from_json(str(capabilities_json))
        
        if success:
            capabilities = tinydb_capability_service.get_all_capabilities()
            return {
                "status": "success",
                "message": f"Reloaded {len(capabilities)} capabilities",
                "capabilities": [cap.get("name") for cap in capabilities]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reload capabilities"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reloading capabilities: {str(e)}"
        )


@router.get("", response_model=List[Capability])
async def get_capabilities():
    """Get all available capabilities.
    
    Returns:
        List of all capabilities
    """
    service = get_capability_service()
    return service.get_all_capabilities()


@router.get("/{capability_id}", response_model=Capability)
async def get_capability(capability_id: str):
    """Get a specific capability by ID.
    
    Args:
        capability_id: The capability ID to retrieve
        
    Returns:
        Capability details
        
    Raises:
        HTTPException: 404 if capability not found
    """
    service = get_capability_service()
    capability = service.get_capability_by_id(capability_id)
    
    if capability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' not found"
        )
    
    return capability


@router.get("/{capability_id}/versions", response_model=List[CapabilityVersion])
async def get_capability_versions(capability_id: str):
    """Get available versions for a capability.
    
    Args:
        capability_id: The capability ID
        
    Returns:
        List of available versions
        
    Raises:
        HTTPException: 404 if capability not found
    """
    service = get_capability_service()
    
    # First check if capability exists
    capability = service.get_capability_by_id(capability_id)
    if capability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{capability_id}' not found"
        )
    
    versions = service.get_capability_versions(capability_id)
    return versions
