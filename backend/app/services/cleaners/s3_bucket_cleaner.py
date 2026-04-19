"""
S3 Bucket Cleaner
Detects and cleans up orphaned S3 buckets
"""
import boto3
from typing import Dict, Optional, Callable
import logging
from botocore.exceptions import ClientError
from app.services.resource_cleanup_registry import ResourceCleanerBase
from app.models.validation import ResourceDefinition

logger = logging.getLogger(__name__)


class S3BucketCleaner(ResourceCleanerBase):
    """Cleaner for S3 buckets"""
    
    def detect(self, resource_identifier: str, region: str, credentials: Optional[Dict[str, str]] = None) -> bool:
        """
        Check if S3 bucket exists
        
        Args:
            resource_identifier: Bucket name
            region: AWS region
            credentials: Optional AWS credentials
            
        Returns:
            True if bucket exists, False otherwise
        """
        try:
            if credentials:
                s3_client = boto3.client(
                    's3',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                s3_client = boto3.client('s3', region_name=region)
            
            # Try to get bucket location to check if it exists
            s3_client.head_bucket(Bucket=resource_identifier)
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['404', 'NoSuchBucket']:
                return False
            elif error_code == '403':
                # Bucket exists but we don't have permission
                logger.warning(f"Access denied to bucket {resource_identifier}")
                return True
            else:
                logger.error(f"Error checking bucket {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error checking bucket {resource_identifier}: {str(e)}")
            return False
    
    def cleanup(
        self,
        resource_identifier: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up S3 bucket by emptying and deleting it
        
        Args:
            resource_identifier: Bucket name
            region: AWS region
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            if credentials:
                s3_client = boto3.client(
                    's3',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
                s3_resource = boto3.resource(
                    's3',
                    region_name=region,
                    aws_access_key_id=credentials.get('aws_access_key_id'),
                    aws_secret_access_key=credentials.get('aws_secret_access_key'),
                    aws_session_token=credentials.get('aws_session_token')
                )
            else:
                s3_client = boto3.client('s3', region_name=region)
                s3_resource = boto3.resource('s3', region_name=region)
            
            bucket = s3_resource.Bucket(resource_identifier)
            
            if callback:
                callback(f"Emptying S3 bucket: {resource_identifier}")
            
            # Delete all objects
            logger.info(f"Deleting all objects in bucket: {resource_identifier}")
            bucket.objects.all().delete()
            
            # Delete all object versions and delete markers
            logger.info(f"Deleting all versions in bucket: {resource_identifier}")
            bucket.object_versions.all().delete()
            
            if callback:
                callback(f"Deleting S3 bucket: {resource_identifier}")
            
            # Delete the bucket
            logger.info(f"Deleting bucket: {resource_identifier}")
            bucket.delete()
            
            logger.info(f"Successfully deleted S3 bucket: {resource_identifier}")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['NoSuchBucket', '404']:
                logger.info(f"Bucket {resource_identifier} does not exist (already deleted)")
                return True
            else:
                logger.error(f"Error cleaning up bucket {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error cleaning up bucket {resource_identifier}: {str(e)}")
            return False
    
    def get_name(self, resource_def: ResourceDefinition, parameters: Dict[str, str]) -> str:
        """
        Extract bucket name from resource definition
        
        Args:
            resource_def: CloudFormation resource definition
            parameters: Resolved parameters
            
        Returns:
            Bucket name
        """
        properties = resource_def.properties
        
        # Check for BucketName property
        if 'BucketName' in properties:
            bucket_name = properties['BucketName']
            # If it's a string, return it
            if isinstance(bucket_name, str):
                return bucket_name
        
        # If no explicit name, CloudFormation generates one
        # We can't predict the generated name, so return empty
        return ""
