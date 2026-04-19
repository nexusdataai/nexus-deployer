"""
Validation data models for pre-deployment validation system
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


class StackStatus(str, Enum):
    """Stack status categories"""
    NOT_EXISTS = "not_exists"
    STABLE = "stable"  # CREATE_COMPLETE, UPDATE_COMPLETE
    UNSTABLE = "unstable"  # ROLLBACK_COMPLETE, DELETE_FAILED, etc.
    IN_PROGRESS = "in_progress"  # CREATE_IN_PROGRESS, UPDATE_IN_PROGRESS


class IssueType(str, Enum):
    """Type of validation issue"""
    UNSTABLE_STACK = "unstable_stack"
    ORPHANED_RESOURCE = "orphaned_resource"


class Severity(str, Enum):
    """Severity level of validation issue"""
    CRITICAL = "critical"
    WARNING = "warning"


class ResourceDefinition(BaseModel):
    """CloudFormation resource definition"""
    logical_id: str
    resource_type: str
    properties: Dict[str, Any]
    deletion_policy: Optional[str] = None


class OrphanedResource(BaseModel):
    """Detected orphaned resource"""
    resource_type: str
    resource_identifier: str
    region: str
    stack_name: str
    detected_at: datetime


class ValidationIssue(BaseModel):
    """Single validation issue"""
    issue_type: IssueType
    severity: Severity
    stack_name: Optional[str] = None
    resource_type: Optional[str] = None
    resource_identifier: str
    description: str
    resolved: bool = False
    resolution_details: Optional[str] = None


class ValidationReport(BaseModel):
    """Report from pre-deployment validation"""
    success: bool
    issues_found: List[ValidationIssue] = []
    issues_resolved: List[ValidationIssue] = []
    issues_unresolved: List[ValidationIssue] = []
    validation_time: float
    summary: str
