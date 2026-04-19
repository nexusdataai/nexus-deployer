"""
Secrets Manager Provisioner.

Feature: pure-eks-deployment
Requirements: 4.7
"""
import json
import logging
from typing import Dict, List, Any

import boto3
from botocore.exceptions import ClientError

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)

# Default Axway configuration (StarHub UAT / Pre-Production)
# These are the UAT credentials. For production, update the Secrets Manager
# secret with environment-specific values after deployment.
AXWAY_CONFIG_TEMPLATE = {
    "AXWAY_TOKEN_URL": "https://api-uat.starhub.com/auth/realms/api/protocol/openid-connect/token",
    "AXWAY_QUERY_URL": "https://api-uat.starhub.com/common/document-management/pp/v1/retrieve-query-data",
    "AXWAY_CLIENT_ID": "cloudsense-pp",
    "AXWAY_CLIENT_SECRET": "bJCoYYuuySDPkN5b1tR06XnKNRvPhdkw",
    "AXWAY_KEY_ID": "cloudsense-pp",
    "AXWAY_PROVIDER_ORG": "ebg-pp-rhsso",
    "AXWAY_LEAD_CREATE_URL": "https://api-uat.starhub.com/product/stock-management/pp/v1/create-lead",
    "AXWAY_CONTENT_VERSION_URL": "https://api-uat.starhub.com/common/document-management/pp/v1/update-content-version",
    "AXWAY_CONTENT_DOCUMENT_LINK_URL": "https://api-uat.starhub.com/common/document-management/pp/v1/content-document-link",
    "AXWAY_ATTACHMENT_URL": "https://api-uat.starhub.com/common/document-management/pp/v1/attachment",
}


class SecretsProvisioner:
    """Provisions AWS Secrets Manager secrets."""
    
    # Standard application secrets
    SECRET_TYPES = ["api-keys", "wxcc", "openai", "license", "anthropic", "github"]
    
    # BSS Magic secrets (auto-created with defaults on first deploy)
    BSSMAGIC_SECRET_TYPES = ["bssmagic-credentials", "bssmagic-axway-config"]
    
    def __init__(self, naming: ResourceNaming, region: str):
        self.naming = naming
        self.region = region
        self.client = boto3.client("secretsmanager", region_name=region)
    
    async def provision_all(self) -> List[Dict[str, Any]]:
        """Provision all required secrets with placeholder/default values."""
        results = []
        
        # Standard application secrets
        for secret_type in self.SECRET_TYPES:
            secret_name = self.naming.secret_name(secret_type)
            result = await self.create_secret(secret_name, {"placeholder": "update-me"})
            results.append(result)
        
        # BSS Magic secrets (auto-created so infrastructure is ready)
        results.extend(await self.provision_bssmagic_secrets())
        
        return results
    
    async def provision_bssmagic_secrets(self) -> List[Dict[str, Any]]:
        """
        Provision BSS Magic secrets with sensible defaults.
        
        Creates:
        - bssmagic-credentials: Placeholder (binary secret, must be manually uploaded)
        - bssmagic-axway-config: Axway config template with UAT endpoint defaults
        """
        results = []
        
        # Axway config secret (JSON with UAT defaults)
        axway_secret_name = self.naming.secret_name("bssmagic-axway-config")
        result = await self.create_secret(
            axway_secret_name,
            AXWAY_CONFIG_TEMPLATE,
            description="BSS Magic Axway proxy configuration (update CLIENT_ID, CLIENT_SECRET, KEY_ID, PROVIDER_ORG for your environment)"
        )
        results.append(result)
        
        # Credentials secret
        # e2e-deploy.sh uploads the actual binary from bssmagic-image/secrets/credentials.zip
        # This creates a placeholder only if the secret doesn't exist yet (so the infra is ready)
        creds_secret_name = self.naming.secret_name("bssmagic-credentials")
        try:
            self.client.describe_secret(SecretId=creds_secret_name)
            try:
                self.client.tag_resource(SecretId=creds_secret_name, Tags=self.naming.aws_tags())
            except Exception:
                pass
            logger.info(f"Secret {creds_secret_name} already exists")
            results.append({"name": creds_secret_name, "status": "exists", "type": "Secret"})
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                # Create as placeholder — e2e-deploy.sh will overwrite with real binary
                self.client.create_secret(
                    Name=creds_secret_name,
                    SecretString='{"status":"awaiting-upload","instructions":"e2e-deploy.sh uploads credentials.zip automatically from bssmagic-image/secrets/credentials.zip"}',
                    Description="BSS Magic credentials.zip (uploaded by e2e-deploy.sh)",
                    Tags=self.naming.aws_tags(),
                )
                logger.info(f"Created placeholder secret: {creds_secret_name}")
                results.append({"name": creds_secret_name, "status": "created", "type": "Secret"})
            else:
                raise
        
        return results
    
    async def create_secret(self, secret_name: str, value: Dict, description: str = None) -> Dict[str, Any]:
        """Create a secret if it doesn't already exist."""
        try:
            try:
                desc = self.client.describe_secret(SecretId=secret_name)
                try:
                    self.client.tag_resource(SecretId=secret_name, Tags=self.naming.aws_tags())
                except Exception:
                    pass
                logger.info(f"Secret {secret_name} already exists")
                return {"name": secret_name, "status": "exists", "type": "Secret"}
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
            
            desc = description or f"Totogi secret for {self.naming.capability_name}"
            self.client.create_secret(
                Name=secret_name,
                SecretString=json.dumps(value),
                Description=desc,
                Tags=self.naming.aws_tags(),
            )
            logger.info(f"Created secret: {secret_name}")
            return {"name": secret_name, "status": "created", "type": "Secret"}
        except Exception as e:
            logger.error(f"Failed to create secret {secret_name}: {e}")
            return {"name": secret_name, "status": "failed", "error": str(e), "type": "Secret"}
    
    async def delete_all(self) -> List[Dict[str, Any]]:
        """Delete all provisioned secrets (including BSS Magic secrets)."""
        results = []
        all_types = self.SECRET_TYPES + self.BSSMAGIC_SECRET_TYPES
        for secret_type in all_types:
            secret_name = self.naming.secret_name(secret_type)
            result = await self.delete_secret(secret_name)
            results.append(result)
        return results
    
    async def delete_secret(self, secret_name: str) -> Dict[str, Any]:
        """Delete a secret."""
        try:
            self.client.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
            logger.info(f"Deleted secret: {secret_name}")
            return {"name": secret_name, "status": "deleted", "type": "Secret"}
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return {"name": secret_name, "status": "not_found", "type": "Secret"}
            return {"name": secret_name, "status": "failed", "error": str(e), "type": "Secret"}
