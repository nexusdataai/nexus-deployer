"""
Property-based tests for Failure Handling.

Property 9: Failure Handling and Halt
- Stack update failure SHALL halt further updates
- Successful stacks before failure SHALL be reported
- CloudFormation rollback status SHALL be detected

Validates: Requirements 8.1, 8.2, 8.4, 8.5
"""
import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

from app.models.update_config import UpdateConfig
from app.models.update_result import UpdateResult
from app.services.update_workflow_orchestrator import UpdateWorkflowOrchestrator


# Strategies for generating test data
stack_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)


def create_mock_stack(name: str, stack_type: str = 'backend') -> dict:
    """Create a mock stack configuration."""
    return {
        'stack_name': name,
        'stack_type': stack_type,
        'template_path': f'/templates/{name}.yaml'
    }


class TestFailureHandling:
    """
    Property 9: Failure Handling and Halt
    
    Tests that failures are handled correctly and workflow halts appropriately.
    """

    @given(
        num_stacks_before_failure=st.integers(min_value=1, max_value=5),
        num_stacks_after_failure=st.integers(min_value=1, max_value=5)
    )
    @settings(max_examples=10)
    def test_updates_halt_on_failure(
        self,
        num_stacks_before_failure: int,
        num_stacks_after_failure: int
    ):
        """
        Property: Stack update failure SHALL halt further updates.
        
        Validates: Requirement 8.1
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        # Create stacks: some before failure, one that fails, some after
        stacks = []
        for i in range(num_stacks_before_failure):
            stacks.append(create_mock_stack(f'success-{i}', 'backend'))
        
        stacks.append(create_mock_stack('failing-stack', 'backend'))
        
        for i in range(num_stacks_after_failure):
            stacks.append(create_mock_stack(f'after-{i}', 'backend'))
        
        config = UpdateConfig(preserve_cognito=False)
        
        attempted_stacks = []
        
        def mock_deploy(stack, region, preserved_outputs=None):
            stack_name = stack.get('stack_name')
            attempted_stacks.append(stack_name)
            return stack_name != 'failing-stack'
        
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
        
        # Stacks after failure should not be attempted
        for i in range(num_stacks_after_failure):
            assert f'after-{i}' not in attempted_stacks
        
        # Result should indicate failure
        assert result.success is False
        assert 'failing-stack' in result.stacks_failed

    @given(num_successful=st.integers(min_value=1, max_value=10))
    @settings(max_examples=10)
    def test_successful_stacks_reported_before_failure(self, num_successful: int):
        """
        Property: Successful stacks before failure SHALL be reported.
        
        Validates: Requirement 8.2
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = []
        for i in range(num_successful):
            stacks.append(create_mock_stack(f'success-{i}', 'backend'))
        stacks.append(create_mock_stack('failing-stack', 'backend'))
        
        config = UpdateConfig(preserve_cognito=False)
        
        def mock_deploy(stack, region, preserved_outputs=None):
            return stack.get('stack_name') != 'failing-stack'
        
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
        
        # All successful stacks should be in updated list
        assert len(result.stacks_updated) == num_successful
        for i in range(num_successful):
            assert f'success-{i}' in result.stacks_updated

    def test_error_message_contains_failed_stack(self):
        """
        Property: Error message SHALL identify the failed stack.
        
        Validates: Requirement 8.4
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [
            create_mock_stack('stack-1', 'backend'),
            create_mock_stack('failing-stack', 'backend')
        ]
        
        config = UpdateConfig(preserve_cognito=False)
        
        def mock_deploy(stack, region, preserved_outputs=None):
            return stack.get('stack_name') != 'failing-stack'
        
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
        
        # Error message should mention the failed stack
        assert result.error_message is not None
        assert 'failing-stack' in result.error_message

    def test_exception_during_deploy_handled(self):
        """
        Property: Exceptions during deployment SHALL be caught and reported.
        
        Validates: Requirement 8.5
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        stacks = [create_mock_stack('exception-stack', 'backend')]
        config = UpdateConfig(preserve_cognito=False)
        
        def mock_deploy_exception(stack, region, preserved_outputs=None):
            raise Exception("CloudFormation error: Access denied")
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator, '_deploy_stack', side_effect=mock_deploy_exception):
                        result = orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks
                        )
        
        # Should not raise, should return failure result
        assert result.success is False
        assert 'exception-stack' in result.stacks_failed
        assert result.error_message is not None


class TestUpdateResultFailureProperties:
    """Tests for UpdateResult failure-related properties."""

    @given(
        num_updated=st.integers(min_value=0, max_value=10),
        num_failed=st.integers(min_value=0, max_value=10)
    )
    @settings(max_examples=10)
    def test_has_failures_property(self, num_updated: int, num_failed: int):
        """
        Property: has_failures SHALL be True iff stacks_failed is non-empty.
        """
        result = UpdateResult(
            success=num_failed == 0,
            stacks_updated=[f'u-{i}' for i in range(num_updated)],
            stacks_failed=[f'f-{i}' for i in range(num_failed)]
        )
        
        assert result.has_failures == (num_failed > 0)

    @given(error_msg=st.text(min_size=1, max_size=200))
    @settings(max_examples=10)
    def test_error_message_preserved(self, error_msg: str):
        """
        Property: Error message SHALL be preserved in result.
        """
        result = UpdateResult(
            success=False,
            error_message=error_msg
        )
        
        assert result.error_message == error_msg


class TestProgressReportingOnFailure:
    """Tests for progress reporting during failures."""

    def test_fail_prefix_used_on_failure(self):
        """
        Property: [FAIL] prefix SHALL be used when stack fails.
        """
        orchestrator = UpdateWorkflowOrchestrator()
        
        messages = []
        def capture_callback(msg):
            messages.append(msg)
        
        stacks = [create_mock_stack('failing-stack', 'backend')]
        config = UpdateConfig(preserve_cognito=False)
        
        def mock_deploy(stack, region, preserved_outputs=None):
            return False
        
        with patch.object(orchestrator.output_preserver, 'preserve_all_outputs'):
            with patch.object(orchestrator.output_preserver, 'get_cognito_outputs', return_value=None):
                with patch.object(orchestrator.output_preserver, 'get_outputs_for_stack', return_value=None):
                    with patch.object(orchestrator, '_deploy_stack', side_effect=mock_deploy):
                        orchestrator.execute_update(
                            capability_name='test',
                            environment='dev',
                            region='us-east-1',
                            update_config=config,
                            stacks_to_deploy=stacks,
                            callback=capture_callback
                        )
        
        # Should have a FAIL message
        fail_messages = [m for m in messages if '[FAIL]' in m]
        assert len(fail_messages) >= 1

    def test_completion_summary_shows_failure(self):
        """
        Property: Completion summary SHALL indicate failure status.
        """
        result = UpdateResult(
            success=False,
            stacks_updated=['stack-1'],
            stacks_failed=['stack-2'],
            error_message='Stack update failed'
        )
        
        orchestrator = UpdateWorkflowOrchestrator()
        summary = orchestrator._generate_completion_summary(result)
        
        # Summary should indicate failure
        assert 'FAILED' in summary
        assert 'Failed: 1' in summary
