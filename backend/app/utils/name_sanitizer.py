"""
Resource name sanitization utilities
Handles capability name sanitization for AWS resource naming conventions
"""
import re


def sanitize_capability_name(capability_name: str, resource_type: str = None) -> str:
    """
    Sanitize capability name for AWS resource naming
    
    Applies the following transformations:
    - Replace spaces with hyphens
    - Replace underscores with hyphens
    - Convert uppercase letters to lowercase
    - Remove invalid characters based on resource type
    
    Args:
        capability_name: The capability name to sanitize
        resource_type: Optional AWS resource type for type-specific rules
        
    Returns:
        Sanitized capability name
    """
    if not capability_name:
        return ""
    
    # Replace spaces with hyphens
    sanitized = capability_name.replace(' ', '-')
    
    # Replace underscores with hyphens
    sanitized = sanitized.replace('_', '-')
    
    # Convert to lowercase
    sanitized = sanitized.lower()
    
    # Remove invalid characters based on resource type
    if resource_type:
        sanitized = _apply_resource_type_rules(sanitized, resource_type)
    else:
        # Default: keep only alphanumeric and hyphens
        sanitized = re.sub(r'[^a-z0-9-]', '', sanitized)
    
    # Remove leading/trailing hyphens
    sanitized = sanitized.strip('-')
    
    # Replace multiple consecutive hyphens with single hyphen
    sanitized = re.sub(r'-+', '-', sanitized)
    
    return sanitized


def _apply_resource_type_rules(name: str, resource_type: str) -> str:
    """
    Apply resource-type-specific naming rules
    
    Args:
        name: Name to sanitize
        resource_type: AWS resource type
        
    Returns:
        Sanitized name according to resource type rules
    """
    # S3 bucket names: lowercase, numbers, hyphens, dots (but we'll avoid dots for simplicity)
    if resource_type == 'AWS::S3::Bucket':
        # S3 buckets: alphanumeric and hyphens only, 3-63 characters
        name = re.sub(r'[^a-z0-9-]', '', name)
        # Ensure it doesn't start or end with hyphen
        name = name.strip('-')
        # Truncate if too long (leave room for environment suffix)
        if len(name) > 50:
            name = name[:50]
        return name
    
    # ALB names: alphanumeric and hyphens, max 32 characters
    elif resource_type == 'AWS::ElasticLoadBalancingV2::LoadBalancer':
        name = re.sub(r'[^a-z0-9-]', '', name)
        name = name.strip('-')
        if len(name) > 25:  # Leave room for environment suffix
            name = name[:25]
        return name
    
    # CloudFront: more flexible, but keep it simple
    elif resource_type == 'AWS::CloudFront::Distribution':
        name = re.sub(r'[^a-z0-9-]', '', name)
        return name
    
    # ECR repository names: lowercase, numbers, hyphens, underscores, slashes
    # But we'll stick to hyphens for consistency
    elif resource_type == 'AWS::ECR::Repository':
        name = re.sub(r'[^a-z0-9-/]', '', name)
        return name
    
    # CloudWatch log group names: more flexible
    elif resource_type == 'AWS::Logs::LogGroup':
        # Log groups can have more characters, but keep it clean
        name = re.sub(r'[^a-z0-9-/._]', '', name)
        return name
    
    # Default: alphanumeric and hyphens only
    else:
        name = re.sub(r'[^a-z0-9-]', '', name)
        return name
