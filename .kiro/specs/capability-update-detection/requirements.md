# Requirements Document

## Introduction

This document specifies the requirements for detecting existing capability installations during deployment and providing users with options to either clean and redeploy or update the existing installation. The feature enhances the deployment workflow by preventing accidental overwrites and giving users control over how to handle existing deployments.

## Glossary

- **Capability**: A modular business functionality (e.g., Call Processing, Billing Engine) that can be deployed to AWS infrastructure
- **Deployment Orchestrator**: The service responsible for coordinating CloudFormation stack deployments
- **CloudFormation Stack**: An AWS resource that represents a collection of AWS resources managed as a single unit
- **Stack Detection Service**: A service that checks for existing deployment records in TinyDB for a capability
- **TinyDB**: A lightweight document-oriented database used to store deployment state and capability information locally
- **Deployment State**: Persistent record in TinyDB containing capability name, environment, region, deployed stacks, and metadata
- **Clean Deployment**: Complete removal of all existing stacks followed by fresh deployment
- **Update Deployment**: Modification of existing stacks without deletion, preserving data and configurations where possible
- **Deployment Wizard**: The UI workflow that guides users through capability deployment
- **Stack Status**: The current state of a CloudFormation stack (e.g., CREATE_COMPLETE, UPDATE_COMPLETE, ROLLBACK_COMPLETE)

## Requirements

### Requirement 1

**User Story:** As a deployment operator, I want the system to detect if a capability is already installed in the target environment, so that I can make an informed decision about how to proceed with the deployment.

#### Acceptance Criteria

1. WHEN a user initiates a capability deployment THEN the Deployment Orchestrator SHALL check for existing deployment records in TinyDB for that capability in the target environment
2. WHEN checking for existing deployments THEN the Stack Detection Service SHALL query TinyDB deployment state for the specified capability name and environment combination
3. WHEN an existing deployment record is found THEN the Stack Detection Service SHALL retrieve the list of deployed stacks from the TinyDB record
4. WHEN existing stacks are found THEN the Stack Detection Service SHALL return a list containing stack names, stack types, and region information from the TinyDB record
5. WHEN no existing deployment record is found in TinyDB THEN the Stack Detection Service SHALL return an empty list indicating a clean deployment can proceed

### Requirement 2

**User Story:** As a deployment operator, I want to be presented with clear options when an existing capability installation is detected, so that I can choose the appropriate deployment strategy based on my needs.

#### Acceptance Criteria

1. WHEN existing capability stacks are detected THEN the Deployment Wizard SHALL display a deployment strategy selection dialog before proceeding
2. WHEN displaying the strategy selection dialog THEN the system SHALL show the capability name, environment, region, and count of existing stacks
3. WHEN displaying the strategy selection dialog THEN the system SHALL present two options: "Clean and Redeploy" and "Update Existing"
4. WHEN displaying the "Clean and Redeploy" option THEN the system SHALL include a warning that all existing resources will be deleted and data may be lost
5. WHEN displaying the "Update Existing" option THEN the system SHALL indicate that existing resources will be preserved and updated in place
6. WHEN the user selects a deployment strategy THEN the system SHALL store the selection and proceed with the chosen approach
7. WHEN the user cancels the strategy selection THEN the system SHALL abort the deployment and return to the previous wizard step

### Requirement 3

**User Story:** As a deployment operator, I want the system to execute a clean deployment when I choose that option, so that I can start fresh with a completely new installation.

#### Acceptance Criteria

1. WHEN the user selects "Clean and Redeploy" THEN the Deployment Orchestrator SHALL invoke the cleanup service to delete all existing stacks before starting deployment
2. WHEN performing clean deployment THEN the Cleanup Service SHALL delete stacks in reverse order of the STACK_ORDER
3. WHEN deleting each stack THEN the Cleanup Service SHALL wait for deletion to complete before proceeding to the next stack
4. WHEN all stacks are deleted successfully THEN the Deployment Orchestrator SHALL proceed with normal deployment workflow
5. WHEN any stack deletion fails THEN the Deployment Orchestrator SHALL log the error and halt the deployment process
6. WHEN performing clean deployment THEN the system SHALL provide progress updates to the user showing which stacks are being deleted

