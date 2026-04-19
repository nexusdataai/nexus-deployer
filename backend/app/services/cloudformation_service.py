"""
CloudFormation Deployment Service
Cross-platform Python implementation of deployment automation
"""
import boto3
import time
import yaml
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from botocore.exceptions import ClientError, WaiterError
from datetime import datetime

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.utils.resource_resolver import ResourceResolver


class CloudFormationDeploymentService:
    """Service for deploying CloudFormation stacks"""
    
    # Stack deployment order - Backend first (foundation), then Frontend (depends on backend APIs)
    # Backend stacks provide the foundation, APIs, and services that frontend depends on
    STACK_ORDER = [
        # Backend stacks first - foundation and core services
        "backend-foundation",      # CloudWatch, basic infrastructure
        "backend-iam-roles",       # IAM roles and policies
        "backend-regional-cert",   # SSL certificates for backend
        "backend-storage",         # DynamoDB, S3, ECR
        "backend-network",         # VPC, subnets, security groups
        "backend-service",         # ECS service, ALB (HTTP only initially)
        "backend-domain",          # Route53, SSL cert, ALB HTTPS update
        
        # Frontend stacks second - depends on backend being ready
        "frontend-global",         # CloudFront, WAF (global resources)
        "frontend-cognito",        # Cognito User Pool
        "frontend-regional",       # S3 bucket, regional frontend resources
    ]
    
    # Template mappings
    TEMPLATE_MAP = {
        "frontend-global": "frontend/global-stack.yaml",
        "frontend-cognito": "frontend/cognito-stack.yaml",
        "frontend-regional": "frontend/regional-stack.yaml",
        "backend-foundation": "backend/foundation-stack.yaml",
        "backend-iam-roles": "backend/iam-roles-stack.yaml",
        "backend-regional-cert": "backend/regional-cert-stack.yaml",
        "backend-storage": "backend/storage-stack.yaml",
        "backend-network": "backend/network-stack.yaml",
        "backend-service": "backend/service-stack.yaml",
        "backend-domain": "backend/domain-stack.yaml",
    }
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize CloudFormation service
        
        Args:
            credentials: Optional AWS credentials dict with keys:
                - aws_access_key_id
                - aws_secret_access_key
                - aws_session_token (optional)
        """
        self.credentials = credentials or {}
        self.templates_dir = ResourceResolver.get_templates_dir()
        self._clients_cache: Dict[str, Any] = {}  # Cache clients by service:region key
        
    def _get_client(self, service: str, region: str, force_new: bool = False) -> Any:
        """Get boto3 client with credentials
        
        Args:
            service: AWS service name (e.g., 'cloudformation', 's3')
            region: AWS region
            force_new: If True, create a new client even if cached
            
        Returns:
            boto3 client
        """
        cache_key = f"{service}:{region}"
        
        if not force_new and cache_key in self._clients_cache:
            return self._clients_cache[cache_key]
        
        kw = {"region_name": region, **self.credentials}
        client = boto3.client(service, **merge_vpc_boto3_kwargs(service, region, kw))
        self._clients_cache[cache_key] = client
        return client
    
    def refresh_credentials(self, new_credentials: Dict[str, str]):
        """Update credentials and clear client cache
        
        Args:
            new_credentials: New AWS credentials dict
        """
        self.credentials = new_credentials
        self._clients_cache.clear()  # Force new clients with new credentials
    
    def load_template(self, template_name: str) -> str:
        """Load CloudFormation template"""
        template_path = self.templates_dir / self.TEMPLATE_MAP[template_name]
        
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        with open(template_path, 'r') as f:
            return f.read()
    
    def get_stack_name(self, capability_name: str, environment: str, stack_type: str) -> str:
        """Generate stack name - sanitize to meet CloudFormation requirements"""
        # CloudFormation stack names must match pattern: [a-zA-Z][-a-zA-Z0-9]*
        # Replace spaces and invalid characters with hyphens
        sanitized_name = capability_name.replace(' ', '-').replace('_', '-')
        # Remove any other invalid characters
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        # Ensure it starts with a letter
        if sanitized_name and not sanitized_name[0].isalpha():
            sanitized_name = 'stack-' + sanitized_name
        return f"{sanitized_name}-{environment}-{stack_type}"
    
    def stack_exists(self, cfn_client: Any, stack_name: str) -> bool:
        """Check if stack exists and is in a state that can be updated"""
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get('Stacks', [])
            if stacks:
                status = stacks[0].get('StackStatus', 'UNKNOWN')
                # Stacks in these states cannot be updated and should be treated as "doesn't exist"
                # They need to be deleted first before creating a new stack
                failed_states = [
                    'ROLLBACK_COMPLETE',
                    'ROLLBACK_FAILED',
                    'DELETE_FAILED',
                ]
                if status in failed_states:
                    return False  # Treat as doesn't exist - needs deletion
                # Stack exists and can be updated
                return True
            return False
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = str(e).lower()
            
            # Stack doesn't exist - this is expected for new deployments
            if error_code == 'ValidationError' or 'does not exist' in error_message:
                return False
            
            # Some other error - re-raise it
            raise
    
    def get_stack_status(self, cfn_client: Any, stack_name: str) -> Optional[str]:
        """Get stack status"""
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            return response['Stacks'][0]['StackStatus']
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            # Stack doesn't exist - return None (expected for new stacks)
            if error_code == 'ValidationError' and 'does not exist' in error_message:
                return None
            
            # Credential/auth errors - log and re-raise so caller can handle
            if error_code in ['ExpiredTokenException', 'InvalidClientTokenId', 'AccessDenied', 'UnauthorizedAccess']:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"AWS credential error checking stack {stack_name}: [{error_code}] {error_message}")
                raise  # Re-raise so wait_for_stack can handle it
            
            # Other errors - log but return None
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error checking stack status for {stack_name}: [{error_code}] {error_message}")
            return None
    
    def get_stack_outputs(self, cfn_client: Any, stack_name: str) -> Dict[str, str]:
        """Get stack outputs"""
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            outputs = response['Stacks'][0].get('Outputs', [])
            return {o['OutputKey']: o['OutputValue'] for o in outputs}
        except ClientError:
            return {}
    
    def wait_for_stack(self, cfn_client: Any, stack_name: str, operation: str, 
                      callback: Optional[callable] = None) -> Tuple[bool, Optional[str]]:
        """
        Wait for stack operation to complete
        
        Args:
            cfn_client: CloudFormation client
            stack_name: Name of the stack
            operation: Operation type ('create', 'update', 'delete')
            callback: Optional callback function for progress updates
            
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        waiter_map = {
            'create': 'stack_create_complete',
            'update': 'stack_update_complete',
            'delete': 'stack_delete_complete',
        }
        
        waiter_name = waiter_map.get(operation)
        
        # Verify we can communicate with AWS before starting the wait loop
        if callback:
            callback(f"{stack_name}: Verifying AWS connectivity...")
        
        try:
            # Test API connectivity by getting initial status
            initial_status = self.get_stack_status(cfn_client, stack_name)
            if callback:
                callback(f"{stack_name}: [OK] AWS connectivity verified, initial status: {initial_status or 'Stack not yet visible'}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            if callback:
                callback(f"{stack_name}: [X] AWS connectivity check failed: [{error_code}] {error_message}")
            
            # If it's a credential error, fail immediately
            if error_code in ['ExpiredTokenException', 'InvalidClientTokenId', 'AccessDenied', 'UnauthorizedAccess']:
                return False, f"AWS credentials invalid or expired: [{error_code}] {error_message}"
        if not waiter_name:
            raise ValueError(f"Invalid operation: {operation}")
        
        try:
            # Poll for status updates
            max_attempts = 240  # 60 minutes (15 second intervals)
            delay = 15  # Reduced from 30 to 15 seconds for more responsive UI
            
            if callback:
                callback(f"{stack_name}: Starting {operation} operation monitoring...")
                callback(f"{stack_name}: Will check status every {delay} seconds (max {max_attempts} attempts)")
            
            last_status = None
            consecutive_errors = 0
            max_consecutive_errors = 3  # Allow a few retries before failing
            
            for attempt in range(max_attempts):
                try:
                    status = self.get_stack_status(cfn_client, stack_name)
                    consecutive_errors = 0  # Reset error counter on success
                    
                    # Log status on every check to keep UI updated
                    if status != last_status:
                        if callback:
                            elapsed_mins = int((attempt * delay) / 60)
                            callback(f"{stack_name}: Status changed to {status or 'PENDING'} (elapsed: {elapsed_mins}m)")
                        last_status = status
                    else:
                        # Even if status hasn't changed, send periodic updates
                        if callback and attempt > 0:
                            elapsed_mins = int((attempt * delay) / 60)
                            elapsed_secs = attempt * delay
                            callback(f"{stack_name}: {status or 'PENDING'} - {elapsed_secs}s elapsed...")
                    
                    # Special case for delete operation: if stack no longer exists, deletion succeeded
                    if operation == 'delete' and status is None:
                        if callback:
                            callback(f"{stack_name}: [OK] Stack deleted successfully (no longer exists)")
                        return True, None
                    
                    # Check for completion or failure
                    # IMPORTANT: Check for ROLLBACK and FAILED before COMPLETE
                    # because ROLLBACK_COMPLETE contains "COMPLETE" but is actually a failure
                    if status and 'ROLLBACK' in status:
                        error = self._get_stack_failure_reason(cfn_client, stack_name)
                        if callback:
                            callback(f"{stack_name}: [X] {status} - Rollback detected")
                            callback(f"{stack_name}: [X] Rollback reason: {error}")
                        return False, f"Stack rollback: {error}"
                    elif status and 'FAILED' in status:
                        error = self._get_stack_failure_reason(cfn_client, stack_name)
                        if callback:
                            callback(f"{stack_name}: [X] {status}")
                            callback(f"{stack_name}: [X] Failure reason: {error}")
                        return False, error
                    elif status in ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'DELETE_COMPLETE', 'IMPORT_COMPLETE']:
                        if callback:
                            callback(f"{stack_name}: [OK] {status} - Success!")
                        return True, None
                    
                    time.sleep(delay)
                    
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    error_message = e.response.get('Error', {}).get('Message', str(e))
                    consecutive_errors += 1
                    
                    # Check for credential expiration errors
                    if error_code in ['ExpiredTokenException', 'InvalidClientTokenId', 'AccessDenied', 'UnauthorizedAccess']:
                        if callback:
                            callback(f"{stack_name}: [!] AWS credentials may have expired: [{error_code}]")
                            callback(f"{stack_name}: [!] Error: {error_message}")
                            callback(f"{stack_name}: [!] Consecutive errors: {consecutive_errors}/{max_consecutive_errors}")
                        
                        if consecutive_errors >= max_consecutive_errors:
                            if callback:
                                callback(f"{stack_name}: [X] Too many credential errors - deployment cannot continue")
                                callback(f"{stack_name}: [X] Please check if your AWS session has expired")
                            return False, f"AWS credentials expired or invalid: [{error_code}] {error_message}"
                    else:
                        if callback:
                            callback(f"{stack_name}: [!] AWS API Error while checking status: {error_code}")
                            callback(f"{stack_name}: [!] Error details: {error_message}")
                    
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
                except Exception as e:
                    consecutive_errors += 1
                    if callback:
                        callback(f"{stack_name}: [!] Error checking status - {str(e)}")
                        callback(f"{stack_name}: [!] Consecutive errors: {consecutive_errors}/{max_consecutive_errors}")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        if callback:
                            callback(f"{stack_name}: [X] Too many consecutive errors - stopping")
                        return False, f"Too many errors checking stack status: {str(e)}"
                    
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(delay)
            
            if callback:
                callback(f"{stack_name}: [X] Timeout after {max_attempts * delay} seconds ({int(max_attempts * delay / 60)} minutes)")
                callback(f"{stack_name}: [X] Last known status: {last_status or 'UNKNOWN'}")
            return False, "Timeout waiting for stack operation"
            
        except WaiterError as e:
            error = self._get_stack_failure_reason(cfn_client, stack_name)
            if callback:
                callback(f"{stack_name}: [X] Waiter error - {error}")
            return False, error
        except Exception as e:
            if callback:
                callback(f"{stack_name}: [X] Exception during wait - {str(e)}")
            return False, str(e)
    
    def _get_stack_failure_reason(self, cfn_client: Any, stack_name: str) -> str:
        """Get detailed failure reason from stack events"""
        try:
            response = cfn_client.describe_stack_events(StackName=stack_name)
            events = response.get('StackEvents', [])
            
            # Find failed events
            for event in events:
                status = event.get('ResourceStatus', '')
                if 'FAILED' in status:
                    reason = event.get('ResourceStatusReason', 'Unknown error')
                    resource = event.get('LogicalResourceId', 'Unknown resource')
                    return f"{resource}: {reason}"
            
            return "Stack operation failed"
        except Exception:
            return "Unable to determine failure reason"
    
    def create_or_update_stack(self, cfn_client: Any, stack_name: str, 
                              template_body: str, parameters: List[Dict[str, str]],
                              tags: List[Dict[str, str]], capabilities: List[str],
                              callback: Optional[callable] = None) -> Tuple[bool, Optional[str]]:
        """
        Create or update a CloudFormation stack
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        # Check if stack exists and its status
        region = cfn_client.meta.region_name
        stack_status = None
        stack_cannot_be_updated = False
        
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get('Stacks', [])
            if stacks:
                stack_status = stacks[0].get('StackStatus', 'UNKNOWN')
                
                # States where stack cannot be updated and must be deleted/recreated
                non_updatable_states = [
                    'ROLLBACK_COMPLETE',        # Stack rolled back, cannot update
                    'ROLLBACK_FAILED',          # Rollback failed, stuck state
                    'DELETE_FAILED',            # Deletion failed, stuck state
                    'UPDATE_ROLLBACK_FAILED',   # Update rollback failed, stuck state
                    'CREATE_FAILED',            # Creation failed
                    'UPDATE_ROLLBACK_COMPLETE', # Update rolled back completely
                ]
                stack_cannot_be_updated = stack_status in non_updatable_states
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'ValidationError' or 'does not exist' in str(e).lower():
                # Stack doesn't exist - this is fine
                stack_status = None
            else:
                # Some other error - re-raise it
                raise
        
        # For backend-service stacks, check for orphaned ALBs ONLY if:
        # 1. Stack doesn't exist at all, OR
        # 2. Stack exists in a non-updatable state (must be recreated)
        if 'backend-service' in stack_name or 'service' in stack_name:
            if stack_status is None or stack_cannot_be_updated:
                # Extract ALB name from stack name (format: {capability}-{env}-backend-service)
                # ALB name format: {capability}-{env}-alb
                alb_name = stack_name.replace('-backend-service', '-alb')
                if callback:
                    if stack_status is None:
                        callback(f"{stack_name}: Stack doesn't exist, checking for orphaned resources...")
                    else:
                        callback(f"{stack_name}: Stack in {stack_status} state (non-updatable), checking for orphaned resources...")
                self._cleanup_orphaned_alb(alb_name, region, callback)
        
        # For frontend-global stacks, check for orphaned WAF log groups ONLY if:
        # 1. Stack doesn't exist at all, OR
        # 2. Stack exists in a non-updatable state (must be recreated)
        if 'frontend-global' in stack_name:
            if stack_status is None or stack_cannot_be_updated:
                # Extract capability and environment from stack name
                # Format: {capability}-{env}-frontend-global
                parts = stack_name.replace('-frontend-global', '').rsplit('-', 1)
                if len(parts) == 2:
                    capability_name, environment = parts
                    if callback:
                        if stack_status is None:
                            callback(f"{stack_name}: Stack doesn't exist, checking for orphaned WAF resources...")
                        else:
                            callback(f"{stack_name}: Stack in {stack_status} state (non-updatable), checking for orphaned WAF resources...")
                    self._cleanup_orphaned_waf_log_group(capability_name, environment, callback)
        
        # For backend-storage stacks, check for orphaned resources ONLY if:
        # 1. Stack doesn't exist at all, OR
        # 2. Stack exists in a non-updatable state (must be recreated)
        if 'backend-storage' in stack_name or 'storage' in stack_name:
            if stack_status is None or stack_cannot_be_updated:
                # Extract capability and environment from stack name
                # Format: {capability}-{env}-backend-storage
                parts = stack_name.replace('-backend-storage', '').rsplit('-', 1)
                if len(parts) == 2:
                    capability_name, environment = parts
                    if callback:
                        if stack_status is None:
                            callback(f"{stack_name}: Stack doesn't exist, checking for orphaned storage resources...")
                        else:
                            callback(f"{stack_name}: Stack in {stack_status} state (non-updatable), checking for orphaned storage resources...")
                    # Cleanup all orphaned storage resources
                    self._cleanup_orphaned_dynamodb_tables(capability_name, environment, region, callback)
                    self._cleanup_orphaned_storage_s3_buckets(capability_name, environment, region, callback)
                    self._cleanup_orphaned_ecr_repository(capability_name, environment, region, callback)
        
        # For backend-foundation stacks, check for orphaned CloudWatch log groups ONLY if:
        # 1. Stack doesn't exist at all, OR
        # 2. Stack exists in a non-updatable state (must be recreated)
        if 'backend-foundation' in stack_name or stack_name.endswith('-foundation'):
            if stack_status is None or stack_cannot_be_updated:
                # Extract capability and environment from stack name
                # Format: {capability}-{env}-backend-foundation
                parts = stack_name.replace('-backend-foundation', '').rsplit('-', 1)
                if len(parts) == 2:
                    capability_name, environment = parts
                    if callback:
                        if stack_status is None:
                            callback(f"{stack_name}: Stack doesn't exist, checking for orphaned CloudWatch log groups...")
                        else:
                            callback(f"{stack_name}: Stack in {stack_status} state (non-updatable), checking for orphaned CloudWatch log groups...")
                    self._cleanup_orphaned_foundation_log_groups(capability_name, environment, region, callback)
            
            # For STABLE foundation stacks, verify resources still exist before updating
            # If resources were deleted outside CloudFormation, we need to delete and recreate the stack
            elif stack_status and 'COMPLETE' in stack_status and 'ROLLBACK' not in stack_status:
                parts = stack_name.replace('-backend-foundation', '').rsplit('-', 1)
                if len(parts) == 2:
                    capability_name, environment = parts
                    if callback:
                        callback(f"{stack_name}: Stack is stable, verifying CloudWatch log groups exist...")
                    
                    # Check if log groups exist - if not, we need to delete and recreate the stack
                    resources_missing = self._check_foundation_resources_missing(capability_name, environment, region, callback)
                    
                    if resources_missing:
                        if callback:
                            callback(f"{stack_name}: [!] Stack resources were deleted outside CloudFormation")
                            callback(f"{stack_name}: Deleting stack to allow clean recreation...")
                        
                        # Delete the stack so it can be recreated
                        try:
                            cfn_client.delete_stack(StackName=stack_name)
                            success, error = self.wait_for_stack(cfn_client, stack_name, 'delete', callback)
                            if success:
                                if callback:
                                    callback(f"{stack_name}: [OK] Stack deleted, will recreate with fresh resources")
                                # Reset state to force creation
                                stack_status = None
                                stack_cannot_be_updated = False
                            else:
                                if callback:
                                    callback(f"{stack_name}: [!] Failed to delete stack: {error}")
                        except ClientError as e:
                            if callback:
                                callback(f"{stack_name}: [!] Error deleting stack: {str(e)}")
        
        # Handle non-updatable stacks that need deletion and recreation
        if stack_cannot_be_updated:
            if callback:
                callback(f"{stack_name}: Stack in {stack_status} state, deleting before recreating...")
            
            # Disable ALB deletion protection if this is a backend-service stack
            if 'backend-service' in stack_name or 'service' in stack_name:
                self._disable_alb_deletion_protection(stack_name, region, callback)
            
            # Delete the failed stack
            cfn_client.delete_stack(StackName=stack_name)
            # Wait for deletion to complete
            if callback:
                callback(f"{stack_name}: Waiting for stack deletion...")
            success, error = self.wait_for_stack(cfn_client, stack_name, 'delete', callback)
            if not success:
                return False, f"Failed to delete existing stack: {error}"
            if callback:
                callback(f"{stack_name}: Stack deleted successfully, proceeding with creation...")
            
            # After successful deletion, force creation mode
            exists = False
            operation = 'create'
        else:
            # Normal flow: check if stack exists
            exists = self.stack_exists(cfn_client, stack_name)
            operation = 'update' if exists else 'create'
        
        try:
            if exists:
                # Update stack
                try:
                    if callback:
                        callback(f"{stack_name}: Stack exists, updating...")
                    
                    response = cfn_client.update_stack(
                        StackName=stack_name,
                        TemplateBody=template_body,
                        Parameters=parameters,
                        Tags=tags,
                        Capabilities=capabilities
                    )
                    
                    if callback:
                        callback(f"{stack_name}: Update initiated")
                        
                except ClientError as e:
                    if 'No updates are to be performed' in str(e):
                        if callback:
                            callback(f"{stack_name}: No updates needed")
                        return True, None  # No changes needed
                    raise
            else:
                # Create stack
                if callback:
                    callback(f"{stack_name}: Stack does not exist, creating new stack...")
                    callback(f"{stack_name}: Parameters: {len(parameters)} items")
                    callback(f"{stack_name}: Tags: {len(tags)} items")
                    callback(f"{stack_name}: Capabilities: {capabilities}")
                
                try:
                    response = cfn_client.create_stack(
                        StackName=stack_name,
                        TemplateBody=template_body,
                        Parameters=parameters,
                        Tags=tags,
                        Capabilities=capabilities
                    )
                    
                    stack_id = response.get('StackId')
                    if callback:
                        callback(f"{stack_name}: [OK] Stack creation API call successful!")
                        callback(f"{stack_name}: Stack ID: {stack_id}")
                        callback(f"{stack_name}: Waiting for stack creation to complete...")
                        
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    error_msg = e.response.get('Error', {}).get('Message', str(e))
                    if callback:
                        callback(f"{stack_name}: [X] CloudFormation API Error: {error_code}")
                        callback(f"{stack_name}: [X] Error Message: {error_msg}")
                    raise
            
            # Wait for completion
            return self.wait_for_stack(cfn_client, stack_name, operation, callback)
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            if callback:
                callback(f"{stack_name}: [X] AWS Error [{error_code}]: {error_msg}")
            return False, f"[{error_code}] {error_msg}"
        except Exception as e:
            if callback:
                callback(f"{stack_name}: [X] Exception: {str(e)}")
            return False, str(e)
    
    def _cleanup_orphaned_alb(self, alb_name: str, region: str,
                              callback: Optional[callable] = None) -> bool:
        """
        Check for and clean up orphaned ALB (ALB without a CloudFormation stack)
        
        Args:
            alb_name: Expected ALB name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful or no orphaned ALB found
        """
        try:
            elbv2_client = self._get_client('elbv2', region)
            
            # List all ALBs and find one with matching name
            if callback:
                callback(f"Checking for orphaned ALB: {alb_name}")
            
            response = elbv2_client.describe_load_balancers()
            albs = response.get('LoadBalancers', [])
            
            orphaned_alb = None
            for alb in albs:
                if alb.get('LoadBalancerName') == alb_name:
                    orphaned_alb = alb
                    break
            
            if not orphaned_alb:
                if callback:
                    callback(f"[OK] No orphaned ALB found with name: {alb_name}")
                return True
            
            alb_arn = orphaned_alb.get('LoadBalancerArn')
            if callback:
                callback(f"[!] Found orphaned ALB: {alb_name}")
                callback(f"[!] ALB ARN: {alb_arn}")
            
            # Check if deletion protection is enabled
            alb_attrs_response = elbv2_client.describe_load_balancer_attributes(
                LoadBalancerArn=alb_arn
            )
            
            deletion_protection_enabled = False
            for attr in alb_attrs_response.get('Attributes', []):
                if attr.get('Key') == 'deletion_protection.enabled':
                    deletion_protection_enabled = attr.get('Value') == 'true'
                    break
            
            # Disable deletion protection if enabled
            if deletion_protection_enabled:
                if callback:
                    callback(f"Disabling deletion protection on orphaned ALB...")
                
                elbv2_client.modify_load_balancer_attributes(
                    LoadBalancerArn=alb_arn,
                    Attributes=[
                        {
                            'Key': 'deletion_protection.enabled',
                            'Value': 'false'
                        }
                    ]
                )
                if callback:
                    callback(f"[OK] Deletion protection disabled")
            
            # Delete the orphaned ALB
            if callback:
                callback(f"Deleting orphaned ALB: {alb_name}")
            
            elbv2_client.delete_load_balancer(LoadBalancerArn=alb_arn)
            
            # Wait for deletion to complete
            if callback:
                callback(f"Waiting for ALB deletion to complete...")
            
            max_attempts = 60  # 5 minutes
            for attempt in range(max_attempts):
                try:
                    # Check if ALB still exists
                    elbv2_client.describe_load_balancers(LoadBalancerArns=[alb_arn])
                    time.sleep(5)
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code == 'LoadBalancerNotFound':
                        if callback:
                            callback(f"[OK] Orphaned ALB deleted successfully")
                        return True
                    raise
            
            if callback:
                callback(f"[!] Timeout waiting for ALB deletion")
            return False
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = str(e)
            if callback:
                callback(f"[!] Error cleaning up orphaned ALB: [{error_code}] {error_msg}")
            # Don't fail the deployment - let CloudFormation try
            return True
        except Exception as e:
            if callback:
                callback(f"[!] Error cleaning up orphaned ALB: {str(e)}")
            # Don't fail the deployment - let CloudFormation try
            return True
    
    def _disable_alb_deletion_protection(self, stack_name: str, region: str,
                                         callback: Optional[callable] = None) -> bool:
        """
        Disable deletion protection on ALB before stack deletion
        
        Args:
            stack_name: CloudFormation stack name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if successful or no ALB found, False if failed
        """
        try:
            cfn_client = self._get_client('cloudformation', region)
            elbv2_client = self._get_client('elbv2', region)
            
            # Get stack resources to find the ALB
            response = cfn_client.describe_stack_resources(StackName=stack_name)
            resources = response.get('StackResources', [])
            
            # Find ALB resource
            alb_arn = None
            for resource in resources:
                if resource.get('ResourceType') == 'AWS::ElasticLoadBalancingV2::LoadBalancer':
                    alb_arn = resource.get('PhysicalResourceId')
                    break
            
            if not alb_arn:
                if callback:
                    callback(f"{stack_name}: No ALB found in stack")
                return True  # No ALB to disable
            
            if callback:
                callback(f"{stack_name}: Found ALB, checking deletion protection...")
            
            # Get current ALB attributes
            alb_response = elbv2_client.describe_load_balancer_attributes(
                LoadBalancerArn=alb_arn
            )
            
            # Check if deletion protection is enabled
            deletion_protection_enabled = False
            for attr in alb_response.get('Attributes', []):
                if attr.get('Key') == 'deletion_protection.enabled':
                    deletion_protection_enabled = attr.get('Value') == 'true'
                    break
            
            if not deletion_protection_enabled:
                if callback:
                    callback(f"{stack_name}: ALB deletion protection already disabled")
                return True
            
            # Disable deletion protection
            if callback:
                callback(f"{stack_name}: Disabling ALB deletion protection...")
            
            elbv2_client.modify_load_balancer_attributes(
                LoadBalancerArn=alb_arn,
                Attributes=[
                    {
                        'Key': 'deletion_protection.enabled',
                        'Value': 'false'
                    }
                ]
            )
            
            if callback:
                callback(f"{stack_name}: [OK] ALB deletion protection disabled successfully")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = str(e)
            if callback:
                callback(f"{stack_name}: [!] Could not disable ALB deletion protection: [{error_code}] {error_msg}")
            # Don't fail the deletion - let CloudFormation try anyway
            return True
        except Exception as e:
            if callback:
                callback(f"{stack_name}: [!] Error disabling ALB deletion protection: {str(e)}")
            # Don't fail the deletion - let CloudFormation try anyway
            return True
    
    def _cleanup_orphaned_waf_log_group(self, capability_name: str, environment: str, 
                                        callback: Optional[callable] = None) -> bool:
        """
        Check for and clean up orphaned WAF CloudWatch log group
        
        Args:
            capability_name: Capability name (will be sanitized to lowercase with hyphens)
            environment: Environment name
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful or no orphaned log group found
        """
        try:
            # WAF log groups are always in us-east-1 (global)
            logs_client = self._get_client('logs', 'us-east-1')
            
            # Sanitize capability name to match CloudFormation stack naming
            # Convert to lowercase and replace spaces/underscores with hyphens
            sanitized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
            sanitized_capability = ''.join(c for c in sanitized_capability if c.isalnum() or c == '-')
            
            # WAF log group name format: aws-waf-logs-{capability}-{environment}-frontend
            log_group_name = f"aws-waf-logs-{sanitized_capability}-{environment}-frontend"
            
            if callback:
                callback(f"Checking for orphaned WAF log group: {log_group_name}")
            
            # Check if log group exists by trying to describe it
            try:
                response = logs_client.describe_log_groups(
                    logGroupNamePrefix=log_group_name,
                    limit=1
                )
                
                # Check if any log groups were found
                log_groups = response.get('logGroups', [])
                
                if not log_groups:
                    # No log group found
                    if callback:
                        callback(f"[OK] No orphaned WAF log group found")
                    return True
                
                # Log group exists - delete it
                if callback:
                    callback(f"[!] Found orphaned WAF log group: {log_group_name}")
                    callback(f"[!] Deleting orphaned log group...")
                
                logs_client.delete_log_group(logGroupName=log_group_name)
                
                if callback:
                    callback(f"[OK] Orphaned WAF log group deleted successfully")
                return True
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == 'ResourceNotFoundException':
                    # Log group doesn't exist - that's fine
                    if callback:
                        callback(f"[OK] No orphaned WAF log group found")
                    return True
                else:
                    # Some other error
                    raise
                    
        except Exception as e:
            if callback:
                callback(f"[!] Error cleaning up WAF log group: {str(e)}")
            # Don't fail the deployment - log the error and continue
            return True
    
    def _cleanup_orphaned_dynamodb_tables(self, capability_name: str, environment: str, region: str,
                                           callback: Optional[callable] = None) -> bool:
        """
        Check for and clean up orphaned DynamoDB tables
        
        Args:
            capability_name: Capability name (will be sanitized to lowercase with hyphens)
            environment: Environment name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful or no orphaned tables found
        """
        try:
            dynamodb_client = self._get_client('dynamodb', region)
            
            # Sanitize capability name to match CloudFormation stack naming
            sanitized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
            sanitized_capability = ''.join(c for c in sanitized_capability if c.isalnum() or c == '-')
            
            # DynamoDB table names from storage stack (per INFRASTRUCTURE_REQUIREMENTS.md):
            table_names = [
                f"{sanitized_capability}-{environment}-transformation-system",
                f"{sanitized_capability}-{environment}-license",
                f"{sanitized_capability}-{environment}-wxcc-task-tracking",
            ]
            
            tables_deleted = 0
            for table_name in table_names:
                if callback:
                    callback(f"Checking for orphaned DynamoDB table: {table_name}")
                
                try:
                    # Check if table exists
                    dynamodb_client.describe_table(TableName=table_name)
                    
                    # Table exists - delete it
                    if callback:
                        callback(f"[!] Found orphaned DynamoDB table: {table_name}")
                        callback(f"[!] Deleting orphaned table...")
                    
                    dynamodb_client.delete_table(TableName=table_name)
                    
                    # Wait for deletion to complete
                    if callback:
                        callback(f"Waiting for table deletion to complete...")
                    
                    max_attempts = 60  # 5 minutes
                    for attempt in range(max_attempts):
                        try:
                            dynamodb_client.describe_table(TableName=table_name)
                            time.sleep(5)
                        except ClientError as e:
                            error_code = e.response.get('Error', {}).get('Code', '')
                            if error_code == 'ResourceNotFoundException':
                                if callback:
                                    callback(f"[OK] Orphaned DynamoDB table deleted successfully: {table_name}")
                                tables_deleted += 1
                                break
                            raise
                    else:
                        if callback:
                            callback(f"[!] Timeout waiting for table deletion: {table_name}")
                    
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code == 'ResourceNotFoundException':
                        # Table doesn't exist - that's fine
                        if callback:
                            callback(f"[OK] No orphaned table found: {table_name}")
                    else:
                        # Some other error
                        if callback:
                            callback(f"[!] Error checking table {table_name}: {str(e)}")
            
            if tables_deleted > 0 and callback:
                callback(f"[OK] Cleaned up {tables_deleted} orphaned DynamoDB table(s)")
            elif callback:
                callback(f"[OK] No orphaned DynamoDB tables found")
            
            return True
                    
        except Exception as e:
            if callback:
                callback(f"[!] Error cleaning up DynamoDB tables: {str(e)}")
            # Don't fail the deployment - log the error and continue
            return True
    
    def _cleanup_orphaned_foundation_log_groups(self, capability_name: str, environment: str, region: str,
                                                 callback: Optional[callable] = None) -> bool:
        """
        Check for and clean up orphaned CloudWatch log groups from backend-foundation stack
        
        Args:
            capability_name: Capability name (will be sanitized to lowercase with hyphens)
            environment: Environment name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful or no orphaned log groups found
        """
        try:
            logs_client = self._get_client('logs', region)
            
            # Sanitize capability name to match CloudFormation stack naming
            sanitized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
            sanitized_capability = ''.join(c for c in sanitized_capability if c.isalnum() or c == '-')
            
            # CloudWatch log group names from foundation stack:
            # 1. ECS Log Group: /ecs/{capability}-{environment}
            # 2. Application Log Group: /aws/application/{capability}-{environment}
            log_group_names = [
                f"/ecs/{sanitized_capability}-{environment}",
                f"/aws/application/{sanitized_capability}-{environment}"
            ]
            
            log_groups_deleted = 0
            for log_group_name in log_group_names:
                if callback:
                    callback(f"Checking for orphaned CloudWatch log group: {log_group_name}")
                
                try:
                    # Check if log group exists
                    response = logs_client.describe_log_groups(
                        logGroupNamePrefix=log_group_name,
                        limit=1
                    )
                    
                    log_groups = response.get('logGroups', [])
                    
                    # Check if exact match exists
                    log_group_exists = any(lg.get('logGroupName') == log_group_name for lg in log_groups)
                    
                    if not log_group_exists:
                        if callback:
                            callback(f"[OK] No orphaned log group found: {log_group_name}")
                        continue
                    
                    # Log group exists - delete it
                    if callback:
                        callback(f"[!] Found orphaned CloudWatch log group: {log_group_name}")
                        callback(f"[!] Deleting orphaned log group...")
                    
                    logs_client.delete_log_group(logGroupName=log_group_name)
                    
                    if callback:
                        callback(f"[OK] Orphaned CloudWatch log group deleted successfully: {log_group_name}")
                    log_groups_deleted += 1
                    
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code == 'ResourceNotFoundException':
                        # Log group doesn't exist - that's fine
                        if callback:
                            callback(f"[OK] No orphaned log group found: {log_group_name}")
                    else:
                        # Some other error
                        if callback:
                            callback(f"[!] Error checking log group {log_group_name}: {str(e)}")
            
            if log_groups_deleted > 0 and callback:
                callback(f"[OK] Cleaned up {log_groups_deleted} orphaned CloudWatch log group(s)")
            elif callback:
                callback(f"[OK] No orphaned CloudWatch log groups found")
            
            return True
                    
        except Exception as e:
            if callback:
                callback(f"[!] Error cleaning up CloudWatch log groups: {str(e)}")
            # Don't fail the deployment - log the error and continue
            return True
    
    def _check_foundation_resources_missing(self, capability_name: str, environment: str, region: str,
                                            callback: Optional[callable] = None) -> bool:
        """
        Check if foundation stack resources (CloudWatch log groups) are missing.
        
        This is used to detect when a stack exists but its resources were deleted
        outside of CloudFormation, which would cause an update to fail.
        
        Args:
            capability_name: Capability name (will be sanitized to lowercase with hyphens)
            environment: Environment name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if any required resources are missing, False if all exist
        """
        try:
            logs_client = self._get_client('logs', region)
            
            # Sanitize capability name to match CloudFormation stack naming
            sanitized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
            sanitized_capability = ''.join(c for c in sanitized_capability if c.isalnum() or c == '-')
            
            # CloudWatch log group names from foundation stack:
            # 1. ECS Log Group: /ecs/{capability}-{environment}
            # 2. Application Log Group: /aws/application/{capability}-{environment}
            log_group_names = [
                f"/ecs/{sanitized_capability}-{environment}",
                f"/aws/application/{sanitized_capability}-{environment}"
            ]
            
            for log_group_name in log_group_names:
                try:
                    # Check if log group exists
                    response = logs_client.describe_log_groups(
                        logGroupNamePrefix=log_group_name,
                        limit=1
                    )
                    
                    log_groups = response.get('logGroups', [])
                    
                    # Check if exact match exists
                    log_group_exists = any(lg.get('logGroupName') == log_group_name for lg in log_groups)
                    
                    if not log_group_exists:
                        if callback:
                            callback(f"[!] Required log group missing: {log_group_name}")
                        return True  # Resource is missing
                    
                    if callback:
                        callback(f"[OK] Log group exists: {log_group_name}")
                        
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code == 'ResourceNotFoundException':
                        if callback:
                            callback(f"[!] Required log group missing: {log_group_name}")
                        return True  # Resource is missing
                    else:
                        # Some other error - log but don't fail
                        if callback:
                            callback(f"[!] Error checking log group {log_group_name}: {str(e)}")
            
            # All resources exist
            return False
                    
        except Exception as e:
            if callback:
                callback(f"[!] Error checking foundation resources: {str(e)}")
            # On error, assume resources exist to avoid unnecessary stack deletion
            return False
    
    def _cleanup_orphaned_storage_s3_buckets(self, capability_name: str, environment: str, region: str,
                                              callback: Optional[callable] = None) -> bool:
        """
        Check for and clean up orphaned S3 buckets from backend-storage stack
        
        Cleans up (based on INFRASTRUCTURE_REQUIREMENTS.md):
        - call-data bucket: {capability}-{environment}-call-data
        - wxcc-simulator bucket: {capability}-{environment}-wxcc-simulator
        - journey-logs bucket: {capability}-{environment}-journey-logs
        - journey-reports bucket: {capability}-{environment}-journey-reports
        
        Args:
            capability_name: Capability name (will be sanitized to lowercase with hyphens)
            environment: Environment name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful or no orphaned buckets found
        """
        try:
            s3_client = self._get_client('s3', region)
            
            # Sanitize capability name to match CloudFormation stack naming
            sanitized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
            sanitized_capability = ''.join(c for c in sanitized_capability if c.isalnum() or c == '-')
            
            # S3 bucket names from storage stack (per INFRASTRUCTURE_REQUIREMENTS.md):
            bucket_names = [
                f"{sanitized_capability}-{environment}-call-data",
                f"{sanitized_capability}-{environment}-wxcc-simulator",
                f"{sanitized_capability}-{environment}-journey-logs",
                f"{sanitized_capability}-{environment}-journey-reports",
            ]
            
            buckets_deleted = 0
            for bucket_name in bucket_names:
                if callback:
                    callback(f"Checking for orphaned S3 bucket: {bucket_name}")
                
                try:
                    # Check if bucket exists
                    s3_client.head_bucket(Bucket=bucket_name)
                    
                    # Bucket exists - empty and delete it
                    if callback:
                        callback(f"[!] Found orphaned S3 bucket: {bucket_name}")
                        callback(f"[!] Emptying bucket contents...")
                    
                    # Empty the bucket first (delete all objects and versions)
                    try:
                        # List and delete all object versions
                        paginator = s3_client.get_paginator('list_object_versions')
                        for page in paginator.paginate(Bucket=bucket_name):
                            # Delete versions
                            versions = page.get('Versions', [])
                            if versions:
                                objects_to_delete = [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in versions]
                                s3_client.delete_objects(
                                    Bucket=bucket_name,
                                    Delete={'Objects': objects_to_delete}
                                )
                            
                            # Delete delete markers
                            delete_markers = page.get('DeleteMarkers', [])
                            if delete_markers:
                                markers_to_delete = [{'Key': m['Key'], 'VersionId': m['VersionId']} for m in delete_markers]
                                s3_client.delete_objects(
                                    Bucket=bucket_name,
                                    Delete={'Objects': markers_to_delete}
                                )
                        
                        if callback:
                            callback(f"[OK] Bucket emptied successfully")
                    except Exception as e:
                        if callback:
                            callback(f"[!] Error emptying bucket: {str(e)}")
                    
                    # Delete the bucket
                    if callback:
                        callback(f"[!] Deleting orphaned bucket...")
                    
                    s3_client.delete_bucket(Bucket=bucket_name)
                    
                    if callback:
                        callback(f"[OK] Orphaned S3 bucket deleted successfully: {bucket_name}")
                    buckets_deleted += 1
                    
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if error_code in ['404', 'NoSuchBucket']:
                        # Bucket doesn't exist - that's fine
                        if callback:
                            callback(f"[OK] No orphaned bucket found: {bucket_name}")
                    else:
                        # Some other error
                        if callback:
                            callback(f"[!] Error checking bucket {bucket_name}: {str(e)}")
            
            if buckets_deleted > 0 and callback:
                callback(f"[OK] Cleaned up {buckets_deleted} orphaned S3 bucket(s)")
            elif callback:
                callback(f"[OK] No orphaned S3 buckets found")
            
            return True
                    
        except Exception as e:
            if callback:
                callback(f"[!] Error cleaning up S3 buckets: {str(e)}")
            # Don't fail the deployment - log the error and continue
            return True
    
    def _cleanup_orphaned_ecr_repository(self, capability_name: str, environment: str, region: str,
                                          callback: Optional[callable] = None) -> bool:
        """
        Check for and clean up orphaned ECR repository from backend-storage stack
        
        Cleans up:
        - ECR Repository: {capability}-{environment}
        
        Args:
            capability_name: Capability name (will be sanitized to lowercase with hyphens)
            environment: Environment name
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful or no orphaned repository found
        """
        try:
            ecr_client = self._get_client('ecr', region)
            
            # Sanitize capability name to match CloudFormation stack naming
            sanitized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
            sanitized_capability = ''.join(c for c in sanitized_capability if c.isalnum() or c == '-')
            
            # ECR repository name from storage stack: {capability}-{environment}
            repository_name = f"{sanitized_capability}-{environment}"
            
            if callback:
                callback(f"Checking for orphaned ECR repository: {repository_name}")
            
            try:
                # Check if repository exists
                ecr_client.describe_repositories(repositoryNames=[repository_name])
                
                # Repository exists - delete it
                if callback:
                    callback(f"[!] Found orphaned ECR repository: {repository_name}")
                    callback(f"[!] Deleting orphaned repository (force=True)...")
                
                # Delete with force=True to delete even if it contains images
                ecr_client.delete_repository(
                    repositoryName=repository_name,
                    force=True
                )
                
                if callback:
                    callback(f"[OK] Orphaned ECR repository deleted successfully: {repository_name}")
                return True
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                if error_code == 'RepositoryNotFoundException':
                    # Repository doesn't exist - that's fine
                    if callback:
                        callback(f"[OK] No orphaned ECR repository found: {repository_name}")
                    return True
                else:
                    # Some other error
                    if callback:
                        callback(f"[!] Error checking repository {repository_name}: {str(e)}")
                    raise
                    
        except Exception as e:
            if callback:
                callback(f"[!] Error cleaning up ECR repository: {str(e)}")
            # Don't fail the deployment - log the error and continue
            return True
    
    def delete_stack(self, cfn_client: Any, stack_name: str,
                    callback: Optional[callable] = None) -> Tuple[bool, Optional[str]]:
        """
        Delete a CloudFormation stack
        
        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        if not self.stack_exists(cfn_client, stack_name):
            return True, None  # Already deleted
        
        try:
            # Get region from client
            region = cfn_client.meta.region_name
            
            # Disable ALB deletion protection if this is a backend-service stack
            if 'backend-service' in stack_name or 'service' in stack_name:
                self._disable_alb_deletion_protection(stack_name, region, callback)
            
            cfn_client.delete_stack(StackName=stack_name)
            success, error = self.wait_for_stack(cfn_client, stack_name, 'delete', callback)
            
            # After successful deletion, cleanup any orphaned resources
            if success:
                # For frontend-global stacks, cleanup orphaned WAF log groups
                if 'frontend-global' in stack_name:
                    # Extract capability and environment from stack name
                    # Format: {capability}-{env}-frontend-global
                    parts = stack_name.replace('-frontend-global', '').rsplit('-', 1)
                    if len(parts) == 2:
                        capability_name, environment = parts
                        if callback:
                            callback(f"{stack_name}: Checking for orphaned WAF resources after deletion...")
                        self._cleanup_orphaned_waf_log_group(capability_name, environment, callback)
                
                # For backend-service stacks, cleanup orphaned ALBs
                if 'backend-service' in stack_name or 'service' in stack_name:
                    alb_name = stack_name.replace('-backend-service', '-alb')
                    if callback:
                        callback(f"{stack_name}: Checking for orphaned ALB after deletion...")
                    self._cleanup_orphaned_alb(alb_name, region, callback)
                
                # For backend-storage stacks, cleanup orphaned storage resources
                if 'backend-storage' in stack_name or 'storage' in stack_name:
                    # Extract capability and environment from stack name
                    # Format: {capability}-{env}-backend-storage
                    parts = stack_name.replace('-backend-storage', '').rsplit('-', 1)
                    if len(parts) == 2:
                        capability_name, environment = parts
                        if callback:
                            callback(f"{stack_name}: Checking for orphaned storage resources after deletion...")
                        self._cleanup_orphaned_dynamodb_tables(capability_name, environment, region, callback)
                        self._cleanup_orphaned_storage_s3_buckets(capability_name, environment, region, callback)
                        self._cleanup_orphaned_ecr_repository(capability_name, environment, region, callback)
                
                # For backend-foundation stacks, cleanup orphaned CloudWatch log groups
                if 'backend-foundation' in stack_name or stack_name.endswith('-foundation'):
                    # Extract capability and environment from stack name
                    # Format: {capability}-{env}-backend-foundation
                    parts = stack_name.replace('-backend-foundation', '').rsplit('-', 1)
                    if len(parts) == 2:
                        capability_name, environment = parts
                        if callback:
                            callback(f"{stack_name}: Checking for orphaned CloudWatch log groups after deletion...")
                        self._cleanup_orphaned_foundation_log_groups(capability_name, environment, region, callback)
            
            return success, error
        except ClientError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)
    
    # Valid CloudFormation parameter values (from template constraints)
    ALLOWED_LOG_RETENTION_DAYS = [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365]
    ALLOWED_TASK_CPU = [256, 512, 1024, 2048, 4096]
    ALLOWED_TASK_MEMORY = [512, 1024, 2048, 3072, 4096, 5120, 6144, 7168, 8192, 16384, 30720]
    
    def _normalize_log_retention_days(self, value: Any) -> int:
        """Normalize LogRetentionDays to a valid CloudFormation value."""
        try:
            days = int(value)
        except (ValueError, TypeError):
            return 7  # Default
        
        if days in self.ALLOWED_LOG_RETENTION_DAYS:
            return days
        
        # Find the closest allowed value
        for allowed in self.ALLOWED_LOG_RETENTION_DAYS:
            if days <= allowed:
                return allowed
        return 365  # Max value
    
    def _normalize_task_cpu(self, value: Any) -> int:
        """Normalize TaskCpu to a valid CloudFormation value."""
        try:
            cpu = int(value)
        except (ValueError, TypeError):
            return 512  # Default
        
        if cpu in self.ALLOWED_TASK_CPU:
            return cpu
        
        # Find the closest allowed value (round up)
        for allowed in self.ALLOWED_TASK_CPU:
            if cpu <= allowed:
                return allowed
        return 4096  # Max value
    
    def _normalize_task_memory(self, value: Any) -> int:
        """Normalize TaskMemory to a valid CloudFormation value."""
        try:
            memory = int(value)
        except (ValueError, TypeError):
            return 1024  # Default
        
        if memory in self.ALLOWED_TASK_MEMORY:
            return memory
        
        # Find the closest allowed value (round up)
        for allowed in self.ALLOWED_TASK_MEMORY:
            if memory <= allowed:
                return allowed
        return 30720  # Max value
    
    def build_parameters(self, config: Dict[str, Any], stack_type: str, 
                        stack_outputs: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Build CloudFormation parameters for a stack
        
        Args:
            config: Deployment configuration
            stack_type: Type of stack (e.g., 'frontend-global')
            stack_outputs: Outputs from previously deployed stacks
            
        Returns:
            List of parameter dicts for CloudFormation
        """
        parameters = []
        
        # Common parameters - sanitize capability name for CloudFormation
        capability_name = config.get('capability', {}).get('name', '')
        # CloudFormation requires lowercase alphanumeric with hyphens
        capability_name = capability_name.lower().replace(' ', '-').replace('_', '-')
        capability_name = ''.join(c for c in capability_name if c.isalnum() or c == '-')
        if capability_name and not capability_name[0].isalnum():
            capability_name = 'cap-' + capability_name
        
        environment = config.get('target', {}).get('environment', '')
        
        if 'frontend' in stack_type:
            # Frontend parameters
            if stack_type == 'frontend-global':
                # Get domain configuration
                domain_config = config.get('infrastructure', {}).get('domain', {})
                base_domain = domain_config.get('base', '')
                hosted_zone_id = domain_config.get('hosted_zone_id', '')
                frontend_subdomain = domain_config.get('frontend_subdomain', 'app')
                
                # Get CloudFront/WAF configuration
                cloudfront_config = config.get('infrastructure', {}).get('frontend', {}).get('cloudfront', {})
                waf_enabled = str(cloudfront_config.get('waf_enabled', True)).lower()
                rate_limit = str(cloudfront_config.get('rate_limit', 2000))
                
                # Base parameters (always required)
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'BaseDomain', 'ParameterValue': base_domain},
                    {'ParameterKey': 'FrontendSubdomain', 'ParameterValue': frontend_subdomain},
                    {'ParameterKey': 'HostedZoneId', 'ParameterValue': hosted_zone_id},
                    {'ParameterKey': 'EnableWAF', 'ParameterValue': waf_enabled},
                    {'ParameterKey': 'RateLimitPerIP', 'ParameterValue': rate_limit},
                ]
            elif stack_type == 'frontend-cognito':
                # Get FrontendDomainName from global stack outputs
                global_outputs = stack_outputs.get('frontend-global', {})
                frontend_domain = global_outputs.get('FrontendDomainName', '')
                
                # Note: AdminTempPassword removed from template - passwords set via Cognito API after deployment
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'FrontendDomainName', 'ParameterValue': frontend_domain},
                ]
            elif stack_type == 'frontend-regional':
                # Get global stack name for importing outputs
                global_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'frontend-global'
                )
                
                # Get outputs from global stack (deployed in us-east-1)
                # Since regional stack is in a different region, we can't use Fn::ImportValue
                # We need to pass these values as parameters
                global_outputs = stack_outputs.get('frontend-global', {})
                frontend_domain_name = global_outputs.get('FrontendDomainName', '')
                certificate_arn = global_outputs.get('CertificateArn', '')
                waf_web_acl_arn = global_outputs.get('WAFWebACLArn', '')
                hosted_zone_id = global_outputs.get('HostedZoneId', '')
                
                # Get CloudFront configuration
                cloudfront_config = config.get('infrastructure', {}).get('frontend', {}).get('cloudfront', {})
                price_class = cloudfront_config.get('price_class', 'PriceClass_100')
                default_root_object = cloudfront_config.get('default_root_object', 'index.html')
                error_page_path = cloudfront_config.get('error_page_path', '/index.html')
                default_cache_ttl = str(cloudfront_config.get('default_cache_ttl', 86400))
                max_cache_ttl = str(cloudfront_config.get('max_cache_ttl', 31536000))
                enable_ipv6 = str(cloudfront_config.get('enable_ipv6', True)).lower()
                
                parameters = [
                    {'ParameterKey': 'GlobalStackName', 'ParameterValue': global_stack_name},
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'CloudFrontPriceClass', 'ParameterValue': price_class},
                    {'ParameterKey': 'DefaultRootObject', 'ParameterValue': default_root_object},
                    {'ParameterKey': 'ErrorPagePath', 'ParameterValue': error_page_path},
                    {'ParameterKey': 'DefaultCacheTTL', 'ParameterValue': default_cache_ttl},
                    {'ParameterKey': 'MaxCacheTTL', 'ParameterValue': max_cache_ttl},
                    {'ParameterKey': 'EnableIPV6', 'ParameterValue': enable_ipv6},
                    # Pass global stack outputs as parameters (cross-region compatibility)
                    {'ParameterKey': 'FrontendDomainName', 'ParameterValue': frontend_domain_name},
                    {'ParameterKey': 'CertificateArn', 'ParameterValue': certificate_arn},
                    {'ParameterKey': 'WAFWebACLArn', 'ParameterValue': waf_web_acl_arn},
                    {'ParameterKey': 'HostedZoneId', 'ParameterValue': hosted_zone_id},
                ]
        
        elif 'backend' in stack_type:
            # Backend parameters
            if stack_type == 'backend-foundation':
                # Foundation stack now only needs basic parameters (no domain info)
                # Normalize LogRetentionDays to a valid CloudFormation value
                log_retention_raw = config.get('infrastructure', {}).get('monitoring', {}).get('cloudwatch', {}).get('log_retention_days', 7)
                log_retention_days = self._normalize_log_retention_days(log_retention_raw)
                
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'LogRetentionDays', 'ParameterValue': str(log_retention_days)},
                ]
            elif stack_type == 'backend-iam-roles':
                # IAM roles stack - simple parameters
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                ]
            elif stack_type == 'backend-regional-cert':
                base_domain = config.get('infrastructure', {}).get('domain', {}).get('base', '')
                hosted_zone_id = config.get('infrastructure', {}).get('domain', {}).get('hosted_zone_id', '')
                
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'BaseDomain', 'ParameterValue': base_domain},
                    {'ParameterKey': 'HostedZoneId', 'ParameterValue': hosted_zone_id},
                    {'ParameterKey': 'ApiSubdomain', 'ParameterValue': 'api'},
                ]
            elif stack_type == 'backend-storage':
                # Get foundation and IAM roles stack names
                foundation_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'backend-foundation'
                )
                iam_roles_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'backend-iam-roles'
                )
                
                # Get storage configuration
                storage_config = config.get('infrastructure', {}).get('backend', {}).get('storage', {})
                enable_backup = str(storage_config.get('enable_backup', True)).lower()
                enable_pitr = str(storage_config.get('enable_point_in_time_recovery', True)).lower()
                dynamodb_billing_mode = storage_config.get('dynamodb_billing_mode', 'PAY_PER_REQUEST')
                ecr_scan_on_push = str(storage_config.get('ecr_image_scan_on_push', True)).lower()
                ecr_retention_days = str(storage_config.get('ecr_image_retention_days', 7))
                
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'FoundationStackName', 'ParameterValue': foundation_stack_name},
                    {'ParameterKey': 'IAMRolesStackName', 'ParameterValue': iam_roles_stack_name},
                    {'ParameterKey': 'EnableBackup', 'ParameterValue': enable_backup},
                    {'ParameterKey': 'EnablePointInTimeRecovery', 'ParameterValue': enable_pitr},
                    {'ParameterKey': 'DynamoDBBillingMode', 'ParameterValue': dynamodb_billing_mode},
                    {'ParameterKey': 'ECRImageScanOnPush', 'ParameterValue': ecr_scan_on_push},
                    {'ParameterKey': 'ECRImageRetentionDays', 'ParameterValue': ecr_retention_days},
                ]
            elif stack_type == 'backend-network':
                # Get container port from config
                ecs_config = config.get('infrastructure', {}).get('backend', {}).get('ecs', {})
                container_port = str(ecs_config.get('container_port', 8000))
                
                vpc_config = config.get('infrastructure', {}).get('backend', {}).get('vpc', {})
                create_new_vpc = vpc_config.get('create_new', True)
                
                if create_new_vpc:
                    # Creating new VPC
                    parameters = [
                        {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                        {'ParameterKey': 'Environment', 'ParameterValue': environment},
                        {'ParameterKey': 'UseExistingVPC', 'ParameterValue': 'false'},
                        {'ParameterKey': 'VPCCidr', 'ParameterValue': vpc_config.get('vpc_cidr', '10.0.0.0/16')},
                        {'ParameterKey': 'ContainerPort', 'ParameterValue': container_port},
                    ]
                else:
                    # Using existing VPC
                    # Support both individual subnet fields and array format
                    public_subnets = vpc_config.get('subnets', {}).get('public', [])
                    private_subnets = vpc_config.get('subnets', {}).get('private', [])
                    
                    # Use individual fields if available, otherwise fall back to arrays
                    public_subnet_1 = vpc_config.get('public_subnet_1') or (public_subnets[0] if len(public_subnets) > 0 else '')
                    public_subnet_2 = vpc_config.get('public_subnet_2') or (public_subnets[1] if len(public_subnets) > 1 else '')
                    private_subnet_1 = vpc_config.get('private_subnet_1') or (private_subnets[0] if len(private_subnets) > 0 else '')
                    private_subnet_2 = vpc_config.get('private_subnet_2') or (private_subnets[1] if len(private_subnets) > 1 else '')
                    
                    parameters = [
                        {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                        {'ParameterKey': 'Environment', 'ParameterValue': environment},
                        {'ParameterKey': 'UseExistingVPC', 'ParameterValue': 'true'},
                        {'ParameterKey': 'ExistingVPCId', 'ParameterValue': vpc_config.get('vpc_id', '')},
                        {'ParameterKey': 'ExistingPublicSubnet1', 'ParameterValue': public_subnet_1},
                        {'ParameterKey': 'ExistingPublicSubnet2', 'ParameterValue': public_subnet_2},
                        {'ParameterKey': 'ExistingPrivateSubnet1', 'ParameterValue': private_subnet_1},
                        {'ParameterKey': 'ExistingPrivateSubnet2', 'ParameterValue': private_subnet_2},
                        {'ParameterKey': 'ContainerPort', 'ParameterValue': container_port},
                    ]
            elif stack_type == 'backend-service':
                # Get stack names for references
                foundation_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'backend-foundation'
                )
                iam_roles_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'backend-iam-roles'
                )
                storage_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'backend-storage'
                )
                network_stack_name = self.get_stack_name(
                    config.get('capability', {}).get('name', ''),
                    config.get('target', {}).get('environment', ''),
                    'backend-network'
                )
                
                # Get container image from config
                # If not specified, use the ECR repository from storage stack with 'latest' tag
                container_image = config.get('source', {}).get('backend', {}).get('ecr_uri', '')
                using_placeholder_image = False
                if not container_image:
                    # Try to get ECR URI from storage stack outputs
                    storage_outputs = stack_outputs.get('backend-storage', {})
                    ecr_uri = storage_outputs.get('ECRRepositoryUri', '')
                    if ecr_uri:
                        container_image = f"{ecr_uri}:latest"
                    else:
                        # Use a placeholder image - infrastructure will be created
                        # but with DesiredCount=0 to avoid health check failures
                        container_image = 'public.ecr.aws/nginx/nginx:alpine'
                        using_placeholder_image = True
                
                # Get ECS configuration
                ecs_config = config.get('infrastructure', {}).get('backend', {}).get('ecs', {})
                container_port = str(ecs_config.get('container_port', 8000))
                health_check_path = ecs_config.get('health_check_path', '/health')
                # Normalize TaskCpu and TaskMemory to valid CloudFormation values
                task_cpu_raw = ecs_config.get('task_cpu', 512)
                task_memory_raw = ecs_config.get('task_memory', 1024)
                task_cpu = str(self._normalize_task_cpu(task_cpu_raw))
                task_memory = str(self._normalize_task_memory(task_memory_raw))
                
                # If using placeholder image, set desired count to 0
                # This allows the infrastructure to be created without failing health checks
                if using_placeholder_image:
                    desired_count = '0'  # No tasks until a real image is deployed
                else:
                    desired_count = str(ecs_config.get('desired_count', 2))
                
                # Service stack should NOT create Route53 record (domain stack will do it)
                create_route53_record = 'false'
                
                # Check if domain stack has been deployed (has outputs)
                # If domain stack exists, use its certificate; otherwise deploy without HTTPS
                domain_outputs = stack_outputs.get('backend-domain', {})
                use_domain_cert = 'true' if domain_outputs.get('BackendCertificateArn') else 'false'
                domain_stack_name = ''
                if use_domain_cert == 'true':
                    domain_stack_name = self.get_stack_name(
                        config.get('capability', {}).get('name', ''),
                        config.get('target', {}).get('environment', ''),
                        'backend-domain'
                    )
                
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'FoundationStackName', 'ParameterValue': foundation_stack_name},
                    {'ParameterKey': 'IAMRolesStackName', 'ParameterValue': iam_roles_stack_name},
                    {'ParameterKey': 'DomainStackName', 'ParameterValue': domain_stack_name},
                    {'ParameterKey': 'StorageStackName', 'ParameterValue': storage_stack_name},
                    {'ParameterKey': 'NetworkStackName', 'ParameterValue': network_stack_name},
                    {'ParameterKey': 'ContainerPort', 'ParameterValue': container_port},
                    {'ParameterKey': 'TaskCpu', 'ParameterValue': task_cpu},
                    {'ParameterKey': 'TaskMemory', 'ParameterValue': task_memory},
                    {'ParameterKey': 'DesiredCount', 'ParameterValue': desired_count},
                    {'ParameterKey': 'HealthCheckPath', 'ParameterValue': health_check_path},
                    {'ParameterKey': 'CreateRoute53Record', 'ParameterValue': create_route53_record},
                    {'ParameterKey': 'UseDomainCertificate', 'ParameterValue': use_domain_cert},
                ]
                
                # Only include ContainerImage if specified (otherwise use template default)
                if container_image:
                    parameters.append({'ParameterKey': 'ContainerImage', 'ParameterValue': container_image})
            elif stack_type == 'backend-domain':
                # Domain stack - deployed after service stack
                # Get domain configuration
                domain_config = config.get('infrastructure', {}).get('domain', {})
                base_domain = domain_config.get('base', '')
                hosted_zone_id = domain_config.get('hosted_zone_id', '')
                backend_subdomain = domain_config.get('backend_subdomain', 'api')
                
                # Get ALB DNS and Hosted Zone ID from service stack outputs
                service_outputs = stack_outputs.get('backend-service', {})
                load_balancer_dns = service_outputs.get('LoadBalancerDNS', '')
                load_balancer_zone = service_outputs.get('LoadBalancerZone', '')
                
                # During pre-deployment validation, stack_outputs may be empty
                # Use placeholder values that satisfy MinLength=1 constraint
                # These will be replaced with real values during actual deployment
                if not load_balancer_dns:
                    load_balancer_dns = 'pending-from-service-stack'
                if not load_balancer_zone:
                    load_balancer_zone = 'pending-from-service-stack'
                
                parameters = [
                    {'ParameterKey': 'CapabilityName', 'ParameterValue': capability_name},
                    {'ParameterKey': 'Environment', 'ParameterValue': environment},
                    {'ParameterKey': 'BaseDomain', 'ParameterValue': base_domain},
                    {'ParameterKey': 'ApiSubdomain', 'ParameterValue': backend_subdomain},
                    {'ParameterKey': 'HostedZoneId', 'ParameterValue': hosted_zone_id},
                    # Pass ALB info directly (no circular dependency)
                    {'ParameterKey': 'LoadBalancerDns', 'ParameterValue': load_balancer_dns},
                    {'ParameterKey': 'LoadBalancerHostedZoneId', 'ParameterValue': load_balancer_zone},
                    {'ParameterKey': 'CreateCertificate', 'ParameterValue': 'true'},
                    {'ParameterKey': 'CreateRoute53Record', 'ParameterValue': 'true'},
                    {'ParameterKey': 'CreateHealthCheck', 'ParameterValue': 'true' if environment == 'prod' else 'false'},
                ]
        
        return parameters
    
    def build_parameters_with_preserved_outputs(
        self,
        config: Dict[str, Any],
        stack_type: str,
        stack_outputs: Dict[str, Dict[str, str]],
        preserved_outputs: Optional[Dict[str, str]] = None
    ) -> List[Dict[str, str]]:
        """
        Build CloudFormation parameters for a stack, using preserved outputs when available.
        
        This method is used during UPDATE workflows to ensure that preserved stack outputs
        (like Cognito User Pool IDs) are passed to dependent stacks even when the source
        stack is being skipped.
        
        Args:
            config: Deployment configuration
            stack_type: Type of stack (e.g., 'frontend-global')
            stack_outputs: Outputs from previously deployed stacks
            preserved_outputs: Optional dict of preserved outputs to merge
            
        Returns:
            List of parameter dicts for CloudFormation
        """
        # Merge preserved outputs into stack_outputs
        merged_outputs = dict(stack_outputs)
        
        if preserved_outputs:
            for key, value in preserved_outputs.items():
                # Only use preserved output if not already in stack_outputs
                if key not in merged_outputs:
                    merged_outputs[key] = value
        
        # Use the standard build_parameters with merged outputs
        return self.build_parameters(config, stack_type, merged_outputs)
    
    def should_skip_stack_for_update(
        self,
        stack_type: str,
        stacks_to_skip: List[str]
    ) -> bool:
        """
        Determine if a stack should be skipped during an update workflow.
        
        Args:
            stack_type: Type of stack (e.g., 'frontend-cognito')
            stacks_to_skip: List of stack types to skip
            
        Returns:
            True if the stack should be skipped
        """
        return stack_type in stacks_to_skip
    
    def build_tags(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Build CloudFormation tags"""
        tags = []
        
        # Add common tags from config
        common_tags = config.get('tags', {}).get('common', {})
        for key, value in common_tags.items():
            tags.append({'Key': key, 'Value': str(value)})
        
        # Add deployment metadata
        tags.append({'Key': 'DeployedBy', 'Value': 'TotogiInstaller'})
        tags.append({'Key': 'DeploymentTime', 'Value': datetime.utcnow().isoformat()})
        
        return tags
