#!/usr/bin/env python3
"""Bootstrap local AWS emulation resources (standalone — no operator package required)."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError


def _sanitize(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]", "-", name.lower())
    return re.sub(r"-+", "-", s).strip("-")


class LocalNaming:
    def __init__(self, capability: str, environment: str, account_id: Optional[str] = None):
        self.capability_name = _sanitize(capability)
        self.environment = _sanitize(environment)
        self.account_id = account_id

    def dynamodb_table(self, purpose: str) -> str:
        return f"{self.capability_name}-{self.environment}-{purpose}"

    def s3_bucket(self, purpose: str) -> str:
        base = f"{self.capability_name}-{self.environment}-{purpose}"
        return f"{base}-{self.account_id}" if self.account_id else base

    def glue_database(self) -> str:
        return f"{self.capability_name}_{self.environment}_db".replace("-", "_")

    def mimir_blocks_bucket(self) -> str:
        return self.s3_bucket("mimir-blocks")


# Minimal schemas aligned with operator DynamoDBProvisioner (PK/SK tables).
TABLE_SCHEMAS: Dict[str, Dict[str, Any]] = {
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
        "GlobalSecondaryIndexes": [{
            "IndexName": "GSI1",
            "KeySchema": [
                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
    },
    "license": {
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
    },
    "sessions": {
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "PK", "AttributeType": "S"}],
    },
    "audit-log": {
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
    },
    "foundry-workspace": {
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
    },
    "control-plane-audit": {
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
    },
    "rbac": {
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "PK", "AttributeType": "S"}],
    },
    "diagnostics": {
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "PK", "AttributeType": "S"}],
    },
    "health": {
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "PK", "AttributeType": "S"}],
    },
}


def _client(service: str, endpoint: str, region: str):
    return boto3.client(
        service,
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


def _ensure_bucket(s3, name: str) -> None:
    try:
        s3.head_bucket(Bucket=name)
        print(f"  bucket exists: {name}")
    except ClientError:
        s3.create_bucket(Bucket=name)
        print(f"  bucket created: {name}")


def _ensure_dynamodb_table(ddb, table_name: str, schema: Dict[str, Any]) -> None:
    api = dict(schema)
    api["BillingMode"] = "PAY_PER_REQUEST"
    try:
        ddb.describe_table(TableName=table_name)
        print(f"  ddb table exists: {table_name}")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    ddb.create_table(TableName=table_name, **api)
    for _ in range(30):
        if ddb.describe_table(TableName=table_name)["Table"]["TableStatus"] == "ACTIVE":
            break
        time.sleep(2)
    print(f"  ddb table created: {table_name}")


def _ensure_glue_database(glue, db_name: str) -> None:
    try:
        glue.get_database(Name=db_name)
        print(f"  glue database exists: {db_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityNotFoundException":
            raise
        glue.create_database(DatabaseInput={"Name": db_name, "Description": "Nexus local dev"})
        print(f"  glue database created: {db_name}")


def bucket_names(naming: LocalNaming) -> List[str]:
    return sorted(set([
        naming.s3_bucket("solution-results"),
        naming.s3_bucket("journey-logs"),
        naming.s3_bucket("journey-reports"),
        naming.s3_bucket("external-simulator"),
        naming.s3_bucket("wxcc-simulator"),
        naming.s3_bucket("sfdc-simulator"),
        naming.s3_bucket("oracle-erp-simulator"),
        naming.s3_bucket("sap-simulator"),
        naming.mimir_blocks_bucket(),
        f"{naming.capability_name}-{naming.environment}-athena-results",
        f"{naming.capability_name}-{naming.environment}-warehouse",
        "warehouse",
        "athena-results",
    ]))


def provision_capability(
    capability: str,
    environment: str,
    account_id: str,
    region: str,
    minio_endpoint: str,
    scylla_endpoint: str,
    ministack_endpoint: str,
) -> None:
    print(f"Provisioning local resources for {capability}/{environment}")
    naming = LocalNaming(capability, environment, account_id=account_id)
    s3 = _client("s3", minio_endpoint, region)
    for b in bucket_names(naming):
        _ensure_bucket(s3, b)
    ddb = _client("dynamodb", scylla_endpoint, region)
    for purpose, schema in TABLE_SCHEMAS.items():
        _ensure_dynamodb_table(ddb, naming.dynamodb_table(purpose), schema)
    glue = _client("glue", ministack_endpoint, region)
    _ensure_glue_database(glue, naming.glue_database())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capabilities", default="ontology,nexus-ai")
    parser.add_argument("--environment", default=os.getenv("INIT_ENVIRONMENT", "local"))
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--account-id", default=os.getenv("LOCAL_AWS_ACCOUNT_ID", "000000000000"))
    parser.add_argument("--minio-endpoint", default=os.getenv("MINIO_ENDPOINT", "http://minio-svc:9000"))
    parser.add_argument("--scylla-endpoint", default=os.getenv("SCYLLA_ENDPOINT", "http://scylla-svc:8000"))
    parser.add_argument("--ministack-endpoint", default=os.getenv("MINISTACK_ENDPOINT", "http://ministack-svc:4566"))
    args = parser.parse_args()
    caps = [c.strip() for c in args.capabilities.split(",") if c.strip()]
    for cap in caps:
        provision_capability(
            cap, args.environment, args.account_id, args.region,
            args.minio_endpoint, args.scylla_endpoint, args.ministack_endpoint,
        )
    print(json.dumps({"capabilities": caps, "environment": args.environment}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
