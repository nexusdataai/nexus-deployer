"""
Cognito-related data models for update workflow preservation.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field


class CognitoOutputs(BaseModel):
    """
    Cognito stack outputs that need to be preserved during updates.
    """
    user_pool_id: str = Field(
        description="Cognito User Pool ID"
    )
    user_pool_client_id: str = Field(
        description="Cognito User Pool Client ID"
    )
    user_pool_domain: str = Field(
        description="Cognito User Pool Domain for OAuth"
    )
    region: str = Field(
        description="AWS region where the User Pool is deployed"
    )
    admin_user_email: Optional[str] = Field(
        default=None,
        description="Default admin user email address"
    )
    callback_url: Optional[str] = Field(
        default=None,
        description="OAuth callback URL"
    )


class CognitoValidationResult(BaseModel):
    """
    Result of validating a Cognito User Pool.
    """
    is_valid: bool = Field(
        description="Whether the User Pool is valid and accessible"
    )
    user_pool_accessible: bool = Field(
        description="Whether the User Pool can be accessed via API"
    )
    client_configured: bool = Field(
        description="Whether the App Client is properly configured"
    )
    user_count: int = Field(
        default=0,
        description="Number of users in the User Pool"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if validation failed"
    )
    remediation_steps: Optional[List[str]] = Field(
        default=None,
        description="Steps to remediate validation failures"
    )
    validation_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the validation was performed"
    )


class UserExportRecord(BaseModel):
    """
    Record of a single user exported from Cognito.
    """
    username: str = Field(
        description="User's username (typically email)"
    )
    email: str = Field(
        description="User's email address"
    )
    attributes: Dict[str, str] = Field(
        default_factory=dict,
        description="User's custom attributes"
    )
    groups: List[str] = Field(
        default_factory=list,
        description="Groups the user belongs to"
    )
    enabled: bool = Field(
        default=True,
        description="Whether the user account is enabled"
    )
    status: str = Field(
        default="CONFIRMED",
        description="User's account status"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the user was created"
    )


class ExportResult(BaseModel):
    """
    Result of exporting users from a Cognito User Pool.
    """
    success: bool = Field(
        description="Whether the export was successful"
    )
    export_path: Optional[str] = Field(
        default=None,
        description="Path to the export file"
    )
    user_count: int = Field(
        default=0,
        description="Number of users exported"
    )
    export_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the export was performed"
    )
    capability_name: str = Field(
        description="Name of the capability"
    )
    environment: str = Field(
        description="Environment (dev, stage, prod)"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if export failed"
    )


class DriftItem(BaseModel):
    """
    A single configuration drift item between deployed and template.
    """
    setting_name: str = Field(
        description="Name of the setting that has drifted"
    )
    template_value: str = Field(
        description="Value defined in the template"
    )
    deployed_value: str = Field(
        description="Value currently deployed"
    )
    category: str = Field(
        description="Category of the setting (password_policy, mfa, app_client, custom_attributes)"
    )


class DriftDetectionResult(BaseModel):
    """
    Result of detecting configuration drift in Cognito.
    """
    has_drift: bool = Field(
        description="Whether any drift was detected"
    )
    drift_items: List[DriftItem] = Field(
        default_factory=list,
        description="List of detected drift items"
    )
    detection_timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When drift detection was performed"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if detection failed"
    )
    categories_checked: List[str] = Field(
        default_factory=lambda: ['password_policy', 'mfa', 'app_client', 'custom_attributes'],
        description="Categories that were checked for drift"
    )
