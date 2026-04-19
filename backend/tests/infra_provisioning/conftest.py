"""
Pytest fixtures for infrastructure provisioning tests.

Uses moto for mocking AWS services when available.
"""

import pytest
import boto3


# Try to import moto, but make it optional
try:
    from moto import mock_aws
    MOTO_AVAILABLE = True
except ImportError:
    MOTO_AVAILABLE = False
    mock_aws = None


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto."""
    import os
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "ap-southeast-1"


@pytest.fixture
def mock_aws_services(aws_credentials):
    """Mock all AWS services used by provisioning."""
    if MOTO_AVAILABLE:
        with mock_aws():
            yield
    else:
        yield


@pytest.fixture
def dynamodb_client(mock_aws_services):
    """Create a mocked DynamoDB client."""
    return boto3.client("dynamodb", region_name="ap-southeast-1")


@pytest.fixture
def s3_client(mock_aws_services):
    """Create a mocked S3 client."""
    return boto3.client("s3", region_name="ap-southeast-1")


@pytest.fixture
def ssm_client(mock_aws_services):
    """Create a mocked SSM client."""
    return boto3.client("ssm", region_name="ap-southeast-1")


@pytest.fixture
def secretsmanager_client(mock_aws_services):
    """Create a mocked Secrets Manager client."""
    return boto3.client("secretsmanager", region_name="ap-southeast-1")


@pytest.fixture
def glue_client(mock_aws_services):
    """Create a mocked Glue client."""
    return boto3.client("glue", region_name="ap-southeast-1")


@pytest.fixture
def logs_client(mock_aws_services):
    """Create a mocked CloudWatch Logs client."""
    return boto3.client("logs", region_name="ap-southeast-1")
