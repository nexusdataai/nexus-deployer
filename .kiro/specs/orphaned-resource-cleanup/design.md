# Design Document: Orphaned Resource Cleanup and Pre-Deployment Validation

## Overview

This design introduces a comprehensive pre-deployment validation system that detects and cleans up orphaned AWS resources and unstable CloudFormation stacks before deployment begins. The system ensures deployments fail fast by identifying issues immediately, rather than discovering them mid-deployment after significant time has been invested.

The solution consists of three main components:
1. **Pre-Deployment Validator** - Orchestrates validation before deployment starts
2. **Template Parser** - Extracts resource definitions from CloudFormation templates
3. **Resource Cleanup Registry** - Extensible system for detecting and cleaning up orphaned resources

## Architecture

### High-Level Flow

```
Deployment Request
       ↓
Pre-Deployment Validation
       ├─→ Check Stack Status (detect unstable stacks)
       ├─→ Parse Templates (identify resources to be created)
       ├─→ Detect Orphaned Resources (check if resources already exist)
       └─→ Cleanup (remove unstable stacks and orphaned resources)
       ↓
Validation Report
       ├─→ Issues Found? → Cleanup → Retry Validation
       └─→ No Issues? → Proceed to Deployment
       ↓
Normal Stack Deployment
```

### Component Interaction

```
DeploymentOrchestrator
       ↓
PreDeploymentValidator
       ├─→ CloudFormationService (stack status checks)
       ├─→ TemplateParser (extract resource definitions)
       └─→ ResourceCleanupRegistry
              ├─→ S3BucketCleaner
              ├─→ ALBCleaner
              ├─→ CloudFrontCleaner
              ├─→ ECRRepositoryCleaner
              └─→ CloudWatchLogGroupCleaner
```

## Components and Interfaces

### 1. PreDeploymentValidator

**Purpose**: Orchestrates pre-deployment validation and cleanup

**Interface**:
```python
class PreDeploymentValidator:
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """Initialize validator with AWS credentials"""
        
    def validate_deployment(
        self,
        config: Dict[str, Any],
        deploy_frontend: bool,
        deploy_backend: bool,
        callback: Optional[Callable] = None
    ) -> ValidationReport:
        """
        Validate deployment configuration and environment
        
        Returns:
            ValidationReport with issues found and cleanup results
        """
        
    def check_stack_status(
        self,
        stack_name: str,
        region: str
    ) -> StackStatus:
        """Check if stack exists and its status"""
        
    def cleanup_unstable_stack(
        self,
        stack_name: str,
        region: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """Delete unstable stack"""
```

**Key Methods**:
- `validate_deployment()` - Main entry point for validation
- `check_stack_status()` - Checks individual stack status
- `cleanup_unstable_stack()` - Removes stacks in failed states
- `detect_orphaned_resources()` - Finds orphaned resources for a stack
- `cleanup_orphaned_resources()` - Removes orphaned resources

### 2. TemplateParser

**Purpose**: Parse CloudFormation templates to extract resource definitions

**Interface**:
```python
class TemplateParser:
    def parse_template(
        self,
        template_body: str,
        parameters: List[Dict[str, str]]
    ) -> List[ResourceDefinition]:
        """
        Parse CloudFormation template and extract resource definitions
        
        Args:
            template_body: YAML/JSON template content
            parameters: Parameter values for resolution
            
        Returns:
            List of ResourceDefinition objects
        """
        
    def resolve_parameters(
        self,
        value: Any,
        parameters: Dict[str, str]
    ) -> Any:
        """Resolve parameter references in template values"""
```

**Key Responsibilities**:
- Parse YAML/JSON CloudFormation templates
- Extract resource definitions (Type, Properties)
- Resolve parameter references (Ref, Sub, GetAtt)
- Handle intrinsic functions
- Extract resource naming properties

### 3. ResourceCleanupRegistry

**Purpose**: Extensible registry for resource type detection and cleanup

**Interface**:
```python
class ResourceCleanupRegistry:
    def register_resource_type(
        self,
        resource_type: str,
        detector: Callable,
        cleaner: Callable,
        namer: Callable
    ):
        """Register a new resource type for detection and cleanup"""
        
    def detect_orphaned_resource(
        self,
        resource_def: ResourceDefinition,
        region: str
    ) -> Optional[OrphanedResource]:
        """Detect if a resource exists as orphaned"""
        
    def cleanup_orphaned_resource(
        self,
        orphaned_resource: OrphanedResource,
        region: str,
        callback: Optional[Callable] = None
    ) -> bool:
        """Clean up an orphaned resource"""
```

**Built-in Resource Types**:
- `AWS::S3::Bucket`
- `AWS::ElasticLoadBalancingV2::LoadBalancer`
- `AWS::CloudFront::Distribution`
- `AWS::ECR::Repository`
- `AWS::Logs::LogGroup`

### 4. Resource-Specific Cleaners

Each resource type has a dedicated cleaner class:

