"""
Stack Dependency Analyzer
Analyzes CloudFormation templates to extract dependency information
"""
import yaml
import json
import re
from typing import Dict, Any, List, Optional, Tuple, Set
from pathlib import Path

from app.models.dependency import (
    TemplateDependencies,
    ImportReference,
    ExportDeclaration
)


class StackDependencyAnalyzer:
    """Analyzes CloudFormation templates for dependencies"""
    
    # YAML short-form intrinsic function tags
    YAML_SHORT_FORMS = {
        '!ImportValue', '!Sub', '!Ref', '!GetAtt', '!If', '!Condition',
        '!And', '!Or', '!Not', '!Equals', '!Join', '!Select', '!Split',
        '!Base64', '!Cidr', '!FindInMap', '!GetAZs', '!Transform'
    }
    
    def analyze_template(self, template: Dict[str, Any]) -> TemplateDependencies:
        """
        Analyze a CloudFormation template
        
        Args:
            template: Parsed CloudFormation template dict
            
        Returns:
            TemplateDependencies containing imports, exports, and conditions
        """
        dependencies = TemplateDependencies()
        
        # Extract imports from the entire template (with condition tracking)
        dependencies.imports = self.extract_imports(template)
        
        # Extract exports from Outputs section
        dependencies.exports = self.extract_exports(template)
        
        # Extract conditions
        dependencies.conditions = self.extract_conditions(template)
        
        # Extract parameters
        dependencies.parameters = template.get('Parameters', {})
        
        return dependencies
    
    def extract_imports(self, template: Dict[str, Any], path: str = "",
                       current_condition: Optional[str] = None) -> List[ImportReference]:
        """
        Extract all Fn::ImportValue references from a template
        
        Handles:
        - Direct Fn::ImportValue references
        - Short-form !ImportValue syntax
        - Nested intrinsic functions (Fn::If, Fn::Sub containing imports)
        - Conditional imports within Fn::If blocks
        
        Args:
            template: Template dict or sub-dict to search
            path: Current path in template (for tracking location)
            current_condition: Name of condition if inside Fn::If block
            
        Returns:
            List of ImportReference objects
        """
        imports = []
        
        if isinstance(template, dict):
            # Check for Fn::If - track condition context for nested imports
            if 'Fn::If' in template:
                if_value = template['Fn::If']
                if isinstance(if_value, list) and len(if_value) >= 2:
                    condition_name = if_value[0] if isinstance(if_value[0], str) else None
                    # Process true branch with condition context
                    if len(if_value) > 1:
                        imports.extend(self.extract_imports(
                            if_value[1], f"{path}.Fn::If[1]", condition_name
                        ))
                    # Process false branch with negated condition context
                    if len(if_value) > 2:
                        imports.extend(self.extract_imports(
                            if_value[2], f"{path}.Fn::If[2]", f"NOT_{condition_name}" if condition_name else None
                        ))
                    return imports  # Don't recurse further for Fn::If
            
            # Check for Fn::ImportValue in long form
            if 'Fn::ImportValue' in template:
                import_value = template['Fn::ImportValue']
                export_names = self._resolve_import_value(import_value)
                for export_name in export_names:
                    imports.append(ImportReference(
                        export_name=export_name,
                        resource_path=path,
                        is_conditional=current_condition is not None,
                        condition_name=current_condition
                    ))
            
            # Check for Fn::Sub which may contain ${ImportValue} references
            if 'Fn::Sub' in template:
                sub_value = template['Fn::Sub']
                sub_imports = self._extract_imports_from_sub(sub_value, path, current_condition)
                imports.extend(sub_imports)
            
            # Recursively search all dict values (except already processed keys)
            for key, value in template.items():
                if key in ('Fn::ImportValue', 'Fn::If', 'Fn::Sub'):
                    continue  # Already processed
                new_path = f"{path}.{key}" if path else key
                imports.extend(self.extract_imports(value, new_path, current_condition))
                
        elif isinstance(template, list):
            # Recursively search all list items
            for i, item in enumerate(template):
                new_path = f"{path}[{i}]"
                imports.extend(self.extract_imports(item, new_path, current_condition))
        
        return imports
    
    def _extract_imports_from_sub(self, sub_value: Any, path: str,
                                  current_condition: Optional[str]) -> List[ImportReference]:
        """
        Extract ImportValue references from Fn::Sub expressions
        
        Fn::Sub can contain ${!ImportValue ExportName} syntax
        
        Args:
            sub_value: The value of Fn::Sub (string or [string, dict])
            path: Current path in template
            current_condition: Current condition context
            
        Returns:
            List of ImportReference objects found in Sub expression
        """
        imports = []
        
        # Get the template string
        template_str = ""
        variable_map = {}
        
        if isinstance(sub_value, str):
            template_str = sub_value
        elif isinstance(sub_value, list) and len(sub_value) >= 1:
            template_str = sub_value[0] if isinstance(sub_value[0], str) else ""
            if len(sub_value) > 1 and isinstance(sub_value[1], dict):
                variable_map = sub_value[1]
        
        # Look for ${!ImportValue ExportName} pattern in template string
        # Note: ${!Literal} is escape syntax, but ${!ImportValue X} is valid
        import_pattern = r'\$\{!ImportValue\s+([^}]+)\}'
        matches = re.findall(import_pattern, template_str)
        
        for export_name in matches:
            export_name = export_name.strip()
            imports.append(ImportReference(
                export_name=export_name,
                resource_path=f"{path}.Fn::Sub",
                is_conditional=current_condition is not None,
                condition_name=current_condition
            ))
        
        # Also check variable map for ImportValue references
        for var_name, var_value in variable_map.items():
            if isinstance(var_value, dict):
                if 'Fn::ImportValue' in var_value:
                    export_names = self._resolve_import_value(var_value['Fn::ImportValue'])
                    for export_name in export_names:
                        imports.append(ImportReference(
                            export_name=export_name,
                            resource_path=f"{path}.Fn::Sub.{var_name}",
                            is_conditional=current_condition is not None,
                            condition_name=current_condition
                        ))
        
        return imports
    
    def _resolve_import_value(self, import_value: Any) -> List[str]:
        """
        Resolve the actual export name(s) from an import value
        
        Handles:
        - Direct string values
        - Fn::Sub expressions
        - Fn::If expressions (returns both possible values)
        - Fn::Join expressions
        
        Args:
            import_value: The value from Fn::ImportValue
            
        Returns:
            List of export name strings (may be empty if cannot be resolved)
        """
        if isinstance(import_value, str):
            return [import_value]
        
        if isinstance(import_value, dict):
            # Handle Fn::Sub
            if 'Fn::Sub' in import_value:
                sub_value = import_value['Fn::Sub']
                if isinstance(sub_value, str):
                    # For simple substitutions, return the template
                    # Variables like ${AWS::StackName} will be in the string
                    return [sub_value]
                elif isinstance(sub_value, list) and len(sub_value) > 0:
                    return [sub_value[0]] if isinstance(sub_value[0], str) else []
            
            # Handle Fn::If - return both possible values
            if 'Fn::If' in import_value:
                if_value = import_value['Fn::If']
                if isinstance(if_value, list):
                    results = []
                    # True branch
                    if len(if_value) > 1:
                        results.extend(self._resolve_import_value(if_value[1]))
                    # False branch
                    if len(if_value) > 2:
                        results.extend(self._resolve_import_value(if_value[2]))
                    return results
            
            # Handle Fn::Join
            if 'Fn::Join' in import_value:
                join_value = import_value['Fn::Join']
                if isinstance(join_value, list) and len(join_value) == 2:
                    delimiter = join_value[0]
                    parts = join_value[1]
                    if isinstance(parts, list):
                        # Try to resolve all parts that are strings
                        resolved_parts = []
                        for part in parts:
                            if isinstance(part, str):
                                resolved_parts.append(part)
                            elif isinstance(part, dict):
                                # Could be Ref, GetAtt, etc. - use placeholder
                                resolved_parts.append('${...}')
                        if resolved_parts:
                            return [delimiter.join(resolved_parts)]
            
            # Handle Fn::Ref (common in export names)
            if 'Ref' in import_value:
                ref_value = import_value['Ref']
                if isinstance(ref_value, str):
                    return [f"${{Ref:{ref_value}}}"]
        
        return []
    
    def extract_exports(self, template: Dict[str, Any]) -> List[ExportDeclaration]:
        """
        Extract all Export declarations from Outputs section
        
        Args:
            template: CloudFormation template dict
            
        Returns:
            List of ExportDeclaration objects
        """
        exports = []
        outputs = template.get('Outputs', {})
        
        for output_key, output_value in outputs.items():
            if not isinstance(output_value, dict):
                continue
            
            export_section = output_value.get('Export')
            if not export_section:
                continue
            
            # Get export name
            export_name = export_section.get('Name')
            if not export_name:
                continue
            
            # Resolve export name if it's a function
            resolved_name = self._resolve_export_name(export_name)
            
            # Check if output is conditional
            condition_name = output_value.get('Condition')
            is_conditional = condition_name is not None
            
            # Get the value being exported
            value = output_value.get('Value')
            
            exports.append(ExportDeclaration(
                export_name=resolved_name or str(export_name),
                output_key=output_key,
                is_conditional=is_conditional,
                condition_name=condition_name,
                value=value
            ))
        
        return exports
    
    def _resolve_export_name(self, export_name: Any) -> Optional[str]:
        """
        Resolve the actual export name from an export value
        
        Args:
            export_name: The Name value from Export
            
        Returns:
            Export name string or None if cannot be resolved
        """
        if isinstance(export_name, str):
            return export_name
        
        # Handle Fn::Sub
        if isinstance(export_name, dict):
            if 'Fn::Sub' in export_name:
                sub_value = export_name['Fn::Sub']
                if isinstance(sub_value, str):
                    return sub_value
                elif isinstance(sub_value, list) and len(sub_value) > 0:
                    return sub_value[0] if isinstance(sub_value[0], str) else None
            
            # Handle Fn::Join
            if 'Fn::Join' in export_name:
                join_value = export_name['Fn::Join']
                if isinstance(join_value, list) and len(join_value) == 2:
                    delimiter = join_value[0]
                    parts = join_value[1]
                    if isinstance(parts, list):
                        resolved_parts = []
                        for part in parts:
                            if isinstance(part, str):
                                resolved_parts.append(part)
                            elif isinstance(part, dict):
                                resolved_parts.append('${...}')
                        if resolved_parts:
                            return delimiter.join(resolved_parts)
        
        return None
    
    def extract_conditions(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract condition definitions from template
        
        Args:
            template: CloudFormation template dict
            
        Returns:
            Dict of condition name to condition definition
        """
        return template.get('Conditions', {})
    
    def is_conditional_export(self, export: ExportDeclaration, 
                             template: Dict[str, Any]) -> Optional[str]:
        """
        Check if an export is conditional and return condition name
        
        Args:
            export: ExportDeclaration to check
            template: CloudFormation template dict
            
        Returns:
            Condition name if conditional, None otherwise
        """
        outputs = template.get('Outputs', {})
        output = outputs.get(export.output_key, {})
        return output.get('Condition')
    
    def load_template_file(self, template_path: str) -> Dict[str, Any]:
        """
        Load a CloudFormation template from file
        
        Handles both YAML and JSON formats, including CloudFormation
        short-form intrinsic functions (!Ref, !Sub, !ImportValue, etc.)
        
        Args:
            template_path: Path to template file (YAML or JSON)
            
        Returns:
            Parsed template dict
        """
        path = Path(template_path)
        
        with open(path, 'r') as f:
            content = f.read()
        
        # Try YAML first with CloudFormation-aware loader
        try:
            return self._load_yaml_with_cfn_tags(content)
        except yaml.YAMLError:
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse template as YAML or JSON: {e}")
    
    def _load_yaml_with_cfn_tags(self, content: str) -> Dict[str, Any]:
        """
        Load YAML content with CloudFormation intrinsic function tag support
        
        Converts short-form tags like !Ref, !Sub, !ImportValue to their
        long-form equivalents (Fn::Ref, Fn::Sub, Fn::ImportValue)
        
        Args:
            content: YAML content string
            
        Returns:
            Parsed template dict
        """
        # Create a custom loader that handles CloudFormation tags
        class CFNLoader(yaml.SafeLoader):
            pass
        
        # Define constructors for CloudFormation intrinsic functions
        def construct_cfn_tag(loader, tag_suffix, node):
            """Generic constructor for CloudFormation tags"""
            if isinstance(node, yaml.ScalarNode):
                value = loader.construct_scalar(node)
            elif isinstance(node, yaml.SequenceNode):
                value = loader.construct_sequence(node)
            elif isinstance(node, yaml.MappingNode):
                value = loader.construct_mapping(node)
            else:
                value = None
            
            # Map short-form to long-form
            tag_map = {
                'Ref': 'Ref',
                'Sub': 'Fn::Sub',
                'ImportValue': 'Fn::ImportValue',
                'GetAtt': 'Fn::GetAtt',
                'If': 'Fn::If',
                'Condition': 'Condition',
                'And': 'Fn::And',
                'Or': 'Fn::Or',
                'Not': 'Fn::Not',
                'Equals': 'Fn::Equals',
                'Join': 'Fn::Join',
                'Select': 'Fn::Select',
                'Split': 'Fn::Split',
                'Base64': 'Fn::Base64',
                'Cidr': 'Fn::Cidr',
                'FindInMap': 'Fn::FindInMap',
                'GetAZs': 'Fn::GetAZs',
                'Transform': 'Fn::Transform',
            }
            
            long_form = tag_map.get(tag_suffix, f'Fn::{tag_suffix}')
            return {long_form: value}
        
        # Register constructors for all CloudFormation tags
        cfn_tags = [
            'Ref', 'Sub', 'ImportValue', 'GetAtt', 'If', 'Condition',
            'And', 'Or', 'Not', 'Equals', 'Join', 'Select', 'Split',
            'Base64', 'Cidr', 'FindInMap', 'GetAZs', 'Transform'
        ]
        
        for tag in cfn_tags:
            CFNLoader.add_constructor(
                f'!{tag}',
                lambda loader, node, t=tag: construct_cfn_tag(loader, t, node)
            )
        
        return yaml.load(content, Loader=CFNLoader)
