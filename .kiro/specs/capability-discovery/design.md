# Design Document: Capability Discovery

## Overview

The Capability Discovery feature enables users to discover capabilities deployed in AWS accounts by scanning CloudFormation stacks. This solves the problem of fragmented visibility when multiple users deploy capabilities using separate local TinyDB instances.

The solution introduces a new `DiscoveryService` that scans CloudFormation stacks, parses stack names using the established naming convention `{capability-name}-{environment}-{stack-type}`, groups stacks into capabilities, and synchronizes the results with the local TinyDB database.

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (React)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────────────────┐ │
│  │ LandingZone     │  │ DiscoveryPanel   │  │ CapabilitySelection         │ │
│  │ Selector        │  │ Component        │  │ (Enhanced)                  │ │
│  └────────┬────────┘  └────────┬─────────┘  └──────────────┬──────────────┘ │
│           │                    │                           │                 │
│           └────────────────────┼───────────────────────────┘                 │
│                                │                                             │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │ REST API
┌────────────────────────────────┼─────────────────────────────────────────────┐
│                                │           Backend (FastAPI)                 │
├────────────────────────────────┼─────────────────────────────────────────────┤
│                                ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                      Discovery Router (/api/discovery)                  │ │
│  │  POST /landing-zones          - Create/update landing zone              │ │
│  │  GET  /landing-zones          - List all landing zones                  │ │
│  │  DELETE /landing-zones/{id}   - Remove landing zone                     │ │
│  │  POST /discover               - Start discovery for landing zone        │ │
│  │  GET  /discover/{id}/status   - Get discovery job status                │ │
│  │  POST /refresh                - Refresh capabilities for landing zone   │ │
│  └────────────────────────────────┬────────────────────────────────────────┘ │
│                                   │                                          │
│  ┌────────────────────────────────▼────────────────────────────────────────┐ │
│  │                         DiscoveryService                                │ │
│  │  - scan_cloudformation_stacks()                                         │ │
│  │  - parse_stack_name()                                                   │ │
│  │  - group_stacks_by_capability()                                         │ │
│  │  - determine_capability_status()                                        │ │
│  │  - sync_to_tinydb()                                                     │ │
│  └────────────────────────────────┬────────────────────────────────────────┘ │
│                                   │                                          │
│  ┌────────────────────────────────▼────────────────────────────────────────┐ │
│  │                      LandingZoneManager                                 │ │
│  │  - create_landing_zone()                                                │ │
│  │  - list_landing_zones()                                                 │ │
│  │  - delete_landing_zone()                                                │ │
│  │  - update_discovery_timestamp()                                         │ │
│  └────────────────────────────────┬────────────────────────────────────────┘ │
│                                   │                                          │
│  ┌────────────────────────────────▼────────────────────────────────────────┐ │
│  │                    TinyDB (State Storage)                               │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  │ │
│  │  │ landing_zones   │  │ installations   │  │ discovered_stacks       │  │ │
│  │  │ table           │  │ table           │  │ table                   │  │ │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    AWS Session Manager                                  │ │
│  │  - Manages AWS credentials for discovery operations                     │ │
│  │  - Reuses existing ADFS/SAML authentication flow                        │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              AWS Account                                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    CloudFormation Service                               │ │
│  │  - ListStacks API                                                       │ │
│  │  - DescribeStacks API                                                   │ │
│  │  - Stack naming: {capability}-{env}-{stack-type}                        │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```


## Data Models

### LandingZone Model

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum

class CloudProvider(str, Enum):
    AWS = "aws"
    AZURE = "azure"  # Future
    GCP = "gcp"      # Future

@dataclass
class LandingZone:
    """Represents a cloud account configured for capability discovery."""
    landing_zone_id: str           # UUID
    name: str                      # User-friendly name (e.g., "Production Account")
    provider: CloudProvider        # aws, azure, gcp
    account_id: str                # AWS Account ID
    account_alias: Optional[str]   # AWS Account Alias if available
    default_region: str            # Primary region for discovery
    created_at: datetime
    last_discovery_at: Optional[datetime]
    discovery_status: str          # idle, running, completed, failed
    capabilities_count: int        # Number of discovered capabilities
    
    def to_dict(self) -> dict:
        return {
            "landing_zone_id": self.landing_zone_id,
            "name": self.name,
            "provider": self.provider.value,
            "account_id": self.account_id,
            "account_alias": self.account_alias,
            "default_region": self.default_region,
            "created_at": self.created_at.isoformat(),
            "last_discovery_at": self.last_discovery_at.isoformat() if self.last_discovery_at else None,
            "discovery_status": self.discovery_status,
            "capabilities_count": self.capabilities_count,
        }
```

### DiscoveredCapability Model

```python
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum

class CapabilityStatus(str, Enum):
    HEALTHY = "healthy"           # All stacks CREATE_COMPLETE or UPDATE_COMPLETE
    FAILED = "failed"             # Any stack in FAILED or ROLLBACK state
    IN_PROGRESS = "in_progress"   # Any stack in IN_PROGRESS state
    PARTIAL = "partial"           # Some expected stacks missing
    NOT_FOUND = "not_found"       # Exists in TinyDB but not in AWS

@dataclass
class DiscoveredStack:
    """Individual CloudFormation stack discovered."""
    stack_name: str
    stack_type: str               # backend-foundation, frontend-global, etc.
    stack_status: str             # CloudFormation status
    region: str
    created_time: datetime
    last_updated_time: Optional[datetime]
    outputs: Dict[str, str]       # Stack outputs

@dataclass
class DiscoveredCapability:
    """A capability discovered from CloudFormation stacks."""
    capability_name: str
    environment: str              # dev, test, stage, prod
    landing_zone_id: str          # Reference to landing zone
    account_id: str
    primary_region: str
    status: CapabilityStatus
    stacks: List[DiscoveredStack]
    missing_stacks: List[str]     # Stack types that are expected but missing
    discovered_at: datetime
    version: Optional[str]        # Extracted from stack tags if available
    frontend_url: Optional[str]   # From stack outputs
    backend_url: Optional[str]    # From stack outputs
    
    def to_dict(self) -> dict:
        return {
            "capability_name": self.capability_name,
            "environment": self.environment,
            "landing_zone_id": self.landing_zone_id,
            "account_id": self.account_id,
            "primary_region": self.primary_region,
            "status": self.status.value,
            "stacks": [self._stack_to_dict(s) for s in self.stacks],
            "missing_stacks": self.missing_stacks,
            "discovered_at": self.discovered_at.isoformat(),
            "version": self.version,
            "frontend_url": self.frontend_url,
            "backend_url": self.backend_url,
        }
    
    def _stack_to_dict(self, stack: DiscoveredStack) -> dict:
        return {
            "stack_name": stack.stack_name,
            "stack_type": stack.stack_type,
            "stack_status": stack.stack_status,
            "region": stack.region,
            "created_time": stack.created_time.isoformat(),
            "last_updated_time": stack.last_updated_time.isoformat() if stack.last_updated_time else None,
            "outputs": stack.outputs,
        }
```


