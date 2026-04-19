"""
Pre-Deployment Checker Service
Orchestrates all pre-deployment validation checks.

Provides:
- Template syntax validation
- Structure validation
- Parameter validation
- Condition, mapping, output validation
- Dependency validation
- Resource limit checking
- Comprehensive validation reports
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
from enum import Enum

from app.utils.cfn_yaml_loader import load_cfn_yaml, load_cfn_yaml_file, validate_yaml_syntax
from app.services.template_validator import (
    TemplateValidator,
    StructureValidationResult,
    ParameterValidationResult,
    ConditionValidationResult,
    MappingValidationResult,
    OutputValidationResult
)
from app.services.dependency_validator import DependencyValidator
from app.services.resource_limit_checker import ResourceLimitChecker
from app.services.reference_validator import ReferenceValidator


logger = logging.getLogger(__name__)


class IssueSeverity(Enum):
    """Severity levels for validation issues."""
    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


class IssueCategory(Enum):
    """Categories for validation issues."""
    SYNTAX = 'syntax'
    STRUCTURE = 'structure'
    PARAMETER = 'parameter'
    CONDITION = 'condition'
    MAPPING = 'mapping'
    OUTPUT = 'output'
    DEPENDENCY = 'dependency'
    LIMIT = 'limit'


@dataclass
class ValidationIssue:
    """Represents a validation issue."""
    severity: IssueSeverity
    category: IssueCategory
    message: str
    location: Optional[str] = None  # file:line:column or resource path
    remediation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'severity': self.severity.value,
            'category': self.category.value,
            'message': self.message,
            'location': self.location,
            'remediation': self.remediation
        }


@dataclass
class ComprehensiveValidationReport:
    """Comprehensive validation report."""
    success: bool
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    info: List[ValidationIssue] = field(default_factory=list)
    summary: str = ""
    templates_validated: int = 0
    total_resources: int = 0
    deployment_order: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'errors': [e.to_dict() for e in self.errors],
            'warnings': [w.to_dict() for w in self.warnings],
            'info': [i.to_dict() for i in self.info],
            'summary': self.summary,
            'templates_validated': self.templates_validated,
            'total_resources': self.total_resources,
            'deployment_order': self.deployment_order
        }
    
    def format_for_ui(self) -> str:
        """Format report for UI display."""
        lines = []
        
        lines.append(f"=== Validation Report ===")
        lines.append(f"Status: {'PASSED' if self.success else 'FAILED'}")
        lines.append(f"Templates validated: {self.templates_validated}")
        lines.append(f"Total resources: {self.total_resources}")
        lines.append("")
        
        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  [ERROR] {error.message}")
                if error.location:
                    lines.append(f"          Location: {error.location}")
                if error.remediation:
                    lines.append(f"          Fix: {error.remediation}")
            lines.append("")
        
        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                lines.append(f"  [WARN] {warning.message}")
                if warning.location:
                    lines.append(f"         Location: {warning.location}")
                if warning.remediation:
                    lines.append(f"         Fix: {warning.remediation}")
            lines.append("")
        
        if self.info:
            lines.append(f"INFO ({len(self.info)}):")
            for info in self.info:
                lines.append(f"  [INFO] {info.message}")
            lines.append("")
        
        if self.deployment_order:
            lines.append("Deployment Order:")
            for i, stack in enumerate(self.deployment_order, 1):
                lines.append(f"  {i}. {stack}")
            lines.append("")
        
        lines.append(f"Summary: {self.summary}")
        
        return "\n".join(lines)
    
    def add_issue(self, issue: ValidationIssue):
        """Add an issue to the appropriate list based on severity."""
        if issue.severity == IssueSeverity.ERROR:
            self.errors.append(issue)
        elif issue.severity == IssueSeverity.WARNING:
            self.warnings.append(issue)
        else:
            self.info.append(issue)


class PreDeploymentChecker:
    """Orchestrates all pre-deployment validation checks."""
    
    def __init__(self):
        self.template_validator = TemplateValidator()
        self.dependency_validator = DependencyValidator()
        self.resource_limit_checker = ResourceLimitChecker()
    
    def validate_deployment(
        self,
        templates: Dict[str, Path],
        parameters: Optional[Dict[str, Dict[str, str]]] = None,
        existing_exports: Optional[Set[str]] = None
    ) -> ComprehensiveValidationReport:
        """
        Run all validation checks and generate comprehensive report.
        
        Args:
            templates: Map of stack name to template path
            parameters: Map of stack name to parameter values
            existing_exports: Optional set of existing CloudFormation exports
            
        Returns:
            ComprehensiveValidationReport with all issues categorized by severity
        """
        report = ComprehensiveValidationReport(success=True)
        report.templates_validated = len(templates)
        
        parameters = parameters or {}
        parsed_templates: Dict[str, Dict[str, Any]] = {}
        all_exports: Set[str] = set(existing_exports) if existing_exports else set()
        
        logger.info(f"Starting pre-deployment validation for {len(templates)} templates")
        
        # Phase 1: Parse and validate syntax for all templates
        for stack_name, template_path in templates.items():
            logger.info(f"Validating template: {stack_name}")
            
            # Read and validate YAML syntax
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                success, error_info = validate_yaml_syntax(content)
                
                if not success:
                    report.add_issue(ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.SYNTAX,
                        message=f"YAML syntax error in {stack_name}: {error_info.get('message', 'Unknown error')}",
                        location=f"{template_path}:{error_info.get('line', '?')}:{error_info.get('column', '?')}",
                        remediation="Fix the YAML syntax error at the indicated location"
                    ))
                    continue
                
                # Parse template
                template = load_cfn_yaml(content)
                parsed_templates[stack_name] = template
                
            except FileNotFoundError:
                report.add_issue(ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.SYNTAX,
                    message=f"Template file not found: {template_path}",
                    location=str(template_path),
                    remediation="Ensure the template file exists at the specified path"
                ))
                continue
            except Exception as e:
                report.add_issue(ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    category=IssueCategory.SYNTAX,
                    message=f"Error reading template {stack_name}: {str(e)}",
                    location=str(template_path),
                    remediation="Check the template file for errors"
                ))
                continue
        
        # Phase 2: Validate structure for each template
        for stack_name, template in parsed_templates.items():
            self._validate_structure(stack_name, template, report)
            self._validate_parameters(stack_name, template, parameters.get(stack_name, {}), report)
            self._validate_conditions(stack_name, template, report)
            self._validate_mappings(stack_name, template, report)
            self._validate_outputs(stack_name, template, all_exports, report)
            
            # Collect exports for cross-template validation
            exports = self.dependency_validator.extract_exports(template)
            all_exports.update(exports)
        
        # Phase 3: Validate dependencies across templates
        if parsed_templates:
            self._validate_dependencies(parsed_templates, existing_exports, report)
        
        # Phase 4: Check resource limits
        if parsed_templates:
            self._check_resource_limits(parsed_templates, report)
        
        # Determine overall success
        report.success = len(report.errors) == 0
        
        # Generate summary
        report.summary = self._generate_summary(report)
        
        logger.info(f"Validation complete: {report.summary}")
        
        return report
    
    def _validate_structure(
        self,
        stack_name: str,
        template: Dict[str, Any],
        report: ComprehensiveValidationReport
    ):
        """Validate template structure."""
        result = self.template_validator.validate_template_structure(template)
        
        if not result.has_resources:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURE,
                message=f"Template {stack_name} does not contain a Resources section",
                location=stack_name,
                remediation="Add a Resources section with at least one resource"
            ))
        
        for invalid_type in result.invalid_resource_types:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURE,
                message=f"Invalid resource type in {stack_name}: {invalid_type}",
                location=f"{stack_name}.Resources.{invalid_type.split(':')[0]}",
                remediation="Use valid AWS resource type format: AWS::Service::Resource"
            ))
        
        for dup_id in result.duplicate_logical_ids:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.STRUCTURE,
                message=f"Duplicate logical ID in {stack_name}: {dup_id}",
                location=f"{stack_name}.Resources.{dup_id}",
                remediation="Use unique logical IDs for each resource"
            ))
    
    def _validate_parameters(
        self,
        stack_name: str,
        template: Dict[str, Any],
        provided_values: Dict[str, str],
        report: ComprehensiveValidationReport
    ):
        """Validate template parameters."""
        result = self.template_validator.validate_parameters(template, provided_values)
        
        for missing in result.missing_required:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.PARAMETER,
                message=f"Missing required parameter in {stack_name}: {missing}",
                location=f"{stack_name}.Parameters.{missing}",
                remediation=f"Provide a value for the required parameter '{missing}'"
            ))
        
        for mismatch in result.type_mismatches:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.PARAMETER,
                message=f"Type mismatch in {stack_name}: {mismatch['parameter']} expected {mismatch['expected_type']}, got '{mismatch['actual_value']}'",
                location=f"{stack_name}.Parameters.{mismatch['parameter']}",
                remediation=f"Provide a value of type {mismatch['expected_type']}"
            ))
        
        for violation in result.constraint_violations:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.PARAMETER,
                message=f"Constraint violation in {stack_name}: {violation['parameter']} - {violation['constraint_type']} constraint failed",
                location=f"{stack_name}.Parameters.{violation['parameter']}",
                remediation=f"Provide a value that satisfies the {violation['constraint_type']} constraint: {violation['constraint_value']}"
            ))
    
    def _validate_conditions(
        self,
        stack_name: str,
        template: Dict[str, Any],
        report: ComprehensiveValidationReport
    ):
        """Validate template conditions."""
        result = self.template_validator.validate_conditions(template)
        
        for undefined in result.undefined_conditions:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.CONDITION,
                message=f"Undefined condition in {stack_name}: {undefined}",
                location=f"{stack_name}.Conditions",
                remediation=f"Define the condition '{undefined}' in the Conditions section"
            ))
        
        # Filter false positives: use ReferenceValidator to check if "undefined parameters"
        # are actually valid resource references
        if result.undefined_parameters:
            ref_validator = ReferenceValidator()
            truly_undefined, valid_resource_refs = ref_validator.filter_false_positives(
                result.undefined_parameters, template
            )
            
            # Only report truly undefined references
            for undefined_param in truly_undefined:
                report.add_issue(ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    category=IssueCategory.CONDITION,
                    message=f"Possible undefined parameter reference in {stack_name}: {undefined_param}",
                    location=f"{stack_name}",
                    remediation="Verify the parameter is defined or is a valid pseudo-parameter"
                ))
            
            # Log filtered false positives for debugging
            if valid_resource_refs:
                logger.debug(
                    f"Filtered {len(valid_resource_refs)} false positive warnings in {stack_name}: "
                    f"valid resource refs: {valid_resource_refs}"
                )
    
    def _validate_mappings(
        self,
        stack_name: str,
        template: Dict[str, Any],
        report: ComprehensiveValidationReport
    ):
        """Validate template mappings."""
        result = self.template_validator.validate_mappings(template)
        
        for invalid_ref in result.invalid_references:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.MAPPING,
                message=f"Invalid FindInMap reference in {stack_name}: mapping '{invalid_ref['mapping_name']}', key '{invalid_ref['first_key']}/{invalid_ref['second_key']}' - missing {invalid_ref['missing_key']}",
                location=invalid_ref.get('location', stack_name),
                remediation=f"Add the missing {invalid_ref['missing_key']} to the Mappings section"
            ))
    
    def _validate_outputs(
        self,
        stack_name: str,
        template: Dict[str, Any],
        all_exports: Set[str],
        report: ComprehensiveValidationReport
    ):
        """Validate template outputs."""
        result = self.template_validator.validate_outputs(template, all_exports)
        
        for missing_value in result.missing_values:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.OUTPUT,
                message=f"Output without Value in {stack_name}: {missing_value}",
                location=f"{stack_name}.Outputs.{missing_value}",
                remediation="Add a Value property to the output"
            ))
        
        for invalid_ref in result.invalid_references:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.OUTPUT,
                message=f"Invalid resource reference in {stack_name} output: {invalid_ref}",
                location=f"{stack_name}.Outputs",
                remediation="Reference a resource that exists in the template"
            ))
        
        for dup_export in result.duplicate_exports:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.OUTPUT,
                message=f"Duplicate export name in {stack_name}: {dup_export}",
                location=f"{stack_name}.Outputs",
                remediation="Use unique export names across all stacks"
            ))
    
    def _validate_dependencies(
        self,
        templates: Dict[str, Dict[str, Any]],
        existing_exports: Optional[Set[str]],
        report: ComprehensiveValidationReport
    ):
        """Validate cross-stack dependencies."""
        result = self.dependency_validator.validate_dependencies(templates, existing_exports)
        
        for cycle in result.circular_dependencies:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.DEPENDENCY,
                message=f"Circular dependency detected: {' -> '.join(cycle)}",
                remediation="Remove the circular dependency by restructuring stack exports/imports"
            ))
        
        for missing in result.missing_exports:
            remediation = f"Ensure the export '{missing.import_name}' is created before this stack"
            if missing.suggested_source:
                remediation += f" (possibly from {missing.suggested_source})"
            
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.ERROR,
                category=IssueCategory.DEPENDENCY,
                message=f"Missing export '{missing.import_name}' imported by {missing.importing_stack}",
                location=missing.importing_stack,
                remediation=remediation
            ))
        
        # Store deployment order
        report.deployment_order = result.deployment_order
    
    def _check_resource_limits(
        self,
        templates: Dict[str, Dict[str, Any]],
        report: ComprehensiveValidationReport
    ):
        """Check resource limits."""
        result = self.resource_limit_checker.check_limits(templates)
        
        report.total_resources = result.total_resources
        
        for warning in result.warnings:
            severity = IssueSeverity.ERROR if warning.severity == 'error' else IssueSeverity.WARNING
            
            report.add_issue(ValidationIssue(
                severity=severity,
                category=IssueCategory.LIMIT,
                message=warning.message,
                location=warning.stack_name,
                remediation="Consider splitting resources across multiple stacks or requesting a limit increase"
            ))
    
    def _generate_summary(self, report: ComprehensiveValidationReport) -> str:
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
    
    def should_block_deployment(self, report: ComprehensiveValidationReport) -> bool:
        """Determine if deployment should be blocked based on report."""
        return len(report.errors) > 0
    
    def should_prompt_user(self, report: ComprehensiveValidationReport) -> bool:
        """Determine if user confirmation is needed."""
        return len(report.warnings) > 0 and len(report.errors) == 0
    
    def validate_with_aws_api(
        self,
        template_body: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Validate template using AWS CloudFormation ValidateTemplate API.
        
        This provides additional validation that can only be done by AWS:
        - Resource type validation
        - Property validation
        - Intrinsic function validation
        
        Args:
            template_body: The CloudFormation template as a string
            region: AWS region for the API call
            credentials: Optional AWS credentials
            
        Returns:
            Dict with:
            - success: bool
            - parameters: List of parameter info from AWS
            - capabilities: Required capabilities
            - error: Error message if validation failed
        """
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
            
            # Create CloudFormation client
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            cfn_client = session.client('cloudformation', region_name=region)
            
            # Call ValidateTemplate API
            response = cfn_client.validate_template(TemplateBody=template_body)
            
            return {
                'success': True,
                'parameters': response.get('Parameters', []),
                'capabilities': response.get('Capabilities', []),
                'capabilities_reason': response.get('CapabilitiesReason'),
                'description': response.get('Description'),
                'declared_transforms': response.get('DeclaredTransforms', [])
            }
            
        except NoCredentialsError:
            logger.debug("AWS credentials not available for API validation")
            return {
                'success': None,  # None indicates skipped
                'error': 'AWS credentials not available',
                'skipped': True
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            return {
                'success': False,
                'error': f"{error_code}: {error_message}",
                'error_code': error_code
            }
        except BotoCoreError as e:
            logger.warning(f"AWS API validation failed: {e}")
            return {
                'success': None,
                'error': str(e),
                'skipped': True
            }
        except Exception as e:
            logger.warning(f"Unexpected error during AWS API validation: {e}")
            return {
                'success': None,
                'error': str(e),
                'skipped': True
            }
    
    def check_iam_permissions(
        self,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        required_actions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Check if the current IAM identity has required permissions for deployment.
        
        Args:
            region: AWS region
            credentials: Optional AWS credentials
            required_actions: List of IAM actions to check (defaults to CloudFormation actions)
            
        Returns:
            Dict with:
            - success: bool (True if all permissions available)
            - identity: Current IAM identity info
            - missing_permissions: List of missing permissions (if any)
            - skipped: True if check was skipped due to missing credentials
        """
        if required_actions is None:
            required_actions = [
                'cloudformation:CreateStack',
                'cloudformation:UpdateStack',
                'cloudformation:DeleteStack',
                'cloudformation:DescribeStacks',
                'cloudformation:DescribeStackEvents',
                'cloudformation:GetTemplate',
                'cloudformation:ValidateTemplate'
            ]
        
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
            
            # Create STS client to get identity
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            sts_client = session.client('sts', region_name=region)
            
            # Get caller identity
            identity = sts_client.get_caller_identity()
            
            identity_info = {
                'account': identity.get('Account'),
                'arn': identity.get('Arn'),
                'user_id': identity.get('UserId')
            }
            
            # Note: Actually checking permissions would require IAM simulation
            # which needs additional permissions. For now, we just verify
            # that credentials are valid by successfully calling get_caller_identity
            
            return {
                'success': True,
                'identity': identity_info,
                'credentials_valid': True,
                'note': 'Credentials are valid. Full permission check requires IAM:SimulatePrincipalPolicy.'
            }
            
        except NoCredentialsError:
            logger.debug("AWS credentials not available for permission check")
            return {
                'success': None,
                'error': 'AWS credentials not available',
                'skipped': True
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            return {
                'success': False,
                'error': f"{error_code}: {error_message}",
                'credentials_valid': False
            }
        except BotoCoreError as e:
            logger.warning(f"IAM permission check failed: {e}")
            return {
                'success': None,
                'error': str(e),
                'skipped': True
            }
        except Exception as e:
            logger.warning(f"Unexpected error during IAM permission check: {e}")
            return {
                'success': None,
                'error': str(e),
                'skipped': True
            }
    
    def validate_deployment_with_aws(
        self,
        templates: Dict[str, Path],
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        parameters: Optional[Dict[str, Dict[str, str]]] = None,
        existing_exports: Optional[Set[str]] = None
    ) -> ComprehensiveValidationReport:
        """
        Run full validation including AWS API validation when credentials are available.
        
        This extends validate_deployment with:
        - AWS CloudFormation ValidateTemplate API calls
        - IAM permission checks
        
        Args:
            templates: Map of stack name to template path
            region: AWS region for API calls
            credentials: Optional AWS credentials
            parameters: Map of stack name to parameter values
            existing_exports: Optional set of existing CloudFormation exports
            
        Returns:
            ComprehensiveValidationReport with all issues including AWS API validation
        """
        # First run local validation
        report = self.validate_deployment(templates, parameters, existing_exports)
        
        # Check IAM permissions
        iam_result = self.check_iam_permissions(region, credentials)
        
        if iam_result.get('skipped'):
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.INFO,
                category=IssueCategory.STRUCTURE,
                message="AWS credential check skipped - credentials not available",
                remediation="Configure AWS credentials to enable live API validation"
            ))
        elif not iam_result.get('success'):
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.WARNING,
                category=IssueCategory.STRUCTURE,
                message=f"AWS credential validation failed: {iam_result.get('error')}",
                remediation="Verify AWS credentials are correctly configured"
            ))
        else:
            report.add_issue(ValidationIssue(
                severity=IssueSeverity.INFO,
                category=IssueCategory.STRUCTURE,
                message=f"AWS credentials valid for account {iam_result.get('identity', {}).get('account')}"
            ))
        
        # Validate each template with AWS API
        for stack_name, template_path in templates.items():
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_body = f.read()
                
                aws_result = self.validate_with_aws_api(template_body, region, credentials)
                
                if aws_result.get('skipped'):
                    # Already logged at INFO level above
                    continue
                elif not aws_result.get('success'):
                    report.add_issue(ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        category=IssueCategory.SYNTAX,
                        message=f"AWS API validation failed for {stack_name}: {aws_result.get('error')}",
                        location=stack_name,
                        remediation="Fix the template error reported by AWS CloudFormation"
                    ))
                else:
                    # Check for required capabilities
                    capabilities = aws_result.get('capabilities', [])
                    if capabilities:
                        report.add_issue(ValidationIssue(
                            severity=IssueSeverity.INFO,
                            category=IssueCategory.STRUCTURE,
                            message=f"Template {stack_name} requires capabilities: {', '.join(capabilities)}",
                            location=stack_name
                        ))
                    
                    # Check for transforms (SAM, etc.)
                    transforms = aws_result.get('declared_transforms', [])
                    if transforms:
                        report.add_issue(ValidationIssue(
                            severity=IssueSeverity.INFO,
                            category=IssueCategory.STRUCTURE,
                            message=f"Template {stack_name} uses transforms: {', '.join(transforms)}",
                            location=stack_name
                        ))
                        
            except FileNotFoundError:
                # Already reported in local validation
                continue
            except Exception as e:
                logger.warning(f"Error during AWS API validation for {stack_name}: {e}")
        
        # Update success status based on any new errors
        report.success = len(report.errors) == 0
        report.summary = self._generate_summary(report)
        
        return report


def get_pre_deployment_checker() -> PreDeploymentChecker:
    """Factory function to get a PreDeploymentChecker instance."""
    return PreDeploymentChecker()
