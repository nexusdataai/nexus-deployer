"""
Pre-Deployment Validator
Validates deployment environment before starting deployment
Detects and cleans up unstable stacks and orphaned resources
"""
import boto3
import time
import logging
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from botocore.exceptions import ClientError
from pathlib import Path

from app.models.validation import (
    ValidationReport,
    ValidationIssue,
    IssueType,
    Severity,
    StackStatus,
    OrphanedResource
)
from app.services.template_parser import TemplateParser
from app.services.resource_cleanup_registry import ResourceCleanupRegistry
from app.services.cleaners.s3_bucket_cleaner import S3BucketCleaner
from app.services.cleaners.alb_cleaner import ALBCleaner
from app.services.cleaners.cloudfront_cleaner import CloudFrontCleaner
from app.services.cleaners.ecr_repository_cleaner import ECRRepositoryCleaner
from app.services.cleaners.cloudwatch_log_group_cleaner import CloudWatchLogGroupCleaner
from app.utils.resource_resolver import ResourceResolver

logger = logging.getLogger(__name__)


class PreDeploymentValidator:
    """Validates deployment environment and cleans up issues"""
    
    # Unstable stack statuses that need cleanup
    UNSTABLE_STATUSES = [
        'ROLLBACK_COMPLETE',
        'DELETE_FAILED',
        'UPDATE_ROLLBACK_COMPLETE',
        'ROLLBACK_FAILED',
        'CREATE_FAILED'
    ]
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize validator with AWS credentials
        
        Args:
            credentials: Optional AWS credentials dict with keys:
                - aws_access_key_id
                - aws_secret_access_key
                - aws_session_token (optional)
        """
        self.credentials = credentials or {}
        self.template_parser = TemplateParser()
        self.cleanup_registry = ResourceCleanupRegistry()
        self.templates_dir = ResourceResolver.get_templates_dir()
        
        # Register all resource cleaners
        self._register_cleaners()
        
        logger.info("PreDeploymentValidator initialized")
    
    def _register_cleaners(self):
        """Register all resource type cleaners"""
        # Register S3 bucket cleaner
        self.cleanup_registry.register_resource_type(
            'AWS::S3::Bucket',
            S3BucketCleaner()
        )
        
        # Register ALB cleaner
        self.cleanup_registry.register_resource_type(
            'AWS::ElasticLoadBalancingV2::LoadBalancer',
            ALBCleaner()
        )
        
        # Register CloudFront cleaner
        self.cleanup_registry.register_resource_type(
            'AWS::CloudFront::Distribution',
            CloudFrontCleaner()
        )
        
        # Register ECR repository cleaner
        self.cleanup_registry.register_resource_type(
            'AWS::ECR::Repository',
            ECRRepositoryCleaner()
        )
        
        # Register CloudWatch log group cleaner
        self.cleanup_registry.register_resource_type(
            'AWS::Logs::LogGroup',
            CloudWatchLogGroupCleaner()
        )
        
        logger.info(f"Registered {len(self.cleanup_registry.get_supported_resource_types())} resource cleaners")
    
    def _get_client(self, service: str, region: str) -> Any:
        """Get boto3 client with credentials"""
        if self.credentials:
            return boto3.client(
                service,
                region_name=region,
                aws_access_key_id=self.credentials.get('aws_access_key_id'),
                aws_secret_access_key=self.credentials.get('aws_secret_access_key'),
                aws_session_token=self.credentials.get('aws_session_token')
            )
        else:
            return boto3.client(service, region_name=region)
    
    def check_stack_status(self, stack_name: str, region: str) -> StackStatus:
        """
        Check if stack exists and its status
        
        Args:
            stack_name: Name of the CloudFormation stack
            region: AWS region
            
        Returns:
            StackStatus enum value
        """
        try:
            cfn_client = self._get_client('cloudformation', region)
            response = cfn_client.describe_stacks(StackName=stack_name)
            
            stacks = response.get('Stacks', [])
            if not stacks:
                return StackStatus.NOT_EXISTS
            
            status = stacks[0].get('StackStatus', '')
            
            # Check if unstable
            if status in self.UNSTABLE_STATUSES:
                logger.warning(f"Stack {stack_name} is in unstable state: {status}")
                return StackStatus.UNSTABLE
            
            # Check if in progress
            if 'IN_PROGRESS' in status:
                return StackStatus.IN_PROGRESS
            
            # Check if stable
            if 'COMPLETE' in status and 'ROLLBACK' not in status:
                return StackStatus.STABLE
            
            # Default to unstable for any other status
            return StackStatus.UNSTABLE
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'ValidationError' or 'does not exist' in str(e).lower():
                return StackStatus.NOT_EXISTS
            else:
                logger.error(f"Error checking stack {stack_name}: {str(e)}")
                raise
    
    def cleanup_unstable_stack(
        self,
        stack_name: str,
        region: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Delete unstable stack
        
        Args:
            stack_name: Name of the CloudFormation stack
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            cfn_client = self._get_client('cloudformation', region)
            
            if callback:
                callback(f"Disabling termination protection for stack: {stack_name}")
            
            # Disable termination protection
            logger.info(f"Disabling termination protection for stack: {stack_name}")
            try:
                cfn_client.update_termination_protection(
                    StackName=stack_name,
                    EnableTerminationProtection=False
                )
            except ClientError as e:
                # If already disabled or not supported, continue
                logger.debug(f"Could not disable termination protection: {str(e)}")
            
            if callback:
                callback(f"Deleting unstable stack: {stack_name}")
            
            # Delete the stack
            logger.info(f"Deleting unstable stack: {stack_name}")
            cfn_client.delete_stack(StackName=stack_name)
            
            # Wait for deletion to complete
            if callback:
                callback(f"Waiting for stack deletion to complete: {stack_name}")
            
            logger.info(f"Waiting for stack deletion: {stack_name}")
            max_wait = 600  # 10 minutes
            wait_interval = 10
            elapsed = 0
            
            while elapsed < max_wait:
                time.sleep(wait_interval)
                elapsed += wait_interval
                
                status = self.check_stack_status(stack_name, region)
                
                if status == StackStatus.NOT_EXISTS:
                    logger.info(f"Stack {stack_name} successfully deleted")
                    if callback:
                        callback(f"Stack {stack_name} successfully deleted")
                    return True
                
                if callback and elapsed % 30 == 0:
                    callback(f"Still waiting for stack deletion ({elapsed}s elapsed)...")
            
            # Timeout
            logger.warning(f"Timeout waiting for stack deletion: {stack_name}")
            return False
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'ValidationError' or 'does not exist' in str(e).lower():
                logger.info(f"Stack {stack_name} does not exist (already deleted)")
                return True
            else:
                logger.error(f"Error deleting stack {stack_name}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error deleting stack {stack_name}: {str(e)}")
            return False
    
    def detect_orphaned_resources(
        self,
        stack_name: str,
        template_body: str,
        parameters: List[Dict[str, str]],
        region: str
    ) -> List[OrphanedResource]:
        """
        Find orphaned resources for a stack
        
        Args:
            stack_name: Name of the CloudFormation stack
            template_body: CloudFormation template content
            parameters: Parameter values
            region: AWS region
            
        Returns:
            List of OrphanedResource objects
        """
        orphaned_resources = []
        
        try:
            # Parse template to get resource definitions
            resource_defs = self.template_parser.parse_template(template_body, parameters)
            
            # Convert parameters list to dict
            param_dict = {}
            if parameters:
                for param in parameters:
                    param_dict[param.get('ParameterKey', '')] = param.get('ParameterValue', '')
            
            # Check each resource
            for resource_def in resource_defs:
                orphaned = self.cleanup_registry.detect_orphaned_resource(
                    resource_def,
                    region,
                    param_dict,
                    self.credentials if self.credentials else None
                )
                
                if orphaned:
                    orphaned.stack_name = stack_name
                    orphaned_resources.append(orphaned)
            
            return orphaned_resources
            
        except Exception as e:
            logger.error(f"Error detecting orphaned resources for stack {stack_name}: {str(e)}")
            return []
    
    def cleanup_orphaned_resources(
        self,
        orphaned_resources: List[OrphanedResource],
        callback: Optional[Callable] = None
    ) -> List[OrphanedResource]:
        """
        Remove orphaned resources
        
        Args:
            orphaned_resources: List of OrphanedResource objects
            callback: Optional callback for progress updates
            
        Returns:
            List of successfully cleaned up resources
        """
        cleaned_up = []
        
        # Sort resources by dependency order
        sorted_resources = self.cleanup_registry.get_cleanup_order(orphaned_resources)
        
        for resource in sorted_resources:
            try:
                if callback:
                    callback(f"Cleaning up {resource.resource_type}: {resource.resource_identifier}")
                
                success = self.cleanup_registry.cleanup_orphaned_resource(
                    resource,
                    self.credentials if self.credentials else None,
                    callback
                )
                
                if success:
                    cleaned_up.append(resource)
                    logger.info(f"Successfully cleaned up: {resource.resource_type} - {resource.resource_identifier}")
                else:
                    logger.warning(f"Failed to clean up: {resource.resource_type} - {resource.resource_identifier}")
                    
            except Exception as e:
                logger.error(f"Error cleaning up {resource.resource_identifier}: {str(e)}")
        
        return cleaned_up
    
    def validate_deployment(
        self,
        config: Dict[str, Any],
        deploy_frontend: bool,
        deploy_backend: bool,
        callback: Optional[Callable] = None
    ) -> ValidationReport:
        """
        Validate deployment configuration and environment
        
        Args:
            config: Deployment configuration
            deploy_frontend: Whether to deploy frontend stacks
            deploy_backend: Whether to deploy backend stacks
            callback: Optional callback for progress updates
            
        Returns:
            ValidationReport with issues found and cleanup results
        """
        start_time = time.time()
        issues_found = []
        issues_resolved = []
        issues_unresolved = []
        
        try:
            if callback:
                callback("Starting pre-deployment validation...")
            
            logger.info("Starting pre-deployment validation")
            
            # Get deployment configuration
            capability_name = config.get('capability_name', '')
            environment = config.get('environment', '')
            region = config.get('region', 'us-east-1')
            
            # Determine which stacks to validate based on deployment flags
            from app.services.cloudformation_service import CloudFormationDeploymentService
            cf_service = CloudFormationDeploymentService(self.credentials)
            
            stacks_to_validate = []
            for stack_type in cf_service.STACK_ORDER:
                # Filter based on deployment flags
                if deploy_frontend and stack_type.startswith('frontend'):
                    stacks_to_validate.append(stack_type)
                elif deploy_backend and stack_type.startswith('backend'):
                    stacks_to_validate.append(stack_type)
            
            if callback:
                callback(f"Validating {len(stacks_to_validate)} stacks...")
            
            logger.info(f"Validating {len(stacks_to_validate)} stacks")
            
            # Validate each stack
            for stack_type in stacks_to_validate:
                stack_name = cf_service.get_stack_name(capability_name, environment, stack_type)
                
                if callback:
                    callback(f"Checking stack: {stack_name}")
                
                logger.info(f"Checking stack: {stack_name}")
                
                # Check stack status
                status = self.check_stack_status(stack_name, region)
                
                # Handle UNSTABLE stacks - delete them first
                if status == StackStatus.UNSTABLE:
                    # Create issue for unstable stack
                    issue = ValidationIssue(
                        issue_type=IssueType.UNSTABLE_STACK,
                        severity=Severity.CRITICAL,
                        stack_name=stack_name,
                        resource_identifier=stack_name,
                        description=f"Stack {stack_name} is in an unstable state and needs cleanup"
                    )
                    issues_found.append(issue)
                    
                    # Try to cleanup
                    if callback:
                        callback(f"Cleaning up unstable stack: {stack_name}")
                    
                    logger.info(f"Stack {stack_name} is UNSTABLE - will delete and skip orphaned check")
                    
                    success = self.cleanup_unstable_stack(stack_name, region, callback)
                    
                    if success:
                        issue.resolved = True
                        issue.resolution_details = "Stack successfully deleted"
                        issues_resolved.append(issue)
                        logger.info(f"Resolved unstable stack: {stack_name}")
                        
                        # Skip orphaned resource check - stack deletion handles cleanup
                        if callback:
                            callback(f"[OK] Cleaned up unstable stack {stack_name} - skipping orphaned resource check")
                        logger.info(f"Skipping orphaned resource check for {stack_name} - stack deletion handles cleanup")
                    else:
                        issues_unresolved.append(issue)
                        logger.error(f"Failed to resolve unstable stack: {stack_name}")
                    
                    # Always skip orphaned check after attempting unstable stack deletion
                    continue
                
                # Handle STABLE stacks - skip orphaned resource check
                if status == StackStatus.STABLE:
                    if callback:
                        callback(f"[OK] Stack {stack_name} is stable - skipping orphaned resource check")
                    logger.info(f"Stack {stack_name} is STABLE - skipping orphaned resource check (resources are managed by stack)")
                    continue
                
                # Handle IN_PROGRESS stacks - skip orphaned resource check
                if status == StackStatus.IN_PROGRESS:
                    if callback:
                        callback(f"[!] Stack {stack_name} is in progress - skipping orphaned resource check")
                    logger.warning(f"Stack {stack_name} is IN_PROGRESS - skipping orphaned resource check")
                    continue
                
                # Handle NOT_EXISTS stacks - ONLY NOW check for orphaned resources
                if status == StackStatus.NOT_EXISTS:
                    if callback:
                        callback(f"Stack {stack_name} does not exist - checking for orphaned resources")
                    logger.info(f"Stack {stack_name} does NOT exist - checking for orphaned resources")
                    
                    # Check for orphaned resources that may have been left behind
                    try:
                        # Load template
                        template_body = cf_service.load_template(stack_type)
                        
                        # Build parameters from config
                        # Get all parameters needed for this stack type
                        stack_params = cf_service.build_parameters(
                            {
                                'capability': {'name': capability_name},
                                'target': {'environment': environment, 'region': region},
                                'infrastructure': config.get('infrastructure', {}),
                                'source': config.get('source', {}),
                                'tags': config.get('tags', {})
                            },
                            stack_type,
                            {}  # No stack outputs yet
                        )
                        
                        if callback:
                            callback(f"Checking for orphaned resources from {stack_name}...")
                        
                        # Detect orphaned resources
                        orphaned = self.detect_orphaned_resources(
                            stack_name,
                            template_body,
                            stack_params,
                            region
                        )
                        
                        if orphaned:
                            logger.info(f"Found {len(orphaned)} orphaned resources for {stack_name}")
                            if callback:
                                callback(f"[!] Found {len(orphaned)} orphaned resources from {stack_name}")
                            
                            # Create issues for orphaned resources
                            for resource in orphaned:
                                issue = ValidationIssue(
                                    issue_type=IssueType.ORPHANED_RESOURCE,
                                    severity=Severity.CRITICAL,
                                    stack_name=stack_name,
                                    resource_type=resource.resource_type,
                                    resource_identifier=resource.resource_identifier,
                                    description=f"Orphaned {resource.resource_type}: {resource.resource_identifier}"
                                )
                                issues_found.append(issue)
                                if callback:
                                    callback(f"[!] Orphaned resource: {resource.resource_type} - {resource.resource_identifier}")
                            
                            # Try to cleanup orphaned resources
                            if callback:
                                callback(f"[CLEAN] Cleaning up {len(orphaned)} orphaned resources...")
                            
                            cleaned = self.cleanup_orphaned_resources(orphaned, callback)
                            
                            # Mark issues as resolved or unresolved
                            for resource in orphaned:
                                matching_issue = next(
                                    (i for i in issues_found 
                                     if i.resource_identifier == resource.resource_identifier),
                                    None
                                )
                                
                                if matching_issue:
                                    if resource in cleaned:
                                        matching_issue.resolved = True
                                        matching_issue.resolution_details = "Resource successfully cleaned up"
                                        issues_resolved.append(matching_issue)
                                        if callback:
                                            callback(f"[OK] Cleaned up: {resource.resource_type} - {resource.resource_identifier}")
                                    else:
                                        issues_unresolved.append(matching_issue)
                                        if callback:
                                            callback(f"[X] Failed to clean up: {resource.resource_type} - {resource.resource_identifier}")
                        else:
                            if callback:
                                callback(f"[OK] No orphaned resources found from {stack_name}")
                    
                    except FileNotFoundError:
                        logger.warning(f"Template not found for {stack_type}, skipping orphaned resource check")
                    except Exception as e:
                        logger.error(f"Error checking orphaned resources for {stack_name}: {str(e)}")
                        if callback:
                            callback(f"[!] Error checking orphaned resources: {str(e)}")
            
            # Build validation report
            validation_time = time.time() - start_time
            success = len(issues_unresolved) == 0
            
            if success:
                summary = f"Validation successful. Found {len(issues_found)} issues, resolved {len(issues_resolved)}."
            else:
                summary = f"Validation failed. Found {len(issues_found)} issues, resolved {len(issues_resolved)}, {len(issues_unresolved)} unresolved."
            
            if callback:
                callback(summary)
            
            logger.info(summary)
            
            report = ValidationReport(
                success=success,
                issues_found=issues_found,
                issues_resolved=issues_resolved,
                issues_unresolved=issues_unresolved,
                validation_time=validation_time,
                summary=summary
            )
            
            return report
            
        except Exception as e:
            logger.error(f"Error during validation: {str(e)}")
            validation_time = time.time() - start_time
            
            return ValidationReport(
                success=False,
                issues_found=issues_found,
                issues_resolved=issues_resolved,
                issues_unresolved=issues_unresolved,
                validation_time=validation_time,
                summary=f"Validation error: {str(e)}"
            )
