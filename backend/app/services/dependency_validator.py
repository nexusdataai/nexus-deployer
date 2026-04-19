"""
Dependency Validator Service
Validates cross-stack dependencies in CloudFormation deployments.

Provides:
- ImportValue reference extraction
- Export name extraction
- Dependency graph building
- Circular dependency detection
- Missing export detection
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Set, Any, Optional, Tuple
from collections import defaultdict

from app.utils.cfn_yaml_loader import CFNTag, extract_intrinsic_functions


logger = logging.getLogger(__name__)


@dataclass
class DependencyGraph:
    """Represents stack dependencies."""
    nodes: Set[str] = field(default_factory=set)  # Stack names
    edges: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))  # stack -> dependencies
    
    def add_node(self, stack_name: str):
        """Add a stack to the graph."""
        self.nodes.add(stack_name)
    
    def add_edge(self, from_stack: str, to_stack: str):
        """Add a dependency edge (from_stack depends on to_stack)."""
        self.nodes.add(from_stack)
        self.nodes.add(to_stack)
        self.edges[from_stack].add(to_stack)
    
    def has_cycle(self) -> Tuple[bool, List[str]]:
        """
        Check for circular dependencies using DFS.
        
        Returns:
            Tuple of (has_cycle: bool, cycle_path: List[str])
        """
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(node: str) -> Tuple[bool, List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.edges.get(node, set()):
                if neighbor not in visited:
                    has_cycle, cycle = dfs(neighbor)
                    if has_cycle:
                        return True, cycle
                elif neighbor in rec_stack:
                    # Found cycle - extract the cycle path
                    cycle_start = path.index(neighbor)
                    cycle_path = path[cycle_start:] + [neighbor]
                    return True, cycle_path
            
            path.pop()
            rec_stack.remove(node)
            return False, []
        
        for node in self.nodes:
            if node not in visited:
                has_cycle, cycle = dfs(node)
                if has_cycle:
                    return True, cycle
        
        return False, []
    
    def get_deployment_order(self) -> List[str]:
        """
        Get topologically sorted deployment order.
        
        Returns:
            List of stack names in deployment order (dependencies first)
            
        Raises:
            ValueError: If graph has cycles
        """
        has_cycle, cycle = self.has_cycle()
        if has_cycle:
            raise ValueError(f"Cannot determine deployment order: circular dependency detected: {' -> '.join(cycle)}")
        
        # Kahn's algorithm for topological sort
        in_degree = {node: 0 for node in self.nodes}
        for node in self.nodes:
            for dep in self.edges.get(node, set()):
                in_degree[node] = in_degree.get(node, 0)  # Ensure node exists
        
        # Count incoming edges
        for node, deps in self.edges.items():
            for dep in deps:
                if dep in in_degree:
                    pass  # dep is a dependency, not dependent
        
        # Reverse the edges to get "depended on by" relationship
        reverse_edges = defaultdict(set)
        for node, deps in self.edges.items():
            for dep in deps:
                reverse_edges[dep].add(node)
        
        # Recalculate in-degree based on reverse edges
        in_degree = {node: 0 for node in self.nodes}
        for node, dependents in reverse_edges.items():
            for dependent in dependents:
                in_degree[dependent] = in_degree.get(dependent, 0) + 1
        
        # Start with nodes that have no dependencies
        queue = [node for node in self.nodes if in_degree.get(node, 0) == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            for dependent in reverse_edges.get(node, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        return result


@dataclass
class MissingExport:
    """Represents a missing export."""
    import_name: str
    importing_stack: str
    suggested_source: Optional[str] = None


@dataclass
class DependencyValidationResult:
    """Result of dependency validation."""
    success: bool
    circular_dependencies: List[List[str]] = field(default_factory=list)
    missing_exports: List[MissingExport] = field(default_factory=list)
    deployment_order: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'circular_dependencies': self.circular_dependencies,
            'missing_exports': [
                {
                    'import_name': m.import_name,
                    'importing_stack': m.importing_stack,
                    'suggested_source': m.suggested_source
                }
                for m in self.missing_exports
            ],
            'deployment_order': self.deployment_order,
            'issues': self.issues
        }


class DependencyValidator:
    """Validates cross-stack dependencies."""
    
    def extract_imports(self, template: Dict[str, Any]) -> List[str]:
        """
        Extract all !ImportValue references from template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            List of import names
        """
        imports = []
        
        def find_imports(obj: Any):
            if isinstance(obj, CFNTag):
                if obj.tag == 'ImportValue':
                    # ImportValue can be a string or another intrinsic function
                    if isinstance(obj.value, str):
                        imports.append(obj.value)
                    elif isinstance(obj.value, CFNTag):
                        # Dynamic import name - can't validate statically
                        pass
                # Recursively check value
                find_imports(obj.value)
            elif isinstance(obj, dict):
                # Also check for long-form Fn::ImportValue
                if 'Fn::ImportValue' in obj:
                    value = obj['Fn::ImportValue']
                    if isinstance(value, str):
                        imports.append(value)
                for value in obj.values():
                    find_imports(value)
            elif isinstance(obj, list):
                for item in obj:
                    find_imports(item)
        
        find_imports(template)
        return imports
    
    def extract_exports(self, template: Dict[str, Any]) -> List[str]:
        """
        Extract all Export names from template outputs.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            List of export names
        """
        exports = []
        
        outputs = template.get('Outputs', {})
        for output_name, output_def in outputs.items():
            if isinstance(output_def, dict):
                export = output_def.get('Export', {})
                if isinstance(export, dict):
                    export_name = export.get('Name')
                    if export_name:
                        if isinstance(export_name, str):
                            exports.append(export_name)
                        elif isinstance(export_name, CFNTag):
                            # Dynamic export name - can't validate statically
                            # But we can try to extract if it's a simple Sub
                            if export_name.tag == 'Sub' and isinstance(export_name.value, str):
                                # Simple substitution - extract the base name
                                # This is a heuristic and may not always work
                                pass
        
        return exports
    
    def build_dependency_graph(
        self,
        templates: Dict[str, Dict[str, Any]]
    ) -> DependencyGraph:
        """
        Build dependency graph from multiple templates.
        
        Args:
            templates: Map of stack name to parsed template
            
        Returns:
            DependencyGraph representing stack dependencies
        """
        graph = DependencyGraph()
        
        # First pass: collect all exports and their source stacks
        export_to_stack: Dict[str, str] = {}
        for stack_name, template in templates.items():
            graph.add_node(stack_name)
            exports = self.extract_exports(template)
            for export_name in exports:
                export_to_stack[export_name] = stack_name
        
        # Second pass: build edges based on imports
        for stack_name, template in templates.items():
            imports = self.extract_imports(template)
            for import_name in imports:
                if import_name in export_to_stack:
                    source_stack = export_to_stack[import_name]
                    if source_stack != stack_name:  # Don't add self-dependency
                        graph.add_edge(stack_name, source_stack)
        
        return graph
    
    def validate_dependencies(
        self,
        templates: Dict[str, Dict[str, Any]],
        existing_exports: Optional[Set[str]] = None
    ) -> DependencyValidationResult:
        """
        Validate all dependencies.
        
        Args:
            templates: Map of stack name to parsed template
            existing_exports: Optional set of existing CloudFormation exports
            
        Returns:
            DependencyValidationResult with validation details
        """
        result = DependencyValidationResult(success=True)
        
        if not templates:
            return result
        
        # Build dependency graph
        graph = self.build_dependency_graph(templates)
        
        # Check for circular dependencies
        has_cycle, cycle = graph.has_cycle()
        if has_cycle:
            result.circular_dependencies.append(cycle)
            result.issues.append(
                f"Circular dependency detected: {' -> '.join(cycle)}"
            )
            result.success = False
        
        # Collect all exports from templates being deployed
        all_exports: Set[str] = set()
        for template in templates.values():
            all_exports.update(self.extract_exports(template))
        
        # Add existing exports if provided
        if existing_exports:
            all_exports.update(existing_exports)
        
        # Check for missing exports
        for stack_name, template in templates.items():
            imports = self.extract_imports(template)
            for import_name in imports:
                if import_name not in all_exports:
                    # Try to suggest which stack might provide it
                    suggested_source = None
                    # Common naming patterns
                    for other_stack in templates.keys():
                        if other_stack.lower() in import_name.lower():
                            suggested_source = other_stack
                            break
                    
                    result.missing_exports.append(MissingExport(
                        import_name=import_name,
                        importing_stack=stack_name,
                        suggested_source=suggested_source
                    ))
        
        if result.missing_exports:
            result.issues.append(
                f"Found {len(result.missing_exports)} missing exports"
            )
            result.success = False
        
        # Get deployment order if no cycles
        if not result.circular_dependencies:
            try:
                result.deployment_order = graph.get_deployment_order()
            except ValueError as e:
                result.issues.append(str(e))
                result.success = False
        
        return result


def get_dependency_validator() -> DependencyValidator:
    """Factory function to get a DependencyValidator instance."""
    return DependencyValidator()
