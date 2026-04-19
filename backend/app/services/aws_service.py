"""AWS service for credential validation and permission management."""
import re
from typing import Dict, Optional, List, Tuple
import boto3
from botocore.exceptions import ClientError, BotoCoreError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

from app.models.aws_config import (
    AWSConfiguration,
    AWSCredentials,
    Permission,
    PermissionStatus,
    RoleValidationResponse,
    AWSRegion
)


class AWSService:
    """Service for AWS operations including role validation and permission verification."""
    
    # ARN pattern for IAM roles
    ROLE_ARN_PATTERN = r'^arn:aws:iam::(\d{12}):role/([\w+=,.@-]+)$'
    
    # In-memory storage for assumed role credentials (session-scoped)
    _credentials_cache: Dict[str, AWSCredentials] = {}
    
    @staticmethod
    def validate_role_arn_format(role_arn: str) -> Tuple[bool, Optional[str]]:
        """Validate Role ARN format.
        
        Args:
            role_arn: The Role ARN to validate
            
        Returns:
            Tuple of (is_valid, account_id)
        """
        match = re.match(AWSService.ROLE_ARN_PATTERN, role_arn)
        if match:
            account_id = match.group(1)
            return True, account_id
        return False, None
    
    @staticmethod
    def assume_role(role_arn: str, region: str, session_name: str = "TotogiInstaller") -> RoleValidationResponse:
        """Assume an IAM role and validate access.
        
        Args:
            role_arn: The Role ARN to assume
            region: AWS region
            session_name: Session name for the assumed role
            
        Returns:
            RoleValidationResponse with validation results
        """
        # First validate ARN format
        is_valid_format, account_id = AWSService.validate_role_arn_format(role_arn)
        
        if not is_valid_format:
            return RoleValidationResponse(
                valid=False,
                error="Invalid Role ARN format",
                troubleshooting=[
                    "Role ARN must match pattern: arn:aws:iam::<account-id>:role/<role-name>",
                    "Example: arn:aws:iam::123456789012:role/MyDeploymentRole",
                    "Ensure there are no extra spaces or special characters"
                ]
            )
        
        try:
            # Create STS client
            sts_client = boto3.client(
                "sts", **merge_vpc_boto3_kwargs("sts", region, {"region_name": region})
            )
            
            # Attempt to assume the role
            response = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
                DurationSeconds=3600  # 1 hour
            )
            
            # Extract credentials
            credentials = response['Credentials']
            aws_credentials = AWSCredentials(
                access_key_id=credentials['AccessKeyId'],
                secret_access_key=credentials['SecretAccessKey'],
                session_token=credentials['SessionToken'],
                expiration=credentials['Expiration']
            )
            
            # Cache credentials for later use
            AWSService._credentials_cache[role_arn] = aws_credentials
            
            return RoleValidationResponse(
                valid=True,
                account_id=account_id
            )
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            troubleshooting = []
            
            if error_code == 'AccessDenied':
                troubleshooting = [
                    "The current AWS credentials do not have permission to assume this role",
                    "Ensure the role's trust policy allows your AWS account/user to assume it",
                    "Check that sts:AssumeRole permission is granted to your credentials"
                ]
            elif error_code == 'InvalidClientTokenId':
                troubleshooting = [
                    "AWS credentials are invalid or expired",
                    "Configure valid AWS credentials using AWS CLI or environment variables",
                    "Run 'aws configure' to set up credentials"
                ]
            elif error_code == 'NoSuchEntity':
                troubleshooting = [
                    "The specified role does not exist",
                    "Verify the role ARN is correct",
                    "Ensure the role exists in the specified AWS account"
                ]
            else:
                troubleshooting = [
                    f"AWS Error: {error_message}",
                    "Check AWS credentials and permissions",
                    "Verify network connectivity to AWS"
                ]
            
            return RoleValidationResponse(
                valid=False,
                error=f"{error_code}: {error_message}",
                troubleshooting=troubleshooting
            )
            
        except BotoCoreError as e:
            return RoleValidationResponse(
                valid=False,
                error=f"AWS SDK Error: {str(e)}",
                troubleshooting=[
                    "Check network connectivity",
                    "Verify AWS SDK configuration",
                    "Ensure boto3 is properly installed"
                ]
            )
        except Exception as e:
            return RoleValidationResponse(
                valid=False,
                error=f"Unexpected error: {str(e)}",
                troubleshooting=[
                    "An unexpected error occurred",
                    "Check application logs for details",
                    "Contact support if the issue persists"
                ]
            )
    
    @staticmethod
    def get_cached_credentials(role_arn: str) -> Optional[AWSCredentials]:
        """Get cached credentials for a role.
        
        Args:
            role_arn: The Role ARN
            
        Returns:
            Cached credentials if available, None otherwise
        """
        return AWSService._credentials_cache.get(role_arn)
    
    @staticmethod
    def get_aws_regions() -> List[AWSRegion]:
        """Get list of available AWS regions.
        
        Returns:
            List of AWS regions
        """
        # Common AWS regions with friendly names
        regions = [
            AWSRegion(code="us-east-1", name="US East (N. Virginia)"),
            AWSRegion(code="us-east-2", name="US East (Ohio)"),
            AWSRegion(code="us-west-1", name="US West (N. California)"),
            AWSRegion(code="us-west-2", name="US West (Oregon)"),
            AWSRegion(code="ap-south-1", name="Asia Pacific (Mumbai)"),
            AWSRegion(code="ap-northeast-1", name="Asia Pacific (Tokyo)"),
            AWSRegion(code="ap-northeast-2", name="Asia Pacific (Seoul)"),
            AWSRegion(code="ap-southeast-1", name="Asia Pacific (Singapore)"),
            AWSRegion(code="ap-southeast-2", name="Asia Pacific (Sydney)"),
            AWSRegion(code="ca-central-1", name="Canada (Central)"),
            AWSRegion(code="eu-central-1", name="Europe (Frankfurt)"),
            AWSRegion(code="eu-west-1", name="Europe (Ireland)"),
            AWSRegion(code="eu-west-2", name="Europe (London)"),
            AWSRegion(code="eu-west-3", name="Europe (Paris)"),
            AWSRegion(code="eu-north-1", name="Europe (Stockholm)"),
            AWSRegion(code="sa-east-1", name="South America (São Paulo)"),
        ]
        return regions
    
    @staticmethod
    def validate_region(region: str) -> bool:
        """Validate if a region code is valid.
        
        Args:
            region: AWS region code to validate
            
        Returns:
            True if region is valid, False otherwise
        """
        valid_regions = {r.code for r in AWSService.get_aws_regions()}
        return region in valid_regions
    
    @staticmethod
    def verify_permissions(role_arn: str, region: str, required_permissions: List[str]) -> PermissionStatus:
        """Verify IAM permissions for a role.
        
        Args:
            role_arn: The Role ARN to check
            region: AWS region
            required_permissions: List of required IAM actions
            
        Returns:
            PermissionStatus with verification results
        """
        # Get cached credentials
        credentials = AWSService.get_cached_credentials(role_arn)
        
        if credentials is None:
            # Need to assume role first
            validation_response = AWSService.assume_role(role_arn, region)
            if not validation_response.valid:
                # Return empty permission status if role assumption failed
                return PermissionStatus(
                    all_granted=False,
                    required_permissions=[],
                    missing_permissions=required_permissions,
                    iam_policy_json=None
                )
            credentials = AWSService.get_cached_credentials(role_arn)
        
        try:
            # Create IAM client with assumed role credentials
            iam_kw = {
                "region_name": region,
                "aws_access_key_id": credentials.access_key_id,
                "aws_secret_access_key": credentials.secret_access_key,
                "aws_session_token": credentials.session_token,
            }
            iam_client = boto3.client(
                "iam", **merge_vpc_boto3_kwargs("iam", region, iam_kw)
            )

            sts_client = boto3.client(
                "sts", **merge_vpc_boto3_kwargs("sts", region, dict(iam_kw))
            )
            
            # Get the assumed role ARN
            caller_identity = sts_client.get_caller_identity()
            assumed_role_arn = caller_identity['Arn']
            
            # Simulate permissions for each required action
            permissions: List[Permission] = []
            missing_permissions: List[str] = []
            
            for action in required_permissions:
                try:
                    # Simulate the policy
                    response = iam_client.simulate_principal_policy(
                        PolicySourceArn=role_arn,
                        ActionNames=[action],
                        ResourceArns=['*']
                    )
                    
                    # Check evaluation results
                    evaluation_results = response.get('EvaluationResults', [])
                    if evaluation_results:
                        result = evaluation_results[0]
                        decision = result.get('EvalDecision', 'deny')
                        granted = decision.lower() == 'allowed'
                    else:
                        granted = False
                    
                    permissions.append(Permission(
                        action=action,
                        granted=granted,
                        resource='*'
                    ))
                    
                    if not granted:
                        missing_permissions.append(action)
                        
                except ClientError as e:
                    # If simulation fails, assume permission is not granted
                    permissions.append(Permission(
                        action=action,
                        granted=False,
                        resource='*'
                    ))
                    missing_permissions.append(action)
            
            all_granted = len(missing_permissions) == 0
            
            # Generate IAM policy JSON for missing permissions
            iam_policy_json = None
            if missing_permissions:
                iam_policy_json = AWSService._generate_iam_policy(missing_permissions)
            
            return PermissionStatus(
                all_granted=all_granted,
                required_permissions=permissions,
                missing_permissions=missing_permissions,
                iam_policy_json=iam_policy_json
            )
            
        except Exception as e:
            # On error, return all permissions as not granted
            permissions = [
                Permission(action=action, granted=False, resource='*')
                for action in required_permissions
            ]
            
            return PermissionStatus(
                all_granted=False,
                required_permissions=permissions,
                missing_permissions=required_permissions,
                iam_policy_json=AWSService._generate_iam_policy(required_permissions)
            )
    
    @staticmethod
    def _generate_iam_policy(actions: List[str]) -> str:
        """Generate IAM policy JSON for a list of actions.
        
        Args:
            actions: List of IAM actions
            
        Returns:
            IAM policy JSON string
        """
        import json
        
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": actions,
                    "Resource": "*"
                }
            ]
        }
        
        return json.dumps(policy, indent=2)


# Global instance
_aws_service: Optional[AWSService] = None


def get_aws_service() -> AWSService:
    """Get the global AWS service instance.
    
    Returns:
        AWSService instance
    """
    global _aws_service
    if _aws_service is None:
        _aws_service = AWSService()
    return _aws_service
