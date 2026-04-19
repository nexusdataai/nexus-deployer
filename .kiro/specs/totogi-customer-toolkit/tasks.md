# Implementation Plan

- [x] 1. Set up project structure and development environment

  - Create frontend directory with React + Vite application scaffold
  - Create backend directory with Python FastAPI application scaffold
  - Create electron directory for desktop wrapper
  - Set up TypeScript configuration for frontend
  - Set up Python virtual environment and requirements.txt
  - Configure build tools (Vite for frontend, PyInstaller for backend, electron-builder for packaging)
  - Install core dependencies (React, FastAPI, boto3, Electron)
  - Create directory structure for components, services, routers, and scripts
  - _Requirements: 1.1, 1.2_

- [x] 2. Implement capability service and data models



  - [ ] 2.1 Create capability data models (Pydantic and TypeScript)
    - Define Capability Pydantic model with all required fields
    - Define TypeScript Capability interface for frontend

    - Create capability configuration JSON schema
    - _Requirements: 2.1, 2.2, 2.5_

  - [x] 2.2 Implement capability service backend (FastAPI)

    - Create capability service to load capabilities from JSON files
    - Implement GET /api/capabilities endpoint
    - Implement GET /api/capabilities/{id} endpoint
    - Implement GET /api/capabilities/{id}/versions endpoint
    - Add capability validation logic with Pydantic
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [ ]* 2.3 Write unit tests for capability service (pytest)
    - Test capability loading from JSON
    - Test API endpoints return correct data
    - Test version listing for multi-version capabilities
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 3. Implement AWS service for credential and permission management (boto3)





  - [ ] 3.1 Create AWS configuration data models
    - Define AWSConfiguration Pydantic model
    - Define PermissionStatus Pydantic model
    - Define Permission Pydantic model
    - Define TypeScript interfaces for frontend


    - _Requirements: 3.1, 3.2, 4.1_

  - [ ] 3.2 Implement Role ARN validation (FastAPI + boto3)
    - Create ARN format validation function
    - Implement POST /api/aws/validate-credentials endpoint
    - Add STS AssumeRole integration using boto3
    - Store temporary credentials in memory
    - _Requirements: 3.1, 3.2, 3.4_



  - [ ]* 3.3 Write property test for ARN validation
    - **Property 6: Role ARN format validation**
    - **Validates: Requirements 3.2**

  - [ ] 3.4 Implement AWS region validation
    - Create region validation function
    - Load valid AWS regions from boto3
    - Implement GET /api/aws/regions endpoint
    - _Requirements: 3.3_




  - [ ]* 3.5 Write property test for region validation
    - **Property 7: AWS Region validation**
    - **Validates: Requirements 3.3**

  - [ ] 3.6 Implement permission verification service (boto3 IAM)
    - Create permission verification logic using IAM simulate_principal_policy
    - Implement POST /api/aws/verify-permissions endpoint
    - Generate IAM policy JSON for missing permissions
    - Return structured permission status
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 3.7 Write property test for permission verification
    - **Property 11: Permission verification completeness**
    - **Validates: Requirements 4.1**

  - [ ]* 3.8 Write unit tests for AWS service (pytest + moto)
    - Test role assumption with valid and invalid ARNs
    - Test permission verification with various permission sets
    - Test IAM policy JSON generation
    - _Requirements: 3.1, 3.2, 3.4, 4.1_

