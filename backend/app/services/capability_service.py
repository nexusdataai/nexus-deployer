"""Capability service for loading and managing capabilities."""
import json
import os
import sys
from pathlib import Path
from typing import List, Optional
from app.models.capability import Capability, CapabilityList, CapabilityVersion
from app.services.tinydb_capability_service import tinydb_capability_service


class CapabilityService:
    """Service for managing capability definitions - now using TinyDB backend."""
    
    def __init__(self, capabilities_path: Optional[str] = None, use_tinydb: bool = True):
        """Initialize the capability service.
        
        Args:
            capabilities_path: Path to capabilities JSON file. If None, uses default location.
            use_tinydb: Whether to use TinyDB backend (default: True)
        """
        if capabilities_path is None:
            # Handle both development and PyInstaller packaged modes
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                # Running as PyInstaller bundle - data is in _MEIPASS
                base_path = Path(sys._MEIPASS)
            else:
                # Running in development mode
                base_path = Path(__file__).parent.parent.parent
            capabilities_path = base_path / "capabilities" / "capabilities.json"
        
        self.capabilities_path = Path(capabilities_path)
        self.use_tinydb = use_tinydb
        self._capabilities: Optional[CapabilityList] = None
    
    def _load_capabilities(self) -> CapabilityList:
        """Load capabilities from JSON file.
        
        Returns:
            CapabilityList containing all capabilities
            
        Raises:
            FileNotFoundError: If capabilities file doesn't exist
            json.JSONDecodeError: If JSON is invalid
        """
        if not self.capabilities_path.exists():
            raise FileNotFoundError(f"Capabilities file not found: {self.capabilities_path}")
        
        with open(self.capabilities_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return CapabilityList(**data)
    
    def get_all_capabilities(self) -> List[Capability]:
        """Get all available capabilities.
        
        Returns:
            List of all capabilities
        """
        if self.use_tinydb:
            # Use TinyDB backend
            capabilities_data = tinydb_capability_service.get_all_capabilities()
            # Convert dict to Capability objects
            return [Capability(**cap) for cap in capabilities_data]
        else:
            # Fallback to JSON file
            if self._capabilities is None:
                self._capabilities = self._load_capabilities()
            return self._capabilities.capabilities
    
    def get_capability_by_id(self, capability_id: str) -> Optional[Capability]:
        """Get a specific capability by ID.
        
        Args:
            capability_id: The capability ID to retrieve
            
        Returns:
            Capability if found, None otherwise
        """
        if self.use_tinydb:
            # Use TinyDB backend
            capability_data = tinydb_capability_service.get_capability_by_id(capability_id)
            if capability_data:
                return Capability(**capability_data)
            return None
        else:
            # Fallback to JSON file
            capabilities = self.get_all_capabilities()
            
            for capability in capabilities:
                if capability.id == capability_id:
                    return capability
            
            return None
    
    def get_capability_versions(self, capability_id: str) -> List[CapabilityVersion]:
        """Get available versions for a capability.
        
        Args:
            capability_id: The capability ID
            
        Returns:
            List of available versions
            
        Note:
            Currently returns only the current version. In a real implementation,
            this would query a version registry or database.
        """
        capability = self.get_capability_by_id(capability_id)
        
        if capability is None:
            return []
        
        # For now, return only the current version
        # In a real implementation, this would fetch from a version registry
        return [
            CapabilityVersion(
                version=capability.version,
                release_date="2024-01-15",
                changelog="Current stable release"
            )
        ]
    
    def reload_capabilities(self) -> None:
        """Reload capabilities from disk.
        
        Useful for development or when capabilities are updated.
        """
        self._capabilities = None


# Global instance
_capability_service: Optional[CapabilityService] = None


def get_capability_service() -> CapabilityService:
    """Get the global capability service instance.
    
    Returns:
        CapabilityService instance
    """
    global _capability_service
    if _capability_service is None:
        _capability_service = CapabilityService()
    return _capability_service
