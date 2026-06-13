#!/usr/bin/env python3
"""Test script for pure Python ADFS authentication - matching aws-adfs library approach.

Credentials are read from environment variables; do not hard-code them. If
ADFS_TEST_USERNAME / ADFS_TEST_PASSWORD are unset, this script exits early.
"""
import os
import sys
import requests
import urllib3
import base64
import defusedxml.ElementTree as ET
import re

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Test credentials (env-driven; never commit real values)
ADFS_HOST = os.environ.get("ADFS_TEST_HOST", "adfs.example.com")
USERNAME = os.environ.get("ADFS_TEST_USERNAME", "")
PASSWORD = os.environ.get("ADFS_TEST_PASSWORD", "")  # pragma: allowlist secret

if not USERNAME or not PASSWORD:
    sys.stderr.write(
        "Set ADFS_TEST_USERNAME and ADFS_TEST_PASSWORD before running this script.\n"
    )
    sys.exit(2)

def test_adfs_auth():
    """Test ADFS authentication using the same approach as aws-adfs library."""
    
    print(f"Username: {USERNAME}")
    
    # Build the authentication URL (same format as aws-adfs library)
    provider_id = 'urn:amazon:webservices'
    auth_url = f'https://{ADFS_HOST}/adfs/ls/IdpInitiatedSignOn.aspx?loginToRp={provider_id}'
    
    print(f"\nStep 1: Auth URL: {auth_url}")
    
    # Create session
    session = requests.Session()
    ssl_verify = False
    
    # Headers similar to aws-adfs
    headers = {'Accept-Language': 'en'}
    
    # POST credentials directly (like aws-adfs library does)
    data = {
        'UserName': USERNAME,
        'Password': PASSWORD,
        'AuthMethod': 'FormsAuthentication'
    }
    
    print("\nStep 2: POSTing credentials directly...")
    try:
        response = session.post(
            auth_url,
            verify=ssl_verify,
            headers=headers,
            data=data,
            timeout=60
        )
        print(f"  Status: {response.status_code}")
        print(f"  Final URL: {response.url}")
    except requests.exceptions.RequestException as e:
        print(f"  ERROR: {str(e)}")
        return
    
    # Parse response using lxml (same as aws-adfs)
    print("\nStep 3: Parsing response with lxml...")
    try:
        import lxml.etree as LET
        html_response = LET.fromstring(response.text, LET.HTMLParser())
        
        # Look for SAMLResponse input
        saml_input = html_response.find('.//input[@name="SAMLResponse"]')
        if saml_input is not None:
            saml_assertion = saml_input.get('value')
            if saml_assertion:
                print(f"  Found SAML assertion! Length: {len(saml_assertion)}")
                
                # Parse roles
                print("\nStep 4: Parsing SAML roles...")
                saml_xml = base64.b64decode(saml_assertion)
                root = ET.fromstring(saml_xml)
                
                roles = []
                for attr in root.iter('{urn:oasis:names:tc:SAML:2.0:assertion}Attribute'):
                    if attr.get('Name') == 'https://aws.amazon.com/SAML/Attributes/Role':
                        for value in attr.iter('{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue'):
                            role_string = value.text
                            if role_string:
                                parts = role_string.split(',')
                                if len(parts) == 2:
                                    if 'saml-provider' in parts[0]:
                                        principal_arn = parts[0].strip()
                                        role_arn = parts[1].strip()
                                    else:
                                        role_arn = parts[0].strip()
                                        principal_arn = parts[1].strip()
                                    
                                    role_match = re.match(r'arn:aws:iam::(\d+):role/(.+)', role_arn)
                                    if role_match:
                                        account_id = role_match.group(1)
                                        role_name = role_match.group(2)
                                        roles.append({
                                            'role_arn': role_arn,
                                            'principal_arn': principal_arn,
                                            'account_id': account_id,
                                            'role_name': role_name
                                        })
                
                print(f"  Found {len(roles)} role(s):")
                for role in roles:
                    print(f"    - {role['role_name']} ({role['account_id']})")
                    print(f"      ARN: {role['role_arn']}")
                
                if roles:
                    print("\n✅ SUCCESS! ADFS authentication working!")
                return
        
        # Check if still on login page
        password_input = html_response.find('.//input[@name="Password"]')
        if password_input is not None:
            error_elem = html_response.find('.//*[@id="errorText"]')
            error_text = ""
            if error_elem is not None and error_elem.text:
                error_text = error_elem.text.strip()
            
            if error_text:
                print(f"  ERROR from ADFS: {error_text}")
            else:
                print("  ERROR: Still on login page - authentication failed")
            
            # Print some debug info
            print("\n  Debug: Looking for error elements...")
            for elem in html_response.iter():
                if elem.get('id') and 'error' in elem.get('id', '').lower():
                    print(f"    Found element id={elem.get('id')}: {elem.text}")
        else:
            print("  No SAML assertion and not on login page - unexpected response")
            
    except ImportError:
        print("  lxml not available, using BeautifulSoup...")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        saml_input = soup.find('input', {'name': 'SAMLResponse'})
        if saml_input and saml_input.get('value'):
            print(f"  Found SAML assertion! Length: {len(saml_input.get('value'))}")
        else:
            print("  No SAML assertion found")
            if soup.find('input', {'name': 'Password'}):
                print("  Still on login page - authentication failed")


if __name__ == "__main__":
    test_adfs_auth()
