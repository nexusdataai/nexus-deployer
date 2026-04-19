"""
Application Load Balancer Cleaner
Detects and cleans up orphaned ALBs
"""
import boto3
from typing import Dict, Optional, Callable
import logging
from botocore.exceptions import ClientError
from app.services.resource_cleanup_registry import ResourceCleanerBase
from app.models.validation import ResourceDefinition

logger = logging.getLogger(__name__)


class ALBCleaner(ResourceCleanerBase):
    """Cleaner for Application Load Balancers"""
    
    def detect(self, resource_identifier: str, region: str, credentials: Optional[Dict[str, str]] = None) -> bool:
        """
        Check if ALB exists
        
        Args:
            resource_identifier: ALB name
            region: AWS region
            credentials: Optional AWS credentials
            
        Returns:
            True if ALB exists, False otherwise
        """
        try:
            if credentials:
                elbv2_client = boto3.client(
                    'elbv2',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                elbv2_client = boto3.client('elbv2', region_name=region)
            
            # Try to describe load balancers with this name
            response = elbv2_client.describe_load_balancers(Names=[resource_identifier])
            
            if response.get('LoadBalancers'):
                return True
            return False
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'LoadBalancerNotFound':
                return False
            else:
                logger.error(f"Error checking ALB {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error checking ALB {resource_identifier}: {str(e)}")
            return False
    
    def cleanup(
        self,
        resource_identifier: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up ALB by disabling deletion protection and deleting it
        
        Args:
            resource_identifier: ALB name
            region: AWS region
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            if credentials:
                elbv2_client = boto3.client(
                    'elbv2',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                elbv2_client = boto3.client('elbv2', region_name=region)
            
            # Get the ALB ARN
            response = elbv2_client.describe_load_balancers(Names=[resource_identifier])
            
            if not response.get('LoadBalancers'):
                logger.info(f"ALB {resource_identifier} does not exist (already deleted)")
                return True
            
            alb_arn = response['LoadBalancers'][0]['LoadBalancerArn']
            
            if callback:
                callback(f"Disabling deletion protection for ALB: {resource_identifier}")
            
            # Disable deletion protection
            logger.info(f"Disabling deletion protection for ALB: {resource_identifier}")
            try:
                elbv2_client.modify_load_balancer_attributes(
                    LoadBalancerArn=alb_arn,
                    Attributes=[
                        {
                            'Key': 'deletion_protection.enabled',
                            'Value': 'false'
                        }
                    ]
                )
            except ClientError as e:
                # If deletion protection is already disabled, continue
                logger.debug(f"Could not disable deletion protection: {str(e)}")
            
            if callback:
                callback(f"Deleting ALB: {resource_identifier}")
            
            # Delete the ALB
            logger.info(f"Deleting ALB: {resource_identifier}")
            elbv2_client.delete_load_balancer(LoadBalancerArn=alb_arn)
            
            logger.info(f"Successfully deleted ALB: {resource_identifier}")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'LoadBalancerNotFound':
                logger.info(f"ALB {resource_identifier} does not exist (already deleted)")
                return True
            else:
                logger.error(f"Error cleaning up ALB {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error cleaning up ALB {resource_identifier}: {str(e)}")
            return False
    
    def get_name(self, resource_def: ResourceDefinition, parameters: Dict[str, str]) -> str:
        """
        Extract ALB name from resource definition
        
        Args:
            resource_def: CloudFormation resource definition
            parameters: Resolved parameters
            
        Returns:
            ALB name
        """
        properties = resource_def.properties
        
        # Check for Name property
        if 'Name' in properties:
            alb_name = properties['Name']
            # If it's a string, return it
            if isinstance(alb_name, str):
                return alb_name
        
        # If no explicit name, CloudFormation generates one
        # We can't predict the generated name, so return empty
        return ""
