# Design Document

## Overview

The Totogi Capability Deployment Wizard is a streamlined desktop application that guides users through deploying business capabilities into their AWS environments. The design prioritizes simplicity and ease of use, eliminating authentication barriers and focusing solely on the deployment workflow. The wizard follows a linear step-by-step process: capability selection → AWS credential configuration → permission verification → deployment execution → post-verification → log collection.

Key architectural decisions:
- **No authentication required** - wizard starts immediately without login
- **Stateless operation** - no persistent user sessions or databases
- **Desktop application** - packaged with Electron for native experience
- **Single-page application** - smooth transitions between wizard steps
- **Real-time feedback** - live deployment logs and progress indicators
- **Self-contained** - all deployment logic embedded in the installer
- **Bundled runtimes** - Python backend and Electron runtime included in installer

The system consists of three main components:
1. **React-based frontend** - Wizard UI built with React + TypeScript + Vite
2. **Python FastAPI backend** - Handles AWS SDK operations (boto3), deployment script execution, and log aggregation
3. **Electron wrapper** - Packages everything as a native desktop application

## Technology Stack

### Frontend
- **React 18+** - UI framework
- **TypeScript** - Type safety
- **Vite** - Fast build tool and dev server
- **Tailwind CSS** - Utility-first styling
- **React Router** - Client-side routing
- **Axios** - HTTP client for API calls

### Backend
- **Python 3.11+** - Backend runtime
- **FastAPI** - Modern Python web framework
- **Pydantic** - Data validation and settings
- **boto3** - AWS SDK for Python
- **uvicorn** - ASGI server
- **websockets** - WebSocket support
- **PyInstaller** - Bundle Python app into executable

### Desktop Packaging
- **Electron** - Desktop application framework
- **electron-builder** - Build and package installers
- **electron-updater** - Auto-update functionality

### Development Tools
- **pytest** - Python testing framework
- **Vitest** - Frontend testing framework
- **fast-check** - Property-based testing (TypeScript)
- **hypothesis** - Property-based testing (Python)

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│              Electron Desktop Application                   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │   Electron Main Process (Node.js)                     │ │
│  │   - Spawns Python FastAPI backend on startup          │ │
│  │   - Manages application window lifecycle              │ │
│  │   - Handles system tray and notifications             │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │   React Wizard Application (Renderer Process)         │ │
│  │   - Capability Selection                              │ │
│  │   - AWS Configuration Form                            │ │
│  │   - Permission Verification Display                   │ │
│  │   - Deployment Progress Monitor                       │ │
│  │   - Log Viewer                                        │ │
│  │   - Post-Verification Results                         │ │
│  │   - Diagnostic Log Download                           │ │
│  │   - Calls localhost:8000 API                          │ │
│  └───────────────────────────────────────────────────────┘ │
│                         │                                   │
│                         │ REST API / WebSocket              │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐ │
│  │   Python FastAPI Backend (Bundled with PyInstaller)   │ │
│  │                                                        │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │ │
│  │  │ Capability   │  │ AWS          │  │ Deployment  │ │ │
│  │  │ Service      │  │ Service      │  │ Service     │ │ │
│  │  └──────────────┘  └──────────────┘  └─────────────┘ │ │
│  │                                                        │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │ │
│  │  │ Verification │  │ Log          │  │ Diagnostic  │ │ │
│  │  │ Service      │  │ Service      │  │ Service     │ │ │
│  │  └──────────────┘  └──────────────┘  └─────────────┘ │ │
│  │                                                        │ │
│  │  - Runs on localhost:8000                             │ │
│  │  - Uses boto3 for AWS operations                      │ │
│  │  - Executes deployment scripts via subprocess         │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ boto3 (AWS SDK for Python)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  AWS Services                               │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ IAM / STS    │  │ CloudFormation│ │ CloudWatch   │     │
│  │ (Assume Role)│  │ (Deploy Stack)│  │ (Logs/Events)│     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Workflow

```
Start Wizard → Select Capability → Configure AWS (Role ARN + Region) →
Verify Permissions → Review Configuration → Execute Deployment →
Stream Logs → Post-Verification → Display Results → Download Logs
```

### State Management

The wizard maintains deployment state in browser memory (React state):
- Current step in wizard
- Selected capability and version
- AWS Role ARN and region
- Permission verification results
- Deployment progress and status
- Collected logs
- Post-verification results

No persistent storage is used - each deployment is independent.

## Components and Interfaces

### Frontend Components

#### 1. Wizard Shell Component

**Responsibilities:**
- Manage wizard step navigation
- Display progress indicator
- Handle step transitions
- Maintain deployment state

