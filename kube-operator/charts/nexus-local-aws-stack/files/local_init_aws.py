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

    def ai_engine_ssm_parameter(self, key: str) -> str:
        return f"/{self.capability_name}/{self.environment}/{key}"

    def secret_name(self, secret_type: str) -> str:
        return f"{self.capability_name}/{self.environment}/{secret_type}"


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
        "KeySchema": [
            {"AttributeName": "scope", "KeyType": "HASH"},
            {"AttributeName": "run_id", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "scope", "AttributeType": "S"},
            {"AttributeName": "run_id", "AttributeType": "S"},
        ],
    },
    "health": {
        "KeySchema": [
            {"AttributeName": "scope", "KeyType": "HASH"},
            {"AttributeName": "iso_ts", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "scope", "AttributeType": "S"},
            {"AttributeName": "iso_ts", "AttributeType": "S"},
        ],
    },
    # ai-engine tables — source: nexus-ai-engine/adapters/dynamodb/table_definitions.py
    "journeys": {
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
            },
        ],
    },
    "executions": {
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "journey_id", "AttributeType": "S"},
            {"AttributeName": "started_at", "AttributeType": "S"},
            {"AttributeName": "tenant_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "journey_id", "KeyType": "HASH"},
                    {"AttributeName": "started_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "tenant_id", "KeyType": "HASH"},
                    {"AttributeName": "status", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    },
    "prompts": {
        "KeySchema": [
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        "AttributeDefinitions": [
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
    },
}

_ONTOLOGY_TABLES = [
    "transformation-system",
    "license",
    "sessions",
    "audit-log",
    "foundry-workspace",
    "control-plane-audit",
    "rbac",
    "diagnostics",
    "health",
]

CAPABILITY_TABLES: Dict[str, List[str]] = {
    "ontology": _ONTOLOGY_TABLES,
    "nexus-ai": _ONTOLOGY_TABLES,
    "ai-engine": ["journeys", "executions", "prompts"],
}

CAPABILITY_BUCKETS: Dict[str, List[str]] = {
    "ontology": [
        "solution-results",
        "journey-logs",
        "journey-reports",
        "external-simulator",
        "wxcc-simulator",
        "sfdc-simulator",
        "oracle-erp-simulator",
        "sap-simulator",
        "mimir-blocks",
        "athena-results",
        "warehouse",
    ],
    "nexus-ai": [
        "solution-results",
        "journey-logs",
        "journey-reports",
        "external-simulator",
        "wxcc-simulator",
        "sfdc-simulator",
        "oracle-erp-simulator",
        "sap-simulator",
        "mimir-blocks",
        "athena-results",
        "warehouse",
    ],
    "ai-engine": ["journey-logs", "journey-reports"],
}


def _capability_tables(capability: str) -> List[str]:
    cap = _sanitize(capability)
    if cap in CAPABILITY_TABLES:
        return CAPABILITY_TABLES[cap]
    return _ONTOLOGY_TABLES


def _capability_buckets(capability: str, naming: LocalNaming) -> List[str]:
    cap = _sanitize(capability)
    purposes = CAPABILITY_BUCKETS.get(cap, CAPABILITY_BUCKETS["ontology"])
    names: List[str] = []
    for purpose in purposes:
        if purpose in ("warehouse", "athena-results"):
            names.append(purpose)
            continue
        if purpose == "athena-results" and cap != "ai-engine":
            names.append(f"{naming.capability_name}-{naming.environment}-athena-results")
            continue
        if purpose == "warehouse" and cap != "ai-engine":
            names.append(f"{naming.capability_name}-{naming.environment}-warehouse")
            continue
        names.append(naming.s3_bucket(purpose))
    return sorted(set(names))


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


def _schema_fingerprint(schema: Dict[str, Any]) -> tuple:
    keys = tuple((k["AttributeName"], k["KeyType"]) for k in schema["KeySchema"])
    attrs = tuple(sorted(a["AttributeName"] for a in schema["AttributeDefinitions"]))
    gsis = tuple(
        (
            g["IndexName"],
            tuple((k["AttributeName"], k["KeyType"]) for k in g["KeySchema"]),
        )
        for g in schema.get("GlobalSecondaryIndexes", []) or []
    )
    return (keys, attrs, gsis)


def _table_fingerprint(table_desc: Dict[str, Any]) -> tuple:
    table = table_desc["Table"]
    keys = tuple((k["AttributeName"], k["KeyType"]) for k in table["KeySchema"])
    attrs = tuple(sorted(a["AttributeName"] for a in table["AttributeDefinitions"]))
    gsis = tuple(
        (
            g["IndexName"],
            tuple((k["AttributeName"], k["KeyType"]) for k in g["KeySchema"]),
        )
        for g in table.get("GlobalSecondaryIndexes", []) or []
    )
    return (keys, attrs, gsis)


def _wait_table_active(ddb, table_name: str) -> None:
    for _ in range(30):
        if ddb.describe_table(TableName=table_name)["Table"]["TableStatus"] == "ACTIVE":
            return
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for table {table_name} to become ACTIVE")


def _delete_dynamodb_table(ddb, table_name: str) -> None:
    try:
        ddb.delete_table(TableName=table_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return
    for _ in range(30):
        try:
            ddb.describe_table(TableName=table_name)
            time.sleep(2)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return
            raise
    raise RuntimeError(f"Timed out waiting for table {table_name} deletion")


def _ensure_dynamodb_table(ddb, table_name: str, schema: Dict[str, Any]) -> None:
    api = dict(schema)
    api["BillingMode"] = "PAY_PER_REQUEST"
    expected = _schema_fingerprint(schema)
    try:
        desc = ddb.describe_table(TableName=table_name)
        if _table_fingerprint(desc) == expected:
            print(f"  ddb table exists: {table_name}")
            return
        print(f"  ddb table schema mismatch — recreating: {table_name}")
        _delete_dynamodb_table(ddb, table_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    ddb.create_table(TableName=table_name, **api)
    _wait_table_active(ddb, table_name)
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


def _ai_engine_ssm_parameters(naming: LocalNaming) -> Dict[str, str]:
    """Flat SSM keys matching nexus-ai-engine serve --ssm-prefix contract."""
    env = naming.environment
    return {
        naming.ai_engine_ssm_parameter("dynamodb_transformation_table"): naming.dynamodb_table("journeys"),
        naming.ai_engine_ssm_parameter("dynamodb_executions_table"): naming.dynamodb_table("executions"),
        naming.ai_engine_ssm_parameter("dynamodb_prompts_table"): naming.dynamodb_table("prompts"),
        naming.ai_engine_ssm_parameter("s3_journey_logs_bucket"): naming.s3_bucket("journey-logs"),
        naming.ai_engine_ssm_parameter("s3_journey_reports_bucket"): naming.s3_bucket("journey-reports"),
        naming.ai_engine_ssm_parameter("environment"): env,
        naming.ai_engine_ssm_parameter("capability_name"): "ai-engine",
        naming.ai_engine_ssm_parameter("max_concurrent_jobs"): "10",
    }


def _ensure_ssm_parameters(ssm, params: Dict[str, str]) -> None:
    for name, value in sorted(params.items()):
        ssm.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)
        print(f"  ssm parameter: {name}")


_AI_ENGINE_SECRET_TYPES = ["api-keys", "openai", "anthropic", "github", "license"]


def _ensure_secrets(sm, naming: LocalNaming) -> None:
    for secret_type in _AI_ENGINE_SECRET_TYPES:
        name = naming.secret_name(secret_type)
        try:
            sm.describe_secret(SecretId=name)
            print(f"  secret exists: {name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            sm.create_secret(
                Name=name,
                SecretString=json.dumps({"placeholder": "update-me"}),
                Description=f"Nexus local dev secret ({secret_type})",
            )
            print(f"  secret created: {name}")


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
    for b in _capability_buckets(capability, naming):
        _ensure_bucket(s3, b)
    ddb = _client("dynamodb", scylla_endpoint, region)
    for purpose in _capability_tables(capability):
        schema = TABLE_SCHEMAS[purpose]
        _ensure_dynamodb_table(ddb, naming.dynamodb_table(purpose), schema)
    if _sanitize(capability) != "ai-engine":
        glue = _client("glue", ministack_endpoint, region)
        _ensure_glue_database(glue, naming.glue_database())
    else:
        ssm = _client("ssm", ministack_endpoint, region)
        _ensure_ssm_parameters(ssm, _ai_engine_ssm_parameters(naming))
        sm = _client("secretsmanager", ministack_endpoint, region)
        _ensure_secrets(sm, naming)


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
    shared_mimir = os.getenv("SHARED_MIMIR_BUCKET", "").strip()
    if shared_mimir:
        s3 = _client("s3", args.minio_endpoint, args.region)
        _ensure_bucket(s3, shared_mimir)
        print(f"  shared mimir blocks bucket: {shared_mimir}")
    print(json.dumps({"capabilities": caps, "environment": args.environment}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
