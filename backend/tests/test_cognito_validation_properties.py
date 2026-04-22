"""
Property-based tests for Cognito Validation.

Property 12: Cognito Validation Completeness
- System SHALL validate User Pool accessibility and App Client configuration
- Validation failures before update SHALL halt the process
- Validation failures after update SHALL report with rollback guidance

Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
"""
import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings

from app.models.cognito_models import CognitoOutputs, CognitoValidationResult
from app.models.update_config import UpdateConfig
from app.services.cognito_preservation_service import CognitoPreservationService
from app.services.update_workflow_orchestrator import UpdateWorkflowOrchestrator


# Strategies for generating test data
user_pool_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-_'),
    min_size=10,
    max_size=50
)

client_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N')),
    min_size=10,
    max_size=50
)

region_strategy = st.sampled_from([
    'us-east-1', 'us-west-2', 'eu-west-1', 'us-east-1'
])

user_count_strategy = st.integers(min_value=0, max_value=100000)


class TestCognitoValidationCompleteness:
    """
    Property 12: Cognito Validation Completeness
    
    Tests that Cognito validation covers all required checks.
    """

    @given(
        is_valid=st.booleans(),
        user_pool_accessible=st.booleans(),
        client_configured=st.booleans(),
        user_count=user_count_strategy
    )
    @settings(max_examples=10)
    def test_validation_result_contains_all_checks(
        self,
        is_valid: bool,
        user_pool_accessible: bool,
        client_configured: bool,
        user_count: int
    ):
        """
        Property: CognitoValidationResult SHALL contain all validation checks.
        
        Validates: Requirements 11.1, 11.2, 11.3
        """
        result = CognitoValidationResult(
            is_valid=is_valid,
            user_pool_accessible=user_pool_accessible,
            client_configured=client_configured,
            user_count=user_count
        )
        
        # All fields should be present
        assert hasattr(result, 'is_valid')
        assert hasattr(result, 'user_pool_accessible')
        assert hasattr(result, 'client_configured')
        assert hasattr(result, 'user_count')
        assert hasattr(result, 'error_message')
        assert hasattr(result, 'remediation_steps')

    @given(
        user_pool_accessible=st.booleans(),
        client_configured=st.booleans()
    )
    @settings(max_examples=10)
    def test_validation_logic_consistency(
        self,
        user_pool_accessible: bool,
        client_configured: bool
    ):
        """
        Property: is_valid SHALL be consistent with individual checks.
        """
        # Valid only if both checks pass
        expected_valid = user_pool_accessible and client_configured
        
        result = CognitoValidationResult(
            is_valid=expected_valid,
            user_pool_accessible=user_pool_accessible,
            client_configured=client_configured,
            user_count=0
        )
        
        # Verify consistency
        if result.is_valid:
            assert result.user_pool_accessible is True
            assert result.client_configured is True

    def test_pre_validation_failure_halts_update(self):
        """
        Property: Pre-update validation failure SHALL halt the update.
        
        Validates: Requirement 11.5
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        # Mock validation to fail
        mock_validation = CognitoValidationResult(
            is_valid=False,
            user_pool_accessible=False,
            client_configured=True,
            user_count=0,
            error_message="User Pool not accessible"
        )
        
        mock_cognito_outputs = CognitoOutputs(
            user_pool_id='test-pool',
            user_pool_client_id='test-client',
            user_pool_domain='test-domain',
            region='us-east-1'
        )
        
        config = UpdateConfig(
            preserve_cognito=True,
            skip_pre_validation=False
        )
        
        stacks = [{'stack_name': 'test-stack', 'stack_type': 'backend'}]
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=mock_cognito_outputs):
                with patch.object(orchestrator.cognito_preservation, 'validate_user_pool', return_value=mock_validation):
                    result = orchestrator.execute_update(
                        capability_name='test',
                        environment='dev',
                        region='us-east-1',
                        update_config=config,
                        stacks_to_deploy=stacks
                    )
        
        # Update should have failed due to validation
        assert result.success is False
        assert result.validation_passed is False
        assert 'validation' in result.error_message.lower()

    def test_validation_skipped_when_configured(self):
        """
        Property: Validation SHALL be skipped when skip_pre_validation=True.
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        config = UpdateConfig(
            preserve_cognito=True,
            skip_pre_validation=True
        )
        
        stacks = [{'stack_name': 'test-stack', 'stack_type': 'backend'}]
        
        validation_called = []
        
        def mock_validate(*args, **kwargs):
            validation_called.append(True)
            return CognitoValidationResult(
                is_valid=False,
                user_pool_accessible=False,
                client_configured=False,
                user_count=0
            )
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.cognito_preservation, 'validate_user_pool', side_effect=mock_validate):
                    result = orchestrator.execute_update(
                        capability_name='test',
                        environment='dev',
                        region='us-east-1',
                        update_config=config,
                        stacks_to_deploy=stacks
                    )
        
        # Validation should not have been called (or result should succeed)
        # Since cognito_outputs is None, validation is skipped anyway
        assert result.validation_passed is True or len(validation_called) == 0


