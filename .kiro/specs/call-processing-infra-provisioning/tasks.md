# Implementation Plan: Call Processing Infrastructure Provisioning

## Overview

This implementation plan creates a Python-based infrastructure provisioning system for the call-processing capability. The system provisions DynamoDB tables, S3 buckets, SSM parameters, Secrets Manager secrets, Glue databases/tables, and CloudWatch log groups following the established naming convention. Implementation uses boto3 for AWS interactions and hypothesis for property-based testing.

## Tasks

- [x] 1. Set up project structure and core data models
  - Create directory structure under `backend/app/services/infra_provisioning/`
  - Define core data models (ResourceType, ResourceStatus, VerificationResult, etc.)
  - Define environment configuration dataclass with defaults
  - Create ResourceNaming utility class
  - _Requirements: 8.3, 8.4_

- [x] 2. Implement DynamoDB Provisioner
  - [x] 2.1 Create DynamoDBProvisioner class with table creation methods
    - Implement `create_transformation_system_table()` with PK/SK schema and GSI1
    - Implement `create_license_table()` with PK/SK schema and 3 GSIs
    - Implement `create_wxcc_task_tracking_table()` with task_id hash key
    - Implement `table_exists()` and `wait_for_table_active()` helper methods
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 2.2 Write property test for DynamoDB table creation
    - **Property 1: DynamoDB Table Creation Completeness**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.5**

- [x] 3. Implement S3 Provisioner
  - [x] 3.1 Create S3Provisioner class with bucket creation methods
    - Implement `create_call_data_bucket()` with folder structure
    - Implement `create_wxcc_simulator_bucket()` with folder structure
    - Implement `create_journey_logs_bucket()` and `create_journey_reports_bucket()`
    - Implement `bucket_exists()` and `create_folder_structure()` helper methods
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.2 Write property test for S3 bucket creation
    - **Property 2: S3 Bucket Creation Completeness**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

- [x] 4. Implement SSM Parameter Provisioner
  - [x] 4.1 Create SSMProvisioner class with parameter creation methods
    - Implement `create_all_parameters()` orchestration method
    - Implement `create_parameter()` for individual parameter creation/update
    - Implement getter methods for each category (aws, server, cognito, wxcc, s3, dynamodb, glue, cloudwatch)
    - Handle parameter update when value differs
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 4.2 Write property test for SSM parameter creation
    - **Property 3: SSM Parameter Creation Completeness**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

- [x] 5. Implement Secrets Manager Provisioner
  - [x] 5.1 Create SecretsProvisioner class with secret creation methods
    - Implement `create_all_secrets()` orchestration method
    - Implement `create_secret()` for individual secret creation
    - Implement `secret_exists()` helper method
    - Implement `get_placeholder_secrets()` for default placeholder values
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 5.2 Write property test for secrets creation
    - **Property 4: Secrets Creation Completeness**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8**

- [x] 6. Implement Glue Provisioner
  - [x] 6.1 Create GlueProvisioner class with database and table creation
    - Implement `create_database()` for analytics database
    - Implement `create_wxcc_calls_table()` with Parquet format and partitioning
    - Implement `database_exists()` and `table_exists()` helper methods
    - Configure table to read from call-data bucket
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.2 Write property test for Glue resource creation
    - **Property 5: Glue Resource Creation Completeness**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

- [x] 7. Implement CloudWatch Provisioner
  - [x] 7.1 Create CloudWatchProvisioner class with log group creation
    - Implement `create_log_group()` with environment-specific retention
    - Implement `log_group_exists()` helper method
    - Implement `get_retention_days()` based on environment
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 7.2 Write property test for CloudWatch log group creation
    - **Property 6: CloudWatch Log Group Creation with Correct Retention**
    - **Validates: Requirements 6.1, 6.2**

- [x] 8. Checkpoint - Ensure all provisioner tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement Provisioning Orchestrator
  - [x] 9.1 Create ProvisioningOrchestrator class
    - Implement `__init__()` with environment, region, and dry_run parameters
    - Implement `provision_all()` to orchestrate all provisioners
    - Implement individual provisioning methods (provision_dynamodb, provision_s3, etc.)
    - Implement dry-run mode that validates without creating resources
    - _Requirements: 8.1, 8.2, 10.4_

  - [x] 9.2 Write property test for provisioning idempotency
    - **Property 7: Provisioning Idempotency**
    - **Validates: Requirements 1.4, 2.7, 4.7, 5.5, 6.3, 9.1, 9.2, 9.3, 9.4**

  - [x] 9.3 Write property test for dry-run mode
    - **Property 11: Dry-Run Mode Safety**
    - **Validates: Requirements 10.4**

