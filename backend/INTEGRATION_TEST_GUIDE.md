# Integration Testing Guide for Pre-Deployment Validation Fix

This guide provides step-by-step instructions for manually testing the pre-deployment validation fix with real AWS deployments.

## Prerequisites

1. AWS account with appropriate permissions
2. AWS credentials configured
3. Test capability configuration file
4. Frontend artifact in S3 (for frontend deployments)

## Test Scenario 1: UPDATE_EXISTING with Stable Stack

**Objective**: Verify that stable stacks do NOT have their resources deleted during UPDATE_EXISTING deployment.

### Steps:

1. **Initial Deployment** - Create a stable stack:
   ```bash
   # Deploy a capability to create initial stable stacks
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   ```

2. **Verify Stack is Stable**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - Confirm StackStatus is `CREATE_COMPLETE` or `UPDATE_COMPLETE`

3. **Verify S3 Bucket Exists**:
   ```bash
   aws s3 ls | grep test-capability-dev-frontend
   ```
   - Note the bucket name

4. **Re-deploy with UPDATE_EXISTING**:
   ```bash
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   ```

5. **Check Deployment Logs**:
   - Look for: "Stack test-capability-dev-frontend-regional is stable - skipping orphaned resource check"
   - Should NOT see: "Checking for orphaned resources"
   - Should NOT see: "Cleaning up S3 bucket"

6. **Verify S3 Bucket Still Exists**:
   ```bash
   aws s3 ls | grep test-capability-dev-frontend
   ```
   - Bucket should still exist with same name
   - Files should still be present

7. **Verify Stack Update Succeeded**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - StackStatus should be `UPDATE_COMPLETE`
   - Should NOT be `UPDATE_ROLLBACK_COMPLETE`

### Expected Results:
- ✅ Validation runs but skips orphaned resource detection for stable stack
- ✅ S3 bucket is NOT deleted
- ✅ Stack update succeeds without rollback
- ✅ Deployment completes successfully

### Failure Indicators:
- ❌ S3 bucket is deleted during validation
- ❌ Stack update fails with "resource doesn't exist" error
- ❌ Stack status is `UPDATE_ROLLBACK_COMPLETE`

---

## Test Scenario 2: UPDATE_EXISTING with Non-Existent Stack

**Objective**: Verify that orphaned resources are detected and cleaned when stack doesn't exist.

### Steps:

1. **Create Orphaned Resources** - Deploy then manually delete stack:
   ```bash
   # Deploy capability
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   
   # Manually delete the stack (but leave S3 bucket)
   aws cloudformation delete-stack \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   
   # Wait for deletion
   aws cloudformation wait stack-delete-complete \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```

2. **Verify Stack Doesn't Exist**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - Should return error: "Stack does not exist"

3. **Verify S3 Bucket Still Exists** (orphaned):
   ```bash
   aws s3 ls | grep test-capability-dev-frontend
   ```
   - Bucket should still exist (orphaned resource)

4. **Re-deploy with UPDATE_EXISTING**:
   ```bash
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   ```

5. **Check Deployment Logs**:
   - Look for: "Stack test-capability-dev-frontend-regional does not exist - checking for orphaned resources"
   - Should see: "Found X orphaned resources"
   - Should see: "Cleaning up S3 bucket"

6. **Verify Orphaned Resources Cleaned**:
   ```bash
   aws s3 ls | grep test-capability-dev-frontend
   ```
   - Old bucket should be deleted

7. **Verify New Stack Created**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - StackStatus should be `CREATE_COMPLETE`

### Expected Results:
- ✅ Validation detects stack doesn't exist
- ✅ Orphaned resources are detected
- ✅ Orphaned S3 bucket is cleaned up
- ✅ New stack is created successfully

---

## Test Scenario 3: CLEAN_DEPLOY Strategy

**Objective**: Verify that CLEAN_DEPLOY skips validation entirely.

### Steps:

1. **Deploy with Stable Stack**:
   ```bash
   # Create initial deployment
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   ```

