"""
Property-based tests for CognitoPreservationService.

Property 2: Cognito Stack Skip During Update
- UPDATE workflow with include_cognito_update=False → Cognito is preserved (skipped)
- UPDATE workflow with include_cognito_update=True → Cognito is updated
- INSTALL workflow → Cognito is never preserved

Validates: Requirements 2.1, 2.5, 2.6
"""
import pytest
from hypothesis import given, strategies as st, settings

from app.models.workflow_classification import WorkflowType
from app.services.cognito_preservation_service import CognitoPreservationService


class TestCognitoStackSkipDuringUpdate:
    """
    Property 2: Cognito Stack Skip During Update
    
    Tests that Cognito stack is correctly skipped or included based on
    workflow type and user preference.
    """

    @given(include_cognito_update=st.booleans())
    @settings(max_examples=10)
    def test_install_workflow_never_preserves_cognito(
        self,
        include_cognito_update: bool
    ):
        """
        Property: For any INSTALL workflow, regardless of include_cognito_update,
        Cognito SHALL NOT be preserved (will be created fresh).
        
        Validates: Requirement 2.1 (inverse - install creates new)
        """
        service = CognitoPreservationService()
        
        should_preserve = service.should_preserve_cognito(
            workflow_type=WorkflowType.INSTALL,
            include_cognito_update=include_cognito_update
        )
        
        assert should_preserve is False
        
        # Verify stacks_to_skip is empty for install
        stacks_to_skip = service.get_stacks_to_skip(
            workflow_type=WorkflowType.INSTALL,
            include_cognito_update=include_cognito_update
        )
        assert CognitoPreservationService.COGNITO_STACK_TYPE not in stacks_to_skip

    def test_update_workflow_without_cognito_update_preserves(self):
        """
        Property: For UPDATE workflow with include_cognito_update=False,
        Cognito SHALL be preserved (skipped during deployment).
        
        Validates: Requirement 2.1
        """
        service = CognitoPreservationService()
        
        should_preserve = service.should_preserve_cognito(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=False
        )
        
        assert should_preserve is True
        
        # Verify Cognito is in stacks_to_skip
        stacks_to_skip = service.get_stacks_to_skip(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=False
        )
        assert CognitoPreservationService.COGNITO_STACK_TYPE in stacks_to_skip

    def test_update_workflow_with_cognito_update_does_not_preserve(self):
        """
        Property: For UPDATE workflow with include_cognito_update=True,
        Cognito SHALL NOT be preserved (will be updated).
        
        Validates: Requirement 3.4 (user confirms Cognito update)
        """
        service = CognitoPreservationService()
        
        should_preserve = service.should_preserve_cognito(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=True
        )
        
        assert should_preserve is False
        
        # Verify Cognito is NOT in stacks_to_skip
        stacks_to_skip = service.get_stacks_to_skip(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=True
        )
        assert CognitoPreservationService.COGNITO_STACK_TYPE not in stacks_to_skip

    @given(
        workflow_type=st.sampled_from([WorkflowType.INSTALL, WorkflowType.UPDATE]),
        include_cognito_update=st.booleans()
    )
    @settings(max_examples=10)
    def test_preservation_decision_is_deterministic(
        self,
        workflow_type: WorkflowType,
        include_cognito_update: bool
    ):
        """
        Property: For any given workflow_type and include_cognito_update,
        the preservation decision SHALL be deterministic (same inputs → same output).
        """
        service = CognitoPreservationService()
        
        # Call twice with same inputs
        result1 = service.should_preserve_cognito(workflow_type, include_cognito_update)
        result2 = service.should_preserve_cognito(workflow_type, include_cognito_update)
        
        assert result1 == result2

    @given(
        workflow_type=st.sampled_from([WorkflowType.INSTALL, WorkflowType.UPDATE]),
        include_cognito_update=st.booleans()
    )
    @settings(max_examples=10)
    def test_stacks_to_skip_consistent_with_should_preserve(
        self,
        workflow_type: WorkflowType,
        include_cognito_update: bool
    ):
        """
        Property: get_stacks_to_skip() SHALL be consistent with should_preserve_cognito().
        If should_preserve returns True, Cognito stack type SHALL be in stacks_to_skip.
        """
        service = CognitoPreservationService()
        
        should_preserve = service.should_preserve_cognito(workflow_type, include_cognito_update)
        stacks_to_skip = service.get_stacks_to_skip(workflow_type, include_cognito_update)
        
        cognito_in_skip_list = CognitoPreservationService.COGNITO_STACK_TYPE in stacks_to_skip
        
        assert should_preserve == cognito_in_skip_list


