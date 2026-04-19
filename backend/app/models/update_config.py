"""
Update workflow configuration data models.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class UpdateWorkflowConfig(BaseModel):
    """
    Configuration for update workflow behavior.
    These are system-level defaults that can be overridden per-operation.
    """
    # Cognito preservation settings
    default_preserve_cognito: bool = Field(
        default=True,
        description="Default to preserving Cognito during updates"
    )
    require_backup_before_cognito_update: bool = Field(
        default=True,
        description="Require user data backup before Cognito updates"
    )
    
    # Selective update settings
    enable_selective_updates: bool = Field(
        default=True,
        description="Allow selecting specific stacks to update"
    )
    
    # Validation settings
    validate_cognito_before_update: bool = Field(
        default=True,
        description="Validate Cognito User Pool before update"
    )
    validate_cognito_after_update: bool = Field(
        default=True,
        description="Validate Cognito User Pool after update"
    )
    
    # Drift detection settings
    enable_drift_detection: bool = Field(
        default=True,
        description="Enable Cognito drift detection"
    )
    
    # Audit settings
    enable_audit_trail: bool = Field(
        default=True,
        description="Enable audit trail for update operations"
    )


class UpdateConfig(BaseModel):
    """
    Per-operation update configuration.
    Overrides system defaults for a specific update operation.
    """
    preserve_cognito: bool = Field(
        default=True,
        description="Whether to preserve Cognito during this update"
    )
    include_cognito_update: bool = Field(
        default=False,
        description="Whether to include Cognito in the update"
    )
    require_user_backup: bool = Field(
        default=True,
        description="Whether to require user backup before Cognito update"
    )
    selected_stacks: Optional[List[str]] = Field(
        default=None,
        description="Specific stacks to update (None = all stacks)"
    )
    skip_drift_detection: bool = Field(
        default=False,
        description="Skip drift detection for this update"
    )
    skip_pre_validation: bool = Field(
        default=False,
        description="Skip pre-update Cognito validation"
    )
    skip_post_validation: bool = Field(
        default=False,
        description="Skip post-update Cognito validation"
    )


def apply_defaults(
    update_config: UpdateConfig,
    workflow_config: UpdateWorkflowConfig
) -> UpdateConfig:
    """
    Apply workflow defaults to update config where not explicitly set.
    
    Args:
        update_config: Per-operation config
        workflow_config: System defaults
        
    Returns:
        UpdateConfig with defaults applied
    """
    # Create a copy with defaults applied
    return UpdateConfig(
        preserve_cognito=update_config.preserve_cognito,
        include_cognito_update=update_config.include_cognito_update,
        require_user_backup=(
            update_config.require_user_backup 
            if update_config.include_cognito_update 
            else workflow_config.require_backup_before_cognito_update
        ),
        selected_stacks=update_config.selected_stacks,
        skip_drift_detection=(
            update_config.skip_drift_detection 
            or not workflow_config.enable_drift_detection
        ),
        skip_pre_validation=(
            update_config.skip_pre_validation 
            or not workflow_config.validate_cognito_before_update
        ),
        skip_post_validation=(
            update_config.skip_post_validation 
            or not workflow_config.validate_cognito_after_update
        )
    )
