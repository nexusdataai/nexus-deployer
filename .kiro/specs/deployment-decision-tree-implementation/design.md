# Design Document

## Overview

This design implements CloudFormation-based stack detection that queries actual AWS stack states and automatically recommends deployment strategies based on the Deployment Decision Tree. The system will replace the current TinyDB-only detection with real-time CloudFormation queries, enabling automatic detection of failed stacks and intelligent strategy recommendations.

The design follows the decision tree logic:
- **No stacks exist** → Recommend UPDATE_EXISTING (first deployment)
- **All stacks stable** (CREATE_COMPLETE/UPDATE_COMPLETE) → Recommend UPDATE_EXISTING
- **Any stack failed** (ROLLBACK_COMPLETE, UPDATE_ROLLBACK_COMPLETE, DELETE_FAILED, CREATE_FAILED) → Recommend CLEAN_DEPLOY
- **Any stack in progress** → Recommend WAIT

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React)                          │
│  ┌────────────────────────────────────────────────────┐    │
│  │  StrategySelection Component                        │    │
│  │  - Calls /api/deployment/detect-stacks             │    │
│  │  - Displays recommended strategy                    │    │
│  │  - Shows stack states and reasons                   │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                Backend API (FastAPI)                         │
│  ┌────────────────────────────────────────────────────┐    │
│  │  /api/deployment/detect-stacks endpoint            │    │
│  │  - Receives capability_name, environment, region   │    │
│  │  - Calls StackDetectionService                     │    │
│  │  - Returns StackDetectionResult with strategy      │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            StackDetectionService (Enhanced)                  │
│  ┌────────────────────────────────────────────────────┐    │
│  │  detect_existing_stacks()                          │    │
│  │  1. Query CloudFormation for actual stack states   │    │
│  │  2. Classify each stack (updatable/failed/progress)│    │
│  │  3. Apply decision tree logic                      │    │
│  │  4. Generate recommendation with reasoning         │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  AWS CloudFormation API                      │
│  - describe_stacks() for each expected stack                │
│  - Returns: StackName, StackStatus, StatusReason, etc.      │
└─────────────────────────────────────────────────────────────┘
```

### Stack Detection Flow

```
1. User navigates to Strategy Selection step
   │
   ▼
2. Frontend calls /api/deployment/detect-stacks
   │
   ▼
3. StackDetectionService.detect_existing_stacks()
   │
   ├─→ For each expected stack type:
   │   ├─→ Determine correct region (us-east-1 for global, target region for others)
   │   ├─→ Call CloudFormation describe_stacks()
   │   ├─→ Handle stack not found (mark as "not found", not failed)
   │   ├─→ Extract: name, status, status_reason, timestamps
   │   └─→ Classify: updatable / failed / in-progress
   │
   ▼
4. Apply Decision Tree Logic
   │
   ├─→ Any stack in progress? → Recommend WAIT
   ├─→ Any stack failed? → Recommend CLEAN_DEPLOY
   ├─→ All stacks updatable or not found? → Recommend UPDATE_EXISTING
   └─→ No stacks exist? → Recommend UPDATE_EXISTING
   │
   ▼
5. Generate human-readable reasoning
   │
   ▼
6. Return StackDetectionResult to frontend
   │
   ▼
