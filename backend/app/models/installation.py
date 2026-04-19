"""
Installation tracking models for deployment session persistence
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any


class InstallationStatus(str, Enum):
    """Status of a deployment installation"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class StackOperationStatus(str, Enum):
    """Status of a stack operation"""
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StackOperationType(str, Enum):
    """Type of stack operation"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SKIP = "skip"


@dataclass
class InstallationRecord:
    """
    Record of a deployment installation with full metadata.
    
    Tracks the complete lifecycle of a deployment including
    capability info, timing, status, and output URLs.
    """
    installation_id: str
    capability_name: str
    capability_version: str
    environment: str
    region: str
    account_id: str
    strategy: str  # CLEAN_DEPLOY or UPDATE_EXISTING
    deploy_frontend: bool
    deploy_backend: bool
    status: InstallationStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    error: Optional[str] = None
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None
    cognito_config: Optional[Dict[str, Any]] = None
    stacks_summary: Dict[str, int] = field(default_factory=lambda: {
        "created": 0,
        "updated": 0,
        "failed": 0,
        "skipped": 0
    })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for TinyDB storage"""
        return {
            "installation_id": self.installation_id,
            "capability_name": self.capability_name,
            "capability_version": self.capability_version,
            "environment": self.environment,
            "region": self.region,
            "account_id": self.account_id,
            "strategy": self.strategy,
            "deploy_frontend": self.deploy_frontend,
            "deploy_backend": self.deploy_backend,
            "status": self.status.value if isinstance(self.status, InstallationStatus) else self.status,
            "started_at": self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "frontend_url": self.frontend_url,
            "backend_url": self.backend_url,
            "cognito_config": self.cognito_config,
            "stacks_summary": self.stacks_summary,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InstallationRecord":
        """Create from dictionary (TinyDB storage)"""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        
        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)
        
        status = data.get("status", "pending")
        if isinstance(status, str):
            status = InstallationStatus(status)
        
        return cls(
            installation_id=data["installation_id"],
            capability_name=data["capability_name"],
            capability_version=data["capability_version"],
            environment=data["environment"],
            region=data["region"],
            account_id=data["account_id"],
            strategy=data["strategy"],
            deploy_frontend=data["deploy_frontend"],
            deploy_backend=data["deploy_backend"],
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=data.get("duration_seconds"),
            error=data.get("error"),
            frontend_url=data.get("frontend_url"),
            backend_url=data.get("backend_url"),
            cognito_config=data.get("cognito_config"),
            stacks_summary=data.get("stacks_summary", {
                "created": 0, "updated": 0, "failed": 0, "skipped": 0
            }),
        )


@dataclass
class StackOperationLog:
    """
    Log entry for a stack operation during deployment.
    
    Captures the full lifecycle of a CloudFormation stack operation
    including timing, status, outputs, and error details.
    """
    log_id: str
    installation_id: str
    stack_name: str
    stack_type: str  # frontend-global, backend-service, etc.
    operation: StackOperationType
    status: StackOperationStatus
    region: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    error_message: Optional[str] = None
    stack_outputs: Optional[Dict[str, Any]] = None
    cfn_events: Optional[List[Dict[str, Any]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for TinyDB storage"""
        return {
            "log_id": self.log_id,
            "installation_id": self.installation_id,
            "stack_name": self.stack_name,
            "stack_type": self.stack_type,
            "operation": self.operation.value if isinstance(self.operation, StackOperationType) else self.operation,
            "status": self.status.value if isinstance(self.status, StackOperationStatus) else self.status,
            "region": self.region,
            "started_at": self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "stack_outputs": self.stack_outputs,
            "cfn_events": self.cfn_events,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StackOperationLog":
        """Create from dictionary (TinyDB storage)"""
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)
        
        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)
        
        operation = data.get("operation", "create")
        if isinstance(operation, str):
            operation = StackOperationType(operation)
        
        status = data.get("status", "started")
        if isinstance(status, str):
            status = StackOperationStatus(status)
        
        return cls(
            log_id=data["log_id"],
            installation_id=data["installation_id"],
            stack_name=data["stack_name"],
            stack_type=data["stack_type"],
            operation=operation,
            status=status,
            region=data["region"],
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=data.get("duration_seconds"),
            error_message=data.get("error_message"),
            stack_outputs=data.get("stack_outputs"),
            cfn_events=data.get("cfn_events"),
        )


@dataclass
class StoredCredentials:
    """
    Encrypted AWS credentials stored in TinyDB.
    
    Sensitive fields (access_key, secret_key, session_token) are
    encrypted using Fernet symmetric encryption before storage.
    """
    installation_id: str
    encrypted_access_key: str
    encrypted_secret_key: str
    encrypted_session_token: Optional[str]
    region: str
    account_id: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for TinyDB storage"""
        return {
            "installation_id": self.installation_id,
            "encrypted_access_key": self.encrypted_access_key,
            "encrypted_secret_key": self.encrypted_secret_key,
            "encrypted_session_token": self.encrypted_session_token,
            "region": self.region,
            "account_id": self.account_id,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredCredentials":
        """Create from dictionary (TinyDB storage)"""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        
        last_accessed_at = data.get("last_accessed_at")
        if isinstance(last_accessed_at, str):
            last_accessed_at = datetime.fromisoformat(last_accessed_at)
        
        return cls(
            installation_id=data["installation_id"],
            encrypted_access_key=data["encrypted_access_key"],
            encrypted_secret_key=data["encrypted_secret_key"],
            encrypted_session_token=data.get("encrypted_session_token"),
            region=data["region"],
            account_id=data["account_id"],
            created_at=created_at,
            expires_at=expires_at,
            last_accessed_at=last_accessed_at,
        )