**S3BucketCleaner**:
```python
class S3BucketCleaner:
    def detect(self, bucket_name: str, region: str) -> bool:
        """Check if S3 bucket exists"""
        
    def cleanup(self, bucket_name: str, region: str, callback: Optional[Callable] = None) -> bool:
        """Empty and delete S3 bucket"""
        
    def get_name(self, resource_def: ResourceDefinition, params: Dict) -> str:
        """Extract bucket name from resource definition"""
```

**ALBCleaner**:
```python
class ALBCleaner:
    def detect(self, alb_name: str, region: str) -> bool:
        """Check if ALB exists"""
        
    def cleanup(self, alb_name: str, region: str, callback: Optional[Callable] = None) -> bool:
        """Disable deletion protection and delete ALB"""
        
    def get_name(self, resource_def: ResourceDefinition, params: Dict) -> str:
        """Extract ALB name from resource definition"""
```

Similar patterns for CloudFront, ECR, and CloudWatch cleaners.

## Data Models

### ValidationReport

```python
@dataclass
class ValidationReport:
    """Report from pre-deployment validation"""
    success: bool
    issues_found: List[ValidationIssue]
    issues_resolved: List[ValidationIssue]
    issues_unresolved: List[ValidationIssue]
    validation_time: float
    summary: str
```

### ValidationIssue

```python
@dataclass
class ValidationIssue:
    """Single validation issue"""
    issue_type: IssueType  # UNSTABLE_STACK, ORPHANED_RESOURCE
    severity: Severity  # CRITICAL, WARNING
    stack_name: Optional[str]
    resource_type: Optional[str]
    resource_identifier: str
    description: str
    resolved: bool
    resolution_details: Optional[str]
```

### ResourceDefinition

```python
@dataclass
class ResourceDefinition:
    """CloudFormation resource definition"""
    logical_id: str
    resource_type: str
    properties: Dict[str, Any]
    deletion_policy: Optional[str]
```

### OrphanedResource

```python
@dataclass
class OrphanedResource:
    """Detected orphaned resource"""
    resource_type: str
    resource_identifier: str
    region: str
    stack_name: str
    detected_at: datetime
```

### StackStatus

