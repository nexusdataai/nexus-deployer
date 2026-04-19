# Implementation Plan

- [x] 1. Enhance stack detection data models


  - [x] 1.1 Add new fields to ExistingStackInfo model


    - Add `classification` field (updatable/failed/in_progress)
    - Add `status_reason` field for CloudFormation status reason
    - Add `created_at` and `last_updated_at` timestamp fields
    - _Requirements: 1.4, 4.4_

  - [x] 1.2 Add new fields to StackDetectionResult model


    - Add `recommended_strategy` field (Optional[DeploymentStrategy])
    - Add `recommendation_reason` field (str)
    - Add `has_in_progress_stacks` field (bool)
    - _Requirements: 3.5, 4.1, 4.2, 4.3_

  - [x] 1.3 Create stack state classification constants


    - Define UPDATABLE_STATES set (CREATE_COMPLETE, UPDATE_COMPLETE)
    - Define FAILED_STATES set (ROLLBACK_COMPLETE, UPDATE_ROLLBACK_COMPLETE, DELETE_FAILED, CREATE_FAILED)
    - Define IN_PROGRESS_STATES set (all *_IN_PROGRESS states)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 1.4 Create expected stack types configuration


    - Define FRONTEND_STACKS list with region mapping
    - Define BACKEND_STACKS list with region mapping
    - Map frontend-global to us-east-1, others to target region
    - _Requirements: 1.2, 5.1, 5.2_

- [x] 2. Implement CloudFormation stack querying


  - [x] 2.1 Add CloudFormation client initialization

    - Accept optional credentials parameter
    - Create boto3 CloudFormation client with credentials
    - Support multi-region client creation
    - _Requirements: 5.3, 6.1, 6.2, 6.3_

  - [x] 2.2 Implement _query_cloudformation_stack method

    - Call describe_stacks() for specific stack name
    - Handle ResourceNotFoundException (stack not found) gracefully
    - Extract stack name, status, status_reason, timestamps
    - Return None if stack doesn't exist (not an error)
    - Log errors but don't crash
    - _Requirements: 1.1, 1.3, 1.4, 1.5_

  - [x] 2.3 Implement _classify_stack_state method

    - Check if status in UPDATABLE_STATES → return "updatable"
    - Check if status in FAILED_STATES → return "failed"
    - Check if status in IN_PROGRESS_STATES → return "in_progress"
    - Handle unknown statuses gracefully
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 2.4 Implement multi-region stack detection

    - Determine correct region for each stack type
    - Query frontend-global stacks in us-east-1
    - Query regional stacks in target region
    - Aggregate results from multiple regions
    - Handle region-specific errors gracefully
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 3. Implement decision tree logic

  - [x] 3.1 Implement _recommend_strategy method

    - Check if no stacks exist → UPDATE_EXISTING, "First deployment"
    - Check if any stack in progress → None, "Wait for: [stacks]"
    - Check if any stack failed → CLEAN_DEPLOY, "Failed stacks: [stacks]"
    - Check if all updatable → UPDATE_EXISTING, "All stacks stable"
    - Generate human-readable reasoning with stack details
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 3.2 Implement recommendation reasoning generation

    - List specific stack names in reasoning
    - Include stack states for failed stacks
    - Prioritize failed stacks over in-progress in display
    - Format reasoning for user readability
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 4. Update StackDetectionService.detect_existing_stacks

  - [x] 4.1 Add credentials parameter (optional, backward compatible)

    - Accept credentials dict parameter
    - Fall back to existing behavior if not provided
    - _Requirements: 7.1, 7.2_

  - [x] 4.2 Query CloudFormation for each expected stack

    - Iterate through expected stack types
    - Call _query_cloudformation_stack for each
    - Build list of ExistingStackInfo objects
    - Handle errors per-stack, continue with others
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 4.3 Classify each stack and populate fields

    - Call _classify_stack_state for each stack
    - Set is_updatable based on classification
    - Populate all ExistingStackInfo fields
    - Mark non-existent stacks as "updatable"
    - _Requirements: 2.8, 1.3_

  - [x] 4.4 Apply decision tree and generate recommendation

    - Call _recommend_strategy with all stacks
    - Set recommended_strategy field
    - Set recommendation_reason field
    - Set has_failed_stacks and has_in_progress_stacks flags
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 4.5 Handle errors gracefully

    - Catch CloudFormation API errors
    - Return partial results if available
    - Populate error_message field
    - Don't crash on credential errors
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 5. Create API endpoint for stack detection


  - [x] 5.1 Create StackDetectionRequest model


    - Add capability_name field
    - Add environment field
    - Add region field
    - Add aws_session_id field (for credentials)
    - _Requirements: 7.3_

  - [x] 5.2 Implement POST /api/deployment/detect-stacks endpoint


    - Accept StackDetectionRequest
    - Retrieve AWS credentials from session manager
    - Call StackDetectionService.detect_existing_stacks
    - Return StackDetectionResult
    - Handle authentication errors
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 6. Update frontend StrategySelection component


  - [x] 6.1 Add stack detection API call

    - Call /api/deployment/detect-stacks on mount
    - Pass capability_name, environment, region, aws_session_id
    - Handle loading state
    - Handle errors
    - _Requirements: 7.3_

  - [x] 6.2 Display recommended strategy prominently

    - Show recommended strategy badge/highlight
    - Display recommendation reasoning
    - Allow user to see why strategy was recommended
    - _Requirements: 3.5, 4.1, 4.2, 4.3_

  - [x] 6.3 Display stack states table

    - Show all detected stacks
    - Display stack name, type, status, region
    - Highlight failed stacks in red
    - Highlight in-progress stacks in yellow
    - Show updatable stacks in green
    - _Requirements: 4.4, 4.5_

  - [x] 6.4 Allow strategy override

    - Pre-select recommended strategy
    - Allow user to choose different strategy if needed
    - Show warning if overriding recommendation
    - _Requirements: 3.5_

