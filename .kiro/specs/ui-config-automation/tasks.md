# Implementation Plan: UI Config Automation

## Overview

This implementation plan creates a config generator that extracts API and Cognito configuration from CloudFormation stack outputs and uploads the generated `config.json` to the UI hosting S3 bucket. The implementation uses Bash scripts to integrate with the existing deployment workflow.

**Note:** The Python-based deployment system (`DeploymentOrchestrator`) has been updated to also generate config.json from stack outputs. See `backend/app/services/ui_config_generator.py` for the Python implementation.

## Tasks

- [x] 1. Create core library functions for stack output reading
  - [x] 1.1 Create `lib/stack-reader.sh` with stack output reading functions
    - Implement `read_stack_outputs()` to query CloudFormation stacks
    - Implement `get_api_config()` to extract API Gateway URL
    - Implement `get_cognito_config()` to extract Cognito configuration
    - Implement `get_frontend_config()` to extract S3 bucket and CloudFront distribution
    - Handle stack not found and incomplete state errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4_

  - [x] 1.2 Write property test for stack output extraction
    - **Property 1: Stack Output Extraction Completeness**
    - **Validates: Requirements 1.1, 1.2, 2.1, 2.2**

- [x] 2. Create config.json generation functions
  - [x] 2.1 Create `lib/config-generator.sh` with config building functions
    - Implement `build_config_json()` to construct the JSON structure
    - Implement `build_redirect_uris()` to construct OAuth redirect URIs
    - Implement `validate_config_json()` to verify JSON syntax
    - Implement `derive_stack_names()` to generate stack names from capability/environment
    - _Requirements: 3.1, 3.2, 3.3, 5.3_

  - [x] 2.2 Write property test for config generation schema validity
    - **Property 2: Config Generation Schema Validity**
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [x] 2.3 Write property test for stack name derivation
    - **Property 4: Stack Name Derivation Consistency**
    - **Validates: Requirements 5.3**

- [x] 3. Create S3 upload and backup functions
  - [x] 3.1 Create `lib/s3-uploader.sh` with S3 operations
    - Implement `check_config_exists()` to check for existing config.json
    - Implement `backup_existing_config()` to create timestamped backup
    - Implement `upload_config_to_s3()` with proper headers
    - Implement `invalidate_cloudfront_cache()` for cache invalidation
    - Handle S3 access errors and backup failures
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.2, 6.3, 6.4, 8.1, 8.2, 8.3, 8.4_

  - [x] 3.2 Write property test for S3 upload header correctness
    - **Property 3: S3 Upload Header Correctness**
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [x] 3.3 Write property test for backup creation
    - **Property 8: Backup Creation with Timestamp**
    - **Validates: Requirements 8.1, 8.2**

- [x] 4. Checkpoint - Ensure all library functions work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Create main config generator script
  - [x] 5.1 Create `scripts/generate-ui-config.sh` main script
    - Implement command-line argument parsing
    - Implement YAML configuration file loading
    - Implement dry-run mode logic
    - Implement main workflow orchestration
    - Add proper error handling and exit codes
    - _Requirements: 5.1, 5.2, 5.4, 7.1, 7.2, 7.3, 7.4_

  - [x] 5.2 Write property test for configuration input equivalence
    - **Property 5: Configuration Input Equivalence**
    - **Validates: Requirements 5.4**

  - [x] 5.3 Write property test for dry-run mode
    - **Property 7: Dry-Run Mode Non-Modification**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 5.4 Write property test for no-backup flag
    - **Property 9: No-Backup Flag Behavior**
    - **Validates: Requirements 8.3**

- [x] 6. Integrate with existing deployment workflow
  - [x] 6.1 Update `deploy-capability-layered.sh` to call config generator
    - Add `generate_ui_config()` function
    - Call after frontend deployment completes
    - Pass appropriate parameters from deployment context
    - Respect dry-run mode from parent script
    - _Requirements: 5.1_

  - [x] 6.2 Write property test for CloudFront invalidation
    - **Property 6: CloudFront Invalidation Path Correctness**
    - **Validates: Requirements 6.1, 6.2**

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks including property tests are required
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- Implementation uses Bash to match existing deployment scripts
