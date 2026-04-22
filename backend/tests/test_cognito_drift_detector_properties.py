"""
Property-based tests for CognitoDriftDetector.

Property 7: Drift Detection Coverage
- System SHALL compare password policy, MFA configuration, app client settings, and custom attributes
- Drift detection failures SHALL NOT block the workflow

Validates: Requirements 5.1, 5.2, 5.3, 5.5
"""
import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

from app.models.cognito_models import DriftItem, DriftDetectionResult
from app.services.cognito_drift_detector import CognitoDriftDetector


# Strategies for generating test data
password_length_strategy = st.integers(min_value=6, max_value=99)
boolean_strategy = st.booleans()
mfa_config_strategy = st.sampled_from(['OFF', 'ON', 'OPTIONAL'])
temp_password_days_strategy = st.integers(min_value=1, max_value=365)

region_strategy = st.sampled_from([
    'us-east-1', 'us-west-2', 'eu-west-1', 'us-east-1'
])

oauth_flows_strategy = st.lists(
    st.sampled_from(['code', 'implicit', 'client_credentials']),
    max_size=3,
    unique=True
)

oauth_scopes_strategy = st.lists(
    st.sampled_from(['openid', 'email', 'profile', 'phone', 'aws.cognito.signin.user.admin']),
    max_size=5,
    unique=True
)

auth_flows_strategy = st.lists(
    st.sampled_from([
        'ALLOW_USER_PASSWORD_AUTH',
        'ALLOW_ADMIN_USER_PASSWORD_AUTH',
        'ALLOW_USER_SRP_AUTH',
        'ALLOW_REFRESH_TOKEN_AUTH'
    ]),
    max_size=4,
    unique=True
)


def create_mock_user_pool_response(
    min_length: int = 8,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_numbers: bool = True,
    require_symbols: bool = True,
    temp_password_days: int = 7,
    mfa_config: str = 'OFF',
    custom_attributes: list = None,
    software_token_enabled: bool = None
):
    """Create a mock Cognito describe_user_pool response."""
    # If software_token_enabled is not explicitly set, derive from mfa_config
    if software_token_enabled is None:
        software_token_enabled = mfa_config != 'OFF'
    
    return {
        'UserPool': {
            'Policies': {
                'PasswordPolicy': {
                    'MinimumLength': min_length,
                    'RequireUppercase': require_uppercase,
                    'RequireLowercase': require_lowercase,
                    'RequireNumbers': require_numbers,
                    'RequireSymbols': require_symbols,
                    'TemporaryPasswordValidityDays': temp_password_days
                }
            },
            'MfaConfiguration': mfa_config,
            'SmsAuthenticationMessage': '',
            'EnabledMfas': ['SOFTWARE_TOKEN_MFA'] if software_token_enabled else [],
            'SchemaAttributes': custom_attributes or []
        }
    }


def create_mock_app_client_response(
    explicit_auth_flows: list = None,
    oauth_flows: list = None,
    oauth_scopes: list = None,
    oauth_enabled: bool = True
):
    """Create a mock Cognito describe_user_pool_client response."""
    return {
        'UserPoolClient': {
            'ExplicitAuthFlows': explicit_auth_flows or [],
            'AllowedOAuthFlows': oauth_flows or [],
            'AllowedOAuthScopes': oauth_scopes or [],
            'AllowedOAuthFlowsUserPoolClient': oauth_enabled,
            'PreventUserExistenceErrors': 'ENABLED',
            'EnableTokenRevocation': True
        }
    }


