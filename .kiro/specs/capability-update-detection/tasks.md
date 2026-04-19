# Implementation Plan

## 1. Backend Data Models and Types

- [ ] 1.1 Create data models for stack detection
  - Create `backend/app/models/stack_detection.py` with Pydantic models
  - Implement `StackDetectionResult` model with all required fields
  - Implement `ExistingStackInfo` model for individual stack information
  - Implement `StackStatusAnalysis` model for stack state analysis
  - Implement `DeploymentStrategy` enum (CLEAN_DEPLOY, UPDATE_EXISTING)
  - Implement `StackDetectionRequest` model for API requests
  - _Requirements: 1.4, 7.4_

- [ ]* 1.2 Write property test for data model validation
  - **Property 21: Detection result schema validation**
  - **Validates: Requirements 7.4**

## 2. Stack Detection Service

- [ ] 2.1 Implement Stack Detection Service core functionality
  - Create `backend/app/services/stack_detection_service.py`
  - Implement `__init__` method accepting AWS credentials
  - Implement `detect_existing_stacks` method to query CloudFormation stacks
  - Query all stack types from STACK_ORDER for given capability/environment
  - Return `StackDetectionResult` with found stacks and metadata
  - Use existing CloudFormationDeploymentService.STACK_ORDER for stack types
  - Use existing CloudFormationDeploymentService.get_stack_name for naming
  - _Requirements: 1.1, 1.2, 1.3, 7.1, 7.2, 7.3_

- [ ] 2.2 Implement stack status analysis
  - Implement `analyze_stack_status` method
  - Identify updatable states (CREATE_COMPLETE, UPDATE_COMPLETE)
  - Identify failed states (ROLLBACK_COMPLETE, ROLLBACK_FAILED, DELETE_FAILED)
  - Return `StackStatusAnalysis` with recommendations
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] 2.3 Add error handling and logging
  - Handle AWS ClientError exceptions gracefully
  - Handle authentication and permission errors
  - Log detection operations with capability, environment, and region
  - Log each stack found with name, type, and status
  - _Requirements: 7.5, 8.1, 8.2_

- [ ]* 2.4 Write property test for detection completeness
  - **Property 1: Detection completeness**
  - **Validates: Requirements 1.2**

- [ ]* 2.5 Write property test for detection result schema
  - **Property 2: Detection result schema**
  - **Validates: Requirements 1.4**

- [ ]* 2.6 Write property test for AWS error handling
  - **Property 22: AWS API error handling**
  - **Validates: Requirements 7.5**

- [ ]* 2.7 Write property test for detection logging
  - **Property 23: Detection logging**
  - **Validates: Requirements 8.1**

- [ ]* 2.8 Write property test for stack discovery logging
  - **Property 24: Stack discovery logging**
  - **Validates: Requirements 8.2**

## 3. API Endpoint for Stack Detection

- [ ] 3.1 Create detection API endpoint
  - Add `POST /api/deployment/detect-stacks` endpoint in `backend/app/routers/deployment.py`
  - Accept `StackDetectionRequest` with capability_name, environment, region, aws_session_id
  - Retrieve AWS credentials from session manager using existing pattern
  - Call Stack Detection Service
  - Return `StackDetectionResult`
  - Handle errors and return appropriate HTTP status codes
  - _Requirements: 1.1, 1.5_

- [ ]* 3.2 Write unit tests for detection endpoint
  - Test successful detection with existing stacks
  - Test detection with no existing stacks
  - Test error handling for invalid inputs
  - Test error handling for AWS API failures
  - _Requirements: 1.1, 1.5_

## 4. Deployment Orchestrator Extensions

- [ ] 4.1 Add strategy-based deployment method
  - Extend `backend/app/services/deployment_orchestrator.py`
  - Implement `deploy_capability_with_strategy` method
  - Accept `DeploymentStrategy` parameter
  - Route to clean deployment or update deployment based on strategy
  - Reuse existing `deploy_capability` logic for normal deployment
  - _Requirements: 3.1, 4.1_

