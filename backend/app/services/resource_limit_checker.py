"""
Resource Limit Checker Service
Checks for CloudFormation resource limits before deployment.

Provides:
- Resource counting by type
- CloudFormation limit warnings
- Limit-prone resource identification
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from collections import defaultdict

from app.utils.cfn_yaml_loader import CFNTag


logger = logging.getLogger(__name__)


@dataclass
class ResourceLimitWarning:
    """Warning about approaching resource limits."""
    resource_type: str
    current_count: int
    limit: int
    severity: str  # 'warning', 'error'
    message: str
    stack_name: Optional[str] = None


@dataclass
class ResourceLimitResult:
    """Result of resource limit checking."""
    success: bool
    total_resources: int = 0
    resources_by_type: Dict[str, int] = field(default_factory=dict)
    resources_by_stack: Dict[str, int] = field(default_factory=dict)
    warnings: List[ResourceLimitWarning] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'success': self.success,
            'total_resources': self.total_resources,
            'resources_by_type': self.resources_by_type,
            'resources_by_stack': self.resources_by_stack,
            'warnings': [
                {
                    'resource_type': w.resource_type,
                    'current_count': w.current_count,
                    'limit': w.limit,
                    'severity': w.severity,
                    'message': w.message,
                    'stack_name': w.stack_name
                }
                for w in self.warnings
            ],
            'issues': self.issues
        }


class ResourceLimitChecker:
    """Checks for CloudFormation resource limits."""
    
    # CloudFormation limits
    STACK_RESOURCE_LIMIT = 500
    OUTPUTS_LIMIT = 200
    PARAMETERS_LIMIT = 200
    MAPPINGS_LIMIT = 200
    CONDITIONS_LIMIT = 200
    
    # Warning thresholds (percentage of limit)
    WARNING_THRESHOLD = 0.8  # 80%
    ERROR_THRESHOLD = 1.0    # 100%
    
    # Limit-prone resource types that often hit account limits
    LIMIT_PRONE_RESOURCES = {
        'AWS::IAM::Role': {
            'account_limit': 1000,
            'description': 'IAM roles per account'
        },
        'AWS::IAM::Policy': {
            'account_limit': 1500,
            'description': 'IAM policies per account'
        },
        'AWS::Lambda::Function': {
            'account_limit': 1000,
            'description': 'Lambda functions per region'
        },
        'AWS::S3::Bucket': {
            'account_limit': 100,
            'description': 'S3 buckets per account'
        },
        'AWS::DynamoDB::Table': {
            'account_limit': 2500,
            'description': 'DynamoDB tables per region'
        },
        'AWS::EC2::SecurityGroup': {
            'account_limit': 2500,
            'description': 'Security groups per VPC'
        },
        'AWS::EC2::VPC': {
            'account_limit': 5,
            'description': 'VPCs per region (default)'
        },
        'AWS::CloudWatch::Alarm': {
            'account_limit': 5000,
            'description': 'CloudWatch alarms per region'
        },
        'AWS::SNS::Topic': {
            'account_limit': 100000,
            'description': 'SNS topics per account'
        },
        'AWS::SQS::Queue': {
            'account_limit': 1000000,
            'description': 'SQS queues per account'
        }
    }
    
    def count_resources(self, template: Dict[str, Any]) -> Dict[str, int]:
        """
        Count resources by type in a template.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            Dictionary of resource type to count
        """
        counts: Dict[str, int] = defaultdict(int)
        
        resources = template.get('Resources', {})
        for logical_id, resource_def in resources.items():
            if isinstance(resource_def, dict):
                resource_type = resource_def.get('Type', 'Unknown')
                
                # Handle CFNTag if Type is dynamic
                if isinstance(resource_type, CFNTag):
                    resource_type = 'Dynamic'
                
                counts[resource_type] += 1
        
        return dict(counts)
    
    def count_template_elements(self, template: Dict[str, Any]) -> Dict[str, int]:
        """
        Count various template elements.
        
        Args:
            template: Parsed CloudFormation template
            
        Returns:
            Dictionary of element type to count
        """
        return {
            'Resources': len(template.get('Resources', {})),
            'Parameters': len(template.get('Parameters', {})),
            'Outputs': len(template.get('Outputs', {})),
            'Mappings': len(template.get('Mappings', {})),
            'Conditions': len(template.get('Conditions', {}))
        }
    
    def check_stack_limits(
        self,
        template: Dict[str, Any],
        stack_name: str = 'Unknown'
    ) -> List[ResourceLimitWarning]:
        """
        Check a single stack for limit concerns.
        
        Args:
            template: Parsed CloudFormation template
            stack_name: Name of the stack
            
        Returns:
            List of warnings
        """
        warnings = []
        
        # Count template elements
        counts = self.count_template_elements(template)
        
        # Check resource limit
        resource_count = counts['Resources']
        if resource_count >= self.STACK_RESOURCE_LIMIT * self.ERROR_THRESHOLD:
            warnings.append(ResourceLimitWarning(
                resource_type='Stack Resources',
                current_count=resource_count,
                limit=self.STACK_RESOURCE_LIMIT,
                severity='error',
                message=f"Stack '{stack_name}' has {resource_count} resources, exceeding limit of {self.STACK_RESOURCE_LIMIT}",
                stack_name=stack_name
            ))
        elif resource_count >= self.STACK_RESOURCE_LIMIT * self.WARNING_THRESHOLD:
            warnings.append(ResourceLimitWarning(
                resource_type='Stack Resources',
                current_count=resource_count,
                limit=self.STACK_RESOURCE_LIMIT,
                severity='warning',
                message=f"Stack '{stack_name}' has {resource_count} resources, approaching limit of {self.STACK_RESOURCE_LIMIT}",
                stack_name=stack_name
            ))
        
        # Check outputs limit
        output_count = counts['Outputs']
        if output_count >= self.OUTPUTS_LIMIT * self.ERROR_THRESHOLD:
            warnings.append(ResourceLimitWarning(
                resource_type='Stack Outputs',
                current_count=output_count,
                limit=self.OUTPUTS_LIMIT,
                severity='error',
                message=f"Stack '{stack_name}' has {output_count} outputs, exceeding limit of {self.OUTPUTS_LIMIT}",
                stack_name=stack_name
            ))
        elif output_count >= self.OUTPUTS_LIMIT * self.WARNING_THRESHOLD:
            warnings.append(ResourceLimitWarning(
                resource_type='Stack Outputs',
                current_count=output_count,
                limit=self.OUTPUTS_LIMIT,
                severity='warning',
                message=f"Stack '{stack_name}' has {output_count} outputs, approaching limit of {self.OUTPUTS_LIMIT}",
                stack_name=stack_name
            ))
        
        # Check parameters limit
        param_count = counts['Parameters']
        if param_count >= self.PARAMETERS_LIMIT * self.ERROR_THRESHOLD:
            warnings.append(ResourceLimitWarning(
                resource_type='Stack Parameters',
                current_count=param_count,
                limit=self.PARAMETERS_LIMIT,
                severity='error',
                message=f"Stack '{stack_name}' has {param_count} parameters, exceeding limit of {self.PARAMETERS_LIMIT}",
                stack_name=stack_name
            ))
        elif param_count >= self.PARAMETERS_LIMIT * self.WARNING_THRESHOLD:
            warnings.append(ResourceLimitWarning(
                resource_type='Stack Parameters',
                current_count=param_count,
                limit=self.PARAMETERS_LIMIT,
                severity='warning',
                message=f"Stack '{stack_name}' has {param_count} parameters, approaching limit of {self.PARAMETERS_LIMIT}",
                stack_name=stack_name
            ))
        
        return warnings
    
    def check_limit_prone_resources(
        self,
        templates: Dict[str, Dict[str, Any]]
    ) -> List[ResourceLimitWarning]:
        """
        Check for limit-prone resources across all templates.
        
        Args:
            templates: Map of stack name to parsed template
            
        Returns:
            List of warnings for limit-prone resources
        """
        warnings = []
        
        # Aggregate counts across all templates
        total_counts: Dict[str, int] = defaultdict(int)
        
        for stack_name, template in templates.items():
            resource_counts = self.count_resources(template)
            for resource_type, count in resource_counts.items():
                total_counts[resource_type] += count
        
        # Check limit-prone resources
        for resource_type, count in total_counts.items():
            if resource_type in self.LIMIT_PRONE_RESOURCES:
                limit_info = self.LIMIT_PRONE_RESOURCES[resource_type]
                account_limit = limit_info['account_limit']
                description = limit_info['description']
                
                # For deployment, we warn if creating many of these resources
                # since we don't know current account usage
                if count >= 10:  # Arbitrary threshold for "many"
                    warnings.append(ResourceLimitWarning(
                        resource_type=resource_type,
                        current_count=count,
                        limit=account_limit,
                        severity='warning',
                        message=f"Deployment creates {count} {resource_type} resources. Account limit: {account_limit} ({description})"
                    ))
        
        return warnings
    
    def check_limits(
        self,
        templates: Dict[str, Dict[str, Any]]
    ) -> ResourceLimitResult:
        """
        Check all templates for limit concerns.
        
        Args:
            templates: Map of stack name to parsed template
            
        Returns:
            ResourceLimitResult with all warnings
        """
        result = ResourceLimitResult(success=True)
        
        # Aggregate resource counts
        all_resources: Dict[str, int] = defaultdict(int)
        
        for stack_name, template in templates.items():
            # Count resources in this stack
            resource_counts = self.count_resources(template)
            stack_total = sum(resource_counts.values())
            result.resources_by_stack[stack_name] = stack_total
            
            # Aggregate by type
            for resource_type, count in resource_counts.items():
                all_resources[resource_type] += count
            
            # Check stack-level limits
            stack_warnings = self.check_stack_limits(template, stack_name)
            result.warnings.extend(stack_warnings)
        
        result.resources_by_type = dict(all_resources)
        result.total_resources = sum(all_resources.values())
        
        # Check limit-prone resources
        limit_prone_warnings = self.check_limit_prone_resources(templates)
        result.warnings.extend(limit_prone_warnings)
        
        # Determine success (errors = failure, warnings = success with warnings)
        has_errors = any(w.severity == 'error' for w in result.warnings)
        if has_errors:
            result.success = False
            result.issues.append("One or more stacks exceed CloudFormation limits")
        
        if result.warnings:
            warning_count = len([w for w in result.warnings if w.severity == 'warning'])
            error_count = len([w for w in result.warnings if w.severity == 'error'])
            if warning_count > 0:
                result.issues.append(f"{warning_count} resource limit warnings")
            if error_count > 0:
                result.issues.append(f"{error_count} resource limit errors")
        
        return result


def get_resource_limit_checker() -> ResourceLimitChecker:
    """Factory function to get a ResourceLimitChecker instance."""
    return ResourceLimitChecker()
