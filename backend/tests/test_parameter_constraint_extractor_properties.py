"""
Property-based tests for Parameter Constraint Extractor.

Feature: deployment-prerequisites-verification
Property 10: Constraint Extraction Completeness
Validates: Requirements 1.1
"""
import pytest
from hypothesis import given, strategies as st, settings, assume

from app.services.parameter_constraint_extractor import (
    ParameterConstraintExtractor,
    ParameterConstraint,
    ParameterDefinition,
    get_parameter_constraint_extractor
)


class TestParameterConstraintExtractorProperties:
    """Property-based tests for ParameterConstraintExtractor."""
    
    def setup_method(self):
        self.extractor = ParameterConstraintExtractor()
    
    # Strategy for generating valid CloudFormation parameter types
    cfn_types = st.sampled_from([
        'String', 'Number', 'List<Number>', 'CommaDelimitedList',
        'AWS::EC2::VPC::Id', 'AWS::EC2::Subnet::Id', 'AWS::EC2::SecurityGroup::Id',
        'AWS::SSM::Parameter::Value<String>'
    ])
    
    # Strategy for generating parameter names
    param_names = st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_'),
        min_size=1,
        max_size=50
    ).filter(lambda x: x[0].isalpha() if x else False)
    
    @given(
        param_name=param_names,
        param_type=cfn_types,
        allowed_values=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10)
    )
    @settings(max_examples=100)
    def test_allowed_values_constraint_extracted(self, param_name, param_type, allowed_values):
        """
        Property 10: For any template with AllowedValues constraint,
        the extractor SHALL extract the AllowedValues constraint.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': param_type,
                    'AllowedValues': allowed_values
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Should have at least Type and AllowedValues constraints
        assert len(constraints) >= 2
        
        # Find AllowedValues constraint
        av_constraints = [c for c in constraints if c.constraint_type == 'AllowedValues']
        assert len(av_constraints) == 1
        assert av_constraints[0].parameter_name == param_name
        assert av_constraints[0].constraint_value == allowed_values
    
    @given(
        param_name=param_names,
        min_length=st.integers(min_value=0, max_value=1000)
    )
    @settings(max_examples=100)
    def test_min_length_constraint_extracted(self, param_name, min_length):
        """
        Property 10: For any template with MinLength constraint,
        the extractor SHALL extract the MinLength constraint.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'MinLength': min_length
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Find MinLength constraint
        ml_constraints = [c for c in constraints if c.constraint_type == 'MinLength']
        assert len(ml_constraints) == 1
        assert ml_constraints[0].parameter_name == param_name
        assert ml_constraints[0].constraint_value == min_length
    
    @given(
        param_name=param_names,
        max_length=st.integers(min_value=1, max_value=10000)
    )
    @settings(max_examples=100)
    def test_max_length_constraint_extracted(self, param_name, max_length):
        """
        Property 10: For any template with MaxLength constraint,
        the extractor SHALL extract the MaxLength constraint.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'MaxLength': max_length
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Find MaxLength constraint
        ml_constraints = [c for c in constraints if c.constraint_type == 'MaxLength']
        assert len(ml_constraints) == 1
        assert ml_constraints[0].parameter_name == param_name
        assert ml_constraints[0].constraint_value == max_length
    
    @given(
        param_name=param_names,
        pattern=st.sampled_from([r'^[a-z]+$', r'^\d{3}-\d{4}$', r'^[A-Za-z0-9]+$', r'.+'])
    )
    @settings(max_examples=100)
    def test_allowed_pattern_constraint_extracted(self, param_name, pattern):
        """
        Property 10: For any template with AllowedPattern constraint,
        the extractor SHALL extract the AllowedPattern constraint.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'AllowedPattern': pattern
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Find AllowedPattern constraint
        ap_constraints = [c for c in constraints if c.constraint_type == 'AllowedPattern']
        assert len(ap_constraints) == 1
        assert ap_constraints[0].parameter_name == param_name
        assert ap_constraints[0].constraint_value == pattern
    
    @given(
        param_name=param_names,
        param_type=cfn_types
    )
    @settings(max_examples=100)
    def test_type_constraint_always_extracted(self, param_name, param_type):
        """
        Property 10: For any parameter, the extractor SHALL extract the Type constraint.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': param_type
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Find Type constraint
        type_constraints = [c for c in constraints if c.constraint_type == 'Type']
        assert len(type_constraints) == 1
        assert type_constraints[0].parameter_name == param_name
        assert type_constraints[0].constraint_value == param_type
    
    @given(
        param_name=param_names,
        min_value=st.floats(min_value=-1e10, max_value=1e10, allow_nan=False, allow_infinity=False),
        max_value=st.floats(min_value=-1e10, max_value=1e10, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=100)
    def test_min_max_value_constraints_extracted(self, param_name, min_value, max_value):
        """
        Property 10: For any Number parameter with MinValue/MaxValue constraints,
        the extractor SHALL extract both constraints.
        """
        assume(min_value <= max_value)
        
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'Number',
                    'MinValue': min_value,
                    'MaxValue': max_value
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Find MinValue constraint
        min_constraints = [c for c in constraints if c.constraint_type == 'MinValue']
        assert len(min_constraints) == 1
        assert min_constraints[0].constraint_value == min_value
        
        # Find MaxValue constraint
        max_constraints = [c for c in constraints if c.constraint_type == 'MaxValue']
        assert len(max_constraints) == 1
        assert max_constraints[0].constraint_value == max_value
    
    @given(
        param_name=param_names,
        default_value=st.text(min_size=1, max_size=50)
    )
    @settings(max_examples=100)
    def test_default_value_preserved(self, param_name, default_value):
        """
        Property 10: For any parameter with a default value,
        the extractor SHALL preserve the default value in constraints.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'Default': default_value
                }
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # All constraints should have the default value
        for constraint in constraints:
            assert constraint.default_value == default_value
    
    @given(
        num_params=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=50)
    def test_all_parameters_processed(self, num_params):
        """
        Property 10: For any template with N parameters,
        the extractor SHALL process all N parameters.
        """
        template = {
            'Parameters': {
                f'Param{i}': {
                    'Type': 'String',
                    'AllowedValues': [f'value{i}']
                }
                for i in range(num_params)
            }
        }
        
        constraints = self.extractor.extract_constraints(template)
        
        # Should have constraints for all parameters
        param_names = {c.parameter_name for c in constraints}
        expected_names = {f'Param{i}' for i in range(num_params)}
        assert param_names == expected_names
    
    def test_empty_template_returns_empty_list(self):
        """Empty template should return empty constraint list."""
        template = {}
        constraints = self.extractor.extract_constraints(template)
        assert constraints == []
    
    def test_template_without_parameters_returns_empty_list(self):
        """Template without Parameters section should return empty list."""
        template = {
            'Resources': {
                'MyBucket': {'Type': 'AWS::S3::Bucket'}
            }
        }
        constraints = self.extractor.extract_constraints(template)
        assert constraints == []


