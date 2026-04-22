#!/usr/bin/env python3
"""Test script for full ADFS authentication flow including role selection."""
import sys
import os

# Add the backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.aws_auth_service import AWSAuthService

# Test credentials
ADFS_URL = "adfs.devfactory.com/adfs/ls/idpinitiatedsignon"
USERNAME = r"devfactory\papubhattacharya"
PASSWORD = "Promodeagro@1977"
REGION = "us-east-1"

def test_full_adfs_flow():
    """Test the complete ADFS authentication flow."""
    
    print("=" * 60)
    print("ADFS Full Flow Test")
    print("=" * 60)
    
    # Step 1: Fetch roles
    print("\n[STEP 1] Fetching ADFS roles...")
    print(f"  URL: {ADFS_URL}")
    print(f"  Username: {USERNAME}")
    print(f"  Region: {REGION}")
    
    try:
        roles, session_id = AWSAuthService.fetch_adfs_roles(
            ADFS_URL, USERNAME, PASSWORD, REGION
        )
        print(f"\n[SUCCESS] Got {len(roles)} roles, session_id: {session_id}")
        
        for i, role in enumerate(roles):
            print(f"  [{i+1}] {role.role_name} ({role.account_id})")
            print(f"      ARN: {role.role_arn}")
        
    except Exception as e:
        print(f"\n[FAILED] fetch_adfs_roles error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 2: Select first role
    if roles:
        print("\n[STEP 2] Selecting first role...")
        selected_role = roles[0]
        print(f"  Role ARN: {selected_role.role_arn}")
        print(f"  Session ID: {session_id}")
        
        try:
            response = AWSAuthService.select_adfs_role(
                session_id, selected_role.role_arn, REGION
            )
            
            print(f"\n[RESULT] select_adfs_role response:")
            print(f"  valid: {response.valid}")
            print(f"  success: {getattr(response, 'success', None)}")
            print(f"  account_id: {response.account_id}")
            print(f"  error: {response.error}")
            
            if response.valid and response.credentials:
                print(f"\n[SUCCESS] Got AWS credentials!")
                print(f"  Access Key ID: {response.credentials.get('access_key_id', '')[:10]}...")
            else:
                print(f"\n[FAILED] No credentials returned")
                if response.troubleshooting:
                    print("  Troubleshooting:")
                    for tip in response.troubleshooting:
                        print(f"    - {tip}")
                        
        except Exception as e:
            print(f"\n[FAILED] select_adfs_role error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Test complete")
    print("=" * 60)


if __name__ == "__main__":
    test_full_adfs_flow()
