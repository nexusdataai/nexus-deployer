# Requirements Document

## Introduction

This feature automates the generation and deployment of the UI configuration file (`config.json`) as part of the nexus-deployer automation workflow. The UI application reads API and Cognito configuration from `config.json` hosted in S3. This feature extracts the necessary configuration values from CloudFormation stack outputs (API Gateway URL, Cognito User Pool details) and creates/updates the `config.json` file in the S3 bucket where the UI is hosted.

## Glossary

- **Config_Generator**: The component responsible for extracting stack outputs and generating the config.json file
- **Stack_Output_Reader**: The component that reads CloudFormation stack outputs for API and Cognito stacks
- **S3_Config_Uploader**: The component that uploads the generated config.json to the UI hosting S3 bucket
- **Config_Schema**: The JSON structure containing API and Cognito configuration required by the UI
- **API_Stack**: The CloudFormation stack that deploys the backend API Gateway
- **Cognito_Stack**: The CloudFormation stack that deploys the Cognito User Pool and Client
- **UI_Hosting_Bucket**: The S3 bucket where the UI static files and config.json are hosted

## Requirements

### Requirement 1: Extract API Configuration from Stack Outputs

**User Story:** As a deployment operator, I want the automation to extract API Gateway URL from CloudFormation stack outputs, so that the UI can be configured to communicate with the correct backend API.

#### Acceptance Criteria

1. WHEN the Config_Generator runs, THE Stack_Output_Reader SHALL query the API stack for the API Gateway endpoint URL
2. WHEN the API stack output contains the base URL, THE Config_Generator SHALL extract and store the `api.baseUrl` value
3. IF the API stack does not exist or is not in a complete state, THEN THE Config_Generator SHALL report an error with the stack name and status
4. IF the API Gateway URL output is missing from the stack, THEN THE Config_Generator SHALL report a descriptive error indicating the missing output key

### Requirement 2: Extract Cognito Configuration from Stack Outputs

**User Story:** As a deployment operator, I want the automation to extract Cognito User Pool details from CloudFormation stack outputs, so that the UI can authenticate users against the correct identity provider.

#### Acceptance Criteria

1. WHEN the Config_Generator runs, THE Stack_Output_Reader SHALL query the Cognito stack for User Pool ID, Client ID, Domain, and Region
2. WHEN the Cognito stack outputs are available, THE Config_Generator SHALL extract and store:
   - `cognito.userPoolId` from the UserPoolId output
   - `cognito.clientId` from the UserPoolClientId output
   - `cognito.domain` from the UserPoolDomain output
   - `cognito.region` from the deployment region
3. IF the Cognito stack does not exist or is not in a complete state, THEN THE Config_Generator SHALL report an error with the stack name and status
4. IF any required Cognito output is missing, THEN THE Config_Generator SHALL report a descriptive error indicating which output key is missing

### Requirement 3: Generate Config.json with Complete Schema

**User Story:** As a deployment operator, I want the automation to generate a complete config.json file with all required fields, so that the UI application can function correctly.

#### Acceptance Criteria

1. WHEN all stack outputs are successfully extracted, THE Config_Generator SHALL create a config.json with the following structure:
   - `version`: Configuration version string
   - `api.baseUrl`: API Gateway endpoint URL
   - `api.timeout`: Request timeout in milliseconds (default: 30000)
   - `gateway.apiKey`: Gateway API key (if applicable)
   - `dataSource`: Data source type (default: "api")
   - `enableFallback`: Fallback mode flag (default: true)
   - `cognito.region`: AWS region
   - `cognito.userPoolId`: Cognito User Pool ID
   - `cognito.clientId`: Cognito App Client ID
   - `cognito.domain`: Cognito hosted UI domain
   - `cognito.redirectSignIn`: OAuth redirect URI for sign-in
   - `cognito.redirectSignOut`: OAuth redirect URI for sign-out
