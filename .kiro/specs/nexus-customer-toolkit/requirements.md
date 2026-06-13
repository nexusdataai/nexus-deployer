<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Requirements Document

## Introduction

The Nexus AI Capability Installation Wizard is a simple, wizard-style deployment tool that enables customers to deploy any capability into their AWS environment. The wizard starts immediately without authentication, guides users through adding AWS environment credentials with adequate permissions, executes deployment scripts while showing real-time logs, performs comprehensive post-deployment verification, and collects diagnostic logs for troubleshooting. The system prioritizes simplicity and a guided step-by-step experience.

## Glossary

- **Installation Wizard**: The Nexus AI Capability Installation Wizard application
- **Capability**: A modular business function that can be deployed independently into customer AWS infrastructure
- **Deployment**: The process of provisioning a capability into customer AWS infrastructure using automated scripts
- **Role ARN**: Amazon Resource Name for an IAM role that grants the necessary deployment permissions
- **Deployment Script**: An automated script that provisions AWS resources for a capability using CloudFormation or similar tools
- **Deployment Logs**: Real-time output from the deployment script execution displayed in the wizard
- **Post-Verification**: Automated health checks and validation performed after deployment to confirm successful installation
- **Diagnostic Logs**: A compressed ZIP archive containing deployment logs, error messages, and system information for troubleshooting
- **AWS Environment**: A customer's AWS account and region configuration where capabilities will be deployed
- **Adequate Permissions**: The minimum set of IAM permissions required to successfully deploy a capability

## Requirements

### Requirement 1

**User Story:** As a user, I want to start the installation wizard without authentication, so that I can immediately begin deploying capabilities

#### Acceptance Criteria

1. WHEN a user launches the Installation Wizard THEN the Installation Wizard SHALL start immediately without requiring any login credentials
2. WHEN the Installation Wizard starts THEN the Installation Wizard SHALL display a welcome screen with a brief overview of the deployment process
3. THE Installation Wizard SHALL NOT require user registration, account creation, or authentication to operate
4. WHEN the welcome screen is displayed THEN the Installation Wizard SHALL provide a start button to begin the deployment workflow
5. WHEN a user clicks the start button THEN the Installation Wizard SHALL navigate to the capability selection screen

### Requirement 2

**User Story:** As a user, I want to select which capability to deploy, so that I can install the specific business function I need

#### Acceptance Criteria

1. WHEN a user reaches the capability selection screen THEN the Installation Wizard SHALL display a list of all available capabilities with descriptions
2. WHEN a user selects a capability THEN the Installation Wizard SHALL display detailed information including prerequisites and required AWS resources
3. WHEN a capability has multiple versions THEN the Installation Wizard SHALL allow the user to select the desired version
4. WHEN a user confirms capability selection THEN the Installation Wizard SHALL navigate to the AWS environment configuration screen
5. WHEN capability information is displayed THEN the Installation Wizard SHALL show estimated deployment time and required IAM permissions

### Requirement 3

**User Story:** As a user, I want to add my AWS environment with Role ARN and permissions, so that the wizard can deploy resources into my AWS account

#### Acceptance Criteria

1. WHEN a user reaches the AWS environment configuration screen THEN the Installation Wizard SHALL prompt for AWS Role ARN and AWS Region
2. WHEN a user enters a Role ARN THEN the Installation Wizard SHALL validate the ARN format matches AWS IAM role naming conventions
3. WHEN a user selects an AWS Region THEN the Installation Wizard SHALL validate the region is supported by AWS services
4. WHEN a user provides a Role ARN THEN the Installation Wizard SHALL attempt to assume the role to verify access
5. WHEN role assumption succeeds THEN the Installation Wizard SHALL proceed to permission verification
6. WHEN role assumption fails THEN the Installation Wizard SHALL display an error message with troubleshooting steps

### Requirement 4

**User Story:** As a user, I want the wizard to verify adequate permissions, so that I can confirm my AWS role has all necessary permissions before deployment

#### Acceptance Criteria

