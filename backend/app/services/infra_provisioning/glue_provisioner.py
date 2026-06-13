"""
Glue Provisioner for call-processing capability.

Creates and manages Glue resources:
- Analytics database: call-processing-{env}-analytics

NOTE: The historical wxcc_calls table was removed when call processing
was retired as a feature. The Glue *database* is still provisioned in
case future features add their own Glue tables to it.
"""

import logging
from datetime import datetime
from typing import List, Optional, Callable

import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

from .models import (
    ResourceType,
    ResourceStatus,
    ResourceStatusType,
    get_environment_config,
)
from .naming import ResourceNaming

logger = logging.getLogger(__name__)


class GlueProvisioner:
    """Provisions the Glue analytics database for call-processing capability."""

    def __init__(
        self,
        environment: str,
        region: str,
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        boto3_session: Optional['boto3.Session'] = None,
    ):
        """
        Initialize the Glue provisioner.

        Args:
            environment: Target environment (dev, stage, test, prod)
            region: AWS region
            endpoint_url: Optional endpoint URL for LocalStack
            progress_callback: Optional callback for real-time progress updates
            boto3_session: Optional boto3 session with fresh credentials
        """
        self.environment = environment
        self.region = region
        self.endpoint_url = endpoint_url
        self.naming = ResourceNaming(environment)
        self.config = get_environment_config(environment)
        self.progress_callback = progress_callback

        client_kwargs = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        merged = merge_vpc_boto3_kwargs("glue", region, dict(client_kwargs))
        if boto3_session:
            self.client = boto3_session.client("glue", **merged)
        else:
            self.client = boto3.client("glue", **merged)

    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)

    def provision_all(self) -> List[ResourceStatus]:
        """Provision the Glue analytics database."""
        self._log_progress(f"  > Creating Glue database: {self.naming.glue_database()}")
        return [self.create_database()]

    def create_database(self) -> ResourceStatus:
        """
        Create the analytics database.

        Database: call-processing-{env}-analytics
        """
        database_name = self.naming.glue_database()

        if self.database_exists(database_name):
            self._log_progress(f"    [OK] Database {database_name} already exists")
            return ResourceStatus(
                resource_type=ResourceType.GLUE_DATABASE,
                resource_name=database_name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Database {database_name} already exists",
            )

        try:
            self._log_progress(f"    Creating database {database_name}...")

            self.client.create_database(
                DatabaseInput={
                    "Name": database_name,
                    "Description": f"Analytics database for call-processing capability ({self.environment})",
                }
            )

            self._log_progress(f"    [OK] Database {database_name} created successfully")
            return ResourceStatus(
                resource_type=ResourceType.GLUE_DATABASE,
                resource_name=database_name,
                status=ResourceStatusType.CREATED,
                message=f"Database {database_name} created successfully",
                created_at=datetime.utcnow(),
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"Failed to create database {database_name}: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.GLUE_DATABASE,
                resource_name=database_name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create database: {error_msg}",
                error=error_code,
            )

    def database_exists(self, database_name: str) -> bool:
        """Check if database exists."""
        try:
            self.client.get_database(Name=database_name)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                return False
            raise