### Requirement 4

**User Story:** As a deployment operator, I want the system to execute an update deployment when I choose that option, so that I can modify the existing installation without losing data or causing unnecessary downtime.

#### Acceptance Criteria

1. WHEN the user selects "Update Existing" THEN the Deployment Orchestrator SHALL use CloudFormation update operations instead of create operations for existing stacks
2. WHEN updating existing stacks THEN the CloudFormation Service SHALL call update_stack for stacks that exist
3. WHEN updating a stack with no changes THEN the CloudFormation Service SHALL handle the "No updates are to be performed" response gracefully and continue
4. WHEN updating stacks THEN the system SHALL preserve existing stack outputs and pass them to dependent stacks
5. WHEN any stack update fails THEN the Deployment Orchestrator SHALL log the error and halt the deployment process
6. WHEN performing update deployment THEN the system SHALL provide progress updates to the user showing which stacks are being updated

### Requirement 5

**User Story:** As a deployment operator, I want the system to update the TinyDB deployment state after successful deployments, so that future deployments can detect existing installations accurately.

#### Acceptance Criteria

1. WHEN a deployment completes successfully THEN the Deployment Orchestrator SHALL save the deployment state to TinyDB
2. WHEN saving deployment state THEN the system SHALL store the capability name, environment, region, and list of deployed stacks
3. WHEN saving deployment state THEN the system SHALL store stack names, stack types, and deployment metadata for each stack
4. WHEN saving deployment state THEN the system SHALL update the last_deployment timestamp
5. WHEN a deployment record already exists in TinyDB THEN the system SHALL update the existing record rather than creating a duplicate
6. WHEN a clean deployment is performed THEN the system SHALL delete the old deployment record from TinyDB before saving the new deployment state

### Requirement 6

**User Story:** As a deployment operator, I want the detection and strategy selection to happen early in the deployment workflow, so that I don't waste time configuring settings only to discover conflicts later.

#### Acceptance Criteria

1. WHEN the user completes AWS configuration and permission verification THEN the system SHALL perform stack detection before proceeding to deployment execution
2. WHEN stack detection occurs THEN the system SHALL insert the strategy selection step between permission verification and deployment execution
3. WHEN no existing stacks are detected THEN the system SHALL skip the strategy selection step and proceed directly to deployment execution
4. WHEN the user navigates backward from the strategy selection step THEN the system SHALL return to the permission verification step
5. WHEN the user navigates forward from the strategy selection step THEN the system SHALL proceed to deployment execution with the selected strategy

### Requirement 7

**User Story:** As a system administrator, I want the stack detection logic to be reusable across different parts of the application, so that we can check for existing installations in multiple contexts.

#### Acceptance Criteria

1. WHEN implementing stack detection THEN the system SHALL create a dedicated Stack Detection Service class
2. WHEN the Stack Detection Service is created THEN it SHALL use the TinyDB Deployment State Service for querying deployment records
3. WHEN the Stack Detection Service checks for deployments THEN it SHALL provide a method that accepts capability name and environment as parameters
4. WHEN the Stack Detection Service returns results THEN it SHALL return a structured object containing stack information and detection metadata
5. WHEN the Stack Detection Service encounters TinyDB errors THEN it SHALL handle them gracefully and return appropriate error information

### Requirement 8

**User Story:** As a deployment operator, I want detailed logging of the detection and strategy selection process, so that I can audit deployment decisions and troubleshoot issues.

#### Acceptance Criteria

1. WHEN stack detection begins THEN the system SHALL log the capability name and environment being checked in TinyDB
2. WHEN deployment records are found in TinyDB THEN the system SHALL log each stack name and type
3. WHEN the user selects a deployment strategy THEN the system SHALL log the selected strategy and timestamp
4. WHEN clean deployment is executed THEN the system SHALL log each stack deletion operation and result
5. WHEN update deployment is executed THEN the system SHALL log each stack update operation and result
6. WHEN deployment state is saved to TinyDB THEN the system SHALL log the save operation with capability name and environment
7. WHEN errors occur during detection or strategy execution THEN the system SHALL log detailed error messages with context
