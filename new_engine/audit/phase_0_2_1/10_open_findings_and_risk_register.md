# Phase 0.2.1 — Open Findings and Risk Register

**Date:** 2026-10-04  
**Classification:** SOURCE VERIFIED / RUNTIME VERIFIED / DOCUMENTED ONLY / UNKNOWN / NOT TESTED

---

## 1. Critical Findings (Block Phase 1)

| # | Finding | Evidence | Risk | Blocks Phase 1? | Required Action |
|---|---------|----------|------|-----------------|-----------------|
| CF-01 | **Dual active `attendance.db` instances** with different data | `01_sqlite_inventory_and_integrity.md` §4; `03_attendance_authority_verdict.md` §5 | Data divergence; attendance records written to one DB invisible to other | **YES** | Fix CWD-dependent path; choose single authoritative path (`app/data/attendance.db`); merge or archive `data/attendance.db` |
| CF-02 | **CWD-dependent database path resolution** | `02_database_path_and_owner_trace.md` §6; `app/config/settings.py` lines 43-59 | Root cause of CF-01; unpredictable which DB is written | **YES** | Make `Settings.paths.data_dir` absolute (from `__file__` or env); change `StorageConfig.database_path` to `Path` with validator |
| CF-03 | **Missing Legacy Backend API endpoints for AI Worker** | `16_blockers_and_recovery_plan.md` §2.1; `03_attendance_authority_verdict.md` §2 | PipelineEngine cannot deliver events to Legacy Backend | **YES** | Implement 4 endpoints in Week 1: `POST /api/v1/attendance/events`, `POST /api/v1/health/ai-worker`, `POST /api/v1/ai/control/*`, `POST /api/v1/enrollment/reload` |
| CF-04 | **Unsafe recovery procedures documented** | `07_runtime_recovery_safety.md` §2 | `taskkill /F /IM python.exe` kills all Python; `del *.db-wal` corrupts databases | **YES** | Replace with safe procedures (graceful shutdown, PID identification, WAL preservation, integrity checks) |
| CF-05 | **Quarantine rollback capability not demonstrated** | `06_rollback_evidence_audit.md` §8 | Only 4 trivial samples tested; no hash manifest; critical assets untested | **YES** | Create quarantine manifest with SHA256; test restoration of critical assets (worktree, models, forensic logs) |

---

## 2. High-Priority Findings

| # | Finding | Evidence | Risk | Blocks Phase 1? | Required Action |
|---|---------|----------|------|-----------------|-----------------|
| HP-01 | **`generated_live/` contains Agent Manager worktree mirror** (vendor SDKs, venv, source) | `05_quarantine_integrity_audit.md` §3.6 | Misclassified as "generated live data"; loss = vendor SDK re-download, venv rebuild, worktree state loss | NO (but critical for disaster recovery) | Reclassify; exclude from cleanup; verify `models/arcface/` has `glintr100.onnx` independently |
| HP-02 | **`root_model_duplicates/glintr100.onnx` may be ONLY ArcFace copy** | `05_quarantine_integrity_audit.md` §3.2; enrollment metadata SHA256 match | If `models/arcface/glintr100.onnx` missing, enrollment broken | NO (verify active copy exists) | Verify `models/arcface/glintr100.onnx` exists and matches SHA256 |
| HP-03 | **PipelineEngine `attendance_events.db` not quarantined** | `04_database_comparison.md` §5.1 | Phase 0.2 claim "PipelineEngine DBs quarantined" is false | NO (Architecture A: PipelineEngine keeps local CrossingEvent store) | Document as intentional; Phase 1: migrate to API-only or read-only cache |
| HP-04 | **No quarantine manifest with hashes** | `05_quarantine_integrity_audit.md` §4; `06_rollback_evidence_audit.md` §4 | Cannot verify quarantine integrity independently | NO (but needed for disaster recovery) | Generate manifest JSON with path, original_path, sha256, size, timestamp, category |
| HP-05 | **Phase 0.2 artifact count discrepancy** | `08_phase_0_2_artifact_manifest.md` §3-5 | Claimed 17 artifacts; Artifact 06 embedded, Artifact 04 references missing log | NO | Accept corrected manifest; update final verdict if needed |
| HP-06 | **Enrollment NPY not auto-loaded by backend service** | `16_blockers_and_recovery_plan.md` §2.3; `03_attendance_authority_verdict.md` §9 | Backend enrollment API reports 0 enrolled despite valid NPY | YES (part of CF-03) | Implement `POST /api/v1/enrollment/reload` + startup load + file watcher |

