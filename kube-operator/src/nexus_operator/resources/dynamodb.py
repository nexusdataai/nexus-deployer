"""
DynamoDB Provisioner for creating tables.

Feature: pure-eks-deployment
Requirements: 4.4
"""
import logging
from typing import Dict, List, Optional, Any

from botocore.exceptions import ClientError

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class DynamoDBProvisioner:
    """Provisions DynamoDB tables for Nexus capabilities."""
    
    # Table schemas matching ECS/CloudFormation deployment
    # Backend expects uppercase PK/SK keys and GSI1 on transformation-system
    TABLE_SCHEMAS = {
        "transformation-system": {
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
            "BillingMode": "PAY_PER_REQUEST",
        },
        "license": {
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
            "BillingMode": "PAY_PER_REQUEST",
        },
        "sessions": {
            "KeySchema": [
                {"AttributeName": "session_id", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "session_id", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        "audit-log": {
            "KeySchema": [
                {"AttributeName": "audit_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "audit_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        "foundry-workspace": {
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
            "BillingMode": "PAY_PER_REQUEST",
        },
        "control-plane-audit": {
            # Keys must match AuditLogger._log_item in
            # nexus-backend/src/services/control_plane/audit_logger.py which
            # writes `session_id` (str) and `step` (zero-padded str e.g. "0001").
            "KeySchema": [
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "step", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "step", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        "rbac": {
            "KeySchema": [
                {"AttributeName": "config_key", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "config_key", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
        "diagnostics": {
            # AI-OPs diagnostics history (Phase 1). Scope buckets are the
            # diagnostic route family (e.g. "o2c", "simulators", "react-tools",
            # "automation", "virtual-data", "dashboard", "connector-apis").
            # TTL attr `expires_at` set by writers to 30 days.
            "KeySchema": [
                {"AttributeName": "scope", "KeyType": "HASH"},
                {"AttributeName": "run_id", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "scope", "AttributeType": "S"},
                {"AttributeName": "run_id", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
            # Internal metadata (not a boto3 CreateTable param — stripped before
            # the API call). Triggers a post-create update_time_to_live() call
            # so rows auto-expire instead of accumulating forever.
            "_ttl_attribute": "expires_at",
        },
        "health": {
            # AI Health Central snapshots (Phase 1). Scope is a plane name or
            # "all". TTL attr `expires_at` set by writers to 90 days.
            "KeySchema": [
                {"AttributeName": "scope", "KeyType": "HASH"},
                {"AttributeName": "iso_ts", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "scope", "AttributeType": "S"},
                {"AttributeName": "iso_ts", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "_ttl_attribute": "expires_at",
        },
    }
    
    def __init__(self, naming: ResourceNaming, region: str):
        self.naming = naming
        self.region = region
        self.client = vpc_boto3_client("dynamodb", region_name=region)
    
    async def provision_all(self) -> List[Dict[str, Any]]:
        """Provision all required DynamoDB tables."""
        results = []
        for table_purpose, schema in self.TABLE_SCHEMAS.items():
            table_name = self.naming.dynamodb_table(table_purpose)
            result = await self.create_table(table_name, schema)
            results.append(result)
        return results
    
    async def create_table(self, table_name: str, schema: Dict) -> Dict[str, Any]:
        """Create a single DynamoDB table."""
        # Split boto3 CreateTable params from internal metadata (keys starting
        # with `_`). Currently the only internal key is `_ttl_attribute`, which
        # drives a post-create update_time_to_live() call.
        ttl_attribute = schema.get("_ttl_attribute")
        api_schema = {k: v for k, v in schema.items() if not k.startswith("_")}

        try:
            try:
                desc = self.client.describe_table(TableName=table_name)
                table_arn = desc["Table"]["TableArn"]
                table_status = desc["Table"].get("TableStatus", "")
                if table_status != "ACTIVE":
                    import time
                    for _ in range(6):
                        time.sleep(5)
                        check = self.client.describe_table(TableName=table_name)
                        if check["Table"].get("TableStatus") == "ACTIVE":
                            break
                try:
                    self.client.tag_resource(ResourceArn=table_arn, Tags=self.naming.aws_tags())
                except Exception:
                    pass
                if ttl_attribute:
                    self._ensure_ttl(table_name, ttl_attribute)
                logger.info(f"DynamoDB table {table_name} already exists")
                return {"name": table_name, "status": "exists", "type": "DynamoDB"}
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
            
            response = self.client.create_table(TableName=table_name, **api_schema)
            table_arn = response["TableDescription"]["TableArn"]
            try:
                self.client.tag_resource(ResourceArn=table_arn, Tags=self.naming.aws_tags())
            except Exception as tag_err:
                logger.warning(f"Tagging during create failed, retrying after wait: {tag_err}")
                import time
                time.sleep(5)
                try:
                    self.client.tag_resource(ResourceArn=table_arn, Tags=self.naming.aws_tags())
                except Exception:
                    logger.warning(f"Tagging retry also failed for {table_name} — tag manually")
            if ttl_attribute:
                # TTL config requires the table to be ACTIVE. Wait for it.
                try:
                    waiter = self.client.get_waiter("table_exists")
                    waiter.wait(TableName=table_name, WaiterConfig={"Delay": 5, "MaxAttempts": 24})
                except Exception as wait_err:
                    logger.warning(f"table_exists waiter failed for {table_name}: {wait_err}")
                self._ensure_ttl(table_name, ttl_attribute)
            logger.info(f"Created DynamoDB table: {table_name}")
            return {"name": table_name, "status": "created", "type": "DynamoDB"}
            
        except Exception as e:
            logger.error(f"Failed to create table {table_name}: {e}")
            return {"name": table_name, "status": "failed", "error": str(e), "type": "DynamoDB"}

    def _ensure_ttl(self, table_name: str, attribute_name: str) -> None:
        """Enable DynamoDB TTL on ``attribute_name`` for ``table_name`` (idempotent).

        No-op if TTL is already ENABLED/ENABLING with the same attribute. Any
        error is logged and swallowed so a TTL configuration hiccup never
        blocks provisioning.
        """
        try:
            current = self.client.describe_time_to_live(TableName=table_name)
            spec = current.get("TimeToLiveDescription", {}) or {}
            if (
                spec.get("TimeToLiveStatus") in ("ENABLED", "ENABLING")
                and spec.get("AttributeName") == attribute_name
            ):
                return
            self.client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": attribute_name},
            )
            logger.info(f"Enabled TTL on {table_name} (attribute={attribute_name})")
        except ClientError as e:
            logger.warning(f"TTL setup failed for {table_name} ({attribute_name}): {e}")
        except Exception as e:
            logger.warning(f"TTL setup unexpected error for {table_name}: {e}")
    
    async def delete_all(self) -> List[Dict[str, Any]]:
        """Delete all provisioned tables."""
        results = []
        for table_purpose in self.TABLE_SCHEMAS.keys():
            table_name = self.naming.dynamodb_table(table_purpose)
            result = await self.delete_table(table_name)
            results.append(result)
        return results
    
    async def delete_table(self, table_name: str) -> Dict[str, Any]:
        """Delete a DynamoDB table."""
        try:
            self.client.delete_table(TableName=table_name)
            logger.info(f"Deleted DynamoDB table: {table_name}")
            return {"name": table_name, "status": "deleted", "type": "DynamoDB"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return {"name": table_name, "status": "not_found", "type": "DynamoDB"}
            logger.error(f"Failed to delete table {table_name}: {e}")
            return {"name": table_name, "status": "failed", "error": str(e), "type": "DynamoDB"}
