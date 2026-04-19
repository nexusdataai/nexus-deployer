"""
Cross-Stack Dependency Checker Service
Validates cross-stack dependencies via CloudFormation exports/imports.

Provides:
- Export extraction from templates
- Import extraction from templates
- Dependency graph construction
- Topological sort for deployment order
- Missing export detection

Feature: deployment-prerequisites-verification
Requirements: 2.1, 2.2, 2.3, 2.4, 2.6
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict

from app.utils.cfn_yaml_loader import CFNTag


logger = logging.getLogger(__name__)


@dataclass
class StackExport:
    """Represents a CloudFormation export."""
    stack_name: str
    export_name: str
    output_name: str
    value_type: str = "unknown"  # 'static', 'ref', 'getatt', 'sub'


@dataclass
class StackImport:
    """Represents a CloudFormation import (Fn::ImportValue)."""
    stack_name: str
    import_name: str
    location: str  # Where in the template the import is used


@dataclass
class MissingExport:
    """Represents a missing export dependency."""
    importing_stack: str
    import_name: str
    location: str
    suggested_source: Optional[str] = None


@dataclass
class CrossStackDependencyResult:
    """Result of cross-stack dependency validation."""
    success: bool
    exports: List[StackExport] = field(default_factory=list)
    imports: List[StackImport] = field(default_factory=list)
    missing_exports: List[MissingExport] = field(default_factory=list)
    circular_dependencies: List[List[str]] = field(default_factory=list)
    deployment_order: List[str] = field(default_factory=list)
    dependency_graph: Dict[str, Set[str]] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'exports': [{'stack': e.stack_name, 'export': e.export_name, 'output': e.output_name} for e in self.exports],
            'imports': [{'stack': i.stack_name, 'import': i.import_name, 'location': i.location} for i in self.imports],
            'missing_exports': [{'stack': m.importing_stack, 'import': m.import_name, 'suggested': m.suggested_source} for m in self.missing_exports],
            'circular_dependencies': self.circular_dependencies,
            'deployment_order': self.deployment_order,
            'dependency_graph': {k: list(v) for k, v in self.dependency_graph.items()},
            'issues': self.issues
        }


class CrossStackDependencyChecker:
    """Validates cross-stack dependencies via CloudFormation exports/imports."""
    
    def extract_exports(
        self,
        template: Dict[str, Any],
        stack_name: str = ""
    ) -> List[StackExport]:
        """
        Extract all exports from a template's Outputs section.
        
        Args:
            template: Parsed CloudFormation template
            stack_name: Name of the stack for tracking
            
        Returns:
            List of StackExport objects
        """
        exports = []
        outputs = template.get('Outputs', {})
        
        if not outputs or not isinstance(outputs, dict):
            return exports
        
        for output_name, output_def in outputs.items():
            if not isinstance(output_def, dict):
                continue
            
            export = output_def.get('Export')
            if not export:
                continue
            
            export_name = None
            
            # Handle Export.Name which can be string or intrinsic function
            if isinstance(export, dict):
                name_value = export.get('Name')
                if isinstance(name_value, str):
                    export_name = name_value
                elif isinstance(name_value, CFNTag):
                    # Dynamic export name - extract what we can
                    if name_value.tag == 'Sub':
                        export_name = f"<dynamic:{name_value.value}>"
                    elif name_value.tag == 'Ref':
                        export_name = f"<ref:{name_value.value}>"
                    else:
                        export_name = f"<{name_value.tag}>"
            
            if export_name:
                # Determine value type
                value = output_def.get('Value')
                value_type = 'static'
                if isinstance(value, CFNTag):
                    value_type = value.tag.lower()
                
                exports.append(StackExport(
                    stack_name=stack_name,
                    export_name=export_name,
                    output_name=output_name,
                    value_type=value_type
                ))
        
        return exports
    
    def extract_imports(
        self,
        template: Dict[str, Any],
        stack_name: str = ""
    ) -> List[StackImport]:
        """
        Extract all Fn::ImportValue references from a template.
        
        Args:
            template: Parsed CloudFormation template
            stack_name: Name of the stack for tracking
            
        Returns:
            List of StackImport objects
        """
        imports = []
        
        def find_imports(obj: Any, path: str = ""):
            """Recursively find ImportValue references."""
            if isinstance(obj, CFNTag):
                if obj.tag == 'ImportValue':
                    import_name = None
                    if isinstance(obj.value, str):
                        import_name = obj.value
                    elif isinstance(obj.value, CFNTag):
                        if obj.value.tag == 'Sub':
                            import_name = f"<dynamic:{obj.value.value}>"
                        else:
                            import_name = f"<{obj.value.tag}>"
                    
                    if import_name:
                        imports.append(StackImport(
                            stack_name=stack_name,
                            import_name=import_name,
                            location=path
                        ))
                else:
                    find_imports(obj.value, f"{path}.{obj.tag}")
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    find_imports(value, f"{path}.{key}" if path else key)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_imports(item, f"{path}[{i}]")
        
        find_imports(template)
        return imports
    
    def build_dependency_graph(
        self,
        templates: Dict[str, Dict[str, Any]]
    ) -> Tuple[Dict[str, Set[str]], Dict[str, List[StackExport]]]:
        """
        Build a dependency graph from multiple templates.
        
        Args:
            templates: Map of stack name to parsed template
            
        Returns:
            Tuple of (dependency_graph, export_map)
            - dependency_graph: stack -> set of stacks it depends on
            - export_map: export_name -> list of stacks that export it
        """
        dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        export_map: Dict[str, List[StackExport]] = defaultdict(list)
        
        # First pass: collect all exports
        for stack_name, template in templates.items():
            exports = self.extract_exports(template, stack_name)
            for export in exports:
                if not export.export_name.startswith('<'):  # Skip dynamic exports
                    export_map[export.export_name].append(export)
        
        # Second pass: find imports and build dependencies
        for stack_name, template in templates.items():
            imports = self.extract_imports(template, stack_name)
            for imp in imports:
                if imp.import_name.startswith('<'):
                    continue  # Skip dynamic imports
                
                # Find which stack exports this
                if imp.import_name in export_map:
                    for export in export_map[imp.import_name]:
                        if export.stack_name != stack_name:
                            dependency_graph[stack_name].add(export.stack_name)
        
        return dict(dependency_graph), dict(export_map)

    def detect_circular_dependencies(
        self,
        dependency_graph: Dict[str, Set[str]]
    ) -> List[List[str]]:
        """
        Detect circular dependencies in the dependency graph.
        
        Args:
            dependency_graph: stack -> set of stacks it depends on
            
        Returns:
            List of cycles (each cycle is a list of stack names)
        """
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]) -> bool:
            """DFS to detect cycles."""
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in dependency_graph.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor, path):
                        return True
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
                    return True
            
            path.pop()
            rec_stack.remove(node)
            return False
        
        for node in dependency_graph:
            if node not in visited:
                dfs(node, [])
        
        return cycles
    
    def get_deployment_order(
        self,
        dependency_graph: Dict[str, Set[str]],
        all_stacks: Set[str]
    ) -> List[str]:
        """
        Get topologically sorted deployment order.
        
        Args:
            dependency_graph: stack -> set of stacks it depends on
            all_stacks: Set of all stack names
            
        Returns:
            List of stack names in deployment order (dependencies first)
        """
        # Kahn's algorithm for topological sort
        in_degree: Dict[str, int] = {stack: 0 for stack in all_stacks}
        
        for stack, deps in dependency_graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[stack] = in_degree.get(stack, 0) + 1
        
        # Start with stacks that have no dependencies
        queue = [stack for stack, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            # Sort for deterministic order
            queue.sort()
            current = queue.pop(0)
            result.append(current)
            
            # Reduce in-degree for dependent stacks
            for stack, deps in dependency_graph.items():
                if current in deps:
                    in_degree[stack] -= 1
                    if in_degree[stack] == 0:
                        queue.append(stack)
        
        # Add any remaining stacks (might be in cycles)
        for stack in all_stacks:
            if stack not in result:
                result.append(stack)
        
        return result
    
    def check_dependencies(
        self,
        templates: Dict[str, Dict[str, Any]],
        existing_exports: Optional[Set[str]] = None
    ) -> CrossStackDependencyResult:
        """
        Check all cross-stack dependencies.
        
        Args:
            templates: Map of stack name to parsed template
            existing_exports: Optional set of exports already in AWS
            
        Returns:
            CrossStackDependencyResult with all dependency information
        """
        result = CrossStackDependencyResult(success=True)
        existing_exports = existing_exports or set()
        
        # Extract all exports and imports
        all_exports: Dict[str, StackExport] = {}
        
        for stack_name, template in templates.items():
            exports = self.extract_exports(template, stack_name)
            result.exports.extend(exports)
            for export in exports:
                if not export.export_name.startswith('<'):
                    all_exports[export.export_name] = export
            
            imports = self.extract_imports(template, stack_name)
            result.imports.extend(imports)
        
        # Build dependency graph
        dependency_graph, _ = self.build_dependency_graph(templates)
        result.dependency_graph = dependency_graph
        
        # Check for missing exports
        available_exports = set(all_exports.keys()) | existing_exports
        
        for imp in result.imports:
            if imp.import_name.startswith('<'):
                continue  # Skip dynamic imports
            
            if imp.import_name not in available_exports:
                # Find suggested source
                suggested = None
                for export_name, export in all_exports.items():
                    if imp.import_name in export_name or export_name in imp.import_name:
                        suggested = export.stack_name
                        break
                
                result.missing_exports.append(MissingExport(
                    importing_stack=imp.stack_name,
                    import_name=imp.import_name,
                    location=imp.location,
                    suggested_source=suggested
                ))
        
        # Detect circular dependencies
        cycles = self.detect_circular_dependencies(dependency_graph)
        result.circular_dependencies = cycles
        
        # Get deployment order
        all_stacks = set(templates.keys())
        result.deployment_order = self.get_deployment_order(dependency_graph, all_stacks)
        
        # Determine success
        if result.missing_exports:
            result.success = False
            result.issues.append(f"Found {len(result.missing_exports)} missing exports")
        
        if result.circular_dependencies:
            result.success = False
            result.issues.append(f"Found {len(result.circular_dependencies)} circular dependencies")
        
        return result
    
    async def get_existing_exports(
        self,
        region: str,
        credentials: Optional[Dict[str, str]] = None
    ) -> Set[str]:
        """
        Query CloudFormation for existing exports.
        
        Args:
            region: AWS region
            credentials: Optional AWS credentials
            
        Returns:
            Set of export names
        """
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError
            
            session_kwargs = {}
            if credentials:
                session_kwargs['aws_access_key_id'] = credentials.get('aws_access_key_id')
                session_kwargs['aws_secret_access_key'] = credentials.get('aws_secret_access_key')
                if credentials.get('aws_session_token'):
                    session_kwargs['aws_session_token'] = credentials.get('aws_session_token')
            
            session = boto3.Session(**session_kwargs)
            cfn = session.client('cloudformation', region_name=region)
            
            exports = set()
            paginator = cfn.get_paginator('list_exports')
            
            for page in paginator.paginate():
                for export in page.get('Exports', []):
                    exports.add(export.get('Name', ''))
            
            return exports
            
        except (NoCredentialsError, ClientError) as e:
            logger.warning(f"Could not fetch existing exports: {e}")
            return set()
        except Exception as e:
            logger.warning(f"Error fetching exports: {e}")
            return set()


def get_cross_stack_dependency_checker() -> CrossStackDependencyChecker:
    """Factory function to get a CrossStackDependencyChecker instance."""
    return CrossStackDependencyChecker()
