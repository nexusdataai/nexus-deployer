"""
Validation Report Generator Service
Generates comprehensive validation reports with remediation guidance.

Provides:
- ValidationReport dataclass with errors, warnings, info
- ValidationIssue dataclass with severity, category, remediation
- JSON serialization for API responses
- Human-readable formatting for UI display

Feature: deployment-prerequisites-verification
Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime


logger = logging.getLogger(__name__)


class Severity(Enum):
    """Severity levels for validation issues."""
    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


class Category(Enum):
    """Categories for validation issues."""
    PARAMETER = 'parameter'
    REFERENCE = 'reference'
    DEPENDENCY = 'dependency'
    STRUCTURE = 'structure'
    SYNTAX = 'syntax'
    LIMIT = 'limit'
    CREDENTIAL = 'credential'
    PREREQUISITE = 'prerequisite'


@dataclass
class ValidationIssue:
    """Represents a single validation issue with remediation guidance."""
    severity: Severity
    category: Category
    message: str
    location: Optional[str] = None
    remediation: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'severity': self.severity.value,
            'category': self.category.value,
            'message': self.message,
            'location': self.location,
            'remediation': self.remediation,
            'details': self.details
        }
    
    def format_for_display(self) -> str:
        """Format for human-readable display."""
        prefix = {
            Severity.ERROR: '❌ ERROR',
            Severity.WARNING: '⚠️ WARNING',
            Severity.INFO: 'ℹ️ INFO'
        }.get(self.severity, 'UNKNOWN')
        
        lines = [f"{prefix}: {self.message}"]
        if self.location:
            lines.append(f"   Location: {self.location}")
        if self.remediation:
            lines.append(f"   Fix: {self.remediation}")
        
        return '\n'.join(lines)


@dataclass
class ValidationReport:
    """Comprehensive validation report."""
    success: bool
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    info: List[ValidationIssue] = field(default_factory=list)
    summary: str = ""
    templates_validated: int = 0
    total_resources: int = 0
    deployment_order: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'timestamp': self.timestamp,
            'errors': [e.to_dict() for e in self.errors],
            'warnings': [w.to_dict() for w in self.warnings],
            'info': [i.to_dict() for i in self.info],
            'summary': self.summary,
            'templates_validated': self.templates_validated,
            'total_resources': self.total_resources,
            'deployment_order': self.deployment_order,
            'metadata': self.metadata,
            'counts': {
                'errors': len(self.errors),
                'warnings': len(self.warnings),
                'info': len(self.info)
            }
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def format_for_ui(self) -> str:
        """Format report for UI display."""
        lines = []
        
        # Header
        status = '✅ PASSED' if self.success else '❌ FAILED'
        lines.append(f"═══════════════════════════════════════")
        lines.append(f"  Validation Report - {status}")
        lines.append(f"═══════════════════════════════════════")
        lines.append(f"  Templates: {self.templates_validated}")
        lines.append(f"  Resources: {self.total_resources}")
        lines.append(f"  Timestamp: {self.timestamp}")
        lines.append("")
        
        # Errors
        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            lines.append("─" * 40)
            for error in self.errors:
                lines.append(error.format_for_display())
                lines.append("")
        
        # Warnings
        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            lines.append("─" * 40)
            for warning in self.warnings:
                lines.append(warning.format_for_display())
                lines.append("")
        
        # Info
        if self.info:
            lines.append(f"INFO ({len(self.info)}):")
            lines.append("─" * 40)
            for info_item in self.info:
                lines.append(info_item.format_for_display())
                lines.append("")
        
        # Deployment Order
        if self.deployment_order:
            lines.append("DEPLOYMENT ORDER:")
            lines.append("─" * 40)
            for i, stack in enumerate(self.deployment_order, 1):
                lines.append(f"  {i}. {stack}")
            lines.append("")
        
        # Summary
        lines.append("─" * 40)
        lines.append(f"Summary: {self.summary}")
        
        return '\n'.join(lines)
    
    def add_issue(self, issue: ValidationIssue):
        """Add an issue to the appropriate list based on severity."""
        if issue.severity == Severity.ERROR:
            self.errors.append(issue)
        elif issue.severity == Severity.WARNING:
            self.warnings.append(issue)
        else:
            self.info.append(issue)
    
    def merge(self, other: 'ValidationReport'):
        """Merge another report into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)
        self.templates_validated += other.templates_validated
        self.total_resources += other.total_resources
        
        # Update success status
        self.success = self.success and other.success and len(self.errors) == 0


