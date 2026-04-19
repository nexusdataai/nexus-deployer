@echo off
REM Set UTF-8 encoding to prevent emoji encoding errors on Windows
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>&1
call venv\Scripts\activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
