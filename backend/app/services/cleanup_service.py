"""
Cleanup Service
Handles deletion of CloudFormation stacks and associated resources
"""
import boto3
import time
import uuid
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.services.tinydb_deployment_state_service import tinydb_deployment_state_service as deployment_state_service

logger = logging.getLogger(__name__)

# In-memory storage for deletion jobs
_deletion_jobs: Dict[str, Dict[str, Any]] = {}


def get_deletion_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a deletion job by ID"""
    return _deletion_jobs.get(job_id)


def get_deletion_logs(job_id: str) -> List[Dict[str, Any]]:
    """Get logs for a deletion job"""
    job = _deletion_jobs.get(job_id)
    if job:
        return job.get('logs', [])
    return []


class CleanupService:
    """Service for cleaning up deployed capabilities"""
    
    # Stack deletion order (reverse of deployment order)
    # Frontend stacks first (least dependencies), then backend stacks (most dependencies)
    CLEANUP_ORDER = [
        # Frontend stacks first - fewer dependencies
        "frontend-regional",       # S3 bucket, regional frontend resources
        "frontend-cognito",        # Cognito User Pool
        "frontend-global",         # CloudFront, WAF (global resources)
        
        # Backend stacks second - more dependencies, reverse order
        "backend-domain",          # Route53, SSL cert, ALB HTTPS
        "backend-service",         # ECS service, ALB
        "backend-network",         # VPC, subnets, security groups
        "backend-storage",         # DynamoDB, S3, ECR
        "backend-regional-cert",   # SSL certificates
        "backend-iam-roles",       # IAM roles and policies
        "backend-foundation",      # CloudWatch, basic infrastructure
    ]
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        self.credentials = credentials or {}
    
    def _get_client(self, service: str, region: str) -> Any:
        """Get boto3 client with credentials"""
        kw = {"region_name": region, **self.credentials}
        return boto3.client(service, **merge_vpc_boto3_kwargs(service, region, kw))
    
    def get_stack_name(self, capability_name: str, environment: str, stack_type: str) -> str:
        """Generate stack name - sanitize to match CloudFormation service"""
        # Must match the logic in cloudformation_service.py
        # Replace spaces and invalid characters with hyphens
        sanitized_name = capability_name.replace(' ', '-').replace('_', '-')
        # Remove any other invalid characters
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        # Ensure it starts with a letter
        if sanitized_name and not sanitized_name[0].isalpha():
            sanitized_name = 'stack-' + sanitized_name
        return f"{sanitized_name}-{environment}-{stack_type}"
    
    def stack_exists(self, cfn_client: Any, stack_name: str) -> bool:
        """Check if stack exists"""
        try:
            cfn_client.describe_stacks(StackName=stack_name)
            return True
        except ClientError as e:
            if 'does not exist' in str(e).lower():
                return False
            raise
    
    def get_stack_status(self, cfn_client: Any, stack_name: str) -> Optional[str]:
        """Get current stack status"""
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            if response['Stacks']:
                return response['Stacks'][0].get('StackStatus')
        except ClientError:
            pass
        return None

    def disable_alb_deletion_protection(self, region: str, capability_name: str,
                                        environment: str, callback: Optional[Callable] = None) -> List[str]:
        """Disable deletion protection on all ALBs for this capability"""
        disabled_albs = []
        try:
            elbv2_client = self._get_client('elbv2', region)
            paginator = elbv2_client.get_paginator('describe_load_balancers')
            
            # Sanitize capability name to match stack naming
            sanitized_name = capability_name.replace(' ', '-').replace('_', '-')
            sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
            name_pattern = f"{sanitized_name}-{environment}".lower()
            
            if callback:
                callback(f"  Looking for ALBs matching pattern: {name_pattern}")
            
            alb_count = 0
            for page in paginator.paginate():
                for lb in page.get('LoadBalancers', []):
                    alb_count += 1
                    lb_name = lb.get('LoadBalancerName', '')
                    lb_name_lower = lb_name.lower()
                    lb_arn = lb.get('LoadBalancerArn', '')
                    
                    # Check if this ALB matches our capability
                    if name_pattern in lb_name_lower or sanitized_name.lower() in lb_name_lower:
                        if callback:
                            callback(f"  Found matching ALB: {lb_name}")
                        try:
                            attrs = elbv2_client.describe_load_balancer_attributes(LoadBalancerArn=lb_arn)
                            deletion_protection_enabled = False
                            for attr in attrs.get('Attributes', []):
                                if attr.get('Key') == 'deletion_protection.enabled':
                                    deletion_protection_enabled = attr.get('Value') == 'true'
                                    break
                            
                            if deletion_protection_enabled:
                                if callback:
                                    callback(f"  Disabling deletion protection on: {lb_name}")
                                elbv2_client.modify_load_balancer_attributes(
                                    LoadBalancerArn=lb_arn,
                                    Attributes=[{'Key': 'deletion_protection.enabled', 'Value': 'false'}]
                                )
                                disabled_albs.append(lb_name)
                                if callback:
                                    callback(f"  [OK] Disabled ALB deletion protection: {lb_name}")
                            else:
                                if callback:
                                    callback(f"  [i] ALB {lb_name} deletion protection already disabled")
                        except Exception as e:
                            if callback:
                                callback(f"  [!] Could not modify ALB {lb_name}: {str(e)}")
            
            if callback:
                callback(f"  Scanned {alb_count} ALBs, disabled protection on {len(disabled_albs)}")
                
        except Exception as e:
            if callback:
                callback(f"  [!] Error listing ALBs: {str(e)}")
        return disabled_albs
    
    def disable_rds_deletion_protection(self, region: str, capability_name: str,
                                        environment: str, callback: Optional[Callable] = None) -> List[str]:
        """Disable deletion protection on RDS instances/clusters"""
        disabled_dbs = []
        try:
            rds_client = self._get_client('rds', region)
            
            # Sanitize capability name to match stack naming
            sanitized_name = capability_name.replace(' ', '-').replace('_', '-')
            sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
            name_pattern = f"{sanitized_name}-{environment}".lower()
            
            # Check DB instances
            try:
                instances = rds_client.describe_db_instances()
                for db in instances.get('DBInstances', []):
                    db_id = db.get('DBInstanceIdentifier', '').lower()
                    if name_pattern in db_id and db.get('DeletionProtection', False):
                        rds_client.modify_db_instance(
                            DBInstanceIdentifier=db['DBInstanceIdentifier'],
                            DeletionProtection=False,
                            ApplyImmediately=True
                        )
                        disabled_dbs.append(db['DBInstanceIdentifier'])
                        if callback:
                            callback(f"  [OK] Disabled RDS deletion protection: {db['DBInstanceIdentifier']}")
            except Exception as e:
                logger.warning(f"Error checking RDS instances: {e}")
        except Exception as e:
            if callback:
                callback(f"  [!] Error checking RDS: {str(e)}")
        return disabled_dbs
    
    def delete_orphaned_resources(self, region: str, capability_name: str,
                                  environment: str, callback: Optional[Callable] = None) -> Dict[str, List[str]]:
        """Delete orphaned resources that might prevent stack deletion"""
        deleted = {'target_groups': [], 'listeners': [], 'security_groups': []}
        
        # Sanitize capability name to match stack naming
        sanitized_name = capability_name.replace(' ', '-').replace('_', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        name_pattern = f"{sanitized_name}-{environment}".lower()
        
        try:
            elbv2_client = self._get_client('elbv2', region)
            paginator = elbv2_client.get_paginator('describe_target_groups')
            
            for page in paginator.paginate():
                for tg in page.get('TargetGroups', []):
                    tg_name = tg.get('TargetGroupName', '').lower()
                    if name_pattern in tg_name and not tg.get('LoadBalancerArns'):
                        try:
                            elbv2_client.delete_target_group(TargetGroupArn=tg['TargetGroupArn'])
                            deleted['target_groups'].append(tg['TargetGroupName'])
                            if callback:
                                callback(f"  [OK] Deleted orphaned target group: {tg['TargetGroupName']}")
                        except Exception as e:
                            if callback:
                                callback(f"  [!] Could not delete target group: {str(e)}")
        except Exception as e:
            if callback:
                callback(f"  [!] Error cleaning target groups: {str(e)}")
        return deleted

    def empty_s3_bucket(self, bucket_name: str, region: str = 'us-east-1',
                       callback: Optional[Callable] = None) -> bool:
        """Empty S3 bucket (required before stack deletion)"""
        try:
            s3_client = self._get_client('s3', region)
            
            try:
                s3_client.head_bucket(Bucket=bucket_name)
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    return True
                raise
            
            if callback:
                callback(f"  Emptying S3 bucket {bucket_name}...")
            
            objects_deleted = 0
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                if 'Contents' in page:
                    objects = [{'Key': obj['Key']} for obj in page['Contents']]
                    if objects:
                        s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': objects})
                        objects_deleted += len(objects)
            
            # Delete versions
            paginator = s3_client.get_paginator('list_object_versions')
            for page in paginator.paginate(Bucket=bucket_name):
                versions = []
                if 'Versions' in page:
                    versions.extend([{'Key': v['Key'], 'VersionId': v['VersionId']} for v in page['Versions']])
                if 'DeleteMarkers' in page:
                    versions.extend([{'Key': d['Key'], 'VersionId': d['VersionId']} for d in page['DeleteMarkers']])
                if versions:
                    s3_client.delete_objects(Bucket=bucket_name, Delete={'Objects': versions})
                    objects_deleted += len(versions)
            
            if callback:
                callback(f"  [OK] Deleted {objects_deleted} objects from {bucket_name}")
            return True
        except Exception as e:
            if callback:
                callback(f"  [!] Error emptying bucket {bucket_name}: {str(e)}")
            return False
    
    def delete_ecr_repository(self, repository_name: str, region: str = 'us-east-1',
                             callback: Optional[Callable] = None) -> bool:
        """Delete ECR repository"""
        try:
            ecr_client = self._get_client('ecr', region)
            ecr_client.delete_repository(repositoryName=repository_name, force=True)
            if callback:
                callback(f"  [OK] Deleted ECR repository: {repository_name}")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'RepositoryNotFoundException':
                return True
            if callback:
                callback(f"  [!] Error deleting ECR repository: {str(e)}")
            return False

    def _check_stack_exports_in_use(self, cfn_client: Any, stack_name: str) -> List[str]:
        """Check if stack has exports that are being used by other stacks"""
        exports_in_use = []
        try:
            # Get all exports
            paginator = cfn_client.get_paginator('list_exports')
            for page in paginator.paginate():
                for export in page.get('Exports', []):
                    # Check if this export belongs to our stack
                    if stack_name in export.get('ExportingStackId', ''):
                        export_name = export.get('Name', '')
                        # Check if any stack is importing this export
                        try:
                            imports = cfn_client.list_imports(ExportName=export_name)
                            if imports.get('Imports'):
                                exports_in_use.append({
                                    'export_name': export_name,
                                    'imported_by': imports.get('Imports', [])
                                })
                        except ClientError as e:
                            # No imports for this export
                            if 'is not imported by any stack' not in str(e):
                                logger.warning(f"Error checking imports for {export_name}: {e}")
        except Exception as e:
            logger.warning(f"Error checking stack exports: {e}")
        return exports_in_use

    def _get_stack_deletion_blockers(self, cfn_client: Any, stack_name: str) -> Optional[str]:
        """Identify what might be blocking stack deletion"""
        blockers = []
        
        # Check for exports in use
        exports_in_use = self._check_stack_exports_in_use(cfn_client, stack_name)
        if exports_in_use:
            for export_info in exports_in_use:
                importing_stacks = ', '.join(export_info['imported_by'][:3])
                if len(export_info['imported_by']) > 3:
                    importing_stacks += f" and {len(export_info['imported_by']) - 3} more"
                blockers.append(f"Export '{export_info['export_name']}' is used by: {importing_stacks}")
        
        # Check stack status for any in-progress operations
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            if response['Stacks']:
                stack = response['Stacks'][0]
                status = stack.get('StackStatus', '')
                if 'IN_PROGRESS' in status and 'DELETE' not in status:
                    blockers.append(f"Stack has operation in progress: {status}")
        except Exception as e:
            logger.warning(f"Error checking stack status: {e}")
        
        return '; '.join(blockers) if blockers else None

    def delete_stack_with_status(self, cfn_client: Any, stack_name: str, 
                                  callback: Optional[Callable] = None) -> Dict[str, Any]:
        """Delete a stack with detailed status reporting"""
        result = {
            'stack_name': stack_name,
            'initial_status': None,
            'final_status': None,
            'success': False,
            'error': None
        }
        
        try:
            # Check if stack exists and get initial status
            if not self.stack_exists(cfn_client, stack_name):
                result['initial_status'] = 'DOES_NOT_EXIST'
                result['final_status'] = 'DELETED'
                result['success'] = True
                if callback:
                    callback(f"  [OK] {stack_name}: Already deleted")
                return result
            
            initial_status = self.get_stack_status(cfn_client, stack_name)
            result['initial_status'] = initial_status
            
            # Check if stack is in a state that can be deleted
            if initial_status and 'IN_PROGRESS' in initial_status and 'DELETE' not in initial_status:
                if callback:
                    callback(f"  [!] {stack_name}: Cannot delete - operation in progress ({initial_status})")
                result['final_status'] = initial_status
                result['error'] = f'Stack has operation in progress: {initial_status}'
                return result
            
            if callback:
                callback(f"  [SYNC] {stack_name}: Initiating deletion (was {initial_status})...")
            
            # Initiate deletion
            cfn_client.delete_stack(StackName=stack_name)
            
            # Poll for status with detailed updates
            max_wait = 600  # 10 minutes max
            poll_interval = 15  # Poll every 15 seconds for real-time feedback
            elapsed = 0
            deletion_started = False
            stuck_count = 0  # Track how many times we see the same non-delete status
            max_stuck_count = 4  # After 4 polls (60s) with no change, investigate
            
            while elapsed < max_wait:
                time.sleep(poll_interval)
                elapsed += poll_interval
                
                current_status = self.get_stack_status(cfn_client, stack_name)
                
                if current_status is None:
                    # Stack no longer exists - deletion complete
                    result['final_status'] = 'DELETE_COMPLETE'
                    result['success'] = True
                    if callback:
                        callback(f"  [OK] {stack_name}: DELETE_COMPLETE ({elapsed}s)")
                    return result
                
                if current_status == 'DELETE_COMPLETE':
                    result['final_status'] = 'DELETE_COMPLETE'
                    result['success'] = True
                    if callback:
                        callback(f"  [OK] {stack_name}: DELETE_COMPLETE ({elapsed}s)")
                    return result
                
                if current_status == 'DELETE_FAILED':
                    result['final_status'] = 'DELETE_FAILED'
                    result['success'] = False
                    # Get failure reason
                    try:
                        events = cfn_client.describe_stack_events(StackName=stack_name)
                        for event in events.get('StackEvents', []):
                            if 'FAILED' in event.get('ResourceStatus', ''):
                                result['error'] = event.get('ResourceStatusReason', 'Unknown error')
                                break
                    except:
                        pass
                    if callback:
                        callback(f"  [X] {stack_name}: DELETE_FAILED - {result.get('error', 'Unknown error')}")
                    return result
                
                if current_status == 'DELETE_IN_PROGRESS':
                    deletion_started = True
                    stuck_count = 0  # Reset stuck counter
                    if callback:
                        callback(f"  [...] {stack_name}: DELETE_IN_PROGRESS ({elapsed}s elapsed)...")
                else:
                    # Status is not DELETE_IN_PROGRESS - deletion may not have started
                    stuck_count += 1
                    
                    if not deletion_started and stuck_count >= max_stuck_count:
                        # Deletion hasn't started after 60 seconds - investigate why
                        if callback:
                            callback(f"  [!] {stack_name}: Deletion not starting, checking for blockers...")
                        
                        blockers = self._get_stack_deletion_blockers(cfn_client, stack_name)
                        if blockers:
                            result['final_status'] = 'BLOCKED'
                            result['error'] = f'Deletion blocked: {blockers}'
                            if callback:
                                callback(f"  [X] {stack_name}: BLOCKED - {blockers}")
                            return result
                        
                        # Try to delete again
                        if callback:
                            callback(f"  [SYNC] {stack_name}: Retrying deletion...")
                        try:
                            cfn_client.delete_stack(StackName=stack_name)
                            stuck_count = 0  # Reset and give it another chance
                        except ClientError as e:
                            if 'does not exist' in str(e).lower():
                                result['final_status'] = 'DELETE_COMPLETE'
                                result['success'] = True
                                if callback:
                                    callback(f"  [OK] {stack_name}: DELETE_COMPLETE ({elapsed}s)")
                                return result
                            # Log the error but continue polling
                            if callback:
                                callback(f"  [!] {stack_name}: Retry failed - {str(e)}")
                    elif callback:
                        # Log the current status
                        callback(f"  [SYNC] {stack_name}: {current_status} ({elapsed}s elapsed)...")
            
            # Timeout - provide detailed reason
            result['final_status'] = 'TIMEOUT'
            if not deletion_started:
                blockers = self._get_stack_deletion_blockers(cfn_client, stack_name)
                if blockers:
                    result['error'] = f'Deletion never started. Blockers: {blockers}'
                else:
                    result['error'] = f'Deletion never started after {max_wait}s - stack may have dependencies'
            else:
                result['error'] = f'Deletion timed out after {max_wait}s'
            
            if callback:
                callback(f"  [!] {stack_name}: {result['error']}")
            return result
            
        except ClientError as e:
            if 'does not exist' in str(e).lower():
                result['final_status'] = 'DELETED'
                result['success'] = True
                if callback:
                    callback(f"  [OK] {stack_name}: Already deleted")
                return result
            result['error'] = str(e)
            if callback:
                callback(f"  [X] {stack_name}: Error - {str(e)}")
            return result
        except Exception as e:
            result['error'] = str(e)
            if callback:
                callback(f"  [X] {stack_name}: Error - {str(e)}")
            return result

    def complete_cleanup(self, capability_name: str, environment: str, region: str,
                        account_id: str, callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Complete cleanup of ALL resources for a capability
        """
        # Sanitize capability name once at the start
        sanitized_name = capability_name.replace(' ', '-').replace('_', '-')
        sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
        
        if callback:
            callback("[CLEAN] Starting COMPLETE CLEANUP")
            callback(f"   Capability: {sanitized_name}")
            callback(f"   Environment: {environment}")
            callback(f"   Region: {region}")
            callback("")
        
        results = {
            'stacks_deleted': [],
            'stacks_failed': [],
            'resources_cleaned': [],
            'errors': [],
            'stack_details': []
        }
        
        cfn_client = self._get_client('cloudformation', region)
        cfn_us_east_1 = self._get_client('cloudformation', 'us-east-1')
        
        # Step 1: Disable ALL deletion protection
        if callback:
            callback("=" * 60)
            callback("STEP 1: Disabling deletion protection on all resources")
            callback("=" * 60)
        
        # ALB deletion protection (CRITICAL - must be done first!)
        if callback:
            callback("\n[PIN] Checking Application Load Balancers...")
        disabled_albs = self.disable_alb_deletion_protection(region, capability_name, environment, callback)
        results['resources_cleaned'].extend([f"ALB protection: {alb}" for alb in disabled_albs])
        
        # RDS deletion protection
        if callback:
            callback("\n[PIN] Checking RDS instances...")
        disabled_dbs = self.disable_rds_deletion_protection(region, capability_name, environment, callback)
        results['resources_cleaned'].extend([f"RDS protection: {db}" for db in disabled_dbs])
        
        # CloudFormation stack termination protection
        if callback:
            callback("\n[PIN] Checking CloudFormation stack protection...")
        
        for stack_type in self.CLEANUP_ORDER:
            stack_name = self.get_stack_name(capability_name, environment, stack_type)
            try:
                client = cfn_us_east_1 if 'global' in stack_type else cfn_client
                if self.stack_exists(client, stack_name):
                    client.update_termination_protection(
                        StackName=stack_name,
                        EnableTerminationProtection=False
                    )
                    if callback:
                        callback(f"  [OK] Disabled termination protection: {stack_name}")
            except Exception as e:
                if callback:
                    callback(f"  [!] Could not disable protection for {stack_name}")
        
        # Step 2: Clean orphaned resources
        if callback:
            callback("\n" + "=" * 60)
            callback("STEP 2: Cleaning orphaned resources")
            callback("=" * 60)
        
        orphaned = self.delete_orphaned_resources(region, capability_name, environment, callback)
        for resource_type, items in orphaned.items():
            results['resources_cleaned'].extend([f"{resource_type}: {item}" for item in items])
        
        # Step 3: Empty S3 buckets
        if callback:
            callback("\n" + "=" * 60)
            callback("STEP 3: Emptying S3 buckets")
            callback("=" * 60)
        
        bucket_patterns = [
            f"{sanitized_name}-{environment}-frontend",
            f"{sanitized_name}-{environment}-data",
            f"{sanitized_name.lower()}-{environment}-frontend",
            f"{sanitized_name.lower()}-{environment}-data",
        ]
        for bucket in bucket_patterns:
            if self.empty_s3_bucket(bucket, region, callback):
                results['resources_cleaned'].append(f"S3: {bucket}")
        
        # Step 4: Delete ECR repositories
        if callback:
            callback("\n" + "=" * 60)
            callback("STEP 4: Deleting ECR repositories")
            callback("=" * 60)
        
        # ECR repository names must be lowercase and follow AWS naming rules
        # Only lowercase letters, numbers, hyphens, underscores, periods, and forward slashes
        ecr_name = f"{sanitized_name.lower()}-{environment}"
        # Remove any invalid characters for ECR
        ecr_name = ''.join(c for c in ecr_name if c.isalnum() or c in '-_.')
        
        if self.delete_ecr_repository(ecr_name, region, callback):
            results['resources_cleaned'].append(f"ECR: {ecr_name}")
        
        # Step 5: Delete CloudWatch log groups
        if callback:
            callback("\n" + "=" * 60)
            callback("STEP 5: Deleting CloudWatch log groups")
            callback("=" * 60)
        
        logs_client = self._get_client('logs', region)
        log_groups = [
            f"/ecs/{sanitized_name}-{environment}",
            f"/aws/application/{sanitized_name}-{environment}",
            f"/ecs/{sanitized_name.lower()}-{environment}",
            f"/aws/application/{sanitized_name.lower()}-{environment}",
        ]
        for log_group in log_groups:
            try:
                logs_client.delete_log_group(logGroupName=log_group)
                results['resources_cleaned'].append(f"LogGroup: {log_group}")
                if callback:
                    callback(f"  [OK] Deleted log group: {log_group}")
            except ClientError as e:
                if e.response['Error']['Code'] != 'ResourceNotFoundException':
                    if callback:
                        callback(f"  [!] Could not delete log group: {log_group}")

        # Step 6: Delete CloudFormation stacks with detailed status
        if callback:
            callback("\n" + "=" * 60)
            callback("STEP 6: Deleting CloudFormation stacks")
            callback("=" * 60)
            callback("")
        
        # First pass - delete all stacks
        blocked_stacks = []  # Track stacks blocked by exports
        for stack_type in self.CLEANUP_ORDER:
            stack_name = self.get_stack_name(capability_name, environment, stack_type)
            client = cfn_us_east_1 if 'global' in stack_type else cfn_client
            
            stack_result = self.delete_stack_with_status(client, stack_name, callback)
            results['stack_details'].append(stack_result)
            
            if stack_result['success']:
                results['stacks_deleted'].append(stack_name)
            elif stack_result.get('final_status') == 'BLOCKED':
                # Stack is blocked by exports - save for later retry after dependent stacks are deleted
                blocked_stacks.append((stack_name, stack_type, client))
                if callback:
                    callback(f"  [i] {stack_name}: Will retry after dependent stacks are deleted")
            else:
                results['stacks_failed'].append(stack_name)
                if stack_result.get('error'):
                    results['errors'].append(f"{stack_name}: {stack_result['error']}")
        
        # Retry blocked stacks (they may be unblocked now that dependent stacks are deleted)
        if blocked_stacks:
            if callback:
                callback("\n" + "-" * 40)
                callback("Retrying blocked stacks (dependencies may be resolved)...")
                callback("-" * 40)
            
            # Wait for resources to settle
            time.sleep(15)
            
            for stack_name, stack_type, client in blocked_stacks:
                stack_result = self.delete_stack_with_status(client, stack_name, callback)
                
                if stack_result['success']:
                    results['stacks_deleted'].append(stack_name)
                else:
                    results['stacks_failed'].append(stack_name)
                    if stack_result.get('error'):
                        results['errors'].append(f"{stack_name} (blocked retry): {stack_result['error']}")
        
        # Retry other failed stacks once
        if results['stacks_failed']:
            if callback:
                callback("\n" + "-" * 40)
                callback("Retrying failed stacks...")
                callback("-" * 40)
            
            # Wait for resources to settle
            time.sleep(15)
            
            retry_stacks = results['stacks_failed'].copy()
            results['stacks_failed'] = []
            
            for stack_name in retry_stacks:
                # Determine which client to use
                client = cfn_us_east_1 if 'global' in stack_name else cfn_client
                
                stack_result = self.delete_stack_with_status(client, stack_name, callback)
                
                if stack_result['success']:
                    results['stacks_deleted'].append(stack_name)
                else:
                    results['stacks_failed'].append(stack_name)
                    if stack_result.get('error'):
                        results['errors'].append(f"{stack_name} (retry): {stack_result['error']}")
        
        # Step 7: Clean up deployment state
        if callback:
            callback("\n" + "=" * 60)
            callback("STEP 7: Cleaning up deployment state")
            callback("=" * 60)
        
        try:
            # Try to delete with the original capability name
            deployment_state_service.delete_deployment_state(capability_name, environment)
            results['resources_cleaned'].append("Deployment state")
            if callback:
                callback(f"  [OK] Deleted deployment state for: {capability_name}")
            
            # Also try with the name converted back to spaces (in case it was passed with hyphens)
            # e.g., "Call-Processing" -> "Call Processing"
            original_name = capability_name.replace('-', ' ')
            if original_name != capability_name:
                deployment_state_service.delete_deployment_state(original_name, environment)
                if callback:
                    callback(f"  [OK] Also deleted deployment state for: {original_name}")
        except Exception as e:
            if callback:
                callback(f"  [!] Could not delete deployment state: {str(e)}")
        
        # Summary
        if callback:
            callback("\n" + "=" * 60)
            callback("CLEANUP SUMMARY")
            callback("=" * 60)
            callback(f"[OK] Stacks deleted: {len(results['stacks_deleted'])}")
            callback(f"[X] Stacks failed: {len(results['stacks_failed'])}")
            callback(f"[CLEAN] Resources cleaned: {len(results['resources_cleaned'])}")
            
            if results['stacks_deleted']:
                callback("\nDeleted stacks:")
                for stack in results['stacks_deleted']:
                    callback(f"  [OK] {stack}")
            
            if results['stacks_failed']:
                callback("\nFailed stacks:")
                for stack in results['stacks_failed']:
                    callback(f"  [X] {stack}")
            
            if results['errors']:
                callback("\nErrors:")
                for error in results['errors'][:5]:
                    callback(f"  - {error}")
        
        # Track deletion in installation history
        if results['stacks_deleted']:
            try:
                from app.services.installation_tracker import get_installation_tracker
                tracker = get_installation_tracker()
                
                deletion_id = tracker.create_deletion_record(
                    capability_name=capability_name,
                    capability_version="unknown",  # We don't have version info during deletion
                    environment=environment,
                    region=region,
                    account_id=account_id,
                    stacks_deleted=results['stacks_deleted']
                )
                
                if callback:
                    callback(f"\n[NOTE] Deletion tracked in installation history: {deletion_id}")
                    
            except Exception as e:
                if callback:
                    callback(f"\n[!] Could not track deletion in history: {str(e)}")
        
        # Step 8: Clean up call-processing infrastructure resources (if applicable)
        normalized_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
        if normalized_capability == "call-processing":
            if callback:
                callback("\n" + "=" * 60)
                callback("STEP 8: Cleaning up call-processing infrastructure resources")
                callback("=" * 60)
            
            infra_cleaned = self.cleanup_call_processing_infrastructure(environment, region, callback)
            results['resources_cleaned'].extend(infra_cleaned)
        
        results['success'] = len(results['stacks_failed']) == 0
        results['summary'] = f"Deleted {len(results['stacks_deleted'])} stacks, cleaned {len(results['resources_cleaned'])} resources"
        
        return results
    
    def cleanup_call_processing_infrastructure(self, environment: str, region: str,
                                               callback: Optional[Callable] = None) -> List[str]:
        """
        Clean up call-processing specific infrastructure resources.
        
        This includes:
        - DynamoDB tables (transformation-system, license, wxcc-task-tracking)
        - S3 buckets (call-data, wxcc-simulator, journey-logs, journey-reports)
        - SSM parameters (/call-processing/{env}/*)
        - Secrets Manager secrets (call-processing/{env}/*)
        - Glue database and tables
        - CloudWatch log groups (/aws/call-processing/{env})
        
        Args:
            environment: Target environment (dev, stage, test, prod)
            region: AWS region
            callback: Optional callback for progress updates
            
        Returns:
            List of cleaned up resource names
        """
        cleaned = []
        
        # 1. Delete DynamoDB tables
        if callback:
            callback("\n[PKG] Deleting DynamoDB tables...")
        
        dynamodb_tables = [
            f"call-processing-{environment}-transformation-system",
            f"call-processing-{environment}-license",
            f"call-processing-{environment}-wxcc-task-tracking",
        ]
        
        dynamodb_client = self._get_client('dynamodb', region)
        for table_name in dynamodb_tables:
            try:
                dynamodb_client.delete_table(TableName=table_name)
                cleaned.append(f"DynamoDB: {table_name}")
                if callback:
                    callback(f"  [OK] Deleted DynamoDB table: {table_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    if callback:
                        callback(f"  [i] DynamoDB table not found: {table_name}")
                else:
                    if callback:
                        callback(f"  [!] Error deleting DynamoDB table {table_name}: {str(e)}")
        
        # 2. Delete S3 buckets (empty first, then delete)
        if callback:
            callback("\n[BUCKET] Deleting S3 buckets...")
        
        s3_buckets = [
            f"call-processing-{environment}-call-data",
            f"call-processing-{environment}-wxcc-simulator",
            f"call-processing-{environment}-journey-logs",
            f"call-processing-{environment}-journey-reports",
        ]
        
        s3_client = self._get_client('s3', region)
        for bucket_name in s3_buckets:
            try:
                # First empty the bucket
                self.empty_s3_bucket(bucket_name, region, callback)
                # Then delete the bucket
                s3_client.delete_bucket(Bucket=bucket_name)
                cleaned.append(f"S3: {bucket_name}")
                if callback:
                    callback(f"  [OK] Deleted S3 bucket: {bucket_name}")
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code in ['NoSuchBucket', '404']:
                    if callback:
                        callback(f"  [i] S3 bucket not found: {bucket_name}")
                else:
                    if callback:
                        callback(f"  [!] Error deleting S3 bucket {bucket_name}: {str(e)}")
        
        # 3. Delete SSM parameters
        if callback:
            callback("\n[TOOL] Deleting SSM parameters...")
        
        ssm_client = self._get_client('ssm', region)
        ssm_path = f"/call-processing/{environment}/"
        
        try:
            # Get all parameters under the path
            paginator = ssm_client.get_paginator('get_parameters_by_path')
            params_to_delete = []
            
            for page in paginator.paginate(Path=ssm_path, Recursive=True):
                for param in page.get('Parameters', []):
                    params_to_delete.append(param['Name'])
            
            # Delete in batches of 10 (AWS limit)
            for i in range(0, len(params_to_delete), 10):
                batch = params_to_delete[i:i+10]
                if batch:
                    ssm_client.delete_parameters(Names=batch)
                    for param_name in batch:
                        cleaned.append(f"SSM: {param_name}")
            
            if callback:
                callback(f"  [OK] Deleted {len(params_to_delete)} SSM parameters")
        except ClientError as e:
            if callback:
                callback(f"  [!] Error deleting SSM parameters: {str(e)}")
        
        # 4. Delete Secrets Manager secrets
        if callback:
            callback("\n[LOCK] Deleting Secrets Manager secrets...")
        
        secrets_client = self._get_client('secretsmanager', region)
        secret_names = [
            f"call-processing/{environment}/api-keys",
            f"call-processing/{environment}/wxcc",
            f"call-processing/{environment}/openai",
            f"call-processing/{environment}/license",
            f"call-processing/{environment}/anthropic",
            f"call-processing/{environment}/github",
        ]
        
        for secret_name in secret_names:
            try:
                secrets_client.delete_secret(
                    SecretId=secret_name,
                    ForceDeleteWithoutRecovery=True
                )
                cleaned.append(f"Secret: {secret_name}")
                if callback:
                    callback(f"  [OK] Deleted secret: {secret_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    if callback:
                        callback(f"  [i] Secret not found: {secret_name}")
                else:
                    if callback:
                        callback(f"  [!] Error deleting secret {secret_name}: {str(e)}")
        
        # 5. Delete Glue database and tables
        if callback:
            callback("\n[CHART] Deleting Glue resources...")
        
        glue_client = self._get_client('glue', region)
        # Use hyphen naming convention to match provisioning: call-processing-{env}-analytics
        database_name = f"call-processing-{environment}-analytics"
        
        try:
            # Delete tables first
            try:
                tables = glue_client.get_tables(DatabaseName=database_name)
                for table in tables.get('TableList', []):
                    table_name = table['Name']
                    glue_client.delete_table(DatabaseName=database_name, Name=table_name)
                    cleaned.append(f"Glue Table: {database_name}.{table_name}")
                    if callback:
                        callback(f"  [OK] Deleted Glue table: {database_name}.{table_name}")
            except ClientError as e:
                if e.response['Error']['Code'] != 'EntityNotFoundException':
                    if callback:
                        callback(f"  [!] Error listing Glue tables: {str(e)}")
            
            # Delete database
            glue_client.delete_database(Name=database_name)
            cleaned.append(f"Glue Database: {database_name}")
            if callback:
                callback(f"  [OK] Deleted Glue database: {database_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'EntityNotFoundException':
                if callback:
                    callback(f"  [i] Glue database not found: {database_name}")
            else:
                if callback:
                    callback(f"  [!] Error deleting Glue database {database_name}: {str(e)}")
        
        # 6. Delete CloudWatch log group
        if callback:
            callback("\n[LIST] Deleting CloudWatch log groups...")
        
        logs_client = self._get_client('logs', region)
        log_group_name = f"/aws/call-processing/{environment}"
        
        try:
            logs_client.delete_log_group(logGroupName=log_group_name)
            cleaned.append(f"LogGroup: {log_group_name}")
            if callback:
                callback(f"  [OK] Deleted log group: {log_group_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                if callback:
                    callback(f"  [i] Log group not found: {log_group_name}")
            else:
                if callback:
                    callback(f"  [!] Error deleting log group {log_group_name}: {str(e)}")
        
        if callback:
            callback(f"\n[OK] Cleaned up {len(cleaned)} call-processing infrastructure resources")
        
        return cleaned
    
    def cleanup_capability(self, capability_name: str, environment: str, region: str,
                          callback: Optional[Callable] = None) -> Dict[str, bool]:
        """Simple cleanup workflow - delegates to complete_cleanup"""
        result = self.complete_cleanup(capability_name, environment, region, '', callback)
        return {stack: True for stack in result.get('stacks_deleted', [])}
