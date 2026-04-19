"""
Stack Detection Service
Detects existing capability deployments by querying CloudFormation
"""
import logging
import boto3
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from botocore.exceptions import ClientError

from app.services.tinydb_deployment_state_service import (
    TinyDBDeploymentStateService,
    tinydb_deployment_state_service
)
from app.models.stack_detection import (
    StackDetectionResult,
    ExistingStackInfo,
    DeploymentStrategy,
    UPDATABLE_STATES,
    FAILED_STATES,
    IN_PROGRESS_STATES,
    FRONTEND_STACKS,
    BACKEND_STACKS,
)

logger = logging.getLogger(__name__)


class StackDetectionService:
    """Service for detecting existing capability deployments by querying CloudFormation"""
    
    def __init__(
        self, 
        credentials: Optional[Dict[str, str]] = None,
        deployment_state_service: Optional[TinyDBDeploymentStateService] = None
    ):
        """
        Initialize stack detection service
        
        Args:
            credentials: Optional AWS credentials dict
            deployment_state_service: TinyDB deployment state service (uses global instance if None)
        """
        self.credentials = credentials or {}
        self.deployment_state_service = deployment_state_service or tinydb_deployment_state_service
        logger.info("Stack Detection Service initialized (CloudFormation-based)")
    
    def _get_client(self, service_name: str, region: str):
        """
        Get boto3 client with credentials
        
        Args:
            service_name: AWS service name (e.g., 'cloudformation')
            region: AWS region
            
        Returns:
            boto3 client
        """
        if self.credentials:
            return boto3.client(
                service_name,
                region_name=region,
                aws_access_key_id=self.credentials.get('aws_access_key_id'),
                aws_secret_access_key=self.credentials.get('aws_secret_access_key'),
                aws_session_token=self.credentials.get('aws_session_token'),
            )
        else:
            return boto3.client(service_name, region_name=region)
    
    def _classify_stack_state(self, stack_status: str) -> str:
        """
        Classify stack status as: updatable, failed, or in_progress
        
        Args:
            stack_status: CloudFormation stack status
            
        Returns:
            Classification string: "updatable", "failed", or "in_progress"
        """
        if stack_status in UPDATABLE_STATES:
            return "updatable"
        elif stack_status in FAILED_STATES:
            return "failed"
        elif stack_status in IN_PROGRESS_STATES:
            return "in_progress"
        else:
            # Unknown status - log warning and treat as updatable
            logger.warning(f"Unknown stack status: {stack_status}, treating as updatable")
            return "updatable"
    
    def _query_cloudformation_stack(
        self,
        stack_name: str,
        region: str,
        cfn_client
    ) -> Optional[ExistingStackInfo]:
        """
        Query CloudFormation for a single stack
        
        Args:
            stack_name: Name of the stack
            region: AWS region
            cfn_client: boto3 CloudFormation client
            
        Returns:
            ExistingStackInfo if stack exists, None if not found
        """
        try:
            response = cfn_client.describe_stacks(StackName=stack_name)
            
            if not response.get('Stacks'):
                return None
            
            stack = response['Stacks'][0]
            stack_status = stack['StackStatus']
            classification = self._classify_stack_state(stack_status)
            
            # Extract stack type from name (e.g., "capability-env-frontend-global" -> "frontend-global")
            parts = stack_name.split('-')
            stack_type = '-'.join(parts[2:]) if len(parts) > 2 else stack_name
            
            return ExistingStackInfo(
                stack_name=stack_name,
                stack_type=stack_type,
                stack_status=stack_status,
                region=region,
                created_at=stack.get('CreationTime'),
                last_updated_at=stack.get('LastUpdatedTime'),
                is_updatable=(classification == "updatable"),
                status_reason=stack.get('StackStatusReason'),
                classification=classification
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ValidationError' and 'does not exist' in str(e):
                # Stack doesn't exist - not an error
                logger.info(f"Stack {stack_name} does not exist in {region}")
                return None
            else:
                # Other errors - log and re-raise
                logger.error(f"Error querying stack {stack_name} in {region}: {str(e)}")
                raise
    
    def _recommend_strategy(
        self,
        stacks: List[ExistingStackInfo]
    ) -> Tuple[Optional[DeploymentStrategy], str]:
        """
        Apply decision tree logic to recommend strategy
        
        Args:
            stacks: List of detected stacks
            
        Returns:
            (strategy, reason) tuple
        """
        if not stacks:
            # No stacks exist - first deployment
            return (
                DeploymentStrategy.UPDATE_EXISTING,
                "First deployment - no existing stacks found"
            )
        
        # Check for in-progress stacks
        in_progress_stacks = [s for s in stacks if s.classification == "in_progress"]
        if in_progress_stacks:
            stack_names = ", ".join([s.stack_name for s in in_progress_stacks])
            return (
                None,
                f"Wait for in-progress operations to complete: {stack_names}"
            )
        
        # Check for failed stacks
        failed_stacks = [s for s in stacks if s.classification == "failed"]
        if failed_stacks:
            stack_details = ", ".join([f"{s.stack_name} ({s.stack_status})" for s in failed_stacks])
            return (
                DeploymentStrategy.CLEAN_DEPLOY,
                f"Failed stacks detected: {stack_details}. Cleanup required before redeployment."
            )
        
        # All stacks are updatable
        return (
            DeploymentStrategy.UPDATE_EXISTING,
            "All stacks are stable and updatable - in-place update recommended"
        )
    
    def detect_existing_stacks(
        self,
        capability_name: str,
        environment: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        deploy_frontend: bool = True,
        deploy_backend: bool = True
    ) -> StackDetectionResult:
        """
        Detect existing stacks by querying CloudFormation
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            region: Target deployment region
            credentials: Optional AWS credentials (overrides instance credentials)
            deploy_frontend: Whether frontend stacks should be checked
            deploy_backend: Whether backend stacks should be checked
            
        Returns:
            StackDetectionResult with stacks found, recommendation, and metadata
        """
        # Use provided credentials or fall back to instance credentials
        if credentials:
            self.credentials = credentials
        
        errors = []
        stacks_found = []
        
        try:
            logger.info(f"Detecting existing stacks: {capability_name} ({environment}) in {region}")
            
            # Determine which stacks to check
            expected_stacks = {}
            if deploy_frontend:
                expected_stacks.update(FRONTEND_STACKS)
            if deploy_backend:
                expected_stacks.update(BACKEND_STACKS)
            
            # Query each expected stack
            for stack_type, region_spec in expected_stacks.items():
                # Determine the correct region for this stack
                stack_region = 'us-east-1' if region_spec == 'us-east-1' else region
                stack_name = f"{capability_name}-{environment}-{stack_type}"
                
                try:
                    logger.info(f"Querying stack {stack_name} in {stack_region}")
                    cfn_client = self._get_client('cloudformation', stack_region)
                    stack_info = self._query_cloudformation_stack(stack_name, stack_region, cfn_client)
                    
                    if stack_info:
                        stacks_found.append(stack_info)
                        logger.info(f"  Found: {stack_name} - {stack_info.stack_status} ({stack_info.classification})")
                    else:
                        logger.info(f"  Not found: {stack_name}")
                        
                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    error_msg = f"Error querying {stack_name} in {stack_region}: {error_code}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    # Continue with other stacks
                    
                except Exception as e:
                    error_msg = f"Unexpected error querying {stack_name}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    # Continue with other stacks
            
            # Apply decision tree logic
            recommended_strategy, recommendation_reason = self._recommend_strategy(stacks_found)
            
            # Calculate flags
            has_failed_stacks = any(s.classification == "failed" for s in stacks_found)
            has_in_progress_stacks = any(s.classification == "in_progress" for s in stacks_found)
            is_updatable = not has_failed_stacks and not has_in_progress_stacks
            
            result = StackDetectionResult(
                capability_name=capability_name,
                environment=environment,
                region=region,
                stacks_found=stacks_found,
                has_existing_stacks=len(stacks_found) > 0,
                has_failed_stacks=has_failed_stacks,
                has_in_progress_stacks=has_in_progress_stacks,
                is_updatable=is_updatable,
                recommended_strategy=recommended_strategy,
                recommendation_reason=recommendation_reason,
                detection_timestamp=datetime.utcnow(),
                error_message="; ".join(errors) if errors else None
            )
            
            logger.info(f"Detection complete: {len(stacks_found)} stacks found")
            logger.info(f"Recommendation: {recommended_strategy.value if recommended_strategy else 'WAIT'}")
            logger.info(f"Reason: {recommendation_reason}")
            
            return result
            
        except Exception as e:
            logger.error(f"Fatal error detecting stacks: {str(e)}")
            # Return result with error
            return StackDetectionResult(
                capability_name=capability_name,
                environment=environment,
                region=region,
                stacks_found=stacks_found,  # Return partial results if any
                has_existing_stacks=len(stacks_found) > 0,
                has_failed_stacks=False,
                has_in_progress_stacks=False,
                is_updatable=False,
                recommended_strategy=None,
                recommendation_reason="",
                detection_timestamp=datetime.utcnow(),
                error_message=str(e)
            )
    
    # ==================== EKS Deployment Detection ====================
    # Feature: pure-eks-deployment
    # Requirements: 9.2, 9.3
    
    def detect_eks_deployment(
        self,
        capability_name: str,
        environment: str,
        cluster_name: str,
        namespace: str,
        aws_session_id: Optional[str] = None
    ) -> Dict:
        """
        Detect existing EKS deployment by checking for TotogiCapability CR.
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/staging/prod)
            cluster_name: EKS cluster name
            namespace: Kubernetes namespace
            aws_session_id: Optional AWS session ID
            
        Returns:
            Dict with detection results
        """
        try:
            logger.info(f"Detecting EKS deployment: {capability_name} ({environment}) in {cluster_name}/{namespace}")
            
            # Check local state first
            state = self.deployment_state_service.load_deployment_state(capability_name, environment)
            
            if state and state.get("deployment_type") == "eks":
                logger.info(f"Found EKS deployment in local state")
                return {
                    "found": True,
                    "deployment_type": "eks",
                    "cluster_arn": state.get("cluster_arn"),
                    "namespace": state.get("namespace"),
                    "cr_name": state.get("cr_name"),
                    "resources": state.get("resources", {}),
                    "last_deployment": state.get("last_deployment"),
                    "source": "local_state",
                    "is_updatable": True,
                    "recommendation": "UPDATE_EXISTING",
                    "recommendation_reason": "Existing EKS deployment found - update via CR modification"
                }
            
            # If no local state, could query K8s API for CR
            # This would require operator_deployment_service
            # For now, return not found
            logger.info(f"No EKS deployment found in local state")
            return {
                "found": False,
                "deployment_type": None,
                "is_updatable": True,
                "recommendation": "CLEAN_DEPLOY",
                "recommendation_reason": "No existing EKS deployment found - fresh deployment"
            }
            
        except Exception as e:
            logger.error(f"Error detecting EKS deployment: {e}")
            return {
                "found": False,
                "deployment_type": None,
                "error": str(e),
                "is_updatable": False,
                "recommendation": None,
                "recommendation_reason": f"Error during detection: {e}"
            }
    
    def detect_any_deployment(
        self,
        capability_name: str,
        environment: str,
        region: str,
        credentials: Optional[Dict[str, str]] = None,
        eks_cluster_name: Optional[str] = None,
        eks_namespace: Optional[str] = None
    ) -> Dict:
        """
        Detect any existing deployment (CloudFormation or EKS).
        
        Args:
            capability_name: Name of the capability
            environment: Environment
            region: AWS region
            credentials: Optional AWS credentials
            eks_cluster_name: Optional EKS cluster name (for EKS detection)
            eks_namespace: Optional Kubernetes namespace
            
        Returns:
            Dict with detection results including deployment type
        """
        # First check local state for deployment type
        state = self.deployment_state_service.load_deployment_state(capability_name, environment)
        
        if state:
            deployment_type = state.get("deployment_type", "cloudformation")
            
            if deployment_type == "eks":
                return {
                    "deployment_type": "eks",
                    "found": True,
                    "cluster_arn": state.get("cluster_arn"),
                    "namespace": state.get("namespace"),
                    "cr_name": state.get("cr_name"),
                    "resources": state.get("resources", {}),
                    "is_updatable": True,
                    "recommendation": "UPDATE_EXISTING"
                }
        
        # Check for CloudFormation stacks
        cfn_result = self.detect_existing_stacks(
            capability_name=capability_name,
            environment=environment,
            region=region,
            credentials=credentials
        )
        
        if cfn_result.has_existing_stacks:
            return {
                "deployment_type": "cloudformation",
                "found": True,
                "stacks": [s.dict() for s in cfn_result.stacks_found],
                "is_updatable": cfn_result.is_updatable,
                "has_failed_stacks": cfn_result.has_failed_stacks,
                "recommendation": cfn_result.recommended_strategy.value if cfn_result.recommended_strategy else None,
                "recommendation_reason": cfn_result.recommendation_reason
            }
        
        # Check for EKS deployment if cluster info provided
        if eks_cluster_name and eks_namespace:
            eks_result = self.detect_eks_deployment(
                capability_name=capability_name,
                environment=environment,
                cluster_name=eks_cluster_name,
                namespace=eks_namespace
            )
            
            if eks_result.get("found"):
                return eks_result
        
        # No deployment found
        return {
            "deployment_type": None,
            "found": False,
            "is_updatable": True,
            "recommendation": "CLEAN_DEPLOY",
            "recommendation_reason": "No existing deployment found"
        }


# Global instance
stack_detection_service = StackDetectionService()
