@echo off
REM Simple AWS ADFS Login using Python
REM Uses the same authentication logic as the deployment wizard

setlocal

REM Save current directory
set "ORIGINAL_DIR=%CD%"
set "SCRIPT_DIR=%~dp0"

REM Change to script directory
cd /d "%SCRIPT_DIR%"

echo.
echo ========================================
echo   AWS ADFS Login (Python)
echo ========================================
echo.

REM Check if .env.local exists
if not exist ".env.local" (
    echo ERROR: .env.local file not found
    echo Please create .env.local with your ADFS credentials
    echo.
    cd /d "%ORIGINAL_DIR%"
    exit /b 1
)

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found
    echo Please install Python or activate your virtual environment
    echo.
    cd /d "%ORIGINAL_DIR%"
    exit /b 1
)

REM Run the Python login script
python aws-login-python.py

set "EXIT_CODE=%errorlevel%"

REM Return to original directory
cd /d "%ORIGINAL_DIR%"

exit /b %EXIT_CODE%
