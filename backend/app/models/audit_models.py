"""
Audit trail data models for update workflow operations.
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class UpdateAuditRecord(BaseModel):
    """
    Audit trail record for update operations.
    """
    # Operation identification
    operation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this operation"
    )
    operation_type: str = Field(
        default="update",
        description="Type of operation (update, install)"
    )
    
    # Deployment context
    capability_name: str = Field(
        description="Name of the capability being updated"
    )
    environment: str = Field(
        description="Environment (dev, stage, prod)"
    )
    region: str = Field(
        description="AWS region"
    )
    
    # Operator information
    operator_identity: Optional[str] = Field(
        default=None,
        description="Identity of the operator performing the update"
    )
    
    # Timing
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the operation started"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the operation completed"
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        description="Total duration in seconds"
    )
    
    # Stack actions
    stacks_updated: List[str] = Field(
        default_factory=list,
        description="Stacks that were successfully updated"
    )
    stacks_preserved: List[str] = Field(
        default_factory=list,
        description="Stacks that were preserved (skipped)"
    )
    stacks_failed: List[str] = Field(
        default_factory=list,
        description="Stacks that failed to update"
    )
    
    # Cognito specific
    cognito_preserved: bool = Field(
        default=False,
        description="Whether Cognito was preserved"
    )
    user_data_exported: bool = Field(
        default=False,
        description="Whether user data was exported"
    )
    export_location: Optional[str] = Field(
        default=None,
        description="Path to user data export file"
    )
    export_user_count: Optional[int] = Field(
        default=None,
        description="Number of users exported"
    )
    
    # Drift detection
    drift_detected: bool = Field(
        default=False,
        description="Whether configuration drift was detected"
    )
    drift_items_count: int = Field(
        default=0,
        description="Number of drift items found"
    )
    
    # Result
    success: bool = Field(
        default=False,
        description="Whether the operation succeeded"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if operation failed"
    )
    
    # Configuration used
    config_preserve_cognito: bool = Field(
        default=True,
        description="preserve_cognito setting used"
    )
    config_include_cognito_update: bool = Field(
        default=False,
        description="include_cognito_update setting used"
    )
    config_selected_stacks: Optional[List[str]] = Field(
        default=None,
        description="selected_stacks setting used"
    )

    def complete(
        self,
        success: bool,
        error_message: Optional[str] = None
    ) -> None:
        """
        Mark the operation as complete.
        
        Args:
            success: Whether operation succeeded
            error_message: Error message if failed
        """
        self.completed_at = datetime.utcnow()
        self.success = success
        self.error_message = error_message
        
        if self.timestamp and self.completed_at:
            delta = self.completed_at - self.timestamp
            self.duration_seconds = delta.total_seconds()

    def add_updated_stack(self, stack_name: str) -> None:
        """Add a stack to the updated list."""
        if stack_name not in self.stacks_updated:
            self.stacks_updated.append(stack_name)

    def add_preserved_stack(self, stack_name: str) -> None:
        """Add a stack to the preserved list."""
        if stack_name not in self.stacks_preserved:
            self.stacks_preserved.append(stack_name)

    def add_failed_stack(self, stack_name: str) -> None:
        """Add a stack to the failed list."""
        if stack_name not in self.stacks_failed:
            self.stacks_failed.append(stack_name)

    def set_export_details(
        self,
        exported: bool,
        location: Optional[str] = None,
        user_count: Optional[int] = None
    ) -> None:
        """Set user data export details."""
        self.user_data_exported = exported
        self.export_location = location
        self.export_user_count = user_count

    def set_drift_details(
        self,
        detected: bool,
        items_count: int = 0
    ) -> None:
        """Set drift detection details."""
        self.drift_detected = detected
        self.drift_items_count = items_count

    def to_summary(self) -> dict:
        """Generate a summary dict for logging/display."""
        return {
            'operation_id': self.operation_id,
            'capability': self.capability_name,
            'environment': self.environment,
            'success': self.success,
            'stacks_updated': len(self.stacks_updated),
            'stacks_preserved': len(self.stacks_preserved),
            'stacks_failed': len(self.stacks_failed),
            'cognito_preserved': self.cognito_preserved,
            'duration_seconds': self.duration_seconds
        }
