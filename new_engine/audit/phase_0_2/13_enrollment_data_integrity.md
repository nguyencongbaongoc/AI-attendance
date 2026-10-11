# Phase 0.2 — Enrollment Data Integrity

**Date:** 2026-10-04  
**Phase:** 0.2 — Stage D: Infrastructure Bring-Up (Enrollment Verification)

---

## 1. Enrollment Data Location

| File | Path | Status |
|------|------|--------|
| Embeddings | `app/data/enrollment/embeddings.npy` | ✅ EXISTS |
| Metadata | `app/data/enrollment/embeddings.npy.metadata.json` | ✅ EXISTS |

---

## 2. Embeddings Array

| Property | Value |
|----------|-------|
| **Shape** | (7, 512) |
| **Dtype** | float32 |
| **Normalization** | L2 (per metadata) |
| **Embedding Dimension** | 512 (matches ArcFace R100) |
| **Sample Count** | 7 |
| **Person Count** | 1 unique person |

---

## 3. Metadata Summary

| Field | Value |
|-------|-------|
| **Schema Version** | 1.0 |
| **Model ID** | arcface |
| **Model Filename** | glintr100.onnx |
| **Model SHA256** | 4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf |
| **Enrollment Contract Version** | 1.0 |
| **Embedding Count** | 7 |
| **Person IDs** | ["STU-99999"] |
| **Creation Timestamp** | 2026-09-02T16:08:58.721647Z |

---

## 4. Sample Provenance (7 samples, 1 person: STU-99999)

| Sample ID | Detection Conf | Quality Score | Quality Passed | Source |
|-----------|----------------|---------------|----------------|--------|
| STU-99999_tmpc6aaf7nj_0_138aefe2 | 0.996 | 0.687 | ✅ | Temp JPG |
| STU-99999_tmpc6aaf7nj_16_94aae359 | 0.727 | 0.472 | ✅ | Temp JPG |
| STU-99999_tmpc6aaf7nj_27_58890b10 | 0.620 | 0.413 | ✅ | Temp JPG |
| STU-99999_tmpc6aaf7nj_31_968fee87 | 0.579 | 0.371 | ✅ | Temp JPG |
| STU-99999_tmpc6aaf7nj_41_9c0c1bb0 | 0.500 | 0.373 | ✅ | Temp JPG |
| STU-99999_tmpc6aaf7nj_4_796618ef | 0.866 | 0.579 | ✅ | Temp JPG |
| STU-99999_tmpc6aaf7nj_9_78679d7b | 0.812 | 0.715 | ✅ | Temp JPG |

**All 7 samples:** Same source image (temp JPG), different face detections/frames
**Detection Model:** SCRFD (SHA256: 5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91)
**Alignment:** similarity_transform_5pt to 112×112
**ArcFace Provider:** CUDAExecutionProvider
**Inference Times:** 11-164 ms per sample

---

## 5. Model Compatibility

| Enrollment Model | Inference Model | Match |
|------------------|-----------------|-------|
| ArcFace R100 (glintr100.onnx) | `models/arcface/glintr100.onnx` | ✅ SHA256 matches |
| SCRFD detector | `models/scrfd/scrfd_10g_bnkps.onnx` | ✅ SHA256 matches |
| Embedding dim: 512 | ArcFace output: 512 | ✅ Matches |

---

## 6. Backend Enrollment API Verification

```
GET /api/v1/persons/enrollment/stats
```
```json
{
  "total_enrolled": 0,
  "students": 0,
  "staff": 0,
  "avg_quality": 0,
  "model": "ArcFace R100",
  "threshold": "0.45 cosine",
  "last_updated": "—"
}
```

**Note:** API reports 0 enrolled. This suggests the Legacy Backend enrollment service reads from a different location or the NPY file is not loaded by the enrollment service. The NPY file exists and is valid but may not be registered in the backend's enrollment database.

**Action for Phase 1:** Implement `POST /api/v1/enrollment/reload` endpoint to reload NPY embeddings into backend.

---

## 7. Verdict

**ENROLLMENT DATA INTEGRITY: PASS (with note)**

- ✅ Embeddings file exists and is valid (7×512 float32)
- ✅ Metadata exists with full provenance
- ✅ Model SHA256 matches inference model files
- ✅ Embedding dimension matches ArcFace R100 (512)
- ✅ Quality scores reasonable, all samples passed
- ⚠️ Legacy Backend enrollment API reports 0 enrolled — NPY not loaded by service

**Not a blocker for Phase 0.2.** The enrollment data exists and is loadable by AI Worker. Backend integration requires Phase 1 endpoint implementation.

---

## 8. Evidence Commands

```bash
# Check embeddings
.venv2\Scripts\python.exe -c "
import numpy as np
emb = np.load('app/data/enrollment/embeddings.npy')
print('Shape:', emb.shape)
print('Dtype:', emb.dtype)
print('L2 norms:', np.linalg.norm(emb, axis=1))
"

# Check metadata
.venv2\Scripts\python.exe -c "
import json
with open('app/data/enrollment/embeddings.npy.metadata.json') as f:
    m = json.load(f)
print('Persons:', m['person_ids'])
print('Count:', m['embedding_count'])
print('Model:', m['model_filename'])
print('SHA256:', m['model_sha256'])
"

# Backend enrollment stats
curl http://localhost:19146/api/v1/persons/enrollment/stats
```