- [ ] 4.2 Implement clean deployment flow
  - When strategy is CLEAN_DEPLOY, invoke existing cleanup_service first
  - Cleanup service already deletes stacks in reverse STACK_ORDER
  - Cleanup service already waits for each deletion to complete
  - Cleanup service already logs operations
  - After cleanup completes, call existing `deploy_capability` method
  - Handle deletion failures by halting deployment
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 4.3 Implement update deployment flow
  - When strategy is UPDATE_EXISTING, call existing `deploy_capability` method
  - CloudFormationService already handles update vs create logic
  - CloudFormationService already preserves stack outputs
  - CloudFormationService already handles "No updates to perform" gracefully
  - Ensure proper logging of update operations
  - Handle update failures by halting deployment
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [ ]* 4.4 Write property test for cleanup invocation
  - **Property 6: Clean deployment invokes cleanup**
  - **Validates: Requirements 3.1**

- [ ]* 4.5 Write property test for deployment after cleanup
  - **Property 9: Deployment proceeds after cleanup**
  - **Validates: Requirements 3.4**

- [ ]* 4.6 Write property test for cleanup failure handling
  - **Property 10: Cleanup failure halts deployment**
  - **Validates: Requirements 3.5**

- [ ]* 4.7 Write property test for update operations
  - **Property 12: Update uses update operations**
  - **Validates: Requirements 4.1**

- [ ]* 4.8 Write property test for update failure handling
  - **Property 14: Update failure halts deployment**
  - **Validates: Requirements 4.5**

## 5. Frontend Type Definitions

- [ ] 5.1 Add TypeScript types for stack detection
  - Update `frontend/src/types/wizard.ts`
  - Add `STRATEGY_SELECTION` to `WizardStep` enum (after PERMISSION_VERIFICATION)
  - Create `StackDetectionResult` interface
  - Create `ExistingStackInfo` interface
  - Create `StackStatusAnalysis` interface
  - Create `DeploymentStrategy` enum
  - _Requirements: 2.1, 2.2_

- [ ] 5.2 Extend wizard state types
  - Add `detectionResult` field to `WizardState` interface
  - Add `selectedStrategy` field to `WizardState` interface
  - _Requirements: 2.6_

## 6. Frontend API Service

- [ ] 6.1 Add detection API call
  - Update `frontend/src/services/api.ts`
  - Implement `detectExistingStacks` function
  - Call `POST /api/deployment/detect-stacks` endpoint
  - Return `StackDetectionResult`
  - Handle errors appropriately
  - _Requirements: 1.1_

## 7. Wizard Context Updates

- [ ] 7.1 Extend wizard context with detection state
  - Update `frontend/src/context/WizardContext.tsx`
  - Add `detectionResult` to initial wizard state
  - Add `selectedStrategy` to initial wizard state
  - Implement `setDetectionResult` method
  - Implement `setSelectedStrategy` method
  - Update `goToNextStep` and `goToPreviousStep` to include STRATEGY_SELECTION in step order
  - _Requirements: 2.6, 6.2_

- [ ]* 7.2 Write property test for strategy selection persistence
  - **Property 5: Strategy selection persistence**
  - **Validates: Requirements 2.6**

- [ ]* 7.3 Write property test for strategy selection logging
  - **Property 25: Strategy selection logging**
  - **Validates: Requirements 8.3**

## 8. Strategy Selection UI Component

