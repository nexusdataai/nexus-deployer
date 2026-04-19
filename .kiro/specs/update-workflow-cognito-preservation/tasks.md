# Implementation Plan: Update Workflow Cognito Preservation

## Overview

This implementation plan breaks down the update workflow changes into discrete coding tasks. The implementation follows a bottom-up approach, starting with core services and building up to the orchestration layer. Python is used for the backend services, consistent with the existing codebase.

## Tasks

- [x] 1. Create Workflow Classification Components
  - [x] 1.1 Create WorkflowType enum and WorkflowClassification data model
    - Add `WorkflowType` enum with INSTALL and UPDATE values
    - Add `WorkflowClassification` dataclass with workflow_type, capability_name, environment, region, existing_stacks, strategy_selected, classification_timestamp, and reason fields
    - Create in `backend/app/models/workflow_classification.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.2 Implement WorkflowClassifier service
    - Create `WorkflowClassifier` class in `backend/app/services/workflow_classifier.py`
    - Implement `classify_workflow()` method that uses Stack Detection Service
    - Return INSTALL when no existing deployment found
    - Return INSTALL when user selects "Clean Deploy" strategy
    - Return UPDATE when user selects "Update Existing" strategy
    - Add logging for workflow classification with timestamp and capability details
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.3 Write property test for workflow classification
    - **Property 1: Workflow Classification Consistency**
    - Generate random deployment scenarios with various detection results and strategies
    - Verify classification follows the rules consistently
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4**

- [x] 2. Implement Cognito Preservation Service
  - [x] 2.1 Create CognitoOutputs and CognitoValidationResult data models
    - Add `CognitoOutputs` dataclass with user_pool_id, user_pool_client_id, user_pool_domain, region, admin_user_email
    - Add `CognitoValidationResult` dataclass with is_valid, user_pool_accessible, client_configured, user_count, error_message, remediation_steps
    - Create in `backend/app/models/cognito_models.py`
    - _Requirements: 2.3, 2.5, 11.1_

  - [x] 2.2 Implement CognitoPreservationService
    - Create `CognitoPreservationService` class in `backend/app/services/cognito_preservation_service.py`
    - Implement `get_existing_cognito_outputs()` to retrieve outputs from deployed Cognito stack
    - Implement `validate_user_pool()` to check User Pool accessibility and App Client configuration
    - Implement `should_preserve_cognito()` to determine preservation based on workflow type and user choice
    - _Requirements: 2.1, 2.3, 2.5, 2.6, 11.1, 11.2, 11.3_

  - [x] 2.3 Write property test for Cognito preservation logic
    - **Property 2: Cognito Stack Skip During Update**
    - Generate random UPDATE workflow configurations
    - Verify Cognito stack is excluded when include_cognito_update is false
    - **Validates: Requirements 2.1, 2.5, 2.6**

- [x] 3. Implement Cognito User Export Service
  - [x] 3.1 Create UserExportRecord and ExportResult data models
    - Add `UserExportRecord` dataclass with username, email, attributes, groups, enabled, status, created_at
    - Add `ExportResult` dataclass with success, export_path, user_count, export_timestamp, capability_name, environment, error_message
    - Create in `backend/app/models/cognito_models.py`
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 3.2 Implement CognitoUserExportService
    - Create `CognitoUserExportService` class in `backend/app/services/cognito_user_export_service.py`
    - Implement `list_users()` using Cognito list_users API with pagination
    - Implement `export_users()` to export all users to JSON file with timestamp and capability identifiers
    - Handle export failures and return appropriate error messages
    - _Requirements: 4.2, 4.3, 4.4, 4.5_

  - [x] 3.3 Write property test for user export
    - **Property 5: User Data Export Completeness**
    - Generate random user lists
    - Verify export includes all users with attributes
    - Verify export file naming includes timestamp and capability
    - **Validates: Requirements 4.2, 4.3, 4.4**

- [x] 4. Checkpoint - Core Services Complete
  - All core service tests pass.

- [x] 5. Implement Cognito Drift Detector
  - [x] 5.1 Create DriftItem and DriftDetectionResult data models
    - Add `DriftItem` dataclass with setting_name, template_value, deployed_value, category
    - Add `DriftDetectionResult` dataclass with has_drift, drift_items, detection_timestamp, error_message
    - Create in `backend/app/models/cognito_models.py`
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 5.2 Implement CognitoDriftDetector
    - Create `CognitoDriftDetector` class in `backend/app/services/cognito_drift_detector.py`
    - Implement `detect_drift()` to compare deployed Cognito with template
    - Compare password policy, MFA configuration, app client settings, custom attributes
    - Handle detection failures gracefully (don't block workflow)
    - _Requirements: 5.1, 5.2, 5.3, 5.5_

  - [x] 5.3 Write property test for drift detection
    - **Property 7: Drift Detection Coverage**
    - Generate random Cognito configurations
    - Verify all setting categories are compared
    - Verify failures don't block workflow
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5**

- [x] 6. Implement Stack Output Preserver
  - [x] 6.1 Create PreservedOutputs data model
    - Add `PreservedOutputs` dataclass with stack_name, outputs, retrieved_at, is_cognito_stack
    - Create in `backend/app/models/stack_outputs.py`
    - _Requirements: 6.1, 6.2_

  - [x] 6.2 Implement StackOutputPreserver
    - Create `StackOutputPreserver` class in `backend/app/services/stack_output_preserver.py`
    - Implement `preserve_all_outputs()` to retrieve outputs from all existing stacks
    - Implement `get_cognito_outputs()` to return preserved Cognito outputs
    - Implement `get_outputs_for_stack()` to return outputs for specific stack
    - Add logging for output preservation
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 6.3 Write property test for output preservation
    - **Property 3: Cognito Output Preservation**
    - Generate random stack configurations
    - Verify Cognito outputs are retrieved and available for dependent stacks
    - **Validates: Requirements 2.3, 2.4, 6.1, 6.2, 6.3, 6.4**

- [x] 7. Checkpoint - Supporting Services Complete
  - All supporting service tests pass.

- [x] 8. Implement Update Workflow Configuration
  - [x] 8.1 Create UpdateWorkflowConfig and UpdateConfig data models
    - Add `UpdateWorkflowConfig` dataclass with default_preserve_cognito, require_backup_before_cognito_update, enable_selective_updates, validate_cognito_before_update, validate_cognito_after_update, enable_drift_detection, enable_audit_trail
    - Add `UpdateConfig` dataclass with preserve_cognito, include_cognito_update, require_user_backup, selected_stacks
    - Create in `backend/app/models/update_config.py`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 8.2 Implement configuration loading and defaults
    - Add update workflow configuration to existing config system
    - Implement default application logic
    - Add configuration change logging
    - _Requirements: 10.4, 10.5_

  - [x] 8.3 Write property test for configuration application
    - **Property 11: Configuration Application**
    - Generate random configurations and overrides
    - Verify defaults are applied unless overridden
    - **Validates: Requirements 10.4**

- [x] 9. Implement Update Audit Trail
  - [x] 9.1 Create UpdateAuditRecord data model
    - Add `UpdateAuditRecord` dataclass with operation_id, operation_type, capability_name, environment, region, operator_identity, timestamp, stacks_updated, stacks_preserved, stacks_failed, cognito_preserved, user_data_exported, export_location, export_user_count, success, error_message, duration_seconds
    - Create in `backend/app/models/audit_models.py`
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 9.2 Implement audit trail recording
    - Add audit record creation to deployment state service
    - Implement per-stack action recording
    - Implement Cognito preservation recording
    - Implement export details recording
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [x] 9.3 Write property test for audit trail
    - **Property 13: Audit Trail Completeness**
    - Generate random update operations
    - Verify audit records contain all required fields
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**

- [x] 10. Implement Update Workflow Orchestrator
  - [x] 10.1 Create UpdateResult data model
    - Add `UpdateResult` dataclass with success, stacks_updated, stacks_preserved, stacks_failed, cognito_preserved, user_backup_path, error_message
    - Create in `backend/app/models/update_result.py`
    - _Requirements: 7.5, 8.2_

  - [x] 10.2 Implement UpdateWorkflowOrchestrator core logic
    - Create `UpdateWorkflowOrchestrator` class in `backend/app/services/update_workflow_orchestrator.py`
    - Implement `execute_update()` method with full workflow:
      1. Classify workflow
      2. Retrieve existing stack outputs
      3. Validate Cognito User Pool (if enabled)
      4. Optionally export user data
      5. Optionally detect drift
      6. Deploy stacks (skipping Cognito if preserving)
      7. Post-update validation
      8. Generate audit record
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.1, 5.1, 11.1, 11.4_

  - [x] 10.3 Implement selective stack update logic
    - Implement `get_stacks_to_update()` method
    - Validate dependencies for skipped stacks
    - Report required additional stacks if validation fails
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x] 10.4 Implement progress reporting
    - Add [PRESERVE] prefix for preserved stacks
    - Add [UPDATE] prefix for updated stacks
    - Generate completion summary with counts
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 10.5 Write property test for progress reporting
    - **Property 8: Progress Reporting Format**
    - Generate random update scenarios
    - Verify message format consistency
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

- [x] 11. Checkpoint - Orchestrator Complete
  - All orchestrator tests pass.

- [x] 12. Implement Failure Handling
  - [x] 12.1 Implement stack update failure handling
    - Halt further updates on failure
    - Report successful stacks before failure
    - Detect CloudFormation rollback status
    - Verify system consistency after rollback
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 12.2 Implement Cognito validation failure handling
    - Halt update if pre-validation fails
    - Report with remediation steps
    - Provide rollback guidance for post-validation failures
    - _Requirements: 11.5, 11.6_

  - [x] 12.3 Write property test for failure handling
    - **Property 9: Failure Handling and Halt**
    - Generate random failure scenarios
    - Verify updates halt on failure
    - Verify successful stacks are reported
    - **Validates: Requirements 8.1, 8.2, 8.4, 8.5**

- [x] 13. Integrate with Deployment Orchestrator
  - [x] 13.1 Modify DeploymentOrchestrator to use workflow classification
    - Add workflow classification at deployment start
    - Route to appropriate workflow (install or update)
    - Pass preserved outputs to dependent stacks
    - _Requirements: 1.1, 2.4, 6.3_

  - [x] 13.2 Modify CloudFormationService for update semantics
    - Ensure update_stack is used for Cognito when included
    - Skip Cognito stack when preserving
    - Use preserved outputs for parameters
    - _Requirements: 2.1, 3.5, 6.4_

  - [x] 13.3 Write property test for Cognito update inclusion
    - **Property 4: Cognito Update Inclusion**
    - Generate scenarios where user confirms Cognito update
    - Verify Cognito is included and update_stack is used
    - **Validates: Requirements 3.4, 3.5**

- [x] 14. Implement Frontend Update Options
  - [x] 14.1 Add update options to deployment wizard
    - Add Cognito preservation toggle
    - Add user data backup option
    - Add selective stack update UI
    - Display warnings for Cognito updates
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.6, 9.1_

  - [x] 14.2 Add drift detection display
    - Show drift summary when detected
    - Indicate when configuration is current
    - _Requirements: 5.3, 5.4_

  - [x] 14.3 Write property test for selective updates
    - **Property 10: Selective Update Validation**
    - Generate random stack selections
    - Verify only selected stacks are updated
    - Verify dependency validation
    - **Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.6**

- [x] 15. Implement Cognito Validation
  - [x] 15.1 Implement pre-update Cognito validation
    - Validate User Pool accessibility
    - Validate User Pool ID matches deployment state
    - Validate App Client configuration
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 15.2 Implement post-update Cognito validation
    - Perform validation after update completes
    - Report failures with rollback guidance
    - _Requirements: 11.4, 11.6_

  - [x] 15.3 Write property test for Cognito validation
    - **Property 12: Cognito Validation Completeness**
    - Generate random validation scenarios
    - Verify all validation checks are performed
    - Verify failure handling
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**

- [x] 16. Final Checkpoint - All Tests Pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify integration with existing deployment flow
  - Test end-to-end update workflow with Cognito preservation

## Notes

- All tasks including property-based tests are required for comprehensive coverage
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Unit tests validate specific examples and edge cases
- The implementation uses Python with hypothesis for property-based testing

