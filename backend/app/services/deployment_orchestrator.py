"""
Deployment Orchestrator
Coordinates CloudFormation, S3, and cleanup services for complete deployment workflow
"""
import yaml
import logging
from typing import Dict, Optional, Any, Callable, List
from pathlib import Path
from datetime import datetime

from app.services.cloudformation_service import CloudFormationDeploymentService
from app.services.s3_upload_service import S3UploadService
from app.services.cleanup_service import CleanupService
from app.services.ui_config_generator import UIConfigGenerator
from app.services.template_validator import TemplateValidator
from app.models.stack_detection import DeploymentStrategy
from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service as deployment_state_service
from app.services.stack_dependency_analyzer import StackDependencyAnalyzer
from app.services.dependency_validator import DependencyValidator
from app.services.deployment_planner import DeploymentPlanner
from app.models.dependency import ValidationResult, DeploymentPlan
from app.services.pre_deployment_checker import PreDeploymentChecker, get_pre_deployment_checker
from app.services.prerequisites_verifier import PrerequisitesVerifier, get_prerequisites_verifier

# Update workflow imports
from app.models.workflow_classification import WorkflowType, WorkflowClassification
from app.models.update_config import UpdateConfig, UpdateWorkflowConfig
from app.services.workflow_classifier import WorkflowClassifier, get_workflow_classifier
from app.services.update_workflow_orchestrator import UpdateWorkflowOrchestrator, get_update_workflow_orchestrator
from app.services.cognito_preservation_service import CognitoPreservationService
from app.services.stack_output_preserver import StackOutputPreserver


logger = logging.getLogger(__name__)


