"""
ECR Repository Cleaner
Detects and cleans up orphaned ECR repositories
"""
import boto3
from typing import Dict, Optional, Callable
import logging
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.services.resource_cleanup_registry import ResourceCleanerBase
from app.models.validation import ResourceDefinition

logger = logging.getLogger(__name__)


class ECRRepositoryCleaner(ResourceCleanerBase):
    """Cleaner for ECR repositories"""
    
    def detect(self, resource_identifier: str, region: str, credentials: Optional[Dict[str, str]] = None) -> bool:
        """
        Check if ECR repository exists
        
        Args:
            resource_identifier: Repository name
            region: AWS region
            credentials: Optional AWS credentials
            
        Returns:
            True if repository exists, False otherwise
        """
        try:
            if credentials:
                kw = {
                    "region_name": region,
                    "aws_access_key_id": credentials.get("aws_access_key_id"),
                    "aws_secret_access_key": credentials.get("aws_secret_access_key"),
                    "aws_session_token": credentials.get("aws_session_token"),
                }
                ecr_client = boto3.client("ecr", **merge_vpc_boto3_kwargs("ecr", region, kw))
            else:
                ecr_client = boto3.client(
                    "ecr", **merge_vpc_boto3_kwargs("ecr", region, {"region_name": region})
                )
            
            # Try to describe repository
            response = ecr_client.describe_repositories(repositoryNames=[resource_identifier])
            
            if response.get('repositories'):
                return True
            return False
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'RepositoryNotFoundException':
                return False
            else:
                logger.error(f"Error checking ECR repository {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error checking ECR repository {resource_identifier}: {str(e)}")
            return False
    
    def cleanup(
        self,
        resource_identifier: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up ECR repository by deleting all images and then the repository
        
        Args:
            resource_identifier: Repository name
            region: AWS region
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            if credentials:
                kw = {
                    "region_name": region,
                    "aws_access_key_id": credentials.get("aws_access_key_id"),
                    "aws_secret_access_key": credentials.get("aws_secret_access_key"),
                    "aws_session_token": credentials.get("aws_session_token"),
                }
                ecr_client = boto3.client("ecr", **merge_vpc_boto3_kwargs("ecr", region, kw))
            else:
                ecr_client = boto3.client(
                    "ecr", **merge_vpc_boto3_kwargs("ecr", region, {"region_name": region})
                )
            
            if callback:
                callback(f"Deleting images in ECR repository: {resource_identifier}")
            
            # List all images
            logger.info(f"Listing images in ECR repository: {resource_identifier}")
            try:
                response = ecr_client.list_images(repositoryName=resource_identifier)
                image_ids = response.get('imageIds', [])
                
                # Delete all images if any exist
                if image_ids:
                    logger.info(f"Deleting {len(image_ids)} images from ECR repository: {resource_identifier}")
                    ecr_client.batch_delete_image(
                        repositoryName=resource_identifier,
                        imageIds=image_ids
                    )
            except ClientError as e:
                # If repository is empty or doesn't exist, continue
                logger.debug(f"Could not list/delete images: {str(e)}")
            
            if callback:
                callback(f"Deleting ECR repository: {resource_identifier}")
            
            # Delete the repository (force=True will delete even if images remain)
            logger.info(f"Deleting ECR repository: {resource_identifier}")
            ecr_client.delete_repository(repositoryName=resource_identifier, force=True)
            
            logger.info(f"Successfully deleted ECR repository: {resource_identifier}")
            return True
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'RepositoryNotFoundException':
                logger.info(f"ECR repository {resource_identifier} does not exist (already deleted)")
                return True
            else:
                logger.error(f"Error cleaning up ECR repository {resource_identifier}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Unexpected error cleaning up ECR repository {resource_identifier}: {str(e)}")
            return False
    
    def get_name(self, resource_def: ResourceDefinition, parameters: Dict[str, str]) -> str:
        """
        Extract repository name from resource definition
        
        Args:
            resource_def: CloudFormation resource definition
            parameters: Resolved parameters
            
        Returns:
            Repository name
        """
        properties = resource_def.properties
        
        # Check for RepositoryName property
        if 'RepositoryName' in properties:
            repo_name = properties['RepositoryName']
            # If it's a string, return it
            if isinstance(repo_name, str):
                return repo_name
        
        # If no explicit name, CloudFormation generates one
        # We can't predict the generated name, so return empty
        return ""
