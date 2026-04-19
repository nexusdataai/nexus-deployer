"""
CloudFormation YAML Loader
Custom YAML loader that handles all CloudFormation intrinsic functions.

This module provides a YAML loader that correctly parses CloudFormation templates
containing intrinsic functions like !Ref, !Sub, !GetAtt, !Condition, etc.

The standard yaml.safe_load() fails on these tags because they are custom YAML tags
that require special handling.
"""
import yaml
import logging
from typing import Any, Dict, Union
from pathlib import Path

logger = logging.getLogger(__name__)


# All CloudFormation intrinsic function tags
CFN_INTRINSIC_FUNCTIONS = [
    # Reference functions
    'Ref',
    'GetAtt',
    'ImportValue',
    
    # String manipulation
    'Sub',
    'Join',
    'Split',
    'Select',
    'Base64',
    
    # Conditional functions
    'If',
    'Condition',
    'And',
    'Or',
    'Not',
    'Equals',
    
    # Mapping and lookup
    'FindInMap',
    'GetAZs',
    'Cidr',
    
    # Transform
    'Transform',
]


class CFNTag:
    """
    Represents a CloudFormation intrinsic function tag.
    
    This class preserves the tag name and value so that the template
    structure is maintained after parsing.
    """
    def __init__(self, tag: str, value: Any):
        self.tag = tag
        self.value = value
    
    def __repr__(self) -> str:
        return f"CFNTag({self.tag}, {self.value!r})"
    
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, CFNTag):
            return self.tag == other.tag and self.value == other.value
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation (long-form syntax)."""
        # Handle GetAtt special case - it uses Fn::GetAtt
        if self.tag == 'GetAtt':
            return {'Fn::GetAtt': self.value}
        elif self.tag == 'Ref':
            return {'Ref': self.value}
        elif self.tag == 'Condition':
            return {'Condition': self.value}
        else:
            return {f'Fn::{self.tag}': self.value}


class CFNYAMLLoader(yaml.SafeLoader):
    """
    Custom YAML loader that handles CloudFormation intrinsic functions.
    
    Supports all CloudFormation intrinsic functions in both short-form (!Ref)
    and long-form (Ref:) syntax.
    
    Example:
        >>> content = '''
        ... Resources:
        ...   MyBucket:
        ...     Type: AWS::S3::Bucket
        ...     Properties:
        ...       BucketName: !Sub "${AWS::StackName}-bucket"
        ... '''
        >>> template = load_cfn_yaml(content)
    """
    pass


def _create_cfn_constructor(tag_name: str):
    """
    Create a constructor function for a CloudFormation intrinsic function tag.
    
    Args:
        tag_name: The name of the intrinsic function (e.g., 'Ref', 'Sub')
        
    Returns:
        A constructor function for the YAML loader
    """
    def constructor(loader: yaml.Loader, node: yaml.Node) -> CFNTag:
        """Construct a CFNTag from a YAML node."""
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        elif isinstance(node, yaml.MappingNode):
            value = loader.construct_mapping(node, deep=True)
        else:
            value = None
        
        return CFNTag(tag_name, value)
    
    return constructor


def _unknown_tag_constructor(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> CFNTag:
    """
    Constructor for unknown YAML tags.
    
    Logs a warning but continues parsing to handle custom or future tags.
    """
    logger.warning(f"Unknown YAML tag encountered: !{tag_suffix}")
    
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node, deep=True)
    else:
        value = None
    
    return CFNTag(tag_suffix, value)


# Register constructors for all CloudFormation intrinsic functions
for func_name in CFN_INTRINSIC_FUNCTIONS:
    # Register short-form tag (e.g., !Ref)
    CFNYAMLLoader.add_constructor(
        f'!{func_name}',
        _create_cfn_constructor(func_name)
    )

# Register multi-constructor for unknown tags (catches any !TagName not explicitly registered)
CFNYAMLLoader.add_multi_constructor('!', _unknown_tag_constructor)


def load_cfn_yaml(content: str) -> Dict[str, Any]:
    """
    Load CloudFormation YAML content with intrinsic function support.
    
    Args:
        content: YAML string content to parse
        
    Returns:
        Parsed template as a dictionary
        
    Raises:
        yaml.YAMLError: If the YAML is invalid
        
    Example:
        >>> content = "BucketName: !Sub '${AWS::StackName}-bucket'"
        >>> result = load_cfn_yaml(content)
        >>> isinstance(result['BucketName'], CFNTag)
        True
    """
    return yaml.load(content, Loader=CFNYAMLLoader)


def load_cfn_yaml_file(file_path: Union[str, Path]) -> Dict[str, Any]:
    """
    Load CloudFormation YAML file with intrinsic function support.
    
    Args:
        file_path: Path to the YAML file
        
    Returns:
        Parsed template as a dictionary
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        yaml.YAMLError: If the YAML is invalid
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Template file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return load_cfn_yaml(content)


def cfn_tag_to_dict(obj: Any) -> Any:
    """
    Recursively convert CFNTag objects to dictionary representation.
    
    This is useful for serializing parsed templates back to JSON/YAML
    or for comparison purposes.
    
    Args:
        obj: Object to convert (may contain CFNTag instances)
        
    Returns:
        Object with CFNTag instances converted to dictionaries
    """
    if isinstance(obj, CFNTag):
        # Convert the tag itself
        result = obj.to_dict()
        # Recursively convert the value
        key = list(result.keys())[0]
        result[key] = cfn_tag_to_dict(result[key])
        return result
    elif isinstance(obj, dict):
        return {k: cfn_tag_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [cfn_tag_to_dict(item) for item in obj]
    else:
        return obj


def extract_intrinsic_functions(template: Dict[str, Any]) -> list:
    """
    Extract all intrinsic function usages from a parsed template.
    
    Args:
        template: Parsed CloudFormation template
        
    Returns:
        List of tuples (path, CFNTag) where path is the location in the template
    """
    results = []
    
    def _extract(obj: Any, path: str = ""):
        if isinstance(obj, CFNTag):
            results.append((path, obj))
            # Also check the value for nested intrinsic functions
            _extract(obj.value, f"{path}.{obj.tag}")
        elif isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                _extract(value, new_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _extract(item, f"{path}[{i}]")
    
    _extract(template)
    return results


def validate_yaml_syntax(content: str) -> tuple:
    """
    Validate YAML syntax and return detailed error information.
    
    Args:
        content: YAML string content to validate
        
    Returns:
        Tuple of (success: bool, error_info: dict or None)
        error_info contains: line, column, message, context
    """
    try:
        load_cfn_yaml(content)
        return True, None
    except yaml.YAMLError as e:
        error_info = {
            'message': str(e),
            'line': None,
            'column': None,
            'context': None
        }
        
        # Extract line and column from the error if available
        if hasattr(e, 'problem_mark') and e.problem_mark:
            mark = e.problem_mark
            error_info['line'] = mark.line + 1  # YAML uses 0-based line numbers
            error_info['column'] = mark.column + 1
            
            # Extract context (surrounding lines)
            lines = content.split('\n')
            start = max(0, mark.line - 2)
            end = min(len(lines), mark.line + 3)
            context_lines = []
            for i in range(start, end):
                prefix = ">>> " if i == mark.line else "    "
                context_lines.append(f"{prefix}{i + 1}: {lines[i]}")
            error_info['context'] = '\n'.join(context_lines)
        
        return False, error_info
