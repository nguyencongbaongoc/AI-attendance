# Open Findings and Risk Register

**Date:** 2026-10-04  
**Phase:** 0.2.2  
**Classification:** SOURCE-VERIFIED / RUNTIME-VERIFIED

---

## 1. Resolved Critical Findings

| ID | Finding | Resolution |
|---|---|---|
| CF-01 | Dual active `attendance.db` | Gate A: Authoritative `app/data/attendance.db` established; secondary preserved |
| CF-02 | CWD-dependent path resolution | Gate B: All paths resolved from `__file__` (repo root) |
| CF-03 | Missing 4 API endpoints | Gate E: All 4 implemented; 2 fully functional, 2 scaffolded |
| CF-04 | Unsafe recovery procedures | Gate C: All dangerous instructions replaced with safe procedures |
| CF-05 | Incomplete quarantine/rollback | Gate D: Manifest + classification complete; rollback tests pending |

---

## 2. Open Findings

### 2.1 Critical (Block Phase 1)

| ID | Finding | Impact | Required Action |
|---|---|---|---|
| OF-01 | PipelineEngine health/control endpoints scaffolded | AI Worker cannot report operational health or receive control commands | Implement PipelineEngine control interface + health reporting; forward from Legacy Backend |
| OF-02 | Rollback tests not executed | Cannot verify disaster recovery for critical assets (worktree, models, SDKs) | Execute 5-category rollback tests; update `07_rollback_verification.md` |

### 2.2 High Priority

| ID | Finding | Impact | Required Action |
|---|---|---|---|
| OF-03 | Admin API key not enforced on enrollment reload | Unauthorized reload possible | Enforce `ADMIN_API_KEY` header verification |
| OF-04 | Enrollment file watcher not implemented | Automatic reload on NPY changes not available | Implement file watcher or document manual process |
| OF-05 | PipelineEngine `attendance_events.db` not migrated to API-only | Local SQLite still used for CrossingEvent storage | Phase 1: Migrate to API-only or read-only cache |

### 2.3 Medium Priority

| ID | Finding | Impact | Required Action |
|---|---|---|---|
| OF-06 | Camera 2 FPS variance (47 vs 30) | Timestamp sync issues possible | Investigate during integration testing |
| OF-07 | `generated_live` worktree in quarantine | 4.12 GB Agent Manager worktree misclassified | Document as preserved; exclude from future cleanup |
| OF-08 | `root_model_duplicates/glintr100.onnx` may be only ArcFace copy | If active model missing, enrollment breaks | Verify `models/arcface/glintr100.onnx` exists and matches SHA256 |
| OF-09 | No quarantine manifest in Phase 0.2 artifacts | Historical audit trail incomplete | Archive Phase 0.2.2 manifest with Phase 0.2 artifacts |

### 2.4 Low Priority

| ID | Finding | Impact |
|---|---|---|
| OF-10 | GTX 1660 Ti: No NVDEC hardware decode | Software decode only (known, accepted) |
| OF-11 | `video_pipeline_v2` source in quarantine | May contain unique logic not yet migrated |
| OF-12 | Phase 0.2 artifact count discrepancy | 17 files claimed, 17 exist but #06 embedded, #04 references missing log |

---

## 3. Risk Register (Updated)

| Risk | Likelihood | Impact | Current Mitigation | Residual Risk |
|---|---|---|---|---|
| Camera hardware unavailable | HIGH | HIGH | Document as BLOCKED, test with FFmpeg loop | MEDIUM |
| Enrollment data corrupted | LOW | HIGH | Backup NPY + metadata, verify SHA256 | LOW |
| GPU OOM during inference | MEDIUM | HIGH | VRAM budget 4GB, headroom 2GB, no silent CPU fallback | LOW |
| MediaMTX port conflict | LOW | MEDIUM | Dynamic port discovery, PID-based cleanup | LOW |
| Database lock contention | LOW | MEDIUM | Single authoritative DB, WAL mode, connection pooling | LOW |
| Timestamp sync drift | MEDIUM | HIGH | `stream_epoch` + PTS contract defined in API | MEDIUM |
| NPY reload not auto-triggered | HIGH | MEDIUM | Manual reload endpoint implemented | MEDIUM |
| Quarantine loss (no rollback test) | MEDIUM | HIGH | Manifest created, tests designed | MEDIUM |
| PipelineEngine control interface missing | HIGH | HIGH | Health/control endpoints scaffolded | HIGH |
| AI Worker health not persisted | HIGH | MEDIUM | Health endpoint accepts data but doesn't store | MEDIUM |
| Dual attendance DB recreated | LOW | CRITICAL | Gate B path resolution fixed | LOW |

---

## 4. Decisions Required Before Phase 1

| Decision | Options | Recommendation |
|---|---|---|
| Single authoritative `attendance.db` path | A) `app/data/attendance.db` (has production data) B) `data/attendance.db` (configured default) C) New path | **A** — contains real attendance records |
| `data/attendance.db` disposal | A) Merge into `app/data/` then delete B) Keep as read-only archive C) Rename to `data/attendance_legacy.db` | **A** — merge any unique records (none found), then remove |
| PipelineEngine local `attendance_events.db` | A) Keep as local CrossingEvent cache B) Remove entirely, use API only C) Make read-only, populate from API | **A** for Phase 1 (local cache); **B** for Phase 2+ |
| `generated_live/` worktree handling | A) Keep in quarantine (exclude from cleanup) B) Restore to `.kilo/worktrees/` C) Archive externally | **A** — it's a valid Agent Manager worktree |
| Recovery procedure replacement | A) Patch `16_blockers_and_recovery_plan.md` B) Create new `16_safe_recovery_procedures.md` C) Embed in Phase 1 ops docs | **B** — separate safe procedures doc |

---

## 5. Phase 1 Entry Gate Criteria

**Phase 1 may proceed ONLY when:**

- [ ] OF-01 resolved: PipelineEngine health/control interface implemented
- [ ] OF-02 resolved: Rollback tests executed for all 5 critical categories
- [ ] OF-03 resolved: Admin API key enforced on enrollment reload
- [ ] OF-05 resolved: PipelineEngine migration plan approved (API-only or cache)
- [ ] All CF-XX resolved (CF-01 through CF-05)
- [ ] Architecture A invariants verified (see `11_architecture_invariant_audit.md`)

**If any OF-01 or OF-02 remains unresolved: Phase 1 BLOCKED.**

---

## 6. Phase 1 Scope Confirmation

Based on Phase 0.2.2 remediation, Phase 1 should address:

1. **Week 1:** PipelineEngine control interface + health reporting integration
2. **Week 2-3:** PipelineEngine refactor to use Legacy Backend API for all attendance writes
3. **Week 3:** Integration testing + timestamp sync validation
4. **Week 4:** UI integration (hls.js, Canvas overlay, WebSocket)
5. **Week 5:** Validation + rollback test execution

**Phase 1 must NOT:**
- Modify Architecture A invariants
- Create second attendance authority
- Introduce silent frame dropping or CPU fallback
- Duplicate Phase 22-25 resolver logic

---

**End of Open Findings and Risk Register**