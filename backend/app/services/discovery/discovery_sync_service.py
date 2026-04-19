"""
Discovery Sync Service

Synchronizes discovered capabilities with TinyDB installations table.
Creates, updates, or marks capabilities based on discovery results.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Set, Tuple

from tinydb import Query

from app.services.installation_tracker import InstallationTracker, get_installation_tracker
from .models import DiscoveredCapability, CapabilityStatus

logger = logging.getLogger(__name__)


class DiscoverySyncService:
    """Synchronizes discovered capabilities with TinyDB installations table."""
    
    def __init__(self, installation_tracker: Optional[InstallationTracker] = None):
        """
        Initialize sync service.
        
        Args:
            installation_tracker: Installation tracker instance (uses global if None)
        """
        self.tracker = installation_tracker or get_installation_tracker()
    
    def sync_discovered_capabilities(
        self,
        capabilities: List[DiscoveredCapability],
        landing_zone_id: str,
    ) -> Dict[str, int]:
        """
        Sync discovered capabilities to TinyDB.
        
        - Creates new installation records for newly discovered capabilities
        - Updates existing records with current status
        - Marks capabilities that exist in TinyDB but not in AWS as "not_found_in_aws"
        
        Args:
            capabilities: List of discovered capabilities
            landing_zone_id: Landing zone identifier
            
        Returns:
            Dict with counts: created, updated, marked_not_found
        """
        stats = {"created": 0, "updated": 0, "marked_not_found": 0}
        
        # Get existing discovered installations for this landing zone
        existing = self._get_existing_installations(landing_zone_id)
        existing_keys: Set[Tuple[str, str, str]] = {
            (i["capability_name"], i["environment"], i["account_id"])
            for i in existing
        }
        
        discovered_keys: Set[Tuple[str, str, str]] = set()
        
        for capability in capabilities:
            key = (capability.capability_name, capability.environment, capability.account_id)
            discovered_keys.add(key)
            
            if key in existing_keys:
                # Update existing installation
                self._update_installation(capability)
                stats["updated"] += 1
                logger.debug(f"Updated installation: {capability.capability_name}/{capability.environment}")
            else:
                # Create new installation record
                self._create_installation(capability, landing_zone_id)
                stats["created"] += 1
                logger.info(f"Created installation: {capability.capability_name}/{capability.environment}")
        
        # Mark installations not found in AWS
        for key in existing_keys - discovered_keys:
            capability_name, environment, account_id = key
            self._mark_not_found(capability_name, environment, account_id, landing_zone_id)
            stats["marked_not_found"] += 1
            logger.info(f"Marked not found: {capability_name}/{environment}")
        
        logger.info(f"Sync complete: created={stats['created']}, updated={stats['updated']}, marked_not_found={stats['marked_not_found']}")
        return stats

    def _get_existing_installations(self, landing_zone_id: str) -> List[Dict]:
        """
        Get existing discovered installations for a landing zone.
        
        Args:
            landing_zone_id: Landing zone identifier
            
        Returns:
            List of installation records
        """
        InstallQuery = Query()
        return self.tracker.installations_table.search(
            (InstallQuery.strategy == "DISCOVERED") &
            (InstallQuery.landing_zone_id == landing_zone_id)
        )
    
    def _create_installation(self, capability: DiscoveredCapability, landing_zone_id: str):
        """
        Create installation record from discovered capability.
        
        Args:
            capability: Discovered capability
            landing_zone_id: Landing zone identifier
        """
        # Map capability status to installation status
        status_map = {
            CapabilityStatus.HEALTHY: "completed",
            CapabilityStatus.FAILED: "failed",
            CapabilityStatus.IN_PROGRESS: "running",
            CapabilityStatus.PARTIAL: "partial",
            CapabilityStatus.NOT_FOUND: "not_found",
        }
        
        # Generate unique installation ID
        installation_id = f"discovered-{capability.capability_name}-{capability.environment}-{capability.account_id}"
        
        # Determine what's deployed
        has_frontend = any(s.stack_type.startswith("frontend") for s in capability.stacks)
        has_backend = any(s.stack_type.startswith("backend") for s in capability.stacks)
        
        # Build stacks summary
        stacks_summary = {
            "total": len(capability.stacks),
            "healthy": sum(1 for s in capability.stacks if "COMPLETE" in s.stack_status and "ROLLBACK" not in s.stack_status),
            "failed": sum(1 for s in capability.stacks if "FAILED" in s.stack_status or "ROLLBACK" in s.stack_status),
            "in_progress": sum(1 for s in capability.stacks if "IN_PROGRESS" in s.stack_status),
            "missing": len(capability.missing_stacks),
        }
        
        # Build stacks detail for reference
        stacks_detail = [
            {
                "stack_name": s.stack_name,
                "stack_type": s.stack_type,
                "status": s.stack_status,
                "region": s.region,
            }
            for s in capability.stacks
        ]
        
        record = {
            "installation_id": installation_id,
            "capability_name": capability.capability_name,
            "capability_version": capability.version or "unknown",
            "environment": capability.environment,
            "region": capability.primary_region,
            "account_id": capability.account_id,
            "strategy": "DISCOVERED",
            "deploy_frontend": has_frontend,
            "deploy_backend": has_backend,
            "status": status_map.get(capability.status, "unknown"),
            "started_at": capability.discovered_at.isoformat() if isinstance(capability.discovered_at, datetime) else capability.discovered_at,
            "completed_at": capability.discovered_at.isoformat() if isinstance(capability.discovered_at, datetime) else capability.discovered_at,
            "frontend_url": capability.frontend_url,
            "backend_url": capability.backend_url,
            "landing_zone_id": landing_zone_id,
            "discovered_at": capability.discovered_at.isoformat() if isinstance(capability.discovered_at, datetime) else capability.discovered_at,
            "stacks_summary": stacks_summary,
            "stacks_detail": stacks_detail,
            "missing_stacks": capability.missing_stacks,
        }
        
        self.tracker.installations_table.insert(record)
    
    def _update_installation(self, capability: DiscoveredCapability):
        """
        Update existing installation record with current discovery data.
        
        Args:
            capability: Discovered capability
        """
        InstallQuery = Query()
        
        # Map capability status to installation status
        status_map = {
            CapabilityStatus.HEALTHY: "completed",
            CapabilityStatus.FAILED: "failed",
            CapabilityStatus.IN_PROGRESS: "running",
            CapabilityStatus.PARTIAL: "partial",
            CapabilityStatus.NOT_FOUND: "not_found",
        }
        
        # Build stacks summary
        stacks_summary = {
            "total": len(capability.stacks),
            "healthy": sum(1 for s in capability.stacks if "COMPLETE" in s.stack_status and "ROLLBACK" not in s.stack_status),
            "failed": sum(1 for s in capability.stacks if "FAILED" in s.stack_status or "ROLLBACK" in s.stack_status),
            "in_progress": sum(1 for s in capability.stacks if "IN_PROGRESS" in s.stack_status),
            "missing": len(capability.missing_stacks),
        }
        
        # Build stacks detail
        stacks_detail = [
            {
                "stack_name": s.stack_name,
                "stack_type": s.stack_type,
                "status": s.stack_status,
                "region": s.region,
            }
            for s in capability.stacks
        ]
        
        discovered_at = capability.discovered_at.isoformat() if isinstance(capability.discovered_at, datetime) else capability.discovered_at
        
        updates = {
            "status": status_map.get(capability.status, "unknown"),
            "frontend_url": capability.frontend_url,
            "backend_url": capability.backend_url,
            "discovered_at": discovered_at,
            "capability_version": capability.version or "unknown",
            "stacks_summary": stacks_summary,
            "stacks_detail": stacks_detail,
            "missing_stacks": capability.missing_stacks,
            "region": capability.primary_region,
        }
        
        self.tracker.installations_table.update(
            updates,
            (InstallQuery.capability_name == capability.capability_name) &
            (InstallQuery.environment == capability.environment) &
            (InstallQuery.account_id == capability.account_id) &
            (InstallQuery.strategy == "DISCOVERED")
        )
    
    def _mark_not_found(
        self,
        capability_name: str,
        environment: str,
        account_id: str,
        landing_zone_id: str
    ):
        """
        Mark installation as not found in AWS.
        
        This preserves the record but updates its status to indicate
        the capability was not found during the latest discovery.
        
        Args:
            capability_name: Capability name
            environment: Environment
            account_id: AWS account ID
            landing_zone_id: Landing zone identifier
        """
        InstallQuery = Query()
        
        self.tracker.installations_table.update(
            {
                "status": "not_found_in_aws",
                "discovered_at": datetime.utcnow().isoformat(),
            },
            (InstallQuery.capability_name == capability_name) &
            (InstallQuery.environment == environment) &
            (InstallQuery.account_id == account_id) &
            (InstallQuery.strategy == "DISCOVERED") &
            (InstallQuery.landing_zone_id == landing_zone_id)
        )
    
    def get_discovered_capabilities(
        self,
        landing_zone_id: Optional[str] = None,
        account_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get discovered capabilities from TinyDB.
        
        Args:
            landing_zone_id: Optional filter by landing zone
            account_id: Optional filter by account ID
            
        Returns:
            List of installation records for discovered capabilities
        """
        InstallQuery = Query()
        
        conditions = [InstallQuery.strategy == "DISCOVERED"]
        
        if landing_zone_id:
            conditions.append(InstallQuery.landing_zone_id == landing_zone_id)
        
        if account_id:
            conditions.append(InstallQuery.account_id == account_id)
        
        # Combine conditions
        query = conditions[0]
        for condition in conditions[1:]:
            query = query & condition
        
        return self.tracker.installations_table.search(query)
    
    def delete_discovered_capabilities(self, landing_zone_id: str) -> int:
        """
        Delete all discovered capabilities for a landing zone.
        
        Args:
            landing_zone_id: Landing zone identifier
            
        Returns:
            Number of records deleted
        """
        InstallQuery = Query()
        
        removed = self.tracker.installations_table.remove(
            (InstallQuery.strategy == "DISCOVERED") &
            (InstallQuery.landing_zone_id == landing_zone_id)
        )
        
        return len(removed)
