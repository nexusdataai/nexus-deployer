"""AWS configuration data models."""
from typing import Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class SourceAuthMethod(str, Enum):
    """Source authentication methods for Role ARN assumption."""
    ACCESS_KEY = "access_key"
    AWS_PROFILE = "aws_profile"
    INSTANCE_PROFILE = "instance_profile"
    ENVIRONMENT = "environment"  # Use environment variables or default credential chain


class AWSAuthMethod(str, Enum):
    """AWS authentication methods."""
    ROLE_ARN = "role_arn"
    ACCESS_KEY = "access_key"
    ADFS_SAML = "adfs_saml"
    INSTANCE_PROFILE = "instance_profile"
    AWS_PROFILE = "aws_profile"


class AWSCredentials(BaseModel):
    """AWS credentials."""
    access_key_id: str = Field(..., description="AWS Access Key ID")
    secret_access_key: str = Field(..., description="AWS Secret Access Key")
    session_token: Optional[str] = Field(None, description="AWS Session Token (for temporary credentials)")
    expiration: Optional[datetime] = Field(None, description="Credentials expiration time")


class AWSConfiguration(BaseModel):
    """AWS environment configuration."""
    auth_method: AWSAuthMethod = Field(..., description="Authentication method")
    region: str = Field(..., description="AWS Region")
    account_id: Optional[str] = Field(None, description="AWS Account ID")
    
    # Role ARN method
    role_arn: Optional[str] = Field(None, description="IAM Role ARN to assume")
    
    # Access Key method
    access_key_id: Optional[str] = Field(None, description="AWS Access Key ID")
    secret_access_key: Optional[str] = Field(None, description="AWS Secret Access Key")
    
    # ADFS/SAML method
    adfs_url: Optional[str] = Field(None, description="ADFS endpoint URL")
    adfs_username: Optional[str] = Field(None, description="ADFS username")
    adfs_password: Optional[str] = Field(None, description="ADFS password")
    
    # AWS Profile method
    profile_name: Optional[str] = Field(None, description="AWS CLI profile name")
    
    # Temporary credentials (result of authentication)
    temporary_credentials: Optional[AWSCredentials] = Field(None, description="Temporary credentials")


class Permission(BaseModel):
    """Individual IAM permission."""
    action: str = Field(..., description="IAM action (e.g., 's3:GetObject')")
    granted: bool = Field(..., description="Whether the permission is granted")
    resource: Optional[str] = Field("*", description="Resource ARN the permission applies to")


class PermissionStatus(BaseModel):
    """Status of permission verification."""
    all_granted: bool = Field(..., description="Whether all required permissions are granted")
    required_permissions: List[Permission] = Field(default_factory=list, description="List of all required permissions")
    missing_permissions: List[str] = Field(default_factory=list, description="List of missing permission actions")
    iam_policy_json: Optional[str] = Field(None, description="IAM policy JSON for missing permissions")


class AuthValidationRequest(BaseModel):
    """Request to validate AWS authentication."""
    auth_method: AWSAuthMethod = Field(..., description="Authentication method")
    region: str = Field(..., description="AWS Region")
    
    # Role ARN method
    role_arn: Optional[str] = Field(None, description="IAM Role ARN to validate")
    
    # Source credentials for Role ARN assumption
    source_auth_method: Optional[SourceAuthMethod] = Field(
        None, 
        description="Source authentication method for assuming the role"
    )
    source_access_key_id: Optional[str] = Field(
        None, 
        description="Source AWS Access Key ID (for source_auth_method=access_key)"
    )
    source_secret_access_key: Optional[str] = Field(
        None, 
        description="Source AWS Secret Access Key (for source_auth_method=access_key)"
    )
    source_profile_name: Optional[str] = Field(
        None, 
        description="Source AWS CLI profile name (for source_auth_method=aws_profile)"
    )
    
    # Access Key method (direct, not for role assumption)
    access_key_id: Optional[str] = Field(None, description="AWS Access Key ID")
    secret_access_key: Optional[str] = Field(None, description="AWS Secret Access Key")
    
    # ADFS/SAML method
    adfs_url: Optional[str] = Field(None, description="ADFS endpoint URL")
    adfs_username: Optional[str] = Field(None, description="ADFS username")
    adfs_password: Optional[str] = Field(None, description="ADFS password")
    
    # AWS Profile method
    profile_name: Optional[str] = Field(None, description="AWS CLI profile name")


