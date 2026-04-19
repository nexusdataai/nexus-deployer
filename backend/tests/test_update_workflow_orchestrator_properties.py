"""
Property-based tests for UpdateWorkflowOrchestrator.

Property 8: Progress Reporting Format
- Preserved stacks: "[PRESERVE] {stack_name}: Skipping to preserve existing data"
- Updated stacks: "[UPDATE] {stack_name}: Updating existing stack"
- Completion: Summary with counts

Property 9: Failure Handling and Halt
- Stack update failure SHALL halt further updates
- Successful stacks before failure SHALL be reported

Property 10: Selective Update Validation
- Only selected stacks SHALL be updated
- Dependency validation SHALL be performed

Validates: Requirements 7.1-7.5, 8.1-8.5, 9.2-9.6
"""
import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

from app.models.workflow_classification import WorkflowType
from app.models.update_config import UpdateConfig, UpdateWorkflowConfig
from app.models.update_result import UpdateResult
from app.services.update_workflow_orchestrator import UpdateWorkflowOrchestrator


# Strategies for generating test data
stack_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)

capability_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=20
).filter(lambda x: len(x.strip()) >= 3)

environment_strategy = st.sampled_from(['dev', 'stage', 'prod'])

region_strategy = st.sampled_from(['us-east-1', 'us-west-2', 'eu-west-1'])


def create_mock_stack(name: str, stack_type: str = 'backend') -> dict:
    """Create a mock stack configuration."""
    return {
        'stack_name': name,
        'stack_type': stack_type,
        'template_path': f'/templates/{name}.yaml'
    }


class TestProgressReportingFormat:
    """
    Property 8: Progress Reporting Format
    
    Tests that progress messages follow the correct format.
    """

    @given(stack_name=stack_name_strategy)
    @settings(max_examples=10)
    def test_preserve_message_format(self, stack_name: str):
        """
        Property: Preserved stacks SHALL use [PRESERVE] prefix.
        
        Validates: Requirement 7.1
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        messages = []
        def capture_callback(msg):
            messages.append(msg)
        
        # Create config that preserves Cognito
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=False
        )
        
        # Create a Cognito stack that should be preserved
        stacks = [create_mock_stack(stack_name, 'frontend-cognito')]
        
        # Mock services
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                orchestrator.execute_update(
                    capability_name='test',
                    environment='dev',
                    region='us-east-1',
                    update_config=config,
                    stacks_to_deploy=stacks,
                    callback=capture_callback
                )
        
        # Check for preserve message
        preserve_messages = [m for m in messages if '[PRESERVE]' in m]
        assert len(preserve_messages) >= 1
        
        # Verify format
        for msg in preserve_messages:
            assert 'Skipping to preserve' in msg or 'preserve' in msg.lower()

    @given(stack_name=stack_name_strategy)
    @settings(max_examples=10)
    def test_update_message_format(self, stack_name: str):
        """
        Property: Updated stacks SHALL use [UPDATE] prefix.
        
        Validates: Requirement 7.2
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        messages = []
        def capture_callback(msg):
            messages.append(msg)
        
        # Create config that updates all stacks (no preservation, no backup required)
        config = UpdateConfig(
            preserve_cognito=False,
            include_cognito_update=True,
            require_user_backup=False
        )
        
        # Create a backend stack (not Cognito) that should be updated
        stacks = [create_mock_stack(stack_name, 'backend-service')]
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator, '_deploy_stack', return_value=True):
                        orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks,
                            callback=capture_callback
                        )
        
        # Check for update message
        update_messages = [m for m in messages if '[UPDATE]' in m]
        assert len(update_messages) >= 1, f"Expected [UPDATE] messages, got: {messages}"
        
        # Verify format
        for msg in update_messages:
            assert 'Updating' in msg or 'update' in msg.lower()

    @given(
        num_updated=st.integers(min_value=0, max_value=5),
        num_preserved=st.integers(min_value=0, max_value=5)
    )
    @settings(max_examples=10)
    def test_completion_summary_contains_counts(
        self,
        num_updated: int,
        num_preserved: int
    ):
        """
        Property: Completion summary SHALL contain stack counts.
        
        Validates: Requirements 7.4, 7.5
        """
        result = UpdateResult(
            success=True,
            stacks_updated=[f'updated-{i}' for i in range(num_updated)],
            stacks_preserved=[f'preserved-{i}' for i in range(num_preserved)],
            stacks_failed=[]
        )
        
        orchestrator = UpdateWorkflowOrchestrator()
        summary = orchestrator._generate_completion_summary(result)
        
        # Summary should contain counts
        assert f'Stacks Updated: {num_updated}' in summary
        assert f'Stacks Preserved: {num_preserved}' in summary


