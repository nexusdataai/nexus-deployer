# Design Document

## Overview

This design addresses CloudFormation deployment failures caused by missing stack exports by implementing comprehensive dependency validation, intelligent deployment ordering, and graceful handling of conditional resources. The solution enhances the existing deployment orchestrator with pre-flight dependency checks and provides clear, actionable error messages when dependencies cannot be satisfied.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Deployment Request                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Deployment Orchestrator                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  1. Template Parser                                   │  │
│  │     - Parse CloudFormation templates                  │  │
│  │     - Extract Fn::ImportValue references              │  │
│  │     - Extract Export declarations                     │  │
│  │     - Identify conditional resources                  │  │
│  └──────────────────────────────────────────────────────┘  │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  2. Dependency Validator                              │  │
│  │     - Build dependency graph                          │  │
│  │     - Check for circular dependencies                 │  │
│  │     - Validate export existence in AWS                │  │
│  │     - Evaluate conditional resource states            │  │
│  └──────────────────────────────────────────────────────┘  │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  3. Deployment Planner                                │  │
│  │     - Determine deployment order                      │  │
│  │     - Identify missing prerequisite stacks            │  │
│  │     - Generate deployment plan                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  4. Stack Deployer                                    │  │
│  │     - Execute deployment plan                         │  │
│  │     - Monitor stack creation/update                   │  │
│  │     - Collect outputs for dependent stacks            │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
User Request
     │
     ▼
[Parse Templates] ──> Extract imports/exports
     │
     ▼
[Build Dependency Graph]
     │
     ├──> Check AWS for existing exports
     │
     ├──> Evaluate conditions
     │
     └──> Detect circular dependencies
     │
     ▼
[Generate Deployment Plan]
     │
     ├──> Order stacks by dependencies
     │
     ├──> Identify missing stacks
     │
     └──> Validate all dependencies can be satisfied
     │
     ▼
[Execute Deployment] (if validation passes)
     │
     └──> Deploy stacks in order
