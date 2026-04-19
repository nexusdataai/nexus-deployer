# Capability Update Detection (TinyDB-Based)

## Overview

The Capability Update Detection feature detects existing capability deployments from TinyDB and provides users with deployment strategy options (Clean Deploy or Update Existing). This implementation uses TinyDB as the single source of truth for deployment state, eliminating the need for AWS CloudFormation API calls during detection.

## Key Features

### 1. TinyDB-Based Detection
- **Fast Detection**: No AWS API calls needed - queries local TinyDB database
- **Offline Capable**: Works without AWS credentials during detection phase
- **Single Source of Truth**: Consistent with the TinyDB state management strategy

### 2. Deployment Strategies
- **Clean Deploy**: Deletes all existing stacks and TinyDB records, then performs fresh deployment
- **Update Existing**: Updates existing stacks in place, preserving data and configurations

### 3. Automatic State Management
- **Post-Deployment**: Automatically saves deployment state to TinyDB after successful deployment
- **Post-Cleanup**: Automatically deletes deployment state from TinyDB after successful cleanup

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Deployment Wizard UI                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Permission   │→ │  Detection   │→ │  Strategy        │  │
│  │ Verification │  │  (TinyDB)    │  │  Selection       │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  Backend Services                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ StackDetectionService                                 │  │
│  │ - detect_existing_stacks()                            │  │
│  │ - Queries TinyDB for deployment records              │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ TinyDBDeploymentStateService                          │  │
│  │ - load_deployment_state()                             │  │
│  │ - save_deployment_state()                             │  │
│  │ - delete_deployment_state()                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                            ↓                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ DeploymentOrchestrator                                │  │
│  │ - deploy_capability_with_strategy()                   │  │
│  │ - Saves state after deployment                        │  │
│  │ - Deletes state after cleanup                         │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  TinyDB (Local Storage)                      │
│  deployments table:                                          │
│  - capability_name                                           │
│  - environment                                               │
│  - region                                                    │
│  - stacks[]                                                  │
│  - last_deployment                                           │
│  - metadata                                                  │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. StackDetectionService

**Location**: `backend/app/services/stack_detection_service.py`

**Purpose**: Detects existing deployments from TinyDB

**Key Methods**:
```python
def detect_existing_stacks(
    capability_name: str,
    environment: str
) -> StackDetectionResult:
    """
    Query TinyDB for existing deployment record
    Returns StackDetectionResult with stacks found
    """
```

### 2. Data Models

**Location**: `backend/app/models/stack_detection.py`

**Models**:
- `StackDetectionResult`: Result of detection operation
- `ExistingStackInfo`: Information about a single stack
- `DeploymentStrategy`: Enum (CLEAN_DEPLOY, UPDATE_EXISTING)
- `StackDetectionRequest`: API request model

### 3. API Endpoint

**Endpoint**: `POST /api/deployment/detect-stacks`

**Request**:
```json
{
  "capability_name": "my-capability",
  "environment": "dev"
}
```

**Response**:
```json
{
  "capability_name": "my-capability",
  "environment": "dev",
  "region": "us-east-1",
  "stacks_found": [
    {
      "stack_name": "my-capability-dev-backend-foundation",
      "stack_type": "backend-foundation",
      "stack_status": "DEPLOYED",
      "region": "us-east-1",
      "is_updatable": true
    }
  ],
  "has_existing_stacks": true,
  "has_failed_stacks": false,
  "is_updatable": true,
  "detection_timestamp": "2024-01-15T10:30:00Z"
}
```

### 4. DeploymentOrchestrator Extensions

**Location**: `backend/app/services/deployment_orchestrator.py`

**Key Methods**:
```python
def deploy_capability_with_strategy(
    config: Dict[str, Any],
    strategy: DeploymentStrategy,
    deploy_frontend: bool = True,
    deploy_backend: bool = True,
    callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Deploy with specified strategy:
    - CLEAN_DEPLOY: Cleanup first, then deploy
    - UPDATE_EXISTING: Update in place
    """
```

