"""
Property-based tests for Resource Limit Checker.

Feature: cloudformation-template-reliability
Property 5: Resource Limit Checker Warns About Limit Concerns

Validates: Requirements 5.1, 5.2, 5.3, 5.4
"""
import pytest
from hypothesis import given, strategies as st, settings

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.resource_limit_checker import (
    ResourceLimitChecker,
    ResourceLimitWarning,
    ResourceLimitResult
)


# Strategies for generating test data
resource_types = st.sampled_from([
    'AWS::S3::Bucket',
    'AWS::Lambda::Function',
    'AWS::DynamoDB::Table',
    'AWS::IAM::Role',
    'AWS::EC2::Instance',
    'AWS::SNS::Topic',
    'AWS::SQS::Queue',
    'AWS::CloudWatch::Alarm'
])

logical_ids = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=('L', 'N'))
).filter(lambda x: x[0].isalpha() if x else False)


class TestResourceLimitCheckerProperty:
    """
    Property 5: Resource Limit Checker Warns About Limit Concerns
    
    For any set of CloudFormation templates, the Resource_Limit_Checker
    SHALL accurately count resources by type and generate warnings when
    counts approach or exceed CloudFormation limits.
    """
    
    def setup_method(self):
        self.checker = ResourceLimitChecker()
    
    @given(
        resource_type=resource_types,
        count=st.integers(min_value=1, max_value=50)
    )
    @settings(max_examples=100)
    def test_resource_counting_is_accurate(self, resource_type: str, count: int):
        """
        Requirement 5.1: Resource counts by type are accurate.
        """
        # Generate template with specified number of resources
        resources = {}
        for i in range(count):
            resources[f'Resource{i}'] = {
                'Type': resource_type,
                'Properties': {}
            }
        
        template = {'Resources': resources}
        
        counts = self.checker.count_resources(template)
        
        assert counts.get(resource_type, 0) == count
    
    @given(count=st.integers(min_value=400, max_value=499))
    @settings(max_examples=20)
    def test_warning_generated_at_80_percent_threshold(self, count: int):
        """
        Requirement 5.2: Warning generated when approaching 500 resource limit.
        """
        # Generate template with resources approaching limit
        resources = {}
        for i in range(count):
            resources[f'Resource{i}'] = {
                'Type': 'AWS::S3::Bucket',
                'Properties': {}
            }
        
        template = {'Resources': resources}
        
        warnings = self.checker.check_stack_limits(template, 'TestStack')
        
        # Should have warning if count >= 400 (80% of 500)
        resource_warnings = [w for w in warnings if w.resource_type == 'Stack Resources']
        assert len(resource_warnings) > 0
        assert resource_warnings[0].severity == 'warning'
    
    @given(count=st.integers(min_value=500, max_value=600))
    @settings(max_examples=20)
    def test_error_generated_at_100_percent_threshold(self, count: int):
        """
        Requirement 5.2: Error generated when exceeding 500 resource limit.
        """
        # Generate template with resources exceeding limit
        resources = {}
        for i in range(count):
            resources[f'Resource{i}'] = {
                'Type': 'AWS::S3::Bucket',
                'Properties': {}
            }
        
        template = {'Resources': resources}
        
        warnings = self.checker.check_stack_limits(template, 'TestStack')
        
        # Should have error if count >= 500
        resource_warnings = [w for w in warnings if w.resource_type == 'Stack Resources']
        assert len(resource_warnings) > 0
        assert resource_warnings[0].severity == 'error'
    
    def test_limit_prone_resources_flagged(self):
        """
        Requirement 5.3: Limit-prone resources are identified.
        """
        # Create template with many IAM roles (limit-prone)
        resources = {}
        for i in range(15):
            resources[f'Role{i}'] = {
                'Type': 'AWS::IAM::Role',
                'Properties': {}
            }
        
        templates = {'TestStack': {'Resources': resources}}
        
        result = self.checker.check_limits(templates)
        
        # Should have warning about IAM roles
        iam_warnings = [w for w in result.warnings if 'IAM::Role' in w.resource_type]
        assert len(iam_warnings) > 0
    
    def test_multiple_stacks_aggregated(self):
        """
        Requirement 5.1: Resources are counted across all templates.
        """
        templates = {
            'Stack1': {
                'Resources': {
                    'Bucket1': {'Type': 'AWS::S3::Bucket'},
                    'Bucket2': {'Type': 'AWS::S3::Bucket'}
                }
            },
            'Stack2': {
                'Resources': {
                    'Bucket3': {'Type': 'AWS::S3::Bucket'},
                    'Function1': {'Type': 'AWS::Lambda::Function'}
                }
            }
        }
        
        result = self.checker.check_limits(templates)
        
        assert result.total_resources == 4
        assert result.resources_by_type.get('AWS::S3::Bucket', 0) == 3
        assert result.resources_by_type.get('AWS::Lambda::Function', 0) == 1
        assert result.resources_by_stack.get('Stack1', 0) == 2
        assert result.resources_by_stack.get('Stack2', 0) == 2
    
    def test_no_warning_below_threshold(self):
        """Resources below threshold should not generate warnings."""
        resources = {}
        for i in range(100):  # Well below 400 (80% of 500)
            resources[f'Resource{i}'] = {
                'Type': 'AWS::S3::Bucket',
                'Properties': {}
            }
        
        template = {'Resources': resources}
        
        warnings = self.checker.check_stack_limits(template, 'TestStack')
        
        # Should have no resource count warnings
        resource_warnings = [w for w in warnings if w.resource_type == 'Stack Resources']
        assert len(resource_warnings) == 0
    
    def test_output_limit_warning(self):
        """Output limit warnings should be generated."""
        outputs = {}
        for i in range(170):  # Above 80% of 200
            outputs[f'Output{i}'] = {
                'Value': f'value{i}'
            }
        
        template = {
            'Resources': {'Bucket': {'Type': 'AWS::S3::Bucket'}},
            'Outputs': outputs
        }
        
        warnings = self.checker.check_stack_limits(template, 'TestStack')
        
        output_warnings = [w for w in warnings if w.resource_type == 'Stack Outputs']
        assert len(output_warnings) > 0
    
    def test_parameter_limit_warning(self):
        """Parameter limit warnings should be generated."""
        parameters = {}
        for i in range(170):  # Above 80% of 200
            parameters[f'Param{i}'] = {
                'Type': 'String',
                'Default': f'value{i}'
            }
        
        template = {
            'Parameters': parameters,
            'Resources': {'Bucket': {'Type': 'AWS::S3::Bucket'}}
        }
        
        warnings = self.checker.check_stack_limits(template, 'TestStack')
        
        param_warnings = [w for w in warnings if w.resource_type == 'Stack Parameters']
        assert len(param_warnings) > 0


