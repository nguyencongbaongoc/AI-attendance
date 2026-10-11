# Backend Wiring Matrix & Target Plan Gap Analysis

**Generated:** 2026-10-11  
**Scope:** Read-only AST / Graphify audit of `app/`, `pipeline_engine/`, `scripts/`, `tools/`  
**Mode:** Compliance check against Target Architecture (MySQL Master DB, Excel Import/Export, `student_id` → `{student_id}.npy`, ArcFace DB Loader)

---

## A. Component Wiring Matrix

| Component / Feature | Current State | File Location / Path | Wired to Main API? |
| :--- | :--- | :--- | :--- |
| **MySQL Engine** | **Missing** — No MySQL connection logic, zero references to `pymysql`/`mysql` in codebase. System is strictly SQLite-bound. | N/A | N/A |
| **SQLite Schema** | **Exists** — `attendance_records` table (52 columns), 4 auxiliary DBs: `parent_registry.db`, `notification_queue.db`, `exit_sessions.db`. Idempotent migration for evidence URLs implemented. | `app/attendance/storage.py:80-160`<br>`app/attendance/storage.py:31-54` | Yes — via `AttendanceStorage` & `AttendanceRepository` |
| **Student Master Model** | **Partial** — `app/identity/models.py` defines `GlobalPersonID` with `person_id` (e.g., `PERSON_A1B2C3D4`), `IdentityState` enum, and embeddings. **No `Student` / `Class` / `Roster` entity.** Enrollment uses `person_id` (e.g., `TEST-001`, `STU-10001`) but no class linkage. | `app/identity/models.py:52-64`<br>`app/vision/enrollment.py:320-492` | Yes — `persons_router` (`/api/v1/persons`) |
| **Excel Importer** | **Exists (Timetable only)** — `TimetableLoader.load_from_excel()` parses `.xlsx` with required columns: `student_id`, `class_name`, `day`, `session_type`, `entry_time`, `exit_time`. Validates against enrollment `person_ids`. **No Student Roster import endpoint.** | `app/attendance/timetable_loader.py:244-284`<br>`app/attendance/timetable_loader.py:37-65` | Yes — via `timetable_router` (mounted) |
| **Excel Exporter** | **Exists** — `DailyExcelExporter.export_daily_attendance()` generates multi-sheet `.xlsx` (DAILY_ATTENDANCE, EVENTS, SUMMARY, PROVENANCE, EXPECTED_SCHEDULE) with color-coded states and provenance. Uses `openpyxl`. | `app/attendance/daily_excel.py:88-189`<br>`app/api/excel.py:115-157` | Yes — `excel_router` (`/api/v1/excel`) |
| **Face `.npy` by ID** | **Partial / Non-Compliant** — Two storage patterns coexist:<br>1. **Composite**: `app/data/enrollment/embeddings.npy` (N×512) + `embeddings.npy.metadata.json` with `person_ids` array.<br>2. **Per-Person**: `app/api/enrollment.py:186-193` writes `{person_id}.npy` (e.g., `STU-10001.npy`).<br>ArcFace `load_enrollment_database()` loads **composite only**; `person_id` keys are `person_0000`, `person_0001` then overridden by metadata. | `app/vision/enrollment.py:699-788`<br>`app/api/enrollment.py:186-193`<br>`pipeline_engine/inference/face_recognition.py:196-263` | Yes — `enrollment_router` (`/api/v1/enrollment`) |
| **ArcFace DB Loader** | **File-based, not DB-driven** — `ArcFaceRecognizer.load_enrollment_database(embeddings_path, metadata_path)` loads from NPY files. **No MySQL/SQLite query.** On startup, logs warn if `data/embeddings.npy` missing. | `pipeline_engine/inference/face_recognition.py:196-263`<br>`pipeline_engine/inference/face_recognition.py:543-545` | No — initialized via `create_arcface_recognizer()` in CameraRuntime, not via API |

---

## B. Target Plan Gap Analysis

### ✅ Fully Matched (Already Built & Wired)
| Feature | Evidence |
| :--- | :--- |
| **Daily Excel Export (multi-sheet, color-coded, provenance)** | `app/attendance/daily_excel.py`, `app/api/excel.py` — 5 sheets, conditional formatting, absolute paths |
| **Timetable Excel Import (validation, enrollment cross-check)** | `app/attendance/timetable_loader.py` — required columns, defaults, duplicate/overlap detection, enrollment validation |
| **Enrollment API (image upload → composite NPY + per-person NPY)** | `app/api/enrollment.py:118-215` — `POST /persons`, `GET /persons`, `POST /reload` |
| **Attendance Query API (filters, timeline, summary, stats)** | `app/api/attendance.py` — 9 endpoints, `AttendanceQueryBuilder` fluent API |
| **Persons Search & Enrollment Stats API** | `app/api/persons.py` — search, detail, appearances, enrollment list/stats |
| **SQLite Attendance Storage (idempotent, indexed, migration)** | `app/attendance/storage.py` — `attendance_records` with 52 cols, 19 indexes, WAL, thread-safe |

