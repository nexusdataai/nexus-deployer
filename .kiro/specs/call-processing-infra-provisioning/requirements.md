# Requirements Document

## Introduction

This feature provides automated infrastructure provisioning for the call-processing capability. It creates all required AWS resources (DynamoDB tables, S3 buckets, Glue databases/tables), SSM parameters, and Secrets Manager secrets following the established naming convention (`call-processing-{env}-{resource}`). The feature includes comprehensive post-verification steps to ensure all resources are created correctly and accessible.

## Glossary

- **Provisioning_Service**: The backend service responsible for creating and managing AWS infrastructure resources
- **DynamoDB_Provisioner**: Component that creates and configures DynamoDB tables with proper schemas and GSIs
- **S3_Provisioner**: Component that creates and configures S3 buckets with proper structure
- **SSM_Provisioner**: Component that creates SSM Parameter Store parameters
- **Secrets_Provisioner**: Component that creates Secrets Manager secrets
- **Glue_Provisioner**: Component that creates Glue databases and tables
- **Verification_Service**: Component that validates all created resources exist and are accessible
- **Environment**: Deployment target (dev, stage, test, prod)
- **Naming_Convention**: Pattern `call-processing-{env}-{resource}` for AWS resources

## Requirements

### Requirement 1: DynamoDB Table Provisioning

**User Story:** As a deployment operator, I want to provision all required DynamoDB tables for the call-processing capability, so that the backend service has proper data storage.

#### Acceptance Criteria

1. WHEN the operator initiates DynamoDB provisioning for an environment, THE DynamoDB_Provisioner SHALL create the `call-processing-{env}-transformation-system` table with PK (HASH), SK (RANGE) key schema and GSI1 (GSI1PK, GSI1SK) global secondary index
2. WHEN the operator initiates DynamoDB provisioning for an environment, THE DynamoDB_Provisioner SHALL create the `call-processing-{env}-license` table with PK (HASH), SK (RANGE) key schema and status-index, holder-index, license-index GSIs
3. WHEN the operator initiates DynamoDB provisioning for an environment, THE DynamoDB_Provisioner SHALL create the `call-processing-{env}-wxcc-task-tracking` table with task_id (HASH) key schema
4. IF a DynamoDB table already exists with the same name, THEN THE DynamoDB_Provisioner SHALL skip creation and log that the table already exists
5. WHEN a table is created, THE DynamoDB_Provisioner SHALL wait for the table status to become ACTIVE before proceeding

### Requirement 2: S3 Bucket Provisioning

**User Story:** As a deployment operator, I want to provision all required S3 buckets for the call-processing capability, so that the service has proper object storage.

#### Acceptance Criteria

1. WHEN the operator initiates S3 provisioning for an environment, THE S3_Provisioner SHALL create the `call-processing-{env}-call-data` bucket for processed call data and Glue tables
2. WHEN the operator initiates S3 provisioning for an environment, THE S3_Provisioner SHALL create the `call-processing-{env}-wxcc-simulator` bucket for WXCC simulator data
3. WHEN the operator initiates S3 provisioning for an environment, THE S3_Provisioner SHALL create the `call-processing-{env}-journey-logs` bucket for journey execution logs
4. WHEN the operator initiates S3 provisioning for an environment, THE S3_Provisioner SHALL create the `call-processing-{env}-journey-reports` bucket for journey reports and artifacts
5. WHEN the `call-processing-{env}-call-data` bucket is created, THE S3_Provisioner SHALL create the folder structure: `call-data/`, `call-detail/`, `recordings/`, `transcripts/`, `athena-results/`
6. WHEN the `call-processing-{env}-wxcc-simulator` bucket is created, THE S3_Provisioner SHALL create the folder structure: `wxcc-simulator/tasks/`, `wxcc-simulator/recordings/`, `wxcc-simulator/sample-recordings/`
7. IF an S3 bucket already exists with the same name, THEN THE S3_Provisioner SHALL skip creation and log that the bucket already exists

### Requirement 3: SSM Parameter Store Provisioning

**User Story:** As a deployment operator, I want to provision all required SSM parameters for the call-processing capability, so that the service can retrieve configuration at runtime.

#### Acceptance Criteria

1. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create AWS configuration parameters under `/call-processing/{env}/aws/` including `region`
2. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create server configuration parameters under `/call-processing/{env}/server/` including `environment`, `log-level`, `min-workers`, `max-workers`, `timeout`
3. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create Cognito configuration parameters under `/call-processing/{env}/cognito/` including `region`, `user-pool-id`, `app-client-id`
4. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create WXCC configuration parameters under `/call-processing/{env}/wxcc/` including `enabled`, `bucket`, `prefix`, `org-id`
5. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create S3 configuration parameters under `/call-processing/{env}/s3/` including `recordings-bucket`, `journey-logs-bucket`, `journey-reports-bucket`
6. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create DynamoDB configuration parameters under `/call-processing/{env}/dynamodb/` including `transformation-table`, `license-table`, `wxcc-task-table`
7. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create Glue configuration parameters under `/call-processing/{env}/glue/` including `database`, `table`
8. WHEN the operator initiates SSM provisioning for an environment, THE SSM_Provisioner SHALL create CloudWatch configuration parameters under `/call-processing/{env}/cloudwatch/` including `log-group`, `stream-prefix`
9. IF an SSM parameter already exists with the same path, THEN THE SSM_Provisioner SHALL update the parameter value and log that the parameter was updated

### Requirement 4: Secrets Manager Provisioning

**User Story:** As a deployment operator, I want to provision all required secrets for the call-processing capability, so that sensitive configuration is securely stored.

#### Acceptance Criteria

1. WHEN the operator initiates secrets provisioning for an environment, THE Secrets_Provisioner SHALL create the `call-processing/{env}/api-keys` secret for API_KEY
2. WHEN the operator initiates secrets provisioning for an environment, THE Secrets_Provisioner SHALL create the `call-processing/{env}/wxcc` secret for WXCC_SIM_TOKEN
3. WHEN the operator initiates secrets provisioning for an environment, THE Secrets_Provisioner SHALL create the `call-processing/{env}/openai` secret for OPENAI_API_KEY
4. WHEN the operator initiates secrets provisioning for an environment, THE Secrets_Provisioner SHALL create the `call-processing/{env}/license` secret for LICENSE_PUBLIC_KEY and LICENSE_PRIVATE_KEY
5. WHEN the operator initiates secrets provisioning for an environment, THE Secrets_Provisioner SHALL create the `call-processing/{env}/anthropic` secret for CLAUDE_API_KEY and ANTHROPIC_API_KEY
6. WHEN the operator initiates secrets provisioning for an environment, THE Secrets_Provisioner SHALL create the `call-processing/{env}/github` secret for GITHUB_TOKEN
7. IF a secret already exists with the same name, THEN THE Secrets_Provisioner SHALL skip creation and log that the secret already exists
8. WHEN creating secrets, THE Secrets_Provisioner SHALL use placeholder values that indicate the secret needs to be updated with actual values

### Requirement 5: Glue Database and Table Provisioning

**User Story:** As a deployment operator, I want to provision the Glue database and tables for the call-processing capability, so that analytics queries can be run against call data.

#### Acceptance Criteria

1. WHEN the operator initiates Glue provisioning for an environment, THE Glue_Provisioner SHALL create the `call-processing-{env}-analytics` database
2. WHEN the operator initiates Glue provisioning for an environment, THE Glue_Provisioner SHALL create the `wxcc_calls` table in the analytics database with appropriate schema for call data
3. WHEN the Glue table is created, THE Glue_Provisioner SHALL configure it to read Parquet data from the `call-processing-{env}-call-data` bucket under the `call-data/` prefix
4. WHEN the Glue table is created, THE Glue_Provisioner SHALL configure partitioning by year, month, and day
5. IF the Glue database already exists, THEN THE Glue_Provisioner SHALL skip database creation and proceed with table creation

### Requirement 6: CloudWatch Log Group Provisioning

**User Story:** As a deployment operator, I want to provision CloudWatch log groups for the call-processing capability, so that application logs are properly collected.

#### Acceptance Criteria

1. WHEN the operator initiates CloudWatch provisioning for an environment, THE Provisioning_Service SHALL create the `/aws/call-processing/{env}` log group
2. WHEN the log group is created, THE Provisioning_Service SHALL set an appropriate retention policy (30 days for dev/test, 90 days for stage, 365 days for prod)
3. IF the log group already exists, THEN THE Provisioning_Service SHALL skip creation and log that the log group already exists

### Requirement 7: Post-Provisioning Verification

**User Story:** As a deployment operator, I want to verify all provisioned resources are correctly created and accessible, so that I can confirm the infrastructure is ready for deployment.

#### Acceptance Criteria

