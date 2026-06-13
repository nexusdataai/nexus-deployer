"""
Provisioning Orchestrator for call-processing capability.

Central coordinator that manages the provisioning workflow for all
infrastructure resources including DynamoDB, S3, SSM, Secrets, Glue,
and CloudWatch.
"""

import logging
from datetime import datetime
from typing import List, Optional, Callable

from .models import (
    ResourceStatus,
    ResourceStatusType,
    ProvisioningReport,
    VerificationReport,
    VALID_ENVIRONMENTS,
)
from .naming import ResourceNaming
from .dynamodb_provisioner import DynamoDBProvisioner
from .s3_provisioner import S3Provisioner
from .ssm_provisioner import SSMProvisioner
from .secrets_provisioner import SecretsProvisioner
from .glue_provisioner import GlueProvisioner
from .cloudwatch_provisioner import CloudWatchProvisioner
from .exceptions import InvalidEnvironmentError

logger = logging.getLogger(__name__)


class ProvisioningOrchestrator:
    """Orchestrates the provisioning of all call-processing infrastructure."""
    
    def __init__(
        self,
        environment: str,
        region: str = "us-east-1",
        dry_run: bool = False,
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        credentials: Optional[dict] = None,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            environment: Target environment (dev, stage, test, prod)
            region: AWS region
            dry_run: If True, validate without creating resources
            endpoint_url: Optional endpoint URL for LocalStack
            progress_callback: Optional callback for real-time progress updates
            credentials: Optional AWS credentials dict with keys:
                - aws_access_key_id
                - aws_secret_access_key
                - aws_session_token (optional)
        """
        if environment not in VALID_ENVIRONMENTS:
            raise InvalidEnvironmentError(environment, list(VALID_ENVIRONMENTS))
        
        self.environment = environment
        self.region = region
        self.dry_run = dry_run
        self.endpoint_url = endpoint_url
        self.naming = ResourceNaming(environment)
        self.progress_callback = progress_callback
        self.credentials = credentials
        
        # Initialize provisioners
        self._init_provisioners()
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def _init_provisioners(self):
        """Initialize all provisioner instances with fresh boto3 sessions."""
        # Force boto3 to pick up fresh credentials from environment
        # by creating a new session explicitly
        import boto3
        
        # Create a fresh session that will read current environment variables
        fresh_session = boto3.Session(
            region_name=self.region,
        )
        
        self.dynamodb = DynamoDBProvisioner(
            self.environment, self.region, self.endpoint_url, self.progress_callback,
            boto3_session=fresh_session
        )
        self.s3 = S3Provisioner(
            self.environment, self.region, self.endpoint_url, self.progress_callback,
            boto3_session=fresh_session
        )
        self.ssm = SSMProvisioner(
            self.environment, self.region, self.endpoint_url, self.progress_callback,
            boto3_session=fresh_session
        )
        self.secrets = SecretsProvisioner(
            self.environment, self.region, self.endpoint_url, self.progress_callback,
            boto3_session=fresh_session
        )
        self.glue = GlueProvisioner(
            self.environment, self.region, self.endpoint_url, self.progress_callback,
            boto3_session=fresh_session
        )
        self.cloudwatch = CloudWatchProvisioner(
            self.environment, self.region, self.endpoint_url, self.progress_callback,
            boto3_session=fresh_session
        )
    
    def provision_all(self) -> ProvisioningReport:
        """
        Provision all infrastructure resources.
        
        NOTE: S3 buckets and DynamoDB tables are created by CloudFormation (storage-stack.yaml)
        to provide better lifecycle management, rollback, and drift detection.
        This orchestrator only provisions SSM parameters, Secrets, Glue, and CloudWatch resources.
        
        Returns:
            ProvisioningReport with status of all resources
        """
        started_at = datetime.utcnow()
        all_results: List[ResourceStatus] = []
        
        self._log_progress(f"Starting provisioning for environment: {self.environment}")
        self._log_progress(f"Dry run mode: {self.dry_run}")
        
        if self.dry_run:
            # In dry-run mode, just validate and return what would be created
            all_results = self._get_dry_run_results()
        else:
            # NOTE: S3 and DynamoDB are provisioned by CloudFormation storage-stack.yaml
            # This avoids duplicate resource creation and provides better lifecycle management
            self._log_progress("")
            self._log_progress("[i]️ S3 buckets and DynamoDB tables are managed by CloudFormation")
            
            # Provision only resources NOT managed by CloudFormation
            self._log_progress("")
            self._log_progress("⚙️ Step 1/4: Provisioning SSM parameters...")
            all_results.extend(self.provision_ssm())
            
            self._log_progress("")
            self._log_progress("[LOCK] Step 2/4: Provisioning Secrets Manager secrets...")
            all_results.extend(self.provision_secrets())
            
            self._log_progress("")
            self._log_progress("[CHART] Step 3/4: Provisioning Glue resources...")
            all_results.extend(self.provision_glue())
            
            self._log_progress("")
            self._log_progress("[NOTE] Step 4/4: Provisioning CloudWatch log groups...")
            all_results.extend(self.provision_cloudwatch())
        
        completed_at = datetime.utcnow()
        
        report = ProvisioningReport(
            environment=self.environment,
            region=self.region,
            started_at=started_at,
            completed_at=completed_at,
            dry_run=self.dry_run,
            resources=all_results,
        )
        
        self._log_progress("")
        self._log_progress(f"Provisioning completed. Success: {report.overall_success}")
        self._log_progress(f"Created: {report.success_count}, Already existed: {report.already_existed_count}, Failed: {report.failed_count}")
        
        return report
    
    def _get_dry_run_results(self) -> List[ResourceStatus]:
        """
        Get results for dry-run mode without creating resources.
        
        NOTE: S3 buckets and DynamoDB tables are managed by CloudFormation,
        so they are not included in the dry-run results.
        
        Returns:
            List of ResourceStatus showing what would be created
        """
        results = []
        
        # NOTE: DynamoDB tables and S3 buckets are managed by CloudFormation (storage-stack.yaml)
        # They are not provisioned by this orchestrator
        
        # SSM parameters
        for path in self.ssm.get_all_parameter_paths():
            results.append(ResourceStatus(
                resource_type=self.ssm.create_parameter.__annotations__.get('return', None) or ResourceStatus,
                resource_name=path,
                status=ResourceStatusType.SKIPPED,
                message=f"[DRY RUN] Would create SSM parameter: {path}",
            ))
        
        # Secrets
        for secret_name in self.secrets.get_all_secret_names():
            results.append(ResourceStatus(
                resource_type=self.secrets.create_secret.__annotations__.get('return', None) or ResourceStatus,
                resource_name=secret_name,
                status=ResourceStatusType.SKIPPED,
                message=f"[DRY RUN] Would create secret: {secret_name}",
            ))
        
        # Glue database
        results.append(ResourceStatus(
            resource_type=self.glue.create_database.__annotations__.get('return', None) or ResourceStatus,
            resource_name=self.naming.glue_database(),
            status=ResourceStatusType.SKIPPED,
            message=f"[DRY RUN] Would create Glue database: {self.naming.glue_database()}",
        ))
        
        # CloudWatch log group
        results.append(ResourceStatus(
            resource_type=self.cloudwatch.create_log_group.__annotations__.get('return', None) or ResourceStatus,
            resource_name=self.naming.log_group(),
            status=ResourceStatusType.SKIPPED,
            message=f"[DRY RUN] Would create CloudWatch log group: {self.naming.log_group()}",
        ))
        
        return results

    def provision_dynamodb(self) -> List[ResourceStatus]:
        """
        Provision DynamoDB tables only.
        
        Returns:
            List of ResourceStatus for each table
        """
        logger.info("Provisioning DynamoDB tables...")
        return self.dynamodb.provision_all()
    
    def provision_s3(self) -> List[ResourceStatus]:
        """
        Provision S3 buckets only.
        
        Returns:
            List of ResourceStatus for each bucket
        """
        logger.info("Provisioning S3 buckets...")
        return self.s3.provision_all()
    
    def provision_ssm(self) -> List[ResourceStatus]:
        """
        Provision SSM parameters only.
        
        Returns:
            List of ResourceStatus for each parameter
        """
        logger.info("Provisioning SSM parameters...")
        return self.ssm.provision_all()
    
    def provision_secrets(self) -> List[ResourceStatus]:
        """
        Provision Secrets Manager secrets only.
        
        Returns:
            List of ResourceStatus for each secret
        """
        logger.info("Provisioning Secrets Manager secrets...")
        return self.secrets.provision_all()
    
    def provision_glue(self) -> List[ResourceStatus]:
        """
        Provision Glue database and tables only.
        
        Returns:
            List of ResourceStatus for each resource
        """
        logger.info("Provisioning Glue resources...")
        return self.glue.provision_all()
    
    def provision_cloudwatch(self) -> List[ResourceStatus]:
        """
        Provision CloudWatch log groups only.
        
        Returns:
            List of ResourceStatus for each log group
        """
        logger.info("Provisioning CloudWatch log groups...")
        return self.cloudwatch.provision_all()
    
    def verify_all(self) -> VerificationReport:
        """
        Verify all provisioned resources.
        
        Returns:
            VerificationReport with status of all resources
        """
        # Import here to avoid circular imports
        from .verification_service import VerificationService
        
        verifier = VerificationService(
            self.environment, self.region, self.endpoint_url,
            credentials=self.credentials
        )
        return verifier.verify_all()