---

## 3. Medium-Priority Findings

| # | Finding | Evidence | Risk | Blocks Phase 1? |
|---|---------|----------|------|-----------------|
| MP-01 | **Camera 2 FPS variance (47 vs 30 expected)** | `17_phase_0_2_final_verdict.md` §4; `16_blockers_and_recovery_plan.md` §2.5 | Timestamp sync issues; may indicate stream problems | NO (investigate in integration) |
| MP-02 | **`data/attendance_daily.db` referenced in config but missing** | `pipeline_engine/config/pipeline.yaml` line 282 | PipelineEngine expects it; may error on startup | NO (Phase 1: remove or implement) |
| MP-03 | **Supporting DB duplicates (exit_sessions, parent_registry, notification_queue)** | `01_sqlite_inventory_and_integrity.md` §3.4-3.6; `04_database_comparison.md` §4 | Byte-identical pairs from CWD bug; waste space, confusion | NO (remove `data/` copies after CF-02 fix) |
| MP-04 | **Phase 0.2 claim "1,600 files, 6.5 GB" vs actual "5,343 files, 7.53 GB"** | `08_phase_0_2_artifact_manifest.md` §5.1 | Undercounted due to nested worktree in `generated_live/` | NO (accept corrected numbers) |
| MP-05 | **`video_pipeline_v2/` source code in quarantine** | `05_quarantine_integrity_audit.md` §3.7 | Superseded but may contain unique logic not migrated | NO (review before permanent archive) |
| MP-06 | **No `attendance_daily.db` exists but config references it** | `pipeline_engine/config/pipeline.yaml` line 282 | PipelineEngine may fail if code expects it | NO (remove config reference or create) |

---

## 4. Low-Priority Findings

| # | Finding | Evidence | Risk |
|---|---------|----------|------|
| LP-01 | **`UI/index.html` untracked, purpose unknown** | `04_cleanup_execution_log.md` §5 | May be dead code |
| LP-02 | **`test_data/` contains mix of fixtures and fix scripts** | `04_cleanup_execution_log.md` §5 | Should separate |
| LP-03 | **`isolated_src/`, `isolated_tests/` not found in filesystem** | `04_cleanup_execution_log.md` §5 | May be in quarantine or deleted |
| LP-04 | **GTX 1660 Ti: No NVDEC hardware decode** | `17_phase_0_2_final_verdict.md` §4 | Known limitation; software decode only |
| LP-05 | **Empty directories in quarantine contain 8 files** | `05_quarantine_integrity_audit.md` §2 | Misclassified |

---

## 5. Unknown / Not Tested

| # | Finding | Why Unknown | Investigation Needed |
|---|---------|-------------|---------------------|
| UNK-01 | **Which `attendance.db` does RUNNING backend write to?** | Both have active WAL; depends on CWD at startup | Check running process CWD; or add logging |
| UNK-02 | **Does PipelineEngine ever write to `data/attendance.db`?** | No code path found, but not 100% proven | Full code audit of PipelineEngine imports |
| UNK-03 | **Are there other hidden database files?** | Only searched `*.db`, `*.sqlite*`, `*.db-wal`, `*.db-shm` | Search for other extensions |
| UNK-04 | **Quarantine `generated_live/` worktree state** | Not inspected deeply | Check `.kilo/agent-manager.json` for worktree metadata |
| UNK-05 | **Enrollment NPY reload mechanism design** | Not implemented | Phase 1 design decision |