- [ ] 4. Implement deployment service and script execution (Python subprocess)
  - [ ] 4.1 Create deployment data models
    - Define Deployment Pydantic model
    - Define DeploymentStatus enum
    - Define LogEntry Pydantic model
    - Define TypeScript interfaces for frontend
    - _Requirements: 5.1, 5.2, 6.1_

  - [ ] 4.2 Implement deployment script execution (Python subprocess)
    - Create deployment service with subprocess execution
    - Implement POST /api/deployments endpoint
    - Pass AWS credentials and configuration to deployment script via environment variables
    - Capture stdout/stderr from deployment script
    - Monitor script exit code
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 4.3 Implement deployment status tracking
    - Create in-memory deployment state storage (dict)
    - Implement GET /api/deployments/{id}/status endpoint
    - Track deployment progress and current stage
    - Update status based on script output
    - _Requirements: 5.2, 11.1, 11.2_

  - [ ]* 4.4 Write property test for deployment execution
    - **Property 15: Deployment script execution**
    - **Validates: Requirements 5.1**

  - [ ]* 4.5 Write unit tests for deployment service (pytest)
    - Test deployment script execution with valid configuration
    - Test script output capture
    - Test deployment status tracking
    - Test error handling for script failures
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 5. Implement real-time log streaming with WebSocket (FastAPI WebSocket)
  - [ ] 5.1 Set up WebSocket endpoint in FastAPI
    - Create WebSocket route /api/deployments/{id}/logs
    - Implement connection handling
    - _Requirements: 6.1, 6.2_

  - [ ] 5.2 Implement log streaming service
    - Create log service to buffer deployment logs in memory
    - Stream logs to connected WebSocket clients
    - Implement log entry formatting with timestamps and levels
    - Add log level detection (info, warning, error)
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ] 5.3 Implement GET /api/deployments/{id}/logs endpoint
    - Return historical logs for a deployment
    - Support pagination for large log sets
    - _Requirements: 6.1, 10.1_

  - [ ]* 5.4 Write property test for log timeliness
    - **Property 21: Log entry timeliness**
    - **Validates: Requirements 6.2**

  - [ ]* 5.5 Write property test for log highlighting
    - **Property 22: Error log highlighting**
    - **Property 23: Warning log highlighting**
    - **Validates: Requirements 6.3, 6.4**

  - [ ]* 5.6 Write unit tests for log service (pytest)
    - Test log buffering and retrieval
    - Test log level detection
    - Test WebSocket message formatting
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 6. Implement post-verification service (boto3 CloudFormation)
  - [ ] 6.1 Create verification data models
    - Define VerificationResult Pydantic model
    - Define VerificationCheck Pydantic model
    - Define TypeScript interfaces for frontend
    - _Requirements: 7.1, 7.5, 7.6_

  - [ ] 6.2 Implement verification service
    - Create verification service to execute post-deployment checks
    - Implement POST /api/deployments/{id}/verify endpoint
    - Test deployed endpoint connectivity using requests library
    - Validate CloudFormation stack status using boto3
    - Verify stack outputs are present
    - Execute capability-specific verification scripts
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ] 6.3 Integrate CloudFormation SDK (boto3)
    - Add CloudFormation client from boto3
    - Implement stack status checking
    - Implement stack output retrieval
    - _Requirements: 7.3, 7.4, 8.1_

  - [ ]* 6.4 Write property test for automatic verification
    - **Property 25: Automatic verification execution**
    - **Validates: Requirements 7.1**

  - [ ]* 6.5 Write property test for verification completeness
    - **Property 26: Endpoint connectivity testing**
    - **Property 27: CloudFormation stack status validation**
    - **Property 28: Stack outputs validation**
    - **Validates: Requirements 7.2, 7.3, 7.4**

  - [ ]* 6.6 Write unit tests for verification service (pytest + moto)
    - Test endpoint health checks
    - Test CloudFormation stack validation
    - Test verification result aggregation
    - Test failure handling
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 7. Implement diagnostic log collection and ZIP generation (Python zipfile)
  - [ ] 7.1 Create diagnostic service
    - Create diagnostic service to collect all troubleshooting data
    - Implement POST /api/deployments/{id}/diagnostic-logs endpoint
    - Collect deployment logs, CloudFormation events, errors
    - Include AWS configuration and metadata
    - _Requirements: 9.1, 9.2, 9.3, 10.2_

  - [ ] 7.2 Implement ZIP archive generation (Python zipfile)
    - Use zipfile library to generate ZIP
    - Generate in-memory ZIP with BytesIO
    - Create timestamped filename
    - Return ZIP via FastAPI FileResponse
    - _Requirements: 9.4, 9.5, 10.5_

  - [ ]* 7.3 Write property test for diagnostic log content
    - **Property 36: Diagnostic log content completeness**
    - **Property 37: Diagnostic log metadata inclusion**
    - **Validates: Requirements 9.2, 9.3**

  - [ ]* 7.4 Write property test for ZIP generation
    - **Property 38: Diagnostic log ZIP compression**
    - **Validates: Requirements 9.4**

  - [ ]* 7.5 Write unit tests for diagnostic service (pytest)
    - Test diagnostic data collection
    - Test ZIP generation with various log sizes
    - Test filename formatting
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ] 8. Implement CloudFormation event retrieval (boto3)
  - [ ] 8.1 Implement CloudFormation event service
    - Create service to fetch stack events using boto3
    - Implement GET /api/deployments/{id}/cloudformation-events endpoint
    - Format events for table display
    - Add auto-refresh capability
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

  - [ ]* 8.2 Write property test for event field completeness
    - **Property 63: Stack event field completeness**
    - **Validates: Requirements 15.3**

  - [ ]* 8.3 Write unit tests for CloudFormation event service (pytest + moto)
    - Test event retrieval from CloudFormation
    - Test event formatting
    - Test failure event detection
    - _Requirements: 15.1, 15.2, 15.3, 15.5_

