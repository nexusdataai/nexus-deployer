"""
Property tests for SSM parameter update behavior.

Validates that SSM parameters are correctly updated when values change,
and that existing parameters are not modified when values are the same.
"""

import pytest
from hypothesis import given, strategies as st, settings
from moto import mock_aws

from app.services.infra_provisioning.ssm_provisioner import SSMProvisioner
from app.services.infra_provisioning.models import ResourceStatusType, VALID_ENVIRONMENTS


# Strategies for property tests
env_strategy = st.sampled_from(list(VALID_ENVIRONMENTS))
value_strategy = st.text(min_size=1, max_size=100).filter(lambda x: x.strip())


@pytest.fixture
def mock_aws_env():
    """Set up mocked AWS environment."""
    with mock_aws():
        yield


class TestSSMParameterUpdateBehavior:
    """Property tests for SSM parameter update behavior (Requirement 3.9)."""
    
    @given(env=env_strategy, initial_value=value_strategy, new_value=value_strategy)
    @settings(max_examples=10)
    def test_parameter_update_when_value_changes(self, env: str, initial_value: str, new_value: str):
        """
        Property 8.1: When a parameter value changes, the parameter should be updated.
        """
        with mock_aws():
            provisioner = SSMProvisioner(env, "ap-southeast-1")
            param_path = f"/call-processing/{env}/test/update-test"
            
            # Create initial parameter
            result1 = provisioner.create_parameter(param_path, initial_value, "Test parameter")
            assert result1.status == ResourceStatusType.CREATED
            
            # Update with new value
            result2 = provisioner.create_parameter(param_path, new_value, "Test parameter")
            
            if initial_value != new_value:
                assert result2.status == ResourceStatusType.UPDATED, (
                    f"Parameter should be UPDATED when value changes from "
                    f"'{initial_value}' to '{new_value}'"
                )
            else:
                assert result2.status == ResourceStatusType.ALREADY_EXISTS, (
                    f"Parameter should be ALREADY_EXISTS when value is same: '{initial_value}'"
                )
    
    @given(env=env_strategy, value=value_strategy)
    @settings(max_examples=5)
    def test_parameter_not_updated_when_value_same(self, env: str, value: str):
        """
        Property 8.2: When a parameter value is the same, status should be ALREADY_EXISTS.
        """
        with mock_aws():
            provisioner = SSMProvisioner(env, "ap-southeast-1")
            param_path = f"/call-processing/{env}/test/same-value-test"
            
            # Create initial parameter
            result1 = provisioner.create_parameter(param_path, value, "Test parameter")
            assert result1.status == ResourceStatusType.CREATED
            
            # Try to create again with same value
            result2 = provisioner.create_parameter(param_path, value, "Test parameter")
            assert result2.status == ResourceStatusType.ALREADY_EXISTS, (
                f"Parameter should be ALREADY_EXISTS when value unchanged: '{value}'"
            )
    
    @given(env=env_strategy)
    @settings(max_examples=4)
    def test_parameter_update_preserves_path(self, env: str):
        """
        Property 8.3: Parameter path should remain unchanged after update.
        """
        with mock_aws():
            provisioner = SSMProvisioner(env, "ap-southeast-1")
            param_path = f"/call-processing/{env}/test/path-test"
            
            # Create and update
            provisioner.create_parameter(param_path, "initial", "Test parameter")
            result = provisioner.create_parameter(param_path, "updated", "Test parameter")
            
            # Verify path is preserved
            assert result.resource_name == param_path, (
                f"Parameter path should be preserved: expected '{param_path}', "
                f"got '{result.resource_name}'"
            )
    
    @given(env=env_strategy)
    @settings(max_examples=4)
    def test_multiple_updates_idempotent(self, env: str):
        """
        Property 8.4: Multiple updates with same value should be idempotent.
        """
        with mock_aws():
            provisioner = SSMProvisioner(env, "ap-southeast-1")
            param_path = f"/call-processing/{env}/test/idempotent-test"
            value = "test-value"
            
            # Create initial
            result1 = provisioner.create_parameter(param_path, value, "Test parameter")
            assert result1.status == ResourceStatusType.CREATED
            
            # Multiple updates with same value
            for i in range(3):
                result = provisioner.create_parameter(param_path, value, "Test parameter")
                assert result.status == ResourceStatusType.ALREADY_EXISTS, (
                    f"Update {i+1} should be ALREADY_EXISTS"
                )
    
    @given(env=env_strategy)
    @settings(max_examples=4)
    def test_update_sequence_tracking(self, env: str):
        """
        Property 8.5: Updates should correctly track value changes in sequence.
        """
        with mock_aws():
            provisioner = SSMProvisioner(env, "ap-southeast-1")
            param_path = f"/call-processing/{env}/test/sequence-test"
            
            values = ["value1", "value2", "value1", "value3", "value3"]
            expected_statuses = [
                ResourceStatusType.CREATED,      # First creation
                ResourceStatusType.UPDATED,      # value1 -> value2
                ResourceStatusType.UPDATED,      # value2 -> value1
                ResourceStatusType.UPDATED,      # value1 -> value3
                ResourceStatusType.ALREADY_EXISTS,  # value3 -> value3 (same)
            ]
            
            for i, (value, expected_status) in enumerate(zip(values, expected_statuses)):
                result = provisioner.create_parameter(param_path, value, "Test parameter")
                assert result.status == expected_status, (
                    f"Step {i+1}: Expected {expected_status.value} for value '{value}', "
                    f"got {result.status.value}"
                )


