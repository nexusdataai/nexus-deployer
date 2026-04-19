"""
Cognito User Export Service

Handles user data backup before Cognito modifications during update workflows.
Exports all users from a Cognito User Pool to a JSON file for recovery purposes.
"""
import json
import logging
import boto3
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.models.cognito_models import UserExportRecord, ExportResult


logger = logging.getLogger(__name__)


class CognitoUserExportService:
    """
    Service for exporting users from Cognito User Pools.
    """

    # Default export directory
    DEFAULT_EXPORT_DIR = Path("exports/cognito")

    def __init__(
        self,
        credentials: Optional[Dict[str, str]] = None,
        export_dir: Optional[Path] = None
    ):
        """
        Initialize the Cognito user export service.
        
        Args:
            credentials: Optional AWS credentials dict
            export_dir: Directory to store export files
        """
        self.credentials = credentials or {}
        self.export_dir = export_dir or self.DEFAULT_EXPORT_DIR
        self._clients_cache: Dict[str, Any] = {}

    def _get_client(self, service: str, region: str) -> Any:
        """
        Get a boto3 client for the specified service and region.
        """
        cache_key = f"{service}:{region}"
        
        if cache_key not in self._clients_cache:
            kw = {"region_name": region, **self.credentials}
            self._clients_cache[cache_key] = boto3.client(
                service, **merge_vpc_boto3_kwargs(service, region, kw)
            )
        
        return self._clients_cache[cache_key]

    def list_users(
        self,
        user_pool_id: str,
        region: str
    ) -> List[UserExportRecord]:
        """
        List all users in a Cognito User Pool with pagination.
        
        Args:
            user_pool_id: Cognito User Pool ID
            region: AWS region
            
        Returns:
            List of UserExportRecord objects
        """
        users = []
        
        try:
            cognito_client = self._get_client('cognito-idp', region)
            
            # Paginate through all users
            paginator = cognito_client.get_paginator('list_users')
            
            for page in paginator.paginate(UserPoolId=user_pool_id):
                for user in page.get('Users', []):
                    user_record = self._convert_user_to_record(user, user_pool_id, region)
                    if user_record:
                        users.append(user_record)
            
            logger.info(f"[EXPORT] Listed {len(users)} users from User Pool {user_pool_id}")
            
        except ClientError as e:
            logger.error(f"[EXPORT] Error listing users from {user_pool_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"[EXPORT] Unexpected error listing users: {e}")
            raise
        
        return users

    def _convert_user_to_record(
        self,
        user: Dict[str, Any],
        user_pool_id: str,
        region: str
    ) -> Optional[UserExportRecord]:
        """
        Convert a Cognito user response to a UserExportRecord.
        
        Args:
            user: User data from Cognito API
            user_pool_id: User Pool ID
            region: AWS region
            
        Returns:
            UserExportRecord or None if conversion fails
        """
        try:
            # Extract attributes
            attributes = {}
            email = ""
            
            for attr in user.get('Attributes', []):
                attr_name = attr.get('Name', '')
                attr_value = attr.get('Value', '')
                attributes[attr_name] = attr_value
                
                if attr_name == 'email':
                    email = attr_value
            
            # Get user groups
            groups = self._get_user_groups(
                user_pool_id=user_pool_id,
                username=user.get('Username', ''),
                region=region
            )
            
            return UserExportRecord(
                username=user.get('Username', ''),
                email=email,
                attributes=attributes,
                groups=groups,
                enabled=user.get('Enabled', True),
                status=user.get('UserStatus', 'UNKNOWN'),
                created_at=user.get('UserCreateDate')
            )
            
        except Exception as e:
            logger.warning(f"[EXPORT] Error converting user record: {e}")
            return None

    def _get_user_groups(
        self,
        user_pool_id: str,
        username: str,
        region: str
    ) -> List[str]:
        """
        Get groups for a specific user.
        
        Args:
            user_pool_id: User Pool ID
            username: Username to get groups for
            region: AWS region
            
        Returns:
            List of group names
        """
        groups = []
        
        try:
            cognito_client = self._get_client('cognito-idp', region)
            
            response = cognito_client.admin_list_groups_for_user(
                UserPoolId=user_pool_id,
                Username=username
            )
            
            for group in response.get('Groups', []):
                groups.append(group.get('GroupName', ''))
                
        except ClientError as e:
            logger.warning(f"[EXPORT] Error getting groups for user {username}: {e}")
        except Exception as e:
            logger.warning(f"[EXPORT] Unexpected error getting user groups: {e}")
        
        return groups

    def export_users(
        self,
        user_pool_id: str,
        region: str,
        capability_name: str,
        environment: str
    ) -> ExportResult:
        """
        Export all users from a Cognito User Pool to a JSON file.
        
        Args:
            user_pool_id: Cognito User Pool ID
            region: AWS region
            capability_name: Name of the capability
            environment: Environment (dev, stage, prod)
            
        Returns:
            ExportResult with export status and file path
        """
        export_timestamp = datetime.utcnow()
        
        try:
            # List all users
            users = self.list_users(user_pool_id, region)
            
            # Generate export file path
            export_path = self._generate_export_path(
                capability_name=capability_name,
                environment=environment,
                timestamp=export_timestamp
            )
            
            # Ensure export directory exists
            export_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert users to serializable format
            users_data = [
                {
                    'username': u.username,
                    'email': u.email,
                    'attributes': u.attributes,
                    'groups': u.groups,
                    'enabled': u.enabled,
                    'status': u.status,
                    'created_at': u.created_at.isoformat() if u.created_at else None
                }
                for u in users
            ]
            
            # Write export file
            export_data = {
                'export_timestamp': export_timestamp.isoformat(),
                'user_pool_id': user_pool_id,
                'region': region,
                'capability_name': capability_name,
                'environment': environment,
                'user_count': len(users),
                'users': users_data
            }
            
            with open(export_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(
                f"[EXPORT] Successfully exported {len(users)} users to {export_path}"
            )
            
            return ExportResult(
                success=True,
                export_path=str(export_path),
                user_count=len(users),
                export_timestamp=export_timestamp,
                capability_name=capability_name,
                environment=environment
            )
            
        except ClientError as e:
            error_message = f"AWS error during export: {str(e)}"
            logger.error(f"[EXPORT] {error_message}")
            
            return ExportResult(
                success=False,
                user_count=0,
                export_timestamp=export_timestamp,
                capability_name=capability_name,
                environment=environment,
                error_message=error_message
            )
            
        except Exception as e:
            error_message = f"Unexpected error during export: {str(e)}"
            logger.error(f"[EXPORT] {error_message}")
            
            return ExportResult(
                success=False,
                user_count=0,
                export_timestamp=export_timestamp,
                capability_name=capability_name,
                environment=environment,
                error_message=error_message
            )

    def _generate_export_path(
        self,
        capability_name: str,
        environment: str,
        timestamp: datetime
    ) -> Path:
        """
        Generate the export file path with timestamp and capability identifiers.
        
        Format: exports/cognito/{capability}-{env}-{timestamp}.json
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            timestamp: Export timestamp
            
        Returns:
            Path to the export file
        """
        # Sanitize capability name for filename
        safe_name = capability_name.replace(' ', '-').replace('_', '-').lower()
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')
        
        # Format timestamp
        timestamp_str = timestamp.strftime('%Y%m%d-%H%M%S')
        
        filename = f"{safe_name}-{environment}-{timestamp_str}.json"
        
        return self.export_dir / filename

    def get_export_file_info(self, export_path: str) -> Optional[Dict[str, Any]]:
        """
        Read and return metadata from an export file.
        
        Args:
            export_path: Path to the export file
            
        Returns:
            Dict with export metadata or None if file doesn't exist
        """
        try:
            path = Path(export_path)
            if not path.exists():
                return None
            
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return {
                'export_timestamp': data.get('export_timestamp'),
                'user_pool_id': data.get('user_pool_id'),
                'region': data.get('region'),
                'capability_name': data.get('capability_name'),
                'environment': data.get('environment'),
                'user_count': data.get('user_count', 0)
            }
            
        except Exception as e:
            logger.error(f"[EXPORT] Error reading export file {export_path}: {e}")
            return None


def get_cognito_user_export_service(
    credentials: Optional[Dict[str, str]] = None,
    export_dir: Optional[Path] = None
) -> CognitoUserExportService:
    """
    Factory function to create a CognitoUserExportService instance.
    
    Args:
        credentials: Optional AWS credentials
        export_dir: Optional export directory
        
    Returns:
        Configured CognitoUserExportService instance
    """
    return CognitoUserExportService(
        credentials=credentials,
        export_dir=export_dir
    )
