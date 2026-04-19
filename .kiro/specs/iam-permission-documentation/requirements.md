# Requirements Document

## Introduction

This feature adds comprehensive IAM permission documentation and guidance to the installation wizard, helping users understand and configure the minimum required AWS permissions for deploying and deleting capabilities in their target AWS environment. The documentation will be integrated into the wizard flow at appropriate steps, providing contextual guidance and actionable setup instructions.

## Glossary

- **Wizard**: The step-by-step installation interface that guides users through capability deployment
- **IAM_Role**: AWS Identity and Access Management role that grants permissions to perform AWS operations
- **Deployment_Role**: The IAM role assumed by the installer to create/manage AWS resources in the target account
- **Trust_Policy**: IAM policy document that specifies which principals can assume a role
- **Permission_Policy**: IAM policy document that specifies what actions a role can perform
- **CloudFormation**: AWS service used to provision and manage infrastructure as code
- **Cross_Account_Deployment**: Deploying resources to an AWS account different from where the installer runs
- **External_ID**: A unique identifier used in trust policies to prevent confused deputy attacks
- **Permission_Verification_Step**: The wizard step that validates AWS credentials and permissions

## Requirements

### Requirement 1: IAM Permission Summary Panel

**User Story:** As a user configuring AWS credentials, I want to see a summary of required IAM permissions, so that I understand what access the deployment role needs.

#### Acceptance Criteria

1. WHEN a user reaches the AWS Configuration step, THE Wizard SHALL display an expandable "Required Permissions" panel
2. WHEN the user expands the permissions panel, THE Wizard SHALL show a categorized list of AWS services and their purposes
3. THE Wizard SHALL display permissions grouped by category: Infrastructure, Frontend, Backend, Data, and Monitoring
4. WHEN displaying each service category, THE Wizard SHALL show the service name, purpose, and key actions required
5. THE Wizard SHALL provide a link to download the complete IAM policy JSON file

### Requirement 2: IAM Role Setup Guide

**User Story:** As a user setting up a new deployment, I want step-by-step instructions for creating the required IAM role, so that I can properly configure my target AWS account.

#### Acceptance Criteria

1. WHEN a user clicks "Setup Guide" in the AWS Configuration step, THE Wizard SHALL display a modal with setup instructions
2. THE Setup_Guide SHALL provide three setup options: CloudFormation template, AWS CLI commands, and manual console steps
3. WHEN the user selects CloudFormation option, THE Wizard SHALL display the template download link and deployment command
4. WHEN the user selects CLI option, THE Wizard SHALL display copyable AWS CLI commands for role creation
5. WHEN the user selects manual option, THE Wizard SHALL display step-by-step console instructions with screenshots placeholders
6. THE Setup_Guide SHALL include trust policy configuration with placeholders for source account ID and external ID
7. THE Setup_Guide SHALL warn users about security best practices including external ID usage and least privilege

### Requirement 3: Permission Verification Feedback

**User Story:** As a user verifying permissions, I want detailed feedback on missing permissions, so that I can fix IAM configuration issues.

#### Acceptance Criteria

1. WHEN permission verification fails, THE Wizard SHALL display which specific permissions are missing
2. WHEN displaying missing permissions, THE Wizard SHALL group them by AWS service
3. THE Wizard SHALL provide remediation suggestions for each missing permission category
4. WHEN a permission is partially granted, THE Wizard SHALL indicate which actions are available and which are restricted
5. THE Wizard SHALL provide a "Copy Missing Permissions" button that generates a minimal IAM policy for missing actions

### Requirement 4: Cross-Account Deployment Documentation

**User Story:** As a user deploying to a different AWS account, I want guidance on cross-account setup, so that I can configure trust relationships correctly.

#### Acceptance Criteria

1. WHEN a user enters a role ARN from a different account, THE Wizard SHALL display cross-account setup guidance
2. THE Cross_Account guidance SHALL explain the trust relationship requirements
3. THE Wizard SHALL provide a template trust policy with the source account ID pre-filled
4. THE Wizard SHALL explain the purpose and importance of external IDs for security
5. WHEN cross-account deployment is detected, THE Wizard SHALL verify the trust relationship before proceeding

### Requirement 5: Resource Cost Estimation

**User Story:** As a user planning a deployment, I want to understand the cost implications of the resources being created, so that I can make informed decisions.

#### Acceptance Criteria

1. THE Wizard SHALL display an estimated monthly cost range for the deployment
2. WHEN displaying cost estimates, THE Wizard SHALL list the major cost-contributing resources
3. THE Wizard SHALL differentiate costs between environments (dev vs prod)
4. THE Wizard SHALL provide links to AWS pricing pages for detailed cost information
5. IF NAT Gateway is enabled, THEN THE Wizard SHALL highlight its significant cost impact (~$45/month)

### Requirement 6: Quick Validation Script

**User Story:** As a user troubleshooting permission issues, I want a validation script I can run, so that I can verify my IAM setup independently.

#### Acceptance Criteria

1. THE Wizard SHALL provide a downloadable permission validation script
2. THE Validation_Script SHALL check all required permissions and report results
3. WHEN the script detects missing permissions, THE Validation_Script SHALL output the specific missing actions
4. THE Validation_Script SHALL be available in both Bash and PowerShell formats
5. THE Wizard SHALL display the script download option in the Permission Verification step

### Requirement 7: Contextual Help Tooltips

**User Story:** As a user unfamiliar with AWS IAM, I want contextual help explaining IAM concepts, so that I can understand the configuration requirements.

#### Acceptance Criteria

1. WHEN hovering over IAM-related fields, THE Wizard SHALL display explanatory tooltips
2. THE Tooltips SHALL explain Role ARN format and how to find it in AWS Console
3. THE Tooltips SHALL explain what regions are available and how to choose one
4. THE Tooltips SHALL explain the difference between same-account and cross-account deployments
5. WHEN an error occurs, THE Wizard SHALL provide contextual help specific to that error type

### Requirement 8: Delete Operation Permissions

**User Story:** As a user deleting a deployment, I want to know if my role has sufficient permissions for deletion, so that I can avoid partial cleanup failures.

#### Acceptance Criteria

1. WHEN entering delete mode, THE Wizard SHALL verify delete-specific permissions
2. THE Wizard SHALL display which resources will be deleted and the permissions required
3. IF delete permissions are insufficient, THEN THE Wizard SHALL list the missing delete actions
4. THE Wizard SHALL warn about resources that may be retained (S3 buckets with data, DynamoDB tables)
5. THE Wizard SHALL provide guidance on manual cleanup for resources that cannot be automatically deleted
