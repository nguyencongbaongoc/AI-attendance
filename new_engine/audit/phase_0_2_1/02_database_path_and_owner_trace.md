# Phase 0.2.1 — Database Path and Owner Trace

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED

---

## 1. Executive Summary

Traced all database path references from source code and configuration. **Critical finding:** Legacy Backend has a working-directory-dependent database path resolution that creates two active `attendance.db` instances. PipelineEngine independently configures `data/attendance_events.db` (different schema).

---

## 2. Configuration-Level Path Resolution

### 2.1 `app/config/settings.py` — `Settings.paths.data_dir`

```python
class PathsConfig(BaseModel):
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / "data", description="Data directory")
    # ... validator resolves to absolute path
```

**Resolution:** `Path.cwd() / "data"` → depends on current working directory at startup.

| Startup CWD | Resolved `data_dir` | Resulting `attendance.db` |
|-------------|---------------------|---------------------------|
| Project root (`/repo`) | `/repo/data` | `data/attendance.db` |
| `app/` directory | `/repo/app/data` | `app/data/attendance.db` |

**Evidence:** SOURCE VERIFIED — `settings.py` lines 43-59

---

### 2.2 `app/config/settings.py` — Individual DB Configs

| Config Class | Field | Default Value | Resolution |
|--------------|-------|---------------|------------|
| `ParentRegistryConfig` | `db_path` | `"data/parent_registry.db"` | Relative to `data_dir` |
| `NotificationQueueConfig` | `db_path` | `"data/notification_queue.db"` | Relative to `data_dir` |
| `ExitSessionConfig` | `db_path` | `"data/exit_sessions.db"` | Relative to `data_dir` |

**Note:** These are string paths, not `Path` objects — they are joined with `data_dir` at runtime.

**Evidence:** SOURCE VERIFIED — `settings.py` lines 253-276

---

### 2.3 `app/attendance/storage.py` — `StorageConfig`

```python
@dataclass
class StorageConfig:
    database_path: str = "data/attendance.db"
```

**Resolution:** Passed to `sqlite3.connect(str(db_path))` — relative to process CWD.

**Evidence:** SOURCE VERIFIED — `storage.py` lines 20-27, 121-124

---

## 3. Source Code Database References

### 3.1 Legacy Backend — Attendance Storage

| File | Line | Database Path | Read/Write | Component | Purpose |
|------|------|---------------|------------|-----------|---------|
| `app/attendance/storage.py` | 23 | `data/attendance.db` (default) | R/W | `AttendanceStorage` | Phase 25 AttendanceRecord persistence |
| `app/attendance/storage.py` | 121 | `str(db_path)` | R/W | `AttendanceStorage._get_connection()` | SQLite connection |
| `app/attendance/repository.py` | 47 | Via `create_attendance_storage()` | R/W | `AttendanceRepository` | High-level attendance persistence |
| `app/attendance/engine.py` | 121 | Via `create_attendance_repository()` | R/W | `AttendanceEngine` | Policy-driven attendance resolution |
| `app/api/attendance.py` | 41 | Via `create_attendance_repository()` | R | API endpoints | Query attendance records |
| `app/api/persons.py` | 34 | Via `create_attendance_repository()` | R | API endpoints | Person attendance queries |
| `app/api/replay.py` | 150 | Via `create_attendance_repository()` | R | API endpoints | Replay attendance data |
| `app/api/provenance.py` | — | Via injected `AttendanceRepository` | R | API endpoints | Provenance chain queries |
| `app/attendance/daily_excel.py` | 107 | Via `AttendanceRepository()` | R | Excel export | Daily attendance export |
| `app/attendance/query.py` | 72 | Via injected `AttendanceRepository` | R | Query builder | Complex attendance queries |
| `app/streaming/detection_pipeline.py` | 218 | Via `create_attendance_repository()` | R/W | Detection pipeline | Store crossing events as attendance |
| `app/attendance/policy_engine/factory.py` | — | Via `AttendanceRepository` | R/W | Policy engine | Attendance policy evaluation |
| `app/attendance/policy_engine/excel_integration.py` | 81, 447 | Via `AttendanceRepository` | R | Excel integration | Excel attendance reports |