- [x] 10. Implement Verification Service
  - [x] 10.1 Create VerificationService class
    - Implement `verify_all()` to verify all resource types
    - Implement individual verification methods for each resource type
    - Generate comprehensive verification report
    - Include failure reasons for any failed verifications
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

  - [x] 10.2 Write property test for verification completeness
    - **Property 9: Verification Report Completeness**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8**

- [x] 11. Implement Error Handling
  - [x] 11.1 Create custom exception classes
    - Implement ProvisioningError base class
    - Implement ResourceCreationError, ResourceVerificationError
    - Implement PermissionError with required permission info
    - Implement TimeoutError for resource state timeouts
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 11.2 Add error handling to all provisioners
    - Wrap AWS API calls with try/except
    - Log specific errors with resource name and failure reason
    - Halt on critical failures, continue on recoverable errors
    - _Requirements: 10.1, 10.2_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement CLI Interface
  - [x] 13.1 Create CLI entry point
    - Add argparse-based CLI with subcommands (provision, verify, dry-run)
    - Support --environment flag for target environment
    - Support --region flag for AWS region
    - Support --resource-type flag to provision specific resources only
    - Output JSON or human-readable reports
    - _Requirements: 8.1, 8.2, 8.4_

- [x] 14. Write property test for naming convention
  - [x] 14.1 Write property test for naming convention consistency
    - **Property 10: Naming Convention Consistency**
    - **Validates: Requirements 8.3**

- [x] 15. Write property test for SSM parameter update
  - [x] 15.1 Write property test for SSM parameter update behavior
    - **Property 8: SSM Parameter Update Behavior**
    - **Validates: Requirements 3.9**

- [x] 16. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Implement Provisioning API Router
  - [x] 17.1 Create provisioning API router with endpoints
    - Create `backend/app/routers/provisioning.py` with FastAPI router
    - Implement `POST /api/provisioning/provision` endpoint
    - Implement `POST /api/provisioning/verify` endpoint
    - Implement `POST /api/provisioning/dry-run` endpoint
    - Implement `GET /api/provisioning/{provisioning_id}/status` endpoint
    - Add request/response models (ProvisioningRequest, ProvisioningStatusResponse)
    - _Requirements: 11.2, 11.3, 11.4_

  - [x] 17.2 Add background task support for async provisioning
    - Implement in-memory storage for provisioning jobs
    - Add background task to run provisioning asynchronously
    - Implement progress tracking with resource-level updates
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

  - [x] 17.3 Register provisioning router in main app
    - Update `backend/app/main.py` to include provisioning router
    - _Requirements: 11.2_

- [x] 18. Integrate Provisioning into Deployment Service
  - [x] 18.1 Add infrastructure provisioning stage to deployment flow
    - Update `DeploymentStage` enum to include `INFRASTRUCTURE_PROVISIONING`
    - Add `_provision_infrastructure()` method to DeploymentService
    - Call provisioning before CloudFormation deployment in `_execute_deployment()`
    - _Requirements: 11.1, 11.6, 11.7_

  - [x] 18.2 Add provisioning progress logging
    - Log progress for each resource type (DynamoDB, S3, SSM, etc.)
    - Update deployment progress percentage to include provisioning stage
    - _Requirements: 12.1, 12.3_

  - [x] 18.3 Handle provisioning failures
    - Halt deployment if provisioning fails
    - Report specific resource failures to user
    - _Requirements: 11.6_

- [x] 19. Write integration tests for API and deployment flow
  - [x] 19.1 Write tests for provisioning API endpoints
    - Test provision endpoint creates all resources
    - Test verify endpoint returns accurate status
    - Test dry-run endpoint doesn't create resources
    - Test status endpoint returns progress
    - _Requirements: 11.2, 11.3, 11.4, 12.2_

  - [x] 19.2 Write tests for deployment service integration
    - Test deployment calls provisioning before CloudFormation
    - Test deployment halts on provisioning failure
    - Test deployment proceeds after successful provisioning
    - _Requirements: 11.1, 11.6, 11.7_

- [x] 20. Checkpoint - Ensure API integration tests pass
  - All tests pass (19 tests total: 10 deployment integration + 9 API tests)

## Notes

- Tasks 1-16 are complete (core provisioning implementation)
- Tasks 17-20 are new (API and deployment wizard integration)
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using hypothesis library
- Unit tests validate specific examples and edge cases
- Integration tests should use LocalStack for AWS service mocking
- All provisioners should be idempotent - safe to run multiple times
- The provisioning API enables the deployment wizard to trigger infrastructure creation
- Infrastructure provisioning runs BEFORE CloudFormation stack deployment
