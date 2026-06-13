# Quick Start: AWS Login Setup

## Problem
The `aws-adfs` package is not installed, causing the login script to fail.

## Solution

### Step 1: Install aws-adfs Package

```powershell
# Install aws-adfs globally
pip install aws-adfs

# Or if you have a virtual environment
pip install aws-adfs --user
```

### Step 2: Verify Installation

```powershell
# Check if aws-adfs is installed
aws-adfs --version
```

### Step 3: Run Login Script

```powershell
cd C:\mycode\nexus\nexus-deployer\deploy
.\aws-login.bat
```

## Alternative: One-Line Installation and Login

```powershell
pip install aws-adfs && cd C:\mycode\nexus\nexus-deployer\deploy && .\aws-login.bat
```

## Configuration

Your `.env.local` file is already configured with:
- ADFS Host: `adfs.devfactory.com/adfs/ls/idpinitiatedsignon`
- Username: `devfactory\papubhattacharya`
- Role: `arn:aws:iam::764119721991:role/RAM-AWS-Prod-TelcoDR-Nexus AIPS-Admin`
- Profile: `default`

## Troubleshooting

### Issue: pip not found
```powershell
# Use Python module syntax
python -m pip install aws-adfs
```

### Issue: Permission denied
```powershell
# Install for current user only
pip install aws-adfs --user
```

### Issue: SSL verification errors
The script already disables SSL verification with `--no-ssl-verification` flag.

### Issue: Multiple roles available
If you don't specify `AWS_ROLE_ARN` in `.env.local`, you'll be prompted to select a role interactively.

## Next Steps

After successful login:
1. Verify credentials: `aws sts get-caller-identity`
2. Test S3 access: `aws s3 ls`
3. Proceed with deployment using the wizard

## Session Duration

The session lasts for 3600 seconds (1 hour). After expiration, run the login script again.
