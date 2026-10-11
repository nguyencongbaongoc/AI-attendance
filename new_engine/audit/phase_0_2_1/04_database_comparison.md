# Phase 0.2.1 — Database Comparison: Active vs Quarantined

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED / RUNTIME VERIFIED / DOCUMENTED ONLY

---

## 1. Executive Summary

Phase 0.2 claimed 4 databases quarantined in `data_duplicate_dbs/` and then "restored to `data/`". **The quarantine directory is empty** — no databases remain there. The 4 databases exist only in `data/` (project root), with byte-identical duplicates in `app/data/`. This comparison evaluates active vs intended quarantine state.

---

## 2. Phase 0.2 Claim vs Reality

| Database | Phase 0.2 Claim | Actual State |
|----------|-----------------|--------------|
| `attendance.db` | Quarantined to `data_duplicate_dbs/`, then restored to `data/` | **NOT in quarantine**; exists in `data/` (65,536 bytes) AND `app/data/` (86,016 bytes) — different files |
| `exit_sessions.db` | Quarantined to `data_duplicate_dbs/`, then restored to `data/` | **NOT in quarantine**; byte-identical pair in `data/` and `app/data/` |
| `parent_registry.db` | Quarantined to `data_duplicate_dbs/`, then restored to `data/` | **NOT in quarantine**; byte-identical pair in `data/` and `app/data/` |
| `notification_queue.db` | Quarantined to `data_duplicate_dbs/`, then restored to `data/` | **NOT in quarantine**; byte-identical pair in `data/` and `app/data/` |

**Quarantine directory `new_engine/audit/phase_0_2/quarantine/data_duplicate_dbs/` is EMPTY** (0 files, 0 bytes).

**Evidence:** RUNTIME VERIFIED — filesystem inspection

---

## 3. Detailed Comparison: `attendance.db`

### 3.1 `app/data/attendance.db` (AUTHORITATIVE)

| Property | Value |
|----------|-------|
| Path | `app/data/attendance.db` |
| Size | 86,016 bytes |
| SHA256 | f711c4392426c4c1f6ae278fed12b5121dc4cccf29a18a4a899485ec4100f5eb |
| Records | 108 attendance_records |
| Data Provenance | Mixed: test records (`rec_in_1`, `rec_out_1`, `rec_e2e_in_1`) + production records (`ATT-*` with full provenance chain) |
| Timestamp Range | 5.24 → 1,787,502,600.0 (2026-09-22) |
| WAL/SHM | Active (32 KB each) |
| Schema | Full Phase 25 (23 cols, 10 indexes, 7 constraints) |

### 3.2 `data/attendance.db` (ACTIVE SECONDARY)

| Property | Value |
|----------|-------|
| Path | `data/attendance.db` |
| Size | 65,536 bytes |
| SHA256 | 30fb1f177f284b3fd573d2baa46538da2993b0bf5b6c6cb48717116a429d7080 |
| Records | 18 attendance_records |
| Data Provenance | Benchmark/test only (`ATT-*` with `CAM1`, frame indices 40-182, timestamps 6-100s) |
| Timestamp Range | 6.91 → 100.28 |
| WAL/SHM | Active (32 KB each) |
| Schema | Identical Phase 25 |

### 3.3 Comparison Result

| Aspect | Same? | Details |
|--------|-------|---------|
| File identity (SHA256) | ❌ NO | Different hashes = different files |
| Schema | ✅ YES | Identical `attendance_records` table |
| Record count | ❌ NO | 108 vs 18 |
| Data overlap | ❌ NO | Different provenance; no shared `attendance_record_id` values |
| WAL/SHM state | ✅ YES | Both active |
| Logical identity | ❌ NO | Different data populations |

**Conclusion:** Two **distinct** databases with same schema but different data. NOT the same file copied.

---

## 4. Detailed Comparison: Supporting Databases (Byte-Identical Pairs)

### 4.1 `exit_sessions.db`

| Path | SHA256 | Size | Records | Identical? |
|------|--------|------|---------|------------|
| `app/data/exit_sessions.db` | eeefde20e6d9d3314c9a72a32a8b4b38101958d042e1f12ead3ac947741a724a | 24,576 | 0 | ✅ YES |
| `data/exit_sessions.db` | eeefde20e6d9d3314c9a72a32a8b4b38101958d042e1f12ead3ac947741a724a | 24,576 | 0 | ✅ YES |

### 4.2 `parent_registry.db`

| Path | SHA256 | Size | Records | Identical? |
|------|--------|------|---------|------------|
| `app/data/parent_registry.db` | 0aa11dab160117070214ce16125e476d98bfbfd8ff48cb4a06b7f81a79b96ec8 | 45,056 | 0 (all 3 tables) | ✅ YES |
| `data/parent_registry.db` | 0aa11dab160117070214ce16125e476d98bfbfd8ff48cb4a06b7f81a79b96ec8 | 45,056 | 0 (all 3 tables) | ✅ YES |

