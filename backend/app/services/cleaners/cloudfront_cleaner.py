"""
CloudFront Distribution Cleaner
Detects and cleans up orphaned CloudFront distributions
"""
import boto3
import time
from typing import Dict, Optional, Callable
import logging
from botocore.exceptions import ClientError
from app.services.resource_cleanup_registry import ResourceCleanerBase
from app.models.validation import ResourceDefinition

logger = logging.getLogger(__name__)


class CloudFrontCleaner(ResourceCleanerBase):
    """Cleaner for CloudFront distributions"""
    
    def detect(self, resource_identifier: str, region: str, credentials: Optional[Dict[str, str]] = None) -> bool:
        """
        Check if CloudFront distribution exists
        
        Args:
            resource_identifier: Distribution ID
            region: AWS region (CloudFront is global, but we keep for consistency)
            credentials: Optional AWS credentials
            
        Returns:
            True if distribution exists, False otherwise
        """
        try:
            if credentials:
                cf_client = boto3.client(
                    'cloudfront',
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                cf_client = boto3.client('cloudfront')
            
            # Try to get distribution
            cf_client.get_distribution(Id=resource_identifier)
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchDistribution':
                return False
            else:
                logger.error(f"Error checking CloudFront distribution {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error checking CloudFront distribution {resource_identifier}: {str(e)}")
            return False
    
    def cleanup(
        self,
        resource_identifier: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up CloudFront distribution by disabling and deleting it
        
        Args:
            resource_identifier: Distribution ID
            region: AWS region
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            if credentials:
                cf_client = boto3.client(
                    'cloudfront',
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                cf_client = boto3.client('cloudfront')
            
            # Get the distribution
            response = cf_client.get_distribution(Id=resource_identifier)
            distribution = response['Distribution']
            etag = response['ETag']
            
            # Check if already disabled
            if distribution['DistributionConfig']['Enabled']:
                if callback:
                    callback(f"Disabling CloudFront distribution: {resource_identifier}")
                
                # Disable the distribution
                logger.info(f"Disabling CloudFront distribution: {resource_identifier}")
                config = distribution['DistributionConfig']
                config['Enabled'] = False
                
                update_response = cf_client.update_distribution(
                    Id=resource_identifier,
                    DistributionConfig=config,
                    IfMatch=etag
                )
                etag = update_response['ETag']
                
                # Wait for distribution to be deployed
                if callback:
                    callback(f"Waiting for CloudFront distribution to be disabled: {resource_identifier}")
                
                logger.info(f"Waiting for CloudFront distribution to be disabled: {resource_identifier}")
                max_wait = 600  # 10 minutes
                wait_interval = 30
                elapsed = 0
                
                while elapsed < max_wait:
                    time.sleep(wait_interval)
                    elapsed += wait_interval
                    
                    status_response = cf_client.get_distribution(Id=resource_identifier)
                    status = status_response['Distribution']['Status']
                    
                    if status == 'Deployed':
                        logger.info(f"CloudFront distribution disabled: {resource_identifier}")
                        etag = status_response['ETag']
                        break
                    
                    if callback:
                        callback(f"Waiting for CloudFront distribution (status: {status})...")
                else:
                    logger.warning(f"Timeout waiting for CloudFront distribution to be disabled: {resource_identifier}")
                    # Continue anyway and try to delete
            
            if callback:
                callback(f"Deleting CloudFront distribution: {resource_identifier}")
            
            # Delete the distribution
            logger.info(f"Deleting CloudFront distribution: {resource_identifier}")
            cf_client.delete_distribution(Id=resource_identifier, IfMatch=etag)
            
            logger.info(f"Successfully deleted CloudFront distribution: {resource_identifier}")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchDistribution':
                logger.info(f"CloudFront distribution {resource_identifier} does not exist (already deleted)")
                return True
            else:
                logger.error(f"Error cleaning up CloudFront distribution {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error cleaning up CloudFront distribution {resource_identifier}: {str(e)}")
            return False
    
    def get_name(self, resource_def: ResourceDefinition, parameters: Dict[str, str]) -> str:
        """
        Extract distribution identifier from resource definition
        
        Args:
            resource_def: CloudFormation resource definition
            parameters: Resolved parameters
            
        Returns:
            Distribution ID (empty if not available, as ID is generated by CloudFormation)
        """
        # CloudFront distributions don't have a name property
        # The ID is generated by AWS, so we can't predict it
        # We would need to query CloudFormation to get the physical resource ID
        return ""
