"""Enhanced AWS authentication service supporting multiple auth methods."""
import re
import os
import sys
import time
import socket
import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime
import boto3
from botocore.exceptions import ClientError, BotoCoreError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

from app.models.aws_config import (
    AWSAuthMethod,
    SourceAuthMethod,
    AWSConfiguration,
    AWSCredentials,
    RoleValidationResponse,
    AuthValidationRequest,
    ADFSRole,
    DiagnosticInfo,
)

logger = logging.getLogger(__name__)


class AWSAuthService:
    """Service for AWS authentication using multiple methods."""
    
    # ARN pattern for IAM roles
    ROLE_ARN_PATTERN = r'^arn:aws:iam::(\d{12}):role/([\w+=,.@-]+)$'
    
    # In-memory storage for credentials (session-scoped)
    _credentials_cache: Dict[str, AWSCredentials] = {}
    
    @staticmethod
    def _extract_adfs_host(adfs_url: str) -> str:
        """Extract ADFS host from URL, handling both full URLs and hostnames.
        
        Args:
            adfs_url: ADFS URL (with or without https://)
            
        Returns:
            Clean ADFS hostname with path
        """
        adfs_host = adfs_url
        if adfs_url.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(adfs_url)
            adfs_host = parsed.netloc + parsed.path
        
        # Remove trailing slashes
        adfs_host = adfs_host.rstrip('/')
        return adfs_host
    
    @staticmethod
    def _safe_str(text: str) -> str:
        """Safely convert text to ASCII-safe string, replacing problematic characters.
        
        This handles Unicode characters (like emojis) that can't be encoded
        with the default Windows charmap codec.
        
        Args:
            text: Input text that may contain Unicode characters
            
        Returns:
            ASCII-safe string with problematic characters replaced
        """
        if not text:
            return text
        try:
            # Try to encode as ASCII, replacing non-ASCII characters
            return text.encode('ascii', errors='replace').decode('ascii')
        except Exception:
            # Fallback: remove all non-ASCII characters
            return ''.join(c if ord(c) < 128 else '?' for c in text)
    
    @staticmethod
    def _check_endpoint_reachability(host: str, port: int = 443, timeout: float = 5.0) -> Tuple[bool, Optional[str]]:
        """Check if an endpoint is reachable via TCP connection.
        
        Args:
            host: Hostname to check
            port: Port number (default 443 for HTTPS)
            timeout: Connection timeout in seconds
            
        Returns:
            Tuple of (is_reachable, error_message)
        """
        try:
            # Extract hostname from URL if needed
            if '/' in host:
                host = host.split('/')[0]
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                return True, None
            else:
                return False, f"Connection refused (error code: {result})"
        except socket.gaierror as e:
            return False, f"DNS resolution failed: {str(e)}"
        except socket.timeout:
            return False, f"Connection timeout after {timeout}s"
        except Exception as e:
            return False, f"Network error: {str(e)}"
    
    @staticmethod
    def _test_https_endpoint(url: str, timeout: float = 10.0) -> Tuple[bool, Optional[int], Optional[str]]:
        """Test HTTPS endpoint and return status.
        
        Args:
            url: Full URL to test
            timeout: Request timeout in seconds
            
        Returns:
            Tuple of (success, http_status_code, error_message)
        """
        try:
            import requests
            from requests.exceptions import SSLError, ConnectionError, Timeout
            
            # Ensure URL has https://
            if not url.startswith('http'):
                url = f"https://{url}"
            
            response = requests.get(url, timeout=timeout, verify=False, allow_redirects=True)
            return True, response.status_code, None
        except SSLError as e:
            return False, None, f"SSL/TLS error: {str(e)}"
        except ConnectionError as e:
            return False, None, f"Connection error: {str(e)}"
        except Timeout:
            return False, None, f"Request timeout after {timeout}s"
        except Exception as e:
            return False, None, f"HTTP error: {str(e)}"
    
    @staticmethod
    def _validate_adfs_endpoint(host: str, timeout: float = 10.0) -> Tuple[bool, str]:
        """Validate that the endpoint is actually an ADFS server.
        
        Checks for ADFS-specific endpoints and responses to determine
        if this is a valid ADFS server configured for AWS federation.
        
        Args:
            host: Hostname to check (without protocol)
            timeout: Request timeout in seconds
            
        Returns:
            Tuple of (is_valid_adfs, details_message)
        """
        import requests
        from urllib.parse import urljoin
        
        # Clean up host
        if host.startswith('http'):
            from urllib.parse import urlparse
            parsed = urlparse(host)
            host = parsed.netloc
        
        base_url = f"https://{host}"
        
        # ADFS-specific endpoints to check
        adfs_indicators = []
        
        try:
            # Check 1: ADFS metadata endpoint (FederationMetadata.xml)
            metadata_urls = [
                f"{base_url}/FederationMetadata/2007-06/FederationMetadata.xml",
                f"{base_url}/adfs/FederationMetadata/2007-06/FederationMetadata.xml",
            ]
            
            metadata_found = False
            for metadata_url in metadata_urls:
                try:
                    response = requests.get(metadata_url, timeout=timeout, verify=False)
                    if response.status_code == 200:
                        content = response.text.lower()
                        if 'entitydescriptor' in content or 'saml' in content or 'federation' in content:
                            metadata_found = True
                            adfs_indicators.append(f"Federation metadata found at {metadata_url}")
                            break
                except:
                    pass
            
            # Check 2: ADFS sign-on page
            signon_urls = [
                f"{base_url}/adfs/ls/idpinitiatedsignon",
                f"{base_url}/adfs/ls/IdpInitiatedSignOn.aspx",
                f"{base_url}/adfs/ls",
            ]
            
            signon_found = False
            for signon_url in signon_urls:
                try:
                    response = requests.get(signon_url, timeout=timeout, verify=False, allow_redirects=True)
                    content = response.text.lower()
                    # Look for ADFS-specific content
                    if any(indicator in content for indicator in ['adfs', 'active directory', 'federation', 'saml', 'sign in', 'username', 'password']):
                        signon_found = True
                        adfs_indicators.append(f"ADFS sign-on page found at {signon_url}")
                        break
                except:
                    pass
            
            # Check 3: Look for AWS-specific SAML configuration
            # Check if the response mentions AWS or amazon
            aws_configured = False
            try:
                response = requests.get(f"{base_url}/adfs/ls/idpinitiatedsignon", timeout=timeout, verify=False, allow_redirects=True)
                content = response.text.lower()
                if 'amazon' in content or 'aws' in content or 'urn:amazon:webservices' in content:
                    aws_configured = True
                    adfs_indicators.append("AWS federation appears to be configured")
            except:
                pass
            
            # Determine if this is a valid ADFS endpoint
            if metadata_found or signon_found:
                details = "; ".join(adfs_indicators) if adfs_indicators else "ADFS endpoint validated"
                if not aws_configured:
                    details += " (Note: AWS federation configuration not detected, but may still work)"
                return True, details
            
            # Not an ADFS endpoint - provide helpful message
            # Try to identify what kind of server it is
            try:
                response = requests.get(base_url, timeout=timeout, verify=False, allow_redirects=True)
                content = response.text.lower()
                server_header = response.headers.get('Server', '').lower()
                
                if 'google' in content or 'google' in server_header:
                    return False, "This appears to be a Google server, not an ADFS endpoint. Please provide your organization's ADFS URL (e.g., adfs.yourcompany.com/adfs/ls/idpinitiatedsignon)"
                elif 'microsoft' in server_header or 'iis' in server_header:
                    return False, "This is a Microsoft IIS server but ADFS endpoints were not found. Verify the ADFS path (typically /adfs/ls/idpinitiatedsignon)"
                elif 'nginx' in server_header or 'apache' in server_header:
                    return False, f"This appears to be a {server_header} web server, not an ADFS endpoint. Please provide your organization's ADFS URL."
                else:
                    return False, f"No ADFS endpoints found at {host}. Expected to find ADFS federation metadata or sign-on page. Please verify the URL is correct."
                    
            except Exception as e:
                return False, f"Could not validate ADFS endpoint: {str(e)}"
                
        except Exception as e:
            return False, f"Error validating ADFS endpoint: {str(e)}"
    
    @staticmethod
    def _create_diagnostic_info(
        step: str,
        auth_method: str,
        endpoint_url: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        raw_output: Optional[str] = None,
        start_time: Optional[float] = None,
        endpoint_reachable: Optional[bool] = None,
        http_status_code: Optional[int] = None,
        network_error: Optional[str] = None,
        ssl_error: Optional[str] = None
    ) -> DiagnosticInfo:
        """Create a DiagnosticInfo object with the provided details.
        
        Args:
            step: Current authentication step
            auth_method: Authentication method being used
            endpoint_url: URL being accessed
            error_code: Error code if any
            error_message: Error message if any
            raw_output: Raw output from tools (will be sanitized)
            start_time: Start time for duration calculation
            endpoint_reachable: Whether endpoint was reachable
            http_status_code: HTTP status code if applicable
            network_error: Network-level error if any
            ssl_error: SSL/TLS error if any
            
        Returns:
            DiagnosticInfo object
        """
        duration_ms = None
        if start_time:
            duration_ms = int((time.time() - start_time) * 1000)
        
        # Sanitize raw output - remove passwords and limit length
        sanitized_output = None
        if raw_output:
            sanitized_output = AWSAuthService._safe_str(raw_output)
            # Limit to 1000 chars
            if len(sanitized_output) > 1000:
                sanitized_output = sanitized_output[:1000] + "... [truncated]"
        
        return DiagnosticInfo(
            timestamp=datetime.now().isoformat(),
            step=step,
            endpoint_url=endpoint_url,
            endpoint_reachable=endpoint_reachable,
            http_status_code=http_status_code,
            error_code=error_code,
            error_message=error_message,
            raw_output=sanitized_output,
            network_error=network_error,
            ssl_error=ssl_error,
            auth_method_used=auth_method,
            duration_ms=duration_ms
        )
    
    @staticmethod
    def validate_auth(request: AuthValidationRequest) -> RoleValidationResponse:
        """Validate AWS authentication using the specified method.
        
        Args:
            request: Authentication validation request
            
        Returns:
            RoleValidationResponse with validation results
        """
        if request.auth_method == AWSAuthMethod.ROLE_ARN:
            return AWSAuthService._validate_role_arn(
                role_arn=request.role_arn,
                region=request.region,
                source_auth_method=request.source_auth_method,
                source_access_key_id=request.source_access_key_id,
                source_secret_access_key=request.source_secret_access_key,
                source_profile_name=request.source_profile_name
            )
        elif request.auth_method == AWSAuthMethod.ACCESS_KEY:
            return AWSAuthService._validate_access_key(
                request.access_key_id,
                request.secret_access_key,
                request.region
            )
        elif request.auth_method == AWSAuthMethod.AWS_PROFILE:
            return AWSAuthService._validate_aws_profile(
                request.profile_name,
                request.region
            )
        elif request.auth_method == AWSAuthMethod.INSTANCE_PROFILE:
            return AWSAuthService._validate_instance_profile(request.region)
        elif request.auth_method == AWSAuthMethod.ADFS_SAML:
            return AWSAuthService._validate_adfs_saml(
                request.adfs_url,
                request.adfs_username,
                request.adfs_password,
                request.region
            )
        else:
            return RoleValidationResponse(
                valid=False,
                error=f"Unsupported authentication method: {request.auth_method}",
                troubleshooting=["Please select a supported authentication method"]
            )
    
    @staticmethod
    def _validate_role_arn(
        role_arn: str, 
        region: str,
        source_auth_method: Optional[SourceAuthMethod] = None,
        source_access_key_id: Optional[str] = None,
        source_secret_access_key: Optional[str] = None,
        source_profile_name: Optional[str] = None
    ) -> RoleValidationResponse:
        """Validate Role ARN authentication by assuming the role.
        
        Args:
            role_arn: IAM Role ARN to assume
            region: AWS region
            source_auth_method: Method to obtain source credentials for assuming the role
            source_access_key_id: Source AWS Access Key ID (if source_auth_method is ACCESS_KEY)
            source_secret_access_key: Source AWS Secret Access Key (if source_auth_method is ACCESS_KEY)
            source_profile_name: Source AWS CLI profile name (if source_auth_method is AWS_PROFILE)
            
        Returns:
            RoleValidationResponse
        """
        # Validate ARN format
        match = re.match(AWSAuthService.ROLE_ARN_PATTERN, role_arn)
        if not match:
            return RoleValidationResponse(
                valid=False,
                error="Invalid Role ARN format",
                troubleshooting=[
                    "Role ARN must match pattern: arn:aws:iam::<account-id>:role/<role-name>",
                    "Example: arn:aws:iam::123456789012:role/MyDeploymentRole",
                ]
            )
        
        account_id = match.group(1)
        
        try:
            # Create STS client based on source authentication method
            sts_client = None
            source_info = "default credential chain"
            
            if source_auth_method == SourceAuthMethod.ACCESS_KEY:
                # Use provided access key credentials
                if not source_access_key_id or not source_secret_access_key:
                    return RoleValidationResponse(
                        valid=False,
                        error="Source Access Key credentials are required",
                        troubleshooting=[
                            "Provide both Source Access Key ID and Secret Access Key",
                            "These credentials will be used to assume the target role"
                        ]
                    )
                sts_client = boto3.client(
                    "sts",
                    **merge_vpc_boto3_kwargs(
                        "sts",
                        region,
                        {
                            "region_name": region,
                            "aws_access_key_id": source_access_key_id,
                            "aws_secret_access_key": source_secret_access_key,
                        },
                    ),
                )
                source_info = f"access key {source_access_key_id[:8]}..."
                
            elif source_auth_method == SourceAuthMethod.AWS_PROFILE:
                # Use AWS CLI profile
                if not source_profile_name:
                    return RoleValidationResponse(
                        valid=False,
                        error="Source AWS profile name is required",
                        troubleshooting=[
                            "Select an AWS CLI profile to use as source credentials",
                            "The profile must have permission to assume the target role"
                        ]
                    )
                try:
                    session = boto3.Session(profile_name=source_profile_name, region_name=region)
                    sts_client = session.client(
                        "sts",
                        **merge_vpc_boto3_kwargs("sts", region, {"region_name": region}),
                    )
                    source_info = f"profile '{source_profile_name}'"
                except Exception as e:
                    return RoleValidationResponse(
                        valid=False,
                        error=f"Failed to load AWS profile '{source_profile_name}': {str(e)}",
                        troubleshooting=[
                            f"Verify profile '{source_profile_name}' exists in ~/.aws/credentials",
                            "Run 'aws configure --profile <name>' to create the profile"
                        ]
                    )
                    
            elif source_auth_method == SourceAuthMethod.INSTANCE_PROFILE:
                # Use instance profile (EC2/ECS metadata)
                sts_client = boto3.client(
                    "sts",
                    **merge_vpc_boto3_kwargs("sts", region, {"region_name": region}),
                )
                source_info = "instance profile"

            else:
                # Default: use environment variables or default credential chain
                sts_client = boto3.client(
                    "sts",
                    **merge_vpc_boto3_kwargs("sts", region, {"region_name": region}),
                )
                source_info = "environment/default credentials"
            
            # First, verify source credentials are valid
            try:
                source_identity = sts_client.get_caller_identity()
                source_account = source_identity.get('Account', 'unknown')
                source_arn = source_identity.get('Arn', 'unknown')
                print(f"[DBG] DEBUG: Source credentials valid - Account: {source_account}, ARN: {source_arn}")
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                return RoleValidationResponse(
                    valid=False,
                    error=f"Source credentials invalid: {error_code}",
                    troubleshooting=[
                        f"The source credentials ({source_info}) are invalid or expired",
                        "Verify the source credentials are correct",
                        "Check that the source credentials have not expired"
                    ]
                )
            
            # Assume the role using source credentials
            response = sts_client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="NexusInstaller",
                DurationSeconds=3600
            )
            
            # Extract and cache credentials
            creds = response['Credentials']
            aws_credentials = AWSCredentials(
                access_key_id=creds['AccessKeyId'],
                secret_access_key=creds['SecretAccessKey'],
                session_token=creds['SessionToken'],
                expiration=creds['Expiration']
            )
            
            cache_key = f"role_arn:{role_arn}"
            AWSAuthService._credentials_cache[cache_key] = aws_credentials
            
            print(f"[DBG] DEBUG: Successfully assumed role {role_arn} using {source_info}")
            
            return RoleValidationResponse(
                valid=True,
                success=True,
                account_id=account_id,
                credentials={
                    "access_key_id": creds['AccessKeyId'],
                    "secret_access_key": creds['SecretAccessKey'],
                    "session_token": creds['SessionToken']
                }
            )
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            troubleshooting = []
            if error_code == 'AccessDenied':
                troubleshooting = [
                    "Source credentials cannot assume this role",
                    "Check the role's trust policy allows the source identity",
                    "Ensure the source identity has sts:AssumeRole permission",
                    "Verify the role ARN is correct"
                ]
            elif error_code == 'InvalidClientTokenId':
                troubleshooting = [
                    "Source AWS credentials are invalid or expired",
                    "Verify the source credentials are correct",
                ]
            elif error_code == 'MalformedPolicyDocument':
                troubleshooting = [
                    "The role's trust policy is malformed",
                    "Check the IAM role configuration in AWS Console"
                ]
            else:
                troubleshooting = [f"AWS Error: {error_message}"]
            
            return RoleValidationResponse(
                valid=False,
                error=f"{error_code}: {error_message}",
                troubleshooting=troubleshooting
            )
        except Exception as e:
            return RoleValidationResponse(
                valid=False,
                error=f"Unexpected error: {str(e)}",
                troubleshooting=["Check application logs for details"]
            )
    
    @staticmethod
    def _validate_access_key(
        access_key_id: str,
        secret_access_key: str,
        region: str
    ) -> RoleValidationResponse:
        """Validate Access Key authentication.
        
        Args:
            access_key_id: AWS Access Key ID
            secret_access_key: AWS Secret Access Key
            region: AWS region
            
        Returns:
            RoleValidationResponse
        """
        if not access_key_id or not secret_access_key:
            return RoleValidationResponse(
                valid=False,
                error="Access Key ID and Secret Access Key are required",
                troubleshooting=["Provide both Access Key ID and Secret Access Key"]
            )
        
        try:
            # Create STS client with provided credentials
            sts_client = boto3.client(
                "sts",
                **merge_vpc_boto3_kwargs(
                    "sts",
                    region,
                    {
                        "region_name": region,
                        "aws_access_key_id": access_key_id,
                        "aws_secret_access_key": secret_access_key,
                    },
                ),
            )
            
            # Get caller identity to validate credentials
            response = sts_client.get_caller_identity()
            account_id = response['Account']
            
            # Cache credentials
            aws_credentials = AWSCredentials(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key
            )
            
            cache_key = f"access_key:{access_key_id}"
            AWSAuthService._credentials_cache[cache_key] = aws_credentials
            
            return RoleValidationResponse(
                valid=True,
                success=True,
                account_id=account_id,
                credentials={
                    "access_key_id": access_key_id,
                    "secret_access_key": secret_access_key
                }
            )
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            troubleshooting = []
            if error_code == 'InvalidClientTokenId':
                troubleshooting = [
                    "Access Key ID is invalid",
                    "Verify the Access Key ID is correct",
                ]
            elif error_code == 'SignatureDoesNotMatch':
                troubleshooting = [
                    "Secret Access Key is incorrect",
                    "Verify the Secret Access Key matches the Access Key ID",
                ]
            else:
                troubleshooting = [f"AWS Error: {error_message}"]
            
            return RoleValidationResponse(
                valid=False,
                error=f"{error_code}: {error_message}",
                troubleshooting=troubleshooting
            )
        except Exception as e:
            return RoleValidationResponse(
                valid=False,
                error=f"Unexpected error: {str(e)}",
                troubleshooting=["Check application logs for details"]
            )
    
    @staticmethod
    def _validate_aws_profile(profile_name: str, region: str) -> RoleValidationResponse:
        """Validate AWS CLI Profile authentication.
        
        Args:
            profile_name: AWS CLI profile name
            region: AWS region
            
        Returns:
            RoleValidationResponse
        """
        if not profile_name:
            return RoleValidationResponse(
                valid=False,
                error="Profile name is required",
                troubleshooting=["Provide an AWS CLI profile name"]
            )
        
        try:
            # Create session with profile
            session = boto3.Session(profile_name=profile_name, region_name=region)
            sts_client = session.client('sts')
            
            # Get caller identity
            response = sts_client.get_caller_identity()
            account_id = response['Account']
            
            # Get credentials from session
            credentials = session.get_credentials()
            aws_credentials = AWSCredentials(
                access_key_id=credentials.access_key,
                secret_access_key=credentials.secret_key,
                session_token=credentials.token
            )
            
            cache_key = f"profile:{profile_name}"
            AWSAuthService._credentials_cache[cache_key] = aws_credentials
            
            return RoleValidationResponse(
                valid=True,
                success=True,
                account_id=account_id,
                credentials={
                    "access_key_id": credentials.access_key,
                    "secret_access_key": credentials.secret_key,
                    "session_token": credentials.token
                }
            )
            
        except Exception as e:
            error_message = str(e)
            troubleshooting = [
                f"Profile '{profile_name}' not found or invalid",
                "Run 'aws configure --profile <name>' to create the profile",
                "Check ~/.aws/credentials and ~/.aws/config files",
            ]
            
            return RoleValidationResponse(
                valid=False,
                error=error_message,
                troubleshooting=troubleshooting
            )
    
    @staticmethod
    def _validate_instance_profile(region: str) -> RoleValidationResponse:
        """Validate Instance Profile authentication (EC2/ECS).
        
        Args:
            region: AWS region
            
        Returns:
            RoleValidationResponse
        """
        try:
            # Try to use instance metadata
            sts_client = boto3.client(
                "sts",
                **merge_vpc_boto3_kwargs("sts", region, {"region_name": region}),
            )
            
            # Get caller identity
            response = sts_client.get_caller_identity()
            account_id = response['Account']
            arn = response['Arn']
            
            # Verify it's an instance profile
            if 'assumed-role' not in arn:
                return RoleValidationResponse(
                    valid=False,
                    error="Not running on an EC2 instance with an instance profile",
                    troubleshooting=[
                        "Instance profile authentication only works on EC2/ECS",
                        "Ensure the instance has an IAM role attached",
                    ]
                )
            
            # Get credentials from boto3 (will use instance metadata)
            session = boto3.Session(region_name=region)
            credentials = session.get_credentials()
            
            aws_credentials = AWSCredentials(
                access_key_id=credentials.access_key,
                secret_access_key=credentials.secret_key,
                session_token=credentials.token
            )
            
            cache_key = "instance_profile"
            AWSAuthService._credentials_cache[cache_key] = aws_credentials
            
            return RoleValidationResponse(
                valid=True,
                account_id=account_id
            )
            
        except Exception as e:
            return RoleValidationResponse(
                valid=False,
                error=f"Instance profile not available: {str(e)}",
                troubleshooting=[
                    "Ensure you're running on an EC2 instance",
                    "Verify the instance has an IAM role attached",
                    "Check instance metadata service is accessible",
                ]
            )
    
    @staticmethod
    def _validate_adfs_saml(
        adfs_url: str,
        username: str,
        password: str,
        region: str
    ) -> RoleValidationResponse:
        """Validate ADFS/SAML authentication using pure Python.
        
        Uses requests library with NTLM/form-based auth - no aws-adfs.exe required.
        This method validates credentials and returns success if roles are found.
        
        Args:
            adfs_url: ADFS endpoint URL (e.g., adfs.devfactory.com/adfs/ls/idpinitiatedsignon)
            username: ADFS username (e.g., devfactory\\username)
            password: ADFS password
            region: AWS region
            
        Returns:
            RoleValidationResponse with diagnostics
        """
        import base64
        import xml.etree.ElementTree as ET
        import requests
        from requests_ntlm import HttpNtlmAuth
        from bs4 import BeautifulSoup
        import urllib3
        
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        start_time = time.time()
        diagnostics = None
        
        if not adfs_url or not username or not password:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="input_validation",
                auth_method="adfs_saml",
                error_code="MISSING_INPUT",
                error_message="ADFS URL, username, and password are required",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="ADFS URL, username, and password are required",
                troubleshooting=["Provide all ADFS authentication details"],
                diagnostics=diagnostics
            )
        
        # Extract host from URL
        adfs_host = AWSAuthService._extract_adfs_host(adfs_url)
        full_adfs_url = f"https://{adfs_host}" if not adfs_host.startswith('http') else adfs_host
        endpoint_host = adfs_host.split('/')[0] if '/' in adfs_host else adfs_host
        
        # Step 1: Check endpoint reachability
        logger.info(f"[DIAG] Checking ADFS endpoint reachability: {adfs_host}")
        is_reachable, reachability_error = AWSAuthService._check_endpoint_reachability(endpoint_host)
        
        if not is_reachable:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="endpoint_reachability",
                auth_method="adfs_saml",
                endpoint_url=full_adfs_url,
                endpoint_reachable=False,
                error_code="ENDPOINT_UNREACHABLE",
                error_message=reachability_error,
                network_error=reachability_error,
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error=f"ADFS endpoint unreachable: {reachability_error}",
                troubleshooting=[
                    f"Cannot connect to ADFS server at {endpoint_host}:443",
                    "Check network connectivity and firewall rules",
                    "Verify the ADFS URL is correct",
                    "Ensure you are on the corporate network or VPN",
                ],
                diagnostics=diagnostics
            )
        
        logger.info(f"[DIAG] ADFS endpoint is reachable, testing HTTPS...")
        
        # Step 2: Test HTTPS endpoint
        https_success, http_status, https_error = AWSAuthService._test_https_endpoint(full_adfs_url)
        
        if not https_success:
            ssl_error = https_error if 'SSL' in str(https_error) or 'TLS' in str(https_error) else None
            network_error = https_error if not ssl_error else None
            
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="https_test",
                auth_method="adfs_saml",
                endpoint_url=full_adfs_url,
                endpoint_reachable=True,
                http_status_code=http_status,
                error_code="HTTPS_FAILED",
                error_message=https_error,
                ssl_error=ssl_error,
                network_error=network_error,
                start_time=start_time
            )
            
            troubleshooting = [
                f"HTTPS connection to {full_adfs_url} failed",
                "Check if the ADFS URL is correct",
            ]
            if ssl_error:
                troubleshooting.extend([
                    "SSL/TLS certificate issue detected",
                    "The server certificate may be self-signed or expired",
                ])
            
            return RoleValidationResponse(
                valid=False,
                error=f"ADFS HTTPS test failed: {https_error}",
                troubleshooting=troubleshooting,
                diagnostics=diagnostics
            )
        
        # Step 3: Validate this is actually an ADFS endpoint
        is_adfs, adfs_check_details = AWSAuthService._validate_adfs_endpoint(endpoint_host)
        
        if not is_adfs:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="adfs_validation",
                auth_method="adfs_saml",
                endpoint_url=full_adfs_url,
                endpoint_reachable=True,
                http_status_code=http_status,
                error_code="NOT_ADFS_ENDPOINT",
                error_message=adfs_check_details,
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error=f"Not a valid ADFS endpoint: {adfs_check_details}",
                troubleshooting=[
                    "Verify the URL points to an ADFS server",
                    "Example: adfs.yourcompany.com/adfs/ls/idpinitiatedsignon",
                ],
                diagnostics=diagnostics
            )
        
        logger.info(f"[DIAG] HTTPS test passed (status: {http_status}), proceeding with ADFS auth...")
        
        try:
            # Create a session for ADFS authentication
            session = requests.Session()
            session.verify = False  # Disable SSL verification for corporate ADFS
            
            # Build the ADFS IDP-initiated sign-on URL for AWS
            if '/adfs/ls' in adfs_host.lower():
                idp_entry_url = full_adfs_url
            else:
                idp_entry_url = f"https://{endpoint_host}/adfs/ls/IdpInitiatedSignOn.aspx?loginToRp=urn:amazon:webservices"
            
            # Step 4: Try NTLM authentication first
            saml_response = None
            try:
                auth = HttpNtlmAuth(username, password)
                response = session.get(idp_entry_url, auth=auth, timeout=30)
                
                if response.status_code == 200 and 'SAMLResponse' in response.text:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    saml_input = soup.find('input', {'name': 'SAMLResponse'})
                    if saml_input:
                        saml_response = saml_input.get('value')
                        logger.info("[DIAG] Got SAML response from NTLM auth")
            except Exception as e:
                logger.info(f"[DIAG] NTLM auth failed: {e}, trying form-based")
            
            # Step 5: If no SAML response yet, try form-based login
            if not saml_response:
                response = session.get(idp_entry_url, timeout=30)
                soup = BeautifulSoup(response.text, 'html.parser')
                
                form = soup.find('form')
                if form:
                    form_action = form.get('action', '')
                    if form_action.startswith('/'):
                        form_action = f"https://{endpoint_host}{form_action}"
                    elif not form_action.startswith('http'):
                        form_action = f"https://{endpoint_host}/adfs/ls/{form_action}"
                    
                    form_data = {}
                    for input_tag in form.find_all('input'):
                        name = input_tag.get('name')
                        value = input_tag.get('value', '')
                        if name:
                            form_data[name] = value
                    
                    form_data['UserName'] = username
                    form_data['Password'] = password
                    
                    response = session.post(form_action, data=form_data, timeout=30)
                    
                    # Check for authentication errors
                    response_lower = response.text.lower()
                    if any(err in response_lower for err in ['invalid username', 'invalid password', 
                                                              'authentication failed', 'incorrect username or password',
                                                              'logon failure', 'wrong password', 'access denied']):
                        diagnostics = AWSAuthService._create_diagnostic_info(
                            step="adfs_authentication",
                            auth_method="adfs_saml",
                            endpoint_url=full_adfs_url,
                            endpoint_reachable=True,
                            http_status_code=response.status_code,
                            error_code="INVALID_CREDENTIALS",
                            error_message="Invalid username or password",
                            start_time=start_time
                        )
                        return RoleValidationResponse(
                            valid=False,
                            error="ADFS authentication failed: Invalid username or password",
                            troubleshooting=[
                                "Verify your username format (domain\\username)",
                                "Check that your password is correct",
                                "Ensure your account is not locked",
                            ],
                            diagnostics=diagnostics
                        )
                    
                    if 'SAMLResponse' in response.text:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        saml_input = soup.find('input', {'name': 'SAMLResponse'})
                        if saml_input:
                            saml_response = saml_input.get('value')
            
            if not saml_response:
                diagnostics = AWSAuthService._create_diagnostic_info(
                    step="adfs_authentication",
                    auth_method="adfs_saml",
                    endpoint_url=full_adfs_url,
                    endpoint_reachable=True,
                    error_code="NO_SAML_RESPONSE",
                    error_message="Failed to obtain SAML response from ADFS",
                    start_time=start_time
                )
                return RoleValidationResponse(
                    valid=False,
                    error="Failed to obtain SAML response from ADFS",
                    troubleshooting=[
                        "Verify credentials are correct",
                        "Check ADFS is configured for AWS federation",
                    ],
                    diagnostics=diagnostics
                )
            
            # Step 6: Parse SAML to extract roles and validate
            saml_decoded = base64.b64decode(saml_response).decode('utf-8')
            root = ET.fromstring(saml_decoded)
            
            roles = []
            for attr in root.iter():
                if 'Attribute' in attr.tag:
                    attr_name = attr.get('Name', '')
                    if 'Role' in attr_name or 'role' in attr_name:
                        for value in attr:
                            if 'AttributeValue' in value.tag:
                                role_value = value.text
                                if role_value and 'arn:aws:iam' in role_value:
                                    parts = role_value.split(',')
                                    if len(parts) >= 2:
                                        roles.append(parts[1].strip())  # role_arn
            
            if roles:
                # Extract account ID from first role
                import re
                match = re.search(r'arn:aws:iam::(\d+):role/', roles[0])
                account_id = match.group(1) if match else None
                
                logger.info(f"[DIAG] ADFS validation successful, found {len(roles)} roles")
                
                return RoleValidationResponse(
                    valid=True,
                    account_id=account_id
                )
            else:
                diagnostics = AWSAuthService._create_diagnostic_info(
                    step="saml_parsing",
                    auth_method="adfs_saml",
                    endpoint_url=full_adfs_url,
                    endpoint_reachable=True,
                    error_code="NO_ROLES_FOUND",
                    error_message="No AWS roles found in SAML assertion",
                    start_time=start_time
                )
                return RoleValidationResponse(
                    valid=False,
                    error="No AWS roles found in SAML assertion",
                    troubleshooting=[
                        "User may not have AWS roles assigned in ADFS",
                        "Contact your administrator to assign AWS roles",
                    ],
                    diagnostics=diagnostics
                )
                
        except requests.exceptions.Timeout:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="adfs_authentication",
                auth_method="adfs_saml",
                endpoint_url=full_adfs_url,
                endpoint_reachable=True,
                error_code="TIMEOUT",
                error_message="ADFS authentication timeout",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="ADFS authentication timeout",
                troubleshooting=[
                    "ADFS server may be slow or unresponsive",
                    "Check network connectivity",
                    "Try again later",
                ],
                diagnostics=diagnostics
            )
        except Exception as e:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="adfs_authentication",
                auth_method="adfs_saml",
                endpoint_url=full_adfs_url,
                error_code="EXCEPTION",
                error_message=str(e),
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error=f"ADFS authentication error: {str(e)}",
                troubleshooting=[
                    "Check ADFS URL format",
                    "Verify username and password",
                    "Check network connectivity to ADFS server",
                ],
                diagnostics=diagnostics
            )
    
    @staticmethod
    def get_cached_credentials(cache_key: str) -> Optional[AWSCredentials]:
        """Get cached credentials.
        
        Args:
            cache_key: Cache key for credentials
            
        Returns:
            Cached credentials if available
        """
        return AWSAuthService._credentials_cache.get(cache_key)
    
    @staticmethod
    def list_aws_profiles() -> List[str]:
        """List available AWS CLI profiles.
        
        Returns:
            List of profile names
        """
        try:
            import configparser
            profiles = []
            
            # Check ~/.aws/credentials
            credentials_path = os.path.expanduser('~/.aws/credentials')
            if os.path.exists(credentials_path):
                config = configparser.ConfigParser()
                config.read(credentials_path)
                profiles.extend(config.sections())
            
            # Check ~/.aws/config
            config_path = os.path.expanduser('~/.aws/config')
            if os.path.exists(config_path):
                config = configparser.ConfigParser()
                config.read(config_path)
                for section in config.sections():
                    if section.startswith('profile '):
                        profile_name = section.replace('profile ', '')
                        if profile_name not in profiles:
                            profiles.append(profile_name)
            
            return sorted(list(set(profiles)))
        except Exception:
            return []
    
    # ADFS Role Selection Support
    # Session storage for SAML assertions
    _saml_sessions: Dict[str, Dict] = {}
    
    @staticmethod
    def fetch_adfs_roles(
        adfs_url: str,
        username: str,
        password: str,
        region: str
    ) -> Tuple[List, str]:
        """Fetch available ADFS roles without selecting one.
        
        Uses the aws-adfs Python library directly instead of CLI executable.
        
        Args:
            adfs_url: ADFS endpoint URL
            username: ADFS username
            password: ADFS password
            region: AWS region
            
        Returns:
            Tuple of (roles_list, session_id)
            
        Raises:
            Exception with detailed diagnostic information
        """
        import uuid
        import base64
        import xml.etree.ElementTree as ET
        from datetime import datetime, timedelta
        import requests
        from requests_ntlm import HttpNtlmAuth
        from bs4 import BeautifulSoup
        
        start_time = time.time()
        diagnostic_steps = []  # Track all diagnostic steps
        
        def add_step(step_name: str, status: str, details: str = None, duration_ms: int = None):
            """Add a diagnostic step."""
            step = {
                "step": step_name,
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
            if details:
                step["details"] = details
            if duration_ms:
                step["duration_ms"] = duration_ms
            diagnostic_steps.append(step)
            logger.info(f"[DIAG] Step '{step_name}': {status} - {details or ''}")
        
        def build_diagnostic_error(error_code: str, error_message: str, raw_output: str = None):
            """Build a detailed diagnostic error message."""
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Sanitize raw output - remove password
            safe_output = raw_output or ""
            if password and safe_output:
                safe_output = safe_output.replace(password, '***PASSWORD***')
            
            # Build steps summary
            steps_summary = " -> ".join([f"{s['step']}({s['status']})" for s in diagnostic_steps])
            
            return (
                f"{error_message} | "
                f"DIAGNOSTIC_INFO: error_code={error_code}, "
                f"endpoint_url={full_adfs_url}, "
                f"duration_ms={duration_ms}, "
                f"steps=[{steps_summary}], "
                f"raw_output={safe_output}"
            )
        
        # Extract host from URL
        adfs_host = AWSAuthService._extract_adfs_host(adfs_url)
        full_adfs_url = f"https://{adfs_host}" if not adfs_host.startswith('http') else adfs_host
        endpoint_host = adfs_host.split('/')[0] if '/' in adfs_host else adfs_host
        
        add_step("url_parsing", "success", f"Host: {endpoint_host}, Full URL: {full_adfs_url}")
        
        # Step 1: Check endpoint reachability
        step_start = time.time()
        is_reachable, reachability_error = AWSAuthService._check_endpoint_reachability(endpoint_host)
        step_duration = int((time.time() - step_start) * 1000)
        
        if not is_reachable:
            add_step("network_reachability", "failed", reachability_error, step_duration)
            error_type = "DNS_RESOLUTION_FAILED" if "DNS" in str(reachability_error) else "ENDPOINT_UNREACHABLE"
            raise Exception(build_diagnostic_error(
                error_type,
                f"ADFS endpoint not reachable: {reachability_error}"
            ))
        
        add_step("network_reachability", "success", f"Port 443 reachable", step_duration)
        
        # Step 2: Test HTTPS endpoint
        step_start = time.time()
        https_success, http_status, https_error = AWSAuthService._test_https_endpoint(full_adfs_url)
        step_duration = int((time.time() - step_start) * 1000)
        
        if not https_success:
            add_step("https_connection", "failed", f"HTTP error: {https_error}", step_duration)
            is_ssl_error = 'SSL' in str(https_error) or 'TLS' in str(https_error)
            error_type = "SSL_ERROR" if is_ssl_error else "HTTPS_FAILED"
            raise Exception(build_diagnostic_error(
                error_type,
                f"ADFS HTTPS connection failed: {https_error}"
            ))
        
        add_step("https_connection", "success", f"HTTP Status: {http_status}", step_duration)
        
        # Step 3: Validate this is actually an ADFS endpoint
        step_start = time.time()
        is_adfs, adfs_check_details = AWSAuthService._validate_adfs_endpoint(endpoint_host)
        step_duration = int((time.time() - step_start) * 1000)
        
        if not is_adfs:
            add_step("adfs_validation", "failed", adfs_check_details, step_duration)
            raise Exception(build_diagnostic_error(
                "NOT_ADFS_ENDPOINT",
                f"URL does not appear to be a valid ADFS endpoint: {adfs_check_details}",
                adfs_check_details
            ))
        
        add_step("adfs_validation", "success", adfs_check_details, step_duration)
        
        # Step 4: Authenticate with ADFS using Python library directly
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            add_step("adfs_authentication", "started", "Authenticating with ADFS...")
            step_start = time.time()
            
            # Create a session for ADFS authentication
            session = requests.Session()
            session.verify = False  # Disable SSL verification for corporate ADFS
            
            # Build the ADFS IDP-initiated sign-on URL for AWS
            # Must include the AWS relying party identifier
            provider_id = 'urn:amazon:webservices'
            if '/adfs/ls' in adfs_host.lower():
                # User provided full path - ensure it has the loginToRp parameter
                if 'loginToRp=' not in full_adfs_url.lower():
                    # Add the AWS relying party
                    if '?' in full_adfs_url:
                        idp_entry_url = f"{full_adfs_url}&loginToRp={provider_id}"
                    else:
                        idp_entry_url = f"{full_adfs_url}?loginToRp={provider_id}"
                else:
                    idp_entry_url = full_adfs_url
            else:
                # Construct the IDP-initiated sign-on URL
                idp_entry_url = f"https://{endpoint_host}/adfs/ls/IdpInitiatedSignOn.aspx?loginToRp={provider_id}"
            
            add_step("adfs_url_constructed", "success", f"IDP URL: {idp_entry_url}")
            
            # Headers similar to aws-adfs library
            headers = {'Accept-Language': 'en'}
            
            # Step 4a: Try direct POST with credentials (aws-adfs library approach)
            # This is the most reliable method for ADFS
            add_step("direct_post_auth", "started", "Attempting direct POST authentication")
            
            form_data = {
                'UserName': username,
                'Password': password,
                'AuthMethod': 'FormsAuthentication'
            }
            
            response = session.post(
                idp_entry_url,
                headers=headers,
                data=form_data,
                timeout=60
            )
            
            step_duration = int((time.time() - step_start) * 1000)
            
            # Check if we got a SAML response
            saml_response = None
            if 'SAMLResponse' in response.text:
                add_step("direct_post_auth", "success", f"Got SAML response via direct POST", step_duration)
                
                # Use lxml if available (more reliable), fallback to BeautifulSoup
                try:
                    import lxml.etree as LET
                    html_response = LET.fromstring(response.text, LET.HTMLParser())
                    saml_input = html_response.find('.//input[@name="SAMLResponse"]')
                    if saml_input is not None:
                        saml_response = saml_input.get('value')
                except ImportError:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    saml_input = soup.find('input', {'name': 'SAMLResponse'})
                    if saml_input:
                        saml_response = saml_input.get('value')
            else:
                add_step("direct_post_auth", "failed", "No SAML response from direct POST", step_duration)
                
                # Check if we're still on the login page (authentication failed)
                try:
                    import lxml.etree as LET
                    html_response = LET.fromstring(response.text, LET.HTMLParser())
                    password_input = html_response.find('.//input[@name="Password"]')
                    error_elem = html_response.find('.//*[@id="errorText"]')
                    
                    if password_input is not None:
                        error_text = ""
                        if error_elem is not None and error_elem.text:
                            error_text = error_elem.text.strip()
                        
                        if error_text:
                            raise Exception(build_diagnostic_error(
                                "INVALID_CREDENTIALS",
                                f"ADFS authentication failed: {error_text}",
                                response.text[:1000]
                            ))
                        else:
                            # Try NTLM as fallback
                            add_step("ntlm_auth", "started", "Trying NTLM authentication as fallback")
                            step_start = time.time()
                            
                            auth = HttpNtlmAuth(username, password)
                            response = session.get(idp_entry_url, auth=auth, headers=headers, timeout=30)
                            step_duration = int((time.time() - step_start) * 1000)
                            
                            if 'SAMLResponse' in response.text:
                                add_step("ntlm_auth", "success", "Got SAML response via NTLM", step_duration)
                                html_response = LET.fromstring(response.text, LET.HTMLParser())
                                saml_input = html_response.find('.//input[@name="SAMLResponse"]')
                                if saml_input is not None:
                                    saml_response = saml_input.get('value')
                            else:
                                add_step("ntlm_auth", "failed", "No SAML response from NTLM", step_duration)
                except ImportError:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    password_input = soup.find('input', {'name': 'Password'})
                    
                    if password_input:
                        error_elem = soup.find(id='errorText')
                        error_text = error_elem.text.strip() if error_elem and error_elem.text else ""
                        
                        if error_text:
                            raise Exception(build_diagnostic_error(
                                "INVALID_CREDENTIALS",
                                f"ADFS authentication failed: {error_text}",
                                response.text[:1000]
                            ))
                        else:
                            # Try NTLM as fallback
                            add_step("ntlm_auth", "started", "Trying NTLM authentication as fallback")
                            step_start = time.time()
                            
                            auth = HttpNtlmAuth(username, password)
                            response = session.get(idp_entry_url, auth=auth, headers=headers, timeout=30)
                            step_duration = int((time.time() - step_start) * 1000)
                            
                            if 'SAMLResponse' in response.text:
                                add_step("ntlm_auth", "success", "Got SAML response via NTLM", step_duration)
                                soup = BeautifulSoup(response.text, 'html.parser')
                                saml_input = soup.find('input', {'name': 'SAMLResponse'})
                                if saml_input:
                                    saml_response = saml_input.get('value')
                            else:
                                add_step("ntlm_auth", "failed", "No SAML response from NTLM", step_duration)
            
            if not saml_response:
                raise Exception(build_diagnostic_error(
                    "NO_SAML_RESPONSE",
                    "Failed to obtain SAML response from ADFS. Authentication may have failed.",
                    response.text[:1000]
                ))
            
            # Step 5: Parse the SAML assertion to extract roles
            add_step("saml_parsing", "started", "Parsing SAML assertion for roles")
            step_start = time.time()
            
            try:
                # Decode the SAML response
                saml_decoded = base64.b64decode(saml_response).decode('utf-8')
                
                # Parse the XML
                root = ET.fromstring(saml_decoded)
                
                # Define namespaces
                namespaces = {
                    'saml2p': 'urn:oasis:names:tc:SAML:2.0:protocol',
                    'saml2': 'urn:oasis:names:tc:SAML:2.0:assertion',
                    'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
                    'saml': 'urn:oasis:names:tc:SAML:2.0:assertion',
                }
                
                # Find all role attributes
                # AWS roles are in the attribute with Name="https://aws.amazon.com/SAML/Attributes/Role"
                roles = []
                seen_role_arns = set()  # Track seen role ARNs to avoid duplicates
                
                # Find Attribute elements (iterate once, not per namespace)
                for attr in root.iter():
                    if 'Attribute' in attr.tag:
                        attr_name = attr.get('Name', '')
                        if 'Role' in attr_name or 'role' in attr_name:
                            # Found role attribute, get values
                            for value in attr:
                                if 'AttributeValue' in value.tag:
                                    role_value = value.text
                                    if role_value and 'arn:aws:iam' in role_value:
                                        # Parse the role value: principal_arn,role_arn
                                        parts = role_value.split(',')
                                        if len(parts) >= 2:
                                            principal_arn = parts[0].strip()
                                            role_arn = parts[1].strip()
                                            
                                            # Skip if we've already seen this role
                                            if role_arn in seen_role_arns:
                                                continue
                                            seen_role_arns.add(role_arn)
                                            
                                            # Extract account ID and role name
                                            import re
                                            match = re.search(r'arn:aws:iam::(\d+):role/(.+)', role_arn)
                                            if match:
                                                account_id = match.group(1)
                                                role_name = match.group(2)
                                                
                                                roles.append(ADFSRole(
                                                    role_arn=role_arn,
                                                    principal_arn=principal_arn,
                                                    account_id=account_id,
                                                    role_name=role_name,
                                                    account_alias=None
                                                ))
                
                step_duration = int((time.time() - step_start) * 1000)
                
                if roles:
                    add_step("saml_parsing", "success", f"Found {len(roles)} roles", step_duration)
                    
                    # Generate session ID and cache
                    session_id = str(uuid.uuid4())
                    AWSAuthService._saml_sessions[session_id] = {
                        'adfs_url': adfs_url,
                        'username': username,
                        'password': password,
                        'region': region,
                        'roles': [r.dict() for r in roles],
                        'saml_response': saml_response,  # Cache for role selection
                        'created_at': datetime.now(),
                        'expires_at': datetime.now() + timedelta(minutes=30),
                    }
                    
                    return roles, session_id
                else:
                    add_step("saml_parsing", "failed", "No roles found in SAML assertion", step_duration)
                    raise Exception(build_diagnostic_error(
                        "NO_ROLES_FOUND",
                        "No AWS roles found in SAML assertion. User may not have AWS roles assigned in ADFS.",
                        saml_decoded[:1000]
                    ))
                    
            except ET.ParseError as e:
                step_duration = int((time.time() - step_start) * 1000)
                add_step("saml_parsing", "failed", f"XML parse error: {str(e)}", step_duration)
                raise Exception(build_diagnostic_error(
                    "SAML_PARSE_ERROR",
                    f"Failed to parse SAML assertion: {str(e)}",
                    saml_response[:500] if saml_response else "No SAML response"
                ))
                
        except requests.exceptions.Timeout:
            raise Exception(build_diagnostic_error(
                "TIMEOUT",
                "ADFS authentication timeout",
                None
            ))
        except Exception as e:
            if "DIAGNOSTIC_INFO" in str(e):
                raise  # Re-raise if already formatted
            raise Exception(f"Failed to fetch ADFS roles: {str(e)}")
    
    @staticmethod
    def select_adfs_role(
        session_id: str,
        role_arn: str,
        region: str
    ) -> RoleValidationResponse:
        """Select an ADFS role and get credentials using AWS STS AssumeRoleWithSAML.
        
        Uses pure Python approach - no aws-adfs.exe subprocess required.
        Uses the cached SAML response from fetch_adfs_roles to assume the role.
        
        Args:
            session_id: Session ID from fetch_adfs_roles
            role_arn: Selected role ARN
            region: AWS region
            
        Returns:
            RoleValidationResponse with credentials and diagnostics
        """
        from datetime import datetime
        
        start_time = time.time()
        
        # Retrieve session
        session = AWSAuthService._saml_sessions.get(session_id)
        if not session:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="session_validation",
                auth_method="adfs_saml",
                error_code="SESSION_NOT_FOUND",
                error_message="Session expired or invalid",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="Session expired or invalid",
                troubleshooting=[
                    "Session may have expired (30 minute timeout)",
                    "Please fetch roles again",
                ],
                diagnostics=diagnostics
            )
        
        # Check if session expired
        if datetime.now() > session['expires_at']:
            del AWSAuthService._saml_sessions[session_id]
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="session_validation",
                auth_method="adfs_saml",
                error_code="SESSION_EXPIRED",
                error_message="Session expired",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="Session expired",
                troubleshooting=["Please fetch roles again"],
                diagnostics=diagnostics
            )
        
        # Find the selected role and get its principal_arn
        roles = session['roles']
        selected_role = None
        for role in roles:
            if role['role_arn'] == role_arn:
                selected_role = role
                break
        
        if selected_role is None:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="role_validation",
                auth_method="adfs_saml",
                error_code="ROLE_NOT_FOUND",
                error_message=f"Selected role {role_arn} not found in session",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="Selected role not found in session",
                troubleshooting=["Please fetch roles again"],
                diagnostics=diagnostics
            )
        
        # Get the cached SAML response
        saml_response = session.get('saml_response')
        if not saml_response:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="saml_validation",
                auth_method="adfs_saml",
                error_code="NO_SAML_RESPONSE",
                error_message="SAML response not found in session",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="SAML response not found in session",
                troubleshooting=["Please fetch roles again"],
                diagnostics=diagnostics
            )
        
        # Extract role and principal ARNs
        principal_arn = selected_role.get('principal_arn')
        username = session.get('username', 'unknown')
        
        if not principal_arn:
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="role_validation",
                auth_method="adfs_saml",
                error_code="NO_PRINCIPAL_ARN",
                error_message="Principal ARN not found for selected role",
                start_time=start_time
            )
            return RoleValidationResponse(
                valid=False,
                error="Principal ARN not found for selected role",
                troubleshooting=["Please fetch roles again"],
                diagnostics=diagnostics
            )
        
        logger.info(f"[DIAG] Assuming role {role_arn} with principal {principal_arn}")
        
        try:
            # Use AWS STS AssumeRoleWithSAML to get credentials
            # This is the pure Python approach - no aws-adfs.exe needed
            sts_client = boto3.client(
                "sts",
                **merge_vpc_boto3_kwargs("sts", region, {"region_name": region}),
            )
            
            response = sts_client.assume_role_with_saml(
                RoleArn=role_arn,
                PrincipalArn=principal_arn,
                SAMLAssertion=saml_response,
                DurationSeconds=3600  # 1 hour
            )
            
            # Extract credentials from response
            creds = response['Credentials']
            access_key = creds['AccessKeyId']
            secret_key = creds['SecretAccessKey']
            session_token = creds['SessionToken']
            expiration = creds['Expiration']
            
            # Get account ID from the assumed role identity
            account_id = response.get('AssumedRoleUser', {}).get('Arn', '').split(':')[4] if response.get('AssumedRoleUser') else None
            
            # If we couldn't get account_id from response, extract from role_arn
            if not account_id:
                import re
                match = re.search(r'arn:aws:iam::(\d+):role/', role_arn)
                if match:
                    account_id = match.group(1)
            
            # Cache credentials
            aws_credentials = AWSCredentials(
                access_key_id=access_key,
                secret_access_key=secret_key,
                session_token=session_token,
                expiration=expiration
            )
            
            cache_key = f"adfs:{username}:{role_arn}"
            AWSAuthService._credentials_cache[cache_key] = aws_credentials
            
            logger.info(f"[DIAG] Successfully assumed role {role_arn} for account {account_id}")
            
            # NOTE: Do NOT delete session after successful use
            # This allows users to re-authenticate or select different roles
            # without having to re-fetch roles. Session will expire naturally
            # based on expires_at timestamp (30 minutes).
            
            return RoleValidationResponse(
                valid=True,
                success=True,
                account_id=account_id,
                credentials={
                    "access_key_id": access_key,
                    "secret_access_key": secret_key,
                    "session_token": session_token
                }
            )
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            
            logger.error(f"[DIAG] STS AssumeRoleWithSAML failed: {error_code} - {error_message}")
            
            # Map AWS error codes to user-friendly messages
            troubleshooting = []
            if error_code == 'ExpiredTokenException':
                troubleshooting = [
                    "SAML assertion has expired",
                    "Please fetch roles again to get a fresh SAML token",
                ]
                error_code = "SAML_EXPIRED"
            elif error_code == 'InvalidIdentityToken':
                troubleshooting = [
                    "SAML assertion is invalid or malformed",
                    "Please fetch roles again",
                    "Verify ADFS is correctly configured for AWS",
                ]
                error_code = "INVALID_SAML"
            elif error_code == 'AccessDenied':
                troubleshooting = [
                    "Access denied when assuming role",
                    "Verify the role trust policy allows SAML federation",
                    "Check that your ADFS user has permission for this role",
                ]
                error_code = "ACCESS_DENIED"
            elif error_code == 'MalformedPolicyDocument':
                troubleshooting = [
                    "Role trust policy is malformed",
                    "Contact your AWS administrator",
                ]
            else:
                troubleshooting = [
                    f"AWS STS error: {error_message}",
                    "Try fetching roles again",
                ]
            
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="sts_assume_role",
                auth_method="adfs_saml",
                error_code=error_code,
                error_message=error_message,
                start_time=start_time
            )
            
            return RoleValidationResponse(
                valid=False,
                error=f"Failed to assume role: {error_message}",
                troubleshooting=troubleshooting,
                diagnostics=diagnostics
            )
            
        except BotoCoreError as e:
            logger.error(f"[DIAG] BotoCore error: {str(e)}")
            
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="sts_assume_role",
                auth_method="adfs_saml",
                error_code="BOTO_ERROR",
                error_message=str(e),
                start_time=start_time
            )
            
            return RoleValidationResponse(
                valid=False,
                error=f"AWS SDK error: {str(e)}",
                troubleshooting=[
                    "Check network connectivity to AWS",
                    "Verify AWS region is correct",
                    "Try fetching roles again",
                ],
                diagnostics=diagnostics
            )
            
        except Exception as e:
            logger.error(f"[DIAG] Unexpected error in select_adfs_role: {str(e)}")
            
            diagnostics = AWSAuthService._create_diagnostic_info(
                step="sts_assume_role",
                auth_method="adfs_saml",
                error_code="EXCEPTION",
                error_message=str(e),
                start_time=start_time
            )
            
            return RoleValidationResponse(
                valid=False,
                error=f"Role selection error: {str(e)}",
                troubleshooting=[
                    "Check application logs",
                    "Try fetching roles again",
                ],
                diagnostics=diagnostics
            )
    
    @staticmethod
    def cleanup_expired_sessions():
        """Clean up expired SAML sessions."""
        from datetime import datetime
        expired_sessions = [
            sid for sid, session in AWSAuthService._saml_sessions.items()
            if datetime.now() > session['expires_at']
        ]
        for sid in expired_sessions:
            del AWSAuthService._saml_sessions[sid]


# Global instance
_aws_auth_service: Optional[AWSAuthService] = None


def get_aws_auth_service() -> AWSAuthService:
    """Get the global AWS auth service instance.
    
    Returns:
        AWSAuthService instance
    """
    global _aws_auth_service
    if _aws_auth_service is None:
        _aws_auth_service = AWSAuthService()
    return _aws_auth_service