```python
class StackStatus(Enum):
    """Stack status categories"""
    NOT_EXISTS = "not_exists"
    STABLE = "stable"  # CREATE_COMPLETE, UPDATE_COMPLETE
    UNSTABLE = "unstable"  # ROLLBACK_COMPLETE, DELETE_FAILED, etc.
    IN_PROGRESS = "in_progress"  # CREATE_IN_PROGRESS, UPDATE_IN_PROGRESS
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Validation runs before deployment

*For any* deployment request, pre-deployment validation should complete before any CloudFormation stack creation API calls are made.
**Validates: Requirements 1.1, 10.1**

### Property 2: All stacks are validated

*For any* deployment configuration, validation should check every stack in the STACK_ORDER that matches the deployment flags (deploy_frontend, deploy_backend).
**Validates: Requirements 1.2**

### Property 3: Unstable stacks are identified

*For any* stack in an unstable state (ROLLBACK_COMPLETE, DELETE_FAILED, UPDATE_ROLLBACK_COMPLETE, ROLLBACK_FAILED, CREATE_FAILED), the system should identify it as unstable.
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

### Property 4: Unstable stacks are deleted

*For any* unstable stack detected, the system should attempt to delete it before proceeding with deployment.
**Validates: Requirements 3.1**

### Property 5: Deletion protection is disabled

*For any* stack with resources that have deletion protection enabled, the system should disable deletion protection before attempting deletion.
**Validates: Requirements 3.2**

### Property 6: Deletion completion is verified

*For any* stack deletion operation, the system should wait for deletion to complete and verify the stack no longer exists.
**Validates: Requirements 3.3, 3.4**

### Property 7: Template parsing extracts all resources

*For any* valid CloudFormation template, parsing should extract all resource definitions with their types and properties.
**Validates: Requirements 4.1, 4.2, 4.3**

### Property 8: Parameter references are resolved

*For any* template with parameter references (Ref, Sub), the parser should resolve them to actual values using the provided parameters.
**Validates: Requirements 4.4**

### Property 9: Orphaned S3 buckets are cleaned up

*For any* orphaned S3 bucket detected, the system should empty all objects (including versions and delete markers) and then delete the bucket.
**Validates: Requirements 6.1, 11.2**

### Property 10: Orphaned ALBs are cleaned up

*For any* orphaned ALB detected, the system should disable deletion protection and delete the ALB.
**Validates: Requirements 6.2**

### Property 11: Orphaned CloudFront distributions are cleaned up

*For any* orphaned CloudFront distribution detected, the system should disable the distribution, wait for deployment, then delete it.
**Validates: Requirements 6.3, 11.1**

### Property 12: Orphaned ECR repositories are cleaned up

*For any* orphaned ECR repository detected, the system should delete all images and then delete the repository.
**Validates: Requirements 6.4, 11.4**

### Property 13: Orphaned CloudWatch log groups are cleaned up

*For any* orphaned CloudWatch log group detected, the system should delete the log group.
**Validates: Requirements 6.5**

### Property 14: Progress is logged

*For any* validation or cleanup operation, the system should log progress updates including stack names, resource identifiers, and operation status.
**Validates: Requirements 7.2, 7.3, 7.4**

### Property 15: Capability names are sanitized

*For any* capability name, the system should sanitize it by replacing spaces and underscores with hyphens, converting to lowercase, and removing invalid characters.
**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

### Property 16: Non-critical errors don't fail deployment

*For any* non-critical error during cleanup (ResourceNotFoundException, NoSuchBucket, throttling), the system should log the error and continue with deployment.
**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

### Property 17: Critical errors fail deployment

*For any* critical error during cleanup that prevents deployment from succeeding, the system should log the error and fail the deployment with a detailed error report.
**Validates: Requirements 9.5**

### Property 18: Validation resolves issues before deployment

*For any* deployment with validation issues, the system should attempt to resolve all issues before proceeding to stack deployment.
**Validates: Requirements 10.2**

### Property 19: Unresolvable issues fail deployment

*For any* validation issue that cannot be resolved, the system should fail the deployment and return a detailed error report.
**Validates: Requirements 10.3**

### Property 20: Successful validation proceeds to deployment

*For any* deployment where validation succeeds (no issues or all issues resolved), the system should proceed with normal stack deployment.
**Validates: Requirements 10.4**

### Property 21: Resource cleanup follows dependency order

*For any* set of orphaned resources with dependencies, the system should clean them up in dependency order (e.g., empty S3 before delete, disable CloudFront before delete).
**Validates: Requirements 11.5**

## Error Handling

### Error Categories

1. **Non-Critical Errors** (log and continue):
   - ResourceNotFoundException
   - NoSuchBucket
   - LoadBalancerNotFound
   - Throttling errors
   - Resource already deleted

2. **Critical Errors** (fail deployment):
   - Access denied errors
   - Invalid credentials
   - Template parsing failures
   - Unresolvable orphaned resources
   - Stack deletion failures

### Error Recovery

- **Retry Logic**: Implement exponential backoff for transient AWS API errors
- **Partial Cleanup**: If some resources can't be cleaned up, log warnings but continue if non-critical
- **Rollback**: If validation cleanup fails critically, report all issues without attempting deployment

### Logging Strategy

All errors should be logged with:
- Error code
- Error message
- Resource identifier
- Stack name (if applicable)
- Timestamp
- Severity level

## Testing Strategy

### Unit Testing

Unit tests will cover:
- Template parsing with various CloudFormation constructs
- Parameter resolution logic
- Resource name sanitization
- Individual resource cleaner functions
- Stack status detection
- Error handling for specific AWS error codes

### Property-Based Testing

Property-based tests will verify:
- All stacks in deployment order are validated
- All unstable stacks are identified correctly
- All orphaned resources are detected
- Cleanup operations complete successfully
- Parameter resolution works for all valid templates
- Name sanitization produces valid resource names
- Logging occurs for all operations
- Error handling is consistent

### Integration Testing

Integration tests will use mocked AWS clients to test:
- End-to-end validation workflow
- Multiple orphaned resources cleanup
- Unstable stack deletion
- Template parsing with real CloudFormation templates
- Error scenarios (access denied, throttling, etc.)

## Implementation Notes

### Integration with Existing Code

The PreDeploymentValidator will be integrated into DeploymentOrchestrator:

```python
class DeploymentOrchestrator:
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        self.validator = PreDeploymentValidator(credentials)
        # ... existing initialization
        
    def deploy_capability(self, config, deploy_frontend, deploy_backend, callback):
        # NEW: Run pre-deployment validation
        validation_report = self.validator.validate_deployment(
            config, deploy_frontend, deploy_backend, callback
        )
        
        if not validation_report.success:
            return {
                'success': False,
                'error': f"Pre-deployment validation failed: {validation_report.summary}",
                'validation_report': validation_report
            }
        
        # Existing deployment logic continues...
```

### Configuration

Add configuration option to enable/disable validation:

```python
# In config YAML
deployment:
  pre_validation:
    enabled: true  # Set to false to skip validation
    cleanup_orphaned_resources: true
    cleanup_unstable_stacks: true
```

### Performance Considerations

- Template parsing is done once per stack
- Resource detection uses batch AWS API calls where possible
- Cleanup operations run in parallel for independent resources
- Validation adds ~30-60 seconds to deployment time but saves hours of debugging

### Backward Compatibility

- Validation is enabled by default but can be disabled
- Existing deployments continue to work without changes
- Validation report is optional in deployment response
- Existing cleanup code is reused where possible

## Future Enhancements

1. **Parallel Validation**: Validate multiple stacks concurrently
2. **Dry-Run Mode**: Report issues without performing cleanup
3. **Resource Tagging**: Tag orphaned resources before deletion for audit trail
4. **Cost Estimation**: Estimate cost of orphaned resources
5. **Scheduled Cleanup**: Periodic cleanup of orphaned resources across all environments
6. **Additional Resource Types**: VPC, Security Groups, IAM Roles, etc.
7. **Validation Caching**: Cache validation results for repeated deployments
8. **Webhook Notifications**: Send alerts when orphaned resources are found
