"""
Property-based tests for Update Audit Trail.

Property 13: Audit Trail Completeness
- Audit record SHALL contain operation type, timestamp, operator identity,
  per-stack actions, Cognito preservation status, export details, and final result

Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5
"""
import pytest
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, settings, assume

from app.models.audit_models import UpdateAuditRecord


# Strategies for generating test data
capability_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-'),
    min_size=3,
    max_size=30
).filter(lambda x: len(x.strip()) >= 3)

environment_strategy = st.sampled_from(['dev', 'stage', 'prod', 'test'])

region_strategy = st.sampled_from([
    'us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1'
])

stack_list_strategy = st.lists(
    st.text(min_size=3, max_size=50, alphabet='abcdefghijklmnopqrstuvwxyz-0123456789'),
    min_size=0,
    max_size=10,
    unique=True
)

operator_strategy = st.one_of(
    st.none(),
    st.text(min_size=3, max_size=100)
)

error_message_strategy = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=500)
)


class TestAuditTrailCompleteness:
    """
    Property 13: Audit Trail Completeness
    
    Tests that audit records contain all required fields.
    """

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy,
        operator=operator_strategy
    )
    @settings(max_examples=10)
    def test_audit_record_contains_required_fields(
        self,
        capability_name: str,
        environment: str,
        region: str,
        operator: str
    ):
        """
        Property: Audit record SHALL contain all required identification fields.
        
        Validates: Requirement 12.1
        """
        record = UpdateAuditRecord(
            capability_name=capability_name,
            environment=environment,
            region=region,
            operator_identity=operator
        )
        
        # Required fields
        assert record.operation_id is not None
        assert len(record.operation_id) > 0
        assert record.operation_type == "update"
        assert record.capability_name == capability_name
        assert record.environment == environment
        assert record.region == region
        assert record.operator_identity == operator
        assert record.timestamp is not None

    @given(
        stacks_updated=stack_list_strategy,
        stacks_preserved=stack_list_strategy,
        stacks_failed=stack_list_strategy
    )
    @settings(max_examples=10)
    def test_audit_record_contains_stack_actions(
        self,
        stacks_updated: list,
        stacks_preserved: list,
        stacks_failed: list
    ):
        """
        Property: Audit record SHALL contain per-stack actions.
        
        Validates: Requirement 12.2
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1',
            stacks_updated=stacks_updated,
            stacks_preserved=stacks_preserved,
            stacks_failed=stacks_failed
        )
        
        assert record.stacks_updated == stacks_updated
        assert record.stacks_preserved == stacks_preserved
        assert record.stacks_failed == stacks_failed

    @given(
        cognito_preserved=st.booleans(),
        user_exported=st.booleans(),
        user_count=st.integers(min_value=0, max_value=100000)
    )
    @settings(max_examples=10)
    def test_audit_record_contains_cognito_details(
        self,
        cognito_preserved: bool,
        user_exported: bool,
        user_count: int
    ):
        """
        Property: Audit record SHALL contain Cognito preservation status and export details.
        
        Validates: Requirements 12.3, 12.4
        """
        export_location = '/exports/users.json' if user_exported else None
        
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1',
            cognito_preserved=cognito_preserved,
            user_data_exported=user_exported,
            export_location=export_location,
            export_user_count=user_count if user_exported else None
        )
        
        assert record.cognito_preserved == cognito_preserved
        assert record.user_data_exported == user_exported
        
        if user_exported:
            assert record.export_location == export_location
            assert record.export_user_count == user_count

    @given(
        success=st.booleans(),
        error_message=error_message_strategy
    )
    @settings(max_examples=10)
    def test_audit_record_contains_result(
        self,
        success: bool,
        error_message: str
    ):
        """
        Property: Audit record SHALL contain final result.
        
        Validates: Requirement 12.5
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1',
            success=success,
            error_message=error_message if not success else None
        )
        
        assert record.success == success
        if not success and error_message:
            assert record.error_message == error_message