### DiscoveryJob Model

```python
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from enum import Enum

class DiscoveryJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class DiscoveryJob:
    """Tracks a discovery operation."""
    job_id: str
    landing_zone_id: str
    status: DiscoveryJobStatus
    started_at: datetime
    completed_at: Optional[datetime]
    stacks_scanned: int
    capabilities_found: int
    errors: List[str]
    progress_message: str
```

## Service Implementations

### DiscoveryService

```python
"""
Discovery Service for scanning CloudFormation stacks and identifying capabilities.
"""
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import boto3
from botocore.exceptions import ClientError

from .models import (
    DiscoveredCapability,
    DiscoveredStack,
    CapabilityStatus,
    DiscoveryJob,
    DiscoveryJobStatus,
)

logger = logging.getLogger(__name__)

# Known stack types from CloudFormationDeploymentService.STACK_ORDER
KNOWN_STACK_TYPES = [
    "backend-foundation",
    "backend-iam-roles",
    "backend-regional-cert",
    "backend-storage",
    "backend-network",
    "backend-service",
    "backend-domain",
    "frontend-global",
    "frontend-cognito",
    "frontend-regional",
]

# Stack types for frontend-only deployment
FRONTEND_STACK_TYPES = ["frontend-global", "frontend-cognito", "frontend-regional"]

# Stack types for backend-only deployment
BACKEND_STACK_TYPES = [
    "backend-foundation",
    "backend-iam-roles",
    "backend-regional-cert",
    "backend-storage",
    "backend-network",
    "backend-service",
    "backend-domain",
]

# Valid environments
VALID_ENVIRONMENTS = ["dev", "test", "stage", "prod"]


class DiscoveryService:
    """Service for discovering capabilities from CloudFormation stacks."""
    
    def __init__(
        self,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize discovery service.
        
        Args:
            region: AWS region to scan
            credentials: Optional AWS credentials dict
        """
        self.region = region
        self.credentials = credentials or {}
        self._cfn_client = None
    
    @property
    def cfn_client(self):
        """Lazy-load CloudFormation client."""
        if self._cfn_client is None:
            self._cfn_client = boto3.client(
                "cloudformation",
                region_name=self.region,
                **self.credentials
            )
        return self._cfn_client
    
    def discover_capabilities(
        self,
        landing_zone_id: str,
        account_id: str,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[List[DiscoveredCapability], List[str]]:
        """
        Discover all capabilities in the AWS account.
        
        Args:
            landing_zone_id: Landing zone identifier
            account_id: AWS account ID
            progress_callback: Optional callback for progress updates
            
        Returns:
            Tuple of (discovered_capabilities, errors)
        """
        errors = []
        all_stacks = []
        
        if progress_callback:
            progress_callback("Scanning CloudFormation stacks...")
        
        try:
            # List all stacks (excluding deleted)
            paginator = self.cfn_client.get_paginator("list_stacks")
            
            for page in paginator.paginate(
                StackStatusFilter=[
                    "CREATE_COMPLETE",
                    "CREATE_IN_PROGRESS",
                    "CREATE_FAILED",
                    "UPDATE_COMPLETE",
                    "UPDATE_IN_PROGRESS",
                    "UPDATE_FAILED",
                    "UPDATE_ROLLBACK_COMPLETE",
                    "UPDATE_ROLLBACK_IN_PROGRESS",
                    "UPDATE_ROLLBACK_FAILED",
                    "ROLLBACK_COMPLETE",
                    "ROLLBACK_IN_PROGRESS",
                    "ROLLBACK_FAILED",
                ]
            ):
                for stack_summary in page.get("StackSummaries", []):
                    stack_name = stack_summary["StackName"]
                    
                    # Try to parse as capability stack
                    parsed = self.parse_stack_name(stack_name)
                    if parsed:
                        capability_name, environment, stack_type = parsed
                        
                        # Get full stack details
                        try:
                            stack_details = self._get_stack_details(stack_name)
                            if stack_details:
                                all_stacks.append({
                                    "capability_name": capability_name,
                                    "environment": environment,
                                    "stack_type": stack_type,
                                    "stack_details": stack_details,
                                })
                        except ClientError as e:
                            errors.append(f"Error getting details for {stack_name}: {str(e)}")
            
            if progress_callback:
                progress_callback(f"Found {len(all_stacks)} capability stacks")
            
            # Group stacks by capability
            capabilities = self._group_stacks_into_capabilities(
                all_stacks, landing_zone_id, account_id
            )
            
            if progress_callback:
                progress_callback(f"Discovered {len(capabilities)} capabilities")
            
            return capabilities, errors
            
        except ClientError as e:
            error_msg = f"CloudFormation API error: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
            return [], errors
    
    def parse_stack_name(self, stack_name: str) -> Optional[Tuple[str, str, str]]:
        """
        Parse stack name to extract capability, environment, and stack type.
        
        Stack naming convention: {capability-name}-{environment}-{stack-type}
        Example: Call-Processing-prod-backend-service
        
        Args:
            stack_name: CloudFormation stack name
            
        Returns:
            Tuple of (capability_name, environment, stack_type) or None if not matching
        """
        # Try each known stack type (longest first to avoid partial matches)
        sorted_types = sorted(KNOWN_STACK_TYPES, key=len, reverse=True)
        
        for stack_type in sorted_types:
            suffix = f"-{stack_type}"
            if stack_name.endswith(suffix):
                # Remove the stack type suffix
                prefix = stack_name[:-len(suffix)]
                
                # Now extract environment from the end of prefix
                for env in VALID_ENVIRONMENTS:
                    env_suffix = f"-{env}"
                    if prefix.endswith(env_suffix):
                        capability_name = prefix[:-len(env_suffix)]
                        if capability_name:  # Ensure we have a capability name
                            return (capability_name, env, stack_type)
        
        return None
    
    def _get_stack_details(self, stack_name: str) -> Optional[Dict]:
        """Get detailed information about a stack."""
        try:
            response = self.cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get("Stacks", [])
            if stacks:
                stack = stacks[0]
                return {
                    "stack_name": stack["StackName"],
                    "stack_status": stack["StackStatus"],
                    "created_time": stack.get("CreationTime"),
                    "last_updated_time": stack.get("LastUpdatedTime"),
                    "outputs": {
                        o["OutputKey"]: o["OutputValue"]
                        for o in stack.get("Outputs", [])
                    },
                    "tags": {
                        t["Key"]: t["Value"]
                        for t in stack.get("Tags", [])
                    },
                }
            return None
        except ClientError:
            return None
    
    def _group_stacks_into_capabilities(
        self,
        stacks: List[Dict],
        landing_zone_id: str,
        account_id: str,
    ) -> List[DiscoveredCapability]:
        """Group discovered stacks into capabilities."""
        # Group by (capability_name, environment)
        grouped: Dict[Tuple[str, str], List[Dict]] = {}
        
        for stack_info in stacks:
            key = (stack_info["capability_name"], stack_info["environment"])
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(stack_info)
        
        # Convert to DiscoveredCapability objects
        capabilities = []
        
        for (capability_name, environment), stack_list in grouped.items():
            # Build DiscoveredStack objects
            discovered_stacks = []
            stack_types_found = set()
            
            for stack_info in stack_list:
                details = stack_info["stack_details"]
                stack_types_found.add(stack_info["stack_type"])
                
                discovered_stacks.append(DiscoveredStack(
                    stack_name=details["stack_name"],
                    stack_type=stack_info["stack_type"],
                    stack_status=details["stack_status"],
                    region=self.region,
                    created_time=details["created_time"],
                    last_updated_time=details.get("last_updated_time"),
                    outputs=details.get("outputs", {}),
                ))
            
            # Determine status and missing stacks
            status, missing = self._determine_capability_status(
                discovered_stacks, stack_types_found
            )
            
            # Extract URLs from outputs
            frontend_url = None
            backend_url = None
            version = None
            
            for stack in discovered_stacks:
                if "CloudFrontURL" in stack.outputs:
                    frontend_url = stack.outputs["CloudFrontURL"]
                if "FrontendURL" in stack.outputs:
                    frontend_url = stack.outputs["FrontendURL"]
                if "BackendURL" in stack.outputs:
                    backend_url = stack.outputs["BackendURL"]
                if "ALBDNSName" in stack.outputs:
                    backend_url = stack.outputs["ALBDNSName"]
            
            # Try to get version from tags
            for stack_info in stack_list:
                tags = stack_info["stack_details"].get("tags", {})
                if "Version" in tags:
                    version = tags["Version"]
                    break
            
            capabilities.append(DiscoveredCapability(
                capability_name=capability_name,
                environment=environment,
                landing_zone_id=landing_zone_id,
                account_id=account_id,
                primary_region=self.region,
                status=status,
                stacks=discovered_stacks,
                missing_stacks=missing,
                discovered_at=datetime.utcnow(),
                version=version,
                frontend_url=frontend_url,
                backend_url=backend_url,
            ))
        
        return capabilities
    
    def _determine_capability_status(
        self,
        stacks: List[DiscoveredStack],
        stack_types_found: set,
    ) -> Tuple[CapabilityStatus, List[str]]:
        """
        Determine overall capability status from stack statuses.
        
        Returns:
            Tuple of (status, missing_stack_types)
        """
        # Check for failures first
        for stack in stacks:
            if "FAILED" in stack.stack_status or "ROLLBACK" in stack.stack_status:
                return CapabilityStatus.FAILED, []
        
        # Check for in-progress
        for stack in stacks:
            if "IN_PROGRESS" in stack.stack_status:
                return CapabilityStatus.IN_PROGRESS, []
        
        # Determine expected stacks based on what's deployed
        has_frontend = any(st in stack_types_found for st in FRONTEND_STACK_TYPES)
        has_backend = any(st in stack_types_found for st in BACKEND_STACK_TYPES)
        
        expected_types = set()
        if has_frontend:
            expected_types.update(FRONTEND_STACK_TYPES)
        if has_backend:
            expected_types.update(BACKEND_STACK_TYPES)
        
        # Check for missing stacks
        missing = list(expected_types - stack_types_found)
        
        if missing:
            return CapabilityStatus.PARTIAL, missing
        
        return CapabilityStatus.HEALTHY, []
```


