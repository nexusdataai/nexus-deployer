"""
Pre-Deployment Checklist Service
Verifies all prerequisites before deployment.

Provides:
- AWS credentials verification
- Region access verification
- Template file existence checks
- Secrets Manager verification
- SSM Parameter verification
- Comprehensive checklist execution

Feature: deployment-prerequisites-verification
Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
from enum import Enum


logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """Status of a checklist item."""
    PASSED = 'passed'
    FAILED = 'failed'
    SKIPPED = 'skipped'
    WARNING = 'warning'


@dataclass
class CheckResult:
    """Result of a single checklist item."""
    name: str
    status: CheckStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    remediation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'name': self.name,
            'status': self.status.value,
            'message': self.message,
            'details': self.details,
            'remediation': self.remediation
        }


@dataclass
class ChecklistResult:
    """Result of running the complete checklist."""
    success: bool
    checks: List[CheckResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    skipped: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'checks': [c.to_dict() for c in self.checks],
            'passed': self.passed,
            'failed': self.failed,
            'warnings': self.warnings,
            'skipped': self.skipped
        }
    
    def add_check(self, check: CheckResult):
        """Add a check result and update counts."""
        self.checks.append(check)
        if check.status == CheckStatus.PASSED:
            self.passed += 1
        elif check.status == CheckStatus.FAILED:
            self.failed += 1
        elif check.status == CheckStatus.WARNING:
            self.warnings += 1
        else:
            self.skipped += 1


class PreDeploymentChecklist:
    """Verifies all prerequisites before deployment."""
    
    def check_aws_credentials(
        self,
        credentials: Optional[Dict[str, str]] = None
    ) -> CheckResult:
        """
        Verify AWS credentials are valid.
        
        Args:
            credentials: Optional explicit credentials
            
        Returns:
            CheckResult with credential status
        """
        try:
            import boto3
            from botocore.exceptions import NoCredentialsError, ClientError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            sts = session.client('sts')
            
            identity = sts.get_caller_identity()
            
            return CheckResult(
                name='AWS Credentials',
                status=CheckStatus.PASSED,
                message=f"Valid credentials for account {identity.get('Account')}",
                details={
                    'account': identity.get('Account'),
                    'arn': identity.get('Arn'),
                    'user_id': identity.get('UserId')
                }
            )
            
        except NoCredentialsError:
            return CheckResult(
                name='AWS Credentials',
                status=CheckStatus.FAILED,
                message="No AWS credentials found",
                remediation="Configure AWS credentials via environment variables, ~/.aws/credentials, or IAM role"
            )
        except ClientError as e:
            return CheckResult(
                name='AWS Credentials',
                status=CheckStatus.FAILED,
                message=f"Invalid AWS credentials: {e.response['Error']['Message']}",
                remediation="Check that your AWS credentials are valid and not expired"
            )
        except Exception as e:
            return CheckResult(
                name='AWS Credentials',
                status=CheckStatus.SKIPPED,
                message=f"Could not verify credentials: {str(e)}",
                remediation="Ensure boto3 is installed and AWS is accessible"
            )
    
    def check_region_access(
        self,
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> CheckResult:
        """
        Verify access to the specified AWS region.
        
        Args:
            region: AWS region to check
            credentials: Optional explicit credentials
            
        Returns:
            CheckResult with region access status
        """
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            ec2 = session.client('ec2', region_name=region)
            
            # Simple API call to verify region access
            ec2.describe_availability_zones()
            
            return CheckResult(
                name='Region Access',
                status=CheckStatus.PASSED,
                message=f"Access to region {region} confirmed",
                details={'region': region}
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AuthFailure':
                return CheckResult(
                    name='Region Access',
                    status=CheckStatus.FAILED,
                    message=f"Not authorized to access region {region}",
                    remediation="Check IAM permissions for the target region"
                )
            elif error_code == 'InvalidRegion':
                return CheckResult(
                    name='Region Access',
                    status=CheckStatus.FAILED,
                    message=f"Invalid region: {region}",
                    remediation="Use a valid AWS region code (e.g., us-east-1, eu-west-1)"
                )
            else:
                return CheckResult(
                    name='Region Access',
                    status=CheckStatus.WARNING,
                    message=f"Region check returned: {e.response['Error']['Message']}",
                    details={'error_code': error_code}
                )
        except Exception as e:
            return CheckResult(
                name='Region Access',
                status=CheckStatus.SKIPPED,
                message=f"Could not verify region access: {str(e)}"
            )
    
    def check_templates_exist(
        self,
        template_paths: List[Path]
    ) -> CheckResult:
        """
        Verify all template files exist.
        
        Args:
            template_paths: List of template file paths
            
        Returns:
            CheckResult with template existence status
        """
        missing = []
        found = []
        
        for path in template_paths:
            if path.exists():
                found.append(str(path))
            else:
                missing.append(str(path))
        
        if missing:
            return CheckResult(
                name='Template Files',
                status=CheckStatus.FAILED,
                message=f"Missing {len(missing)} template files",
                details={'missing': missing, 'found': found},
                remediation="Ensure all template files are present in the templates directory"
            )
        
        return CheckResult(
            name='Template Files',
            status=CheckStatus.PASSED,
            message=f"All {len(found)} template files found",
            details={'found': found}
        )
    
    def check_secrets_exist(
        self,
        secret_names: List[str],
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> CheckResult:
        """
        Verify required secrets exist in Secrets Manager.
        
        Args:
            secret_names: List of secret names to check
            region: AWS region
            credentials: Optional explicit credentials
            
        Returns:
            CheckResult with secrets status
        """
        if not secret_names:
            return CheckResult(
                name='Secrets Manager',
                status=CheckStatus.SKIPPED,
                message="No secrets to verify"
            )
        
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            sm = session.client('secretsmanager', region_name=region)
            
            missing = []
            found = []
            
            for secret_name in secret_names:
                try:
                    sm.describe_secret(SecretId=secret_name)
                    found.append(secret_name)
                except ClientError as e:
                    if e.response['Error']['Code'] == 'ResourceNotFoundException':
                        missing.append(secret_name)
                    else:
                        missing.append(f"{secret_name} (access denied)")
            
            if missing:
                return CheckResult(
                    name='Secrets Manager',
                    status=CheckStatus.FAILED,
                    message=f"Missing {len(missing)} required secrets",
                    details={'missing': missing, 'found': found},
                    remediation="Create the missing secrets in AWS Secrets Manager"
                )
            
            return CheckResult(
                name='Secrets Manager',
                status=CheckStatus.PASSED,
                message=f"All {len(found)} required secrets found",
                details={'found': found}
            )
            
        except Exception as e:
            return CheckResult(
                name='Secrets Manager',
                status=CheckStatus.SKIPPED,
                message=f"Could not verify secrets: {str(e)}"
            )
    
    def check_ssm_parameters(
        self,
        parameter_names: List[str],
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> CheckResult:
        """
        Verify required SSM parameters exist.
        
        Args:
            parameter_names: List of SSM parameter names to check
            region: AWS region
            credentials: Optional explicit credentials
            
        Returns:
            CheckResult with SSM parameter status
        """
        if not parameter_names:
            return CheckResult(
                name='SSM Parameters',
                status=CheckStatus.SKIPPED,
                message="No SSM parameters to verify"
            )
        
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            ssm = session.client('ssm', region_name=region)
            
            missing = []
            found = []
            
            # SSM GetParameters can check up to 10 at a time
            for i in range(0, len(parameter_names), 10):
                batch = parameter_names[i:i+10]
                try:
                    response = ssm.get_parameters(Names=batch)
                    found.extend([p['Name'] for p in response.get('Parameters', [])])
                    missing.extend(response.get('InvalidParameters', []))
                except ClientError:
                    missing.extend(batch)
            
            if missing:
                return CheckResult(
                    name='SSM Parameters',
                    status=CheckStatus.FAILED,
                    message=f"Missing {len(missing)} required SSM parameters",
                    details={'missing': missing, 'found': found},
                    remediation="Create the missing parameters in AWS Systems Manager Parameter Store"
                )
            
            return CheckResult(
                name='SSM Parameters',
                status=CheckStatus.PASSED,
                message=f"All {len(found)} required SSM parameters found",
                details={'found': found}
            )
            
        except Exception as e:
            return CheckResult(
                name='SSM Parameters',
                status=CheckStatus.SKIPPED,
                message=f"Could not verify SSM parameters: {str(e)}"
            )

    def check_cloudformation_permissions(
        self,
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> CheckResult:
        """
        Verify CloudFormation permissions.
        
        Args:
            region: AWS region
            credentials: Optional explicit credentials
            
        Returns:
            CheckResult with CloudFormation permission status
        """
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            cfn = session.client('cloudformation', region_name=region)
            
            # Try to list stacks - requires cloudformation:ListStacks
            cfn.list_stacks(StackStatusFilter=['CREATE_COMPLETE'])
            
            return CheckResult(
                name='CloudFormation Permissions',
                status=CheckStatus.PASSED,
                message="CloudFormation access confirmed",
                details={'region': region}
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDenied':
                return CheckResult(
                    name='CloudFormation Permissions',
                    status=CheckStatus.FAILED,
                    message="Insufficient CloudFormation permissions",
                    remediation="Ensure IAM role/user has cloudformation:* permissions"
                )
            else:
                return CheckResult(
                    name='CloudFormation Permissions',
                    status=CheckStatus.WARNING,
                    message=f"CloudFormation check returned: {e.response['Error']['Message']}"
                )
        except Exception as e:
            return CheckResult(
                name='CloudFormation Permissions',
                status=CheckStatus.SKIPPED,
                message=f"Could not verify CloudFormation permissions: {str(e)}"
            )
    
    def check_s3_access(
        self,
        bucket_name: Optional[str],
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> CheckResult:
        """
        Verify S3 bucket access for template storage.
        
        Args:
            bucket_name: S3 bucket name (optional)
            region: AWS region
            credentials: Optional explicit credentials
            
        Returns:
            CheckResult with S3 access status
        """
        if not bucket_name:
            return CheckResult(
                name='S3 Access',
                status=CheckStatus.SKIPPED,
                message="No S3 bucket specified"
            )
        
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            s3 = session.client('s3', region_name=region)
            
            # Check bucket exists and is accessible
            s3.head_bucket(Bucket=bucket_name)
            
            return CheckResult(
                name='S3 Access',
                status=CheckStatus.PASSED,
                message=f"S3 bucket '{bucket_name}' is accessible",
                details={'bucket': bucket_name}
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                return CheckResult(
                    name='S3 Access',
                    status=CheckStatus.FAILED,
                    message=f"S3 bucket '{bucket_name}' does not exist",
                    remediation="Create the S3 bucket or use an existing bucket"
                )
            elif error_code == '403':
                return CheckResult(
                    name='S3 Access',
                    status=CheckStatus.FAILED,
                    message=f"Access denied to S3 bucket '{bucket_name}'",
                    remediation="Check S3 bucket policy and IAM permissions"
                )
            else:
                return CheckResult(
                    name='S3 Access',
                    status=CheckStatus.WARNING,
                    message=f"S3 check returned: {e.response['Error']['Message']}"
                )
        except Exception as e:
            return CheckResult(
                name='S3 Access',
                status=CheckStatus.SKIPPED,
                message=f"Could not verify S3 access: {str(e)}"
            )
    
    def run_checklist(
        self,
        region: str,
        template_paths: Optional[List[Path]] = None,
        secret_names: Optional[List[str]] = None,
        ssm_parameters: Optional[List[str]] = None,
        s3_bucket: Optional[str] = None,
        credentials: Optional[Dict[str, str]] = None
    ) -> ChecklistResult:
        """
        Run the complete pre-deployment checklist.
        
        Args:
            region: AWS region for deployment
            template_paths: List of template file paths
            secret_names: List of required secret names
            ssm_parameters: List of required SSM parameter names
            s3_bucket: Optional S3 bucket for templates
            credentials: Optional explicit AWS credentials
            
        Returns:
            ChecklistResult with all check results
        """
        result = ChecklistResult(success=True)
        
        # 1. Check AWS credentials
        cred_check = self.check_aws_credentials(credentials)
        result.add_check(cred_check)
        
        # If credentials failed, skip AWS-dependent checks
        if cred_check.status == CheckStatus.FAILED:
            result.success = False
            return result
        
        # 2. Check region access
        region_check = self.check_region_access(region, credentials)
        result.add_check(region_check)
        
        # 3. Check CloudFormation permissions
        cfn_check = self.check_cloudformation_permissions(region, credentials)
        result.add_check(cfn_check)
        
        # 4. Check template files
        if template_paths:
            template_check = self.check_templates_exist(template_paths)
            result.add_check(template_check)
        
        # 5. Check secrets
        if secret_names:
            secrets_check = self.check_secrets_exist(secret_names, region, credentials)
            result.add_check(secrets_check)
        
        # 6. Check SSM parameters
        if ssm_parameters:
            ssm_check = self.check_ssm_parameters(ssm_parameters, region, credentials)
            result.add_check(ssm_check)
        
        # 7. Check S3 access
        if s3_bucket:
            s3_check = self.check_s3_access(s3_bucket, region, credentials)
            result.add_check(s3_check)
        
        # Determine overall success
        result.success = result.failed == 0
        
        return result


def get_pre_deployment_checklist() -> PreDeploymentChecklist:
    """Factory function to get a PreDeploymentChecklist instance."""
    return PreDeploymentChecklist()
