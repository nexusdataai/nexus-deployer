"""
Custom exceptions for infrastructure provisioning.

Provides specific exception types for different error scenarios
during resource provisioning and verification.
"""

from typing import Optional
from .models import ResourceType


class ProvisioningError(Exception):
    """Base exception for provisioning errors."""
    
    def __init__(
        self,
        resource_type: ResourceType,
        resource_name: str,
        message: str,
        recoverable: bool = True,
    ):
        """
        Initialize the provisioning error.
        
        Args:
            resource_type: Type of resource that failed
            resource_name: Name of the resource
            message: Error message
            recoverable: Whether the error is recoverable (can continue)
        """
        self.resource_type = resource_type
        self.resource_name = resource_name
        self.message = message
        self.recoverable = recoverable
        super().__init__(f"{resource_type.value} '{resource_name}': {message}")


class ResourceCreationError(ProvisioningError):
    """Error during resource creation."""
    
    def __init__(
        self,
        resource_type: ResourceType,
        resource_name: str,
        message: str,
        aws_error_code: Optional[str] = None,
    ):
        """
        Initialize the resource creation error.
        
        Args:
            resource_type: Type of resource that failed
            resource_name: Name of the resource
            message: Error message
            aws_error_code: AWS error code if applicable
        """
        self.aws_error_code = aws_error_code
        super().__init__(resource_type, resource_name, message, recoverable=True)


class ResourceVerificationError(ProvisioningError):
    """Error during resource verification."""
    
    def __init__(
        self,
        resource_type: ResourceType,
        resource_name: str,
        message: str,
        expected_state: Optional[str] = None,
        actual_state: Optional[str] = None,
    ):
        """
        Initialize the resource verification error.
        
        Args:
            resource_type: Type of resource that failed verification
            resource_name: Name of the resource
            message: Error message
            expected_state: Expected state of the resource
            actual_state: Actual state of the resource
        """
        self.expected_state = expected_state
        self.actual_state = actual_state
        super().__init__(resource_type, resource_name, message, recoverable=True)


class ProvisioningPermissionError(ProvisioningError):
    """IAM permission denied error."""
    
    def __init__(
        self,
        resource_type: ResourceType,
        resource_name: str,
        required_permission: str,
    ):
        """
        Initialize the permission error.
        
        Args:
            resource_type: Type of resource that requires permission
            resource_name: Name of the resource
            required_permission: IAM permission that is required
        """
        self.required_permission = required_permission
        super().__init__(
            resource_type,
            resource_name,
            f"Permission denied. Required: {required_permission}",
            recoverable=False,
        )


class ProvisioningTimeoutError(ProvisioningError):
    """Resource did not reach expected state in time."""
    
    def __init__(
        self,
        resource_type: ResourceType,
        resource_name: str,
        expected_state: str,
        timeout_seconds: int,
    ):
        """
        Initialize the timeout error.
        
        Args:
            resource_type: Type of resource that timed out
            resource_name: Name of the resource
            expected_state: State the resource was expected to reach
            timeout_seconds: Timeout duration in seconds
        """
        self.expected_state = expected_state
        self.timeout_seconds = timeout_seconds
        super().__init__(
            resource_type,
            resource_name,
            f"Timed out waiting for state '{expected_state}' after {timeout_seconds}s",
            recoverable=True,
        )


class InvalidEnvironmentError(Exception):
    """Invalid environment specified."""
    
    def __init__(self, environment: str, valid_environments: list):
        """
        Initialize the invalid environment error.
        
        Args:
            environment: The invalid environment that was specified
            valid_environments: List of valid environment names
        """
        self.environment = environment
        self.valid_environments = valid_environments
        super().__init__(
            f"Invalid environment '{environment}'. "
            f"Valid environments: {', '.join(sorted(valid_environments))}"
        )