### LandingZoneManager

```python
"""
Landing Zone Manager for managing AWS account configurations.
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
        """Initialize landing zone manager."""
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
        Create a new landing zone.
        
        Args:
            name: User-friendly name
            provider: Cloud provider (aws, azure, gcp)
            account_id: Cloud account identifier
            default_region: Default region for discovery
            account_alias: Optional account alias
            
        Returns:
            Landing zone ID
        """
        # Check for existing landing zone with same account
        LZQuery = Query()
        existing = self.landing_zones_table.get(
            (LZQuery.provider == provider.value) & 
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
            logger.info(f"Updated existing landing zone {landing_zone_id}")
            return landing_zone_id
        
        # Create new landing zone
        landing_zone_id = str(uuid.uuid4())
        
        landing_zone = LandingZone(
            landing_zone_id=landing_zone_id,
            name=name,
            provider=provider,
            account_id=account_id,
            account_alias=account_alias,
            default_region=default_region,
            created_at=datetime.utcnow(),
            last_discovery_at=None,
            discovery_status="idle",
            capabilities_count=0,
        )
        
        self.landing_zones_table.insert(landing_zone.to_dict())
        logger.info(f"Created landing zone {landing_zone_id} for {provider.value} account {account_id}")
        
        return landing_zone_id
    
    def get_landing_zone(self, landing_zone_id: str) -> Optional[Dict]:
        """Get landing zone by ID."""
        LZQuery = Query()
        return self.landing_zones_table.get(LZQuery.landing_zone_id == landing_zone_id)
    
    def list_landing_zones(self, provider: Optional[CloudProvider] = None) -> List[Dict]:
        """List all landing zones, optionally filtered by provider."""
        if provider:
            LZQuery = Query()
            return self.landing_zones_table.search(LZQuery.provider == provider.value)
        return self.landing_zones_table.all()
    
    def delete_landing_zone(self, landing_zone_id: str) -> bool:
        """Delete a landing zone."""
        LZQuery = Query()
        removed = self.landing_zones_table.remove(LZQuery.landing_zone_id == landing_zone_id)
        return len(removed) > 0
    
    def update_discovery_status(
        self,
        landing_zone_id: str,
        status: str,
        capabilities_count: Optional[int] = None,
    ):
        """Update discovery status for a landing zone."""
        LZQuery = Query()
        updates = {"discovery_status": status}
        
        if status == "completed":
            updates["last_discovery_at"] = datetime.utcnow().isoformat()
        
        if capabilities_count is not None:
            updates["capabilities_count"] = capabilities_count
        
        self.landing_zones_table.update(updates, LZQuery.landing_zone_id == landing_zone_id)
```

