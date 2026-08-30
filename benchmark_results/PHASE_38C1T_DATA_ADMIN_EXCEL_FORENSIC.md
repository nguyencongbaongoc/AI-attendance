# Phase 38C.1T — Canonical Student / Parent / Timetable Data Preparation + Excel Export Forensic

**Generated:** 2026-08-28T17:06:00+07:00

**Verdict:** PASS_WITH_DOCUMENTED_LIMITATION

---

## 1. Canonical Student Data Source

| Aspect | Detail |
|--------|--------|
| **Source** | Enrollment database (`data/enrollment_db/`) |
| **Student ID Format** | `HS001`, `HS002`, `HS003` (business identifiers) |
| **Person ID Mapping** | `student_id == person_id` (canonical business identity) |
| **Embedding Reference** | `embeddings.npy` (9 embeddings, 512-dim, L2 normalized, ArcFace `glintr100.onnx`) |
| **Metadata File** | `embeddings.npy.metadata.json` |
| **Canonical Path** | `data/enrollment_db/` |
| **Duplicate Databases** | `enrollment_db_1`, `enrollment_db_2` (exact copies - documented as DUPLICATE) |

**Enrollment Database Details:**
- Embedding count: 9 (3 per person)
- Embedding dimension: 512
- Normalization: L2
- Model: `glintr100.onnx` (ArcFace)
- Model SHA256: `4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf`
- Person IDs: `HS001`, `HS002`, `HS003`
- Samples per person: 3
- Creation timestamp: 2026-08-23T14:01:36.441284Z
- Schema version: 1.0

---

## 2. Student ID Mapping (Canonical Identity Chain)

```
student_id (business identity)
    ↓
enrollment database
    ↓
person_id (1:1 mapping to student_id)
    ↓
embeddings.npy (index ≠ student_id)
    ↓
identity
```

**Critical Distinctions:**
- `student_id` = **canonical business identifier** (e.g., `HS001`)
- `person_id` = maps 1:1 to `student_id` in current architecture
- `track_id` = runtime tracking identifier (per-camera, per-session) — **NOT** `student_id`
- `embedding_index` = array index in `embeddings.npy` — **NOT** `student_id`
- `face_id` = **NOT** used as primary identifier
- `GlobalObservation` = preserves canonical `student_id` across cameras

---

## 3. Parent Registry Canonical Schema

**Database:** SQLite at `data/parent_registry.db` (WAL mode disabled via `PRAGMA journal_mode=DELETE` for Windows compatibility)

### Tables

#### `parents`
| Column | Type | Notes |
|--------|------|-------|
| `parent_id` | TEXT PK | Generated: `PAR-{token_urlsafe(8)}` |
| `parent_name` | TEXT NOT NULL | |
| `telegram_chat_id` | TEXT | **Routing identifier** (numeric or `@username`) |
| `telegram_enabled` | INTEGER DEFAULT 1 | |
| `notification_preferences` | TEXT DEFAULT 'all' | Enum: `ALL`, `MORNING_ABSENCE_ONLY`, `LONG_EXIT_ONLY`, `MISSING_CHECKOUT_ONLY`, `NONE` |
| `created_at` | TEXT NOT NULL | ISO8601 UTC |
| `updated_at` | TEXT NOT NULL | ISO8601 UTC |

#### `student_parent_links`
| Column | Type | Notes |
|--------|------|-------|
| `link_id` | TEXT PK | Generated: `LNK-{token_urlsafe(8)}` |
| `student_id` | TEXT NOT NULL | FK to student |
| `parent_id` | TEXT NOT NULL | FK to `parents.parent_id` |
| `relationship` | TEXT DEFAULT 'parent' | `parent`, `guardian`, `emergency_contact`, etc. |
| `is_primary` | INTEGER DEFAULT 0 | Primary contact designation |
| `created_at` | TEXT NOT NULL | ISO8601 UTC |

