# Implementation Plan

- [x] 1. Create data models for validation system





  - Create ValidationReport, ValidationIssue, ResourceDefinition, OrphanedResource, and StackStatus models
  - Add models to app/models/validation.py
  - _Requirements: 1.5, 4.1, 4.2_

- [x] 2. Implement TemplateParser for CloudFormation template parsing












  - Create app/services/template_parser.py
  - Implement parse_template() to extract resource definitions from YAML/JSON
  - Implement resolve_parameters() to handle Ref, Sub, and GetAtt intrinsic functions
  - Handle template parsing errors gracefully
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ]* 2.1 Write property test for template parsing
  - **Property 7: Template parsing extracts all resources**
  - **Validates: Requirements 4.1, 4.2, 4.3**

- [ ]* 2.2 Write property test for parameter resolution
  - **Property 8: Parameter references are resolved**
  - **Validates: Requirements 4.4**

- [x] 3. Implement resource name sanitization utilities


  - Create app/utils/name_sanitizer.py
  - Implement sanitize_capability_name() function
  - Handle spaces, underscores, uppercase, and invalid characters
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ]* 3.1 Write property test for name sanitization
  - **Property 15: Capability names are sanitized**
  - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

- [x] 4. Create resource cleaner base class and registry


  - Create app/services/resource_cleanup_registry.py
  - Implement ResourceCleanerBase abstract class
  - Implement ResourceCleanupRegistry with register/detect/cleanup methods
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [x] 5. Implement S3BucketCleaner


  - Create app/services/cleaners/s3_bucket_cleaner.py
  - Implement detect() to check if S3 bucket exists
  - Implement cleanup() to empty all objects, versions, and delete markers, then delete bucket
  - Implement get_name() to extract bucket name from resource definition
  - Handle S3-specific errors (NoSuchBucket, etc.)
  - _Requirements: 5.1, 6.1, 11.2_

- [ ]* 5.1 Write property test for S3 bucket cleanup
  - **Property 9: Orphaned S3 buckets are cleaned up**
  - **Validates: Requirements 6.1, 11.2**

- [x] 6. Implement ALBCleaner


  - Create app/services/cleaners/alb_cleaner.py
  - Implement detect() to check if ALB exists
  - Implement cleanup() to disable deletion protection and delete ALB
  - Implement get_name() to extract ALB name from resource definition
  - Handle ALB-specific errors (LoadBalancerNotFound, etc.)
  - _Requirements: 5.2, 6.2_

- [ ]* 6.1 Write property test for ALB cleanup
  - **Property 10: Orphaned ALBs are cleaned up**
  - **Validates: Requirements 6.2**

- [x] 7. Implement CloudFrontCleaner


  - Create app/services/cleaners/cloudfront_cleaner.py
  - Implement detect() to check if CloudFront distribution exists
  - Implement cleanup() to disable distribution, wait for deployment, then delete
  - Implement get_name() to extract distribution identifier from resource definition
  - Handle CloudFront-specific errors and wait logic
  - _Requirements: 5.3, 6.3, 11.1_

- [ ]* 7.1 Write property test for CloudFront cleanup
  - **Property 11: Orphaned CloudFront distributions are cleaned up**
  - **Validates: Requirements 6.3, 11.1**

- [x] 8. Implement ECRRepositoryCleaner


  - Create app/services/cleaners/ecr_repository_cleaner.py
  - Implement detect() to check if ECR repository exists
  - Implement cleanup() to delete all images then delete repository
  - Implement get_name() to extract repository name from resource definition
  - Handle ECR-specific errors (RepositoryNotFoundException, etc.)
  - _Requirements: 5.4, 6.4, 11.4_

- [ ]* 8.1 Write property test for ECR repository cleanup
  - **Property 12: Orphaned ECR repositories are cleaned up**
  - **Validates: Requirements 6.4, 11.4**

- [x] 9. Implement CloudWatchLogGroupCleaner


  - Create app/services/cleaners/cloudwatch_log_group_cleaner.py
  - Implement detect() to check if log group exists
  - Implement cleanup() to delete log group
  - Implement get_name() to extract log group name from resource definition
  - Handle CloudWatch-specific errors (ResourceNotFoundException, etc.)
  - _Requirements: 5.5, 6.5_

- [ ]* 9.1 Write property test for CloudWatch log group cleanup
  - **Property 13: Orphaned CloudWatch log groups are cleaned up**
  - **Validates: Requirements 6.5**

