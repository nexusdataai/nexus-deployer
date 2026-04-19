"""
Diagnostic script to identify deployment failures
"""
import boto3
import sys
from datetime import datetime, timedelta

def diagnose_stack_failure(stack_name, region='us-east-1'):
    """
    Diagnose why a CloudFormation stack failed
    
    Args:
        stack_name: Name of the failed stack
        region: AWS region (default: us-east-1 for frontend-global)
    """
    print(f"\n{'='*80}")
    print(f"Diagnosing Stack Failure: {stack_name}")
    print(f"Region: {region}")
    print(f"{'='*80}\n")
    
    try:
        cfn = boto3.client('cloudformation', region_name=region)
        
        # Get stack status
        print("1. Checking stack status...")
        try:
            response = cfn.describe_stacks(StackName=stack_name)
            stack = response['Stacks'][0]
            status = stack.get('StackStatus')
            status_reason = stack.get('StackStatusReason', 'N/A')
            
            print(f"   Status: {status}")
            print(f"   Reason: {status_reason}")
        except Exception as e:
            print(f"   ❌ Could not get stack status: {str(e)}")
            return
        
        # Get stack events (last 50)
        print("\n2. Analyzing stack events (last 50)...")
        try:
            response = cfn.describe_stack_events(StackName=stack_name)
            events = response.get('StackEvents', [])[:50]
            
            failed_events = []
            cancelled_events = []
            
            for event in events:
                resource_status = event.get('ResourceStatus', '')
                resource_type = event.get('ResourceType', '')
                logical_id = event.get('LogicalResourceId', '')
                reason = event.get('ResourceStatusReason', '')
                timestamp = event.get('Timestamp')
                
                if 'FAILED' in resource_status:
                    failed_events.append({
                        'resource': logical_id,
                        'type': resource_type,
                        'status': resource_status,
                        'reason': reason,
                        'time': timestamp
                    })
                elif 'cancelled' in reason.lower():
                    cancelled_events.append({
                        'resource': logical_id,
                        'type': resource_type,
                        'status': resource_status,
                        'reason': reason,
                        'time': timestamp
                    })
            
            if failed_events:
                print(f"\n   ❌ Found {len(failed_events)} FAILED resources:")
                for event in failed_events:
                    print(f"\n   Resource: {event['resource']}")
                    print(f"   Type: {event['type']}")
                    print(f"   Status: {event['status']}")
                    print(f"   Reason: {event['reason']}")
                    print(f"   Time: {event['time']}")
            
            if cancelled_events:
                print(f"\n   ⚠ Found {len(cancelled_events)} CANCELLED resources:")
                for event in cancelled_events:
                    print(f"\n   Resource: {event['resource']}")
                    print(f"   Type: {event['type']}")
                    print(f"   Status: {event['status']}")
                    print(f"   Reason: {event['reason']}")
                    print(f"   Time: {event['time']}")
            
            if not failed_events and not cancelled_events:
                print("   ✓ No failed or cancelled events found in last 50 events")
                print("\n   Recent events:")
                for event in events[:10]:
                    print(f"   - {event.get('LogicalResourceId')}: {event.get('ResourceStatus')} - {event.get('ResourceStatusReason', 'N/A')}")
                    
        except Exception as e:
            print(f"   ❌ Could not get stack events: {str(e)}")
        
        # Check for specific resource issues
        print("\n3. Checking for common issues...")
        
        # Check ACM certificates
        print("\n   a) Checking ACM certificates...")
        try:
            acm = boto3.client('acm', region_name=region)
            response = acm.list_certificates(CertificateStatuses=['PENDING_VALIDATION', 'FAILED'])
            certs = response.get('CertificateSummaryList', [])
            
            if certs:
                print(f"   Found {len(certs)} certificates in PENDING_VALIDATION or FAILED state:")
                for cert in certs:
                    cert_arn = cert.get('CertificateArn')
                    domain = cert.get('DomainName')
                    
                    # Get certificate details
                    cert_details = acm.describe_certificate(CertificateArn=cert_arn)
                    cert_info = cert_details.get('Certificate', {})
                    status = cert_info.get('Status')
                    
                    print(f"\n   Certificate: {domain}")
                    print(f"   ARN: {cert_arn}")
                    print(f"   Status: {status}")
                    
                    # Check validation options
                    validation_options = cert_info.get('DomainValidationOptions', [])
                    for option in validation_options:
                        print(f"\n   Validation for: {option.get('DomainName')}")
                        print(f"   Validation Status: {option.get('ValidationStatus')}")
                        
                        resource_record = option.get('ResourceRecord', {})
                        if resource_record:
                            print(f"   DNS Record Name: {resource_record.get('Name')}")
                            print(f"   DNS Record Type: {resource_record.get('Type')}")
                            print(f"   DNS Record Value: {resource_record.get('Value')}")
            else:
                print("   ✓ No pending or failed certificates found")
                
        except Exception as e:
            print(f"   ⚠ Could not check ACM certificates: {str(e)}")
        
        # Check Route53 hosted zones
        print("\n   b) Checking Route53 permissions...")
        try:
            route53 = boto3.client('route53')
            response = route53.list_hosted_zones()
            zones = response.get('HostedZones', [])
            print(f"   ✓ Can list hosted zones ({len(zones)} zones found)")
        except Exception as e:
            print(f"   ❌ Cannot list hosted zones: {str(e)}")
            print("   This might indicate insufficient Route53 permissions")
        
        # Check CloudWatch Logs
        print("\n   c) Checking CloudWatch Log Groups...")
        try:
            logs = boto3.client('logs', region_name=region)
            response = logs.describe_log_groups(logGroupNamePrefix='aws-waf-logs-')
            log_groups = response.get('logGroups', [])
            
            if log_groups:
                print(f"   Found {len(log_groups)} WAF log groups:")
                for lg in log_groups:
                    print(f"   - {lg.get('logGroupName')}")
            else:
                print("   ✓ No WAF log groups found")
                
        except Exception as e:
            print(f"   ⚠ Could not check log groups: {str(e)}")
        
        print(f"\n{'='*80}")
        print("Diagnosis complete")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"\n❌ Error during diagnosis: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python diagnose_deployment_failure.py <stack-name> [region]")
        print("Example: python diagnose_deployment_failure.py call-processing-prod-frontend-global us-east-1")
        sys.exit(1)
    
    stack_name = sys.argv[1]
    region = sys.argv[2] if len(sys.argv) > 2 else 'us-east-1'
    
    diagnose_stack_failure(stack_name, region)
