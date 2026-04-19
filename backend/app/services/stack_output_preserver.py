"""
Stack Output Preserver Service

Manages preservation and reuse of CloudFormation stack outputs during update workflows.
Ensures Cognito outputs and other critical values are available for dependent stacks.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.models.stack_outputs import PreservedOutputs
from app.models.cognito_models import CognitoOutputs


logger = logging.getLogger(__name__)


class StackOutputPreserver:
    """
    Service for preserving and managing CloudFormation stack outputs.
    
    During update workflows, this service retrieves outputs from existing stacks
    before any modifications, ensuring values like Cognito User Pool IDs are
    available for dependent stacks.
    """

    # Stack type identifier for Cognito
    COGNITO_STACK_TYPE = "frontend-cognito"
    
    # Known Cognito output keys
    COGNITO_OUTPUT_KEYS = [
        'UserPoolId',
        'UserPoolClientId', 
        'UserPoolDomain',
        'UserPoolArn',
        'IdentityPoolId'
    ]

    def __init__(
        self,
        credentials: Optional[Dict[str, str]] = None,
        cfn_service: Optional[Any] = None
    ):
        """
        Initialize the stack output preserver.
        
        Args:
            credentials: Optional AWS credentials dict
            cfn_service: Optional CloudFormation service instance
        """
        self.credentials = credentials or {}
        self.cfn_service = cfn_service
        self._preserved_outputs: Dict[str, PreservedOutputs] = {}
        self._clients_cache: Dict[str, Any] = {}

    def _get_client(self, service: str, region: str) -> Any:
        """Get a boto3 client for the specified service and region."""
        cache_key = f"{service}:{region}"
        
        if cache_key not in self._clients_cache:
            kw = {"region_name": region, **self.credentials}
            self._clients_cache[cache_key] = boto3.client(
                service, **merge_vpc_boto3_kwargs(service, region, kw)
            )
        
        return self._clients_cache[cache_key]

    def preserve_all_outputs(
        self,
        capability_name: str,
        environment: str,
        region: str,
        stack_names: Optional[List[str]] = None
    ) -> Dict[str, PreservedOutputs]:
        """
        Retrieve and store outputs from all existing stacks.
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev, stage, prod)
            region: AWS region
            stack_names: Optional list of specific stack names to preserve
            
        Returns:
            Dict mapping stack names to PreservedOutputs
        """
        self._preserved_outputs.clear()
        
        try:
            cfn_client = self._get_client('cloudformation', region)
            
            # Get stacks to preserve
            if stack_names:
                stacks_to_check = stack_names
            else:
                stacks_to_check = self._discover_capability_stacks(
                    cfn_client, capability_name, environment
                )
            
            for stack_name in stacks_to_check:
                try:
                    preserved = self._preserve_stack_outputs(
                        cfn_client=cfn_client,
                        stack_name=stack_name,
                        capability_name=capability_name,
                        environment=environment,
                        region=region
                    )
                    
                    if preserved:
                        self._preserved_outputs[stack_name] = preserved
                        logger.info(
                            f"[PRESERVE] Preserved {len(preserved.outputs)} outputs "
                            f"from stack {stack_name}"
                        )
                        
                except ClientError as e:
                    logger.warning(
                        f"[PRESERVE] Could not preserve outputs from {stack_name}: {e}"
                    )
            
            logger.info(
                f"[PRESERVE] Preserved outputs from {len(self._preserved_outputs)} stacks"
            )
            
            return self._preserved_outputs
            
        except Exception as e:
            logger.error(f"[PRESERVE] Error preserving stack outputs: {e}")
            return {}

    def _discover_capability_stacks(
        self,
        cfn_client: Any,
        capability_name: str,
        environment: str
    ) -> List[str]:
        """
        Discover all stacks belonging to a capability.
        
        Args:
            cfn_client: CloudFormation client
            capability_name: Capability name
            environment: Environment
            
        Returns:
            List of stack names
        """
        stacks = []
        
        try:
            # List all stacks with matching prefix
            prefix = f"{capability_name}-{environment}"
            
            paginator = cfn_client.get_paginator('list_stacks')
            
            for page in paginator.paginate(
                StackStatusFilter=[
                    'CREATE_COMPLETE',
                    'UPDATE_COMPLETE',
                    'UPDATE_ROLLBACK_COMPLETE'
                ]
            ):
                for stack in page.get('StackSummaries', []):
                    stack_name = stack.get('StackName', '')
                    if stack_name.startswith(prefix):
                        stacks.append(stack_name)
                        
        except ClientError as e:
            logger.warning(f"[PRESERVE] Error discovering stacks: {e}")
        
        return stacks

    def _preserve_stack_outputs(
        self,
        cfn_client: Any,
        stack_name: str,
        capability_name: str,
        environment: str,
        region: str
    ) -> Optional[PreservedOutputs]:
        """
        Preserve outputs from a single stack.
        
        Args:
            cfn_client: CloudFormation client
            stack_name: Stack name
            capability_name: Capability name
            environment: Environment
            region: AWS region
            
        Returns:
            PreservedOutputs or None if stack not found
        """
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get('Stacks', [])
            
            if not stacks:
                return None
            
            stack = stacks[0]
            stack_status = stack.get('StackStatus', '')
            
            # Extract outputs
            outputs = {}
            for output in stack.get('Outputs', []):
                key = output.get('OutputKey', '')
                value = output.get('OutputValue', '')
                if key and value:
                    outputs[key] = value
            
            # Determine if this is a Cognito stack
            is_cognito = self._is_cognito_stack(stack_name, outputs)
            
            return PreservedOutputs(
                stack_name=stack_name,
                outputs=outputs,
                retrieved_at=datetime.utcnow(),
                is_cognito_stack=is_cognito,
                stack_status=stack_status,
                capability_name=capability_name,
                environment=environment,
                region=region
            )
            
        except ClientError as e:
            if 'does not exist' in str(e):
                return None
            raise

    def _is_cognito_stack(self, stack_name: str, outputs: Dict[str, str]) -> bool:
        """
        Determine if a stack is the Cognito stack.
        
        Args:
            stack_name: Stack name
            outputs: Stack outputs
            
        Returns:
            True if this is the Cognito stack
        """
        # Check by stack name
        if self.COGNITO_STACK_TYPE in stack_name.lower():
            return True
        
        # Check by outputs
        cognito_outputs_found = sum(
            1 for key in self.COGNITO_OUTPUT_KEYS
            if key in outputs
        )
        
        # If stack has multiple Cognito-related outputs, it's likely the Cognito stack
        return cognito_outputs_found >= 2

    def get_cognito_outputs(self) -> Optional[CognitoOutputs]:
        """
        Get preserved Cognito outputs for dependent stacks.
        
        Returns:
            CognitoOutputs or None if not preserved
        """
        for stack_name, preserved in self._preserved_outputs.items():
            if preserved.is_cognito_stack:
                outputs = preserved.outputs
                
                return CognitoOutputs(
                    user_pool_id=outputs.get('UserPoolId', ''),
                    user_pool_client_id=outputs.get('UserPoolClientId', ''),
                    user_pool_domain=outputs.get('UserPoolDomain', ''),
                    region=preserved.region or ''
                )
        
        return None

    def get_outputs_for_stack(self, stack_name: str) -> Optional[Dict[str, str]]:
        """
        Get preserved outputs for a specific stack.
        
        Args:
            stack_name: Stack name
            
        Returns:
            Dict of outputs or None if not preserved
        """
        preserved = self._preserved_outputs.get(stack_name)
        if preserved:
            return preserved.outputs
        return None

    def get_all_preserved_outputs(self) -> Dict[str, PreservedOutputs]:
        """
        Get all preserved outputs.
        
        Returns:
            Dict mapping stack names to PreservedOutputs
        """
        return self._preserved_outputs.copy()

    def get_output_value(
        self,
        stack_name: str,
        output_key: str
    ) -> Optional[str]:
        """
        Get a specific output value from a preserved stack.
        
        Args:
            stack_name: Stack name
            output_key: Output key
            
        Returns:
            Output value or None
        """
        outputs = self.get_outputs_for_stack(stack_name)
        if outputs:
            return outputs.get(output_key)
        return None

    def has_cognito_outputs(self) -> bool:
        """
        Check if Cognito outputs have been preserved.
        
        Returns:
            True if Cognito outputs are available
        """
        return self.get_cognito_outputs() is not None

    def get_preserved_stack_names(self) -> List[str]:
        """
        Get list of all preserved stack names.
        
        Returns:
            List of stack names
        """
        return list(self._preserved_outputs.keys())

    def clear_preserved_outputs(self) -> None:
        """Clear all preserved outputs."""
        self._preserved_outputs.clear()
        logger.info("[PRESERVE] Cleared all preserved outputs")

    def get_preservation_summary(self) -> Dict[str, Any]:
        """
        Get a summary of preserved outputs.
        
        Returns:
            Summary dict with counts and details
        """
        cognito_stack = None
        for name, preserved in self._preserved_outputs.items():
            if preserved.is_cognito_stack:
                cognito_stack = name
                break
        
        return {
            'total_stacks': len(self._preserved_outputs),
            'stack_names': list(self._preserved_outputs.keys()),
            'cognito_stack': cognito_stack,
            'has_cognito_outputs': self.has_cognito_outputs(),
            'total_outputs': sum(
                len(p.outputs) for p in self._preserved_outputs.values()
            )
        }


def get_stack_output_preserver(
    credentials: Optional[Dict[str, str]] = None,
    cfn_service: Optional[Any] = None
) -> StackOutputPreserver:
    """
    Factory function to create a StackOutputPreserver instance.
    
    Args:
        credentials: Optional AWS credentials
        cfn_service: Optional CloudFormation service
        
    Returns:
        Configured StackOutputPreserver instance
    """
    return StackOutputPreserver(
        credentials=credentials,
        cfn_service=cfn_service
    )
