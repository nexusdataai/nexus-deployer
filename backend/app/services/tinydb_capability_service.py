"""
TinyDB-based Capability Service
Manages capabilities catalogue using TinyDB
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from tinydb import Query

from .tinydb_state_manager import TinyDBStateManager, get_state_manager, DatabaseError

logger = logging.getLogger(__name__)


class TinyDBCapabilityService:
    """Service for managing capabilities catalogue using TinyDB"""
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """
        Initialize capability service with TinyDB
        
        Args:
            db_manager: TinyDB state manager (uses global instance if None)
        """
        self.db_manager = db_manager or get_state_manager()
        self.capabilities_table = self.db_manager.get_table("capabilities")
        logger.info("TinyDB Capability Service initialized")
    
    def load_capabilities_from_json(self, json_path: str) -> bool:
        """
        Load capabilities from JSON file into TinyDB
        
        Args:
            json_path: Path to capabilities JSON file
            
        Returns:
            True if loaded successfully
        """
        try:
            json_file = Path(json_path)
            
            if not json_file.exists():
                logger.error(f"Capabilities JSON file not found: {json_path}")
                return False
            
            with open(json_file, 'r') as f:
                capabilities_data = json.load(f)
            
            # Handle both list format and object with "capabilities" key
            if isinstance(capabilities_data, dict) and "capabilities" in capabilities_data:
                capabilities_list = capabilities_data["capabilities"]
            elif isinstance(capabilities_data, list):
                capabilities_list = capabilities_data
            else:
                logger.error("Capabilities JSON must be a list or object with 'capabilities' key")
                return False
            
            # Clear existing capabilities
            self.capabilities_table.truncate()
            
            # Insert capabilities
            for capability in capabilities_list:
                # Add timestamps if not present
                if "created_at" not in capability:
                    capability["created_at"] = datetime.utcnow().isoformat()
                if "updated_at" not in capability:
                    capability["updated_at"] = datetime.utcnow().isoformat()
                
                self.capabilities_table.insert(capability)
            
            logger.info(f"Loaded {len(capabilities_data)} capabilities from {json_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load capabilities from JSON: {str(e)}")
            return False
    
    def get_all_capabilities(self) -> List[Dict[str, Any]]:
        """
        Get all capabilities
        
        Returns:
            List of all capability records
        """
        try:
            capabilities = self.capabilities_table.all()
            logger.info(f"Retrieved {len(capabilities)} capabilities")
            return capabilities
        except Exception as e:
            logger.error(f"Failed to get all capabilities: {str(e)}")
            return []
    
    def get_capability_by_id(self, capability_id: str) -> Optional[Dict[str, Any]]:
        """
        Get capability by ID
        
        Args:
            capability_id: Capability ID
            
        Returns:
            Capability record or None if not found
        """
        try:
            CapabilityQuery = Query()
            capability = self.capabilities_table.get(CapabilityQuery.id == capability_id)
            
            if capability:
                logger.info(f"Retrieved capability: {capability_id}")
            else:
                logger.info(f"Capability not found: {capability_id}")
            
            return capability
        except Exception as e:
            logger.error(f"Failed to get capability by ID: {str(e)}")
            return None
    
    def update_capability(
        self,
        capability_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update capability information
        
        Args:
            capability_id: Capability ID
            updates: Dict with fields to update
            
        Returns:
            True if updated successfully
        """
        try:
            CapabilityQuery = Query()
            
            # Add updated_at timestamp
            updates["updated_at"] = datetime.utcnow().isoformat()
            
            updated = self.capabilities_table.update(
                updates,
                CapabilityQuery.id == capability_id
            )
            
            if updated:
                logger.info(f"Updated capability: {capability_id}")
                return True
            else:
                logger.warning(f"Capability not found for update: {capability_id}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to update capability: {str(e)}")
            return False
    
    def add_capability(self, capability: Dict[str, Any]) -> bool:
        """
        Add new capability to catalogue
        
        Args:
            capability: Capability data
            
        Returns:
            True if added successfully
        """
        try:
            # Add timestamps
            capability["created_at"] = datetime.utcnow().isoformat()
            capability["updated_at"] = datetime.utcnow().isoformat()
            
            self.capabilities_table.insert(capability)
            logger.info(f"Added new capability: {capability.get('id', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add capability: {str(e)}")
            return False
    
    def search_capabilities(
        self,
        search_term: str,
        category: Optional[str] = None,
        cloud_provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search capabilities with filters
        
        Args:
            search_term: Search term for name/description
            category: Filter by category
            cloud_provider: Filter by cloud provider
            
        Returns:
            List of matching capabilities
        """
        try:
            CapabilityQuery = Query()
            
            # Get all capabilities and filter in Python for case-insensitive search
            all_capabilities = self.capabilities_table.all()
            results = []
            
            search_lower = search_term.lower()
            
            for cap in all_capabilities:
                # Check search term match (case-insensitive partial match)
                name_match = search_lower in cap.get("name", "").lower()
                desc_match = search_lower in cap.get("description", "").lower()
                
                if not (name_match or desc_match):
                    continue
                
                # Check category filter
                if category and cap.get("category") != category:
                    continue
                
                # Check cloud provider filter
                if cloud_provider:
                    supported_clouds = cap.get("supported_clouds", [])
                    if cloud_provider not in supported_clouds:
                        continue
                
                results.append(cap)
            
            logger.info(f"Search found {len(results)} capabilities")
            return results
            
        except Exception as e:
            logger.error(f"Failed to search capabilities: {str(e)}")
            return []
    
    def get_capabilities_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Get capabilities filtered by category
        
        Args:
            category: Category name
            
        Returns:
            List of capabilities in the category
        """
        try:
            CapabilityQuery = Query()
            capabilities = self.capabilities_table.search(CapabilityQuery.category == category)
            logger.info(f"Found {len(capabilities)} capabilities in category '{category}'")
            return capabilities
        except Exception as e:
            logger.error(f"Failed to get capabilities by category: {str(e)}")
            return []
    
    def sort_capabilities(
        self,
        capabilities: List[Dict[str, Any]],
        sort_field: str,
        ascending: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Sort capabilities by specified field
        
        Args:
            capabilities: List of capabilities to sort
            sort_field: Field name to sort by
            ascending: Sort order (True for ascending, False for descending)
            
        Returns:
            Sorted list of capabilities
        """
        try:
            sorted_caps = sorted(
                capabilities,
                key=lambda x: x.get(sort_field, ""),
                reverse=not ascending
            )
            return sorted_caps
        except Exception as e:
            logger.error(f"Failed to sort capabilities: {str(e)}")
            return capabilities
    
    def compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two semantic version strings
        
        Args:
            version1: First version string (e.g., "1.2.3")
            version2: Second version string (e.g., "1.3.0")
            
        Returns:
            -1 if version1 < version2, 0 if equal, 1 if version1 > version2
        """
        try:
            # Parse version strings
            v1_parts = [int(x) for x in version1.split('.')]
            v2_parts = [int(x) for x in version2.split('.')]
            
            # Pad shorter version with zeros
            max_len = max(len(v1_parts), len(v2_parts))
            v1_parts += [0] * (max_len - len(v1_parts))
            v2_parts += [0] * (max_len - len(v2_parts))
            
            # Compare
            if v1_parts < v2_parts:
                return -1
            elif v1_parts > v2_parts:
                return 1
            else:
                return 0
                
        except Exception as e:
            logger.error(f"Failed to compare versions: {str(e)}")
            return 0
    
    def query_nested_field(
        self,
        field_path: str,
        field_value: Any
    ) -> List[Dict[str, Any]]:
        """
        Query capabilities by nested field value
        
        Args:
            field_path: Dot-separated path to nested field (e.g., "requirements.frontend")
            field_value: Value to match
            
        Returns:
            List of matching capabilities
        """
        try:
            all_capabilities = self.capabilities_table.all()
            results = []
            
            for cap in all_capabilities:
                # Navigate nested fields
                current = cap
                for field in field_path.split('.'):
                    if isinstance(current, dict) and field in current:
                        current = current[field]
                    else:
                        current = None
                        break
                
                # Check if value matches
                if current == field_value:
                    results.append(cap)
            
            logger.info(f"Nested field query found {len(results)} capabilities")
            return results
            
        except Exception as e:
            logger.error(f"Failed to query nested field: {str(e)}")
            return []


# Global instance
tinydb_capability_service = TinyDBCapabilityService()
