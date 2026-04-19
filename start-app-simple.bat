@echo off
REM Totogi Installer - Simple Startup Script (Batch wrapper)

echo ========================================
echo   Totogi Installer - Simple Startup
echo ========================================
echo.

REM Check if PowerShell is available
where powershell >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PowerShell is not available
    pause
    exit /b 1
)

REM Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0start-app-simple.ps1"

pause