**State:**
```typescript
interface WizardState {
  currentStep: WizardStep;
  capability: SelectedCapability | null;
  awsConfig: AWSConfiguration | null;
  permissionStatus: PermissionStatus | null;
  deploymentId: string | null;
  deploymentStatus: DeploymentStatus;
  logs: LogEntry[];
  verificationResults: VerificationResult | null;
}

enum WizardStep {
  WELCOME,
  CAPABILITY_SELECTION,
  AWS_CONFIGURATION,
  PERMISSION_VERIFICATION,
  CONFIGURATION_REVIEW,
  DEPLOYMENT_EXECUTION,
  POST_VERIFICATION,
  RESULTS
}
```

#### 2. Welcome Screen Component

**Responsibilities:**
- Display welcome message and workflow overview
- Provide "Begin Deployment" button
- Show deployment history (optional)

**UI Elements:**
- Welcome heading
- Workflow diagram
- Begin button
- View history link (optional)

#### 3. Capability Selection Component

**Responsibilities:**
- Fetch and display available capabilities
- Show capability details and prerequisites
- Allow version selection
- Navigate to AWS configuration

**API Calls:**
```
GET /api/capabilities
GET /api/capabilities/:id/versions
```

**UI Elements:**
- Capability list with search/filter
- Capability detail panel
- Version dropdown
- Next button

#### 4. AWS Configuration Component

**Responsibilities:**
- Collect AWS Role ARN and region
- Validate ARN format
- Test credential assumption
- Navigate to permission verification

**API Calls:**
```
POST /api/aws/validate-credentials
```

**Form Fields:**
- Role ARN input (with format validation)
- Region dropdown (populated from AWS regions)
- Test credentials button
- Next button (enabled after validation)

**Validation Rules:**
- ARN format: `arn:aws:iam::\d{12}:role/[\w+=,.@-]+`
- Region must be valid AWS region

#### 5. Permission Verification Component

**Responsibilities:**
- Display permission check progress
- Show required vs granted permissions
- Provide IAM policy JSON for missing permissions
- Allow retry after permission correction

**API Calls:**
```
POST /api/aws/verify-permissions
```

**UI Elements:**
- Permission check progress spinner
- Required permissions list (with checkmarks/X marks)
- Missing permissions alert
- Copy IAM policy button
- Retry button
- Next button (enabled when all permissions granted)

#### 6. Configuration Review Component

**Responsibilities:**
- Display deployment configuration summary
- Allow editing of any parameter
- Confirm configuration before deployment

**UI Elements:**
- Configuration summary table
- Edit buttons for each parameter
- Export configuration button
- Start deployment button

#### 7. Deployment Execution Component

**Responsibilities:**
- Execute deployment via API
- Display real-time deployment logs
- Show progress indicator
- Handle deployment cancellation

**API Calls:**
```
POST /api/deployments
GET /api/deployments/:id/logs (WebSocket)
POST /api/deployments/:id/cancel
```

**UI Elements:**
- Progress bar with percentage
- Current stage indicator
- Log viewer with auto-scroll
- Cancel button
- View CloudFormation events button

#### 8. Log Viewer Component

**Responsibilities:**
- Display deployment logs in real-time
- Highlight errors and warnings
- Support auto-scroll and manual scroll
- Provide log filtering

**Features:**
- Color-coded log levels (error=red, warning=yellow, info=white)
- Timestamps for each entry
- Auto-scroll (pauses when user scrolls up)
- Search/filter functionality

#### 9. Post-Verification Component

**Responsibilities:**
- Execute post-deployment verification checks
- Display verification results
- Show deployed resource information

**API Calls:**
```
POST /api/deployments/:id/verify
```

**UI Elements:**
- Verification progress indicator
- Check results list (with pass/fail status)
- Resource information table
- Copy buttons for resource values

#### 10. Results Component

**Responsibilities:**
- Display deployment success or failure summary
- Show deployed resource details
- Provide log download
- Allow starting new deployment

**UI Elements:**
- Success/failure banner
- CloudFormation stack outputs
- Download logs button
- Deploy another capability button
- Retry deployment button (on failure)

#### 11. Diagnostic Log Download Component

**Responsibilities:**
- Generate diagnostic log ZIP archive
- Trigger browser download
- Include all relevant troubleshooting information

**API Calls:**
```
POST /api/deployments/:id/diagnostic-logs
```

**Included in ZIP:**
- Deployment logs
- CloudFormation events
- Error messages
- Configuration parameters
- System information
- Timestamp metadata

### Backend Services

#### 1. Capability Service

**API Endpoints:**
```
GET    /api/capabilities
GET    /api/capabilities/:id
GET    /api/capabilities/:id/versions
```

**Responsibilities:**
- Serve capability catalog from configuration files
- Provide capability metadata and documentation
- List available versions for each capability

