<!-- (renamed totogi-* -> nexus-* on 2026-06-13; original wording was design-snapshot) -->
# Design Document: Update Workflow Cognito Preservation

## Overview

This design document describes the architecture and implementation approach for differentiating install and update workflows in the Nexus AI Customer Toolkit deployer, with a primary focus on preserving Cognito User Pool data during update operations.

The current system treats both install and update operations similarly, which can result in the Cognito User Pool being recreated during updates, erasing all user data. This design introduces workflow classification, selective stack updates, and data preservation mechanisms to ensure user authentication data is protected during capability updates.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        UPDATE WORKFLOW ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────────────┐ │
│  │  Deployment      │────▶│  Workflow        │────▶│  Stack Update            │ │
│  │  Wizard (UI)     │     │  Classifier      │     │  Orchestrator            │ │
│  └──────────────────┘     └──────────────────┘     └──────────────────────────┘ │
│           │                        │                           │                 │
│           │                        ▼                           ▼                 │
│           │              ┌──────────────────┐     ┌──────────────────────────┐  │
│           │              │  Stack Detection │     │  Cognito Preservation    │  │
│           │              │  Service         │     │  Service                 │  │
│           │              └──────────────────┘     └──────────────────────────┘  │
│           │                        │                           │                 │
│           ▼                        ▼                           ▼                 │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────────────┐ │
│  │  Update Options  │     │  TinyDB State    │     │  Cognito User Export     │ │
│  │  Dialog          │     │  Service         │     │  Service                 │ │
│  └──────────────────┘     └──────────────────┘     └──────────────────────────┘ │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Workflow Classification Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        WORKFLOW CLASSIFICATION FLOW                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  Deployment Initiated                                                            │
│         │                                                                        │
│         ▼                                                                        │
│  ┌─────────────────────┐                                                        │
│  │ Check TinyDB for    │                                                        │
│  │ existing deployment │                                                        │
│  └──────────┬──────────┘                                                        │
│             │                                                                    │
│     ┌───────┴───────┐                                                           │
│     │               │                                                           │
│     ▼               ▼                                                           │
│  No Record       Record Found                                                   │
│     │               │                                                           │
│     │               ▼                                                           │
│     │        ┌─────────────────────┐                                            │
│     │        │ User selects        │                                            │
│     │        │ deployment strategy │                                            │
│     │        └──────────┬──────────┘                                            │
│     │                   │                                                        │
│     │           ┌───────┴───────┐                                               │
│     │           │               │                                               │
│     │           ▼               ▼                                               │
│     │     Clean Deploy    Update Existing                                       │
│     │           │               │                                               │
│     ▼           ▼               ▼                                               │
│  ┌─────────────────┐     ┌─────────────────┐                                    │
│  │ INSTALL_WORKFLOW│     │ UPDATE_WORKFLOW │                                    │
│  │ (Full deploy)   │     │ (Preserve data) │                                    │
│  └─────────────────┘     └─────────────────┘                                    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. WorkflowClassifier

Determines whether the deployment should follow install or update workflow.

```python
from enum import Enum
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

class WorkflowType(Enum):
    INSTALL = "install"
    UPDATE = "update"

@dataclass
class WorkflowClassification:
    workflow_type: WorkflowType
    capability_name: str
    environment: str
    region: str
    existing_stacks: list
    strategy_selected: Optional[str]
    classification_timestamp: datetime
    reason: str

class WorkflowClassifier:
    def __init__(self, stack_detection_service, deployment_state_service):
        self.stack_detection = stack_detection_service
        self.state_service = deployment_state_service
    
    def classify_workflow(
        self,
        capability_name: str,
        environment: str,
        region: str,
        user_strategy: Optional[str] = None
    ) -> WorkflowClassification:
        """
        Classify the deployment as install or update workflow.
        
        Args:
            capability_name: Name of the capability being deployed
            environment: Target environment (dev, stage, prod)
            region: AWS region
            user_strategy: User-selected strategy (clean_deploy or update_existing)
            
        Returns:
            WorkflowClassification with workflow type and metadata
        """
        pass
```

### 2. CognitoPreservationService

Manages Cognito User Pool preservation during updates.

