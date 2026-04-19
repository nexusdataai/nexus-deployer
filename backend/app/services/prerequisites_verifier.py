"""
Prerequisites Verifier Service
Orchestrates all pre-deployment validation checks.

Combines:
- Parameter constraint validation
- Reference validation (no false positives)
- Cross-stack dependency validation
- Pre-deployment checklist
- Comprehensive report generation

Feature: deployment-prerequisites-verification
Requirements: 1.6, 1.7, 5.1, 5.2, 5.3
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

from app.utils.cfn_yaml_loader import load_cfn_yaml, load_cfn_yaml_file
from app.services.parameter_constraint_extractor import ParameterConstraintExtractor
from app.services.parameter_value_validator import ParameterValueValidator
from app.services.reference_validator import ReferenceValidator
from app.services.cross_stack_dependency_checker import CrossStackDependencyChecker
from app.services.pre_deployment_checklist import PreDeploymentChecklist, CheckStatus
from app.services.validation_report_generator import (
    ValidationReportGenerator,
    ValidationReport,
    ValidationIssue,
    Severity,
    Category
)


logger = logging.getLogger(__name__)


@dataclass
class PrerequisitesResult:
    """Result of prerequisites verification."""
    success: bool
    can_deploy: bool  # True if no blocking errors
    report: ValidationReport
    checklist_passed: bool = True
    parameter_validation_passed: bool = True
    reference_validation_passed: bool = True
    dependency_validation_passed: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'can_deploy': self.can_deploy,
            'report': self.report.to_dict(),
            'checklist_passed': self.checklist_passed,
            'parameter_validation_passed': self.parameter_validation_passed,
            'reference_validation_passed': self.reference_validation_passed,
            'dependency_validation_passed': self.dependency_validation_passed
        }


class PrerequisitesVerifier:
    """Orchestrates all pre-deployment validation checks."""
    
    def __init__(self):
        self.constraint_extractor = ParameterConstraintExtractor()
        self.parameter_validator = ParameterValueValidator()
        self.reference_validator = ReferenceValidator()
        self.dependency_checker = CrossStackDependencyChecker()
        self.checklist = PreDeploymentChecklist()
        self.report_generator = ValidationReportGenerator()
    
    def verify_prerequisites(
        self,
        templates: Dict[str, Path],
        parameters: Optional[Dict[str, Dict[str, str]]] = None,
        region: str = "us-east-1",
        credentials: Optional[Dict[str, str]] = None,
        existing_exports: Optional[Set[str]] = None,
        secret_names: Optional[List[str]] = None,
        ssm_parameters: Optional[List[str]] = None,
        s3_bucket: Optional[str] = None,
        skip_aws_checks: bool = False
    ) -> PrerequisitesResult:
        """
        Run all prerequisite verifications.
        
        Args:
            templates: Map of stack name to template path
            parameters: Map of stack name to parameter values
            region: AWS region for deployment
            credentials: Optional AWS credentials
            existing_exports: Optional set of existing CloudFormation exports
            secret_names: Optional list of required secrets
            ssm_parameters: Optional list of required SSM parameters
            s3_bucket: Optional S3 bucket for templates
            skip_aws_checks: Skip AWS API checks (for offline validation)
            
        Returns:
            PrerequisitesResult with comprehensive validation results
        """
        parameters = parameters or {}
        
        # Create report
        report = self.report_generator.create_report(
            templates_validated=len(templates)
        )
        
        result = PrerequisitesResult(
            success=True,
            can_deploy=True,
            report=report
        )
        
        # Parse all templates
        parsed_templates: Dict[str, Dict[str, Any]] = {}
        total_resources = 0
        
        for stack_name, template_path in templates.items():
            try:
                template = load_cfn_yaml_file(template_path)
                parsed_templates[stack_name] = template
                total_resources += len(template.get('Resources', {}))
            except Exception as e:
                report.add_issue(ValidationIssue(
                    severity=Severity.ERROR,
                    category=Category.SYNTAX,
                    message=f"Failed to parse template {stack_name}: {str(e)}",
                    location=str(template_path),
                    remediation="Fix the YAML syntax error in the template"
                ))
                result.success = False
                result.can_deploy = False
        
        report.total_resources = total_resources
        
        # 1. Run pre-deployment checklist (AWS checks)
        if not skip_aws_checks:
            checklist_result = self.checklist.run_checklist(
                region=region,
                template_paths=list(templates.values()),
                secret_names=secret_names,
                ssm_parameters=ssm_parameters,
                s3_bucket=s3_bucket,
                credentials=credentials
            )
            
            result.checklist_passed = checklist_result.success
            
            for check in checklist_result.checks:
                if check.status == CheckStatus.FAILED:
                    report.add_issue(ValidationIssue(
                        severity=Severity.ERROR,
                        category=Category.PREREQUISITE,
                        message=f"{check.name}: {check.message}",
                        remediation=check.remediation
                    ))
                elif check.status == CheckStatus.WARNING:
                    report.add_issue(ValidationIssue(
                        severity=Severity.WARNING,
                        category=Category.PREREQUISITE,
                        message=f"{check.name}: {check.message}",
                        remediation=check.remediation
                    ))
                elif check.status == CheckStatus.PASSED:
                    report.add_issue(ValidationIssue(
                        severity=Severity.INFO,
                        category=Category.PREREQUISITE,
                        message=f"{check.name}: {check.message}"
                    ))
            
            if not checklist_result.success:
                result.success = False
                result.can_deploy = False
        
        # 2. Validate parameters for each template
        for stack_name, template in parsed_templates.items():
            stack_params = parameters.get(stack_name, {})
            
            param_result = self.parameter_validator.validate_all_parameters(
                template, stack_params
            )
            
            if not param_result.success:
                result.parameter_validation_passed = False
                result.success = False
                result.can_deploy = False
                
                for error in param_result.errors:
                    self.report_generator.add_parameter_error(
                        report,
                        parameter_name=error.parameter_name,
                        constraint_type=error.constraint_type or 'Unknown',
                        constraint_value=error.constraint_value,
                        actual_value=error.configured_value,
                        template_name=stack_name
                    )
        
        # 3. Validate references (fix false positives)
        for stack_name, template in parsed_templates.items():
            ref_result = self.reference_validator.validate_all_references(template)
            
            if not ref_result.success:
                result.reference_validation_passed = False
                result.success = False
                result.can_deploy = False
                
                for invalid_ref in ref_result.invalid_refs:
                    self.report_generator.add_reference_error(
                        report,
                        reference_type=invalid_ref.reference_type,
                        target=invalid_ref.target,
                        location=f"{stack_name}.{invalid_ref.location}"
                    )
                
                for invalid_getatt in ref_result.invalid_getatt:
                    self.report_generator.add_reference_error(
                        report,
                        reference_type='GetAtt',
                        target=invalid_getatt.target,
                        location=f"{stack_name}.{invalid_getatt.location}"
                    )
            
            # Log valid resource refs (these would have been false positives before)
            if ref_result.valid_resource_refs:
                logger.debug(
                    f"Template {stack_name} has {len(ref_result.valid_resource_refs)} "
                    f"valid resource references: {ref_result.valid_resource_refs}"
                )
        
        # 4. Validate cross-stack dependencies
        dep_result = self.dependency_checker.check_dependencies(
            parsed_templates, existing_exports
        )
        
        if not dep_result.success:
            result.dependency_validation_passed = False
            result.success = False
            result.can_deploy = False
            
            for missing in dep_result.missing_exports:
                self.report_generator.add_dependency_error(
                    report,
                    import_name=missing.import_name,
                    importing_stack=missing.importing_stack,
                    suggested_source=missing.suggested_source
                )
            
            for cycle in dep_result.circular_dependencies:
                self.report_generator.add_circular_dependency_error(report, cycle)
        
        # Set deployment order
        report.deployment_order = dep_result.deployment_order
        
        # Finalize report
        self.report_generator.finalize_report(report)
        result.report = report
        
        return result
    
    def verify_single_template(
        self,
        template_path: Path,
        parameters: Optional[Dict[str, str]] = None,
        stack_name: str = "Template"
    ) -> PrerequisitesResult:
        """
        Verify prerequisites for a single template.
        
        Args:
            template_path: Path to the template file
            parameters: Parameter values
            stack_name: Name for the stack
            
        Returns:
            PrerequisitesResult with validation results
        """
        return self.verify_prerequisites(
            templates={stack_name: template_path},
            parameters={stack_name: parameters or {}},
            skip_aws_checks=True
        )
    
    def quick_validate(
        self,
        template: Dict[str, Any],
        parameters: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Quick validation of a parsed template without AWS checks.
        
        Args:
            template: Parsed CloudFormation template
            parameters: Parameter values
            
        Returns:
            Dict with validation results
        """
        parameters = parameters or {}
        
        # Parameter validation
        param_result = self.parameter_validator.validate_all_parameters(
            template, parameters
        )
        
        # Reference validation
        ref_result = self.reference_validator.validate_all_references(template)
        
        return {
            'success': param_result.success and ref_result.success,
            'parameter_errors': [e.to_dict() for e in param_result.errors],
            'reference_errors': [
                r.to_dict() for r in ref_result.invalid_refs + ref_result.invalid_getatt
            ],
            'valid_resource_refs': ref_result.valid_resource_refs,
            'valid_parameter_refs': ref_result.valid_parameter_refs
        }


def get_prerequisites_verifier() -> PrerequisitesVerifier:
    """Factory function to get a PrerequisitesVerifier instance."""
    return PrerequisitesVerifier()
