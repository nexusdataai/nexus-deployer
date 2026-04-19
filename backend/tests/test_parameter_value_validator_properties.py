"""
Property Tests for Parameter Value Validator
Tests validation of parameter values against CloudFormation constraints.

Feature: deployment-prerequisites-verification
Requirements: 1.2, 1.3, 1.4, 1.5
"""
import pytest
from hypothesis import given, strategies as st, assume, settings, HealthCheck

from app.services.parameter_value_validator import (
    ParameterValueValidator,
    ParameterValidationResult,
    ValidationReport
)
from app.services.parameter_constraint_extractor import ParameterConstraint


class TestAllowedValuesValidation:
    """Property 1: AllowedValues Constraint Validation (Requirement 1.2)"""
    
    @given(
        allowed_values=st.lists(st.text(min_size=1, max_size=10), min_size=2, max_size=5, unique=True)
    )
    @settings(max_examples=30, suppress_health_check=[HealthCheck.filter_too_much])
    def test_value_in_allowed_list_is_valid(self, allowed_values):
        """Property: If value is in allowed list, validation passes."""
        assume(len(allowed_values) >= 1)
        value = allowed_values[0]  # Pick first value from allowed list
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_allowed_values(value, allowed_values)
        
        assert is_valid is True
        assert error is None
    
    @given(
        value=st.text(min_size=1, max_size=20),
        allowed_values=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10, unique=True)
    )
    @settings(max_examples=50)
    def test_value_not_in_allowed_list_is_invalid(self, value, allowed_values):
        """Property: If value is not in allowed list, validation fails."""
        assume(value not in allowed_values)
        assume(str(value) not in [str(v) for v in allowed_values])
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_allowed_values(value, allowed_values)
        
        assert is_valid is False
        assert error is not None
        assert "not in allowed values" in error
    
    def test_numeric_string_comparison(self):
        """Numeric values can match string representations."""
        validator = ParameterValueValidator()
        
        # Test with specific values
        is_valid, _ = validator.validate_allowed_values("30", [1, 7, 14, 30, 60])
        assert is_valid is True
        
        is_valid, _ = validator.validate_allowed_values(30, [1, 7, 14, 30, 60])
        assert is_valid is True


class TestMinLengthValidation:
    """Property 2: MinLength Constraint Validation (Requirement 1.3)"""
    
    @given(
        value=st.text(min_size=0, max_size=100),
        min_length=st.integers(min_value=0, max_value=50)
    )
    @settings(max_examples=50)
    def test_value_meeting_min_length_is_valid(self, value, min_length):
        """Property: If value length >= min_length, validation passes."""
        assume(len(value) >= min_length)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_min_length(value, min_length)
        
        assert is_valid is True
        assert error is None
    
    @given(
        value=st.text(min_size=0, max_size=50),
        min_length=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=50)
    def test_value_below_min_length_is_invalid(self, value, min_length):
        """Property: If value length < min_length, validation fails."""
        assume(len(value) < min_length)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_min_length(value, min_length)
        
        assert is_valid is False
        assert error is not None
        assert "less than minimum" in error
    
    def test_empty_value_with_min_length_one(self):
        """Empty string fails MinLength=1 validation."""
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_min_length("", 1)
        
        assert is_valid is False
        assert "less than minimum" in error


class TestMaxLengthValidation:
    """Property 3: MaxLength Constraint Validation (Requirement 1.4)"""
    
    @given(
        value=st.text(min_size=0, max_size=100),
        max_length=st.integers(min_value=0, max_value=200)
    )
    @settings(max_examples=50)
    def test_value_within_max_length_is_valid(self, value, max_length):
        """Property: If value length <= max_length, validation passes."""
        assume(len(value) <= max_length)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_max_length(value, max_length)
        
        assert is_valid is True
        assert error is None
    
    @given(
        value=st.text(min_size=1, max_size=100),
        max_length=st.integers(min_value=0, max_value=50)
    )
    @settings(max_examples=50)
    def test_value_exceeding_max_length_is_invalid(self, value, max_length):
        """Property: If value length > max_length, validation fails."""
        assume(len(value) > max_length)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_max_length(value, max_length)
        
        assert is_valid is False
        assert error is not None
        assert "exceeds maximum" in error


