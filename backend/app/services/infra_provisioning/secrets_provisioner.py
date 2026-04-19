"""
Secrets Manager Provisioner for call-processing capability.

Creates and manages secrets:
- api-keys: API_KEY
- wxcc: WXCC_SIM_TOKEN
- openai: OPENAI_API_KEY
- license: LICENSE_PUBLIC_KEY, LICENSE_PRIVATE_KEY
- anthropic: CLAUDE_API_KEY, ANTHROPIC_API_KEY
- github: GITHUB_TOKEN
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable

import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

from .models import (
    ResourceType,
    ResourceStatus,
    ResourceStatusType,
    get_environment_config,
)
from .naming import ResourceNaming

logger = logging.getLogger(__name__)


class SecretsProvisioner:
    """Provisions Secrets Manager secrets for call-processing capability."""
    
    def __init__(
        self,
        environment: str,
        region: str,
        endpoint_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
        boto3_session: Optional['boto3.Session'] = None,
    ):
        """
        Initialize the Secrets provisioner.
        
        Args:
            environment: Target environment (dev, stage, test, prod)
            region: AWS region
            endpoint_url: Optional endpoint URL for LocalStack
            progress_callback: Optional callback for real-time progress updates
            boto3_session: Optional boto3 session with fresh credentials
        """
        self.environment = environment
        self.region = region
        self.endpoint_url = endpoint_url
        self.naming = ResourceNaming(environment)
        self.config = get_environment_config(environment)
        self.progress_callback = progress_callback
        
        # Initialize boto3 client
        client_kwargs = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        
        merged = merge_vpc_boto3_kwargs("secretsmanager", region, dict(client_kwargs))
        # Use provided session or create new one
        if boto3_session:
            self.client = boto3_session.client("secretsmanager", **merged)
        else:
            self.client = boto3.client("secretsmanager", **merged)
    
    def _log_progress(self, message: str):
        """Log progress to both logger and callback if available."""
        logger.info(message)
        if self.progress_callback:
            self.progress_callback(message)
    
    def provision_all(self) -> List[ResourceStatus]:
        """
        Provision all secrets.
        
        Returns:
            List of ResourceStatus for each secret
        """
        return self.create_all_secrets()
    
    def create_all_secrets(self) -> List[ResourceStatus]:
        """
        Create all secrets for the environment.
        
        Returns:
            List of ResourceStatus for each secret
        """
        results = []
        
        # Get all secrets with placeholder values
        all_secrets = self.get_placeholder_secrets()
        total = len(all_secrets)
        
        self._log_progress(f"  Creating {total} secrets...")
        
        for idx, (name, (secret_value, description)) in enumerate(all_secrets.items(), 1):
            # Extract secret type from name for logging
            parts = name.split('/')
            secret_type = parts[-1] if parts else name
            self._log_progress(f"    [{idx}/{total}] {secret_type}")
            result = self.create_secret(name, secret_value, description)
            results.append(result)
        
        return results
    
    def create_secret(
        self,
        name: str,
        secret_value: Dict[str, str],
        description: str,
    ) -> ResourceStatus:
        """
        Create a secret if it doesn't exist.
        
        Args:
            name: Secret name (e.g., call-processing/{env}/api-keys)
            secret_value: Dictionary of key-value pairs
            description: Secret description
            
        Returns:
            ResourceStatus indicating success or failure
        """
        if self.secret_exists(name):
            self._log_progress(f"      [OK] Already exists")
            return ResourceStatus(
                resource_type=ResourceType.SECRET,
                resource_name=name,
                status=ResourceStatusType.ALREADY_EXISTS,
                message=f"Secret {name} already exists",
            )
        
        try:
            self._log_progress(f"      Creating...")
            
            self.client.create_secret(
                Name=name,
                Description=description,
                SecretString=json.dumps(secret_value),
            )
            
            self._log_progress(f"      [OK] Created with placeholder values")
            return ResourceStatus(
                resource_type=ResourceType.SECRET,
                resource_name=name,
                status=ResourceStatusType.CREATED,
                message=f"Secret {name} created with placeholder values",
                created_at=datetime.utcnow(),
            )
            
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            self._log_progress(f"      [X] Failed: {error_msg}")
            return ResourceStatus(
                resource_type=ResourceType.SECRET,
                resource_name=name,
                status=ResourceStatusType.FAILED,
                message=f"Failed to create secret: {error_msg}",
                error=error_code,
            )
    
    def secret_exists(self, name: str) -> bool:
        """
        Check if a secret already exists.
        
        Args:
            name: Secret name
            
        Returns:
            True if secret exists, False otherwise
        """
        try:
            self.client.describe_secret(SecretId=name)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return False
            raise
    
    def get_placeholder_secrets(self) -> Dict[str, tuple]:
        """
        Get all secrets with placeholder values.
        
        Returns:
            Dictionary mapping secret name to (value_dict, description) tuple
        """
        return {
            self.naming.secret("api-keys"): (
                {"API_KEY": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE"},
                "Gateway API key for authentication",
            ),
            self.naming.secret("wxcc"): (
                {"WXCC_SIM_TOKEN": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE"},
                "WXCC simulator authentication token",
            ),
            self.naming.secret("openai"): (
                {"OPENAI_API_KEY": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE"},
                "OpenAI API key for transcription",
            ),
            self.naming.secret("license"): (
                {
                    "LICENSE_PUBLIC_KEY": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE",
                    "LICENSE_PRIVATE_KEY": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE",
                },
                "License verification keys",
            ),
            self.naming.secret("anthropic"): (
                {
                    "CLAUDE_API_KEY": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE",
                    "ANTHROPIC_API_KEY": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE",
                },
                "Anthropic Claude API keys",
            ),
            self.naming.secret("github"): (
                {"GITHUB_TOKEN": "PLACEHOLDER_UPDATE_WITH_ACTUAL_VALUE"},
                "GitHub personal access token",
            ),
        }
    
    def get_all_secret_names(self) -> List[str]:
        """
        Get all secret names that should be created.
        
        Returns:
            List of secret names
        """
        return list(self.get_placeholder_secrets().keys())
