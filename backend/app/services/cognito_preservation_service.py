"""
Cognito Preservation Service

Manages Cognito User Pool preservation during update workflows.
Retrieves existing outputs, validates User Pool accessibility,
and determines whether Cognito should be preserved or updated.
"""
import logging
import boto3
from typing import Optional, Dict, Any, List
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.models.cognito_models import CognitoOutputs, CognitoValidationResult
from app.models.workflow_classification import WorkflowType


logger = logging.getLogger(__name__)


class CognitoPreservationService:
    """
    Service for managing Cognito User Pool preservation during updates.
    """

    # Cognito stack type identifier
    COGNITO_STACK_TYPE = "frontend-cognito"

    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize the Cognito preservation service.
        
        Args:
            credentials: Optional AWS credentials dict with keys:
                - aws_access_key_id
                - aws_secret_access_key
                - aws_session_token (optional)
        """
        self.credentials = credentials or {}
        self._clients_cache: Dict[str, Any] = {}

    def _get_client(self, service: str, region: str) -> Any:
        """
        Get a boto3 client for the specified service and region.
        
        Args:
            service: AWS service name (e.g., 'cognito-idp', 'cloudformation')
            region: AWS region
            
        Returns:
            boto3 client
        """
        cache_key = f"{service}:{region}"
        
        if cache_key not in self._clients_cache:
            kw = {"region_name": region, **self.credentials}
            self._clients_cache[cache_key] = boto3.client(
                service, **merge_vpc_boto3_kwargs(service, region, kw)
            )
        
        return self._clients_cache[cache_key]

    def get_existing_cognito_outputs(
        self,
        stack_name: str,
        region: str
    ) -> Optional[CognitoOutputs]:
        """
        Retrieve existing Cognito outputs from a deployed CloudFormation stack.
        
        Args:
            stack_name: Name of the Cognito CloudFormation stack
            region: AWS region where the stack is deployed
            
        Returns:
            CognitoOutputs if stack exists and has outputs, None otherwise
        """
        try:
            cfn_client = self._get_client('cloudformation', region)
            
            response = cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get('Stacks', [])
            
            if not stacks:
                logger.warning(f"Cognito stack {stack_name} not found in region {region}")
                return None
            
            stack = stacks[0]
            outputs = stack.get('Outputs', [])
            
            # Convert outputs list to dict
            outputs_dict = {o['OutputKey']: o['OutputValue'] for o in outputs}
            
            # Extract required Cognito outputs
            user_pool_id = outputs_dict.get('UserPoolId')
            user_pool_client_id = outputs_dict.get('UserPoolClientId')
            user_pool_domain = outputs_dict.get('UserPoolDomain')
            
            if not user_pool_id or not user_pool_client_id:
                logger.warning(
                    f"Cognito stack {stack_name} missing required outputs: "
                    f"UserPoolId={user_pool_id}, UserPoolClientId={user_pool_client_id}"
                )
                return None
            
            cognito_outputs = CognitoOutputs(
                user_pool_id=user_pool_id,
                user_pool_client_id=user_pool_client_id,
                user_pool_domain=user_pool_domain or "",
                region=region,
                admin_user_email=outputs_dict.get('AdminUserEmail'),
                callback_url=outputs_dict.get('CallbackURL')
            )
            
            logger.info(
                f"[COGNITO] Retrieved existing outputs from {stack_name}: "
                f"UserPoolId={user_pool_id}"
            )
            
            return cognito_outputs
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'ValidationError' or 'does not exist' in str(e).lower():
                logger.info(f"Cognito stack {stack_name} does not exist")
                return None
            
            logger.error(f"Error retrieving Cognito outputs from {stack_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving Cognito outputs: {e}")
            return None

    def validate_user_pool(
        self,
        user_pool_id: str,
        client_id: str,
        region: str
    ) -> CognitoValidationResult:
        """
        Validate that a Cognito User Pool is accessible and functional.
        
        Checks:
        1. User Pool exists and is accessible
        2. App Client is configured correctly
        3. Counts users in the pool
        
        Args:
            user_pool_id: Cognito User Pool ID
            client_id: Cognito App Client ID
            region: AWS region
            
        Returns:
            CognitoValidationResult with validation status
        """
        user_pool_accessible = False
        client_configured = False
        user_count = 0
        error_message = None
        remediation_steps = []
        
        try:
            cognito_client = self._get_client('cognito-idp', region)
            
            # Check User Pool accessibility
            try:
                pool_response = cognito_client.describe_user_pool(
                    UserPoolId=user_pool_id
                )
                user_pool_accessible = True
                
                # Get estimated user count
                user_pool_info = pool_response.get('UserPool', {})
                user_count = user_pool_info.get('EstimatedNumberOfUsers', 0)
                
                logger.info(
                    f"[COGNITO] User Pool {user_pool_id} accessible, "
                    f"estimated users: {user_count}"
                )
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                error_message = f"User Pool not accessible: {error_code}"
                remediation_steps.append(
                    "Verify AWS credentials have cognito-idp:DescribeUserPool permission"
                )
                remediation_steps.append(
                    f"Check if User Pool {user_pool_id} exists in region {region}"
                )
                logger.error(f"[COGNITO] User Pool validation failed: {e}")
            
            # Check App Client configuration
            if user_pool_accessible:
                try:
                    client_response = cognito_client.describe_user_pool_client(
                        UserPoolId=user_pool_id,
                        ClientId=client_id
                    )
                    client_configured = True
                    
                    client_info = client_response.get('UserPoolClient', {})
                    logger.info(
                        f"[COGNITO] App Client {client_id} configured: "
                        f"name={client_info.get('ClientName')}"
                    )
                    
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')
                    if not error_message:
                        error_message = f"App Client not configured: {error_code}"
                    remediation_steps.append(
                        f"Check if App Client {client_id} exists in User Pool {user_pool_id}"
                    )
                    logger.error(f"[COGNITO] App Client validation failed: {e}")
            
        except Exception as e:
            error_message = f"Unexpected validation error: {str(e)}"
            remediation_steps.append("Check AWS credentials and network connectivity")
            logger.error(f"[COGNITO] Unexpected validation error: {e}")
        
        is_valid = user_pool_accessible and client_configured
        
        return CognitoValidationResult(
            is_valid=is_valid,
            user_pool_accessible=user_pool_accessible,
            client_configured=client_configured,
            user_count=user_count,
            error_message=error_message,
            remediation_steps=remediation_steps if remediation_steps else None
        )

    def should_preserve_cognito(
        self,
        workflow_type: WorkflowType,
        include_cognito_update: bool = False
    ) -> bool:
        """
        Determine if Cognito should be preserved based on workflow type and user choice.
        
        Preservation Rules:
        1. INSTALL workflow → Never preserve (always create new)
        2. UPDATE workflow + include_cognito_update=False → Preserve
        3. UPDATE workflow + include_cognito_update=True → Don't preserve (update)
        
        Args:
            workflow_type: The classified workflow type
            include_cognito_update: Whether user chose to include Cognito in update
            
        Returns:
            True if Cognito should be preserved (skipped during deployment)
        """
        # Install workflow never preserves
        if workflow_type == WorkflowType.INSTALL:
            logger.info("[COGNITO] Install workflow - Cognito will be created fresh")
            return False
        
        # Update workflow - check user preference
        if workflow_type == WorkflowType.UPDATE:
            if include_cognito_update:
                logger.info("[COGNITO] Update workflow with Cognito update - will update Cognito stack")
                return False
            else:
                logger.info("[COGNITO] Update workflow - preserving Cognito to protect user data")
                return True
        
        # Default to preserve for safety
        logger.warning("[COGNITO] Unknown workflow type - defaulting to preserve")
        return True

    def get_stacks_to_skip(
        self,
        workflow_type: WorkflowType,
        include_cognito_update: bool = False
    ) -> List[str]:
        """
        Get list of stack types to skip during deployment.
        
        Args:
            workflow_type: The classified workflow type
            include_cognito_update: Whether user chose to include Cognito in update
            
        Returns:
            List of stack type identifiers to skip
        """
        stacks_to_skip = []
        
        if self.should_preserve_cognito(workflow_type, include_cognito_update):
            stacks_to_skip.append(self.COGNITO_STACK_TYPE)
        
        return stacks_to_skip

    def verify_cognito_accessible(
        self,
        cognito_outputs: CognitoOutputs
    ) -> CognitoValidationResult:
        """
        Verify that the Cognito User Pool from preserved outputs is accessible.
        
        This should be called before proceeding with update workflow to ensure
        the preserved Cognito is still functional.
        
        Args:
            cognito_outputs: Previously retrieved Cognito outputs
            
        Returns:
            CognitoValidationResult with accessibility status
        """
        return self.validate_user_pool(
            user_pool_id=cognito_outputs.user_pool_id,
            client_id=cognito_outputs.user_pool_client_id,
            region=cognito_outputs.region
        )


def get_cognito_preservation_service(
    credentials: Optional[Dict[str, str]] = None
) -> CognitoPreservationService:
    """
    Factory function to create a CognitoPreservationService instance.
    
    Args:
        credentials: Optional AWS credentials
        
    Returns:
        Configured CognitoPreservationService instance
    """
    return CognitoPreservationService(credentials=credentials)
