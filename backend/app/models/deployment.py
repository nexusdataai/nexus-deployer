"""
Deployment data models
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class DeploymentStatus(str, Enum):
    """Deployment status enum"""
    PENDING = "pending"
    INITIALIZING = "initializing"
    VALIDATING = "validating"
    DEPLOYING = "deploying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentStage(str, Enum):
    """Deployment stages"""
    INITIALIZATION = "initialization"
    ARTIFACT_VERIFICATION = "artifact_verification"
    INFRASTRUCTURE_PROVISIONING = "infrastructure_provisioning"  # NEW: Provision DynamoDB, S3, SSM, etc.
    FRONTEND_GLOBAL = "frontend_global"
    FRONTEND_COGNITO = "frontend_cognito"
    FRONTEND_REGIONAL = "frontend_regional"
    FRONTEND_UPLOAD = "frontend_upload"
    BACKEND_FOUNDATION = "backend_foundation"
    BACKEND_STORAGE = "backend_storage"
    BACKEND_NETWORK = "backend_network"
    BACKEND_SERVICE = "backend_service"
    VERIFICATION = "verification"
    COMPLETED = "completed"


class LogLevel(str, Enum):
    """Log level enum"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    DEBUG = "debug"


class DeploymentRequest(BaseModel):
    """Request to start a deployment"""
    capability_id: str
    capability_name: str
    capability_version: str
    environment: str
    region: str
    account_id: str
    role_arn: Optional[str] = None
    
    # AWS Session ID for stored credentials
    aws_session_id: Optional[str] = None
    
    # ADFS credentials for session persistence and re-authentication
    adfs_url: Optional[str] = None
    adfs_username: Optional[str] = None
    adfs_password: Optional[str] = None
    adfs_role_arn: Optional[str] = None
    auth_method: Optional[str] = None
    
    # Artifact sources
    frontend_s3_uri: Optional[str] = None
    backend_ecr_uri: Optional[str] = None
    
    # Deployment options
    deploy_frontend: bool = True
    deploy_backend: bool = True
    
    # Deployment strategy (clean_deploy or update_existing)
    deployment_strategy: Optional[str] = None
    
    # Infrastructure configuration (optional - will use saved config if not provided)
    infrastructure_config: Optional[Dict[str, Any]] = None
    
    # Legacy fields for backward compatibility
    base_domain: Optional[str] = None
    hosted_zone_id: Optional[str] = None
    frontend_subdomain: str = "app"
    container_port: int = 8080
    health_check_path: str = "/health"
    task_cpu: int = 1024
    task_memory: int = 2048
    desired_count: int = 2


class DeploymentLogEntry(BaseModel):
    """Single log entry"""
    timestamp: datetime
    level: LogLevel
    stage: Optional[str] = None
    message: str
    details: Optional[Dict[str, Any]] = None


class StackDeploymentInfo(BaseModel):
    """Information about a deployed stack"""
    stack_name: str
    stack_type: str
    status: str
    region: str
    outputs: Optional[Dict[str, str]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DeploymentResponse(BaseModel):
    """Response for deployment status"""
    deployment_id: str
    status: DeploymentStatus
    current_stage: Optional[DeploymentStage] = None
    progress: int = Field(ge=0, le=100, default=0)
    message: Optional[str] = None
    error: Optional[str] = None
    
    # Installation tracking
    installation_id: Optional[str] = None
    
    # Deployment details
    capability_name: str
    environment: str
    region: str
    
    # Timestamps
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Deployed stacks
    stacks: List[StackDeploymentInfo] = []
    
    # Deployment outputs
    frontend_url: Optional[str] = None
    backend_url: Optional[str] = None
    cognito_config: Optional[Dict[str, Any]] = None
    
    # Pre-deployment validation
    validation_report: Optional[Dict[str, Any]] = None
    validation_issues: Optional[List[Dict[str, Any]]] = None


class DeploymentLogsResponse(BaseModel):
    """Response for deployment logs"""
    deployment_id: str
    logs: List[DeploymentLogEntry]
    total_count: int
