"""
Update workflow result data models.
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class UpdateResult(BaseModel):
    """
    Result of an update workflow execution.
    """
    success: bool = Field(
        description="Whether the update completed successfully"
    )
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
    cognito_preserved: bool = Field(
        default=False,
        description="Whether Cognito was preserved"
    )
    user_backup_path: Optional[str] = Field(
        default=None,
        description="Path to user data backup file"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if update failed"
    )
    drift_detected: bool = Field(
        default=False,
        description="Whether configuration drift was detected"
    )
    drift_summary: Optional[str] = Field(
        default=None,
        description="Summary of detected drift"
    )
    validation_passed: bool = Field(
        default=True,
        description="Whether pre/post validation passed"
    )
    validation_message: Optional[str] = Field(
        default=None,
        description="Validation failure message"
    )
    operation_id: Optional[str] = Field(
        default=None,
        description="Audit trail operation ID"
    )

    @property
    def total_stacks(self) -> int:
        """Total number of stacks processed."""
        return (
            len(self.stacks_updated) + 
            len(self.stacks_preserved) + 
            len(self.stacks_failed)
        )

    @property
    def has_failures(self) -> bool:
        """Whether any stacks failed."""
        return len(self.stacks_failed) > 0

    def to_summary(self) -> str:
        """Generate a human-readable summary."""
        lines = []
        
        if self.success:
            lines.append("Update completed successfully.")
        else:
            lines.append(f"Update failed: {self.error_message or 'Unknown error'}")
        
        lines.append(f"  Updated: {len(self.stacks_updated)} stacks")
        lines.append(f"  Preserved: {len(self.stacks_preserved)} stacks")
        
        if self.stacks_failed:
            lines.append(f"  Failed: {len(self.stacks_failed)} stacks")
        
        if self.cognito_preserved:
            lines.append("  Cognito User Pool: Preserved")
        
        if self.user_backup_path:
            lines.append(f"  User backup: {self.user_backup_path}")
        
        if self.drift_detected:
            lines.append(f"  Drift detected: {self.drift_summary or 'Yes'}")
        
        return '\n'.join(lines)
