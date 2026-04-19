"""
Configuration management API endpoints
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from app.models.config import (
    EnvironmentConfig,
    ConfigSaveRequest,
    ConfigResponse,
)
from app.services.config_service import config_service
from app.services.preset_service import preset_service

router = APIRouter(prefix="/api/config", tags=["configuration"])


@router.get("/presets")
async def get_all_presets():
    """
    Get all environment presets from JSON configuration.
    Returns defaults and presets for all environments.
    """
    try:
        presets = preset_service.get_all_presets()
        return {
            "success": True,
            "data": presets
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/presets/{environment}")
async def get_preset(environment: str):
    """
    Get preset configuration for a specific environment.
    """
    try:
        preset = preset_service.get_preset(environment)
        if preset is None:
            raise HTTPException(
                status_code=404, 
                detail=f"No preset found for environment: {environment}"
            )
        return {
            "success": True,
            "environment": environment,
            "data": preset
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/presets/reload")
async def reload_presets():
    """
    Reload presets from JSON file.
    Useful after modifying the environment_presets.json file.
    """
    try:
        success = preset_service.reload()
        if success:
            return {
                "success": True,
                "message": "Presets reloaded successfully"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to reload presets")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{capability_name}/{environment}", response_model=ConfigResponse)
async def get_config(capability_name: str, environment: str):
    """
    Get configuration for a capability and environment.
    Returns user config if exists, otherwise template or defaults.
    """
    try:
        config = config_service.get_config(capability_name, environment)
        return ConfigResponse(
            success=True,
            message="Configuration retrieved successfully",
            config=config
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save", response_model=ConfigResponse)
async def save_config(request: ConfigSaveRequest):
    """
    Save user configuration for a capability and environment.
    """
    try:
        success = config_service.save_config(
            request.capability_name,
            request.environment,
            request.config
        )
        
        if success:
            return ConfigResponse(
                success=True,
                message="Configuration saved successfully",
                config=request.config
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{capability_name}/{environment}", response_model=ConfigResponse)
async def delete_config(capability_name: str, environment: str):
    """
    Delete user configuration (reset to defaults).
    """
    try:
        success = config_service.delete_config(capability_name, environment)
        
        if success:
            # Return default config after deletion
            config = config_service.get_config(capability_name, environment)
            return ConfigResponse(
                success=True,
                message="Configuration reset to defaults",
                config=config
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to delete configuration")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