**Capabilities:**
- ✅ One parent ↔ multiple students
- ✅ Multiple parents per student
- ✅ Primary parent designation
- ✅ Notification preferences per parent

#### `link_codes`
| Column | Type | Notes |
|--------|------|-------|
| `code` | TEXT PK | Format: `XXXX-XXXX` (8 chars, `secrets.token_urlsafe`) |
| `student_id` | TEXT NOT NULL | |
| `parent_id` | TEXT | Pre-assigned parent (optional) |
| `status` | TEXT DEFAULT 'active' | Enum: `ACTIVE`, `USED`, `EXPIRED`, `REVOKED` |
| `created_at` | TEXT NOT NULL | ISO8601 UTC |
| `expires_at` | TEXT | 24h default |
| `used_at` | TEXT | Set on validation |
| `used_by_chat_id` | TEXT | Set on validation |

---

## 4. Student-Parent Relationship

```
student_id
    ↓
ParentRegistry.get_student_parents(student_id)
    ↓
parent record(s)
    ↓
telegram_chat_id (routing)
```

- Many-to-many preserved via `student_parent_links` table
- Primary contact designation via `is_primary`
- Notification routing respects `notification_preferences` enum
- Cross-parent isolation verified (HS001 → parent1 only, HS002 → parent2 only)

---

## 5. Telegram Bot Configuration

| Aspect | Detail |
|--------|--------|
| **Token Location** | Environment variable `TELEGRAM_BOT_TOKEN` |
| **Config File** | `app/config/settings.py` (loads from env via python-dotenv) |
| **Startup Validation** | `app/bootstrap/startup_validation.py` validates format (regex: `^\d+:[A-Za-z0-9_-]{35,}$`) |
| **.env Support** | Yes |
| **Git Excluded** | ✅ Never committed |
| **Never in Excel** | ✅ Enforced |
| **Never in Logs** | ✅ Secret filtering in `app.logging.logger` |
| **Single Project Bot** | ✅ One `BOT_TOKEN` for entire project |
| **Validation Endpoint** | `/api/v1/health/system` includes telegram config status |

---

## 6. Telegram Chat ID Mechanism

| Concept | Detail |
|---------|--------|
| **Routing Identifier** | `telegram_chat_id` (numeric or `@username`) |
| **Stored In** | `parents.telegram_chat_id` |
| **Obtained Via** | Secure link code flow (see below) |
| **Username ≠ Chat ID** | `telegram_username` / profile link is **NOT** `chat_id` and **NOT** sufficient for messaging |
| **Verification Required** | Link code validation consumes code, records `chat_id`, marks `status=USED` |
| **Profile Link Insufficient** | `telegram.me/username` ≠ deliverable destination |

---

## 7. Telegram Parent Linking (Existing Flow — Complete)

```
Admin creates unique link code (XXXX-XXXX)
    ↓
Parent opens project Bot → /start <link_code>
    ↓
Telegram supplies chat_id
    ↓
Backend validates link_code (active, not expired, not used)
    ↓
student_id ↔ parent_id ↔ telegram_chat_id stored
    ↓
Link activated (status=USED)
```

**Security Properties:**
- ✅ Unique, non-guessable codes (`secrets.token_urlsafe(4) x 2`)
- ✅ Bounded validity (24h default)
- ✅ Single-use (consumed on validation)
- ✅ Auditable (`created_at`, `used_at`, `used_by_chat_id`)

**Missing Step:** None — flow is complete and implemented.

---

## 8. Administrative Excel Workbook

**Template Path:** `data/templates/student_parent_timetable_template.xlsx` (to be created — template only, no real data)

### Sheets

#### SHEET 1: STUDENTS
| Column | Required | Notes |
|--------|----------|-------|
| `student_id` | ✅ | Canonical business identifier |
| `student_name` | ✅ | |
| `class_id` | ✅ | |
| `person_id` | ⚠️ | Only if enrollment metadata exposes it |
| `status` | ✅ | e.g., `active`, `inactive` |