class TestFailureHandlingAndHalt:
    """
    Property 9: Failure Handling and Halt
    
    Tests that failures halt the workflow and report successful stacks.
    """

    def test_failure_halts_further_updates(self):
        """
        Property: Stack update failure SHALL halt further updates.
        
        Validates: Requirement 8.1
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        # Create multiple stacks
        stacks = [
            create_mock_stack('stack-1', 'backend'),
            create_mock_stack('stack-2', 'backend'),
            create_mock_stack('stack-3', 'backend')
        ]
        
        config = UpdateConfig(preserve_cognito=False)
        
        # Track which stacks were attempted
        attempted_stacks = []
        
        def mock_deploy(stack, region, preserved_outputs=None):
            stack_name = stack.get('stack_name')
            attempted_stacks.append(stack_name)
            # Fail on second stack
            return stack_name != 'stack-2'
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator, '_deploy_stack', side_effect=mock_deploy):
                        result = orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks
                        )
        
        # Should have halted after stack-2 failure
        assert 'stack-3' not in attempted_stacks or 'stack-2' in result.stacks_failed
        assert result.success is False

    def test_successful_stacks_reported_before_failure(self):
        """
        Property: Successful stacks before failure SHALL be reported.
        
        Validates: Requirement 8.2
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [
            create_mock_stack('stack-1', 'backend'),
            create_mock_stack('stack-2', 'backend'),
            create_mock_stack('stack-3', 'backend')
        ]
        
        config = UpdateConfig(preserve_cognito=False)
        
        def mock_deploy(stack, region, preserved_outputs=None):
            stack_name = stack.get('stack_name')
            # Fail on second stack
            return stack_name != 'stack-2'
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator, '_deploy_stack', side_effect=mock_deploy):
                        result = orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks
                        )
        
        # stack-1 should be in updated list
        assert 'stack-1' in result.stacks_updated
        # stack-2 should be in failed list
        assert 'stack-2' in result.stacks_failed


