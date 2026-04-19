#!/usr/bin/env python3
"""
AWS ADFS Login Script (Python)
Uses the same authentication logic as the deployment wizard
"""
import os
import sys
import subprocess
import tempfile
import configparser
from pathlib import Path


def load_env_file(env_file='.env.local'):
    """Load environment variables from .env.local file."""
    env_vars = {}
    if not os.path.exists(env_file):
        print(f"ERROR: {env_file} not found")
        return None
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    
    return env_vars


def extract_adfs_host(adfs_url):
    """Extract ADFS host from URL."""
    adfs_host = adfs_url
    if adfs_url.startswith('http'):
        from urllib.parse import urlparse
        parsed = urlparse(adfs_url)
        adfs_host = parsed.netloc + parsed.path
    
    return adfs_host.rstrip('/')


def aws_adfs_login(adfs_host, username, password, region='us-east-1', profile='default', role_arn=None):
    """
    Authenticate with AWS using ADFS (same logic as wizard).
    
    Args:
        adfs_host: ADFS hostname with path
        username: ADFS username (domain\\username)
        password: ADFS password
        region: AWS region
        profile: AWS CLI profile name
        role_arn: Optional specific role ARN to use
        
    Returns:
        True if successful, False otherwise
    """
    print(f"Authenticating with ADFS...")
    print(f"  Host: {adfs_host}")
    print(f"  User: {username}")
    print(f"  Region: {region}")
    print(f"  Profile: {profile}")
    if role_arn:
        print(f"  Role: {role_arn}")
    print()
    
    # Get aws-adfs executable path
    # Try multiple locations for aws-adfs
    aws_adfs_exe = None
    
    # Location 1: Same directory as Python executable (virtual env)
    venv_scripts = os.path.dirname(sys.executable)
    if sys.platform == 'win32':
        candidate = os.path.join(venv_scripts, 'aws-adfs.exe')
    else:
        candidate = os.path.join(venv_scripts, 'aws-adfs')
    
    if os.path.exists(candidate):
        aws_adfs_exe = candidate
    else:
        # Location 2: User's local Scripts directory (Windows Store Python)
        if sys.platform == 'win32':
            import site
            user_site = site.getusersitepackages()
            if user_site:
                user_scripts = os.path.join(os.path.dirname(user_site), 'Scripts', 'aws-adfs.exe')
                if os.path.exists(user_scripts):
                    aws_adfs_exe = user_scripts
        
        # Location 3: Try to find it in PATH
        if not aws_adfs_exe:
            import shutil
            aws_adfs_exe = shutil.which('aws-adfs')
    
    if not aws_adfs_exe or not os.path.exists(aws_adfs_exe):
        print(f"ERROR: aws-adfs not found")
        print("Searched locations:")
        print(f"  - {candidate}")
        if sys.platform == 'win32':
            print(f"  - User Scripts directory")
        print(f"  - System PATH")
        print()
        print("Install it with: pip install aws-adfs")
        print("Or ensure it's in your PATH")
        return False
    
    # Prepare environment variables
    env = os.environ.copy()
    env['PYTHONWARNINGS'] = 'ignore:Unverified HTTPS request'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['username'] = username
    env['password'] = password
    
    # Build command (same as wizard)
    cmd = [
        aws_adfs_exe, 'login',
        '--adfs-host', adfs_host,
        '--region', region,
        '--provider-id', 'urn:amazon:webservices',
        '--s3-signature-version', 's3v4',
        '--session-duration', '3600',
        '--no-ssl-verification',
        '--no-sspi',  # Disable Windows SSPI
        '--env',  # Use environment variables for credentials
        '--profile', profile
    ]
    
    # Add role ARN if specified
    if role_arn:
        cmd.extend(['--role-arn', role_arn])
    
    try:
        # Run aws-adfs
        if role_arn:
            # Role specified, no interaction needed
            print("Running aws-adfs login with specified role...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
                encoding='utf-8',
                errors='replace'
            )
        else:
            # No role specified, let user select interactively
            print("Running aws-adfs login...")
            print("You will be prompted to select a role if multiple roles are available.")
            print()
            result = subprocess.run(
                cmd,
                timeout=120,
                env=env
            )
        
        if result.returncode == 0:
            print("✓ Authentication successful!")
            print()
            
            # Verify credentials work
            print("Testing credentials...")
            test_result = subprocess.run(
                ['aws', 'sts', 'get-caller-identity', '--profile', profile, '--region', region],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if test_result.returncode == 0:
                print("✓ Credentials verified!")
                print()
                print("Identity:")
                print(test_result.stdout)
                print()
                print(f"Credentials saved to profile: {profile}")
                print()
                if profile == 'default':
                    print("You can now use AWS CLI commands directly:")
                    print("  aws s3 ls")
                    print("  aws sts get-caller-identity")
                else:
                    print(f"Use --profile {profile} with AWS CLI commands:")
                    print(f"  aws s3 ls --profile {profile}")
                    print(f"  aws sts get-caller-identity --profile {profile}")
                print()
                return True
            else:
                print("✗ Credential verification failed")
                print(test_result.stderr)
                return False
        else:
            # Parse error (filter SSL warnings)
            error_output = result.stderr or result.stdout or "Authentication failed"
            error_lines = []
            for line in error_output.split('\n'):
                if any(x in line for x in ['InsecureRequestWarning', 'Unverified HTTPS', 
                                           'connectionpool.py', 'urllib3', 'Traceback']):
                    continue
                if line.strip():
                    error_lines.append(line.strip())
            
            if error_lines:
                print("✗ Authentication failed:")
                for line in error_lines[:10]:
                    print(f"  {line}")
            else:
                print("✗ Authentication failed (no error details)")
            
            return False
            
    except subprocess.TimeoutExpired:
        print("✗ Authentication timeout (120 seconds)")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    """Main entry point."""
    print("=" * 60)
    print("  AWS ADFS Login (Python)")
    print("=" * 60)
    print()
    
    # Load configuration from .env.local
    env_vars = load_env_file('.env.local')
    if not env_vars:
        print("Please create .env.local file with your ADFS credentials")
        return 1
    
    # Extract configuration
    adfs_url = env_vars.get('ADFS_HOST', '')
    username = env_vars.get('AD_USERNAME', '')
    # Handle escaped backslashes in username (domain\\user -> domain\user)
    username = username.replace('\\\\', '\\')
    password = env_vars.get('AD_PASSWORD', '')
    region = env_vars.get('AWS_REGION', 'us-east-1')
    profile = env_vars.get('AWS_PROFILE', 'default')
    role_arn = env_vars.get('AWS_ROLE_ARN', '')  # Optional role ARN
    
    if not adfs_url or not username or not password:
        print("ERROR: Missing required configuration in .env.local:")
        if not adfs_url:
            print("  - ADFS_HOST")
        if not username:
            print("  - AD_USERNAME")
        if not password:
            print("  - AD_PASSWORD")
        return 1
    
    # Extract ADFS host
    adfs_host = extract_adfs_host(adfs_url)
    
    # Perform login
    success = aws_adfs_login(adfs_host, username, password, region, profile, role_arn)
    
    if success:
        print("=" * 60)
        print("  Login Complete!")
        print("=" * 60)
        return 0
    else:
        print()
        print("=" * 60)
        print("  Login Failed")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
