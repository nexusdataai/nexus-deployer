"""
Regional HTTPS endpoints for boto3 (VPC interface/gateway compatibility).

Mirror of starhub-deployer/backend/app/utils/aws_vpc_endpoints.py — keep in sync.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import boto3


def dynamodb_endpoint_url(region_name: str) -> str:
    override = os.environ.get("DYNAMODB_ENDPOINT_URL") or os.environ.get("AWS_ENDPOINT_URL_DYNAMODB")
    if override:
        return override
    return f"https://dynamodb.{region_name}.amazonaws.com"


_EXPLICIT_ENDPOINTS_DISABLED = os.environ.get("AWS_DISABLE_EXPLICIT_SERVICE_ENDPOINTS", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

_VPC_FRIENDLY_ENDPOINT_HOSTS: Dict[str, str] = {
    "ec2": "ec2.{region}.amazonaws.com",
    "s3": "s3.{region}.amazonaws.com",
    "ssm": "ssm.{region}.amazonaws.com",
    "sts": "sts.{region}.amazonaws.com",
    "glue": "glue.{region}.amazonaws.com",
    "ecr": "api.ecr.{region}.amazonaws.com",
    "secretsmanager": "secretsmanager.{region}.amazonaws.com",
    "logs": "logs.{region}.amazonaws.com",
    "cognito-idp": "cognito-idp.{region}.amazonaws.com",
    "athena": "athena.{region}.amazonaws.com",
    "events": "events.{region}.amazonaws.com",
    "eks": "eks.{region}.amazonaws.com",
    "iam": "iam.{region}.amazonaws.com",
}


def explicit_service_endpoint_url(service_name: str, region_name: str) -> Optional[str]:
    if _EXPLICIT_ENDPOINTS_DISABLED:
        return None
    env_key = f"AWS_ENDPOINT_URL_{service_name.upper().replace('-', '_')}"
    env_val = os.environ.get(env_key)
    if env_val:
        return env_val
    if service_name == "dynamodb":
        return dynamodb_endpoint_url(region_name)
    host_tmpl = _VPC_FRIENDLY_ENDPOINT_HOSTS.get(service_name)
    if not host_tmpl:
        return None
    return f"https://{host_tmpl.format(region=region_name)}"


def merge_vpc_boto3_kwargs(
    service_name: str,
    region_name: Optional[str],
    kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(kwargs or {})
    r = merged.get("region_name") or region_name
    if r is None:
        r = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-1"
    merged.setdefault("region_name", r)
    r = merged["region_name"]
    if merged.get("endpoint_url"):
        return merged
    ep = explicit_service_endpoint_url(service_name, r)
    if ep:
        merged["endpoint_url"] = ep
    return merged


def vpc_boto3_client(service_name: str, **kwargs: Any):
    return boto3.client(service_name, **merge_vpc_boto3_kwargs(service_name, kwargs.get("region_name"), kwargs))


def vpc_boto3_resource(service_name: str, **kwargs: Any):
    return boto3.resource(service_name, **merge_vpc_boto3_kwargs(service_name, kwargs.get("region_name"), kwargs))
