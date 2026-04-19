"""
Verification Service for call-processing capability.

Verifies all provisioned resources exist and are accessible,
generating a comprehensive report.
"""

import logging
from datetime import datetime
from typing import List, Optional

import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

from .models import (
    ResourceType,
    VerificationResult,
    VerificationStatusType,
    VerificationReport,
)
from .naming import ResourceNaming

logger = logging.getLogger(__name__)


class VerificationService:
    """Verifies all provisioned resources exist and are accessible."""
    
    def __init__(
        self,
        environment: str,
        region: str,
        endpoint_url: Optional[str] = None,
        credentials: Optional[dict] = None,
    ):
        """
        Initialize verification service.
        
        Args:
            environment: Environment name (dev, test, stage, prod)
            region: AWS region
            endpoint_url: Optional endpoint URL (for LocalStack)
            credentials: Optional AWS credentials dict with keys:
                - aws_access_key_id
                - aws_secret_access_key
                - aws_session_token (optional)
        """
        self.environment = environment
        self.region = region
        self.endpoint_url = endpoint_url
        self.naming = ResourceNaming(environment)
        
        # Initialize boto3 clients with optional credentials
        client_kwargs = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        
        # Add credentials if provided
        if credentials:
            client_kwargs.update(credentials)

        self.dynamodb = boto3.client(
            "dynamodb", **merge_vpc_boto3_kwargs("dynamodb", region, dict(client_kwargs))
        )
        self.s3 = boto3.client("s3", **merge_vpc_boto3_kwargs("s3", region, dict(client_kwargs)))
        self.ssm = boto3.client("ssm", **merge_vpc_boto3_kwargs("ssm", region, dict(client_kwargs)))
        self.secretsmanager = boto3.client(
            "secretsmanager", **merge_vpc_boto3_kwargs("secretsmanager", region, dict(client_kwargs))
        )
        self.glue = boto3.client("glue", **merge_vpc_boto3_kwargs("glue", region, dict(client_kwargs)))
        self.logs = boto3.client("logs", **merge_vpc_boto3_kwargs("logs", region, dict(client_kwargs)))
    
    def verify_all(self) -> VerificationReport:
        """
        Verify all resources and generate report.
        
        Returns:
            VerificationReport with status of all resources
        """
        logger.info(f"Starting verification for environment: {self.environment}")
        started_at = datetime.utcnow()
        
        all_results: List[VerificationResult] = []
        
        all_results.extend(self.verify_dynamodb_tables())
        all_results.extend(self.verify_s3_buckets())
        all_results.extend(self.verify_ssm_parameters())
        all_results.extend(self.verify_secrets())
        all_results.extend(self.verify_glue_resources())
        all_results.extend(self.verify_cloudwatch())
        
        completed_at = datetime.utcnow()
        
        report = VerificationReport(
            environment=self.environment,
            region=self.region,
            started_at=started_at,
            completed_at=completed_at,
            results=all_results,
        )
        
        logger.info(f"Verification completed. Success: {report.all_passed}")
        logger.info(f"Passed: {report.passed_count}, Failed: {report.failed_count}")
        
        return report
    
    def verify_dynamodb_tables(self) -> List[VerificationResult]:
        """Verify all DynamoDB tables exist and are ACTIVE."""
        results = []
        
        table_names = [
            self.naming.transformation_system_table(),
            self.naming.license_table(),
            self.naming.wxcc_task_tracking_table(),
            self.naming.lead_opportunity_tracking_table(),
        ]
        
        for table_name in table_names:
            result = self._verify_dynamodb_table(table_name)
            results.append(result)
        
        return results
    
    def _verify_dynamodb_table(self, table_name: str) -> VerificationResult:
        """Verify a single DynamoDB table."""
        try:
            response = self.dynamodb.describe_table(TableName=table_name)
            status = response["Table"]["TableStatus"]
            
            if status == "ACTIVE":
                return VerificationResult(
                    resource_type=ResourceType.DYNAMODB_TABLE,
                    resource_name=table_name,
                    status=VerificationStatusType.VERIFIED,
                    details=f"Table exists and is ACTIVE",
                )
            else:
                return VerificationResult(
                    resource_type=ResourceType.DYNAMODB_TABLE,
                    resource_name=table_name,
                    status=VerificationStatusType.INVALID_STATE,
                    details=f"Table exists but status is {status}",
                    failure_reason=f"Expected ACTIVE status, got {status}",
                )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return VerificationResult(
                    resource_type=ResourceType.DYNAMODB_TABLE,
                    resource_name=table_name,
                    status=VerificationStatusType.NOT_FOUND,
                    details="Table does not exist",
                    failure_reason="Table not found",
                    error="ResourceNotFoundException",
                )
            return VerificationResult(
                resource_type=ResourceType.DYNAMODB_TABLE,
                resource_name=table_name,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access table: {str(e)}",
                failure_reason=f"Access error: {e.response.get('Error', {}).get('Code')}",
                error=e.response.get("Error", {}).get("Code"),
            )
    
    def verify_s3_buckets(self) -> List[VerificationResult]:
        """Verify all S3 buckets exist and are accessible."""
        results = []
        
        bucket_names = [
            self.naming.call_data_bucket(),
            self.naming.wxcc_simulator_bucket(),
            self.naming.journey_logs_bucket(),
            self.naming.journey_reports_bucket(),
        ]
        
        for bucket_name in bucket_names:
            result = self._verify_s3_bucket(bucket_name)
            results.append(result)
        
        return results
    
    def _verify_s3_bucket(self, bucket_name: str) -> VerificationResult:
        """Verify a single S3 bucket."""
        try:
            self.s3.head_bucket(Bucket=bucket_name)
            return VerificationResult(
                resource_type=ResourceType.S3_BUCKET,
                resource_name=bucket_name,
                status=VerificationStatusType.VERIFIED,
                details="Bucket exists and is accessible",
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket"):
                return VerificationResult(
                    resource_type=ResourceType.S3_BUCKET,
                    resource_name=bucket_name,
                    status=VerificationStatusType.NOT_FOUND,
                    details="Bucket does not exist",
                    failure_reason="Bucket not found",
                    error="NoSuchBucket",
                )
            if error_code == "403":
                return VerificationResult(
                    resource_type=ResourceType.S3_BUCKET,
                    resource_name=bucket_name,
                    status=VerificationStatusType.INACCESSIBLE,
                    details="Bucket exists but access denied",
                    failure_reason="Access denied",
                    error="AccessDenied",
                )
            return VerificationResult(
                resource_type=ResourceType.S3_BUCKET,
                resource_name=bucket_name,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access bucket: {str(e)}",
                failure_reason=f"Access error: {error_code}",
                error=error_code,
            )

    def verify_ssm_parameters(self) -> List[VerificationResult]:
        """Verify all SSM parameters exist."""
        results = []
        
        # Import SSMProvisioner to get parameter paths
        from .ssm_provisioner import SSMProvisioner
        provisioner = SSMProvisioner(self.environment, self.region, self.endpoint_url)
        
        for path in provisioner.get_all_parameter_paths():
            result = self._verify_ssm_parameter(path)
            results.append(result)
        
        return results
    
    def _verify_ssm_parameter(self, path: str) -> VerificationResult:
        """Verify a single SSM parameter."""
        try:
            response = self.ssm.get_parameter(Name=path)
            return VerificationResult(
                resource_type=ResourceType.SSM_PARAMETER,
                resource_name=path,
                status=VerificationStatusType.VERIFIED,
                details=f"Parameter exists with value length {len(response['Parameter']['Value'])}",
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
                return VerificationResult(
                    resource_type=ResourceType.SSM_PARAMETER,
                    resource_name=path,
                    status=VerificationStatusType.NOT_FOUND,
                    details="Parameter does not exist",
                    failure_reason="Parameter not found",
                    error="ParameterNotFound",
                )
            return VerificationResult(
                resource_type=ResourceType.SSM_PARAMETER,
                resource_name=path,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access parameter: {str(e)}",
                failure_reason=f"Access error: {e.response.get('Error', {}).get('Code')}",
                error=e.response.get("Error", {}).get("Code"),
            )
    
    def verify_secrets(self) -> List[VerificationResult]:
        """Verify all secrets exist."""
        results = []
        
        secret_names = self.naming.all_secrets()
        
        for secret_name in secret_names:
            result = self._verify_secret(secret_name)
            results.append(result)
        
        return results
    
    def _verify_secret(self, secret_name: str) -> VerificationResult:
        """Verify a single secret."""
        try:
            self.secretsmanager.describe_secret(SecretId=secret_name)
            return VerificationResult(
                resource_type=ResourceType.SECRET,
                resource_name=secret_name,
                status=VerificationStatusType.VERIFIED,
                details="Secret exists",
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return VerificationResult(
                    resource_type=ResourceType.SECRET,
                    resource_name=secret_name,
                    status=VerificationStatusType.NOT_FOUND,
                    details="Secret does not exist",
                    failure_reason="Secret not found",
                    error="ResourceNotFoundException",
                )
            return VerificationResult(
                resource_type=ResourceType.SECRET,
                resource_name=secret_name,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access secret: {str(e)}",
                failure_reason=f"Access error: {e.response.get('Error', {}).get('Code')}",
                error=e.response.get("Error", {}).get("Code"),
            )
    
    def verify_glue_resources(self) -> List[VerificationResult]:
        """Verify Glue database and table exist."""
        results = []
        
        # Verify database
        database_name = self.naming.glue_database()
        results.append(self._verify_glue_database(database_name))
        
        # Verify table
        table_name = self.naming.glue_table()
        results.append(self._verify_glue_table(database_name, table_name))
        
        return results
    
    def _verify_glue_database(self, database_name: str) -> VerificationResult:
        """Verify a Glue database."""
        try:
            self.glue.get_database(Name=database_name)
            return VerificationResult(
                resource_type=ResourceType.GLUE_DATABASE,
                resource_name=database_name,
                status=VerificationStatusType.VERIFIED,
                details="Database exists",
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                return VerificationResult(
                    resource_type=ResourceType.GLUE_DATABASE,
                    resource_name=database_name,
                    status=VerificationStatusType.NOT_FOUND,
                    details="Database does not exist",
                    failure_reason="Database not found",
                    error="EntityNotFoundException",
                )
            return VerificationResult(
                resource_type=ResourceType.GLUE_DATABASE,
                resource_name=database_name,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access database: {str(e)}",
                failure_reason=f"Access error: {e.response.get('Error', {}).get('Code')}",
                error=e.response.get("Error", {}).get("Code"),
            )
    
    def _verify_glue_table(self, database_name: str, table_name: str) -> VerificationResult:
        """Verify a Glue table."""
        full_name = f"{database_name}.{table_name}"
        try:
            self.glue.get_table(DatabaseName=database_name, Name=table_name)
            return VerificationResult(
                resource_type=ResourceType.GLUE_TABLE,
                resource_name=full_name,
                status=VerificationStatusType.VERIFIED,
                details="Table exists",
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                return VerificationResult(
                    resource_type=ResourceType.GLUE_TABLE,
                    resource_name=full_name,
                    status=VerificationStatusType.NOT_FOUND,
                    details="Table does not exist",
                    failure_reason="Table not found",
                    error="EntityNotFoundException",
                )
            return VerificationResult(
                resource_type=ResourceType.GLUE_TABLE,
                resource_name=full_name,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access table: {str(e)}",
                failure_reason=f"Access error: {e.response.get('Error', {}).get('Code')}",
                error=e.response.get("Error", {}).get("Code"),
            )
    
    def verify_cloudwatch(self) -> List[VerificationResult]:
        """Verify CloudWatch log group exists."""
        results = []
        
        log_group_name = self.naming.log_group()
        results.append(self._verify_log_group(log_group_name))
        
        return results
    
    def _verify_log_group(self, log_group_name: str) -> VerificationResult:
        """Verify a CloudWatch log group."""
        try:
            response = self.logs.describe_log_groups(
                logGroupNamePrefix=log_group_name,
                limit=1,
            )
            
            for group in response.get("logGroups", []):
                if group["logGroupName"] == log_group_name:
                    retention = group.get("retentionInDays", "not set")
                    return VerificationResult(
                        resource_type=ResourceType.CLOUDWATCH_LOG_GROUP,
                        resource_name=log_group_name,
                        status=VerificationStatusType.VERIFIED,
                        details=f"Log group exists with retention: {retention} days",
                    )
            
            return VerificationResult(
                resource_type=ResourceType.CLOUDWATCH_LOG_GROUP,
                resource_name=log_group_name,
                status=VerificationStatusType.NOT_FOUND,
                details="Log group does not exist",
                failure_reason="Log group not found",
            )
        except ClientError as e:
            return VerificationResult(
                resource_type=ResourceType.CLOUDWATCH_LOG_GROUP,
                resource_name=log_group_name,
                status=VerificationStatusType.INACCESSIBLE,
                details=f"Cannot access log group: {str(e)}",
                failure_reason=f"Access error: {e.response.get('Error', {}).get('Code')}",
                error=e.response.get("Error", {}).get("Code"),
            )
