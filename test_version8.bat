@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PY=C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\.venv2\Scripts\python.exe"

echo import sys; print(sys.version_info.major) > "%TEMP%\check_version.py"
for /f "usebackq delims=" %%v in (`call "!PY!" "%TEMP%\check_version.py" 2^>nul`) do set "PY_MAJOR=%%v"
del "%TEMP%\check_version.py"

echo PY_MAJOR=!PY_MAJOR!
if "!PY_MAJOR!"=="3" (
    echo OK
) else (
    echo FAIL
)