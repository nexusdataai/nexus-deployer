# Real-Time Deletion Log Streaming Requirements

## Problem Statement

Users report that deletion logs are not refreshing in real-time during capability deletion. The logs appear all at once when the deletion completes, rather than streaming live updates every 15 seconds as expected.

## Current Issues

1. **ECR Repository Naming Error**: ECR repository names must follow AWS naming constraints (lowercase, alphanumeric, hyphens, underscores, periods only)
2. **Log Refresh Frequency**: Deletion logs not updating every 15 seconds during stack deletion
3. **Real-Time Feedback**: Users don't see progress during long-running stack deletions

## User Stories

### US-1: Real-Time Log Streaming
**As a** user deleting a capability  
**I want** to see deletion logs update every 15 seconds  
**So that** I know the deletion is progressing and not stuck

**Acceptance Criteria:**
- Deletion logs update every 15 seconds during stack deletion
- Each stack deletion shows progress messages like "DELETE_IN_PROGRESS (30s elapsed)"
- Frontend polls backend every 2 seconds for new logs
- Backend flushes logs immediately to the job storage

### US-2: ECR Repository Naming Fix
**As a** user deleting a capability with ECR repositories  
**I want** ECR deletion to succeed without naming errors  
**So that** the deletion completes successfully

**Acceptance Criteria:**
- ECR repository names are sanitized to lowercase alphanumeric with allowed special characters
- No "Invalid parameter" errors during ECR deletion
- ECR repositories are successfully deleted

### US-3: Stack Deletion Progress
**As a** user waiting for stack deletion  
**I want** to see detailed progress for each stack  
**So that** I understand what's happening and how long it might take

**Acceptance Criteria:**
- Each stack shows "DELETE_IN_PROGRESS" messages every 15 seconds
- Elapsed time is displayed for each stack deletion
- Final status (DELETE_COMPLETE/DELETE_FAILED) is shown clearly
- Error messages are displayed if deletion fails

## Technical Requirements

### Backend Changes
1. **Cleanup Service**: Ensure `delete_stack_with_status` logs every 15 seconds
2. **ECR Naming**: Sanitize ECR repository names to meet AWS constraints
3. **Log Flushing**: Ensure logs are immediately available to polling endpoints

### Frontend Changes
1. **Polling Frequency**: Continue polling every 2 seconds
2. **Log Display**: Show logs as they arrive, not just when complete
3. **Progress Indicators**: Show elapsed time and current status

## Success Metrics

- Deletion logs update within 15 seconds of backend log generation
- ECR deletion succeeds without naming errors
- Users see continuous progress during long-running deletions
- No more "logs not refreshing" user complaints

## Dependencies

- Existing deletion infrastructure (async jobs, polling endpoints)
- CloudFormation stack deletion APIs
- ECR repository deletion APIs

## Risks

- High polling frequency might impact performance
- Log storage might grow large for long deletions
- Network issues could cause log polling failures

## Out of Scope

- Changing the overall deletion architecture
- Adding WebSocket real-time streaming
- Modifying the deletion job storage mechanism