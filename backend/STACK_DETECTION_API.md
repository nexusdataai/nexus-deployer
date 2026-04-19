# Stack Detection API Documentation

## Overview

The Stack Detection API provides automatic detection of existing CloudFormation stacks and intelligent deployment strategy recommendations based on the Deployment Decision Tree.

## Endpoint

### POST /api/deployment/detect-stacks

Detects existing CloudFormation stacks and recommends a deployment strategy.

#### Request Body

```json
{
  "capability_name": "string",
  "environment": "string",
  "region": "string",
  "aws_session_id": "string (optional)",
  "deploy_frontend": "boolean (optional, default: true)",
  "deploy_backend": "boolean (optional, default: true)"
}
```

**Parameters:**

- `capability_name` (required): Name of the capability to detect
- `environment` (required): Environment (dev, test, stage, prod)
- `region` (required): Target AWS region for deployment
- `aws_session_id` (optional): AWS session ID for authentication
- `deploy_frontend` (optional): Whether to check frontend stacks (default: true)
- `deploy_backend` (optional): Whether to check backend stacks (default: true)

#### Response

```json
{
  "capability_name": "string",
  "environment": "string",
  "region": "string",
  "stacks_found": [
    {
      "stack_name": "string",
      "stack_type": "string",
      "stack_status": "string",
      "region": "string",
      "created_at": "datetime (optional)",
      "last_updated_at": "datetime (optional)",
      "is_updatable": "boolean",
      "status_reason": "string (optional)",
      "classification": "string"
    }
  ],
  "has_existing_stacks": "boolean",
  "has_failed_stacks": "boolean",
  "has_in_progress_stacks": "boolean",
  "is_updatable": "boolean",
  "recommended_strategy": "string (optional)",
  "recommendation_reason": "string",
  "detection_timestamp": "datetime",
  "error_message": "string (optional)"
}
```

**Response Fields:**

- `stacks_found`: Array of detected stacks with their current states
- `has_existing_stacks`: True if any stacks were found
- `has_failed_stacks`: True if any stacks are in failed states
- `has_in_progress_stacks`: True if any stacks have operations in progress
- `is_updatable`: True if all stacks can be updated in place
- `recommended_strategy`: Recommended deployment strategy ("clean_deploy" or "update_existing"), or null if should wait
- `recommendation_reason`: Human-readable explanation for the recommendation
- `error_message`: Error details if any queries failed (partial results may still be returned)

#### Stack Classifications

Each stack is classified into one of three categories:

- **updatable**: Stack is in a stable state and can be updated in place
  - States: `CREATE_COMPLETE`, `UPDATE_COMPLETE`
  
- **failed**: Stack is in a failed state and requires deletion before redeployment
  - States: `ROLLBACK_COMPLETE`, `UPDATE_ROLLBACK_COMPLETE`, `DELETE_FAILED`, `CREATE_FAILED`
  
- **in_progress**: Stack has an operation in progress
  - States: `CREATE_IN_PROGRESS`, `UPDATE_IN_PROGRESS`, `DELETE_IN_PROGRESS`, `ROLLBACK_IN_PROGRESS`, `UPDATE_ROLLBACK_IN_PROGRESS`

#### Deployment Strategy Recommendations

The API applies the following decision tree logic:

1. **No stacks exist** → Recommend `UPDATE_EXISTING` (first deployment)
2. **Any stack in progress** → Recommend `null` (wait for operations to complete)
3. **Any stack failed** → Recommend `CLEAN_DEPLOY` (cleanup required)
4. **All stacks updatable** → Recommend `UPDATE_EXISTING` (in-place update)

#### Multi-Region Support

The API automatically queries the correct region for each stack type:

- **frontend-global**: Always queried in `us-east-1` (CloudFront, ACM, WAF)
- **Other stacks**: Queried in the target deployment region

#### Error Handling

The API handles errors gracefully:

- **Stack not found**: Not treated as an error; stack is simply not included in results
- **Access denied**: Logged and included in `error_message`; partial results returned
- **Expired credentials**: Returns 401 error with clear message
- **Network errors**: Logged and included in `error_message`; partial results returned

## Usage Examples

### Example 1: First Deployment (No Existing Stacks)

**Request:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "aws_session_id": "abc123"
}
```

**Response:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "stacks_found": [],
  "has_existing_stacks": false,
  "has_failed_stacks": false,
  "has_in_progress_stacks": false,
  "is_updatable": true,
  "recommended_strategy": "update_existing",
  "recommendation_reason": "First deployment - no existing stacks found",
  "detection_timestamp": "2025-12-20T10:30:00Z"
}
```