class TestParameterDefinitionExtraction:
    """Tests for complete parameter definition extraction."""
    
    def setup_method(self):
        self.extractor = ParameterConstraintExtractor()
    
    def test_extract_complete_definition(self):
        """Test extracting a complete parameter definition."""
        template = {
            'Parameters': {
                'Environment': {
                    'Type': 'String',
                    'Default': 'dev',
                    'Description': 'Environment name',
                    'AllowedValues': ['dev', 'staging', 'prod'],
                    'AllowedPattern': '^[a-z]+$',
                    'MinLength': 2,
                    'MaxLength': 10,
                    'ConstraintDescription': 'Must be lowercase letters',
                    'NoEcho': False
                }
            }
        }
        
        definitions = self.extractor.extract_parameter_definitions(template)
        
        assert len(definitions) == 1
        defn = definitions[0]
        assert defn.name == 'Environment'
        assert defn.param_type == 'String'
        assert defn.default == 'dev'
        assert defn.description == 'Environment name'
        assert defn.allowed_values == ['dev', 'staging', 'prod']
        assert defn.allowed_pattern == '^[a-z]+$'
        assert defn.min_length == 2
        assert defn.max_length == 10
        assert defn.constraint_description == 'Must be lowercase letters'
        assert defn.no_echo is False
    
    def test_get_required_parameters(self):
        """Test identifying required parameters (no default)."""
        template = {
            'Parameters': {
                'Required1': {'Type': 'String'},
                'Optional1': {'Type': 'String', 'Default': 'default'},
                'Required2': {'Type': 'Number'},
                'Optional2': {'Type': 'Number', 'Default': 0}
            }
        }
        
        required = self.extractor.get_required_parameters(template)
        
        assert set(required) == {'Required1', 'Required2'}


class TestFactoryFunction:
    """Tests for factory function."""
    
    def test_get_parameter_constraint_extractor(self):
        """Test factory function returns correct type."""
        extractor = get_parameter_constraint_extractor()
        assert isinstance(extractor, ParameterConstraintExtractor)
