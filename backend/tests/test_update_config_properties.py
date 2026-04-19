"""
Property-based tests for Update Configuration.

Property 11: Configuration Application
- Configured defaults SHALL be applied unless explicitly overridden

Validates: Requirements 10.4
"""
import pytest
from hypothesis import given, strategies as st, settings

from app.models.update_config import (
    UpdateWorkflowConfig,
    UpdateConfig,
    apply_defaults
)


# Strategies for generating test data
boolean_strategy = st.booleans()

stack_list_strategy = st.one_of(
    st.none(),
    st.lists(
        st.text(min_size=3, max_size=30, alphabet='abcdefghijklmnopqrstuvwxyz-'),
        min_size=0,
        max_size=5,
        unique=True
    )
)


class TestConfigurationApplication:
    """
    Property 11: Configuration Application
    
    Tests that defaults are correctly applied to update configurations.
    """

    @given(
        default_preserve=boolean_strategy,
        require_backup=boolean_strategy,
        enable_selective=boolean_strategy,
        validate_before=boolean_strategy,
        validate_after=boolean_strategy,
        enable_drift=boolean_strategy,
        enable_audit=boolean_strategy
    )
    @settings(max_examples=10)
    def test_workflow_config_preserves_all_fields(
        self,
        default_preserve: bool,
        require_backup: bool,
        enable_selective: bool,
        validate_before: bool,
        validate_after: bool,
        enable_drift: bool,
        enable_audit: bool
    ):
        """
        Property: UpdateWorkflowConfig SHALL preserve all input fields.
        """
        config = UpdateWorkflowConfig(
            default_preserve_cognito=default_preserve,
            require_backup_before_cognito_update=require_backup,
            enable_selective_updates=enable_selective,
            validate_cognito_before_update=validate_before,
            validate_cognito_after_update=validate_after,
            enable_drift_detection=enable_drift,
            enable_audit_trail=enable_audit
        )
        
        assert config.default_preserve_cognito == default_preserve
        assert config.require_backup_before_cognito_update == require_backup
        assert config.enable_selective_updates == enable_selective
        assert config.validate_cognito_before_update == validate_before
        assert config.validate_cognito_after_update == validate_after
        assert config.enable_drift_detection == enable_drift
        assert config.enable_audit_trail == enable_audit

    @given(
        preserve_cognito=boolean_strategy,
        include_cognito_update=boolean_strategy,
        require_user_backup=boolean_strategy,
        selected_stacks=stack_list_strategy,
        skip_drift=boolean_strategy,
        skip_pre_val=boolean_strategy,
        skip_post_val=boolean_strategy
    )
    @settings(max_examples=10)
    def test_update_config_preserves_all_fields(
        self,
        preserve_cognito: bool,
        include_cognito_update: bool,
        require_user_backup: bool,
        selected_stacks: list,
        skip_drift: bool,
        skip_pre_val: bool,
        skip_post_val: bool
    ):
        """
        Property: UpdateConfig SHALL preserve all input fields.
        """
        config = UpdateConfig(
            preserve_cognito=preserve_cognito,
            include_cognito_update=include_cognito_update,
            require_user_backup=require_user_backup,
            selected_stacks=selected_stacks,
            skip_drift_detection=skip_drift,
            skip_pre_validation=skip_pre_val,
            skip_post_validation=skip_post_val
        )
        
        assert config.preserve_cognito == preserve_cognito
        assert config.include_cognito_update == include_cognito_update
        assert config.require_user_backup == require_user_backup
        assert config.selected_stacks == selected_stacks
        assert config.skip_drift_detection == skip_drift
        assert config.skip_pre_validation == skip_pre_val
        assert config.skip_post_validation == skip_post_val

    @given(
        workflow_enable_drift=boolean_strategy,
        update_skip_drift=boolean_strategy
    )
    @settings(max_examples=10)
    def test_drift_detection_defaults_applied(
        self,
        workflow_enable_drift: bool,
        update_skip_drift: bool
    ):
        """
        Property: Drift detection setting SHALL respect both workflow and update config.
        
        Validates: Requirement 10.4
        """
        workflow_config = UpdateWorkflowConfig(
            enable_drift_detection=workflow_enable_drift
        )
        
        update_config = UpdateConfig(
            skip_drift_detection=update_skip_drift
        )
        
        result = apply_defaults(update_config, workflow_config)
        
        # Skip drift if either config says to skip
        expected_skip = update_skip_drift or not workflow_enable_drift
        assert result.skip_drift_detection == expected_skip

    @given(
        workflow_validate_before=boolean_strategy,
        workflow_validate_after=boolean_strategy,
        update_skip_pre=boolean_strategy,
        update_skip_post=boolean_strategy
    )
    @settings(max_examples=10)
    def test_validation_defaults_applied(
        self,
        workflow_validate_before: bool,
        workflow_validate_after: bool,
        update_skip_pre: bool,
        update_skip_post: bool
    ):
        """
        Property: Validation settings SHALL respect both workflow and update config.
        
        Validates: Requirement 10.4
        """
        workflow_config = UpdateWorkflowConfig(
            validate_cognito_before_update=workflow_validate_before,
            validate_cognito_after_update=workflow_validate_after
        )
        
        update_config = UpdateConfig(
            skip_pre_validation=update_skip_pre,
            skip_post_validation=update_skip_post
        )
        
        result = apply_defaults(update_config, workflow_config)
        
        # Skip validation if either config says to skip
        expected_skip_pre = update_skip_pre or not workflow_validate_before
        expected_skip_post = update_skip_post or not workflow_validate_after
        
        assert result.skip_pre_validation == expected_skip_pre
        assert result.skip_post_validation == expected_skip_post

    def test_default_workflow_config_values(self):
        """
        Property: Default UpdateWorkflowConfig SHALL have safe defaults.
        """
        config = UpdateWorkflowConfig()
        
        # Safe defaults
        assert config.default_preserve_cognito is True
        assert config.require_backup_before_cognito_update is True
        assert config.enable_selective_updates is True
        assert config.validate_cognito_before_update is True
        assert config.validate_cognito_after_update is True
        assert config.enable_drift_detection is True
        assert config.enable_audit_trail is True

    def test_default_update_config_values(self):
        """
        Property: Default UpdateConfig SHALL have safe defaults.
        """
        config = UpdateConfig()
        
        # Safe defaults - preserve Cognito by default
        assert config.preserve_cognito is True
        assert config.include_cognito_update is False
        assert config.require_user_backup is True
        assert config.selected_stacks is None
        assert config.skip_drift_detection is False
        assert config.skip_pre_validation is False
        assert config.skip_post_validation is False


