# Design Document

## Overview

This design addresses a critical bug in the pre-deployment validation system where orphaned resource detection incorrectly runs against stable, existing CloudFormation stacks. The fix involves modifying the validation logic to only check for orphaned resources when the stack does not exist, and adding strategy-aware validation to skip pre-deployment checks for CLEAN_DEPLOY operations.

The solution ensures that:
1. Stack-managed resources are never incorrectly identified as orphaned
2. Orphaned resource detection only runs when truly needed
3. CLEAN_DEPLOY strategy bypasses validation to avoid duplicate cleanup
4. Clear logging explains all validation decisions

## Architecture

### Component Interaction

```
DeploymentOrchestrator
    ↓
    ├─→ [Check Strategy]
    │   ├─→ CLEAN_DEPLOY → Skip Validation → Cleanup → Deploy
    │   └─→ UPDATE_EXISTING → Run Validation → Deploy
    │
    └─→ PreDeploymentValidator
        ↓
        ├─→ Check Stack Status
        │   ├─→ NOT_EXISTS → Check Orphaned Resources
        │   ├─→ UNSTABLE → Delete Stack → Skip Orphaned Check
        │   └─→ STABLE → Skip Orphaned Check
        │
        └─→ OrphanedResourceDetection (only if stack NOT_EXISTS)
```

### Key Changes

1. **PreDeploymentValidator.validate_deployment()**
   - Add stack status check before orphaned resource detection
   - Only run orphaned resource detection when stack does NOT exist
   - Skip orphaned resource detection for STABLE stacks
   - Skip orphaned resource detection after deleting UNSTABLE stacks

2. **DeploymentOrchestrator.deploy_capability_with_strategy()**
   - Check deployment strategy before running validation
   - Skip validation entirely for CLEAN_DEPLOY strategy
   - Run validation only for UPDATE_EXISTING strategy

## Components and Interfaces

### Modified: PreDeploymentValidator

**File**: `backend/app/services/pre_deployment_validator.py`

**Changes to `validate_deployment()` method**:

```python
def validate_deployment(
    self,
    config: Dict[str, Any],
    deploy_frontend: bool,
    deploy_backend: bool,
    callback: Optional[Callable] = None
) -> ValidationReport:
    """
    Validate deployment configuration and environment
    
    Key Logic Changes:
    1. Check stack status BEFORE orphaned resource detection
    2. Only check orphaned resources if stack does NOT exist
    3. Skip orphaned check for STABLE stacks
    4. Skip orphaned check after deleting UNSTABLE stacks
    """
```

**New Logic Flow**:

```python
for stack_type in stacks_to_validate:
    stack_name = get_stack_name(...)
    status = self.check_stack_status(stack_name, region)
    
    # Handle unstable stacks
    if status == StackStatus.UNSTABLE:
        cleanup_unstable_stack(...)
        # SKIP orphaned resource check - stack deletion handles cleanup
        continue
    
    # Handle stable stacks
    if status == StackStatus.STABLE:
        # SKIP orphaned resource check - resources are managed by stack
        log("Skipping orphaned resource check for stable stack")
        continue
    
    # Handle non-existent stacks
    if status == StackStatus.NOT_EXISTS:
        # ONLY NOW check for orphaned resources
        orphaned = detect_orphaned_resources(...)
        cleanup_orphaned_resources(orphaned)
```

### Modified: DeploymentOrchestrator

**File**: `backend/app/services/deployment_orchestrator.py`

**Changes to `deploy_capability_with_strategy()` method**:

```python
def deploy_capability_with_strategy(
    self,
    config: Dict[str, Any],
    strategy: DeploymentStrategy,
    deploy_frontend: bool = True,
    deploy_backend: bool = True,
    callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Deploy with strategy-aware validation
    
    Key Logic Changes:
    1. Skip validation for CLEAN_DEPLOY strategy
    2. Run validation only for UPDATE_EXISTING strategy
    """
```

**New Logic Flow**:

```python
if strategy == DeploymentStrategy.CLEAN_DEPLOY:
    # Skip validation - cleanup will handle everything
    log("Skipping pre-deployment validation for CLEAN_DEPLOY strategy")
    
    # Perform cleanup
    cleanup_result = self.cleanup_capability(...)
    
    # Deploy fresh
    result = self.deploy_capability(config, ..., skip_validation=True)
    
elif strategy == DeploymentStrategy.UPDATE_EXISTING:
    # Run validation as normal
    result = self.deploy_capability(config, ..., skip_validation=False)
```

**Changes to `deploy_capability()` method**:

Add optional parameter to skip validation:

```python
def deploy_capability(
    self,
    config: Dict[str, Any],
    deploy_frontend: bool = True,
    deploy_backend: bool = True,
    callback: Optional[Callable] = None,
    skip_validation: bool = False  # NEW PARAMETER
) -> Dict[str, Any]:
    """
    Deploy a complete capability
    
    Args:
        skip_validation: If True, skip pre-deployment validation
    """
    
    # Check if validation should run
    validation_enabled = config.get('deployment', {}).get('pre_validation', {}).get('enabled', True)
    
    if skip_validation or not validation_enabled:
        # Skip validation
        pass
    else:
        # Run validation
        validation_report = self.validator.validate_deployment(...)
```

## Data Models

No changes to existing data models. The fix uses existing structures:

- `StackStatus` enum (already defined)
- `ValidationReport` (already defined)
- `DeploymentStrategy` enum (already defined)

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Stable stacks never trigger orphaned resource detection

*For any* CloudFormation stack in a stable state (CREATE_COMPLETE, UPDATE_COMPLETE), running pre-deployment validation should NOT execute orphaned resource detection for that stack.

**Validates: Requirements 1.1, 1.5**

### Property 2: Non-existent stacks always trigger orphaned resource detection

*For any* stack name that does not exist in CloudFormation, running pre-deployment validation should execute orphaned resource detection to find resources left behind.

**Validates: Requirements 1.2**

### Property 3: Unstable stack deletion skips orphaned resource detection

*For any* CloudFormation stack in an unstable state, after the validator deletes the stack, it should NOT run orphaned resource detection.

**Validates: Requirements 1.3**

### Property 4: CLEAN_DEPLOY strategy skips validation

*For any* deployment using CLEAN_DEPLOY strategy, the deployment orchestrator should NOT run pre-deployment validation.

**Validates: Requirements 1.4, 4.1**

### Property 5: UPDATE_EXISTING strategy runs validation

*For any* deployment using UPDATE_EXISTING strategy, the deployment orchestrator should run pre-deployment validation (unless explicitly disabled in config).

**Validates: Requirements 4.2**

### Property 6: Validation skip is logged

*For any* case where validation or orphaned resource detection is skipped, the system should log the reason and relevant context.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

## Error Handling

### Stack Status Check Failures

- If `check_stack_status()` raises an exception (other than "does not exist"), propagate the error
- Log the error with full context
- Return validation failure with error details

### Orphaned Resource Detection Failures

- If `detect_orphaned_resources()` raises an exception, log the error but continue validation
- Mark the issue as unresolved in the validation report
- Do not fail the entire validation due to detection errors

### Cleanup Failures

- If orphaned resource cleanup fails, mark the issue as unresolved
- Log the failure with resource details
- Continue with remaining validations
- Return validation failure if any critical issues remain unresolved

## Testing Strategy

### Unit Tests

1. **Test stable stack skips orphaned detection**
   - Mock `check_stack_status()` to return `StackStatus.STABLE`
   - Call `validate_deployment()`
   - Assert `detect_orphaned_resources()` is NOT called
   - Assert log contains "Skipping orphaned resource check for stable stack"

2. **Test non-existent stack triggers orphaned detection**
   - Mock `check_stack_status()` to return `StackStatus.NOT_EXISTS`
   - Call `validate_deployment()`
   - Assert `detect_orphaned_resources()` IS called
   - Assert orphaned resources are cleaned up