def create_template_file(
    tmpdir: str,
    min_length: int = 8,
    require_uppercase: bool = True,
    require_lowercase: bool = True,
    require_numbers: bool = True,
    require_symbols: bool = True,
    temp_password_days: int = 7,
    mfa_config: str = 'OFF',
    explicit_auth_flows: list = None,
    oauth_flows: list = None,
    oauth_scopes: list = None,
    oauth_enabled: bool = True
) -> Path:
    """Create a CloudFormation template file for testing."""
    template = {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Resources': {
            'UserPool': {
                'Type': 'AWS::Cognito::UserPool',
                'Properties': {
                    'Policies': {
                        'PasswordPolicy': {
                            'MinimumLength': min_length,
                            'RequireUppercase': require_uppercase,
                            'RequireLowercase': require_lowercase,
                            'RequireNumbers': require_numbers,
                            'RequireSymbols': require_symbols,
                            'TemporaryPasswordValidityDays': temp_password_days
                        }
                    },
                    'MfaConfiguration': mfa_config
                }
            },
            'UserPoolClient': {
                'Type': 'AWS::Cognito::UserPoolClient',
                'Properties': {
                    'ExplicitAuthFlows': explicit_auth_flows or [],
                    'AllowedOAuthFlows': oauth_flows or [],
                    'AllowedOAuthScopes': oauth_scopes or [],
                    'AllowedOAuthFlowsUserPoolClient': oauth_enabled,
                    'PreventUserExistenceErrors': 'ENABLED',
                    'EnableTokenRevocation': True
                }
            }
        }
    }
    
    template_path = Path(tmpdir) / 'template.yaml'
    with open(template_path, 'w') as f:
        import yaml
        yaml.dump(template, f)
    
    return template_path