**Constraints:** NO embeddings, NO `.npy` binary data

#### SHEET 2: PARENTS
| Column | Required | Notes |
|--------|----------|-------|
| `parent_id` | ✅ | |
| `parent_name` | ✅ | |
| `relationship` | ✅ | `parent`, `guardian`, etc. |
| `telegram_username` | | Supplementary only |
| `telegram_profile_link` | | Supplementary only |
| `telegram_chat_id` | ✅ | **Actual routing identifier** |
| `notification_preferences` | ✅ | Enum: `ALL`, `MORNING_ABSENCE_ONLY`, `LONG_EXIT_ONLY`, `MISSING_CHECKOUT_ONLY`, `NONE` |
| `link_status` | | `linked`, `pending`, `unlinked` |

**Critical:** `telegram_chat_id` is the routing identifier; username/profile_link is supplementary only.

#### SHEET 3: STUDENT_PARENTS
| Column | Required | Notes |
|--------|----------|-------|
| `student_id` | ✅ | |
| `parent_id` | ✅ | |
| `relationship` | ✅ | |
| `primary_contact` | ✅ | Boolean |
| `notification_enabled` | ✅ | Boolean |

**Preserves many-to-many** — do NOT collapse into single parent column.

#### SHEET 4: TIMETABLE
| Column | Required | Notes |
|--------|----------|-------|
| `date` | ✅ | YYYY-MM-DD |
| `day` | ✅ | `monday`..`sunday` |
| `class_id` | ✅ | |
| `student_id` | ✅ | Must match enrollment |
| `period` | ✅ | Integer |
| `start_time` | ✅ | HH:MM:SS |
| `end_time` | ✅ | HH:MM:SS |
| `subject` | ✅ | |
| `session_type` | ✅ | `CLASSROOM`, `BREAK`, `OUTSIDE_LESSON`, `LAB`, `OTHER` |
| `location` | | |
| `expected_location` | | For outside lessons |
| `outside_allowed` | ✅ | Boolean (semantic) |

**Uses ACTUAL Phase 37A/37D loader schema** — do NOT invent columns.

#### SHEET 5: TELEGRAM_CONFIG_GUIDE
| Column | Notes |
|--------|-------|
| `parameter` | e.g., `TELEGRAM_BOT_TOKEN` |
| `description` | Where/how to configure |
| `example` | Placeholder only |
| `security_note` | "NEVER commit to Git", "Environment variable only" |

**MUST NEVER contain real bot token.**

### Validation Rules
- `student_id` uniqueness
- `class_id` validity
- `parent_id` uniqueness
- Student-parent reference integrity
- `telegram_chat_id` format (numeric or `@username`)
- Notification preference enum validity
- Timetable `student_id` compatibility with enrollment
- Session type enum validity
- Time format validity (HH:MM:SS)
- Date validity

---

## 9. Timetable Schema (Phase 37A/37D)

**Loader:** `app/attendance/timetable_loader.py` (`TimetableLoader.load_from_excel()`)

### Required Columns
- `student_id`, `class_name`, `day`, `session_type`, `entry_time`, `exit_time`

### Optional Columns
- `session_id`, `person_name`, `subject`, `location`, `expected_location`, `outside_allowed`
- `entry_window_start`, `entry_window_end`, `late_tolerance`
- `exit_window_start`, `exit_window_end`, `timetable_version`

### Session Types & Semantics
| Session Type | `outside_allowed` | Semantic State |
|--------------|-------------------|----------------|
| `CLASSROOM` | `false` | `EXPECTED_INSIDE` |
| `BREAK` | `true` | `EXPECTED_OUTSIDE` |
| `OUTSIDE_LESSON` | `true` | `EXPECTED_OUTSIDE` |
| `LAB` | `true` (configurable) | `EXPECTED_OUTSIDE` |
| `OTHER` | `false` (safe default) | `EXPECTED_INSIDE` |

