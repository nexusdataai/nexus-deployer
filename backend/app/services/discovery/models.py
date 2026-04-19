"""
Data Models for Capability Discovery

Defines the data structures used for discovering capabilities from
CloudFormation stacks and managing landing zones.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from enum import Enum


class CloudProvider(str, Enum):
    """Supported cloud providers for capability discovery."""
    AWS = "aws"
    AZURE = "azure"  # Future support
    GCP = "gcp"      # Future support


class CapabilityStatus(str, Enum):
    """Status of a discovered capability based on its stack states."""
    HEALTHY = "healthy"           # All stacks CREATE_COMPLETE or UPDATE_COMPLETE
    FAILED = "failed"             # Any stack in FAILED or ROLLBACK state
    IN_PROGRESS = "in_progress"   # Any stack in IN_PROGRESS state
    PARTIAL = "partial"           # Some expected stacks missing
    NOT_FOUND = "not_found"       # Exists in TinyDB but not in AWS


class DiscoveryJobStatus(str, Enum):
    """Status of a discovery job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class LandingZone:
    """Represents a cloud account configured for capability discovery."""
    landing_zone_id: str
    name: str
    provider: CloudProvider
    account_id: str
    default_region: str
    account_alias: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_discovery_at: Optional[datetime] = None
    discovery_status: str = "idle"
    capabilities_count: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for TinyDB storage."""
        return {
            "landing_zone_id": self.landing_zone_id,
            "name": self.name,
            "provider": self.provider.value if isinstance(self.provider, CloudProvider) else self.provider,
            "account_id": self.account_id,
            "account_alias": self.account_alias,
            "default_region": self.default_region,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "last_discovery_at": self.last_discovery_at.isoformat() if self.last_discovery_at else None,
            "discovery_status": self.discovery_status,
            "capabilities_count": self.capabilities_count,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "LandingZone":
        """Create LandingZone from dictionary."""
        return cls(
            landing_zone_id=data["landing_zone_id"],
            name=data["name"],
            provider=CloudProvider(data["provider"]) if isinstance(data["provider"], str) else data["provider"],
            account_id=data["account_id"],
            account_alias=data.get("account_alias"),
            default_region=data["default_region"],
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"],
            last_discovery_at=datetime.fromisoformat(data["last_discovery_at"]) if data.get("last_discovery_at") else None,
            discovery_status=data.get("discovery_status", "idle"),
            capabilities_count=data.get("capabilities_count", 0),
        )


@dataclass
class DiscoveredStack:
    """Individual CloudFormation stack discovered during scanning."""
    stack_name: str
    stack_type: str               # backend-foundation, frontend-global, etc.
    stack_status: str             # CloudFormation status
    region: str
    created_time: Optional[datetime] = None
    last_updated_time: Optional[datetime] = None
    outputs: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "stack_name": self.stack_name,
            "stack_type": self.stack_type,
            "stack_status": self.stack_status,
            "region": self.region,
            "created_time": self.created_time.isoformat() if self.created_time else None,
            "last_updated_time": self.last_updated_time.isoformat() if self.last_updated_time else None,
            "outputs": self.outputs,
            "tags": self.tags,
        }


@dataclass
class DiscoveredCapability:
    """A capability discovered from CloudFormation stacks."""
    capability_name: str
    environment: str              # dev, test, stage, prod
    landing_zone_id: str          # Reference to landing zone
    account_id: str
    primary_region: str
    status: CapabilityStatus
    stacks: List[DiscoveredStack] = field(default_factory=list)
    missing_stacks: List[str] = field(default_factory=list)  # Stack types that are expected but missing
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    version: Optional[str] = None        # Extracted from stack tags if available
    frontend_url: Optional[str] = None   # From stack outputs
    backend_url: Optional[str] = None    # From stack outputs
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "capability_name": self.capability_name,
            "environment": self.environment,
            "landing_zone_id": self.landing_zone_id,
            "account_id": self.account_id,
            "primary_region": self.primary_region,
            "status": self.status.value if isinstance(self.status, CapabilityStatus) else self.status,
            "stacks": [s.to_dict() for s in self.stacks],
            "missing_stacks": self.missing_stacks,
            "discovered_at": self.discovered_at.isoformat() if isinstance(self.discovered_at, datetime) else self.discovered_at,
            "version": self.version,
            "frontend_url": self.frontend_url,
            "backend_url": self.backend_url,
        }


@dataclass
class DiscoveryJob:
    """Tracks a discovery operation."""
    job_id: str
    landing_zone_id: str
    status: DiscoveryJobStatus
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    stacks_scanned: int = 0
    capabilities_found: int = 0
    errors: List[str] = field(default_factory=list)
    progress_message: str = "Initializing..."
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "job_id": self.job_id,
            "landing_zone_id": self.landing_zone_id,
            "status": self.status.value if isinstance(self.status, DiscoveryJobStatus) else self.status,
            "started_at": self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "stacks_scanned": self.stacks_scanned,
            "capabilities_found": self.capabilities_found,
            "errors": self.errors,
            "progress_message": self.progress_message,
        }