**Capability Metadata:**
```typescript
interface Capability {
  id: string;
  name: string;
  description: string;
  versions: string[];
  latestVersion: string;
  prerequisites: string[];
  estimatedDeploymentTime: number; // minutes
  requiredAWSResources: string[];
  requiredIAMPermissions: string[];
  deploymentScriptPath: string;
  postVerificationScriptPath: string;
}
```

**Data Source:**
- Capabilities defined in JSON configuration files
- Deployment scripts stored in `/scripts/capabilities/` directory

#### 2. AWS Service

**API Endpoints:**
```
POST   /api/aws/validate-credentials
POST   /api/aws/verify-permissions
GET    /api/aws/regions
```

**Responsibilities:**
- Validate AWS Role ARN format
- Assume IAM role using STS
- Verify required IAM permissions
- List available AWS regions

**Credential Validation Logic:**
1. Parse Role ARN
2. Call STS AssumeRole with provided ARN
3. Store temporary credentials in memory (session-scoped)
4. Return success/failure

**Permission Verification Logic:**
1. Retrieve required permissions for capability
2. Use IAM SimulatePrincipalPolicy API
3. Check each required permission
4. Return list of granted and missing permissions

**Dependencies:**
- boto3 (AWS SDK for Python)
- STS client for role assumption
- IAM client for permission simulation

#### 3. Deployment Service

**API Endpoints:**
```
POST   /api/deployments
GET    /api/deployments/:id/status
GET    /api/deployments/:id/logs (WebSocket)
POST   /api/deployments/:id/cancel
GET    /api/deployments/:id/cloudformation-events
```

**Responsibilities:**
- Execute deployment scripts
- Stream deployment logs to client
- Track deployment progress
- Handle deployment cancellation
- Retrieve CloudFormation stack events

**Deployment Execution Logic:**
1. Generate unique deployment ID
2. Prepare deployment script with parameters
3. Execute script as child process
4. Capture stdout/stderr
5. Stream logs via WebSocket
6. Monitor script exit code
7. Update deployment status
8. Trigger post-verification on success

**Deployment Script Interface:**
```bash
#!/bin/bash
# Deployment script receives parameters as environment variables
# CAPABILITY_ID, CAPABILITY_VERSION, AWS_REGION, ROLE_ARN, DEPLOYMENT_ID

# Script should:
# 1. Assume the provided IAM role
# 2. Deploy CloudFormation stack
# 3. Output progress to stdout
# 4. Exit with 0 on success, non-zero on failure
```

**WebSocket Protocol:**
```typescript
// Server → Client messages
interface LogMessage {
  type: 'log';
  timestamp: string;
  level: 'info' | 'warning' | 'error';
  message: string;
}

interface StatusMessage {
  type: 'status';
  status: 'running' | 'completed' | 'failed';
  progress: number; // 0-100
  currentStage: string;
}
```

**Dependencies:**
- Python subprocess module
- WebSocket library (websockets or fastapi-websocket)
- boto3 CloudFormation client

#### 4. Verification Service

**API Endpoints:**
```
POST   /api/deployments/:id/verify
```

**Responsibilities:**
- Execute post-deployment verification checks
- Test deployed endpoint connectivity
- Validate CloudFormation stack outputs
- Return verification results

**Verification Logic:**
1. Retrieve CloudFormation stack outputs
2. Execute capability-specific verification script
3. Test endpoint health (HTTP requests)
4. Validate expected outputs exist
5. Return pass/fail for each check

**Verification Script Interface:**
```bash
#!/bin/bash
# Verification script receives stack outputs as environment variables
# Should perform health checks and exit with 0 on success

# Example checks:
# - HTTP GET to endpoint returns 200
# - Database connection succeeds
# - Required resources exist
```

**Verification Result:**
```typescript
interface VerificationResult {
  overallStatus: 'passed' | 'failed';
  checks: VerificationCheck[];
  stackOutputs: Record<string, string>;
  timestamp: string;
}

interface VerificationCheck {
  name: string;
  status: 'passed' | 'failed';
  message: string;
  details?: string;
}
```

#### 5. Log Service

**API Endpoints:**
```
GET    /api/deployments/:id/logs
```

**Responsibilities:**
- Store deployment logs in memory
- Retrieve logs for display
- Aggregate logs from multiple sources

**Log Storage:**
- In-memory log buffer per deployment ID
- Maximum 10,000 log entries per deployment
- Logs cleared after 1 hour of inactivity

**Log Entry Format:**
```typescript
interface LogEntry {
  timestamp: string;
  level: 'info' | 'warning' | 'error';
  source: 'deployment-script' | 'cloudformation' | 'system';
  message: string;
}
```

#### 6. Diagnostic Service

**API Endpoints:**
```
POST   /api/deployments/:id/diagnostic-logs
```

