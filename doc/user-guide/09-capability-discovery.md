# Capability Discovery Guide

This guide explains how to use the Capability Discovery feature to find and manage capabilities deployed across your AWS accounts.

---

## Overview

The Capability Discovery feature enables you to discover capabilities that have been deployed to your AWS accounts by scanning CloudFormation stacks. This is particularly useful when:

- Multiple team members deploy capabilities using different workstations
- You need a unified view of all deployed capabilities across accounts
- You want to verify the current state of your infrastructure
- You're onboarding to an existing environment with pre-deployed capabilities

### How It Works

The discovery process:
1. Connects to your AWS account using your credentials
2. Scans CloudFormation stacks in the specified region
3. Identifies stacks matching the capability naming convention
4. Groups related stacks into capabilities
5. Determines the health status of each capability
6. Synchronizes the results with your local database

---

## Key Concepts

### Landing Zones

A **Landing Zone** represents an AWS account configured for capability discovery. Each landing zone stores:

| Property | Description |
|----------|-------------|
| **Name** | User-friendly identifier (e.g., "Production Account") |
| **Account ID** | 12-digit AWS account number |
| **Account Alias** | Optional AWS account alias |
| **Default Region** | Primary region for discovery |
| **Last Discovery** | Timestamp of most recent scan |
| **Capabilities Count** | Number of discovered capabilities |

You can configure multiple landing zones to manage capabilities across different AWS accounts from a single interface.

### Capability Status

Discovered capabilities are assigned a status based on their CloudFormation stack states:

| Status | Description | Indicator |
|--------|-------------|-----------|
| **Healthy** | All stacks are in COMPLETE state | 🟢 Green |
| **Partial** | Some expected stacks are missing | 🟡 Amber |
| **In Progress** | Stacks are currently being created/updated | 🔵 Blue |
| **Failed** | One or more stacks are in FAILED or ROLLBACK state | 🔴 Red |
| **Not Found in AWS** | Previously discovered but no longer exists | ⚪ Gray |

### Stack Types

The discovery service recognizes the following stack types:

**Backend Stacks:**
- `backend-foundation` - Core infrastructure (VPC, IAM base)
- `backend-iam-roles` - IAM roles and policies
- `backend-storage` - DynamoDB, S3, ECR
- `backend-network` - ALB, security groups
- `backend-service` - ECS/Fargate services
- `backend-domain` - Route53, certificates

**Frontend Stacks:**
- `frontend-global` - CloudFront, WAF, S3
- `frontend-cognito` - User authentication
- `frontend-regional` - Regional resources

---

## Getting Started

### Prerequisites

Before using capability discovery, ensure you have:

1. **AWS Credentials** - Valid credentials with permissions to:
   - `cloudformation:ListStacks`
   - `cloudformation:DescribeStacks`
   - `sts:GetCallerIdentity`
   - `iam:ListAccountAliases`

2. **Network Access** - Connectivity to AWS APIs from your workstation

3. **Authenticated Session** - Complete AWS authentication in the installer

---

## Setting Up Landing Zones

### Step 1: Access the Discovery Feature

From the main application:

1. Navigate to the **Capability Selection** screen
2. Look for the **"Discover from AWS"** option or the **Landing Zones** panel

<!-- Screenshot placeholder: Landing Zone Selector -->
![Landing Zone Selector](./screen-shots/landing-zone-selector.png)

### Step 2: Select Cloud Provider

The landing zone selector displays available cloud providers:

| Provider | Status |
|----------|--------|
| **Amazon Web Services (AWS)** | ✅ Supported |
| Microsoft Azure | 🔜 Coming Soon |
| Google Cloud Platform | 🔜 Coming Soon |

Click on **AWS** to proceed (it should be selected by default).

### Step 3: Add a New Landing Zone

1. Click **"+ Add Landing Zone"** button
2. Fill in the required information:

| Field | Required | Description | Example |
|-------|----------|-------------|---------|
| **Name** | Yes | Friendly name for this account | "Production Account" |
| **AWS Account ID** | Yes | 12-digit AWS account number | "123456789012" |
| **Default Region** | Yes | Primary region for discovery | "ap-southeast-1" |
| **Account Alias** | No | AWS account alias if configured | "totogi-prod" |

<!-- Screenshot placeholder: Add Landing Zone Form -->
![Add Landing Zone Form](./screen-shots/add-landing-zone.png)

3. Click **"Add Landing Zone"** to save

### Step 4: Verify Landing Zone

After adding, your landing zone appears in the list showing:
- Name and account details
- Default region
- Last discovery timestamp (shows "Never" for new zones)
- Number of discovered capabilities

---

## Running Capability Discovery

### Starting Discovery

1. **Select a Landing Zone** - Click on the landing zone you want to scan
2. **Ensure AWS Authentication** - You must have valid AWS credentials
3. **Click "Discover"** - Initiates the discovery process