- [ ] 9. Implement deployment cancellation and rollback (boto3)
  - [ ] 9.1 Implement cancellation service
    - Add cancellation logic to deployment service
    - Implement POST /api/deployments/{id}/cancel endpoint
    - Terminate running deployment script (subprocess.terminate)
    - Trigger CloudFormation stack deletion for rollback
    - Collect cancellation logs
    - _Requirements: 14.1, 14.3, 14.4, 14.5_

  - [ ]* 9.2 Write property test for cancellation
    - **Property 58: Script termination on confirmed cancellation**
    - **Property 59: Resource rollback on cancellation**
    - **Validates: Requirements 14.3, 14.4**

  - [ ]* 9.3 Write unit tests for cancellation service (pytest)
    - Test script termination
    - Test rollback initiation
    - Test cancellation summary generation
    - _Requirements: 14.3, 14.4, 14.5_

- [ ] 10. Implement Electron wrapper and desktop packaging
  - [ ] 10.1 Create Electron main process
    - Set up Electron main.js to spawn Python backend on startup
    - Implement window management
    - Handle application lifecycle (quit, close)
    - Kill Python backend process on app quit
    - _Requirements: 1.1, 1.2_

  - [ ] 10.2 Create Electron preload script
    - Set up secure IPC communication
    - Expose safe APIs to renderer process
    - _Requirements: 1.1_

  - [ ] 10.3 Configure electron-builder
    - Set up package.json with build configuration
    - Configure extraResources to bundle Python backend




    - Configure platform-specific settings (Windows, Mac, Linux)
    - Add application icons
    - _Requirements: 1.1_

  - [x]* 10.4 Test Electron packaging


    - Test backend spawning in development mode
    - Test backend spawning in production mode
    - Test installer creation for target platforms
    - _Requirements: 1.1_

- [ ] 11. Implement frontend wizard shell and navigation (React)
  - [ ] 11.1 Create wizard state management (React Context)
    - Set up React Context for wizard state
    - Define WizardState interface
    - Implement state transitions between wizard steps
    - Create navigation functions
    - _Requirements: 1.1, 1.5, 2.4, 3.5_

  - [ ] 11.2 Create wizard shell component
    - Build wizard container component
    - Implement step navigation UI




    - Add progress indicator showing current step
    - Handle step transitions
    - _Requirements: 1.1, 1.2, 1.5_

  - [ ]* 11.3 Write property test for navigation
    - **Property 1: Welcome to capability selection navigation**
    - **Property 2: Capability selection to AWS configuration navigation**
    - **Property 3: Successful role assumption navigation**
    - **Validates: Requirements 1.5, 2.4, 3.5**






  - [ ]* 11.4 Write unit tests for wizard state management (Vitest)
    - Test state transitions
    - Test navigation functions
    - Test state persistence during wizard flow
    - _Requirements: 1.5, 2.4, 3.5, 12.2, 13.2_

