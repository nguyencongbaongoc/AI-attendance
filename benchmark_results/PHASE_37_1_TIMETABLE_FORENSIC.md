# Phase 37.1 Timetable Forensic Audit Report

**Timestamp:** 2026-08-27T05:19:02Z

**Verdict:** TIMETABLE_EXISTS_BUT_INCOMPLETE

---

## 1. Executive Summary

| Aspect | Finding |
|--------|---------|
| Timetable subsystem exists | YES |
| Implementation phase | Phase 26 (not Phase 25) |
| Contract complete | YES |
| Runtime integration | YES (via AttendanceDecisionContext) |
| External data source | NO |
| Production ready | NO |

**Missing pieces:**
- No external timetable data file (Excel/CSV/JSON) found
- No timetable loader/parser implementation
- No holiday/exception/leave calendar support
- No UI for timetable management
- No integration with student registry for class/session assignment

---

## 2. Exact Timetable Implementation Found

**Location:** pp/attendance/timetable.py (Phase 26, not Phase 25)

**Components:**
- TimetableEntry - immutable dataclass with full validation
- Timetable - collection with query methods (get_entry, get_entries_for_session, get_entries_for_person)
- SessionDay enum - 7 days (monday-sunday)
- SessionType enum - 4 types (morning, afternoon, full_day, evening)
- AttendanceState enum - 6 states (UNKNOWN, EXPECTED, PRESENT, LATE, LEFT, ABSENT)
- DecisionReason enum - 12 reasons
- generate_timetable_id() - deterministic ID generation
- alidate_timetable_entry() - validation function

**Data format:** In-memory Python objects, JSON serializable

**Schema (TimetableEntry):**
- Identity: entry_id, person_id, session_id
- Session: session_type, day, class_name, person_name
- Time boundaries (seconds from midnight): entry_time, exit_time, entry_window_start, entry_window_end, late_tolerance, exit_window_start, exit_window_end
- Versioning: 	imetable_version, created_at, updated_at

---

## 3. Phase 25 Evidence

**Phase 25 was:** Attendance Persistence (SQLite storage for AttendanceRecord)

**Phase 25 did NOT implement:** Timetable/schedule subsystem

**Phase 25 files:**
- pp/attendance/contract.py - AttendanceRecord contract
- pp/attendance/storage.py - SQLite storage
- pp/attendance/repository.py - High-level repository
- pp/attendance/query.py - Query utilities
- scripts/phase25_attendance_persistence.py - Acceptance script

**Phase 25 verdict:** PASS (from enchmark_results/PHASE_25_ATTENDANCE_PERSISTENCE.json)

**Known limitations from Phase 25:**
- Identity enrichment from GlobalObservation not yet implemented (returns UNKNOWN)
- No automatic retention/deletion policy implemented
- Single-node SQLite backend (no distributed locking)
- Query builder fluent API not fully tested in integration

---

## 4. Current Runtime Path

`
student/identity
  -> recognition
  -> person_id (e.g., HS001)
  -> student_id (same as person_id)
  -> raw IN/OUT events (Phase 23)
  -> ResolvedTransition (Phase 24)
  -> AttendanceEngine (Phase 26)
`

**Timetable entry point:** AttendanceDecisionContext.timetable (required parameter)

**Person ID resolution:** Requires person_id_override in AttendanceDecisionContext (no automatic lookup from GlobalObservation)

**Day resolution:** Requires day_override in AttendanceDecisionContext (no automatic derivation from timestamp)

**Integration status:** Contract exists and is consumed, but requires manual overrides for person_id and day

---

## 5. Data/Schema Analysis

**TimetableEntry fields:**
- entry_id, person_id, session_id, session_type, day, class_name, person_name
- entry_time, exit_time, entry_window_start, entry_window_end
- late_tolerance, exit_window_start, exit_window_end
- 	imetable_version, created_at, updated_at

**Time representation:** Seconds from midnight (int)
**Day representation:** SessionDay enum (monday-sunday)
**Session representation:** SessionType enum (morning, afternoon, full_day, evening)
**Validation:** Comprehensive __post_init__ validation
**Serialization:** 	o_dict/from_dict, 	o_json/from_json

