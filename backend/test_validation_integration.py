"""
Integration test for pre-deployment validation system
Tests the complete validation workflow without actual AWS calls
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.pre_deployment_validator import PreDeploymentValidator
from app.services.resource_cleanup_registry import ResourceCleanupRegistry
from app.services.cleaners.s3_bucket_cleaner import S3BucketCleaner
from app.services.cleaners.alb_cleaner import ALBCleaner
from app.services.cleaners.cloudfront_cleaner import CloudFrontCleaner
from app.services.cleaners.ecr_repository_cleaner import ECRRepositoryCleaner
from app.services.cleaners.cloudwatch_log_group_cleaner import CloudWatchLogGroupCleaner
from app.utils.name_sanitizer import sanitize_capability_name
from app.models.validation import ResourceDefinition, OrphanedResource, StackStatus


def test_validator_initialization():
    """Test that validator initializes correctly"""
    print("Testing validator initialization...")
    
    validator = PreDeploymentValidator()
    
    # Check that cleaners are registered
    supported_types = validator.cleanup_registry.get_supported_resource_types()
    print(f"✓ Validator initialized with {len(supported_types)} resource cleaners")
    
    expected_types = [
        'AWS::S3::Bucket',
        'AWS::ElasticLoadBalancingV2::LoadBalancer',
        'AWS::CloudFront::Distribution',
        'AWS::ECR::Repository',
        'AWS::Logs::LogGroup'
    ]
    
    for expected_type in expected_types:
        assert expected_type in supported_types, f"Missing cleaner for {expected_type}"
        print(f"  ✓ {expected_type} cleaner registered")
    
    print("✓ Validator initialization test passed!\n")


def test_name_sanitization():
    """Test capability name sanitization"""
    print("Testing name sanitization...")
    
    test_cases = [
        ("My Test Capability", "AWS::S3::Bucket", "my-test-capability"),
        ("Test_Capability", "AWS::S3::Bucket", "test-capability"),
        ("TEST-CAPABILITY", "AWS::S3::Bucket", "test-capability"),
        ("My  Multiple   Spaces", "AWS::S3::Bucket", "my-multiple-spaces"),
        ("Special!@#$Chars", "AWS::S3::Bucket", "specialchars"),
    ]
    
    for input_name, resource_type, expected in test_cases:
        result = sanitize_capability_name(input_name, resource_type)
        assert result == expected, f"Expected {expected}, got {result}"
        print(f"  ✓ '{input_name}' -> '{result}'")
    
    print("✓ Name sanitization test passed!\n")


def test_cleanup_ordering():
    """Test dependency-aware cleanup ordering"""
    print("Testing cleanup ordering...")
    
    from datetime import datetime
    
    # Create orphaned resources in random order
    resources = [
        OrphanedResource(
            resource_type='AWS::Logs::LogGroup',
            resource_identifier='log-group-1',
            region='us-east-1',
            stack_name='test-stack',
            detected_at=datetime.now()
        ),
        OrphanedResource(
            resource_type='AWS::CloudFront::Distribution',
            resource_identifier='dist-1',
            region='us-east-1',
            stack_name='test-stack',
            detected_at=datetime.now()
        ),
        OrphanedResource(
            resource_type='AWS::S3::Bucket',
            resource_identifier='bucket-1',
            region='us-east-1',
            stack_name='test-stack',
            detected_at=datetime.now()
        ),
        OrphanedResource(
            resource_type='AWS::ElasticLoadBalancingV2::LoadBalancer',
            resource_identifier='alb-1',
            region='us-east-1',
            stack_name='test-stack',
            detected_at=datetime.now()
        ),
    ]
    
    registry = ResourceCleanupRegistry()
    sorted_resources = registry.get_cleanup_order(resources)
    
    # Verify order: CloudFront -> ALB -> S3 -> Logs
    expected_order = [
        'AWS::CloudFront::Distribution',
        'AWS::ElasticLoadBalancingV2::LoadBalancer',
        'AWS::S3::Bucket',
        'AWS::Logs::LogGroup'
    ]
    
    actual_order = [r.resource_type for r in sorted_resources]
    
    print(f"  Original order: {[r.resource_type.split('::')[-1] for r in resources]}")
    print(f"  Sorted order:   {[r.resource_type.split('::')[-1] for r in sorted_resources]}")
    
    assert actual_order == expected_order, f"Order mismatch: {actual_order}"
    print("✓ Cleanup ordering test passed!\n")


def test_resource_definition_extraction():
    """Test extracting resource names from definitions"""
    print("Testing resource definition extraction...")
    
    # Test S3 bucket name extraction
    s3_cleaner = S3BucketCleaner()
    s3_def = ResourceDefinition(
        logical_id='MyBucket',
        resource_type='AWS::S3::Bucket',
        properties={'BucketName': 'my-test-bucket'},
        deletion_policy='Retain'
    )
    
    bucket_name = s3_cleaner.get_name(s3_def, {})
    assert bucket_name == 'my-test-bucket', f"Expected 'my-test-bucket', got '{bucket_name}'"
    print(f"  ✓ S3 bucket name extracted: {bucket_name}")
    
    # Test ALB name extraction
    alb_cleaner = ALBCleaner()
    alb_def = ResourceDefinition(
        logical_id='MyALB',
        resource_type='AWS::ElasticLoadBalancingV2::LoadBalancer',
        properties={'Name': 'my-test-alb'},
        deletion_policy=None
    )
    
    alb_name = alb_cleaner.get_name(alb_def, {})
    assert alb_name == 'my-test-alb', f"Expected 'my-test-alb', got '{alb_name}'"
    print(f"  ✓ ALB name extracted: {alb_name}")
    
    # Test log group name extraction
    log_cleaner = CloudWatchLogGroupCleaner()
    log_def = ResourceDefinition(
        logical_id='MyLogGroup',
        resource_type='AWS::Logs::LogGroup',
        properties={'LogGroupName': '/aws/test/logs'},
        deletion_policy=None
    )
    
    log_name = log_cleaner.get_name(log_def, {})
    assert log_name == '/aws/test/logs', f"Expected '/aws/test/logs', got '{log_name}'"
    print(f"  ✓ Log group name extracted: {log_name}")
    
    print("✓ Resource definition extraction test passed!\n")


def test_stack_status_enum():
    """Test stack status enum values"""
    print("Testing stack status enum...")
    
    assert StackStatus.NOT_EXISTS == "not_exists"
    assert StackStatus.STABLE == "stable"
    assert StackStatus.UNSTABLE == "unstable"
    assert StackStatus.IN_PROGRESS == "in_progress"
    
    print("  ✓ All stack status values correct")
    print("✓ Stack status enum test passed!\n")


if __name__ == '__main__':
    print("=" * 60)
    print("Pre-Deployment Validation Integration Tests")
    print("=" * 60)
    print()
    
    try:
        test_validator_initialization()
        test_name_sanitization()
        test_cleanup_ordering()
        test_resource_definition_extraction()
        test_stack_status_enum()
        
        print("=" * 60)
        print("✓ ALL INTEGRATION TESTS PASSED!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
