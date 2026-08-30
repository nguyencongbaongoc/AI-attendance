# Phase 39 Bootstrap Entrypoint Repair

## 1. Why bootstrap.bat Failed

`bootstrap.bat` contained a reference to a non-existent file `bootstrap.py`
in the repository root. The file `bootstrap.py` does **not** exist anywhere
in the repository. The bootstrap validation step invoked:

```
"%VENV_PYTHON%" bootstrap.py
```

which produced:

```
can't open file 'C:\Users\Nguyen Cong Thong\Desktop\AI attendance\bootstrap.py'
[ERROR] Bootstrap validation failed
[ERROR] Exit code: 2
```

The root cause is a stale reference to a previous architecture's entrypoint
(`bootstrap.py`) that was never actually present in the current repository.
The canonical bootstrap validation logic lives in
`app/bootstrap/startup_validation.py` (entry: `run_startup_validation()`).

## 2. Actual Canonical Entrypoint

**Module:** `app.bootstrap.startup_validation`
**Command:** `%VENV_PYTHON% -m app.bootstrap.startup_validation`
**File:** `C:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\bootstrap\startup_validation.py`

This module contains `StartupValidator`, `run_startup_validation()`,
`print_validation_report()`, and an `if __name__ == "__main__"` guard that
runs all checks and exits with code 1 on hard failure, 0 on pass or warn.

## 3. Previous Incorrect Entrypoint

```
bootstrap.py   (does not exist in repository root)
```

## 4. Correct Command (in bootstrap.bat)

Replaced:

```
"%VENV_PYTHON%" bootstrap.py
```

with:

```
"%VENV_PYTHON%" -m app.bootstrap.startup_validation
```

## 5. Python Executable Used

```
C:\Users\Nguyen Cong Thong\Desktop\AI attendance\.venv\Scripts\python.exe
```

Version: Python 3.12.10

This is the canonical project venv interpreter, not the system
`AppData\Local\Programs\Python\Python312\python.exe`.

## 6. Uvicorn / FastAPI Startup

Uvicorn **is started separately** by `bootstrap.bat` (line 118):

```
"%VENV_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The canonical application entrypoint is `app/main.py`, which defines
`create_app()` returning a `FastAPI` instance with a `lifespan` context
manager, and an `if __name__ == "__main__"` block that calls
`uvicorn.run("app.main:app", ...)`.

**No duplicate Uvicorn launch**: bootstrap validation runs first
(`app.bootstrap.startup_validation`), then Uvicorn is launched once.
The architecture intentionally separates bootstrap validation from the
Uvicorn server start.

## 7. MediaMTX Behavior

MediaMTX is **not** automatically launched by `bootstrap.bat`. The script
checks for `mediamtx\mediamtx.exe` and, if present, prints instructions for
manual startup:

```
cd /d "%SCRIPT_DIR%\mediamtx" && mediamtx.exe mediamtx.yml
```

No second MediaMTX instance is launched.

## 8. Startup Chain (Traced)

| Step | File | Function / Command |
|------|------|--------------------|
| Bootstrap launcher | `bootstrap.bat` | Shell script launcher |
| Canonical Python entrypoint | `app/bootstrap/startup_validation.py` | `run_startup_validation()` via `-m app.bootstrap.startup_validation` |
| Configuration | `app/config/settings.py` | `load_settings()` |
| Startup validation | `app/bootstrap/startup_validation.py` | `StartupValidator.run_all_validations()` |
| FastAPI app factory | `app/main.py` | `create_app()` |
| Uvicorn server | `bootstrap.bat` | `%VENV_PYTHON% -m uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| API readiness | `app/api/health.py` | `/api/v1/health/system` endpoint |

## 9. Tests Performed

| # | Test | Result |
|---|------|--------|
| 1 | Bootstrap validation via venv python module | PASS (exit code 0, 27 pass / 3 warn / 1 skip) |
| 2 | Python executable path check | PASS (`...\AI attendance\.venv\Scripts\python.exe`) |
| 3 | Python version | PASS (3.12.10) |
| 4 | FastAPI startup via `app/main.py` | PASS (Uvicorn started, port 8000) |
| 5 | API health endpoint `GET /api/v1/health/system` | PASS (HTTP 200, overall_status=unhealthy due to no cameras) |
| 6 | Clean shutdown of Uvicorn | PASS (process terminated) |
| 7 | Second startup | PASS (server restarted, health endpoint responded) |

## 10. Files Modified

- `bootstrap.bat`
  - Line 84: Replaced `"%VENV_PYTHON%" bootstrap.py` with
    `"%VENV_PYTHON%" -m app.bootstrap.startup_validation`
  - Line 5: Updated REM comment to reference the correct module.

## Files Created

- `benchmark_results/PHASE_39_BOOTSTRAP_ENTRYPOINT_REPAIR.md` (this file)
- `benchmark_results/PHASE_39_BOOTSTRAP_ENTRYPOINT_REPAIR.json`

## Invariants Preserved

- embeddings.npy: not modified
- enrollment database: not modified
- timetable data: not modified
- attendance database: not modified
- Telegram token: not modified
- camera architecture: not modified
- MediaMTX architecture: not modified (manual startup only)
- GPU architecture: not modified
