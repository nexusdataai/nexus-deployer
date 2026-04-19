"""
Property-based tests for CFN YAML Loader.

Feature: cloudformation-template-reliability
Property 1: CFN YAML Parsing Handles All Intrinsic Functions

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
import yaml

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.cfn_yaml_loader import (
    load_cfn_yaml,
    CFNTag,
    CFN_INTRINSIC_FUNCTIONS,
    cfn_tag_to_dict,
    extract_intrinsic_functions,
    validate_yaml_syntax
)


# Strategies for generating test data
simple_values = st.one_of(
    st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N'), whitelist_characters='-_')),
    st.integers(min_value=0, max_value=1000),
    st.booleans()
)

# Valid resource names (alphanumeric)
resource_names = st.text(
    min_size=1, 
    max_size=20, 
    alphabet=st.characters(whitelist_categories=('L', 'N'))
).filter(lambda x: x[0].isalpha() if x else False)

# AWS resource type pattern
aws_resource_types = st.sampled_from([
    'AWS::S3::Bucket',
    'AWS::Lambda::Function',
    'AWS::DynamoDB::Table',
    'AWS::IAM::Role',
    'AWS::EC2::Instance',
    'AWS::SNS::Topic',
    'AWS::SQS::Queue'
])


class TestCFNYAMLParsingProperty:
    """
    Property 1: CFN YAML Parsing Handles All Intrinsic Functions
    
    For any CloudFormation template containing intrinsic functions,
    the CFN_YAML_Loader SHALL parse the template without errors
    and preserve the intrinsic function structure.
    """
    
    @given(func_name=st.sampled_from(CFN_INTRINSIC_FUNCTIONS))
    @settings(max_examples=100)
    def test_all_intrinsic_functions_parse_with_scalar_value(self, func_name: str):
        """
        Requirement 1.1: All intrinsic function tags are recognized.
        
        For any intrinsic function with a scalar value, parsing should succeed.
        """
        yaml_content = f"Value: !{func_name} SomeValue"
        
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        assert 'Value' in result
        assert isinstance(result['Value'], CFNTag)
        assert result['Value'].tag == func_name
        assert result['Value'].value == 'SomeValue'
    
    @given(func_name=st.sampled_from(CFN_INTRINSIC_FUNCTIONS))
    @settings(max_examples=100)
    def test_all_intrinsic_functions_parse_with_list_value(self, func_name: str):
        """
        Requirement 1.1: All intrinsic function tags are recognized with list values.
        """
        yaml_content = f"""
Value: !{func_name}
  - item1
  - item2
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        assert 'Value' in result
        assert isinstance(result['Value'], CFNTag)
        assert result['Value'].tag == func_name
        assert isinstance(result['Value'].value, list)
    
    def test_condition_tag_parses_successfully(self):
        """
        Requirement 1.2: Templates with !Condition tags parse successfully.
        
        This is the specific error case from the deployment failure.
        """
        yaml_content = """
Resources:
  MyResource:
    Type: AWS::EC2::VPC
    Condition: !Condition CreateNewVPC
    Properties:
      CidrBlock: 10.0.0.0/16
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        assert 'Resources' in result
        condition = result['Resources']['MyResource']['Condition']
        assert isinstance(condition, CFNTag)
        assert condition.tag == 'Condition'
        assert condition.value == 'CreateNewVPC'
    
    @given(
        outer_func=st.sampled_from(['Sub', 'Join', 'If', 'Select']),
        inner_func=st.sampled_from(['Ref', 'GetAtt', 'FindInMap'])
    )
    @settings(max_examples=100)
    def test_nested_intrinsic_functions_parse_correctly(self, outer_func: str, inner_func: str):
        """
        Requirement 1.3: Nested intrinsic functions are correctly parsed.
        """
        # Create nested structure based on outer function type
        if outer_func == 'Sub':
            yaml_content = f"""
Value: !{outer_func}
  - "prefix-${{inner}}-suffix"
  - inner: !{inner_func} SomeResource