---

## 6. Student ID Compatibility

**Canonical identity chain:**
`
Excel student_id (e.g., HS001)
  -> person_id in enrollment directory structure
  -> embeddings.npy.metadata.json person_ids: [HS001, HS002, HS003]
  -> TimetableEntry.person_id (same string)
`

**Technical IDs kept separate:**
- 	rack_id (local camera track)
- person_id (embedding index / enrollment identity)
- embedding_index (array index in embeddings.npy)
- global_observation_id (cross-camera fusion)
- event_id (attendance decision)
- ideo_id (replay source)

**Contract preserved:** YES - existing person_id strings used directly

---

## 7. Enrollment/.npy Compatibility

**Enrollment DB structure:** data/enrollment_db/embeddings.npy + embeddings.npy.metadata.json

**Person IDs in metadata:** HS001, HS002, HS003 (3 persons, 9 embeddings)

**Timetable person_id match:** YES - uses same string identifiers

**No second identity database:** CONFIRMED - timetable references existing enrollment person_ids

---

## 8. Attendance Engine Compatibility

| Feature | Status | Details |
|---------|--------|---------|
| Consumes timetable | YES | Via AttendanceDecisionContext.timetable |
| Expected arrival logic | IMPLEMENTED | entry_window_start <= timestamp <= entry_window_end -> PRESENT |
| Expected departure logic | IMPLEMENTED | exit_window_start <= timestamp <= exit_window_end -> LEFT |
| Absence logic | IMPLEMENTED | Outside windows -> ABSENT |
| IN/OUT state | IMPLEMENTED | From ResolvedTransition.direction (in/out) |
| Repeated IN/OUT handling | UPSTREAM | Phase 24 resolver suppresses repeated events |
| Unknown identity handling | IMPLEMENTED | IdentityHandlingPolicy enum (UNRESOLVED, UNKNOWN_PERSON, PENDING_REVIEW) |
| Camera health handling | UPSTREAM | Not in attendance engine |
| 07:30/17:30/30-min policies | NOT IMPLEMENTED | Correctly deferred to Phase 37.2+ |

---

## 9. Existing Tests and Results

| Test Suite | Tests | Result |
|------------|-------|--------|
| 	est_attendance_timetable.py | 19 | PASSED |
| 	est_attendance_engine.py | 12 | PASSED |
| 	est_attendance_policy.py | 17 | PASSED |
| 	est_attendance_integration.py | 5 | PASSED |
| scripts/phase26_acceptance.py | 74 criteria | ALL PASSED |

**All tests pass:** YES

---

## 10. Defects

1. **datetime.utcnow() deprecation warnings** in 	imetable.py, policy.py, engine.py
2. **AttendanceEngine._determine_person_id()** raises IdentityResolutionError without person_id_override
3. **AttendanceEngine._determine_day()** raises IdentityResolutionError without day_override
4. **No automatic person_id lookup** from GlobalObservation.identity_evidence_ref
5. **No automatic day derivation** from event timestamp

---

## 11. Missing Components

1. External timetable data source (Excel/CSV/JSON file)
2. Timetable loader/parser (from file to Timetable object)
3. Holiday/exception calendar support
4. Leave/exemption management
5. Student-to-class/session assignment mapping
6. UI for timetable management
7. Automatic person_id resolution from GlobalObservation
8. Automatic day derivation from timestamp

---

## 12. Architectural Risks

1. Timetable contract exists but no data source - runtime requires manual construction
2. person_id and day must be provided as overrides - not derived from upstream
3. No validation that timetable person_ids match enrolled students
4. No versioning/migration strategy for timetable changes
5. SessionFinalizationPolicy TIME_BASED and MANUAL not fully exercised in tests

---

## 13. Compatibility Matrix

