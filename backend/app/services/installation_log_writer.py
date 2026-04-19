"""
Installation Log Writer Service
Writes deployment logs to file for persistence and debugging.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default logs directory - can be overridden via environment variable
DEFAULT_LOGS_DIR = Path(__file__).parent.parent.parent / "data" / "installation_logs"


class InstallationLogWriter:
    """
    Writes deployment logs to file for persistence.
    
    Each installation gets its own log file named {installation_id}.log
    containing timestamped log entries for debugging and audit purposes.
    """
    
    def __init__(self, installation_id: str, logs_dir: Optional[Path] = None):
        """
        Initialize log writer for an installation.
        
        Args:
            installation_id: Unique installation identifier
            logs_dir: Directory to store log files (uses default if None)
        """
        self.installation_id = installation_id
        self.logs_dir = logs_dir or self._get_logs_dir()
        self.log_file = self.logs_dir / f"{installation_id}.log"
        
        # Ensure logs directory exists
        self.logs_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_logs_dir(self) -> Path:
        """Get logs directory from environment or use default."""
        env_dir = os.environ.get("INSTALLATION_LOGS_DIR")
        if env_dir:
            return Path(env_dir)
        return DEFAULT_LOGS_DIR
    
    def write(self, level: str, message: str, timestamp: Optional[datetime] = None):
        """
        Append log entry to file.
        
        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG)
            message: Log message
            timestamp: Timestamp for entry (uses current time if None)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        entry = f"[{timestamp.isoformat()}] [{level}] {message}\n"
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(entry)
        except Exception as e:
            logger.warning(f"Failed to write installation log: {e}")
    
    def read(self) -> str:
        """
        Read entire log file content.
        
        Returns:
            Log file content as string, or empty string if file doesn't exist
        """
        try:
            if self.log_file.exists():
                return self.log_file.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"Failed to read installation log: {e}")
        return ""
    
    def exists(self) -> bool:
        """Check if log file exists."""
        return self.log_file.exists()
    
    def delete(self):
        """Delete the log file."""
        try:
            if self.log_file.exists():
                self.log_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete installation log: {e}")


# Cache of log writers by installation_id
_log_writers: dict = {}


def get_log_writer(installation_id: str) -> InstallationLogWriter:
    """
    Get or create a log writer for an installation.
    
    Args:
        installation_id: Unique installation identifier
        
    Returns:
        InstallationLogWriter instance
    """
    if installation_id not in _log_writers:
        _log_writers[installation_id] = InstallationLogWriter(installation_id)
    return _log_writers[installation_id]


def clear_log_writer(installation_id: str):
    """Remove log writer from cache."""
    if installation_id in _log_writers:
        del _log_writers[installation_id]


def read_installation_log(installation_id: str) -> str:
    """
    Read installation log content.
    
    Args:
        installation_id: Unique installation identifier
        
    Returns:
        Log content as string
    """
    writer = InstallationLogWriter(installation_id)
    return writer.read()