- [ ] 12. Implement welcome screen component (React)
  - [ ] 12.1 Create welcome screen UI
    - Build welcome screen component
    - Display welcome message and workflow overview
    - Add start button
    - Implement navigation to capability selection
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

  - [ ]* 12.2 Write unit tests for welcome screen (Vitest + React Testing Library)
    - Test component rendering
    - Test start button presence
    - Test navigation on button click
    - _Requirements: 1.2, 1.4, 1.5_

- [ ] 13. Implement capability selection component (React)
  - [ ] 13.1 Create capability selection UI
    - Build capability list component
    - Fetch capabilities from API using axios
    - Display capability cards with descriptions
    - Implement capability detail panel
    - Add version selection dropdown
    - Add confirm button
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 13.2 Write property test for capability display
    - **Property 8: Capability detail display**
    - **Property 9: Version selection for multi-version capabilities**
    - **Property 10: Capability information completeness**
    - **Validates: Requirements 2.2, 2.3, 2.5**

  - [ ]* 13.3 Write unit tests for capability selection (Vitest)
    - Test capability list rendering
    - Test capability selection
    - Test version dropdown for multi-version capabilities
    - Test navigation on confirm
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 14. Implement AWS configuration component (React)
  - [ ] 14.1 Create AWS configuration form UI
    - Build AWS configuration form component
    - Add Role ARN input field with validation
    - Add AWS Region dropdown
    - Implement real-time ARN format validation
    - Add test credentials button
    - Display validation results
    - Add next button (enabled after validation)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ] 14.2 Integrate with AWS service API
    - Call POST /api/aws/validate-credentials on form submission
    - Handle validation success and failure
    - Display error messages with troubleshooting guidance
    - _Requirements: 3.4, 3.5, 3.6_

  - [ ]* 14.3 Write property test for ARN validation UI
    - **Property 6: Role ARN format validation**
    - **Validates: Requirements 3.2**

  - [ ]* 14.4 Write unit tests for AWS configuration component (Vitest)
    - Test form rendering
    - Test ARN validation
    - Test region selection
    - Test credential testing
    - Test error display
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6_

- [ ] 15. Implement permission verification component (React)
  - [ ] 15.1 Create permission verification UI
    - Build permission verification component
    - Display permission check progress spinner
    - Show required permissions list with checkmarks/X marks
    - Display missing permissions alert
    - Add copy IAM policy button
    - Add retry button
    - Add next button (enabled when all permissions granted)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ] 15.2 Integrate with permission verification API
    - Call POST /api/aws/verify-permissions
    - Display verification results
    - Handle missing permissions
    - Implement IAM policy JSON copy to clipboard
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 15.3 Write property test for permission display
    - **Property 12: All permissions granted behavior**
    - **Property 13: Missing permissions display**
    - **Property 14: IAM policy JSON availability**
    - **Validates: Requirements 4.2, 4.3, 4.4**

  - [ ]* 15.4 Write unit tests for permission verification component (Vitest)
    - Test permission list rendering
    - Test success state display
    - Test missing permissions display
    - Test IAM policy copy functionality
    - Test retry button
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 16. Implement deployment execution component (React)
  - [ ] 16.1 Create deployment execution UI
    - Build deployment execution component
    - Display progress bar with percentage
    - Show current deployment stage
    - Add cancel button
    - Add view CloudFormation events button
    - _Requirements: 5.1, 5.2, 11.1, 11.2, 14.1, 15.1_

  - [ ] 16.2 Integrate with deployment API
    - Call POST /api/deployments to start deployment
    - Poll GET /api/deployments/{id}/status for progress updates
    - Handle deployment completion (success/failure)
    - Navigate to post-verification or error screen
    - _Requirements: 5.1, 5.2, 5.4, 5.5_

  - [ ] 16.3 Implement deployment cancellation
    - Add confirmation dialog for cancellation
    - Call POST /api/deployments/{id}/cancel
    - Display cancellation summary
    - _Requirements: 14.1, 14.2, 14.3, 14.5_

  - [ ]* 16.4 Write property test for deployment execution
    - **Property 16: Deployment progress indicator**
    - **Property 45: Progress bar display**
    - **Property 46: Current stage display**
    - **Validates: Requirements 5.2, 11.1, 11.2**

  - [ ]* 16.5 Write property test for cancellation
    - **Property 56: Cancel button visibility during execution**
    - **Property 57: Cancellation confirmation prompt**
    - **Validates: Requirements 14.1, 14.2**

  - [ ]* 16.6 Write unit tests for deployment execution component (Vitest)
    - Test deployment initiation
    - Test progress display
    - Test cancellation flow
    - Test navigation on completion
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 14.1, 14.2, 14.3_