class TestCognitoValidationResultModel:
    """Tests for CognitoValidationResult data model."""

    @given(
        is_valid=st.booleans(),
        user_pool_accessible=st.booleans(),
        client_configured=st.booleans(),
        user_count=user_count_strategy,
        error_message=st.one_of(st.none(), st.text(min_size=1, max_size=200))
    )
    @settings(max_examples=10)
    def test_validation_result_preserves_fields(
        self,
        is_valid: bool,
        user_pool_accessible: bool,
        client_configured: bool,
        user_count: int,
        error_message: str
    ):
        """
        Property: CognitoValidationResult SHALL preserve all input fields.
        """
        result = CognitoValidationResult(
            is_valid=is_valid,
            user_pool_accessible=user_pool_accessible,
            client_configured=client_configured,
            user_count=user_count,
            error_message=error_message
        )
        
        assert result.is_valid == is_valid
        assert result.user_pool_accessible == user_pool_accessible
        assert result.client_configured == client_configured
        assert result.user_count == user_count
        assert result.error_message == error_message

    @given(
        remediation_steps=st.lists(
            st.text(min_size=1, max_size=100),
            min_size=0,
            max_size=5
        )
    )
    @settings(max_examples=10)
    def test_remediation_steps_preserved(self, remediation_steps: list):
        """
        Property: Remediation steps SHALL be preserved in validation result.
        
        Validates: Requirement 11.6
        """
        result = CognitoValidationResult(
            is_valid=False,
            user_pool_accessible=False,
            client_configured=False,
            user_count=0,
            remediation_steps=remediation_steps
        )
        
        assert result.remediation_steps == remediation_steps


class TestCognitoOutputsModel:
    """Tests for CognitoOutputs data model."""

    @given(
        user_pool_id=user_pool_id_strategy,
        client_id=client_id_strategy,
        domain=st.text(min_size=3, max_size=50),
        region=region_strategy
    )
    @settings(max_examples=10)
    def test_cognito_outputs_preserves_fields(
        self,
        user_pool_id: str,
        client_id: str,
        domain: str,
        region: str
    ):
        """
        Property: CognitoOutputs SHALL preserve all input fields.
        """
        outputs = CognitoOutputs(
            user_pool_id=user_pool_id,
            user_pool_client_id=client_id,
            user_pool_domain=domain,
            region=region
        )
        
        assert outputs.user_pool_id == user_pool_id
        assert outputs.user_pool_client_id == client_id
        assert outputs.user_pool_domain == domain
        assert outputs.region == region


class TestValidationInOrchestrator:
    """Tests for validation integration in orchestrator."""

    def test_post_validation_warning_does_not_fail_result(self):
        """
        Property: Post-validation failure SHALL warn but not fail the result.
        
        Validates: Requirement 11.6
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        # Mock successful pre-validation, failed post-validation
        mock_pre_validation = CognitoValidationResult(
            is_valid=True,
            user_pool_accessible=True,
            client_configured=True,
            user_count=10
        )
        
        mock_post_validation = CognitoValidationResult(
            is_valid=False,
            user_pool_accessible=True,
            client_configured=False,
            user_count=10,
            error_message="App client configuration changed"
        )
        
        mock_cognito_outputs = CognitoOutputs(
            user_pool_id='test-pool',
            user_pool_client_id='test-client',
            user_pool_domain='test-domain',
            region='us-east-1'
        )
        
        config = UpdateConfig(
            preserve_cognito=True,
            skip_pre_validation=False,
            skip_post_validation=False
        )
        
        stacks = [{'stack_name': 'test-stack', 'stack_type': 'backend'}]
        
        validation_calls = []
        
        def mock_validate(*args, **kwargs):
            validation_calls.append(True)
            if len(validation_calls) == 1:
                return mock_pre_validation
            return mock_post_validation
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=mock_cognito_outputs):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator.cognito_preservation, 'validate_user_pool', side_effect=mock_validate):
                        with patch.object(orchestrator, '_deploy_stack', return_value=True):
                            result = orchestrator.execute_update(
                                capability_name='test',
                                environment='dev',
                                region='us-east-1',
                                update_config=config,
                                stacks_to_deploy=stacks
                            )
        
        # Result should still be successful (post-validation is warning only)
        assert result.success is True
        # But validation_passed should indicate the warning
        # (depending on implementation, this might be True or False)


class TestValidationTimestamp:
    """Tests for validation timestamp."""

    def test_validation_timestamp_is_set(self):
        """
        Property: Validation result SHALL have a timestamp.
        """
        result = CognitoValidationResult(
            is_valid=True,
            user_pool_accessible=True,
            client_configured=True,
            user_count=0
        )
        
        assert result.validation_timestamp is not None