1. WHEN provisioning completes, THE Verification_Service SHALL verify all DynamoDB tables exist and are in ACTIVE status
2. WHEN provisioning completes, THE Verification_Service SHALL verify all S3 buckets exist and are accessible
3. WHEN provisioning completes, THE Verification_Service SHALL verify all SSM parameters exist and contain expected values
4. WHEN provisioning completes, THE Verification_Service SHALL verify all Secrets Manager secrets exist
5. WHEN provisioning completes, THE Verification_Service SHALL verify the Glue database and table exist
6. WHEN provisioning completes, THE Verification_Service SHALL verify the CloudWatch log group exists
7. WHEN verification completes, THE Verification_Service SHALL generate a comprehensive report listing all resources with their status (created, already-existed, failed)
8. IF any resource verification fails, THEN THE Verification_Service SHALL include the failure reason in the report and mark the overall provisioning as incomplete

### Requirement 8: Environment-Specific Configuration

**User Story:** As a deployment operator, I want to provision resources with environment-appropriate settings, so that each environment has proper configuration.

#### Acceptance Criteria

1. WHEN provisioning for the `dev` environment, THE Provisioning_Service SHALL use development-appropriate defaults (e.g., lower capacity, shorter retention)
2. WHEN provisioning for the `prod` environment, THE Provisioning_Service SHALL use production-appropriate defaults (e.g., higher capacity, longer retention, encryption enabled)
3. WHEN provisioning for any environment, THE Provisioning_Service SHALL apply the naming convention `call-processing-{env}-{resource}` consistently
4. THE Provisioning_Service SHALL support the following environments: `dev`, `stage`, `test`, `prod`

### Requirement 9: Idempotent Provisioning

**User Story:** As a deployment operator, I want provisioning to be idempotent, so that I can safely re-run provisioning without causing errors or duplicating resources.

#### Acceptance Criteria

1. WHEN provisioning is run multiple times for the same environment, THE Provisioning_Service SHALL produce the same end state
2. WHEN a resource already exists, THE Provisioning_Service SHALL not fail but instead log the existing resource and continue
3. WHEN provisioning completes, THE Provisioning_Service SHALL report which resources were created vs which already existed
4. FOR ALL provisioning operations, running provisioning twice in succession SHALL result in the second run reporting all resources as already-existed

### Requirement 10: Error Handling and Rollback

**User Story:** As a deployment operator, I want clear error handling during provisioning, so that I can understand and resolve any issues.

#### Acceptance Criteria

1. IF a resource creation fails, THEN THE Provisioning_Service SHALL log the specific error with resource name and failure reason
2. IF a critical resource fails to create, THEN THE Provisioning_Service SHALL halt provisioning and report the failure
3. WHEN an error occurs, THE Provisioning_Service SHALL provide actionable error messages indicating how to resolve the issue
4. THE Provisioning_Service SHALL support a dry-run mode that validates configuration without creating resources

### Requirement 11: Deployment Wizard API Integration

**User Story:** As a deployment operator using the wizard UI, I want infrastructure provisioning to be triggered automatically as part of the deployment flow, so that DynamoDB tables, S3 buckets, and other resources are created before the application is deployed.

#### Acceptance Criteria

1. WHEN the deployment wizard starts a deployment, THE Deployment_Service SHALL call the Provisioning_Orchestrator to provision infrastructure resources before deploying CloudFormation stacks
2. THE Provisioning_Service SHALL expose REST API endpoints for provisioning (`POST /api/provisioning/provision`), verification (`POST /api/provisioning/verify`), and dry-run (`POST /api/provisioning/dry-run`)
3. WHEN the API receives a provisioning request, THE Provisioning_Service SHALL accept environment, region, and optional AWS credentials parameters
4. WHEN provisioning is triggered via API, THE Provisioning_Service SHALL return a provisioning report with status of all resources (created, already-existed, failed)
5. WHEN the deployment wizard UI displays deployment progress, THE UI SHALL show infrastructure provisioning as a distinct stage before CloudFormation deployment
6. IF infrastructure provisioning fails, THEN THE Deployment_Service SHALL halt the deployment and report the failure to the user
7. WHEN provisioning completes successfully, THE Deployment_Service SHALL proceed with CloudFormation stack deployment

### Requirement 12: Provisioning Status and Progress Tracking

**User Story:** As a deployment operator, I want to see real-time progress of infrastructure provisioning, so that I can monitor the deployment status.

#### Acceptance Criteria

1. WHEN provisioning is in progress, THE Provisioning_Service SHALL emit progress updates for each resource type being provisioned
2. THE API SHALL support polling for provisioning status via `GET /api/provisioning/{provisioning_id}/status`
3. WHEN a resource is successfully provisioned, THE Provisioning_Service SHALL update the progress to reflect completion of that resource type
4. THE provisioning status response SHALL include: overall progress percentage, current stage, list of completed resources, list of pending resources, and any errors encountered
