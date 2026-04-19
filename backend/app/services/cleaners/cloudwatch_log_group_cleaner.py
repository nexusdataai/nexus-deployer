"""
CloudWatch Log Group Cleaner
Detects and cleans up orphaned CloudWatch log groups
"""
import boto3
from typing import Dict, Optional, Callable
import logging
from botocore.exceptions import ClientError
from app.services.resource_cleanup_registry import ResourceCleanerBase
from app.models.validation import ResourceDefinition

logger = logging.getLogger(__name__)


class CloudWatchLogGroupCleaner(ResourceCleanerBase):
    """Cleaner for CloudWatch log groups"""
    
    def detect(self, resource_identifier: str, region: str, credentials: Optional[Dict[str, str]] = None) -> bool:
        """
        Check if CloudWatch log group exists
        
        Args:
            resource_identifier: Log group name
            region: AWS region
            credentials: Optional AWS credentials
            
        Returns:
            True if log group exists, False otherwise
        """
        try:
            if credentials:
                logs_client = boto3.client(
                    'logs',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                logs_client = boto3.client('logs', region_name=region)
            
            # Try to describe log group
            response = logs_client.describe_log_groups(logGroupNamePrefix=resource_identifier)
            
            # Check if exact match exists
            for log_group in response.get('logGroups', []):
                if log_group['logGroupName'] == resource_identifier:
                    return True
            
            return False
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'ResourceNotFoundException':
                return False
            else:
                logger.error(f"Error checking CloudWatch log group {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error checking CloudWatch log group {resource_identifier}: {str(e)}")
            return False
    
    def cleanup(
        self,
        resource_identifier: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up CloudWatch log group by deleting it
        
        Args:
            resource_identifier: Log group name
            region: AWS region
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            if credentials:
                logs_client = boto3.client(
                    'logs',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                logs_client = boto3.client('logs', region_name=region)
            
            if callback:
                callback(f"Deleting CloudWatch log group: {resource_identifier}")
            
            # Delete the log group
            logger.info(f"Deleting CloudWatch log group: {resource_identifier}")
            logs_client.delete_log_group(logGroupName=resource_identifier)
            
            logger.info(f"Successfully deleted CloudWatch log group: {resource_identifier}")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'ResourceNotFoundException':
                logger.info(f"CloudWatch log group {resource_identifier} does not exist (already deleted)")
                return True
            else:
                logger.error(f"Error cleaning up CloudWatch log group {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error cleaning up CloudWatch log group {resource_identifier}: {str(e)}")
            return False
    
    def get_name(self, resource_def: ResourceDefinition, parameters: Dict[str, str]) -> str:
        """
        Extract log group name from resource definition
        
        Args:
            resource_def: CloudFormation resource definition
            parameters: Resolved parameters
            
        Returns:
            Log group name
        """
        properties = resource_def.properties
        
        # Check for LogGroupName property
        if 'LogGroupName' in properties:
            log_group_name = properties['LogGroupName']
            # If it's a string, return it
            if isinstance(log_group_name, str):
                return log_group_name
        
        # If no explicit name, CloudFormation generates one
        # We can't predict the generated name, so return empty
        return ""
