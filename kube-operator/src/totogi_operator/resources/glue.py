"""
Glue Provisioner for creating databases and tables.

Feature: pure-eks-deployment
Requirements: 4.4
"""
import logging
from typing import Dict, List, Any

import boto3
from botocore.exceptions import ClientError

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class GlueProvisioner:
    """Provisions AWS Glue databases and tables for Totogi capabilities."""
    
    # WXCC call records table schema - must match JSON structure written by call processor
    # See: starhub-backend/src/stages/call-process/call_processor.py
    CALL_RECORDS_COLUMNS = [
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
    
    # Hive-style partitions for efficient querying
    PARTITION_KEYS = [
        {"Name": "year", "Type": "string"},
        {"Name": "month", "Type": "string"},
        {"Name": "day", "Type": "string"},
        {"Name": "hour", "Type": "string"},
    ]
    
    def __init__(self, naming: ResourceNaming, region: str):
        self.naming = naming
        self.region = region
        self.client = boto3.client("glue", region_name=region)
        self.athena_client = boto3.client("athena", region_name=region)
        self.s3_client = boto3.client("s3", region_name=region)
    
    async def provision_all(self, s3_location: str = None) -> List[Dict[str, Any]]:
        """
        Provision Glue database and tables.
        
        Args:
            s3_location: S3 location for table data (optional)
        """
        results = []
        
        # Create database
        db_result = await self.create_database()
        results.append(db_result)
        
        if db_result["status"] in ["created", "exists"]:
            # Create call records table
            table_result = await self.create_call_records_table(s3_location)
            results.append(table_result)
            
            # Discover and register existing S3 partitions (from previous deployments)
            if table_result["status"] in ["created", "exists"]:
                await self._discover_partitions()
        
        # Configure Athena workgroup with output location
        await self._configure_athena_output()
        
        return results
    
    async def _configure_athena_output(self):
        """Configure Athena primary workgroup with an output location for query results."""
        try:
            # Use the call-data bucket for Athena results
            bucket = self.naming.call_data_bucket()
            output_location = f"s3://{bucket}/athena-results/"
            
            # Ensure the bucket exists before configuring Athena
            try:
                self.s3_client.head_bucket(Bucket=bucket)
            except ClientError:
                logger.warning(f"S3 bucket {bucket} not accessible, skipping Athena configuration")
                return
            
            # Check current workgroup configuration
            try:
                wg = self.athena_client.get_work_group(WorkGroup="primary")
                current_output = (wg.get("WorkGroup", {})
                                   .get("Configuration", {})
                                   .get("ResultConfiguration", {})
                                   .get("OutputLocation", ""))
                if current_output:
                    logger.info(f"Athena primary workgroup already has output: {current_output}")
                    return
            except ClientError:
                pass
            
            self.athena_client.update_work_group(
                WorkGroup="primary",
                ConfigurationUpdates={
                    "ResultConfigurationUpdates": {
                        "OutputLocation": output_location
                    }
                }
            )
            logger.info(f"Configured Athena output location: {output_location}")
        except Exception as e:
            logger.warning(f"Failed to configure Athena output location: {e}")
    
    async def _discover_partitions(self):
        """Discover and register existing S3 data partitions in the Glue table."""
        database_name = self.naming.glue_database()
        table_name = self.naming.glue_table("call_records")
        bucket = self.naming.call_data_bucket()
        
        try:
            s3 = boto3.client("s3", region_name=self.region)
            
            # Get table storage descriptor for partition template
            table = self.client.get_table(DatabaseName=database_name, Name=table_name)
            sd = table["Table"]["StorageDescriptor"]
            
            # List existing S3 partitions
            paginator = s3.get_paginator("list_objects_v2")
            partitions_seen = set()
            
            for page in paginator.paginate(Bucket=bucket, Prefix="call-data/year="):
                for obj in page.get("Contents", []):
                    parts = obj["Key"].split("/")
                    if len(parts) >= 5:
                        partition_path = "/".join(parts[:5]) + "/"
                        if partition_path not in partitions_seen:
                            partitions_seen.add(partition_path)
            
            if not partitions_seen:
                logger.info("No existing S3 partitions found to register")
                return
            
            # Register each partition
            registered = 0
            for partition_path in partitions_seen:
                parts = partition_path.split("/")
                year = parts[1].split("=")[1]
                month = parts[2].split("=")[1]
                day = parts[3].split("=")[1]
                hour = parts[4].split("=")[1]
                location = f"s3://{bucket}/{partition_path}"
                
                try:
                    psd = sd.copy()
                    psd["Location"] = location
                    psd.pop("Parameters", None)
                    
                    self.client.create_partition(
                        DatabaseName=database_name,
                        TableName=table_name,
                        PartitionInput={
                            "Values": [year, month, day, hour],
                            "StorageDescriptor": psd,
                        },
                    )
                    registered += 1
                except ClientError as e:
                    if e.response["Error"]["Code"] == "AlreadyExistsException":
                        pass  # Partition already registered
                    else:
                        logger.warning(f"Failed to register partition {partition_path}: {e}")
            
            if registered > 0:
                logger.info(f"Registered {registered} existing S3 partitions in Glue table {table_name}")
                
        except Exception as e:
            logger.warning(f"Partition discovery failed (non-fatal): {e}")
    
    async def create_database(self) -> Dict[str, Any]:
        """Create the Glue database."""
        database_name = self.naming.glue_database()
        
        try:
            # Check if database exists
            try:
                self.client.get_database(Name=database_name)
                logger.info(f"Glue database {database_name} already exists")
                return {"name": database_name, "status": "exists", "type": "GlueDatabase"}
            except ClientError as e:
                if e.response["Error"]["Code"] != "EntityNotFoundException":
                    raise
            
            # Create database
            self.client.create_database(
                DatabaseInput={
                    "Name": database_name,
                    "Description": f"Glue database for {self.naming.capability_name} ({self.naming.environment})",
                }
            )
            try:
                account_id = boto3.client("sts", region_name=self.region).get_caller_identity()["Account"]
                db_arn = f"arn:aws:glue:{self.region}:{account_id}:database/{database_name}"
                self.client.tag_resource(ResourceArn=db_arn, TagsToAdd=self.naming.aws_tags_dict())
            except Exception as tag_err:
                logger.warning(f"Failed to tag Glue database (non-fatal): {tag_err}")
            logger.info(f"Created Glue database: {database_name}")
            return {"name": database_name, "status": "created", "type": "GlueDatabase"}
            
        except Exception as e:
            logger.error(f"Failed to create Glue database {database_name}: {e}")
            return {"name": database_name, "status": "failed", "error": str(e), "type": "GlueDatabase"}

    async def create_call_records_table(self, s3_location: str = None) -> Dict[str, Any]:
        """Create the call records table."""
        database_name = self.naming.glue_database()
        table_name = self.naming.glue_table("call_records")
        
        # Default S3 location if not provided
        # Must match the prefix used by the backend's GlueCatalog (call-data/)
        if not s3_location:
            s3_location = f"s3://{self.naming.call_data_bucket()}/call-data/"
        
        try:
            # Check if table exists
            try:
                self.client.get_table(DatabaseName=database_name, Name=table_name)
                logger.info(f"Glue table {table_name} already exists")
                return {"name": table_name, "database": database_name, "status": "exists", "type": "GlueTable"}
            except ClientError as e:
                if e.response["Error"]["Code"] != "EntityNotFoundException":
                    raise
            
            # Create table with JSON format
            self.client.create_table(
                DatabaseName=database_name,
                TableInput={
                    "Name": table_name,
                    "Description": f"WXCC call records for {self.naming.capability_name} - recordings, transcripts, and metadata",
                    "StorageDescriptor": {
                        "Columns": self.CALL_RECORDS_COLUMNS,
                        "Location": s3_location,
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
                    "PartitionKeys": self.PARTITION_KEYS,
                    "TableType": "EXTERNAL_TABLE",
                    "Parameters": {
                        "classification": "json",
                        "typeOfData": "file",
                        "EXTERNAL": "TRUE",
                    },
                }
            )
            try:
                account_id = boto3.client("sts", region_name=self.region).get_caller_identity()["Account"]
                table_arn = f"arn:aws:glue:{self.region}:{account_id}:table/{database_name}/{table_name}"
                self.client.tag_resource(ResourceArn=table_arn, TagsToAdd=self.naming.aws_tags_dict())
            except Exception as tag_err:
                logger.warning(f"Failed to tag Glue table (non-fatal): {tag_err}")
            logger.info(f"Created Glue table: {table_name}")
            return {"name": table_name, "database": database_name, "status": "created", "type": "GlueTable"}
            
        except Exception as e:
            logger.error(f"Failed to create Glue table {table_name}: {e}")
            return {"name": table_name, "database": database_name, "status": "failed", "error": str(e), "type": "GlueTable"}
    
    async def delete_all(self) -> List[Dict[str, Any]]:
        """Delete all provisioned Glue resources."""
        results = []
        
        database_name = self.naming.glue_database()
        table_name = self.naming.glue_table("call_records")
        
        # Delete table first
        table_result = await self.delete_table(database_name, table_name)
        results.append(table_result)
        
        # Then delete database
        db_result = await self.delete_database(database_name)
        results.append(db_result)
        
        return results
    
    async def delete_table(self, database_name: str, table_name: str) -> Dict[str, Any]:
        """Delete a Glue table."""
        try:
            self.client.delete_table(DatabaseName=database_name, Name=table_name)
            logger.info(f"Deleted Glue table: {table_name}")
            return {"name": table_name, "database": database_name, "status": "deleted", "type": "GlueTable"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityNotFoundException":
                return {"name": table_name, "database": database_name, "status": "not_found", "type": "GlueTable"}
            logger.error(f"Failed to delete Glue table {table_name}: {e}")
            return {"name": table_name, "database": database_name, "status": "failed", "error": str(e), "type": "GlueTable"}
    
    async def delete_database(self, database_name: str) -> Dict[str, Any]:
        """Delete a Glue database."""
        try:
            self.client.delete_database(Name=database_name)
            logger.info(f"Deleted Glue database: {database_name}")
            return {"name": database_name, "status": "deleted", "type": "GlueDatabase"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityNotFoundException":
                return {"name": database_name, "status": "not_found", "type": "GlueDatabase"}
            logger.error(f"Failed to delete Glue database {database_name}: {e}")
            return {"name": database_name, "status": "failed", "error": str(e), "type": "GlueDatabase"}
