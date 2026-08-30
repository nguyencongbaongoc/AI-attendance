# Phase 14 — ArcFace Identity Matching Benchmark Report

## Executive Summary

**Phase**: 14 — ArcFace Identity Matching  
**Status**: PASS  
**Date**: 2026-08-20  
**Environment**: Windows 11, Python 3.12.10, NVIDIA GPU (CUDA available)

Phase 14 implements OFFLINE ArcFace identity matching against a Phase 13 enrollment database. The implementation provides deterministic identity matching with three possible outcomes: MATCH, UNKNOWN, and AMBIGUOUS.

---

## Matching Contract

### IdentityMatchResult Fields
- **status**: MATCH / UNKNOWN / AMBIGUOUS
- **person_id**: Matched person ID (null for UNKNOWN/AMBIGUOUS)
- **similarity**: Best cosine similarity score [0, 1]
- **matched_sample_id**: Sample ID of best match (null for UNKNOWN/AMBIGUOUS)
- **candidate_count**: Number of database embeddings evaluated
- **threshold**: Match threshold used (default 0.5)
- **ambiguity_margin**: Ambiguity margin used (default 0.05)
- **database_schema_version**: Schema version of enrollment database
- **model_identity**: Model identity (arcface/glintr100.onnx)
- **provenance**: Complete audit trail

### QueryEmbeddingContract
- **embedding**: 512D float32 L2-normalized vector
- **provenance**: Optional query provenance

### MatchingConfig
- **match_threshold**: Minimum similarity for MATCH (default 0.5)
- **ambiguity_margin**: Max difference between best and second-best for MATCH (default 0.05)
- **person_aggregation_policy**: "best_sample" or "average" (default "best_sample")

---

## Database Validation

Before matching, the Phase 13 enrollment database is validated:

**Required checks:**
- Shape: (N, 512), dtype: float32
- All values finite
- L2-normalized embeddings (norm ≈ 1.0, atol=1e-5)
- Metadata schema_version = "1.0"
- embedding_dimension = 512
- dtype = "float32"
- normalization = "L2"
- model_id = "arcface"
- model_filename = "glintr100.onnx"
- model_sha256 non-empty
- embedding_count matches array shape
- sample_provenance length matches embedding_count

**Rejection behavior:** Invalid databases raise ValueError with descriptive message. No silent repair.

---

## Query Validation

Query embeddings are validated before matching:
- Shape: (512,), dtype: float32
- All values finite
- Non-zero norm
- L2-normalized (norm ≈ 1.0, atol=1e-4)

Invalid queries raise ValueError immediately.

---

## Cosine Similarity

Since both database and query embeddings are L2-normalized:
```
cosine_similarity = dot(query, database_embedding)
```

**Implementation:** Vectorized NumPy dot product for efficiency.
**Validation:** Output similarities checked for finite values and range [-1, 1] with 1e-6 tolerance.

---

## Best Candidate Selection

For each query:
1. Compute cosine similarity against all N database embeddings
2. Build candidate matches with sample_id, person_id, similarity, provenance
3. Aggregate to person level using configured policy

---

## Person-Level Matching

**Aggregation Policy: "best_sample" (default)**
- For each person, use the maximum similarity across their samples
- Person-level match sorted by best similarity descending

**Aggregation Policy: "average"**
- Average similarity across all samples for each person
- Person-level match sorted by average similarity descending

**Key Design Decision:** Ambiguity is evaluated at PERSON level, not sample level. Multiple samples for the same person do NOT trigger ambiguity.

---

## Decision Logic

### UNKNOWN
```
best_person_similarity < match_threshold
→ status = UNKNOWN, person_id = None
```

### AMBIGUOUS
```
best_person_similarity >= match_threshold
AND (best_person_similarity - second_best_person_similarity) < ambiguity_margin
→ status = AMBIGUOUS, person_id = None
```

### MATCH
```
best_person_similarity >= match_threshold
AND (best_person_similarity - second_best_person_similarity) >= ambiguity_margin
→ status = MATCH, person_id = best_person.person_id
```

---

## Threshold Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| match_threshold | 0.5 | Minimum similarity for MATCH |
| ambiguity_margin | 0.05 | Max gap between best and second-best for MATCH |

**Note:** These are engineering baselines, not accuracy claims. Real-world validation data required for production thresholds.

---

## Provenance Preservation

Every match result includes complete provenance:

**MATCH provenance:**
- query_provenance
- database_model_id, database_model_filename, database_model_sha256
- database_schema_version
- matching_time_ms
- person_aggregation_policy
- decision: "match"
- matched_person_id, matched_sample_id, matched_similarity
- sample_count_for_person
- all_person_matches (top 5)

**UNKNOWN provenance:**
- decision: "below_threshold"
- best_person_id, best_person_similarity
- all_person_matches (top 5)