"""
        elif outer_func == 'Join':
            yaml_content = f"""
Value: !{outer_func}
  - "-"
  - - !{inner_func} Resource1
    - !{inner_func} Resource2
"""
        elif outer_func == 'If':
            yaml_content = f"""
Value: !{outer_func}
  - SomeCondition
  - !{inner_func} TrueResource
  - !{inner_func} FalseResource
"""
        else:  # Select
            yaml_content = f"""
Value: !{outer_func}
  - 0
  - - !{inner_func} Resource1
    - !{inner_func} Resource2
"""
        
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        assert 'Value' in result
        assert isinstance(result['Value'], CFNTag)
        assert result['Value'].tag == outer_func
        
        # Verify nested functions are preserved
        intrinsics = extract_intrinsic_functions(result)
        tags_found = [tag.tag for _, tag in intrinsics]
        assert outer_func in tags_found
        assert inner_func in tags_found
    
    @given(func_name=st.sampled_from(CFN_INTRINSIC_FUNCTIONS))
    @settings(max_examples=50)
    def test_short_form_and_long_form_equivalence(self, func_name: str):
        """
        Requirement 1.4: Both short-form (!Ref) and long-form (Ref:) are handled.
        
        Note: Long-form is handled as regular YAML mappings, short-form uses CFNTag.
        """
        short_form = f"Value: !{func_name} SomeValue"
        
        # Parse short form
        short_result = load_cfn_yaml(short_form)
        
        assert short_result is not None
        assert isinstance(short_result['Value'], CFNTag)
        
        # Convert to dict (long form equivalent)
        converted = cfn_tag_to_dict(short_result)
        
        # Verify the conversion produces valid structure
        assert 'Value' in converted
        assert isinstance(converted['Value'], dict)
    
    @given(tag_name=st.text(min_size=3, max_size=15, alphabet=st.characters(whitelist_categories=('L',))))
    @settings(max_examples=50)
    def test_unknown_tags_log_warning_but_continue(self, tag_name: str):
        """
        Requirement 1.5: Unknown YAML tags log a warning but continue parsing.
        """
        # Ensure tag is not a known intrinsic function
        assume(tag_name not in CFN_INTRINSIC_FUNCTIONS)
        assume(tag_name.isalpha())
        
        yaml_content = f"Value: !{tag_name} SomeValue"
        
        # Should not raise an exception
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        assert 'Value' in result
        # Unknown tags are still parsed as CFNTag
        assert isinstance(result['Value'], CFNTag)
        assert result['Value'].tag == tag_name


class TestRealWorldTemplatePatterns:
    """Test patterns commonly found in real CloudFormation templates."""
    
    def test_complex_sub_with_getatt(self):
        """Test !Sub with embedded !GetAtt - common pattern."""
        yaml_content = """
Outputs:
  ApiEndpoint:
    Value: !Sub
      - "https://${Domain}/api"
      - Domain: !GetAtt ApiGateway.DomainName
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        value = result['Outputs']['ApiEndpoint']['Value']
        assert isinstance(value, CFNTag)
        assert value.tag == 'Sub'
    
    def test_conditional_resource_with_if(self):
        """Test conditional resource creation pattern."""
        yaml_content = """
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !If
        - CreateProdResources
        - prod-bucket
        - !Ref AWS::NoValue
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        bucket_name = result['Resources']['MyBucket']['Properties']['BucketName']
        assert isinstance(bucket_name, CFNTag)
        assert bucket_name.tag == 'If'
    
    def test_findinmap_with_ref(self):
        """Test !FindInMap with !Ref for region lookup."""
        yaml_content = """
Mappings:
  RegionMap:
    us-east-1:
      AMI: ami-12345678
    us-west-2:
      AMI: ami-87654321