class TestCognitoPreservationRules:
    """
    Additional tests for preservation rule consistency.
    """

    def test_update_workflow_default_preserves_cognito(self):
        """
        Test that UPDATE workflow defaults to preserving Cognito
        when include_cognito_update is not specified (defaults to False).
        """
        service = CognitoPreservationService()
        
        # Default value for include_cognito_update is False
        should_preserve = service.should_preserve_cognito(
            workflow_type=WorkflowType.UPDATE
        )
        
        assert should_preserve is True

    def test_cognito_stack_type_constant(self):
        """
        Test that the Cognito stack type constant is correctly defined.
        """
        assert CognitoPreservationService.COGNITO_STACK_TYPE == "frontend-cognito"

    @given(
        workflow_type=st.sampled_from([WorkflowType.INSTALL, WorkflowType.UPDATE]),
        include_cognito_update=st.booleans()
    )
    @settings(max_examples=10)
    def test_stacks_to_skip_only_contains_cognito_or_empty(
        self,
        workflow_type: WorkflowType,
        include_cognito_update: bool
    ):
        """
        Property: get_stacks_to_skip() SHALL only return Cognito stack type or empty list.
        No other stack types should be in the skip list from this service.
        """
        service = CognitoPreservationService()
        
        stacks_to_skip = service.get_stacks_to_skip(workflow_type, include_cognito_update)
        
        # Should only contain Cognito stack type or be empty
        for stack in stacks_to_skip:
            assert stack == CognitoPreservationService.COGNITO_STACK_TYPE


class TestCognitoOutputsModel:
    """Tests for CognitoOutputs data model."""

    @given(
        user_pool_id=st.text(min_size=1, max_size=100),
        user_pool_client_id=st.text(min_size=1, max_size=100),
        user_pool_domain=st.text(min_size=0, max_size=200),
        region=st.sampled_from(['us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1'])
    )
    @settings(max_examples=10)
    def test_cognito_outputs_preserves_all_fields(
        self,
        user_pool_id: str,
        user_pool_client_id: str,
        user_pool_domain: str,
        region: str
    ):
        """
        Property: CognitoOutputs SHALL preserve all input fields correctly.
        """
        from app.models.cognito_models import CognitoOutputs
        
        outputs = CognitoOutputs(
            user_pool_id=user_pool_id,
            user_pool_client_id=user_pool_client_id,
            user_pool_domain=user_pool_domain,
            region=region
        )
        
        assert outputs.user_pool_id == user_pool_id
        assert outputs.user_pool_client_id == user_pool_client_id
        assert outputs.user_pool_domain == user_pool_domain
        assert outputs.region == region


class TestCognitoValidationResultModel:
    """Tests for CognitoValidationResult data model."""

    @given(
        is_valid=st.booleans(),
        user_pool_accessible=st.booleans(),
        client_configured=st.booleans(),
        user_count=st.integers(min_value=0, max_value=1000000)
    )
    @settings(max_examples=10)
    def test_validation_result_preserves_all_fields(
        self,
        is_valid: bool,
        user_pool_accessible: bool,
        client_configured: bool,
        user_count: int
    ):
        """
        Property: CognitoValidationResult SHALL preserve all input fields correctly.
        """
        from app.models.cognito_models import CognitoValidationResult
        
        result = CognitoValidationResult(
            is_valid=is_valid,
            user_pool_accessible=user_pool_accessible,
            client_configured=client_configured,
            user_count=user_count
        )
        
        assert result.is_valid == is_valid
        assert result.user_pool_accessible == user_pool_accessible
        assert result.client_configured == client_configured
        assert result.user_count == user_count
