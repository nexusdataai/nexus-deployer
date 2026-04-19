"""
Deployment State Service
Tracks deployed stacks in filesystem for faster detection
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DeploymentStateService:
    """Service for managing deployment state on filesystem"""
    
    def __init__(self, state_dir: Optional[str] = None):
        """
        Initialize deployment state service
        
        Args:
            state_dir: Directory to store state files (default: deploy/state)
        """
        if state_dir:
            self.state_dir = Path(state_dir)
        else:
            # Default to deploy/state directory
            self.state_dir = Path(__file__).parent.parent.parent.parent / "deploy" / "state"
        
        # Create state directory if it doesn't exist
        self.state_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Deployment state directory: {self.state_dir}")
    
    def _get_state_file_path(self, capability_name: str, environment: str) -> Path:
        """Get the path to the state file for a capability/environment"""
        # Sanitize names for filesystem
        safe_capability = capability_name.lower().replace(' ', '-').replace('_', '-')
        safe_capability = ''.join(c for c in safe_capability if c.isalnum() or c == '-')
        safe_env = environment.lower()
        
        filename = f"{safe_capability}-{safe_env}.json"
        return self.state_dir / filename
    
    def save_deployment_state(
        self,
        capability_name: str,
        environment: str,
        region: str,
        stacks: List[Dict[str, Any]],
        deployment_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save deployment state to filesystem
        
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
            state_file = self._get_state_file_path(capability_name, environment)
            
            state = {
                "capability_name": capability_name,
                "environment": environment,
                "region": region,
                "stacks": stacks,
                "last_deployment": datetime.utcnow().isoformat(),
                "metadata": deployment_metadata or {}
            }
            
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            
            logger.info(f"Saved deployment state: {state_file}")
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
        Load deployment state from filesystem
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            
        Returns:
            Deployment state dict or None if not found
        """
        try:
            state_file = self._get_state_file_path(capability_name, environment)
            
            if not state_file.exists():
                logger.info(f"No deployment state found: {state_file}")
                return None
            
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            logger.info(f"Loaded deployment state: {state_file}")
            logger.info(f"  Last deployment: {state.get('last_deployment')}")
            logger.info(f"  Stacks: {len(state.get('stacks', []))}")
            
            return state
            
        except Exception as e:
            logger.error(f"Failed to load deployment state: {str(e)}")
            return None
    
    def delete_deployment_state(
        self,
        capability_name: str,
        environment: str
    ) -> bool:
        """
        Delete deployment state from filesystem
        
        Args:
            capability_name: Name of the capability
            environment: Environment (dev/test/stage/prod)
            
        Returns:
            True if deleted successfully
        """
        try:
            state_file = self._get_state_file_path(capability_name, environment)
            
            if state_file.exists():
                state_file.unlink()
                logger.info(f"Deleted deployment state: {state_file}")
                return True
            else:
                logger.info(f"No state file to delete: {state_file}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete deployment state: {str(e)}")
            return False
    
    def list_deployments(self) -> List[Dict[str, Any]]:
        """
        List all tracked deployments
        
        Returns:
            List of deployment summaries
        """
        deployments = []
        
        try:
            for state_file in self.state_dir.glob("*.json"):
                try:
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                    
                    deployments.append({
                        "capability_name": state.get("capability_name"),
                        "environment": state.get("environment"),
                        "region": state.get("region"),
                        "stack_count": len(state.get("stacks", [])),
                        "last_deployment": state.get("last_deployment"),
                        "state_file": str(state_file)
                    })
                except Exception as e:
                    logger.warning(f"Failed to read state file {state_file}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Failed to list deployments: {str(e)}")
        
        return deployments
    
    def update_stack_in_state(
        self,
        capability_name: str,
        environment: str,
        stack_name: str,
        stack_updates: Dict[str, Any]
    ) -> bool:
        """
        Update a specific stack's information in the state
        
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
                return False
            
            # Find and update the stack
            stacks = state.get("stacks", [])
            for stack in stacks:
                if stack.get("stack_name") == stack_name:
                    stack.update(stack_updates)
                    stack["last_updated"] = datetime.utcnow().isoformat()
                    break
            
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


# Global instance
deployment_state_service = DeploymentStateService()