- [x] 7. Write unit tests for stack classification


  - [x] 7.1 Test _classify_stack_state with all CloudFormation statuses

    - Test CREATE_COMPLETE → "updatable"
    - Test UPDATE_COMPLETE → "updatable"
    - Test ROLLBACK_COMPLETE → "failed"
    - Test UPDATE_ROLLBACK_COMPLETE → "failed"
    - Test DELETE_FAILED → "failed"
    - Test CREATE_FAILED → "failed"
    - Test CREATE_IN_PROGRESS → "in_progress"
    - Test UPDATE_IN_PROGRESS → "in_progress"
    - Test DELETE_IN_PROGRESS → "in_progress"
    - Test unknown status → handle gracefully
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 8. Write unit tests for decision tree logic


  - [x] 8.1 Test _recommend_strategy with no stacks

    - Empty stack list → UPDATE_EXISTING
    - Verify reasoning mentions "first deployment"
    - _Requirements: 3.3_

  - [x] 8.2 Test _recommend_strategy with all updatable stacks

    - All stacks CREATE_COMPLETE or UPDATE_COMPLETE → UPDATE_EXISTING
    - Verify reasoning mentions "all stacks stable"
    - _Requirements: 3.1_

  - [x] 8.3 Test _recommend_strategy with failed stacks

    - Any stack in failed state → CLEAN_DEPLOY
    - Verify reasoning lists failed stack names
    - _Requirements: 3.2, 4.1_

  - [x] 8.4 Test _recommend_strategy with in-progress stacks

    - Any stack in progress → None (wait)
    - Verify reasoning lists in-progress stack names
    - _Requirements: 3.4, 4.3_

  - [x] 8.5 Test _recommend_strategy with mixed states

    - Some not found, some updatable → UPDATE_EXISTING
    - Verify reasoning mentions partial deployment
    - _Requirements: 2.8_

- [x] 9. Write integration tests


  - [x] 9.1 Test end-to-end stack detection with mocked CloudFormation

    - Mock boto3 CloudFormation client
    - Mock describe_stacks responses
    - Verify correct StackDetectionResult
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 9.2 Test multi-region detection

    - Mock stacks in us-east-1 (frontend-global)
    - Mock stacks in target region (others)
    - Verify correct region routing
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 9.3 Test error handling

    - Mock AccessDeniedException → partial results
    - Mock ExpiredTokenException → clear error message
    - Mock ResourceNotFoundException → stack not found (not error)
    - Verify system doesn't crash
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 9.4 Test API endpoint

    - Test POST /api/deployment/detect-stacks
    - Verify request/response format
    - Test with various scenarios
    - _Requirements: 7.3_

- [x] 10. Update documentation


  - [x] 10.1 Update API documentation

    - Document new /detect-stacks endpoint
    - Document request/response models
    - Provide usage examples
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 10.2 Update user guide

    - Explain automatic strategy recommendation
    - Document how to interpret stack states
    - Explain when to override recommendations
    - _Requirements: 3.5, 4.1, 4.2, 4.3_

- [x] 11. Checkpoint - Ensure all tests pass



  - Ensure all tests pass, ask the user if questions arise.
