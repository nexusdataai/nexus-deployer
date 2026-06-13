<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Requirements Document

## Introduction

This document defines the requirements for implementing a robust startup health check system for the Nexus AI Capability Installer. The current implementation has a race condition where the frontend UI loads and attempts to fetch capabilities before the backend service is fully initialized, resulting in errors displayed to users on the first screen. This feature will ensure all services are ready before the UI becomes interactive, providing a smooth startup experience.

## Glossary

- **Electron_Shell**: The Electron application that hosts the frontend and spawns the backend process
- **Backend_Service**: The Python FastAPI backend that provides API endpoints for capabilities, deployments, and AWS operations
- **Frontend_UI**: The React-based user interface that displays capabilities and deployment wizards
- **Health_Check_Endpoint**: An API endpoint that returns the readiness status of a service
- **Startup_Orchestrator**: The component responsible for coordinating service startup sequence
- **Loading_Screen**: A visual indicator shown to users while services are initializing
- **Readiness_State**: The state indicating whether a service is ready to accept requests

## Requirements

### Requirement 1: Backend Health Check Endpoint

**User Story:** As a system component, I want to query the backend's readiness status, so that I can determine when it's safe to make API calls.

#### Acceptance Criteria

1. THE Backend_Service SHALL expose a `/api/health/ready` endpoint that returns readiness status
2. WHEN the Backend_Service is fully initialized THEN the Health_Check_Endpoint SHALL return HTTP 200 with `{"ready": true}`
3. WHEN the Backend_Service is still initializing THEN the Health_Check_Endpoint SHALL return HTTP 503 with `{"ready": false, "reason": "<initialization_step>"}`
4. THE Health_Check_Endpoint SHALL verify database connectivity before reporting ready
5. THE Health_Check_Endpoint SHALL verify template availability before reporting ready
6. THE Health_Check_Endpoint SHALL respond within 500ms to avoid blocking startup checks

### Requirement 2: Electron Startup Orchestration

**User Story:** As a user, I want the application to wait for all services before showing the main UI, so that I don't see errors on startup.

#### Acceptance Criteria

1. WHEN the Electron_Shell starts THEN it SHALL spawn the Backend_Service before loading the Frontend_UI
2. THE Electron_Shell SHALL poll the Health_Check_Endpoint until the Backend_Service reports ready
3. WHEN polling the Health_Check_Endpoint THEN the Electron_Shell SHALL use exponential backoff starting at 100ms
4. IF the Backend_Service does not become ready within 30 seconds THEN the Electron_Shell SHALL display an error message with retry option
5. THE Electron_Shell SHALL log all startup health check attempts for debugging
6. WHEN the Backend_Service reports ready THEN the Electron_Shell SHALL proceed to load the Frontend_UI

### Requirement 3: Frontend Loading State

**User Story:** As a user, I want to see a loading indicator during startup, so that I know the application is initializing.

#### Acceptance Criteria

1. WHEN the Frontend_UI loads THEN it SHALL display a Loading_Screen until backend readiness is confirmed
2. THE Loading_Screen SHALL display the current initialization status (e.g., "Connecting to backend...", "Loading capabilities...")
3. THE Loading_Screen SHALL include a progress indicator showing startup progress
4. WHEN the Backend_Service becomes ready THEN the Loading_Screen SHALL transition smoothly to the main UI
5. IF an error occurs during startup THEN the Loading_Screen SHALL display the error with a retry button
6. THE Loading_Screen SHALL match the application's visual design and branding

### Requirement 4: Frontend API Retry Logic

**User Story:** As a developer, I want the frontend to automatically retry failed API calls during startup, so that transient errors don't cause permanent failures.

#### Acceptance Criteria

1. WHEN an API call fails with a connection error THEN the Frontend_UI SHALL retry the call with exponential backoff
2. THE Frontend_UI SHALL retry failed API calls up to 3 times before showing an error
3. WHEN retrying an API call THEN the Frontend_UI SHALL wait 1s, 2s, then 4s between attempts
4. IF all retry attempts fail THEN the Frontend_UI SHALL display a user-friendly error message
5. THE Frontend_UI SHALL provide a manual retry button after all automatic retries are exhausted
6. WHEN the Backend_Service becomes available THEN pending retries SHALL succeed without user intervention

