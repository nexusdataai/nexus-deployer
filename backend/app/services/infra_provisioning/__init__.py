"""
Infrastructure Provisioning Service for Call Processing Capability.

This module provides automated provisioning of AWS resources including:
- DynamoDB tables
- S3 buckets
- SSM Parameter Store parameters
- Secrets Manager secrets
- Glue databases and tables
- CloudWatch log groups

All resources follow the naming convention: call-processing-{env}-{resource}

Usage:
    from app.services.infra_provisioning import ProvisioningOrchestrator
    
    orchestrator = ProvisioningOrchestrator(environment="dev", region="us-east-1")
    report = orchestrator.provision_all()
    
CLI Usage:
    python -m app.services.infra_provisioning.cli provision --environment dev
    python -m app.services.infra_provisioning.cli verify --environment prod
    python -m app.services.infra_provisioning.cli dry-run --environment stage
"""

# Import models first (no dependencies on other modules in this package)
from .models import (
    ResourceType,
    ResourceStatusType,
    VerificationStatusType,
    ResourceStatus,
    VerificationResult,
    ProvisioningReport,
    VerificationReport,
    EnvironmentConfig,
    ENVIRONMENT_CONFIGS,
    VALID_ENVIRONMENTS,
)

# Import naming (no dependencies on other modules in this package)
from .naming import ResourceNaming

# Import exceptions (depends on models)
from .exceptions import (
    ProvisioningError,
    ResourceCreationError,
    ResourceVerificationError,
    ProvisioningPermissionError,
    ProvisioningTimeoutError,
    InvalidEnvironmentError,
)


def __getattr__(name):
    """Lazy import for provisioners to avoid circular imports."""
    if name == "DynamoDBProvisioner":
        from .dynamodb_provisioner import DynamoDBProvisioner
        return DynamoDBProvisioner
    elif name == "S3Provisioner":
        from .s3_provisioner import S3Provisioner
        return S3Provisioner
    elif name == "SSMProvisioner":
        from .ssm_provisioner import SSMProvisioner
        return SSMProvisioner
    elif name == "SecretsProvisioner":
        from .secrets_provisioner import SecretsProvisioner
        return SecretsProvisioner
    elif name == "GlueProvisioner":
        from .glue_provisioner import GlueProvisioner
        return GlueProvisioner
    elif name == "CloudWatchProvisioner":
        from .cloudwatch_provisioner import CloudWatchProvisioner
        return CloudWatchProvisioner
    elif name == "ProvisioningOrchestrator":
        from .orchestrator import ProvisioningOrchestrator
        return ProvisioningOrchestrator
    elif name == "VerificationService":
        from .verification_service import VerificationService
        return VerificationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Models
    "ResourceType",
    "ResourceStatusType",
    "VerificationStatusType",
    "ResourceStatus",
    "VerificationResult",
    "ProvisioningReport",
    "VerificationReport",
    "EnvironmentConfig",
    "ENVIRONMENT_CONFIGS",
    "VALID_ENVIRONMENTS",
    # Naming
    "ResourceNaming",
    # Exceptions
    "ProvisioningError",
    "ResourceCreationError",
    "ResourceVerificationError",
    "ProvisioningPermissionError",
    "ProvisioningTimeoutError",
    "InvalidEnvironmentError",
    # Provisioners (lazy loaded)
    "DynamoDBProvisioner",
    "S3Provisioner",
    "SSMProvisioner",
    "SecretsProvisioner",
    "GlueProvisioner",
    "CloudWatchProvisioner",
    # Orchestrator (lazy loaded)
    "ProvisioningOrchestrator",
    # Verification (lazy loaded)
    "VerificationService",
]
