@echo off
REM ============================================================
REM AI Attendance System - Windows Bootstrap Launcher (Phase 42)
REM ============================================================
REM Minimal entrypoint that invokes bootstrap.py for service orchestration.
REM ============================================================

REM Set window title
title AI Attendance System - Bootstrap

REM Resolve script directory (repository root)
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Change to repository root
cd /d "%SCRIPT_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to change to repository root: %SCRIPT_DIR%
    echo [ERROR] Exit code: %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo ============================================================
echo AI Attendance System - Windows Bootstrap
echo ============================================================
echo Repository root: %SCRIPT_DIR%
echo.

REM Check for Python in virtual environment
set "VENV_PYTHON=%SCRIPT_DIR%\.venv2\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found at: %VENV_PYTHON%
    echo [ERROR] Exit code: 1
    echo [HINT] Run 'python -m venv .venv2 && .venv2\Scripts\pip install -r requirements\base.txt -r requirements\windows.txt' first.
    pause
    exit /b 1
)

echo [INFO] Using Python: %VENV_PYTHON%
echo.

REM Invoke bootstrap.py - it owns all service orchestration
echo [INFO] Starting bootstrap orchestrator...
"%VENV_PYTHON%" bootstrap.py
set "BOOTSTRAP_EXIT=%ERRORLEVEL%"

if %BOOTSTRAP_EXIT% neq 0 (
    echo.
    echo [ERROR] Bootstrap failed with exit code: %BOOTSTRAP_EXIT%
    pause
    exit /b %BOOTSTRAP_EXIT%
)

echo.
echo [INFO] Bootstrap completed successfully.
exit /b 0