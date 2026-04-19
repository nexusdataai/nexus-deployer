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
    
    def wxcc_task_tracking_table(self) -> str:
        """Get the WXCC task tracking table name."""
        return f"{self.capability}-{self.env}-wxcc-task-tracking"
    
    def lead_opportunity_tracking_table(self) -> str:
        """Get the lead/opportunity tracking table name."""
        return f"{self.capability}-{self.env}-lead-opportunity-tracking"
    
    def all_dynamodb_tables(self) -> List[str]:
        """Get all DynamoDB table names."""
        return [
            self.transformation_system_table(),
            self.license_table(),
            self.wxcc_task_tracking_table(),
            self.lead_opportunity_tracking_table(),
        ]
    
    # ==================== S3 Buckets ====================
    
    def call_data_bucket(self) -> str:
        """Get the call-data bucket name."""
        return f"{self.capability}-{self.env}-call-data"
    
    def wxcc_simulator_bucket(self) -> str:
        """Get the WXCC simulator bucket name."""
        return f"{self.capability}-{self.env}-wxcc-simulator"
    
    def journey_logs_bucket(self) -> str:
        """Get the journey logs bucket name."""
        return f"{self.capability}-{self.env}-journey-logs"
    
    def journey_reports_bucket(self) -> str:
        """Get the journey reports bucket name."""
        return f"{self.capability}-{self.env}-journey-reports"
    
    def all_s3_buckets(self) -> List[str]:
        """Get all S3 bucket names."""
        return [
            self.call_data_bucket(),
            self.wxcc_simulator_bucket(),
            self.journey_logs_bucket(),
            self.journey_reports_bucket(),
        ]
    
    # ==================== S3 Folder Structures ====================
    
    def call_data_folders(self) -> List[str]:
        """Get folder structure for call-data bucket."""
        return [
            "call-data/",
            "call-detail/",
            "recordings/",
            "transcripts/",
            "athena-results/",
        ]
    
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
    
    def glue_table(self) -> str:
        """Get the Glue wxcc_calls table name."""
        return "wxcc_calls"
    
    def glue_table_location(self) -> str:
        """Get the S3 location for the Glue table."""
        return f"s3://{self.call_data_bucket()}/call-data/"
    
    # ==================== CloudWatch ====================
    
    def log_group(self) -> str:
        """Get the CloudWatch log group name."""
        return f"/aws/{self.capability}/{self.env}"
