"""
Cognito SSM Integration Service

Stores Cognito User Pool configuration in SSM Parameter Store after deployment.
This enables runtime configuration for backend services without hardcoding values.
"""

import logging
from typing import Dict, Any, Optional

import boto3
from botocore.exceptions import ClientError

from app.models.cognito_models import CognitoOutputs
from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

logger = logging.getLogger(__name__)


class CognitoSSMIntegration:
    """Service for storing Cognito configuration in SSM Parameter Store."""
    
    def __init__(
        self,
        capability_name: str,
        environment: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ):
        """
        Initialize Cognito SSM integration.
        
        Args:
            capability_name: Capability name (e.g., "call-processing")
            environment: Environment (dev, staging, prod)
            region: AWS region
            credentials: Optional AWS credentials
        """
        self.capability_name = capability_name
        self.environment = environment
        self.region = region
        self.credentials = credentials or {}
        
        # Create SSM client
        self.ssm_client = boto3.client(
            "ssm",
            **merge_vpc_boto3_kwargs(
                "ssm", region, {**self.credentials, "region_name": region}
            ),
        )
    
    def _get_ssm_path(self, parameter_name: str) -> str:
        """
        Build SSM parameter path.
        
        Args:
            parameter_name: Parameter name (e.g., "user-pool-id")
        
        Returns:
            Full SSM path (e.g., "/call-processing/prod/cognito/user-pool-id")
        """
        return f"/{self.capability_name}/{self.environment}/cognito/{parameter_name}"
    
    def store_cognito_outputs(
        self,
        cognito_outputs: CognitoOutputs,
        frontend_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Store Cognito outputs in SSM Parameter Store.
        
        Creates parameters following the pattern:
        /{capability}/{environment}/cognito/{parameter}
        
        Args:
            cognito_outputs: Cognito stack outputs
            frontend_url: Optional frontend URL for redirect_uri
        
        Returns:
            Dict with results for each parameter
        """
        results = {}
        
        # Build parameter mapping
        # Note: app-client-id matches the SSM parameter path used by starhub-backend
        
        # Build full domain URL if only prefix provided
        domain = cognito_outputs.domain
        if domain and not domain.endswith(".amazoncognito.com"):
            domain = f"{domain}.auth.{self.region}.amazoncognito.com"
        
        parameters = {
            "region": self.region,
            "user-pool-id": cognito_outputs.user_pool_id,
            "app-client-id": cognito_outputs.client_id,
            "domain": domain,
            "redirect-uri": frontend_url or cognito_outputs.callback_url or ""
        }
        
        # Store each parameter
        for param_name, param_value in parameters.items():
            if not param_value:
                logger.warning(f"Skipping empty parameter: {param_name}")
                continue
            
            path = self._get_ssm_path(param_name)
            
            try:
                self.ssm_client.put_parameter(
                    Name=path,
                    Value=param_value,
                    Type='String',
                    Description=f'Cognito {param_name} for {self.capability_name} ({self.environment})',
                    Overwrite=True,
                    Tags=[
                        {'Key': 'Capability', 'Value': self.capability_name},
                        {'Key': 'Environment', 'Value': self.environment},
                        {'Key': 'ManagedBy', 'Value': 'starhub-deployer'},
                        {'Key': 'Component', 'Value': 'cognito'}
                    ]
                )
                
                logger.info(f"✅ Stored Cognito parameter in SSM: {path} = {param_value[:20]}...")
                results[param_name] = {"status": "created", "path": path, "value": param_value}
                
            except ClientError as e:
                logger.error(f"❌ Failed to store parameter {path}: {e}")
                results[param_name] = {"status": "failed", "error": str(e)}
            except Exception as e:
                logger.error(f"❌ Unexpected error storing parameter {path}: {e}")
                results[param_name] = {"status": "failed", "error": str(e)}
        
        success_count = sum(1 for r in results.values() if r["status"] == "created")
        logger.info(f"Stored {success_count}/{len(parameters)} Cognito parameters in SSM")
        
        return results
    
    def store_cognito_from_stack_outputs(
        self,
        stack_outputs: Dict[str, str],
        frontend_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Store Cognito configuration from CloudFormation stack outputs.
        
        Args:
            stack_outputs: Raw CloudFormation stack outputs dict
            frontend_url: Optional frontend URL for redirect_uri
        
        Returns:
            Dict with results
        """
        try:
            # Extract Cognito outputs
            cognito_outputs = CognitoOutputs(
                user_pool_id=stack_outputs.get('UserPoolId', ''),
                client_id=stack_outputs.get('UserPoolClientId', ''),
                domain=stack_outputs.get('UserPoolDomain', ''),
                region=stack_outputs.get('Region', self.region),
                callback_url=stack_outputs.get('CallbackURL', frontend_url)
            )
            
            if not cognito_outputs.user_pool_id or not cognito_outputs.client_id:
                logger.error("❌ Cognito outputs incomplete (missing user_pool_id or client_id)")
                return {"status": "failed", "error": "Incomplete Cognito outputs"}
            
            logger.info(f"Storing Cognito configuration in SSM for {self.capability_name}/{self.environment}")
            logger.info(f"  User Pool ID: {cognito_outputs.user_pool_id}")
            logger.info(f"  Client ID: {cognito_outputs.client_id}")
            logger.info(f"  Domain: {cognito_outputs.domain}")
            
            return self.store_cognito_outputs(cognito_outputs, frontend_url)
            
        except Exception as e:
            logger.error(f"❌ Failed to process Cognito outputs: {e}")
            return {"status": "failed", "error": str(e)}
    
    def delete_cognito_parameters(self) -> Dict[str, Any]:
        """
        Delete all Cognito parameters from SSM.
        
        Used during cleanup.
        
        Returns:
            Dict with deletion results
        """
        results = {}
        param_names = ["region", "user-pool-id", "app-client-id", "domain", "redirect-uri"]
        
        for param_name in param_names:
            path = self._get_ssm_path(param_name)
            
            try:
                self.ssm_client.delete_parameter(Name=path)
                logger.info(f"✅ Deleted Cognito parameter: {path}")
                results[param_name] = {"status": "deleted", "path": path}
                
            except ClientError as e:
                if e.response['Error']['Code'] == 'ParameterNotFound':
                    logger.debug(f"Parameter not found (already deleted): {path}")
                    results[param_name] = {"status": "not_found", "path": path}
                else:
                    logger.error(f"❌ Failed to delete parameter {path}: {e}")
                    results[param_name] = {"status": "failed", "error": str(e)}
        
        return results


def get_cognito_ssm_integration(
    capability_name: str,
    environment: str,
    region: str,
    credentials: Optional[Dict[str, str]] = None
) -> CognitoSSMIntegration:
    """
    Get CognitoSSMIntegration instance.
    
    Args:
        capability_name: Capability name
        environment: Environment
        region: AWS region
        credentials: Optional AWS credentials
    
    Returns:
        CognitoSSMIntegration instance
    """
    return CognitoSSMIntegration(
        capability_name=capability_name,
        environment=environment,
        region=region,
        credentials=credentials
    )
