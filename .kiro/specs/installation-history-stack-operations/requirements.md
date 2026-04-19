# Requirements Document

## Introduction

This feature addresses a gap in the deployment session persistence implementation where stack operations are not being logged to the installation history. The root cause is that the `installation_id` is created during deployment but not passed to the `DeploymentOrchestrator`, preventing stack operation logging. Additionally, there is no installation log being stored for debugging and audit purposes.

## Glossary

- **Installation_History**: The UI view showing past deployment executions with their details
- **Stack_Operations**: Individual CloudFormation stack create/update/delete operations during deployment
- **Installation_ID**: A unique identifier (UUID) assigned to each deployment execution
- **Deployment_Orchestrator**: The service that coordinates CloudFormation stack deployments
- **Installation_Tracker**: The service that persists installation records and stack operation logs to TinyDB
- **Installation_Log**: A text-based log file capturing deployment progress messages for debugging

## Requirements

### Requirement 1

**User Story:** As a deployment operator, I want to see all stack operations in the installation history, so that I can understand what CloudFormation stacks were deployed during each installation.

#### Acceptance Criteria

1. WHEN a deployment starts THEN the Deployment_Service SHALL pass the Installation_ID to the Deployment_Orchestrator
2. WHEN a stack operation begins THEN the Deployment_Orchestrator SHALL log the operation to the Installation_Tracker with stack name, type, and region
3. WHEN a stack operation completes THEN the Deployment_Orchestrator SHALL update the log with status, outputs, and duration
4. WHEN viewing installation details THEN the Installation_History SHALL display all stack operations with their status and timing

### Requirement 2

**User Story:** As a deployment operator, I want installation logs persisted to storage, so that I can review deployment progress messages after the deployment completes.

#### Acceptance Criteria

1. WHEN a deployment starts THEN the Deployment_Service SHALL create an installation log file associated with the Installation_ID
2. WHEN a log message is added during deployment THEN the Deployment_Service SHALL append the message to the installation log file
3. WHEN querying installation details THEN the API SHALL return the installation log content
4. WHEN the installation log is retrieved THEN the log SHALL contain timestamps and log levels for each entry

### Requirement 3

**User Story:** As a deployment operator, I want the stacks summary to accurately reflect deployed stacks, so that I can quickly see how many stacks were created, updated, or failed.

#### Acceptance Criteria

1. WHEN a deployment completes THEN the Installation_Tracker SHALL calculate the stacks_summary from logged operations
2. WHEN displaying installation details THEN the stacks_summary SHALL show counts for created, updated, failed, and skipped stacks
3. WHEN a stack operation fails THEN the stacks_summary SHALL increment the failed count