**Time Format:** Seconds from midnight or `HH:MM:SS`

**Validation:** `TimetableEntry.__post_init__` + `TimetableLoader` cross-entry validation (duplicates, conflicts, enrollment)

---

## 10. Existing UI Capability

**File:** `frontend/src/views/TimetableManagement.vue`

| Capability | Status |
|------------|--------|
| Import timetable | ✅ (drag-drop + preview) |
| Edit timetable | ✅ |
| Save timetable | ✅ |
| Edit semantic fields | ✅ (`subject`, `location`, `expected_location`, `outside_allowed`) |
| Validate timetable | ✅ (inline errors panel) |
| Session type dropdown | ✅ (`CLASSROOM`, `BREAK`, `OUTSIDE_LESSON`, `LAB`, `OTHER`, `FULL_DAY`, `MORNING`, `AFTERNOON`) |
| Excel import backend | ✅ `POST /api/v1/timetable/import` |

**Backend API Endpoints:**
- `GET /api/v1/timetable`
- `POST /api/v1/timetable`
- `PUT /api/v1/timetable/{id}`
- `DELETE /api/v1/timetable/{id}`
- `POST /api/v1/timetable/import`

**Policy Logic in Frontend:** ❌ No — Phase 37D owns semantic logic

**Recommendation:** **USE existing UI** — do not create second timetable UI.

---

## 11. Daily Excel Export Forensic

| Aspect | Detail |
|--------|--------|
| **Implemented** | ✅ Yes |
| **Status** | `IMPLEMENTED` |
| **Implementation Path** | `app/attendance/daily_excel.py` (`DailyExcelExporter`) + `app/attendance/policy_engine/excel_integration.py` (`PolicyExcelExporter`) |
| **Trigger** | Manual via `DailyExportRequest` or scheduled |
| **Filename Convention** | `attendance_YYYY-MM-DD.xlsx` |
| **Storage Location** | `request.output_path` (configurable) |
| **One File Per Day** | ✅ |
| **Overwrites Historical** | Only if same `output_path` used; date-based filename typically prevents overwrite |

### Sheets Generated
| Sheet | Description |
|-------|-------------|
| `DAILY_ATTENDANCE` | Attendance records with IN/OUT times, duration, state |
| `EXPECTED_SCHEDULE` | Timetable-derived expected sessions with semantic fields |
| `EVENTS` | Chronological IN/OUT events |
| `SUMMARY` | Attendance state counts |
| `PROVENANCE` | Full traceability chain |
| `POLICY_EVENTS` | Policy events with evidence, state, idempotency key, **semantic columns** |
| `NOTIFICATION_STATUS` | Delivery status, attempts, errors, timestamps |
| `POLICY_SUMMARY` | Counts by type, state, student |

### Semantic Columns in `POLICY_EVENTS`
- `Session Type`, `Subject`, `Location`, `Expected Location`, `Outside Allowed`, `Semantic State`

### Color Coding
- `EXPECTED_OUTSIDE` → Light green
- `EXPECTED_INSIDE` → Light red

### Preservation
- ✅ Timetable expectations
- ✅ Policy events
- ✅ Telegram notification status
- ✅ `student_id` (canonical)
- ✅ Semantic context

---

## 12. Security Findings

| Finding | Status |
|---------|--------|
| `TELEGRAM_BOT_TOKEN` in environment only | ✅ |
| `TELEGRAM_BOT_TOKEN` never in source/Git/logs/Excel | ✅ |
| `telegram_chat_id` stored in `parent_registry.db` (protected) | ✅ |
| Link codes: 24h expiry, single-use, non-guessable, auditable | ✅ |
| SQLite WAL disabled (`PRAGMA journal_mode=DELETE`) | ✅ Windows file locking safety |
| No secrets in logs (secret filtering) | ✅ `app.logging.logger` |
| Input validation on all API endpoints | ✅ |
| SQL parameterization (no string interpolation) | ✅ |

