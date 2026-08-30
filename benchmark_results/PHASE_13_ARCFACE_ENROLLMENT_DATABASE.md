# Phase 13 — ArcFace Enrollment Database

**Status: PASS**

**Timestamp:** 2026-08-19T22:46:00+07:00

---

## Test Results

| Category | Total | Passed | Failed | Skipped |
|----------|-------|--------|--------|---------|
| Phase 13 Targeted Tests | 70 | 67 | 0 | 3 |
| Full Regression | 745 | 737 | 0 | 8 |

---

## Safety Verification

All safety boundaries verified:

- ✅ No camera access
- ✅ No MediaMTX
- ✅ No RTSP/RTMP
- ✅ No live FFmpeg streaming
- ✅ No attendance/IN/OUT logic
- ✅ No schedule/Excel access
- ✅ No identity matching
- ✅ No 1K3D68 usage

---

## Image Enrollment

**Pipeline:** `IMAGE → Face Detection → Face Crop → Normal Alignment → 112×112 → ArcFace → 512D → L2 normalize`

- ✅ Contract compliance
- ✅ Provenance preserved
- ✅ Quality filtering
- ✅ Duplicate filtering

---

## Video Enrollment

**Pipeline:** `VIDEO → VideoFrameIterator → Face Detection → Face Crop → Normal Alignment → 112×112 → ArcFace → 512D → L2 normalize`

- ✅ Contract compliance
- ✅ Provenance preserved (including frame_index)
- ✅ Frame-by-frame processing (bounded memory)
- ✅ Quality filtering
- ✅ Duplicate filtering

---

## Embedding Schema

| Property | Value |
|----------|-------|
| dtype | float32 |
| dimension | 512 |
| normalization | L2 |
| model | ArcFace glintr100.onnx |

---

## Database Schema

### embeddings.npy
- **Shape:** (N, 512)
- **Dtype:** float32

### embeddings.npy.metadata.json
```json
{
  "schema_version": "1.0",
  "embedding_dimension": 512,
  "dtype": "float32",
  "normalization": "L2",
  "model_id": "arcface",
  "model_filename": "glintr100.onnx",
  "model_sha256": "verified",
  "enrollment_contract_version": "1.0",
  "embedding_count": N,
  "person_ids": [...],
  "sample_provenance": [...],
  "creation_timestamp": "ISO 8601"
}
```

---

## Provenance (Per Sample)

Every accepted sample retains:

- ✅ person_id
- ✅ source_type (IMAGE/VIDEO)
- ✅ source identifier
- ✅ frame_index (for video)
- ✅ timestamp (ISO 8601)
- ✅ face detection provenance (model, SHA256, confidence, bbox, landmarks)
- ✅ preprocessing contract (crop method, alignment method, size, interpolation)
- ✅ ArcFace model identity (model_id, filename, SHA256, dimension, normalization)
- ✅ quality score
- ✅ quality passed flag
- ✅ duplicate status

---

## Duplicate Filtering Policy

- **Method:** Cosine similarity
- **Threshold:** 0.98 (configurable)
- **Explainable:** Every duplicate decision records `duplicate_of` sample_id
- **Preserves legitimate samples:** Does not delete different samples to reduce database size

---

## Quality Filtering Policy

| Check | Threshold | Deterministic |
|-------|-----------|---------------|
| Min face area | 400 px² | ✅ |
| Min crop dimension | 32 px | ✅ |
| Min detection confidence | 0.5 | ✅ |
| Min embedding norm | 0.1 | ✅ |
| Finite values | Required | ✅ |
| Non-empty aligned face | Required | ✅ |

All rejection reasons recorded.

---

## Determinism

- ✅ Sample ordering: sorted by (person_id, source, sample_id)
- ✅ Duplicate decisions: identical across runs
- ✅ Same source + same config → identical output

---

## Memory Safety

- ✅ Video enrollment: frame-by-frame streaming, no full-video accumulation
- ✅ Bounded RAM: only accepted embeddings + rejected metadata stored
- ✅ No unbounded frame queues
- ✅ Database writer: collects all samples then writes (acceptable for Phase 13 scope)

---

## Negative Tests (All Pass)

- ✅ Missing person_id → rejected
- ✅ Invalid source type → rejected
- ✅ Missing source → rejected
- ✅ Invalid embedding shape → rejected
- ✅ Invalid embedding dtype → rejected
- ✅ NaN embedding → rejected
- ✅ Non-normalized embedding → rejected
- ✅ Corrupted metadata JSON → rejected with "Database validation failed"
- ✅ Incompatible schema version → rejected

---

## Blockers

None.

---

## Ready for Phase 14

**YES** — All Phase 13 acceptance criteria met.