### DiscoverySyncService

```python
"""
Discovery Sync Service for synchronizing discovered capabilities with TinyDB.
"""
import logging
from datetime import datetime
from typing import List, Optional, Dict
from tinydb import Query

from app.services.installation_tracker import InstallationTracker, get_installation_tracker
from .models import DiscoveredCapability, CapabilityStatus

logger = logging.getLogger(__name__)


class DiscoverySyncService:
    """Synchronizes discovered capabilities with TinyDB installations table."""
    
    def __init__(self, installation_tracker: Optional[InstallationTracker] = None):
        """Initialize sync service."""
        self.tracker = installation_tracker or get_installation_tracker()
    
    def sync_discovered_capabilities(
        self,
        capabilities: List[DiscoveredCapability],
        landing_zone_id: str,
    ) -> Dict[str, int]:
        """
        Sync discovered capabilities to TinyDB.
        
        Args:
            capabilities: List of discovered capabilities
            landing_zone_id: Landing zone identifier
            
        Returns:
            Dict with counts: created, updated, marked_not_found
        """
        stats = {"created": 0, "updated": 0, "marked_not_found": 0}
        
        # Get existing installations for this landing zone
        existing = self._get_existing_installations(landing_zone_id)
        existing_keys = {
            (i["capability_name"], i["environment"], i["account_id"])
            for i in existing
        }
        
        discovered_keys = set()
        
        for capability in capabilities:
            key = (capability.capability_name, capability.environment, capability.account_id)
            discovered_keys.add(key)
            
            if key in existing_keys:
                # Update existing
                self._update_installation(capability)
                stats["updated"] += 1
            else:
                # Create new
                self._create_installation(capability, landing_zone_id)
                stats["created"] += 1
        
        # Mark installations not found in AWS
        for key in existing_keys - discovered_keys:
            capability_name, environment, account_id = key
            self._mark_not_found(capability_name, environment, account_id)
            stats["marked_not_found"] += 1
        
        logger.info(f"Sync complete: {stats}")
        return stats
    
    def _get_existing_installations(self, landing_zone_id: str) -> List[Dict]:
        """Get existing installations for a landing zone."""
        InstallQuery = Query()
        return self.tracker.installations_table.search(
            (InstallQuery.strategy == "DISCOVERED") &
            (InstallQuery.landing_zone_id == landing_zone_id)
        )
    
    def _create_installation(self, capability: DiscoveredCapability, landing_zone_id: str):
        """Create installation record from discovered capability."""
        # Map capability status to installation status
        status_map = {
            CapabilityStatus.HEALTHY: "completed",
            CapabilityStatus.FAILED: "failed",
            CapabilityStatus.IN_PROGRESS: "running",
            CapabilityStatus.PARTIAL: "partial",
            CapabilityStatus.NOT_FOUND: "not_found",
        }
        
        record = {
            "installation_id": f"discovered-{capability.capability_name}-{capability.environment}-{capability.account_id}",
            "capability_name": capability.capability_name,
            "capability_version": capability.version or "unknown",
            "environment": capability.environment,
            "region": capability.primary_region,
            "account_id": capability.account_id,
            "strategy": "DISCOVERED",
            "deploy_frontend": any(s.stack_type.startswith("frontend") for s in capability.stacks),
            "deploy_backend": any(s.stack_type.startswith("backend") for s in capability.stacks),
            "status": status_map.get(capability.status, "unknown"),
            "started_at": capability.discovered_at.isoformat(),
            "completed_at": capability.discovered_at.isoformat(),
            "frontend_url": capability.frontend_url,
            "backend_url": capability.backend_url,
            "landing_zone_id": landing_zone_id,
            "discovered_at": capability.discovered_at.isoformat(),
            "stacks_summary": {
                "total": len(capability.stacks),
                "healthy": sum(1 for s in capability.stacks if "COMPLETE" in s.stack_status),
                "failed": sum(1 for s in capability.stacks if "FAILED" in s.stack_status),
                "missing": len(capability.missing_stacks),
            },
        }
        
        self.tracker.installations_table.insert(record)
    
    def _update_installation(self, capability: DiscoveredCapability):
        """Update existing installation record."""
        InstallQuery = Query()
        
        status_map = {
            CapabilityStatus.HEALTHY: "completed",
            CapabilityStatus.FAILED: "failed",
            CapabilityStatus.IN_PROGRESS: "running",
            CapabilityStatus.PARTIAL: "partial",
            CapabilityStatus.NOT_FOUND: "not_found",
        }
        
        updates = {
            "status": status_map.get(capability.status, "unknown"),
            "frontend_url": capability.frontend_url,
            "backend_url": capability.backend_url,
            "discovered_at": capability.discovered_at.isoformat(),
            "capability_version": capability.version or "unknown",
            "stacks_summary": {
                "total": len(capability.stacks),
                "healthy": sum(1 for s in capability.stacks if "COMPLETE" in s.stack_status),
                "failed": sum(1 for s in capability.stacks if "FAILED" in s.stack_status),
                "missing": len(capability.missing_stacks),
            },
        }
        
        self.tracker.installations_table.update(
            updates,
            (InstallQuery.capability_name == capability.capability_name) &
            (InstallQuery.environment == capability.environment) &
            (InstallQuery.account_id == capability.account_id)
        )
    
    def _mark_not_found(self, capability_name: str, environment: str, account_id: str):
        """Mark installation as not found in AWS."""
        InstallQuery = Query()
        
        self.tracker.installations_table.update(
            {"status": "not_found_in_aws"},
            (InstallQuery.capability_name == capability_name) &
            (InstallQuery.environment == environment) &
            (InstallQuery.account_id == account_id)
        )
```


