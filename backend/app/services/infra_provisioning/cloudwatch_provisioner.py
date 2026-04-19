"""
CloudWatch Provisioner for call-processing capability.
"""
import logging
from datetime import datetime
from typing import List, Optional, Callable

import boto3
from botocore.exceptions import ClientError

from .models import (
    ResourceType,
    ResourceStatus,
    ResourceStatusType,
    get_environment_config,
)
from .naming import ResourceNaming

logger = logging.getLogger(__name__)


class CloudWatchProvisioner:
    """Provisions CloudWatch log groups for call-processing capability."""
    
    RETENTION_DAYS = {"dev": 30, "test": 30, "stage": 90, "prod": 365}
    
    def __init__(
        self, 
        environment: str, 
        region: str, 
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        boto3_session: Optional['boto3.Session'] = None,
    ):
        self.environment = environment
        self.region = region
        self.endpoint_url = endpoint_url
        self.naming = ResourceNaming(environment)
        self.config = get_environment_config(environment)
        self.progress_callback = progress_callback
        client_kwargs = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        
        # Use provided session or create new one
        if boto3_session:
            self.client = boto3_session.client("logs", **client_kwargs)
        else:
            self.client = boto3.client("logs", **client_kwargs)
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def provision_all(self) -> List[ResourceStatus]:
        return [self.create_log_group()]
    
    def create_log_group(self) -> ResourceStatus:
        log_group_name = self.naming.log_group()
        if self.log_group_exists(log_group_name):
            self._log_progress(f"  [OK] Log group {log_group_name} already exists")
            return ResourceStatus(
                resource_type=ResourceType.CLOUDWATCH_LOG_GROUP,
                resource_name=log_group_name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Log group {log_group_name} already exists",
            )
        try:
            self._log_progress(f"  > Creating log group: {log_group_name}")
            self.client.create_log_group(logGroupName=log_group_name)
            retention_days = self.get_retention_days()
            self.client.put_retention_policy(logGroupName=log_group_name, retentionInDays=retention_days)
            self._log_progress(f"  [OK] Log group created with {retention_days} days retention")
            return ResourceStatus(
                resource_type=ResourceType.CLOUDWATCH_LOG_GROUP,
                resource_name=log_group_name,
                status=ResourceStatusType.CREATED,
                message=f"Log group created with {retention_days} days retention",
                created_at=datetime.utcnow(),
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            return ResourceStatus(
                resource_type=ResourceType.CLOUDWATCH_LOG_GROUP,
                resource_name=log_group_name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create log group: {error_msg}",
                error=error_code,
            )
    
    def log_group_exists(self, log_group_name: str) -> bool:
        try:
            response = self.client.describe_log_groups(logGroupNamePrefix=log_group_name, limit=1)
            for group in response.get("logGroups", []):
                if group["logGroupName"] == log_group_name:
                    return True
            return False
        except ClientError:
            return False
    
    def get_retention_days(self) -> int:
        return self.RETENTION_DAYS.get(self.environment, 30)
