# Implementation Plan: CloudFormation Template Reliability

## Overview

This implementation plan addresses CloudFormation template validation failures caused by YAML parsing errors with intrinsic functions and adds comprehensive pre-deployment reliability checks. The tasks are ordered to first fix the immediate parsing issue, then add validation components incrementally.

## Tasks

- [x] 1. Create CFN YAML Loader for intrinsic function support
  - [x] 1.1 Create app/utils/cfn_yaml_loader.py module
    - Implement custom YAML loader extending yaml.SafeLoader
    - Register constructors for all 18 CloudFormation intrinsic functions
    - Handle both short-form (!Ref) and long-form (Ref:) syntax
    - Log warnings for unknown tags but continue parsing
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [x] 1.2 Write property test for CFN YAML parsing
    - **Property 1: CFN YAML Parsing Handles All Intrinsic Functions**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

- [x] 2. Update Template Validator to use CFN YAML Loader
  - [x] 2.1 Refactor template_validator.py to use cfn_yaml_loader
    - Replace yaml.safe_load with load_cfn_yaml
    - Update validate_template_integrity to handle intrinsic functions
    - Add line/column error reporting for syntax errors
    - _Requirements: 2.1, 2.4_

- [x] 3. Checkpoint - Verify intrinsic function parsing
  - Test parsing of templates with !Condition, !Ref, !Sub tags
  - Ensure all tests pass, ask the user if questions arise

- [x] 4. Add template structure validation
  - [x] 4.1 Implement validate_template_structure method
    - Check for Resources section presence
    - Validate resource type naming pattern (AWS::Service::Resource)
    - Detect duplicate logical IDs
    - _Requirements: 2.2, 2.3, 2.5_
  - [x] 4.2 Write property test for structure validation
    - **Property 2: Template Structure Validation Detects Invalid Templates**
    - **Validates: Requirements 2.2, 2.3, 2.4, 2.5**

- [x] 5. Add parameter validation
  - [x] 5.1 Implement validate_parameters method
    - Check required parameters have values
    - Validate parameter types (String, Number, List, etc.)
    - Check AllowedValues constraints
    - Check AllowedPattern regex constraints
    - Check MinValue/MaxValue for numeric parameters
    - Report all violations in single result
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - [x] 5.2 Write property test for parameter validation
    - **Property 3: Parameter Validation Catches All Constraint Violations**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

- [x] 6. Add condition validation
  - [x] 6.1 Implement validate_conditions method
    - Verify all referenced conditions are defined
    - Validate condition functions use valid intrinsic functions
    - Check that referenced parameters exist
    - _Requirements: 6.1, 6.2, 6.4_
  - [x] 6.2 Write property test for condition validation
    - **Property 6: Condition Validation Detects Undefined References**
    - **Validates: Requirements 6.1, 6.2, 6.4**

- [x] 7. Add mapping validation
  - [x] 7.1 Implement validate_mappings method
    - Verify all FindInMap references point to existing mappings
    - Check first-level and second-level keys exist
    - Report specific missing key paths
    - _Requirements: 7.1, 7.2_
  - [x] 7.2 Write property test for mapping validation
    - **Property 7: Mapping Validation Detects Invalid FindInMap References**
    - **Validates: Requirements 7.1, 7.2**

- [x] 8. Add output validation
  - [x] 8.1 Implement validate_outputs method
    - Verify all outputs have Value property
    - Check referenced resources exist
    - Detect duplicate export names across deployment
    - _Requirements: 8.1, 8.2, 8.3_
  - [x] 8.2 Write property test for output validation
    - **Property 8: Output Validation Detects Invalid Outputs**
    - **Validates: Requirements 8.1, 8.2, 8.3**

- [x] 9. Checkpoint - Verify template validation
  - Test validation with real templates from deploy/templates/
  - Ensure all tests pass, ask the user if questions arise

- [x] 10. Create Dependency Validator
  - [x] 10.1 Create app/services/dependency_validator.py
    - Implement extract_imports to find all !ImportValue references
    - Implement extract_exports to find all Export names
    - Implement build_dependency_graph for multi-stack deployments
    - Implement cycle detection algorithm
    - _Requirements: 4.1, 4.3, 4.4_
  - [x] 10.2 Write property test for dependency validation
    - **Property 4: Dependency Graph Correctly Models Stack Relationships**
    - **Validates: Requirements 4.1, 4.3, 4.4**

- [x] 11. Create Resource Limit Checker
  - [x] 11.1 Create app/services/resource_limit_checker.py
    - Implement count_resources to count by type
    - Implement check_limits with CloudFormation limits (500 resources/stack)
    - Add warnings for limit-prone resources (IAM, Lambda, S3, DynamoDB)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [x] 11.2 Write property test for resource limit checking
    - **Property 5: Resource Limit Checker Warns About Limit Concerns**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

- [x] 12. Create Pre-Deployment Checker orchestrator
  - [x] 12.1 Create app/services/pre_deployment_checker.py
    - Implement ValidationIssue and ValidationReport data classes
    - Implement validate_deployment to orchestrate all checks
    - Categorize issues by severity (error, warning, info)
    - Include remediation suggestions for each issue
    - Implement should_block_deployment and should_prompt_user
    - _Requirements: 9.1, 9.2, 9.3, 9.5, 9.6_
  - [x] 12.2 Write property test for validation report
    - **Property 9: Validation Report Correctly Categorizes and Reports Issues**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.5, 9.6**

- [x] 13. Integrate Pre-Deployment Checker into deployment flow
  - [x] 13.1 Update deployment_orchestrator.py
    - Call Pre-Deployment Checker before starting deployment
    - Block deployment if errors found
    - Prompt user for confirmation if only warnings
    - Display validation report in UI-friendly format
    - _Requirements: 9.4, 9.5, 9.6_

- [x] 14. Add optional AWS API validation
  - [x] 14.1 Implement AWS API validation methods
    - Call CloudFormation ValidateTemplate API when credentials available
    - Check IAM permissions for deployment
    - Skip gracefully when credentials unavailable
    - _Requirements: 10.1, 10.2, 10.5_

- [x] 15. Final checkpoint - End-to-end verification
  - Test full validation pipeline with real templates
  - Verify error messages are clear and actionable
  - Test deployment blocking and user prompting
  - Ensure all tests pass, ask the user if questions arise

## Notes

- All tasks including property-based tests are required
- Task 1 (CFN YAML Loader) is the critical fix for the immediate parsing error
- Tasks 2-3 integrate the fix into existing code
- Tasks 4-12 add comprehensive validation capabilities
- Task 13 integrates everything into the deployment flow
- Task 14 adds optional live AWS validation
- Each task references specific requirements for traceability