| Existing Component | Current Implementation | Phase 37 Requirement | Compatible | Action |
|---|---|---|---|---|
| Excel student registry | Inferred from enrollment dirs (HS001, HS002, HS003) | Canonical business identity | YES | Use existing person_id |
| Enrollment DB | data/enrollment_db/ with 3 persons, 9 embeddings | Single identity source | YES | Timetable person_id must match |
| embeddings.npy | (9, 512) float32 L2-normalized | Face recognition backend | YES | No change needed |
| metadata.json | Full provenance per sample | Audit trail | YES | No change needed |
| person_id | String identifier (HS001, HS002, HS003) | Timetable person reference | YES | Direct mapping |
| AttendanceRecord (Phase 25) | SQLite persistence with full provenance | Persist attendance decisions | YES | AttendanceDecision compatible |
| Timetable (Phase 26) | In-memory contract, JSON serializable | Schedule for decisions | YES | Reuse contract; add loader |
| Raw IN/OUT (Phase 23/24) | ResolvedTransition with direction, timestamp | Event input to engine | YES | No change needed |
| Provenance chain | Full chain preserved | Forensic reproducibility | YES | Timetable fields in AttendanceDecision |
| Event bus | Direct function calls | Async notification | YES | Deferred to Phase 37.2+ |
| UI | Phase 28 Live UI (frontend/) | Timetable management UI | YES | Extend existing UI |
| Notification layer | Not implemented | 07:30/17:30/30-min policies | YES | Deferred to Phase 37.2+ |

---

## 14. Exact Recommendation for Phase 37.2

**Decision:** TIMETABLE_EXISTS_BUT_INCOMPLETE

**Action:** Implement timetable data layer (loader, file format, holiday calendar) on top of existing Phase 26 contract

**Do NOT:**
- Create parallel timetable system
- Modify Phase 26 contract

**Required implementation:**
1. Define timetable file format (Excel/CSV/JSON) with columns: student_id, class_name, day, period, entry_time, exit_time, entry_window, late_tolerance, exit_window
2. Implement TimetableLoader.parse(file_path) -> Timetable
3. Add holiday/exception calendar support (separate file or embedded)
4. Implement automatic person_id resolution from GlobalObservation -> enrollment metadata
5. Implement automatic day derivation from event timestamp (timezone-aware)
6. Add validation: timetable person_ids must exist in enrollment database
7. Add timetable versioning and change detection
8. Extend Phase 30 Daily Excel to include timetable-derived expected times

**Files to create:**
- pp/attendance/timetable_loader.py
- pp/attendance/calendar.py (holidays/exceptions)
- data/timetable/ (directory for timetable files)
- 	ests/unit/test_timetable_loader.py
- 	ests/integration/test_timetable_integration.py

**Files to modify:**
- pp/attendance/engine.py (add automatic person_id/day resolution)
- pp/attendance/daily_excel.py (include timetable expected times)

---

## 15. Files Inspected

- pp/attendance/timetable.py
- pp/attendance/engine.py
- pp/attendance/policy.py
- pp/attendance/contract.py
- pp/attendance/repository.py
- pp/attendance/query.py
- pp/attendance/daily_excel.py
- pp/attendance/__init__.py
- pp/vision/enrollment.py
- pp/vision/enrollment_contract.py
- pp/in_out/resolver_contract.py
- data/enrollment_db/embeddings.npy.metadata.json
- scripts/phase25_attendance_persistence.py
- scripts/phase26_acceptance.py
- scripts/phase30a_enrollment.py
- 	ests/unit/test_attendance_timetable.py
- 	ests/unit/test_attendance_engine.py
- 	ests/unit/test_attendance_policy.py
- 	ests/unit/test_attendance/
- 	ests/integration/test_attendance_integration.py
- enchmark_results/PHASE_25_ATTENDANCE_PERSISTENCE.json
- enchmark_results/PHASE_25_ATTENDANCE_PERSISTENCE.md
- enchmark_results/PHASE_26_ATTENDANCE_ENGINE.json
- enchmark_results/PHASE_26_ATTENDANCE_ENGINE.md
- enchmark_results/PHASE_30_DAILY_EXCEL.md

---

## 16. Files Modified

**NONE** - This is a forensic audit only. No production code was modified.
