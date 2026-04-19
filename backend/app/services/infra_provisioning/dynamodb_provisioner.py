"""
DynamoDB Provisioner for call-processing capability.

Creates and manages DynamoDB tables with proper schemas and GSIs:
- transformation-system: Journey/Stage/Job state management
- license: License records and audit logs
- wxcc-task-tracking: WXCC task tracking
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, Callable

import boto3
from botocore.exceptions import ClientError

from .models import (
    ResourceType,
    ResourceStatus,
    ResourceStatusType,
    EnvironmentConfig,
    get_environment_config,
)
from .naming import ResourceNaming
from .exceptions import (
    ResourceCreationError,
    ProvisioningTimeoutError,
)

logger = logging.getLogger(__name__)


class DynamoDBProvisioner:
    """Provisions DynamoDB tables for call-processing capability."""
    
    def __init__(
        self,
        environment: str,
        region: str,
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        boto3_session: Optional['boto3.Session'] = None,
    ):
        """
        Initialize the DynamoDB provisioner.
        
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
        
        # Initialize boto3 client
        client_kwargs = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        
        # Use provided session or create new one
        if boto3_session:
            self.client = boto3_session.client("dynamodb", **client_kwargs)
        else:
            self.client = boto3.client("dynamodb", **client_kwargs)
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def provision_all(self) -> List[ResourceStatus]:
        """
        Provision all DynamoDB tables.
        
        Returns:
            List of ResourceStatus for each table
        """
        results = []
        self._log_progress(f"  Creating 3 DynamoDB tables...")
        self._log_progress(f"  [1/3] transformation-system table")
        results.append(self.create_transformation_system_table())
        self._log_progress(f"  [2/3] license table")
        results.append(self.create_license_table())
        self._log_progress(f"  [3/3] wxcc-task-tracking table")
        results.append(self.create_wxcc_task_tracking_table())
        return results
    
    def create_transformation_system_table(self) -> ResourceStatus:
        """
        Create the transformation-system table.
        
        Table: call-processing-{env}-transformation-system
        Key Schema: PK (HASH), SK (RANGE)
        GSI: GSI1 (GSI1PK, GSI1SK)
        
        Returns:
            ResourceStatus indicating success or failure
        """
        table_name = self.naming.transformation_system_table()
        
        if self.table_exists(table_name):
            self._log_progress(f"  [OK] Table {table_name} already exists")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Table {table_name} already exists",
            )
        
        try:
            self._log_progress(f"  > Creating table: {table_name}")
            self._log_progress(f"    Key Schema: PK (HASH), SK (RANGE)")
            self._log_progress(f"    GSI: GSI1 (GSI1PK, GSI1SK)")
            self._log_progress(f"    Billing Mode: {self.config.dynamodb_billing_mode}")
            
            create_params = {
                "TableName": table_name,
                "KeySchema": [
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "GSI1PK", "AttributeType": "S"},
                    {"AttributeName": "GSI1SK", "AttributeType": "S"},
                ],
                "GlobalSecondaryIndexes": [
                    {
                        "IndexName": "GSI1",
                        "KeySchema": [
                            {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                            {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                "BillingMode": self.config.dynamodb_billing_mode,
            }
            
            # Add provisioned capacity if not PAY_PER_REQUEST
            if self.config.dynamodb_billing_mode == "PROVISIONED":
                create_params["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": self.config.dynamodb_read_capacity or 5,
                    "WriteCapacityUnits": self.config.dynamodb_write_capacity or 5,
                }
                create_params["GlobalSecondaryIndexes"][0]["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": self.config.dynamodb_read_capacity or 5,
                    "WriteCapacityUnits": self.config.dynamodb_write_capacity or 5,
                }
            
            self.client.create_table(**create_params)
            
            # Wait for table to become active
            self._log_progress(f"    [...] Waiting for table to become ACTIVE...")
            self.wait_for_table_active(table_name)
            
            self._log_progress(f"  [OK] Table {table_name} created successfully")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.CREATED,
                message=f"Table {table_name} created successfully",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"  [X] Failed to create table {table_name}: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create table: {error_msg}",
                error=error_code,
            )

    def create_license_table(self) -> ResourceStatus:
        """
        Create the license table.
        
        Table: call-processing-{env}-license
        Key Schema: PK (HASH), SK (RANGE)
        GSIs: status-index, holder-index, license-index
        
        Returns:
            ResourceStatus indicating success or failure
        """
        table_name = self.naming.license_table()
        
        if self.table_exists(table_name):
            self._log_progress(f"  [OK] Table {table_name} already exists")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Table {table_name} already exists",
            )
        
        try:
            self._log_progress(f"  > Creating table: {table_name}")
            self._log_progress(f"    Key Schema: PK (HASH), SK (RANGE)")
            self._log_progress(f"    GSIs: status-index, holder-index, license-index")
            
            create_params = {
                "TableName": table_name,
                "KeySchema": [
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "status", "AttributeType": "S"},
                    {"AttributeName": "holder_id", "AttributeType": "S"},
                    {"AttributeName": "license_id", "AttributeType": "S"},
                ],
                "GlobalSecondaryIndexes": [
                    {
                        "IndexName": "status-index",
                        "KeySchema": [
                            {"AttributeName": "status", "KeyType": "HASH"},
                            {"AttributeName": "SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                    {
                        "IndexName": "holder-index",
                        "KeySchema": [
                            {"AttributeName": "holder_id", "KeyType": "HASH"},
                            {"AttributeName": "SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                    {
                        "IndexName": "license-index",
                        "KeySchema": [
                            {"AttributeName": "license_id", "KeyType": "HASH"},
                            {"AttributeName": "SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                ],
                "BillingMode": self.config.dynamodb_billing_mode,
            }
            
            # Add provisioned capacity if not PAY_PER_REQUEST
            if self.config.dynamodb_billing_mode == "PROVISIONED":
                create_params["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": self.config.dynamodb_read_capacity or 5,
                    "WriteCapacityUnits": self.config.dynamodb_write_capacity or 5,
                }
                for gsi in create_params["GlobalSecondaryIndexes"]:
                    gsi["ProvisionedThroughput"] = {
                        "ReadCapacityUnits": self.config.dynamodb_read_capacity or 5,
                        "WriteCapacityUnits": self.config.dynamodb_write_capacity or 5,
                    }
            
            self.client.create_table(**create_params)
            
            # Wait for table to become active
            self._log_progress(f"    [...] Waiting for table to become ACTIVE...")
            self.wait_for_table_active(table_name)
            
            self._log_progress(f"  [OK] Table {table_name} created successfully")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.CREATED,
                message=f"Table {table_name} created successfully",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"  [X] Failed to create table {table_name}: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create table: {error_msg}",
                error=error_code,
            )
    
    def create_wxcc_task_tracking_table(self) -> ResourceStatus:
        """
        Create the WXCC task tracking table.
        
        Table: call-processing-{env}-wxcc-task-tracking
        Key Schema: task_id (HASH)
        
        Returns:
            ResourceStatus indicating success or failure
        """
        table_name = self.naming.wxcc_task_tracking_table()
        
        if self.table_exists(table_name):
            self._log_progress(f"  [OK] Table {table_name} already exists")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Table {table_name} already exists",
            )
        
        try:
            self._log_progress(f"  > Creating table: {table_name}")
            self._log_progress(f"    Key Schema: task_id (HASH)")
            
            create_params = {
                "TableName": table_name,
                "KeySchema": [
                    {"AttributeName": "task_id", "KeyType": "HASH"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": "task_id", "AttributeType": "S"},
                ],
                "BillingMode": self.config.dynamodb_billing_mode,
            }
            
            # Add provisioned capacity if not PAY_PER_REQUEST
            if self.config.dynamodb_billing_mode == "PROVISIONED":
                create_params["ProvisionedThroughput"] = {
                    "ReadCapacityUnits": self.config.dynamodb_read_capacity or 5,
                    "WriteCapacityUnits": self.config.dynamodb_write_capacity or 5,
                }
            
            self.client.create_table(**create_params)
            
            # Wait for table to become active
            self._log_progress(f"    [...] Waiting for table to become ACTIVE...")
            self.wait_for_table_active(table_name)
            
            self._log_progress(f"  [OK] Table {table_name} created successfully")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.CREATED,
                message=f"Table {table_name} created successfully",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"  [X] Failed to create table {table_name}: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create table: {error_msg}",
                error=error_code,
            )
    
    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table already exists.
        
        Args:
            table_name: Name of the table to check
            
        Returns:
            True if table exists, False otherwise
        """
        try:
            self.client.describe_table(TableName=table_name)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return False
            raise
    
    def wait_for_table_active(self, table_name: str, timeout: int = 300) -> bool:
        """
        Wait for table to become ACTIVE.
        
        Args:
            table_name: Name of the table to wait for
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if table became active
            
        Raises:
            ProvisioningTimeoutError: If table doesn't become active in time
        """
        start_time = time.time()
        last_status = None
        poll_count = 0
        
        while time.time() - start_time < timeout:
            try:
                response = self.client.describe_table(TableName=table_name)
                status = response["Table"]["TableStatus"]
                
                if status == "ACTIVE":
                    elapsed = int(time.time() - start_time)
                    self._log_progress(f"    [OK] Table is now ACTIVE (took {elapsed}s)")
                    return True
                
                # Log status changes
                if status != last_status:
                    self._log_progress(f"    Status: {status}...")
                    last_status = status
                
                # Log periodic updates every 10 polls (20 seconds)
                poll_count += 1
                if poll_count % 10 == 0:
                    elapsed = int(time.time() - start_time)
                    self._log_progress(f"    Still waiting... ({elapsed}s elapsed)")
                
                time.sleep(2)
                
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                    logger.debug(f"Table {table_name} not found yet, waiting...")
                    time.sleep(2)
                else:
                    raise
        
        raise ProvisioningTimeoutError(
            resource_type=ResourceType.DYNAMODB_TABLE,
            resource_name=table_name,
            expected_state="ACTIVE",
            timeout_seconds=timeout,
        )
    
    def get_table_status(self, table_name: str) -> Optional[str]:
        """
        Get the current status of a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            Table status string or None if table doesn't exist
        """
        try:
            response = self.client.describe_table(TableName=table_name)
            return response["Table"]["TableStatus"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return None
            raise