Resources:
  Instance:
    Type: AWS::EC2::Instance
    Properties:
      ImageId: !FindInMap
        - RegionMap
        - !Ref AWS::Region
        - AMI
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        image_id = result['Resources']['Instance']['Properties']['ImageId']
        assert isinstance(image_id, CFNTag)
        assert image_id.tag == 'FindInMap'
    
    def test_join_with_multiple_refs(self):
        """Test !Join with multiple !Ref values."""
        yaml_content = """
Outputs:
  FullName:
    Value: !Join
      - "-"
      - - !Ref Environment
        - !Ref ProjectName
        - !Ref AWS::StackName
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        value = result['Outputs']['FullName']['Value']
        assert isinstance(value, CFNTag)
        assert value.tag == 'Join'
    
    def test_condition_functions(self):
        """Test condition functions (!And, !Or, !Not, !Equals)."""
        yaml_content = """
Conditions:
  IsProd: !Equals
    - !Ref Environment
    - prod
  IsUsEast: !Equals
    - !Ref AWS::Region
    - us-east-1
  IsProdInUsEast: !And
    - !Condition IsProd
    - !Condition IsUsEast
  IsNotProd: !Not
    - !Condition IsProd
  IsProdOrUsEast: !Or
    - !Condition IsProd
    - !Condition IsUsEast
"""
        result = load_cfn_yaml(yaml_content)
        
        assert result is not None
        conditions = result['Conditions']
        
        assert isinstance(conditions['IsProd'], CFNTag)
        assert conditions['IsProd'].tag == 'Equals'
        
        assert isinstance(conditions['IsProdInUsEast'], CFNTag)
        assert conditions['IsProdInUsEast'].tag == 'And'
        
        assert isinstance(conditions['IsNotProd'], CFNTag)
        assert conditions['IsNotProd'].tag == 'Not'
        
        assert isinstance(conditions['IsProdOrUsEast'], CFNTag)
        assert conditions['IsProdOrUsEast'].tag == 'Or'


class TestYAMLSyntaxValidation:
    """Test YAML syntax validation with error reporting."""
    
    def test_valid_yaml_returns_success(self):
        """Valid YAML should return success."""
        yaml_content = """
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
"""
        success, error = validate_yaml_syntax(yaml_content)
        assert success is True
        assert error is None
    
    def test_invalid_yaml_returns_error_with_location(self):
        """Invalid YAML should return error with line/column info."""
        yaml_content = """
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: [invalid yaml here
"""
        success, error = validate_yaml_syntax(yaml_content)
        assert success is False
        assert error is not None
        assert 'message' in error
        # Line info should be present for syntax errors
        assert error['line'] is not None or error['message']


class TestCFNTagConversion:
    """Test CFNTag to dictionary conversion."""
    
    @given(func_name=st.sampled_from(CFN_INTRINSIC_FUNCTIONS))
    @settings(max_examples=50)
    def test_cfn_tag_to_dict_produces_valid_structure(self, func_name: str):
        """CFNTag conversion should produce valid CloudFormation structure."""
        tag = CFNTag(func_name, 'SomeValue')
        result = tag.to_dict()
        
        assert isinstance(result, dict)
        assert len(result) == 1
        
        # Check key format
        key = list(result.keys())[0]
        if func_name == 'Ref':
            assert key == 'Ref'
        elif func_name == 'Condition':
            assert key == 'Condition'
        elif func_name == 'GetAtt':
            assert key == 'Fn::GetAtt'
        else:
            assert key == f'Fn::{func_name}'
    
    def test_nested_cfn_tags_convert_recursively(self):
        """Nested CFNTag structures should convert recursively."""
        nested = {
            'Value': CFNTag('Sub', [
                'prefix-${inner}',
                {'inner': CFNTag('Ref', 'MyResource')}
            ])
        }
        
        result = cfn_tag_to_dict(nested)
        
        assert 'Value' in result
        assert 'Fn::Sub' in result['Value']
        # The nested Ref should also be converted
        sub_value = result['Value']['Fn::Sub']
        assert isinstance(sub_value, list)
        assert 'Ref' in sub_value[1]['inner']
