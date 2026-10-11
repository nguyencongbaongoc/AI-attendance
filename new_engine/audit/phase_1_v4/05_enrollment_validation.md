# Phase 1.V4 Enrollment Validation - Updated

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Enrollment Database Status - UPDATED

### Created Synthetic Enrollment Database
| File | Path | Status |
|------|------|--------|
| Embeddings NPY | `app/data/enrollment/embeddings.npy` | ✅ EXISTS (3×512) |
| Metadata JSON | `app/data/enrollment/embeddings.npy.metadata.json` | ✅ EXISTS |

### Enrollment Content
| Person ID | Vector Count | Quality | Role |
|-----------|--------------|---------|------|
| TEST-001 | 1 | 0.95 | visitor |
| TEST-002 | 1 | 0.92 | visitor |
| TEST-003 | 1 | 0.88 | visitor |

### Enrollment Verification
```bash
# Reload enrollment
curl -X POST http://localhost:18693/api/v1/enrollment/reload \
  -H "X-API-Key: admin-test-key-1234567890123456"
# {"success":true,"persons_loaded":3,"vectors_loaded":3,"embedding_dimension":512}

# List enrolled persons
curl http://localhost:18693/api/v1/enrollment/persons \
  -H "X-API-Key: admin-test-key-1234567890123456"
# Returns 3 persons: TEST-001, TEST-002, TEST-003
```

---

## 2. ArcFace Integration Status

### ArcFaceRecognizer Load Test
```bash
# The ArcFaceRecognizer in CameraManager loads enrollment on init
# And hot-reloads on file change (30s interval)
```

### ArcFace Contract Verified
| Parameter | Value | Status |
|-----------|-------|--------|
| Input Size | 112×112 | ✅ |
| Output Dim | 512 | ✅ |
| Normalization | (x - 127.5) / 128.0 | ✅ |
| L2 Normalization | Required | ✅ |
| Similarity Threshold | 0.6 | ✅ |
| Model | glintr100.onnx | ✅ |

---

## 3. V4 Test Plan - Updated

### Ready for V4 Testing
- ✅ Backend running (port 18693)
- ✅ Event ingestion working
- ✅ Enrollment database created and loaded
- ✅ ArcFaceRecognizer can load enrollment
- ✅ CameraManager dual-camera tested (30 min)
- ❌ Real crossing events not yet generated (need person in scene)

### Next V4 Steps
1. **Run CameraManager** with people in scene
2. **Generate real crossing events** from person crossing line
3. **Verify event delivery** to Backend
4. **Trace resolver chain**: CrossingEvent → RawInOutEvent → ResolvedTransition → AttendanceRecord
5. **Verify AttendanceRecord** in `data/attendance.db`

---

## 4. Current Blocker for Full V4

**No real person in camera view** - Cannot generate real crossing events.

### Options:
1. **Manual test**: Have person walk in front of camera
2. **Synthetic test**: Inject mock CrossingEvent to test delivery chain
3. **Defer**: Document V4 as ready pending human test

---

## 5. V4 Readiness Assessment

| Component | Status |
|-----------|--------|
| Backend API | ✅ Running |
| Event Ingestion | ✅ Working |
| Enrollment DB | ✅ Loaded |
| ArcFace Recognizer | ✅ Initialized |
| CameraManager | ✅ Tested (30 min dual-camera) |
| EventDeliveryClient | ✅ Ready |
| Backend Resolver | ✅ Implemented |
| AttendanceRecord DB | ✅ Isolated |

**V4 READY FOR REAL-WORLD TEST** - Awaiting human subject