class TestAllowedPatternValidation:
    """Property 4: AllowedPattern Constraint Validation (Requirement 1.5)"""
    
    @given(value=st.from_regex(r'^[a-z]+$', fullmatch=True))
    @settings(max_examples=30)
    def test_value_matching_pattern_is_valid(self, value):
        """Property: If value matches pattern, validation passes."""
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_pattern(value, r'^[a-z]+$')
        
        assert is_valid is True
        assert error is None
    
    @given(value=st.from_regex(r'^[A-Z0-9]+$', fullmatch=True))
    @settings(max_examples=30)
    def test_value_not_matching_pattern_is_invalid(self, value):
        """Property: If value doesn't match pattern, validation fails."""
        assume(len(value) > 0)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_pattern(value, r'^[a-z]+$')
        
        assert is_valid is False
        assert error is not None
        assert "does not match pattern" in error
    
    def test_invalid_regex_pattern_returns_error(self):
        """Invalid regex pattern returns error message."""
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_pattern("test", r'[invalid(')
        
        assert is_valid is False
        assert "Invalid regex pattern" in error


class TestMinMaxValueValidation:
    """Tests for MinValue and MaxValue constraints."""
    
    @given(
        value=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
        min_value=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=50)
    def test_value_meeting_min_value_is_valid(self, value, min_value):
        """Property: If value >= min_value, validation passes."""
        assume(value >= min_value)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_min_value(value, min_value)
        
        assert is_valid is True
        assert error is None
    
    @given(
        value=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
        max_value=st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=50)
    def test_value_within_max_value_is_valid(self, value, max_value):
        """Property: If value <= max_value, validation passes."""
        assume(value <= max_value)
        
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_max_value(value, max_value)
        
        assert is_valid is True
        assert error is None


class TestTypeValidation:
    """Tests for Type constraint validation."""
    
    @given(value=st.integers())
    @settings(max_examples=30)
    def test_number_type_with_integer(self, value):
        """Integer values pass Number type validation."""
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_type(value, 'Number')
        
        assert is_valid is True
    
    @given(value=st.floats(allow_nan=False, allow_infinity=False))
    @settings(max_examples=30)
    def test_number_type_with_float(self, value):
        """Float values pass Number type validation."""
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_type(value, 'Number')
        
        assert is_valid is True
    
    def test_number_type_with_non_numeric_string(self):
        """Non-numeric string fails Number type validation."""
        validator = ParameterValueValidator()
        is_valid, error = validator.validate_type("not-a-number", 'Number')
        
        assert is_valid is False
        assert "not a valid number" in error


class TestParameterValidation:
    """Tests for complete parameter validation."""
    
    def test_validate_parameter_with_allowed_values_constraint(self):
        """Validate parameter against AllowedValues constraint."""
        validator = ParameterValueValidator()
        constraint = ParameterConstraint(
            parameter_name="LogRetentionDays",
            constraint_type="AllowedValues",
            constraint_value=[1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653],
            default_value=30
        )
        
        # Valid value
        result = validator.validate_parameter(30, constraint)
        assert result.is_valid is True
        
        # Invalid value
        result = validator.validate_parameter(10, constraint)
        assert result.is_valid is False
        assert result.remediation is not None
    
    def test_validate_parameter_with_min_length_constraint(self):
        """Validate parameter against MinLength constraint."""
        validator = ParameterValueValidator()
        constraint = ParameterConstraint(
            parameter_name="LoadBalancerDns",
            constraint_type="MinLength",
            constraint_value=1
        )
        
        # Valid value
        result = validator.validate_parameter("my-alb.example.com", constraint)
        assert result.is_valid is True
        
        # Invalid value (empty)
        result = validator.validate_parameter("", constraint)
        assert result.is_valid is False
        assert "at least 1 characters" in result.remediation


class TestValidationReport:
    """Tests for complete validation report generation."""
    
    def test_validate_all_parameters_with_valid_values(self):
        """All valid parameters produce successful report."""
        validator = ParameterValueValidator()
        template = {
            'Parameters': {
                'Environment': {
                    'Type': 'String',
                    'AllowedValues': ['dev', 'staging', 'prod'],
                    'Default': 'dev'
                },
                'InstanceCount': {
                    'Type': 'Number',
                    'MinValue': 1,
                    'MaxValue': 10,
                    'Default': 2
                }
            }
        }
        
        provided_values = {
            'Environment': 'prod',
            'InstanceCount': '5'
        }
        
        report = validator.validate_all_parameters(template, provided_values)
        
        assert report.success is True
        assert len(report.errors) == 0
    
    def test_validate_all_parameters_with_constraint_violations(self):
        """Constraint violations produce failed report with errors."""
        validator = ParameterValueValidator()
        template = {
            'Parameters': {
                'Environment': {
                    'Type': 'String',
                    'AllowedValues': ['dev', 'staging', 'prod']
                },
                'LoadBalancerDns': {
                    'Type': 'String',
                    'MinLength': 1
                }
            }
        }
        
        provided_values = {
            'Environment': 'invalid-env',
            'LoadBalancerDns': ''
        }
        
        report = validator.validate_all_parameters(template, provided_values)
        
        assert report.success is False
        assert len(report.errors) >= 2
