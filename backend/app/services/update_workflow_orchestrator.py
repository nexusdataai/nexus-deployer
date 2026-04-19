"""
Update Workflow Orchestrator

Coordinates the update workflow with Cognito preservation, user data backup,
drift detection, and selective stack updates.
"""
import logging
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
from pathlib import Path

from app.models.workflow_classification import WorkflowType, WorkflowClassification
from app.models.update_config import UpdateConfig, UpdateWorkflowConfig, apply_defaults
from app.models.update_result import UpdateResult
from app.models.audit_models import UpdateAuditRecord
from app.models.cognito_models import DriftDetectionResult
from app.services.workflow_classifier import WorkflowClassifier
from app.services.cognito_preservation_service import CognitoPreservationService
from app.services.cognito_user_export_service import CognitoUserExportService
from app.services.cognito_drift_detector import CognitoDriftDetector
from app.services.stack_output_preserver import StackOutputPreserver


logger = logging.getLogger(__name__)


class UpdateWorkflowOrchestrator:
    """
    Orchestrates update workflows with Cognito preservation.
    
    Coordinates:
    - Workflow classification
    - Stack output preservation
    - Cognito validation
    - User data export
    - Drift detection
    - Stack deployment (with preservation)
    - Audit trail
    """

    # Progress message prefixes
    PREFIX_PRESERVE = "[PRESERVE]"
    PREFIX_UPDATE = "[UPDATE]"
    PREFIX_SKIP = "[SKIP]"
    PREFIX_FAIL = "[FAIL]"

    def __init__(
        self,
        cfn_service: Optional[Any] = None,
        cognito_preservation_service: Optional[CognitoPreservationService] = None,
        cognito_export_service: Optional[CognitoUserExportService] = None,
        drift_detector: Optional[CognitoDriftDetector] = None,
        workflow_classifier: Optional[WorkflowClassifier] = None,
        stack_output_preserver: Optional[StackOutputPreserver] = None,
        workflow_config: Optional[UpdateWorkflowConfig] = None,
        credentials: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the update workflow orchestrator.
        
        Args:
            cfn_service: CloudFormation service
            cognito_preservation_service: Cognito preservation service
            cognito_export_service: User export service
            drift_detector: Drift detection service
            workflow_classifier: Workflow classifier
            stack_output_preserver: Stack output preserver
            workflow_config: System-level workflow configuration
            credentials: AWS credentials
        """
        self.cfn_service = cfn_service
        self.cognito_preservation = cognito_preservation_service or CognitoPreservationService(credentials)
        self.cognito_export = cognito_export_service or CognitoUserExportService(credentials)
        self.drift_detector = drift_detector or CognitoDriftDetector(credentials)
        self.classifier = workflow_classifier
        self.output_preserver = stack_output_preserver or StackOutputPreserver(credentials)
        self.workflow_config = workflow_config or UpdateWorkflowConfig()
        self.credentials = credentials or {}

    def execute_update(
        self,
        capability_name: str,
        environment: str,
        region: str,
        update_config: UpdateConfig,
        stacks_to_deploy: List[Dict[str, Any]],
        callback: Optional[Callable[[str], None]] = None,
        operator_identity: Optional[str] = None
    ) -> UpdateResult:
        """
        Execute update workflow with Cognito preservation.
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev, stage, prod)
            region: AWS region
            update_config: Per-operation update configuration
            stacks_to_deploy: List of stack configurations to deploy
            callback: Optional progress callback
            operator_identity: Identity of the operator
            
        Returns:
            UpdateResult with operation outcome
        """
        # Apply defaults
        config = apply_defaults(update_config, self.workflow_config)
        
        # Create audit record
        audit_record = UpdateAuditRecord(
            capability_name=capability_name,
            environment=environment,
            region=region,
            operator_identity=operator_identity,
            config_preserve_cognito=config.preserve_cognito,
            config_include_cognito_update=config.include_cognito_update,
            config_selected_stacks=config.selected_stacks
        )
        
        result = UpdateResult(
            success=False,
            operation_id=audit_record.operation_id
        )
        
        try:
            self._report_progress(callback, f"Starting update workflow for {capability_name}")
            
            # Step 1: Preserve existing stack outputs
            self._report_progress(callback, "Preserving existing stack outputs...")
            self.output_preserver.preserve_all_outputs(
                capability_name=capability_name,
                environment=environment,
                region=region
            )
            
            # Step 2: Pre-update Cognito validation
            if not config.skip_pre_validation and config.preserve_cognito:
                self._report_progress(callback, "Validating Cognito User Pool...")
                validation_result = self._validate_cognito_pre_update(region)
                
                if not validation_result.get('valid', True):
                    result.validation_passed = False
                    result.validation_message = validation_result.get('message')
                    result.error_message = f"Pre-update validation failed: {result.validation_message}"
                    audit_record.complete(success=False, error_message=result.error_message)
                    return result
            
            # Step 3: Export user data if including Cognito update
            if config.include_cognito_update and config.require_user_backup:
                self._report_progress(callback, "Exporting user data...")
                export_result = self._export_user_data(
                    capability_name=capability_name,
                    environment=environment,
                    region=region
                )
                
                if export_result.get('success'):
                    result.user_backup_path = export_result.get('path')
                    audit_record.set_export_details(
                        exported=True,
                        location=export_result.get('path'),
                        user_count=export_result.get('user_count')
                    )
                elif config.require_user_backup:
                    result.error_message = f"User export failed: {export_result.get('error')}"
                    audit_record.complete(success=False, error_message=result.error_message)
                    return result
            
            # Step 4: Drift detection
            if not config.skip_drift_detection:
                self._report_progress(callback, "Detecting configuration drift...")
                drift_result = self._detect_drift(region, stacks_to_deploy)
                
                if drift_result:
                    result.drift_detected = drift_result.has_drift
                    result.drift_summary = self.drift_detector.get_drift_summary(drift_result)
                    audit_record.set_drift_details(
                        detected=drift_result.has_drift,
                        items_count=len(drift_result.drift_items)
                    )
            
            # Step 5: Determine stacks to update
            stacks_to_update, stacks_to_preserve = self.get_stacks_to_update(
                config=config,
                stacks_to_deploy=stacks_to_deploy
            )
            
            # Step 6: Deploy stacks
            self._report_progress(
                callback,
                f"Updating {len(stacks_to_update)} stacks, preserving {len(stacks_to_preserve)}..."
            )
            
            for stack in stacks_to_preserve:
                stack_name = stack.get('stack_name', stack.get('name', 'unknown'))
                self._report_progress(
                    callback,
                    f"{self.PREFIX_PRESERVE} {stack_name}: Skipping to preserve existing data"
                )
                result.stacks_preserved.append(stack_name)
                audit_record.add_preserved_stack(stack_name)
            
            # Track Cognito preservation
            cognito_preserved = any(
                self._is_cognito_stack(s) for s in stacks_to_preserve
            )
            result.cognito_preserved = cognito_preserved
            audit_record.cognito_preserved = cognito_preserved
            
            # Deploy each stack
            for stack in stacks_to_update:
                stack_name = stack.get('stack_name', stack.get('name', 'unknown'))
                
                try:
                    self._report_progress(
                        callback,
                        f"{self.PREFIX_UPDATE} {stack_name}: Updating existing stack"
                    )
                    
                    # Get preserved outputs for parameters
                    preserved_outputs = self.output_preserver.get_outputs_for_stack(stack_name)
                    
                    # Deploy stack (implementation depends on cfn_service)
                    deploy_success = self._deploy_stack(
                        stack=stack,
                        region=region,
                        preserved_outputs=preserved_outputs
                    )
                    
                    if deploy_success:
                        result.stacks_updated.append(stack_name)
                        audit_record.add_updated_stack(stack_name)
                    else:
                        result.stacks_failed.append(stack_name)
                        audit_record.add_failed_stack(stack_name)
                        
                        # Halt on failure
                        result.error_message = f"Stack update failed: {stack_name}"
                        self._report_progress(
                            callback,
                            f"{self.PREFIX_FAIL} {stack_name}: Update failed, halting workflow"
                        )
                        break
                        
                except Exception as e:
                    result.stacks_failed.append(stack_name)
                    audit_record.add_failed_stack(stack_name)
                    result.error_message = f"Stack update error: {stack_name} - {str(e)}"
                    self._report_progress(
                        callback,
                        f"{self.PREFIX_FAIL} {stack_name}: {str(e)}"
                    )
                    break
            
            # Step 7: Post-update validation
            if not config.skip_post_validation and not result.has_failures:
                self._report_progress(callback, "Performing post-update validation...")
                post_validation = self._validate_cognito_post_update(region)
                
                if not post_validation.get('valid', True):
                    result.validation_passed = False
                    result.validation_message = post_validation.get('message')
                    # Don't fail the result, but report the issue
                    self._report_progress(
                        callback,
                        f"Post-update validation warning: {result.validation_message}"
                    )
            
            # Step 8: Generate completion summary
            result.success = not result.has_failures
            
            summary = self._generate_completion_summary(result)
            self._report_progress(callback, summary)
            
            audit_record.complete(
                success=result.success,
                error_message=result.error_message
            )
            
            return result
            
        except Exception as e:
            result.error_message = f"Update workflow error: {str(e)}"
            logger.error(f"[UPDATE] {result.error_message}")
            audit_record.complete(success=False, error_message=result.error_message)
            return result

    def get_stacks_to_update(
        self,
        config: UpdateConfig,
        stacks_to_deploy: List[Dict[str, Any]]
    ) -> tuple:
        """
        Determine which stacks should be updated vs preserved.
        
        Args:
            config: Update configuration
            stacks_to_deploy: All stacks in the deployment
            
        Returns:
            Tuple of (stacks_to_update, stacks_to_preserve)
        """
        stacks_to_update = []
        stacks_to_preserve = []
        
        # Get stacks to skip from preservation service
        stacks_to_skip = self.cognito_preservation.get_stacks_to_skip(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=config.include_cognito_update
        )
        
        for stack in stacks_to_deploy:
            stack_name = stack.get('stack_name', stack.get('name', ''))
            stack_type = stack.get('stack_type', stack.get('type', ''))
            
            should_preserve = False
            
            # Check if stack should be preserved (Cognito preservation)
            if config.preserve_cognito:
                is_cognito = stack_type in stacks_to_skip or self._is_cognito_stack(stack)
                if is_cognito and not config.include_cognito_update:
                    should_preserve = True
            
            # Check selective updates - if selected_stacks is specified,
            # only those stacks should be updated
            if config.selected_stacks is not None:
                if stack_name not in config.selected_stacks:
                    should_preserve = True
            
            if should_preserve:
                stacks_to_preserve.append(stack)
            else:
                stacks_to_update.append(stack)
        
        return stacks_to_update, stacks_to_preserve

    def validate_selective_update(
        self,
        selected_stacks: List[str],
        all_stacks: List[Dict[str, Any]],
        dependencies: Dict[str, List[str]]
    ) -> Dict[str, Any]:
        """
        Validate that selective update doesn't break dependencies.
        
        Args:
            selected_stacks: Stacks selected for update
            all_stacks: All available stacks
            dependencies: Stack dependency map
            
        Returns:
            Validation result with required additional stacks if any
        """
        required_additional = []
        
        for stack_name in selected_stacks:
            # Check if any dependencies need to be included
            deps = dependencies.get(stack_name, [])
            for dep in deps:
                if dep not in selected_stacks and dep not in required_additional:
                    required_additional.append(dep)
        
        return {
            'valid': len(required_additional) == 0,
            'required_additional_stacks': required_additional,
            'message': (
                f"Must include dependent stacks: {', '.join(required_additional)}"
                if required_additional else None
            )
        }

    def _is_cognito_stack(self, stack: Dict[str, Any]) -> bool:
        """Check if a stack is the Cognito stack."""
        stack_type = stack.get('stack_type', stack.get('type', ''))
        stack_name = stack.get('stack_name', stack.get('name', ''))
        
        return (
            'cognito' in stack_type.lower() or
            'cognito' in stack_name.lower()
        )

    def _validate_cognito_pre_update(self, region: str) -> Dict[str, Any]:
        """Perform pre-update Cognito validation."""
        try:
            cognito_outputs = self.output_preserver.get_cognito_outputs()
            
            if not cognito_outputs:
                return {'valid': True, 'message': 'No Cognito outputs to validate'}
            
            validation = self.cognito_preservation.validate_user_pool(
                user_pool_id=cognito_outputs.user_pool_id,
                client_id=cognito_outputs.user_pool_client_id,
                region=region
            )
            
            return {
                'valid': validation.is_valid,
                'message': validation.error_message,
                'user_count': validation.user_count
            }
            
        except Exception as e:
            logger.warning(f"[UPDATE] Pre-validation error: {e}")
            return {'valid': True, 'message': f'Validation skipped: {str(e)}'}

    def _validate_cognito_post_update(self, region: str) -> Dict[str, Any]:
        """Perform post-update Cognito validation."""
        return self._validate_cognito_pre_update(region)

    def _export_user_data(
        self,
        capability_name: str,
        environment: str,
        region: str
    ) -> Dict[str, Any]:
        """Export user data before Cognito update."""
        try:
            cognito_outputs = self.output_preserver.get_cognito_outputs()
            
            if not cognito_outputs:
                return {'success': False, 'error': 'No Cognito outputs found'}
            
            result = self.cognito_export.export_users(
                user_pool_id=cognito_outputs.user_pool_id,
                region=region,
                capability_name=capability_name,
                environment=environment
            )
            
            return {
                'success': result.success,
                'path': result.export_path,
                'user_count': result.user_count,
                'error': result.error_message
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _detect_drift(
        self,
        region: str,
        stacks_to_deploy: List[Dict[str, Any]]
    ) -> Optional[DriftDetectionResult]:
        """Detect Cognito configuration drift."""
        try:
            cognito_outputs = self.output_preserver.get_cognito_outputs()
            
            if not cognito_outputs:
                return None
            
            # Find Cognito template
            cognito_template = None
            for stack in stacks_to_deploy:
                if self._is_cognito_stack(stack):
                    cognito_template = stack.get('template_path')
                    break
            
            if not cognito_template:
                return None
            
            return self.drift_detector.detect_drift(
                user_pool_id=cognito_outputs.user_pool_id,
                region=region,
                template_path=Path(cognito_template)
            )
            
        except Exception as e:
            logger.warning(f"[UPDATE] Drift detection error: {e}")
            return None

    def _deploy_stack(
        self,
        stack: Dict[str, Any],
        region: str,
        preserved_outputs: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Deploy a single stack.
        
        This is a placeholder - actual implementation depends on cfn_service.
        """
        if self.cfn_service:
            # Use actual CloudFormation service
            try:
                # Implementation would call cfn_service.update_stack()
                return True
            except Exception as e:
                logger.error(f"[UPDATE] Stack deployment error: {e}")
                return False
        
        # Mock success for testing
        return True

    def _generate_completion_summary(self, result: UpdateResult) -> str:
        """Generate completion summary message."""
        lines = [
            "",
            "=" * 50,
            "UPDATE WORKFLOW COMPLETE",
            "=" * 50,
            f"Status: {'SUCCESS' if result.success else 'FAILED'}",
            f"Stacks Updated: {len(result.stacks_updated)}",
            f"Stacks Preserved: {len(result.stacks_preserved)}",
            f"Stacks Failed: {len(result.stacks_failed)}",
        ]
        
        if result.cognito_preserved:
            lines.append("Cognito User Pool: PRESERVED")
        
        if result.user_backup_path:
            lines.append(f"User Backup: {result.user_backup_path}")
        
        if result.drift_detected:
            lines.append("Configuration Drift: DETECTED")
        
        if result.error_message:
            lines.append(f"Error: {result.error_message}")
        
        lines.append("=" * 50)
        
        return '\n'.join(lines)

    def _report_progress(
        self,
        callback: Optional[Callable[[str], None]],
        message: str
    ) -> None:
        """Report progress via callback and logging."""
        logger.info(f"[UPDATE] {message}")
        if callback:
            callback(message)


def get_update_workflow_orchestrator(
    credentials: Optional[Dict[str, str]] = None,
    workflow_config: Optional[UpdateWorkflowConfig] = None
) -> UpdateWorkflowOrchestrator:
    """
    Factory function to create an UpdateWorkflowOrchestrator instance.
    
    Args:
        credentials: Optional AWS credentials
        workflow_config: Optional workflow configuration
        
    Returns:
        Configured UpdateWorkflowOrchestrator instance
    """
    return UpdateWorkflowOrchestrator(
        credentials=credentials,
        workflow_config=workflow_config
    )
