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
        try:
            # Check if table exists
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
                logger.info(f"DynamoDB table {table_name} already exists")
                return {"name": table_name, "status": "exists", "type": "DynamoDB"}
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
            
            # Create table
            response = self.client.create_table(TableName=table_name, **schema)
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
            logger.info(f"Created DynamoDB table: {table_name}")
            return {"name": table_name, "status": "created", "type": "DynamoDB"}
            
        except Exception as e:
            logger.error(f"Failed to create table {table_name}: {e}")
            return {"name": table_name, "status": "failed", "error": str(e), "type": "DynamoDB"}
    
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