2. WHEN generating redirect URIs, THE Config_Generator SHALL construct them using the frontend domain from stack outputs or configuration
3. THE Config_Generator SHALL validate that the generated JSON is syntactically valid before proceeding

### Requirement 4: Upload Config.json to S3 Hosting Bucket

**User Story:** As a deployment operator, I want the automation to upload the generated config.json to the UI hosting S3 bucket, so that the deployed UI can access the configuration.

#### Acceptance Criteria

1. WHEN the config.json is generated successfully, THE S3_Config_Uploader SHALL upload it to the UI hosting S3 bucket at the path `/config.json`
2. WHEN uploading, THE S3_Config_Uploader SHALL set the content-type header to `application/json`
3. WHEN uploading, THE S3_Config_Uploader SHALL set cache-control headers to prevent caching (`no-cache, no-store, must-revalidate`)
4. IF the S3 upload fails, THEN THE S3_Config_Uploader SHALL report the error with bucket name and error details
5. WHEN the upload succeeds, THE S3_Config_Uploader SHALL log the S3 URI of the uploaded config.json

### Requirement 5: Integrate with Existing Deployment Workflow

**User Story:** As a deployment operator, I want the config.json generation to be integrated into the existing deployment workflow, so that it runs automatically after frontend and Cognito stacks are deployed.

#### Acceptance Criteria

1. WHEN the frontend deployment completes successfully, THE Config_Generator SHALL automatically execute as part of the deployment workflow
2. THE Config_Generator SHALL accept configuration parameters for:
   - API stack name or naming pattern
   - Cognito stack name or naming pattern
   - UI hosting S3 bucket name
   - Environment name (dev, stage, prod)
   - Capability name
3. WHEN stack names are not explicitly provided, THE Config_Generator SHALL derive them using the naming convention: `{capability-name}-{environment}-{stack-type}`
4. THE Config_Generator SHALL support both command-line parameters and YAML configuration file input

### Requirement 6: Support CloudFront Cache Invalidation

**User Story:** As a deployment operator, I want the automation to invalidate CloudFront cache for config.json after upload, so that users immediately receive the updated configuration.

#### Acceptance Criteria

1. WHEN config.json is successfully uploaded to S3, THE S3_Config_Uploader SHALL create a CloudFront invalidation for `/config.json`
2. WHEN creating the invalidation, THE S3_Config_Uploader SHALL identify the CloudFront distribution from the frontend stack outputs
3. IF CloudFront distribution ID is not available, THEN THE S3_Config_Uploader SHALL log a warning and skip invalidation
4. WHEN the invalidation is created, THE S3_Config_Uploader SHALL log the invalidation ID for tracking

### Requirement 7: Provide Dry-Run Mode

**User Story:** As a deployment operator, I want to preview the generated config.json without uploading it, so that I can verify the configuration before deployment.

#### Acceptance Criteria

1. WHEN the `--dry-run` flag is provided, THE Config_Generator SHALL generate and display the config.json content without uploading
2. WHEN in dry-run mode, THE Config_Generator SHALL validate all stack outputs are accessible
3. WHEN in dry-run mode, THE Config_Generator SHALL verify S3 bucket exists and is accessible
4. THE Config_Generator SHALL clearly indicate when running in dry-run mode in its output

### Requirement 8: Handle Existing Config.json

**User Story:** As a deployment operator, I want the automation to handle existing config.json files appropriately, so that I can choose to preserve or override existing configurations.

#### Acceptance Criteria

1. WHEN config.json already exists in the S3 bucket, THE S3_Config_Uploader SHALL backup the existing file before overwriting
2. WHEN backing up, THE S3_Config_Uploader SHALL copy the existing config.json to `config.json.backup` with a timestamp suffix
3. WHEN the `--no-backup` flag is provided, THE S3_Config_Uploader SHALL skip the backup step
4. IF the backup operation fails, THEN THE S3_Config_Uploader SHALL report a warning but continue with the upload
