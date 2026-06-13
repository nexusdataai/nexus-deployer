@echo off
REM Nexus AI Installer - Stop Script (Batch)

echo ========================================
echo   Nexus AI Installer - Stop
echo ========================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0stop-app.ps1"

pause
