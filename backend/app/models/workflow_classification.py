"""
Workflow Classification data models for differentiating install and update workflows.
"""
from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class WorkflowType(str, Enum):
    """Workflow type classification for deployment operations."""
    INSTALL = "install"
    UPDATE = "update"


class WorkflowClassification(BaseModel):
    """
    Classification result for a deployment workflow.
    
    Determines whether a deployment should follow the install workflow
    (full deployment) or update workflow (preserve existing data).
    """
    workflow_type: WorkflowType = Field(
        description="The classified workflow type (install or update)"
    )
    capability_name: str = Field(
        description="Name of the capability being deployed"
    )
    environment: str = Field(
        description="Target environment (dev, stage, prod)"
    )
    region: str = Field(
        description="AWS region for deployment"
    )
    existing_stacks: List[str] = Field(
        default_factory=list,
        description="List of existing stack names found during detection"
    )
    strategy_selected: Optional[str] = Field(
        default=None,
        description="User-selected deployment strategy (clean_deploy or update_existing)"
    )
    classification_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when classification was performed"
    )
    reason: str = Field(
        default="",
        description="Human-readable reason for the classification"
    )

    class Config:
        use_enum_values = True

    def is_update(self) -> bool:
        """Check if this is an update workflow."""
        return self.workflow_type == WorkflowType.UPDATE

    def is_install(self) -> bool:
        """Check if this is an install workflow."""
        return self.workflow_type == WorkflowType.INSTALL
