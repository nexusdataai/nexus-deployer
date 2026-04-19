# Deployment Utility Scripts

This directory contains utility and verification scripts for the business capability deployment system.

## Scripts Overview

### 🔍 Verification Scripts

#### `test-artifact-verification.sh`
Tests the artifact verification functionality of the main deployment script.
- Demonstrates how S3 and ECR artifact checks work
- Shows error messages when artifacts are missing
- Useful for troubleshooting deployment issues

**Usage:**
```bash
./scripts/test-artifact-verification.sh
```

#### `validate-permissions.sh`
Validates that the current AWS user/role has the necessary IAM permissions for deployment.
- Checks access to required AWS services
- Tests critical permissions
- Provides a summary of passed/failed checks

**Usage:**
```bash
./scripts/validate-permissions.sh
```

### 🛠️ Setup Scripts

#### `setup-deployment-role.sh`
Interactive script to create a cross-account IAM role for deployments.
- Creates the deployment role in the target AWS account
- Configures trust relationships with source account
- Generates secure external IDs
- Supports environment and resource restrictions

**Usage:**
```bash
# Basic setup
./scripts/setup-deployment-role.sh \
  --source-account 123456789012 \
  --external-id my-secure-id

# With restrictions
./scripts/setup-deployment-role.sh \
  --source-account 123456789012 \
  --external-id my-secure-id \
  --environment prod \
  --capability-prefix my-app
```

**Options:**
- `-s, --source-account`: Source AWS account ID (required)
- `-t, --target-account`: Target AWS account ID (optional, uses current)
- `-r, --role-name`: Name for the deployment role
- `-e, --external-id`: External ID for secure access
- `-d, --duration`: Max session duration in seconds
- `--environment`: Restrict to environment (dev/stage/prod/*)
- `--capability-prefix`: Restrict to capability name prefix
- `--region`: AWS region (default: us-east-1)
- `--no-external-id`: Don't require external ID

## Main Deployment Script

The primary deployment script remains in the parent directory:
```bash
../deploy-capability-layered.sh
```

## Directory Structure

```
/opt/mycode/trilogy/starhub-deployer/deploy/
├── deploy-capability-layered.sh    # Main deployment script
├── scripts/                         # Utility scripts (this directory)
│   ├── test-artifact-verification.sh
│   ├── validate-permissions.sh
│   └── setup-deployment-role.sh
├── iam/                            # IAM policies and templates
│   ├── deployment-role-policy.json
│   ├── deployment-role-trust-policy.json
│   ├── deployment-role-stack.yaml
│   └── README.md
├── templates/                      # CloudFormation templates
│   ├── frontend/
│   └── backend/
├── lib/                           # Shared libraries
│   ├── colors.sh
│   ├── logging.sh
│   ├── aws-helpers.sh
│   └── stack-helpers.sh
└── config/                        # Configuration files
    └── example-config.yaml
```

## Common Use Cases

### 1. Pre-deployment Validation
```bash
# Check permissions first
./scripts/validate-permissions.sh

# If permissions are good, proceed with deployment
../deploy-capability-layered.sh -c ../config/prod-config.yaml
```

### 2. Setting Up Cross-Account Deployment
```bash
# Step 1: Create role in target account
./scripts/setup-deployment-role.sh \
  --source-account 123456789012 \
  --external-id secure-id-123

# Step 2: Use the role ARN in deployment
../deploy-capability-layered.sh \
  -c ../config/prod-config.yaml \
  --role-arn arn:aws:iam::TARGET:role/DeploymentRole
```

### 3. Troubleshooting Artifact Issues
```bash
# Test artifact verification logic
./scripts/test-artifact-verification.sh

# Then run deployment with verbose mode
../deploy-capability-layered.sh \
  -c ../config/prod-config.yaml \
  --verbose
```

## Notes

- All scripts are executable and include help documentation (`-h` or `--help`)
- Scripts use the shared libraries from `../lib/` for consistent output formatting
- The setup script requires the CloudFormation template in `../iam/deployment-role-stack.yaml`
- Error handling and validation are built into all scripts

## Support

For issues with these scripts:
1. Run with `--help` flag for usage information
2. Check the main deployment documentation in `../README.md`
3. Review IAM documentation in `../iam/README.md`

---

*Last Updated: November 2024*
