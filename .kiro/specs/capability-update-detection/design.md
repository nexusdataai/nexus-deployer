# Design Document: Capability Update Detection

## Overview

The Capability Update Detection feature enhances the deployment workflow by automatically detecting existing capability installations and providing users with intelligent deployment strategy options. This prevents accidental overwrites, data loss, and gives operators explicit control over whether to perform a clean redeployment or an in-place update.

The feature integrates seamlessly into the existing deployment wizard workflow, inserting a strategy selection step when existing installations are detected. It leverages the existing CloudFormation service infrastructure and cleanup mechanisms while adding new detection and decision-making capabilities.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Deployment Wizard UI                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Permission   │→ │  Detection   │→ │  Strategy Selection  │  │
│  │ Verification │  │  Step        │  │  Dialog              │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Backend Services Layer                        │
│  ┌──────────────────────┐  ┌──────────────────────────────┐    │
│  │ Stack Detection      │  │ Deployment Orchestrator      │    │
│  │ Service              │  │ - Clean Deployment Mode      │    │
│  │ - Query TinyDB       │  │ - Update Deployment Mode     │    │
│  │ - Return Metadata    │  │ - Save State to TinyDB       │    │
│  └──────────────────────┘  └──────────────────────────────┘    │
│              ↓                           ↓                       │
│  ┌──────────────────────────────────────────────────────┐      │
│  │ TinyDB Deployment State Service                      │      │
│  │ - load_deployment_state()                            │      │
│  │ - save_deployment_state()                            │      │
│  │ - delete_deployment_state()                          │      │
│  └──────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Local Storage (TinyDB)                        │
│  ┌──────────────────────┐  ┌──────────────────────────────┐    │
│  │ Deployments Table    │  │ Deployment Records           │    │
│  │ - capability_name    │  │ - environment                │    │
│  │ - stacks[]           │  │ - region                     │    │
│  │ - last_deployment    │  │ - metadata                   │    │
│  └──────────────────────┘  └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

1. **Detection Phase**: After permission verification, the Stack Detection Service queries TinyDB for existing deployment records
2. **Decision Phase**: If a deployment record exists with stacks, the UI presents strategy options to the user
3. **Execution Phase**: Based on user selection, the Deployment Orchestrator executes either clean or update deployment
4. **State Persistence Phase**: After successful deployment, the Deployment Orchestrator saves the deployment state to TinyDB

## Components and Interfaces

### 1. Stack Detection Service

**Purpose**: Detect existing deployment records in TinyDB for a capability

**Location**: `backend/app/services/stack_detection_service.py`

**Interface**:
```python
class StackDetectionService:
    def __init__(self, deployment_state_service: Optional[TinyDBDeploymentStateService] = None):
        """Initialize with TinyDB deployment state service"""
        
    def detect_existing_stacks(
        self,
        capability_name: str,
        environment: str
    ) -> StackDetectionResult:
        """
        Detect existing deployment record in TinyDB for a capability
        
        Returns:
            StackDetectionResult with stacks found and metadata
        """
```

### 2. Deployment Orchestrator Extensions

**Purpose**: Handle deployment strategy execution

**Location**: `backend/app/services/deployment_orchestrator.py`

**New Methods**:
```python
class DeploymentOrchestrator:
    def deploy_capability_with_strategy(
        self,
        config: Dict[str, Any],
        strategy: DeploymentStrategy,
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        Deploy capability with specified strategy
        
        Args:
            strategy: CLEAN_DEPLOY or UPDATE_EXISTING
        """
```

### 3. Strategy Selection Component

**Purpose**: UI component for user to select deployment strategy

**Location**: `frontend/src/components/StrategySelection.tsx`

**Interface**:
```typescript
interface StrategySelectionProps {
  detectionResult: StackDetectionResult;
  onStrategySelected: (strategy: DeploymentStrategy) => void;
  onCancel: () => void;
}

export const StrategySelection: React.FC<StrategySelectionProps>
```

### 4. API Endpoints

**New Endpoint**: `POST /api/deployment/detect-stacks`

```python
@router.post("/detect-stacks")
async def detect_stacks(request: StackDetectionRequest) -> StackDetectionResult:
    """Detect existing stacks for a capability"""
```

## Data Models

### StackDetectionResult

```python
class StackDetectionResult(BaseModel):
    """Result of stack detection operation"""
    capability_name: str
    environment: str
    region: str
    stacks_found: List[ExistingStackInfo]
    has_existing_stacks: bool
    has_failed_stacks: bool
    is_updatable: bool
    detection_timestamp: datetime
```