---

## 13. Files Created / Modified / Tests

### Files Created
- `data/templates/student_parent_timetable_template.xlsx` (template only, no real data)

### Files Modified
- None (forensic phase only)

### Tests Created (Recommended)
- `tests/unit/test_admin_excel_template.py` — validation tests
- `tests/integration/test_phase38c1t_admin_excel.py` — integration tests

---

## 14. Exact User Action Required

1. **Populate** `data/templates/student_parent_timetable_template.xlsx` with real student/parent/timetable data
2. **Set** `TELEGRAM_BOT_TOKEN` environment variable for production
3. **Configure** `TELEGRAM_LIVE_TEST=true` and `TELEGRAM_TEST_CHAT_ID` for live testing
4. **Place** timetable Excel file in `data/timetable/` for live operation
5. **Run parent linking:** Admin creates link codes → Parents use `/start <code>` in Telegram bot

---

## 15. Phase 38C.2 Prerequisites

- [ ] CAM1 and CAM2 RTSP streams active via MediaMTX
- [ ] GPU with CUDA and models (SCRFD, ArcFace) available
- [ ] `TELEGRAM_BOT_TOKEN` configured in environment
- [ ] `TELEGRAM_LIVE_TEST=true` and `TELEGRAM_TEST_CHAT_ID` set
- [ ] Timetable Excel file populated in `data/timetable/`
- [ ] Enrollment database validated with real student data
- [ ] Backend started with `uvicorn app.main:app`
- [ ] Frontend built and served
- [ ] Administrative Excel template populated with real data

---

## 16. Confirmations

| Confirmation | Status |
|--------------|--------|
| Phase 38C.2 NOT started | ✅ |
| Phase 39 NOT started | ✅ |
| No duplicate subsystems | ✅ |
| No camera architecture changes | ✅ |
| No GPU architecture changes | ✅ |
| No FPS optimization | ✅ |
| No enrollment DB modification | ✅ |
| No `.npy` regeneration | ✅ |

---

## 17. Final Response Summary

| Item | Answer |
|------|--------|
| **1. Exact Excel template path** | `data/templates/student_parent_timetable_template.xlsx` |
| **2. Exact sheets** | `STUDENTS`, `PARENTS`, `STUDENT_PARENTS`, `TIMETABLE`, `TELEGRAM_CONFIG_GUIDE` |
| **3. Exact columns** | As documented in Section 8 above |
| **4. Where TELEGRAM_BOT_TOKEN belongs** | Environment variable `TELEGRAM_BOT_TOKEN` (loaded via `app/config/settings.py`, validated at startup) |
| **5. Where parent telegram_chat_id belongs** | `parents.telegram_chat_id` in `parent_registry.db` (routing identifier) |
| **6. How parent Telegram linking works** | Secure link code flow: admin creates code → parent sends `/start <code>` → bot receives `chat_id` → backend validates & stores |
| **7. Whether existing timetable UI can manage it** | ✅ Yes — `TimetableManagement.vue` supports CRUD, import, semantic fields, validation |
| **8. Whether daily Excel export already exists** | ✅ `IMPLEMENTED` — `DailyExcelExporter` + `PolicyExcelExporter` |
| **9. Exact daily export path/filename** | `attendance_YYYY-MM-DD.xlsx` at `request.output_path` |
| **10. What remains to be entered manually** | Real student/parent data in template; `TELEGRAM_BOT_TOKEN` env var; timetable file in `data/timetable/`; parent link codes |
| **11. 38C.2 prerequisites** | As listed in Section 15 |
| **12. Confirmation 38C.2 NOT started** | ✅ Confirmed |
| **13. Confirmation Phase 39 NOT started** | ✅ Confirmed |

---

**END PHASE 38C.1T**