# Pre-Deployment Validation

## Overview

The pre-deployment validation system automatically detects and cleans up issues before deployment begins, ensuring deployments fail fast and succeed more reliably.

## Features

### Unstable Stack Detection and Cleanup

The system automatically detects CloudFormation stacks in unstable states:
- `ROLLBACK_COMPLETE`
- `DELETE_FAILED`
- `UPDATE_ROLLBACK_COMPLETE`
- `ROLLBACK_FAILED`
- `CREATE_FAILED`

When detected, these stacks are automatically deleted to allow fresh deployment.

### Orphaned Resource Detection and Cleanup

The system detects and cleans up orphaned AWS resources that exist outside CloudFormation management:

#### Supported Resource Types

1. **S3 Buckets** (`AWS::S3::Bucket`)
   - Empties all objects, versions, and delete markers
   - Deletes the bucket

2. **Application Load Balancers** (`AWS::ElasticLoadBalancingV2::LoadBalancer`)
   - Disables deletion protection
   - Deletes the ALB

3. **CloudFront Distributions** (`AWS::CloudFront::Distribution`)
   - Disables the distribution
   - Waits for deployment to complete
   - Deletes the distribution

4. **ECR Repositories** (`AWS::ECR::Repository`)
   - Deletes all images
   - Deletes the repository

5. **CloudWatch Log Groups** (`AWS::Logs::LogGroup`)
   - Deletes the log group

## Configuration

Pre-deployment validation is enabled by default. To disable it, add the following to your deployment configuration:

```yaml
deployment:
  pre_validation:
    enabled: false
```

### Configuration Options

```yaml
deployment:
  pre_validation:
    enabled: true  # Enable/disable validation (default: true)
    cleanup_orphaned_resources: true  # Clean up orphaned resources (default: true)
    cleanup_unstable_stacks: true  # Clean up unstable stacks (default: true)
```

## How It Works

### Validation Workflow

1. **Stack Status Check**: For each stack in the deployment order, check if it exists and its status
2. **Unstable Stack Cleanup**: If a stack is in an unstable state, delete it
3. **Template Parsing**: Parse CloudFormation templates to identify resources that will be created
4. **Orphaned Resource Detection**: Check if any of those resources already exist
5. **Orphaned Resource Cleanup**: Clean up any orphaned resources found
6. **Validation Report**: Generate a report with all issues found and resolved

### Dependency-Aware Cleanup

Resources are cleaned up in dependency order to avoid conflicts:

1. CloudFront distributions (takes longest, start first)
2. Application Load Balancers
3. ECR repositories
4. S3 buckets
5. CloudWatch log groups

## Validation Report

The validation report includes:

- **success**: Whether validation passed
- **issues_found**: List of all issues detected
- **issues_resolved**: List of issues successfully resolved
- **issues_unresolved**: List of issues that could not be resolved
- **validation_time**: Time taken for validation
- **summary**: Human-readable summary

### Example Report

```json
{
  "success": true,
  "issues_found": [
    {
      "issue_type": "unstable_stack",
      "severity": "critical",
      "stack_name": "my-app-dev-backend-storage",
      "resource_identifier": "my-app-dev-backend-storage",
      "description": "Stack my-app-dev-backend-storage is in an unstable state",
      "resolved": true,
      "resolution_details": "Stack successfully deleted"
    },
    {
      "issue_type": "orphaned_resource",
      "severity": "critical",
      "stack_name": "my-app-dev-backend-storage",
      "resource_type": "AWS::S3::Bucket",
      "resource_identifier": "my-app-dev-data",
      "description": "Orphaned AWS::S3::Bucket: my-app-dev-data",
      "resolved": true,
      "resolution_details": "Resource successfully cleaned up"
    }
  ],
  "issues_resolved": [...],
  "issues_unresolved": [],
  "validation_time": 45.2,
  "summary": "Validation successful. Found 2 issues, resolved 2."
}
```

## Error Handling

### Non-Critical Errors

These errors are logged but don't fail the deployment:
- `ResourceNotFoundException`
- `NoSuchBucket`
- `LoadBalancerNotFound`
- Throttling errors
- Resource already deleted

### Critical Errors

These errors fail the deployment:
- Access denied errors
- Invalid credentials
- Template parsing failures
- Unresolvable orphaned resources
- Stack deletion failures

## Troubleshooting

### Validation Fails with Access Denied

Ensure your AWS credentials have the necessary permissions:
- `cloudformation:DescribeStacks`
- `cloudformation:DeleteStack`
- `cloudformation:UpdateTerminationProtection`
- `s3:ListBucket`, `s3:DeleteObject`, `s3:DeleteBucket`
- `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DeleteLoadBalancer`
- `cloudfront:GetDistribution`, `cloudfront:UpdateDistribution`, `cloudfront:DeleteDistribution`
- `ecr:DescribeRepositories`, `ecr:DeleteRepository`, `ecr:BatchDeleteImage`
- `logs:DescribeLogGroups`, `logs:DeleteLogGroup`

### Validation Times Out

CloudFront distributions can take up to 10 minutes to disable. If validation times out:
1. Check the CloudFront console to see if the distribution is still disabling
2. Wait for it to complete, then retry deployment
3. Or disable validation temporarily and manually clean up the distribution

### Orphaned Resources Not Detected

Resources are only detected if they have explicit names in the CloudFormation template. Resources with auto-generated names cannot be detected before the stack is created.

## Adding New Resource Types

To add support for a new resource type:

1. Create a new cleaner class in `app/services/cleaners/`:

```python
from app.services.resource_cleanup_registry import ResourceCleanerBase
from app.models.validation import ResourceDefinition

class MyResourceCleaner(ResourceCleanerBase):
    def detect(self, resource_identifier: str, region: str, credentials=None) -> bool:
        # Check if resource exists
        pass
    
    def cleanup(self, resource_identifier: str, region: str, credentials=None, callback=None) -> bool:
        # Clean up the resource
        pass
    
    def get_name(self, resource_def: ResourceDefinition, parameters: dict) -> str:
        # Extract resource name from definition
        pass
```

2. Register the cleaner in `PreDeploymentValidator._register_cleaners()`:

```python
self.cleanup_registry.register_resource_type(
    'AWS::MyService::MyResource',
    MyResourceCleaner()
)
```

3. Update the cleanup order in `ResourceCleanupRegistry.get_cleanup_order()` if needed.

## API Integration

The validation report is included in the deployment response:

```python
{
    "deployment_id": "...",
    "status": "completed",
    "validation_report": {
        "success": true,
        "issues_found": [...],
        "issues_resolved": [...],
        "issues_unresolved": [],
        "validation_time": 45.2,
        "summary": "..."
    }
}
```

## Performance Considerations

- Validation adds 30-60 seconds to deployment time for clean environments
- Environments with orphaned resources may take longer (up to 10 minutes for CloudFront)
- Template parsing is done once per stack
- Resource detection uses batch AWS API calls where possible
- Cleanup operations run sequentially to respect dependencies