**Responsibilities:**
- Collect all diagnostic information
- Generate ZIP archive
- Include deployment logs, errors, configuration
- Return downloadable file

**Diagnostic Package Contents:**
- `deployment-logs.txt`: All deployment logs
- `cloudformation-events.json`: CloudFormation stack events
- `configuration.json`: Deployment configuration parameters
- `errors.txt`: All error messages
- `system-info.json`: System metadata (timestamp, versions)
- `verification-results.json`: Post-verification results (if available)

**ZIP Generation:**
- Use zipfile library (Python standard library)
- Generate in-memory ZIP with BytesIO
- Stream to client as download via FastAPI FileResponse

## Data Models

### Capability Model

```typescript
interface Capability {
  id: string;
  name: string;
  description: string;
  versions: string[];
  latestVersion: string;
  prerequisites: string[];
  estimatedDeploymentTime: number;
  requiredAWSResources: string[];
  requiredIAMPermissions: string[];
  deploymentScriptPath: string;
  postVerificationScriptPath: string;
  documentationUrl?: string;
}
```

### AWS Configuration Model

```typescript
interface AWSConfiguration {
  roleArn: string;
  region: string;
  accountId: string; // Extracted from ARN
  temporaryCredentials?: {
    accessKeyId: string;
    secretAccessKey: string;
    sessionToken: string;
    expiration: Date;
  };
}
```

### Permission Status Model

```typescript
interface PermissionStatus {
  allGranted: boolean;
  requiredPermissions: Permission[];
  missingPermissions: string[];
  iamPolicyJson: string; // For missing permissions
}

interface Permission {
  action: string;
  granted: boolean;
}
```

### Deployment Model

```typescript
interface Deployment {
  id: string;
  capabilityId: string;
  capabilityVersion: string;
  awsConfig: AWSConfiguration;
  status: DeploymentStatus;
  progress: number; // 0-100
  currentStage: string;
  startedAt: Date;
  completedAt?: Date;
  cloudFormationStackId?: string;
  cloudFormationStackName?: string;
  error?: string;
}

enum DeploymentStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled'
}
```

### Log Entry Model

```typescript
interface LogEntry {
  timestamp: string;
  level: 'info' | 'warning' | 'error';
  source: 'deployment-script' | 'cloudformation' | 'system';
  message: string;
}
```

### Verification Result Model

```typescript
interface VerificationResult {
  overallStatus: 'passed' | 'failed';
  checks: VerificationCheck[];
  stackOutputs: Record<string, string>;
  timestamp: string;
}

interface VerificationCheck {
  name: string;
  status: 'passed' | 'failed';
  message: string;
  details?: string;
}
```

### CloudFormation Event Model

