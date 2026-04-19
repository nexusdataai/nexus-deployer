"""
Data models for CloudFormation stack dependency tracking
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum


class IssueSeverity(str, Enum):
    """Severity levels for dependency issues"""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueType(str, Enum):
    """Types of dependency issues"""
    MISSING_EXPORT = "missing_export"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    CONDITIONAL_MISMATCH = "conditional_mismatch"
    NAMING_VIOLATION = "naming_violation"


class DeploymentAction(str, Enum):
    """Actions for stack deployment"""
    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"


@dataclass
class ImportReference:
    """Represents a Fn::ImportValue reference in a CloudFormation template"""
    export_name: str  # The name being imported
    resource_path: str  # Path in template where import occurs
    is_conditional: bool = False  # Whether the import is within a condition
    condition_name: Optional[str] = None  # Name of the condition if conditional


@dataclass
class ExportDeclaration:
    """Represents an Export in CloudFormation Outputs section"""
    export_name: str  # The export name
    output_key: str  # The output key in the template
    is_conditional: bool = False  # Whether the export is conditional
    condition_name: Optional[str] = None  # Name of the condition if conditional
    value: Any = None  # The value being exported (can be Ref, GetAtt, etc.)


@dataclass
class TemplateDependencies:
    """Complete dependency information for a CloudFormation template"""
    imports: List[ImportReference] = field(default_factory=list)
    exports: List[ExportDeclaration] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DependencyNode:
    """Node in the dependency graph representing a CloudFormation stack"""
    stack_name: str
    stack_type: str
    template_path: str
    imports: List[ImportReference] = field(default_factory=list)
    exports: List[ExportDeclaration] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)  # Stack names this stack depends on


@dataclass
class DependencyGraph:
    """Directed graph of stack dependencies"""
    nodes: Dict[str, DependencyNode] = field(default_factory=dict)  # stack_name -> node
    edges: List[Tuple[str, str]] = field(default_factory=list)  # (from_stack, to_stack) edges
    
    def get_dependencies(self, stack_name: str) -> List[str]:
        """Get all stacks that this stack depends on"""
        if stack_name not in self.nodes:
            return []
        return self.nodes[stack_name].depends_on
    
    def get_dependents(self, stack_name: str) -> List[str]:
        """Get all stacks that depend on this stack"""
        dependents = []
        for node_name, node in self.nodes.items():
            if stack_name in node.depends_on:
                dependents.append(node_name)
        return dependents
    
    def add_node(self, node: DependencyNode):
        """Add a node to the graph"""
        self.nodes[node.stack_name] = node
    
    def add_edge(self, from_stack: str, to_stack: str):
        """Add an edge to the graph"""
        edge = (from_stack, to_stack)
        if edge not in self.edges:
            self.edges.append(edge)


@dataclass
class DependencyIssue:
    """Represents a dependency validation issue"""
    severity: IssueSeverity
    issue_type: IssueType
    stack_name: str
    description: str
    suggested_action: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of dependency validation"""
    success: bool
    issues: List[DependencyIssue] = field(default_factory=list)
    dependency_graph: Optional[DependencyGraph] = None
    deployment_order: Optional[List[str]] = None
    summary: str = ""
    
    def add_issue(self, issue: DependencyIssue):
        """Add an issue to the validation result"""
        self.issues.append(issue)
        if issue.severity == IssueSeverity.ERROR:
            self.success = False


@dataclass
class StackDeploymentStep:
    """Single step in deployment plan"""
    step_number: int
    stack_name: str
    stack_type: str
    action: DeploymentAction
    reason: str
    dependencies_satisfied: List[str] = field(default_factory=list)
    will_provide_exports: List[str] = field(default_factory=list)


@dataclass
class DeploymentPlan:
    """Complete deployment plan"""
    steps: List[StackDeploymentStep] = field(default_factory=list)
    total_stacks: int = 0
    estimated_duration_minutes: int = 0
    validation_passed: bool = False
    warnings: List[str] = field(default_factory=list)
    
    def add_step(self, step: StackDeploymentStep):
        """Add a step to the deployment plan"""
        self.steps.append(step)
        self.total_stacks += 1