```python
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class CognitoOutputs:
    user_pool_id: str
    user_pool_client_id: str
    user_pool_domain: str
    region: str
    admin_user_email: Optional[str] = None

@dataclass
class CognitoValidationResult:
    is_valid: bool
    user_pool_accessible: bool
    client_configured: bool
    user_count: int
    error_message: Optional[str] = None
    remediation_steps: Optional[List[str]] = None

class CognitoPreservationService:
    def __init__(self, credentials: Dict[str, str]):
        self.credentials = credentials
    
    def get_existing_cognito_outputs(
        self,
        stack_name: str,
        region: str
    ) -> Optional[CognitoOutputs]:
        """Retrieve existing Cognito outputs from deployed stack."""
        pass
    
    def validate_user_pool(
        self,
        user_pool_id: str,
        client_id: str,
        region: str
    ) -> CognitoValidationResult:
        """Validate that the Cognito User Pool is accessible and functional."""
        pass
    
    def should_preserve_cognito(
        self,
        workflow_type: WorkflowType,
        include_cognito_update: bool
    ) -> bool:
        """Determine if Cognito should be preserved based on workflow and user choice."""
        pass
```

### 3. CognitoUserExportService

Handles user data backup before Cognito modifications.

```python
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

@dataclass
class UserExportRecord:
    username: str
    email: str
    attributes: Dict[str, str]
    groups: List[str]
    enabled: bool
    status: str
    created_at: datetime

@dataclass
class ExportResult:
    success: bool
    export_path: Path
    user_count: int
    export_timestamp: datetime
    capability_name: str
    environment: str
    error_message: Optional[str] = None

class CognitoUserExportService:
    def __init__(self, credentials: Dict[str, str], export_dir: Path):
        self.credentials = credentials
        self.export_dir = export_dir
    
    def export_users(
        self,
        user_pool_id: str,
        region: str,
        capability_name: str,
        environment: str
    ) -> ExportResult:
        """Export all users from a Cognito User Pool."""
        pass
    
    def list_users(
        self,
        user_pool_id: str,
        region: str
    ) -> List[UserExportRecord]:
        """List all users in a Cognito User Pool."""
        pass
```

### 4. CognitoDriftDetector

Detects configuration drift between deployed Cognito and template.

```python
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class DriftItem:
    setting_name: str
    template_value: str
    deployed_value: str
    category: str  # password_policy, mfa, app_client, custom_attributes

@dataclass
class DriftDetectionResult:
    has_drift: bool
    drift_items: List[DriftItem]
    detection_timestamp: datetime
    error_message: Optional[str] = None

class CognitoDriftDetector:
    def __init__(self, credentials: Dict[str, str]):
        self.credentials = credentials
    
    def detect_drift(
        self,
        user_pool_id: str,
        region: str,
        template_path: Path
    ) -> DriftDetectionResult:
        """
        Compare deployed Cognito configuration with template.
        
        Checks:
        - Password policy (MinimumLength, RequireUppercase, etc.)
        - MFA configuration
        - App client settings
        - Custom attributes
        """
        pass
```

### 5. UpdateWorkflowOrchestrator

Coordinates the update workflow with preservation logic.

```python
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

@dataclass
class UpdateConfig:
    preserve_cognito: bool = True
    include_cognito_update: bool = False
    require_user_backup: bool = True
    selected_stacks: Optional[List[str]] = None

@dataclass
class UpdateResult:
    success: bool
    stacks_updated: List[str]
    stacks_preserved: List[str]
    stacks_failed: List[str]
    cognito_preserved: bool
    user_backup_path: Optional[Path] = None
    error_message: Optional[str] = None

class UpdateWorkflowOrchestrator:
    def __init__(
        self,
        cfn_service,
        cognito_preservation_service,
        cognito_export_service,
        drift_detector,
        workflow_classifier
    ):
        self.cfn_service = cfn_service
        self.cognito_preservation = cognito_preservation_service
        self.cognito_export = cognito_export_service
        self.drift_detector = drift_detector
        self.classifier = workflow_classifier
    
    def execute_update(
        self,
        config: Dict,
        update_config: UpdateConfig,
        callback: Optional[Callable] = None
    ) -> UpdateResult:
        """
        Execute update workflow with Cognito preservation.
        
        Steps:
        1. Classify workflow
        2. Retrieve existing stack outputs
        3. Validate Cognito User Pool
        4. Optionally export user data
        5. Optionally detect drift
        6. Deploy stacks (skipping Cognito if preserving)
        7. Post-update validation
        8. Generate audit record
        """
        pass
    
    def get_stacks_to_update(
        self,
        update_config: UpdateConfig,
        existing_stacks: List[str]
    ) -> List[str]:
        """Determine which stacks should be updated based on config."""
        pass
```