```typescript
interface CloudFormationEvent {
  timestamp: Date;
  resourceType: string;
  logicalResourceId: string;
  resourceStatus: string;
  resourceStatusReason?: string;
}
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Navigation Properties

Property 1: Welcome to capability selection navigation
*For any* wizard state displaying the welcome screen, clicking the start button should navigate to the capability selection screen
**Validates: Requirements 1.5**

Property 2: Capability selection to AWS configuration navigation
*For any* selected capability, confirming the selection should navigate to the AWS environment configuration screen
**Validates: Requirements 2.4**

Property 3: Successful role assumption navigation
*For any* successful AWS role assumption, the wizard should proceed to permission verification
**Validates: Requirements 3.5**

Property 4: Retry deployment navigation
*For any* retry deployment action, the wizard should navigate back to the AWS environment configuration screen
**Validates: Requirements 12.2**

Property 5: Deploy another capability navigation
*For any* deploy another capability action, the wizard should navigate back to the capability selection screen
**Validates: Requirements 13.2**

### Input Validation Properties

Property 6: Role ARN format validation
*For any* string input as a Role ARN, the wizard should validate it matches AWS IAM role naming conventions (arn:aws:iam::\d{12}:role/[\w+=,.@-]+)
**Validates: Requirements 3.2**

Property 7: AWS Region validation
*For any* region input, the wizard should validate it is a supported AWS region
**Validates: Requirements 3.3**

### Capability Display Properties

Property 8: Capability detail display
*For any* selected capability, the wizard should display detailed information including prerequisites and required AWS resources
**Validates: Requirements 2.2**

Property 9: Version selection for multi-version capabilities
*For any* capability with multiple versions, the wizard should provide version selection UI
**Validates: Requirements 2.3**

Property 10: Capability information completeness
*For any* displayed capability, the wizard should show estimated deployment time and required IAM permissions
**Validates: Requirements 2.5**

### Permission Verification Properties

Property 11: Permission verification completeness
*For any* capability and assumed role, the wizard should check all required IAM permissions for that capability
**Validates: Requirements 4.1**

Property 12: All permissions granted behavior
*For any* permission check where all required permissions are granted, the wizard should display a success message and enable the deploy button
**Validates: Requirements 4.2**

Property 13: Missing permissions display
*For any* permission check with missing permissions, the wizard should display the list of missing permissions with descriptions
**Validates: Requirements 4.3**

Property 14: IAM policy JSON availability
*For any* insufficient permission state, the wizard should provide a copy button to copy the required IAM policy JSON
**Validates: Requirements 4.4**

### Deployment Execution Properties

Property 15: Deployment script execution
*For any* valid configuration, clicking the deploy button should execute the deployment script with the configured AWS environment parameters
**Validates: Requirements 5.1**

Property 16: Deployment progress indicator
*For any* deployment script execution, the wizard should display a deployment in progress indicator
**Validates: Requirements 5.2**

Property 17: Script output capture
*For any* deployment script output, the wizard should capture it for real-time display
**Validates: Requirements 5.3**

Property 18: Successful deployment navigation
*For any* successfully completed deployment script, the wizard should proceed to post-verification
**Validates: Requirements 5.4**

Property 19: Failed deployment error handling
*For any* failed deployment script, the wizard should capture error details and navigate to the error screen
**Validates: Requirements 5.5**

### Log Display Properties

Property 20: Real-time log display
*For any* executing deployment, the wizard should display deployment logs in real-time with automatic scrolling
**Validates: Requirements 6.1**

Property 21: Log entry timeliness
*For any* new log entry generated, the wizard should append it to the log display within two seconds
**Validates: Requirements 6.2**

Property 22: Error log highlighting
*For any* error-level log entry, the wizard should highlight it in red color
**Validates: Requirements 6.3**

Property 23: Warning log highlighting
*For any* warning-level log entry, the wizard should highlight it in yellow color
**Validates: Requirements 6.4**

Property 24: Manual scroll pause behavior
*For any* manual scroll action by the user, the wizard should pause automatic scrolling until the user scrolls to the bottom
**Validates: Requirements 6.5**

### Post-Verification Properties

Property 25: Automatic verification execution
*For any* successfully completed deployment, the wizard should automatically execute all post-verification checks
**Validates: Requirements 7.1**

Property 26: Endpoint connectivity testing
*For any* post-verification execution, the wizard should test all deployed endpoints for connectivity and health status
**Validates: Requirements 7.2**

Property 27: CloudFormation stack status validation
*For any* post-verification execution, the wizard should validate the CloudFormation stack status is CREATE_COMPLETE
**Validates: Requirements 7.3**

Property 28: Stack outputs validation
*For any* post-verification execution, the wizard should verify all expected stack outputs are present
**Validates: Requirements 7.4**

Property 29: Verification success display
*For any* verification where all checks pass, the wizard should display a success screen with deployment summary
**Validates: Requirements 7.5**

Property 30: Verification failure handling
*For any* verification with at least one failed check, the wizard should display failure details and automatically collect diagnostic logs
**Validates: Requirements 7.6**

### Resource Information Properties

Property 31: Stack outputs display
*For any* successful post-verification, the wizard should display all CloudFormation stack outputs
**Validates: Requirements 8.1**

Property 32: Resource information completeness
*For any* displayed resource information, the wizard should show endpoint URLs, resource ARNs, and configuration values
**Validates: Requirements 8.2**

Property 33: Copy button availability
*For any* displayed resource output value, the wizard should provide a copy button
**Validates: Requirements 8.3**

Property 34: Clipboard copy functionality
*For any* copy button click, the wizard should copy the associated value to the system clipboard
**Validates: Requirements 8.4**

### Diagnostic Log Properties

Property 35: Automatic diagnostic log collection on failure
*For any* deployment or verification failure, the wizard should automatically collect all diagnostic logs
**Validates: Requirements 9.1**

Property 36: Diagnostic log content completeness
*For any* diagnostic log collection, the wizard should include deployment script output, CloudFormation events, and error messages
**Validates: Requirements 9.2**

Property 37: Diagnostic log metadata inclusion
*For any* diagnostic log collection, the wizard should include AWS environment configuration and timestamp metadata
**Validates: Requirements 9.3**

Property 38: Diagnostic log ZIP compression
*For any* diagnostic log collection, the wizard should compress all logs into a ZIP archive
**Validates: Requirements 9.4**

Property 39: ZIP download availability
*For any* created diagnostic ZIP archive, the wizard should provide a download button with a timestamped filename
**Validates: Requirements 9.5**

Property 40: Manual log download button visibility
*For any* state where deployment logs are displayed, the wizard should provide a download logs button visible at all times
**Validates: Requirements 10.1**

Property 41: Manual ZIP generation
*For any* download logs button click, the wizard should generate a diagnostic log ZIP archive
**Validates: Requirements 10.2**

Property 42: Current log inclusion in manual download
*For any* manually generated ZIP archive, the wizard should include all deployment logs captured up to the current point
**Validates: Requirements 10.3**

Property 43: Manual ZIP metadata inclusion
*For any* manually generated ZIP archive, the wizard should include system information, configuration parameters, and AWS environment details
**Validates: Requirements 10.4**

Property 44: Manual ZIP download trigger
*For any* ready ZIP archive from manual download, the wizard should trigger a browser download with a descriptive timestamped filename
**Validates: Requirements 10.5**

### Progress Indicator Properties

Property 45: Progress bar display
*For any* executing deployment, the wizard should display a progress bar showing overall completion percentage
**Validates: Requirements 11.1**

Property 46: Current stage display
*For any* executing deployment, the wizard should display the current deployment stage name
**Validates: Requirements 11.2**

Property 47: Progress indicator update timeliness
*For any* stage transition, the wizard should update the progress indicator within one second
**Validates: Requirements 11.3**

Property 48: Time remaining display
*For any* long-running deployment stage, the wizard should display an estimated time remaining
**Validates: Requirements 11.4**

Property 49: Completion progress display
*For any* completed deployment, the wizard should display the progress bar at one hundred percent
**Validates: Requirements 11.5**

### Retry and Reset Properties

Property 50: Retry button display on failure
*For any* failed deployment, the wizard should display a retry deployment button
**Validates: Requirements 12.1**

Property 51: Configuration preservation on retry
*For any* retry deployment action, the wizard should preserve all previously entered configuration values
**Validates: Requirements 12.3**

Property 52: Configuration editability on retry
*For any* retry state, the wizard should allow modification of any configuration parameter
**Validates: Requirements 12.4**

Property 53: Retry execution with updated configuration
*For any* retry confirmation, the wizard should execute the deployment script again with the updated configuration
**Validates: Requirements 12.5**

Property 54: State clearing on new deployment
*For any* new deployment start, the wizard should clear all previous deployment state and logs
**Validates: Requirements 13.3**

Property 55: Credential re-entry requirement
*For any* new deployment start, the wizard should require re-entry of AWS environment credentials (not pre-fill them)
**Validates: Requirements 13.4**

### Cancellation Properties

Property 56: Cancel button visibility during execution
*For any* executing deployment, the wizard should display a cancel deployment button
**Validates: Requirements 14.1**

Property 57: Cancellation confirmation prompt
*For any* cancel deployment button click, the wizard should prompt for confirmation before proceeding
**Validates: Requirements 14.2**

Property 58: Script termination on confirmed cancellation
*For any* confirmed cancellation, the wizard should terminate the deployment script execution immediately
**Validates: Requirements 14.3**

Property 59: Resource rollback on cancellation
*For any* deployment cancellation, the wizard should attempt to roll back any partially created AWS resources
**Validates: Requirements 14.4**

Property 60: Cancellation summary display
*For any* completed cancellation, the wizard should display a cancellation summary with cleanup status and collected logs
**Validates: Requirements 14.5**

### CloudFormation Event Properties

Property 61: Stack events button availability
*For any* executing deployment, the wizard should provide a view stack events button
**Validates: Requirements 15.1**

Property 62: Stack events table display
*For any* view stack events button click, the wizard should display CloudFormation stack events in a table format
**Validates: Requirements 15.2**

Property 63: Stack event field completeness
*For any* displayed stack event, the wizard should show timestamp, resource type, logical resource ID, status, and status reason
**Validates: Requirements 15.3**

Property 64: Stack events auto-refresh
*For any* displayed stack events, the wizard should refresh the event list automatically every five seconds
**Validates: Requirements 15.4**

Property 65: Failed event highlighting
*For any* stack event with a failure status, the wizard should highlight it in red color
**Validates: Requirements 15.5**

## Error Handling

### Frontend Error Handling

**Network Errors:**
- Display user-friendly error messages for API failures
- Provide retry buttons for transient failures
- Show connection status indicator
- Cache capability list for offline viewing

**Validation Errors:**
- Real-time validation feedback on form inputs
- Clear error messages with correction guidance
- Prevent form submission until validation passes
- Highlight invalid fields

**WebSocket Disconnection:**
- Automatically attempt reconnection
- Display connection status to user
- Buffer logs during disconnection
- Resume log streaming on reconnection

**Browser Compatibility:**
- Detect unsupported browsers and show warning
- Graceful degradation for missing features
- Polyfills for older browsers

### Backend Error Handling

**AWS SDK Errors:**
- Catch and classify AWS errors (authentication, authorization, throttling, service errors)
- Return structured error responses with error codes
- Log errors for debugging
- Provide actionable error messages to frontend

**Deployment Script Errors:**
- Capture script exit codes
- Parse error messages from script output
- Classify errors (configuration, permission, resource limit, service unavailable)
- Include troubleshooting guidance in error response

**CloudFormation Errors:**
- Monitor stack events for failures
- Extract failure reasons from stack events
- Provide rollback status
- Include failed resource details

**Permission Errors:**
- Detect insufficient permissions during deployment
- Generate IAM policy JSON for missing permissions
- Provide clear guidance on permission correction
- Allow permission re-verification

**Resource Limit Errors:**
- Detect AWS service quota errors
- Provide guidance on requesting limit increases
- Include relevant AWS documentation links

**Timeout Handling:**
- Set reasonable timeouts for all AWS operations
- Handle long-running deployments gracefully
- Provide progress updates during long operations
- Allow user cancellation

### Error Response Format

```typescript
interface ErrorResponse {
  error: {
    code: string;
    message: string;
    details?: any;
    troubleshooting?: string[];
    documentationUrl?: string;
  };
}
```

**Error Codes:**
- `INVALID_ROLE_ARN`: Role ARN format is invalid
- `ROLE_ASSUMPTION_FAILED`: Unable to assume the provided role
- `INSUFFICIENT_PERMISSIONS`: Role lacks required permissions
- `DEPLOYMENT_FAILED`: Deployment script failed
- `VERIFICATION_FAILED`: Post-verification checks failed
- `CLOUDFORMATION_ERROR`: CloudFormation stack operation failed
- `NETWORK_ERROR`: Network connectivity issue
- `TIMEOUT`: Operation exceeded timeout
- `CANCELLED`: User cancelled the operation

## Electron Packaging and Distribution

### Build Process

**1. Build Python Backend (PyInstaller)**
```bash
cd backend
pip install -r requirements.txt
pyinstaller --onefile \
            --name totogi-backend \
            --add-data "capabilities:capabilities" \
            --hidden-import boto3 \
            --hidden-import botocore \
            app/main.py
