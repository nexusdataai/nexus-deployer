"""
Property-based tests for WorkflowClassifier.

Property 1: Workflow Classification Consistency
- No existing deployment record → INSTALL workflow
- Existing record + "Clean Deploy" strategy → INSTALL workflow
- Existing record + "Update Existing" strategy → UPDATE workflow

Validates: Requirements 1.1, 1.2, 1.3, 1.4
"""
import pytest
from hypothesis import given, strategies as st, settings
from datetime import datetime

from app.models.workflow_classification import WorkflowType, WorkflowClassification
from app.services.workflow_classifier import WorkflowClassifier


# Strategies for generating test data
capability_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-_'),
    min_size=1,
    max_size=50
).filter(lambda x: x and x[0].isalpha())

environment_strategy = st.sampled_from(['dev', 'stage', 'prod'])

region_strategy = st.sampled_from([
    'us-east-1', 'us-west-2', 'eu-west-1', 'ap-southeast-1', 'ap-northeast-1'
])

stack_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('Ll', 'Lu', 'Nd'), whitelist_characters='-'),
    min_size=5,
    max_size=100
).filter(lambda x: x and x[0].isalpha())

existing_stacks_strategy = st.lists(stack_name_strategy, min_size=0, max_size=10)

strategy_strategy = st.sampled_from([None, 'clean_deploy', 'update_existing'])


class TestWorkflowClassificationConsistency:
    """
    Property 1: Workflow Classification Consistency
    
    Tests that workflow classification follows consistent rules:
    - No existing stacks → INSTALL
    - Existing stacks + clean_deploy → INSTALL
    - Existing stacks + update_existing → UPDATE
    """

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy
    )
    @settings(max_examples=10)
    def test_no_existing_stacks_returns_install(
        self,
        capability_name: str,
        environment: str,
        region: str
    ):
        """
        Property: For any deployment with no existing stacks,
        the classifier SHALL return INSTALL workflow.
        
        Validates: Requirement 1.2
        """
        classifier = WorkflowClassifier()
        
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy=None,
            existing_stacks=[]  # No existing stacks
        )
        
        assert result.workflow_type == WorkflowType.INSTALL
        assert result.is_install() is True
        assert result.is_update() is False
        assert len(result.existing_stacks) == 0

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy,
        existing_stacks=st.lists(stack_name_strategy, min_size=1, max_size=10)
    )
    @settings(max_examples=10)
    def test_existing_stacks_with_clean_deploy_returns_install(
        self,
        capability_name: str,
        environment: str,
        region: str,
        existing_stacks: list
    ):
        """
        Property: For any deployment with existing stacks AND user selects
        "clean_deploy" strategy, the classifier SHALL return INSTALL workflow.
        
        Validates: Requirement 1.4
        """
        classifier = WorkflowClassifier()
        
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy='clean_deploy',
            existing_stacks=existing_stacks
        )
        
        assert result.workflow_type == WorkflowType.INSTALL
        assert result.is_install() is True
        assert result.strategy_selected == 'clean_deploy'

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy,
        existing_stacks=st.lists(stack_name_strategy, min_size=1, max_size=10)
    )
    @settings(max_examples=10)
    def test_existing_stacks_with_update_existing_returns_update(
        self,
        capability_name: str,
        environment: str,
        region: str,
        existing_stacks: list
    ):
        """
        Property: For any deployment with existing stacks AND user selects
        "update_existing" strategy, the classifier SHALL return UPDATE workflow.
        
        Validates: Requirement 1.3
        """
        classifier = WorkflowClassifier()
        
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy='update_existing',
            existing_stacks=existing_stacks
        )
        
        assert result.workflow_type == WorkflowType.UPDATE
        assert result.is_update() is True
        assert result.is_install() is False
        assert result.strategy_selected == 'update_existing'

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy,
        existing_stacks=existing_stacks_strategy,
        user_strategy=strategy_strategy
    )
    @settings(max_examples=10)
    def test_classification_always_returns_valid_result(
        self,
        capability_name: str,
        environment: str,
        region: str,
        existing_stacks: list,
        user_strategy: str
    ):
        """
        Property: For any valid input combination, the classifier SHALL
        return a valid WorkflowClassification with all required fields.
        
        Validates: Requirement 1.1
        """
        classifier = WorkflowClassifier()
        
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy=user_strategy,
            existing_stacks=existing_stacks
        )
        
        # Verify all required fields are present
        assert result.workflow_type in [WorkflowType.INSTALL, WorkflowType.UPDATE]
        assert result.capability_name == capability_name
        assert result.environment == environment
        assert result.region == region
        assert isinstance(result.existing_stacks, list)
        assert result.strategy_selected == user_strategy
        assert isinstance(result.classification_timestamp, datetime)
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy,
        existing_stacks=st.lists(stack_name_strategy, min_size=1, max_size=10)
    )
    @settings(max_examples=10)
    def test_existing_stacks_without_strategy_defaults_to_update(
        self,
        capability_name: str,
        environment: str,
        region: str,
        existing_stacks: list
    ):
        """
        Property: For any deployment with existing stacks but no strategy
        selected, the classifier SHALL default to UPDATE workflow for safety.
        
        This ensures data preservation when user hasn't explicitly chosen.
        """
        classifier = WorkflowClassifier()
        
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy=None,  # No strategy selected
            existing_stacks=existing_stacks
        )
        
        # Should default to UPDATE to preserve data
        assert result.workflow_type == WorkflowType.UPDATE
        assert result.is_update() is True


class TestWorkflowClassificationMetadata:
    """Tests for classification metadata correctness."""

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy,
        existing_stacks=existing_stacks_strategy
    )
    @settings(max_examples=10)
    def test_classification_preserves_input_metadata(
        self,
        capability_name: str,
        environment: str,
        region: str,
        existing_stacks: list
    ):
        """
        Property: Classification result SHALL preserve all input metadata
        (capability_name, environment, region, existing_stacks).
        """
        classifier = WorkflowClassifier()
        
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy=None,
            existing_stacks=existing_stacks
        )
        
        assert result.capability_name == capability_name
        assert result.environment == environment
        assert result.region == region
        assert result.existing_stacks == existing_stacks

    @given(
        capability_name=capability_name_strategy,
        environment=environment_strategy,
        region=region_strategy
    )
    @settings(max_examples=10)
    def test_classification_timestamp_is_recent(
        self,
        capability_name: str,
        environment: str,
        region: str
    ):
        """
        Property: Classification timestamp SHALL be set to current time.
        """
        before = datetime.utcnow()
        
        classifier = WorkflowClassifier()
        result = classifier.classify_workflow(
            capability_name=capability_name,
            environment=environment,
            region=region,
            user_strategy=None,
            existing_stacks=[]
        )
        
        after = datetime.utcnow()
        
        assert before <= result.classification_timestamp <= after
