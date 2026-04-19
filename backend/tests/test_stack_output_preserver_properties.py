"""
Property-based tests for StackOutputPreserver.

Property 3: Cognito Output Preservation
- System SHALL retrieve existing Cognito outputs before any stack modifications
- Outputs SHALL be passed to all dependent stacks that require Cognito configuration

Validates: Requirements 2.3, 2.4, 6.1, 6.2, 6.3, 6.4
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

from app.models.stack_outputs import PreservedOutputs
from app.models.cognito_models import CognitoOutputs
from app.services.stack_output_preserver import StackOutputPreserver


# Strategies for generating test data
stack_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=50
).filter(lambda x: len(x.strip()) >= 3)

output_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N')),
    min_size=1,
    max_size=30
)

output_value_strategy = st.text(min_size=1, max_size=100)

outputs_strategy = st.dictionaries(
    keys=output_key_strategy,
    values=output_value_strategy,
    min_size=0,
    max_size=10
)

capability_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)

environment_strategy = st.sampled_from(['dev', 'stage', 'prod', 'test'])

region_strategy = st.sampled_from([
    'us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1'
])


def create_mock_stack_response(
    stack_name: str,
    outputs: dict,
    status: str = 'CREATE_COMPLETE'
):
    """Create a mock CloudFormation describe_stacks response."""
    cfn_outputs = [
        {'OutputKey': key, 'OutputValue': value}
        for key, value in outputs.items()
    ]
    
    return {
        'Stacks': [{
            'StackName': stack_name,
            'StackStatus': status,
            'Outputs': cfn_outputs
        }]
    }


def create_cognito_outputs():
    """Create standard Cognito outputs for testing."""
    return {
        'UserPoolId': 'us-east-1_ABC123',
        'UserPoolClientId': 'client123456',
        'UserPoolDomain': 'my-app-domain',
        'UserPoolArn': 'arn:aws:cognito-idp:us-east-1:123456789:userpool/us-east-1_ABC123'
    }


class TestCognitoOutputPreservation:
    """
    Property 3: Cognito Output Preservation
    
    Tests that Cognito outputs are correctly retrieved and preserved.
    """

    @given(
        user_pool_id=st.text(min_size=10, max_size=50),
        client_id=st.text(min_size=10, max_size=50),
        domain=st.text(min_size=5, max_size=50)
    )
    @settings(max_examples=10)
    def test_cognito_outputs_are_preserved(
        self,
        user_pool_id: str,
        client_id: str,
        domain: str
    ):
        """
        Property: Cognito outputs SHALL be retrieved and preserved.
        
        Validates: Requirement 6.1
        """
        preserver = StackOutputPreserver()
        
        cognito_outputs = {
            'UserPoolId': user_pool_id,
            'UserPoolClientId': client_id,
            'UserPoolDomain': domain
        }
        
        mock_response = create_mock_stack_response(
            'test-cap-dev-frontend-cognito',
            cognito_outputs
        )
        
        mock_client = MagicMock()
        mock_client.describe_stacks.return_value = mock_response
        mock_client.get_paginator.return_value.paginate.return_value = [{
            'StackSummaries': [{
                'StackName': 'test-cap-dev-frontend-cognito',
                'StackStatus': 'CREATE_COMPLETE'
            }]
        }]
        
        with patch.object(preserver, '_get_client', return_value=mock_client):
            result = preserver.preserve_all_outputs(
                capability_name='test-cap',
                environment='dev',
                region='us-east-1'
            )
        
        # Should have preserved the stack
        assert len(result) >= 1
        
        # Should be able to get Cognito outputs
        cognito = preserver.get_cognito_outputs()
        assert cognito is not None
        assert cognito.user_pool_id == user_pool_id
        assert cognito.user_pool_client_id == client_id
        assert cognito.user_pool_domain == domain

    @given(
        outputs=outputs_strategy,
        capability_name=capability_name_strategy,
        environment=environment_strategy
    )
    @settings(max_examples=10)
    def test_all_outputs_are_preserved(
        self,
        outputs: dict,
        capability_name: str,
        environment: str
    ):
        """
        Property: All stack outputs SHALL be preserved.
        
        Validates: Requirement 6.2
        """
        preserver = StackOutputPreserver()
        
        stack_name = f"{capability_name}-{environment}-backend"
        mock_response = create_mock_stack_response(stack_name, outputs)
        
        mock_client = MagicMock()
        mock_client.describe_stacks.return_value = mock_response
        mock_client.get_paginator.return_value.paginate.return_value = [{
            'StackSummaries': [{
                'StackName': stack_name,
                'StackStatus': 'CREATE_COMPLETE'
            }]
        }]
        
        with patch.object(preserver, '_get_client', return_value=mock_client):
            result = preserver.preserve_all_outputs(
                capability_name=capability_name,
                environment=environment,
                region='us-east-1'
            )
        
        if stack_name in result:
            preserved = result[stack_name]
            # All outputs should be preserved
            for key, value in outputs.items():
                assert key in preserved.outputs
                assert preserved.outputs[key] == value

    @given(
        stack_names=st.lists(stack_name_strategy, min_size=1, max_size=5, unique=True)
    )
    @settings(max_examples=10)
    def test_multiple_stacks_preserved(self, stack_names: list):
        """
        Property: Multiple stacks SHALL be preserved.
        
        Validates: Requirement 6.1
        """
        preserver = StackOutputPreserver()
        
        # Create mock responses for each stack
        def mock_describe_stacks(StackName):
            return create_mock_stack_response(
                StackName,
                {'Output1': f'value-{StackName}'}
            )
        
        mock_client = MagicMock()
        mock_client.describe_stacks.side_effect = mock_describe_stacks
        
        with patch.object(preserver, '_get_client', return_value=mock_client):
            result = preserver.preserve_all_outputs(
                capability_name='test',
                environment='dev',
                region='us-east-1',
                stack_names=stack_names
            )
        
        # All stacks should be preserved
        assert len(result) == len(stack_names)
        for stack_name in stack_names:
            assert stack_name in result

    def test_cognito_outputs_available_for_dependent_stacks(self):
        """
        Property: Cognito outputs SHALL be available for dependent stacks.
        
        Validates: Requirements 2.3, 2.4, 6.3, 6.4
        """
        preserver = StackOutputPreserver()
        
        cognito_outputs = create_cognito_outputs()
        cognito_stack = 'my-app-dev-frontend-cognito'
        
        mock_response = create_mock_stack_response(cognito_stack, cognito_outputs)
        
        mock_client = MagicMock()
        mock_client.describe_stacks.return_value = mock_response
        mock_client.get_paginator.return_value.paginate.return_value = [{
            'StackSummaries': [{
                'StackName': cognito_stack,
                'StackStatus': 'CREATE_COMPLETE'
            }]
        }]
        
        with patch.object(preserver, '_get_client', return_value=mock_client):
            preserver.preserve_all_outputs(
                capability_name='my-app',
                environment='dev',
                region='us-east-1'
            )
        
        # Cognito outputs should be available
        cognito = preserver.get_cognito_outputs()
        assert cognito is not None
        
        # Should be able to get specific output values
        user_pool_id = preserver.get_output_value(cognito_stack, 'UserPoolId')
        assert user_pool_id == cognito_outputs['UserPoolId']


class TestPreservedOutputsModel:
    """Tests for PreservedOutputs data model."""

    @given(
        stack_name=stack_name_strategy,
        outputs=outputs_strategy,
        is_cognito=st.booleans()
    )
    @settings(max_examples=10)
    def test_preserved_outputs_preserves_fields(
        self,
        stack_name: str,
        outputs: dict,
        is_cognito: bool
    ):
        """
        Property: PreservedOutputs SHALL preserve all input fields correctly.
        """
        timestamp = datetime.utcnow()
        
        preserved = PreservedOutputs(
            stack_name=stack_name,
            outputs=outputs,
            retrieved_at=timestamp,
            is_cognito_stack=is_cognito
        )
        
        assert preserved.stack_name == stack_name
        assert preserved.outputs == outputs
        assert preserved.retrieved_at == timestamp
        assert preserved.is_cognito_stack == is_cognito


class TestCognitoStackDetection:
    """Tests for Cognito stack detection logic."""

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy
    )
    @settings(max_examples=10)
    def test_cognito_stack_detected_by_name(
        self,
        capability_name: str,
        environment: str
    ):
        """
        Property: Cognito stack SHALL be detected by name pattern.
        """
        preserver = StackOutputPreserver()
        
        # Stack name containing 'frontend-cognito' should be detected
        stack_name = f"{capability_name}-{environment}-frontend-cognito"
        outputs = {'SomeOutput': 'value'}
        
        is_cognito = preserver._is_cognito_stack(stack_name, outputs)
        assert is_cognito is True

    def test_cognito_stack_detected_by_outputs(self):
        """
        Property: Cognito stack SHALL be detected by output keys.
        """
        preserver = StackOutputPreserver()
        
        # Stack with Cognito outputs should be detected
        outputs = {
            'UserPoolId': 'pool-123',
            'UserPoolClientId': 'client-456'
        }
        
        is_cognito = preserver._is_cognito_stack('some-stack', outputs)
        assert is_cognito is True

    @given(
        stack_name=stack_name_strategy.filter(
            lambda x: 'cognito' not in x.lower()
        )
    )
    @settings(max_examples=10)
    def test_non_cognito_stack_not_detected(self, stack_name: str):
        """
        Property: Non-Cognito stacks SHALL NOT be detected as Cognito.
        """
        preserver = StackOutputPreserver()
        
        # Stack without Cognito name or outputs
        outputs = {'SomeOutput': 'value', 'AnotherOutput': 'value2'}
        
        is_cognito = preserver._is_cognito_stack(stack_name, outputs)
        assert is_cognito is False


class TestOutputRetrieval:
    """Tests for output retrieval methods."""

    @given(
        stack_name=stack_name_strategy,
        outputs=outputs_strategy
    )
    @settings(max_examples=10)
    def test_get_outputs_for_stack(
        self,
        stack_name: str,
        outputs: dict
    ):
        """
        Property: get_outputs_for_stack SHALL return correct outputs.
        """
        preserver = StackOutputPreserver()
        
        # Manually add preserved outputs
        preserver._preserved_outputs[stack_name] = PreservedOutputs(
            stack_name=stack_name,
            outputs=outputs
        )
        
        retrieved = preserver.get_outputs_for_stack(stack_name)
        assert retrieved == outputs

    @given(stack_name=stack_name_strategy)
    @settings(max_examples=10)
    def test_get_outputs_for_nonexistent_stack(self, stack_name: str):
        """
        Property: get_outputs_for_stack SHALL return None for unknown stacks.
        """
        preserver = StackOutputPreserver()
        
        retrieved = preserver.get_outputs_for_stack(stack_name)
        assert retrieved is None

    @given(
        stack_name=stack_name_strategy,
        outputs=outputs_strategy
    )
    @settings(max_examples=10)
    def test_get_output_value(
        self,
        stack_name: str,
        outputs: dict
    ):
        """
        Property: get_output_value SHALL return correct value for key.
        """
        assume(len(outputs) > 0)
        
        preserver = StackOutputPreserver()
        
        preserver._preserved_outputs[stack_name] = PreservedOutputs(
            stack_name=stack_name,
            outputs=outputs
        )
        
        # Get first key
        key = list(outputs.keys())[0]
        expected_value = outputs[key]
        
        retrieved = preserver.get_output_value(stack_name, key)
        assert retrieved == expected_value


class TestPreservationSummary:
    """Tests for preservation summary."""

    @given(
        num_stacks=st.integers(min_value=0, max_value=10)
    )
    @settings(max_examples=10)
    def test_preservation_summary_counts(self, num_stacks: int):
        """
        Property: Preservation summary SHALL report correct counts.
        """
        preserver = StackOutputPreserver()
        
        # Add stacks
        for i in range(num_stacks):
            preserver._preserved_outputs[f'stack-{i}'] = PreservedOutputs(
                stack_name=f'stack-{i}',
                outputs={'output': f'value-{i}'}
            )
        
        summary = preserver.get_preservation_summary()
        
        assert summary['total_stacks'] == num_stacks
        assert len(summary['stack_names']) == num_stacks

    def test_clear_preserved_outputs(self):
        """
        Property: clear_preserved_outputs SHALL remove all preserved data.
        """
        preserver = StackOutputPreserver()
        
        # Add some outputs
        preserver._preserved_outputs['stack-1'] = PreservedOutputs(
            stack_name='stack-1',
            outputs={'key': 'value'}
        )
        
        assert len(preserver._preserved_outputs) > 0
        
        preserver.clear_preserved_outputs()
        
        assert len(preserver._preserved_outputs) == 0
        assert preserver.get_cognito_outputs() is None
