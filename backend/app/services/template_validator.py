"""
Template Validator Service
Validates CloudFormation templates before deployment.

Provides:
- Pre-deployment template existence checks
- YAML syntax validation with CloudFormation intrinsic function support
- CloudFormation structure validation
- Manifest-based integrity verification
- Parameter, condition, mapping, and output validation
"""
import json
import re
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field, asdict

from app.utils.resource_resolver import ResourceResolver, TemplateNotFoundError
from app.utils.cfn_yaml_loader import (
    load_cfn_yaml,
    CFNTag,
    validate_yaml_syntax,
    extract_intrinsic_functions
)


logger = logging.getLogger(__name__)


@dataclass
class MissingTemplate:
    """Represents a missing template file."""
    template_name: str
    expected_path: str
    remediation: str


@dataclass
class IntegrityIssue:
    """Represents a template integrity issue."""
    template_path: str
    issue_type: str  # "invalid_yaml", "missing_cfn_section", "file_read_error", "invalid_resource_type"
    details: str
    line: Optional[int] = None
    column: Optional[int] = None
    context: Optional[str] = None


@dataclass
class TemplateValidationResult:
    """Result of template validation."""
    success: bool
    templates_checked: List[str] = field(default_factory=list)
    missing_templates: List[MissingTemplate] = field(default_factory=list)
    integrity_issues: List[IntegrityIssue] = field(default_factory=list)
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'templates_checked': self.templates_checked,
            'missing_templates': [asdict(m) for m in self.missing_templates],
            'integrity_issues': [asdict(i) for i in self.integrity_issues],
            'summary': self.summary
        }


