"""
Property-based tests for CognitoUserExportService.

Property 5: User Data Export Completeness
- Export SHALL include all users from the Cognito User Pool with their attributes
- Export file SHALL be stored with timestamp and capability identifiers
- Export result SHALL report the correct user count

Validates: Requirements 4.2, 4.3, 4.4
"""
import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

from app.models.cognito_models import UserExportRecord, ExportResult
from app.services.cognito_user_export_service import CognitoUserExportService


# Strategies for generating test data
username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-_'),
    min_size=3,
    max_size=50
).filter(lambda x: len(x.strip()) >= 3)

email_strategy = st.emails()

attribute_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=20, alphabet='abcdefghijklmnopqrstuvwxyz_'),
    values=st.text(min_size=0, max_size=100),
    max_size=10
)

group_strategy = st.lists(
    st.text(min_size=1, max_size=30, alphabet='abcdefghijklmnopqrstuvwxyz-'),
    max_size=5,
    unique=True
)

capability_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-_'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)

environment_strategy = st.sampled_from(['dev', 'stage', 'prod', 'test'])

region_strategy = st.sampled_from([
    'us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1', 'ap-northeast-1'
])


def generate_mock_cognito_user(username: str, email: str, attributes: dict, groups: list):
    """Generate a mock Cognito user response."""
    attrs = [{'Name': 'email', 'Value': email}]
    for key, value in attributes.items():
        attrs.append({'Name': key, 'Value': value})
    
    return {
        'Username': username,
        'Attributes': attrs,
        'Enabled': True,
        'UserStatus': 'CONFIRMED',
        'UserCreateDate': datetime.utcnow()
    }