- [ ] 17. Implement log viewer component (React + WebSocket)
  - [ ] 17.1 Create log viewer UI
    - Build log viewer component
    - Display logs with timestamps
    - Implement color-coded log levels (red for errors, yellow for warnings)
    - Add auto-scroll functionality
    - Implement manual scroll pause behavior
    - Add download logs button
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 10.1_

  - [ ] 17.2 Integrate WebSocket for real-time logs
    - Connect to WebSocket endpoint ws://localhost:8000/api/deployments/{id}/logs
    - Receive and display log messages in real-time
    - Handle WebSocket disconnection and reconnection
    - Buffer logs during disconnection
    - _Requirements: 6.1, 6.2_

  - [ ]* 17.3 Write property test for log display
    - **Property 20: Real-time log display**
    - **Property 22: Error log highlighting**
    - **Property 23: Warning log highlighting**
    - **Property 24: Manual scroll pause behavior**
    - **Validates: Requirements 6.1, 6.3, 6.4, 6.5**

  - [ ]* 17.4 Write unit tests for log viewer component (Vitest)
    - Test log rendering
    - Test color coding
    - Test auto-scroll
    - Test manual scroll pause
    - Test WebSocket integration
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 18. Implement post-verification component (React)
  - [ ] 18.1 Create post-verification UI
    - Build post-verification component
    - Display verification progress indicator
    - Show verification check results list with pass/fail status
    - Display success or failure banner
    - _Requirements: 7.1, 7.5, 7.6_

  - [ ] 18.2 Integrate with verification API
    - Call POST /api/deployments/{id}/verify automatically after deployment
    - Display verification results
    - Handle verification success and failure
    - Trigger diagnostic log collection on failure
    - _Requirements: 7.1, 7.5, 7.6_

  - [ ]* 18.3 Write property test for verification
    - **Property 25: Automatic verification execution**
    - **Property 29: Verification success display**
    - **Property 30: Verification failure handling**
    - **Validates: Requirements 7.1, 7.5, 7.6**

  - [ ]* 18.4 Write unit tests for post-verification component (Vitest)
    - Test verification initiation
    - Test check results display
    - Test success state
    - Test failure state
    - _Requirements: 7.1, 7.5, 7.6_