1. WHEN the Installation Wizard verifies permissions THEN the Installation Wizard SHALL check the assumed role has all required IAM permissions for the selected capability
2. WHEN all required permissions are present THEN the Installation Wizard SHALL display a success message and enable the deploy button
3. WHEN required permissions are missing THEN the Installation Wizard SHALL display a list of missing permissions with descriptions
4. WHEN permissions are insufficient THEN the Installation Wizard SHALL provide a copy button to copy the required IAM policy JSON
5. WHEN a user corrects permissions externally THEN the Installation Wizard SHALL provide a re-check permissions button to verify again

### Requirement 5

**User Story:** As a user, I want to run the deployment script, so that the capability is provisioned in my AWS environment

#### Acceptance Criteria

1. WHEN a user clicks the deploy button THEN the Installation Wizard SHALL execute the deployment script with the configured AWS environment parameters
2. WHEN the deployment script starts THEN the Installation Wizard SHALL display a deployment in progress indicator
3. WHEN the deployment script executes THEN the Installation Wizard SHALL capture all script output for real-time display
4. WHEN the deployment script completes successfully THEN the Installation Wizard SHALL proceed to post-verification
5. WHEN the deployment script fails THEN the Installation Wizard SHALL capture error details and navigate to the error screen

### Requirement 6

**User Story:** As a user, I want to view deployment logs in real-time, so that I can monitor deployment progress and identify any issues as they occur

#### Acceptance Criteria

1. WHEN the deployment script is executing THEN the Installation Wizard SHALL display deployment logs in real-time with automatic scrolling
2. WHEN new log entries are generated THEN the Installation Wizard SHALL append them to the log display within two seconds
3. WHEN the log display contains error messages THEN the Installation Wizard SHALL highlight errors in red color
4. WHEN the log display contains warning messages THEN the Installation Wizard SHALL highlight warnings in yellow color
5. WHEN a user manually scrolls the log display THEN the Installation Wizard SHALL pause automatic scrolling until the user scrolls to the bottom

### Requirement 7

**User Story:** As a user, I want the wizard to perform post-deployment verification, so that I can confirm the capability is deployed correctly and functioning

#### Acceptance Criteria

1. WHEN deployment completes successfully THEN the Installation Wizard SHALL automatically execute all post-verification checks
2. WHEN post-verification executes THEN the Installation Wizard SHALL test deployed endpoints for connectivity and health status
3. WHEN post-verification executes THEN the Installation Wizard SHALL validate CloudFormation stack status is CREATE_COMPLETE
4. WHEN post-verification executes THEN the Installation Wizard SHALL verify all expected stack outputs are present
5. WHEN all verification checks pass THEN the Installation Wizard SHALL display a success screen with deployment summary
6. WHEN any verification check fails THEN the Installation Wizard SHALL display failure details and automatically collect diagnostic logs

### Requirement 8

**User Story:** As a user, I want to view deployed resource information, so that I can access and use the deployed capability

#### Acceptance Criteria

1. WHEN post-verification succeeds THEN the Installation Wizard SHALL display all CloudFormation stack outputs
2. WHEN resource information is displayed THEN the Installation Wizard SHALL show endpoint URLs, resource ARNs, and configuration values
3. WHEN resource information is displayed THEN the Installation Wizard SHALL provide copy buttons for each output value
4. WHEN a user clicks a copy button THEN the Installation Wizard SHALL copy the value to the system clipboard
5. WHEN resource information is displayed THEN the Installation Wizard SHALL provide an export button to save all outputs to a JSON file

### Requirement 9

**User Story:** As a user, I want to collect and download diagnostic logs, so that I can troubleshoot deployment issues or share logs with support

#### Acceptance Criteria

1. WHEN deployment or verification fails THEN the Installation Wizard SHALL automatically collect all diagnostic logs
2. WHEN diagnostic logs are collected THEN the Installation Wizard SHALL include deployment script output, CloudFormation events, and error messages
3. WHEN diagnostic logs are collected THEN the Installation Wizard SHALL include AWS environment configuration and timestamp metadata
4. WHEN diagnostic logs are collected THEN the Installation Wizard SHALL compress all logs into a ZIP archive
5. WHEN the ZIP archive is created THEN the Installation Wizard SHALL provide a download button to save the archive locally with a timestamped filename

### Requirement 10

**User Story:** As a user, I want to download diagnostic logs at any time during deployment, so that I can collect troubleshooting information proactively

