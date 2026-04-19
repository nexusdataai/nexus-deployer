# Requirements Document

## Introduction

This document defines the requirements for the Capability Discovery feature in the Totogi Customer Toolkit. The feature enables users to discover capabilities that have been deployed to AWS accounts by scanning CloudFormation stacks, solving the problem of inconsistent capability visibility when multiple users deploy capabilities using different local TinyDB instances.

Currently, the Toolkit stores installed capability metadata in a local TinyDB database. This creates a fragmented view where each user only sees capabilities they personally deployed. The Capability Discovery feature provides a unified view by scanning actual AWS infrastructure and synchronizing the local database with the real deployment state.

## Glossary

- **Discovery_Service**: The backend service responsible for scanning AWS CloudFormation stacks and identifying deployed capabilities
- **Landing_Zone**: An AWS account configured for capability deployments, identified by account ID and alias
- **Capability**: A modular business function that can be deployed via CloudFormation stacks
- **Stack_Naming_Convention**: The pattern `{capability-name}-{environment}-{stack-type}` used to identify capability stacks
- **Stack_Type**: One of the predefined CloudFormation stack categories (backend-foundation, backend-iam-roles, backend-storage, backend-network, backend-service, backend-domain, frontend-global, frontend-cognito, frontend-regional)
- **Deployment_Status**: The aggregated health state of a capability derived from its constituent stack statuses
- **TinyDB**: The local JSON-based database used for storing capability and installation metadata
- **ADFS_Authentication**: Active Directory Federation Services authentication flow for obtaining AWS credentials
- **Installation_Tracker**: The existing service that manages capability installation records in TinyDB

## Requirements

### Requirement 1: Cloud Provider Selection

**User Story:** As a user, I want to select a cloud provider for capability discovery, so that I can discover capabilities deployed in my target infrastructure.

#### Acceptance Criteria

1. WHEN a user initiates capability discovery THEN THE Discovery_Service SHALL display a cloud provider selection interface with AWS, Azure, and GCP options
2. WHEN AWS is selected THEN THE Discovery_Service SHALL proceed to AWS credential configuration
3. WHEN Azure or GCP is selected THEN THE Discovery_Service SHALL display a "Coming Soon" message and prevent further progression
4. THE Discovery_Service SHALL visually indicate AWS as the currently supported provider

### Requirement 2: AWS Authentication for Discovery

**User Story:** As a user, I want to authenticate with AWS using existing ADFS/SAML flows, so that I can securely access AWS accounts for capability discovery.

#### Acceptance Criteria

1. WHEN a user selects AWS for discovery THEN THE Discovery_Service SHALL present the existing ADFS/SAML authentication interface
2. WHEN valid ADFS credentials are provided THEN THE Discovery_Service SHALL obtain temporary AWS credentials via STS AssumeRoleWithSAML
3. WHEN authentication succeeds THEN THE Discovery_Service SHALL store the session for subsequent discovery operations
4. IF authentication fails THEN THE Discovery_Service SHALL display the specific error message and allow retry
5. WHEN AWS credentials expire during discovery THEN THE Discovery_Service SHALL prompt for re-authentication
6. THE Discovery_Service SHALL reuse existing AWS session if valid credentials are already available

### Requirement 3: Landing Zone Management

**User Story:** As a user, I want to manage multiple AWS accounts as landing zones, so that I can discover capabilities across my organization's infrastructure.

#### Acceptance Criteria

1. WHEN a user authenticates with AWS THEN THE Discovery_Service SHALL extract and display the account ID and account alias
2. WHEN a new account is discovered THEN THE Discovery_Service SHALL allow the user to save it as a named landing zone
3. WHEN viewing landing zones THEN THE Discovery_Service SHALL display all saved landing zones with account ID, alias, and last discovery timestamp
4. WHEN a user selects a landing zone THEN THE Discovery_Service SHALL initiate discovery for that specific AWS account
5. THE Discovery_Service SHALL persist landing zone configurations in TinyDB for future sessions
6. WHEN a user removes a landing zone THEN THE Discovery_Service SHALL delete the landing zone configuration but preserve discovered capability records