- [ ] 19. Implement results component (React)
  - [ ] 19.1 Create results display UI
    - Build results component
    - Display CloudFormation stack outputs
    - Show endpoint URLs, resource ARNs, and configuration values
    - Add copy buttons for each output value
    - Add export button to save outputs to JSON
    - Add download logs button
    - Add deploy another capability button
    - Add retry deployment button (on failure)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.5, 10.1, 12.1, 13.1_

  - [ ] 19.2 Implement clipboard copy functionality
    - Add copy to clipboard for each output value
    - Display copy confirmation
    - _Requirements: 8.4_

  - [ ] 19.3 Implement JSON export
    - Generate JSON file with all stack outputs
    - Trigger browser download
    - _Requirements: 8.5_

  - [ ]* 19.4 Write property test for results display
    - **Property 31: Stack outputs display**
    - **Property 32: Resource information completeness**
    - **Property 33: Copy button availability**
    - **Property 34: Clipboard copy functionality**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**

  - [ ]* 19.5 Write unit tests for results component (Vitest)
    - Test stack outputs rendering
    - Test copy functionality
    - Test export functionality
    - Test button visibility based on deployment status
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 20. Implement diagnostic log download functionality (React)
  - [ ] 20.1 Integrate diagnostic log download
    - Add download logs button to relevant screens
    - Call POST /api/deployments/{id}/diagnostic-logs
    - Trigger browser download of ZIP file
    - Display download confirmation
    - _Requirements: 9.5, 10.1, 10.2, 10.5_

  - [ ]* 20.2 Write property test for log download
    - **Property 40: Manual log download button visibility**
    - **Property 41: Manual ZIP generation**
    - **Property 44: Manual ZIP download trigger**
    - **Validates: Requirements 10.1, 10.2, 10.5**

  - [ ]* 20.3 Write unit tests for diagnostic log download (Vitest)
    - Test download button presence
    - Test ZIP generation API call
    - Test browser download trigger
    - _Requirements: 10.1, 10.2, 10.5_

- [ ] 21. Implement CloudFormation events viewer component (React)
  - [ ] 21.1 Create CloudFormation events UI
    - Build events viewer component
    - Display events in table format
    - Show timestamp, resource type, logical resource ID, status, status reason
    - Highlight failed events in red
    - Implement auto-refresh every 5 seconds
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_

  - [ ] 21.2 Integrate with CloudFormation events API
    - Call GET /api/deployments/{id}/cloudformation-events
    - Display events in table
    - Implement auto-refresh polling
    - _Requirements: 15.2, 15.4_

  - [ ]* 21.3 Write property test for events display
    - **Property 62: Stack events table display**
    - **Property 63: Stack event field completeness**
    - **Property 65: Failed event highlighting**
    - **Validates: Requirements 15.2, 15.3, 15.5**

  - [ ]* 21.4 Write unit tests for CloudFormation events component (Vitest)
    - Test events table rendering
    - Test field display
    - Test failure highlighting
    - Test auto-refresh
    - _Requirements: 15.2, 15.3, 15.4, 15.5_

- [ ] 22. Implement retry and reset functionality (React)
  - [ ] 22.1 Implement retry deployment
    - Add retry button on failure screen
    - Navigate back to AWS configuration with preserved values
    - Allow configuration modification
    - Re-execute deployment on confirmation
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ] 22.2 Implement deploy another capability
    - Add deploy another button on success screen
    - Clear all wizard state
    - Navigate back to capability selection
    - Require re-entry of AWS credentials
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [ ]* 22.3 Write property test for retry
    - **Property 50: Retry button display on failure**
    - **Property 51: Configuration preservation on retry**
    - **Property 52: Configuration editability on retry**
    - **Validates: Requirements 12.1, 12.3, 12.4**

  - [ ]* 22.4 Write property test for reset
    - **Property 54: State clearing on new deployment**
    - **Property 55: Credential re-entry requirement**
    - **Validates: Requirements 13.3, 13.4**

  - [ ]* 22.5 Write unit tests for retry and reset (Vitest)
    - Test retry navigation
    - Test state preservation on retry
    - Test state clearing on new deployment
    - Test credential re-entry requirement
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 13.2, 13.3, 13.4_

- [ ] 23. Create sample capability and deployment scripts
  - [ ] 23.1 Create sample capability definition
    - Create JSON configuration for a sample capability
    - Define required permissions
    - Define prerequisites
    - Add capability metadata
    - _Requirements: 2.1, 2.2_

  - [ ] 23.2 Create sample deployment script (Bash)
    - Write bash script to deploy CloudFormation stack
    - Accept environment variables for configuration
    - Output progress logs to stdout
    - Handle errors and exit codes
    - _Requirements: 5.1, 5.3_

  - [ ] 23.3 Create sample verification script (Bash)
    - Write bash script to verify deployment
    - Test endpoint connectivity
    - Validate stack outputs
    - Return exit code based on verification results
    - _Requirements: 7.1, 7.2, 7.4_