- [x] 10. Implement PreDeploymentValidator core logic


  - Create app/services/pre_deployment_validator.py
  - Implement __init__() to initialize with credentials and services
  - Implement check_stack_status() to detect unstable stacks
  - Implement cleanup_unstable_stack() to delete unstable stacks
  - Implement detect_orphaned_resources() to find orphaned resources for a stack
  - Implement cleanup_orphaned_resources() to remove orphaned resources
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ]* 10.1 Write property test for unstable stack detection
  - **Property 3: Unstable stacks are identified**
  - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

- [ ]* 10.2 Write property test for unstable stack deletion
  - **Property 4: Unstable stacks are deleted**
  - **Property 5: Deletion protection is disabled**
  - **Property 6: Deletion completion is verified**
  - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

- [x] 11. Implement PreDeploymentValidator main validation workflow


  - Implement validate_deployment() method
  - Iterate through all stacks in deployment order
  - Check stack status and cleanup unstable stacks
  - Parse templates and detect orphaned resources
  - Cleanup orphaned resources
  - Build and return ValidationReport
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ]* 11.1 Write property test for validation workflow
  - **Property 1: Validation runs before deployment**
  - **Property 2: All stacks are validated**
  - **Validates: Requirements 1.1, 1.2, 10.1**

- [ ]* 11.2 Write property test for issue resolution
  - **Property 18: Validation resolves issues before deployment**
  - **Property 19: Unresolvable issues fail deployment**
  - **Property 20: Successful validation proceeds to deployment**
  - **Validates: Requirements 10.2, 10.3, 10.4**

- [x] 12. Implement error handling and logging

  - Add comprehensive error handling for all AWS API calls
  - Implement error categorization (critical vs non-critical)
  - Add detailed logging for all validation and cleanup operations
  - Handle ResourceNotFoundException, NoSuchBucket, throttling, etc.
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ]* 12.1 Write property test for error handling
  - **Property 16: Non-critical errors don't fail deployment**
  - **Property 17: Critical errors fail deployment**
  - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

- [ ]* 12.2 Write property test for logging
  - **Property 14: Progress is logged**
  - **Validates: Requirements 7.2, 7.3, 7.4**

- [x] 13. Register all resource cleaners in ResourceCleanupRegistry


  - Register S3BucketCleaner for AWS::S3::Bucket
  - Register ALBCleaner for AWS::ElasticLoadBalancingV2::LoadBalancer
  - Register CloudFrontCleaner for AWS::CloudFront::Distribution
  - Register ECRRepositoryCleaner for AWS::ECR::Repository
  - Register CloudWatchLogGroupCleaner for AWS::Logs::LogGroup
  - _Requirements: 12.4, 12.5_

- [x] 14. Integrate PreDeploymentValidator into DeploymentOrchestrator


  - Modify app/services/deployment_orchestrator.py
  - Add PreDeploymentValidator initialization in __init__()
  - Call validator.validate_deployment() at start of deploy_capability()
  - Handle validation failure by returning error response
  - Pass validation report in deployment response
  - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [ ]* 14.1 Write integration test for orchestrator validation
  - Test that validation runs before deployment
  - Test that validation failures prevent deployment
  - Test that validation success allows deployment to proceed

- [x] 15. Add configuration support for validation


  - Add validation configuration to config YAML schema
  - Support enabled/disabled flag
  - Support cleanup_orphaned_resources flag
  - Support cleanup_unstable_stacks flag
  - Update config loading in DeploymentOrchestrator
  - _Requirements: 10.5_

- [x] 16. Update deployment models to include validation report


  - Modify app/models/deployment.py
  - Add validation_report field to DeploymentResponse
  - Add validation_issues field for issue details
  - Ensure backward compatibility
  - _Requirements: 1.5_

- [x] 17. Update API endpoints to expose validation information

  - Modify app/routers/deployment.py
  - Include validation report in deployment status response
  - Add endpoint to retrieve validation details
  - Update API documentation
  - _Requirements: 1.5, 7.5_

- [x] 18. Add dependency-aware cleanup ordering


  - Implement cleanup_order() method in ResourceCleanupRegistry
  - Define dependency relationships between resource types
  - Sort orphaned resources by dependency order before cleanup
  - Handle circular dependencies gracefully
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ]* 18.1 Write property test for dependency ordering
  - **Property 21: Resource cleanup follows dependency order**
  - **Validates: Requirements 11.5**

- [x] 19. Checkpoint - Ensure all tests pass


  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Update documentation


  - Add pre-deployment validation section to README
  - Document configuration options
  - Add troubleshooting guide for validation failures
  - Document how to add new resource types
  - _Requirements: All_

- [x] 21. Final Checkpoint - Ensure all tests pass



  - Ensure all tests pass, ask the user if questions arise.