7. Frontend displays recommendation with details
```

## Components and Interfaces

### 1. Enhanced StackDetectionService

**Location:** `backend/app/services/stack_detection_service.py`

**Key Methods:**

```python
class StackDetectionService:
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """Initialize with optional AWS credentials"""
        
    def detect_existing_stacks(
        self,
        capability_name: str,
        environment: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> StackDetectionResult:
        """
        Detect existing stacks by querying CloudFormation
        
        Returns:
            StackDetectionResult with:
            - stacks_found: List of ExistingStackInfo
            - recommended_strategy: CLEAN_DEPLOY | UPDATE_EXISTING | None (if wait)
            - recommendation_reason: Human-readable explanation
            - has_failed_stacks: Boolean
            - has_in_progress_stacks: Boolean
        """
        
    def _query_cloudformation_stack(
        self,
        stack_name: str,
        region: str,
        cfn_client
    ) -> Optional[ExistingStackInfo]:
        """Query CloudFormation for a single stack"""
        
    def _classify_stack_state(self, stack_status: str) -> str:
        """Classify stack status as: updatable, failed, or in_progress"""
        
    def _recommend_strategy(
        self,
        stacks: List[ExistingStackInfo]
    ) -> Tuple[Optional[DeploymentStrategy], str]:
        """
        Apply decision tree logic to recommend strategy
        
        Returns:
            (strategy, reason) tuple
        """
```

### 2. Updated StackDetectionResult Model

**Location:** `backend/app/models/stack_detection.py`

**Enhanced Fields:**

```python
class ExistingStackInfo(BaseModel):
    stack_name: str
    stack_type: str
    stack_status: str  # CloudFormation status
    region: str
    created_at: Optional[datetime]
    last_updated_at: Optional[datetime]
    is_updatable: bool  # Derived from status
    status_reason: Optional[str]  # Why stack is in this state
    classification: str  # "updatable", "failed", "in_progress"

class StackDetectionResult(BaseModel):
    capability_name: str
    environment: str
    region: str
    stacks_found: List[ExistingStackInfo]
    has_existing_stacks: bool
    has_failed_stacks: bool
    has_in_progress_stacks: bool
    is_updatable: bool
    recommended_strategy: Optional[DeploymentStrategy]  # NEW
    recommendation_reason: str  # NEW
    detection_timestamp: datetime
    error_message: Optional[str] = None
```

### 3. New API Endpoint

**Location:** `backend/app/routers/deployment.py`

```python
@router.post("/detect-stacks")
async def detect_stacks(request: StackDetectionRequest):
    """
    Detect existing stacks and recommend deployment strategy
    
    Request:
        - capability_name
        - environment
        - region
        - aws_session_id (for credentials)
        
    Response:
        - StackDetectionResult with recommendation
    """
```

### 4. Frontend Integration

**Location:** `frontend/src/components/StrategySelection.tsx`

**Changes:**
- Call `/api/deployment/detect-stacks` on component mount
- Display recommended strategy prominently
- Show stack states in a table
- Display recommendation reasoning
- Allow user to override recommendation if needed

## Data Models

### Stack State Classification

```python
UPDATABLE_STATES = {
    'CREATE_COMPLETE',
    'UPDATE_COMPLETE',
}

FAILED_STATES = {
    'ROLLBACK_COMPLETE',
    'UPDATE_ROLLBACK_COMPLETE',
    'DELETE_FAILED',
    'CREATE_FAILED',
}

IN_PROGRESS_STATES = {
    'CREATE_IN_PROGRESS',
    'UPDATE_IN_PROGRESS',
    'DELETE_IN_PROGRESS',
    'ROLLBACK_IN_PROGRESS',
    'UPDATE_ROLLBACK_IN_PROGRESS',
}
```

### Expected Stack Types by Deployment

```python
FRONTEND_STACKS = [
    'frontend-global',    # Region: us-east-1
    'frontend-regional',  # Region: target region
]

BACKEND_STACKS = [
    'backend-foundation', # Region: target region
    'backend-storage',    # Region: target region
    'backend-service',    # Region: target region
]
```

### Decision Tree Logic

```python
def _recommend_strategy(stacks: List[ExistingStackInfo]) -> Tuple[Optional[DeploymentStrategy], str]:
    """
    Decision tree implementation:
    
    1. If no stacks exist:
       → UPDATE_EXISTING, "First deployment - no existing stacks"
       
    2. If any stack is in progress:
       → None, "Wait for in-progress operations: [stack names]"
       
    3. If any stack is failed:
       → CLEAN_DEPLOY, "Failed stacks detected: [stack names with states]"
       
    4. If all stacks are updatable:
       → UPDATE_EXISTING, "All stacks are stable and updatable"
       
    5. Mixed states (some not found, some updatable):
       → UPDATE_EXISTING, "Partial deployment detected - can update existing and create missing"
    """
```

## Error Handling

### CloudFormation API Errors

1. **Stack Not Found (ResourceNotFoundException)**
   - Not treated as error
   - Mark stack as "not found"
   - Classification: "updatable" (can be created)

2. **Access Denied (AccessDeniedException)**
   - Log error
   - Include in error_message
   - Continue with other stacks
   - Return partial results

3. **Expired Credentials (ExpiredTokenException)**
   - Return clear error message
   - Suggest re-authentication
   - Don't crash

4. **Network/Timeout Errors**
   - Log error
   - Include in error_message
   - Return partial results if available

### Multi-Region Handling

- Frontend-global stacks: Query us-east-1
- Other stacks: Query target region
- If one region fails, continue with other region
- Aggregate errors in error_message field

## Testing Strategy

### Unit Tests

1. **Stack Classification Tests**
   - Test each CloudFormation status maps to correct classification
   - Test edge cases (unknown statuses)

2. **Decision Tree Logic Tests**
   - Test all decision tree branches
   - Test with various stack state combinations
   - Verify correct strategy recommendations

3. **CloudFormation Query Tests**
   - Mock boto3 CloudFormation client
   - Test successful queries
   - Test stack not found handling
   - Test error handling

### Integration Tests

1. **End-to-End Detection Test**
   - Create test stacks in AWS (or use mocks)
   - Query detection service
   - Verify correct results

2. **Multi-Region Test**
   - Test with frontend-global (us-east-1) and regional stacks
   - Verify correct region routing

3. **API Endpoint Test**
   - Test /detect-stacks endpoint
   - Verify request/response format
   - Test with various scenarios

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Stack state classification consistency

*For any* CloudFormation stack status, the classification function should always return one of: "updatable", "failed", or "in_progress", and the classification should match the decision tree matrix.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**

### Property 2: Strategy recommendation determinism

*For any* given set of stack states, the recommendation function should always return the same strategy and the strategy should follow the decision tree logic.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

### Property 3: Region routing correctness

*For any* stack type, if the stack type is "frontend-global" then the query region should be "us-east-1", otherwise it should be the target region.

**Validates: Requirements 5.1, 5.2, 5.3**

### Property 4: Error resilience

*For any* CloudFormation API error (except authentication), the system should return a StackDetectionResult (possibly with partial data) and should not crash.

**Validates: Requirements 6.4, 6.5**

### Property 5: Stack not found handling

*For any* stack that does not exist in CloudFormation, the system should classify it as "updatable" (can be created) and should not classify it as "failed".

**Validates: Requirements 1.3, 2.8**

### Property 6: Recommendation reasoning completeness

*For any* strategy recommendation, the reasoning should include specific stack names and states that led to the recommendation.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

### Property 7: Backward compatibility

*For any* existing code that calls StackDetectionService, the API signature should remain compatible (new parameters are optional).

**Validates: Requirements 7.1, 7.2, 7.3**
