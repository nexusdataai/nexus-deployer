@echo off
REM Totogi Installer - Stop Script (Batch)

echo ========================================
echo   Totogi Installer - Stop
echo ========================================
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0stop-app.ps1"

pause