# Output: backend/dist/totogi-backend.exe (Windows)
```

**2. Build React Frontend (Vite)**
```bash
cd frontend
npm install
npm run build
# Output: frontend/dist/ (static files)
```

**3. Package with Electron Builder**
```bash
cd electron
npm install
npm run build
# Output: electron/dist/Totogi-Installer-Setup-1.0.0.exe
```

### Electron Configuration

**electron/package.json:**
```json
{
  "name": "totogi-installer",
  "version": "1.0.0",
  "main": "main.js",
  "build": {
    "appId": "com.totogi.installer",
    "productName": "Totogi Capability Installer",
    "files": [
      "main.js",
      "preload.js",
      "../frontend/dist/**/*"
    ],
    "extraResources": [
      {
        "from": "../backend/dist/totogi-backend.exe",
        "to": "backend/totogi-backend.exe"
      },
      {
        "from": "../scripts/capabilities",
        "to": "capabilities"
      }
    ],
    "win": {
      "target": ["nsis", "portable"],
      "icon": "assets/icon.ico"
    },
    "mac": {
      "target": "dmg",
      "icon": "assets/icon.icns"
    },
    "linux": {
      "target": ["AppImage", "deb"],
      "icon": "assets/icon.png"
    }
  }
}
```

### Electron Main Process

**electron/main.js:**
```javascript
const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const isDev = process.env.NODE_ENV === 'development';

