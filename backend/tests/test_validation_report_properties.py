"""
Property Tests for Validation Report Generator
Tests comprehensive validation report generation.

Feature: deployment-prerequisites-verification
Requirements: 5.1, 5.2, 5.3
"""
import pytest
from hypothesis import given, strategies as st, settings

from app.services.validation_report_generator import (
    ValidationReportGenerator,
    ValidationReport,
    ValidationIssue,
    Severity,
    Category
)


class TestValidationReportCompleteness:
    """Property 9: Validation Report Completeness (Requirements 5.1, 5.2, 5.3)"""
    
    def test_report_contains_all_added_errors(self):
        """All added errors appear in the report."""
        generator = ValidationReportGenerator()
        report = generator.create_report(templates_validated=3)
        
        # Add multiple errors
        generator.add_parameter_error(
            report,
            parameter_name="LogRetentionDays",
            constraint_type="AllowedValues",
            constraint_value=[1, 7, 14, 30],
            actual_value=10,
            template_name="TestStack"
        )
        
        generator.add_reference_error(
            report,
            reference_type="Ref",
            target="UndefinedResource",
            location="Resources.MyResource.Properties"
        )
        
        generator.add_dependency_error(
            report,
            import_name="Network-VpcId",
            importing_stack="AppStack",
            suggested_source="NetworkStack"
        )
        
        assert len(report.errors) == 3
        
        # Verify each error type is present
        error_categories = {e.category for e in report.errors}
        assert Category.PARAMETER in error_categories
        assert Category.REFERENCE in error_categories
        assert Category.DEPENDENCY in error_categories
    
    def test_report_success_reflects_errors(self):
        """Report success is False when errors exist."""
        generator = ValidationReportGenerator()
        report = generator.create_report()
        
        # Initially successful
        assert report.success is True
        
        # Add an error
        generator.add_parameter_error(
            report, "Param", "MinLength", 1, "", "Stack"
        )
        
        # Finalize
        generator.finalize_report(report)
        
        assert report.success is False
    
    def test_report_success_with_only_warnings(self):
        """Report success is True when only warnings exist."""
        generator = ValidationReportGenerator()
        report = generator.create_report()
        
        generator.add_resource_warning(
            report,
            message="Resource might be expensive",
            location="Resources.ExpensiveResource"
        )
        
        generator.finalize_report(report)
        
        assert report.success is True
        assert len(report.warnings) == 1
    
    def test_report_json_serialization(self):
        """Report can be serialized to JSON."""
        generator = ValidationReportGenerator()
        report = generator.create_report(templates_validated=2, total_resources=10)
        
        generator.add_parameter_error(
            report, "Param", "AllowedValues", ["a", "b"], "c", "Stack"
        )
        generator.add_info(report, "Deployment will use 2 stacks")
        generator.finalize_report(report)
        
        json_str = report.to_json()
        
        assert '"success": false' in json_str
        assert '"templates_validated": 2' in json_str
        assert '"total_resources": 10' in json_str
    
    def test_report_ui_formatting(self):
        """Report can be formatted for UI display."""
        generator = ValidationReportGenerator()
        report = generator.create_report(templates_validated=1)
        
        generator.add_parameter_error(
            report, "Environment", "AllowedValues", ["dev", "prod"], "invalid", "MyStack"
        )
        generator.finalize_report(report)
        
        ui_output = report.format_for_ui()
        
        assert "FAILED" in ui_output
        assert "ERROR" in ui_output
        assert "Environment" in ui_output
        assert "AllowedValues" in ui_output
    
    def test_report_merge(self):
        """Reports can be merged together."""
        generator = ValidationReportGenerator()
        
        report1 = generator.create_report(templates_validated=1, total_resources=5)
        generator.add_parameter_error(report1, "P1", "MinLength", 1, "", "S1")
        
        report2 = generator.create_report(templates_validated=2, total_resources=10)
        generator.add_reference_error(report2, "Ref", "Target", "Location")
        
        report1.merge(report2)
        
        assert report1.templates_validated == 3
        assert report1.total_resources == 15
        assert len(report1.errors) == 2
    
    @given(
        num_errors=st.integers(min_value=0, max_value=10),
        num_warnings=st.integers(min_value=0, max_value=10)
    )
    @settings(max_examples=20)
    def test_report_counts_match_issues(self, num_errors, num_warnings):
        """Report counts match actual issue counts."""
        generator = ValidationReportGenerator()
        report = generator.create_report()
        
        for i in range(num_errors):
            generator.add_parameter_error(
                report, f"Param{i}", "MinLength", 1, "", "Stack"
            )
        
        for i in range(num_warnings):
            generator.add_resource_warning(
                report, f"Warning {i}", f"Location{i}"
            )
        
        assert len(report.errors) == num_errors
        assert len(report.warnings) == num_warnings
        
        report_dict = report.to_dict()
        assert report_dict['counts']['errors'] == num_errors
        assert report_dict['counts']['warnings'] == num_warnings


class TestValidationIssue:
    """Tests for ValidationIssue formatting."""
    
    def test_issue_to_dict(self):
        """Issue can be converted to dictionary."""
        issue = ValidationIssue(
            severity=Severity.ERROR,
            category=Category.PARAMETER,
            message="Test error",
            location="Stack.Parameters.Test",
            remediation="Fix it"
        )
        
        d = issue.to_dict()
        
        assert d['severity'] == 'error'
        assert d['category'] == 'parameter'
        assert d['message'] == "Test error"
        assert d['location'] == "Stack.Parameters.Test"
        assert d['remediation'] == "Fix it"
    
    def test_issue_display_format(self):
        """Issue can be formatted for display."""
        issue = ValidationIssue(
            severity=Severity.WARNING,
            category=Category.REFERENCE,
            message="Possible issue",
            location="Resources.MyResource",
            remediation="Check the reference"
        )
        
        display = issue.format_for_display()
        
        assert "WARNING" in display
        assert "Possible issue" in display
        assert "Resources.MyResource" in display
        assert "Check the reference" in display


class TestCircularDependencyReporting:
    """Tests for circular dependency error reporting."""
    
    def test_circular_dependency_error_format(self):
        """Circular dependency errors are properly formatted."""
        generator = ValidationReportGenerator()
        report = generator.create_report()
        
        cycle = ["StackA", "StackB", "StackC", "StackA"]
        generator.add_circular_dependency_error(report, cycle)
        
        assert len(report.errors) == 1
        error = report.errors[0]
        
        assert error.category == Category.DEPENDENCY
        assert "StackA → StackB → StackC → StackA" in error.message
        assert "circular" in error.remediation.lower()


class TestRemediationGuidance:
    """Tests for remediation guidance generation."""
    
    @pytest.mark.parametrize("constraint_type,expected_text", [
        ("AllowedValues", "allowed values"),
        ("MinLength", "at least"),
        ("MaxLength", "at most"),
        ("AllowedPattern", "pattern"),
        ("MinValue", ">="),
        ("MaxValue", "<="),
    ])
    def test_parameter_remediation_contains_guidance(self, constraint_type, expected_text):
        """Parameter remediations contain appropriate guidance."""
        generator = ValidationReportGenerator()
        report = generator.create_report()
        
        generator.add_parameter_error(
            report,
            parameter_name="TestParam",
            constraint_type=constraint_type,
            constraint_value="test_value",
            actual_value="bad_value",
            template_name="TestStack"
        )
        
        assert len(report.errors) == 1
        assert expected_text in report.errors[0].remediation.lower()