### 4.3 `notification_queue.db`

| Path | SHA256 | Size | Records | Identical? |
|------|--------|------|---------|------------|
| `app/data/notification_queue.db` | 670211d208999b820855c2244da5d8bcebdf4a731bcfc22bdd08f019eea49894 | 32,768 | 0 | ✅ YES |
| `data/notification_queue.db` | 670211d208999b820855c2244da5d8bcebdf4a731bcfc22bdd08f019eea49894 | 32,768 | 0 | ✅ YES |

---

## 5. PipelineEngine Database Comparison

### 5.1 `data/attendance_events.db` vs Quarantine

| Property | Value |
|----------|-------|
| Path | `data/attendance_events.db` |
| Size | 20,480 bytes |
| SHA256 | 0fbdab692515cec5a724e7e6eb275d679b51534b389943830522c9b58f2d1c6a |
| Schema | `attendance_events` (PipelineEngine CrossingEvent schema) |
| Records | 0 |
| In Quarantine? | ❌ NO — never quarantined per Phase 0.2 |

**Note:** `pipeline_engine/config/pipeline.yaml` also references `data/attendance_daily.db` (line 282) — **does not exist** on filesystem.

---

## 6. Quarantine Manifest Verification

### 6.1 Phase 0.2 Cleanup Log Claims (§2.3)

> "These 4 databases were RESTORED to `data/` after quarantine to support Legacy Backend operation"

**Verification:** 
- Quarantine directory empty ✅ (confirmed)
- 4 databases exist in `data/` ✅ (confirmed)
- Byte-identical duplicates exist in `app/data/` ✅ (confirmed)

**But:** The "restored" databases in `data/` are **not** the same as the `app/data/` versions for `attendance.db` — they are different files with different data. For the other 3, they are byte-identical.

### 6.2 Missing Quarantine Evidence

No quarantine manifest/log file found with:
- Original paths of quarantined databases
- SHA256 hashes at quarantine time
- Restoration timestamps and verification hashes

**Evidence:** NOT TESTED — no such file exists in quarantine directory

---

## 7. Summary Comparison Matrix

| Database Pair | Same File? | Same Schema? | Same Data? | Both Active? | Action Needed |
|---------------|------------|--------------|------------|--------------|---------------|
| `app/data/attendance.db` ↔ `data/attendance.db` | ❌ NO | ✅ YES | ❌ NO | ✅ YES (both WAL) | **MERGE/CHOICE REQUIRED** |
| `app/data/exit_sessions.db` ↔ `data/exit_sessions.db` | ✅ YES (byte-identical) | ✅ YES | ✅ YES (both empty) | ❌ NO (no WAL) | Remove `data/` duplicate |
| `app/data/parent_registry.db` ↔ `data/parent_registry.db` | ✅ YES (byte-identical) | ✅ YES | ✅ YES (both empty) | ❌ NO (no WAL) | Remove `data/` duplicate |
| `app/data/notification_queue.db` ↔ `data/notification_queue.db` | ✅ YES (byte-identical) | ✅ YES | ✅ YES (both empty) | ❌ NO (no WAL) | Remove `data/` duplicate |
| `data/attendance_events.db` ↔ (quarantine) | N/A | N/A | N/A | ⚠️ Exists only in `data/` | PipelineEngine-owned; keep for now |

---

## 8. Critical Findings

1. **`attendance.db` is NOT a duplicate pair** — two different databases with different data, both actively written (WAL present). This is a **data integrity risk**.

2. **Supporting databases ARE true duplicates** — byte-identical pairs from CWD-dependent path resolution. Safe to remove `data/` copies.

3. **Quarantine is empty for databases** — Phase 0.2 "restored" them but left the `app/data/` copies, creating the duplicate pairs.

4. **No quarantine audit trail** — Cannot verify what was originally quarantined vs what exists now.

---

## 9. Recommendations

| Database | Recommendation | Priority |
|----------|----------------|----------|
| `app/data/attendance.db` | **KEEP** as authoritative (has production data) | HIGH |
| `data/attendance.db` | **MERGE INTO** `app/data/` then remove, OR designate as read-only archive | HIGH |
| `data/exit_sessions.db` | **REMOVE** (byte-identical to `app/data/`) | MEDIUM |
| `data/parent_registry.db` | **REMOVE** (byte-identical to `app/data/`) | MEDIUM |
| `data/notification_queue.db` | **REMOVE** (byte-identical to `app/data/`) | MEDIUM |
| `data/attendance_events.db` | **KEEP** for PipelineEngine local crossing events; Phase 1: migrate to API-only | MEDIUM |
| `data/attendance_daily.db` | **DO NOT CREATE** — PipelineEngine should use Legacy Backend API | LOW |

---

**End of Database Comparison**