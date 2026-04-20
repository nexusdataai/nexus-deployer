"""
IAM role ARN resolver for IRSA.

IAM roles are pre-created by the cluster admin (create-hardened-eks-cluster.sh).
This module only resolves role ARNs by naming convention -- it makes NO IAM API calls.
"""
import logging
import os
from typing import Dict, Any, Optional

from ..utils.naming import ResourceNaming

logger = logging.getLogger(__name__)


class IAMProvisioner:
    """Resolves pre-created IAM role ARNs by naming convention. No IAM API calls."""

    def __init__(self, naming: ResourceNaming, region: str, account_id: Optional[str] = None, oidc_provider: Optional[str] = None):
        self.naming = naming
        self.region = region
        self.account_id = account_id or os.environ.get("AWS_ACCOUNT_ID", "000000000000")
        self.oidc_provider = oidc_provider or os.environ.get("OIDC_PROVIDER", "")

    async def create_application_role(self, resources: Dict[str, Any] = None) -> Dict[str, Any]:
        """Return the pre-created app role ARN by naming convention. No IAM API call."""
        role_name = self.naming.application_role()
        role_arn = f"arn:aws:iam::{self.account_id}:role/{role_name}"
        logger.info(f"Using pre-created app role: {role_arn}")
        return {"name": role_name, "status": "assumed", "type": "IAM", "arn": role_arn}

    async def delete_application_role(self) -> Dict[str, Any]:
        """IAM role lifecycle is admin-managed. Skipping deletion."""
        role_name = self.naming.application_role()
        logger.info(f"IAM role {role_name} lifecycle is admin-managed — skipping deletion")
        return {"name": role_name, "status": "skipped", "type": "IAM"}
