"""
S3 Provisioner for creating buckets.

Feature: pure-eks-deployment
Requirements: 4.4
"""
import logging
from typing import Dict, List, Any

from botocore.exceptions import ClientError

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class S3Provisioner:
    """Provisions S3 buckets for Totogi capabilities."""
    
    BUCKET_PURPOSES = ["call-data", "wxcc-simulator", "sfdc-simulator", "journey-logs", "journey-reports", "bssmagic-dumps"]
    
    def __init__(self, naming: ResourceNaming, region: str):
        self.naming = naming
        self.region = region
        self.client = vpc_boto3_client("s3", region_name=region)
    
    async def provision_all(self) -> List[Dict[str, Any]]:
        """Provision all required S3 buckets."""
        results = []
        for purpose in self.BUCKET_PURPOSES:
            bucket_name = self.naming.s3_bucket(purpose)
            result = await self.create_bucket(bucket_name)
            results.append(result)
        return results
    
    async def create_bucket(self, bucket_name: str) -> Dict[str, Any]:
        """Create a single S3 bucket."""
        try:
            # Check if bucket exists and is accessible
            try:
                self.client.head_bucket(Bucket=bucket_name)
                try:
                    self.client.put_bucket_tagging(Bucket=bucket_name, Tagging={"TagSet": self.naming.aws_tags()})
                except Exception:
                    pass
                logger.info(f"S3 bucket {bucket_name} already exists")
                return {"name": bucket_name, "status": "exists", "type": "S3"}
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code == "403":
                    logger.warning(f"S3 bucket {bucket_name} exists but is owned by another account")
                    return {"name": bucket_name, "status": "failed", "error": "Bucket exists in another account", "type": "S3"}
                if error_code != "404":
                    raise
            
            # Create bucket with region-specific config
            create_params = {"Bucket": bucket_name}
            if self.region != "us-east-1":
                create_params["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            
            self.client.create_bucket(**create_params)
            
            # Enable versioning
            self.client.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={"Status": "Enabled"}
            )
            
            # Apply standard tags
            self.client.put_bucket_tagging(
                Bucket=bucket_name,
                Tagging={"TagSet": self.naming.aws_tags()}
            )
            
            logger.info(f"Created S3 bucket: {bucket_name}")
            return {"name": bucket_name, "status": "created", "type": "S3"}
            
        except Exception as e:
            logger.error(f"Failed to create bucket {bucket_name}: {e}")
            return {"name": bucket_name, "status": "failed", "error": str(e), "type": "S3"}
    
    async def delete_all(self) -> List[Dict[str, Any]]:
        """Delete all provisioned buckets."""
        results = []
        for purpose in self.BUCKET_PURPOSES:
            bucket_name = self.naming.s3_bucket(purpose)
            result = await self.delete_bucket(bucket_name)
            results.append(result)
        return results
    
    async def delete_bucket(self, bucket_name: str) -> Dict[str, Any]:
        """Delete an S3 bucket (must be empty)."""
        try:
            self.client.delete_bucket(Bucket=bucket_name)
            logger.info(f"Deleted S3 bucket: {bucket_name}")
            return {"name": bucket_name, "status": "deleted", "type": "S3"}
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchBucket":
                return {"name": bucket_name, "status": "not_found", "type": "S3"}
            logger.error(f"Failed to delete bucket {bucket_name}: {e}")
            return {"name": bucket_name, "status": "failed", "error": str(e), "type": "S3"}
