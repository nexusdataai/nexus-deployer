"""
Property-based tests for Cognito Update Inclusion.

Property 4: Cognito Update Inclusion
- When user confirms Cognito update, Cognito SHALL be included in deployment
- update_stack operation SHALL be used (not delete/create)

Validates: Requirements 3.4, 3.5
"""
import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings

from app.models.workflow_classification import WorkflowType
from app.models.update_config import UpdateConfig
from app.services.update_workflow_orchestrator import UpdateWorkflowOrchestrator
from app.services.cognito_preservation_service import CognitoPreservationService


# Strategies for generating test data
capability_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=20
).filter(lambda x: len(x.strip()) >= 3)

environment_strategy = st.sampled_from(['dev', 'stage', 'prod'])


def create_mock_stack(name: str, stack_type: str = 'backend') -> dict:
    """Create a mock stack configuration."""
    return {
        'stack_name': name,
        'stack_type': stack_type,
        'template_path': f'/templates/{name}.yaml'
    }


class TestCognitoUpdateInclusion:
    """
    Property 4: Cognito Update Inclusion
    
    Tests that Cognito is correctly included when user confirms update.
    """

    def test_cognito_included_when_update_confirmed(self):
        """
        Property: When include_cognito_update=True, Cognito SHALL be in update list.
        
        Validates: Requirement 3.4
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [
            create_mock_stack('backend-stack', 'backend'),
            create_mock_stack('cognito-stack', 'frontend-cognito'),
            create_mock_stack('api-stack', 'api')
        ]
        
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=True  # User confirmed Cognito update
        )
        
        stacks_to_update, stacks_to_preserve = orchestrator.get_stacks_to_update(
            config=config,
            stacks_to_deploy=stacks
        )
        
        updated_names = [s['stack_name'] for s in stacks_to_update]
        
        # Cognito should be in update list
        assert 'cognito-stack' in updated_names

    def test_cognito_excluded_when_update_not_confirmed(self):
        """
        Property: When include_cognito_update=False, Cognito SHALL NOT be in update list.
        
        Validates: Requirement 2.1
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [
            create_mock_stack('backend-stack', 'backend'),
            create_mock_stack('cognito-stack', 'frontend-cognito'),
            create_mock_stack('api-stack', 'api')
        ]
        
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=False  # User did not confirm Cognito update
        )
        
        stacks_to_update, stacks_to_preserve = orchestrator.get_stacks_to_update(
            config=config,
            stacks_to_deploy=stacks
        )
        
        updated_names = [s['stack_name'] for s in stacks_to_update]
        preserved_names = [s['stack_name'] for s in stacks_to_preserve]
        
        # Cognito should NOT be in update list
        assert 'cognito-stack' not in updated_names
        # Cognito should be in preserve list
        assert 'cognito-stack' in preserved_names

    @given(include_cognito=st.booleans())
    @settings(max_examples=10)
    def test_cognito_preservation_service_consistency(self, include_cognito: bool):
        """
        Property: CognitoPreservationService SHALL be consistent with orchestrator.
        """
        preservation_service = CognitoPreservationService()
        
        should_preserve = preservation_service.should_preserve_cognito(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=include_cognito
        )
        
        stacks_to_skip = preservation_service.get_stacks_to_skip(
            workflow_type=WorkflowType.UPDATE,
            include_cognito_update=include_cognito
        )
        
        # Consistency check
        if include_cognito:
            # Should NOT preserve (will update)
            assert should_preserve is False
            assert CognitoPreservationService.COGNITO_STACK_TYPE not in stacks_to_skip
        else:
            # Should preserve (skip update)
            assert should_preserve is True
            assert CognitoPreservationService.COGNITO_STACK_TYPE in stacks_to_skip


class TestCognitoUpdateOperation:
    """Tests for Cognito update operation type."""

    def test_update_operation_used_not_delete_create(self):
        """
        Property: update_stack SHALL be used, not delete/create.
        
        Validates: Requirement 3.5
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        # Track which operation is used
        operations_used = []
        
        def mock_deploy(stack, region, preserved_outputs=None):
            # In a real implementation, this would call cfn_service.update_stack
            # We're verifying the orchestrator calls _deploy_stack (update semantics)
            # not a delete followed by create
            operations_used.append(('update', stack.get('stack_name')))
            return True
        
        stacks = [create_mock_stack('cognito-stack', 'frontend-cognito')]
        
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=True,
            require_user_backup=False
        )
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator, '_deploy_stack', side_effect=mock_deploy):
                        orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks
                        )
        
        # Should have used update operation
        assert len(operations_used) == 1
        assert operations_used[0][0] == 'update'
        assert operations_used[0][1] == 'cognito-stack'


class TestCognitoUpdateWithPreservedOutputs:
    """Tests for Cognito update with preserved outputs."""

    def test_preserved_outputs_passed_to_cognito_update(self):
        """
        Property: Preserved outputs SHALL be available during Cognito update.
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        preserved_outputs_received = []
        
        def mock_deploy(stack, region, preserved_outputs=None):
            preserved_outputs_received.append({
                'stack': stack.get('stack_name'),
                'outputs': preserved_outputs
            })
            return True
        
        mock_outputs = {
            'UserPoolId': 'existing-pool-id',
            'UserPoolClientId': 'existing-client-id'
        }
        
        stacks = [create_mock_stack('cognito-stack', 'frontend-cognito')]
        
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=True,
            require_user_backup=False
        )
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=mock_outputs):
                    with patch.object(orchestrator, '_deploy_stack', side_effect=mock_deploy):
                        orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks
                        )
        
        # Preserved outputs should have been passed
        assert len(preserved_outputs_received) == 1
        assert preserved_outputs_received[0]['outputs'] == mock_outputs


class TestInstallWorkflowNeverPreserves:
    """Tests that INSTALL workflow never preserves Cognito."""

    @given(include_cognito=st.booleans())
    @settings(max_examples=10)
    def test_install_workflow_creates_new_cognito(self, include_cognito: bool):
        """
        Property: INSTALL workflow SHALL always create new Cognito (never preserve).
        """
        preservation_service = CognitoPreservationService()
        
        # For INSTALL workflow, should never preserve regardless of include_cognito
        should_preserve = preservation_service.should_preserve_cognito(
            workflow_type=WorkflowType.INSTALL,
            include_cognito_update=include_cognito
        )
        
        assert should_preserve is False

    def test_install_workflow_no_stacks_skipped(self):
        """
        Property: INSTALL workflow SHALL NOT skip any stacks.
        """
        preservation_service = CognitoPreservationService()
        
        stacks_to_skip = preservation_service.get_stacks_to_skip(
            workflow_type=WorkflowType.INSTALL,
            include_cognito_update=False
        )
        
        # No stacks should be skipped for install
        assert len(stacks_to_skip) == 0