**AMBIGUOUS provenance:**
- decision: "ambiguous"
- best_person_id, best_person_similarity
- second_best_person_id, second_best_person_similarity
- margin
- all_person_matches (top 5)

---

## Determinism

**Guaranteed deterministic behavior:**
- Same query + same database + same config → identical results
- Database sample ordering does not affect decision
- Tie handling is deterministic (no dependence on array order)
- Person aggregation uses explicit sorting by (person_id, similarity)

---

## Order Independence

Database sample ordering does not affect identity decision:
- Shuffling database samples produces identical MATCH/UNKNOWN/AMBIGUOUS decision
- Identical person_id and similarity within tolerance
- Deterministic tie handling when candidates equivalent

---

## Database Integrity

**Rejected databases:**
- Corrupted .npy files
- Corrupted metadata JSON
- Wrong model_id (not "arcface")
- Wrong model_filename (not "glintr100.onnx")
- Empty model_sha256
- Wrong embedding dimension (not 512)
- Wrong dtype (not float32)
- NaN/Inf values in embeddings
- Non-normalized embeddings
- Incompatible schema_version

All rejections raise ValueError with descriptive message.

---

## Performance & Memory

**Tested characteristics:**
- Bounded memory: 1000-embedding database, 10 repeated queries → no memory growth
- No database mutation: Original embeddings unchanged after matching
- No unbounded candidate accumulation: 100 repeated queries → constant candidate_count
- Vectorized similarity computation: O(N) with NumPy dot product

---

## Safety Boundaries

**Phase 14 is OFFLINE ONLY. Verified no access to:**
- Camera / CameraCapture / cv2.VideoCapture
- MediaMTX
- RTSP / RTMP
- Live FFmpeg / subprocess
- Attendance logic
- IN/OUT logic
- Schedule logic
- Excel / openpyxl
- 1K3D68
- Model weight modification

---

## Test Results Summary

### Phase 14 Targeted Tests: 91 tests
- **Passed**: 91
- **Failed**: 0
- **Skipped**: 0

### Full Regression: 836 tests
- **Passed**: 828
- **Skipped**: 8
- **Failed**: 0

### Test Coverage
| Category | Tests |
|----------|-------|
| Matching Contract | 14 |
| Database Validation | 8 |
| Query Validation | 6 |
| Cosine Similarity | 6 |
| Best Candidate | 1 |
| Person-Level Matching | 3 |
| Unknown Threshold | 2 |
| Ambiguity | 3 |
| Same-Person Multiple Samples | 2 |
| Unknown Case | 2 |
| Ambiguous Case | 3 |
| Order Independence | 2 |
| Determinism | 2 |
| Provenance | 4 |
| Database Integrity | 10 |
| Performance/Memory | 3 |
| Safety | 10 |
| Integration | 3 |
| Negative Cases | 7 |
| **Total** | **91** |

---

## Files Created

### Implementation
- `app/vision/matching_contract.py` — Matching contract definitions
- `app/vision/matching.py` — Identity matching implementation

### Tests
- `tests/unit/test_phase14_matching.py` — 91 comprehensive unit tests

---

## Phase Boundary Verification

✅ **Phase 14 does NOT implement:**
- MediaMTX / RTMP / RTSP
- StreamKeeper / CameraCapture
- IPC / Scheduler
- SCRFD / ArcFace inference (reuses Phase 12)
- 1K3D68 / ReID / YOLO
- Tracking / Identity / Attendance
- Line crossing / Stranger detection
- Annotation / API / Database

✅ **Phase 14 ONLY implements:**
- Offline identity matching against Phase 13 database
- MATCH / UNKNOWN / AMBIGUOUS decisions
- Database validation & query validation
- Person-level aggregation
- Provenance preservation

---

## Known Limitations

1. **Threshold calibration**: Default thresholds (0.5 match, 0.05 ambiguity) are engineering baselines. Production deployment requires validation on representative dataset.

2. **Approximate nearest neighbor**: Current implementation uses exact vectorized comparison. For large databases (>10K embeddings), consider FAISS/ANN in future phase.

3. **Single-query API**: No batch matching API yet. Can be added if needed.

4. **No score calibration**: Raw cosine similarity used. Temperature scaling or Platt calibration could improve threshold interpretability.

---

## Final Verdict

**PHASE 14 = PASS**

- ✅ All targeted tests pass (91/91)
- ✅ Full regression passes (828/828, 8 skipped)
- ✅ Safety boundaries verified
- ✅ Database validation works
- ✅ Matching logic correct (MATCH/UNKNOWN/AMBIGUOUS)
- ✅ Determinism guaranteed
- ✅ Provenance preserved
- ✅ Memory bounded
- ✅ No phase boundary violations

**Ready for Phase 15: YES**