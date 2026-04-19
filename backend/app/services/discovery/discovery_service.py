"""
Discovery Service for Capability Discovery

Scans CloudFormation stacks in AWS accounts to discover deployed capabilities
by parsing stack names that follow the naming convention:
{capability-name}-{environment}-{stack-type}
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set

import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

from .models import (
    DiscoveredCapability,
    DiscoveredStack,
    CapabilityStatus,
)

logger = logging.getLogger(__name__)

# Known stack types from CloudFormationDeploymentService.STACK_ORDER
KNOWN_STACK_TYPES = [
    "backend-foundation",
    "backend-iam-roles",
    "backend-regional-cert",
    "backend-storage",
    "backend-network",
    "backend-service",
    "backend-domain",
    "frontend-global",
    "frontend-cognito",
    "frontend-regional",
]

# Stack types for frontend-only deployment
FRONTEND_STACK_TYPES = ["frontend-global", "frontend-cognito", "frontend-regional"]

# Stack types for backend-only deployment
BACKEND_STACK_TYPES = [
    "backend-foundation",
    "backend-iam-roles",
    "backend-regional-cert",
    "backend-storage",
    "backend-network",
    "backend-service",
    "backend-domain",
]

# Valid environments
VALID_ENVIRONMENTS = ["dev", "test", "stage", "prod"]

# Stack statuses to include in discovery (exclude deleted stacks)
DISCOVERABLE_STACK_STATUSES = [
    "CREATE_COMPLETE",
    "CREATE_IN_PROGRESS",
    "CREATE_FAILED",
    "UPDATE_COMPLETE",
    "UPDATE_IN_PROGRESS",
    "UPDATE_FAILED",
    "UPDATE_ROLLBACK_COMPLETE",
    "UPDATE_ROLLBACK_IN_PROGRESS",
    "UPDATE_ROLLBACK_FAILED",
    "ROLLBACK_COMPLETE",
    "ROLLBACK_IN_PROGRESS",
    "ROLLBACK_FAILED",
    "IMPORT_COMPLETE",
    "IMPORT_IN_PROGRESS",
]


class DiscoveryService:
    """Service for discovering capabilities from CloudFormation stacks."""
    
    def __init__(
        self,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize discovery service.
        
        Args:
            region: AWS region to scan
            credentials: Optional AWS credentials dict with keys:
                - aws_access_key_id
                - aws_secret_access_key
                - aws_session_token (optional)
        """
        self.region = region
        self.credentials = credentials or {}
        self._cfn_client = None
    
    @property
    def cfn_client(self):
        """Lazy-load CloudFormation client with credentials."""
        if self._cfn_client is None:
            kw = {"region_name": self.region, **self.credentials}
            self._cfn_client = boto3.client(
                "cloudformation",
                **merge_vpc_boto3_kwargs("cloudformation", self.region, kw),
            )
        return self._cfn_client
    
    def discover_capabilities(
        self,
        landing_zone_id: str,
        account_id: str,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[List[DiscoveredCapability], List[str]]:
        """
        Discover all capabilities in the AWS account by scanning CloudFormation stacks.
        
        Args:
            landing_zone_id: Landing zone identifier for tracking
            account_id: AWS account ID
            progress_callback: Optional callback for progress updates
            
        Returns:
            Tuple of (discovered_capabilities, errors)
        """
        errors = []
        all_stacks = []
        
        if progress_callback:
            progress_callback(f"Scanning CloudFormation stacks in {self.region}...")
        
        try:
            # List all stacks using paginator
            paginator = self.cfn_client.get_paginator("list_stacks")
            
            stack_count = 0
            for page in paginator.paginate(StackStatusFilter=DISCOVERABLE_STACK_STATUSES):
                for stack_summary in page.get("StackSummaries", []):
                    stack_name = stack_summary["StackName"]
                    stack_count += 1
                    
                    # Try to parse as capability stack
                    parsed = self.parse_stack_name(stack_name)
                    if parsed:
                        capability_name, environment, stack_type = parsed
                        
                        if progress_callback and stack_count % 10 == 0:
                            progress_callback(f"Scanned {stack_count} stacks, found {len(all_stacks)} capability stacks...")
                        
                        # Get full stack details
                        try:
                            stack_details = self._get_stack_details(stack_name)
                            if stack_details:
                                all_stacks.append({
                                    "capability_name": capability_name,
                                    "environment": environment,
                                    "stack_type": stack_type,
                                    "stack_details": stack_details,
                                })
                        except ClientError as e:
                            error_msg = f"Error getting details for {stack_name}: {str(e)}"
                            errors.append(error_msg)
                            logger.warning(error_msg)
            
            if progress_callback:
                progress_callback(f"Found {len(all_stacks)} capability stacks out of {stack_count} total stacks")
            
            # Group stacks by capability
            capabilities = self._group_stacks_into_capabilities(
                all_stacks, landing_zone_id, account_id
            )
            
            if progress_callback:
                progress_callback(f"Discovered {len(capabilities)} capabilities")
            
            return capabilities, errors
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            error_msg = f"CloudFormation API error [{error_code}]: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
            return [], errors
        except Exception as e:
            error_msg = f"Unexpected error during discovery: {str(e)}"
            errors.append(error_msg)
            logger.exception(error_msg)
            return [], errors
    
    def parse_stack_name(self, stack_name: str) -> Optional[Tuple[str, str, str]]:
        """
        Parse stack name to extract capability, environment, and stack type.
        
        Stack naming convention: {capability-name}-{environment}-{stack-type}
        Example: Call-Processing-prod-backend-service
        
        Args:
            stack_name: CloudFormation stack name
            
        Returns:
            Tuple of (capability_name, environment, stack_type) or None if not matching
        """
        # Try each known stack type (longest first to avoid partial matches)
        sorted_types = sorted(KNOWN_STACK_TYPES, key=len, reverse=True)
        
        for stack_type in sorted_types:
            suffix = f"-{stack_type}"
            if stack_name.endswith(suffix):
                # Remove the stack type suffix
                prefix = stack_name[:-len(suffix)]
                
                # Now extract environment from the end of prefix
                for env in VALID_ENVIRONMENTS:
                    env_suffix = f"-{env}"
                    if prefix.endswith(env_suffix):
                        capability_name = prefix[:-len(env_suffix)]
                        if capability_name:  # Ensure we have a capability name
                            return (capability_name, env, stack_type)
        
        return None

    def _get_stack_details(self, stack_name: str) -> Optional[Dict]:
        """
        Get detailed information about a stack.
        
        Args:
            stack_name: CloudFormation stack name
            
        Returns:
            Dict with stack details or None if not found
        """
        try:
            response = self.cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get("Stacks", [])
            if stacks:
                stack = stacks[0]
                return {
                    "stack_name": stack["StackName"],
                    "stack_id": stack.get("StackId"),
                    "stack_status": stack["StackStatus"],
                    "stack_status_reason": stack.get("StackStatusReason"),
                    "created_time": stack.get("CreationTime"),
                    "last_updated_time": stack.get("LastUpdatedTime"),
                    "outputs": {
                        o["OutputKey"]: o["OutputValue"]
                        for o in stack.get("Outputs", [])
                    },
                    "tags": {
                        t["Key"]: t["Value"]
                        for t in stack.get("Tags", [])
                    },
                }
            return None
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ValidationError" and "does not exist" in str(e):
                return None
            raise
    
    def _group_stacks_into_capabilities(
        self,
        stacks: List[Dict],
        landing_zone_id: str,
        account_id: str,
    ) -> List[DiscoveredCapability]:
        """
        Group discovered stacks into capabilities.
        
        Args:
            stacks: List of stack info dicts
            landing_zone_id: Landing zone identifier
            account_id: AWS account ID
            
        Returns:
            List of DiscoveredCapability objects
        """
        # Group by (capability_name, environment)
        grouped: Dict[Tuple[str, str], List[Dict]] = {}
        
        for stack_info in stacks:
            key = (stack_info["capability_name"], stack_info["environment"])
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(stack_info)
        
        # Convert to DiscoveredCapability objects
        capabilities = []
        
        for (capability_name, environment), stack_list in grouped.items():
            # Build DiscoveredStack objects
            discovered_stacks = []
            stack_types_found: Set[str] = set()
            
            for stack_info in stack_list:
                details = stack_info["stack_details"]
                stack_types_found.add(stack_info["stack_type"])
                
                # Parse datetime fields
                created_time = details.get("created_time")
                last_updated_time = details.get("last_updated_time")
                
                discovered_stacks.append(DiscoveredStack(
                    stack_name=details["stack_name"],
                    stack_type=stack_info["stack_type"],
                    stack_status=details["stack_status"],
                    region=self.region,
                    created_time=created_time,
                    last_updated_time=last_updated_time,
                    outputs=details.get("outputs", {}),
                    tags=details.get("tags", {}),
                ))
            
            # Determine status and missing stacks
            status, missing = self._determine_capability_status(
                discovered_stacks, stack_types_found
            )
            
            # Extract URLs from outputs
            frontend_url = None
            backend_url = None
            version = None
            
            for stack in discovered_stacks:
                # Frontend URLs
                if "CloudFrontURL" in stack.outputs:
                    frontend_url = stack.outputs["CloudFrontURL"]
                if "FrontendURL" in stack.outputs:
                    frontend_url = stack.outputs["FrontendURL"]
                if "WebsiteURL" in stack.outputs:
                    frontend_url = stack.outputs["WebsiteURL"]
                
                # Backend URLs
                if "BackendURL" in stack.outputs:
                    backend_url = stack.outputs["BackendURL"]
                if "ALBDNSName" in stack.outputs:
                    backend_url = stack.outputs["ALBDNSName"]
                if "ApiEndpoint" in stack.outputs:
                    backend_url = stack.outputs["ApiEndpoint"]
            
            # Try to get version from tags
            for stack_info in stack_list:
                tags = stack_info["stack_details"].get("tags", {})
                if "Version" in tags:
                    version = tags["Version"]
                    break
                if "version" in tags:
                    version = tags["version"]
                    break
                if "CapabilityVersion" in tags:
                    version = tags["CapabilityVersion"]
                    break
            
            capabilities.append(DiscoveredCapability(
                capability_name=capability_name,
                environment=environment,
                landing_zone_id=landing_zone_id,
                account_id=account_id,
                primary_region=self.region,
                status=status,
                stacks=discovered_stacks,
                missing_stacks=missing,
                discovered_at=datetime.utcnow(),
                version=version,
                frontend_url=frontend_url,
                backend_url=backend_url,
            ))
        
        return capabilities
    
    def _determine_capability_status(
        self,
        stacks: List[DiscoveredStack],
        stack_types_found: Set[str],
    ) -> Tuple[CapabilityStatus, List[str]]:
        """
        Determine overall capability status from stack statuses.
        
        Priority: FAILED > IN_PROGRESS > PARTIAL > HEALTHY
        
        Args:
            stacks: List of discovered stacks
            stack_types_found: Set of stack types that were found
            
        Returns:
            Tuple of (status, missing_stack_types)
        """
        # Check for failures first (highest priority)
        for stack in stacks:
            if "FAILED" in stack.stack_status or "ROLLBACK" in stack.stack_status:
                return CapabilityStatus.FAILED, []
        
        # Check for in-progress operations
        for stack in stacks:
            if "IN_PROGRESS" in stack.stack_status:
                return CapabilityStatus.IN_PROGRESS, []
        
        # Determine expected stacks based on what's deployed
        has_frontend = any(st in stack_types_found for st in FRONTEND_STACK_TYPES)
        has_backend = any(st in stack_types_found for st in BACKEND_STACK_TYPES)
        
        expected_types: Set[str] = set()
        if has_frontend:
            expected_types.update(FRONTEND_STACK_TYPES)
        if has_backend:
            expected_types.update(BACKEND_STACK_TYPES)
        
        # Check for missing stacks
        missing = sorted(list(expected_types - stack_types_found))
        
        if missing:
            return CapabilityStatus.PARTIAL, missing
        
        return CapabilityStatus.HEALTHY, []
