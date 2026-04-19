"""Capability data models."""
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class CapabilityArtifact(BaseModel):
    """Artifact information for a capability component."""
    s3_uri: Optional[str] = Field(None, description="S3 URI for frontend artifacts")
    ecr_uri: Optional[str] = Field(None, description="ECR URI for backend container images")
    size_mb: int = Field(..., description="Artifact size in megabytes")


class CapabilityArtifacts(BaseModel):
    """All artifacts for a capability."""
    frontend: Optional[CapabilityArtifact] = None
    backend: Optional[CapabilityArtifact] = None


class EKSArtifacts(BaseModel):
    """EKS-specific artifacts for Pure EKS deployments."""
    frontend_ecr_uri: Optional[str] = Field(None, description="ECR URI for frontend container image")
    backend_ecr_uri: Optional[str] = Field(None, description="ECR URI for backend container image")


class CapabilityRequirements(BaseModel):
    """Requirements for deploying a capability."""
    frontend: bool = Field(False, description="Requires frontend deployment")
    backend: bool = Field(False, description="Requires backend deployment")
    database: bool = Field(False, description="Requires database")
    authentication: bool = Field(False, description="Requires authentication")


class AWSOptions(BaseModel):
    """AWS deployment options for a capability."""
    frontend: List[str] = Field(default_factory=list, description="Frontend deployment options")
    backend: List[str] = Field(default_factory=list, description="Backend deployment options")


class Capability(BaseModel):
    """Complete capability definition."""
    id: str = Field(..., description="Unique capability identifier")
    name: str = Field(..., description="Display name")
    version: str = Field(..., description="Current version")
    description: str = Field(..., description="Capability description")
    icon: Optional[str] = Field(None, description="Icon filename")
    category: str = Field(..., description="Capability category")
    status: Optional[str] = Field(None, description="Capability status: available, coming_soon, deprecated")
    status_message: Optional[str] = Field(None, description="Status message to display")
    supported_clouds: List[str] = Field(default_factory=list, description="Supported cloud providers")
    supported_environments: List[str] = Field(default_factory=list, description="Supported environments")
    requirements: CapabilityRequirements = Field(..., description="Deployment requirements")
    artifacts: CapabilityArtifacts = Field(..., description="Deployment artifacts")
    eks_artifacts: Optional[EKSArtifacts] = Field(None, description="EKS-specific artifacts for Pure EKS deployments")
    aws_options: Optional[AWSOptions] = Field(None, description="AWS-specific options")
    estimated_deployment_time: int = Field(..., description="Estimated deployment time in minutes")
    documentation_url: Optional[str] = Field(None, description="Documentation URL")
    required_iam_permissions: List[str] = Field(default_factory=list, description="Required IAM permissions")
    eks_iam_permissions: List[str] = Field(default_factory=list, description="EKS-specific IAM permissions")
    prerequisites: List[str] = Field(default_factory=list, description="Prerequisites")


class CapabilityList(BaseModel):
    """List of capabilities."""
    capabilities: List[Capability] = Field(default_factory=list)


class CapabilityVersion(BaseModel):
    """Version information for a capability."""
    version: str = Field(..., description="Version number")
    release_date: str = Field(..., description="Release date")
    changelog: Optional[str] = Field(None, description="Version changelog")