class TestUserDataExportCompleteness:
    """
    Property 5: User Data Export Completeness
    
    Tests that user export includes all users with attributes and
    export files are properly named with timestamps and capability identifiers.
    """

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy
    )
    @settings(max_examples=10)
    def test_export_path_includes_capability_and_timestamp(
        self,
        capability_name: str,
        environment: str
    ):
        """
        Property: Export file path SHALL include capability name and timestamp.
        
        Validates: Requirement 4.4
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CognitoUserExportService(export_dir=Path(tmpdir))
            timestamp = datetime.utcnow()
            
            export_path = service._generate_export_path(
                capability_name=capability_name,
                environment=environment,
                timestamp=timestamp
            )
            
            # Path should be under export directory
            assert str(export_path).startswith(tmpdir)
            
            # Filename should contain environment
            filename = export_path.name
            assert environment in filename
            
            # Filename should contain timestamp in expected format
            timestamp_str = timestamp.strftime('%Y%m%d-%H%M%S')
            assert timestamp_str in filename
            
            # Filename should end with .json
            assert filename.endswith('.json')

    @given(
        users_data=st.lists(
            st.tuples(username_strategy, email_strategy, attribute_strategy, group_strategy),
            min_size=0,
            max_size=20
        ),
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy
    )
    @settings(max_examples=10)
    def test_export_includes_all_users(
        self,
        users_data: list,
        capability_name: str,
        environment: str,
        region: str
    ):
        """
        Property: Export SHALL include all users from the User Pool.
        
        Validates: Requirement 4.2
        """
        # Make usernames unique
        unique_users = {}
        for username, email, attrs, groups in users_data:
            if username not in unique_users:
                unique_users[username] = (username, email, attrs, groups)
        
        users_list = list(unique_users.values())
        
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CognitoUserExportService(export_dir=Path(tmpdir))
            
            # Create mock users
            mock_cognito_users = [
                generate_mock_cognito_user(u, e, a, g)
                for u, e, a, g in users_list
            ]
            
            # Mock the Cognito client
            mock_client = MagicMock()
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [{'Users': mock_cognito_users}]
            mock_client.get_paginator.return_value = mock_paginator
            mock_client.admin_list_groups_for_user.return_value = {'Groups': []}
            
            with patch.object(service, '_get_client', return_value=mock_client):
                result = service.export_users(
                    user_pool_id='test-pool-id',
                    region=region,
                    capability_name=capability_name,
                    environment=environment
                )
            
            # Verify result
            assert result.success is True
            assert result.user_count == len(users_list)
            
            # Verify export file exists and contains all users
            if result.export_path:
                export_path = Path(result.export_path)
                assert export_path.exists()
                
                with open(export_path, 'r', encoding='utf-8') as f:
                    export_data = json.load(f)
                
                assert export_data['user_count'] == len(users_list)
                assert len(export_data['users']) == len(users_list)

    @given(
        username=username_strategy,
        email=email_strategy,
        attributes=attribute_strategy
    )
    @settings(max_examples=10)
    def test_export_preserves_user_attributes(
        self,
        username: str,
        email: str,
        attributes: dict
    ):
        """
        Property: Export SHALL preserve all user attributes.
        
        Validates: Requirement 4.3
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CognitoUserExportService(export_dir=Path(tmpdir))
            
            # Create mock user with attributes
            mock_user = generate_mock_cognito_user(username, email, attributes, [])
            
            # Mock the Cognito client
            mock_client = MagicMock()
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [{'Users': [mock_user]}]
            mock_client.get_paginator.return_value = mock_paginator
            mock_client.admin_list_groups_for_user.return_value = {'Groups': []}
            
            with patch.object(service, '_get_client', return_value=mock_client):
                result = service.export_users(
                    user_pool_id='test-pool-id',
                    region='us-east-1',
                    capability_name='test-cap',
                    environment='dev'
                )
            
            assert result.success is True
            
            # Read export file and verify attributes
            if result.export_path:
                with open(result.export_path, 'r', encoding='utf-8') as f:
                    export_data = json.load(f)
                
                exported_user = export_data['users'][0]
                assert exported_user['username'] == username
                assert exported_user['email'] == email
                
                # Verify all custom attributes are preserved
                for key, value in attributes.items():
                    assert key in exported_user['attributes']
                    assert exported_user['attributes'][key] == value

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy
    )
    @settings(max_examples=10)
    def test_export_result_contains_metadata(
        self,
        capability_name: str,
        environment: str,
        region: str
    ):
        """
        Property: ExportResult SHALL contain capability name, environment, and timestamp.
        
        Validates: Requirement 4.4
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CognitoUserExportService(export_dir=Path(tmpdir))
            
            # Mock empty user pool
            mock_client = MagicMock()
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [{'Users': []}]
            mock_client.get_paginator.return_value = mock_paginator
            
            with patch.object(service, '_get_client', return_value=mock_client):
                result = service.export_users(
                    user_pool_id='test-pool-id',
                    region=region,
                    capability_name=capability_name,
                    environment=environment
                )
            
            # Verify metadata in result
            assert result.capability_name == capability_name
            assert result.environment == environment
            assert result.export_timestamp is not None
            assert isinstance(result.export_timestamp, datetime)


class TestExportResultCorrectness:
    """
    Tests for ExportResult correctness properties.
    """

    @given(user_count=st.integers(min_value=0, max_value=1000))
    @settings(max_examples=10)
    def test_export_result_user_count_matches_actual(self, user_count: int):
        """
        Property: ExportResult.user_count SHALL match the actual number of exported users.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CognitoUserExportService(export_dir=Path(tmpdir))
            
            # Generate mock users
            mock_users = [
                generate_mock_cognito_user(f'user{i}', f'user{i}@test.com', {}, [])
                for i in range(user_count)
            ]
            
            mock_client = MagicMock()
            mock_paginator = MagicMock()
            mock_paginator.paginate.return_value = [{'Users': mock_users}]
            mock_client.get_paginator.return_value = mock_paginator
            mock_client.admin_list_groups_for_user.return_value = {'Groups': []}
            
            with patch.object(service, '_get_client', return_value=mock_client):
                result = service.export_users(
                    user_pool_id='test-pool-id',
                    region='us-east-1',
                    capability_name='test',
                    environment='dev'
                )
            
            assert result.user_count == user_count

    def test_export_failure_returns_error_message(self):
        """
        Property: Failed export SHALL return error_message in ExportResult.
        
        Validates: Requirement 4.5
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            service = CognitoUserExportService(export_dir=Path(tmpdir))
            
            # Mock client that raises an error
            mock_client = MagicMock()
            mock_client.get_paginator.side_effect = Exception("Access denied")
            
            with patch.object(service, '_get_client', return_value=mock_client):
                result = service.export_users(
                    user_pool_id='test-pool-id',
                    region='us-east-1',
                    capability_name='test',
                    environment='dev'
                )
            
            assert result.success is False
            assert result.error_message is not None
            assert len(result.error_message) > 0


class TestUserExportRecordModel:
    """Tests for UserExportRecord data model."""

    @given(
        username=username_strategy,
        email=email_strategy,
        attributes=attribute_strategy,
        groups=group_strategy,
        enabled=st.booleans(),
        status=st.sampled_from(['CONFIRMED', 'UNCONFIRMED', 'FORCE_CHANGE_PASSWORD', 'RESET_REQUIRED'])
    )
    @settings(max_examples=10)
    def test_user_export_record_preserves_all_fields(
        self,
        username: str,
        email: str,
        attributes: dict,
        groups: list,
        enabled: bool,
        status: str
    ):
        """
        Property: UserExportRecord SHALL preserve all input fields correctly.
        """
        record = UserExportRecord(
            username=username,
            email=email,
            attributes=attributes,
            groups=groups,
            enabled=enabled,
            status=status
        )
        
        assert record.username == username
        assert record.email == email
        assert record.attributes == attributes
        assert record.groups == groups
        assert record.enabled == enabled
        assert record.status == status


class TestExportResultModel:
    """Tests for ExportResult data model."""

    @given(
        success=st.booleans(),
        user_count=st.integers(min_value=0, max_value=1000000),
        capability_name=capability_name_strategy,
        environment=environment_strategy
    )
    @settings(max_examples=10)
    def test_export_result_preserves_all_fields(
        self,
        success: bool,
        user_count: int,
        capability_name: str,
        environment: str
    ):
        """
        Property: ExportResult SHALL preserve all input fields correctly.
        """
        timestamp = datetime.utcnow()
        
        result = ExportResult(
            success=success,
            user_count=user_count,
            export_timestamp=timestamp,
            capability_name=capability_name,
            environment=environment
        )
        
        assert result.success == success
        assert result.user_count == user_count
        assert result.export_timestamp == timestamp
        assert result.capability_name == capability_name
        assert result.environment == environment