class RoleValidationRequest(BaseModel):
    """Request to validate AWS Role ARN (legacy)."""
    role_arn: str = Field(..., description="IAM Role ARN to validate")
    region: str = Field(..., description="AWS Region")


class DiagnosticInfo(BaseModel):
    """Detailed diagnostic information for troubleshooting authentication issues."""
    timestamp: Optional[str] = Field(None, description="Timestamp of the diagnostic")
    step: Optional[str] = Field(None, description="Authentication step that was being performed")
    endpoint_url: Optional[str] = Field(None, description="Endpoint URL being accessed")
    endpoint_reachable: Optional[bool] = Field(None, description="Whether the endpoint was reachable")
    http_status_code: Optional[int] = Field(None, description="HTTP status code from the endpoint")
    error_code: Optional[str] = Field(None, description="AWS or ADFS error code")
    error_message: Optional[str] = Field(None, description="Detailed error message")
    raw_output: Optional[str] = Field(None, description="Raw output from authentication tool (sanitized)")
    network_error: Optional[str] = Field(None, description="Network-level error if any")
    ssl_error: Optional[str] = Field(None, description="SSL/TLS error if any")
    auth_method_used: Optional[str] = Field(None, description="Authentication method that was attempted")
    duration_ms: Optional[int] = Field(None, description="Time taken for the operation in milliseconds")
    steps: Optional[str] = Field(None, description="Step-by-step diagnostic trail: step1(status) -> step2(status) -> ...")


class RoleValidationResponse(BaseModel):
    """Response from role validation."""
    valid: bool = Field(..., description="Whether the role is valid and assumable")
    account_id: Optional[str] = Field(None, description="AWS Account ID")
    error: Optional[str] = Field(None, description="Error message if validation failed")
    troubleshooting: Optional[List[str]] = Field(None, description="Troubleshooting steps")
    session_id: Optional[str] = Field(None, description="AWS session ID for storing credentials")
    credentials: Optional[dict] = Field(None, description="AWS credentials (for internal use)")
    success: bool = Field(True, description="Whether authentication was successful")
    diagnostics: Optional[DiagnosticInfo] = Field(None, description="Detailed diagnostic information for troubleshooting")


class PermissionVerificationRequest(BaseModel):
    """Request to verify IAM permissions."""
    role_arn: str = Field(..., description="IAM Role ARN")
    region: str = Field(..., description="AWS Region")
    required_permissions: List[str] = Field(..., description="List of required IAM actions")


class AWSRegion(BaseModel):
    """AWS Region information."""
    code: str = Field(..., description="Region code (e.g., 'us-east-1')")
    name: str = Field(..., description="Region name (e.g., 'US East (N. Virginia)')")


class ADFSRole(BaseModel):
    """ADFS/SAML AWS Role information."""
    role_arn: str = Field(..., description="IAM Role ARN")
    principal_arn: str = Field(..., description="SAML Provider ARN")
    account_id: str = Field(..., description="AWS Account ID")
    role_name: str = Field(..., description="Role name (extracted from ARN)")
    account_alias: Optional[str] = Field(None, description="Account alias or friendly name")


class ADFSRolesResponse(BaseModel):
    """Response containing available ADFS roles."""
    roles: List[ADFSRole] = Field(..., description="List of available roles")
    session_id: str = Field(..., description="Session ID for role selection")


class ADFSRolesRequest(BaseModel):
    """Request to fetch available ADFS roles."""
    adfs_url: str = Field(..., description="ADFS endpoint URL")
    adfs_username: str = Field(..., description="ADFS username")
    adfs_password: str = Field(..., description="ADFS password")
    region: str = Field(..., description="AWS Region")


class ADFSRoleSelectionRequest(BaseModel):
    """Request to select an ADFS role and get credentials."""
    session_id: str = Field(..., description="Session ID from roles fetch")
    role_arn: str = Field(..., description="Selected role ARN")
    region: str = Field(..., description="AWS Region")