class TestAuditRecordMethods:
    """Tests for UpdateAuditRecord methods."""

    @given(
        success=st.booleans(),
        error_message=error_message_strategy
    )
    @settings(max_examples=10)
    def test_complete_method_sets_fields(
        self,
        success: bool,
        error_message: str
    ):
        """
        Property: complete() SHALL set completed_at, success, error_message, and duration.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        # Ensure some time passes
        record.timestamp = datetime.utcnow() - timedelta(seconds=5)
        
        record.complete(success=success, error_message=error_message)
        
        assert record.completed_at is not None
        assert record.success == success
        assert record.error_message == error_message
        assert record.duration_seconds is not None
        assert record.duration_seconds >= 0

    @given(stack_name=st.text(min_size=3, max_size=50))
    @settings(max_examples=10)
    def test_add_updated_stack(self, stack_name: str):
        """
        Property: add_updated_stack() SHALL add stack to updated list.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        record.add_updated_stack(stack_name)
        
        assert stack_name in record.stacks_updated

    @given(stack_name=st.text(min_size=3, max_size=50))
    @settings(max_examples=10)
    def test_add_preserved_stack(self, stack_name: str):
        """
        Property: add_preserved_stack() SHALL add stack to preserved list.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        record.add_preserved_stack(stack_name)
        
        assert stack_name in record.stacks_preserved

    @given(stack_name=st.text(min_size=3, max_size=50))
    @settings(max_examples=10)
    def test_add_failed_stack(self, stack_name: str):
        """
        Property: add_failed_stack() SHALL add stack to failed list.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        record.add_failed_stack(stack_name)
        
        assert stack_name in record.stacks_failed

    @given(
        exported=st.booleans(),
        user_count=st.integers(min_value=0, max_value=100000)
    )
    @settings(max_examples=10)
    def test_set_export_details(self, exported: bool, user_count: int):
        """
        Property: set_export_details() SHALL set export fields correctly.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        location = '/exports/test.json' if exported else None
        record.set_export_details(
            exported=exported,
            location=location,
            user_count=user_count if exported else None
        )
        
        assert record.user_data_exported == exported
        assert record.export_location == location
        if exported:
            assert record.export_user_count == user_count

    @given(
        detected=st.booleans(),
        items_count=st.integers(min_value=0, max_value=100)
    )
    @settings(max_examples=10)
    def test_set_drift_details(self, detected: bool, items_count: int):
        """
        Property: set_drift_details() SHALL set drift fields correctly.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        record.set_drift_details(detected=detected, items_count=items_count)
        
        assert record.drift_detected == detected
        assert record.drift_items_count == items_count


class TestAuditRecordUniqueness:
    """Tests for audit record uniqueness."""

    def test_operation_id_is_unique(self):
        """
        Property: Each audit record SHALL have a unique operation_id.
        """
        records = [
            UpdateAuditRecord(
                capability_name='test-cap',
                environment='dev',
                region='us-east-1'
            )
            for _ in range(10)
        ]
        
        operation_ids = [r.operation_id for r in records]
        
        # All IDs should be unique
        assert len(operation_ids) == len(set(operation_ids))


class TestAuditRecordSummary:
    """Tests for audit record summary generation."""

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        success=st.booleans(),
        num_updated=st.integers(min_value=0, max_value=10),
        num_preserved=st.integers(min_value=0, max_value=10),
        num_failed=st.integers(min_value=0, max_value=10)
    )
    @settings(max_examples=10)
    def test_to_summary_contains_key_fields(
        self,
        capability_name: str,
        environment: str,
        success: bool,
        num_updated: int,
        num_preserved: int,
        num_failed: int
    ):
        """
        Property: to_summary() SHALL return dict with key fields.
        """
        record = UpdateAuditRecord(
            capability_name=capability_name,
            environment=environment,
            region='us-east-1',
            success=success,
            stacks_updated=[f'stack-{i}' for i in range(num_updated)],
            stacks_preserved=[f'preserved-{i}' for i in range(num_preserved)],
            stacks_failed=[f'failed-{i}' for i in range(num_failed)]
        )
        
        summary = record.to_summary()
        
        assert summary['operation_id'] == record.operation_id
        assert summary['capability'] == capability_name
        assert summary['environment'] == environment
        assert summary['success'] == success
        assert summary['stacks_updated'] == num_updated
        assert summary['stacks_preserved'] == num_preserved
        assert summary['stacks_failed'] == num_failed


class TestAuditRecordNoDuplicates:
    """Tests for preventing duplicate entries."""

    @given(stack_name=st.text(min_size=3, max_size=50))
    @settings(max_examples=10)
    def test_add_updated_stack_no_duplicates(self, stack_name: str):
        """
        Property: Adding same stack twice SHALL NOT create duplicates.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        record.add_updated_stack(stack_name)
        record.add_updated_stack(stack_name)
        
        assert record.stacks_updated.count(stack_name) == 1

    @given(stack_name=st.text(min_size=3, max_size=50))
    @settings(max_examples=10)
    def test_add_preserved_stack_no_duplicates(self, stack_name: str):
        """
        Property: Adding same stack twice SHALL NOT create duplicates.
        """
        record = UpdateAuditRecord(
            capability_name='test-cap',
            environment='dev',
            region='us-east-1'
        )
        
        record.add_preserved_stack(stack_name)
        record.add_preserved_stack(stack_name)
        
        assert record.stacks_preserved.count(stack_name) == 1
