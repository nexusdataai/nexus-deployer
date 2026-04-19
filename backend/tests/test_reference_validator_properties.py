"""
Property Tests for Reference Validator
Tests validation of CloudFormation references to eliminate false positives.

Feature: deployment-prerequisites-verification
Requirements: 4.1, 4.2, 4.3, 4.4
"""
import pytest
from hypothesis import given, strategies as st, assume, settings

from app.services.reference_validator import (
    ReferenceValidator,
    ReferenceIssue,
    ReferenceValidationResult,
    PSEUDO_PARAMETERS
)
from app.utils.cfn_yaml_loader import CFNTag


# Strategy for valid CloudFormation logical IDs
logical_id_strategy = st.from_regex(r'^[A-Za-z][A-Za-z0-9]{0,19}$', fullmatch=True)


class TestResourceReferenceValidation:
    """Property 5: Resource Reference Validation - No False Positives (Requirements 4.1, 4.4)"""
    
    @given(
        resource_id=logical_id_strategy,
        other_resources=st.lists(logical_id_strategy, min_size=0, max_size=5, unique=True)
    )
    @settings(max_examples=50)
    def test_ref_to_defined_resource_is_valid(self, resource_id, other_resources):
        """Property: !Ref to a defined resource is always valid (no false positive)."""
        all_resources = set(other_resources) | {resource_id}
        
        validator = ReferenceValidator()
        is_valid, issue = validator.validate_ref(
            resource_id,
            defined_parameters=set(),
            defined_resources=all_resources,
            location="Resources.TestResource.Properties.Ref"
        )
        
        assert is_valid is True, f"!Ref to resource {resource_id} should be valid"
        assert issue is None
    
    @given(
        resource_id=logical_id_strategy,
        defined_resources=st.lists(logical_id_strategy, min_size=1, max_size=5, unique=True)
    )
    @settings(max_examples=50)
    def test_ref_to_undefined_resource_is_invalid(self, resource_id, defined_resources):
        """Property: !Ref to undefined target is invalid."""
        assume(resource_id not in defined_resources)
        assume(resource_id not in PSEUDO_PARAMETERS)
        
        validator = ReferenceValidator()
        is_valid, issue = validator.validate_ref(
            resource_id,
            defined_parameters=set(),
            defined_resources=set(defined_resources),
            location="Resources.TestResource"
        )
        
        assert is_valid is False
        assert issue is not None
        assert issue.target == resource_id
    
    def test_common_resource_refs_are_valid(self):
        """Common resource references like VPC, Subnet should be valid."""
        validator = ReferenceValidator()
        
        # These are the exact resources that were causing false positives
        resources = {
            'VPC', 'PublicSubnet1', 'PublicSubnet2', 'PrivateSubnet1', 'PrivateSubnet2',
            'ALBSecurityGroup', 'ECSSecurityGroup', 'InternetGateway', 'NATGateway',
            'PublicRouteTable', 'PrivateRouteTable', 'ECSCluster', 'TaskDefinition',
            'ECSService', 'ApplicationLoadBalancer', 'TargetGroup', 'Listener'
        }
        
        for resource_id in resources:
            is_valid, issue = validator.validate_ref(
                resource_id,
                defined_parameters=set(),
                defined_resources=resources,
                location=f"Resources.SomeResource.Properties.{resource_id}Ref"
            )
            
            assert is_valid is True, f"!Ref to {resource_id} should be valid"
            assert issue is None


