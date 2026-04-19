"""
Parameter Constraint Extractor Service
Extracts parameter constraints from CloudFormation templates.

Provides:
- AllowedValues constraint extraction
- MinLength/MaxLength constraint extraction
- AllowedPattern constraint extraction
- Type constraint extraction
- Default value extraction

Feature: deployment-prerequisites-verification
Requirements: 1.1
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from app.utils.cfn_yaml_loader import CFNTag


logger = logging.getLogger(__name__)


@dataclass
class ParameterConstraint:
    """Represents a CloudFormation parameter constraint."""
    parameter_name: str
    constraint_type: str  # AllowedValues, MinLength, MaxLength, AllowedPattern, Type, MinValue, MaxValue
    constraint_value: Any  # List for AllowedValues, int for lengths, str for pattern
    default_value: Optional[str] = None
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'parameter_name': self.parameter_name,
            'constraint_type': self.constraint_type,
            'constraint_value': self.constraint_value,
            'default_value': self.default_value,
            'description': self.description
        }


@dataclass
class ParameterDefinition:
    """Complete parameter definition from a template."""
    name: str
    param_type: str = 'String'
    default: Optional[str] = None
    description: Optional[str] = None
    allowed_values: Optional[List[Any]] = None
    allowed_pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    constraint_description: Optional[str] = None
    no_echo: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'name': self.name,
            'type': self.param_type,
        }
        if self.default is not None:
            result['default'] = self.default
        if self.description:
            result['description'] = self.description
        if self.allowed_values:
            result['allowed_values'] = self.allowed_values
        if self.allowed_pattern:
            result['allowed_pattern'] = self.allowed_pattern
        if self.min_length is not None:
            result['min_length'] = self.min_length
        if self.max_length is not None:
            result['max_length'] = self.max_length
        if self.min_value is not None:
            result['min_value'] = self.min_value
        if self.max_value is not None:
            result['max_value'] = self.max_value
        if self.constraint_description:
            result['constraint_description'] = self.constraint_description
        if self.no_echo:
            result['no_echo'] = self.no_echo
        return result


class ParameterConstraintExtractor:
    """Extracts parameter constraints from CloudFormation templates."""
    
    def extract_constraints(self, template: Dict[str, Any]) -> List[ParameterConstraint]:
        """
        Extract all parameter constraints from a template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            List of ParameterConstraint objects
        """
        constraints = []
        
        parameters = template.get('Parameters', {})
        if not parameters:
            return constraints
        
        for param_name, param_def in parameters.items():
            if not isinstance(param_def, dict):
                continue
            
            default_value = param_def.get('Default')
            description = param_def.get('Description')
            
            # Extract Type constraint
            param_type = param_def.get('Type', 'String')
            if param_type:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='Type',
                    constraint_value=param_type,
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
            
            # Extract AllowedValues constraint
            allowed_values = param_def.get('AllowedValues')
            if allowed_values:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='AllowedValues',
                    constraint_value=allowed_values,
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
            
            # Extract MinLength constraint
            min_length = param_def.get('MinLength')
            if min_length is not None:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='MinLength',
                    constraint_value=int(min_length),
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
            
            # Extract MaxLength constraint
            max_length = param_def.get('MaxLength')
            if max_length is not None:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='MaxLength',
                    constraint_value=int(max_length),
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
            
            # Extract AllowedPattern constraint
            allowed_pattern = param_def.get('AllowedPattern')
            if allowed_pattern:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='AllowedPattern',
                    constraint_value=allowed_pattern,
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
            
            # Extract MinValue constraint (for Number type)
            min_value = param_def.get('MinValue')
            if min_value is not None:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='MinValue',
                    constraint_value=float(min_value),
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
            
            # Extract MaxValue constraint (for Number type)
            max_value = param_def.get('MaxValue')
            if max_value is not None:
                constraints.append(ParameterConstraint(
                    parameter_name=param_name,
                    constraint_type='MaxValue',
                    constraint_value=float(max_value),
                    default_value=str(default_value) if default_value is not None else None,
                    description=description
                ))
        
        return constraints
    
    def extract_parameter_definitions(self, template: Dict[str, Any]) -> List[ParameterDefinition]:
        """
        Extract complete parameter definitions from a template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            List of ParameterDefinition objects
        """
        definitions = []
        
        parameters = template.get('Parameters', {})
        if not parameters:
            return definitions
        
        for param_name, param_def in parameters.items():
            if not isinstance(param_def, dict):
                continue
            
            definition = ParameterDefinition(
                name=param_name,
                param_type=param_def.get('Type', 'String'),
                default=param_def.get('Default'),
                description=param_def.get('Description'),
                allowed_values=param_def.get('AllowedValues'),
                allowed_pattern=param_def.get('AllowedPattern'),
                min_length=self._safe_int(param_def.get('MinLength')),
                max_length=self._safe_int(param_def.get('MaxLength')),
                min_value=self._safe_float(param_def.get('MinValue')),
                max_value=self._safe_float(param_def.get('MaxValue')),
                constraint_description=param_def.get('ConstraintDescription'),
                no_echo=param_def.get('NoEcho', False)
            )
            definitions.append(definition)
        
        return definitions
    
    def get_required_parameters(self, template: Dict[str, Any]) -> List[str]:
        """
        Get parameters that have no default value (required).
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            List of required parameter names
        """
        required = []
        
        parameters = template.get('Parameters', {})
        if not parameters:
            return required
        
        for param_name, param_def in parameters.items():
            if not isinstance(param_def, dict):
                continue
            
            if 'Default' not in param_def:
                required.append(param_name)
        
        return required
    
    def get_constraints_for_parameter(
        self,
        template: Dict[str, Any],
        parameter_name: str
    ) -> List[ParameterConstraint]:
        """
        Get all constraints for a specific parameter.
        
        Args:
            template: Parsed CloudFormation template
            parameter_name: Name of the parameter
            
        Returns:
            List of ParameterConstraint objects for the parameter
        """
        all_constraints = self.extract_constraints(template)
        return [c for c in all_constraints if c.parameter_name == parameter_name]
    
    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert value to int."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert value to float."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


def get_parameter_constraint_extractor() -> ParameterConstraintExtractor:
    """Factory function to get a ParameterConstraintExtractor instance."""
    return ParameterConstraintExtractor()
