"""
Configuration management service
"""
import os
import json
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from app.models.config import (
    EnvironmentConfig,
    InfrastructureConfig,
    DomainConfig,
    FrontendConfig,
    BackendConfig,
    MonitoringConfig,
)
from app.services.preset_service import preset_service


class ConfigurationService:
    """Service for managing environment configurations"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent.parent.parent / "deploy" / "config"
        self.templates_dir = self.base_dir / "templates"
        self.user_dir = self.base_dir / "user"
        
        # Ensure directories exist
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.user_dir.mkdir(parents=True, exist_ok=True)
    
    def get_config(self, capability_name: str, environment: str) -> EnvironmentConfig:
        """
        Get configuration for a capability and environment.
        Priority: User config > Environment preset > Minimal defaults
        """
        # Try user config first
        user_config_path = self.user_dir / f"{capability_name}-{environment}.json"
        if user_config_path.exists():
            with open(user_config_path, 'r') as f:
                config_data = json.load(f)
                return EnvironmentConfig(**config_data)
        
        # Try environment preset from JSON file
        preset = preset_service.get_preset(environment)
        if preset:
            return EnvironmentConfig(**preset)
        
        # Try environment template (legacy)
        template_path = self.templates_dir / f"{environment}-template.yaml"
        if template_path.exists():
            with open(template_path, 'r') as f:
                template_data = yaml.safe_load(f)
                # Extract infrastructure section
                if 'infrastructure' in template_data:
                    return EnvironmentConfig(infrastructure=template_data['infrastructure'])
        
        # Return minimal defaults
        return self._get_default_config(environment)
    
    def save_config(self, capability_name: str, environment: str, config: EnvironmentConfig) -> bool:
        """Save user configuration"""
        try:
            user_config_path = self.user_dir / f"{capability_name}-{environment}.json"
            
            # Convert to dict and save as JSON
            config_dict = config.model_dump()
            
            with open(user_config_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def delete_config(self, capability_name: str, environment: str) -> bool:
        """Delete user configuration (reset to defaults)"""
        try:
            user_config_path = self.user_dir / f"{capability_name}-{environment}.json"
            if user_config_path.exists():
                user_config_path.unlink()
            return True
        except Exception as e:
            print(f"Error deleting config: {e}")
            return False
    
    def _get_default_config(self, environment: str = 'dev') -> EnvironmentConfig:
        """Get default configuration from presets or fallback"""
        from app.models.config import TagsConfig
        
        # Get defaults from preset service
        defaults = preset_service.get_defaults()
        base_domain = defaults.get('base_domain', 'nexus.ai')
        hosted_zone_id = defaults.get('hosted_zone_id', 'Z084501638STQ2EKKSIA')
        
        # Determine subdomains based on environment
        if environment == 'prod':
            frontend_subdomain = 'call'
            backend_subdomain = 'call-api'
        else:
            frontend_subdomain = f'call-{environment}'
            backend_subdomain = f'call-api-{environment}'
        
        return EnvironmentConfig(
            infrastructure=InfrastructureConfig(
                domain=DomainConfig(
                    base=base_domain,
                    frontend_subdomain=frontend_subdomain,
                    backend_subdomain=backend_subdomain,
                    hosted_zone_id=hosted_zone_id
                ),
                frontend=FrontendConfig(),
                backend=BackendConfig(),
                monitoring=MonitoringConfig(),
                tags=TagsConfig()
            )
        )
    
    def merge_with_deployment_request(
        self, 
        config: EnvironmentConfig, 
        request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge infrastructure config with deployment request data.
        Request data takes priority over config.
        """
        # Start with config as base
        merged = config.model_dump()
        
        # Override domain settings if provided in request
        if 'base_domain' in request_data and request_data['base_domain']:
            merged['infrastructure']['domain']['base'] = request_data['base_domain']
        
        if 'hosted_zone_id' in request_data and request_data['hosted_zone_id']:
            merged['infrastructure']['domain']['hosted_zone_id'] = request_data['hosted_zone_id']
        
        if 'frontend_subdomain' in request_data and request_data['frontend_subdomain']:
            merged['infrastructure']['domain']['frontend_subdomain'] = request_data['frontend_subdomain']
        
        # Override ECS settings if provided in request
        if 'container_port' in request_data:
            merged['infrastructure']['backend']['ecs']['container_port'] = request_data['container_port']
        
        if 'health_check_path' in request_data:
            merged['infrastructure']['backend']['ecs']['health_check_path'] = request_data['health_check_path']
        
        if 'task_cpu' in request_data:
            merged['infrastructure']['backend']['ecs']['task_cpu'] = request_data['task_cpu']
        
        if 'task_memory' in request_data:
            merged['infrastructure']['backend']['ecs']['task_memory'] = request_data['task_memory']
        
        if 'desired_count' in request_data:
            merged['infrastructure']['backend']['ecs']['desired_count'] = request_data['desired_count']
        
        return merged


# Global service instance
config_service = ConfigurationService()
