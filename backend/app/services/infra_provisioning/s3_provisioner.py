"""
S3 Provisioner for call-processing capability.

Creates and manages S3 buckets with proper folder structures:
- call-data: Processed call data for Glue tables
- wxcc-simulator: WXCC simulator data
- journey-logs: Journey execution logs
- journey-reports: Journey reports and artifacts
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
    EnvironmentConfig,
    get_environment_config,
)
from .naming import ResourceNaming

logger = logging.getLogger(__name__)


class S3Provisioner:
    """Provisions S3 buckets for call-processing capability."""
    
    def __init__(
        self,
        environment: str,
        region: str,
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        boto3_session: Optional['boto3.Session'] = None,
    ):
        """
        Initialize the S3 provisioner.
        
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
        
        merged = merge_vpc_boto3_kwargs("s3", region, dict(client_kwargs))
        # Use provided session or create new one
        if boto3_session:
            self.client = boto3_session.client("s3", **merged)
        else:
            self.client = boto3.client("s3", **merged)
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def provision_all(self) -> List[ResourceStatus]:
        """
        Provision all S3 buckets.
        
        Returns:
            List of ResourceStatus for each bucket
        """
        results = []
        self._log_progress(f"  Creating 4 S3 buckets...")
        self._log_progress(f"  [1/4] call-data bucket")
        results.append(self.create_call_data_bucket())
        self._log_progress(f"  [2/4] wxcc-simulator bucket")
        results.append(self.create_wxcc_simulator_bucket())
        self._log_progress(f"  [3/4] journey-logs bucket")
        results.append(self.create_journey_logs_bucket())
        self._log_progress(f"  [4/4] journey-reports bucket")
        results.append(self.create_journey_reports_bucket())
        return results
    
    def create_call_data_bucket(self) -> ResourceStatus:
        """
        Create the call-data bucket with folder structure.
        
        Bucket: call-processing-{env}-call-data
        Folders: call-data/, call-detail/, recordings/, transcripts/, athena-results/
        
        Returns:
            ResourceStatus indicating success or failure
        """
        bucket_name = self.naming.call_data_bucket()
        folders = self.naming.call_data_folders()
        
        return self._create_bucket_with_folders(bucket_name, folders)
    
    def create_wxcc_simulator_bucket(self) -> ResourceStatus:
        """
        Create the WXCC simulator bucket with folder structure.
        
        Bucket: call-processing-{env}-wxcc-simulator
        Folders: wxcc-simulator/tasks/, wxcc-simulator/recordings/, 
                 wxcc-simulator/sample-recordings/
        
        Returns:
            ResourceStatus indicating success or failure
        """
        bucket_name = self.naming.wxcc_simulator_bucket()
        folders = self.naming.wxcc_simulator_folders()
        
        return self._create_bucket_with_folders(bucket_name, folders)
    
    def create_journey_logs_bucket(self) -> ResourceStatus:
        """
        Create the journey logs bucket.
        
        Bucket: call-processing-{env}-journey-logs
        
        Returns:
            ResourceStatus indicating success or failure
        """
        bucket_name = self.naming.journey_logs_bucket()
        return self._create_bucket_with_folders(bucket_name, [])
    
    def create_journey_reports_bucket(self) -> ResourceStatus:
        """
        Create the journey reports bucket.
        
        Bucket: call-processing-{env}-journey-reports
        
        Returns:
            ResourceStatus indicating success or failure
        """
        bucket_name = self.naming.journey_reports_bucket()
        return self._create_bucket_with_folders(bucket_name, [])
    
    def _create_bucket_with_folders(
        self, 
        bucket_name: str, 
        folders: List[str]
    ) -> ResourceStatus:
        """
        Create a bucket with optional folder structure.
        
        Args:
            bucket_name: Name of the bucket to create
            folders: List of folder paths to create
            
        Returns:
            ResourceStatus indicating success or failure
        """
        if self.bucket_exists(bucket_name):
            self._log_progress(f"  [OK] Bucket {bucket_name} already exists")
            return ResourceStatus(
                resource_type=ResourceType.S3_BUCKET,
                resource_name=bucket_name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Bucket {bucket_name} already exists",
            )
        
        try:
            self._log_progress(f"  > Creating bucket: {bucket_name}")
            
            # Create bucket with location constraint for non-us-east-1 regions
            create_params = {"Bucket": bucket_name}
            if self.region != "us-east-1":
                create_params["CreateBucketConfiguration"] = {
                    "LocationConstraint": self.region
                }
            
            self.client.create_bucket(**create_params)
            
            # Enable encryption if configured
            if self.config.s3_encryption_enabled:
                self._log_progress(f"    Enabling encryption...")
                self._enable_encryption(bucket_name)
            
            # Enable versioning if configured
            if self.config.s3_versioning_enabled:
                self._log_progress(f"    Enabling versioning...")
                self._enable_versioning(bucket_name)
            
            # Create folder structure
            if folders:
                self._log_progress(f"    Creating {len(folders)} folders...")
                self.create_folder_structure(bucket_name, folders)
            
            self._log_progress(f"  [OK] Bucket {bucket_name} created successfully")
            return ResourceStatus(
                resource_type=ResourceType.S3_BUCKET,
                resource_name=bucket_name,
                status=ResourceStatusType.CREATED,
                message=f"Bucket {bucket_name} created successfully",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"  [X] Failed to create bucket {bucket_name}: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.S3_BUCKET,
                resource_name=bucket_name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create bucket: {error_msg}",
                error=error_code,
            )

    def bucket_exists(self, bucket_name: str) -> bool:
        """
        Check if a bucket already exists.
        
        Args:
            bucket_name: Name of the bucket to check
            
        Returns:
            True if bucket exists, False otherwise
        """
        try:
            self.client.head_bucket(Bucket=bucket_name)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket"):
                return False
            # For 403 (access denied), the bucket exists but we can't access it
            if error_code == "403":
                return True
            raise
    
    def create_folder_structure(self, bucket_name: str, folders: List[str]) -> None:
        """
        Create folder structure in bucket using empty objects.
        
        Args:
            bucket_name: Name of the bucket
            folders: List of folder paths (must end with /)
        """
        for folder in folders:
            # Ensure folder path ends with /
            if not folder.endswith("/"):
                folder = folder + "/"
            
            try:
                self.client.put_object(
                    Bucket=bucket_name,
                    Key=folder,
                    Body=b"",
                )
                logger.debug(f"Created folder {folder} in bucket {bucket_name}")
            except ClientError as e:
                logger.warning(
                    f"Failed to create folder {folder} in bucket {bucket_name}: {e}"
                )
    
    def _enable_encryption(self, bucket_name: str) -> None:
        """
        Enable server-side encryption on a bucket.
        
        Args:
            bucket_name: Name of the bucket
        """
        try:
            self.client.put_bucket_encryption(
                Bucket=bucket_name,
                ServerSideEncryptionConfiguration={
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "AES256"
                            },
                            "BucketKeyEnabled": True,
                        }
                    ]
                },
            )
            logger.debug(f"Enabled encryption on bucket {bucket_name}")
        except ClientError as e:
            logger.warning(f"Failed to enable encryption on bucket {bucket_name}: {e}")
    
    def _enable_versioning(self, bucket_name: str) -> None:
        """
        Enable versioning on a bucket.
        
        Args:
            bucket_name: Name of the bucket
        """
        try:
            self.client.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"},
            )
            logger.debug(f"Enabled versioning on bucket {bucket_name}")
        except ClientError as e:
            logger.warning(f"Failed to enable versioning on bucket {bucket_name}: {e}")
    
    def verify_folder_structure(self, bucket_name: str, folders: List[str]) -> bool:
        """
        Verify that folder structure exists in bucket.
        
        Args:
            bucket_name: Name of the bucket
            folders: List of folder paths to verify
            
        Returns:
            True if all folders exist, False otherwise
        """
        for folder in folders:
            if not folder.endswith("/"):
                folder = folder + "/"
            
            try:
                response = self.client.list_objects_v2(
                    Bucket=bucket_name,
                    Prefix=folder,
                    MaxKeys=1,
                )
                # Check if the folder marker exists or if there are objects with this prefix
                if response.get("KeyCount", 0) == 0:
                    return False
            except ClientError:
                return False
        
        return True