### ⚠️ Partially Matched / Needs Refactoring
| Feature | Current State | Target Requirement | Gap |
| :--- | :--- | :--- | :--- |
| **Student/Class Roster Model** | `GlobalPersonID` exists but no `Student` (class_id, grade, section), `Class`, or `Roster` table. Timetable uses `student_id` string but no FK to student master. | MySQL tables: `students(student_id PK, full_name, class_id FK)`, `classes(class_id PK, name)`, `rosters` | Add SQLAlchemy/MySQL models; migrate timetable `student_id` → FK |
| **Embedding Storage Contract** | Dual pattern: composite `embeddings.npy` + per-person `{id}.npy`. ArcFace loads composite; enrollment writes both. | **Single contract**: `{student_id}.npy` files in `app/data/embeddings/`; composite NPY retired. ArcFace loads by querying DB for active students. | Standardize on per-person NPY; add `embedding_path` column to student table; retire composite loader |
| **ArcFace Identity Loader** | `load_enrollment_database(npypath, metapath)` — file scan only. | `load_from_database()` — `SELECT student_id FROM students WHERE active=1` → load `app/data/embeddings/{student_id}.npy` | Replace file scan with DB query; add `embedding_path` resolver |
| **MySQL Integration** | Zero MySQL code. Settings has no MySQL section. | Add `MySQLConfig` to settings; SQLAlchemy async engine; repository adapters | New `app/db/` module; `MySQLAttendanceRepository`, `MySQLStudentRepository` |

### ❌ Missing / Needs Implementation
| Feature | Description |
| :--- | :--- |
| **Student Roster Excel Import Endpoint** | `POST /api/v1/students/import` — parse `.xlsx` (`student_id`, `full_name`, `class_id`), upsert into MySQL `students` + `classes`, return validation report. |
| **MySQL Schema & Migrations** | Alembic or raw SQL migrations for `students`, `classes`, `rosters`, `attendance_logs` (MySQL equivalent of `attendance_records`). |
| **MySQL Connection Pool & Settings** | `MySQLConfig(host, port, user, password, database, pool_size)` in `app/config/settings.py`; async engine in `app/db/engine.py`. |
| **Dual-Write / Migration Strategy** | Phase approach: keep SQLite for attendance (low risk), add MySQL for roster. Or full cutover with replication. |
| **ArcFace Hot-Reload on Roster Change** | File watcher or API notification (`POST /enrollment/reload` already exists) → re-query MySQL → reload `{student_id}.npy` files. |
| **Export Snapshot URLs in Excel** | Daily export already has `snapshot_face_url`, `snapshot_scene_url`, `video_clip_url` columns in schema — need to populate & hyperlink in `DAILY_ATTENDANCE` sheet. |

---

## C. Recommended Minimal Path to Target

**Principle:** Non-breaking, incremental. Keep Architecture A (SQLite attendance, composite NPY) stable while adding Architecture B (MySQL roster, per-person NPY) alongside.

| Step | Action | Files to Create / Modify | Risk |
| :--- | :--- | :--- | :--- |
| **1. Add MySQL Config & Engine** | `MySQLConfig` in `settings.py`; `app/db/engine.py` (SQLAlchemy async engine + sessionmaker); `app/db/models.py` (`Student`, `Class`, `Roster`, `AttendanceLog`). | `app/config/settings.py`<br>`app/db/engine.py` (new)<br>`app/db/models.py` (new) | Low — additive only |
| **2. Student Roster Import Endpoint** | `app/api/students.py` (new router) with `POST /import` using `openpyxl`; validates columns, upserts `Student` + `Class`, returns report. Mount in `main.py`. | `app/api/students.py` (new)<br>`app/main.py` (add router) | Low — new endpoint |
| **3. Per-Person NPY Convention** | Modify `app/api/enrollment.py:186-193` to write **only** `app/data/embeddings/{person_id}.npy` (ensure dir exists). Add `embedding_path` column to `Student` model. Deprecate composite `embeddings.npy` write (keep read for backward compat). | `app/api/enrollment.py`<br>`app/db/models.py` | Medium — changes enrollment output; test reload |
| **4. ArcFace DB-Driven Loader** | Add `ArcFaceRecognizer.load_from_student_db(async_session)` method: query active students → load each `{student_id}.npy` → populate `_enrollment_embeddings`. Keep `load_enrollment_database()` for compat. | `pipeline_engine/inference/face_recognition.py` | Medium — core inference path |
| **5. Wire ArcFace Reload to Roster Changes** | On successful student import, call `POST /enrollment/reload` (existing) or add file watcher on `app/data/embeddings/`. | `app/api/students.py` (call reload)<br>or `scripts/embedding_watcher.py` (new) | Low — uses existing reload endpoint |
| **6. Attendance MySQL Adapter (Optional, Phase 2)** | `MySQLAttendanceRepository` implementing same interface as `AttendanceRepository`. Dual-write or cutover via feature flag. | `app/attendance/mysql_repository.py` (new) | High — defer until roster stable |

---

## D. Key Constraints & Notes

1. **No MySQL driver code exists** — `PyMySQL` and `SQLAlchemy` are installed in `.venv2` but unused.
2. **`student_id` ↔ `person_id` mapping** — Timetable uses `student_id` (e.g., `HS001`); enrollment uses `person_id` (e.g., `STU-10001`, `TEST-001`). Need explicit mapping or unify on single ID format.
3. **Composite NPY is loaded by ArcFace at startup** — `CameraRuntimeManager` creates per-camera `ArcFaceRecognizer` instances; each loads `data/embeddings.npy`. This duplicates GPU memory (noted in audit docs). Target: **single shared recognizer** + per-person NPY lazy load.
4. **Daily Excel Exporter is production-ready** — generates 5 sheets, color codes, provenance. Only missing: hyperlinking `snapshot_*_url` columns (already in SQLite schema).
5. **Timetable Loader validates against enrollment `person_ids`** — `TimetableLoader(enrollment_person_ids=[...])` cross-checks. This is the correct integration point for roster validation.

---

## E. Decision Gate

**Ready to implement?** → **Yes, for Steps 1-3 (MySQL Config, Student Import, Per-Person NPY)**. These are additive and non-breaking.

**Defer:** Step 4 (ArcFace DB Loader) until Step 3 verified; Step 6 (Attendance MySQL) until roster pipeline stable.

**Next Action:** Present this matrix; await go-ahead for Step 1 implementation.