### ExistingStackInfo

```python
class ExistingStackInfo(BaseModel):
    """Information about an existing stack"""
    stack_name: str
    stack_type: str  # e.g., "frontend-global", "backend-service"
    stack_status: str  # CloudFormation status
    region: str
    created_at: Optional[datetime]
    last_updated_at: Optional[datetime]
    is_updatable: bool
    status_reason: Optional[str]
```

### StackStatusAnalysis

```python
class StackStatusAnalysis(BaseModel):
    """Analysis of a stack's status"""
    status: str
    is_updatable: bool
    requires_deletion: bool
    requires_manual_intervention: bool
    recommendation: str
    warning_message: Optional[str]
```

### DeploymentStrategy

```python
class DeploymentStrategy(str, Enum):
    """Deployment strategy options"""
    CLEAN_DEPLOY = "clean_deploy"
    UPDATE_EXISTING = "update_existing"
```

### WizardStep Extension

```typescript
// Add new step to existing WizardStep enum
export enum WizardStep {
  // ... existing steps ...
  PERMISSION_VERIFICATION = 'permission_verification',
  STRATEGY_SELECTION = 'strategy_selection',  // NEW
  DEPLOYMENT_EXECUTION = 'deployment_execution',
  // ... rest of steps ...
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Detection completeness
*For any* capability name and environment combination, when detecting existing stacks, the Stack Detection Service should query all stack types defined in STACK_ORDER
**Validates: Requirements 1.2**

### Property 2: Detection result schema
*For any* detection operation that finds stacks, the returned StackDetectionResult should contain stack name, stack type, current status, and region information for each stack
**Validates: Requirements 1.4**

### Property 3: Strategy dialog presentation
*For any* non-empty detection result, the Deployment Wizard should render a strategy selection dialog before proceeding to deployment
**Validates: Requirements 2.1**

### Property 4: Strategy dialog information completeness
*For any* detection result displayed in the strategy dialog, the rendered output should contain capability name, environment, region, and count of existing stacks
**Validates: Requirements 2.2**

### Property 5: Strategy selection persistence
*For any* strategy selection made by the user, the system should store the selection in wizard state and proceed with that strategy
**Validates: Requirements 2.6**

### Property 6: Clean deployment invokes cleanup
*For any* deployment with CLEAN_DEPLOY strategy selected, the Deployment Orchestrator should invoke the cleanup service before starting deployment
**Validates: Requirements 3.1**

### Property 7: Stack deletion ordering
*For any* set of stacks being deleted during clean deployment, the deletion order should be the reverse of STACK_ORDER
**Validates: Requirements 3.2**

### Property 8: Sequential stack deletion
*For any* stack deletion sequence, each stack deletion should complete before the next stack deletion begins
**Validates: Requirements 3.3**

### Property 9: Deployment proceeds after cleanup
*For any* clean deployment where all stacks are deleted successfully, the Deployment Orchestrator should proceed with normal deployment workflow
**Validates: Requirements 3.4**

### Property 10: Cleanup failure halts deployment
*For any* stack deletion failure during clean deployment, the Deployment Orchestrator should halt the deployment process and log the error
**Validates: Requirements 3.5**

### Property 11: Clean deployment progress updates
*For any* clean deployment operation, progress callbacks should be invoked showing which stacks are being deleted
**Validates: Requirements 3.6**

### Property 12: Update uses update operations
*For any* deployment with UPDATE_EXISTING strategy selected and existing stacks, the CloudFormation Service should call update_stack instead of create_stack
**Validates: Requirements 4.1**

### Property 13: Stack output preservation
*For any* stack update operation, existing stack outputs should be retrieved and passed to dependent stacks
**Validates: Requirements 4.4**

### Property 14: Update failure halts deployment
*For any* stack update failure, the Deployment Orchestrator should halt the deployment process and log the error
**Validates: Requirements 4.5**

### Property 15: Update deployment progress updates
*For any* update deployment operation, progress callbacks should be invoked showing which stacks are being updated
**Validates: Requirements 4.6**

### Property 16: Failed stack warnings
*For any* stack in a failed state (ROLLBACK_COMPLETE, ROLLBACK_FAILED, DELETE_FAILED), the system should display a warning message with the stack status and recommended action
**Validates: Requirements 5.4**

### Property 17: Failed stacks cleanup attempt
*For any* failed stack with CLEAN_DEPLOY strategy selected, the cleanup service should attempt to delete it
**Validates: Requirements 5.5**

### Property 18: Failed stacks update prevention
*For any* failed stack with UPDATE_EXISTING strategy selected, the system should display an error indicating the stack cannot be updated
**Validates: Requirements 5.6**

### Property 19: Detection timing in workflow
*For any* deployment workflow, stack detection should occur after permission verification and before deployment execution
**Validates: Requirements 6.1**

### Property 20: Strategy step insertion
*For any* detection result with existing stacks, the wizard should insert the strategy selection step between permission verification and deployment execution
**Validates: Requirements 6.2**

### Property 21: Detection result schema validation
*For any* StackDetectionResult returned by the Stack Detection Service, it should contain all required fields: capability_name, environment, region, stacks_found, has_existing_stacks, and detection_timestamp
**Validates: Requirements 7.4**

### Property 22: AWS API error handling
*For any* AWS API error encountered during stack detection, the Stack Detection Service should handle it gracefully and return appropriate error information
**Validates: Requirements 7.5**

### Property 23: Detection logging
*For any* stack detection operation, the system should log the capability name, environment, and region being checked
**Validates: Requirements 8.1**

### Property 24: Stack discovery logging
*For any* detection result with stacks found, the system should log each stack's name, type, and status
**Validates: Requirements 8.2**

### Property 25: Strategy selection logging
*For any* strategy selection made by the user, the system should log the selected strategy and timestamp
**Validates: Requirements 8.3**

### Property 26: Clean deployment operation logging
*For any* clean deployment execution, the system should log each stack deletion operation and its result
**Validates: Requirements 8.4**

### Property 27: Update deployment operation logging
*For any* update deployment execution, the system should log each stack update operation and its result
**Validates: Requirements 8.5**

### Property 28: Error logging
*For any* error during detection or strategy execution, the system should log detailed error messages with context
**Validates: Requirements 8.6**

## Error Handling

### Detection Errors

1. **AWS API Errors**: Catch boto3 ClientError exceptions and return structured error information
2. **Authentication Errors**: Handle expired credentials gracefully with clear error messages
3. **Permission Errors**: Detect insufficient permissions and provide actionable guidance

### Strategy Execution Errors

1. **Cleanup Failures**: Log detailed error information and halt deployment
2. **Update Failures**: Handle CloudFormation update errors including rollback scenarios
3. **Timeout Errors**: Implement reasonable timeouts for stack operations

### User Experience

1. **Clear Error Messages**: Provide context-specific error messages to users
2. **Recovery Options**: Suggest next steps when errors occur
3. **Audit Trail**: Maintain comprehensive logs for troubleshooting

## Testing Strategy

### Unit Testing

The implementation will include unit tests for:

- Stack Detection Service methods with mocked AWS responses
- Deployment Orchestrator strategy execution logic
- Data model validation and serialization
- Error handling paths

### Property-Based Testing

We will use **Hypothesis** (Python) and **fast-check** (TypeScript) for property-based testing.

Each property-based test will:
- Run a minimum of 100 iterations
- Be tagged with a comment referencing the design document property
- Use the format: `# Feature: capability-update-detection, Property N: <property_text>`

