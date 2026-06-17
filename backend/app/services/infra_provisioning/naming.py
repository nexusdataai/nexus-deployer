"""
Resource naming utilities for call-processing capability.

All resources follow the naming convention from the infrastructure requirements:
- AWS resources: call-processing-{env}-{resource-name}
- SSM parameters: /call-processing/{env}/{category}/{name}
- Secrets: call-processing/{env}/{name}
- CloudWatch: /aws/call-processing/{env}
"""

from typing import List


class ResourceNaming:
    """Generates resource names following the naming convention."""
    
    CAPABILITY = "call-processing"
    
    def __init__(self, environment: str):
        """
        Initialize the naming utility.
        
        Args:
            environment: Target environment (dev, stage, test, prod)
        """
        self.env = environment
        self.capability = self.CAPABILITY
    
    # ==================== DynamoDB Tables ====================
    
    def transformation_system_table(self) -> str:
        """Get the transformation-system table name."""
        return f"{self.capability}-{self.env}-transformation-system"
    
    def license_table(self) -> str:
        """Get the license table name."""
        return f"{self.capability}-{self.env}-license"
    
    def foundry_workspace_table(self) -> str:
        """Get the foundry workspace table name (Solutions, Views, Dashboards, Tools, Data Planes, Connectors, Mapping Rules, VDL Entities)."""
        return f"{self.capability}-{self.env}-foundry-workspace"

    def control_plane_audit_table(self) -> str:
        """Get the control-plane audit table name (agent tool-call audit trail)."""
        return f"{self.capability}-{self.env}-control-plane-audit"

    def rbac_table(self) -> str:
        """Get the RBAC config table name."""
        return f"{self.capability}-{self.env}-rbac"

    def all_dynamodb_tables(self) -> List[str]:
        """Get all DynamoDB table names."""
        return [
            self.transformation_system_table(),
            self.license_table(),
            self.foundry_workspace_table(),
            self.control_plane_audit_table(),
            self.rbac_table(),
        ]
    
    # ==================== S3 Buckets ====================
    
    def wxcc_simulator_bucket(self) -> str:
        """Get the WXCC simulator bucket name."""
        return f"{self.capability}-{self.env}-wxcc-simulator"
    
    def sfdc_simulator_bucket(self) -> str:
        """Get the SFDC simulator bucket name."""
        return f"{self.capability}-{self.env}-sfdc-simulator"
    
    def oracle_erp_simulator_bucket(self) -> str:
        """Get the Oracle ERP simulator bucket name."""
        return f"{self.capability}-{self.env}-oracle-erp-simulator"
    
    def sap_simulator_bucket(self) -> str:
        """Get the SAP simulator bucket name."""
        return f"{self.capability}-{self.env}-sap-simulator"
    
    def journey_logs_bucket(self) -> str:
        """Get the journey logs bucket name."""
        return f"{self.capability}-{self.env}-journey-logs"
    
    def journey_reports_bucket(self) -> str:
        """Get the journey reports bucket name."""
        return f"{self.capability}-{self.env}-journey-reports"
    
    def all_s3_buckets(self) -> List[str]:
        """Get all S3 bucket names."""
        return [
            self.wxcc_simulator_bucket(),
            self.sfdc_simulator_bucket(),
            self.oracle_erp_simulator_bucket(),
            self.sap_simulator_bucket(),
            self.journey_logs_bucket(),
            self.journey_reports_bucket(),
        ]
    
    # ==================== S3 Folder Structures ====================
    
    def wxcc_simulator_folders(self) -> List[str]:
        """Get folder structure for wxcc-simulator bucket."""
        return [
            "wxcc-simulator/tasks/",
            "wxcc-simulator/recordings/",
            "wxcc-simulator/sample-recordings/",
        ]
    
    # ==================== SSM Parameters ====================
    
    def ssm_parameter(self, category: str, name: str) -> str:
        """
        Get SSM parameter path.
        
        Args:
            category: Parameter category (aws, server, cognito, etc.)
            name: Parameter name
            
        Returns:
            Full parameter path
        """
        return f"/{self.capability}/{self.env}/{category}/{name}"
    
    def ssm_parameter_prefix(self, category: str = None) -> str:
        """
        Get SSM parameter prefix for listing.
        
        Args:
            category: Optional category to filter by
            
        Returns:
            Parameter path prefix
        """
        if category:
            return f"/{self.capability}/{self.env}/{category}/"
        return f"/{self.capability}/{self.env}/"
    
    # ==================== Secrets ====================
    
    def secret(self, name: str) -> str:
        """
        Get secret name.
        
        Args:
            name: Secret name (api-keys, wxcc, openai, etc.)
            
        Returns:
            Full secret name
        """
        return f"{self.capability}/{self.env}/{name}"
    
    def all_secrets(self) -> List[str]:
        """Get all secret names."""
        return [
            self.secret("api-keys"),
            self.secret("wxcc"),
            self.secret("openai"),
            self.secret("license"),
            self.secret("anthropic"),
            self.secret("github"),
        ]
    
    # ==================== Glue ====================
    
    def glue_database(self) -> str:
        """Get the Glue analytics database name."""
        return f"{self.capability}-{self.env}-analytics"
    
    # ==================== CloudWatch ====================
    
    def log_group(self) -> str:
        """Get the CloudWatch log group name."""
        return f"/aws/{self.capability}/{self.env}"
