"""
TinyDB-based Deployment State Service
Manages deployment state using TinyDB instead of JSON files
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from tinydb import Query

from .tinydb_state_manager import TinyDBStateManager, get_state_manager, DatabaseError

logger = logging.getLogger(__name__)


class TinyDBDeploymentStateService:
    """Service for managing deployment state using TinyDB"""
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """
        Initialize deployment state service with TinyDB
        
        Args:
            db_manager: TinyDB state manager (uses global instance if None)
        """
        self.db_manager = db_manager or get_state_manager()
        self.deployments_table = self.db_manager.get_table("deployments")
        logger.info("TinyDB Deployment State Service initialized")
    
    def save_deployment_state(
        self,
        capability_name: str,
        environment: str,
        region: str,
        stacks: List[Dict[str, Any]],
        deployment_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save deployment state to TinyDB
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            region: Primary AWS region
            stacks: List of deployed stacks with their details
            deployment_metadata: Additional metadata about the deployment
            
        Returns:
            True if saved successfully
        """
        try:
            DeploymentQuery = Query()
            
            # Generate capability_id from name
            capability_id = capability_name.lower().replace(' ', '-').replace('_', '-')
            capability_id = ''.join(c for c in capability_id if c.isalnum() or c == '-')
            
            # Check if deployment already exists
            existing = self.deployments_table.get(
                (DeploymentQuery.capability_name == capability_name) &
                (DeploymentQuery.environment == environment)
            )
            
            state = {
                "capability_name": capability_name,
                "capability_id": capability_id,
                "environment": environment,
                "region": region,
                "stacks": stacks,
                "last_deployment": datetime.utcnow().isoformat(),
                "metadata": deployment_metadata or {},
                "created_at": existing["created_at"] if existing else datetime.utcnow().isoformat()
            }
            
            if existing:
                # Update existing deployment
                self.deployments_table.update(
                    state,
                    (DeploymentQuery.capability_name == capability_name) &
                    (DeploymentQuery.environment == environment)
                )
                logger.info(f"Updated deployment state: {capability_name} ({environment})")
            else:
                # Insert new deployment
                self.deployments_table.insert(state)
                logger.info(f"Saved new deployment state: {capability_name} ({environment})")
            
            logger.info(f"  Stacks: {len(stacks)}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save deployment state: {str(e)}")
            return False
    
    def load_deployment_state(
        self,
        capability_name: str,
        environment: str
    ) -> Optional[Dict[str, Any]]:
        """
        Load deployment state from TinyDB
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            
        Returns:
            Deployment state dict or None if not found
        """
        try:
            DeploymentQuery = Query()
            
            state = self.deployments_table.get(
                (DeploymentQuery.capability_name == capability_name) &
                (DeploymentQuery.environment == environment)
            )
            
            if state:
                logger.info(f"Loaded deployment state: {capability_name} ({environment})")
                logger.info(f"  Last deployment: {state.get('last_deployment')}")
                logger.info(f"  Stacks: {len(state.get('stacks', []))}")
                return state
            else:
                logger.info(f"No deployment state found: {capability_name} ({environment})")
                return None
            
        except Exception as e:
            logger.error(f"Failed to load deployment state: {str(e)}")
            return None
    
    def delete_deployment_state(
        self,
        capability_name: str,
        environment: str
    ) -> bool:
        """
        Delete deployment state from TinyDB
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            
        Returns:
            True if deleted successfully
        """
        try:
            DeploymentQuery = Query()
            
            removed = self.deployments_table.remove(
                (DeploymentQuery.capability_name == capability_name) &
                (DeploymentQuery.environment == environment)
            )
            
            if removed:
                logger.info(f"Deleted deployment state: {capability_name} ({environment})")
            else:
                logger.info(f"No deployment state to delete: {capability_name} ({environment})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete deployment state: {str(e)}")
            return False
    
    def list_deployments(
        self,
        capability_name: Optional[str] = None,
        environment: Optional[str] = None,
        region: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List deployments with optional filters and pagination
        
        Args:
            capability_name: Filter by capability name
            environment: Filter by environment
            region: Filter by region
            start_date: Filter by start date
            end_date: Filter by end date
            page: Page number (1-indexed)
            page_size: Number of results per page
            
        Returns:
            List of deployment records
        """
        try:
            DeploymentQuery = Query()
            
            # Build query conditions
            conditions = []
            
            if capability_name:
                conditions.append(DeploymentQuery.capability_name == capability_name)
            
            if environment:
                conditions.append(DeploymentQuery.environment == environment)
            
            if region:
                conditions.append(DeploymentQuery.region == region)
            
            if start_date:
                start_iso = start_date.isoformat()
                conditions.append(DeploymentQuery.last_deployment >= start_iso)
            
            if end_date:
                end_iso = end_date.isoformat()
                conditions.append(DeploymentQuery.last_deployment <= end_iso)
            
            # Execute query
            if conditions:
                # Combine all conditions with AND
                query = conditions[0]
                for condition in conditions[1:]:
                    query = query & condition
                deployments = self.deployments_table.search(query)
            else:
                deployments = self.deployments_table.all()
            
            # Apply pagination
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_deployments = deployments[start_idx:end_idx]
            
            logger.info(f"Listed {len(paginated_deployments)} deployments (page {page}, total {len(deployments)})")
            return paginated_deployments
            
        except Exception as e:
            logger.error(f"Failed to list deployments: {str(e)}")
            return []
    
    def delete_stack_from_deployment(
        self,
        capability_name: str,
        environment: str,
        stack_name: str
    ) -> bool:
        """
        Delete a specific stack from deployment state
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            stack_name: Name of the stack to delete
            
        Returns:
            True if deleted successfully
        """
        try:
            state = self.load_deployment_state(capability_name, environment)
            if not state:
                logger.warning(f"No deployment state found: {capability_name} ({environment})")
                return False
            
            # Filter out the stack to delete
            stacks = state.get("stacks", [])
            original_count = len(stacks)
            stacks = [s for s in stacks if s.get("stack_name") != stack_name]
            
            if len(stacks) == original_count:
                logger.warning(f"Stack not found in deployment: {stack_name}")
                return False
            
            # Save updated state
            return self.save_deployment_state(
                capability_name,
                environment,
                state.get("region"),
                stacks,
                state.get("metadata")
            )
            
        except Exception as e:
            logger.error(f"Failed to delete stack from deployment: {str(e)}")
            return False
    
    def get_stack_from_deployment(
        self,
        capability_name: str,
        environment: str,
        stack_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get specific stack details from deployment
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            stack_name: Name of the stack
            
        Returns:
            Stack details or None if not found
        """
        try:
            state = self.load_deployment_state(capability_name, environment)
            if not state:
                return None
            
            stacks = state.get("stacks", [])
            for stack in stacks:
                if stack.get("stack_name") == stack_name:
                    return stack
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get stack from deployment: {str(e)}")
            return None
    
    def update_stack_in_state(
        self,
        capability_name: str,
        environment: str,
        stack_name: str,
        stack_updates: Dict[str, Any]
    ) -> bool:
        """
        Update specific stack information in the deployment state
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            stack_name: Name of the stack to update
            stack_updates: Dict with fields to update
            
        Returns:
            True if updated successfully
        """
        try:
            state = self.load_deployment_state(capability_name, environment)
            if not state:
                logger.warning(f"No deployment state found to update stack: {capability_name} ({environment})")
                return False
            
            # Find and update the stack
            stacks = state.get("stacks", [])
            stack_found = False
            
            for stack in stacks:
                if stack.get("stack_name") == stack_name:
                    stack.update(stack_updates)
                    stack["last_updated"] = datetime.utcnow().isoformat()
                    stack_found = True
                    break
            
            if not stack_found:
                logger.warning(f"Stack not found in deployment state: {stack_name}")
                return False
            
            # Save updated state
            return self.save_deployment_state(
                capability_name,
                environment,
                state.get("region"),
                stacks,
                state.get("metadata")
            )
            
        except Exception as e:
            logger.error(f"Failed to update stack in state: {str(e)}")
            return False
    
    def get_deployment_history(
        self,
        capability_name: str,
        environment: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get deployment history for a capability/environment
        
        Note: Current implementation returns single latest deployment.
        Future enhancement: Store deployment history in separate table.
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            limit: Maximum number of history entries
            
        Returns:
            List of deployment history records
        """
        try:
            state = self.load_deployment_state(capability_name, environment)
            
            if state:
                return [state]
            else:
                return []
            
        except Exception as e:
            logger.error(f"Failed to get deployment history: {str(e)}")
            return []
    
    # ==================== EKS Deployment Methods ====================
    # Feature: pure-eks-deployment
    # Requirements: 9.1, 9.6
    
    def save_eks_deployment_state(
        self,
        capability_name: str,
        environment: str,
        region: str,
        cluster_arn: str,
        namespace: str,
        cr_name: str,
        resources: Dict[str, Any],
        deployment_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save EKS deployment state to TinyDB.
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            region: AWS region
            cluster_arn: EKS cluster ARN
            namespace: Kubernetes namespace
            cr_name: NexusCapability CR name
            resources: Dict of provisioned AWS resources
            deployment_metadata: Additional metadata
            
        Returns:
            True if saved successfully
        """
        try:
            DeploymentQuery = Query()
            
            capability_id = capability_name.lower().replace(' ', '-').replace('_', '-')
            capability_id = ''.join(c for c in capability_id if c.isalnum() or c == '-')
            
            existing = self.deployments_table.get(
                (DeploymentQuery.capability_name == capability_name) &
                (DeploymentQuery.environment == environment)
            )
            
            state = {
                "capability_name": capability_name,
                "capability_id": capability_id,
                "environment": environment,
                "region": region,
                "deployment_type": "eks",
                "cluster_arn": cluster_arn,
                "namespace": namespace,
                "cr_name": cr_name,
                "resources": resources,
                "stacks": [],  # Empty for EKS deployments
                "last_deployment": datetime.utcnow().isoformat(),
                "metadata": deployment_metadata or {},
                "created_at": existing["created_at"] if existing else datetime.utcnow().isoformat()
            }
            
            if existing:
                self.deployments_table.update(
                    state,
                    (DeploymentQuery.capability_name == capability_name) &
                    (DeploymentQuery.environment == environment)
                )
                logger.info(f"Updated EKS deployment state: {capability_name} ({environment})")
            else:
                self.deployments_table.insert(state)
                logger.info(f"Saved new EKS deployment state: {capability_name} ({environment})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save EKS deployment state: {str(e)}")
            return False
    
    def get_eks_deployments(
        self,
        cluster_arn: Optional[str] = None,
        namespace: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List EKS deployments with optional filters.
        
        Args:
            cluster_arn: Filter by EKS cluster ARN
            namespace: Filter by Kubernetes namespace
            
        Returns:
            List of EKS deployment records
        """
        try:
            DeploymentQuery = Query()
            
            conditions = [DeploymentQuery.deployment_type == "eks"]
            
            if cluster_arn:
                conditions.append(DeploymentQuery.cluster_arn == cluster_arn)
            
            if namespace:
                conditions.append(DeploymentQuery.namespace == namespace)
            
            query = conditions[0]
            for condition in conditions[1:]:
                query = query & condition
            
            deployments = self.deployments_table.search(query)
            logger.info(f"Found {len(deployments)} EKS deployments")
            return deployments
            
        except Exception as e:
            logger.error(f"Failed to list EKS deployments: {str(e)}")
            return []
    
    def update_eks_resources(
        self,
        capability_name: str,
        environment: str,
        resources: Dict[str, Any]
    ) -> bool:
        """
        Update the resources dict for an EKS deployment.
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            resources: Updated resources dict
            
        Returns:
            True if updated successfully
        """
        try:
            state = self.load_deployment_state(capability_name, environment)
            if not state:
                logger.warning(f"No deployment state found: {capability_name} ({environment})")
                return False
            
            if state.get("deployment_type") != "eks":
                logger.warning(f"Deployment is not EKS type: {capability_name} ({environment})")
                return False
            
            DeploymentQuery = Query()
            self.deployments_table.update(
                {"resources": resources, "last_deployment": datetime.utcnow().isoformat()},
                (DeploymentQuery.capability_name == capability_name) &
                (DeploymentQuery.environment == environment)
            )
            
            logger.info(f"Updated EKS resources: {capability_name} ({environment})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update EKS resources: {str(e)}")
            return False
    
    def is_eks_deployment(self, capability_name: str, environment: str) -> bool:
        """
        Check if a deployment is an EKS deployment.
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            
        Returns:
            True if deployment is EKS type
        """
        try:
            state = self.load_deployment_state(capability_name, environment)
            return state is not None and state.get("deployment_type") == "eks"
        except Exception:
            return False


# Global instance
tinydb_deployment_state_service = TinyDBDeploymentStateService()