### Example 2: All Stacks Stable (Update Recommended)

**Request:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "aws_session_id": "abc123"
}
```

**Response:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "stacks_found": [
    {
      "stack_name": "call-processing-prod-frontend-global",
      "stack_type": "frontend-global",
      "stack_status": "CREATE_COMPLETE",
      "region": "us-east-1",
      "created_at": "2025-12-19T08:00:00Z",
      "is_updatable": true,
      "classification": "updatable"
    },
    {
      "stack_name": "call-processing-prod-backend-service",
      "stack_type": "backend-service",
      "stack_status": "UPDATE_COMPLETE",
      "region": "us-west-2",
      "created_at": "2025-12-19T08:15:00Z",
      "last_updated_at": "2025-12-20T09:00:00Z",
      "is_updatable": true,
      "classification": "updatable"
    }
  ],
  "has_existing_stacks": true,
  "has_failed_stacks": false,
  "has_in_progress_stacks": false,
  "is_updatable": true,
  "recommended_strategy": "update_existing",
  "recommendation_reason": "All stacks are stable and updatable - in-place update recommended",
  "detection_timestamp": "2025-12-20T10:30:00Z"
}
```

### Example 3: Failed Stack (Clean Deploy Recommended)

**Request:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "aws_session_id": "abc123"
}
```

**Response:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "stacks_found": [
    {
      "stack_name": "call-processing-prod-backend-foundation",
      "stack_type": "backend-foundation",
      "stack_status": "ROLLBACK_COMPLETE",
      "region": "us-west-2",
      "created_at": "2025-12-20T09:00:00Z",
      "is_updatable": false,
      "status_reason": "Resource creation failed: CloudWatch log group already exists",
      "classification": "failed"
    }
  ],
  "has_existing_stacks": true,
  "has_failed_stacks": true,
  "has_in_progress_stacks": false,
  "is_updatable": false,
  "recommended_strategy": "clean_deploy",
  "recommendation_reason": "Failed stacks detected: call-processing-prod-backend-foundation (ROLLBACK_COMPLETE). Cleanup required before redeployment.",
  "detection_timestamp": "2025-12-20T10:30:00Z"
}
```

### Example 4: Operation In Progress (Wait Recommended)

**Request:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "aws_session_id": "abc123"
}
```

**Response:**
```json
{
  "capability_name": "call-processing",
  "environment": "prod",
  "region": "us-west-2",
  "stacks_found": [
    {
      "stack_name": "call-processing-prod-backend-service",
      "stack_type": "backend-service",
      "stack_status": "UPDATE_IN_PROGRESS",
      "region": "us-west-2",
      "created_at": "2025-12-19T08:00:00Z",
      "last_updated_at": "2025-12-20T10:25:00Z",
      "is_updatable": false,
      "classification": "in_progress"
    }
  ],
  "has_existing_stacks": true,
  "has_failed_stacks": false,
  "has_in_progress_stacks": true,
  "is_updatable": false,
  "recommended_strategy": null,
  "recommendation_reason": "Wait for in-progress operations to complete: call-processing-prod-backend-service",
  "detection_timestamp": "2025-12-20T10:30:00Z"
}
```

## Frontend Integration

### TypeScript/React Example

```typescript
import { deploymentApi } from '../services/api';

// Detect existing stacks
const detectStacks = async () => {
  try {
    const result = await deploymentApi.detectExistingStacks(
      'call-processing',
      'prod',
      'us-west-2',
      awsSessionId,
      true,  // deploy_frontend
      true   // deploy_backend
    );
    
    // Display recommended strategy
    if (result.recommended_strategy) {
      console.log(`Recommended: ${result.recommended_strategy}`);
      console.log(`Reason: ${result.recommendation_reason}`);
    } else {
      console.log('Please wait for operations to complete');
    }
    
    // Display stack states
    result.stacks_found.forEach(stack => {
      console.log(`${stack.stack_type}: ${stack.stack_status} (${stack.classification})`);
    });
    
  } catch (error) {
    console.error('Detection failed:', error);
  }
};
```

## See Also

- [Deployment Decision Tree](../DEPLOYMENT_DECISION_TREE.md) - Complete decision tree documentation
- [Deployment Strategy Guide](../DEPLOYMENT_STRATEGY_GUIDE.md) - When to use each strategy
- [Stack Detection Service](../app/services/stack_detection_service.py) - Implementation details
