"""
Cognito User Pool Provisioner

Creates and manages AWS Cognito User Pools for application authentication.

Feature: pure-eks-deployment
Requirements: Authentication, User Management
"""

import logging
from typing import Dict, Any, List

from botocore.exceptions import ClientError

from ..utils.aws_vpc_endpoints import vpc_boto3_client
from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


DEFAULT_ADMIN_EMAIL = "admin@nexus.ai"
DEFAULT_ADMIN_PASSWORD = "Pass123!"


class CognitoProvisioner:
    """Provisions Cognito User Pools and App Clients."""
    
    def __init__(self, naming: ResourceNaming, region: str):
        """
        Initialize Cognito provisioner.
        
        Args:
            naming: Resource naming utility
            region: AWS region
        """
        self.naming = naming
        self.region = region
        self.client = vpc_boto3_client("cognito-idp", region_name=region)
    
    def _get_user_pool_name(self) -> str:
        """Get Cognito User Pool name."""
        return f"{self.naming.capability_name}-{self.naming.environment}"
    
    def _get_domain_prefix(self) -> str:
        """Get Cognito domain prefix."""
        # Use account ID if available for uniqueness
        try:
            sts = vpc_boto3_client("sts", region_name=self.region)
            account_id = sts.get_caller_identity()["Account"]
            return f"{self.naming.capability_name}-{self.naming.environment}-{account_id}"
        except:
            # Fallback without account ID
            import random
            suffix = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            return f"{self.naming.capability_name}-{self.naming.environment}-{suffix}"
    
    async def create_user_pool(
        self,
        admin_email: str = None,
        frontend_url: str = None
    ) -> Dict[str, Any]:
        """
        Create Cognito User Pool with RBAC groups.
        
        Args:
            admin_email: Optional admin user email
            frontend_url: Frontend URL for callback configuration
        
        Returns:
            Dict with User Pool configuration
        """
        pool_name = self._get_user_pool_name()
        
        try:
            # Check if User Pool already exists
            pools_response = self.client.list_user_pools(MaxResults=60)
            for pool in pools_response.get('UserPools', []):
                if pool['Name'] == pool_name:
                    logger.info(f"User Pool already exists: {pool_name} ({pool['Id']})")
                    
                    # Get full pool details
                    pool_details = self.client.describe_user_pool(UserPoolId=pool['Id'])
                    user_pool = pool_details['UserPool']
                    
                    return {
                        "status": "exists",
                        "type": "CognitoUserPool",
                        "user_pool_id": user_pool['Id'],
                        "name": user_pool['Name'],
                        "arn": user_pool['Arn'],
                        "domain": user_pool.get('Domain'),
                        "region": self.region
                    }
            
            # Create new User Pool
            logger.info(f"Creating Cognito User Pool: {pool_name}")
            
            response = self.client.create_user_pool(
                PoolName=pool_name,
                Policies={
                    'PasswordPolicy': {
                        'MinimumLength': 8,
                        'RequireUppercase': True,
                        'RequireLowercase': True,
                        'RequireNumbers': True,
                        'RequireSymbols': False
                    }
                },
                AutoVerifiedAttributes=['email'],
                UsernameAttributes=['email'],
                UsernameConfiguration={
                    'CaseSensitive': False
                },
                Schema=[
                    {
                        'Name': 'email',
                        'AttributeDataType': 'String',
                        'Required': True,
                        'Mutable': True
                    },
                    {
                        'Name': 'name',
                        'AttributeDataType': 'String',
                        'Required': False,
                        'Mutable': True
                    }
                ],
                UserPoolTags=self.naming.aws_tags_dict()
            )
            
            user_pool = response['UserPool']
            user_pool_id = user_pool['Id']
            
            logger.info(f"Created User Pool: {user_pool_id}")
            
            # Create RBAC groups
            await self._create_groups(user_pool_id)
            
            return {
                "status": "created",
                "type": "CognitoUserPool",
                "user_pool_id": user_pool_id,
                "name": user_pool['Name'],
                "arn": user_pool['Arn'],
                "region": self.region
            }
            
        except ClientError as e:
            logger.error(f"Failed to create User Pool: {e}")
            return {
                "status": "failed",
                "type": "CognitoUserPool",
                "error": str(e)
            }
    
    async def _create_groups(self, user_pool_id: str):
        """Create RBAC groups in User Pool."""
        groups = [
            ("Admin", "Administrators with full access"),
            ("Executive", "Executives with broad access"),
            ("SalesManager", "Sales managers"),
            ("Rep", "Sales representatives")
        ]
        
        for group_name, description in groups:
            try:
                self.client.create_group(
                    GroupName=group_name,
                    UserPoolId=user_pool_id,
                    Description=description
                )
                logger.info(f"Created group: {group_name}")
            except ClientError as e:
                if e.response['Error']['Code'] == 'GroupExistsException':
                    logger.info(f"Group already exists: {group_name}")
                else:
                    logger.warning(f"Failed to create group {group_name}: {e}")
    
    async def _create_admin_user(
        self, user_pool_id: str, admin_email: str, admin_password: str = DEFAULT_ADMIN_PASSWORD
    ) -> Dict[str, Any]:
        """
        Create or update the initial admin user with a permanent password.
        """
        admin_password = admin_password or DEFAULT_ADMIN_PASSWORD

        try:
            user_exists = False
            try:
                existing = self.client.admin_get_user(
                    UserPoolId=user_pool_id,
                    Username=admin_email
                )
                user_exists = True
                status = existing.get("UserStatus", "UNKNOWN")
                logger.info(f"Admin user already exists: {admin_email} (status: {status})")
            except ClientError as e:
                if e.response['Error']['Code'] != 'UserNotFoundException':
                    raise

            if not user_exists:
                logger.info(f"Creating admin user: {admin_email}")
                self.client.admin_create_user(
                    UserPoolId=user_pool_id,
                    Username=admin_email,
                    UserAttributes=[
                        {"Name": "email", "Value": admin_email},
                        {"Name": "email_verified", "Value": "true"},
                        {"Name": "name", "Value": "Admin"},
                    ],
                    MessageAction="SUPPRESS",
                )
                try:
                    self.client.admin_add_user_to_group(
                        UserPoolId=user_pool_id,
                        Username=admin_email,
                        GroupName="Admin"
                    )
                except ClientError as group_err:
                    if group_err.response['Error']['Code'] != 'ResourceNotFoundException':
                        logger.warning(f"Could not add {admin_email} to Admin group: {group_err}")

            # Set permanent password (no FORCE_CHANGE_PASSWORD on login)
            self.client.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=admin_email,
                Password=admin_password,
                Permanent=True,
            )

            logger.info(f"Admin user ready: {admin_email} (permanent password set)")

            return {
                "status": "created" if not user_exists else "updated",
                "email": admin_email,
                "password": admin_password,
                "temporary_password": admin_password,
                "user_status": "CONFIRMED",
            }

        except ClientError as e:
            logger.error(f"Failed to create admin user {admin_email}: {e}")
            return {
                "status": "failed",
                "email": admin_email,
                "error": str(e)
            }
    
    async def create_app_client(
        self,
        user_pool_id: str,
        callback_urls: List[str] = None,
        logout_urls: List[str] = None
    ) -> Dict[str, Any]:
        """
        Create App Client for User Pool.
        
        Args:
            user_pool_id: User Pool ID
            callback_urls: OAuth callback URLs
            logout_urls: OAuth logout URLs
        
        Returns:
            Dict with App Client configuration
        """
        client_name = f"{self.naming.capability_name}-client-{self.naming.environment}"
        
        # Default callback URLs if not provided
        if not callback_urls:
            callback_urls = [
                "http://localhost:5173/auth/callback",
                "http://localhost:3000/auth/callback"
            ]
        
        if not logout_urls:
            logout_urls = [
                "http://localhost:5173",
                "http://localhost:5173/login",
                "http://localhost:3000",
                "http://localhost:3000/login"
            ]
        
        try:
            # Check if client already exists
            clients_response = self.client.list_user_pool_clients(
                UserPoolId=user_pool_id,
                MaxResults=60
            )
            
            for client in clients_response.get('UserPoolClients', []):
                if client['ClientName'] == client_name:
                    logger.info(f"App Client already exists: {client_name} ({client['ClientId']})")
                    
                    client_details = self.client.describe_user_pool_client(
                        UserPoolId=user_pool_id,
                        ClientId=client['ClientId']
                    )
                    existing_callbacks = client_details['UserPoolClient'].get('CallbackURLs', [])
                    
                    new_urls_needed = set(callback_urls) - set(existing_callbacks)
                    if new_urls_needed:
                        merged_callbacks = list(set(existing_callbacks) | set(callback_urls))
                        merged_logouts = list(set(
                            client_details['UserPoolClient'].get('LogoutURLs', [])
                        ) | set(logout_urls))
                        logger.info(f"Updating callback URLs on existing client (adding {len(new_urls_needed)} new URLs)")
                        self.client.update_user_pool_client(
                            UserPoolId=user_pool_id,
                            ClientId=client['ClientId'],
                            ClientName=client_name,
                            CallbackURLs=merged_callbacks,
                            LogoutURLs=merged_logouts,
                            SupportedIdentityProviders=client_details['UserPoolClient'].get('SupportedIdentityProviders', ['COGNITO']),
                            AllowedOAuthFlows=client_details['UserPoolClient'].get('AllowedOAuthFlows', ['code']),
                            AllowedOAuthScopes=client_details['UserPoolClient'].get('AllowedOAuthScopes', []),
                            AllowedOAuthFlowsUserPoolClient=True,
                        )
                        logger.info(f"Updated callback URLs: {merged_callbacks}")
                        return {
                            "status": "updated",
                            "type": "CognitoAppClient",
                            "client_id": client['ClientId'],
                            "name": client['ClientName'],
                            "callback_urls": merged_callbacks
                        }
                    
                    return {
                        "status": "exists",
                        "type": "CognitoAppClient",
                        "client_id": client['ClientId'],
                        "name": client['ClientName'],
                        "callback_urls": existing_callbacks
                    }
            
            # Create new App Client
            logger.info(f"Creating App Client: {client_name}")
            
            response = self.client.create_user_pool_client(
                UserPoolId=user_pool_id,
                ClientName=client_name,
                GenerateSecret=False,  # Public client (SPA)
                RefreshTokenValidity=30,  # 30 days
                AccessTokenValidity=60,  # 60 minutes
                IdTokenValidity=60,  # 60 minutes
                TokenValidityUnits={
                    'AccessToken': 'minutes',
                    'IdToken': 'minutes',
                    'RefreshToken': 'days'
                },
                ExplicitAuthFlows=[
                    'ALLOW_USER_SRP_AUTH',
                    'ALLOW_REFRESH_TOKEN_AUTH',
                    'ALLOW_ADMIN_USER_PASSWORD_AUTH'  # Required for direct login
                ],
                SupportedIdentityProviders=['COGNITO'],
                CallbackURLs=callback_urls,
                LogoutURLs=logout_urls,
                AllowedOAuthFlows=['code'],
                AllowedOAuthScopes=[
                    'openid',
                    'email',
                    'profile',
                    'aws.cognito.signin.user.admin'  # Required for admin API access
                ],
                AllowedOAuthFlowsUserPoolClient=True,
                PreventUserExistenceErrors='ENABLED'
            )
            
            client = response['UserPoolClient']
            logger.info(f"Created App Client: {client['ClientId']}")
            
            return {
                "status": "created",
                "type": "CognitoAppClient",
                "client_id": client['ClientId'],
                "name": client['ClientName'],
                "callback_urls": callback_urls
            }
            
        except ClientError as e:
            logger.error(f"Failed to create App Client: {e}")
            return {
                "status": "failed",
                "type": "CognitoAppClient",
                "error": str(e)
            }
    
    async def create_domain(
        self,
        user_pool_id: str,
        domain_prefix: str = None
    ) -> Dict[str, Any]:
        """
        Create Cognito domain for User Pool.
        
        Args:
            user_pool_id: User Pool ID
            domain_prefix: Custom domain prefix (optional)
        
        Returns:
            Dict with domain configuration
        """
        domain_prefix = domain_prefix or self._get_domain_prefix()
        
        try:
            # Check if domain already exists
            try:
                domain_desc = self.client.describe_user_pool_domain(Domain=domain_prefix)
                if domain_desc.get('DomainDescription', {}).get('Domain'):
                    logger.info(f"Domain already exists: {domain_prefix}")
                    return {
                        "status": "exists",
                        "type": "CognitoDomain",
                        "domain": domain_prefix,
                        "full_domain": f"{domain_prefix}.auth.{self.region}.amazoncognito.com"
                    }
            except ClientError:
                pass  # Domain doesn't exist, create it
            
            # Create domain
            logger.info(f"Creating Cognito domain: {domain_prefix}")
            
            self.client.create_user_pool_domain(
                Domain=domain_prefix,
                UserPoolId=user_pool_id
            )
            
            logger.info(f"Created domain: {domain_prefix}")
            
            return {
                "status": "created",
                "type": "CognitoDomain",
                "domain": domain_prefix,
                "full_domain": f"{domain_prefix}.auth.{self.region}.amazoncognito.com"
            }
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'InvalidParameterException':
                # Domain might already exist for this pool
                logger.info(f"Domain already configured: {domain_prefix}")
                return {
                    "status": "exists",
                    "type": "CognitoDomain",
                    "domain": domain_prefix,
                    "full_domain": f"{domain_prefix}.auth.{self.region}.amazoncognito.com"
                }
            
            logger.error(f"Failed to create domain: {e}")
            return {
                "status": "failed",
                "type": "CognitoDomain",
                "error": str(e)
            }
    
    async def provision_all(
        self,
        admin_email: str = None,
        admin_password: str = None,
        frontend_url: str = None,
        callback_urls: List[str] = None
    ) -> Dict[str, Any]:
        """
        Provision complete Cognito setup.
        
        Creates:
        1. User Pool with RBAC groups
        2. App Client with OAuth configuration
        3. Cognito domain
        
        Args:
            admin_email: Admin user email (optional)
            frontend_url: Frontend URL for callbacks
            callback_urls: Additional callback URLs
        
        Returns:
            Dict with all Cognito resources created
        """
        results = {
            "user_pool": None,
            "app_client": None,
            "domain": None,
            "cognito_config": {}
        }
        
        try:
            # Step 1: Create User Pool
            user_pool_result = await self.create_user_pool(admin_email, frontend_url)
            results["user_pool"] = user_pool_result
            
            if user_pool_result["status"] in ["failed"]:
                return results
            
            user_pool_id = user_pool_result["user_pool_id"]
            
            # Step 2: Create App Client
            # Build callback URLs
            all_callback_urls = callback_urls or []
            if frontend_url:
                all_callback_urls.append(f"{frontend_url}/auth/callback")
            all_callback_urls.extend([
                "http://localhost:5173/auth/callback",
                "http://localhost:3000/auth/callback"
            ])
            all_callback_urls = list(set(all_callback_urls))  # Remove duplicates
            
            logout_urls = []
            if frontend_url:
                # Add both bare origin and /login suffix for proper logout redirect
                logout_urls.append(frontend_url)
                logout_urls.append(f"{frontend_url.rstrip('/')}/login")
            logout_urls.extend([
                "http://localhost:5173",
                "http://localhost:5173/login",
                "http://localhost:3000",
                "http://localhost:3000/login"
            ])
            logout_urls = list(set(logout_urls))
            
            app_client_result = await self.create_app_client(
                user_pool_id,
                all_callback_urls,
                logout_urls
            )
            results["app_client"] = app_client_result
            
            if app_client_result["status"] in ["failed"]:
                return results
            
            # Step 3: Create Domain
            domain_result = await self.create_domain(user_pool_id)
            results["domain"] = domain_result
            
            # Step 4: Build Cognito configuration for SSM
            results["cognito_config"] = {
                "region": self.region,
                "user_pool_id": user_pool_id,
                "client_id": app_client_result["client_id"],
                "domain": domain_result["domain"],  # Just the prefix
                "redirect_uri": all_callback_urls[0] if all_callback_urls else ""
            }
            
            # Step 5: Create initial admin user if email provided
            if admin_email:
                admin_result = await self._create_admin_user(
                    user_pool_id, admin_email, admin_password or DEFAULT_ADMIN_PASSWORD
                )
                results["admin_user"] = admin_result
            
            logger.info(f"✅ Cognito provisioning complete for {self.naming.capability_name}-{self.naming.environment}")
            logger.info(f"   User Pool: {user_pool_id}")
            logger.info(f"   Client ID: {app_client_result['client_id']}")
            logger.info(f"   Domain: {domain_result['domain']}")
            if admin_email:
                logger.info(f"   Admin User: {admin_email}")
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to provision Cognito: {e}")
            results["error"] = str(e)
            return results
    
    async def delete_all(self, user_pool_id: str = None) -> List[Dict[str, Any]]:
        """
        Delete Cognito resources.
        
        Args:
            user_pool_id: User Pool ID to delete (finds by name if not provided)
        
        Returns:
            List of deletion results
        """
        results = []
        pool_name = self._get_user_pool_name()
        
        try:
            # Find User Pool if ID not provided
            if not user_pool_id:
                pools_response = self.client.list_user_pools(MaxResults=60)
                for pool in pools_response.get('UserPools', []):
                    if pool['Name'] == pool_name:
                        user_pool_id = pool['Id']
                        break
            
            if not user_pool_id:
                logger.info(f"User Pool not found: {pool_name}")
                return results
            
            # Get pool details including domain
            pool_details = self.client.describe_user_pool(UserPoolId=user_pool_id)
            domain = pool_details['UserPool'].get('Domain')
            
            # Delete domain first if exists
            if domain:
                try:
                    self.client.delete_user_pool_domain(
                        Domain=domain,
                        UserPoolId=user_pool_id
                    )
                    logger.info(f"Deleted domain: {domain}")
                    results.append({
                        "type": "CognitoDomain",
                        "name": domain,
                        "status": "deleted"
                    })
                except ClientError as e:
                    logger.warning(f"Failed to delete domain: {e}")
            
            # Delete User Pool
            self.client.delete_user_pool(UserPoolId=user_pool_id)
            logger.info(f"Deleted User Pool: {user_pool_id}")
            
            results.append({
                "type": "CognitoUserPool",
                "name": user_pool_id,
                "status": "deleted"
            })
            
            return results
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.info(f"User Pool not found: {pool_name}")
            else:
                logger.error(f"Failed to delete User Pool: {e}")
            
            return results
