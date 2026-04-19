"""
Cognito Drift Detector Service

Detects configuration drift between deployed Cognito User Pool and CloudFormation template.
Compares password policy, MFA configuration, app client settings, and custom attributes.
"""
import logging
import json
import yaml
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

from app.utils.aws_vpc_endpoints import merge_vpc_boto3_kwargs
from app.models.cognito_models import DriftItem, DriftDetectionResult


logger = logging.getLogger(__name__)


class CognitoDriftDetector:
    """
    Service for detecting configuration drift in Cognito User Pools.
    
    Compares deployed Cognito configuration with CloudFormation template
    to identify any differences that may have occurred through manual changes
    or other modifications outside of the deployment process.
    """

    # Categories of settings to check for drift
    DRIFT_CATEGORIES = [
        'password_policy',
        'mfa',
        'app_client',
        'custom_attributes'
    ]

    def __init__(self, credentials: Optional[Dict[str, str]] = None):
        """
        Initialize the drift detector.
        
        Args:
            credentials: Optional AWS credentials dict
        """
        self.credentials = credentials or {}
        self._clients_cache: Dict[str, Any] = {}

    def _get_client(self, service: str, region: str) -> Any:
        """Get a boto3 client for the specified service and region."""
        cache_key = f"{service}:{region}"
        
        if cache_key not in self._clients_cache:
            kw = {"region_name": region, **self.credentials}
            self._clients_cache[cache_key] = boto3.client(
                service, **merge_vpc_boto3_kwargs(service, region, kw)
            )
        
        return self._clients_cache[cache_key]

    def detect_drift(
        self,
        user_pool_id: str,
        region: str,
        template_path: Path
    ) -> DriftDetectionResult:
        """
        Compare deployed Cognito configuration with template.
        
        Args:
            user_pool_id: Cognito User Pool ID
            region: AWS region
            template_path: Path to CloudFormation template
            
        Returns:
            DriftDetectionResult with drift items if any found
        """
        detection_timestamp = datetime.utcnow()
        drift_items: List[DriftItem] = []
        
        try:
            # Get deployed configuration
            deployed_config = self._get_deployed_config(user_pool_id, region)
            
            # Parse template configuration
            template_config = self._parse_template_config(template_path)
            
            # Compare password policy
            password_drift = self._compare_password_policy(
                deployed_config.get('password_policy', {}),
                template_config.get('password_policy', {})
            )
            drift_items.extend(password_drift)
            
            # Compare MFA configuration
            mfa_drift = self._compare_mfa_config(
                deployed_config.get('mfa', {}),
                template_config.get('mfa', {})
            )
            drift_items.extend(mfa_drift)
            
            # Compare app client settings
            app_client_drift = self._compare_app_client(
                deployed_config.get('app_client', {}),
                template_config.get('app_client', {})
            )
            drift_items.extend(app_client_drift)
            
            # Compare custom attributes
            attributes_drift = self._compare_custom_attributes(
                deployed_config.get('custom_attributes', []),
                template_config.get('custom_attributes', [])
            )
            drift_items.extend(attributes_drift)
            
            logger.info(
                f"[DRIFT] Drift detection complete for {user_pool_id}: "
                f"{len(drift_items)} drift items found"
            )
            
            return DriftDetectionResult(
                has_drift=len(drift_items) > 0,
                drift_items=drift_items,
                detection_timestamp=detection_timestamp,
                categories_checked=self.DRIFT_CATEGORIES
            )
            
        except Exception as e:
            # Drift detection failures should not block the workflow
            error_message = f"Drift detection failed: {str(e)}"
            logger.warning(f"[DRIFT] {error_message}")
            
            return DriftDetectionResult(
                has_drift=False,
                drift_items=[],
                detection_timestamp=detection_timestamp,
                error_message=error_message,
                categories_checked=self.DRIFT_CATEGORIES
            )

    def _get_deployed_config(
        self,
        user_pool_id: str,
        region: str
    ) -> Dict[str, Any]:
        """
        Get the deployed Cognito configuration.
        
        Args:
            user_pool_id: User Pool ID
            region: AWS region
            
        Returns:
            Dict with deployed configuration
        """
        cognito_client = self._get_client('cognito-idp', region)
        
        # Get User Pool details
        response = cognito_client.describe_user_pool(UserPoolId=user_pool_id)
        user_pool = response.get('UserPool', {})
        
        config = {
            'password_policy': self._extract_password_policy(user_pool),
            'mfa': self._extract_mfa_config(user_pool),
            'custom_attributes': self._extract_custom_attributes(user_pool),
            'app_client': {}
        }
        
        # Get App Client details (first client)
        try:
            clients_response = cognito_client.list_user_pool_clients(
                UserPoolId=user_pool_id,
                MaxResults=1
            )
            clients = clients_response.get('UserPoolClients', [])
            
            if clients:
                client_id = clients[0].get('ClientId')
                client_response = cognito_client.describe_user_pool_client(
                    UserPoolId=user_pool_id,
                    ClientId=client_id
                )
                config['app_client'] = self._extract_app_client_config(
                    client_response.get('UserPoolClient', {})
                )
        except ClientError as e:
            logger.warning(f"[DRIFT] Could not get app client details: {e}")
        
        return config

    def _extract_password_policy(self, user_pool: Dict[str, Any]) -> Dict[str, Any]:
        """Extract password policy from User Pool."""
        policies = user_pool.get('Policies', {})
        password_policy = policies.get('PasswordPolicy', {})
        
        return {
            'MinimumLength': password_policy.get('MinimumLength', 8),
            'RequireUppercase': password_policy.get('RequireUppercase', True),
            'RequireLowercase': password_policy.get('RequireLowercase', True),
            'RequireNumbers': password_policy.get('RequireNumbers', True),
            'RequireSymbols': password_policy.get('RequireSymbols', True),
            'TemporaryPasswordValidityDays': password_policy.get(
                'TemporaryPasswordValidityDays', 7
            )
        }

    def _extract_mfa_config(self, user_pool: Dict[str, Any]) -> Dict[str, Any]:
        """Extract MFA configuration from User Pool."""
        return {
            'MfaConfiguration': user_pool.get('MfaConfiguration', 'OFF'),
            'SmsAuthenticationMessage': user_pool.get('SmsAuthenticationMessage', ''),
            'SoftwareTokenMfaEnabled': self._is_software_token_enabled(user_pool)
        }

    def _is_software_token_enabled(self, user_pool: Dict[str, Any]) -> bool:
        """Check if software token MFA is enabled."""
        mfa_config = user_pool.get('MfaConfiguration', 'OFF')
        if mfa_config == 'OFF':
            return False
        
        # Check if TOTP is in enabled MFA methods
        enabled_mfas = user_pool.get('EnabledMfas', [])
        return 'SOFTWARE_TOKEN_MFA' in enabled_mfas

    def _extract_custom_attributes(self, user_pool: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract custom attributes from User Pool."""
        schema = user_pool.get('SchemaAttributes', [])
        custom_attrs = []
        
        for attr in schema:
            name = attr.get('Name', '')
            if name.startswith('custom:'):
                custom_attrs.append({
                    'Name': name,
                    'AttributeDataType': attr.get('AttributeDataType', 'String'),
                    'Mutable': attr.get('Mutable', True),
                    'Required': attr.get('Required', False)
                })
        
        return custom_attrs

    def _extract_app_client_config(self, client: Dict[str, Any]) -> Dict[str, Any]:
        """Extract App Client configuration."""
        return {
            'ExplicitAuthFlows': sorted(client.get('ExplicitAuthFlows', [])),
            'AllowedOAuthFlows': sorted(client.get('AllowedOAuthFlows', [])),
            'AllowedOAuthScopes': sorted(client.get('AllowedOAuthScopes', [])),
            'AllowedOAuthFlowsUserPoolClient': client.get(
                'AllowedOAuthFlowsUserPoolClient', False
            ),
            'PreventUserExistenceErrors': client.get(
                'PreventUserExistenceErrors', 'LEGACY'
            ),
            'EnableTokenRevocation': client.get('EnableTokenRevocation', True)
        }

    def _parse_template_config(self, template_path: Path) -> Dict[str, Any]:
        """
        Parse Cognito configuration from CloudFormation template.
        
        Args:
            template_path: Path to template file
            
        Returns:
            Dict with template configuration
        """
        if not template_path.exists():
            logger.warning(f"[DRIFT] Template not found: {template_path}")
            return {}
        
        try:
            with open(template_path, 'r') as f:
                if template_path.suffix in ['.yaml', '.yml']:
                    template = yaml.safe_load(f)
                else:
                    template = json.load(f)
            
            return self._extract_template_cognito_config(template)
            
        except Exception as e:
            logger.warning(f"[DRIFT] Error parsing template: {e}")
            return {}

    def _extract_template_cognito_config(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Cognito configuration from CloudFormation template."""
        config = {
            'password_policy': {},
            'mfa': {},
            'app_client': {},
            'custom_attributes': []
        }
        
        resources = template.get('Resources', {})
        
        for resource_name, resource in resources.items():
            resource_type = resource.get('Type', '')
            properties = resource.get('Properties', {})
            
            if resource_type == 'AWS::Cognito::UserPool':
                # Extract password policy
                policies = properties.get('Policies', {})
                password_policy = policies.get('PasswordPolicy', {})
                config['password_policy'] = {
                    'MinimumLength': password_policy.get('MinimumLength', 8),
                    'RequireUppercase': password_policy.get('RequireUppercase', True),
                    'RequireLowercase': password_policy.get('RequireLowercase', True),
                    'RequireNumbers': password_policy.get('RequireNumbers', True),
                    'RequireSymbols': password_policy.get('RequireSymbols', True),
                    'TemporaryPasswordValidityDays': password_policy.get(
                        'TemporaryPasswordValidityDays', 7
                    )
                }
                
                # Extract MFA config
                config['mfa'] = {
                    'MfaConfiguration': properties.get('MfaConfiguration', 'OFF'),
                    'SmsAuthenticationMessage': properties.get(
                        'SmsAuthenticationMessage', ''
                    ),
                    'SoftwareTokenMfaEnabled': self._template_has_software_token(
                        properties
                    )
                }
                
                # Extract custom attributes
                schema = properties.get('Schema', [])
                for attr in schema:
                    name = attr.get('Name', '')
                    if name.startswith('custom:') or attr.get('AttributeDataType'):
                        config['custom_attributes'].append({
                            'Name': f"custom:{name}" if not name.startswith('custom:') else name,
                            'AttributeDataType': attr.get('AttributeDataType', 'String'),
                            'Mutable': attr.get('Mutable', True),
                            'Required': attr.get('Required', False)
                        })
            
            elif resource_type == 'AWS::Cognito::UserPoolClient':
                config['app_client'] = {
                    'ExplicitAuthFlows': sorted(
                        properties.get('ExplicitAuthFlows', [])
                    ),
                    'AllowedOAuthFlows': sorted(
                        properties.get('AllowedOAuthFlows', [])
                    ),
                    'AllowedOAuthScopes': sorted(
                        properties.get('AllowedOAuthScopes', [])
                    ),
                    'AllowedOAuthFlowsUserPoolClient': properties.get(
                        'AllowedOAuthFlowsUserPoolClient', False
                    ),
                    'PreventUserExistenceErrors': properties.get(
                        'PreventUserExistenceErrors', 'LEGACY'
                    ),
                    'EnableTokenRevocation': properties.get(
                        'EnableTokenRevocation', True
                    )
                }
        
        return config

    def _template_has_software_token(self, properties: Dict[str, Any]) -> bool:
        """Check if template enables software token MFA."""
        mfa_config = properties.get('MfaConfiguration', 'OFF')
        if mfa_config == 'OFF':
            return False
        
        enabled_mfas = properties.get('EnabledMfas', [])
        return 'SOFTWARE_TOKEN_MFA' in enabled_mfas

    def _compare_password_policy(
        self,
        deployed: Dict[str, Any],
        template: Dict[str, Any]
    ) -> List[DriftItem]:
        """Compare password policy settings."""
        drift_items = []
        
        if not template:
            return drift_items
        
        for key in ['MinimumLength', 'RequireUppercase', 'RequireLowercase',
                    'RequireNumbers', 'RequireSymbols', 'TemporaryPasswordValidityDays']:
            deployed_value = deployed.get(key)
            template_value = template.get(key)
            
            if deployed_value is not None and template_value is not None:
                if str(deployed_value) != str(template_value):
                    drift_items.append(DriftItem(
                        setting_name=key,
                        template_value=str(template_value),
                        deployed_value=str(deployed_value),
                        category='password_policy'
                    ))
        
        return drift_items

    def _compare_mfa_config(
        self,
        deployed: Dict[str, Any],
        template: Dict[str, Any]
    ) -> List[DriftItem]:
        """Compare MFA configuration."""
        drift_items = []
        
        if not template:
            return drift_items
        
        for key in ['MfaConfiguration', 'SoftwareTokenMfaEnabled']:
            deployed_value = deployed.get(key)
            template_value = template.get(key)
            
            if deployed_value is not None and template_value is not None:
                if str(deployed_value) != str(template_value):
                    drift_items.append(DriftItem(
                        setting_name=key,
                        template_value=str(template_value),
                        deployed_value=str(deployed_value),
                        category='mfa'
                    ))
        
        return drift_items

    def _compare_app_client(
        self,
        deployed: Dict[str, Any],
        template: Dict[str, Any]
    ) -> List[DriftItem]:
        """Compare App Client settings."""
        drift_items = []
        
        if not template:
            return drift_items
        
        for key in ['ExplicitAuthFlows', 'AllowedOAuthFlows', 'AllowedOAuthScopes',
                    'AllowedOAuthFlowsUserPoolClient', 'PreventUserExistenceErrors',
                    'EnableTokenRevocation']:
            deployed_value = deployed.get(key)
            template_value = template.get(key)
            
            if deployed_value is not None and template_value is not None:
                # Convert lists to sorted strings for comparison
                if isinstance(deployed_value, list):
                    deployed_str = ','.join(sorted(deployed_value))
                    template_str = ','.join(sorted(template_value))
                else:
                    deployed_str = str(deployed_value)
                    template_str = str(template_value)
                
                if deployed_str != template_str:
                    drift_items.append(DriftItem(
                        setting_name=key,
                        template_value=template_str,
                        deployed_value=deployed_str,
                        category='app_client'
                    ))
        
        return drift_items

    def _compare_custom_attributes(
        self,
        deployed: List[Dict[str, Any]],
        template: List[Dict[str, Any]]
    ) -> List[DriftItem]:
        """Compare custom attributes."""
        drift_items = []
        
        # Create lookup by name
        deployed_by_name = {attr['Name']: attr for attr in deployed}
        template_by_name = {attr['Name']: attr for attr in template}
        
        # Check for attributes in template but not deployed
        for name, template_attr in template_by_name.items():
            if name not in deployed_by_name:
                drift_items.append(DriftItem(
                    setting_name=f"Attribute:{name}",
                    template_value="defined",
                    deployed_value="missing",
                    category='custom_attributes'
                ))
            else:
                # Compare attribute properties
                deployed_attr = deployed_by_name[name]
                for key in ['AttributeDataType', 'Mutable', 'Required']:
                    if str(template_attr.get(key)) != str(deployed_attr.get(key)):
                        drift_items.append(DriftItem(
                            setting_name=f"Attribute:{name}:{key}",
                            template_value=str(template_attr.get(key)),
                            deployed_value=str(deployed_attr.get(key)),
                            category='custom_attributes'
                        ))
        
        return drift_items

    def get_drift_summary(self, result: DriftDetectionResult) -> str:
        """
        Generate a human-readable drift summary.
        
        Args:
            result: DriftDetectionResult
            
        Returns:
            Summary string
        """
        if result.error_message:
            return f"Drift detection failed: {result.error_message}"
        
        if not result.has_drift:
            return "No configuration drift detected. Deployed configuration matches template."
        
        # Group by category
        by_category: Dict[str, List[DriftItem]] = {}
        for item in result.drift_items:
            if item.category not in by_category:
                by_category[item.category] = []
            by_category[item.category].append(item)
        
        lines = [f"Configuration drift detected ({len(result.drift_items)} items):"]
        
        for category, items in by_category.items():
            lines.append(f"\n  {category.replace('_', ' ').title()}:")
            for item in items:
                lines.append(
                    f"    - {item.setting_name}: "
                    f"template={item.template_value}, deployed={item.deployed_value}"
                )
        
        return '\n'.join(lines)


def get_cognito_drift_detector(
    credentials: Optional[Dict[str, str]] = None
) -> CognitoDriftDetector:
    """
    Factory function to create a CognitoDriftDetector instance.
    
    Args:
        credentials: Optional AWS credentials
        
    Returns:
        Configured CognitoDriftDetector instance
    """
    return CognitoDriftDetector(credentials=credentials)
