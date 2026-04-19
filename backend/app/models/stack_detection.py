"""
Stack Detection data models
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime


# Stack state classification constants
UPDATABLE_STATES = {
    'CREATE_COMPLETE',
    'UPDATE_COMPLETE',
}

FAILED_STATES = {
    'ROLLBACK_COMPLETE',
    'UPDATE_ROLLBACK_COMPLETE',
    'DELETE_FAILED',
    'CREATE_FAILED',
}

IN_PROGRESS_STATES = {
    'CREATE_IN_PROGRESS',
    'UPDATE_IN_PROGRESS',
    'DELETE_IN_PROGRESS',
    'ROLLBACK_IN_PROGRESS',
    'UPDATE_ROLLBACK_IN_PROGRESS',
}

# Expected stack types with region mapping
FRONTEND_STACKS = {
    'frontend-global': 'us-east-1',     # Global resources must be in us-east-1
    'frontend-regional': 'target',      # Use target deployment region
}

BACKEND_STACKS = {
    'backend-foundation': 'target',     # Use target deployment region
    'backend-storage': 'target',        # Use target deployment region
    'backend-service': 'target',        # Use target deployment region
}


class DeploymentStrategy(str, Enum):
    """Deployment strategy options"""
    CLEAN_DEPLOY = "clean_deploy"
    UPDATE_EXISTING = "update_existing"


class ExistingStackInfo(BaseModel):
    """Information about an existing stack"""
    stack_name: str
    stack_type: str  # e.g., "frontend-global", "backend-service"
    stack_status: str  # Status from TinyDB or CloudFormation
    region: str
    created_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    is_updatable: bool = True
    status_reason: Optional[str] = None
    classification: str = "updatable"  # "updatable", "failed", or "in_progress"


class StackDetectionResult(BaseModel):
    """Result of stack detection operation"""
    capability_name: str
    environment: str
    region: str
    stacks_found: List[ExistingStackInfo] = []
    has_existing_stacks: bool
    has_failed_stacks: bool = False
    has_in_progress_stacks: bool = False
    is_updatable: bool = True
    recommended_strategy: Optional[DeploymentStrategy] = None
    recommendation_reason: str = ""
    detection_timestamp: datetime
    error_message: Optional[str] = None


class StackDetectionRequest(BaseModel):
    """Request to detect existing stacks"""
    capability_name: str
    environment: str
    region: str
    aws_session_id: Optional[str] = None
    deploy_frontend: bool = True
    deploy_backend: bool = True
