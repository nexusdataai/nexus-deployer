"""
Parameter Value Validator Service
Validates parameter values against CloudFormation constraints.

Provides:
- AllowedValues validation
- MinLength/MaxLength validation
- AllowedPattern validation
- Type validation
- MinValue/MaxValue validation

Feature: deployment-prerequisites-verification
Requirements: 1.2, 1.3, 1.4, 1.5
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

from app.services.parameter_constraint_extractor import (
    ParameterConstraint,
    ParameterDefinition,
    ParameterConstraintExtractor
)


logger = logging.getLogger(__name__)


@dataclass
class ParameterValidationResult:
    """Result of validating a single parameter."""
    parameter_name: str
    is_valid: bool
    configured_value: Any
    constraint_type: Optional[str] = None
    constraint_value: Optional[Any] = None
    error_message: Optional[str] = None
    remediation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'parameter_name': self.parameter_name,
            'is_valid': self.is_valid,
            'configured_value': self.configured_value,
            'constraint_type': self.constraint_type,
            'constraint_value': self.constraint_value,
            'error_message': self.error_message,
            'remediation': self.remediation
        }


@dataclass
class ValidationReport:
    """Complete validation report for all parameters."""
    success: bool
    results: List[ParameterValidationResult] = field(default_factory=list)
    errors: List[ParameterValidationResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'results': [r.to_dict() for r in self.results],
            'errors': [e.to_dict() for e in self.errors]
        }


class ParameterValueValidator:
    """Validates parameter values against CloudFormation constraints."""
    
    def __init__(self):
        self.extractor = ParameterConstraintExtractor()
    
    def validate_allowed_values(
        self,
        value: Any,
        allowed: List[Any]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if value is in allowed list.
        
        Args:
            value: The value to validate
            allowed: List of allowed values
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if value in allowed:
            return True, None
        
        # Try string comparison for numeric values
        str_value = str(value)
        str_allowed = [str(a) for a in allowed]
        if str_value in str_allowed:
            return True, None
        
        return False, f"Value '{value}' is not in allowed values: {allowed}"
    
    def validate_min_length(
        self,
        value: str,
        min_length: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if value meets minimum length.
        
        Args:
            value: The string value to validate
            min_length: Minimum required length
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        str_value = str(value) if value is not None else ''
        actual_length = len(str_value)
        
        if actual_length >= min_length:
            return True, None
        
        return False, f"Value length {actual_length} is less than minimum {min_length}"
    
    def validate_max_length(
        self,
        value: str,
        max_length: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if value does not exceed maximum length.
        
        Args:
            value: The string value to validate
            max_length: Maximum allowed length
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        str_value = str(value) if value is not None else ''
        actual_length = len(str_value)
        
        if actual_length <= max_length:
            return True, None
        
        return False, f"Value length {actual_length} exceeds maximum {max_length}"
    
    def validate_pattern(
        self,
        value: str,
        pattern: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if value matches regex pattern.
        
        Args:
            value: The string value to validate
            pattern: Regex pattern to match
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        str_value = str(value) if value is not None else ''
        
        try:
            if re.match(pattern, str_value):
                return True, None
            return False, f"Value '{str_value}' does not match pattern '{pattern}'"
        except re.error as e:
            return False, f"Invalid regex pattern '{pattern}': {e}"
    
    def validate_min_value(
        self,
        value: Any,
        min_value: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if numeric value meets minimum.
        
        Args:
            value: The numeric value to validate
            min_value: Minimum allowed value
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            num_value = float(value)
            if num_value >= min_value:
                return True, None
            return False, f"Value {num_value} is less than minimum {min_value}"
        except (ValueError, TypeError):
            return False, f"Cannot convert '{value}' to number for MinValue validation"
    
    def validate_max_value(
        self,
        value: Any,
        max_value: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if numeric value does not exceed maximum.
        
        Args:
            value: The numeric value to validate
            max_value: Maximum allowed value
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            num_value = float(value)
            if num_value <= max_value:
                return True, None
            return False, f"Value {num_value} exceeds maximum {max_value}"
        except (ValueError, TypeError):
            return False, f"Cannot convert '{value}' to number for MaxValue validation"
    
    def validate_type(
        self,
        value: Any,
        param_type: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if value matches expected type.
        
        Args:
            value: The value to validate
            param_type: Expected CloudFormation parameter type
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if param_type == 'Number':
            try:
                float(value)
                return True, None
            except (ValueError, TypeError):
                return False, f"Value '{value}' is not a valid number"
        
        elif param_type == 'List<Number>':
            if isinstance(value, list):
                for item in value:
                    try:
                        float(item)
                    except (ValueError, TypeError):
                        return False, f"List item '{item}' is not a valid number"
                return True, None
            elif isinstance(value, str):
                # Could be comma-separated
                for item in value.split(','):
                    try:
                        float(item.strip())
                    except (ValueError, TypeError):
                        return False, f"List item '{item.strip()}' is not a valid number"
                return True, None
            return False, f"Value '{value}' is not a valid List<Number>"
        
        elif param_type == 'CommaDelimitedList':
            if isinstance(value, (list, str)):
                return True, None
            return False, f"Value '{value}' is not a valid CommaDelimitedList"
        
        elif param_type.startswith('AWS::'):
            # AWS-specific types - basic format validation
            str_value = str(value) if value is not None else ''
            if str_value:
                return True, None
            return False, f"Value is empty for AWS type {param_type}"
        
        # String type or unknown - accept anything
        return True, None
    
    def validate_parameter(
        self,
        value: Any,
        constraint: ParameterConstraint
    ) -> ParameterValidationResult:
        """
        Validate a parameter value against its constraint.
        
        Args:
            value: The value to validate
            constraint: The constraint to validate against
            
        Returns:
            ParameterValidationResult with validation details
        """
        result = ParameterValidationResult(
            parameter_name=constraint.parameter_name,
            is_valid=True,
            configured_value=value,
            constraint_type=constraint.constraint_type,
            constraint_value=constraint.constraint_value
        )
        
        is_valid = True
        error_message = None
        
        if constraint.constraint_type == 'AllowedValues':
            is_valid, error_message = self.validate_allowed_values(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Use one of: {constraint.constraint_value}"
        
        elif constraint.constraint_type == 'MinLength':
            is_valid, error_message = self.validate_min_length(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Provide a value with at least {constraint.constraint_value} characters"
        
        elif constraint.constraint_type == 'MaxLength':
            is_valid, error_message = self.validate_max_length(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Provide a value with at most {constraint.constraint_value} characters"
        
        elif constraint.constraint_type == 'AllowedPattern':
            is_valid, error_message = self.validate_pattern(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Provide a value matching pattern: {constraint.constraint_value}"
        
        elif constraint.constraint_type == 'MinValue':
            is_valid, error_message = self.validate_min_value(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Provide a value >= {constraint.constraint_value}"
        
        elif constraint.constraint_type == 'MaxValue':
            is_valid, error_message = self.validate_max_value(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Provide a value <= {constraint.constraint_value}"
        
        elif constraint.constraint_type == 'Type':
            is_valid, error_message = self.validate_type(
                value, constraint.constraint_value
            )
            if not is_valid:
                result.remediation = f"Provide a value of type {constraint.constraint_value}"
        
        result.is_valid = is_valid
        result.error_message = error_message
        
        return result
    
    def validate_all_parameters(
        self,
        template: Dict[str, Any],
        provided_values: Dict[str, Any]
    ) -> ValidationReport:
        """
        Validate all parameters in a template against provided values.
        
        Args:
            template: Parsed CloudFormation template
            provided_values: Dictionary of parameter name to value
            
        Returns:
            ValidationReport with all validation results
        """
        report = ValidationReport(success=True)
        
        constraints = self.extractor.extract_constraints(template)
        
        # Group constraints by parameter
        param_constraints: Dict[str, List[ParameterConstraint]] = {}
        for constraint in constraints:
            if constraint.parameter_name not in param_constraints:
                param_constraints[constraint.parameter_name] = []
            param_constraints[constraint.parameter_name].append(constraint)
        
        # Validate each parameter
        for param_name, param_constraints_list in param_constraints.items():
            # Get value (provided or default)
            if param_name in provided_values:
                value = provided_values[param_name]
            else:
                # Use default if available
                default = None
                for c in param_constraints_list:
                    if c.default_value is not None:
                        default = c.default_value
                        break
                
                if default is None:
                    # Required parameter not provided
                    result = ParameterValidationResult(
                        parameter_name=param_name,
                        is_valid=False,
                        configured_value=None,
                        error_message="Required parameter not provided",
                        remediation=f"Provide a value for parameter '{param_name}'"
                    )
                    report.results.append(result)
                    report.errors.append(result)
                    report.success = False
                    continue
                
                value = default
            
            # Validate against all constraints (except Type which is informational)
            for constraint in param_constraints_list:
                if constraint.constraint_type == 'Type':
                    # Type validation
                    result = self.validate_parameter(value, constraint)
                    report.results.append(result)
                    if not result.is_valid:
                        report.errors.append(result)
                        report.success = False
                else:
                    result = self.validate_parameter(value, constraint)
                    report.results.append(result)
                    if not result.is_valid:
                        report.errors.append(result)
                        report.success = False
        
        return report


def get_parameter_value_validator() -> ParameterValueValidator:
    """Factory function to get a ParameterValueValidator instance."""
    return ParameterValueValidator()