---

## 6. Risk Register (Updated from Phase 0.2)

| Risk | Likelihood | Impact | Phase 0.2 Mitigation | Phase 0.2.1 Assessment | Phase 1 Mitigation |
|------|------------|--------|----------------------|------------------------|-------------------|
| Camera hardware unavailable | HIGH | HIGH | Document as BLOCKED | **UNCHANGED** | FFmpeg loop test mode |
| Enrollment data corrupted | LOW | HIGH | Backup NPY + metadata, verify SHA256 | **UNCHANGED** | Automated backup + integrity check |
| GPU OOM during inference | MEDIUM | HIGH | VRAM budget 4GB, headroom 2GB | **UNCHANGED** | Explicit OOM handling; no silent CPU fallback |
| MediaMTX port conflict | LOW | MEDIUM | Dynamic port discovery, kill existing | **UNCHANGED** | PID-based cleanup |
| Database lock contention | MEDIUM | MEDIUM | WAL mode, connection pooling | **WORSENED** — dual DB | Single DB + connection pooling |
| Timestamp sync drift | MEDIUM | HIGH | Architecture A design includes sync protocol | **OPEN** — `stream_epoch`, PTS contract undefined | Formal contract in Phase 1 Week 1 |
| NPY reload not implemented | HIGH | MEDIUM | Phase 1 endpoint implementation | **CONFIRMED BLOCKER** | Week 1 implementation |
| Quarantine loss (no manifest) | MEDIUM | HIGH | None | **IDENTIFIED** | Generate manifest + test restoration |
| Recovery procedure data loss | HIGH | CRITICAL | Documented (but unsafe) | **CONFIRMED UNSAFE** | Replace with safe procedures |

---

## 7. Decision Required Before Phase 1

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Single authoritative `attendance.db` path | A) `app/data/attendance.db` (has production data)<br>B) `data/attendance.db` (configured default)<br>C) New path `app/data/attendance.db` with absolute config | **A** — contains real attendance records |
| `data/attendance.db` disposal | A) Merge into `app/data/` then delete<br>B) Keep as read-only archive<br>C) Rename to `data/attendance_legacy.db` | **A** — merge any unique records (none found), then remove |
| PipelineEngine local `attendance_events.db` | A) Keep as local CrossingEvent cache<br>B) Remove entirely, use API only<br>C) Make read-only, populate from API | **A** for Phase 1 (local cache); **B** for Phase 2+ |
| `generated_live/` worktree handling | A) Keep in quarantine (exclude from cleanup)<br>B) Restore to `.kilo/worktrees/`<br>C) Archive externally | **A** — it's a valid Agent Manager worktree |
| Recovery procedure replacement | A) Patch `16_blockers_and_recovery_plan.md`<br>B) Create new `16_safe_recovery_procedures.md`<br>C) Embed in Phase 1 ops docs | **B** — separate safe procedures doc |

---

## 8. Phase 1 Entry Criteria (Revised)

**Phase 1 may proceed ONLY when:**

- [ ] CF-01 resolved: Single authoritative `attendance.db` at fixed absolute path
- [ ] CF-02 resolved: CWD-independent path resolution in code
- [ ] CF-03 resolved: 4 Legacy Backend API endpoints implemented and tested
- [ ] CF-04 resolved: Safe recovery procedures documented and tested
- [ ] CF-05 resolved: Quarantine manifest created; critical asset restoration tested
- [ ] HP-02 verified: `models/arcface/glintr100.onnx` exists and matches enrollment SHA256
- [ ] HP-06 resolved: Enrollment reload endpoint + auto-load implemented

**If any CF-XX remains unresolved: Phase 1 BLOCKED.**

---

**End of Open Findings and Risk Register**