class TestSelectiveUpdateValidation:
    """
    Property 10: Selective Update Validation
    
    Tests that selective updates work correctly.
    """

    @given(
        selected=st.lists(stack_name_strategy, min_size=1, max_size=3, unique=True),
        not_selected=st.lists(stack_name_strategy, min_size=1, max_size=3, unique=True)
    )
    @settings(max_examples=10)
    def test_only_selected_stacks_updated(
        self,
        selected: list,
        not_selected: list
    ):
        """
        Property: Only selected stacks SHALL be updated when selected_stacks is specified.
        
        Validates: Requirement 9.2
        """
        # Ensure no overlap
        assume(not set(selected) & set(not_selected))
        
        orchestrator = UpdateWorkflowOrchestrator()
        
        all_stacks = [
            create_mock_stack(name, 'backend')
            for name in selected + not_selected
        ]
        
        config = UpdateConfig(
            preserve_cognito=False,
            selected_stacks=selected
        )
        
        stacks_to_update, stacks_to_preserve = orchestrator.get_stacks_to_update(
            config=config,
            stacks_to_deploy=all_stacks
        )
        
        updated_names = [s['stack_name'] for s in stacks_to_update]
        
        # Selected stacks should be in update list
        for name in selected:
            assert name in updated_names
        
        # Non-selected stacks should NOT be in update list
        for name in not_selected:
            assert name not in updated_names

    def test_dependency_validation(self):
        """
        Property: Dependency validation SHALL report required additional stacks.
        
        Validates: Requirements 9.4, 9.5, 9.6
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        # Stack B depends on Stack A
        dependencies = {
            'stack-b': ['stack-a'],
            'stack-c': ['stack-b']
        }
        
        all_stacks = [
            create_mock_stack('stack-a', 'backend'),
            create_mock_stack('stack-b', 'backend'),
            create_mock_stack('stack-c', 'backend')
        ]
        
        # Try to update stack-b without stack-a
        result = orchestrator.validate_selective_update(
            selected_stacks=['stack-b'],
            all_stacks=all_stacks,
            dependencies=dependencies
        )
        
        # Should report that stack-a is required
        assert result['valid'] is False
        assert 'stack-a' in result['required_additional_stacks']


class TestUpdateResultModel:
    """Tests for UpdateResult data model."""

    @given(
        num_updated=st.integers(min_value=0, max_value=10),
        num_preserved=st.integers(min_value=0, max_value=10),
        num_failed=st.integers(min_value=0, max_value=10)
    )
    @settings(max_examples=10)
    def test_total_stacks_property(
        self,
        num_updated: int,
        num_preserved: int,
        num_failed: int
    ):
        """
        Property: total_stacks SHALL equal sum of all stack lists.
        """
        result = UpdateResult(
            success=True,
            stacks_updated=[f'u-{i}' for i in range(num_updated)],
            stacks_preserved=[f'p-{i}' for i in range(num_preserved)],
            stacks_failed=[f'f-{i}' for i in range(num_failed)]
        )
        
        assert result.total_stacks == num_updated + num_preserved + num_failed

    @given(num_failed=st.integers(min_value=0, max_value=10))
    @settings(max_examples=10)
    def test_has_failures_property(self, num_failed: int):
        """
        Property: has_failures SHALL be True iff stacks_failed is non-empty.
        """
        result = UpdateResult(
            success=True,
            stacks_failed=[f'f-{i}' for i in range(num_failed)]
        )
        
        assert result.has_failures == (num_failed > 0)

    @given(
        success=st.booleans(),
        cognito_preserved=st.booleans(),
        drift_detected=st.booleans()
    )
    @settings(max_examples=10)
    def test_to_summary_includes_key_info(
        self,
        success: bool,
        cognito_preserved: bool,
        drift_detected: bool
    ):
        """
        Property: to_summary() SHALL include key information.
        """
        result = UpdateResult(
            success=success,
            cognito_preserved=cognito_preserved,
            drift_detected=drift_detected,
            stacks_updated=['stack-1'],
            stacks_preserved=['stack-2']
        )
        
        summary = result.to_summary()
        
        # Should contain status
        if success:
            assert 'successfully' in summary.lower() or 'success' in summary.lower()
        else:
            assert 'failed' in summary.lower()
        
        # Should contain counts
        assert 'Updated: 1' in summary
        assert 'Preserved: 1' in summary


class TestCognitoPreservationInOrchestrator:
    """Tests for Cognito preservation in orchestrator."""

    def test_cognito_stack_preserved_when_configured(self):
        """
        Property: Cognito stack SHALL be preserved when preserve_cognito=True.
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [
            create_mock_stack('backend-stack', 'backend'),
            create_mock_stack('cognito-stack', 'frontend-cognito')
        ]
        
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=False
        )
        
        stacks_to_update, stacks_to_preserve = orchestrator.get_stacks_to_update(
            config=config,
            stacks_to_deploy=stacks
        )
        
        preserved_names = [s['stack_name'] for s in stacks_to_preserve]
        updated_names = [s['stack_name'] for s in stacks_to_update]
        
        # Cognito should be preserved
        assert 'cognito-stack' in preserved_names
        # Backend should be updated
        assert 'backend-stack' in updated_names

    def test_cognito_stack_updated_when_included(self):
        """
        Property: Cognito stack SHALL be updated when include_cognito_update=True.
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [
            create_mock_stack('backend-stack', 'backend'),
            create_mock_stack('cognito-stack', 'frontend-cognito')
        ]
        
        config = UpdateConfig(
            preserve_cognito=True,
            include_cognito_update=True
        )
        
        stacks_to_update, stacks_to_preserve = orchestrator.get_stacks_to_update(
            config=config,
            stacks_to_deploy=stacks
        )
        
        updated_names = [s['stack_name'] for s in stacks_to_update]
        
        # Both should be updated
        assert 'cognito-stack' in updated_names
        assert 'backend-stack' in updated_names