- [ ] 24. Implement error handling and user feedback
  - [ ] 24.1 Add error handling to all API endpoints (FastAPI)
    - Implement structured error responses
    - Add error codes and messages
    - Include troubleshooting guidance
    - Log errors for debugging
    - _Requirements: 3.6, 5.5, 7.6_

  - [ ] 24.2 Add error display components (React)
    - Create error message component
    - Display user-friendly error messages
    - Show troubleshooting steps
    - Add retry buttons where appropriate
    - _Requirements: 3.6, 5.5, 7.6_

  - [ ]* 24.3 Write property test for error handling
    - **Property 19: Failed deployment error handling**
    - **Property 30: Verification failure handling**
    - **Validates: Requirements 5.5, 7.6**

  - [ ]* 24.4 Write unit tests for error handling
    - Test error response formatting
    - Test error display components
    - Test error recovery flows
    - _Requirements: 3.6, 5.5, 7.6_

- [ ] 25. Add styling and responsive design (Tailwind CSS)
  - [ ] 25.1 Implement UI styling
    - Add Tailwind CSS to project
    - Style all wizard components
    - Implement consistent color scheme
    - Add loading spinners and animations
    - _Requirements: 1.2, 6.3, 6.4, 15.5_

  - [ ] 25.2 Implement responsive design
    - Make wizard responsive for different screen sizes
    - Test on various window sizes
    - Adjust layouts for smaller screens
    - _Requirements: 1.2_

- [ ] 26. Build and package application
  - [ ] 26.1 Create PyInstaller spec file for backend
    - Configure backend.spec with all dependencies
    - Add hidden imports for boto3 and dependencies
    - Include capability definitions
    - Test backend executable
    - _Requirements: 1.1_

  - [ ] 26.2 Configure Vite build for frontend
    - Optimize production build
    - Configure base path for Electron
    - Test frontend build
    - _Requirements: 1.1_

  - [ ] 26.3 Configure electron-builder
    - Set up package.json with build configuration
    - Configure extraResources for backend and scripts
    - Add platform-specific settings
    - Create application icons
    - _Requirements: 1.1_

  - [ ] 26.4 Create build scripts
    - Create build-backend.sh script
    - Create build-frontend.sh script
    - Create build-electron.sh script
    - Create build-all.sh master script
    - _Requirements: 1.1_

  - [ ] 26.5 Test installer on target platforms
    - Build and test Windows installer
    - Build and test macOS installer (if applicable)
    - Build and test Linux installer (if applicable)
    - _Requirements: 1.1_

- [ ] 27. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 28. Create deployment documentation
  - [ ] 28.1 Write README with setup instructions
    - Document installation steps
    - Document configuration requirements
    - Document how to run the wizard
    - Document how to add new capabilities
    - _Requirements: 1.1_

  - [ ] 28.2 Create capability authoring guide
    - Document capability JSON schema
    - Document deployment script requirements
    - Document verification script requirements
    - Provide examples
    - _Requirements: 2.1, 5.1, 7.1_

- [ ] 29. Final integration testing and polish
  - [ ] 29.1 Perform end-to-end testing
    - Test complete deployment workflow
    - Test error scenarios
    - Test cancellation and retry
    - Test log download
    - _Requirements: All_

  - [ ] 29.2 Performance optimization
    - Optimize log streaming performance
    - Optimize API response times
    - Minimize bundle size
    - _Requirements: 6.1, 6.2_

  - [ ] 29.3 Security review
    - Ensure credentials are not logged
    - Validate input sanitization
    - Review AWS permission usage
    - Test secure WebSocket connections
    - _Requirements: 3.1, 3.4_

- [ ] 30. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
