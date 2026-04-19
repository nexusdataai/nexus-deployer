"""
Landing Zone Manager

Manages landing zone configurations in TinyDB for capability discovery.
A landing zone represents a cloud account (AWS, Azure, GCP) where capabilities
can be discovered and managed.
"""

import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict

from tinydb import Query

from app.services.tinydb_state_manager import TinyDBStateManager, get_state_manager
from .models import LandingZone, CloudProvider

logger = logging.getLogger(__name__)


class LandingZoneManager:
    """Manages landing zone configurations in TinyDB."""
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """
        Initialize landing zone manager.
        
        Args:
            db_manager: TinyDB state manager (uses global instance if None)
        """
        self.db_manager = db_manager or get_state_manager()
        self.landing_zones_table = self.db_manager.get_table("landing_zones")
        logger.info("LandingZoneManager initialized")
    
    def create_landing_zone(
        self,
        name: str,
        provider: CloudProvider,
        account_id: str,
        default_region: str,
        account_alias: Optional[str] = None,
    ) -> str:
        """
        Create a new landing zone or update existing one.
        
        If a landing zone with the same provider and account_id exists,
        it will be updated instead of creating a duplicate.
        
        Args:
            name: User-friendly name for the landing zone
            provider: Cloud provider (aws, azure, gcp)
            account_id: Cloud account identifier
            default_region: Default region for discovery
            account_alias: Optional account alias
            
        Returns:
            Landing zone ID (UUID)
        """
        LZQuery = Query()
        
        # Check for existing landing zone with same provider and account
        provider_value = provider.value if isinstance(provider, CloudProvider) else provider
        existing = self.landing_zones_table.get(
            (LZQuery.provider == provider_value) & 
            (LZQuery.account_id == account_id)
        )
        
        if existing:
            # Update existing landing zone
            landing_zone_id = existing["landing_zone_id"]
            self.landing_zones_table.update(
                {
                    "name": name,
                    "default_region": default_region,
                    "account_alias": account_alias,
                },
                LZQuery.landing_zone_id == landing_zone_id
            )
            logger.info(f"Updated existing landing zone {landing_zone_id} for {provider_value} account {account_id}")
            return landing_zone_id

        # Create new landing zone
        landing_zone_id = str(uuid.uuid4())
        
        landing_zone = LandingZone(
            landing_zone_id=landing_zone_id,
            name=name,
            provider=provider if isinstance(provider, CloudProvider) else CloudProvider(provider),
            account_id=account_id,
            account_alias=account_alias,
            default_region=default_region,
            created_at=datetime.utcnow(),
            last_discovery_at=None,
            discovery_status="idle",
            capabilities_count=0,
        )
        
        self.landing_zones_table.insert(landing_zone.to_dict())
        logger.info(f"Created landing zone {landing_zone_id} for {provider_value} account {account_id}")
        
        return landing_zone_id
    
    def get_landing_zone(self, landing_zone_id: str) -> Optional[Dict]:
        """
        Get landing zone by ID.
        
        Args:
            landing_zone_id: Unique landing zone identifier
            
        Returns:
            Landing zone dict or None if not found
        """
        LZQuery = Query()
        return self.landing_zones_table.get(LZQuery.landing_zone_id == landing_zone_id)
    
    def get_landing_zone_by_account(
        self,
        provider: CloudProvider,
        account_id: str
    ) -> Optional[Dict]:
        """
        Get landing zone by provider and account ID.
        
        Args:
            provider: Cloud provider
            account_id: Cloud account identifier
            
        Returns:
            Landing zone dict or None if not found
        """
        LZQuery = Query()
        provider_value = provider.value if isinstance(provider, CloudProvider) else provider
        return self.landing_zones_table.get(
            (LZQuery.provider == provider_value) & 
            (LZQuery.account_id == account_id)
        )
    
    def list_landing_zones(self, provider: Optional[CloudProvider] = None) -> List[Dict]:
        """
        List all landing zones, optionally filtered by provider.
        
        Args:
            provider: Optional cloud provider filter
            
        Returns:
            List of landing zone dicts
        """
        if provider:
            LZQuery = Query()
            provider_value = provider.value if isinstance(provider, CloudProvider) else provider
            return self.landing_zones_table.search(LZQuery.provider == provider_value)
        return self.landing_zones_table.all()
    
    def delete_landing_zone(self, landing_zone_id: str) -> bool:
        """
        Delete a landing zone configuration.
        
        Note: This does not delete discovered capability records,
        only the landing zone configuration itself.
        
        Args:
            landing_zone_id: Unique landing zone identifier
            
        Returns:
            True if deleted, False if not found
        """
        LZQuery = Query()
        removed = self.landing_zones_table.remove(LZQuery.landing_zone_id == landing_zone_id)
        
        if removed:
            logger.info(f"Deleted landing zone {landing_zone_id}")
            return True
        
        logger.warning(f"Landing zone {landing_zone_id} not found for deletion")
        return False
    
    def update_discovery_status(
        self,
        landing_zone_id: str,
        status: str,
        capabilities_count: Optional[int] = None,
    ) -> bool:
        """
        Update discovery status for a landing zone.
        
        Args:
            landing_zone_id: Unique landing zone identifier
            status: New status (idle, running, completed, failed)
            capabilities_count: Optional count of discovered capabilities
            
        Returns:
            True if updated successfully
        """
        LZQuery = Query()
        updates = {"discovery_status": status}
        
        if status == "completed":
            updates["last_discovery_at"] = datetime.utcnow().isoformat()
        
        if capabilities_count is not None:
            updates["capabilities_count"] = capabilities_count
        
        result = self.landing_zones_table.update(
            updates,
            LZQuery.landing_zone_id == landing_zone_id
        )
        
        if result:
            logger.debug(f"Updated landing zone {landing_zone_id} status to {status}")
            return True
        
        logger.warning(f"Landing zone {landing_zone_id} not found for status update")
        return False
    
    def update_landing_zone(
        self,
        landing_zone_id: str,
        **kwargs
    ) -> bool:
        """
        Update landing zone fields.
        
        Args:
            landing_zone_id: Unique landing zone identifier
            **kwargs: Fields to update
            
        Returns:
            True if updated successfully
        """
        LZQuery = Query()
        result = self.landing_zones_table.update(
            kwargs,
            LZQuery.landing_zone_id == landing_zone_id
        )
        return len(result) > 0


# Global instance
_landing_zone_manager: Optional[LandingZoneManager] = None


def get_landing_zone_manager() -> LandingZoneManager:
    """Get global LandingZoneManager instance."""
    global _landing_zone_manager
    if _landing_zone_manager is None:
        _landing_zone_manager = LandingZoneManager()
    return _landing_zone_manager


def set_landing_zone_manager(manager: Optional[LandingZoneManager]):
    """Set global LandingZoneManager instance (for testing)."""
    global _landing_zone_manager
    _landing_zone_manager = manager
