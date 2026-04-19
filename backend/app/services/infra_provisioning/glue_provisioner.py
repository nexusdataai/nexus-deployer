"""
Glue Provisioner for call-processing capability.

Creates and manages Glue resources:
- Analytics database: call-processing-{env}-analytics
- wxcc_calls table: JSON format with year/month/day/hour partitioning

IMPORTANT: The table uses JSON format (not Parquet) with JsonSerDe
because call data is written as JSON files to S3.
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


class GlueProvisioner:
    """Provisions Glue database and tables for call-processing capability."""
    
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
        
        # Initialize boto3 client
        client_kwargs = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        
        # Use provided session or create new one
        if boto3_session:
            self.client = boto3_session.client("glue", **client_kwargs)
        else:
            self.client = boto3.client("glue", **client_kwargs)
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def provision_all(self) -> List[ResourceStatus]:
        """
        Provision all Glue resources.
        
        Returns:
            List of ResourceStatus for each resource
        """
        results = []
        self._log_progress(f"  > Creating Glue database: {self.naming.glue_database()}")
        results.append(self.create_database())
        self._log_progress(f"  > Creating Glue table: {self.naming.glue_table()}")
        results.append(self.create_wxcc_calls_table())
        return results
    
    def create_database(self) -> ResourceStatus:
        """
        Create the analytics database.
        
        Database: call-processing-{env}-analytics
        
        Returns:
            ResourceStatus indicating success or failure
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
    
    def create_wxcc_calls_table(self) -> ResourceStatus:
        """
        Create the wxcc_calls table.
        
        Table: wxcc_calls
        Location: s3://call-processing-{env}-call-data/call-data/
        Format: JSON (using JsonSerDe)
        Partitions: year, month, day, hour
        
        Returns:
            ResourceStatus indicating success or failure
        """
        database_name = self.naming.glue_database()
        table_name = self.naming.glue_table()
        
        if self.table_exists(database_name, table_name):
            self._log_progress(f"    [OK] Table {table_name} already exists in {database_name}")
            return ResourceStatus(
                resource_type=ResourceType.GLUE_TABLE,
                resource_name=f"{database_name}.{table_name}",
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Table {table_name} already exists",
            )
        
        try:
            self._log_progress(f"    Creating table {table_name} in {database_name}...")
            self._log_progress(f"      Location: {self.naming.glue_table_location()}")
            self._log_progress(f"      Format: JSON (JsonSerDe)")
            self._log_progress(f"      Partitions: year, month, day, hour")
            
            self.client.create_table(
                DatabaseName=database_name,
                TableInput={
                    "Name": table_name,
                    "Description": "WXCC call data for analytics - recordings, transcripts, and metadata",
                    "StorageDescriptor": {
                        "Columns": self._get_wxcc_calls_columns(),
                        "Location": self.naming.glue_table_location(),
                        "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                        "SerdeInfo": {
                            "SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe",
                            "Parameters": {
                                "serialization.format": "1",
                                "ignore.malformed.json": "true",
                                "case.insensitive": "true",
                            },
                        },
                        "Compressed": False,
                    },
                    "PartitionKeys": [
                        {"Name": "year", "Type": "string"},
                        {"Name": "month", "Type": "string"},
                        {"Name": "day", "Type": "string"},
                        {"Name": "hour", "Type": "string"},
                    ],
                    "TableType": "EXTERNAL_TABLE",
                    "Parameters": {
                        "classification": "json",
                        "typeOfData": "file",
                        "EXTERNAL": "TRUE",
                    },
                },
            )
            
            self._log_progress(f"    [OK] Table {table_name} created successfully")
            return ResourceStatus(
                resource_type=ResourceType.GLUE_TABLE,
                resource_name=f"{database_name}.{table_name}",
                status=ResourceStatusType.CREATED,
                message=f"Table {table_name} created successfully",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"    [X] Failed to create table {table_name}: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.GLUE_TABLE,
                resource_name=f"{database_name}.{table_name}",
                status=ResourceStatusType.FAILED,
                message=f"Failed to create table: {error_msg}",
                error=error_code,
            )
    
    def _get_wxcc_calls_columns(self) -> List[dict]:
        """
        Get column definitions for wxcc_calls table.
        
        IMPORTANT: These column names must match the JSON structure written by
        the call processor (starhub-backend/src/stages/call-process/call_processor.py).
        
        Returns:
            List of column definitions
        """
        return [
            {"Name": "task_id", "Type": "string", "Comment": "Unique task identifier"},
            {"Name": "org_id", "Type": "string", "Comment": "Organization ID"},
            {"Name": "created_at", "Type": "bigint", "Comment": "Call creation timestamp (epoch ms)"},
            {"Name": "status", "Type": "string", "Comment": "Call status (completed, abandoned, etc.)"},
            {"Name": "direction", "Type": "string", "Comment": "Call direction (inbound, outbound)"},
            {"Name": "origin_phone", "Type": "string", "Comment": "Caller phone number"},
            {"Name": "destination_phone", "Type": "string", "Comment": "Destination phone number"},
            {"Name": "queue_name", "Type": "string", "Comment": "Queue name"},
            {"Name": "queue_id", "Type": "string", "Comment": "Queue ID"},
            {"Name": "agent_name", "Type": "string", "Comment": "Agent name"},
            {"Name": "agent_id", "Type": "string", "Comment": "Agent ID"},
            {"Name": "duration_seconds", "Type": "int", "Comment": "Call duration in seconds"},
            {"Name": "recording_file", "Type": "string", "Comment": "S3 path to recording file"},
            {"Name": "transcript_file", "Type": "string", "Comment": "S3 path to transcript file"},
            {"Name": "analysis_file", "Type": "string", "Comment": "S3 path to AI analysis file"},
            {"Name": "sfdc_action_file", "Type": "string", "Comment": "S3 path to Salesforce action file"},
        ]
    
    def database_exists(self, database_name: str) -> bool:
        """
        Check if database exists.
        
        Args:
            database_name: Name of the database
            
        Returns:
            True if database exists, False otherwise
        """
        try:
            self.client.get_database(Name=database_name)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                return False
            raise
    
    def table_exists(self, database_name: str, table_name: str) -> bool:
        """
        Check if table exists.
        
        Args:
            database_name: Name of the database
            table_name: Name of the table
            
        Returns:
            True if table exists, False otherwise
        """
        try:
            self.client.get_table(DatabaseName=database_name, Name=table_name)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                return False
            raise