2. **Verify Stack is Stable**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```

3. **Re-deploy with CLEAN_DEPLOY**:
   ```bash
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy CLEAN_DEPLOY \
     --frontend
   ```

4. **Check Deployment Logs**:
   - Look for: "Skipping pre-deployment validation for CLEAN_DEPLOY strategy"
   - Should NOT see: "Running pre-deployment validation"
   - Should see: "Step 1: Cleaning up existing stacks"
   - Should see: "Step 2: Deploying fresh stacks"

5. **Verify Cleanup Happened**:
   - Old stack should be deleted
   - Old S3 bucket should be deleted

6. **Verify New Deployment Succeeded**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - StackStatus should be `CREATE_COMPLETE`

### Expected Results:
- ✅ Validation is completely skipped
- ✅ Cleanup runs first
- ✅ Fresh deployment succeeds
- ✅ No validation-related errors

---

## Test Scenario 4: Unstable Stack Cleanup

**Objective**: Verify that unstable stacks are deleted without orphaned resource check.

### Steps:

1. **Create Unstable Stack** - Force a stack into ROLLBACK_COMPLETE:
   ```bash
   # Deploy with intentionally bad configuration to cause rollback
   # (e.g., invalid parameter value)
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev-bad.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   ```

2. **Verify Stack is Unstable**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - StackStatus should be `ROLLBACK_COMPLETE` or similar unstable state

3. **Re-deploy with Correct Configuration**:
   ```bash
   python -m app.cli.deploy \
     --config deploy/config/test-capability-dev.yaml \
     --strategy UPDATE_EXISTING \
     --frontend
   ```

4. **Check Deployment Logs**:
   - Look for: "Stack test-capability-dev-frontend-regional is UNSTABLE - will delete and skip orphaned check"
   - Look for: "Cleaned up unstable stack - skipping orphaned resource check"
   - Should NOT see: "Checking for orphaned resources" after unstable stack deletion

5. **Verify New Stack Created**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name test-capability-dev-frontend-regional \
     --region us-east-1
   ```
   - StackStatus should be `CREATE_COMPLETE`

### Expected Results:
- ✅ Unstable stack is detected
- ✅ Unstable stack is deleted
- ✅ Orphaned resource check is skipped after deletion
- ✅ New stack is created successfully

---

## Verification Checklist

After running all test scenarios, verify:

- [ ] Stable stacks never have resources deleted during UPDATE_EXISTING
- [ ] Non-existent stacks trigger orphaned resource detection
- [ ] CLEAN_DEPLOY completely skips validation
- [ ] Unstable stacks are cleaned without orphaned resource check
- [ ] All logging messages are present and accurate
- [ ] No unexpected errors or rollbacks
- [ ] S3 buckets are only deleted when appropriate

## Troubleshooting

### If S3 Bucket is Deleted During UPDATE_EXISTING:
- Check logs for "skipping orphaned resource check"
- Verify stack status was STABLE before deployment
- Check if validation was actually skipped

### If Validation Doesn't Run for UPDATE_EXISTING:
- Check config file for `pre_validation.enabled: false`
- Verify skip_validation parameter is not being passed incorrectly

### If CLEAN_DEPLOY Runs Validation:
- Check logs for "Skipping pre-deployment validation"
- Verify strategy is correctly set to CLEAN_DEPLOY

## Cleanup

After testing, clean up test resources:

```bash
# Delete test stacks
aws cloudformation delete-stack \
  --stack-name test-capability-dev-frontend-regional \
  --region us-east-1

# Delete test S3 buckets
aws s3 rb s3://test-capability-dev-frontend-bucket --force

# Delete deployment state
rm -f deploy/state/test-capability-dev.json
```

## Success Criteria

All tests pass if:
1. ✅ No S3 buckets are deleted during UPDATE_EXISTING with stable stacks
2. ✅ Orphaned resources are cleaned when stack doesn't exist
3. ✅ CLEAN_DEPLOY skips validation entirely
4. ✅ Unstable stacks are cleaned without orphaned checks
5. ✅ All logging messages are correct and informative
