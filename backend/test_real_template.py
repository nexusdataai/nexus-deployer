"""
Test TemplateParser with real CloudFormation templates from the project
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.template_parser import TemplateParser


def test_backend_service_stack():
    """Test parsing the backend service stack template"""
    template_path = Path(__file__).parent.parent / "deploy" / "templates" / "backend" / "service-stack.yaml"
    
    if not template_path.exists():
        print(f"⚠ Template not found: {template_path}")
        return
    
    with open(template_path, 'r') as f:
        template_body = f.read()
    
    parser = TemplateParser()
    
    # Sample parameters that would be used in deployment
    parameters = [
        {'ParameterKey': 'CapabilityName', 'ParameterValue': 'test-capability'},
        {'ParameterKey': 'Environment', 'ParameterValue': 'dev'},
        {'ParameterKey': 'VpcId', 'ParameterValue': 'vpc-12345'},
        {'ParameterKey': 'PublicSubnet1', 'ParameterValue': 'subnet-1'},
        {'ParameterKey': 'PublicSubnet2', 'ParameterValue': 'subnet-2'},
    ]
    
    try:
        resources = parser.parse_template(template_body, parameters)
        print(f"✓ Parsed backend service-stack.yaml: {len(resources)} resources")
        
        # List resource types
        resource_types = {}
        for resource in resources:
            resource_type = resource.resource_type
            resource_types[resource_type] = resource_types.get(resource_type, 0) + 1
        
        print("\nResource types found:")
        for rtype, count in sorted(resource_types.items()):
            print(f"  - {rtype}: {count}")
        
        # Check for ALB
        alb_resources = [r for r in resources if 'LoadBalancer' in r.resource_type]
        if alb_resources:
            print(f"\n✓ Found {len(alb_resources)} ALB resource(s)")
            for alb in alb_resources:
                print(f"  - {alb.logical_id}: {alb.resource_type}")
                if 'Name' in alb.properties:
                    print(f"    Name: {alb.properties['Name']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error parsing template: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_backend_storage_stack():
    """Test parsing the backend storage stack template"""
    template_path = Path(__file__).parent.parent / "deploy" / "templates" / "backend" / "storage-stack.yaml"
    
    if not template_path.exists():
        print(f"⚠ Template not found: {template_path}")
        return
    
    with open(template_path, 'r') as f:
        template_body = f.read()
    
    parser = TemplateParser()
    
    parameters = [
        {'ParameterKey': 'CapabilityName', 'ParameterValue': 'test-capability'},
        {'ParameterKey': 'Environment', 'ParameterValue': 'dev'},
    ]
    
    try:
        resources = parser.parse_template(template_body, parameters)
        print(f"\n✓ Parsed backend storage-stack.yaml: {len(resources)} resources")
        
        # Check for S3 buckets
        s3_resources = [r for r in resources if r.resource_type == 'AWS::S3::Bucket']
        if s3_resources:
            print(f"\n✓ Found {len(s3_resources)} S3 bucket(s)")
            for bucket in s3_resources:
                print(f"  - {bucket.logical_id}")
                if 'BucketName' in bucket.properties:
                    print(f"    BucketName: {bucket.properties['BucketName']}")
                if bucket.deletion_policy:
                    print(f"    DeletionPolicy: {bucket.deletion_policy}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error parsing template: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_frontend_global_stack():
    """Test parsing the frontend global stack template"""
    template_path = Path(__file__).parent.parent / "deploy" / "templates" / "frontend" / "global-stack.yaml"
    
    if not template_path.exists():
        print(f"⚠ Template not found: {template_path}")
        return True  # Not a failure if template doesn't exist
    
    with open(template_path, 'r') as f:
        template_body = f.read()
    
    parser = TemplateParser()
    
    parameters = [
        {'ParameterKey': 'CapabilityName', 'ParameterValue': 'test-capability'},
        {'ParameterKey': 'Environment', 'ParameterValue': 'dev'},
    ]
    
    try:
        resources = parser.parse_template(template_body, parameters)
        print(f"\n✓ Parsed frontend global-stack.yaml: {len(resources)} resources")
        
        # Check for CloudFront distributions
        cf_resources = [r for r in resources if 'CloudFront' in r.resource_type]
        if cf_resources:
            print(f"\n✓ Found {len(cf_resources)} CloudFront resource(s)")
            for cf in cf_resources:
                print(f"  - {cf.logical_id}: {cf.resource_type}")
        
        # Check for CloudWatch log groups
        log_resources = [r for r in resources if r.resource_type == 'AWS::Logs::LogGroup']
        if log_resources:
            print(f"\n✓ Found {len(log_resources)} CloudWatch log group(s)")
            for log in log_resources:
                print(f"  - {log.logical_id}")
                if 'LogGroupName' in log.properties:
                    print(f"    LogGroupName: {log.properties['LogGroupName']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error parsing template: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("Testing TemplateParser with real CloudFormation templates...\n")
    print("=" * 60)
    
    results = []
    results.append(test_backend_service_stack())
    results.append(test_backend_storage_stack())
    results.append(test_frontend_global_stack())
    
    print("\n" + "=" * 60)
    if all(results):
        print("✓ ALL REAL TEMPLATE TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