- [ ] 8.1 Create StrategySelection component
  - Create `frontend/src/components/StrategySelection.tsx`
  - Accept `detectionResult` prop
  - Display capability name, environment, region, and stack count
  - Show two strategy options: "Clean and Redeploy" and "Update Existing"
  - Include warning for "Clean and Redeploy" about data loss
  - Include information for "Update Existing" about preservation
  - Handle user selection and call `onStrategySelected` callback
  - Handle cancellation and call `onCancel` callback
  - Use consistent styling with existing wizard components (similar to PermissionVerification)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [ ] 8.2 Add failed stack warnings to UI
  - Display warning badges for stacks in failed states
  - Show recommended actions for failed stacks
  - Disable "Update Existing" option when failed stacks are present
  - _Requirements: 5.4, 5.6_

- [ ]* 8.3 Write property test for dialog presentation
  - **Property 3: Strategy dialog presentation**
  - **Validates: Requirements 2.1**

- [ ]* 8.4 Write property test for dialog information completeness
  - **Property 4: Strategy dialog information completeness**
  - **Validates: Requirements 2.2**

## 9. Wizard Flow Integration

- [ ] 9.1 Add detection step after permission verification
  - Update `frontend/src/components/WizardShell.tsx`
  - After permission verification completes successfully, call detection API
  - Store detection result in wizard context using `setDetectionResult`
  - If stacks found (`has_existing_stacks: true`), navigate to STRATEGY_SELECTION step
  - If no stacks found, skip directly to DEPLOYMENT_EXECUTION step
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] 9.2 Integrate StrategySelection component into wizard
  - Add STRATEGY_SELECTION case to wizard step rendering in WizardShell
  - Render StrategySelection component with detection result from context
  - Handle strategy selection by storing in context and proceeding to DEPLOYMENT_EXECUTION
  - Handle cancellation by navigating back to PERMISSION_VERIFICATION
  - _Requirements: 2.6, 2.7, 6.4, 6.5_

- [ ] 9.3 Pass strategy to deployment execution
  - Update DeploymentExecution component to read selected strategy from context
  - Pass strategy to backend deployment API in deployment request
  - _Requirements: 3.1, 4.1_

- [ ]* 9.4 Write property test for detection timing
  - **Property 19: Detection timing in workflow**
  - **Validates: Requirements 6.1**

- [ ]* 9.5 Write property test for strategy step insertion
  - **Property 20: Strategy step insertion**
  - **Validates: Requirements 6.2**

## 10. Deployment Service Integration

- [ ] 10.1 Update deployment models to accept strategy
  - Modify `backend/app/models/deployment.py`
  - Add `deployment_strategy` field to `DeploymentRequest` model (Optional[str])
  - Default to None for backward compatibility
  - _Requirements: 3.1, 4.1_

- [ ] 10.2 Update deployment service to use strategy
  - Modify `backend/app/services/deployment_service.py`
  - In deployment execution method, check if strategy is provided
  - If strategy provided, call `deploy_capability_with_strategy` on orchestrator
  - If no strategy, call existing `deploy_capability` method (backward compatible)
  - _Requirements: 3.1, 4.1_

## 11. Error Handling and Logging

- [ ] 11.1 Add comprehensive error logging
  - Log all detection operations with context in Stack Detection Service
  - Log strategy selections with timestamps in deployment service
  - Log deployment operations (clean/update) with results in orchestrator
  - Log errors with detailed context throughout
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ]* 11.2 Write property test for error logging
  - **Property 28: Error logging**
  - **Validates: Requirements 8.6**

## 12. Documentation

- [ ] 12.1 Update API documentation
  - Document new `/api/deployment/detect-stacks` endpoint
  - Document updated deployment request with strategy field
  - Add examples for detection and strategy selection
  - _Requirements: All_

- [ ] 12.2 Add inline code documentation
  - Add docstrings to all new classes and methods
  - Add comments explaining complex logic
  - Document integration points with existing services
  - _Requirements: All_

## 13. Final Checkpoint

- [ ] 13.1 Ensure all tests pass
  - Run all unit tests
  - Run all property-based tests
  - Verify end-to-end flow manually
  - Ensure all tests pass, ask the user if questions arise
  - _Requirements: All_