**State Management**:
- **After Deployment**: Automatically calls `save_deployment_state()` to persist to TinyDB
- **After Cleanup**: Automatically calls `delete_deployment_state()` to remove from TinyDB

## Workflow

### Detection Flow

1. User completes permission verification
2. Frontend calls `POST /api/deployment/detect-stacks`
3. `StackDetectionService` queries TinyDB for deployment record
4. If record exists, returns list of stacks
5. If no record, returns empty result

### Clean Deployment Flow

1. User selects "Clean and Redeploy" strategy
2. `DeploymentOrchestrator.deploy_capability_with_strategy()` is called
3. Cleanup phase:
   - Deletes all CloudFormation stacks
   - Deletes TinyDB deployment record
4. Deployment phase:
   - Creates fresh stacks
   - Saves new deployment state to TinyDB

### Update Deployment Flow

1. User selects "Update Existing" strategy
2. `DeploymentOrchestrator.deploy_capability_with_strategy()` is called
3. Update phase:
   - Updates existing CloudFormation stacks
   - Updates TinyDB deployment record with new information

## Benefits of TinyDB Approach

### Performance
- ✅ **Instant Detection**: No AWS API latency
- ✅ **No Rate Limiting**: No AWS API throttling concerns
- ✅ **Offline Capable**: Works without AWS credentials

### Reliability
- ✅ **Single Source of Truth**: TinyDB is the authoritative state store
- ✅ **Consistent State**: No discrepancies between AWS and local state
- ✅ **Atomic Operations**: TinyDB transactions ensure consistency

### Simplicity
- ✅ **No AWS Permissions Needed**: Detection doesn't require AWS credentials
- ✅ **Simpler Error Handling**: No AWS API errors to handle during detection
- ✅ **Easier Testing**: Can test without AWS infrastructure

## Testing

### Unit Tests

Run the stack detection tests:
```bash
cd backend
python test_stack_detection.py
```

**Test Coverage**:
- Detection with no existing deployment
- Detection with existing deployment
- Detection result structure validation
- TinyDB state persistence

### Integration Tests

The feature integrates with:
- TinyDB state management system
- Deployment orchestrator
- Cleanup service
- Frontend wizard workflow

## Configuration

No additional configuration needed. The feature uses the existing TinyDB configuration from the state management system.

## API Usage Examples

### Detect Existing Stacks

```bash
curl -X POST http://localhost:8000/api/deployment/detect-stacks \
  -H "Content-Type: application/json" \
  -d '{
    "capability_name": "my-capability",
    "environment": "dev"
  }'
```

### Deploy with Strategy

```bash
curl -X POST http://localhost:8000/api/deployment/start \
  -H "Content-Type: application/json" \
  -d '{
    "capability_name": "my-capability",
    "environment": "dev",
    "deployment_strategy": "clean_deploy",
    ...
  }'
```

## Troubleshooting

### Detection Returns Empty Result

**Cause**: No deployment record in TinyDB

**Solution**: This is expected for first-time deployments. Proceed with normal deployment.

### Stacks Exist in AWS but Not Detected

**Cause**: Deployment was performed outside the toolkit or TinyDB was cleared

**Solution**: 
1. Use "Clean and Redeploy" to remove AWS stacks and start fresh
2. Or manually add deployment record to TinyDB

### TinyDB State Out of Sync

**Cause**: Manual stack deletion or TinyDB corruption

**Solution**:
1. Check TinyDB with: `python backend/check_db.py`
2. Manually sync state or perform clean deployment

## Future Enhancements

1. **Stack Status Tracking**: Store actual CloudFormation stack status in TinyDB
2. **Deployment History**: Track multiple deployment versions
3. **Rollback Support**: Ability to rollback to previous deployment state
4. **State Validation**: Periodic validation of TinyDB state against AWS
5. **Import Existing Deployments**: Tool to import existing AWS stacks into TinyDB

## Related Documentation

- [TinyDB State Management](TINYDB_MIGRATION.md)
- [Deployment Orchestrator](app/services/deployment_orchestrator.py)
- [Stack Detection Service](app/services/stack_detection_service.py)