class DeploymentOrchestrator:
    """Orchestrates complete deployment workflow with installation tracking"""
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None, installation_id: Optional[str] = None):
        """
        Initialize deployment orchestrator
        
        Args:
            credentials: Optional AWS credentials dict
            installation_id: Optional installation ID for tracking
        """
        self.credentials = credentials or {}
        self.installation_id = installation_id
        self.cfn_service = CloudFormationDeploymentService(credentials)
        self.s3_service = S3UploadService(credentials)
        self.cleanup_service = CleanupService(credentials)
        self.template_validator = TemplateValidator()
        
        # Initialize pre-deployment validator
        from app.services.pre_deployment_validator import PreDeploymentValidator
        self.validator = PreDeploymentValidator(credentials)
        
        # Initialize comprehensive pre-deployment checker (new)
        self.pre_deployment_checker = get_pre_deployment_checker()
        
        # Initialize prerequisites verifier (comprehensive validation with false positive fix)
        self.prerequisites_verifier = get_prerequisites_verifier()
        
        # Initialize dependency validation components
        self.dependency_analyzer = StackDependencyAnalyzer()
        self.dependency_validator = DependencyValidator()  # No arguments needed
        self.deployment_planner = DeploymentPlanner()
        
        # Initialize workflow classification and update workflow components
        self.workflow_classifier = get_workflow_classifier(
            deployment_state_service=deployment_state_service
        )
        self.update_workflow_orchestrator = get_update_workflow_orchestrator(
            credentials=credentials
        )
        self.cognito_preservation_service = CognitoPreservationService(credentials)
        self.stack_output_preserver = StackOutputPreserver(credentials)
        
        # Lazy load installation tracker
        self._installation_tracker = None
    
    @property
    def installation_tracker(self):
        """Lazy load installation tracker."""
        if self._installation_tracker is None:
            try:
                from app.services.installation_tracker import get_installation_tracker
                self._installation_tracker = get_installation_tracker()
            except Exception as e:
                logger.warning(f"Could not load installation tracker: {e}")
        return self._installation_tracker
    
    def _log_stack_operation(
        self,
        stack_name: str,
        stack_type: str,
        operation: str,
        status: str,
        region: str,
        details: Optional[Dict] = None
    ) -> Optional[str]:
        """Log a stack operation if installation tracking is enabled."""
        if not self.installation_id or not self.installation_tracker:
            return None
        
        try:
            return self.installation_tracker.log_stack_operation(
                installation_id=self.installation_id,
                stack_name=stack_name,
                stack_type=stack_type,
                operation=operation,
                status=status,
                region=region,
                details=details
            )
        except Exception as e:
            logger.warning(f"Failed to log stack operation: {e}")
            return None
    
    def _update_stack_operation(
        self,
        log_id: str,
        status: str,
        error_message: Optional[str] = None,
        stack_outputs: Optional[Dict] = None,
        cfn_events: Optional[List[Dict]] = None
    ):
        """Update a stack operation log entry."""
        if not log_id or not self.installation_tracker:
            return
        
        try:
            self.installation_tracker.update_stack_operation(
                log_id=log_id,
                status=status,
                error_message=error_message,
                stack_outputs=stack_outputs,
                cfn_events=cfn_events
            )
        except Exception as e:
            logger.warning(f"Failed to update stack operation: {e}")
    
    def load_config(self, config_path: str) -> Dict[str, Any]:
        """Load deployment configuration from YAML"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def validate_stack_dependencies(
        self,
        config: Dict[str, Any],
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        callback: Optional[Callable] = None
    ) -> ValidationResult:
        """
        Validate all stack dependencies before deployment
        
        Args:
            config: Deployment configuration
            deploy_frontend: Whether frontend will be deployed
            deploy_backend: Whether backend will be deployed
            callback: Optional progress callback
            
        Returns:
            ValidationResult with success status and any issues found
        """
        from app.utils.cfn_yaml_loader import load_cfn_yaml_file
        
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        region = config.get('target', {}).get('region', '')
        
        if callback:
            callback("[LINK] Validating stack dependencies...")
        
        # Build templates dict (stack_name -> parsed template)
        templates: Dict[str, Dict[str, Any]] = {}
        templates_dir = self.cfn_service.templates_dir
        
        for stack_type in self.cfn_service.STACK_ORDER:
            # Skip based on deployment flags
            if 'frontend' in stack_type and not deploy_frontend:
                continue
            if 'backend' in stack_type and not deploy_backend:
                continue
            
            stack_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
            template_path = templates_dir / self.cfn_service.TEMPLATE_MAP.get(stack_type, '')
            
            if template_path.exists():
                try:
                    template = load_cfn_yaml_file(str(template_path))
                    templates[stack_name] = template
                except Exception as e:
                    if callback:
                        callback(f"[!] Failed to load template {template_path}: {e}")
        
        if callback:
            callback(f"[LINK] Analyzing {len(templates)} stack templates...")
        
        # Validate dependencies - pass templates dict and None for existing_exports
        dep_result = self.dependency_validator.validate_dependencies(templates, None)
        
        # Convert DependencyValidationResult to ValidationResult
        issues = []
        for issue_str in dep_result.issues:
            issues.append(ValidationIssue(
                severity='error',
                description=issue_str
            ))
        
        result = ValidationResult(
            success=dep_result.success,
            issues=issues,
            summary=f"Checked {len(templates)} stacks, found {len(issues)} issues"
        )
        
        if callback:
            if result.success:
                callback(f"[OK] Dependency validation passed: {result.summary}")
            else:
                callback(f"[X] Dependency validation failed: {result.summary}")
                for issue in result.issues:
                    callback(f"  [X] {issue.description}")
        
        return result
    
    def run_comprehensive_template_validation(
        self,
        config: Dict[str, Any],
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Run comprehensive template validation using the Pre-Deployment Checker.
        
        This validates:
        - YAML syntax with CloudFormation intrinsic function support
        - Template structure (Resources section, resource types)
        - Parameters (required values, type constraints)
        - Conditions (undefined references)
        - Mappings (FindInMap references)
        - Outputs (Value property, export names)
        - Cross-stack dependencies (circular dependencies, missing exports)
        - Resource limits (CloudFormation quotas)
        
        Args:
            config: Deployment configuration
            deploy_frontend: Whether frontend will be deployed
            deploy_backend: Whether backend will be deployed
            callback: Optional progress callback
            
        Returns:
            Dict with validation results including:
            - success: bool
            - should_block: bool
            - should_prompt: bool
            - report: ComprehensiveValidationReport as dict
            - ui_report: Formatted string for UI display
        """
        from pathlib import Path
        
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        
        if callback:
            callback("[TPL] Running comprehensive template validation...")
        
        # Build template paths
        templates: Dict[str, Path] = {}
        parameters: Dict[str, Dict[str, str]] = {}
        templates_dir = self.cfn_service.templates_dir
        
        for stack_type in self.cfn_service.STACK_ORDER:
            # Skip based on deployment flags
            if 'frontend' in stack_type and not deploy_frontend:
                continue
            if 'backend' in stack_type and not deploy_backend:
                continue
            
            template_file = self.cfn_service.TEMPLATE_MAP.get(stack_type, '')
            if not template_file:
                continue
                
            template_path = templates_dir / template_file
            
            if template_path.exists():
                stack_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
                templates[stack_name] = template_path
                
                # Build parameters for this stack
                stack_params = self.cfn_service.build_parameters(config, stack_type, {})
                if stack_params:
                    # Convert list of dicts to simple dict
                    params_dict = {p['ParameterKey']: p['ParameterValue'] for p in stack_params}
                    parameters[stack_name] = params_dict
        
        if callback:
            callback(f"[TPL] Validating {len(templates)} templates...")
        
        # Run comprehensive validation
        report = self.pre_deployment_checker.validate_deployment(
            templates=templates,
            parameters=parameters
        )
        
        # Determine blocking/prompting
        should_block = self.pre_deployment_checker.should_block_deployment(report)
        should_prompt = self.pre_deployment_checker.should_prompt_user(report)
        
        # Log results
        if callback:
            if report.success:
                callback(f"[OK] Template validation passed: {report.summary}")
            else:
                callback(f"[X] Template validation failed: {report.summary}")
            
            # Log errors
            for error in report.errors:
                callback(f"  [X] {error.message}")
                if error.location:
                    callback(f"      Location: {error.location}")
                if error.remediation:
                    callback(f"      Fix: {error.remediation}")
            
            # Log warnings
            for warning in report.warnings:
                callback(f"  [!] {warning.message}")
                if warning.remediation:
                    callback(f"      Suggestion: {warning.remediation}")
            
            # Log deployment order if available
            if report.deployment_order:
                callback(f"[ORDER] Recommended deployment order:")
                for i, stack in enumerate(report.deployment_order, 1):
                    callback(f"  {i}. {stack}")
        
        return {
            'success': report.success,
            'should_block': should_block,
            'should_prompt': should_prompt,
            'report': report.to_dict(),
            'ui_report': report.format_for_ui(),
            'errors_count': len(report.errors),
            'warnings_count': len(report.warnings),
            'templates_validated': report.templates_validated,
            'total_resources': report.total_resources,
            'deployment_order': report.deployment_order
        }
    
    def verify_deployment_prerequisites(
        self,
        config: Dict[str, Any],
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        callback: Optional[Callable] = None,
        skip_aws_checks: bool = False
    ) -> Dict[str, Any]:
        """
        Verify all deployment prerequisites using the PrerequisitesVerifier.
        
        This is the comprehensive validation that:
        - Validates parameter constraints (AllowedValues, MinLength, etc.)
        - Validates references (no false positives for valid resource refs)
        - Validates cross-stack dependencies
        - Runs pre-deployment checklist (AWS credentials, region, etc.)
        - Generates actionable remediation reports
        
        Args:
            config: Deployment configuration
            deploy_frontend: Whether frontend will be deployed
            deploy_backend: Whether backend will be deployed
            callback: Optional progress callback
            skip_aws_checks: Skip AWS API checks (for offline validation)
            
        Returns:
            Dict with verification results
        """
        from pathlib import Path
        
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        region = config.get('target', {}).get('region', '')
        
        if callback:
            callback("[PRE] Verifying deployment prerequisites...")
        
        # Build template paths and parameters
        templates: Dict[str, Path] = {}
        parameters: Dict[str, Dict[str, str]] = {}
        templates_dir = self.cfn_service.templates_dir
        
        for stack_type in self.cfn_service.STACK_ORDER:
            if 'frontend' in stack_type and not deploy_frontend:
                continue
            if 'backend' in stack_type and not deploy_backend:
                continue
            
            template_file = self.cfn_service.TEMPLATE_MAP.get(stack_type, '')
            if not template_file:
                continue
                
            template_path = templates_dir / template_file
            
            if template_path.exists():
                stack_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
                templates[stack_name] = template_path
                
                stack_params = self.cfn_service.build_parameters(config, stack_type, {})
                if stack_params:
                    params_dict = {p['ParameterKey']: p['ParameterValue'] for p in stack_params}
                    parameters[stack_name] = params_dict
        
        if callback:
            callback(f"[PRE] Verifying {len(templates)} templates...")
        
        # Run prerequisites verification
        result = self.prerequisites_verifier.verify_prerequisites(
            templates=templates,
            parameters=parameters,
            region=region,
            credentials=self.credentials,
            skip_aws_checks=skip_aws_checks
        )
        
        # Log results
        if callback:
            if result.success:
                callback(f"[OK] Prerequisites verification passed")
            else:
                callback(f"[X] Prerequisites verification failed")
            
            # Log errors
            for error in result.report.errors:
                callback(f"  [X] {error.message}")
                if error.remediation:
                    callback(f"      Fix: {error.remediation}")
            
            # Log warnings
            for warning in result.report.warnings:
                callback(f"  [!] {warning.message}")
            
            # Log deployment order
            if result.report.deployment_order:
                callback(f"[ORDER] Deployment order: {' -> '.join(result.report.deployment_order)}")
        
        return {
            'success': result.success,
            'can_deploy': result.can_deploy,
            'report': result.report.to_dict(),
            'ui_report': result.report.format_for_ui(),
            'checklist_passed': result.checklist_passed,
            'parameter_validation_passed': result.parameter_validation_passed,
            'reference_validation_passed': result.reference_validation_passed,
            'dependency_validation_passed': result.dependency_validation_passed,
            'deployment_order': result.report.deployment_order
        }
    
    def deploy_capability(self, config: Dict[str, Any],
                         deploy_frontend: bool = True,
                         deploy_backend: bool = True,
                         callback: Optional[Callable] = None,
                         skip_validation: bool = False) -> Dict[str, Any]:
        """
        Deploy a complete capability
        
        Args:
            config: Deployment configuration
            deploy_frontend: Whether to deploy frontend
            deploy_backend: Whether to deploy backend
            callback: Optional progress callback
            skip_validation: If True, skip pre-deployment validation (used for CLEAN_DEPLOY)
            
        Returns:
            Dict with deployment results
        """
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        region = config.get('target', {}).get('region', '')
        
        results = {
            'capability_name': capability_name,
            'environment': environment,
            'region': region,
            'stacks': {},
            'frontend_url': None,
            'backend_url': None,
            'cognito_config': None,
            'success': False,
            'error': None
        }
        
        try:
            if callback:
                callback(f"[TOOL] Initializing CloudFormation client for region: {region}")
                callback(f"[TOOL] Credentials configured: {bool(self.credentials)}")
                callback(f"[PKG] Frontend deployment: {'ENABLED' if deploy_frontend else 'DISABLED'}")
                callback(f"[PKG] Backend deployment: {'ENABLED' if deploy_backend else 'DISABLED'}")
            
            # Validate templates exist before starting deployment
            if callback:
                callback("[TPL] Validating CloudFormation templates...")
            
            template_validation = self.template_validator.validate_templates(
                deploy_frontend=deploy_frontend,
                deploy_backend=deploy_backend,
                check_integrity=True
            )
            
            # Store template validation result
            results['template_validation'] = template_validation.to_dict()
            
            if not template_validation.success:
                # Build detailed error message with all missing templates
                error_parts = ["Template validation failed:"]
                
                if template_validation.missing_templates:
                    error_parts.append(f"\n  Missing templates ({len(template_validation.missing_templates)}):")
                    for missing in template_validation.missing_templates:
                        error_parts.append(f"    - {missing.template_name}: {missing.expected_path}")
                    # Add remediation from first missing template
                    if template_validation.missing_templates:
                        error_parts.append(f"\n  Remediation: {template_validation.missing_templates[0].remediation}")
                
                if template_validation.integrity_issues:
                    error_parts.append(f"\n  Integrity issues ({len(template_validation.integrity_issues)}):")
                    for issue in template_validation.integrity_issues:
                        error_parts.append(f"    - {issue.template_path}: {issue.details}")
                
                results['error'] = "".join(error_parts)
                results['success'] = False
                
                if callback:
                    callback(f"[X] {results['error']}")
                
                return results
            
            if callback:
                callback(f"[OK] Template validation passed: {template_validation.summary}")
            
            # Run comprehensive template validation (syntax, structure, parameters, dependencies, limits)
            comprehensive_validation_enabled = config.get('deployment', {}).get('comprehensive_validation', {}).get('enabled', True)
            
            if not skip_validation and comprehensive_validation_enabled:
                if callback:
                    callback("[TPL] Running comprehensive template validation...")
                
                comprehensive_result = self.run_comprehensive_template_validation(
                    config, deploy_frontend, deploy_backend, callback
                )
                
                # Store comprehensive validation result
                results['comprehensive_validation'] = comprehensive_result
                
                # Block deployment if errors found
                if comprehensive_result.get('should_block', False):
                    results['success'] = False
                    results['error'] = f"Comprehensive template validation failed with {comprehensive_result.get('errors_count', 0)} errors"
                    if callback:
                        callback(f"[X] {results['error']}")
                    return results
                
                # Log warning if user should be prompted (warnings but no errors)
                if comprehensive_result.get('should_prompt', False):
                    if callback:
                        callback(f"[!] Template validation passed with {comprehensive_result.get('warnings_count', 0)} warnings")
                        callback("[!] Review warnings above before proceeding")
            elif skip_validation:
                if callback:
                    callback("[!] Skipping comprehensive template validation (skip_validation=True)")
            elif not comprehensive_validation_enabled:
                if callback:
                    callback("[!] Comprehensive template validation is disabled in configuration")
            
            # Check if pre-deployment validation should run
            validation_enabled = config.get('deployment', {}).get('pre_validation', {}).get('enabled', True)
            
            # Skip validation if explicitly requested (e.g., for CLEAN_DEPLOY) or if disabled in config
            if skip_validation:
                if callback:
                    callback("[!] Skipping pre-deployment validation (skip_validation=True)")
                import logging
                logger = logging.getLogger(__name__)
                logger.info("Skipping pre-deployment validation - skip_validation parameter is True")
            elif not validation_enabled:
                if callback:
                    callback("[!] Pre-deployment validation is disabled in configuration")
            else:
                # Run pre-deployment validation
                if callback:
                    callback("[DBG] Running pre-deployment validation...")
                    callback("[DBG] This will check for unstable stacks and orphaned resources...")
                
                validation_config = {
                    'capability_name': capability_name,
                    'environment': environment,
                    'region': region
                }
                
                validation_report = self.validator.validate_deployment(
                    validation_config,
                    deploy_frontend,
                    deploy_backend,
                    callback
                )
                
                # Store validation report in results
                results['validation_report'] = validation_report.dict()
                
                # Log validation details
                if callback:
                    callback(f"[DBG] Validation found {len(validation_report.issues_found)} issues")
                    callback(f"[DBG] Resolved {len(validation_report.issues_resolved)} issues")
                    callback(f"[DBG] Unresolved {len(validation_report.issues_unresolved)} issues")
                
                # If validation failed, return error
                if not validation_report.success:
                    results['success'] = False
                    results['error'] = f"Pre-deployment validation failed: {validation_report.summary}"
                    if callback:
                        callback(f"[X] {results['error']}")
                        # Log unresolved issues
                        for issue in validation_report.issues_unresolved:
                            callback(f"[X] Unresolved: {issue.description}")
                    return results
                
                if callback:
                    callback(f"[OK] Pre-deployment validation passed: {validation_report.summary}")
                
                # Run dependency validation (check for missing exports)
                if callback:
                    callback("[LINK] Running dependency validation...")
                
                dep_validation_result = self.validate_stack_dependencies(
                    config, deploy_frontend, deploy_backend, callback
                )
                
                # Store dependency validation result
                results['dependency_validation'] = {
                    'success': dep_validation_result.success,
                    'summary': dep_validation_result.summary,
                    'issues': [
                        {
                            'severity': issue.severity.value,
                            'type': issue.issue_type.value,
                            'stack': issue.stack_name,
                            'description': issue.description,
                            'action': issue.suggested_action
                        }
                        for issue in dep_validation_result.issues
                    ]
                }
                
                # If dependency validation failed, return error
                if not dep_validation_result.success:
                    results['success'] = False
                    results['error'] = f"Dependency validation failed: {dep_validation_result.summary}"
                    if callback:
                        callback(f"[X] {results['error']}")
                        for issue in dep_validation_result.issues:
                            callback(f"[X] {issue.description}")
                            callback(f"   Action: {issue.suggested_action}")
                    return results
            
            cfn_client = self.cfn_service._get_client('cloudformation', region)
            
            if callback:
                callback(f"[OK] CloudFormation client created successfully")
                # Test the client by listing stacks
                try:
                    test_response = cfn_client.list_stacks(StackStatusFilter=['CREATE_COMPLETE', 'UPDATE_COMPLETE'])
                    stack_count = len(test_response.get('StackSummaries', []))
                    callback(f"[OK] Client test successful - found {stack_count} existing stacks in region")
                except Exception as test_error:
                    callback(f"[!] Client test warning: {str(test_error)}")
            
            stack_outputs = {}
            tags = self.cfn_service.build_tags(config)
            capabilities = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']
            
            # Deploy stacks in order
            for stack_type in self.cfn_service.STACK_ORDER:
                # Skip based on deployment flags
                if 'frontend' in stack_type and not deploy_frontend:
                    continue
                if 'backend' in stack_type and not deploy_backend:
                    continue
                
                stack_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
                
                # Determine the correct region for this stack
                # Global stacks (CloudFront, ACM certificates, WAF) must be in us-east-1
                stack_region = region
                if stack_type == 'frontend-global':
                    stack_region = 'us-east-1'
                    if callback:
                        callback(f"Deploying {stack_name} to us-east-1 (global resources)...")
                else:
                    if callback:
                        callback(f"Deploying {stack_name} to {stack_region}...")
                
                # Log stack operation start
                log_id = self._log_stack_operation(
                    stack_name=stack_name,
                    stack_type=stack_type,
                    operation="create",  # Will be determined by CloudFormation
                    status="started",
                    region=stack_region
                )
                
                # Get the appropriate CloudFormation client for this stack's region
                stack_cfn_client = self.cfn_service._get_client('cloudformation', stack_region)
                
                # Load template
                template_body = self.cfn_service.load_template(stack_type)
                
                # Build parameters
                parameters = self.cfn_service.build_parameters(config, stack_type, stack_outputs)
                
                # Deploy stack - pass through the callback directly
                success, error = self.cfn_service.create_or_update_stack(
                    stack_cfn_client, stack_name, template_body, parameters,
                    tags, capabilities, callback
                )
                
                results['stacks'][stack_name] = {
                    'success': success,
                    'error': error,
                    'stack_type': stack_type,
                    'region': stack_region
                }
                
                if not success:
                    # Log stack operation failure
                    self._update_stack_operation(
                        log_id=log_id,
                        status="failed",
                        error_message=error
                    )
                    results['error'] = f"Stack {stack_name} failed: {error}"
                    return results
                
                # Get stack outputs for next stacks - use the correct region client
                outputs = self.cfn_service.get_stack_outputs(stack_cfn_client, stack_name)
                stack_outputs[stack_type] = outputs
                
                # Log stack operation success with outputs
                self._update_stack_operation(
                    log_id=log_id,
                    status="completed",
                    stack_outputs=outputs
                )
                
                if callback:
                    callback(f"Stack {stack_name} deployed successfully in {stack_region}")
            
            # Deploy frontend artifacts if needed
            if deploy_frontend:
                frontend_s3_uri = config.get('source', {}).get('frontend', {}).get('s3_uri')
                
                if callback:
                    callback(f"[DBG] Checking frontend artifact configuration...")
                    callback(f"  frontend_s3_uri: {frontend_s3_uri or 'NOT SET'}")
                
                if not frontend_s3_uri:
                    if callback:
                        callback("[!] WARNING: No frontend S3 URI configured - skipping artifact upload")
                else:
                    if callback:
                        callback("[PKG] Deploying frontend artifacts...")
                    
                    # Get S3 bucket from stack outputs (bucket is in regional stack)
                    regional_outputs = stack_outputs.get('frontend-regional', {})
                    target_bucket = regional_outputs.get('S3BucketName')
                    distribution_id = regional_outputs.get('CloudFrontDistributionId')
                    
                    if callback:
                        callback(f"[DBG] Stack outputs check:")
                        callback(f"  regional stack outputs: {list(regional_outputs.keys())}")
                        callback(f"  target_bucket: {target_bucket or 'NOT FOUND'}")
                        callback(f"  distribution_id: {distribution_id or 'NOT FOUND'}")
                    
                    if not target_bucket:
                        error_msg = "Frontend regional stack did not output S3BucketName"
                        if callback:
                            callback(f"[X] {error_msg}")
                        results['error'] = error_msg
                        results['success'] = False
                        return results
                    
                    def s3_callback(message):
                        if callback:
                            callback(f"Frontend: {message}")
                    
                    # S3 bucket is in the deployment region (regional stack)
                    success = self.s3_service.deploy_frontend_artifact(
                        frontend_s3_uri, target_bucket, distribution_id,
                        region, s3_callback
                    )
                    
                    if not success:
                        error_msg = "Frontend artifact deployment failed - check logs for details"
                        if callback:
                            callback(f"[X] {error_msg}")
                            callback(f"  Source: {frontend_s3_uri}")
                            callback(f"  Target: {target_bucket}")
                        results['error'] = error_msg
                        results['success'] = False
                        return results
                    
                    # Verify upload
                    try:
                        s3_client = self.s3_service._get_client('s3', region)
                        response = s3_client.list_objects_v2(Bucket=target_bucket, MaxKeys=10)
                        file_count = response.get('KeyCount', 0)
                        if callback:
                            callback(f"[OK] Upload verified: {file_count} files in bucket")
                        if file_count == 0:
                            if callback:
                                callback(f"[!] WARNING: Bucket is empty after upload!")
                    except Exception as e:
                        if callback:
                            callback(f"[!] Could not verify upload: {str(e)}")
                    
                    # Get frontend URL
                    results['frontend_url'] = regional_outputs.get('CloudFrontURL')
                
                # Get Cognito configuration
                cognito_outputs = stack_outputs.get('frontend-cognito', {})
                if cognito_outputs:
                    user_pool_id = cognito_outputs.get('UserPoolId')
                    admin_password = config.get('infrastructure', {}).get('cognito', {}).get('admin_temp_password', 'Admin@Temp123!')
                    
                    # Sanitize capability name for user emails
                    sanitized_name = capability_name.lower().replace(' ', '-').replace('_', '-')
                    
                    results['cognito_config'] = {
                        'user_pool_id': user_pool_id,
                        'client_id': cognito_outputs.get('UserPoolClientId'),
                        'domain': cognito_outputs.get('UserPoolDomain'),
                        'region': region,
                        'admin_user_email': f"admin@{sanitized_name}.local",
                        'admin_temp_password': admin_password,
                        'test_users_info': cognito_outputs.get('TestUsersInfo'),
                    }
                    
                    # Store Cognito configuration in SSM Parameter Store
                    # This enables runtime configuration for backend services
                    if user_pool_id and cognito_outputs.get('UserPoolClientId'):
                        try:
                            from app.services.cognito_ssm_integration import CognitoSSMIntegration
                            
                            if callback:
                                callback("[SSM] Storing Cognito configuration in SSM Parameter Store...")
                            
                            ssm_integration = CognitoSSMIntegration(
                                capability_name=capability_name,
                                environment=environment,
                                region=region,
                                credentials=self.credentials
                            )
                            
                            # Get frontend URL for redirect URI
                            frontend_url = results.get('frontend_url') or regional_outputs.get('CloudFrontURL')
                            if frontend_url:
                                # Ensure it has /auth/callback path
                                if not frontend_url.endswith('/auth/callback'):
                                    redirect_uri = f"{frontend_url.rstrip('/')}/auth/callback"
                                else:
                                    redirect_uri = frontend_url
                            else:
                                redirect_uri = None
                            
                            ssm_result = ssm_integration.store_cognito_from_stack_outputs(
                                stack_outputs=cognito_outputs,
                                frontend_url=redirect_uri
                            )
                            
                            if callback:
                                success_count = sum(1 for r in ssm_result.values() if isinstance(r, dict) and r.get("status") == "created")
                                callback(f"[OK] Stored {success_count} Cognito parameters in SSM")
                            
                            results['cognito_ssm_sync'] = {
                                'success': True,
                                'parameters_stored': ssm_result
                            }
                            
                        except Exception as e:
                            logger.error(f"Failed to store Cognito config in SSM: {e}")
                            if callback:
                                callback(f"[!] Warning: Failed to store Cognito config in SSM: {e}")
                                callback("[!] Cognito will work but backend may not auto-discover settings")
                            results['cognito_ssm_sync'] = {
                                'success': False,
                                'error': str(e)
                            }
                    
                    # Set up Cognito user passwords
                    if user_pool_id:
                        try:
                            from app.services.cognito_user_service import CognitoUserService
                            cognito_service = CognitoUserService(self.credentials)
                            
                            if callback:
                                callback("[LOCK] Setting up Cognito user passwords...")
                            
                            password_result = cognito_service.setup_deployment_users(
                                user_pool_id=user_pool_id,
                                capability_name=capability_name,
                                environment=environment,
                                region=region,
                                password=admin_password,
                                callback=callback
                            )
                            
                            if password_result.get('success'):
                                if callback:
                                    callback(f"[OK] Cognito user passwords configured successfully")
                                    callback(f"  [EMAIL] Admin user: admin@{sanitized_name}.local")
                                    callback(f"  [KEY] Temporary password: {admin_password}")
                                    callback(f"  [!] Users will be prompted to change password on first login")
                            else:
                                if callback:
                                    callback(f"[!] Warning: Some Cognito user passwords could not be set")
                                    callback(f"  [EMAIL] Admin user: admin@{sanitized_name}.local")
                                    callback(f"  [KEY] Set password manually via AWS Console or CLI:")
                                    callback(f"     aws cognito-idp admin-set-user-password --user-pool-id {user_pool_id} --username admin@{sanitized_name}.local --password <password> --permanent")
                        except Exception as e:
                            if callback:
                                callback(f"[!] Warning: Failed to set Cognito passwords: {str(e)}")
                                callback(f"  [EMAIL] Admin user: admin@{sanitized_name}.local")
                                callback(f"  [KEY] Set password manually via AWS Console or CLI:")
                                callback(f"     aws cognito-idp admin-set-user-password --user-pool-id {user_pool_id} --username admin@{sanitized_name}.local --password <password> --permanent")
                
                # Generate and deploy config.json from stack outputs
                # This creates the UI configuration with API URL, Cognito settings, etc.
                if callback:
                    callback("[NOTE] Generating config.json from stack outputs...")
                
                ui_config_generator = UIConfigGenerator(self.credentials)
                config_success = ui_config_generator.generate_and_deploy_config(
                    stack_outputs, region, callback
                )
                
                if not config_success:
                    if callback:
                        callback("[!] Warning: config.json generation failed, but deployment will continue")
            
            # Get backend URL if deployed
            if deploy_backend:
                service_outputs = stack_outputs.get('backend-service', {})
                domain_outputs = stack_outputs.get('backend-domain', {})
                
                # Prefer custom domain URL from domain stack, fallback to ALB URL
                if domain_outputs.get('ApiUrl'):
                    results['backend_url'] = domain_outputs.get('ApiUrl')
                else:
                    results['backend_url'] = service_outputs.get('ServiceURL')
                
                # Second pass: Update service stack with certificate from domain stack
                # This enables HTTPS after the domain stack has created the certificate
                if domain_outputs.get('BackendCertificateArn'):
                    if callback:
                        callback("[SECURE] Updating service stack with SSL certificate...")
                    
                    service_stack_name = self.cfn_service.get_stack_name(capability_name, environment, 'backend-service')
                    stack_cfn_client = self.cfn_service._get_client('cloudformation', region)
                    
                    # Rebuild parameters with domain stack outputs now available
                    template_body = self.cfn_service.load_template('backend-service')
                    parameters = self.cfn_service.build_parameters(config, 'backend-service', stack_outputs)
                    
                    success, error = self.cfn_service.create_or_update_stack(
                        stack_cfn_client, service_stack_name, template_body, parameters,
                        tags, capabilities, callback
                    )
                    
                    if not success:
                        if callback:
                            callback(f"[!] Warning: Failed to update service stack with certificate: {error}")
                            callback("[!] Service is running but HTTPS may not be enabled")
                    else:
                        if callback:
                            callback("[OK] Service stack updated with SSL certificate - HTTPS enabled")
                        
                        # Update the service outputs
                        service_outputs = self.cfn_service.get_stack_outputs(stack_cfn_client, service_stack_name)
                        stack_outputs['backend-service'] = service_outputs
                        
                        # Update backend URL to use custom domain
                        if domain_outputs.get('ApiUrl'):
                            results['backend_url'] = domain_outputs.get('ApiUrl')
            
            results['success'] = True
            
            if callback:
                callback("Deployment completed successfully!")
            
            # Save deployment state to filesystem
            try:
                stacks_info = []
                for stack_name, stack_data in results['stacks'].items():
                    if stack_data.get('success'):
                        stacks_info.append({
                            'stack_name': stack_name,
                            'stack_type': stack_data.get('stack_type'),
                            'region': stack_data.get('region'),
                            'deployed_at': datetime.utcnow().isoformat()
                        })
                
                deployment_state_service.save_deployment_state(
                    capability_name=capability_name,
                    environment=environment,
                    region=region,
                    stacks=stacks_info,
                    deployment_metadata={
                        'frontend_deployed': deploy_frontend,
                        'backend_deployed': deploy_backend,
                        'frontend_url': results.get('frontend_url'),
                        'backend_url': results.get('backend_url')
                    }
                )
                
                if callback:
                    callback(f"[OK] Saved deployment state for {capability_name}-{environment}")
                    
            except Exception as e:
                # Don't fail deployment if state save fails
                if callback:
                    callback(f"[!] Warning: Failed to save deployment state: {str(e)}")
            
            return results
            
        except Exception as e:
            results['error'] = str(e)
            if callback:
                callback(f"Deployment failed: {str(e)}")
            return results
    
    def cleanup_capability(self, capability_name: str, environment: str, region: str,
                          callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Cleanup a deployed capability
        
        Args:
            capability_name: Name of capability
            environment: Environment
            region: AWS region
            callback: Optional progress callback
            
        Returns:
            Dict with cleanup results
        """
        try:
            def cleanup_callback(message):
                if callback:
                    callback(f"Cleanup: {message}")
            
            stack_results = self.cleanup_service.cleanup_capability(
                capability_name, environment, region, cleanup_callback
            )
            
            successful = sum(1 for v in stack_results.values() if v)
            total = len(stack_results)
            
            # Delete deployment state from TinyDB after successful cleanup
            if successful == total:
                try:
                    deployment_state_service.delete_deployment_state(
                        capability_name, environment
                    )
                    if callback:
                        callback(f"[OK] Deleted deployment state from TinyDB")
                except Exception as e:
                    # Don't fail cleanup if TinyDB deletion fails
                    if callback:
                        callback(f"[!] Warning: Failed to delete deployment state: {str(e)}")
            
            return {
                'capability_name': capability_name,
                'environment': environment,
                'region': region,
                'stacks': stack_results,
                'success': successful == total,
                'summary': f"{successful}/{total} stacks deleted"
            }
            
        except Exception as e:
            if callback:
                callback(f"Cleanup failed: {str(e)}")
            return {
                'capability_name': capability_name,
                'environment': environment,
                'region': region,
                'success': False,
                'error': str(e)
            }
    
    def deploy_capability_with_strategy(
        self,
        config: Dict[str, Any],
        strategy: DeploymentStrategy,
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        callback: Optional[Callable] = None,
        update_config: Optional[UpdateConfig] = None
    ) -> Dict[str, Any]:
        """
        Deploy a capability with specified deployment strategy
        
        Args:
            config: Deployment configuration
            strategy: Deployment strategy (CLEAN_DEPLOY or UPDATE_EXISTING)
            deploy_frontend: Whether to deploy frontend
            deploy_backend: Whether to deploy backend
            callback: Optional progress callback
            update_config: Optional update configuration for UPDATE_EXISTING strategy
            
        Returns:
            Dict with deployment results
        """
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        region = config.get('target', {}).get('region', '')
        
        # Ensure strategy is a DeploymentStrategy enum (handle string input)
        if isinstance(strategy, str):
            strategy = DeploymentStrategy(strategy)
        
        try:
            if strategy == DeploymentStrategy.CLEAN_DEPLOY:
                # Clean deployment: cleanup first, then deploy
                # Skip validation for CLEAN_DEPLOY - cleanup will handle everything
                if callback:
                    callback(f"[CLEAN] Starting clean deployment for {capability_name}-{environment}")
                    callback(f"[!] Skipping pre-deployment validation for CLEAN_DEPLOY strategy")
                    callback(f"[CLEAN] Step 1: Cleaning up existing stacks...")
                
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Skipping pre-deployment validation for CLEAN_DEPLOY strategy - cleanup will handle all resources")
                
                # Perform cleanup
                cleanup_result = self.cleanup_capability(
                    capability_name, environment, region, callback
                )
                
                if not cleanup_result.get('success'):
                    error_msg = cleanup_result.get('error', 'Cleanup failed')
                    if callback:
                        callback(f"[X] Cleanup failed: {error_msg}")
                    return {
                        'capability_name': capability_name,
                        'environment': environment,
                        'region': region,
                        'success': False,
                        'error': f"Cleanup failed: {error_msg}",
                        'strategy': strategy.value
                    }
                
                if callback:
                    callback(f"[OK] Cleanup completed successfully")
                    callback(f"[...] Waiting for AWS resources to fully delete...")
                
                # Wait for AWS resources to fully delete
                # CloudWatch log groups, WAF resources, etc. can take time to delete
                import time
                time.sleep(10)  # Wait 10 seconds for resources to fully delete
                
                if callback:
                    callback(f"[OK] Resource deletion wait complete")
                    callback(f"[LAUNCH] Step 2: Deploying fresh stacks...")
                
                # Proceed with deployment, skipping validation
                result = self.deploy_capability(
                    config, deploy_frontend, deploy_backend, callback, skip_validation=True
                )
                result['strategy'] = strategy.value
                return result
                
            elif strategy == DeploymentStrategy.UPDATE_EXISTING:
                # Update deployment: use existing deploy_capability which handles updates
                # Run validation for UPDATE_EXISTING strategy
                if callback:
                    callback(f"[SYNC] Starting update deployment for {capability_name}-{environment}")
                    callback(f"[SYNC] Updating existing stacks in place...")
                
                # Proceed with deployment, validation will run as configured
                result = self.deploy_capability(
                    config, deploy_frontend, deploy_backend, callback, skip_validation=False
                )
                result['strategy'] = strategy.value
                return result
                
            else:
                raise ValueError(f"Unknown deployment strategy: {strategy}")
                
        except Exception as e:
            strategy_value = strategy.value if hasattr(strategy, 'value') else strategy
            if callback:
                callback(f"[X] Deployment with strategy {strategy_value} failed: {str(e)}")
            return {
                'capability_name': capability_name,
                'environment': environment,
                'region': region,
                'success': False,
                'error': str(e),
                'strategy': strategy_value
            }

    def _execute_update_workflow(
        self,
        config: Dict[str, Any],
        classification: WorkflowClassification,
        deploy_frontend: bool,
        deploy_backend: bool,
        callback: Optional[Callable],
        update_config: Optional[UpdateConfig] = None
    ) -> Dict[str, Any]:
        """
        Execute update workflow with Cognito preservation.
        
        Args:
            config: Deployment configuration
            classification: Workflow classification result
            deploy_frontend: Whether to deploy frontend
            deploy_backend: Whether to deploy backend
            callback: Progress callback
            update_config: Update configuration options
            
        Returns:
            Dict with deployment results
        """
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        region = config.get('target', {}).get('region', '')
        
        # Create default update config if not provided
        if update_config is None:
            update_config = UpdateConfig(
                preserve_cognito=True,
                include_cognito_update=False,
                require_user_backup=False
            )
        
        # Build stacks to deploy list
        stacks_to_deploy = []
        for stack_type in self.cfn_service.STACK_ORDER:
            if 'frontend' in stack_type and not deploy_frontend:
                continue
            if 'backend' in stack_type and not deploy_backend:
                continue
            
            stack_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
            stack_region = 'us-east-1' if stack_type == 'frontend-global' else region
            
            stacks_to_deploy.append({
                'stack_name': stack_name,
                'stack_type': stack_type,
                'region': stack_region,
                'template_path': str(self.cfn_service.templates_dir / self.cfn_service.TEMPLATE_MAP.get(stack_type, ''))
            })
        
        # Preserve existing stack outputs before update
        if callback:
            callback(f"[PRESERVE] Preserving existing stack outputs...")
        
        self.stack_output_preserver.preserve_all_outputs(
            capability_name=capability_name,
            environment=environment,
            region=region
        )
        
        # Get preserved Cognito outputs
        cognito_outputs = self.stack_output_preserver.get_cognito_outputs()
        
        if cognito_outputs and callback:
            callback(f"[PRESERVE] Found existing Cognito User Pool: {cognito_outputs.user_pool_id}")
        
        # Determine which stacks to update vs preserve
        stacks_to_skip = self.cognito_preservation_service.get_stacks_to_skip(
            workflow_type=classification.workflow_type,
            include_cognito_update=update_config.include_cognito_update
        )
        
        if callback and stacks_to_skip:
            callback(f"[PRESERVE] Stacks to preserve: {', '.join(stacks_to_skip)}")
        
        # Execute deployment with preservation
        results = {
            'capability_name': capability_name,
            'environment': environment,
            'region': region,
            'stacks': {},
            'frontend_url': None,
            'backend_url': None,
            'cognito_config': None,
            'success': False,
            'error': None,
            'cognito_preserved': False,
            'stacks_preserved': [],
            'stacks_updated': []
        }
        
        try:
            cfn_client = self.cfn_service._get_client('cloudformation', region)
            stack_outputs = {}
            tags = self.cfn_service.build_tags(config)
            capabilities = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']
            
            # Load preserved outputs into stack_outputs for parameter building
            preserved_outputs = self.stack_output_preserver.get_all_preserved_outputs()
            for preserved in preserved_outputs:
                # Map stack name back to stack type
                for stack_type in self.cfn_service.STACK_ORDER:
                    expected_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
                    if preserved.stack_name == expected_name:
                        stack_outputs[stack_type] = preserved.outputs
                        break
            
            # Deploy stacks in order
            for stack_info in stacks_to_deploy:
                stack_type = stack_info['stack_type']
                stack_name = stack_info['stack_name']
                stack_region = stack_info['region']
                
                # Check if this stack should be preserved (skipped)
                if stack_type in stacks_to_skip:
                    if callback:
                        callback(f"[PRESERVE] {stack_name}: Preserving existing stack (Cognito data protected)")
                    
                    results['stacks_preserved'].append(stack_name)
                    results['stacks'][stack_name] = {
                        'success': True,
                        'preserved': True,
                        'stack_type': stack_type,
                        'region': stack_region
                    }
                    
                    if stack_type == 'frontend-cognito':
                        results['cognito_preserved'] = True
                    
                    continue
                
                # Deploy/update the stack
                if callback:
                    callback(f"[UPDATE] Deploying {stack_name} to {stack_region}...")
                
                # Get the appropriate CloudFormation client for this stack's region
                stack_cfn_client = self.cfn_service._get_client('cloudformation', stack_region)
                
                # Load template
                template_body = self.cfn_service.load_template(stack_type)
                
                # Build parameters with preserved outputs
                parameters = self.cfn_service.build_parameters(config, stack_type, stack_outputs)
                
                # Deploy stack
                success, error = self.cfn_service.create_or_update_stack(
                    stack_cfn_client, stack_name, template_body, parameters,
                    tags, capabilities, callback
                )
                
                results['stacks'][stack_name] = {
                    'success': success,
                    'error': error,
                    'stack_type': stack_type,
                    'region': stack_region,
                    'preserved': False
                }
                
                if not success:
                    results['error'] = f"Stack {stack_name} failed: {error}"
                    if callback:
                        callback(f"[X] Stack {stack_name} failed: {error}")
                    return results
                
                results['stacks_updated'].append(stack_name)
                
                # Get stack outputs for next stacks
                outputs = self.cfn_service.get_stack_outputs(stack_cfn_client, stack_name)
                stack_outputs[stack_type] = outputs
                
                if callback:
                    callback(f"[OK] Stack {stack_name} updated successfully in {stack_region}")
            
            # Handle frontend artifacts and Cognito config (same as regular deploy)
            if deploy_frontend:
                # Get frontend URL
                regional_outputs = stack_outputs.get('frontend-regional', {})
                results['frontend_url'] = regional_outputs.get('CloudFrontURL')
                
                # Get Cognito configuration (from preserved or new outputs)
                cognito_outputs_dict = stack_outputs.get('frontend-cognito', {})
                if cognito_outputs_dict:
                    results['cognito_config'] = {
                        'user_pool_id': cognito_outputs_dict.get('UserPoolId'),
                        'client_id': cognito_outputs_dict.get('UserPoolClientId'),
                        'domain': cognito_outputs_dict.get('UserPoolDomain'),
                        'region': region,
                        'preserved': results['cognito_preserved']
                    }
                    
                    # Sync Cognito configuration to SSM Parameter Store
                    # This ensures SSM parameters are up-to-date even for preserved Cognito
                    user_pool_id = cognito_outputs_dict.get('UserPoolId')
                    client_id = cognito_outputs_dict.get('UserPoolClientId')
                    
                    if user_pool_id and client_id:
                        try:
                            from app.services.cognito_ssm_integration import CognitoSSMIntegration
                            
                            if callback:
                                callback("[SSM] Syncing Cognito configuration to SSM Parameter Store...")
                            
                            ssm_integration = CognitoSSMIntegration(
                                capability_name=capability_name,
                                environment=environment,
                                region=region,
                                credentials=self.credentials
                            )
                            
                            # Get frontend URL for redirect URI
                            frontend_url = results.get('frontend_url')
                            if frontend_url:
                                if not frontend_url.endswith('/auth/callback'):
                                    redirect_uri = f"{frontend_url.rstrip('/')}/auth/callback"
                                else:
                                    redirect_uri = frontend_url
                            else:
                                redirect_uri = None
                            
                            ssm_result = ssm_integration.store_cognito_from_stack_outputs(
                                stack_outputs=cognito_outputs_dict,
                                frontend_url=redirect_uri
                            )
                            
                            if callback:
                                success_count = sum(1 for r in ssm_result.values() if isinstance(r, dict) and r.get("status") == "created")
                                callback(f"[OK] Synced {success_count} Cognito parameters to SSM")
                            
                        except Exception as e:
                            logger.error(f"Failed to sync Cognito config to SSM: {e}")
                            if callback:
                                callback(f"[!] Warning: Failed to sync Cognito config to SSM: {e}")
            
            # Get backend URL if deployed
            if deploy_backend:
                service_outputs = stack_outputs.get('backend-service', {})
                domain_outputs = stack_outputs.get('backend-domain', {})
                
                if domain_outputs.get('ApiUrl'):
                    results['backend_url'] = domain_outputs.get('ApiUrl')
                else:
                    results['backend_url'] = service_outputs.get('ServiceURL')
            
            results['success'] = True
            
            if callback:
                preserved_count = len(results['stacks_preserved'])
                updated_count = len(results['stacks_updated'])
                callback(f"[OK] Update deployment completed: {updated_count} updated, {preserved_count} preserved")
                if results['cognito_preserved']:
                    callback(f"[OK] Cognito User Pool preserved - existing users retained")
            
            # Save deployment state
            try:
                stacks_info = []
                for stack_name, stack_data in results['stacks'].items():
                    if stack_data.get('success'):
                        stacks_info.append({
                            'stack_name': stack_name,
                            'stack_type': stack_data.get('stack_type'),
                            'region': stack_data.get('region'),
                            'preserved': stack_data.get('preserved', False),
                            'deployed_at': datetime.utcnow().isoformat()
                        })
                
                deployment_state_service.save_deployment_state(
                    capability_name=capability_name,
                    environment=environment,
                    region=region,
                    stacks=stacks_info,
                    deployment_metadata={
                        'frontend_deployed': deploy_frontend,
                        'backend_deployed': deploy_backend,
                        'frontend_url': results.get('frontend_url'),
                        'backend_url': results.get('backend_url'),
                        'cognito_preserved': results['cognito_preserved'],
                        'workflow_type': 'UPDATE'
                    }
                )
            except Exception as e:
                if callback:
                    callback(f"[!] Warning: Failed to save deployment state: {str(e)}")
            
            return results
            
        except Exception as e:
            results['error'] = str(e)
            if callback:
                callback(f"[X] Update deployment failed: {str(e)}")
            return results

    def deploy_capability_with_validation(
        self,
        config: Dict[str, Any],
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        dry_run: bool = False,
        callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Deploy capability with full dependency validation
        
        Args:
            config: Deployment configuration
            deploy_frontend: Whether to deploy frontend
            deploy_backend: Whether to deploy backend
            dry_run: If True, only validate without deploying
            callback: Progress callback
            
        Returns:
            Deployment result with validation details
        """
        capability_name = config.get('capability', {}).get('name', '')
        environment = config.get('target', {}).get('environment', '')
        region = config.get('target', {}).get('region', '')
        
        results = {
            'capability_name': capability_name,
            'environment': environment,
            'region': region,
            'dry_run': dry_run,
            'validation_result': None,
            'deployment_plan': None,
            'success': False,
            'error': None
        }
        
        try:
            if callback:
                mode = "DRY-RUN" if dry_run else "DEPLOYMENT"
                callback(f"[LAUNCH] Starting {mode} for {capability_name}-{environment}")
            
            # Step 1: Validate stack dependencies
            validation_result = self.validate_stack_dependencies(
                config, deploy_frontend, deploy_backend, callback
            )
            results['validation_result'] = {
                'success': validation_result.success,
                'summary': validation_result.summary,
                'issues': [
                    {
                        'severity': issue.severity.value,
                        'type': issue.issue_type.value,
                        'stack': issue.stack_name,
                        'description': issue.description,
                        'action': issue.suggested_action
                    }
                    for issue in validation_result.issues
                ],
                'deployment_order': validation_result.deployment_order
            }
            
            # Step 2: Get existing stack statuses
            existing_stacks = {}
            for stack_type in self.cfn_service.STACK_ORDER:
                if 'frontend' in stack_type and not deploy_frontend:
                    continue
                if 'backend' in stack_type and not deploy_backend:
                    continue
                
                stack_name = self.cfn_service.get_stack_name(capability_name, environment, stack_type)
                stack_region = 'us-east-1' if stack_type == 'frontend-global' else region
                status = self.dependency_validator.get_stack_status(stack_name, stack_region)
                if status:
                    existing_stacks[stack_name] = status
            
            # Step 3: Create deployment plan
            if validation_result.dependency_graph:
                plan = self.deployment_planner.create_deployment_plan(
                    validation_result.dependency_graph,
                    existing_stacks,
                    validation_result
                )
                results['deployment_plan'] = {
                    'total_stacks': plan.total_stacks,
                    'estimated_duration_minutes': plan.estimated_duration_minutes,
                    'validation_passed': plan.validation_passed,
                    'warnings': plan.warnings,
                    'steps': [
                        {
                            'step': step.step_number,
                            'stack': step.stack_name,
                            'type': step.stack_type,
                            'action': step.action.value,
                            'reason': step.reason
                        }
                        for step in plan.steps
                    ]
                }
                
                # Generate dry-run report
                if dry_run and callback:
                    report = self.deployment_planner.generate_dry_run_report(plan, validation_result)
                    for line in report.split('\n'):
                        callback(line)
            
            # If dry-run, stop here
            if dry_run:
                results['success'] = validation_result.success
                if callback:
                    if validation_result.success:
                        callback("[OK] Dry-run complete. Deployment is likely to succeed.")
                    else:
                        callback("[X] Dry-run complete. Deployment will likely fail.")
                return results
            
            # Step 4: Check if validation passed
            if not validation_result.success:
                results['error'] = f"Dependency validation failed: {validation_result.summary}"
                if callback:
                    callback(f"[X] {results['error']}")
                return results
            
            # Step 5: Proceed with actual deployment
            if callback:
                callback("[OK] Validation passed, proceeding with deployment...")
            
            deployment_result = self.deploy_capability(
                config, deploy_frontend, deploy_backend, callback, skip_validation=False
            )
            
            # Merge results
            results['stacks'] = deployment_result.get('stacks', {})
            results['frontend_url'] = deployment_result.get('frontend_url')
            results['backend_url'] = deployment_result.get('backend_url')
            results['success'] = deployment_result.get('success', False)
            results['error'] = deployment_result.get('error')
            
            return results
            
        except Exception as e:
            results['error'] = str(e)
            if callback:
                callback(f"[X] Deployment failed: {str(e)}")
            return results