## API Endpoints

### Discovery Router

```python
"""
Discovery API Router for capability discovery operations.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query as QueryParam
from pydantic import BaseModel, Field

from app.services.aws_session_manager import aws_session_manager
from .discovery_service import DiscoveryService
from .landing_zone_manager import LandingZoneManager
from .discovery_sync_service import DiscoverySyncService
from .models import CloudProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discovery", tags=["discovery"])

# In-memory storage for discovery jobs
_discovery_jobs = {}


# Request/Response Models

class CloudProviderEnum(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class CreateLandingZoneRequest(BaseModel):
    name: str = Field(..., description="User-friendly name for the landing zone")
    provider: CloudProviderEnum = Field(..., description="Cloud provider")
    account_id: str = Field(..., description="Cloud account identifier")
    default_region: str = Field(default="ap-southeast-1", description="Default region")
    account_alias: Optional[str] = Field(default=None, description="Account alias")


class LandingZoneResponse(BaseModel):
    landing_zone_id: str
    name: str
    provider: str
    account_id: str
    account_alias: Optional[str]
    default_region: str
    created_at: str
    last_discovery_at: Optional[str]
    discovery_status: str
    capabilities_count: int


class StartDiscoveryRequest(BaseModel):
    landing_zone_id: str = Field(..., description="Landing zone to discover")
    aws_session_id: Optional[str] = Field(default=None, description="AWS session for credentials")
    regions: Optional[List[str]] = Field(default=None, description="Regions to scan (default: landing zone region)")


class DiscoveryStatusResponse(BaseModel):
    job_id: str
    landing_zone_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    stacks_scanned: int
    capabilities_found: int
    errors: List[str]
    progress_message: str


class DiscoveredCapabilityResponse(BaseModel):
    capability_name: str
    environment: str
    account_id: str
    primary_region: str
    status: str
    stacks_count: int
    missing_stacks: List[str]
    discovered_at: str
    version: Optional[str]
    frontend_url: Optional[str]
    backend_url: Optional[str]


# Endpoints

@router.post("/landing-zones", response_model=LandingZoneResponse)
async def create_landing_zone(request: CreateLandingZoneRequest):
    """Create or update a landing zone configuration."""
    # Only AWS is currently supported
    if request.provider != CloudProviderEnum.AWS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{request.provider}' is not yet supported. Only AWS is currently available."
        )
    
    manager = LandingZoneManager()
    landing_zone_id = manager.create_landing_zone(
        name=request.name,
        provider=CloudProvider(request.provider.value),
        account_id=request.account_id,
        default_region=request.default_region,
        account_alias=request.account_alias,
    )
    
    landing_zone = manager.get_landing_zone(landing_zone_id)
    return LandingZoneResponse(**landing_zone)


@router.get("/landing-zones", response_model=List[LandingZoneResponse])
async def list_landing_zones(
    provider: Optional[CloudProviderEnum] = QueryParam(default=None)
):
    """List all configured landing zones."""
    manager = LandingZoneManager()
    
    cloud_provider = CloudProvider(provider.value) if provider else None
    landing_zones = manager.list_landing_zones(provider=cloud_provider)
    
    return [LandingZoneResponse(**lz) for lz in landing_zones]


@router.delete("/landing-zones/{landing_zone_id}")
async def delete_landing_zone(landing_zone_id: str):
    """Delete a landing zone configuration."""
    manager = LandingZoneManager()
    
    if not manager.delete_landing_zone(landing_zone_id):
        raise HTTPException(status_code=404, detail="Landing zone not found")
    
    return {"message": "Landing zone deleted", "landing_zone_id": landing_zone_id}


@router.post("/discover", response_model=DiscoveryStatusResponse)
async def start_discovery(
    request: StartDiscoveryRequest,
    background_tasks: BackgroundTasks
):
    """Start capability discovery for a landing zone."""
    manager = LandingZoneManager()
    landing_zone = manager.get_landing_zone(request.landing_zone_id)
    
    if not landing_zone:
        raise HTTPException(status_code=404, detail="Landing zone not found")
    
    # Get AWS credentials
    credentials = None
    if request.aws_session_id:
        credentials = aws_session_manager.get_credentials_dict(request.aws_session_id)
        if not credentials:
            raise HTTPException(status_code=401, detail="AWS session expired or not found")
    
    # Create discovery job
    job_id = str(uuid.uuid4())[:8]
    _discovery_jobs[job_id] = {
        "job_id": job_id,
        "landing_zone_id": request.landing_zone_id,
        "status": "pending",
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
        "stacks_scanned": 0,
        "capabilities_found": 0,
        "errors": [],
        "progress_message": "Initializing...",
    }
    
    # Start background discovery
    regions = request.regions or [landing_zone["default_region"]]
    background_tasks.add_task(
        _run_discovery,
        job_id,
        request.landing_zone_id,
        landing_zone["account_id"],
        regions,
        credentials,
    )
    
    return DiscoveryStatusResponse(**_discovery_jobs[job_id])


@router.get("/discover/{job_id}/status", response_model=DiscoveryStatusResponse)
async def get_discovery_status(job_id: str):
    """Get status of a discovery job."""
    if job_id not in _discovery_jobs:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    
    return DiscoveryStatusResponse(**_discovery_jobs[job_id])


@router.post("/refresh/{landing_zone_id}", response_model=DiscoveryStatusResponse)
async def refresh_capabilities(
    landing_zone_id: str,
    aws_session_id: Optional[str] = QueryParam(default=None),
    background_tasks: BackgroundTasks = None
):
    """Refresh capabilities for a landing zone (re-run discovery)."""
    request = StartDiscoveryRequest(
        landing_zone_id=landing_zone_id,
        aws_session_id=aws_session_id,
    )
    return await start_discovery(request, background_tasks)


# Background task

def _run_discovery(
    job_id: str,
    landing_zone_id: str,
    account_id: str,
    regions: List[str],
    credentials: Optional[dict],
):
    """Background task to run discovery."""
    job = _discovery_jobs.get(job_id)
    if not job:
        return
    
    job["status"] = "running"
    job["progress_message"] = "Starting discovery..."
    
    manager = LandingZoneManager()
    manager.update_discovery_status(landing_zone_id, "running")
    
    all_capabilities = []
    all_errors = []
    total_stacks = 0
    
    try:
        for region in regions:
            job["progress_message"] = f"Scanning region {region}..."
            
            service = DiscoveryService(
                region=region,
                credentials=credentials,
            )
            
            def progress_callback(msg):
                job["progress_message"] = msg
            
            capabilities, errors = service.discover_capabilities(
                landing_zone_id=landing_zone_id,
                account_id=account_id,
                progress_callback=progress_callback,
            )
            
            all_capabilities.extend(capabilities)
            all_errors.extend(errors)
            total_stacks += sum(len(c.stacks) for c in capabilities)
        
        # Sync to TinyDB
        job["progress_message"] = "Syncing to database..."
        sync_service = DiscoverySyncService()
        sync_service.sync_discovered_capabilities(all_capabilities, landing_zone_id)
        
        # Update job status
        job["status"] = "completed"
        job["completed_at"] = datetime.utcnow().isoformat()
        job["stacks_scanned"] = total_stacks
        job["capabilities_found"] = len(all_capabilities)
        job["errors"] = all_errors
        job["progress_message"] = f"Discovery complete: {len(all_capabilities)} capabilities found"
        
        # Update landing zone
        manager.update_discovery_status(
            landing_zone_id,
            "completed",
            capabilities_count=len(all_capabilities),
        )
        
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        job["status"] = "failed"
        job["completed_at"] = datetime.utcnow().isoformat()
        job["errors"].append(str(e))
        job["progress_message"] = f"Discovery failed: {str(e)}"
        
        manager.update_discovery_status(landing_zone_id, "failed")
```


