"""Pytest config — make the parent dir importable as flat modules."""
import sys
from pathlib import Path

# scripts/backup-restore/ contains flat modules (config.py, ssm_backup.py, ...);
# the orchestrator imports them as top-level, so the test path needs to match.
PARENT = Path(__file__).resolve().parent.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))