```

## Components and Interfaces

### 1. StackDependencyAnalyzer

Analyzes CloudFormation templates to extract dependency information.

```python
class StackDependencyAnalyzer:
    """Analyzes CloudFormation templates for dependencies"""
    
    def analyze_template(self, template: Dict[str, Any]) -> TemplateDependencies:
        """
        Analyze a CloudFormation template
        
        Returns:
            TemplateDependencies containing imports, exports, and conditions
        """
        pass
    
    def extract_imports(self, template: Dict[str, Any]) -> List[ImportReference]:
        """Extract all Fn::ImportValue references"""
        pass
    
    def extract_exports(self, template: Dict[str, Any]) -> List[ExportDeclaration]:
        """Extract all Export declarations from Outputs"""
        pass
    
    def extract_conditions(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Extract condition definitions"""
        pass
    
    def is_conditional_export(self, export: ExportDeclaration, 
                             template: Dict[str, Any]) -> Optional[str]:
        """Check if an export is conditional and return condition name"""
        pass
```

### 2. DependencyValidator

Validates that all stack dependencies can be satisfied.

```python
class DependencyValidator:
    """Validates stack dependencies before deployment"""
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        self.credentials = credentials
        self.cfn_client = None
    
    def validate_dependencies(self, 
                            stack_configs: List[StackConfig],
                            region: str) -> ValidationResult:
        """
        Validate all dependencies for a set of stacks
        
        Returns:
            ValidationResult with success status and any issues found
        """
        pass
    
    def check_export_exists(self, export_name: str, region: str) -> bool:
        """Check if an export exists in AWS CloudFormation"""
        pass
    
    def get_stack_exports(self, stack_name: str, region: str) -> List[str]:
        """Get all exports from a deployed stack"""
        pass
    
    def evaluate_condition(self, condition_name: str, 
                          stack_name: str, 
                          region: str) -> Optional[bool]:
        """
        Evaluate if a condition is true for a deployed stack
        
        Returns:
            True/False if stack exists and condition can be evaluated,
            None if stack doesn't exist
        """
        pass
    
    def build_dependency_graph(self, 
                              stack_configs: List[StackConfig]) -> DependencyGraph:
        """Build a directed graph of stack dependencies"""
        pass
    
    def detect_circular_dependencies(self, 
                                    graph: DependencyGraph) -> List[List[str]]:
        """Detect circular dependency chains"""
        pass
```

### 3. DeploymentPlanner

Determines the optimal deployment order and generates a deployment plan.

```python
class DeploymentPlanner:
    """Plans deployment order based on dependencies"""
    
    def create_deployment_plan(self, 
                              stack_configs: List[StackConfig],
                              dependency_graph: DependencyGraph) -> DeploymentPlan:
        """
        Create a deployment plan with proper ordering
        
        Returns:
            DeploymentPlan with ordered stack deployments
        """
        pass
    
    def topological_sort(self, graph: DependencyGraph) -> List[str]:
        """Perform topological sort to determine deployment order"""
        pass
    
    def identify_missing_stacks(self, 
                               required_exports: List[str],
                               available_stacks: List[str]) -> List[str]:
        """Identify which stacks need to be deployed to satisfy dependencies"""
        pass
    
    def generate_dry_run_report(self, plan: DeploymentPlan) -> str:
        """Generate a human-readable dry-run report"""
        pass
```

### 4. Enhanced DeploymentOrchestrator

Extended deployment orchestrator with dependency validation.

```python
class DeploymentOrchestrator:
    """Orchestrates complete deployment workflow with dependency validation"""
    
    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        self.credentials = credentials
        self.dependency_analyzer = StackDependencyAnalyzer()
        self.dependency_validator = DependencyValidator(credentials)
        self.deployment_planner = DeploymentPlanner()
        # ... existing services
    
    def deploy_capability_with_validation(self,
                                         config: Dict[str, Any],
                                         dry_run: bool = False,
                                         callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Deploy capability with full dependency validation
        
        Args:
            config: Deployment configuration
            dry_run: If True, only validate without deploying
            callback: Progress callback
            
        Returns:
            Deployment result with validation details
        """
        pass
    
    def validate_stack_dependencies(self,
                                   stack_configs: List[StackConfig],
                                   region: str,
                                   callback: Optional[Callable] = None) -> ValidationResult:
        """Validate all stack dependencies before deployment"""
        pass
```

## Data Models

### TemplateDependencies

```python
@dataclass
class ImportReference:
    """Represents a Fn::ImportValue reference"""
    export_name: str  # The name being imported
    resource_path: str  # Path in template where import occurs
    is_conditional: bool  # Whether the import is within a condition
    condition_name: Optional[str]  # Name of the condition if conditional

@dataclass
class ExportDeclaration:
    """Represents an Export in Outputs"""
    export_name: str  # The export name
    output_key: str  # The output key in the template
    is_conditional: bool  # Whether the export is conditional
    condition_name: Optional[str]  # Name of the condition if conditional
    value: Any  # The value being exported (can be Ref, GetAtt, etc.)

@dataclass
class TemplateDependencies:
    """Complete dependency information for a template"""
    imports: List[ImportReference]
    exports: List[ExportDeclaration]
    conditions: Dict[str, Any]
    parameters: Dict[str, Any]
```

### DependencyGraph

```python
@dataclass
class DependencyNode:
    """Node in the dependency graph"""
    stack_name: str
    stack_type: str
    template_path: str
    imports: List[ImportReference]
    exports: List[ExportDeclaration]
    depends_on: List[str]  # Stack names this stack depends on

@dataclass
class DependencyGraph:
    """Directed graph of stack dependencies"""
    nodes: Dict[str, DependencyNode]  # stack_name -> node
    edges: List[Tuple[str, str]]  # (from_stack, to_stack) edges
    
    def get_dependencies(self, stack_name: str) -> List[str]:
        """Get all stacks that this stack depends on"""
        pass
    
    def get_dependents(self, stack_name: str) -> List[str]:
        """Get all stacks that depend on this stack"""
        pass
```

### ValidationResult

```python
@dataclass
class DependencyIssue:
    """Represents a dependency validation issue"""
    severity: str  # 'error', 'warning', 'info'
    issue_type: str  # 'missing_export', 'circular_dependency', 'conditional_mismatch'
    stack_name: str
    description: str
    suggested_action: str
    details: Dict[str, Any]

@dataclass
class ValidationResult:
    """Result of dependency validation"""
    success: bool
    issues: List[DependencyIssue]
    dependency_graph: Optional[DependencyGraph]
    deployment_order: Optional[List[str]]
    summary: str
```

### DeploymentPlan

```python
@dataclass
class StackDeploymentStep:
    """Single step in deployment plan"""
    step_number: int
    stack_name: str
    stack_type: str
    action: str  # 'create', 'update', 'skip'
    reason: str
    dependencies_satisfied: List[str]
    will_provide_exports: List[str]

@dataclass
class DeploymentPlan:
    """Complete deployment plan"""
    steps: List[StackDeploymentStep]
    total_stacks: int
    estimated_duration_minutes: int
    validation_passed: bool
    warnings: List[str]
```

## 

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Property 1: Import validation completeness
*For any* stack configuration with imports, the validation function should identify the existence status of all imported values
**Validates: Requirements 1.1**

Property 2: Export source identification
*For any* missing export, the system should correctly identify which stack is responsible for providing that export
**Validates: Requirements 1.2**

Property 3: Error report completeness
*For any* validation error, the error report should contain the export name, providing stack name, and a suggested action
**Validates: Requirements 1.3**

Property 4: Conditional export validation
*For any* stack with conditional exports, the validator should check the condition state before validating dependent imports
**Validates: Requirements 1.5**

Property 5: Deployment ordering respects dependencies
*For any* set of stacks with dependencies, the deployment order should ensure that providing stacks are deployed before consuming stacks
**Validates: Requirements 2.2, 4.3**

Property 6: Certificate selection priority
*For any* configuration with multiple certificate sources, the system should select certificates according to the defined priority order
**Validates: Requirements 2.4**

Property 7: Error messages contain export names
*For any* import failure, the error message should contain the exact export name that is missing
**Validates: Requirements 3.1**

Property 8: Error messages identify providing stacks
*For any* import failure, the error message should identify which stack should provide the missing export
**Validates: Requirements 3.2**

Property 9: Error messages include stack status
*For any* import failure, the error message should include the current deployment status of the providing stack
**Validates: Requirements 3.3**

Property 10: Conditional export errors explain conditions
*For any* missing conditional export, the error message should explain which condition prevented the export from being created
**Validates: Requirements 3.4**

Property 11: Validation finds all issues
*For any* set of stacks with multiple dependency issues, validation should report all issues in a single pass, not just the first issue found
**Validates: Requirements 3.5**

Property 12: Import extraction completeness
*For any* CloudFormation template, the analyzer should identify all Fn::ImportValue references regardless of their location in the template
**Validates: Requirements 4.1**

Property 13: Import-to-stack mapping accuracy
*For any* identified import, the system should correctly map it to the stack that provides the export
**Validates: Requirements 4.2**

Property 14: Circular dependency detection
*For any* dependency graph containing cycles, the system should detect and report the circular dependency chain
**Validates: Requirements 4.4**

Property 15: Export naming convention compliance
*For any* stack export, the export name should follow the pattern `${StackName}-${ResourceType}`
**Validates: Requirements 5.1**

Property 16: Import naming consistency
*For any* stack import, the import reference should use the same naming pattern as its corresponding export
**Validates: Requirements 5.2**

Property 17: Export-import name matching
*For any* pair of export and import, the validator should verify that the names match according to the naming convention
**Validates: Requirements 5.3**

Property 18: Naming mismatch reporting
*For any* set of templates with naming inconsistencies, the system should report all mismatches with suggested corrections
**Validates: Requirements 5.4**

Property 19: Dry-run export validation
*For any* dry-run execution, the system should check the existence of all required exports without creating any resources
**Validates: Requirements 6.2**

## Error Handling

### Missing Export Errors

When an import cannot be satisfied, the system will provide structured error information:

```python
{
    "error_type": "missing_export",
    "export_name": "Call-Processing-prod-backend-domain-BackendCertificateArn",
    "importing_stack": "Call-Processing-prod-backend-service",
    "providing_stack": "Call-Processing-prod-backend-domain",
    "providing_stack_status": "NOT_DEPLOYED",  # or "CREATE_COMPLETE", "ROLLBACK_COMPLETE", etc.
    "is_conditional": True,
    "condition_name": "CreateCert",
    "condition_evaluated": False,
    "suggested_action": "Deploy the domain stack first, or ensure the CreateCert condition is true",
    "details": {
        "import_location": "Resources.LoadBalancer.Properties.Certificates[0].CertificateArn",
        "alternative_options": ["Use RegionalCert instead", "Deploy without HTTPS"]
    }
}
```

### Circular Dependency Errors

When circular dependencies are detected:

```python
{
    "error_type": "circular_dependency",
    "cycle": ["stack-a", "stack-b", "stack-c", "stack-a"],
    "description": "Stack 'stack-a' depends on 'stack-b', which depends on 'stack-c', which depends on 'stack-a'",
    "suggested_action": "Refactor stacks to remove circular dependencies or consolidate into a single stack"
}
```

### Conditional Resource Errors

When conditional exports don't match conditional imports:

```python
{
    "error_type": "conditional_mismatch",
    "export_name": "BackendCertificateArn",
    "export_condition": "CreateCert",
    "export_condition_value": False,
    "importing_stack": "service-stack",
    "import_condition": "UseDomainCert",
    "import_condition_value": True,
    "suggested_action": "Ensure import condition matches export condition, or provide alternative value"
}
```

### Validation Failure Handling

The system will:
1. Collect all validation errors before failing
2. Present errors in order of severity (errors, warnings, info)
3. Group related errors together
4. Provide actionable suggestions for each error
5. Allow users to override warnings (but not errors) with explicit confirmation

### Deployment Failure Recovery

If a deployment fails due to dependency issues:
1. The system will not attempt to deploy dependent stacks
2. Already-deployed stacks will remain in their current state
3. The user will receive a detailed report of what succeeded and what failed
4. The system will suggest a recovery path (e.g., "Deploy domain stack first, then retry")

## Testing Strategy

### Unit Testing

Unit tests will cover:

1. **Template Parsing**
   - Parsing valid CloudFormation templates
   - Extracting imports from various template locations
   - Extracting exports from Outputs section
   - Handling malformed templates gracefully

2. **Dependency Graph Construction**
   - Building graphs from stack configurations
   - Handling empty graphs
   - Handling single-node graphs

3. **Condition Evaluation**
   - Evaluating simple conditions
   - Evaluating complex conditions with Fn::And, Fn::Or, Fn::Not
   - Handling undefined conditions

4. **Error Message Formatting**
   - Generating error messages with all required fields
   - Formatting suggestions appropriately
   - Handling missing optional fields

### Property-Based Testing

Property-based tests will use Python's `hypothesis` library with a minimum of 100 iterations per test.

1. **Property Test: Import Extraction Completeness**
   - Generate random CloudFormation templates with various import patterns
   - Verify all Fn::ImportValue references are found
   - **Feature: cloudformation-export-dependency-fix, Property 12: Import extraction completeness**

2. **Property Test: Deployment Ordering**
   - Generate random dependency graphs (acyclic)
   - Verify topological sort produces valid ordering
   - Verify all dependencies are satisfied in the ordering
   - **Feature: cloudformation-export-dependency-fix, Property 5: Deployment ordering respects dependencies**

3. **Property Test: Circular Dependency Detection**
   - Generate random graphs with known cycles
   - Verify cycles are detected
   - Verify reported cycle is valid
   - **Feature: cloudformation-export-dependency-fix, Property 14: Circular dependency detection**

4. **Property Test: Error Report Completeness**
   - Generate random validation failures
   - Verify all error reports contain required fields
   - **Feature: cloudformation-export-dependency-fix, Property 3: Error report completeness**

5. **Property Test: Validation Completeness**
   - Generate stacks with multiple dependency issues
   - Verify all issues are found in single pass
   - **Feature: cloudformation-export-dependency-fix, Property 11: Validation finds all issues**

6. **Property Test: Export Naming Convention**
   - Generate random stack names and resource types
   - Verify export names follow pattern
   - **Feature: cloudformation-export-dependency-fix, Property 15: Export naming convention compliance**

### Integration Testing

Integration tests will verify:

1. **End-to-End Validation Flow**
   - Load real CloudFormation templates
   - Validate against actual AWS environment
   - Verify correct deployment ordering

2. **AWS API Integration**
   - Check export existence via CloudFormation API
   - Retrieve stack outputs
   - Handle API errors gracefully

3. **Dry-Run Mode**
   - Execute dry-run against real templates
   - Verify no resources are created
   - Verify report accuracy

### Test Data

Test data will include:
- Sample CloudFormation templates with various dependency patterns
- Mock AWS API responses for different scenarios
- Known-good and known-bad dependency graphs
- Real-world templates from the starhub-deployer project

## Implementation Notes

### CloudFormation Template Parsing

The template parser must handle:
- Intrinsic functions (Fn::ImportValue, Fn::Sub, Fn::If, etc.)
- Nested intrinsic functions
- Short-form and long-form function syntax
- YAML and JSON templates

### AWS API Considerations

When checking for exports:
- Use `list_exports` API to get all exports in a region
- Cache export lists to minimize API calls
- Handle pagination for large numbers of exports
- Respect API rate limits

### Condition Evaluation Challenges

Evaluating conditions for deployed stacks is complex because:
- Conditions are evaluated at stack creation time
- Condition logic may depend on parameters
- We cannot directly query condition values via API

Approach:
1. For deployed stacks, check if the conditional resource exists
2. If resource exists, condition was true
3. If resource doesn't exist, condition was false
4. For undeployed stacks, we cannot evaluate conditions

### Backward Compatibility

To maintain backward compatibility:
- New validation is opt-in via configuration flag
- Existing deployments continue to work
- Validation warnings don't block deployment (only errors do)
- Export naming convention is enforced for new stacks only

### Performance Considerations

- Template parsing is done once per deployment
- Dependency graph construction is O(n) where n is number of stacks
- Topological sort is O(V + E) where V is vertices, E is edges
- AWS API calls are minimized through caching
- Validation adds ~5-10 seconds to deployment time

## Future Enhancements

1. **Automatic Dependency Resolution**
   - Automatically deploy missing prerequisite stacks
   - Prompt user for missing configuration

2. **Dependency Visualization**
   - Generate visual dependency graphs
   - Show deployment flow in UI

3. **Smart Retry Logic**
   - Automatically retry failed stacks after dependencies are satisfied
   - Implement exponential backoff for transient failures

4. **Template Linting**
   - Validate templates against best practices
   - Suggest improvements for dependency management

5. **Cross-Region Dependencies**
   - Handle dependencies across AWS regions
   - Validate cross-region export/import patterns
