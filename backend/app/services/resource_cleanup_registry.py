"""
Resource Cleanup Registry
Extensible system for detecting and cleaning up orphaned AWS resources
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional, Callable, Any, List
import logging
from app.models.validation import ResourceDefinition, OrphanedResource

logger = logging.getLogger(__name__)


class ResourceCleanerBase(ABC):
    """Base class for resource-specific cleaners"""
    
    @abstractmethod
    def detect(self, resource_identifier: str, region: str, credentials: Optional[Dict[str, str]] = None) -> bool:
        """
        Check if a resource exists
        
        Args:
            resource_identifier: Unique identifier for the resource
            region: AWS region
            credentials: Optional AWS credentials
            
        Returns:
            True if resource exists, False otherwise
        """
        pass
    
    @abstractmethod
    def cleanup(
        self,
        resource_identifier: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up an orphaned resource
        
        Args:
            resource_identifier: Unique identifier for the resource
            region: AWS region
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get_name(self, resource_def: ResourceDefinition, parameters: Dict[str, str]) -> str:
        """
        Extract resource identifier from resource definition
        
        Args:
            resource_def: CloudFormation resource definition
            parameters: Resolved parameters
            
        Returns:
            Resource identifier (name, ARN, etc.)
        """
        pass


class ResourceCleanupRegistry:
    """Registry for resource type detection and cleanup"""
    
    def __init__(self):
        """Initialize the registry"""
        self._cleaners: Dict[str, ResourceCleanerBase] = {}
        logger.info("ResourceCleanupRegistry initialized")
    
    def register_resource_type(
        self,
        resource_type: str,
        cleaner: ResourceCleanerBase
    ):
        """
        Register a new resource type for detection and cleanup
        
        Args:
            resource_type: AWS resource type (e.g., 'AWS::S3::Bucket')
            cleaner: ResourceCleanerBase instance for this resource type
        """
        self._cleaners[resource_type] = cleaner
        logger.info(f"Registered cleaner for resource type: {resource_type}")
    
    def detect_orphaned_resource(
        self,
        resource_def: ResourceDefinition,
        region: str,
        parameters: Dict[str, str],
        credentials: Optional[Dict[str, str]] = None
    ) -> Optional[OrphanedResource]:
        """
        Detect if a resource exists as orphaned
        
        Args:
            resource_def: CloudFormation resource definition
            region: AWS region
            parameters: Resolved parameters
            credentials: Optional AWS credentials
            
        Returns:
            OrphanedResource if resource exists, None otherwise
        """
        resource_type = resource_def.resource_type
        
        # Check if we have a cleaner for this resource type
        if resource_type not in self._cleaners:
            logger.debug(f"No cleaner registered for resource type: {resource_type}")
            return None
        
        cleaner = self._cleaners[resource_type]
        
        try:
            # Get the resource identifier
            resource_identifier = cleaner.get_name(resource_def, parameters)
            
            if not resource_identifier:
                logger.warning(f"Could not extract identifier for resource: {resource_def.logical_id}")
                return None
            
            # Check if resource exists
            exists = cleaner.detect(resource_identifier, region, credentials)
            
            if exists:
                from datetime import datetime
                orphaned = OrphanedResource(
                    resource_type=resource_type,
                    resource_identifier=resource_identifier,
                    region=region,
                    stack_name="",  # Will be set by caller
                    detected_at=datetime.now()
                )
                logger.info(f"Detected orphaned resource: {resource_type} - {resource_identifier}")
                return orphaned
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting orphaned resource {resource_def.logical_id}: {str(e)}")
            return None
    
    def cleanup_orphaned_resource(
        self,
        orphaned_resource: OrphanedResource,
        credentials: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None
    ) -> bool:
        """
        Clean up an orphaned resource
        
        Args:
            orphaned_resource: OrphanedResource to clean up
            credentials: Optional AWS credentials
            callback: Optional callback for progress updates
            
        Returns:
            True if cleanup successful, False otherwise
        """
        resource_type = orphaned_resource.resource_type
        
        # Check if we have a cleaner for this resource type
        if resource_type not in self._cleaners:
            logger.error(f"No cleaner registered for resource type: {resource_type}")
            return False
        
        cleaner = self._cleaners[resource_type]
        
        try:
            logger.info(f"Cleaning up orphaned resource: {resource_type} - {orphaned_resource.resource_identifier}")
            
            success = cleaner.cleanup(
                orphaned_resource.resource_identifier,
                orphaned_resource.region,
                credentials,
                callback
            )
            
            if success:
                logger.info(f"Successfully cleaned up: {resource_type} - {orphaned_resource.resource_identifier}")
            else:
                logger.warning(f"Failed to clean up: {resource_type} - {orphaned_resource.resource_identifier}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error cleaning up orphaned resource {orphaned_resource.resource_identifier}: {str(e)}")
            return False
    
    def get_supported_resource_types(self) -> list:
        """
        Get list of supported resource types
        
        Returns:
            List of registered resource types
        """
        return list(self._cleaners.keys())
    
    def get_cleanup_order(self, orphaned_resources: List[OrphanedResource]) -> List[OrphanedResource]:
        """
        Sort orphaned resources by dependency order for cleanup
        
        Resources with dependencies should be cleaned up before their dependents.
        For example:
        - CloudFront distributions should be disabled before deletion
        - S3 buckets should be emptied before deletion
        - ALBs should have target groups deleted first
        - ECR repositories should have images deleted first
        
        Args:
            orphaned_resources: List of orphaned resources
            
        Returns:
            Sorted list of orphaned resources in cleanup order
        """
        # Define cleanup priority (lower number = clean up first)
        # Resources that depend on others should be cleaned up first
        priority_map = {
            'AWS::CloudFront::Distribution': 1,  # Takes longest, start first
            'AWS::ElasticLoadBalancingV2::LoadBalancer': 2,  # ALBs
            'AWS::ECR::Repository': 3,  # ECR repos
            'AWS::S3::Bucket': 4,  # S3 buckets
            'AWS::Logs::LogGroup': 5,  # Log groups (least dependencies)
        }
        
        # Sort by priority
        def get_priority(resource: OrphanedResource) -> int:
            return priority_map.get(resource.resource_type, 999)
        
        sorted_resources = sorted(orphaned_resources, key=get_priority)
        
        logger.info(f"Sorted {len(sorted_resources)} resources for cleanup")
        return sorted_resources
