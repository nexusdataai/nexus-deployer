# Implementation Plan: Startup Health Check

## Overview

This implementation plan addresses the race condition where the frontend displays errors when fetching capabilities before the backend is ready. The tasks are ordered to first add the backend startup manager and health endpoint, then update Electron to wait for backend readiness, and finally add frontend loading state and retry logic.

## Tasks

- [x] 1. Create backend startup manager
  - [x] 1.1 Create backend/app/services/startup_manager.py
    - Implement StartupManager class with component registration
    - Add InitializationPhase enum (PENDING, LOGGING, DATABASE, TEMPLATES, ROUTES, READY, DEGRADED, FAILED)
    - Implement ComponentStatus and StartupState dataclasses
    - Add ordered initialization with dependency tracking
    - Implement get_readiness() method for health endpoint
    - _Requirements: 5.1, 5.3, 5.5, 5.6_
  - [x] 1.2 Write property test for startup sequence ordering
    - **Property 2: Startup Sequence Ordering**
    - **Validates: Requirements 5.1, 5.3**

- [x] 2. Create backend health endpoint
  - [x] 2.1 Create backend/app/routers/health.py
    - Implement `/api/health/ready` endpoint returning ReadinessResponse
    - Return HTTP 200 when ready, HTTP 503 when initializing
    - Include component status, phase, and timing information
    - Implement `/api/health/live` liveness probe
    - Implement `/api/health` detailed health with metrics
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [x] 2.2 Write property test for readiness endpoint
    - **Property 1: Readiness Endpoint Consistency**
    - **Validates: Requirements 1.2, 1.3, 5.6**

- [x] 3. Integrate startup manager into backend main.py
  - [x] 3.1 Update backend/app/main.py
    - Initialize StartupManager on startup
    - Register components: logging, database, templates, routes
    - Update startup_event to use StartupManager
    - Include health router
    - _Requirements: 5.1, 5.2, 5.4_
  - [x] 3.2 Write property test for degraded mode
    - **Property 5: Degraded Mode Consistency**
    - **Validates: Requirements 5.4, 6.1, 6.2, 6.5**

- [x] 4. Checkpoint - Verify backend health endpoint
  - Test `/api/health/ready` returns correct status during startup
  - Verify response time is under 500ms
  - Ensure all tests pass, ask the user if questions arise

- [x] 5. Create Electron health poller
  - [x] 5.1 Create electron/startup/health-poller.js
    - Implement HealthPoller class with exponential backoff
    - Add waitForReady() method with configurable timeout
    - Add checkHealth() method for single health check
    - Implement calculateDelay() with exponential backoff formula
    - Add logging for each poll attempt
    - _Requirements: 2.2, 2.3, 2.5_
  - [x] 5.2 Write property test for exponential backoff
    - **Property 3: Exponential Backoff Correctness**
    - **Validates: Requirements 2.3, 4.3**

- [x] 6. Create Electron startup orchestrator
  - [x] 6.1 Create electron/startup/orchestrator.js
    - Implement StartupOrchestrator class
    - Add start() method to coordinate full startup
    - Add startBackend() and waitForBackend() methods
    - Implement handleBackendCrash() for recovery
    - Add getStatus() for progress reporting
    - _Requirements: 2.1, 2.4, 2.6, 9.1, 9.2_
  - [x] 6.2 Write property test for timeout enforcement
    - **Property 6: Timeout Enforcement**
    - **Validates: Requirements 2.4, 7.1, 7.3**

- [x] 7. Update Electron main.js to use startup orchestrator
  - [x] 7.1 Update electron/main.js
    - Replace direct backend spawn with StartupOrchestrator
    - Wait for backend ready before loading frontend
    - Add crash detection and recovery handling
    - Send startup status to frontend via IPC
    - _Requirements: 2.1, 2.6, 9.1, 9.2, 9.3_
  - [x] 7.2 Write property test for service recovery
    - **Property 7: Service Recovery Detection**
    - **Validates: Requirements 9.1, 9.2**

- [x] 8. Checkpoint - Verify Electron startup orchestration
  - Test backend is ready before frontend loads
  - Verify timeout handling works correctly
  - Test crash recovery restarts backend
  - Ensure all tests pass, ask the user if questions arise

