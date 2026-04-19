"""
Check for orphaned S3 buckets that might cause deployment failures
"""
import boto3
import sys
from typing import List, Dict

def check_orphaned_s3_buckets(capability_name: str, environment: str, region: str = 'us-east-1'):
    """
    Check for S3 buckets that exist but don't have a CloudFormation stack
    
    Args:
        capability_name: Name of the capability
        environment: Environment (dev, stage, prod)
        region: AWS region
    """
    print(f"\n{'='*80}")
    print(f"Checking for Orphaned S3 Buckets")
    print(f"Capability: {capability_name}")
    print(f"Environment: {environment}")
    print(f"Region: {region}")
    print(f"{'='*80}\n")
    
    # Sanitize capability name (same as CloudFormation does)
    sanitized_name = capability_name.lower().replace(' ', '-').replace('_', '-')
    sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
    if sanitized_name and not sanitized_name[0].isalnum():
        sanitized_name = 'cap-' + sanitized_name
    
    # Expected bucket name
    expected_bucket_name = f"{sanitized_name}-{environment}-frontend"
    
    print(f"Expected S3 bucket name: {expected_bucket_name}")
    print(f"Checking if bucket exists...\n")
    
    try:
        s3_client = boto3.client('s3', region_name=region)
        
        # Check if bucket exists
        try:
            s3_client.head_bucket(Bucket=expected_bucket_name)
            print(f"✓ Bucket EXISTS: {expected_bucket_name}")
            
            # Get bucket details
            try:
                response = s3_client.get_bucket_location(Bucket=expected_bucket_name)
                location = response.get('LocationConstraint', 'us-east-1')
                print(f"  Location: {location or 'us-east-1'}")
            except Exception as e:
                print(f"  Could not get location: {str(e)}")
            
            # Check if bucket has objects
            try:
                response = s3_client.list_objects_v2(Bucket=expected_bucket_name, MaxKeys=1)
                object_count = response.get('KeyCount', 0)
                if object_count > 0:
                    print(f"  ⚠ Bucket contains objects")
                else:
                    print(f"  ✓ Bucket is empty")
            except Exception as e:
                print(f"  Could not check objects: {str(e)}")
            
            # Check if bucket has versions
            try:
                response = s3_client.list_object_versions(Bucket=expected_bucket_name, MaxKeys=1)
                versions = response.get('Versions', [])
                delete_markers = response.get('DeleteMarkers', [])
                if versions or delete_markers:
                    print(f"  ⚠ Bucket has versions or delete markers")
                else:
                    print(f"  ✓ No versions or delete markers")
            except Exception as e:
                print(f"  Could not check versions: {str(e)}")
            
        except Exception as e:
            error_str = str(e).lower()
            if '404' in error_str or 'not found' in error_str:
                print(f"✓ Bucket DOES NOT EXIST: {expected_bucket_name}")
                print(f"  This is good - no orphaned bucket to clean up")
                return
            else:
                print(f"❌ Error checking bucket: {str(e)}")
                return
        
        # Check if CloudFormation stack exists
        print(f"\nChecking CloudFormation stack...")
        stack_name = f"{sanitized_name}-{environment}-frontend-global"
        print(f"Expected stack name: {stack_name}")
        
        cfn_client = boto3.client('cloudformation', region_name=region)
        
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            stacks = response.get('Stacks', [])
            if stacks:
                status = stacks[0].get('StackStatus')
                print(f"✓ Stack EXISTS: {stack_name}")
                print(f"  Status: {status}")
                print(f"\n⚠ CONCLUSION: Bucket exists AND stack exists")
                print(f"  This is normal - bucket is managed by the stack")
            else:
                print(f"❌ Stack DOES NOT EXIST: {stack_name}")
                print(f"\n⚠ CONCLUSION: ORPHANED BUCKET DETECTED!")
                print(f"  Bucket exists but stack does not")
                print(f"  This will cause deployment failures")
                print(f"\n  To fix, run:")
                print(f"  aws s3 rb s3://{expected_bucket_name} --force")
        except Exception as e:
            error_str = str(e).lower()
            if 'does not exist' in error_str or 'validationerror' in error_str:
                print(f"❌ Stack DOES NOT EXIST: {stack_name}")
                print(f"\n⚠ CONCLUSION: ORPHANED BUCKET DETECTED!")
                print(f"  Bucket exists but stack does not")
                print(f"  This will cause deployment failures")
                print(f"\n  To fix, run:")
                print(f"  aws s3 rb s3://{expected_bucket_name} --force")
            else:
                print(f"❌ Error checking stack: {str(e)}")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*80}\n")


def list_all_s3_buckets_for_capability(capability_name: str):
    """
    List all S3 buckets that might be related to a capability
    
    Args:
        capability_name: Name of the capability
    """
    print(f"\n{'='*80}")
    print(f"Listing All S3 Buckets for Capability: {capability_name}")
    print(f"{'='*80}\n")
    
    # Sanitize capability name
    sanitized_name = capability_name.lower().replace(' ', '-').replace('_', '-')
    sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
    
    try:
        s3_client = boto3.client('s3')
        
        # List all buckets
        response = s3_client.list_buckets()
        buckets = response.get('Buckets', [])
        
        # Filter buckets that match the capability name
        matching_buckets = []
        for bucket in buckets:
            bucket_name = bucket.get('Name', '')
            if sanitized_name in bucket_name:
                matching_buckets.append(bucket)
        
        if matching_buckets:
            print(f"Found {len(matching_buckets)} buckets matching '{sanitized_name}':\n")
            for bucket in matching_buckets:
                bucket_name = bucket.get('Name')
                creation_date = bucket.get('CreationDate')
                print(f"  - {bucket_name}")
                print(f"    Created: {creation_date}")
                
                # Check if bucket is empty
                try:
                    response = s3_client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
                    object_count = response.get('KeyCount', 0)
                    if object_count > 0:
                        print(f"    Status: Contains objects")
                    else:
                        print(f"    Status: Empty")
                except Exception as e:
                    print(f"    Status: Could not check")
                print()
        else:
            print(f"No buckets found matching '{sanitized_name}'")
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print(f"{'='*80}\n")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Check specific bucket:")
        print("    python check_orphaned_s3_buckets.py <capability-name> <environment> [region]")
        print("  List all buckets for capability:")
        print("    python check_orphaned_s3_buckets.py --list <capability-name>")
        print()
        print("Examples:")
        print("  python check_orphaned_s3_buckets.py 'Call Processing' prod us-east-1")
        print("  python check_orphaned_s3_buckets.py call-processing dev")
        print("  python check_orphaned_s3_buckets.py --list 'Call Processing'")
        sys.exit(1)
    
    if sys.argv[1] == '--list':
        if len(sys.argv) < 3:
            print("Error: Capability name required")
            sys.exit(1)
        capability_name = sys.argv[2]
        list_all_s3_buckets_for_capability(capability_name)
    else:
        capability_name = sys.argv[1]
        environment = sys.argv[2] if len(sys.argv) > 2 else 'dev'
        region = sys.argv[3] if len(sys.argv) > 3 else 'us-east-1'
        
        check_orphaned_s3_buckets(capability_name, environment, region)
