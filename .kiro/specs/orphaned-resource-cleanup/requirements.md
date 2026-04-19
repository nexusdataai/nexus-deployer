# Requirements Document

## Introduction

The deployment system currently fails when attempting to create CloudFormation stacks if orphaned AWS resources (resources that exist outside of CloudFormation management) or unstable stacks are present. This occurs when previous deployments fail or are manually deleted, leaving behind resources with DeletionPolicy: Retain or stacks in failed states. The system needs comprehensive pre-deployment validation, orphaned resource detection, and cleanup capabilities to fail fast and ensure successful deployments without wasting time discovering issues mid-deployment.

## Glossary

- **Orphaned Resource**: An AWS resource that exists in the account but is not managed by any CloudFormation stack
- **Unstable Stack**: A CloudFormation stack in a failed or non-updatable state (ROLLBACK_COMPLETE, DELETE_FAILED, UPDATE_ROLLBACK_COMPLETE, etc.)
- **CloudFormation Stack**: A collection of AWS resources managed as a single unit
- **DeletionPolicy Retain**: A CloudFormation setting that preserves resources when the stack is deleted
- **Deployment System**: The Totogi Customer Toolkit deployment orchestration service
- **Pre-Deployment Validation**: Checking for issues before starting deployment to fail fast
- **Resource Type**: The AWS resource type (S3 Bucket, ALB, CloudFront Distribution, ECR Repository, etc.)
- **Stack Template**: CloudFormation template defining resources to be created
- **Resource Identifier**: Unique identifier for an AWS resource (bucket name, ARN, ID, etc.)

## Requirements

### Requirement 1

**User Story:** As a deployment operator, I want the system to perform pre-deployment validation before starting any deployment, so that issues are discovered immediately and deployment fails fast.

#### Acceptance Criteria

1. WHEN a deployment is initiated THEN the system SHALL perform pre-deployment validation before creating any stacks
2. WHEN pre-deployment validation runs THEN the system SHALL check all stacks in the deployment order
3. WHEN pre-deployment validation detects unstable stacks THEN the system SHALL log all unstable stacks found
4. WHEN pre-deployment validation detects orphaned resources THEN the system SHALL log all orphaned resources found
5. WHEN pre-deployment validation completes THEN the system SHALL return a validation report with all issues found

### Requirement 2

**User Story:** As a deployment operator, I want the system to detect unstable CloudFormation stacks, so that they can be cleaned up before deployment.

#### Acceptance Criteria

1. WHEN checking stack status THEN the system SHALL identify stacks in ROLLBACK_COMPLETE state as unstable
2. WHEN checking stack status THEN the system SHALL identify stacks in DELETE_FAILED state as unstable
3. WHEN checking stack status THEN the system SHALL identify stacks in UPDATE_ROLLBACK_COMPLETE state as unstable
4. WHEN checking stack status THEN the system SHALL identify stacks in ROLLBACK_FAILED state as unstable
5. WHEN checking stack status THEN the system SHALL identify stacks in CREATE_FAILED state as unstable

### Requirement 3

**User Story:** As a deployment operator, I want unstable stacks to be automatically deleted, so that deployment can proceed with clean stack creation.

#### Acceptance Criteria

1. WHEN an unstable stack is detected THEN the system SHALL delete the stack before proceeding
2. WHEN deleting an unstable stack THEN the system SHALL disable deletion protection on protected resources
3. WHEN deleting an unstable stack THEN the system SHALL wait for deletion to complete
4. WHEN stack deletion completes THEN the system SHALL verify the stack no longer exists
5. WHEN stack deletion fails THEN the system SHALL log the error and fail the deployment

### Requirement 4

**User Story:** As a deployment operator, I want the system to parse CloudFormation templates to identify resources that will be created, so that orphaned resources can be detected.

#### Acceptance Criteria

1. WHEN parsing a CloudFormation template THEN the system SHALL extract all resource definitions
2. WHEN extracting resource definitions THEN the system SHALL identify the resource type for each resource
3. WHEN extracting resource definitions THEN the system SHALL identify resource properties that determine naming
4. WHEN extracting resource definitions THEN the system SHALL resolve parameter references to determine actual names
5. WHEN template parsing fails THEN the system SHALL log the error and skip orphaned resource detection for that stack

### Requirement 5

**User Story:** As a deployment operator, I want the system to detect orphaned resources for all resource types, so that any orphaned resource can block deployment.

#### Acceptance Criteria

1. WHEN checking for orphaned resources THEN the system SHALL check for orphaned S3 buckets
2. WHEN checking for orphaned resources THEN the system SHALL check for orphaned Application Load Balancers
3. WHEN checking for orphaned resources THEN the system SHALL check for orphaned CloudFront distributions
4. WHEN checking for orphaned resources THEN the system SHALL check for orphaned ECR repositories
5. WHEN checking for orphaned resources THEN the system SHALL check for orphaned CloudWatch log groups