- [x] 9. Create frontend API retry layer
  - [x] 9.1 Create frontend/src/services/api-retry.ts
    - Implement ApiRetryLayer class with configurable retries
    - Add executeWithRetry() method with exponential backoff
    - Support retry callbacks for progress reporting
    - Handle connection errors and 503 responses
    - _Requirements: 4.1, 4.2, 4.3, 4.6_
  - [x] 9.2 Write property test for retry exhaustion
    - **Property 4: Retry Exhaustion Behavior**
    - **Validates: Requirements 4.4, 4.5**

- [x] 10. Update frontend API service to use retry layer
  - [x] 10.1 Update frontend/src/services/api.ts
    - Wrap axios instance with ApiRetryLayer
    - Add retry configuration for startup-critical endpoints
    - Preserve existing API interface
    - _Requirements: 4.1, 4.2, 4.6_

- [x] 11. Create frontend loading screen component
  - [x] 11.1 Create frontend/src/components/LoadingScreen.tsx
    - Implement LoadingScreen component with progress indicator
    - Display current initialization status message
    - Show error state with retry button
    - Add smooth transition to main UI
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [x] 11.2 Write property test for loading screen transitions
    - **Property 9: Loading Screen State Transitions**
    - **Validates: Requirements 3.1, 3.4**

- [x] 12. Create frontend health monitor service
  - [x] 12.1 Create frontend/src/services/health-monitor.ts
    - Implement HealthMonitor class with polling
    - Add subscribe() for status change notifications
    - Track health status and response times
    - Support degraded mode detection
    - _Requirements: 10.2, 10.3, 10.4_

- [x] 13. Create frontend health status indicator
  - [x] 13.1 Create frontend/src/components/HealthIndicator.tsx
    - Display health status icon in header
    - Show tooltip with status details
    - Open diagnostics panel on click
    - Display warning banner in degraded mode
    - _Requirements: 6.3, 10.1, 10.5, 10.6_

- [x] 14. Integrate loading screen into App.tsx
  - [x] 14.1 Update frontend/src/App.tsx
    - Add startup state management
    - Show LoadingScreen until backend ready
    - Initialize HealthMonitor after startup
    - Handle startup errors with retry
    - _Requirements: 3.1, 3.4, 3.5, 4.4, 4.5_

- [x] 15. Checkpoint - Verify frontend startup flow
  - Test loading screen appears on startup
  - Verify smooth transition to main UI
  - Test error handling and retry
  - Ensure all tests pass, ask the user if questions arise

- [x] 16. Add startup configuration support
  - [x] 16.1 Create electron/startup/config.js
    - Load configuration from environment variables
    - Support config file loading
    - Provide sensible defaults
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.6_
  - [x] 16.2 Write property test for configuration defaults
    - **Property 10: Configuration Defaults**
    - **Validates: Requirements 7.5, 7.6**

- [x] 17. Add startup diagnostics logging
  - [x] 17.1 Create electron/startup/diagnostics.js
    - Log timestamps for each startup phase
    - Include system information (OS, memory, disk)
    - Write to dedicated startup log file
    - Log full stack traces on errors
    - _Requirements: 8.1, 8.3, 8.4, 8.6_
  - [x] 17.2 Update backend startup manager for duration logging
    - Log initialization duration for each component
    - _Requirements: 8.2, 5.5_

- [x] 18. Add health response time property test
  - [x] 18.1 Write property test for health response time
    - **Property 8: Health Response Time**
    - **Validates: Requirements 1.6**

- [x] 19. Checkpoint - Integration testing
  - Test full startup sequence end-to-end
  - Verify no capability fetch errors on first screen
  - Test degraded mode behavior
  - Test configuration overrides
  - Ensure all tests pass, ask the user if questions arise

- [x] 20. Final checkpoint - End-to-end verification
  - Start application fresh
  - Verify loading screen appears
  - Verify smooth transition to capabilities list
  - Test backend crash recovery
  - Verify health indicator in header
  - Ensure all tests pass, ask the user if questions arise

## Notes

- All tasks including property-based tests are required
- Tasks 1-3 focus on backend startup manager and health endpoint
- Tasks 5-7 update Electron for startup orchestration
- Tasks 9-14 add frontend loading state and retry logic
- Tasks 16-17 add configuration and diagnostics
- Each task references specific requirements for traceability
- Property tests use hypothesis (Python) and fast-check (TypeScript)
