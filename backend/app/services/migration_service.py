"""
Migration Service
Handles migration from JSON-based state to TinyDB
"""
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from .tinydb_state_manager import TinyDBStateManager, get_state_manager
from .tinydb_deployment_state_service import TinyDBDeploymentStateService

logger = logging.getLogger(__name__)


class MigrationService:
    """Handles migration from JSON-based state to TinyDB"""
    
    def __init__(
        self,
        db_manager: Optional[TinyDBStateManager] = None,
        state_dir: Optional[str] = None
    ):
        """
        Initialize migration service
        
        Args:
            db_manager: TinyDB state manager
            state_dir: Directory containing JSON state files
        """
        self.db_manager = db_manager or get_state_manager()
        
        if state_dir:
            self.state_dir = Path(state_dir)
        else:
            # Default to deploy/state directory
            backend_dir = Path(__file__).parent.parent.parent
            self.state_dir = backend_dir.parent / "deploy" / "state"
        
        self.archive_dir = self.state_dir / "archive"
        self.deployment_service = TinyDBDeploymentStateService(db_manager)
        
        logger.info(f"Migration service initialized")
        logger.info(f"  State directory: {self.state_dir}")
        logger.info(f"  Archive directory: {self.archive_dir}")
    
    def migrate_deployment_states(self) -> Dict[str, Any]:
        """
        Migrate all JSON state files to TinyDB
        
        Returns:
            Migration statistics
        """
        stats = {
            "total_files": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "errors": []
        }
        
        try:
            if not self.state_dir.exists():
                logger.info("State directory does not exist, no migration needed")
                return stats
            
            # Find all JSON files in state directory
            json_files = list(self.state_dir.glob("*.json"))
            stats["total_files"] = len(json_files)
            
            if stats["total_files"] == 0:
                logger.info("No JSON state files found for migration")
                return stats
            
            logger.info(f"Found {stats['total_files']} JSON state files to migrate")
            
            # Create backup before migration
            try:
                backup_path = self.db_manager.backup("pre-migration.db")
                logger.info(f"Created pre-migration backup: {backup_path}")
            except Exception as e:
                logger.warning(f"Failed to create pre-migration backup: {str(e)}")
            
            # Migrate each file
            for json_file in json_files:
                try:
                    logger.info(f"Migrating: {json_file.name}")
                    
                    # Read JSON file
                    with open(json_file, 'r') as f:
                        state_data = json.load(f)
                    
                    # Validate required fields
                    required_fields = ["capability_name", "environment", "region", "stacks"]
                    missing_fields = [f for f in required_fields if f not in state_data]
                    
                    if missing_fields:
                        error_msg = f"Missing required fields: {missing_fields}"
                        logger.warning(f"  Skipping {json_file.name}: {error_msg}")
                        stats["skipped"] += 1
                        stats["errors"].append({
                            "file": json_file.name,
                            "error": error_msg
                        })
                        continue
                    
                    # Migrate to TinyDB
                    success = self.deployment_service.save_deployment_state(
                        capability_name=state_data["capability_name"],
                        environment=state_data["environment"],
                        region=state_data["region"],
                        stacks=state_data.get("stacks", []),
                        deployment_metadata=state_data.get("metadata", {})
                    )
                    
                    if success:
                        stats["successful"] += 1
                        logger.info(f"  Successfully migrated: {json_file.name}")
                    else:
                        stats["failed"] += 1
                        stats["errors"].append({
                            "file": json_file.name,
                            "error": "Failed to save to TinyDB"
                        })
                        
                except json.JSONDecodeError as e:
                    error_msg = f"Invalid JSON: {str(e)}"
                    logger.error(f"  Failed to parse {json_file.name}: {error_msg}")
                    stats["failed"] += 1
                    stats["errors"].append({
                        "file": json_file.name,
                        "error": error_msg
                    })
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"  Failed to migrate {json_file.name}: {error_msg}")
                    stats["failed"] += 1
                    stats["errors"].append({
                        "file": json_file.name,
                        "error": error_msg
                    })
            
            logger.info(f"Migration complete: {stats['successful']} successful, {stats['failed']} failed, {stats['skipped']} skipped")
            return stats
            
        except Exception as e:
            logger.error(f"Migration failed: {str(e)}")
            stats["errors"].append({
                "file": "general",
                "error": str(e)
            })
            return stats
    
    def archive_json_files(self) -> bool:
        """
        Archive migrated JSON files
        
        Returns:
            True if archival successful
        """
        try:
            if not self.state_dir.exists():
                logger.info("State directory does not exist, no files to archive")
                return True
            
            # Create archive directory
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            
            # Find all JSON files
            json_files = list(self.state_dir.glob("*.json"))
            
            if len(json_files) == 0:
                logger.info("No JSON files to archive")
                return True
            
            logger.info(f"Archiving {len(json_files)} JSON files")
            
            # Move each file to archive
            archived_count = 0
            for json_file in json_files:
                try:
                    # Add timestamp to archived filename
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    archive_name = f"{json_file.stem}_{timestamp}{json_file.suffix}"
                    archive_path = self.archive_dir / archive_name
                    
                    shutil.move(str(json_file), str(archive_path))
                    archived_count += 1
                    logger.info(f"  Archived: {json_file.name} -> {archive_name}")
                    
                except Exception as e:
                    logger.error(f"  Failed to archive {json_file.name}: {str(e)}")
            
            logger.info(f"Archived {archived_count} of {len(json_files)} files")
            return archived_count == len(json_files)
            
        except Exception as e:
            logger.error(f"Failed to archive JSON files: {str(e)}")
            return False
    
    def verify_migration(self) -> bool:
        """
        Verify migration completed successfully
        
        Returns:
            True if verification successful
        """
        try:
            # Check if any JSON files remain in state directory
            if self.state_dir.exists():
                remaining_files = list(self.state_dir.glob("*.json"))
                if remaining_files:
                    logger.warning(f"Found {len(remaining_files)} JSON files still in state directory")
                    return False
            
            # Check if TinyDB has deployments
            deployments = self.deployment_service.list_deployments()
            
            if len(deployments) == 0:
                logger.warning("No deployments found in TinyDB after migration")
                return False
            
            logger.info(f"Migration verification successful: {len(deployments)} deployments in TinyDB")
            return True
            
        except Exception as e:
            logger.error(f"Migration verification failed: {str(e)}")
            return False


# Global instance
migration_service = MigrationService()
