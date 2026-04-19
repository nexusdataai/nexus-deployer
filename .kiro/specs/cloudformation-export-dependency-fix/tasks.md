# Implementation Plan

- [x] 1. Create data models for dependency tracking


  - Create `TemplateDependencies`, `ImportReference`, and `ExportDeclaration` dataclasses
  - Create `DependencyNode` and `DependencyGraph` dataclasses
  - Create `DependencyIssue`, `ValidationResult` dataclasses
  - Create `StackDeploymentStep` and `DeploymentPlan` dataclasses
  - _Requirements: 1.1, 1.2, 3.1, 3.2, 4.1, 4.2_

- [x] 2. Implement StackDependencyAnalyzer
- [x] 2.1 Implement template parsing and import extraction




  - Write `analyze_template()` method to parse CloudFormation templates
  - Write `extract_imports()` to find all Fn::ImportValue references
  - Handle both short-form and long-form intrinsic function syntax
  - Handle nested intrinsic functions (Fn::If, Fn::Sub containing imports)
  - Support both YAML and JSON template formats
  - _Requirements: 4.1_

- [ ] 2.2 Write property test for import extraction
  - **Property 12: Import extraction completeness**
  - **Validates: Requirements 4.1**

- [x] 2.3 Implement export extraction


  - Write `extract_exports()` to find all Export declarations in Outputs
  - Extract export names, output keys, and values
  - _Requirements: 4.1, 5.1_

- [x] 2.4 Implement condition extraction and analysis


  - Write `extract_conditions()` to parse Conditions section
  - Write `is_conditional_export()` to check if exports are conditional
  - Link conditional exports to their condition names
  - _Requirements: 1.5, 2.3_

- [ ] 2.5 Write property test for export naming convention
  - **Property 15: Export naming convention compliance**
  - **Validates: Requirements 5.1**

- [x] 3. Implement DependencyValidator
- [x] 3.1 Implement AWS export checking


  - Write `_get_client()` helper for boto3 client creation with credentials
  - Write `check_export_exists()` to query CloudFormation list_exports API
  - Write `get_stack_exports()` to retrieve exports from a deployed stack
  - Implement caching for export lists to minimize API calls
  - Handle pagination for large numbers of exports
  - _Requirements: 1.1, 1.4_



- [x] 3.2 Implement condition evaluation

  - Write `evaluate_condition()` to determine if a condition is true for a deployed stack
  - Check for existence of conditional resources to infer condition state
  - Handle cases where stack doesn't exist (return None)
  - _Requirements: 1.5, 2.3_


- [x] 3.3 Implement dependency graph construction

  - Write `build_dependency_graph()` to create DependencyGraph from stack configs
  - Map imports to their providing stacks
  - Build directed edges between dependent stacks
  - _Requirements: 4.2, 4.3_

- [ ] 3.4 Write property test for import-to-stack mapping
  - **Property 13: Import-to-stack mapping accuracy**
  - **Validates: Requirements 4.2**


- [x] 3.5 Implement circular dependency detection

  - Write `detect_circular_dependencies()` using depth-first search
  - Return all circular dependency chains found
  - _Requirements: 4.4_

- [ ] 3.6 Write property test for circular dependency detection
  - **Property 14: Circular dependency detection**
  - **Validates: Requirements 4.4**

- [x] 3.7 Implement main validation logic


  - Write `validate_dependencies()` to orchestrate all validation checks
  - Check for missing exports
  - Check for circular dependencies
  - Validate conditional exports match conditional imports
  - Collect all issues before returning
  - _Requirements: 1.1, 1.2, 1.3, 3.5_

- [ ] 3.8 Write property test for validation completeness
  - **Property 11: Validation finds all issues**
  - **Validates: Requirements 3.5**

- [x] 4. Implement error reporting

- [x] 4.1 Implement DependencyIssue creation

  - Write helper functions to create structured error messages
  - Ensure all error messages include export name, providing stack, and suggested action
  - Add stack status information to error messages
  - Add condition information for conditional export errors
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4.2 Write property test for error report completeness
  - **Property 3: Error report completeness**
  - **Property 7: Error messages contain export names**
  - **Property 8: Error messages identify providing stacks**
  - **Property 9: Error messages include stack status**
  - **Property 10: Conditional export errors explain conditions**
  - **Validates: Requirements 1.3, 3.1, 3.2, 3.3, 3.4**

- [x] 5. Implement DeploymentPlanner

- [x] 5.1 Implement topological sorting

  - Write `topological_sort()` using Kahn's algorithm or DFS
  - Return deployment order that respects all dependencies
  - Handle graphs with no dependencies (any order is valid)
  - _Requirements: 4.3_

