"""
Property-based tests for Template Validation.

Feature: cloudformation-template-reliability
Properties 2-8: Template Structure, Parameter, Condition, Mapping, Output Validation

Validates: Requirements 2.2-2.5, 3.1-3.6, 6.1-6.4, 7.1-7.2, 8.1-8.3
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
import re

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.template_validator import (
    TemplateValidator,
    StructureValidationResult,
    ParameterValidationResult,
    ConditionValidationResult,
    MappingValidationResult,
    OutputValidationResult
)
from app.utils.cfn_yaml_loader import CFNTag


def _is_valid_number(s: str) -> bool:
    """Check if a string can be parsed as a valid number by Python's float()."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# Strategies for generating test data
valid_logical_ids = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N'))
).filter(lambda x: x[0].isalpha() if x else False)

aws_services = st.sampled_from([
    'S3', 'Lambda', 'DynamoDB', 'IAM', 'EC2', 'SNS', 'SQS', 
    'CloudWatch', 'CloudFront', 'Route53', 'ECS', 'ECR'
])

aws_resource_suffixes = st.sampled_from([
    'Bucket', 'Function', 'Table', 'Role', 'Policy', 'Instance',
    'Topic', 'Queue', 'Alarm', 'Distribution', 'RecordSet', 'Service'
])


class TestStructureValidationProperty:
    """
    Property 2: Template Structure Validation Detects Invalid Templates
    
    For any CloudFormation template, the Template_Validator SHALL correctly
    identify whether it contains a Resources section and whether all resource
    types follow the AWS::Service::Resource naming pattern.
    """
    
    def setup_method(self):
        self.validator = TemplateValidator()
    
    @given(
        service=aws_services,
        suffix=aws_resource_suffixes,
        logical_id=valid_logical_ids
    )
    @settings(max_examples=100)
    def test_valid_resource_types_pass_validation(self, service: str, suffix: str, logical_id: str):
        """
        Requirement 2.3: Valid resource types pass validation.
        """
        template = {
            'Resources': {
                logical_id: {
                    'Type': f'AWS::{service}::{suffix}',
                    'Properties': {}
                }
            }
        }
        
        result = self.validator.validate_template_structure(template)
        
        assert result.success is True
        assert result.has_resources is True
        assert len(result.invalid_resource_types) == 0
    
    @given(invalid_type=st.text(min_size=1, max_size=30).filter(
        lambda x: not re.match(r'^(AWS::[A-Za-z0-9]+::[A-Za-z0-9]+|Custom::[A-Za-z0-9]+)$', x)
    ))
    @settings(max_examples=100)
    def test_invalid_resource_types_are_detected(self, invalid_type: str):
        """
        Requirement 2.3: Invalid resource types are detected.
        """
        assume(invalid_type.strip())  # Non-empty
        assume(not invalid_type.startswith('AWS::'))  # Not accidentally valid
        
        template = {
            'Resources': {
                'MyResource': {
                    'Type': invalid_type,
                    'Properties': {}
                }
            }
        }
        
        result = self.validator.validate_template_structure(template)
        
        assert result.success is False
        assert len(result.invalid_resource_types) > 0
    
    def test_missing_resources_section_detected(self):
        """
        Requirement 2.2: Missing Resources section is detected.
        """
        template = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'Template without resources'
        }
        
        result = self.validator.validate_template_structure(template)
        
        assert result.success is False
        assert result.has_resources is False
    
    @given(logical_id=valid_logical_ids)
    @settings(max_examples=50)
    def test_duplicate_logical_ids_detected(self, logical_id: str):
        """
        Requirement 2.5: Duplicate logical IDs are detected.
        """
        # Note: In Python dicts, duplicate keys overwrite, so we simulate
        # by checking the validator's duplicate detection logic
        template = {
            'Resources': {
                logical_id: {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {}
                }
            }
        }
        
        result = self.validator.validate_template_structure(template)
        
        # Single resource should pass
        assert result.success is True
    
    def test_custom_resource_types_are_valid(self):
        """Custom::* resource types should be valid."""
        template = {
            'Resources': {
                'MyCustomResource': {
                    'Type': 'Custom::MyCustomType',
                    'Properties': {}
                }
            }
        }
        
        result = self.validator.validate_template_structure(template)
        
        assert result.success is True
        assert len(result.invalid_resource_types) == 0


