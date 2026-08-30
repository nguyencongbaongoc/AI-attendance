# PHASE 39D — ADMINISTRATIVE DATA + TIMETABLE BOOTSTRAP REPORT

**Timestamp:** 2026-08-28T15:11:03Z
**Status:** PASS

## Template File

- **File:** `data/templates/student_parent_timetable_template.xlsx`
- **Sheets:** STUDENTS, PARENTS, STUDENT_PARENTS, TIMETABLE, TELEGRAM_CONFIG_GUIDE

## STUDENTS Sheet

| Column | Description |
|--------|-------------|
| student_id | Unique student identifier (must match enrollment person_id) |
| student_name | Student full name |
| class_name | Class assignment |
| enrollment_status | active/inactive |
| notes | Additional notes |

**Rows:** 4 (3 students + header)
**Student IDs:** HS001, HS002, HS003

## PARENTS Sheet

| Column | Description |
|--------|-------------|
| parent_id | Unique parent identifier |
| parent_name | Parent full name |
| relationship | parent/guardian |
| telegram_username | Telegram username (reference only) |
| telegram_profile_link | Telegram profile link (reference only) |
| telegram_chat_id | **ONLY routing identifier** (populated after /start flow) |
| telegram_enabled | true/false |
| notification_preferences | all/morning_absence_only/etc |
| notes | Additional notes |

**Rows:** 3 (3 parents + header)
**Parent IDs:** PAR-ABC12345, PAR-BCD23456, PAR-CDE34567

## STUDENT_PARENTS Sheet

| Column | Description |
|--------|-------------|
| link_id | Unique link identifier |
| student_id | References STUDENTS.student_id |
| parent_id | References PARENTS.parent_id |
| relationship | parent/guardian |
| is_primary | true/false |
| notes | Additional notes |

**Rows:** 4 (4 links + header)
**Links:**
- LNK-ABC12345: HS001 <-> PAR-ABC12345 (primary)
- LNK-BCD23456: HS001 <-> PAR-BCD23456 (secondary)
- LNK-CDE34567: HS002 <-> PAR-BCD23456 (primary)
- LNK-DEF45678: HS003 <-> PAR-CDE34567 (primary)

## TIMETABLE Sheet

### Required Fields
- student_id
- class_name
- day
- session_type
- entry_time
- exit_time

### Optional Semantic Fields
- session_id
- person_name
- subject
- location
- expected_location
- outside_allowed
- entry_window_start
- entry_window_end
- late_tolerance
- exit_window_start
- exit_window_end
- timetable_version

**Rows:** 4 (4 sessions + header)
**Session Types:** classroom, lab, outside_lesson

### Semantic Behavior Mapping

| Session Type | Expected Location |
|--------------|-------------------|
| CLASSROOM | EXPECTED_INSIDE |
| BREAK | EXPECTED_OUTSIDE |
| OUTSIDE_LESSON | EXPECTED_OUTSIDE |
| LAB | CONFIGURABLE (via outside_allowed) |
| OTHER | EXPECTED_INSIDE (safe default) |

## Timetable Loader

- **Method:** `TimetableLoader.load_from_excel()`
- **Verified:** YES - workbook can be validated/imported using production contracts

## Timetable Management UI

- **Component:** `TimetableManagement.vue`
- **Used:** YES
- **No Duplicate UI:** YES - existing component is used, no second timetable UI created

## Verification Results

- [x] Template file exists and loads correctly
- [x] All 5 required sheets present
- [x] STUDENTS sheet has correct columns and data
- [x] PARENTS sheet has correct columns including telegram_chat_id routing
- [x] STUDENT_PARENTS sheet links students to parents correctly
- [x] TIMETABLE sheet has all required and optional semantic fields
- [x] Semantic behavior mapping verified (CLASSROOM->EXPECTED_INSIDE, etc.)
- [x] TimetableLoader.load_from_excel() works with production contracts
- [x] TimetableManagement.vue is the canonical UI (no duplicate)

## Conclusion

Administrative data and timetable bootstrap verified. Template is production-ready with all required sheets, semantic fields, and proper routing configuration.