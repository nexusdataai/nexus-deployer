# Design Document: Installer Uninstall Cleanup

## Overview

This design addresses the issue where the backend process (`totogi-backend.exe`) remains running after the Totogi Capability Installer is uninstalled. The solution involves:

1. Custom NSIS uninstall scripts to terminate processes
2. Graceful shutdown handling in the Python backend
3. Application data cleanup options
4. Comprehensive logging for troubleshooting

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Uninstall Flow                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   NSIS       │───▶│   Process    │───▶│   File       │       │
│  │   Uninstaller│    │   Terminator │    │   Cleanup    │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │                   │                   │                │
│         ▼                   ▼                   ▼                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   Pre-check  │    │   Graceful   │    │   Registry   │       │
│  │   Validation │    │   Shutdown   │    │   Cleanup    │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                             │                                    │
│                             ▼                                    │
│                      ┌──────────────┐                           │
│                      │   Uninstall  │                           │
│                      │   Logger     │                           │
│                      └──────────────┘                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. NSIS Uninstall Script Extension

The electron-builder NSIS configuration will be extended with custom uninstall hooks.

```nsis
; Custom uninstall script hooks
!macro customUnInstall
  ; Terminate backend process
  nsExec::ExecToLog 'taskkill /F /IM totogi-backend.exe'
  
  ; Terminate Electron app
  nsExec::ExecToLog 'taskkill /F /IM "Totogi Installer.exe"'
  
  ; Clean application data (if user opted in)
  ${If} $DeleteAppData == "true"
    RMDir /r "$APPDATA\totogi-installer"
    RMDir /r "$LOCALAPPDATA\totogi-installer"
    RMDir /r "$LOCALAPPDATA\Totogi Installer"
  ${EndIf}
  
  ; Clean temp files
  RMDir /r "$TEMP\totogi-*"
  
  ; Clean registry
  DeleteRegKey HKCU "Software\totogi-installer"
!macroend
```

### 2. Process Terminator Module

A PowerShell script that handles graceful process termination with timeout.

```powershell
# terminate-processes.ps1
param(
    [int]$GracefulTimeoutSeconds = 5,
    [string]$LogFile = "$env:TEMP\totogi-uninstall.log"
)

function Terminate-Process {
    param([string]$ProcessName)
    
    $processes = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
    
    foreach ($proc in $processes) {
        # Try graceful shutdown first
        $proc.CloseMainWindow() | Out-Null
        
        # Wait for graceful shutdown
        $waited = 0
        while (!$proc.HasExited -and $waited -lt $GracefulTimeoutSeconds) {
            Start-Sleep -Seconds 1
            $waited++
        }
        
        # Force kill if still running
        if (!$proc.HasExited) {
            $proc.Kill()
        }
    }
}
```

### 3. Backend Graceful Shutdown Handler

The Python backend will handle SIGTERM/SIGINT signals for graceful shutdown.

```python
# shutdown_handler.py
import signal
import sys
import logging
from typing import Callable, List

logger = logging.getLogger(__name__)

class GracefulShutdownHandler:
    """Handles graceful shutdown of the backend process."""
    
    def __init__(self, timeout_seconds: int = 3):
        self.timeout_seconds = timeout_seconds
        self.shutdown_callbacks: List[Callable] = []
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Register signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        if sys.platform == 'win32':
            signal.signal(signal.SIGBREAK, self._handle_shutdown)
    
    def register_callback(self, callback: Callable):
        """Register a callback to be called during shutdown."""
        self.shutdown_callbacks.append(callback)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal."""
        logger.info(f"Received shutdown signal {signum}")
        
        for callback in self.shutdown_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in shutdown callback: {e}")
        
        logger.info("Graceful shutdown complete")
        sys.exit(0)
```

### 4. Uninstall Logger

Logs all uninstall operations for troubleshooting.

```python
# uninstall_logger.py
import logging
from pathlib import Path
from datetime import datetime

class UninstallLogger:
    """Logs uninstall operations."""
    
    def __init__(self, log_path: Path = None):
        if log_path is None:
            log_path = Path(os.environ.get('TEMP', '/tmp')) / 'totogi-uninstall.log'
        
        self.log_path = log_path
        self._setup_logging()
    
    def _setup_logging(self):
        """Configure logging to file."""
        handler = logging.FileHandler(self.log_path)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
        self.logger = logging.getLogger('uninstall')
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_action(self, action: str, result: str):
        """Log an uninstall action."""
        self.logger.info(f"ACTION: {action} - RESULT: {result}")
    
    def log_error(self, action: str, error: str):
        """Log an error during uninstall."""
        self.logger.error(f"ERROR: {action} - {error}")
    
    def log_summary(self, success_count: int, error_count: int):
        """Log uninstall summary."""
        self.logger.info(f"SUMMARY: {success_count} successful, {error_count} errors")
```

