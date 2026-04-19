"""
Stack output preservation data models for update workflow.
"""
from typing import Optional, Dict
from datetime import datetime
from pydantic import BaseModel, Field


class PreservedOutputs(BaseModel):
    """
    Preserved outputs from a CloudFormation stack.
    """
    stack_name: str = Field(
        description="Name of the CloudFormation stack"
    )
    outputs: Dict[str, str] = Field(
        default_factory=dict,
        description="Stack outputs as key-value pairs"
    )
    retrieved_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the outputs were retrieved"
    )
    is_cognito_stack: bool = Field(
        default=False,
        description="Whether this is the Cognito stack"
    )
    stack_status: Optional[str] = Field(
        default=None,
        description="CloudFormation stack status when retrieved"
    )
    capability_name: Optional[str] = Field(
        default=None,
        description="Name of the capability this stack belongs to"
    )
    environment: Optional[str] = Field(
        default=None,
        description="Environment (dev, stage, prod)"
    )
    region: Optional[str] = Field(
        default=None,
        description="AWS region"
    )