### Requirement 5: Backend Initialization Sequence

**User Story:** As a system administrator, I want the backend to initialize in a predictable order, so that dependencies are ready before dependent services.

#### Acceptance Criteria

1. THE Backend_Service SHALL initialize components in this order: logging, database, templates, API routes
2. WHEN database initialization fails THEN the Backend_Service SHALL retry up to 3 times before marking as degraded
3. THE Backend_Service SHALL track initialization progress and expose it via the Health_Check_Endpoint
4. IF a non-critical component fails to initialize THEN the Backend_Service SHALL continue startup in degraded mode
5. THE Backend_Service SHALL log the duration of each initialization step for performance monitoring
6. WHEN all critical components are initialized THEN the Backend_Service SHALL set Readiness_State to ready

### Requirement 6: Graceful Degradation

**User Story:** As a user, I want the application to work with reduced functionality if some services fail, so that I can still perform basic operations.

#### Acceptance Criteria

1. IF template validation fails on startup THEN the Backend_Service SHALL continue with a warning and allow manual validation
2. IF AWS credential cleanup fails on startup THEN the Backend_Service SHALL continue and log the error
3. THE Frontend_UI SHALL display a warning banner when operating in degraded mode
4. WHEN operating in degraded mode THEN the Frontend_UI SHALL disable features that require unavailable services
5. THE Health_Check_Endpoint SHALL report degraded status with list of unavailable features
6. THE Backend_Service SHALL periodically attempt to recover failed components in the background

### Requirement 7: Startup Timeout Configuration

**User Story:** As a system administrator, I want to configure startup timeouts, so that I can adjust for different deployment environments.

#### Acceptance Criteria

1. THE Electron_Shell SHALL support configurable backend startup timeout (default: 30 seconds)
2. THE Backend_Service SHALL support configurable initialization timeout per component
3. WHEN a timeout is exceeded THEN the system SHALL log detailed diagnostic information
4. THE Frontend_UI SHALL support configurable API retry timeout (default: 10 seconds)
5. Configuration values SHALL be readable from environment variables or config files
6. THE system SHALL use sensible defaults when configuration is not provided

### Requirement 8: Startup Diagnostics

**User Story:** As a developer, I want detailed startup logs, so that I can diagnose initialization failures.

#### Acceptance Criteria

1. THE Electron_Shell SHALL log timestamps for each startup phase
2. THE Backend_Service SHALL log initialization duration for each component
3. WHEN a startup failure occurs THEN the system SHALL log the full error stack trace
4. THE system SHALL write startup logs to a dedicated log file for easy access
5. THE Frontend_UI SHALL display a "View Logs" option when startup errors occur
6. Startup logs SHALL include system information (OS, memory, disk space) for diagnostics

### Requirement 9: Service Recovery

**User Story:** As a user, I want the application to recover automatically if a service crashes during use, so that I don't lose my work.

#### Acceptance Criteria

1. WHEN the Backend_Service crashes THEN the Electron_Shell SHALL detect the failure within 5 seconds
2. THE Electron_Shell SHALL automatically attempt to restart the Backend_Service up to 3 times
3. WHEN the Backend_Service is restarting THEN the Frontend_UI SHALL display a reconnecting indicator
4. IF the Backend_Service cannot be restarted THEN the Frontend_UI SHALL offer to save current state and restart the application
5. THE system SHALL preserve user session data across Backend_Service restarts
6. WHEN the Backend_Service recovers THEN the Frontend_UI SHALL automatically reconnect without user action

### Requirement 10: Health Check Monitoring

**User Story:** As a user, I want to see the current health status of services, so that I can identify issues before they cause problems.

#### Acceptance Criteria

1. THE Frontend_UI SHALL display a health status indicator in the application header
2. THE Frontend_UI SHALL poll the Health_Check_Endpoint every 30 seconds during normal operation
3. WHEN a service becomes unhealthy THEN the Frontend_UI SHALL display a warning notification
4. THE Health_Check_Endpoint SHALL return response time metrics for performance monitoring
5. THE Frontend_UI SHALL display detailed health information in a diagnostics panel
6. WHEN clicking the health indicator THEN the Frontend_UI SHALL show detailed service status