Property-based tests will verify:
- Detection completeness across random capability/environment combinations
- Strategy selection state management with random user inputs
- Stack deletion ordering with random stack configurations
- Logging behavior across various execution paths

### Integration Testing

Integration tests will verify:
- End-to-end detection and deployment flows
- AWS CloudFormation API interactions
- UI wizard navigation with detection step

### Edge Case Testing

Specific edge cases to test:
- Empty detection results (no existing stacks)
- Stacks in failed states (ROLLBACK_COMPLETE, etc.)
- "No updates to perform" CloudFormation response
- Mixed stack states (some updatable, some failed)

## Implementation Notes

### Backward Compatibility

- The feature should not break existing deployments that don't have existing stacks
- When no stacks are detected, the wizard should skip the strategy selection step seamlessly
- Existing cleanup and deployment logic should remain functional

### Performance Considerations

- Stack detection should be fast (< 5 seconds for typical cases)
- Parallel stack status queries where possible
- Cache detection results during a single wizard session

### Security Considerations

- Validate all user inputs (capability names, environments)
- Ensure AWS credentials are properly scoped
- Log security-relevant events (strategy selections, deletions)

### Monitoring and Observability

- Add metrics for detection success/failure rates
- Track strategy selection distribution (clean vs update)
- Monitor deployment success rates by strategy type
