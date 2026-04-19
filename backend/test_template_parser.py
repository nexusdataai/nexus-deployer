"""
Test script for TemplateParser
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.template_parser import TemplateParser


def test_basic_yaml_parsing():
    """Test basic YAML template parsing"""
    template = """
AWSTemplateFormatVersion: '2010-09-09'
Description: Test template

Parameters:
  BucketName:
    Type: String
    Default: my-test-bucket

Resources:
  MyBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Ref BucketName
      VersioningConfiguration:
        Status: Enabled
    DeletionPolicy: Retain
  
  MyLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /aws/test/logs
      RetentionInDays: 7
"""
    
    parser = TemplateParser()
    parameters = [
        {'ParameterKey': 'BucketName', 'ParameterValue': 'actual-bucket-name'}
    ]
    
    resources = parser.parse_template(template, parameters)
    
    print(f"✓ Parsed {len(resources)} resources")
    assert len(resources) == 2, f"Expected 2 resources, got {len(resources)}"
    
    # Check first resource
    bucket = resources[0]
    print(f"✓ Resource 1: {bucket.logical_id} ({bucket.resource_type})")
    assert bucket.logical_id == 'MyBucket'
    assert bucket.resource_type == 'AWS::S3::Bucket'
    assert bucket.deletion_policy == 'Retain'
    assert 'BucketName' in bucket.properties
    print(f"  - BucketName resolved to: {bucket.properties['BucketName']}")
    
    # Check second resource
    log_group = resources[1]
    print(f"✓ Resource 2: {log_group.logical_id} ({log_group.resource_type})")
    assert log_group.logical_id == 'MyLogGroup'
    assert log_group.resource_type == 'AWS::Logs::LogGroup'
    assert log_group.properties['LogGroupName'] == '/aws/test/logs'
    
    print("✓ Basic YAML parsing test passed!")


def test_json_parsing():
    """Test JSON template parsing"""
    template = """{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Resources": {
    "MyALB": {
      "Type": "AWS::ElasticLoadBalancingV2::LoadBalancer",
      "Properties": {
        "Name": "test-alb",
        "Type": "application"
      }
    }
  }
}"""
    
    parser = TemplateParser()
    resources = parser.parse_template(template)
    
    print(f"✓ Parsed {len(resources)} resources from JSON")
    assert len(resources) == 1
    
    alb = resources[0]
    print(f"✓ Resource: {alb.logical_id} ({alb.resource_type})")
    assert alb.resource_type == 'AWS::ElasticLoadBalancingV2::LoadBalancer'
    assert alb.properties['Name'] == 'test-alb'
    
    print("✓ JSON parsing test passed!")


def test_intrinsic_functions():
    """Test intrinsic function resolution"""
    template = """
Parameters:
  Environment:
    Type: String
    Default: dev
  CapabilityName:
    Type: String

Resources:
  MyDistribution:
    Type: AWS::CloudFront::Distribution
    Properties:
      DistributionConfig:
        Comment: !Sub '${CapabilityName}-${Environment}-distribution'
        Enabled: true
        Origins:
          - Id: !Join ['-', [!Ref CapabilityName, 'origin']]
            DomainName: example.com
"""
    
    parser = TemplateParser()
    parameters = [
        {'ParameterKey': 'Environment', 'ParameterValue': 'prod'},
        {'ParameterKey': 'CapabilityName', 'ParameterValue': 'my-app'}
    ]
    
    resources = parser.parse_template(template, parameters)
    
    print(f"✓ Parsed {len(resources)} resources with intrinsic functions")
    assert len(resources) == 1
    
    distribution = resources[0]
    print(f"✓ Resource: {distribution.logical_id} ({distribution.resource_type})")
    
    comment = distribution.properties['DistributionConfig']['Comment']
    print(f"  - Comment (Fn::Sub): {comment}")
    assert 'my-app' in comment
    assert 'prod' in comment
    
    origins = distribution.properties['DistributionConfig']['Origins']
    origin_id = origins[0]['Id']
    print(f"  - Origin ID (Fn::Join): {origin_id}")
    assert 'my-app' in origin_id
    
    print("✓ Intrinsic functions test passed!")


def test_error_handling():
    """Test error handling for invalid templates"""
    parser = TemplateParser()
    
    # Test invalid YAML/JSON
    try:
        parser.parse_template("invalid: yaml: content: [")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"✓ Correctly caught invalid template: {str(e)[:50]}...")
    
    # Test empty template
    resources = parser.parse_template("{}")
    assert len(resources) == 0
    print("✓ Empty template handled correctly")
    
    print("✓ Error handling test passed!")


def test_resolve_parameters():
    """Test parameter resolution utility"""
    parser = TemplateParser()
    
    # Test simple reference
    value = {'Ref': 'MyParam'}
    parameters = {'MyParam': 'resolved-value'}
    result = parser.resolve_parameters(value, parameters)
    print(f"✓ Resolved Ref: {result}")
    assert result == 'resolved-value'
    
    # Test Fn::Sub
    value = {'Fn::Sub': 'prefix-${Param1}-${Param2}'}
    parameters = {'Param1': 'foo', 'Param2': 'bar'}
    result = parser.resolve_parameters(value, parameters)
    print(f"✓ Resolved Fn::Sub: {result}")
    assert result == 'prefix-foo-bar'
    
    print("✓ Parameter resolution test passed!")


if __name__ == '__main__':
    print("Testing TemplateParser...\n")
    
    try:
        test_basic_yaml_parsing()
        print()
        test_json_parsing()
        print()
        test_intrinsic_functions()
        print()
        test_error_handling()
        print()
        test_resolve_parameters()
        print()
        print("=" * 50)
        print("✓ ALL TESTS PASSED!")
        print("=" * 50)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