class TestParameterReferenceValidation:
    """Property 6: Parameter Reference Validation (Requirement 4.2)"""
    
    @given(
        param_name=logical_id_strategy,
        other_params=st.lists(logical_id_strategy, min_size=0, max_size=5, unique=True)
    )
    @settings(max_examples=50)
    def test_ref_to_defined_parameter_is_valid(self, param_name, other_params):
        """Property: !Ref to a defined parameter is always valid."""
        all_params = set(other_params) | {param_name}
        
        validator = ReferenceValidator()
        is_valid, issue = validator.validate_ref(
            param_name,
            defined_parameters=all_params,
            defined_resources=set(),
            location="Resources.TestResource.Properties.ParamRef"
        )
        
        assert is_valid is True
        assert issue is None
    
    @given(
        param_name=logical_id_strategy,
        defined_params=st.lists(logical_id_strategy, min_size=1, max_size=5, unique=True)
    )
    @settings(max_examples=50)
    def test_ref_to_undefined_parameter_is_invalid(self, param_name, defined_params):
        """Property: !Ref to undefined parameter (not resource or pseudo) is invalid."""
        assume(param_name not in defined_params)
        assume(param_name not in PSEUDO_PARAMETERS)
        
        validator = ReferenceValidator()
        is_valid, issue = validator.validate_ref(
            param_name,
            defined_parameters=set(defined_params),
            defined_resources=set(),
            location="Resources.TestResource"
        )
        
        assert is_valid is False
        assert issue is not None


class TestPseudoParameterRecognition:
    """Property 7: Pseudo-Parameter Recognition (Requirement 4.2)"""
    
    @pytest.mark.parametrize("pseudo_param", list(PSEUDO_PARAMETERS))
    def test_all_pseudo_parameters_are_recognized(self, pseudo_param):
        """All AWS pseudo-parameters are recognized as valid."""
        validator = ReferenceValidator()
        
        assert validator.is_pseudo_parameter(pseudo_param) is True
        
        is_valid, issue = validator.validate_ref(
            pseudo_param,
            defined_parameters=set(),
            defined_resources=set(),
            location="Resources.TestResource"
        )
        
        assert is_valid is True
        assert issue is None
    
    @given(name=logical_id_strategy)
    @settings(max_examples=30)
    def test_non_pseudo_parameters_not_recognized(self, name):
        """Non-pseudo-parameters are not recognized as pseudo."""
        assume(name not in PSEUDO_PARAMETERS)
        
        validator = ReferenceValidator()
        assert validator.is_pseudo_parameter(name) is False
    
    def test_pseudo_parameters_complete_list(self):
        """Verify all CloudFormation pseudo-parameters are included."""
        expected = {
            'AWS::AccountId',
            'AWS::NotificationARNs',
            'AWS::NoValue',
            'AWS::Partition',
            'AWS::Region',
            'AWS::StackId',
            'AWS::StackName',
            'AWS::URLSuffix',
        }
        
        assert PSEUDO_PARAMETERS == expected


class TestGetAttValidation:
    """Tests for !GetAtt reference validation."""
    
    @given(
        resource_id=logical_id_strategy,
        attribute=st.sampled_from(['Arn', 'Id', 'Name', 'DomainName', 'Endpoint'])
    )
    @settings(max_examples=30)
    def test_getatt_to_defined_resource_is_valid(self, resource_id, attribute):
        """Property: !GetAtt to defined resource is valid."""
        validator = ReferenceValidator()
        
        # Test list format
        is_valid, issue = validator.validate_getatt(
            [resource_id, attribute],
            defined_resources={resource_id},
            location="Resources.Test"
        )
        assert is_valid is True
        
        # Test string format
        is_valid, issue = validator.validate_getatt(
            f"{resource_id}.{attribute}",
            defined_resources={resource_id},
            location="Resources.Test"
        )
        assert is_valid is True
    
    @given(
        resource_id=logical_id_strategy,
        defined_resources=st.lists(logical_id_strategy, min_size=1, max_size=5, unique=True)
    )
    @settings(max_examples=30)
    def test_getatt_to_undefined_resource_is_invalid(self, resource_id, defined_resources):
        """Property: !GetAtt to undefined resource is invalid."""
        assume(resource_id not in defined_resources)
        
        validator = ReferenceValidator()
        is_valid, issue = validator.validate_getatt(
            [resource_id, 'Arn'],
            defined_resources=set(defined_resources),
            location="Resources.Test"
        )
        
        assert is_valid is False
        assert issue is not None
        assert resource_id in issue.target