### Requirement 4: CloudFormation Stack Discovery

**User Story:** As a user, I want the system to automatically discover deployed capabilities by scanning CloudFormation stacks, so that I can see all capabilities regardless of who deployed them.

#### Acceptance Criteria

1. WHEN discovery is initiated for a landing zone THEN THE Discovery_Service SHALL call CloudFormation ListStacks API to retrieve all stacks
2. WHEN stacks are retrieved THEN THE Discovery_Service SHALL filter stacks matching the naming convention `{capability-name}-{environment}-{stack-type}`
3. WHEN a matching stack is found THEN THE Discovery_Service SHALL extract capability name, environment, and stack type from the stack name
4. WHEN parsing stack names THEN THE Discovery_Service SHALL recognize all valid stack types: backend-foundation, backend-iam-roles, backend-storage, backend-network, backend-service, backend-domain, frontend-global, frontend-cognito, frontend-regional
5. WHEN a capability has multiple stacks THEN THE Discovery_Service SHALL group them by capability name and environment
6. IF a stack name does not match the naming convention THEN THE Discovery_Service SHALL skip it without error
7. WHEN discovery completes THEN THE Discovery_Service SHALL report the count of capabilities discovered and stacks scanned

### Requirement 5: Capability Status Determination

**User Story:** As a user, I want to see the deployment status of discovered capabilities, so that I can understand the health of my deployments.

#### Acceptance Criteria

1. WHEN a capability is discovered THEN THE Discovery_Service SHALL determine its status from constituent stack statuses
2. WHEN all stacks are in CREATE_COMPLETE or UPDATE_COMPLETE state THEN THE Discovery_Service SHALL mark the capability as "Healthy"
3. WHEN any stack is in a FAILED or ROLLBACK state THEN THE Discovery_Service SHALL mark the capability as "Failed"
4. WHEN any stack is in an IN_PROGRESS state THEN THE Discovery_Service SHALL mark the capability as "In Progress"
5. WHEN stacks are partially deployed THEN THE Discovery_Service SHALL mark the capability as "Partial" and list missing stack types
6. WHEN determining status THEN THE Discovery_Service SHALL record the individual status of each stack for detailed viewing
7. THE Discovery_Service SHALL extract and store stack outputs for stacks in COMPLETE states

### Requirement 6: Environment and Region Extraction

**User Story:** As a user, I want discovered capabilities to show their environment and region, so that I can distinguish between dev, test, staging, and production deployments.

#### Acceptance Criteria

1. WHEN parsing stack names THEN THE Discovery_Service SHALL extract the environment segment (dev, test, stage, prod)
2. WHEN a stack is discovered THEN THE Discovery_Service SHALL record the AWS region where the stack exists
3. WHEN a capability spans multiple regions THEN THE Discovery_Service SHALL record all regions (e.g., us-east-1 for global stacks, target region for regional stacks)
4. WHEN displaying discovered capabilities THEN THE Discovery_Service SHALL show environment and primary region for each deployment
5. IF an environment value is not recognized THEN THE Discovery_Service SHALL use the extracted value as-is without validation error

### Requirement 7: TinyDB Synchronization

**User Story:** As a user, I want discovered capabilities to be stored in my local database, so that they appear in the Installed Capabilities section.

#### Acceptance Criteria

1. WHEN discovery completes THEN THE Discovery_Service SHALL create or update installation records in TinyDB via Installation_Tracker
2. WHEN a capability already exists in TinyDB THEN THE Discovery_Service SHALL update its status and metadata rather than create a duplicate
3. WHEN synchronizing THEN THE Discovery_Service SHALL use capability name, environment, and account ID as the unique identifier
4. WHEN a capability exists in TinyDB but not in AWS THEN THE Discovery_Service SHALL mark it as "Not Found in AWS" but preserve the record
5. WHEN creating installation records THEN THE Discovery_Service SHALL populate: capability_name, environment, region, account_id, status, and discovery_timestamp
6. THE Discovery_Service SHALL set the strategy field to "DISCOVERED" for capabilities found via discovery rather than deployment