## Frontend Components

### LandingZoneSelector Component

```tsx
/**
 * Landing Zone Selector Component
 * Allows users to select cloud provider and manage landing zones
 */
import React, { useState, useEffect } from 'react';
import { discoveryApi } from '../services/api';

interface LandingZone {
  landing_zone_id: string;
  name: string;
  provider: string;
  account_id: string;
  account_alias?: string;
  default_region: string;
  last_discovery_at?: string;
  discovery_status: string;
  capabilities_count: number;
}

interface Props {
  onLandingZoneSelect: (landingZone: LandingZone) => void;
  onDiscoverNew: () => void;
}

const LandingZoneSelector: React.FC<Props> = ({ onLandingZoneSelect, onDiscoverNew }) => {
  const [landingZones, setLandingZones] = useState<LandingZone[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProvider, setSelectedProvider] = useState<string>('aws');

  useEffect(() => {
    loadLandingZones();
  }, []);

  const loadLandingZones = async () => {
    try {
      setLoading(true);
      const zones = await discoveryApi.listLandingZones();
      setLandingZones(zones);
    } catch (error) {
      console.error('Failed to load landing zones:', error);
    } finally {
      setLoading(false);
    }
  };

  const providers = [
    { id: 'aws', name: 'Amazon Web Services', icon: '☁️', supported: true },
    { id: 'azure', name: 'Microsoft Azure', icon: '🔷', supported: false },
    { id: 'gcp', name: 'Google Cloud Platform', icon: '🌐', supported: false },
  ];

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold mb-6">Select Cloud Provider</h2>
      
      {/* Provider Selection */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {providers.map((provider) => (
          <button
            key={provider.id}
            onClick={() => provider.supported && setSelectedProvider(provider.id)}
            disabled={!provider.supported}
            className={`p-6 rounded-lg border-2 text-center transition-all ${
              selectedProvider === provider.id
                ? 'border-blue-500 bg-blue-50'
                : provider.supported
                ? 'border-gray-200 hover:border-blue-300'
                : 'border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed'
            }`}
          >
            <span className="text-3xl mb-2 block">{provider.icon}</span>
            <span className="font-medium">{provider.name}</span>
            {!provider.supported && (
              <span className="block text-xs text-amber-600 mt-1">Coming Soon</span>
            )}
          </button>
        ))}
      </div>

      {/* Landing Zones List */}
      {selectedProvider === 'aws' && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h3 className="text-lg font-semibold">AWS Landing Zones</h3>
            <button
              onClick={onDiscoverNew}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              + Add Landing Zone
            </button>
          </div>

          {loading ? (
            <div className="text-center py-8">Loading...</div>
          ) : landingZones.length === 0 ? (
            <div className="text-center py-8 bg-gray-50 rounded-lg">
              <p className="text-gray-600">No landing zones configured</p>
              <p className="text-sm text-gray-500 mt-1">
                Add a landing zone to discover capabilities
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {landingZones
                .filter((lz) => lz.provider === 'aws')
                .map((lz) => (
                  <div
                    key={lz.landing_zone_id}
                    onClick={() => onLandingZoneSelect(lz)}
                    className="p-4 border rounded-lg hover:border-blue-300 cursor-pointer"
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <h4 className="font-medium">{lz.name}</h4>
                        <p className="text-sm text-gray-500">
                          Account: {lz.account_id}
                          {lz.account_alias && ` (${lz.account_alias})`}
                        </p>
                        <p className="text-sm text-gray-500">
                          Region: {lz.default_region}
                        </p>
                      </div>
                      <div className="text-right">
                        <span className="text-sm font-medium text-blue-600">
                          {lz.capabilities_count} capabilities
                        </span>
                        {lz.last_discovery_at && (
                          <p className="text-xs text-gray-400 mt-1">
                            Last scan: {new Date(lz.last_discovery_at).toLocaleDateString()}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default LandingZoneSelector;
```

