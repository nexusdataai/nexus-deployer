"""
Workflow Classifier Service

Determines whether a deployment should follow the install workflow (full deployment)
or update workflow (preserve existing data like Cognito users).
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from app.models.workflow_classification import WorkflowType, WorkflowClassification
from app.models.stack_detection import DeploymentStrategy


logger = logging.getLogger(__name__)


class WorkflowClassifier:
    """
    Classifies deployment workflows as install or update based on
    existing deployment detection and user strategy selection.
    """

    def __init__(self, stack_detection_service=None, deployment_state_service=None):
        """
        Initialize the workflow classifier.
        
        Args:
            stack_detection_service: Service for detecting existing stacks
            deployment_state_service: Service for querying deployment state from TinyDB
        """
        self.stack_detection_service = stack_detection_service
        self.deployment_state_service = deployment_state_service

    def classify_workflow(
        self,
        capability_name: str,
        environment: str,
        region: str,
        user_strategy: Optional[str] = None,
        existing_stacks: Optional[list] = None
    ) -> WorkflowClassification:
        """
        Classify the deployment as install or update workflow.
        
        Classification Rules:
        1. No existing deployment record → INSTALL workflow
        2. Existing record + "Clean Deploy" strategy → INSTALL workflow
        3. Existing record + "Update Existing" strategy → UPDATE workflow
        
        Args:
            capability_name: Name of the capability being deployed
            environment: Target environment (dev, stage, prod)
            region: AWS region
            user_strategy: User-selected strategy (clean_deploy or update_existing)
            existing_stacks: Pre-detected existing stacks (optional, will detect if not provided)
            
        Returns:
            WorkflowClassification with workflow type and metadata
        """
        timestamp = datetime.utcnow()
        
        # Get existing stacks if not provided
        if existing_stacks is None:
            existing_stacks = self._detect_existing_stacks(
                capability_name, environment, region
            )
        
        # Determine workflow type based on rules
        workflow_type, reason = self._determine_workflow_type(
            existing_stacks=existing_stacks,
            user_strategy=user_strategy
        )
        
        classification = WorkflowClassification(
            workflow_type=workflow_type,
            capability_name=capability_name,
            environment=environment,
            region=region,
            existing_stacks=existing_stacks,
            strategy_selected=user_strategy,
            classification_timestamp=timestamp,
            reason=reason
        )
        
        # Log the classification
        self._log_classification(classification)
        
        return classification

    def _detect_existing_stacks(
        self,
        capability_name: str,
        environment: str,
        region: str
    ) -> list:
        """
        Detect existing stacks for the capability.
        
        Args:
            capability_name: Name of the capability
            environment: Target environment
            region: AWS region
            
        Returns:
            List of existing stack names
        """
        if self.deployment_state_service is None:
            logger.warning("No deployment state service configured, assuming no existing stacks")
            return []
        
        try:
            # Query TinyDB for existing deployment record
            deployment_record = self.deployment_state_service.get_deployment_state(
                capability_name=capability_name,
                environment=environment
            )
            
            if deployment_record and deployment_record.get('stacks'):
                stacks = deployment_record.get('stacks', [])
                # Extract stack names from the record
                if isinstance(stacks, list):
                    return [s.get('stack_name', s) if isinstance(s, dict) else s for s in stacks]
                return []
            
            return []
            
        except Exception as e:
            logger.warning(f"Error detecting existing stacks: {e}")
            return []

    def _determine_workflow_type(
        self,
        existing_stacks: list,
        user_strategy: Optional[str]
    ) -> tuple:
        """
        Determine the workflow type based on existing stacks and user strategy.
        
        Args:
            existing_stacks: List of existing stack names
            user_strategy: User-selected deployment strategy
            
        Returns:
            Tuple of (WorkflowType, reason_string)
        """
        has_existing_stacks = len(existing_stacks) > 0
        
        # Rule 1: No existing deployment → INSTALL
        if not has_existing_stacks:
            return (
                WorkflowType.INSTALL,
                "No existing deployment found - proceeding with fresh install"
            )
        
        # Rule 2: Existing + Clean Deploy → INSTALL
        if user_strategy == DeploymentStrategy.CLEAN_DEPLOY.value or user_strategy == "clean_deploy":
            return (
                WorkflowType.INSTALL,
                f"User selected clean deploy - will remove {len(existing_stacks)} existing stacks before install"
            )
        
        # Rule 3: Existing + Update Existing → UPDATE
        if user_strategy == DeploymentStrategy.UPDATE_EXISTING.value or user_strategy == "update_existing":
            return (
                WorkflowType.UPDATE,
                f"User selected update existing - will preserve data in {len(existing_stacks)} stacks"
            )
        
        # Default: If existing stacks but no strategy selected, default to UPDATE for safety
        if has_existing_stacks and user_strategy is None:
            return (
                WorkflowType.UPDATE,
                f"Existing deployment detected with {len(existing_stacks)} stacks - defaulting to update to preserve data"
            )
        
        # Fallback to INSTALL
        return (
            WorkflowType.INSTALL,
            "Defaulting to install workflow"
        )

    def _log_classification(self, classification: WorkflowClassification):
        """
        Log the workflow classification for audit purposes.
        
        Args:
            classification: The workflow classification result
        """
        logger.info(
            f"[WORKFLOW] Classification complete: "
            f"capability={classification.capability_name}, "
            f"environment={classification.environment}, "
            f"region={classification.region}, "
            f"workflow_type={classification.workflow_type}, "
            f"existing_stacks={len(classification.existing_stacks)}, "
            f"strategy={classification.strategy_selected}, "
            f"timestamp={classification.classification_timestamp.isoformat()}"
        )
        logger.info(f"[WORKFLOW] Reason: {classification.reason}")

    def requires_strategy_selection(
        self,
        capability_name: str,
        environment: str,
        region: str
    ) -> bool:
        """
        Check if the deployment requires user to select a strategy.
        
        Returns True if existing stacks are detected, meaning user
        must choose between clean deploy and update existing.
        
        Args:
            capability_name: Name of the capability
            environment: Target environment
            region: AWS region
            
        Returns:
            True if strategy selection is required
        """
        existing_stacks = self._detect_existing_stacks(
            capability_name, environment, region
        )
        return len(existing_stacks) > 0


def get_workflow_classifier(
    stack_detection_service=None,
    deployment_state_service=None
) -> WorkflowClassifier:
    """
    Factory function to create a WorkflowClassifier instance.
    
    Args:
        stack_detection_service: Optional stack detection service
        deployment_state_service: Optional deployment state service
        
    Returns:
        Configured WorkflowClassifier instance
    """
    return WorkflowClassifier(
        stack_detection_service=stack_detection_service,
        deployment_state_service=deployment_state_service
    )
