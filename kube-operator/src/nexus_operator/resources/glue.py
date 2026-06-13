"""
Glue Provisioner for creating databases.

Feature: pure-eks-deployment
Requirements: 4.4

NOTE: The historical `call_records` table + Athena `primary` workgroup
output configuration was removed when call processing was retired as a
feature. The Glue *database* is still provisioned in case future
features add their own Glue tables to it.
"""
import logging
from typing import Dict, List, Any

from botocore.exceptions import ClientError

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class GlueProvisioner:
    """Provisions an AWS Glue database for Nexus capabilities."""

    def __init__(self, naming: ResourceNaming, region: str):
        self.naming = naming
        self.region = region
        self.client = vpc_boto3_client("glue", region_name=region)

    async def provision_all(self) -> List[Dict[str, Any]]:
        """Provision the capability's Glue database."""
        return [await self.create_database()]

    async def create_database(self) -> Dict[str, Any]:
        """Create the Glue database."""
        database_name = self.naming.glue_database()

        try:
            try:
                self.client.get_database(Name=database_name)
                logger.info(f"Glue database {database_name} already exists")
                return {"name": database_name, "status": "exists", "type": "GlueDatabase"}
            except ClientError as e:
                if e.response["Error"]["Code"] != "EntityNotFoundException":
                    raise

            self.client.create_database(
                DatabaseInput={
                    "Name": database_name,
                    "Description": f"Glue database for {self.naming.capability_name} ({self.naming.environment})",
                }
            )
            try:
                account_id = vpc_boto3_client("sts", region_name=self.region).get_caller_identity()["Account"]
                db_arn = f"arn:aws:glue:{self.region}:{account_id}:database/{database_name}"
                self.client.tag_resource(ResourceArn=db_arn, TagsToAdd=self.naming.aws_tags_dict())
            except Exception as tag_err:
                logger.warning(f"Failed to tag Glue database (non-fatal): {tag_err}")
            logger.info(f"Created Glue database: {database_name}")
            return {"name": database_name, "status": "created", "type": "GlueDatabase"}

        except Exception as e:
            logger.error(f"Failed to create Glue database {database_name}: {e}")
            return {"name": database_name, "status": "failed", "error": str(e), "type": "GlueDatabase"}

    async def delete_all(self) -> List[Dict[str, Any]]:
        """Delete the capability's Glue database (and any tables left in it)."""
        database_name = self.naming.glue_database()
        results: List[Dict[str, Any]] = []

        # Best-effort: delete any leftover tables (e.g. historical call_records
        # in long-lived clusters) before dropping the database.
        try:
            paginator = self.client.get_paginator("get_tables")
            for page in paginator.paginate(DatabaseName=database_name):
                for tbl in page.get("TableList", []):
                    tbl_name = tbl["Name"]
                    try:
                        self.client.delete_table(DatabaseName=database_name, Name=tbl_name)
                        results.append({"name": tbl_name, "database": database_name, "status": "deleted", "type": "GlueTable"})
                        logger.info(f"Deleted leftover Glue table: {tbl_name}")
                    except ClientError as e:
                        logger.warning(f"Failed to delete Glue table {tbl_name}: {e}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "EntityNotFoundException":
                logger.warning(f"Glue table cleanup non-fatal error: {e}")

        results.append(await self.delete_database(database_name))
        return results

    async def delete_database(self, database_name: str) -> Dict[str, Any]:
        """Delete the Glue database."""
        try:
            self.client.delete_database(Name=database_name)
            logger.info(f"Deleted Glue database: {database_name}")
            return {"name": database_name, "status": "deleted", "type": "GlueDatabase"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "EntityNotFoundException":
                return {"name": database_name, "status": "not_found", "type": "GlueDatabase"}
            logger.error(f"Failed to delete Glue database {database_name}: {e}")
            return {"name": database_name, "status": "failed", "error": str(e), "type": "GlueDatabase"}
