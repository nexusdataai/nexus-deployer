# Requirements Document

## Introduction

The pre-deployment validator currently has a critical bug where it incorrectly identifies and deletes S3 buckets (and other resources) as "orphaned" even when they belong to existing, stable CloudFormation stacks. This causes deployment failures when attempting to update existing stacks, as CloudFormation tries to update resources that have been deleted by the validator.

The issue occurs during the UPDATE_EXISTING deployment strategy when:
1. A stack exists in a stable state (e.g., CREATE_COMPLETE, UPDATE_COMPLETE)
2. The pre-deployment validator runs orphaned resource detection
3. The validator incorrectly identifies stack-managed resources as orphaned
4. The validator deletes these resources
5. CloudFormation attempts to update the stack but fails because resources are missing

This fix will ensure orphaned resource detection only runs when appropriate and does not interfere with stack-managed resources.

## Glossary

- **PreDeploymentValidator**: Service that validates the deployment environment before starting a deployment
- **OrphanedResource**: An AWS resource that exists outside of CloudFormation management, typically left behind after stack deletion with DeletionPolicy: Retain
- **StableStack**: A CloudFormation stack in a successful state (CREATE_COMPLETE, UPDATE_COMPLETE, etc.)
- **UnstableStack**: A CloudFormation stack in a failed or rollback state (ROLLBACK_COMPLETE, DELETE_FAILED, etc.)
- **DeploymentStrategy**: The approach for deployment - either CLEAN_DEPLOY (delete then create) or UPDATE_EXISTING (update in place)

## Requirements

### Requirement 1

**User Story:** As a deployment operator, I want the pre-deployment validator to only check for orphaned resources when appropriate, so that stack-managed resources are not incorrectly deleted during updates.

#### Acceptance Criteria

1. WHEN a stack exists and is in a stable state (CREATE_COMPLETE, UPDATE_COMPLETE) THEN the PreDeploymentValidator SHALL NOT check for orphaned resources for that stack
2. WHEN a stack does not exist THEN the PreDeploymentValidator SHALL check for orphaned resources that may have been left behind from previous deployments
3. WHEN a stack exists and is in an unstable state THEN the PreDeploymentValidator SHALL delete the unstable stack first, and SHALL NOT check for orphaned resources afterward
4. WHEN the deployment strategy is CLEAN_DEPLOY THEN the PreDeploymentValidator SHALL NOT run at all, as the cleanup process will handle all resource deletion
5. WHEN the deployment strategy is UPDATE_EXISTING and a stack exists in a stable state THEN the PreDeploymentValidator SHALL skip orphaned resource detection for that stack

### Requirement 2

**User Story:** As a deployment operator, I want clear logging about why orphaned resource checks are skipped, so that I can understand the validator's decision-making process.

#### Acceptance Criteria

1. WHEN the validator skips orphaned resource detection for a stable stack THEN the system SHALL log the reason with the stack name and status
2. WHEN the validator skips orphaned resource detection after deleting an unstable stack THEN the system SHALL log that the stack deletion will handle resource cleanup
3. WHEN the validator runs orphaned resource detection THEN the system SHALL log the stack name and reason for checking
4. WHEN the validator is disabled for CLEAN_DEPLOY strategy THEN the system SHALL log that validation is skipped for clean deployments

### Requirement 3

**User Story:** As a deployment operator, I want orphaned resource detection to only identify truly orphaned resources, so that active stack resources are never deleted.

#### Acceptance Criteria

1. WHEN checking for orphaned resources THEN the system SHALL only check for resources that exist outside of any active CloudFormation stack
2. WHEN a resource is managed by an existing stack THEN the system SHALL NOT identify it as orphaned
3. WHEN a resource has DeletionPolicy: Retain and its stack no longer exists THEN the system SHALL identify it as orphaned
4. WHEN detecting orphaned resources THEN the system SHALL verify the stack does not exist before attempting cleanup

### Requirement 4

**User Story:** As a deployment operator, I want the deployment orchestrator to skip pre-deployment validation for CLEAN_DEPLOY strategy, so that the cleanup process is not duplicated.

#### Acceptance Criteria

1. WHEN the deployment strategy is CLEAN_DEPLOY THEN the DeploymentOrchestrator SHALL skip pre-deployment validation entirely
2. WHEN the deployment strategy is UPDATE_EXISTING THEN the DeploymentOrchestrator SHALL run pre-deployment validation as configured
3. WHEN validation is skipped due to CLEAN_DEPLOY strategy THEN the system SHALL log the reason for skipping
4. WHEN validation is skipped THEN the deployment SHALL proceed directly to the cleanup and deployment phases