<!-- Screenshot placeholder: Discovery Panel -->
![Discovery Panel](./screen-shots/discovery-panel.png)

### Monitoring Progress

During discovery, you'll see:

- **Progress Indicator** - Spinning animation while scanning
- **Progress Message** - Current operation status
- **Stacks Scanned** - Number of CloudFormation stacks examined
- **Capabilities Found** - Number of capabilities identified so far

**Example Progress Messages:**
```
Scanning CloudFormation stacks...
Found 15 capability stacks
Discovered 3 capabilities
```

### Discovery Complete

When discovery finishes successfully:

- ✅ Green success banner appears
- Summary shows total capabilities and stacks found
- Discovered capabilities are listed below
- Landing zone's "Last Discovery" timestamp updates

### Discovery Failed

If discovery fails:

- ❌ Red error banner appears
- Error messages explain what went wrong
- Common causes and solutions are listed below

---

## Viewing Discovered Capabilities

### Capability List

After discovery, capabilities are displayed with:

| Information | Description |
|-------------|-------------|
| **Name** | Capability name (e.g., "Call-Processing") |
| **Status Badge** | Health status indicator |
| **"Discovered" Badge** | Purple badge indicating discovery source |
| **Environment** | Deployment environment (DEV, TEST, STAGE, PROD) |
| **Region** | AWS region where deployed |
| **Stacks Count** | Number of CloudFormation stacks |
| **Version** | Version if available from stack tags |
| **Account ID** | AWS account containing the capability |
| **Discovery Date** | When the capability was last discovered |

<!-- Screenshot placeholder: Discovered Capabilities List -->
![Discovered Capabilities](./screen-shots/discovered-capabilities.png)

### Capability Details

Click on a capability to view additional details:

- **Frontend URL** - Link to the deployed frontend application
- **Backend URL** - Link to the backend API endpoint
- **Missing Stacks** - For partial deployments, shows which stacks are missing

### Understanding Status Indicators

**Healthy (Green)**
```
All expected stacks are deployed and in COMPLETE state.
Your capability is fully operational.
```

**Partial (Amber)**
```
Some expected stacks are missing.
Example: "Missing stacks: backend-domain, frontend-cognito"
Consider completing the deployment.
```

**In Progress (Blue)**
```
One or more stacks are currently being created or updated.
Wait for operations to complete, then refresh.
```

**Failed (Red)**
```
One or more stacks are in FAILED or ROLLBACK state.
Review CloudFormation console for error details.
```

---

## Refreshing Capabilities

### Manual Refresh

To update the capability list with current AWS state:

1. Click the **"Refresh"** button in the Discovery Panel
2. Wait for the scan to complete
3. View updated status and any new capabilities

### When to Refresh

Refresh capabilities when:
- Team members have deployed new capabilities
- You've made changes directly in AWS Console
- Stack operations have completed
- You need to verify current deployment state

---

## Multi-Account Workflow

### Managing Multiple AWS Accounts

The discovery feature supports managing capabilities across multiple AWS accounts:

1. **Add Multiple Landing Zones** - Create a landing zone for each AWS account
2. **Switch Between Zones** - Click on different landing zones to view their capabilities
3. **Run Discovery Per Zone** - Each landing zone maintains its own discovery state

### Unified View

When viewing capabilities:
- Each capability shows its **Account ID**
- Same capability name in different accounts appears as separate entries
- Filter by landing zone to focus on specific accounts

### Best Practices for Multi-Account

| Practice | Benefit |
|----------|---------|
| Use descriptive landing zone names | Easy identification (e.g., "Dev Account", "Prod Account") |
| Include account alias | Quick reference without memorizing account IDs |
| Regular discovery refresh | Keep capability status current |
| Consistent naming across accounts | Easier capability tracking |

---

## Filtering and Searching

### Filter by Landing Zone

Use the landing zone selector to filter capabilities:

1. Click on a specific landing zone
2. Only capabilities from that account are displayed
3. Click another zone to switch views

### Filter by Status

Look for capabilities with specific statuses:
- **Healthy** - Fully operational deployments
- **Partial** - Incomplete deployments needing attention
- **Failed** - Deployments requiring troubleshooting

---

## Integration with Deployment Workflow

### Discovered vs. Deployed Capabilities

| Source | Badge | Description |
|--------|-------|-------------|
| **Discovered** | Purple "Discovered" badge | Found via CloudFormation scanning |
| **Deployed** | No badge | Deployed through this installer |

### Actions on Discovered Capabilities

You can perform these actions on discovered capabilities:

| Action | Description |
|--------|-------------|
| **Update** | Deploy a newer version |
| **Delete** | Remove the capability from AWS |
| **View Details** | See stack information and URLs |

### Synchronization

Discovered capabilities are synchronized to your local database:
- Appear in the "Installed Capabilities" section
- Can be managed like locally-deployed capabilities
- Status updates on each discovery refresh

---

## Troubleshooting

### Common Issues and Solutions

#### "Access Denied" Error

