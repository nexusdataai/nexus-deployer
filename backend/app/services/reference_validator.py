"""
Reference Validator Service
Validates CloudFormation !Ref and !GetAtt references to eliminate false positives.

The key issue this solves: The template validator was flagging valid !Ref references
to resources within the same template as "undefined parameter references". This module
properly distinguishes between:
- Parameter references (!Ref to Parameters)
- Resource references (!Ref to Resources)
- Pseudo-parameter references (!Ref to AWS::StackName, AWS::Region, etc.)
- GetAtt references (!GetAtt to Resource.Attribute)

Feature: deployment-prerequisites-verification
Requirements: 4.1, 4.2, 4.3, 4.4
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple

from app.utils.cfn_yaml_loader import CFNTag


logger = logging.getLogger(__name__)


# CloudFormation pseudo-parameters that are always valid
PSEUDO_PARAMETERS = frozenset([
    'AWS::AccountId',
    'AWS::NotificationARNs',
    'AWS::NoValue',
    'AWS::Partition',
    'AWS::Region',
    'AWS::StackId',
    'AWS::StackName',
    'AWS::URLSuffix',
])


@dataclass
class ReferenceIssue:
    """Represents an invalid reference."""
    reference_type: str  # 'Ref', 'GetAtt', 'Sub', 'Condition'
    target: str
    location: str
    message: str
    is_parameter: bool = False
    is_resource: bool = False
    is_pseudo: bool = False
    remediation: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'reference_type': self.reference_type,
            'target': self.target,
            'location': self.location,
            'message': self.message,
            'is_parameter': self.is_parameter,
            'is_resource': self.is_resource,
            'is_pseudo': self.is_pseudo,
            'remediation': self.remediation
        }


@dataclass
class ReferenceValidationResult:
    """Result of reference validation."""
    success: bool
    invalid_refs: List[ReferenceIssue] = field(default_factory=list)
    invalid_getatt: List[ReferenceIssue] = field(default_factory=list)
    valid_resource_refs: List[str] = field(default_factory=list)
    valid_parameter_refs: List[str] = field(default_factory=list)
    valid_pseudo_refs: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'invalid_refs': [r.to_dict() for r in self.invalid_refs],
            'invalid_getatt': [r.to_dict() for r in self.invalid_getatt],
            'valid_resource_refs': self.valid_resource_refs,
            'valid_parameter_refs': self.valid_parameter_refs,
            'valid_pseudo_refs': self.valid_pseudo_refs,
            'issues': self.issues
        }


class ReferenceValidator:
    """Validates CloudFormation references to eliminate false positives."""
    
    def __init__(self):
        self.pseudo_parameters = PSEUDO_PARAMETERS
    
    def extract_resources(self, template: Dict[str, Any]) -> Set[str]:
        """
        Extract all resource logical IDs from template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            Set of resource logical IDs
        """
        resources = template.get('Resources', {})
        if not resources or not isinstance(resources, dict):
            return set()
        return set(resources.keys())
    
    def extract_parameters(self, template: Dict[str, Any]) -> Set[str]:
        """
        Extract all parameter names from template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            Set of parameter names
        """
        parameters = template.get('Parameters', {})
        if not parameters or not isinstance(parameters, dict):
            return set()
        return set(parameters.keys())
    
    def extract_conditions(self, template: Dict[str, Any]) -> Set[str]:
        """
        Extract all condition names from template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            Set of condition names
        """
        conditions = template.get('Conditions', {})
        if not conditions or not isinstance(conditions, dict):
            return set()
        return set(conditions.keys())
    
    def is_pseudo_parameter(self, ref_target: str) -> bool:
        """
        Check if reference target is a CloudFormation pseudo-parameter.
        
        Args:
            ref_target: The target of a !Ref
            
        Returns:
            True if it's a pseudo-parameter
        """
        return ref_target in self.pseudo_parameters
    
    def validate_ref(
        self,
        ref_target: str,
        defined_parameters: Set[str],
        defined_resources: Set[str],
        location: str = ""
    ) -> Tuple[bool, Optional[ReferenceIssue]]:
        """
        Validate a !Ref reference.
        
        A !Ref is valid if it references:
        - A defined parameter
        - A defined resource (returns the physical ID)
        - A pseudo-parameter (AWS::StackName, etc.)
        
        Args:
            ref_target: The target of the !Ref
            defined_parameters: Set of parameter names in template
            defined_resources: Set of resource logical IDs in template
            location: Location in template for error reporting
            
        Returns:
            Tuple of (is_valid, ReferenceIssue if invalid)
        """
        # Check pseudo-parameters first
        if self.is_pseudo_parameter(ref_target):
            return True, None
        
        # Check parameters
        if ref_target in defined_parameters:
            return True, None
        
        # Check resources - THIS IS THE KEY FIX FOR FALSE POSITIVES
        if ref_target in defined_resources:
            return True, None
        
        # Invalid reference
        issue = ReferenceIssue(
            reference_type='Ref',
            target=ref_target,
            location=location,
            message=f"Reference to undefined target: {ref_target}",
            remediation=f"Define '{ref_target}' as a Parameter or Resource, or use a valid pseudo-parameter"
        )
        return False, issue
    
    def validate_getatt(
        self,
        getatt_target: Any,
        defined_resources: Set[str],
        location: str = ""
    ) -> Tuple[bool, Optional[ReferenceIssue]]:
        """
        Validate a !GetAtt reference.
        
        !GetAtt can be:
        - [LogicalId, AttributeName]
        - "LogicalId.AttributeName"
        
        Args:
            getatt_target: The target of the !GetAtt
            defined_resources: Set of resource logical IDs in template
            location: Location in template for error reporting
            
        Returns:
            Tuple of (is_valid, ReferenceIssue if invalid)
        """
        resource_id = None
        attribute = None
        
        if isinstance(getatt_target, list) and len(getatt_target) >= 2:
            resource_id = getatt_target[0]
            attribute = getatt_target[1]
        elif isinstance(getatt_target, str) and '.' in getatt_target:
            parts = getatt_target.split('.', 1)
            resource_id = parts[0]
            attribute = parts[1] if len(parts) > 1 else None
        
        if resource_id is None:
            issue = ReferenceIssue(
                reference_type='GetAtt',
                target=str(getatt_target),
                location=location,
                message=f"Invalid GetAtt format: {getatt_target}",
                remediation="Use format: !GetAtt ResourceLogicalId.AttributeName"
            )
            return False, issue
        
        # Handle CFNTag for dynamic resource IDs
        if isinstance(resource_id, CFNTag):
            # Dynamic reference - can't validate statically
            return True, None
        
        if resource_id not in defined_resources:
            issue = ReferenceIssue(
                reference_type='GetAtt',
                target=str(resource_id),
                location=location,
                message=f"GetAtt references undefined resource: {resource_id}",
                is_resource=True,
                remediation=f"Define resource '{resource_id}' in the Resources section"
            )
            return False, issue
        
        return True, None
    
    def validate_sub(
        self,
        sub_value: Any,
        defined_parameters: Set[str],
        defined_resources: Set[str],
        location: str = ""
    ) -> List[ReferenceIssue]:
        """
        Validate references within a !Sub intrinsic function.
        
        !Sub can contain ${VarName} references to:
        - Parameters
        - Resources
        - Pseudo-parameters
        - Local variables (if !Sub is [string, {var: value}])
        
        Args:
            sub_value: The value of the !Sub
            defined_parameters: Set of parameter names
            defined_resources: Set of resource logical IDs
            location: Location in template
            
        Returns:
            List of ReferenceIssues for invalid references
        """
        import re
        
        issues = []
        local_vars: Set[str] = set()
        template_string = ""
        
        # Handle both forms of !Sub
        if isinstance(sub_value, list) and len(sub_value) >= 2:
            template_string = sub_value[0] if isinstance(sub_value[0], str) else ""
            if isinstance(sub_value[1], dict):
                local_vars = set(sub_value[1].keys())
        elif isinstance(sub_value, str):
            template_string = sub_value
        
        # Find all ${VarName} references (but not ${!Literal})
        var_pattern = re.compile(r'\$\{([^!][^}]*)\}')
        
        for match in var_pattern.finditer(template_string):
            var_ref = match.group(1)
            
            # Handle GetAtt syntax: ${Resource.Attribute}
            if '.' in var_ref:
                resource_id = var_ref.split('.')[0]
                if resource_id in local_vars:
                    continue
                if resource_id in defined_resources:
                    continue
                if self.is_pseudo_parameter(resource_id):
                    continue
                
                issues.append(ReferenceIssue(
                    reference_type='Sub',
                    target=var_ref,
                    location=location,
                    message=f"Sub references undefined resource: {resource_id}",
                    remediation=f"Define resource '{resource_id}' or add it to Sub's variable map"
                ))
            else:
                # Simple variable reference
                if var_ref in local_vars:
                    continue
                if var_ref in defined_parameters:
                    continue
                if var_ref in defined_resources:
                    continue
                if self.is_pseudo_parameter(var_ref):
                    continue
                
                issues.append(ReferenceIssue(
                    reference_type='Sub',
                    target=var_ref,
                    location=location,
                    message=f"Sub references undefined variable: {var_ref}",
                    remediation=f"Define '{var_ref}' as Parameter, Resource, or in Sub's variable map"
                ))
        
        return issues

    def validate_all_references(
        self,
        template: Dict[str, Any]
    ) -> ReferenceValidationResult:
        """
        Validate all references in a CloudFormation template.
        
        This is the main entry point that:
        1. Extracts all parameters, resources, and conditions
        2. Walks the entire template looking for !Ref, !GetAtt, !Sub
        3. Validates each reference against defined targets
        4. Returns a comprehensive result with valid and invalid references
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            ReferenceValidationResult with all validation details
        """
        result = ReferenceValidationResult(success=True)
        
        # Extract all defined names
        defined_parameters = self.extract_parameters(template)
        defined_resources = self.extract_resources(template)
        defined_conditions = self.extract_conditions(template)
        
        # Track valid references for reporting
        seen_resource_refs: Set[str] = set()
        seen_parameter_refs: Set[str] = set()
        seen_pseudo_refs: Set[str] = set()
        
        def walk_template(obj: Any, path: str = ""):
            """Recursively walk template and validate references."""
            if isinstance(obj, CFNTag):
                if obj.tag == 'Ref':
                    ref_target = obj.value
                    if isinstance(ref_target, str):
                        is_valid, issue = self.validate_ref(
                            ref_target,
                            defined_parameters,
                            defined_resources,
                            path
                        )
                        
                        if is_valid:
                            if self.is_pseudo_parameter(ref_target):
                                seen_pseudo_refs.add(ref_target)
                            elif ref_target in defined_resources:
                                seen_resource_refs.add(ref_target)
                            elif ref_target in defined_parameters:
                                seen_parameter_refs.add(ref_target)
                        else:
                            result.invalid_refs.append(issue)
                    
                elif obj.tag == 'GetAtt':
                    is_valid, issue = self.validate_getatt(
                        obj.value,
                        defined_resources,
                        path
                    )
                    if not is_valid:
                        result.invalid_getatt.append(issue)
                
                elif obj.tag == 'Sub':
                    issues = self.validate_sub(
                        obj.value,
                        defined_parameters,
                        defined_resources,
                        path
                    )
                    result.invalid_refs.extend(issues)
                
                # Recursively check the value
                walk_template(obj.value, f"{path}.{obj.tag}")
                
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    new_path = f"{path}.{key}" if path else key
                    walk_template(value, new_path)
                    
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    walk_template(item, f"{path}[{i}]")
        
        # Walk the entire template
        walk_template(template)
        
        # Populate result
        result.valid_resource_refs = sorted(seen_resource_refs)
        result.valid_parameter_refs = sorted(seen_parameter_refs)
        result.valid_pseudo_refs = sorted(seen_pseudo_refs)
        
        # Determine success
        if result.invalid_refs or result.invalid_getatt:
            result.success = False
            if result.invalid_refs:
                result.issues.append(f"Found {len(result.invalid_refs)} invalid Ref/Sub references")
            if result.invalid_getatt:
                result.issues.append(f"Found {len(result.invalid_getatt)} invalid GetAtt references")
        
        return result
    
    def filter_false_positives(
        self,
        undefined_params: List[str],
        template: Dict[str, Any]
    ) -> Tuple[List[str], List[str]]:
        """
        Filter out false positives from a list of "undefined parameters".
        
        This is used to fix the existing template_validator.py behavior
        which incorrectly flags !Ref to resources as undefined parameters.
        
        Args:
            undefined_params: List of "undefined parameter" warnings from validator
            template: Parsed CloudFormation template
            
        Returns:
            Tuple of (truly_undefined, valid_resource_refs)
        """
        defined_resources = self.extract_resources(template)
        
        truly_undefined = []
        valid_resource_refs = []
        
        for param_warning in undefined_params:
            # Extract the reference target from warning format "path: target"
            if ': ' in param_warning:
                target = param_warning.split(': ')[-1]
            else:
                target = param_warning
            
            # Check if it's actually a valid resource reference
            if target in defined_resources:
                valid_resource_refs.append(target)
            elif self.is_pseudo_parameter(target):
                # Also filter out pseudo-parameters that might have been missed
                pass
            else:
                truly_undefined.append(param_warning)
        
        return truly_undefined, valid_resource_refs


def get_reference_validator() -> ReferenceValidator:
    """Factory function to get a ReferenceValidator instance."""
    return ReferenceValidator()