---

### 3.2 Legacy Backend — Supporting Databases

| File | Line | Database Path | Read/Write | Component | Purpose |
|------|------|---------------|------------|-----------|---------|
| `app/attendance/policy_engine/telegram_bot.py` | 479, 538, 638, 660, 673, 686, 720, 733, 744, 755, 772, 925 | `self.db_path` (from `settings.parent_registry.db_path`) | R/W | Telegram bot | Parent registry & notifications |
| `app/attendance/policy_engine/parent_registry.py` | 208-612 | `self.db_path` (from `settings.parent_registry.db_path`) | R/W | Parent registry | Parent/student linking |
| `app/attendance/policy_engine/exit_session.py` | 99-282 | `self.db_path` (from `settings.exit_session.db_path`) | R/W | Exit sessions | Exit session persistence |
| `app/operational/cli.py` | 284, 297 | `settings.notification_queue.db_path` | R | CLI tools | Notification queue inspection |
| `app/operational/cli.py` | 343 | `exit_db` (from `settings.exit_session.db_path`) | R | CLI tools | Exit session inspection |
| `app/bootstrap/startup_validation.py` | 211 | `db_path` (varies) | R | Startup validation | Database connectivity check |

---

### 3.3 PipelineEngine — Independent Databases

| File | Line | Database Path | Read/Write | Component | Purpose |
|------|------|---------------|------------|-----------|---------|
| `pipeline_engine/attendance/attendance_engine.py` | 132 | `"data/attendance_events.db"` (default) | R/W | `AttendanceStore` | CrossingEvent storage |
| `pipeline_engine/attendance/attendance_engine.py` | 139, 174, 212, 246 | `self.db_path` | R/W | `AttendanceStore` | SQLite operations |
| `pipeline_engine/config/pipeline.yaml` | 278 | `event_db_path: "data/attendance_events.db"` | Config | PipelineEngine config | Attendance event store path |
| `pipeline_engine/config/pipeline.yaml` | 282 | `daily_db_path: "data/attendance_daily.db"` | Config | PipelineEngine config | Daily records path |

**Critical:** PipelineEngine uses **different schema** (`attendance_events` table) — NOT `attendance_records`.

---

### 3.4 PipelineEngine — Legacy Backend Database References (Config Only)

| File | Line | Database Path | Context |
|------|------|---------------|---------|
| `pipeline_engine/config/pipeline.yaml` | 429 | `attendance: "data/attendance.db"` | `integration.databases` section — reference only |
| `pipeline_engine/config/pipeline.yaml` | 430 | `exit_sessions: "data/exit_sessions.db"` | Reference only |
| `pipeline_engine/config/pipeline.yaml` | 431 | `notification_queue: "data/notification_queue.db"` | Reference only |
| `pipeline_engine/config/pipeline.yaml` | 432 | `parent_registry: "data/parent_registry.db"` | Reference only |

**Note:** These are in `integration.databases` section — documented references for future integration, NOT currently used by PipelineEngine code.

---

## 4. Runtime Path Resolution Trace

### 4.1 Legacy Backend Startup (from `app/main.py`)

```python
# app/main.py line 139-140
backend_port = find_backend_port()
uvicorn.run("app.main:app", host="0.0.0.0", port=backend_port)
```

**Actual startup command** (from Phase 0.2 verification):
```bash
.venv2\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.');
from app.main import create_app;
import uvicorn;
uvicorn.run(create_app(), host='0.0.0.0', port=19146)
"
```

**CWD at startup:** Project root (`/repo`) — because `sys.path.insert(0, '.')` adds project root.

**Result:** `Path.cwd() / "data"` = `/repo/data` → `data/attendance.db` is the configured default.