### DiscoveryPanel Component

```tsx
/**
 * Discovery Panel Component
 * Shows discovery progress and results
 */
import React, { useState, useEffect } from 'react';
import { discoveryApi } from '../services/api';

interface DiscoveryJob {
  job_id: string;
  status: string;
  progress_message: string;
  stacks_scanned: number;
  capabilities_found: number;
  errors: string[];
}

interface Props {
  landingZoneId: string;
  awsSessionId?: string;
  onComplete: () => void;
  onCancel: () => void;
}

const DiscoveryPanel: React.FC<Props> = ({
  landingZoneId,
  awsSessionId,
  onComplete,
  onCancel,
}) => {
  const [job, setJob] = useState<DiscoveryJob | null>(null);
  const [polling, setPolling] = useState(false);

  const startDiscovery = async () => {
    try {
      const response = await discoveryApi.startDiscovery({
        landing_zone_id: landingZoneId,
        aws_session_id: awsSessionId,
      });
      setJob(response);
      setPolling(true);
    } catch (error) {
      console.error('Failed to start discovery:', error);
    }
  };

  useEffect(() => {
    startDiscovery();
  }, []);

  useEffect(() => {
    if (!polling || !job) return;

    const interval = setInterval(async () => {
      try {
        const status = await discoveryApi.getDiscoveryStatus(job.job_id);
        setJob(status);

        if (status.status === 'completed' || status.status === 'failed') {
          setPolling(false);
          if (status.status === 'completed') {
            setTimeout(onComplete, 1500);
          }
        }
      } catch (error) {
        console.error('Failed to get discovery status:', error);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [polling, job]);

  if (!job) {
    return (
      <div className="text-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto" />
        <p className="mt-4 text-gray-600">Starting discovery...</p>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="bg-white rounded-lg shadow-lg p-6">
        <h3 className="text-lg font-semibold mb-4">Capability Discovery</h3>

        {/* Progress */}
        <div className="mb-6">
          <div className="flex items-center mb-2">
            {job.status === 'running' && (
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600 mr-3" />
            )}
            {job.status === 'completed' && (
              <span className="text-green-500 mr-3">✓</span>
            )}
            {job.status === 'failed' && (
              <span className="text-red-500 mr-3">✗</span>
            )}
            <span className="font-medium">{job.progress_message}</span>
          </div>

          {job.status === 'running' && (
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div className="bg-blue-600 h-2 rounded-full animate-pulse w-3/4" />
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div className="bg-gray-50 rounded-lg p-4 text-center">
            <span className="text-2xl font-bold text-blue-600">
              {job.stacks_scanned}
            </span>
            <p className="text-sm text-gray-500">Stacks Scanned</p>
          </div>
          <div className="bg-gray-50 rounded-lg p-4 text-center">
            <span className="text-2xl font-bold text-green-600">
              {job.capabilities_found}
            </span>
            <p className="text-sm text-gray-500">Capabilities Found</p>
          </div>
        </div>

        {/* Errors */}
        {job.errors.length > 0 && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <h4 className="font-medium text-red-800 mb-2">Errors</h4>
            <ul className="text-sm text-red-600 list-disc list-inside">
              {job.errors.map((error, idx) => (
                <li key={idx}>{error}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3">
          {job.status === 'running' && (
            <button
              onClick={onCancel}
              className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
          )}
          {(job.status === 'completed' || job.status === 'failed') && (
            <button
              onClick={onComplete}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              Continue
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default DiscoveryPanel;
```


## Frontend API Service

```typescript
// Add to services/api.ts

export const discoveryApi = {
  // Landing Zones
  createLandingZone: async (data: {
    name: string;
    provider: 'aws' | 'azure' | 'gcp';
    account_id: string;
    default_region: string;
    account_alias?: string;
  }): Promise<any> => {
    const response = await api.post('/api/discovery/landing-zones', data);
    return response.data;
  },

  listLandingZones: async (provider?: string): Promise<any[]> => {
    const params = provider ? { provider } : {};
    const response = await api.get('/api/discovery/landing-zones', { params });
    return response.data;
  },

  deleteLandingZone: async (landingZoneId: string): Promise<void> => {
    await api.delete(`/api/discovery/landing-zones/${landingZoneId}`);
  },

  // Discovery
  startDiscovery: async (data: {
    landing_zone_id: string;
    aws_session_id?: string;
    regions?: string[];
  }): Promise<any> => {
    const response = await api.post('/api/discovery/discover', data);
    return response.data;
  },

  getDiscoveryStatus: async (jobId: string): Promise<any> => {
    const response = await api.get(`/api/discovery/discover/${jobId}/status`);
    return response.data;
  },

  refreshCapabilities: async (
    landingZoneId: string,
    awsSessionId?: string
  ): Promise<any> => {
    const params = awsSessionId ? { aws_session_id: awsSessionId } : {};
    const response = await api.post(
      `/api/discovery/refresh/${landingZoneId}`,
      null,
      { params }
    );
    return response.data;
  },
};
```

## Correctness Properties

### Property 1: Stack Name Parsing Completeness

*For any* valid stack name following the convention `{capability}-{env}-{stack-type}`, the `parse_stack_name` function should correctly extract all three components.

