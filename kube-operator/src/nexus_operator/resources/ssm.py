"""
SSM Parameter Store Provisioner.

Feature: pure-eks-deployment
Requirements: 4.6
"""
import logging
from typing import Dict, List, Any, Tuple

from botocore.exceptions import ClientError

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class SSMProvisioner:
    """Provisions SSM Parameter Store parameters."""
    
    def __init__(self, naming: ResourceNaming, region: str):
        self.naming = naming
        self.region = region
        self.client = vpc_boto3_client("ssm", region_name=region)
    
    def get_all_parameters(self, resources: Dict[str, Any] = None) -> Dict[str, Tuple[str, str]]:
        """
        Get all parameters with values and descriptions.
        
        Args:
            resources: Optional resource configuration including Cognito config
        
        Returns:
            Dict mapping parameter paths to (value, description) tuples
        """
        params = {}
        
        # AWS parameters
        params[self.naming.ssm_parameter("aws", "region")] = (self.region, "AWS region")
        
        # Server parameters
        params[self.naming.ssm_parameter("server", "environment")] = (
            self.naming.environment, "Deployment environment"
        )
        params[self.naming.ssm_parameter("server", "log-level")] = ("INFO", "Log level")
        
        # DynamoDB parameters
        params[self.naming.ssm_parameter("dynamodb", "transformation-table")] = (
            self.naming.transformation_system_table(), "Transformation table"
        )
        params[self.naming.ssm_parameter("dynamodb", "license-table")] = (
            self.naming.license_table(), "License table"
        )
        params[self.naming.ssm_parameter("dynamodb", "wxcc-task-table")] = (
            self.naming.wxcc_task_tracking_table(), "WXCC task table"
        )
        params[self.naming.ssm_parameter("dynamodb", "sessions-table")] = (
            self.naming.dynamodb_table("sessions"), "Sessions table"
        )
        params[self.naming.ssm_parameter("dynamodb", "audit-log-table")] = (
            self.naming.dynamodb_table("audit-log"), "Audit log table"
        )
        params[self.naming.ssm_parameter("dynamodb", "lead-tracking-table")] = (
            self.naming.lead_opportunity_tracking_table(), "Lead/opportunity tracking table"
        )
        
        # S3 parameters
        params[self.naming.ssm_parameter("s3", "journey-logs-bucket")] = (
            self.naming.journey_logs_bucket(), "Journey logs bucket"
        )
        params[self.naming.ssm_parameter("s3", "journey-reports-bucket")] = (
            self.naming.journey_reports_bucket(), "Journey reports bucket"
        )
        
        # Glue parameters
        params[self.naming.ssm_parameter("glue", "database")] = (
            self.naming.glue_database(), "Glue database"
        )
        
        # WXCC Simulator parameters
        params[self.naming.ssm_parameter("wxcc", "enabled")] = (
            "true", "Enable WXCC simulator"
        )
        params[self.naming.ssm_parameter("wxcc", "bucket")] = (
            self.naming.wxcc_simulator_bucket(), "WXCC simulator S3 bucket"
        )
        params[self.naming.ssm_parameter("wxcc", "prefix")] = (
            "wxcc-simulator", "WXCC simulator S3 prefix"
        )
        params[self.naming.ssm_parameter("wxcc", "org-id")] = (
            "sim-org-001", "Simulated organization ID"
        )
        
        # SFDC Simulator parameters
        params[self.naming.ssm_parameter("sfdc", "enabled")] = (
            "true", "Enable SFDC simulator"
        )
        params[self.naming.ssm_parameter("sfdc", "bucket")] = (
            self.naming.sfdc_simulator_bucket(), "SFDC simulator S3 bucket"
        )
        params[self.naming.ssm_parameter("sfdc", "prefix")] = (
            "sfdc-simulator", "SFDC simulator S3 prefix"
        )
        
        # Oracle ERP Simulator parameters
        params[self.naming.ssm_parameter("oracle-erp", "enabled")] = (
            "true", "Enable Oracle ERP simulator"
        )
        params[self.naming.ssm_parameter("oracle-erp", "bucket")] = (
            self.naming.oracle_erp_simulator_bucket(), "Oracle ERP simulator S3 bucket"
        )
        params[self.naming.ssm_parameter("oracle-erp", "prefix")] = (
            "oracle-erp-simulator", "Oracle ERP simulator S3 prefix"
        )
        
        # SAP Simulator parameters
        params[self.naming.ssm_parameter("sap", "enabled")] = (
            "true", "Enable SAP simulator"
        )
        params[self.naming.ssm_parameter("sap", "bucket")] = (
            self.naming.sap_simulator_bucket(), "SAP simulator S3 bucket"
        )
        params[self.naming.ssm_parameter("sap", "prefix")] = (
            "sap-simulator", "SAP simulator S3 prefix"
        )

        # External Source Simulator parameters
        ext_bucket = self.naming.external_simulator_bucket()
        results_bucket = self.naming.solution_results_bucket()
        mimir_bucket = self.naming.mimir_blocks_bucket()
        mimir_namespace = self.naming.kubernetes_namespace()
        mimir_url = "http://mimir-svc." + mimir_namespace + ".svc.cluster.local:8080"

        params[self.naming.ssm_parameter("external", "enabled")] = ("true", "Enable External simulator")
        params[self.naming.ssm_parameter("external", "bucket")] = (ext_bucket, "External simulator S3 bucket")
        params[self.naming.ssm_parameter("external", "prefix")] = ("external-simulator", "External simulator S3 prefix")

        # Solution Results bucket (Athena-queryable Parquet from journeys)
        params[self.naming.ssm_parameter("s3", "solution-results-bucket")] = (results_bucket, "Bucket for journey-emitted relational result tables")

        # Mimir time-series storage parameters
        params[self.naming.ssm_parameter("mimir", "enabled")] = ("true", "Enable Grafana Mimir")
        params[self.naming.ssm_parameter("mimir", "url")] = (mimir_url, "Mimir HTTP API URL")
        params[self.naming.ssm_parameter("mimir", "tenant-id")] = ("nexus-default", "Default Mimir tenant id")
        params[self.naming.ssm_parameter("mimir", "bucket")] = (mimir_bucket, "Mimir blocks-storage S3 bucket")
        params[self.naming.ssm_parameter("mimir", "retention-days")] = ("90", "Mimir hot retention in days")

        # CloudWatch parameters
        params[self.naming.ssm_parameter("cloudwatch", "log-group")] = (
            self.naming.log_group(), "CloudWatch log group"
        )
        params[self.naming.ssm_parameter("cloudwatch", "stream-prefix")] = (
            "script", "CloudWatch log stream prefix"
        )
        
        # Cognito parameters (if provided in resources)
        if resources and resources.get("cognito"):
            cognito_config = resources["cognito"]
            
            if cognito_config.get("region"):
                params[self.naming.ssm_parameter("cognito", "region")] = (
                    cognito_config["region"], "Cognito region"
                )
            
            if cognito_config.get("user_pool_id"):
                params[self.naming.ssm_parameter("cognito", "user-pool-id")] = (
                    cognito_config["user_pool_id"], "Cognito User Pool ID"
                )
            
            if cognito_config.get("client_id"):
                # Note: app-client-id matches the SSM parameter path used by starhub-backend
                params[self.naming.ssm_parameter("cognito", "app-client-id")] = (
                    cognito_config["client_id"], "Cognito App Client ID"
                )
            
            if cognito_config.get("domain"):
                # Store full domain URL (prefix.auth.region.amazoncognito.com)
                domain = cognito_config["domain"]
                if not domain.endswith(".amazoncognito.com"):
                    # Convert prefix to full domain
                    domain = f"{domain}.auth.{self.region}.amazoncognito.com"
                params[self.naming.ssm_parameter("cognito", "domain")] = (
                    domain, "Cognito domain for OAuth"
                )
            
            if cognito_config.get("redirect_uri"):
                params[self.naming.ssm_parameter("cognito", "redirect-uri")] = (
                    cognito_config["redirect_uri"], "OAuth redirect URI"
                )
            
            logger.info(f"Added {len([k for k in params if '/cognito/' in k])} Cognito parameters to SSM")
        
        return params
    
    async def provision_all(self, resources: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Provision all SSM parameters.
        
        Args:
            resources: Optional resource configuration including Cognito config
        
        Returns:
            List of results for each parameter created
        """
        results = []
        for path, (value, description) in self.get_all_parameters(resources).items():
            result = await self.create_parameter(path, value, description)
            results.append(result)
        return results
    
    async def create_parameter(self, path: str, value: str, description: str) -> Dict[str, Any]:
        """Create or update an SSM parameter."""
        try:
            self.client.put_parameter(
                Name=path,
                Value=value,
                Type="String",
                Description=description,
                Overwrite=True
            )
            try:
                self.client.add_tags_to_resource(
                    ResourceType="Parameter",
                    ResourceId=path,
                    Tags=self.naming.aws_tags()
                )
            except Exception:
                pass
            logger.info(f"Created SSM parameter: {path}")
            return {"name": path, "status": "created", "type": "SSM"}
        except Exception as e:
            logger.error(f"Failed to create parameter {path}: {e}")
            return {"name": path, "status": "failed", "error": str(e), "type": "SSM"}
    
    async def delete_all(self) -> List[Dict[str, Any]]:
        """Delete all provisioned parameters including Cognito params."""
        results = []
        # Delete base parameters
        for path in self.get_all_parameters().keys():
            result = await self.delete_parameter(path)
            results.append(result)
        
        # Also delete Cognito parameters (not included in get_all_parameters without resources)
        cognito_params = [
            self.naming.ssm_parameter("cognito", "region"),
            self.naming.ssm_parameter("cognito", "user-pool-id"),
            self.naming.ssm_parameter("cognito", "app-client-id"),
            self.naming.ssm_parameter("cognito", "domain"),
            self.naming.ssm_parameter("cognito", "redirect-uri"),
        ]
        for path in cognito_params:
            result = await self.delete_parameter(path)
            results.append(result)
        
        return results
    
    async def delete_parameter(self, path: str) -> Dict[str, Any]:
        """Delete an SSM parameter."""
        try:
            self.client.delete_parameter(Name=path)
            logger.info(f"Deleted SSM parameter: {path}")
            return {"name": path, "status": "deleted", "type": "SSM"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "ParameterNotFound":
                return {"name": path, "status": "not_found", "type": "SSM"}
            return {"name": path, "status": "failed", "error": str(e), "type": "SSM"}
