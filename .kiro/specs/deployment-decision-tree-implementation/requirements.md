# Requirements Document

## Introduction

The deployment system needs to automatically detect existing CloudFormation stack states and recommend the appropriate deployment strategy (CLEAN_DEPLOY vs UPDATE_EXISTING) based on the Deployment Decision Tree. Currently, the stack detection service only queries TinyDB records and does not check actual CloudFormation stack states, which means it cannot detect failed stacks that require CLEAN_DEPLOY strategy.

## Glossary

- **CloudFormation Stack**: AWS infrastructure resource group managed as a single unit
- **Stack State**: The current status of a CloudFormation stack (e.g., CREATE_COMPLETE, ROLLBACK_COMPLETE, UPDATE_ROLLBACK_COMPLETE)
- **CLEAN_DEPLOY**: Deployment strategy that deletes all existing stacks and deploys fresh
- **UPDATE_EXISTING**: Deployment strategy that updates existing stacks in place
- **TinyDB**: Local JSON-based database storing deployment state records
- **Deployment Decision Tree**: Logic flowchart that determines which deployment strategy to use based on stack states
- **Updatable State**: Stack states that allow in-place updates (CREATE_COMPLETE, UPDATE_COMPLETE)
- **Failed State**: Stack states that require deletion before redeployment (ROLLBACK_COMPLETE, UPDATE_ROLLBACK_COMPLETE, DELETE_FAILED, CREATE_FAILED)
- **In-Progress State**: Stack states indicating ongoing operations (CREATE_IN_PROGRESS, UPDATE_IN_PROGRESS, DELETE_IN_PROGRESS)

## Requirements

### Requirement 1

**User Story:** As a deployment operator, I want the system to automatically detect CloudFormation stack states, so that I can know if my stacks are in a healthy state before deployment.

#### Acceptance Criteria

1. WHEN the system detects existing stacks THEN the system SHALL query CloudFormation for actual stack states
2. WHEN querying CloudFormation THEN the system SHALL retrieve stack status for all expected stacks (frontend-global, frontend-regional, backend-foundation, backend-storage, backend-service)
3. WHEN a stack does not exist in CloudFormation THEN the system SHALL mark it as "not found" rather than failed
4. WHEN CloudFormation returns stack information THEN the system SHALL extract stack name, status, status reason, creation time, and last update time
5. WHEN CloudFormation API calls fail THEN the system SHALL log the error and continue with remaining stacks

### Requirement 2

**User Story:** As a deployment operator, I want the system to classify stack states as updatable or failed, so that I can understand which stacks can be updated in place.

#### Acceptance Criteria

1. WHEN a stack has status CREATE_COMPLETE THEN the system SHALL classify it as updatable
2. WHEN a stack has status UPDATE_COMPLETE THEN the system SHALL classify it as updatable
3. WHEN a stack has status ROLLBACK_COMPLETE THEN the system SHALL classify it as failed
4. WHEN a stack has status UPDATE_ROLLBACK_COMPLETE THEN the system SHALL classify it as failed
5. WHEN a stack has status DELETE_FAILED THEN the system SHALL classify it as failed
6. WHEN a stack has status CREATE_FAILED THEN the system SHALL classify it as failed
7. WHEN a stack has status ending with "_IN_PROGRESS" THEN the system SHALL classify it as in-progress
8. WHEN a stack does not exist THEN the system SHALL classify it as updatable (can be created)

### Requirement 3

**User Story:** As a deployment operator, I want the system to automatically recommend a deployment strategy based on the decision tree, so that I don't have to manually determine which strategy to use.

#### Acceptance Criteria

1. WHEN all stacks are in updatable states THEN the system SHALL recommend UPDATE_EXISTING strategy
2. WHEN any stack is in a failed state THEN the system SHALL recommend CLEAN_DEPLOY strategy
3. WHEN no stacks exist THEN the system SHALL recommend UPDATE_EXISTING strategy (first deployment)
4. WHEN any stack is in an in-progress state THEN the system SHALL recommend waiting and SHALL NOT recommend a deployment strategy
5. WHEN the system recommends a strategy THEN the system SHALL provide a human-readable reason for the recommendation

### Requirement 4

**User Story:** As a deployment operator, I want to see detailed information about why a strategy was recommended, so that I can understand the system's decision-making process.

#### Acceptance Criteria

1. WHEN the system recommends CLEAN_DEPLOY THEN the system SHALL list all failed stacks with their states
2. WHEN the system recommends UPDATE_EXISTING THEN the system SHALL confirm all stacks are in updatable states
3. WHEN the system recommends waiting THEN the system SHALL list all in-progress stacks
4. WHEN displaying stack information THEN the system SHALL include stack name, current status, and status reason if available
5. WHEN multiple issues exist THEN the system SHALL prioritize showing failed stacks over in-progress stacks

### Requirement 5

**User Story:** As a deployment operator, I want the stack detection to work across multiple AWS regions, so that I can deploy capabilities with global and regional stacks.

#### Acceptance Criteria

1. WHEN detecting frontend-global stacks THEN the system SHALL query CloudFormation in us-east-1 region
2. WHEN detecting regional stacks THEN the system SHALL query CloudFormation in the target deployment region
3. WHEN querying multiple regions THEN the system SHALL use the correct region for each stack type
4. WHEN a region query fails THEN the system SHALL log the error and continue with other regions
5. WHEN returning results THEN the system SHALL include the region for each stack

### Requirement 6

**User Story:** As a deployment operator, I want the system to handle AWS credential issues gracefully, so that I receive clear error messages when authentication fails.

#### Acceptance Criteria

1. WHEN AWS credentials are invalid THEN the system SHALL return an error message indicating authentication failure
2. WHEN AWS credentials are expired THEN the system SHALL return an error message indicating session expiration
3. WHEN AWS credentials lack permissions THEN the system SHALL return an error message indicating insufficient permissions
4. WHEN credential errors occur THEN the system SHALL NOT crash but SHALL return a detection result with error information
5. WHEN partial results are available THEN the system SHALL return those results along with error information for failed queries

### Requirement 7

**User Story:** As a system integrator, I want the enhanced stack detection to integrate seamlessly with existing deployment workflows, so that no breaking changes are introduced.

#### Acceptance Criteria

1. WHEN the stack detection service is called THEN the system SHALL maintain backward compatibility with existing API signatures
2. WHEN returning detection results THEN the system SHALL use the existing StackDetectionResult model
3. WHEN the deployment orchestrator calls stack detection THEN the system SHALL work without requiring orchestrator changes
4. WHEN TinyDB records exist but CloudFormation stacks do not THEN the system SHALL prioritize CloudFormation state over TinyDB records
5. WHEN both TinyDB and CloudFormation data are available THEN the system SHALL merge the information with CloudFormation taking precedence