**Symptoms:**
- Discovery fails immediately
- Error message mentions permissions

**Solutions:**

1. **Verify IAM Permissions**
   
   Ensure your IAM user/role has these permissions:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "cloudformation:ListStacks",
           "cloudformation:DescribeStacks",
           "sts:GetCallerIdentity",
           "iam:ListAccountAliases"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

2. **Check Account Access**
   - Verify you're authenticated to the correct AWS account
   - Confirm the account ID matches your landing zone

3. **Re-authenticate**
   - Go back to AWS Configuration
   - Enter credentials again
   - Test credentials before proceeding

#### "Session Expired" Error

**Symptoms:**
- Discovery fails mid-process
- Error mentions expired credentials

**Solutions:**

1. **Re-authenticate with AWS**
   - Navigate to AWS Configuration
   - Enter fresh credentials
   - Retry discovery

2. **For ADFS/SAML Users**
   - Sessions typically expire after 1 hour
   - Re-authenticate before long operations

#### No Capabilities Found

**Symptoms:**
- Discovery completes successfully
- Zero capabilities discovered

**Possible Causes:**

1. **Wrong Region**
   - Capabilities may be in a different region
   - Update landing zone default region
   - Or check AWS Console for actual deployment region

2. **Non-Standard Stack Names**
   - Discovery only finds stacks matching the naming convention
   - Stack name format: `{capability-name}-{environment}-{stack-type}`
   - Manually deployed stacks may not match

3. **Stacks Deleted**
   - Capabilities may have been removed
   - Check CloudFormation console directly

4. **Wrong Account**
   - Verify the account ID in your landing zone
   - Confirm you're authenticated to the correct account

#### Partial Status Shown

**Symptoms:**
- Capability shows "Partial" status
- Missing stacks are listed

**Understanding:**

This indicates an incomplete deployment. Common scenarios:
- Deployment was interrupted
- Only frontend or backend was deployed
- Some stacks failed and were rolled back

**Solutions:**

1. **Complete the Deployment**
   - Use the Update action to deploy missing stacks
   - Select the same capability and environment

2. **Review Missing Stacks**
   - Check which stack types are missing
   - Verify if they're actually needed for your use case

#### Discovery Takes Too Long

**Symptoms:**
- Discovery runs for extended periods
- Progress seems stuck

**Solutions:**

1. **Check Network Connectivity**
   - Verify stable internet connection
   - Check for firewall or proxy issues

2. **Large Number of Stacks**
   - Accounts with many stacks take longer
   - Discovery scans all CloudFormation stacks

3. **AWS API Throttling**
   - High API usage may cause delays
   - The service implements automatic retry with backoff

#### Rate Limiting Errors

**Symptoms:**
- Error mentions "rate exceeded" or "throttling"
- Discovery fails intermittently

**Solutions:**

1. **Wait and Retry**
   - AWS API rate limits are temporary
   - Wait a few minutes before retrying

2. **Reduce Concurrent Operations**
   - Avoid running multiple discoveries simultaneously
   - Complete one discovery before starting another

### Error Messages Reference

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Access Denied" | Insufficient IAM permissions | Add required permissions |
| "Invalid credentials" | Expired or incorrect credentials | Re-authenticate |
| "Network error" | Connectivity issues | Check internet connection |
| "Rate exceeded" | AWS API throttling | Wait and retry |
| "Stack not found" | Stack was deleted | Refresh to update status |
| "Region not available" | Invalid region specified | Update landing zone region |

### Getting Help

If issues persist:

1. **Check Application Logs**
   - Windows: `%APPDATA%\Totogi Installer\logs\`
   - macOS: `~/Library/Logs/Totogi Installer/`
   - Linux: `~/.config/Totogi Installer/logs/`

2. **Review AWS CloudFormation Console**
   - Direct visibility into stack states
   - Detailed error messages in stack events

3. **Contact Support**
   - Email: support@totogi.com
   - Include discovery logs and error messages

---

## Best Practices

### Regular Discovery

- **Schedule Regular Scans** - Run discovery periodically to keep status current
- **After Team Deployments** - Refresh after team members deploy capabilities
- **Before Updates** - Verify current state before making changes

### Landing Zone Organization

- **Meaningful Names** - Use descriptive names like "Production - Singapore"
- **Document Accounts** - Keep a record of which accounts serve which purpose
- **Consistent Regions** - Set default regions matching your deployment patterns

### Security Considerations

- **Least Privilege** - Grant only required permissions for discovery
- **Credential Rotation** - Regularly rotate AWS credentials
- **Audit Access** - Review who has access to which landing zones

---

## Next Steps

- [Managing Deployments](./05-managing-deployments.md) - Update and delete capabilities
- [AWS Configuration](./04-aws-configuration.md) - Detailed AWS setup
- [Troubleshooting](./06-troubleshooting.md) - General troubleshooting guide
- [FAQ](./07-faq.md) - Frequently asked questions
