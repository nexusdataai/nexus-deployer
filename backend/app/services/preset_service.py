"""
Environment Preset Service
Loads environment configuration presets from JSON file
"""
import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class PresetService:
    """Service for loading environment presets from JSON file"""
    
    def __init__(self):
        self._presets: Optional[Dict[str, Any]] = None
        self._presets_file = self._get_presets_file_path()
    
    def _get_presets_file_path(self) -> str:
        """Get the path to the environment_presets.json file"""
        # Try multiple locations
        possible_paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', 'capabilities', 'environment_presets.json'),
            os.path.join(os.getcwd(), 'capabilities', 'environment_presets.json'),
            os.path.join(os.getcwd(), 'backend', 'capabilities', 'environment_presets.json'),
        ]
        
        for path in possible_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                logger.info(f"Found environment presets at: {abs_path}")
                return abs_path
        
        # Default to first path
        return os.path.abspath(possible_paths[0])
    
    def _load_presets(self) -> Dict[str, Any]:
        """Load presets from JSON file"""
        if self._presets is not None:
            return self._presets
        
        try:
            with open(self._presets_file, 'r') as f:
                self._presets = json.load(f)
                logger.info(f"Loaded environment presets from {self._presets_file}")
                return self._presets
        except FileNotFoundError:
            logger.warning(f"Environment presets file not found: {self._presets_file}")
            return {"defaults": {}, "presets": {}}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse environment presets JSON: {e}")
            return {"defaults": {}, "presets": {}}
    
    def get_all_presets(self) -> Dict[str, Any]:
        """Get all environment presets"""
        data = self._load_presets()
        return {
            "defaults": data.get("defaults", {}),
            "presets": data.get("presets", {})
        }
    
    def get_preset(self, environment: str) -> Optional[Dict[str, Any]]:
        """Get preset for a specific environment"""
        data = self._load_presets()
        presets = data.get("presets", {})
        return presets.get(environment)
    
    def get_defaults(self) -> Dict[str, Any]:
        """Get default values (base domain, hosted zone, etc.)"""
        data = self._load_presets()
        return data.get("defaults", {})
    
    def reload(self) -> bool:
        """Force reload presets from file"""
        self._presets = None
        try:
            self._load_presets()
            return True
        except Exception as e:
            logger.error(f"Failed to reload presets: {e}")
            return False


# Singleton instance
preset_service = PresetService()