**Validates: Requirements 4.3, 4.4, 6.1**

```python
from hypothesis import given, strategies as st

VALID_STACK_TYPES = [
    "backend-foundation", "backend-iam-roles", "backend-regional-cert",
    "backend-storage", "backend-network", "backend-service", "backend-domain",
    "frontend-global", "frontend-cognito", "frontend-regional",
]
VALID_ENVIRONMENTS = ["dev", "test", "stage", "prod"]

@given(
    capability=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-", min_size=1, max_size=30).filter(lambda x: not x.startswith('-') and not x.endswith('-')),
    environment=st.sampled_from(VALID_ENVIRONMENTS),
    stack_type=st.sampled_from(VALID_STACK_TYPES),
)
def test_parse_stack_name_extracts_all_components(capability, environment, stack_type):
    """Valid stack names should be parsed correctly."""
    stack_name = f"{capability}-{environment}-{stack_type}"
    
    result = parse_stack_name(stack_name)
    
    assert result is not None, f"Failed to parse: {stack_name}"
    parsed_capability, parsed_env, parsed_type = result
    assert parsed_capability == capability
    assert parsed_env == environment
    assert parsed_type == stack_type
```

### Property 2: Non-Matching Stacks Are Skipped

*For any* stack name that does not match the naming convention, the `parse_stack_name` function should return None without error.

**Validates: Requirements 4.6**

```python
@given(
    stack_name=st.text(min_size=1, max_size=100)
)
def test_invalid_stack_names_return_none(stack_name):
    """Invalid stack names should return None, not raise exceptions."""
    # Skip if it accidentally matches the pattern
    if any(stack_name.endswith(f"-{env}-{st}") 
           for env in VALID_ENVIRONMENTS 
           for st in VALID_STACK_TYPES):
        return
    
    result = parse_stack_name(stack_name)
    assert result is None
```

### Property 3: Capability Status Determination

*For any* set of stacks, the capability status should be determined correctly based on stack statuses.

**Validates: Requirements 5.2, 5.3, 5.4, 5.5**

```python
@given(
    stack_statuses=st.lists(
        st.sampled_from([
            "CREATE_COMPLETE", "UPDATE_COMPLETE",
            "CREATE_FAILED", "UPDATE_FAILED", "ROLLBACK_COMPLETE",
            "CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS",
        ]),
        min_size=1,
        max_size=10,
    )
)
def test_capability_status_priority(stack_statuses):
    """Status determination follows priority: FAILED > IN_PROGRESS > PARTIAL > HEALTHY."""
    has_failed = any("FAILED" in s or "ROLLBACK" in s for s in stack_statuses)
    has_in_progress = any("IN_PROGRESS" in s for s in stack_statuses)
    
    status = determine_capability_status(stack_statuses)
    
    if has_failed:
        assert status == CapabilityStatus.FAILED
    elif has_in_progress:
        assert status == CapabilityStatus.IN_PROGRESS
    # PARTIAL and HEALTHY depend on expected vs actual stacks
```

### Property 4: TinyDB Sync Idempotency

*For any* set of discovered capabilities, running sync multiple times should produce the same result.

**Validates: Requirements 7.2, 7.3**

```python
def test_sync_idempotency(discovered_capabilities):
    """Syncing the same capabilities twice should not create duplicates."""
    sync_service = DiscoverySyncService()
    
    # First sync
    stats1 = sync_service.sync_discovered_capabilities(discovered_capabilities, "lz-1")
    
    # Second sync with same data
    stats2 = sync_service.sync_discovered_capabilities(discovered_capabilities, "lz-1")
    
    # Second sync should only update, not create
    assert stats2["created"] == 0
    assert stats2["updated"] == len(discovered_capabilities)
```

### Property 5: Landing Zone Uniqueness

*For any* account ID and provider combination, only one landing zone should exist.

**Validates: Requirements 3.2**

```python
def test_landing_zone_uniqueness():
    """Creating landing zone with same account should update, not duplicate."""
    manager = LandingZoneManager()
    
    # Create first
    id1 = manager.create_landing_zone(
        name="Test 1",
        provider=CloudProvider.AWS,
        account_id="123456789012",
        default_region="us-east-1",
    )
    
    # Create second with same account
    id2 = manager.create_landing_zone(
        name="Test 2",
        provider=CloudProvider.AWS,
        account_id="123456789012",
        default_region="us-west-2",
    )
    
    # Should return same ID (updated existing)
    assert id1 == id2
    
    # Should only have one landing zone
    zones = manager.list_landing_zones()
    aws_zones = [z for z in zones if z["account_id"] == "123456789012"]
    assert len(aws_zones) == 1
```

## File Structure

```
nexus-deployer/backend/app/
├── services/
│   └── discovery/
│       ├── __init__.py
│       ├── models.py                    # Data models
│       ├── discovery_service.py         # CloudFormation scanning
│       ├── landing_zone_manager.py      # Landing zone CRUD
│       └── discovery_sync_service.py    # TinyDB synchronization
├── routers/
│   └── discovery.py                     # API endpoints

nexus-deployer/frontend/src/
├── components/
│   ├── LandingZoneSelector.tsx          # Cloud provider selection
│   ├── DiscoveryPanel.tsx               # Discovery progress
│   └── CapabilitySelection.tsx          # Enhanced with discovery
├── services/
│   └── api.ts                           # Add discoveryApi
```

## Integration Points

1. **AWS Session Manager**: Reuse existing ADFS/SAML authentication flow
2. **Installation Tracker**: Extend to support discovered capabilities with `strategy="DISCOVERED"`
3. **TinyDB State Manager**: Add `landing_zones` table
4. **CapabilitySelection Component**: Add "Discover from AWS" option and landing zone filter
5. **Deployment States API**: Include discovered capabilities in listing

## Migration Considerations

1. Existing installations in TinyDB will continue to work
2. Discovered capabilities will have `strategy="DISCOVERED"` to distinguish from deployed
3. Users can manually deploy to discovered capabilities (converts to normal installation)
4. Landing zones are optional - existing workflow continues to work without them
