"""
Cognito User Service
Handles post-deployment Cognito user password setup
"""
import logging
from typing import Dict, Optional, List, Callable
import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs

logger = logging.getLogger(__name__)


class CognitoUserService:
    """Service for managing Cognito users after deployment"""
    
    DEFAULT_PASSWORD = "Admin@Temp123!"
    
    # Users created by the cognito-stack.yaml template
    USER_TEMPLATES = {
        'admin': {
            'username_pattern': 'admin@{capability_name}.local',
            'environments': ['dev', 'stage', 'prod']  # All environments
        },
        'executive': {
            'username_pattern': 'executive@{capability_name}.test',
            'environments': ['dev', 'prod']  # Test users only in dev/prod
        },
        'salesmanager': {
            'username_pattern': 'salesmanager@{capability_name}.test',
            'environments': ['dev', 'prod']
        },
        'rep': {
            'username_pattern': 'rep@{capability_name}.test',
            'environments': ['dev', 'prod']
        }
    }
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """Initialize with optional AWS credentials"""
        self.credentials = credentials or {}
    
    def _get_client(self, service: str, region: str):
        """Get boto3 client with credentials"""
        if self.credentials:
            kw = {
                "region_name": region,
                "aws_access_key_id": self.credentials.get("aws_access_key_id")
                or self.credentials.get("access_key_id"),
                "aws_secret_access_key": self.credentials.get("aws_secret_access_key")
                or self.credentials.get("secret_access_key"),
                "aws_session_token": self.credentials.get("aws_session_token")
                or self.credentials.get("session_token"),
            }
            return boto3.client(service, **merge_vpc_boto3_kwargs(service, region, kw))
        return boto3.client(
            service, **merge_vpc_boto3_kwargs(service, region, {"region_name": region})
        )
    
    def set_user_password(
        self,
        user_pool_id: str,
        username: str,
        password: str,
        region: str,
        permanent: bool = False
    ) -> Dict[str, any]:
        """
        Set password for a Cognito user
        
        Args:
            user_pool_id: Cognito User Pool ID
            username: User's username (email)
            password: Password to set
            region: AWS region
            permanent: If True, set as permanent password (user won't need to change)
            
        Returns:
            Dict with success status and any error
        """
        try:
            client = self._get_client('cognito-idp', region)
            
            client.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=username,
                Password=password,
                Permanent=permanent
            )
            
            logger.info(f"Successfully set password for user {username}")
            return {'success': True, 'username': username}
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']
            
            if error_code == 'UserNotFoundException':
                logger.warning(f"User {username} not found in pool {user_pool_id}")
                return {'success': False, 'username': username, 'error': 'User not found'}
            
            logger.error(f"Failed to set password for {username}: {error_msg}")
            return {'success': False, 'username': username, 'error': error_msg}
            
        except Exception as e:
            logger.error(f"Unexpected error setting password for {username}: {str(e)}")
            return {'success': False, 'username': username, 'error': str(e)}

    def setup_deployment_users(
        self,
        user_pool_id: str,
        capability_name: str,
        environment: str,
        region: str,
        password: Optional[str] = None,
        callback: Optional[Callable] = None
    ) -> Dict[str, any]:
        """
        Set up passwords for all users created by the Cognito stack
        
        Args:
            user_pool_id: Cognito User Pool ID
            capability_name: Name of the capability (used in username pattern)
            environment: Environment (dev, stage, prod)
            region: AWS region
            password: Password to set (defaults to DEFAULT_PASSWORD)
            callback: Optional progress callback
            
        Returns:
            Dict with results for each user
        """
        password = password or self.DEFAULT_PASSWORD
        results = {
            'success': True,
            'users': [],
            'errors': []
        }
        
        # Sanitize capability name to match CloudFormation template format
        # CloudFormation uses lowercase with hyphens (e.g., "call-processing")
        sanitized_name = capability_name.lower().replace(' ', '-').replace('_', '-')
        
        if callback:
            callback(f"[LOCK] Setting up Cognito user passwords...")
        
        for user_type, config in self.USER_TEMPLATES.items():
            # Check if this user type is created in this environment
            if environment not in config['environments']:
                if callback:
                    callback(f"  ⏭ Skipping {user_type} (not created in {environment})")
                continue
            
            # Build username from pattern using sanitized capability name
            username = config['username_pattern'].format(capability_name=sanitized_name)
            
            if callback:
                callback(f"  [KEY] Setting password for {username}...")
            
            result = self.set_user_password(
                user_pool_id=user_pool_id,
                username=username,
                password=password,
                region=region,
                permanent=False  # User must change on first login
            )
            
            results['users'].append(result)
            
            if result['success']:
                if callback:
                    callback(f"  [OK] Password set for {username}")
            else:
                results['success'] = False
                results['errors'].append(result)
                if callback:
                    callback(f"  [X] Failed for {username}: {result.get('error')}")
        
        if callback:
            success_count = sum(1 for u in results['users'] if u['success'])
            total_count = len(results['users'])
            callback(f"[LOCK] Cognito user setup complete: {success_count}/{total_count} users configured")
        
        return results
    
    def get_user_pool_users(
        self,
        user_pool_id: str,
        region: str
    ) -> List[Dict[str, any]]:
        """
        List users in a Cognito User Pool
        
        Args:
            user_pool_id: Cognito User Pool ID
            region: AWS region
            
        Returns:
            List of user info dicts
        """
        try:
            client = self._get_client('cognito-idp', region)
            
            users = []
            paginator = client.get_paginator('list_users')
            
            for page in paginator.paginate(UserPoolId=user_pool_id):
                for user in page.get('Users', []):
                    user_info = {
                        'username': user.get('Username'),
                        'status': user.get('UserStatus'),
                        'enabled': user.get('Enabled'),
                        'created': user.get('UserCreateDate'),
                        'attributes': {
                            attr['Name']: attr['Value']
                            for attr in user.get('Attributes', [])
                        }
                    }
                    users.append(user_info)
            
            return users
            
        except Exception as e:
            logger.error(f"Failed to list users: {str(e)}")
            return []


# Singleton instance
cognito_user_service = CognitoUserService()