class TestConfigurationOverrides:
    """Tests for configuration override behavior."""

    @given(
        preserve_cognito=boolean_strategy,
        include_cognito_update=boolean_strategy
    )
    @settings(max_examples=10)
    def test_explicit_overrides_preserved(
        self,
        preserve_cognito: bool,
        include_cognito_update: bool
    ):
        """
        Property: Explicit overrides SHALL be preserved after apply_defaults.
        """
        workflow_config = UpdateWorkflowConfig()
        
        update_config = UpdateConfig(
            preserve_cognito=preserve_cognito,
            include_cognito_update=include_cognito_update
        )
        
        result = apply_defaults(update_config, workflow_config)
        
        # Explicit values should be preserved
        assert result.preserve_cognito == preserve_cognito
        assert result.include_cognito_update == include_cognito_update

    @given(selected_stacks=stack_list_strategy)
    @settings(max_examples=10)
    def test_selected_stacks_preserved(self, selected_stacks: list):
        """
        Property: selected_stacks SHALL be preserved after apply_defaults.
        """
        workflow_config = UpdateWorkflowConfig()
        update_config = UpdateConfig(selected_stacks=selected_stacks)
        
        result = apply_defaults(update_config, workflow_config)
        
        assert result.selected_stacks == selected_stacks