let backendProcess = null;
let mainWindow = null;

function startBackend() {
  if (isDev) {
    // Development: Run Python directly
    backendProcess = spawn('python', [
      path.join(__dirname, '../backend/app/main.py')
    ]);
  } else {
    // Production: Run bundled executable
    const backendPath = process.platform === 'win32'
      ? path.join(process.resourcesPath, 'backend', 'totogi-backend.exe')
      : path.join(process.resourcesPath, 'backend', 'totogi-backend');
    
    backendProcess = spawn(backendPath);
  }

  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data}`);
  });
}

function createWindow() {
  // Wait for backend to start (2 seconds)
  setTimeout(() => {
    mainWindow = new BrowserWindow({
      width: 1200,
      height: 800,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false
      }
    });

    if (isDev) {
      mainWindow.loadURL('http://localhost:5173'); // Vite dev server
      mainWindow.webContents.openDevTools();
    } else {
      mainWindow.loadFile(path.join(__dirname, '../frontend/dist/index.html'));
    }
  }, 2000);
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('quit', () => {
  if (backendProcess) {
    backendProcess.kill();
  }
});
```

### Bundle Size Estimates

- **React Frontend (built)**: ~2-5 MB
- **Electron Runtime**: ~150 MB
- **Python Backend (PyInstaller)**: ~50-80 MB
- **Total Installer Size**: ~200-250 MB

