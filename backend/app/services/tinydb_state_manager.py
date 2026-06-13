"""
TinyDB State Manager
Core component for managing TinyDB database connections and operations
"""
import os
import shutil
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from tinydb import TinyDB, Query
from tinydb.table import Table
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database errors"""
    pass


class DatabaseWriteError(DatabaseError):
    """Exception raised when database write operations fail"""
    pass


class DatabaseCorruptionError(DatabaseError):
    """Exception raised when database corruption is detected"""
    pass


class TinyDBStateManager:
    """
    Manages TinyDB database connections and operations
    Provides backup, restore, and schema versioning capabilities
    """
    
    CURRENT_SCHEMA_VERSION = "1.0.0"
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize TinyDB connection
        
        Args:
            db_path: Path to database file (default: backend/data/state.db or AppData in packaged mode)
        """
        if db_path:
            self.db_path = Path(db_path)
        else:
            # Check if running as PyInstaller bundle
            import sys
            if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                # Running as packaged app - use AppData for writable storage
                import os
                app_data = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
                self.db_path = Path(app_data) / "NexusInstaller" / "data" / "state.db"
                logger.info(f"Running in packaged mode, using AppData for database")
            else:
                # Development mode - use backend/data/state.db
                backend_dir = Path(__file__).parent.parent.parent
                self.db_path = backend_dir / "data" / "state.db"
        
        # Create data directory if it doesn't exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create backups directory
        self.backup_dir = self.db_path.parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"TinyDB database path: {self.db_path}")
        logger.info(f"TinyDB backup directory: {self.backup_dir}")
        
        # Initialize database connection
        try:
            # Auto-repair: fix CRLF line endings and JSON corruption before opening
            self._repair_db_if_needed()
            
            # Use JSONStorage directly without caching for now to ensure writes persist
            self.db = TinyDB(
                str(self.db_path),
                storage=JSONStorage,
                indent=2,
                ensure_ascii=False
            )
            logger.info("TinyDB connection established successfully")
            
            # Initialize schema version if needed
            self._initialize_schema()
            
        except Exception as e:
            logger.error(f"Failed to initialize TinyDB: {str(e)}")
            raise DatabaseError(f"Database initialization failed: {str(e)}")
    
    def _repair_db_if_needed(self):
        """Auto-repair common database file issues (CRLF, concatenated JSON)."""
        import json as _json
        
        if not self.db_path.exists():
            return
        
        try:
            raw = self.db_path.read_bytes()
            # Quick check: try to parse as-is
            _json.loads(raw)
            
            # Even if valid, fix CRLF to prevent future issues
            if b'\r\n' in raw:
                logger.warning("Database file has CRLF line endings, converting to LF...")
                fixed = raw.replace(b'\r\n', b'\n')
                self.db_path.write_bytes(fixed)
                logger.info("Fixed CRLF line endings in database file")
                
        except _json.JSONDecodeError as e:
            logger.warning(f"Database file has JSON issues: {e}. Attempting auto-repair...")
            
            try:
                content = raw.decode('utf-8')
                # Try raw_decode to get the first valid JSON object
                decoder = _json.JSONDecoder()
                obj, end = decoder.raw_decode(content)
                
                # Backup corrupted file
                backup_path = self.db_path.with_suffix('.db.auto_backup')
                self.db_path.rename(backup_path)
                logger.info(f"Backed up corrupted database to {backup_path}")
                
                # Write clean JSON with LF line endings
                clean = _json.dumps(obj, indent=2, ensure_ascii=False)
                self.db_path.write_text(clean, encoding='utf-8', newline='\n')
                logger.info("Auto-repaired database file successfully")
                
            except Exception as repair_err:
                logger.error(f"Auto-repair failed: {repair_err}")
                # Re-raise original error
                raise

    def _initialize_schema(self):
        """Initialize schema version in metadata table"""
        try:
            metadata_table = self.get_table("metadata")
            MetadataQuery = Query()
            
            # Check if schema version exists
            schema_doc = metadata_table.get(MetadataQuery.key == "schema_version")
            
            if not schema_doc:
                # Create initial schema version
                metadata_table.insert({
                    "key": "schema_version",
                    "value": self.CURRENT_SCHEMA_VERSION,
                    "updated_at": datetime.utcnow().isoformat()
                })
                logger.info(f"Initialized schema version: {self.CURRENT_SCHEMA_VERSION}")
            else:
                logger.info(f"Existing schema version: {schema_doc['value']}")
                
        except Exception as e:
            logger.error(f"Failed to initialize schema: {str(e)}")
            raise DatabaseError(f"Schema initialization failed: {str(e)}")
    
    def get_table(self, table_name: str) -> Table:
        """
        Get or create a table
        
        Args:
            table_name: Name of the table
            
        Returns:
            TinyDB Table object
        """
        try:
            return self.db.table(table_name)
        except Exception as e:
            logger.error(f"Failed to get table '{table_name}': {str(e)}")
            raise DatabaseError(f"Failed to access table '{table_name}': {str(e)}")
    
    def close(self):
        """Close database connection"""
        try:
            if hasattr(self, 'db') and self.db:
                self.db.close()
                logger.info("TinyDB connection closed")
        except Exception as e:
            logger.error(f"Error closing database: {str(e)}")
    
    def backup(self, backup_name: Optional[str] = None) -> str:
        """
        Create database backup
        
        Args:
            backup_name: Optional custom backup name
            
        Returns:
            Path to backup file
        """
        try:
            if not backup_name:
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                backup_name = f"state-{timestamp}.db"
            
            backup_path = self.backup_dir / backup_name
            
            # Close and reopen to ensure all data is flushed
            self.db.close()
            
            # Copy database file
            shutil.copy2(self.db_path, backup_path)
            
            # Reopen database
            self.db = TinyDB(
                str(self.db_path),
                storage=CachingMiddleware(JSONStorage),
                indent=2,
                ensure_ascii=False
            )
            
            logger.info(f"Database backup created: {backup_path}")
            return str(backup_path)
            
        except Exception as e:
            logger.error(f"Failed to create backup: {str(e)}")
            # Reopen database even if backup fails
            try:
                self.db = TinyDB(
                    str(self.db_path),
                    storage=CachingMiddleware(JSONStorage),
                    indent=2,
                    ensure_ascii=False
                )
            except:
                pass
            raise DatabaseError(f"Backup creation failed: {str(e)}")
    
    def restore(self, backup_path: str) -> bool:
        """
        Restore from backup
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            True if restore successful
        """
        try:
            backup_file = Path(backup_path)
            
            if not backup_file.exists():
                raise DatabaseError(f"Backup file not found: {backup_path}")
            
            # Close current database
            self.db.close()
            
            # Replace current database with backup
            shutil.copy2(backup_file, self.db_path)
            
            # Reopen database
            self.db = TinyDB(
                str(self.db_path),
                storage=CachingMiddleware(JSONStorage),
                indent=2,
                ensure_ascii=False
            )
            
            logger.info(f"Database restored from: {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore from backup: {str(e)}")
            # Try to reopen current database
            try:
                self.db = TinyDB(
                    str(self.db_path),
                    storage=CachingMiddleware(JSONStorage),
                    indent=2,
                    ensure_ascii=False
                )
            except:
                pass
            raise DatabaseError(f"Restore failed: {str(e)}")
    
    def get_schema_version(self) -> str:
        """
        Get current schema version
        
        Returns:
            Schema version string
        """
        try:
            metadata_table = self.get_table("metadata")
            MetadataQuery = Query()
            
            schema_doc = metadata_table.get(MetadataQuery.key == "schema_version")
            
            if schema_doc:
                return schema_doc["value"]
            else:
                return "unknown"
                
        except Exception as e:
            logger.error(f"Failed to get schema version: {str(e)}")
            return "unknown"
    
    def migrate_schema(self, target_version: str) -> bool:
        """
        Migrate schema to target version
        
        Args:
            target_version: Target schema version
            
        Returns:
            True if migration successful
        """
        try:
            current_version = self.get_schema_version()
            
            if current_version == target_version:
                logger.info(f"Schema already at version {target_version}")
                return True
            
            # Create automatic backup before migration
            backup_path = self.backup(f"pre-migration-{target_version}.db")
            logger.info(f"Created pre-migration backup: {backup_path}")
            
            # TODO: Implement actual migration logic based on version
            # For now, just update the version
            metadata_table = self.get_table("metadata")
            MetadataQuery = Query()
            
            metadata_table.update(
                {
                    "value": target_version,
                    "updated_at": datetime.utcnow().isoformat()
                },
                MetadataQuery.key == "schema_version"
            )
            
            logger.info(f"Schema migrated from {current_version} to {target_version}")
            return True
            
        except Exception as e:
            logger.error(f"Schema migration failed: {str(e)}")
            # Attempt to restore from backup
            try:
                if 'backup_path' in locals():
                    logger.info("Attempting to restore from backup...")
                    self.restore(backup_path)
            except:
                pass
            raise DatabaseError(f"Schema migration failed: {str(e)}")
    
    def cleanup_old_backups(self, retention_days: int = 30) -> int:
        """
        Remove backups older than retention period
        
        Args:
            retention_days: Number of days to retain backups
            
        Returns:
            Number of backups removed
        """
        try:
            removed_count = 0
            cutoff_time = datetime.utcnow().timestamp() - (retention_days * 86400)
            
            for backup_file in self.backup_dir.glob("*.db"):
                if backup_file.stat().st_mtime < cutoff_time:
                    backup_file.unlink()
                    removed_count += 1
                    logger.info(f"Removed old backup: {backup_file.name}")
            
            logger.info(f"Cleaned up {removed_count} old backups")
            return removed_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old backups: {str(e)}")
            return 0
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


# Global instance (can be overridden for testing)
_global_manager: Optional[TinyDBStateManager] = None


def get_state_manager() -> TinyDBStateManager:
    """
    Get global TinyDB state manager instance
    
    Returns:
        TinyDBStateManager instance
    """
    global _global_manager
    
    if _global_manager is None:
        _global_manager = TinyDBStateManager()
    
    return _global_manager


def set_state_manager(manager: Optional[TinyDBStateManager]):
    """
    Set global TinyDB state manager instance (for testing)
    
    Args:
        manager: TinyDBStateManager instance or None
    """
    global _global_manager
    _global_manager = manager