class TestResourceCountingUnit:
    """Unit tests for resource counting."""
    
    def setup_method(self):
        self.checker = ResourceLimitChecker()
    
    def test_empty_template_returns_zero_counts(self):
        """Empty template should return zero counts."""
        template = {}
        
        counts = self.checker.count_resources(template)
        
        assert len(counts) == 0
    
    def test_template_with_no_resources_returns_zero(self):
        """Template with empty Resources section returns zero."""
        template = {'Resources': {}}
        
        counts = self.checker.count_resources(template)
        
        assert len(counts) == 0
    
    def test_mixed_resource_types_counted_separately(self):
        """Different resource types should be counted separately."""
        template = {
            'Resources': {
                'Bucket1': {'Type': 'AWS::S3::Bucket'},
                'Bucket2': {'Type': 'AWS::S3::Bucket'},
                'Function1': {'Type': 'AWS::Lambda::Function'},
                'Table1': {'Type': 'AWS::DynamoDB::Table'},
                'Table2': {'Type': 'AWS::DynamoDB::Table'},
                'Table3': {'Type': 'AWS::DynamoDB::Table'}
            }
        }
        
        counts = self.checker.count_resources(template)
        
        assert counts['AWS::S3::Bucket'] == 2
        assert counts['AWS::Lambda::Function'] == 1
        assert counts['AWS::DynamoDB::Table'] == 3
    
    def test_template_elements_counted(self):
        """All template elements should be counted."""
        template = {
            'Parameters': {'P1': {}, 'P2': {}},
            'Mappings': {'M1': {}},
            'Conditions': {'C1': {}, 'C2': {}, 'C3': {}},
            'Resources': {'R1': {'Type': 'AWS::S3::Bucket'}},
            'Outputs': {'O1': {}, 'O2': {}}
        }
        
        counts = self.checker.count_template_elements(template)
        
        assert counts['Parameters'] == 2
        assert counts['Mappings'] == 1
        assert counts['Conditions'] == 3
        assert counts['Resources'] == 1
        assert counts['Outputs'] == 2


class TestResourceLimitResult:
    """Tests for ResourceLimitResult."""
    
    def setup_method(self):
        self.checker = ResourceLimitChecker()
    
    def test_success_true_when_no_errors(self):
        """Result should be success when no errors."""
        templates = {
            'Stack1': {
                'Resources': {
                    'Bucket': {'Type': 'AWS::S3::Bucket'}
                }
            }
        }
        
        result = self.checker.check_limits(templates)
        
        assert result.success is True
    
    def test_success_false_when_errors(self):
        """Result should be failure when errors exist."""
        # Create template exceeding limit
        resources = {}
        for i in range(510):
            resources[f'Resource{i}'] = {'Type': 'AWS::S3::Bucket'}
        
        templates = {'Stack1': {'Resources': resources}}
        
        result = self.checker.check_limits(templates)
        
        assert result.success is False
    
    def test_to_dict_serialization(self):
        """Result should serialize to dictionary."""
        templates = {
            'Stack1': {
                'Resources': {
                    'Bucket': {'Type': 'AWS::S3::Bucket'}
                }
            }
        }
        
        result = self.checker.check_limits(templates)
        result_dict = result.to_dict()
        
        assert 'success' in result_dict
        assert 'total_resources' in result_dict
        assert 'resources_by_type' in result_dict
        assert 'resources_by_stack' in result_dict
        assert 'warnings' in result_dict
        assert 'issues' in result_dict