### Distribution

**Windows:**
- NSIS installer (.exe)
- Portable executable (no installation required)

**macOS:**
- DMG disk image
- Code-signed for Gatekeeper

**Linux:**
- AppImage (universal)
- DEB package (Debian/Ubuntu)

## Testing Strategy

### Unit Testing

**Frontend Unit Tests:**
- Component rendering tests (React Testing Library)
- State management tests (Redux/Context)
- Form validation logic tests
- Navigation flow tests
- Error handling tests
- Utility function tests

**Backend Unit Tests (Python/pytest):**
- Service method tests (mocked boto3)
- FastAPI endpoint tests (TestClient)
- Validation logic tests (Pydantic models)
- Error handling tests
- Log aggregation tests
- ZIP generation tests
- Subprocess execution tests

**Test Coverage Goals:**
- Minimum 80% code coverage
- 100% coverage for critical paths (deployment, verification)
- All error paths tested

### Property-Based Testing

Property-based tests will be implemented using **fast-check** (JavaScript/TypeScript property testing library) to verify universal properties across all inputs.

**Configuration:**
- Each property-based test will run a minimum of 100 iterations
- Tests will use random input generation to explore the input space
- Each test will be tagged with a comment referencing the design document property

**Tag Format:**
```typescript
// Feature: totogi-customer-toolkit, Property 6: Role ARN format validation
```

**Property Test Examples:**

1. **ARN Validation Property (Property 6):**
```typescript
// Feature: totogi-customer-toolkit, Property 6: Role ARN format validation
fc.assert(
  fc.property(fc.string(), (input) => {
    const result = validateRoleArn(input);
    const isValidFormat = /^arn:aws:iam::\d{12}:role\/[\w+=,.@-]+$/.test(input);
    return result.valid === isValidFormat;
  }),
  { numRuns: 100 }
);
```

2. **Log Highlighting Property (Property 22, 23):**
```typescript
// Feature: totogi-customer-toolkit, Property 22: Error log highlighting
fc.assert(
  fc.property(
    fc.record({
      level: fc.constantFrom('info', 'warning', 'error'),
      message: fc.string()
    }),
    (logEntry) => {
      const rendered = renderLogEntry(logEntry);
      if (logEntry.level === 'error') {
        return rendered.includes('color: red');
      } else if (logEntry.level === 'warning') {
        return rendered.includes('color: yellow');
      }
      return true;
    }
  ),
  { numRuns: 100 }
);
```

3. **State Clearing Property (Property 54):**
```typescript
// Feature: totogi-customer-toolkit, Property 54: State clearing on new deployment
fc.assert(
  fc.property(
    fc.record({
      capability: fc.string(),
      roleArn: fc.string(),
      logs: fc.array(fc.string())
    }),
    (previousState) => {
      const wizard = new WizardStateMachine(previousState);
      wizard.startNewDeployment();
      const newState = wizard.getState();
      return (
        newState.capability === null &&
        newState.roleArn === null &&
        newState.logs.length === 0
      );
    }
  ),
  { numRuns: 100 }
);
```

4. **Diagnostic Log Content Property (Property 36):**
```typescript
// Feature: totogi-customer-toolkit, Property 36: Diagnostic log content completeness
fc.assert(
  fc.property(
    fc.record({
      deploymentLogs: fc.array(fc.string()),
      cfnEvents: fc.array(fc.object()),
      errors: fc.array(fc.string())
    }),
    (diagnosticData) => {
      const zipContent = generateDiagnosticZip(diagnosticData);
      return (
        zipContent.includes('deployment-logs.txt') &&
        zipContent.includes('cloudformation-events.json') &&
        zipContent.includes('errors.txt')
      );
    }
  ),
  { numRuns: 100 }
);
```

### Integration Testing

**API Integration Tests:**
- Test complete API workflows (capability selection → deployment → verification)
- Test error scenarios with mocked AWS failures
- Test WebSocket log streaming
- Test concurrent deployments

**AWS Integration Tests:**
- Test actual AWS SDK calls in test environment
- Test role assumption with test IAM roles
- Test CloudFormation stack creation/deletion
- Test permission verification with test policies

**End-to-End Tests:**
- Full deployment workflow with test capability
- Test cancellation and rollback
- Test retry after failure
- Test diagnostic log download

### Manual Testing

**Browser Compatibility Testing:**
- Chrome, Firefox, Safari, Edge (latest versions)
- Mobile browsers (iOS Safari, Chrome Mobile)

**User Acceptance Testing:**
- Complete deployment workflow
- Error recovery scenarios
- UI/UX validation
- Performance testing with large logs

**Security Testing:**
- Credential handling validation
- No credential leakage in logs
- Secure WebSocket connections
- Input sanitization