## Data Models

### UninstallConfig

```python
@dataclass
class UninstallConfig:
    """Configuration for uninstall process."""
    delete_app_data: bool = False
    silent_mode: bool = False
    graceful_timeout_seconds: int = 5
    force_kill_timeout_seconds: int = 5
    log_file: Optional[Path] = None
```

### UninstallResult

```python
@dataclass
class UninstallResult:
    """Result of uninstall operation."""
    success: bool
    processes_terminated: List[str]
    files_removed: List[str]
    errors: List[str]
    log_file: Path
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Process Termination Completeness

*For any* running instance of `totogi-backend.exe` or `Totogi Installer.exe`, after the uninstaller completes, no processes with those names from this installation shall remain running.

**Validates: Requirements 1.1, 1.4, 2.1, 2.3**

### Property 2: Graceful Shutdown Timeout

*For any* process termination request, the uninstaller shall wait at most the configured timeout (default 5 seconds) for graceful shutdown before force-killing the process.

**Validates: Requirements 1.2, 7.4**

### Property 3: Application Data Cleanup

*For any* uninstall with `delete_app_data=True`, all files and directories under `%APPDATA%\totogi-installer`, `%LOCALAPPDATA%\totogi-installer`, and `%LOCALAPPDATA%\Totogi Installer` shall be removed.

**Validates: Requirements 3.2, 3.3**

### Property 4: Application Data Preservation

*For any* uninstall with `delete_app_data=False`, all files and directories under the application data paths shall remain unchanged.

**Validates: Requirements 3.4**

### Property 5: Temp File Cleanup

*For any* uninstall operation, all files matching `%TEMP%\totogi-*` and PyInstaller temp directories shall be removed.

**Validates: Requirements 6.1, 6.2, 6.3**

### Property 6: Registry Cleanup

*For any* uninstall operation, all registry keys under `HKCU\Software\totogi-installer` and `HKLM\Software\totogi-installer` shall be removed.

**Validates: Requirements 4.1, 4.2**

### Property 7: Backend Graceful Shutdown

*For any* SIGTERM signal received by the backend process, the process shall complete in-progress operations, close file handles, and release network ports within the configured timeout.

**Validates: Requirements 7.1, 7.2, 7.3**

### Property 8: Uninstall Logging

*For any* uninstall operation, a log file shall be created at `%TEMP%\totogi-uninstall.log` containing entries for each action performed and any errors encountered.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

### Property 9: Silent Mode Exit Codes

*For any* silent uninstall (`/S` flag), the uninstaller shall return exit code 0 on success and non-zero on failure.

**Validates: Requirements 9.1, 9.4**

### Property 10: Error Continuation

*For any* error during a cleanup step, the uninstaller shall log the error and continue with remaining cleanup steps rather than aborting.

**Validates: Requirements 1.3, 5.3, 8.3**

## Error Handling

### Process Termination Errors

- If a process cannot be terminated, log a warning and continue
- If files are locked, schedule removal for next restart using `MoveFileEx` with `MOVEFILE_DELAY_UNTIL_REBOOT`

### Permission Errors

- If lacking permissions, request UAC elevation
- If elevation is denied, display error message with manual cleanup instructions

### File System Errors

- If a directory cannot be removed, log the error and continue
- If a file is in use, attempt to schedule deletion on reboot

## Testing Strategy

### Unit Tests

- Test process detection functions
- Test graceful shutdown handler
- Test file/directory cleanup functions
- Test registry cleanup functions
- Test logging functionality

### Property-Based Tests

Using Hypothesis for Python components:

1. **Process Termination**: Generate random process states and verify termination behavior
2. **File Cleanup**: Generate random file structures and verify cleanup completeness
3. **Timeout Behavior**: Test with various timeout values and process response times

### Integration Tests

- Full uninstall flow with mock processes
- Silent mode testing with various flag combinations
- Error recovery testing with simulated failures

### Manual Tests

- Real uninstall on Windows with running application
- Verify no orphaned processes in Task Manager
- Verify clean registry after uninstall
- Verify application data removal when opted in
