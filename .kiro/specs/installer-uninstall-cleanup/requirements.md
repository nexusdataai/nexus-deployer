# Requirements Document

## Introduction

This document specifies requirements for proper cleanup of system files, services, and processes when the Totogi Capability Installer is uninstalled. Currently, the backend process (`totogi-backend.exe`) remains running after uninstallation, consuming system resources. The installer must properly terminate all spawned processes and clean up application data during uninstallation.

## Glossary

- **Installer**: The NSIS-based Windows installer created by electron-builder
- **Backend_Process**: The `totogi-backend.exe` Python executable that runs as a background process
- **Electron_App**: The main Electron application that spawns the backend process
- **Application_Data**: User data, logs, and configuration files stored in AppData directories
- **Uninstaller**: The Windows uninstaller component that removes the application

## Requirements

### Requirement 1: Terminate Backend Process on Uninstall

**User Story:** As a user, I want the backend process to be terminated when I uninstall the application, so that no orphaned processes consume system resources.

#### Acceptance Criteria

1. WHEN the Uninstaller runs, THE Uninstaller SHALL terminate all running instances of `totogi-backend.exe` before removing files
2. WHEN the Uninstaller terminates processes, THE Uninstaller SHALL wait up to 5 seconds for graceful shutdown before force-killing
3. IF the backend process cannot be terminated, THEN THE Uninstaller SHALL log a warning and continue with uninstallation
4. WHEN the Uninstaller completes, THE system SHALL have no running `totogi-backend.exe` processes from this installation

### Requirement 2: Terminate Electron Application on Uninstall

**User Story:** As a user, I want the main application to be closed when I uninstall, so that files are not locked during removal.

#### Acceptance Criteria

1. WHEN the Uninstaller runs, THE Uninstaller SHALL check if the Electron_App is running
2. IF the Electron_App is running, THEN THE Uninstaller SHALL prompt the user to close it or offer to close it automatically
3. WHEN the Uninstaller closes the Electron_App, THE Uninstaller SHALL also terminate any child processes (including Backend_Process)
4. IF files are locked by running processes, THEN THE Uninstaller SHALL schedule file removal for next system restart

### Requirement 3: Clean Application Data on Uninstall

**User Story:** As a user, I want the option to remove all application data when uninstalling, so that no residual files remain on my system.

#### Acceptance Criteria

1. WHEN the Uninstaller runs, THE Uninstaller SHALL prompt the user whether to remove Application_Data
2. IF the user chooses to remove Application_Data, THEN THE Uninstaller SHALL delete the following directories:
   - `%APPDATA%\totogi-installer`
   - `%LOCALAPPDATA%\totogi-installer`
   - `%LOCALAPPDATA%\Totogi Installer`
3. WHEN removing Application_Data, THE Uninstaller SHALL remove log files, configuration files, and cached data
4. IF the user chooses to keep Application_Data, THEN THE Uninstaller SHALL preserve all user data directories

### Requirement 4: Clean Registry Entries

**User Story:** As a user, I want all registry entries to be removed when I uninstall, so that my system registry remains clean.

#### Acceptance Criteria

1. WHEN the Uninstaller completes, THE Uninstaller SHALL remove all application registry keys under `HKCU\Software\totogi-installer`
2. WHEN the Uninstaller completes, THE Uninstaller SHALL remove all application registry keys under `HKLM\Software\totogi-installer` (if present)
3. WHEN the Uninstaller completes, THE Uninstaller SHALL remove the uninstall registry entry from `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall`

### Requirement 5: Remove Scheduled Tasks and Services

**User Story:** As a user, I want any scheduled tasks or services to be removed when I uninstall, so that no background operations continue.

#### Acceptance Criteria

1. WHEN the Uninstaller runs, THE Uninstaller SHALL check for and remove any scheduled tasks created by the application
2. WHEN the Uninstaller runs, THE Uninstaller SHALL check for and stop/remove any Windows services registered by the application
3. IF scheduled tasks or services cannot be removed, THEN THE Uninstaller SHALL log a warning with manual removal instructions

### Requirement 6: Clean Temporary Files

**User Story:** As a user, I want temporary files to be cleaned up during uninstallation, so that no disk space is wasted.

#### Acceptance Criteria

1. WHEN the Uninstaller runs, THE Uninstaller SHALL remove temporary files from `%TEMP%\totogi-*`
2. WHEN the Uninstaller runs, THE Uninstaller SHALL remove PyInstaller temporary directories if present
3. WHEN the Uninstaller runs, THE Uninstaller SHALL remove any crash dumps or error logs in temp directories

### Requirement 7: Graceful Shutdown Signal

**User Story:** As a developer, I want the backend process to handle shutdown signals gracefully, so that data is not corrupted during uninstallation.

#### Acceptance Criteria

1. WHEN the Backend_Process receives a termination signal, THE Backend_Process SHALL complete any in-progress operations within 3 seconds
2. WHEN the Backend_Process receives a termination signal, THE Backend_Process SHALL close all open file handles
3. WHEN the Backend_Process receives a termination signal, THE Backend_Process SHALL release all network ports
4. IF the Backend_Process does not respond to graceful shutdown within 5 seconds, THEN THE Uninstaller SHALL force-terminate the process

### Requirement 8: Uninstall Logging

**User Story:** As a support engineer, I want uninstallation to be logged, so that I can troubleshoot failed uninstallations.

#### Acceptance Criteria

1. WHEN the Uninstaller runs, THE Uninstaller SHALL create a log file at `%TEMP%\totogi-uninstall.log`
2. WHEN the Uninstaller performs each cleanup step, THE Uninstaller SHALL log the action and result
3. IF any cleanup step fails, THEN THE Uninstaller SHALL log the error details and continue with remaining steps
4. WHEN the Uninstaller completes, THE Uninstaller SHALL log a summary of actions taken and any failures

### Requirement 9: Silent Uninstall Support

**User Story:** As an IT administrator, I want to uninstall the application silently, so that I can automate deployment management.

#### Acceptance Criteria

1. WHEN the Uninstaller is run with `/S` flag, THE Uninstaller SHALL run silently without user prompts
2. WHEN running silently, THE Uninstaller SHALL use default options (keep user data unless `/D` flag is provided)
3. WHEN the Uninstaller is run with `/S /D` flags, THE Uninstaller SHALL silently remove all Application_Data
4. WHEN running silently, THE Uninstaller SHALL return appropriate exit codes (0 for success, non-zero for failure)

### Requirement 10: Pre-Uninstall Validation

**User Story:** As a user, I want the uninstaller to validate the system state before proceeding, so that uninstallation is reliable.

#### Acceptance Criteria

1. WHEN the Uninstaller starts, THE Uninstaller SHALL verify it has sufficient permissions to remove files
2. IF the Uninstaller lacks permissions, THEN THE Uninstaller SHALL request elevation or display an error message
3. WHEN the Uninstaller starts, THE Uninstaller SHALL detect if the application is currently running
4. IF critical system operations are in progress (e.g., active deployment), THEN THE Uninstaller SHALL warn the user before proceeding