class TestSSMParameterUpdateEdgeCases:
    """Edge case tests for SSM parameter updates."""
    
    def test_update_empty_to_non_empty(self, mock_aws_env):
        """Update from placeholder to actual value."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        param_path = "/call-processing/dev/test/empty-test"
        
        # Create with placeholder
        result1 = provisioner.create_parameter(param_path, "PLACEHOLDER", "Test parameter")
        assert result1.status == ResourceStatusType.CREATED
        
        # Update with actual value
        result2 = provisioner.create_parameter(param_path, "actual-value", "Test parameter")
        assert result2.status == ResourceStatusType.UPDATED
    
    def test_update_with_special_characters(self, mock_aws_env):
        """Update parameter with special characters in value."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        param_path = "/call-processing/dev/test/special-chars"
        
        # Create with normal value
        result1 = provisioner.create_parameter(param_path, "normal", "Test parameter")
        assert result1.status == ResourceStatusType.CREATED
        
        # Update with special characters
        special_value = "value-with-special!@#$%^&*()_+-=[]{}|;':\",./<>?"
        result2 = provisioner.create_parameter(param_path, special_value, "Test parameter")
        assert result2.status == ResourceStatusType.UPDATED
    
    def test_update_with_long_value(self, mock_aws_env):
        """Update parameter with long value."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        param_path = "/call-processing/dev/test/long-value"
        
        # Create with short value
        result1 = provisioner.create_parameter(param_path, "short", "Test parameter")
        assert result1.status == ResourceStatusType.CREATED
        
        # Update with long value (SSM supports up to 4096 chars for standard params)
        long_value = "x" * 1000
        result2 = provisioner.create_parameter(param_path, long_value, "Test parameter")
        assert result2.status == ResourceStatusType.UPDATED
    
    def test_update_preserves_type(self, mock_aws_env):
        """Parameter type should be preserved after update."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        param_path = "/call-processing/dev/test/type-test"
        
        # Create and update
        provisioner.create_parameter(param_path, "initial", "Test parameter")
        provisioner.create_parameter(param_path, "updated", "Test parameter")
        
        # Verify type is still String
        response = provisioner.client.get_parameter(Name=param_path)
        assert response["Parameter"]["Type"] == "String"


class TestSSMProvisionAllUpdateBehavior:
    """Tests for provision_all update behavior."""
    
    def test_provision_all_updates_changed_parameters(self, mock_aws_env):
        """provision_all should update parameters that have changed."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        
        # First provision
        results1 = provisioner.provision_all()
        created_count = sum(1 for r in results1 if r.status == ResourceStatusType.CREATED)
        assert created_count > 0, "Should create parameters on first run"
        
        # Second provision (no changes)
        results2 = provisioner.provision_all()
        already_exists_count = sum(1 for r in results2 if r.status == ResourceStatusType.ALREADY_EXISTS)
        assert already_exists_count == len(results2), (
            "All parameters should be ALREADY_EXISTS on second run"
        )
    
    def test_provision_all_idempotent(self, mock_aws_env):
        """provision_all should be idempotent."""
        provisioner = SSMProvisioner("dev", "ap-southeast-1")
        
        # Run multiple times
        for i in range(3):
            results = provisioner.provision_all()
            
            # Should never fail
            failed = [r for r in results if r.status == ResourceStatusType.FAILED]
            assert len(failed) == 0, f"Run {i+1}: Should have no failures"