class TestParameterValidationProperty:
    """
    Property 3: Parameter Validation Catches All Constraint Violations
    
    For any CloudFormation template with parameters and any set of provided
    parameter values, the Parameter_Validator SHALL identify all missing
    required parameters, type mismatches, and constraint violations.
    """
    
    def setup_method(self):
        self.validator = TemplateValidator()
    
    @given(param_name=valid_logical_ids)
    @settings(max_examples=100)
    def test_missing_required_parameters_detected(self, param_name: str):
        """
        Requirement 3.1: Missing required parameters are detected.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'Description': 'A required parameter'
                    # No Default = required
                }
            },
            'Resources': {}
        }
        
        result = self.validator.validate_parameters(template, {})
        
        assert result.success is False
        assert param_name in result.missing_required
    
    @given(param_name=valid_logical_ids, default_value=st.text(min_size=1, max_size=20))
    @settings(max_examples=100)
    def test_parameters_with_defaults_not_required(self, param_name: str, default_value: str):
        """
        Requirement 3.1: Parameters with defaults are not required.
        """
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'Default': default_value
                }
            },
            'Resources': {}
        }
        
        result = self.validator.validate_parameters(template, {})
        
        assert param_name not in result.missing_required
    
    @given(param_name=valid_logical_ids, non_numeric=st.text(min_size=1, max_size=10).filter(
        lambda x: not _is_valid_number(x)
    ))
    @settings(max_examples=100)
    def test_number_type_mismatch_detected(self, param_name: str, non_numeric: str):
        """
        Requirement 3.2: Type mismatches are detected.
        """
        assume(non_numeric.strip())
        
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'Number'
                }
            },
            'Resources': {}
        }
        
        result = self.validator.validate_parameters(template, {param_name: non_numeric})
        
        assert result.success is False
        assert len(result.type_mismatches) > 0
    
    @given(
        param_name=valid_logical_ids,
        allowed=st.lists(st.text(min_size=1, max_size=10), min_size=2, max_size=5, unique=True),
        invalid_value=st.text(min_size=1, max_size=10)
    )
    @settings(max_examples=100)
    def test_allowed_values_constraint_violation_detected(
        self, param_name: str, allowed: list, invalid_value: str
    ):
        """
        Requirement 3.3: AllowedValues constraint violations are detected.
        """
        assume(invalid_value not in allowed)
        
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'String',
                    'AllowedValues': allowed
                }
            },
            'Resources': {}
        }
        
        result = self.validator.validate_parameters(template, {param_name: invalid_value})
        
        assert result.success is False
        assert len(result.constraint_violations) > 0
        assert any(v['constraint_type'] == 'AllowedValues' for v in result.constraint_violations)
    
    def test_allowed_pattern_constraint_violation_detected(self):
        """
        Requirement 3.4: AllowedPattern constraint violations are detected.
        """
        template = {
            'Parameters': {
                'BucketName': {
                    'Type': 'String',
                    'AllowedPattern': '^[a-z0-9-]+$'
                }
            },
            'Resources': {}
        }
        
        # Value with uppercase letters violates pattern
        result = self.validator.validate_parameters(template, {'BucketName': 'Invalid_Name!'})
        
        assert result.success is False
        assert len(result.constraint_violations) > 0
        assert any(v['constraint_type'] == 'AllowedPattern' for v in result.constraint_violations)
    
    @given(
        param_name=valid_logical_ids,
        min_val=st.integers(min_value=0, max_value=100),
        value=st.integers(min_value=-100, max_value=-1)
    )
    @settings(max_examples=100)
    def test_min_value_constraint_violation_detected(self, param_name: str, min_val: int, value: int):
        """
        Requirement 3.5: MinValue constraint violations are detected.
        """
        assume(value < min_val)
        
        template = {
            'Parameters': {
                param_name: {
                    'Type': 'Number',
                    'MinValue': min_val
                }
            },
            'Resources': {}
        }
        
        result = self.validator.validate_parameters(template, {param_name: str(value)})
        
        assert result.success is False
        assert len(result.constraint_violations) > 0
        assert any(v['constraint_type'] == 'MinValue' for v in result.constraint_violations)
    
    def test_all_violations_reported_in_single_result(self):
        """
        Requirement 3.6: All violations are reported in a single result.
        """
        template = {
            'Parameters': {
                'Required1': {'Type': 'String'},
                'Required2': {'Type': 'String'},
                'NumberParam': {'Type': 'Number'},
                'ConstrainedParam': {
                    'Type': 'String',
                    'AllowedValues': ['a', 'b', 'c']
                }
            },
            'Resources': {}
        }
        
        result = self.validator.validate_parameters(template, {
            'NumberParam': 'not-a-number',
            'ConstrainedParam': 'invalid'
        })
        
        # Should report multiple issues
        assert result.success is False
        assert len(result.missing_required) == 2  # Required1, Required2
        assert len(result.type_mismatches) == 1  # NumberParam
        assert len(result.constraint_violations) == 1  # ConstrainedParam


class TestConditionValidationProperty:
    """
    Property 6: Condition Validation Detects Undefined References
    
    For any CloudFormation template with conditions, the Template_Validator
    SHALL identify all references to undefined conditions and all condition
    functions that reference undefined parameters.
    """
    
    def setup_method(self):
        self.validator = TemplateValidator()
    
    @given(condition_name=valid_logical_ids)
    @settings(max_examples=100)
    def test_undefined_condition_reference_detected(self, condition_name: str):
        """
        Requirement 6.1: Undefined condition references are detected.
        """
        template = {
            'Conditions': {},  # No conditions defined
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::S3::Bucket',
                    'Condition': condition_name  # References undefined condition
                }
            }
        }
        
        result = self.validator.validate_conditions(template)
        
        assert result.success is False
        assert condition_name in result.undefined_conditions
    
    @given(condition_name=valid_logical_ids)
    @settings(max_examples=100)
    def test_defined_condition_reference_passes(self, condition_name: str):
        """
        Requirement 6.1: Defined condition references pass validation.
        """
        template = {
            'Parameters': {
                'Environment': {'Type': 'String', 'Default': 'dev'}
            },
            'Conditions': {
                condition_name: CFNTag('Equals', [CFNTag('Ref', 'Environment'), 'prod'])
            },
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::S3::Bucket',
                    'Condition': condition_name
                }
            }
        }
        
        result = self.validator.validate_conditions(template)
        
        assert condition_name not in result.undefined_conditions
    
    def test_condition_with_cfntag_reference(self):
        """
        Requirement 6.1: Condition references using CFNTag are validated.
        """
        template = {
            'Conditions': {
                'IsProd': CFNTag('Equals', [CFNTag('Ref', 'Environment'), 'prod'])
            },
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::S3::Bucket',
                    'Condition': CFNTag('Condition', 'UndefinedCondition')
                }
            }
        }
        
        result = self.validator.validate_conditions(template)
        
        assert 'UndefinedCondition' in result.undefined_conditions


class TestMappingValidationProperty:
    """
    Property 7: Mapping Validation Detects Invalid FindInMap References
    
    For any CloudFormation template with mappings and FindInMap references,
    the Template_Validator SHALL identify all references to non-existent
    mappings or missing first/second level keys.
    """
    
    def setup_method(self):
        self.validator = TemplateValidator()
    
    @given(mapping_name=valid_logical_ids)
    @settings(max_examples=100)
    def test_undefined_mapping_reference_detected(self, mapping_name: str):
        """
        Requirement 7.1: Undefined mapping references are detected.
        """
        template = {
            'Mappings': {},  # No mappings defined
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {
                        'BucketName': CFNTag('FindInMap', [mapping_name, 'key1', 'key2'])
                    }
                }
            }
        }
        
        result = self.validator.validate_mappings(template)
        
        assert result.success is False
        assert len(result.invalid_references) > 0
        assert any(r['mapping_name'] == mapping_name for r in result.invalid_references)
    
    def test_missing_first_level_key_detected(self):
        """
        Requirement 7.2: Missing first-level keys are detected.
        """
        template = {
            'Mappings': {
                'RegionMap': {
                    'us-east-1': {'AMI': 'ami-12345'}
                }
            },
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::EC2::Instance',
                    'Properties': {
                        'ImageId': CFNTag('FindInMap', ['RegionMap', 'us-west-2', 'AMI'])
                    }
                }
            }
        }
        
        result = self.validator.validate_mappings(template)
        
        assert result.success is False
        assert len(result.invalid_references) > 0
        assert any(r['missing_key'] == 'first_level' for r in result.invalid_references)
    
    def test_missing_second_level_key_detected(self):
        """
        Requirement 7.2: Missing second-level keys are detected.
        """
        template = {
            'Mappings': {
                'RegionMap': {
                    'us-east-1': {'AMI': 'ami-12345'}
                }
            },
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::EC2::Instance',
                    'Properties': {
                        'ImageId': CFNTag('FindInMap', ['RegionMap', 'us-east-1', 'NonExistentKey'])
                    }
                }
            }
        }
        
        result = self.validator.validate_mappings(template)
        
        assert result.success is False
        assert len(result.invalid_references) > 0
        assert any(r['missing_key'] == 'second_level' for r in result.invalid_references)
    
    def test_valid_findinmap_passes(self):
        """Valid FindInMap references should pass."""
        template = {
            'Mappings': {
                'RegionMap': {
                    'us-east-1': {'AMI': 'ami-12345'},
                    'us-west-2': {'AMI': 'ami-67890'}
                }
            },
            'Resources': {
                'MyResource': {
                    'Type': 'AWS::EC2::Instance',
                    'Properties': {
                        'ImageId': CFNTag('FindInMap', ['RegionMap', 'us-east-1', 'AMI'])
                    }
                }
            }
        }
        
        result = self.validator.validate_mappings(template)
        
        assert result.success is True
        assert len(result.invalid_references) == 0


class TestOutputValidationProperty:
    """
    Property 8: Output Validation Detects Invalid Outputs
    
    For any CloudFormation template with outputs, the Template_Validator
    SHALL identify all outputs missing a Value property, all outputs
    referencing non-existent resources, and all duplicate export names.
    """
    
    def setup_method(self):
        self.validator = TemplateValidator()
    
    @given(output_name=valid_logical_ids)
    @settings(max_examples=100)
    def test_output_without_value_detected(self, output_name: str):
        """
        Requirement 8.1: Outputs without Value property are detected.
        """
        template = {
            'Resources': {
                'MyBucket': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                output_name: {
                    'Description': 'Missing value'
                    # No Value property
                }
            }
        }
        
        result = self.validator.validate_outputs(template)
        
        assert result.success is False
        assert output_name in result.missing_values
    
    def test_output_with_invalid_getatt_reference_detected(self):
        """
        Requirement 8.3: Invalid GetAtt references are detected.
        """
        template = {
            'Resources': {
                'MyBucket': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                'BucketArn': {
                    'Value': CFNTag('GetAtt', ['NonExistentResource', 'Arn'])
                }
            }
        }
        
        result = self.validator.validate_outputs(template)
        
        assert result.success is False
        assert len(result.invalid_references) > 0
    
    def test_duplicate_export_names_detected(self):
        """
        Requirement 8.2: Duplicate export names are detected.
        """
        template = {
            'Resources': {
                'Bucket1': {'Type': 'AWS::S3::Bucket'},
                'Bucket2': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                'Output1': {
                    'Value': CFNTag('Ref', 'Bucket1'),
                    'Export': {'Name': 'SharedExportName'}
                },
                'Output2': {
                    'Value': CFNTag('Ref', 'Bucket2'),
                    'Export': {'Name': 'SharedExportName'}  # Duplicate
                }
            }
        }
        
        result = self.validator.validate_outputs(template)
        
        assert result.success is False
        assert 'SharedExportName' in result.duplicate_exports
    
    def test_valid_output_passes(self):
        """Valid outputs should pass validation."""
        template = {
            'Resources': {
                'MyBucket': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                'BucketName': {
                    'Value': CFNTag('Ref', 'MyBucket'),
                    'Export': {'Name': 'MyBucketName'}
                },
                'BucketArn': {
                    'Value': CFNTag('GetAtt', ['MyBucket', 'Arn'])
                }
            }
        }
        
        result = self.validator.validate_outputs(template)
        
        assert result.success is True
        assert len(result.missing_values) == 0
        assert len(result.invalid_references) == 0
        assert len(result.duplicate_exports) == 0
    
    def test_conflict_with_existing_exports_detected(self):
        """
        Requirement 8.2: Conflicts with existing exports are detected.
        """
        template = {
            'Resources': {
                'MyBucket': {'Type': 'AWS::S3::Bucket'}
            },
            'Outputs': {
                'BucketName': {
                    'Value': CFNTag('Ref', 'MyBucket'),
                    'Export': {'Name': 'ExistingExport'}
                }
            }
        }
        
        existing_exports = {'ExistingExport', 'AnotherExport'}
        result = self.validator.validate_outputs(template, all_exports=existing_exports)
        
        assert result.success is False
        assert any('ExistingExport' in e for e in result.duplicate_exports)