@dataclass
class ManifestValidationResult:
    """Result of manifest validation."""
    success: bool
    manifest_found: bool
    templates_in_manifest: int = 0
    templates_found: int = 0
    missing_templates: List[str] = field(default_factory=list)
    extra_templates: List[str] = field(default_factory=list)
    hash_mismatches: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class StructureValidationResult:
    """Result of template structure validation."""
    success: bool
    has_resources: bool = False
    invalid_resource_types: List[str] = field(default_factory=list)
    duplicate_logical_ids: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ParameterValidationResult:
    """Result of parameter validation."""
    success: bool
    missing_required: List[str] = field(default_factory=list)
    type_mismatches: List[Dict[str, str]] = field(default_factory=list)
    constraint_violations: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ConditionValidationResult:
    """Result of condition validation."""
    success: bool
    undefined_conditions: List[str] = field(default_factory=list)
    invalid_functions: List[str] = field(default_factory=list)
    undefined_parameters: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class MappingValidationResult:
    """Result of mapping validation."""
    success: bool
    invalid_references: List[Dict[str, str]] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class OutputValidationResult:
    """Result of output validation."""
    success: bool
    missing_values: List[str] = field(default_factory=list)
    invalid_references: List[str] = field(default_factory=list)
    duplicate_exports: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class TemplateValidator:
    """Validates CloudFormation templates before deployment."""
    
    # Required CloudFormation sections (at least one must be present)
    REQUIRED_CFN_SECTIONS = ['AWSTemplateFormatVersion', 'Resources']
    
    # Stack types that require templates
    BACKEND_STACK_TYPES = [
        'backend-foundation',
        'backend-iam-roles',
        'backend-regional-cert',
        'backend-storage',
        'backend-network',
        'backend-service',
        'backend-domain',
    ]
    
    FRONTEND_STACK_TYPES = [
        'frontend-global',
        'frontend-cognito',
        'frontend-regional',
    ]
    
    def __init__(self):
        """Initialize template validator."""
        self.resolver = ResourceResolver
    
    def validate_templates(
        self,
        deploy_frontend: bool = True,
        deploy_backend: bool = True,
        check_integrity: bool = True
    ) -> TemplateValidationResult:
        """
        Validate all templates required for a capability deployment.
        
        Args:
            deploy_frontend: Whether frontend templates are needed
            deploy_backend: Whether backend templates are needed
            check_integrity: Whether to validate YAML and CFN structure
            
        Returns:
            TemplateValidationResult with success status, missing templates, and integrity issues
        """
        result = TemplateValidationResult(success=True)
        
        # Determine which templates to check
        required_templates = []
        if deploy_backend:
            required_templates.extend(self.BACKEND_STACK_TYPES)
        if deploy_frontend:
            required_templates.extend(self.FRONTEND_STACK_TYPES)
        
        templates_dir = self.resolver.get_templates_dir()
        logger.info(f"Validating templates in: {templates_dir}")
        
        # Check each required template
        for template_name in required_templates:
            result.templates_checked.append(template_name)
            
            # Get the relative path for this template
            relative_path = self.resolver.TEMPLATE_MAP.get(template_name)
            if not relative_path:
                result.missing_templates.append(MissingTemplate(
                    template_name=template_name,
                    expected_path="Unknown - template not in TEMPLATE_MAP",
                    remediation="Check that the template name is valid"
                ))
                continue
            
            template_path = templates_dir / relative_path
            
            # Check if template exists
            if not template_path.exists():
                remediation = self._get_remediation_advice()
                result.missing_templates.append(MissingTemplate(
                    template_name=template_name,
                    expected_path=str(template_path),
                    remediation=remediation
                ))
                continue
            
            # Check template integrity if requested
            if check_integrity:
                integrity_result = self.validate_template_integrity(template_path)
                if integrity_result:
                    result.integrity_issues.append(integrity_result)
        
        # Determine overall success
        result.success = len(result.missing_templates) == 0 and len(result.integrity_issues) == 0
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        if result.success:
            logger.info(f"Template validation passed: {result.summary}")
        else:
            logger.warning(f"Template validation failed: {result.summary}")
        
        return result
    
    def validate_template_integrity(self, template_path: Path) -> Optional[IntegrityIssue]:
        """
        Validate a single template's integrity.
        
        Checks:
        - Valid YAML syntax (with CloudFormation intrinsic function support)
        - Contains AWSTemplateFormatVersion or Resources section
        
        Args:
            template_path: Path to the template file
            
        Returns:
            IntegrityIssue if validation fails, None if successful
        """
        try:
            # Read template content
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate YAML syntax using CFN YAML Loader (supports intrinsic functions)
            success, error_info = validate_yaml_syntax(content)
            
            if not success:
                return IntegrityIssue(
                    template_path=str(template_path),
                    issue_type="invalid_yaml",
                    details=f"YAML parsing error: {error_info.get('message', 'Unknown error')}",
                    line=error_info.get('line'),
                    column=error_info.get('column'),
                    context=error_info.get('context')
                )
            
            # Parse the template with CFN YAML Loader
            template_data = load_cfn_yaml(content)
            
            # Check for required CloudFormation sections
            if template_data is None:
                return IntegrityIssue(
                    template_path=str(template_path),
                    issue_type="invalid_yaml",
                    details="Template is empty or contains only comments"
                )
            
            if not isinstance(template_data, dict):
                return IntegrityIssue(
                    template_path=str(template_path),
                    issue_type="invalid_yaml",
                    details="Template root must be a mapping/dictionary"
                )
            
            # Check for at least one required section
            has_required_section = any(
                section in template_data 
                for section in self.REQUIRED_CFN_SECTIONS
            )
            
            if not has_required_section:
                return IntegrityIssue(
                    template_path=str(template_path),
                    issue_type="missing_cfn_section",
                    details=f"Template must contain at least one of: {', '.join(self.REQUIRED_CFN_SECTIONS)}"
                )
            
            # Validation passed
            logger.debug(f"Template integrity validated: {template_path}")
            return None
            
        except IOError as e:
            return IntegrityIssue(
                template_path=str(template_path),
                issue_type="file_read_error",
                details=f"Could not read file: {str(e)}"
            )
    
    def validate_template_structure(self, template: Dict[str, Any]) -> StructureValidationResult:
        """
        Validate template structure.
        
        Checks:
        - Has Resources section
        - Resource types follow AWS::Service::Resource pattern
        - No duplicate logical IDs
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            StructureValidationResult with validation details
        """
        result = StructureValidationResult(success=True, has_resources=False)
        
        # Check for Resources section
        resources = template.get('Resources', {})
        if not resources:
            result.has_resources = False
            result.issues.append("Template does not contain a Resources section")
            result.success = False
            return result
        
        result.has_resources = True
        
        # AWS resource type pattern: AWS::Service::Resource or Custom::Name
        resource_type_pattern = re.compile(r'^(AWS::[A-Za-z0-9]+::[A-Za-z0-9]+|Custom::[A-Za-z0-9]+)$')
        
        # Track logical IDs for duplicate detection
        logical_ids = []
        
        for logical_id, resource_def in resources.items():
            # Check for duplicate logical IDs
            if logical_id in logical_ids:
                result.duplicate_logical_ids.append(logical_id)
            else:
                logical_ids.append(logical_id)
            
            # Get resource type
            if isinstance(resource_def, dict):
                resource_type = resource_def.get('Type', '')
                
                # Handle CFNTag if Type is an intrinsic function
                if isinstance(resource_type, CFNTag):
                    # Dynamic type - skip validation
                    continue
                
                if resource_type and not resource_type_pattern.match(resource_type):
                    result.invalid_resource_types.append(
                        f"{logical_id}: {resource_type}"
                    )
        
        # Determine success
        if result.invalid_resource_types:
            result.issues.append(
                f"Found {len(result.invalid_resource_types)} invalid resource types"
            )
            result.success = False
        
        if result.duplicate_logical_ids:
            result.issues.append(
                f"Found {len(result.duplicate_logical_ids)} duplicate logical IDs"
            )
            result.success = False
        
        return result
    
    def validate_parameters(
        self,
        template: Dict[str, Any],
        provided_values: Dict[str, str]
    ) -> ParameterValidationResult:
        """
        Validate parameters against template definitions.
        
        Checks:
        - Required parameters have values
        - Values match declared types
        - Values satisfy AllowedValues, AllowedPattern, Min/MaxValue constraints
        
        Args:
            template: Parsed CloudFormation template
            provided_values: Dictionary of parameter name to value
            
        Returns:
            ParameterValidationResult with validation details
        """
        result = ParameterValidationResult(success=True)
        
        parameters = template.get('Parameters', {})
        if not parameters:
            return result  # No parameters to validate
        
        for param_name, param_def in parameters.items():
            if not isinstance(param_def, dict):
                continue
            
            # Check if parameter has a default or is provided
            has_default = 'Default' in param_def
            is_provided = param_name in provided_values
            
            # Check required parameters
            if not has_default and not is_provided:
                result.missing_required.append(param_name)
                continue
            
            # Get the value to validate
            value = provided_values.get(param_name, param_def.get('Default', ''))
            
            # Get parameter type
            param_type = param_def.get('Type', 'String')
            
            # Type validation
            if param_type == 'Number':
                try:
                    float(value)
                except (ValueError, TypeError):
                    result.type_mismatches.append({
                        'parameter': param_name,
                        'expected_type': 'Number',
                        'actual_value': str(value)
                    })
                    continue
            
            # AllowedValues constraint
            allowed_values = param_def.get('AllowedValues', [])
            if allowed_values:
                # Handle type coercion: CloudFormation parameters are passed as strings
                # but AllowedValues in templates may be integers or other types
                value_matches = False
                str_value = str(value)
                
                for allowed in allowed_values:
                    # Compare as strings to handle int/string mismatch
                    if str(allowed) == str_value:
                        value_matches = True
                        break
                    # Also try numeric comparison for Number type parameters
                    if param_type == 'Number':
                        try:
                            if float(allowed) == float(value):
                                value_matches = True
                                break
                        except (ValueError, TypeError):
                            pass
                
                if not value_matches:
                    result.constraint_violations.append({
                        'parameter': param_name,
                        'constraint_type': 'AllowedValues',
                        'constraint_value': allowed_values,
                        'actual_value': value
                    })
            
            # AllowedPattern constraint
            allowed_pattern = param_def.get('AllowedPattern')
            if allowed_pattern:
                try:
                    if not re.match(allowed_pattern, str(value)):
                        result.constraint_violations.append({
                            'parameter': param_name,
                            'constraint_type': 'AllowedPattern',
                            'constraint_value': allowed_pattern,
                            'actual_value': value
                        })
                except re.error:
                    # Invalid regex pattern in template
                    result.issues.append(
                        f"Invalid AllowedPattern regex for {param_name}: {allowed_pattern}"
                    )
            
            # MinValue/MaxValue constraints for numbers
            if param_type == 'Number':
                try:
                    num_value = float(value)
                    
                    min_value = param_def.get('MinValue')
                    if min_value is not None and num_value < float(min_value):
                        result.constraint_violations.append({
                            'parameter': param_name,
                            'constraint_type': 'MinValue',
                            'constraint_value': min_value,
                            'actual_value': value
                        })
                    
                    max_value = param_def.get('MaxValue')
                    if max_value is not None and num_value > float(max_value):
                        result.constraint_violations.append({
                            'parameter': param_name,
                            'constraint_type': 'MaxValue',
                            'constraint_value': max_value,
                            'actual_value': value
                        })
                except (ValueError, TypeError):
                    pass  # Already caught in type validation
            
            # MinLength/MaxLength constraints for strings
            if param_type == 'String':
                min_length = param_def.get('MinLength')
                if min_length is not None and len(str(value)) < int(min_length):
                    result.constraint_violations.append({
                        'parameter': param_name,
                        'constraint_type': 'MinLength',
                        'constraint_value': min_length,
                        'actual_value': value
                    })
                
                max_length = param_def.get('MaxLength')
                if max_length is not None and len(str(value)) > int(max_length):
                    result.constraint_violations.append({
                        'parameter': param_name,
                        'constraint_type': 'MaxLength',
                        'constraint_value': max_length,
                        'actual_value': value
                    })
        
        # Determine success
        if result.missing_required:
            result.issues.append(
                f"Missing {len(result.missing_required)} required parameters"
            )
            result.success = False
        
        if result.type_mismatches:
            result.issues.append(
                f"Found {len(result.type_mismatches)} type mismatches"
            )
            result.success = False
        
        if result.constraint_violations:
            result.issues.append(
                f"Found {len(result.constraint_violations)} constraint violations"
            )
            result.success = False
        
        return result
    
    def validate_conditions(self, template: Dict[str, Any]) -> ConditionValidationResult:
        """
        Validate conditions in the template.
        
        Checks:
        - All referenced conditions are defined
        - Condition functions use valid intrinsic functions
        - Referenced parameters exist (but NOT resources - those are valid !Ref targets)
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            ConditionValidationResult with validation details
        """
        result = ConditionValidationResult(success=True)
        
        conditions = template.get('Conditions', {})
        parameters = template.get('Parameters', {})
        resources = template.get('Resources', {})
        
        # Get all defined names
        defined_conditions = set(conditions.keys()) if conditions else set()
        defined_parameters = set(parameters.keys()) if parameters else set()
        # FIX: Also track defined resources to avoid false positives
        defined_resources = set(resources.keys()) if resources else set()
        
        # CloudFormation pseudo-parameters that are always valid
        pseudo_parameters = {
            'AWS::StackName', 'AWS::Region', 'AWS::AccountId', 'AWS::NoValue',
            'AWS::StackId', 'AWS::URLSuffix', 'AWS::Partition', 'AWS::NotificationARNs'
        }
        
        # Valid condition intrinsic functions
        valid_condition_functions = {'And', 'Or', 'Not', 'Equals', 'If', 'Condition'}
        
        # Track referenced conditions
        referenced_conditions: Set[str] = set()
        
        def check_condition_references(obj: Any, path: str = ""):
            """Recursively check for condition references."""
            if isinstance(obj, CFNTag):
                if obj.tag == 'Condition':
                    referenced_conditions.add(obj.value)
                elif obj.tag == 'Ref':
                    ref_target = obj.value
                    # FIX: Check parameters, resources, AND pseudo-parameters
                    # Only flag as undefined if it's not in ANY valid target set
                    if (ref_target not in defined_parameters and 
                        ref_target not in defined_resources and 
                        ref_target not in pseudo_parameters):
                        result.undefined_parameters.append(f"{path}: {ref_target}")
                # Recursively check value
                check_condition_references(obj.value, f"{path}.{obj.tag}")
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    check_condition_references(value, f"{path}.{key}" if path else key)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_condition_references(item, f"{path}[{i}]")
        
        # Check conditions section
        for cond_name, cond_def in conditions.items():
            check_condition_references(cond_def, f"Conditions.{cond_name}")
        
        # Check resources for Condition attribute
        for res_name, res_def in resources.items():
            if isinstance(res_def, dict):
                condition = res_def.get('Condition')
                if condition:
                    if isinstance(condition, str):
                        referenced_conditions.add(condition)
                    elif isinstance(condition, CFNTag) and condition.tag == 'Condition':
                        referenced_conditions.add(condition.value)
                
                # Check properties for condition references
                check_condition_references(res_def, f"Resources.{res_name}")
        
        # Find undefined conditions
        for cond in referenced_conditions:
            if cond not in defined_conditions:
                result.undefined_conditions.append(cond)
        
        # Determine success
        if result.undefined_conditions:
            result.issues.append(
                f"Found {len(result.undefined_conditions)} undefined conditions"
            )
            result.success = False
        
        if result.undefined_parameters:
            result.issues.append(
                f"Found {len(result.undefined_parameters)} undefined parameter references"
            )
            result.success = False
        
        return result
    
    def validate_mappings(self, template: Dict[str, Any]) -> MappingValidationResult:
        """
        Validate mappings in the template.
        
        Checks:
        - All FindInMap references point to existing mappings
        - First-level and second-level keys exist
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            MappingValidationResult with validation details
        """
        result = MappingValidationResult(success=True)
        
        mappings = template.get('Mappings', {})
        
        def check_findinmap(obj: Any, path: str = ""):
            """Recursively check for FindInMap references."""
            if isinstance(obj, CFNTag):
                if obj.tag == 'FindInMap':
                    # FindInMap takes [MapName, FirstLevelKey, SecondLevelKey]
                    if isinstance(obj.value, list) and len(obj.value) >= 3:
                        map_name = obj.value[0]
                        first_key = obj.value[1]
                        second_key = obj.value[2]
                        
                        # Skip if keys are intrinsic functions (dynamic)
                        if isinstance(map_name, CFNTag) or isinstance(first_key, CFNTag) or isinstance(second_key, CFNTag):
                            return
                        
                        # Check if mapping exists
                        if map_name not in mappings:
                            result.invalid_references.append({
                                'location': path,
                                'mapping_name': map_name,
                                'first_key': str(first_key),
                                'second_key': str(second_key),
                                'missing_key': 'mapping'
                            })
                        elif first_key not in mappings.get(map_name, {}):
                            result.invalid_references.append({
                                'location': path,
                                'mapping_name': map_name,
                                'first_key': str(first_key),
                                'second_key': str(second_key),
                                'missing_key': 'first_level'
                            })
                        elif second_key not in mappings.get(map_name, {}).get(first_key, {}):
                            result.invalid_references.append({
                                'location': path,
                                'mapping_name': map_name,
                                'first_key': str(first_key),
                                'second_key': str(second_key),
                                'missing_key': 'second_level'
                            })
                else:
                    # Recursively check value
                    check_findinmap(obj.value, f"{path}.{obj.tag}")
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    check_findinmap(value, f"{path}.{key}" if path else key)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_findinmap(item, f"{path}[{i}]")
        
        # Check entire template for FindInMap references
        check_findinmap(template)
        
        # Determine success
        if result.invalid_references:
            result.issues.append(
                f"Found {len(result.invalid_references)} invalid FindInMap references"
            )
            result.success = False
        
        return result
    
    def validate_outputs(
        self,
        template: Dict[str, Any],
        all_exports: Optional[Set[str]] = None
    ) -> OutputValidationResult:
        """
        Validate outputs in the template.
        
        Checks:
        - All outputs have a Value property
        - Referenced resources exist
        - Export names are unique
        
        Args:
            template: Parsed CloudFormation template
            all_exports: Optional set of all export names across deployment
            
        Returns:
            OutputValidationResult with validation details
        """
        result = OutputValidationResult(success=True)
        
        outputs = template.get('Outputs', {})
        resources = template.get('Resources', {})
        
        if not outputs:
            return result  # No outputs to validate
        
        defined_resources = set(resources.keys()) if resources else set()
        export_names: List[str] = []
        
        for output_name, output_def in outputs.items():
            if not isinstance(output_def, dict):
                continue
            
            # Check for Value property
            if 'Value' not in output_def:
                result.missing_values.append(output_name)
            else:
                # Check if Value references a valid resource
                value = output_def['Value']
                if isinstance(value, CFNTag):
                    if value.tag == 'Ref':
                        ref_name = value.value
                        # Check if it's a resource reference (not a parameter or pseudo-parameter)
                        if ref_name not in defined_resources and not ref_name.startswith('AWS::'):
                            # Could be a parameter - don't flag as error
                            pass
                    elif value.tag == 'GetAtt':
                        # GetAtt references a resource
                        if isinstance(value.value, list) and len(value.value) >= 1:
                            resource_name = value.value[0]
                            if resource_name not in defined_resources:
                                result.invalid_references.append(
                                    f"{output_name}: GetAtt references undefined resource '{resource_name}'"
                                )
                        elif isinstance(value.value, str):
                            # GetAtt with dot notation: Resource.Attribute
                            resource_name = value.value.split('.')[0]
                            if resource_name not in defined_resources:
                                result.invalid_references.append(
                                    f"{output_name}: GetAtt references undefined resource '{resource_name}'"
                                )
            
            # Check for Export
            export = output_def.get('Export', {})
            if export and isinstance(export, dict):
                export_name = export.get('Name')
                if export_name:
                    # Handle intrinsic function in export name
                    if isinstance(export_name, CFNTag):
                        # Dynamic export name - can't validate uniqueness
                        pass
                    else:
                        export_names.append(export_name)
        
        # Check for duplicate exports within this template
        seen_exports = set()
        for export_name in export_names:
            if export_name in seen_exports:
                result.duplicate_exports.append(export_name)
            seen_exports.add(export_name)
            
            # Check against all exports if provided
            if all_exports and export_name in all_exports:
                result.duplicate_exports.append(f"{export_name} (conflicts with existing export)")
        
        # Determine success
        if result.missing_values:
            result.issues.append(
                f"Found {len(result.missing_values)} outputs without Value property"
            )
            result.success = False
        
        if result.invalid_references:
            result.issues.append(
                f"Found {len(result.invalid_references)} invalid resource references"
            )
            result.success = False
        
        if result.duplicate_exports:
            result.issues.append(
                f"Found {len(result.duplicate_exports)} duplicate export names"
            )
            result.success = False
        
        return result
    
    def validate_against_manifest(self) -> ManifestValidationResult:
        """
        Compare available templates against the bundled manifest.
        
        Returns:
            ManifestValidationResult with comparison details
        """
        result = ManifestValidationResult(success=True, manifest_found=False)
        
        manifest_path = self.resolver.get_manifest_path()
        
        if not manifest_path.exists():
            result.manifest_found = False
            result.warnings.append(
                f"Template manifest not found at {manifest_path}. "
                "This may indicate an incomplete installation."
            )
            # Not a failure - manifest is optional for dev mode
            return result
        
        result.manifest_found = True
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            result.success = False
            result.warnings.append(f"Could not read manifest: {str(e)}")
            return result
        
        manifest_templates = manifest_data.get('templates', [])
        result.templates_in_manifest = len(manifest_templates)
        
        templates_dir = self.resolver.get_templates_dir()
        
        # Build set of expected templates from manifest
        expected_templates = {}
        for entry in manifest_templates:
            rel_path = entry.get('relative_path', '')
            expected_templates[rel_path] = entry
        
        # Check which templates exist
        found_templates = set()
        for rel_path in expected_templates:
            full_path = templates_dir / rel_path
            if full_path.exists():
                found_templates.add(rel_path)
                
                # Optionally verify hash
                expected_hash = expected_templates[rel_path].get('sha256')
                if expected_hash:
                    actual_hash = self._compute_file_hash(full_path)
                    if actual_hash != expected_hash:
                        result.hash_mismatches.append(rel_path)
            else:
                result.missing_templates.append(rel_path)
        
        result.templates_found = len(found_templates)
        
        # Check for extra templates not in manifest
        all_templates = self._find_all_templates(templates_dir)
        for template in all_templates:
            if template not in expected_templates:
                result.extra_templates.append(template)
        
        # Determine success
        if result.missing_templates:
            result.success = False
            result.warnings.append(
                f"Missing {len(result.missing_templates)} templates compared to manifest. "
                "The installation may be incomplete."
            )
        
        if result.hash_mismatches:
            result.warnings.append(
                f"{len(result.hash_mismatches)} templates have different content than expected. "
                "Templates may have been modified."
            )
        
        return result
    
    def _get_remediation_advice(self) -> str:
        """Get remediation advice based on environment."""
        if self.resolver.is_packaged():
            return "Please reinstall the application to restore missing templates."
        return "Ensure the deploy/templates directory exists and contains all required templates."
    
    def _generate_summary(self, result: TemplateValidationResult) -> str:
        """Generate a human-readable summary of validation results."""
        parts = []
        
        parts.append(f"Checked {len(result.templates_checked)} templates")
        
        if result.missing_templates:
            parts.append(f"{len(result.missing_templates)} missing")
        
        if result.integrity_issues:
            parts.append(f"{len(result.integrity_issues)} integrity issues")
        
        if result.success:
            parts.append("all valid")
        
        return ", ".join(parts)
    
    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _find_all_templates(self, templates_dir: Path) -> List[str]:
        """Find all YAML templates in the templates directory."""
        templates = []
        if templates_dir.exists():
            for yaml_file in templates_dir.rglob("*.yaml"):
                rel_path = yaml_file.relative_to(templates_dir)
                templates.append(str(rel_path).replace("\\", "/"))
            for yml_file in templates_dir.rglob("*.yml"):
                rel_path = yml_file.relative_to(templates_dir)
                templates.append(str(rel_path).replace("\\", "/"))
        return templates


def get_template_validator() -> TemplateValidator:
    """Factory function to get a TemplateValidator instance."""
    return TemplateValidator()