### Requirement 8: Discovery Refresh

**User Story:** As a user, I want to manually refresh the capability list, so that I can sync with the current AWS state after changes.

#### Acceptance Criteria

1. WHEN viewing discovered capabilities THEN THE Discovery_Service SHALL display a "Refresh" button
2. WHEN refresh is triggered THEN THE Discovery_Service SHALL re-scan CloudFormation stacks for the selected landing zone
3. WHEN refresh completes THEN THE Discovery_Service SHALL update the UI with current capability states
4. WHEN refresh is in progress THEN THE Discovery_Service SHALL display a loading indicator and disable the refresh button
5. WHEN refresh completes THEN THE Discovery_Service SHALL update the "Last Discovery" timestamp for the landing zone
6. IF refresh fails due to credential expiration THEN THE Discovery_Service SHALL prompt for re-authentication

### Requirement 9: Discovery Timestamp Tracking

**User Story:** As a user, I want to see when capabilities were last discovered, so that I can understand how current the information is.

#### Acceptance Criteria

1. WHEN discovery completes THEN THE Discovery_Service SHALL record the timestamp in both landing zone and capability records
2. WHEN displaying landing zones THEN THE Discovery_Service SHALL show "Last Discovery: {timestamp}" for each
3. WHEN displaying discovered capabilities THEN THE Discovery_Service SHALL show "Discovered: {timestamp}" in the capability details
4. THE Discovery_Service SHALL format timestamps in the user's local timezone with date and time
5. WHEN a capability has never been discovered THEN THE Discovery_Service SHALL display "Never" or omit the timestamp field

### Requirement 10: Partial Deployment Handling

**User Story:** As a user, I want to see capabilities that are partially deployed, so that I can identify and resolve incomplete deployments.

#### Acceptance Criteria

1. WHEN a capability has some but not all expected stacks THEN THE Discovery_Service SHALL identify it as partially deployed
2. WHEN displaying partial deployments THEN THE Discovery_Service SHALL list which stack types are present and which are missing
3. WHEN a partial deployment is detected THEN THE Discovery_Service SHALL allow the user to proceed with update/completion deployment
4. THE Discovery_Service SHALL determine expected stacks based on capability requirements (frontend, backend, or both)
5. WHEN calculating partial status THEN THE Discovery_Service SHALL consider frontend-global, frontend-cognito, frontend-regional for frontend and backend-foundation, backend-iam-roles, backend-storage, backend-network, backend-service, backend-domain for backend

### Requirement 11: Multi-Account Unified View

**User Story:** As a user, I want to see capabilities from multiple AWS accounts in a unified view, so that I can manage my entire infrastructure from one place.

#### Acceptance Criteria

1. WHEN multiple landing zones are configured THEN THE Discovery_Service SHALL allow discovery across all of them
2. WHEN displaying capabilities THEN THE Discovery_Service SHALL indicate which landing zone (account) each capability belongs to
3. WHEN filtering capabilities THEN THE Discovery_Service SHALL allow filtering by landing zone
4. THE Discovery_Service SHALL maintain separate discovery timestamps per landing zone
5. WHEN a capability with the same name exists in multiple accounts THEN THE Discovery_Service SHALL display them as separate entries with account identifiers

### Requirement 12: Discovery Error Handling

**User Story:** As a user, I want clear error messages when discovery fails, so that I can troubleshoot and resolve issues.

#### Acceptance Criteria

1. IF AWS API calls fail THEN THE Discovery_Service SHALL display the specific AWS error message
2. IF insufficient IAM permissions prevent stack listing THEN THE Discovery_Service SHALL indicate which permissions are missing
3. IF network connectivity fails THEN THE Discovery_Service SHALL display a connection error and suggest retry
4. WHEN partial discovery succeeds THEN THE Discovery_Service SHALL report which regions or operations failed while showing successful results
5. THE Discovery_Service SHALL log all discovery errors for troubleshooting
6. IF rate limiting occurs THEN THE Discovery_Service SHALL implement exponential backoff and inform the user of the delay