#### Acceptance Criteria

1. WHEN the Installation Wizard displays deployment logs THEN the Installation Wizard SHALL provide a download logs button visible at all times
2. WHEN a user clicks the download logs button THEN the Installation Wizard SHALL generate a diagnostic log ZIP archive
3. WHEN the ZIP archive is generated THEN the Installation Wizard SHALL include all deployment logs captured up to the current point
4. WHEN the ZIP archive is generated THEN the Installation Wizard SHALL include system information, configuration parameters, and AWS environment details
5. WHEN the ZIP archive is ready THEN the Installation Wizard SHALL trigger a browser download with a descriptive timestamped filename

### Requirement 11

**User Story:** As a user, I want to view deployment progress with clear indicators, so that I can understand which stage is executing and how much time remains

#### Acceptance Criteria

1. WHEN deployment is executing THEN the Installation Wizard SHALL display a progress bar showing overall completion percentage
2. WHEN deployment is executing THEN the Installation Wizard SHALL display the current deployment stage name
3. WHEN the Installation Wizard transitions between stages THEN the Installation Wizard SHALL update the progress indicator within one second
4. WHEN a deployment stage is long-running THEN the Installation Wizard SHALL display an estimated time remaining
5. WHEN all deployment stages complete THEN the Installation Wizard SHALL display the progress bar at one hundred percent

### Requirement 12

**User Story:** As a user, I want to retry a failed deployment, so that I can attempt deployment again after correcting configuration or permission issues

#### Acceptance Criteria

1. WHEN deployment fails THEN the Installation Wizard SHALL display a retry deployment button
2. WHEN a user clicks retry deployment THEN the Installation Wizard SHALL navigate back to the AWS environment configuration screen
3. WHEN retrying deployment THEN the Installation Wizard SHALL preserve all previously entered configuration values
4. WHEN retrying deployment THEN the Installation Wizard SHALL allow modification of any configuration parameter
5. WHEN a user confirms retry THEN the Installation Wizard SHALL execute the deployment script again with the updated configuration

### Requirement 13

**User Story:** As a user, I want to deploy another capability after successful deployment, so that I can install multiple capabilities sequentially

#### Acceptance Criteria

1. WHEN deployment completes successfully THEN the Installation Wizard SHALL display a deploy another capability button
2. WHEN a user clicks deploy another capability THEN the Installation Wizard SHALL navigate back to the capability selection screen
3. WHEN starting a new deployment THEN the Installation Wizard SHALL clear all previous deployment state and logs
4. WHEN starting a new deployment THEN the Installation Wizard SHALL require re-entry of AWS environment credentials
5. WHEN starting a new deployment THEN the Installation Wizard SHALL display the welcome screen with workflow overview

### Requirement 14

**User Story:** As a user, I want to cancel a deployment in progress, so that I can stop the deployment if I identify a configuration error

#### Acceptance Criteria

1. WHEN deployment is executing THEN the Installation Wizard SHALL display a cancel deployment button
2. WHEN a user clicks cancel deployment THEN the Installation Wizard SHALL prompt for confirmation before proceeding
3. WHEN a user confirms cancellation THEN the Installation Wizard SHALL terminate the deployment script execution immediately
4. WHEN deployment is canceled THEN the Installation Wizard SHALL attempt to roll back any partially created AWS resources
5. WHEN cancellation completes THEN the Installation Wizard SHALL display a cancellation summary with cleanup status and collected logs

### Requirement 15

**User Story:** As a user, I want to view detailed CloudFormation stack events, so that I can understand the detailed status of AWS resource provisioning

#### Acceptance Criteria

1. WHEN deployment is executing THEN the Installation Wizard SHALL provide a view stack events button
2. WHEN a user clicks view stack events THEN the Installation Wizard SHALL display CloudFormation stack events in a table format
3. WHEN stack events are displayed THEN the Installation Wizard SHALL show timestamp, resource type, logical resource ID, status, and status reason
4. WHEN stack events are displayed THEN the Installation Wizard SHALL refresh the event list automatically every five seconds
5. WHEN stack events include resource failures THEN the Installation Wizard SHALL highlight failed events in red color