class TestDriftDetectionCoverage:
    """
    Property 7: Drift Detection Coverage
    
    Tests that drift detection covers all required categories and
    handles failures gracefully.
    """

    @given(
        min_length=password_length_strategy,
        require_uppercase=boolean_strategy,
        require_lowercase=boolean_strategy,
        require_numbers=boolean_strategy,
        require_symbols=boolean_strategy
    )
    @settings(max_examples=10)
    def test_password_policy_drift_detected(
        self,
        min_length: int,
        require_uppercase: bool,
        require_lowercase: bool,
        require_numbers: bool,
        require_symbols: bool
    ):
        """
        Property: Password policy differences SHALL be detected as drift.
        
        Validates: Requirement 5.1
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = CognitoDriftDetector()
            
            # Create template with different values
            template_path = create_template_file(
                tmpdir,
                min_length=min_length,
                require_uppercase=require_uppercase,
                require_lowercase=require_lowercase,
                require_numbers=require_numbers,
                require_symbols=require_symbols
            )
            
            # Mock deployed config with opposite values
            mock_response = create_mock_user_pool_response(
                min_length=min_length + 1,  # Different
                require_uppercase=not require_uppercase,  # Different
                require_lowercase=require_lowercase,  # Same
                require_numbers=require_numbers,  # Same
                require_symbols=require_symbols  # Same
            )
            
            mock_client = MagicMock()
            mock_client.describe_user_pool.return_value = mock_response
            mock_client.list_user_pool_clients.return_value = {'UserPoolClients': []}
            
            with patch.object(detector, '_get_client', return_value=mock_client):
                result = detector.detect_drift(
                    user_pool_id='test-pool',
                    region='us-east-1',
                    template_path=template_path
                )
            
            # Should detect drift for MinimumLength and RequireUppercase
            assert result.has_drift is True
            
            password_drift = [
                item for item in result.drift_items
                if item.category == 'password_policy'
            ]
            assert len(password_drift) >= 2

    @given(mfa_config=mfa_config_strategy)
    @settings(max_examples=10)
    def test_mfa_configuration_drift_detected(self, mfa_config: str):
        """
        Property: MFA configuration differences SHALL be detected as drift.
        
        Validates: Requirement 5.1
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = CognitoDriftDetector()
            
            # Template has different MFA config
            different_mfa = 'ON' if mfa_config == 'OFF' else 'OFF'
            template_path = create_template_file(tmpdir, mfa_config=different_mfa)
            
            mock_response = create_mock_user_pool_response(mfa_config=mfa_config)
            
            mock_client = MagicMock()
            mock_client.describe_user_pool.return_value = mock_response
            mock_client.list_user_pool_clients.return_value = {'UserPoolClients': []}
            
            with patch.object(detector, '_get_client', return_value=mock_client):
                result = detector.detect_drift(
                    user_pool_id='test-pool',
                    region='us-east-1',
                    template_path=template_path
                )
            
            # Should detect MFA drift
            mfa_drift = [
                item for item in result.drift_items
                if item.category == 'mfa'
            ]
            assert len(mfa_drift) >= 1

    @given(
        deployed_flows=auth_flows_strategy,
        template_flows=auth_flows_strategy
    )
    @settings(max_examples=10)
    def test_app_client_drift_detected(
        self,
        deployed_flows: list,
        template_flows: list
    ):
        """
        Property: App client setting differences SHALL be detected as drift.
        
        Validates: Requirement 5.1
        """
        # Only test when flows are different
        assume(sorted(deployed_flows) != sorted(template_flows))
        
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = CognitoDriftDetector()
            
            template_path = create_template_file(
                tmpdir,
                explicit_auth_flows=template_flows
            )
            
            mock_pool_response = create_mock_user_pool_response()
            mock_client_response = create_mock_app_client_response(
                explicit_auth_flows=deployed_flows
            )
            
            mock_client = MagicMock()
            mock_client.describe_user_pool.return_value = mock_pool_response
            mock_client.list_user_pool_clients.return_value = {
                'UserPoolClients': [{'ClientId': 'test-client'}]
            }
            mock_client.describe_user_pool_client.return_value = mock_client_response
            
            with patch.object(detector, '_get_client', return_value=mock_client):
                result = detector.detect_drift(
                    user_pool_id='test-pool',
                    region='us-east-1',
                    template_path=template_path
                )
            
            # Should detect app client drift
            app_client_drift = [
                item for item in result.drift_items
                if item.category == 'app_client'
            ]
            assert len(app_client_drift) >= 1

    def test_drift_detection_failure_does_not_block(self):
        """
        Property: Drift detection failures SHALL NOT block the workflow.
        
        Validates: Requirement 5.5
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = CognitoDriftDetector()
            
            template_path = create_template_file(tmpdir)
            
            # Mock client that raises an error
            mock_client = MagicMock()
            mock_client.describe_user_pool.side_effect = Exception("Access denied")
            
            with patch.object(detector, '_get_client', return_value=mock_client):
                result = detector.detect_drift(
                    user_pool_id='test-pool',
                    region='us-east-1',
                    template_path=template_path
                )
            
            # Should return a result (not raise exception)
            assert isinstance(result, DriftDetectionResult)
            assert result.error_message is not None
            # has_drift should be False when detection fails
            assert result.has_drift is False

    def test_all_categories_are_checked(self):
        """
        Property: All drift categories SHALL be checked.
        
        Validates: Requirement 5.2
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = CognitoDriftDetector()
            
            template_path = create_template_file(tmpdir)
            
            mock_pool_response = create_mock_user_pool_response()
            mock_client_response = create_mock_app_client_response()
            
            mock_client = MagicMock()
            mock_client.describe_user_pool.return_value = mock_pool_response
            mock_client.list_user_pool_clients.return_value = {
                'UserPoolClients': [{'ClientId': 'test-client'}]
            }
            mock_client.describe_user_pool_client.return_value = mock_client_response
            
            with patch.object(detector, '_get_client', return_value=mock_client):
                result = detector.detect_drift(
                    user_pool_id='test-pool',
                    region='us-east-1',
                    template_path=template_path
                )
            
            # All categories should be in categories_checked
            expected_categories = ['password_policy', 'mfa', 'app_client', 'custom_attributes']
            for category in expected_categories:
                assert category in result.categories_checked


