@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI Attendance Pipeline Engine - Windows Launcher

echo ============================================================
echo AI Attendance Pipeline Engine - Windows Launcher
echo ============================================================

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"
echo Working directory: "%ROOT_DIR%"

:: Locate Python executable (.venv2 takes priority over .venv)
set "PYTHON_EXE="
if exist "%ROOT_DIR%.venv2\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%.venv2\Scripts\python.exe"
) else if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python.exe"
)

if not defined PYTHON_EXE (
    echo [ERROR] Virtual environment not found in .venv2 or .venv!
    echo Please create or activate a virtualenv before running.
    pause
    exit /b 1
)

echo Found Python: "!PYTHON_EXE!"

:: Validate Python major version using temp script with CALL to handle paths with spaces
echo import sys; print(sys.version_info.major) > "%TEMP%\check_py_version.py"
for /f "usebackq delims=" %%v in (`call "!PYTHON_EXE!" "%TEMP%\check_py_version.py" 2^>nul`) do set "PY_MAJOR=%%v"
del "%TEMP%\check_py_version.py"

if not "!PY_MAJOR!"=="3" (
    echo [ERROR] Expected Python 3, got "!PY_MAJOR!"
    pause
    exit /b 1
)

echo Environment validated successfully.
echo ============================================================

:: Launch bootstrap supervisor with full argument passthrough
"!PYTHON_EXE!" "%ROOT_DIR%bootstrap.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "!EXIT_CODE!"=="0" (
    echo.
    echo [STOPPED] Supervisor exited with code: !EXIT_CODE!
    pause
)
exit /b !EXIT_CODE!