"""
SSM Parameter Store Provisioner for call-processing capability.

Creates and manages SSM parameters across categories:
- aws: AWS configuration (region)
- server: Server configuration (environment, log-level, workers, timeout)
- cognito: Cognito authentication (region, user-pool-id, app-client-id)
- wxcc: WXCC simulator (enabled, bucket, prefix, org-id)
- s3: S3 buckets (recordings-bucket, journey-logs-bucket, journey-reports-bucket)
- dynamodb: DynamoDB tables (transformation-table, license-table, wxcc-task-table)
- glue: Glue configuration (database, table)
- cloudwatch: CloudWatch logging (log-group, stream-prefix)
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable

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


class SSMProvisioner:
    """Provisions SSM Parameter Store parameters for call-processing capability."""
    
    def __init__(
        self,
        environment: str,
        region: str,
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        boto3_session: Optional['boto3.Session'] = None,
    ):
        """
        Initialize the SSM provisioner.
        
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
        
        merged = merge_vpc_boto3_kwargs("ssm", region, dict(client_kwargs))
        # Use provided session or create new one
        if boto3_session:
            self.client = boto3_session.client("ssm", **merged)
        else:
            self.client = boto3.client("ssm", **merged)
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def provision_all(self) -> List[ResourceStatus]:
        """
        Provision all SSM parameters.
        
        Returns:
            List of ResourceStatus for each parameter
        """
        return self.create_all_parameters()
    
    def create_all_parameters(self) -> List[ResourceStatus]:
        """
        Create all SSM parameters for the environment.
        
        Returns:
            List of ResourceStatus for each parameter
        """
        results = []
        
        # Get all parameters by category
        all_params = self.get_all_parameters()
        total = len(all_params)
        
        self._log_progress(f"  Creating {total} SSM parameters...")
        
        for idx, (path, (value, description)) in enumerate(all_params.items(), 1):
            # Extract category from path for logging
            parts = path.split('/')
            category = parts[-2] if len(parts) >= 2 else "unknown"
            param_name = parts[-1] if parts else path
            self._log_progress(f"    [{idx}/{total}] {category}/{param_name}")
            result = self.create_parameter(path, value, description)
            results.append(result)
        
        return results
    
    def create_parameter(
        self,
        path: str,
        value: str,
        description: str,
        param_type: str = "String",
    ) -> ResourceStatus:
        """
        Create or update a single SSM parameter.
        
        Args:
            path: Parameter path (e.g., /call-processing/{env}/aws/region)
            value: Parameter value
            description: Parameter description
            param_type: String or SecureString
            
        Returns:
            ResourceStatus indicating success or failure
        """
        try:
            # Check if parameter exists and get current value
            existing_value = self._get_parameter_value(path)
            
            if existing_value is not None:
                if existing_value == value:
                    self._log_progress(f"      [OK] Already exists (unchanged)")
                    return ResourceStatus(
                        resource_type=ResourceType.SSM_PARAMETER,
                        resource_name=path,
                        status=ResourceStatusType.ALREADY_EXISTS,
                        message=f"Parameter {path} already exists with same value",
                    )
                else:
                    # Update the parameter
                    self._log_progress(f"      Updating...")
                    self.client.put_parameter(
                        Name=path,
                        Value=value,
                        Type=param_type,
                        Description=description,
                        Overwrite=True,
                    )
                    self._log_progress(f"      [OK] Updated")
                    return ResourceStatus(
                        resource_type=ResourceType.SSM_PARAMETER,
                        resource_name=path,
                        status=ResourceStatusType.UPDATED,
                        message=f"Parameter {path} updated",
                        created_at=datetime.utcnow(),
                    )
            
            # Create new parameter
            self._log_progress(f"      Creating...")
            self.client.put_parameter(
                Name=path,
                Value=value,
                Type=param_type,
                Description=description,
            )
            
            self._log_progress(f"      [OK] Created")
            return ResourceStatus(
                resource_type=ResourceType.SSM_PARAMETER,
                resource_name=path,
                status=ResourceStatusType.CREATED,
                message=f"Parameter {path} created",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"      [X] Failed: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.SSM_PARAMETER,
                resource_name=path,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create parameter: {error_msg}",
                error=error_code,
            )
    
    def _get_parameter_value(self, path: str) -> Optional[str]:
        """
        Get the current value of a parameter.
        
        Args:
            path: Parameter path
            
        Returns:
            Parameter value or None if not found
        """
        try:
            response = self.client.get_parameter(Name=path)
            return response["Parameter"]["Value"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
                return None
            raise

    def get_all_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get all parameters with their values and descriptions.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        params = {}
        params.update(self.get_aws_parameters())
        params.update(self.get_server_parameters())
        params.update(self.get_cognito_parameters())
        params.update(self.get_wxcc_parameters())
        params.update(self.get_sfdc_parameters())
        params.update(self.get_oracle_erp_parameters())
        params.update(self.get_sap_parameters())
        params.update(self.get_s3_parameters())
        params.update(self.get_dynamodb_parameters())
        params.update(self.get_glue_parameters())
        params.update(self.get_cloudwatch_parameters())
        return params
    
    def get_aws_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get AWS configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("aws", "region"): (
                self.region,
                "AWS region for services",
            ),
        }
    
    def get_server_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get server configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("server", "environment"): (
                self.environment,
                "Deployment environment",
            ),
            self.naming.ssm_parameter("server", "log-level"): (
                self.config.log_level,
                "Logging verbosity",
            ),
            self.naming.ssm_parameter("server", "min-workers"): (
                "2",
                "Minimum worker pool size",
            ),
            self.naming.ssm_parameter("server", "max-workers"): (
                "8",
                "Maximum worker pool size",
            ),
            self.naming.ssm_parameter("server", "timeout"): (
                "60.0",
                "Request timeout in seconds",
            ),
        }
    
    def get_cognito_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get Cognito configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("cognito", "region"): (
                self.region,
                "Cognito region",
            ),
            self.naming.ssm_parameter("cognito", "user-pool-id"): (
                "PLACEHOLDER_USER_POOL_ID",
                "Cognito User Pool ID - update with actual value",
            ),
            self.naming.ssm_parameter("cognito", "app-client-id"): (
                "PLACEHOLDER_APP_CLIENT_ID",
                "Cognito App Client ID - update with actual value",
            ),
        }
    
    def get_wxcc_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get WXCC configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("wxcc", "enabled"): (
                "true",
                "Enable/disable WXCC simulator",
            ),
            self.naming.ssm_parameter("wxcc", "bucket"): (
                self.naming.wxcc_simulator_bucket(),
                "S3 bucket for WXCC simulator data",
            ),
            self.naming.ssm_parameter("wxcc", "prefix"): (
                "wxcc-simulator",
                "S3 prefix for WXCC simulator",
            ),
            self.naming.ssm_parameter("wxcc", "org-id"): (
                "sim-org-001",
                "Simulated organization ID",
            ),
        }
    
    def get_sfdc_parameters(self) -> Dict[str, Tuple[str, str]]:
        """Get SFDC simulator configuration parameters."""
        return {
            self.naming.ssm_parameter("sfdc", "enabled"): (
                "true",
                "Enable/disable SFDC simulator",
            ),
            self.naming.ssm_parameter("sfdc", "bucket"): (
                self.naming.sfdc_simulator_bucket(),
                "S3 bucket for SFDC simulator data",
            ),
            self.naming.ssm_parameter("sfdc", "prefix"): (
                "sfdc-simulator",
                "S3 prefix for SFDC simulator",
            ),
        }
    
    def get_oracle_erp_parameters(self) -> Dict[str, Tuple[str, str]]:
        """Get Oracle ERP simulator configuration parameters."""
        return {
            self.naming.ssm_parameter("oracle-erp", "enabled"): (
                "true",
                "Enable/disable Oracle ERP simulator",
            ),
            self.naming.ssm_parameter("oracle-erp", "bucket"): (
                self.naming.oracle_erp_simulator_bucket(),
                "S3 bucket for Oracle ERP simulator data",
            ),
            self.naming.ssm_parameter("oracle-erp", "prefix"): (
                "oracle-erp-simulator",
                "S3 prefix for Oracle ERP simulator",
            ),
        }
    
    def get_sap_parameters(self) -> Dict[str, Tuple[str, str]]:
        """Get SAP simulator configuration parameters."""
        return {
            self.naming.ssm_parameter("sap", "enabled"): (
                "true",
                "Enable/disable SAP simulator",
            ),
            self.naming.ssm_parameter("sap", "bucket"): (
                self.naming.sap_simulator_bucket(),
                "S3 bucket for SAP simulator data",
            ),
            self.naming.ssm_parameter("sap", "prefix"): (
                "sap-simulator",
                "S3 prefix for SAP simulator",
            ),
        }
    
    def get_s3_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get S3 configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("s3", "recordings-bucket"): (
                self.naming.call_data_bucket(),
                "S3 bucket for call data and Glue tables",
            ),
            self.naming.ssm_parameter("s3", "journey-logs-bucket"): (
                self.naming.journey_logs_bucket(),
                "S3 bucket for journey logs",
            ),
            self.naming.ssm_parameter("s3", "journey-reports-bucket"): (
                self.naming.journey_reports_bucket(),
                "S3 bucket for journey reports",
            ),
        }
    
    def get_dynamodb_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get DynamoDB configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("dynamodb", "transformation-table"): (
                self.naming.transformation_system_table(),
                "DynamoDB transformation system table",
            ),
            self.naming.ssm_parameter("dynamodb", "license-table"): (
                self.naming.license_table(),
                "DynamoDB license table",
            ),
            self.naming.ssm_parameter("dynamodb", "wxcc-task-table"): (
                self.naming.wxcc_task_tracking_table(),
                "DynamoDB WXCC task tracking table",
            ),
            self.naming.ssm_parameter("dynamodb", "lead-tracking-table"): (
                self.naming.lead_opportunity_tracking_table(),
                "DynamoDB lead/opportunity tracking table",
            ),
        }
    
    def get_glue_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get Glue configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("glue", "database"): (
                self.naming.glue_database(),
                "AWS Glue database name",
            ),
            self.naming.ssm_parameter("glue", "table"): (
                self.naming.glue_table(),
                "AWS Glue table name",
            ),
        }
    
    def get_cloudwatch_parameters(self) -> Dict[str, Tuple[str, str]]:
        """
        Get CloudWatch configuration parameters with defaults.
        
        Returns:
            Dictionary mapping parameter path to (value, description) tuple
        """
        return {
            self.naming.ssm_parameter("cloudwatch", "log-group"): (
                self.naming.log_group(),
                "CloudWatch log group",
            ),
            self.naming.ssm_parameter("cloudwatch", "stream-prefix"): (
                "script",
                "Log stream prefix",
            ),
        }
    
    def parameter_exists(self, path: str) -> bool:
        """
        Check if a parameter exists.
        
        Args:
            path: Parameter path
            
        Returns:
            True if parameter exists, False otherwise
        """
        return self._get_parameter_value(path) is not None
    
    def get_all_parameter_paths(self) -> List[str]:
        """
        Get all parameter paths that should be created.
        
        Returns:
            List of parameter paths
        """
        return list(self.get_all_parameters().keys())
