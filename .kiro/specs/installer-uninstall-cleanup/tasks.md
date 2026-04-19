# Implementation Plan: Installer Uninstall Cleanup

## Overview

This implementation plan addresses the issue where the backend process remains running after uninstallation. The tasks are ordered to first add graceful shutdown handling to the backend, then create the uninstall scripts, and finally integrate with electron-builder.

## Tasks

- [x] 1. Add graceful shutdown handler to Python backend
  - [x] 1.1 Create backend/app/utils/shutdown_handler.py
    - Implement GracefulShutdownHandler class
    - Register SIGTERM, SIGINT, SIGBREAK signal handlers
    - Add callback registration for cleanup tasks
    - Implement timeout-based shutdown with logging
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [x] 1.2 Write property test for graceful shutdown
    - **Property 7: Backend Graceful Shutdown**
    - **Validates: Requirements 7.1, 7.2, 7.3**

- [x] 2. Integrate shutdown handler into backend main.py
  - [x] 2.1 Update backend/app/main.py
    - Initialize GracefulShutdownHandler on startup
    - Register cleanup callbacks for open connections
    - Register cleanup for file handles and ports
    - _Requirements: 7.1, 7.2, 7.3_

- [x] 3. Checkpoint - Verify graceful shutdown
  - Test backend responds to SIGTERM correctly
  - Verify port is released after shutdown
  - Ensure all tests pass, ask the user if questions arise

- [x] 4. Create process termination PowerShell script
  - [x] 4.1 Create electron/scripts/terminate-processes.ps1
    - Implement Terminate-Process function with graceful timeout
    - Add logging to uninstall log file
    - Handle both backend and Electron processes
    - Support force-kill after timeout
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.3_
  - [x] 4.2 Write property test for process termination
    - **Property 1: Process Termination Completeness**
    - **Property 2: Graceful Shutdown Timeout**
    - **Validates: Requirements 1.1, 1.2, 1.4, 2.1, 2.3**

- [x] 5. Create application data cleanup script
  - [x] 5.1 Create electron/scripts/cleanup-appdata.ps1
    - Implement removal of AppData directories
    - Add option to preserve or delete user data
    - Handle locked files with reboot scheduling
    - Log all cleanup actions
    - _Requirements: 3.2, 3.3, 3.4_
  - [x] 5.2 Write property test for data cleanup
    - **Property 3: Application Data Cleanup**
    - **Property 4: Application Data Preservation**
    - **Validates: Requirements 3.2, 3.3, 3.4**

- [x] 6. Create temp file cleanup script
  - [x] 6.1 Create electron/scripts/cleanup-temp.ps1
    - Remove totogi-* temp files
    - Remove PyInstaller temp directories
    - Remove crash dumps and error logs
    - _Requirements: 6.1, 6.2, 6.3_
  - [x] 6.2 Write property test for temp cleanup
    - **Property 5: Temp File Cleanup**
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 7. Create registry cleanup script
  - [x] 7.1 Create electron/scripts/cleanup-registry.ps1
    - Remove HKCU\Software\totogi-installer keys
    - Remove HKLM\Software\totogi-installer keys (if admin)
    - Log registry cleanup actions
    - _Requirements: 4.1, 4.2, 4.3_
  - [x] 7.2 Write property test for registry cleanup
    - **Property 6: Registry Cleanup**
    - **Validates: Requirements 4.1, 4.2**

- [x] 8. Create uninstall logger module
  - [x] 8.1 Create electron/scripts/uninstall-logger.ps1
    - Implement logging functions
    - Create log file at %TEMP%\totogi-uninstall.log
    - Add action logging with timestamps
    - Add summary generation
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [x] 8.2 Write property test for uninstall logging
    - **Property 8: Uninstall Logging**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**

- [x] 9. Checkpoint - Verify cleanup scripts
  - Test each script individually
  - Verify logging output
  - Ensure all tests pass, ask the user if questions arise

- [x] 10. Create NSIS installer configuration
  - [x] 10.1 Create electron/installer.nsh
    - Define customUnInstall macro
    - Call process termination script
    - Add user prompt for data cleanup
    - Call cleanup scripts in order
    - Handle silent mode flags
    - _Requirements: 1.1, 2.2, 3.1, 9.1, 9.2, 9.3_

- [x] 11. Update electron-builder configuration
  - [x] 11.1 Update electron/package.json
    - Add nsis.include for installer.nsh
    - Add extraResources for cleanup scripts
    - Configure uninstaller display name
    - _Requirements: 9.1, 9.4_

- [x] 12. Add pre-uninstall validation
  - [x] 12.1 Create electron/scripts/pre-uninstall-check.ps1
    - Check for running application
    - Check for active deployments
    - Verify permissions
    - _Requirements: 10.1, 10.3, 10.4_
  - [x] 12.2 Write property test for validation
    - **Property 10: Error Continuation**
    - **Validates: Requirements 1.3, 5.3, 8.3**

- [x] 13. Update Electron main.js for clean exit
  - [x] 13.1 Update electron/main.js
    - Ensure backend process is killed on app quit
    - Add process tree termination
    - Handle window close vs app quit
    - _Requirements: 2.3_

- [x] 14. Checkpoint - Integration testing
  - Build installer with new uninstall hooks
  - Test full uninstall flow
  - Verify no orphaned processes
  - Test silent uninstall mode
  - Ensure all tests pass, ask the user if questions arise

- [x] 15. Final checkpoint - End-to-end verification
  - Install application
  - Run backend process
  - Uninstall application
  - Verify Task Manager shows no totogi-backend.exe
  - Verify application data cleanup (when opted in)
  - Verify registry is clean
  - Ensure all tests pass, ask the user if questions arise

## Notes

- All tasks including property-based tests are required
- Task 1-2 focus on backend graceful shutdown
- Tasks 4-8 create the cleanup scripts
- Tasks 10-11 integrate with NSIS installer
- Task 13 ensures Electron properly terminates child processes
- Each task references specific requirements for traceability
- PowerShell scripts are used for Windows-specific cleanup operations
