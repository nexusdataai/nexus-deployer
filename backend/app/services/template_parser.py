"""
CloudFormation Template Parser
Parses CloudFormation templates to extract resource definitions
"""
import yaml
import json
import re
from typing import Dict, List, Any, Optional
from app.models.validation import ResourceDefinition


class TemplateParser:
    """Parser for CloudFormation templates"""
    
    def __init__(self):
        """Initialize template parser"""
        # Add custom YAML constructors for CloudFormation intrinsic functions
        self._setup_yaml_constructors()
    
    def _setup_yaml_constructors(self):
        """Setup YAML constructors for CloudFormation intrinsic functions"""
        # Add constructors for CloudFormation tags
        yaml.SafeLoader.add_constructor('!Ref', self._yaml_ref_constructor)
        yaml.SafeLoader.add_constructor('!Sub', self._yaml_sub_constructor)
        yaml.SafeLoader.add_constructor('!GetAtt', self._yaml_getatt_constructor)
        yaml.SafeLoader.add_constructor('!Join', self._yaml_join_constructor)
        yaml.SafeLoader.add_constructor('!Select', self._yaml_select_constructor)
        yaml.SafeLoader.add_constructor('!GetAZs', self._yaml_getazs_constructor)
        yaml.SafeLoader.add_constructor('!Base64', self._yaml_base64_constructor)
        yaml.SafeLoader.add_constructor('!Split', self._yaml_split_constructor)
        yaml.SafeLoader.add_constructor('!FindInMap', self._yaml_findinmap_constructor)
        yaml.SafeLoader.add_constructor('!ImportValue', self._yaml_importvalue_constructor)
        # Condition functions
        yaml.SafeLoader.add_constructor('!Equals', self._yaml_equals_constructor)
        yaml.SafeLoader.add_constructor('!If', self._yaml_if_constructor)
        yaml.SafeLoader.add_constructor('!Not', self._yaml_not_constructor)
        yaml.SafeLoader.add_constructor('!And', self._yaml_and_constructor)
        yaml.SafeLoader.add_constructor('!Or', self._yaml_or_constructor)
    
    @staticmethod
    def _yaml_ref_constructor(loader, node):
        """Constructor for !Ref tag"""
        value = loader.construct_scalar(node)
        return {'Ref': value}
    
    @staticmethod
    def _yaml_sub_constructor(loader, node):
        """Constructor for !Sub tag"""
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
            return {'Fn::Sub': value}
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node)
            return {'Fn::Sub': value}
        return {'Fn::Sub': loader.construct_object(node)}
    
    @staticmethod
    def _yaml_getatt_constructor(loader, node):
        """Constructor for !GetAtt tag"""
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
            # Split on dot for GetAtt
            parts = value.split('.', 1)
            return {'Fn::GetAtt': parts if len(parts) == 2 else [value, '']}
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node)
            return {'Fn::GetAtt': value}
        return {'Fn::GetAtt': loader.construct_object(node)}
    
    @staticmethod
    def _yaml_join_constructor(loader, node):
        """Constructor for !Join tag"""
        value = loader.construct_sequence(node)
        return {'Fn::Join': value}
    
    @staticmethod
    def _yaml_select_constructor(loader, node):
        """Constructor for !Select tag"""
        value = loader.construct_sequence(node)
        return {'Fn::Select': value}
    
    @staticmethod
    def _yaml_getazs_constructor(loader, node):
        """Constructor for !GetAZs tag"""
        value = loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else loader.construct_object(node)
        return {'Fn::GetAZs': value}
    
    @staticmethod
    def _yaml_base64_constructor(loader, node):
        """Constructor for !Base64 tag"""
        value = loader.construct_object(node)
        return {'Fn::Base64': value}
    
    @staticmethod
    def _yaml_split_constructor(loader, node):
        """Constructor for !Split tag"""
        value = loader.construct_sequence(node)
        return {'Fn::Split': value}
    
    @staticmethod
    def _yaml_findinmap_constructor(loader, node):
        """Constructor for !FindInMap tag"""
        value = loader.construct_sequence(node)
        return {'Fn::FindInMap': value}
    
    @staticmethod
    def _yaml_importvalue_constructor(loader, node):
        """Constructor for !ImportValue tag"""
        value = loader.construct_object(node)
        return {'Fn::ImportValue': value}
    
    @staticmethod
    def _yaml_equals_constructor(loader, node):
        """Constructor for !Equals tag"""
        value = loader.construct_sequence(node)
        return {'Fn::Equals': value}
    
    @staticmethod
    def _yaml_if_constructor(loader, node):
        """Constructor for !If tag"""
        value = loader.construct_sequence(node)
        return {'Fn::If': value}
    
    @staticmethod
    def _yaml_not_constructor(loader, node):
        """Constructor for !Not tag"""
        value = loader.construct_sequence(node)
        return {'Fn::Not': value}
    
    @staticmethod
    def _yaml_and_constructor(loader, node):
        """Constructor for !And tag"""
        value = loader.construct_sequence(node)
        return {'Fn::And': value}
    
    @staticmethod
    def _yaml_or_constructor(loader, node):
        """Constructor for !Or tag"""
        value = loader.construct_sequence(node)
        return {'Fn::Or': value}
    
    def parse_template(
        self,
        template_body: str,
        parameters: Optional[List[Dict[str, str]]] = None
    ) -> List[ResourceDefinition]:
        """
        Parse CloudFormation template and extract resource definitions
        
        Args:
            template_body: YAML/JSON template content
            parameters: Parameter values for resolution (list of dicts with ParameterKey and ParameterValue)
            
        Returns:
            List of ResourceDefinition objects
            
        Raises:
            ValueError: If template parsing fails
        """
        try:
            # Convert parameters list to dict for easier lookup
            param_dict = {}
            if parameters:
                for param in parameters:
                    param_dict[param.get('ParameterKey', '')] = param.get('ParameterValue', '')
            
            # Try to parse as YAML first (YAML is a superset of JSON)
            try:
                template = yaml.safe_load(template_body)
            except yaml.YAMLError as yaml_error:
                # If YAML parsing fails, try JSON
                try:
                    template = json.loads(template_body)
                except json.JSONDecodeError as json_error:
                    raise ValueError(f"Failed to parse template as YAML or JSON. YAML error: {str(yaml_error)}, JSON error: {str(json_error)}")
            
            if not isinstance(template, dict):
                raise ValueError("Template must be a dictionary")
            
            # Extract resources section
            resources = template.get('Resources', {})
            if not resources:
                return []
            
            # Parse each resource
            resource_definitions = []
            for logical_id, resource_data in resources.items():
                if not isinstance(resource_data, dict):
                    continue
                
                resource_type = resource_data.get('Type', '')
                properties = resource_data.get('Properties', {})
                deletion_policy = resource_data.get('DeletionPolicy')
                
                # Resolve parameter references in properties
                resolved_properties = self._resolve_value(properties, param_dict, template)
                
                resource_def = ResourceDefinition(
                    logical_id=logical_id,
                    resource_type=resource_type,
                    properties=resolved_properties,
                    deletion_policy=deletion_policy
                )
                resource_definitions.append(resource_def)
            
            return resource_definitions
            
        except Exception as e:
            raise ValueError(f"Template parsing error: {str(e)}")
    
    def resolve_parameters(
        self,
        value: Any,
        parameters: Dict[str, str]
    ) -> Any:
        """
        Resolve parameter references in template values
        
        Args:
            value: Value to resolve (can be string, dict, list, etc.)
            parameters: Parameter key-value pairs
            
        Returns:
            Resolved value
        """
        return self._resolve_value(value, parameters, {})
    
    def _resolve_value(
        self,
        value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> Any:
        """
        Recursively resolve parameter references and intrinsic functions
        
        Args:
            value: Value to resolve
            parameters: Parameter key-value pairs
            template: Full template for resolving references
            
        Returns:
            Resolved value
        """
        # Handle None
        if value is None:
            return None
        
        # Handle dictionaries (may contain intrinsic functions)
        if isinstance(value, dict):
            # Check for intrinsic functions
            if 'Ref' in value:
                return self._resolve_ref(value['Ref'], parameters, template)
            elif 'Fn::Sub' in value:
                return self._resolve_sub(value['Fn::Sub'], parameters, template)
            elif 'Fn::GetAtt' in value:
                return self._resolve_get_att(value['Fn::GetAtt'], parameters, template)
            elif 'Fn::Join' in value:
                return self._resolve_join(value['Fn::Join'], parameters, template)
            elif 'Fn::Select' in value:
                return self._resolve_select(value['Fn::Select'], parameters, template)
            elif 'Fn::Equals' in value:
                return self._resolve_equals(value['Fn::Equals'], parameters, template)
            elif 'Fn::If' in value:
                return self._resolve_if(value['Fn::If'], parameters, template)
            elif 'Fn::Not' in value:
                return self._resolve_not(value['Fn::Not'], parameters, template)
            elif 'Fn::And' in value:
                return self._resolve_and(value['Fn::And'], parameters, template)
            elif 'Fn::Or' in value:
                return self._resolve_or(value['Fn::Or'], parameters, template)
            else:
                # Recursively resolve all values in the dict
                return {k: self._resolve_value(v, parameters, template) for k, v in value.items()}
        
        # Handle lists
        elif isinstance(value, list):
            return [self._resolve_value(item, parameters, template) for item in value]
        
        # Handle strings and other primitives
        else:
            return value
    
    def _resolve_ref(
        self,
        ref: str,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> Any:
        """
        Resolve Ref intrinsic function
        
        Args:
            ref: Reference name (parameter or resource logical ID)
            parameters: Parameter values
            template: Full template
            
        Returns:
            Resolved value or the reference string if not found
        """
        # Check if it's a parameter reference
        if ref in parameters:
            return parameters[ref]
        
        # Check for pseudo parameters
        pseudo_params = {
            'AWS::AccountId': '123456789012',  # Placeholder
            'AWS::Region': 'us-east-1',  # Placeholder
            'AWS::StackName': 'placeholder-stack',  # Placeholder
            'AWS::StackId': 'placeholder-stack-id',  # Placeholder
            'AWS::NoValue': None,
        }
        if ref in pseudo_params:
            return pseudo_params[ref]
        
        # If it's a resource reference, we can't fully resolve it
        # Return a placeholder that includes the logical ID
        return f"{{Ref:{ref}}}"
    
    def _resolve_sub(
        self,
        sub_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> str:
        """
        Resolve Fn::Sub intrinsic function
        
        Args:
            sub_value: Sub function value (string or [string, dict])
            parameters: Parameter values
            template: Full template
            
        Returns:
            Resolved string
        """
        # Fn::Sub can be a string or [string, dict]
        if isinstance(sub_value, str):
            template_string = sub_value
            variables = {}
        elif isinstance(sub_value, list) and len(sub_value) >= 1:
            template_string = sub_value[0]
            variables = sub_value[1] if len(sub_value) > 1 else {}
        else:
            return str(sub_value)
        
        # Replace ${VarName} with values
        def replace_var(match):
            var_name = match.group(1)
            
            # Check explicit variables first
            if var_name in variables:
                var_value = variables[var_name]
                return str(self._resolve_value(var_value, parameters, template))
            
            # Check parameters
            if var_name in parameters:
                return parameters[var_name]
            
            # Check pseudo parameters
            pseudo_params = {
                'AWS::AccountId': '123456789012',
                'AWS::Region': 'us-east-1',
                'AWS::StackName': 'placeholder-stack',
                'AWS::StackId': 'placeholder-stack-id',
            }
            if var_name in pseudo_params:
                return pseudo_params[var_name]
            
            # If not found, keep the placeholder
            return f"${{{var_name}}}"
        
        # Replace all ${VarName} patterns
        result = re.sub(r'\$\{([^}]+)\}', replace_var, template_string)
        return result
    
    def _resolve_get_att(
        self,
        get_att: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> str:
        """
        Resolve Fn::GetAtt intrinsic function
        
        Args:
            get_att: GetAtt value (list of [LogicalId, AttributeName])
            parameters: Parameter values
            template: Full template
            
        Returns:
            Placeholder string (cannot fully resolve without actual resources)
        """
        if isinstance(get_att, list) and len(get_att) >= 2:
            logical_id = get_att[0]
            attribute = get_att[1]
            return f"{{GetAtt:{logical_id}.{attribute}}}"
        return str(get_att)
    
    def _resolve_join(
        self,
        join_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> str:
        """
        Resolve Fn::Join intrinsic function
        
        Args:
            join_value: Join value (list of [delimiter, list_of_values])
            parameters: Parameter values
            template: Full template
            
        Returns:
            Joined string
        """
        if isinstance(join_value, list) and len(join_value) >= 2:
            delimiter = join_value[0]
            values = join_value[1]
            
            if isinstance(values, list):
                resolved_values = [
                    str(self._resolve_value(v, parameters, template))
                    for v in values
                ]
                return delimiter.join(resolved_values)
        
        return str(join_value)
    
    def _resolve_select(
        self,
        select_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> Any:
        """
        Resolve Fn::Select intrinsic function
        
        Args:
            select_value: Select value (list of [index, list_of_values])
            parameters: Parameter values
            template: Full template
            
        Returns:
            Selected value
        """
        if isinstance(select_value, list) and len(select_value) >= 2:
            index = select_value[0]
            values = select_value[1]
            
            # Resolve the index if it's a reference
            resolved_index = self._resolve_value(index, parameters, template)
            
            # Resolve the list
            resolved_values = self._resolve_value(values, parameters, template)
            
            if isinstance(resolved_values, list) and isinstance(resolved_index, int):
                if 0 <= resolved_index < len(resolved_values):
                    return resolved_values[resolved_index]
        
        return str(select_value)
    
    def _resolve_equals(
        self,
        equals_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> bool:
        """
        Resolve Fn::Equals intrinsic function
        
        Args:
            equals_value: Equals value (list of [value1, value2])
            parameters: Parameter values
            template: Full template
            
        Returns:
            Boolean result of comparison
        """
        if isinstance(equals_value, list) and len(equals_value) >= 2:
            val1 = self._resolve_value(equals_value[0], parameters, template)
            val2 = self._resolve_value(equals_value[1], parameters, template)
            return val1 == val2
        return False
    
    def _resolve_if(
        self,
        if_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> Any:
        """
        Resolve Fn::If intrinsic function
        
        Args:
            if_value: If value (list of [condition_name, true_value, false_value])
            parameters: Parameter values
            template: Full template
            
        Returns:
            Resolved value based on condition
        """
        if isinstance(if_value, list) and len(if_value) >= 3:
            condition_name = if_value[0]
            true_value = if_value[1]
            false_value = if_value[2]
            
            # Evaluate the condition
            conditions = template.get('Conditions', {})
            if condition_name in conditions:
                condition_result = self._resolve_value(conditions[condition_name], parameters, template)
                if condition_result:
                    return self._resolve_value(true_value, parameters, template)
                else:
                    return self._resolve_value(false_value, parameters, template)
            
            # If condition not found, default to true value
            return self._resolve_value(true_value, parameters, template)
        
        return if_value
    
    def _resolve_not(
        self,
        not_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> bool:
        """
        Resolve Fn::Not intrinsic function
        
        Args:
            not_value: Not value (list with single condition)
            parameters: Parameter values
            template: Full template
            
        Returns:
            Negated boolean result
        """
        if isinstance(not_value, list) and len(not_value) >= 1:
            condition = self._resolve_value(not_value[0], parameters, template)
            return not bool(condition)
        return True
    
    def _resolve_and(
        self,
        and_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> bool:
        """
        Resolve Fn::And intrinsic function
        
        Args:
            and_value: And value (list of conditions)
            parameters: Parameter values
            template: Full template
            
        Returns:
            Boolean AND of all conditions
        """
        if isinstance(and_value, list):
            results = [self._resolve_value(cond, parameters, template) for cond in and_value]
            return all(bool(r) for r in results)
        return False
    
    def _resolve_or(
        self,
        or_value: Any,
        parameters: Dict[str, str],
        template: Dict[str, Any]
    ) -> bool:
        """
        Resolve Fn::Or intrinsic function
        
        Args:
            or_value: Or value (list of conditions)
            parameters: Parameter values
            template: Full template
            
        Returns:
            Boolean OR of all conditions
        """
        if isinstance(or_value, list):
            results = [self._resolve_value(cond, parameters, template) for cond in or_value]
            return any(bool(r) for r in results)
        return False