**BUT:** If started from `app/` directory (e.g., `cd app && python -m app.main`), CWD = `/repo/app` → `app/data/attendance.db`.

---

### 4.2 Evidence of Dual Active Instances

Both databases have **active WAL/SHM files** (32 KB each), indicating recent writes:

| Database | WAL Size | SHM Size | Interpretation |
|----------|----------|----------|----------------|
| `app/data/attendance.db` | 32 KB | 32 KB | Active writes from Legacy Backend started with CWD=`app/` |
| `data/attendance.db` | 32 KB | 32 KB | Active writes from Legacy Backend started with CWD=project root |

**Conclusion:** The Legacy Backend has been started at least twice with different CWDs, creating two active database instances.

---

## 5. Owner Trace Summary Matrix

| Database | Configured Owner | Actual Writer(s) | Path Resolution | Authority |
|----------|------------------|------------------|-----------------|-----------|
| `data/attendance.db` | Legacy Backend (`Settings.paths.data_dir` + `StorageConfig`) | Legacy Backend (when CWD=project root) | CWD-dependent | **ACTIVE SECONDARY** |
| `app/data/attendance.db` | Legacy Backend (implicit when CWD=`app/`) | Legacy Backend (when CWD=`app/`) | CWD-dependent | **AUTHORITATIVE** (has production data) |
| `data/attendance_events.db` | PipelineEngine (`pipeline.yaml`) | PipelineEngine (`AttendanceStore`) | CWD-dependent (project root) | **PipelineEngine-owned** (different schema) |
| `data/attendance_daily.db` | PipelineEngine (`pipeline.yaml`) | Not yet created | — | **PLANNED** |
| `data/exit_sessions.db` | Legacy Backend (`ExitSessionConfig`) | Legacy Backend | CWD-dependent | **DUPLICATE** of `app/data/exit_sessions.db` |
| `app/data/exit_sessions.db` | Legacy Backend (implicit) | Legacy Backend | CWD-dependent | **AUTHORITATIVE** |
| `data/parent_registry.db` | Legacy Backend (`ParentRegistryConfig`) | Legacy Backend | CWD-dependent | **DUPLICATE** of `app/data/parent_registry.db` |
| `app/data/parent_registry.db` | Legacy Backend (implicit) | Legacy Backend | CWD-dependent | **AUTHORITATIVE** |
| `data/notification_queue.db` | Legacy Backend (`NotificationQueueConfig`) | Legacy Backend | CWD-dependent | **DUPLICATE** of `app/data/notification_queue.db` |
| `app/data/notification_queue.db` | Legacy Backend (implicit) | Legacy Backend | CWD-dependent | **AUTHORITATIVE** |

---

## 6. Critical Path Resolution Bug

**File:** `app/config/settings.py` lines 43-59

```python
data_dir: Path = Field(default_factory=lambda: Path.cwd() / "data", description="Data directory")

@field_validator("*", mode="before")
@classmethod
def resolve_paths(cls, v: Any) -> Path:
    if isinstance(v, (str, Path)):
        return Path(v).resolve()  # Resolves relative to CWD
    return v
```

**Problem:** `Path.cwd()` captures CWD at **settings load time**, not at database connection time. But `StorageConfig.database_path = "data/attendance.db"` is a **string**, not a `Path`, so it bypasses the validator and is resolved at `sqlite3.connect()` time — again relative to CWD.

**Result:** Two different resolution mechanisms, both CWD-dependent, creating ambiguity.

---

## 7. Recommendations for Phase 1

1. **Fix `Settings.paths.data_dir`** to use an explicit, absolute path (e.g., from `__file__` or environment variable).
2. **Change `StorageConfig.database_path`** to `Path` type with validator, or compute absolute path at init.
3. **Eliminate `data/` duplicate** — keep only `app/data/` as authoritative (contains production data).
4. **PipelineEngine** must use Legacy Backend API for attendance writes — remove local `attendance_events.db` or make it read-only cache.

---

**End of Database Path and Owner Trace**