- [ ] 5.2 Write property test for deployment ordering
  - **Property 5: Deployment ordering respects dependencies**
  - **Validates: Requirements 2.2, 4.3**


- [x] 5.3 Implement deployment plan generation

  - Write `create_deployment_plan()` to generate DeploymentPlan
  - Determine action for each stack (create, update, skip)
  - Calculate dependencies satisfied at each step
  - List exports that will be provided by each step
  - _Requirements: 4.3, 4.5_


- [x] 5.4 Implement missing stack identification

  - Write `identify_missing_stacks()` to find prerequisite stacks
  - Compare required exports against available stacks
  - _Requirements: 1.2_


- [x] 5.5 Implement dry-run report generation

  - Write `generate_dry_run_report()` to create human-readable report
  - Include deployment order, actions, and dependencies
  - Include warnings and validation results
  - _Requirements: 6.3_

- [x] 6. Enhance DeploymentOrchestrator

- [x] 6.1 Integrate dependency validation into orchestrator

  - Add `dependency_analyzer`, `dependency_validator`, and `deployment_planner` to `__init__`
  - Write `validate_stack_dependencies()` method
  - Call validation before deployment in `deploy_capability()`
  - _Requirements: 1.1, 1.4_


- [x] 6.2 Implement dry-run mode

  - Add `dry_run` parameter to `deploy_capability_with_validation()`
  - When dry_run is True, perform validation but skip actual deployment
  - Return validation results and deployment plan
  - _Requirements: 6.1, 6.2, 6.3, 6.4_


- [x] 6.3 Implement certificate configuration handling

  - Add logic to detect when custom domain is not configured
  - Skip certificate imports when domain is not configured
  - Handle multiple certificate sources with priority selection
  - _Requirements: 2.1, 2.4_

- [ ] 6.4 Write property test for certificate selection priority
  - **Property 6: Certificate selection priority**
  - **Validates: Requirements 2.4**



- [x] 6.5 Update deployment flow with validation
  - Modify `deploy_capability_with_strategy()` to use new validation
  - Ensure validation runs before CLEAN_DEPLOY and UPDATE_EXISTING
  - Handle validation failures gracefully
  - Provide clear error messages to users via callback
  - _Requirements: 1.1, 1.3, 3.1, 3.2, 3.3_


- [x] 7. Add configuration options

  - Add `pre_validation.enabled` flag to deployment config
  - Add `pre_validation.strict_mode` flag (warnings block deployment)
  - Add `pre_validation.enforce_naming_convention` flag
  - Update config templates (dev, test, stage, prod) with new options
  - _Requirements: 1.1, 5.1, 5.3_


- [x] 8. Update API endpoints

  - Add `/api/deployment/validate` endpoint for dry-run validation
  - Add `/api/deployment/plan` endpoint to get deployment plan
  - Update `/api/deployment/deploy` to use new validation
  - Return validation results in API responses
  - _Requirements: 6.1, 6.2, 6.3_

- [x] 9. Update frontend to display validation results


  - Add validation results display in DeploymentExecution component
  - Show dependency graph visualization (optional)
  - Display deployment plan before execution
  - Show validation errors with suggested actions
  - Add dry-run button to wizard
  - _Requirements: 1.3, 3.1, 3.2, 3.3, 3.4, 6.3_


- [x] 10. Checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Create integration tests
- [x] 11.1 Test end-to-end validation flow


  - Load real CloudFormation templates from deploy/templates
  - Run validation against test AWS environment
  - Verify correct deployment ordering
  - _Requirements: 1.1, 4.3_


- [x] 11.2 Test missing export scenario
  - Create scenario where domain stack is not deployed
  - Attempt to deploy service stack
  - Verify validation catches missing export
  - Verify error message contains all required information
  - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3_


- [x] 11.3 Test conditional export scenario
  - Create scenario where CreateCert condition is false
  - Attempt to deploy service stack with certificate import
  - Verify validation handles conditional export correctly
  - _Requirements: 1.5, 2.3, 3.4_


- [x] 11.4 Test dry-run mode
  - Execute dry-run against real templates
  - Verify no resources are created in AWS
  - Verify report accuracy
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 12. Update documentation


  - Update DEPLOYMENT_STRATEGY_GUIDE.md with validation information
  - Add section on dependency validation to README
  - Document dry-run mode usage
  - Document configuration options
  - Add troubleshooting guide for common dependency issues
  - _Requirements: 1.3, 6.3_


- [x] 13. Final checkpoint - Ensure all tests pass


  - Ensure all tests pass, ask the user if questions arise.
