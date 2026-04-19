@echo off
REM Totogi Installer - Startup Script (Batch)
REM This launches the PowerShell script

echo ========================================
echo   Totogi Installer - Startup
echo ========================================
echo.

REM Check if PowerShell is available
where powershell >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PowerShell is not available
    echo Please run start-app.ps1 directly
    pause
    exit /b 1
)

REM Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0start-app.ps1"

pause
