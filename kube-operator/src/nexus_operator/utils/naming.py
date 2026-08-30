"""
Resource naming utilities for consistent naming across AWS and Kubernetes resources.

Feature: pure-eks-deployment
Requirements: 4.6, 4.7

SSM Parameter pattern: /{capability-name}/{environment}/{category}/{resource}
Secrets Manager pattern: {capability-name}/{environment}/{secret-type}
"""
import re
from typing import Optional


class ResourceNaming:
    """
    Generates consistent resource names for AWS and Kubernetes resources.
    
    Follows the naming conventions:
    - SSM Parameters: /{capability}/{env}/{category}/{resource}
    - Secrets Manager: {capability}/{env}/{secret-type}
    - DynamoDB Tables: {capability}-{env}-{table-name}
    - S3 Buckets: {capability}-{env}-{bucket-purpose}-{account-id}
    - Glue: {capability}_{env}_{resource}
    """
    
    # SSM Parameter categories
    SSM_CATEGORIES = [
        "aws", "server", "cognito", "wxcc", "s3", "dynamodb", "glue", "cloudwatch", "mimir"
    ]
    
    # Secret types
    SECRET_TYPES = [
        "api-keys", "wxcc", "openai", "license", "anthropic", "github"
    ]
    
    def __init__(self, capability_name: str, environment: str, account_id: Optional[str] = None):
        """
        Initialize the naming utility.
        
        Args:
            capability_name: Name of the capability (e.g., "nexus-ai")
            environment: Target environment (dev, staging, prod)
            account_id: AWS account ID (optional, used for globally unique names)
        """
        self.capability_name = self._sanitize_name(capability_name)
        self.environment = self._sanitize_name(environment)
        self.account_id = account_id
    
    @staticmethod
    def _sanitize_name(name: str) -> str:
        """Sanitize a name for use in resource identifiers."""
        # Convert to lowercase and replace invalid characters with hyphens
        sanitized = re.sub(r'[^a-z0-9-]', '-', name.lower())
        # Remove consecutive hyphens
        sanitized = re.sub(r'-+', '-', sanitized)
        # Remove leading/trailing hyphens
        return sanitized.strip('-')
    
    @staticmethod
    def _sanitize_for_glue(name: str) -> str:
        """Sanitize a name for Glue (underscores instead of hyphens)."""
        return name.replace('-', '_')
    
    # ==================== SSM Parameters ====================
    
    def ssm_parameter(self, category: str, resource: str) -> str:
        """
        Generate SSM parameter path.
        
        Pattern: /{capability}/{env}/{category}/{resource}
        
        Args:
            category: Parameter category (aws, server, cognito, etc.)
            resource: Resource name within the category
            
        Returns:
            Full SSM parameter path
        """
        return f"/{self.capability_name}/{self.environment}/{category}/{resource}"
    
    def ssm_parameter_prefix(self, category: Optional[str] = None) -> str:
        """
        Generate SSM parameter prefix for listing/searching.
        
        Args:
            category: Optional category to include in prefix
            
        Returns:
            SSM parameter prefix
        """
        if category:
            return f"/{self.capability_name}/{self.environment}/{category}/"
        return f"/{self.capability_name}/{self.environment}/"
    
    # ==================== Secrets Manager ====================
    
    def secret_name(self, secret_type: str) -> str:
        """
        Generate Secrets Manager secret name.
        
        Pattern: {capability}/{env}/{secret-type}
        
        Args:
            secret_type: Type of secret (api-keys, wxcc, openai, etc.)
            
        Returns:
            Full secret name
        """
        return f"{self.capability_name}/{self.environment}/{secret_type}"
    
    def secret_name_prefix(self) -> str:
        """
        Generate Secrets Manager name prefix for listing.
        
        Returns:
            Secret name prefix
        """
        return f"{self.capability_name}/{self.environment}/"
    
    # ==================== DynamoDB Tables ====================
    
    def dynamodb_table(self, table_purpose: str) -> str:
        """
        Generate DynamoDB table name.
        
        Pattern: {capability}-{env}-{table-purpose}
        
        Args:
            table_purpose: Purpose of the table (e.g., "transformation-system")
            
        Returns:
            DynamoDB table name
        """
        return f"{self.capability_name}-{self.environment}-{table_purpose}"
    
    def transformation_system_table(self) -> str:
        """Get the transformation system table name."""
        return self.dynamodb_table("transformation-system")
    
    def license_table(self) -> str:
        """Get the license table name."""
        return self.dynamodb_table("license")
    
    # ==================== S3 Buckets ====================
    
    def s3_bucket(self, bucket_purpose: str) -> str:
        """
        Generate S3 bucket name.
        
        Pattern: {capability}-{env}-{bucket-purpose}[-{account-id}]
        
        Args:
            bucket_purpose: Purpose of the bucket
            
        Returns:
            S3 bucket name (globally unique if account_id provided)
        """
        base_name = f"{self.capability_name}-{self.environment}-{bucket_purpose}"
        if self.account_id:
            return f"{base_name}-{self.account_id}"
        return base_name
    
    def wxcc_simulator_bucket(self) -> str:
        """Get the WXCC simulator bucket name."""
        return self.s3_bucket("wxcc-simulator")
    
    def sfdc_simulator_bucket(self) -> str:
        """Get the SFDC simulator bucket name."""
        return self.s3_bucket("sfdc-simulator")
    
    def oracle_erp_simulator_bucket(self) -> str:
        """Get the Oracle ERP simulator bucket name."""
        return self.s3_bucket("oracle-erp-simulator")
    
    def sap_simulator_bucket(self) -> str:
        """Get the SAP simulator bucket name."""
        return self.s3_bucket("sap-simulator")
    
    def journey_logs_bucket(self) -> str:
        """Get the journey logs bucket name."""
        return self.s3_bucket("journey-logs")
    
    def journey_reports_bucket(self) -> str:
        """Get the journey reports bucket name."""
        return self.s3_bucket("journey-reports")

    # Legacy CloudFormation names for ai-engine remote AWS (ai-engine-{purpose}-{env})
    def ai_engine_journeys_table(self) -> str:
        return f"ai-engine-journeys-{self.environment}"

    def ai_engine_executions_table(self) -> str:
        return f"ai-engine-executions-{self.environment}"

    def ai_engine_prompts_table(self) -> str:
        return f"ai-engine-prompts-{self.environment}"

    def ai_engine_journey_logs_bucket(self) -> str:
        return f"ai-engine-journey-logs-{self.environment}"

    def ai_engine_journey_reports_bucket(self) -> str:
        return f"ai-engine-journey-reports-{self.environment}"

    def ai_engine_ssm_parameter(self, key: str) -> str:
        """Flat SSM path used by nexus-ai-engine serve --ssm-prefix."""
        return f"/{self.capability_name}/{self.environment}/{key}"

    def mimir_blocks_bucket(self) -> str:
        """Get the Mimir TSDB blocks storage bucket name."""
        return self.s3_bucket("mimir-blocks")

    def external_simulator_bucket(self) -> str:
        """Get the external sources simulator bucket name."""
        return self.s3_bucket("external-simulator")

    def solution_results_bucket(self) -> str:
        """Get the bucket holding journey-emitted relational result tables (Athena-queryable)."""
        return self.s3_bucket("solution-results")

    # ==================== Glue ====================
    
    def glue_database(self) -> str:
        """
        Generate Glue database name.
        
        Pattern: {capability}_{env}_db
        """
        cap = self._sanitize_for_glue(self.capability_name)
        env = self._sanitize_for_glue(self.environment)
        return f"{cap}_{env}_db"
    
    # ==================== IAM ====================
    
    def iam_role(self, role_purpose: str) -> str:
        """
        Generate IAM role name.
        
        Pattern: {capability}-{env}-{role-purpose}
        """
        return f"{self.capability_name}-{self.environment}-{role_purpose}"
    
    def application_role(self) -> str:
        """Get the application IAM role name."""
        return self.iam_role("app-role")
    
    def operator_role(self) -> str:
        """Get the operator IAM role name."""
        return self.iam_role("operator-role")
    
    # ==================== Kubernetes ====================
    
    def kubernetes_namespace(self) -> str:
        """
        Generate Kubernetes namespace name.
        
        Pattern: {capability}-{env}
        """
        return f"{self.capability_name}-{self.environment}"
    
    def kubernetes_service_account(self, component: str = "app") -> str:
        """
        Generate Kubernetes ServiceAccount name.
        
        Pattern: {capability}-{env}-{component}-role-sa
        """
        return f"{self.capability_name}-{self.environment}-{component}-role-sa"
    
    def kubernetes_deployment(self, component: str) -> str:
        """
        Generate Kubernetes Deployment name.
        
        Pattern: {capability}-{env}-{component}
        """
        return f"{self.capability_name}-{self.environment}-{component}"
    
    def kubernetes_service(self, component: str) -> str:
        """
        Generate Kubernetes Service name.
        
        Pattern: {capability}-{env}-{component}-svc
        """
        return f"{self.capability_name}-{self.environment}-{component}-svc"
    
    def kubernetes_ingress(self, component: str = "app") -> str:
        """
        Generate Kubernetes Ingress name.
        
        Pattern: {capability}-{env}-{component}-ingress
        """
        return f"{self.capability_name}-{self.environment}-{component}-ingress"
    
    # ==================== AWS Tags ====================
    
    def aws_tags(self) -> list:
        """Standard AWS resource tags applied to all provisioned resources."""
        return [
            {"Key": "Capability", "Value": self.capability_name},
            {"Key": "Environment", "Value": self.environment},
            {"Key": "managed-by", "Value": "nexus-operator"},
        ]
    
    def aws_tags_dict(self) -> dict:
        """Standard tags as a dict (for APIs that use {Key: Value} format like Cognito, Glue)."""
        return {t["Key"]: t["Value"] for t in self.aws_tags()}
    
    # ==================== CloudWatch ====================
    
    def log_group(self) -> str:
        """
        Generate CloudWatch log group name.
        
        Pattern: /nexus/{capability}/{env}
        """
        return f"/nexus/{self.capability_name}/{self.environment}"
    
    def log_stream_prefix(self, component: str) -> str:
        """
        Generate CloudWatch log stream prefix.
        
        Pattern: {component}/
        """
        return f"{component}/"