class TestDriftDetectionResultModel:
    """Tests for DriftDetectionResult data model."""

    @given(
        has_drift=boolean_strategy,
        num_items=st.integers(min_value=0, max_value=20)
    )
    @settings(max_examples=10)
    def test_drift_detection_result_preserves_fields(
        self,
        has_drift: bool,
        num_items: int
    ):
        """
        Property: DriftDetectionResult SHALL preserve all input fields correctly.
        """
        drift_items = [
            DriftItem(
                setting_name=f'setting_{i}',
                template_value=f'template_{i}',
                deployed_value=f'deployed_{i}',
                category='password_policy'
            )
            for i in range(num_items)
        ]
        
        timestamp = datetime.utcnow()
        
        result = DriftDetectionResult(
            has_drift=has_drift,
            drift_items=drift_items,
            detection_timestamp=timestamp
        )
        
        assert result.has_drift == has_drift
        assert len(result.drift_items) == num_items
        assert result.detection_timestamp == timestamp


class TestDriftItemModel:
    """Tests for DriftItem data model."""

    @given(
        setting_name=st.text(min_size=1, max_size=50),
        template_value=st.text(min_size=0, max_size=100),
        deployed_value=st.text(min_size=0, max_size=100),
        category=st.sampled_from(['password_policy', 'mfa', 'app_client', 'custom_attributes'])
    )
    @settings(max_examples=10)
    def test_drift_item_preserves_fields(
        self,
        setting_name: str,
        template_value: str,
        deployed_value: str,
        category: str
    ):
        """
        Property: DriftItem SHALL preserve all input fields correctly.
        """
        item = DriftItem(
            setting_name=setting_name,
            template_value=template_value,
            deployed_value=deployed_value,
            category=category
        )
        
        assert item.setting_name == setting_name
        assert item.template_value == template_value
        assert item.deployed_value == deployed_value
        assert item.category == category


class TestNoDriftScenarios:
    """Tests for scenarios where no drift should be detected."""

    @given(
        min_length=password_length_strategy,
        require_uppercase=boolean_strategy,
        require_lowercase=boolean_strategy,
        require_numbers=boolean_strategy,
        require_symbols=boolean_strategy,
        mfa_config=mfa_config_strategy
    )
    @settings(max_examples=10)
    def test_identical_config_no_drift(
        self,
        min_length: int,
        require_uppercase: bool,
        require_lowercase: bool,
        require_numbers: bool,
        require_symbols: bool,
        mfa_config: str
    ):
        """
        Property: Identical configurations SHALL NOT produce drift items.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            detector = CognitoDriftDetector()
            
            # Create template and deployed with same values
            template_path = create_template_file(
                tmpdir,
                min_length=min_length,
                require_uppercase=require_uppercase,
                require_lowercase=require_lowercase,
                require_numbers=require_numbers,
                require_symbols=require_symbols,
                mfa_config=mfa_config
            )
            
            # The template doesn't have EnabledMfas, so SoftwareTokenMfaEnabled
            # will be False in template config. We need to match that in mock.
            mock_response = create_mock_user_pool_response(
                min_length=min_length,
                require_uppercase=require_uppercase,
                require_lowercase=require_lowercase,
                require_numbers=require_numbers,
                require_symbols=require_symbols,
                mfa_config=mfa_config,
                software_token_enabled=False  # Match template which has no EnabledMfas
            )
            
            mock_client = MagicMock()
            mock_client.describe_user_pool.return_value = mock_response
            mock_client.list_user_pool_clients.return_value = {'UserPoolClients': []}
            
            with patch.object(detector, '_get_client', return_value=mock_client):
                result = detector.detect_drift(
                    user_pool_id='test-pool',
                    region='us-east-1',
                    template_path=template_path
                )
            
            # No drift for password policy and MFA
            password_mfa_drift = [
                item for item in result.drift_items
                if item.category in ['password_policy', 'mfa']
            ]
            assert len(password_mfa_drift) == 0