class TestFullTemplateValidation:
    """Tests for complete template reference validation."""
    
    def test_template_with_valid_resource_refs_no_false_positives(self):
        """Template with valid resource refs should have no false positives."""
        validator = ReferenceValidator()
        
        # Simulate a template with resources referencing each other
        template = {
            'Parameters': {
                'Environment': {'Type': 'String'}
            },
            'Resources': {
                'VPC': {'Type': 'AWS::EC2::VPC'},
                'PublicSubnet1': {
                    'Type': 'AWS::EC2::Subnet',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC')
                    }
                },
                'SecurityGroup': {
                    'Type': 'AWS::EC2::SecurityGroup',
                    'Properties': {
                        'VpcId': CFNTag('Ref', 'VPC'),
                        'GroupDescription': CFNTag('Sub', '${Environment}-sg')
                    }
                }
            }
        }
        
        result = validator.validate_all_references(template)
        
        assert result.success is True
        assert len(result.invalid_refs) == 0
        assert 'VPC' in result.valid_resource_refs
    
    def test_template_with_pseudo_parameters(self):
        """Template using pseudo-parameters should be valid."""
        validator = ReferenceValidator()
        
        template = {
            'Resources': {
                'Bucket': {
                    'Type': 'AWS::S3::Bucket',
                    'Properties': {
                        'BucketName': CFNTag('Sub', '${AWS::StackName}-${AWS::Region}-bucket')
                    }
                }
            }
        }
        
        result = validator.validate_all_references(template)
        
        assert result.success is True
        assert 'AWS::StackName' in result.valid_pseudo_refs or len(result.invalid_refs) == 0
    
    def test_filter_false_positives_from_existing_warnings(self):
        """Filter false positives from existing validator warnings."""
        validator = ReferenceValidator()
        
        # Simulate warnings from template_validator.py
        undefined_params = [
            "Resources.PublicSubnet1.Properties.VpcId.Ref: VPC",
            "Resources.SecurityGroup.Properties.VpcId.Ref: VPC",
            "Resources.ECSService.Properties.Cluster.Ref: ECSCluster",
            "Resources.TaskDef.Properties.ExecutionRoleArn.Ref: UndefinedRole"
        ]
        
        template = {
            'Resources': {
                'VPC': {'Type': 'AWS::EC2::VPC'},
                'ECSCluster': {'Type': 'AWS::ECS::Cluster'},
                'PublicSubnet1': {'Type': 'AWS::EC2::Subnet'},
                'SecurityGroup': {'Type': 'AWS::EC2::SecurityGroup'},
                'ECSService': {'Type': 'AWS::ECS::Service'},
                'TaskDef': {'Type': 'AWS::ECS::TaskDefinition'}
            }
        }
        
        truly_undefined, valid_refs = validator.filter_false_positives(
            undefined_params, template
        )
        
        # VPC and ECSCluster refs should be filtered out (valid resource refs)
        assert 'VPC' in valid_refs
        assert 'ECSCluster' in valid_refs
        
        # UndefinedRole should remain as truly undefined
        assert len(truly_undefined) == 1
        assert 'UndefinedRole' in truly_undefined[0]


class TestExtraction:
    """Tests for resource/parameter extraction."""
    
    def test_extract_resources(self):
        """Extract all resource logical IDs from template."""
        validator = ReferenceValidator()
        
        template = {
            'Resources': {
                'VPC': {'Type': 'AWS::EC2::VPC'},
                'Subnet': {'Type': 'AWS::EC2::Subnet'},
                'SecurityGroup': {'Type': 'AWS::EC2::SecurityGroup'}
            }
        }
        
        resources = validator.extract_resources(template)
        
        assert resources == {'VPC', 'Subnet', 'SecurityGroup'}
    
    def test_extract_parameters(self):
        """Extract all parameter names from template."""
        validator = ReferenceValidator()
        
        template = {
            'Parameters': {
                'Environment': {'Type': 'String'},
                'InstanceType': {'Type': 'String'},
                'VpcCidr': {'Type': 'String'}
            }
        }
        
        parameters = validator.extract_parameters(template)
        
        assert parameters == {'Environment', 'InstanceType', 'VpcCidr'}
    
    def test_extract_from_empty_template(self):
        """Extraction from empty template returns empty sets."""
        validator = ReferenceValidator()
        
        assert validator.extract_resources({}) == set()
        assert validator.extract_parameters({}) == set()
        assert validator.extract_conditions({}) == set()