### 6. StackOutputPreserver

Manages preservation and reuse of stack outputs during updates.

```python
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class PreservedOutputs:
    stack_name: str
    outputs: Dict[str, str]
    retrieved_at: datetime
    is_cognito_stack: bool = False

class StackOutputPreserver:
    def __init__(self, cfn_service):
        self.cfn_service = cfn_service
        self._preserved_outputs: Dict[str, PreservedOutputs] = {}
    
    def preserve_all_outputs(
        self,
        capability_name: str,
        environment: str,
        region: str
    ) -> Dict[str, PreservedOutputs]:
        """Retrieve and store outputs from all existing stacks."""
        pass
    
    def get_cognito_outputs(self) -> Optional[Dict[str, str]]:
        """Get preserved Cognito outputs for dependent stacks."""
        pass
    
    def get_outputs_for_stack(
        self,
        stack_name: str
    ) -> Optional[Dict[str, str]]:
        """Get preserved outputs for a specific stack."""
        pass
```

## Data Models

### UpdateWorkflowConfig

Configuration for update workflow behavior.

```python
@dataclass
class UpdateWorkflowConfig:
    # Cognito preservation settings
    default_preserve_cognito: bool = True
    require_backup_before_cognito_update: bool = True
    
    # Selective update settings
    enable_selective_updates: bool = True
    
    # Validation settings
    validate_cognito_before_update: bool = True
    validate_cognito_after_update: bool = True
    
    # Drift detection settings
    enable_drift_detection: bool = True
    
    # Audit settings
    enable_audit_trail: bool = True
```

### UpdateAuditRecord

Audit trail for update operations.