### Requirement 6

**User Story:** As a deployment operator, I want orphaned resources to be automatically cleaned up, so that deployment can proceed without manual intervention.

#### Acceptance Criteria

1. WHEN an orphaned S3 bucket is detected THEN the system SHALL empty and delete the bucket
2. WHEN an orphaned ALB is detected THEN the system SHALL disable deletion protection and delete the ALB
3. WHEN an orphaned CloudFront distribution is detected THEN the system SHALL disable and delete the distribution
4. WHEN an orphaned ECR repository is detected THEN the system SHALL delete all images and delete the repository
5. WHEN an orphaned CloudWatch log group is detected THEN the system SHALL delete the log group

### Requirement 7

**User Story:** As a deployment operator, I want the system to provide detailed progress updates during validation and cleanup, so that I can monitor the process.

#### Acceptance Criteria

1. WHEN pre-deployment validation starts THEN the system SHALL log the validation phase start
2. WHEN checking each stack THEN the system SHALL log the stack name and status
3. WHEN detecting orphaned resources THEN the system SHALL log the resource type and identifier
4. WHEN performing cleanup operations THEN the system SHALL log each cleanup step with progress
5. WHEN validation and cleanup complete THEN the system SHALL log a summary with counts of issues found and resolved

### Requirement 8

**User Story:** As a deployment operator, I want resource naming conventions to be handled correctly across all resource types, so that the right resources are identified.

#### Acceptance Criteria

1. WHEN determining resource names THEN the system SHALL apply capability name sanitization rules
2. WHEN sanitizing capability names THEN the system SHALL replace spaces with hyphens
3. WHEN sanitizing capability names THEN the system SHALL replace underscores with hyphens
4. WHEN sanitizing capability names THEN the system SHALL convert uppercase letters to lowercase
5. WHEN sanitizing capability names THEN the system SHALL remove characters that are invalid for the resource type

### Requirement 9

**User Story:** As a deployment operator, I want cleanup operations to be resilient to AWS API errors, so that transient failures do not block deployments.

#### Acceptance Criteria

1. WHEN an AWS API call fails with ResourceNotFoundException THEN the system SHALL treat the resource as non-existent
2. WHEN an AWS API call fails with NoSuchBucket error THEN the system SHALL treat the operation as successful
3. WHEN an AWS API call fails with throttling errors THEN the system SHALL log the error and continue
4. WHEN cleanup operations encounter non-critical errors THEN the system SHALL log warnings and continue
5. WHEN cleanup operations encounter critical errors THEN the system SHALL log errors and fail the deployment

### Requirement 10

**User Story:** As a system architect, I want the pre-deployment validation to be a separate phase, so that all issues are identified before any stack creation begins.

#### Acceptance Criteria

1. WHEN deployment is initiated THEN the system SHALL run pre-deployment validation before any stack operations
2. WHEN pre-deployment validation finds issues THEN the system SHALL attempt to resolve all issues before proceeding
3. WHEN pre-deployment validation cannot resolve issues THEN the system SHALL fail the deployment with detailed error report
4. WHEN pre-deployment validation succeeds THEN the system SHALL proceed with normal stack deployment
5. WHEN pre-deployment validation is disabled THEN the system SHALL skip validation and proceed directly to deployment

### Requirement 11

**User Story:** As a deployment operator, I want the system to handle resource dependencies correctly during cleanup, so that dependent resources are cleaned up in the right order.

#### Acceptance Criteria

1. WHEN cleaning up CloudFront distributions THEN the system SHALL wait for distribution to be disabled before deletion
2. WHEN cleaning up S3 buckets THEN the system SHALL empty all objects before deleting the bucket
3. WHEN cleaning up ALBs THEN the system SHALL delete target groups before deleting the ALB
4. WHEN cleaning up ECR repositories THEN the system SHALL delete all images before deleting the repository
5. WHEN cleanup order matters THEN the system SHALL clean up resources in dependency order

### Requirement 12

**User Story:** As a system architect, I want the validation and cleanup logic to be extensible, so that new resource types can be easily added.

#### Acceptance Criteria

1. WHEN adding a new resource type THEN the system SHALL support registering a detection function
2. WHEN adding a new resource type THEN the system SHALL support registering a cleanup function
3. WHEN adding a new resource type THEN the system SHALL support registering a naming convention function
4. WHEN a resource type is registered THEN the system SHALL automatically include it in validation
5. WHEN a resource type is registered THEN the system SHALL automatically include it in cleanup
