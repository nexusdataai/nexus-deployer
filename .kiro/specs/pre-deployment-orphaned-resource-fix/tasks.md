# Implementation Plan

- [x] 1. Update PreDeploymentValidator to skip orphaned resource detection for stable stacks


  - Modify the `validate_deployment()` method in `backend/app/services/pre_deployment_validator.py`
  - Add stack status check before orphaned resource detection
  - Skip orphaned detection for STABLE stacks with logging
  - Skip orphaned detection after deleting UNSTABLE stacks with logging
  - Only run orphaned detection for NOT_EXISTS stacks
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.1, 2.2, 2.3_

- [x] 1.1 Write unit tests for PreDeploymentValidator changes


  - Test stable stack skips orphaned detection
  - Test non-existent stack triggers orphaned detection
  - Test unstable stack deletion skips orphaned detection
  - Test logging messages for each scenario
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Update DeploymentOrchestrator to skip validation for CLEAN_DEPLOY strategy


  - Modify `deploy_capability_with_strategy()` in `backend/app/services/deployment_orchestrator.py`
  - Add strategy check before running validation
  - Skip validation entirely for CLEAN_DEPLOY strategy
  - Run validation for UPDATE_EXISTING strategy
  - Add logging for validation skip decisions
  - _Requirements: 1.4, 4.1, 4.2, 2.4_

- [x] 2.1 Write unit tests for DeploymentOrchestrator strategy handling


  - Test CLEAN_DEPLOY skips validation
  - Test UPDATE_EXISTING runs validation
  - Test logging messages for each strategy
  - _Requirements: 1.4, 4.1, 4.2_

- [x] 3. Add skip_validation parameter to deploy_capability method

  - Modify `deploy_capability()` in `backend/app/services/deployment_orchestrator.py`
  - Add optional `skip_validation` parameter with default False
  - Check parameter before running validation
  - Maintain backward compatibility
  - _Requirements: 4.1, 4.4_

- [x] 3.1 Write unit tests for skip_validation parameter

  - Test skip_validation=True skips validation
  - Test skip_validation=False runs validation
  - Test default behavior (validation runs)
  - _Requirements: 4.1, 4.4_

- [x] 4. Enhance logging throughout validation flow


  - Add INFO level logs for all validation decisions
  - Add callback messages for UI display
  - Ensure all skip scenarios are logged with context
  - Add stack name and status to all relevant log messages
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 4.1 Write unit tests for logging

  - Test all log messages are generated correctly
  - Test callback messages are sent when callback provided
  - Test log messages contain required context
  - _Requirements: 2.1, 2.2, 2.3, 2.4_


- [x] 5. Integration testing with real deployment scenarios

  - Test UPDATE_EXISTING with stable stack (should not delete resources)
  - Test UPDATE_EXISTING with non-existent stack (should check orphaned resources)
  - Test CLEAN_DEPLOY (should skip validation)
  - Verify S3 buckets are not deleted during UPDATE_EXISTING
  - _Requirements: 1.1, 1.2, 1.4, 1.5_


- [x] 6. Checkpoint - Ensure all tests pass


  - Ensure all tests pass, ask the user if questions arise.
