"""
Data models for infrastructure provisioning.

Defines enums, dataclasses, and configuration for the provisioning system.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime


class ResourceType(Enum):
    """Types of AWS resources that can be provisioned."""
    DYNAMODB_TABLE = "dynamodb_table"
    S3_BUCKET = "s3_bucket"
    SSM_PARAMETER = "ssm_parameter"
    SECRET = "secret"
    GLUE_DATABASE = "glue_database"
    GLUE_TABLE = "glue_table"
    CLOUDWATCH_LOG_GROUP = "cloudwatch_log_group"


class ResourceStatusType(Enum):
    """Status of a resource provisioning operation."""
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"
    UPDATED = "updated"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerificationStatusType(Enum):
    """Status of a resource verification operation."""
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    INACCESSIBLE = "inaccessible"
    INVALID_STATE = "invalid_state"


@dataclass
class ResourceStatus:
    """Status of a single resource provisioning operation."""
    resource_type: ResourceType
    resource_name: str
    status: ResourceStatusType
    message: str
    created_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "resource_type": self.resource_type.value,
            "resource_name": self.resource_name,
            "status": self.status.value,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "error": self.error,
        }


@dataclass
class VerificationResult:
    """Result of verifying a single resource."""
    resource_type: ResourceType
    resource_name: str
    status: VerificationStatusType
    details: str
    failure_reason: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "resource_type": self.resource_type.value,
            "resource_name": self.resource_name,
            "status": self.status.value,
            "details": self.details,
            "failure_reason": self.failure_reason,
            "error": self.error,
        }


@dataclass
class ProvisioningReport:
    """Complete report of provisioning operation."""
    environment: str
    region: str
    started_at: datetime
    completed_at: datetime
    dry_run: bool
    resources: List[ResourceStatus]
    success_count: int = 0
    already_existed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    overall_success: bool = True

    def __post_init__(self):
        """Calculate counts from resources."""
        self.success_count = sum(
            1 for r in self.resources 
            if r.status in (ResourceStatusType.CREATED, ResourceStatusType.UPDATED)
        )
        self.already_existed_count = sum(
            1 for r in self.resources 
            if r.status == ResourceStatusType.ALREADY_EXISTS
        )
        self.failed_count = sum(
            1 for r in self.resources 
            if r.status == ResourceStatusType.FAILED
        )
        self.skipped_count = sum(
            1 for r in self.resources 
            if r.status == ResourceStatusType.SKIPPED
        )
        self.overall_success = self.failed_count == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "environment": self.environment,
            "region": self.region,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "dry_run": self.dry_run,
            "resources": [r.to_dict() for r in self.resources],
            "success_count": self.success_count,
            "already_existed_count": self.already_existed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "overall_success": self.overall_success,
        }


@dataclass
class VerificationReport:
    """Complete report of verification operation."""
    environment: str
    region: str
    started_at: datetime
    completed_at: datetime
    results: List[VerificationResult]
    passed_count: int = 0
    failed_count: int = 0
    all_passed: bool = True

    def __post_init__(self):
        """Calculate counts from results."""
        self.passed_count = sum(
            1 for r in self.results 
            if r.status == VerificationStatusType.VERIFIED
        )
        self.failed_count = sum(
            1 for r in self.results 
            if r.status != VerificationStatusType.VERIFIED
        )
        self.all_passed = self.failed_count == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "environment": self.environment,
            "region": self.region,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "results": [r.to_dict() for r in self.results],
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "all_passed": self.all_passed,
        }


@dataclass
class EnvironmentConfig:
    """Environment-specific configuration."""
    environment: str
    region: str
    dynamodb_billing_mode: str = "PAY_PER_REQUEST"
    dynamodb_read_capacity: Optional[int] = None
    dynamodb_write_capacity: Optional[int] = None
    s3_versioning_enabled: bool = False
    s3_encryption_enabled: bool = True
    cloudwatch_retention_days: int = 30
    log_level: str = "INFO"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "environment": self.environment,
            "region": self.region,
            "dynamodb_billing_mode": self.dynamodb_billing_mode,
            "dynamodb_read_capacity": self.dynamodb_read_capacity,
            "dynamodb_write_capacity": self.dynamodb_write_capacity,
            "s3_versioning_enabled": self.s3_versioning_enabled,
            "s3_encryption_enabled": self.s3_encryption_enabled,
            "cloudwatch_retention_days": self.cloudwatch_retention_days,
            "log_level": self.log_level,
        }


# Environment-specific default configurations
ENVIRONMENT_CONFIGS: Dict[str, EnvironmentConfig] = {
    "dev": EnvironmentConfig(
        environment="dev",
        region="us-east-1",
        dynamodb_billing_mode="PAY_PER_REQUEST",
        dynamodb_read_capacity=None,
        dynamodb_write_capacity=None,
        s3_versioning_enabled=False,
        s3_encryption_enabled=True,
        cloudwatch_retention_days=30,
        log_level="DEBUG",
    ),
    "test": EnvironmentConfig(
        environment="test",
        region="us-east-1",
        dynamodb_billing_mode="PAY_PER_REQUEST",
        dynamodb_read_capacity=None,
        dynamodb_write_capacity=None,
        s3_versioning_enabled=False,
        s3_encryption_enabled=True,
        cloudwatch_retention_days=30,
        log_level="DEBUG",
    ),
    "stage": EnvironmentConfig(
        environment="stage",
        region="us-east-1",
        dynamodb_billing_mode="PAY_PER_REQUEST",
        dynamodb_read_capacity=None,
        dynamodb_write_capacity=None,
        s3_versioning_enabled=True,
        s3_encryption_enabled=True,
        cloudwatch_retention_days=90,
        log_level="INFO",
    ),
    "prod": EnvironmentConfig(
        environment="prod",
        region="us-east-1",
        dynamodb_billing_mode="PAY_PER_REQUEST",
        dynamodb_read_capacity=None,
        dynamodb_write_capacity=None,
        s3_versioning_enabled=True,
        s3_encryption_enabled=True,
        cloudwatch_retention_days=365,
        log_level="INFO",
    ),
}


# Valid environments
VALID_ENVIRONMENTS = frozenset(ENVIRONMENT_CONFIGS.keys())


def get_environment_config(environment: str) -> EnvironmentConfig:
    """
    Get configuration for a specific environment.
    
    Args:
        environment: Environment name (dev, test, stage, prod)
        
    Returns:
        EnvironmentConfig for the specified environment
        
    Raises:
        ValueError: If environment is not valid
    """
    if environment not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"Invalid environment '{environment}'. "
            f"Valid environments: {', '.join(sorted(VALID_ENVIRONMENTS))}"
        )
    return ENVIRONMENT_CONFIGS[environment]
