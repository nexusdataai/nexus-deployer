"""
Installation Tracker Service
Tracks deployment installations with logs and metadata using TinyDB
"""
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from tinydb import Query

from app.services.tinydb_state_manager import TinyDBStateManager, get_state_manager
from app.models.installation import (
    InstallationRecord,
    StackOperationLog,
    InstallationStatus,
    StackOperationStatus,
    StackOperationType,
)

logger = logging.getLogger(__name__)


class InstallationTracker:
    """
    Tracks deployment installations with logs and metadata.
    
    Provides comprehensive tracking of deployment lifecycle including
    installation records, stack operation logs, and query capabilities.
    """
    
    def __init__(self, db_manager: Optional[TinyDBStateManager] = None):
        """
        Initialize installation tracker.
        
        Args:
            db_manager: TinyDB state manager (uses global instance if None)
        """
        self.db_manager = db_manager or get_state_manager()
        self.installations_table = self.db_manager.get_table("installations")
        self.logs_table = self.db_manager.get_table("installation_logs")
        logger.info("InstallationTracker initialized")
    
    def create_installation(
        self,
        capability_name: str,
        capability_version: str,
        environment: str,
        region: str,
        account_id: str,
        strategy: str,
        deploy_frontend: bool,
        deploy_backend: bool
    ) -> str:
        """
        Create new installation record.
        
        Args:
            capability_name: Name of the capability being deployed
            capability_version: Version of the capability
            environment: Target environment (dev, stage, prod)
            region: AWS region
            account_id: AWS account ID
            strategy: Deployment strategy (CLEAN_DEPLOY or UPDATE_EXISTING)
            deploy_frontend: Whether frontend is being deployed
            deploy_backend: Whether backend is being deployed
            
        Returns:
            Unique installation_id (UUID)
        """
        installation_id = str(uuid.uuid4())
        
        record = InstallationRecord(
            installation_id=installation_id,
            capability_name=capability_name,
            capability_version=capability_version,
            environment=environment,
            region=region,
            account_id=account_id,
            strategy=strategy,
            deploy_frontend=deploy_frontend,
            deploy_backend=deploy_backend,
            status=InstallationStatus.PENDING,
            started_at=datetime.utcnow(),
        )
        
        self.installations_table.insert(record.to_dict())
        logger.info(f"Created installation {installation_id} for {capability_name}")
        
        return installation_id
    
    def update_installation(
        self,
        installation_id: str,
        status: Optional[str] = None,
        error: Optional[str] = None,
        frontend_url: Optional[str] = None,
        backend_url: Optional[str] = None,
        cognito_config: Optional[Dict] = None,
        stacks_summary: Optional[Dict[str, int]] = None
    ) -> bool:
        """
        Update installation status and outputs.
        
        Args:
            installation_id: Unique installation identifier
            status: New status (pending, running, completed, failed, cancelled)
            error: Error message if failed
            frontend_url: Frontend URL if deployed
            backend_url: Backend URL if deployed
            cognito_config: Cognito configuration if deployed
            stacks_summary: Summary of stack operations
            
        Returns:
            True if updated successfully
        """
        try:
            InstallQuery = Query()
            existing = self.installations_table.get(
                InstallQuery.installation_id == installation_id
            )
            
            if not existing:
                logger.warning(f"Installation {installation_id} not found")
                return False
            
            updates = {}
            
            if status:
                updates["status"] = status
                
                # Set completed_at and duration for terminal states
                if status in ["completed", "failed", "cancelled"]:
                    completed_at = datetime.utcnow()
                    updates["completed_at"] = completed_at.isoformat()
                    
                    started_at = existing.get("started_at")
                    if started_at:
                        if isinstance(started_at, str):
                            started_at = datetime.fromisoformat(started_at)
                        duration = (completed_at - started_at).total_seconds()
                        updates["duration_seconds"] = int(duration)
            
            if error is not None:
                updates["error"] = error
            
            if frontend_url is not None:
                updates["frontend_url"] = frontend_url
            
            if backend_url is not None:
                updates["backend_url"] = backend_url
            
            if cognito_config is not None:
                updates["cognito_config"] = cognito_config
            
            if stacks_summary is not None:
                updates["stacks_summary"] = stacks_summary
            
            if updates:
                self.installations_table.update(
                    updates,
                    InstallQuery.installation_id == installation_id
                )
                logger.debug(f"Updated installation {installation_id}: {list(updates.keys())}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update installation {installation_id}: {e}")
            return False
    
    def log_stack_operation(
        self,
        installation_id: str,
        stack_name: str,
        stack_type: str,
        operation: str,
        status: str,
        region: str,
        details: Optional[Dict] = None
    ) -> str:
        """
        Log a stack operation.
        
        Args:
            installation_id: Parent installation ID
            stack_name: CloudFormation stack name
            stack_type: Stack type (frontend-global, backend-service, etc.)
            operation: Operation type (create, update, delete, skip)
            status: Operation status (started, completed, failed)
            region: AWS region
            details: Optional additional details
            
        Returns:
            Log entry ID
        """
        log_id = str(uuid.uuid4())
        
        log_entry = StackOperationLog(
            log_id=log_id,
            installation_id=installation_id,
            stack_name=stack_name,
            stack_type=stack_type,
            operation=StackOperationType(operation) if isinstance(operation, str) else operation,
            status=StackOperationStatus(status) if isinstance(status, str) else status,
            region=region,
            started_at=datetime.utcnow(),
        )
        
        log_dict = log_entry.to_dict()
        
        if details:
            log_dict.update(details)
        
        self.logs_table.insert(log_dict)
        logger.debug(f"Logged stack operation: {stack_name} - {operation} - {status}")
        
        return log_id
    
    def update_stack_operation(
        self,
        log_id: str,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        stack_outputs: Optional[Dict] = None,
        cfn_events: Optional[List[Dict]] = None
    ) -> bool:
        """
        Update a stack operation log entry.
        
        Args:
            log_id: Log entry ID
            status: New status
            error_message: Error message if failed
            stack_outputs: Stack outputs if successful
            cfn_events: CloudFormation events if failed
            
        Returns:
            True if updated successfully
        """
        try:
            LogQuery = Query()
            existing = self.logs_table.get(LogQuery.log_id == log_id)
            
            if not existing:
                logger.warning(f"Log entry {log_id} not found")
                return False
            
            updates = {}
            
            if status:
                updates["status"] = status
                
                # Set completed_at and duration for terminal states
                if status in ["completed", "failed", "skipped"]:
                    completed_at = datetime.utcnow()
                    updates["completed_at"] = completed_at.isoformat()
                    
                    started_at = existing.get("started_at")
                    if started_at:
                        if isinstance(started_at, str):
                            started_at = datetime.fromisoformat(started_at)
                        duration = (completed_at - started_at).total_seconds()
                        updates["duration_seconds"] = int(duration)
            
            if error_message is not None:
                updates["error_message"] = error_message
            
            if stack_outputs is not None:
                updates["stack_outputs"] = stack_outputs
            
            if cfn_events is not None:
                updates["cfn_events"] = cfn_events
            
            if updates:
                self.logs_table.update(updates, LogQuery.log_id == log_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update log entry {log_id}: {e}")
            return False
    
    def get_installation(self, installation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get installation with all logs.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            Installation record with logs or None if not found
        """
        try:
            InstallQuery = Query()
            installation = self.installations_table.get(
                InstallQuery.installation_id == installation_id
            )
            
            if not installation:
                return None
            
            # Get associated logs
            LogQuery = Query()
            logs = self.logs_table.search(
                LogQuery.installation_id == installation_id
            )
            
            # Sort logs by started_at
            logs = sorted(logs, key=lambda x: x.get("started_at", ""))
            
            installation["logs"] = logs
            return installation
            
        except Exception as e:
            logger.error(f"Failed to get installation {installation_id}: {e}")
            return None
    
    def get_stack_logs(self, installation_id: str) -> List[Dict[str, Any]]:
        """
        Get stack operation logs for an installation.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            List of stack operation logs
        """
        try:
            LogQuery = Query()
            logs = self.logs_table.search(
                LogQuery.installation_id == installation_id
            )
            
            # Sort by started_at
            return sorted(logs, key=lambda x: x.get("started_at", ""))
            
        except Exception as e:
            logger.error(f"Failed to get stack logs for {installation_id}: {e}")
            return []
    
    def list_installations(
        self,
        capability_name: Optional[str] = None,
        environment: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List installations with filters.
        
        Args:
            capability_name: Filter by capability name
            environment: Filter by environment
            status: Filter by status
            start_date: Filter by start date (inclusive)
            end_date: Filter by end date (inclusive)
            limit: Maximum results to return
            
        Returns:
            List of installation records sorted by started_at descending
        """
        try:
            InstallQuery = Query()
            
            # Build query conditions
            conditions = []
            
            if capability_name:
                conditions.append(InstallQuery.capability_name == capability_name)
            
            if environment:
                conditions.append(InstallQuery.environment == environment)
            
            if status:
                conditions.append(InstallQuery.status == status)
            
            # Execute query
            if conditions:
                query = conditions[0]
                for condition in conditions[1:]:
                    query = query & condition
                installations = self.installations_table.search(query)
            else:
                installations = self.installations_table.all()
            
            # Filter by date range
            if start_date:
                start_iso = start_date.isoformat()
                installations = [
                    i for i in installations
                    if i.get("started_at", "") >= start_iso
                ]
            
            if end_date:
                end_iso = end_date.isoformat()
                installations = [
                    i for i in installations
                    if i.get("started_at", "") <= end_iso
                ]
            
            # Sort by started_at descending
            installations = sorted(
                installations,
                key=lambda x: x.get("started_at", ""),
                reverse=True
            )
            
            # Apply limit
            return installations[:limit]
            
        except Exception as e:
            logger.error(f"Failed to list installations: {e}")
            return []
    
    def create_deletion_record(
        self,
        capability_name: str,
        capability_version: str,
        environment: str,
        region: str,
        account_id: str,
        stacks_deleted: List[str],
        deletion_logs: Optional[str] = None
    ) -> str:
        """
        Create a deletion record to track capability deletions.
        
        Args:
            capability_name: Name of the capability being deleted
            capability_version: Version of the capability (if known)
            environment: Target environment (dev, stage, prod)
            region: AWS region
            account_id: AWS account ID
            stacks_deleted: List of stack names that were deleted
            deletion_logs: Optional deletion logs content
            
        Returns:
            Unique installation_id (UUID) for the deletion record
        """
        installation_id = str(uuid.uuid4())
        
        record = InstallationRecord(
            installation_id=installation_id,
            capability_name=capability_name,
            capability_version=capability_version or "unknown",
            environment=environment,
            region=region,
            account_id=account_id,
            strategy="DELETION",  # Special strategy for deletions
            deploy_frontend=False,  # Not applicable for deletions
            deploy_backend=False,   # Not applicable for deletions
            status=InstallationStatus.DELETED,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),  # Deletion is immediate
            duration_seconds=0,  # Will be updated if we track deletion time
            stacks_summary={
                "deleted": len(stacks_deleted),
                "created": 0,
                "updated": 0,
                "failed": 0,
                "skipped": 0
            }
        )
        
        self.installations_table.insert(record.to_dict())
        
        # Log each deleted stack as a DELETE operation
        for stack_name in stacks_deleted:
            stack_log = StackOperationLog(
                log_id=str(uuid.uuid4()),
                installation_id=installation_id,
                stack_name=stack_name,
                stack_type=self._extract_stack_type(stack_name),
                operation=StackOperationType.DELETE,
                status=StackOperationStatus.COMPLETED,
                region=region,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                duration_seconds=0
            )
            self.logs_table.insert(stack_log.to_dict())
        
        logger.info(f"Created deletion record {installation_id} for {capability_name} ({len(stacks_deleted)} stacks)")
        
        return installation_id
    
    def _extract_stack_type(self, stack_name: str) -> str:
        """Extract stack type from stack name (e.g., 'Call-Processing-prod-backend-service' -> 'backend-service')"""
        # Stack names follow pattern: {capability}-{env}-{stack_type}
        # Find the last occurrence of known stack types
        stack_types = [
            'backend-domain', 'backend-service', 'backend-network', 'backend-storage',
            'backend-regional-cert', 'backend-iam-roles', 'backend-foundation',
            'frontend-regional', 'frontend-cognito', 'frontend-global'
        ]
        
        for stack_type in stack_types:
            if stack_name.endswith(f"-{stack_type}"):
                return stack_type
        
        # Fallback: return the last part after the last hyphen
        parts = stack_name.split('-')
        return '-'.join(parts[-2:]) if len(parts) >= 2 else stack_name
    
    def delete_installation(self, installation_id: str) -> bool:
        """
        Delete an installation and its logs.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            True if deleted successfully
        """
        try:
            InstallQuery = Query()
            LogQuery = Query()
            
            # Delete logs first
            self.logs_table.remove(LogQuery.installation_id == installation_id)
            
            # Delete installation
            self.installations_table.remove(
                InstallQuery.installation_id == installation_id
            )
            
            logger.info(f"Deleted installation {installation_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete installation {installation_id}: {e}")
            return False
    
    def update_stacks_summary(self, installation_id: str) -> bool:
        """
        Update stacks_summary based on logged operations.
        
        Args:
            installation_id: Unique installation identifier
            
        Returns:
            True if updated successfully
        """
        try:
            logs = self.get_stack_logs(installation_id)
            
            summary = {
                "created": 0,
                "updated": 0,
                "failed": 0,
                "skipped": 0
            }
            
            for log in logs:
                operation = log.get("operation", "")
                status = log.get("status", "")
                
                if status == "failed":
                    summary["failed"] += 1
                elif status == "skipped" or operation == "skip":
                    summary["skipped"] += 1
                elif operation == "create" and status == "completed":
                    summary["created"] += 1
                elif operation == "update" and status == "completed":
                    summary["updated"] += 1
            
            return self.update_installation(
                installation_id,
                stacks_summary=summary
            )
            
        except Exception as e:
            logger.error(f"Failed to update stacks summary: {e}")
            return False
    
    # ==================== EKS Installation Methods ====================
    # Feature: pure-eks-deployment
    # Requirements: 9.6
    
    def create_eks_installation(
        self,
        capability_name: str,
        capability_version: str,
        environment: str,
        region: str,
        account_id: str,
        cluster_arn: str,
        namespace: str,
        cr_name: str,
        operator_version: Optional[str] = None
    ) -> str:
        """
        Create installation record for EKS deployment.
        
        Args:
            capability_name: Name of the capability
            capability_version: Version of the capability
            environment: Target environment
            region: AWS region
            account_id: AWS account ID
            cluster_arn: EKS cluster ARN
            namespace: Kubernetes namespace
            cr_name: TotogiCapability CR name
            operator_version: Operator version if known
            
        Returns:
            Unique installation_id
        """
        installation_id = str(uuid.uuid4())
        
        record = InstallationRecord(
            installation_id=installation_id,
            capability_name=capability_name,
            capability_version=capability_version,
            environment=environment,
            region=region,
            account_id=account_id,
            strategy="EKS_OPERATOR",
            deploy_frontend=True,
            deploy_backend=True,
            status=InstallationStatus.PENDING,
            started_at=datetime.utcnow(),
        )
        
        record_dict = record.to_dict()
        
        # Add EKS-specific metadata
        record_dict["deployment_type"] = "eks"
        record_dict["eks_metadata"] = {
            "cluster_arn": cluster_arn,
            "namespace": namespace,
            "cr_name": cr_name,
            "operator_version": operator_version,
        }
        
        self.installations_table.insert(record_dict)
        logger.info(f"Created EKS installation {installation_id} for {capability_name}")
        
        return installation_id
    
    def update_eks_installation(
        self,
        installation_id: str,
        status: Optional[str] = None,
        error: Optional[str] = None,
        frontend_url: Optional[str] = None,
        backend_url: Optional[str] = None,
        resources: Optional[Dict[str, Any]] = None,
        cr_status: Optional[str] = None
    ) -> bool:
        """
        Update EKS installation with status and resources.
        
        Args:
            installation_id: Installation ID
            status: New status
            error: Error message if failed
            frontend_url: Frontend URL
            backend_url: Backend URL
            resources: Dict of provisioned AWS resources
            cr_status: TotogiCapability CR status
            
        Returns:
            True if updated successfully
        """
        try:
            InstallQuery = Query()
            existing = self.installations_table.get(
                InstallQuery.installation_id == installation_id
            )
            
            if not existing:
                logger.warning(f"Installation {installation_id} not found")
                return False
            
            updates = {}
            
            if status:
                updates["status"] = status
                if status in ["completed", "failed", "cancelled"]:
                    completed_at = datetime.utcnow()
                    updates["completed_at"] = completed_at.isoformat()
                    started_at = existing.get("started_at")
                    if started_at:
                        if isinstance(started_at, str):
                            started_at = datetime.fromisoformat(started_at)
                        duration = (completed_at - started_at).total_seconds()
                        updates["duration_seconds"] = int(duration)
            
            if error is not None:
                updates["error"] = error
            
            if frontend_url is not None:
                updates["frontend_url"] = frontend_url
            
            if backend_url is not None:
                updates["backend_url"] = backend_url
            
            # Update EKS metadata
            eks_metadata = existing.get("eks_metadata", {})
            
            if resources is not None:
                eks_metadata["resources"] = resources
            
            if cr_status is not None:
                eks_metadata["cr_status"] = cr_status
            
            if eks_metadata:
                updates["eks_metadata"] = eks_metadata
            
            if updates:
                self.installations_table.update(
                    updates,
                    InstallQuery.installation_id == installation_id
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update EKS installation {installation_id}: {e}")
            return False
    
    def log_eks_resource_operation(
        self,
        installation_id: str,
        resource_type: str,
        resource_name: str,
        operation: str,
        status: str,
        details: Optional[Dict] = None
    ) -> str:
        """
        Log an EKS resource provisioning operation.
        
        Args:
            installation_id: Parent installation ID
            resource_type: Resource type (DynamoDB, S3, IAM, etc.)
            resource_name: Resource name/ARN
            operation: Operation (create, delete)
            status: Status (started, completed, failed)
            details: Optional details
            
        Returns:
            Log entry ID
        """
        log_id = str(uuid.uuid4())
        
        log_entry = {
            "log_id": log_id,
            "installation_id": installation_id,
            "stack_name": f"eks-{resource_type.lower()}",
            "stack_type": resource_type,
            "operation": operation,
            "status": status,
            "region": "",  # EKS resources may span regions
            "started_at": datetime.utcnow().isoformat(),
            "resource_name": resource_name,
            "deployment_type": "eks",
        }
        
        if details:
            log_entry.update(details)
        
        self.logs_table.insert(log_entry)
        logger.debug(f"Logged EKS resource operation: {resource_type}/{resource_name} - {operation}")
        
        return log_id
    
    def get_eks_installations(
        self,
        cluster_arn: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List EKS installations with optional filters.
        
        Args:
            cluster_arn: Filter by cluster ARN
            namespace: Filter by namespace
            limit: Maximum results
            
        Returns:
            List of EKS installation records
        """
        try:
            InstallQuery = Query()
            
            # Get all EKS installations
            installations = self.installations_table.search(
                InstallQuery.deployment_type == "eks"
            )
            
            # Apply filters
            if cluster_arn:
                installations = [
                    i for i in installations
                    if i.get("eks_metadata", {}).get("cluster_arn") == cluster_arn
                ]
            
            if namespace:
                installations = [
                    i for i in installations
                    if i.get("eks_metadata", {}).get("namespace") == namespace
                ]
            
            # Sort by started_at descending
            installations = sorted(
                installations,
                key=lambda x: x.get("started_at", ""),
                reverse=True
            )
            
            return installations[:limit]
            
        except Exception as e:
            logger.error(f"Failed to list EKS installations: {e}")
            return []


# Global instance
_installation_tracker: Optional[InstallationTracker] = None


def get_installation_tracker() -> InstallationTracker:
    """Get global InstallationTracker instance."""
    global _installation_tracker
    if _installation_tracker is None:
        _installation_tracker = InstallationTracker()
    return _installation_tracker


def set_installation_tracker(tracker: Optional[InstallationTracker]):
    """Set global InstallationTracker instance (for testing)."""
    global _installation_tracker
    _installation_tracker = tracker