3. **Test unstable stack deletion skips orphaned detection**
   - Mock `check_stack_status()` to return `StackStatus.UNSTABLE`
   - Mock `cleanup_unstable_stack()` to return True
   - Call `validate_deployment()`
   - Assert `detect_orphaned_resources()` is NOT called after cleanup

4. **Test CLEAN_DEPLOY skips validation**
   - Call `deploy_capability_with_strategy()` with `DeploymentStrategy.CLEAN_DEPLOY`
   - Assert `validator.validate_deployment()` is NOT called
   - Assert log contains "Skipping pre-deployment validation"

5. **Test UPDATE_EXISTING runs validation**
   - Call `deploy_capability_with_strategy()` with `DeploymentStrategy.UPDATE_EXISTING`
   - Assert `validator.validate_deployment()` IS called

### Integration Tests

1. **Test full UPDATE_EXISTING flow with stable stack**
   - Create a stable stack in test environment
   - Run deployment with UPDATE_EXISTING strategy
   - Verify stack resources are not deleted
   - Verify stack update succeeds

2. **Test full CLEAN_DEPLOY flow**
   - Create a stable stack in test environment
   - Run deployment with CLEAN_DEPLOY strategy
   - Verify validation is skipped
   - Verify cleanup runs
   - Verify fresh deployment succeeds

### Property-Based Tests

Property-based tests will be defined in the tasks document and implemented during the implementation phase.

## Logging Strategy

### Log Levels

- **INFO**: Normal validation flow, decisions made, resources found
- **WARNING**: Skipped checks, non-critical issues
- **ERROR**: Validation failures, cleanup failures

### Key Log Messages

1. "Skipping pre-deployment validation for CLEAN_DEPLOY strategy"
2. "Checking stack: {stack_name}"
3. "Stack {stack_name} is STABLE - skipping orphaned resource check"
4. "Stack {stack_name} does NOT exist - checking for orphaned resources"
5. "Stack {stack_name} is UNSTABLE - will delete and skip orphaned check"
6. "Cleaned up unstable stack {stack_name} - skipping orphaned resource check"

### Callback Messages

All log messages should also be sent to the callback (if provided) for UI display:

```python
if callback:
    callback(f"✓ Stack {stack_name} is stable - skipping orphaned resource check")
```

## Backward Compatibility

This fix maintains backward compatibility:

1. **Configuration**: No changes to configuration schema
2. **API**: No changes to public method signatures (only adds optional parameter with default)
3. **Behavior**: Improves correctness without breaking existing workflows
4. **Validation**: Can still be disabled via config if needed

## Performance Considerations

This fix improves performance by:

1. **Reducing unnecessary checks**: Skipping orphaned resource detection for stable stacks eliminates AWS API calls
2. **Faster CLEAN_DEPLOY**: Skipping validation for clean deployments reduces total deployment time
3. **Fewer AWS API calls**: Less resource detection means fewer describe/list operations

## Security Considerations

This fix improves security by:

1. **Preventing accidental deletion**: Stack-managed resources are never deleted by validation
2. **Maintaining resource integrity**: Resources remain under CloudFormation management
3. **Audit trail**: Clear logging of all validation decisions

## Deployment Plan

1. **Phase 1**: Update `PreDeploymentValidator.validate_deployment()` with new logic
2. **Phase 2**: Update `DeploymentOrchestrator.deploy_capability_with_strategy()` to skip validation for CLEAN_DEPLOY
3. **Phase 3**: Update `DeploymentOrchestrator.deploy_capability()` to accept `skip_validation` parameter
4. **Phase 4**: Add comprehensive logging
5. **Phase 5**: Test with real deployments

## Rollback Plan

If issues arise:

1. Revert changes to `pre_deployment_validator.py`
2. Revert changes to `deployment_orchestrator.py`
3. The system will return to previous behavior (with the bug)

## Future Enhancements

1. **Stack resource tracking**: Query CloudFormation to get actual stack resources before checking orphaned status
2. **Resource tagging**: Use tags to identify stack-managed vs orphaned resources
3. **Dry-run mode**: Allow validation to run without cleanup for testing
4. **Validation reports**: Store validation reports for audit and debugging