class ValidationReportGenerator:
    """Generates comprehensive validation reports."""
    
    def create_report(
        self,
        templates_validated: int = 0,
        total_resources: int = 0
    ) -> ValidationReport:
        """Create a new validation report."""
        return ValidationReport(
            success=True,
            templates_validated=templates_validated,
            total_resources=total_resources
        )
    
    def add_parameter_error(
        self,
        report: ValidationReport,
        parameter_name: str,
        constraint_type: str,
        constraint_value: Any,
        actual_value: Any,
        template_name: str = ""
    ):
        """Add a parameter constraint violation error."""
        remediation = self._get_parameter_remediation(constraint_type, constraint_value)
        
        report.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            category=Category.PARAMETER,
            message=f"Parameter '{parameter_name}' violates {constraint_type} constraint",
            location=f"{template_name}.Parameters.{parameter_name}" if template_name else parameter_name,
            remediation=remediation,
            details={
                'constraint_type': constraint_type,
                'constraint_value': constraint_value,
                'actual_value': actual_value
            }
        ))
    
    def add_reference_error(
        self,
        report: ValidationReport,
        reference_type: str,
        target: str,
        location: str
    ):
        """Add an invalid reference error."""
        report.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            category=Category.REFERENCE,
            message=f"Invalid {reference_type} reference to '{target}'",
            location=location,
            remediation=f"Define '{target}' as a Parameter, Resource, or use a valid pseudo-parameter"
        ))
    
    def add_dependency_error(
        self,
        report: ValidationReport,
        import_name: str,
        importing_stack: str,
        suggested_source: Optional[str] = None
    ):
        """Add a missing dependency error."""
        remediation = f"Ensure export '{import_name}' exists before deploying {importing_stack}"
        if suggested_source:
            remediation += f" (deploy {suggested_source} first)"
        
        report.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            category=Category.DEPENDENCY,
            message=f"Missing export '{import_name}' required by {importing_stack}",
            location=importing_stack,
            remediation=remediation
        ))
    
    def add_circular_dependency_error(
        self,
        report: ValidationReport,
        cycle: List[str]
    ):
        """Add a circular dependency error."""
        cycle_str = ' → '.join(cycle)
        
        report.add_issue(ValidationIssue(
            severity=Severity.ERROR,
            category=Category.DEPENDENCY,
            message=f"Circular dependency detected: {cycle_str}",
            remediation="Restructure stack exports/imports to remove the circular dependency"
        ))
    
    def add_resource_warning(
        self,
        report: ValidationReport,
        message: str,
        location: str,
        remediation: Optional[str] = None
    ):
        """Add a resource-related warning."""
        report.add_issue(ValidationIssue(
            severity=Severity.WARNING,
            category=Category.REFERENCE,
            message=message,
            location=location,
            remediation=remediation
        ))
    
    def add_info(
        self,
        report: ValidationReport,
        message: str,
        category: Category = Category.STRUCTURE
    ):
        """Add an informational message."""
        report.add_issue(ValidationIssue(
            severity=Severity.INFO,
            category=category,
            message=message
        ))
    
    def finalize_report(self, report: ValidationReport) -> ValidationReport:
        """Finalize the report with summary and success status."""
        report.success = len(report.errors) == 0
        report.summary = self._generate_summary(report)
        return report
    
    def _get_parameter_remediation(
        self,
        constraint_type: str,
        constraint_value: Any
    ) -> str:
        """Get remediation advice for parameter constraint violations."""
        remediations = {
            'AllowedValues': f"Use one of the allowed values: {constraint_value}",
            'MinLength': f"Provide a value with at least {constraint_value} characters",
            'MaxLength': f"Provide a value with at most {constraint_value} characters",
            'AllowedPattern': f"Provide a value matching the pattern: {constraint_value}",
            'MinValue': f"Provide a value >= {constraint_value}",
            'MaxValue': f"Provide a value <= {constraint_value}",
            'Type': f"Provide a value of type {constraint_value}"
        }
        return remediations.get(constraint_type, f"Fix the {constraint_type} constraint violation")
    
    def _generate_summary(self, report: ValidationReport) -> str:
        """Generate a human-readable summary."""
        parts = []
        
        if report.success:
            parts.append("Validation passed")
        else:
            parts.append("Validation failed")
        
        parts.append(f"{report.templates_validated} templates")
        parts.append(f"{report.total_resources} resources")
        
        if report.errors:
            parts.append(f"{len(report.errors)} errors")
        
        if report.warnings:
            parts.append(f"{len(report.warnings)} warnings")
        
        return ", ".join(parts)


def get_validation_report_generator() -> ValidationReportGenerator:
    """Factory function to get a ValidationReportGenerator instance."""
    return ValidationReportGenerator()