```python
@dataclass
class UpdateAuditRecord:
    operation_id: str
    operation_type: str  # "update"
    capability_name: str
    environment: str
    region: str
    operator_identity: Optional[str]
    timestamp: datetime
    
    # Stack actions
    stacks_updated: List[str]
    stacks_preserved: List[str]
    stacks_failed: List[str]
    
    # Cognito specific
    cognito_preserved: bool
    user_data_exported: bool
    export_location: Optional[str]
    export_user_count: Optional[int]
    
    # Result
    success: bool
    error_message: Optional[str]
    duration_seconds: float
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Workflow Classification Consistency

*For any* deployment request with a capability name, environment, and region, the workflow classifier SHALL produce a consistent classification where:
- No existing deployment record → INSTALL workflow
- Existing record + "Clean Deploy" strategy → INSTALL workflow  
- Existing record + "Update Existing" strategy → UPDATE workflow

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

### Property 2: Cognito Stack Skip During Update

*For any* UPDATE workflow execution where `include_cognito_update` is false, the frontend-cognito stack SHALL NOT be included in the deployment stack list, AND the system SHALL verify the existing User Pool is accessible before proceeding.

**Validates: Requirements 2.1, 2.5, 2.6**

### Property 3: Cognito Output Preservation

*For any* UPDATE workflow, the system SHALL retrieve existing Cognito outputs (UserPoolId, UserPoolClientId, UserPoolDomain) before any stack modifications, AND these outputs SHALL be passed to all dependent stacks that require Cognito configuration.

**Validates: Requirements 2.3, 2.4, 6.1, 6.2, 6.3, 6.4**

### Property 4: Cognito Update Inclusion

*For any* UPDATE workflow where the user confirms Cognito update inclusion, the frontend-cognito stack SHALL be included in the deployment list AND the CloudFormation update_stack operation (not delete/create) SHALL be used.

**Validates: Requirements 3.4, 3.5**

### Property 5: User Data Export Completeness

*For any* user data export operation, the export SHALL include all users from the Cognito User Pool with their attributes, AND the export file SHALL be stored with timestamp and capability identifiers, AND the export result SHALL report the correct user count.

**Validates: Requirements 4.2, 4.3, 4.4**

### Property 6: Export Failure Halts Update

*For any* UPDATE workflow that includes Cognito updates with required backup, if the user data export fails, the Cognito update SHALL be halted and an error SHALL be reported.

**Validates: Requirements 4.5**

### Property 7: Drift Detection Coverage

*For any* drift detection operation, the system SHALL compare password policy, MFA configuration, app client settings, and custom attributes between the deployed Cognito and the template, AND drift detection failures SHALL NOT block the workflow.

**Validates: Requirements 5.1, 5.2, 5.3, 5.5**

### Property 8: Progress Reporting Format

*For any* UPDATE workflow execution, each stack action SHALL be reported with the correct prefix:
- Preserved stacks: "[PRESERVE] {stack_name}: Skipping to preserve existing data"
- Updated stacks: "[UPDATE] {stack_name}: Updating existing stack"
- Completion: Summary with counts of updated, preserved, and failed stacks

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

### Property 9: Failure Handling and Halt

*For any* stack update failure during UPDATE workflow, further stack updates SHALL be halted, AND the system SHALL report which stacks were successfully updated before the failure, AND CloudFormation rollback status SHALL be detected and reported.

**Validates: Requirements 8.1, 8.2, 8.4, 8.5**

### Property 10: Selective Update Validation

*For any* selective update where specific stacks are chosen, only the selected stacks SHALL be updated, AND the system SHALL validate that skipped stacks don't have breaking dependency changes, AND validation failures SHALL report which additional stacks must be included.

**Validates: Requirements 9.2, 9.3, 9.4, 9.5, 9.6**

### Property 11: Configuration Application

*For any* UPDATE workflow, the configured defaults (preserve_cognito, require_backup, enable_selective_updates) SHALL be applied unless explicitly overridden by the operator.

**Validates: Requirements 10.4**

### Property 12: Cognito Validation Completeness

*For any* UPDATE workflow with Cognito validation enabled, the system SHALL validate User Pool accessibility and App Client configuration both before and after the update, AND validation failures before update SHALL halt the process, AND validation failures after update SHALL report with rollback guidance.

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**

### Property 13: Audit Trail Completeness

*For any* UPDATE workflow execution, an audit record SHALL be created containing operation type, timestamp, operator identity, per-stack actions, Cognito preservation status, export details (if applicable), and final result, AND the record SHALL be stored in the deployment state database.

**Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**

## Error Handling

### Cognito Access Errors

When the existing Cognito User Pool is not accessible:
1. Log the error with User Pool ID and region
2. Halt the update workflow
3. Report error with remediation steps:
   - Verify AWS credentials have Cognito permissions
   - Check if User Pool was manually deleted
   - Suggest running install workflow if User Pool is gone

### Export Failures

When user data export fails:
1. Log the error with details
2. If backup is required, halt Cognito update
3. If backup is optional, prompt user to continue or abort
4. Provide guidance on manual export via AWS Console

### Stack Update Failures

When a stack update fails:
1. Log the failure with stack name and error
2. Halt further stack updates
3. Wait for CloudFormation rollback if in progress
4. Report successful stacks before failure
5. Provide manual rollback guidance if needed

### Drift Detection Failures

When drift detection fails:
1. Log the error
2. Allow workflow to continue
3. Warn user that drift status is unknown
4. Suggest manual verification via AWS Console

## Testing Strategy

### Unit Tests

Unit tests will verify individual component behavior:

1. **WorkflowClassifier Tests**
   - Test classification with no existing deployment
   - Test classification with existing deployment and various strategies
   - Test edge cases (missing data, invalid strategies)

2. **CognitoPreservationService Tests**
   - Test output retrieval from existing stacks
   - Test User Pool validation logic
   - Test preservation decision logic

3. **CognitoUserExportService Tests**
   - Test user listing with pagination
   - Test export file generation
   - Test error handling for API failures

4. **CognitoDriftDetector Tests**
   - Test drift detection for each setting category
   - Test comparison logic
   - Test error handling

### Property-Based Tests

Property-based tests will verify universal properties using the `hypothesis` library:

1. **Workflow Classification Property Test**
   - Generate random deployment scenarios
   - Verify classification consistency
   - Minimum 100 iterations

2. **Cognito Output Preservation Property Test**
   - Generate random stack configurations
   - Verify outputs are preserved and passed correctly
   - Minimum 100 iterations

3. **Progress Reporting Property Test**
   - Generate random update scenarios
   - Verify message format consistency
   - Minimum 100 iterations

4. **Audit Trail Property Test**
   - Generate random update operations
   - Verify audit records contain all required fields
   - Minimum 100 iterations

### Integration Tests

Integration tests will verify end-to-end workflows:

1. **Update Workflow Integration Test**
   - Test complete update flow with mocked AWS services
   - Verify Cognito preservation
   - Verify stack output handling

2. **Export and Restore Integration Test**
   - Test user export functionality
   - Verify export file format and content

