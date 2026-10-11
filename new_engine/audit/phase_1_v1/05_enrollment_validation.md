# Phase 1.V1 Enrollment Validation

**Date**: 2026-10-04
**Phase**: 1.V1 - Environment and Camera Source Recovery

---

## 1. Enrollment Database Status

### Required Files (MISSING)
| File | Path | Status | Required For |
|------|------|--------|--------------|
| Embeddings NPY | `data/embeddings.npy` | ❌ NOT EXISTS | ArcFace identity matching |
| Metadata JSON | `data/embeddings.npy.metadata.json` | ❌ NOT EXISTS | Person ID mapping, model verification |

### Enrollment Directory
```
data/enrollment/  # EXISTS but EMPTY
```

---

## 2. Enrollment Pipeline Architecture

### API Endpoint
```
POST /api/v1/enrollment/persons
Content-Type: multipart/form-data
Headers: X-API-Key: <ADMIN_API_KEY>
Fields:
  - person_id: string (e.g., "STU-10001")
  - name: string
  - role: string (student|staff|visitor)
  - student_class: string (optional)
  - image: file (JPEG/PNG)
```

### Processing Pipeline (`app/vision/enrollment.py`)
1. **Save Upload** → Temporary file
2. **process_image_enrollment()** → Face detection + quality + embedding
3. **build_enrollment_database()** → Aggregate → NPY + metadata.json
4. **load_enrollment_database()** → Load into ArcFaceRecognizer

### Models Used
| Model | Purpose | Path |
|-------|---------|------|
| SCRFD 10G | Face detection + 5-point landmarks | `models/scrfd/scrfd_10g_bnkps.onnx` |
| ArcFace (glintr100) | 512D embedding extraction | `models/arcface/glintr100.onnx` |

### Quality Filters (from enrollment config)
- Face detection confidence ≥ 0.5
- Face quality score ≥ threshold
- Pose/yaw/pitch within limits
- Minimum face size
- Sharpness/brightness checks

---

## 3. ArcFace Enrollment Contract

### Embedding Specification
| Parameter | Value | Source |
|-----------|-------|--------|
| Input Size | 112×112 | ArcFaceConfig.input_size |
| Output Dimension | 512 | ArcFaceConfig.embedding_dim |
| Normalization | (x - 127.5) / 128.0 | ArcFaceConfig.mean/std |
| L2 Normalization | Required | ArcFaceRecognizer.infer_embedding() |
| Similarity Threshold | 0.6 | ArcFaceConfig.similarity_threshold |

### NPY Format
```python
# embeddings.npy: shape (N, 512), dtype float32
# Each row = L2-normalized embedding for one enrolled sample
# Multiple samples per person_id are stacked

# metadata.json:
{
  "creation_timestamp": "2026-10-04T12:00:00Z",
  "model_sha256": "<glintr100.onnx sha256>",
  "embedding_dimension": 512,
  "person_ids": ["STU-10001", "STU-10002", ...],
  "sample_provenance": [
    {"person_id": "STU-10001", "sample_index": 0, "quality": 0.95, ...},
    ...
  ]
}
```

---

## 4. ArcFaceRecognizer Loading

### Code Path (`pipeline_engine/inference/face_recognition.py`)
```python
def load_enrollment_database(self, embeddings_path, metadata_path):
    embeddings = np.load(embeddings_path)  # (N, 512)
    # Convert to GPU tensors, L2 normalize
    # Load metadata for person_id mapping
```

### CameraManager Integration (`camera_manager.py:222-225`)
```python
arcface_recognizer.load_enrollment_database(
    "data/embeddings.npy",
    "data/embeddings.npy.metadata.json"
)
```

### Worker Reload (`worker.py:690-705`)
```python
async def _reload_enrollment(self):
    for camera_id in self.engine.camera_manager.get_camera_list():
        camera = self.engine.camera_manager._cameras.get(camera_id)
        if camera and camera.get("arcface"):
            camera["arcface"].load_enrollment_database(
                "data/embeddings.npy",
                "data/embeddings.npy.metadata.json"
            )
```

---

## 5. Test Enrollment Creation Plan

### Prerequisites
1. Legacy Backend running on port 19146
2. `ADMIN_API_KEY` configured in environment
3. Test image with clear face (frontal, good lighting)

### Enrollment Command
```bash
curl -X POST http://localhost:19146/api/v1/enrollment/persons \
  -H "X-API-Key: <ADMIN_API_KEY>" \
  -F "person_id=TEST-001" \
  -F "name=Test Person" \
  -F "role=student" \
  -F "student_class=TEST" \
  -F "image=@test_face.jpg"
```

### Expected Response
```json
{
  "success": true,
  "person_id": "TEST-001",
  "name": "Test Person",
  "role": "student",
  "student_class": "TEST",
  "vector_count": 1,
  "embedding_dimension": 512,
  "model_sha256": "abc123...",
  "output_directory": "C:\\...\\app\\data\\enrollment",
  "npy_filename": "TEST-001.npy"
}
```

### Post-Enrollment Verification
1. Check `data/embeddings.npy` exists (shape: N×512)
2. Check `data/embeddings.npy.metadata.json` exists
3. Verify ArcFaceRecognizer loads without error
4. Test identification with same face → similarity ≥ 0.6

---

## 6. Current Blocker Status

**NO ENROLLMENT DATABASE** - Blocker for:
- V2: Identity matching (ArcFace will return empty matches)
- V3: Dual-camera identity consistency
- V4: End-to-end attendance with recognized identities
- V5: Final qualification

### Impact on Pipeline
| Component | Without Enrollment | With Enrollment |
|-----------|-------------------|-----------------|
| ArcFaceRecognizer.identify() | Returns `[]` (no matches) | Returns `(person_id, similarity)` |
| CrossingEvent.person_id | Always `None` | Populated if similarity ≥ 0.6 |
| CrossingEvent.person_name | Always `None` | From metadata |
| CrossingEvent.identity_confidence | Always `0.0` | Similarity score |
| AttendanceEngine | Tracks unknown persons | Resolves known identities |

### V2 Workaround
Run V2 with **unknown identities only** - proves pipeline works but cannot verify identity matching. Document as "unknown-person processing" vs "identity recognition".

---

## 7. Enrollment API Implementation Check

### `app/api/enrollment.py` Endpoints
| Endpoint | Auth | Purpose |
|----------|------|---------|
| POST /persons | ADMIN | Enroll new person from image |
| GET /persons | ADMIN | List enrolled persons |
| POST /reload | ADMIN | Reload NPY database |
| GET /reload/status | ADMIN | Check database status |

### Dependencies
```python
from app.vision.enrollment import (
    EnrollmentConfig,
    build_enrollment_database,
    load_enrollment_database,
    process_image_enrollment,
)
```

---

## 8. Enrollment Validation Verdict

**STATUS**: ❌ **NO ENROLLMENT DATABASE** - Blocker for identity matching

**V1 Gate Criteria**:
> Enrollment readiness established. If enrollment is absent, report the exact missing dependency and determine whether a legitimate test enrollment can be created through the existing enrollment workflow.

**Finding**: 
- ✅ Enrollment workflow exists and is implemented (`app/api/enrollment.py`)
- ✅ Models available (SCRFD + ArcFace)
- ✅ API endpoints ready (require Backend + ADMIN_API_KEY)
- ❌ No embeddings.npy or metadata.json exist
- ❌ No test enrollments created

**Resolution**: Create test enrollment via API once Backend is running (V1.6).

---

## 9. Evidence Artifacts

### Enrollment API Code
- `app/api/enrollment.py` - Full implementation
- `app/vision/enrollment.py` - Core pipeline (process_image_enrollment, build_enrollment_database)

### ArcFace Contract
- `pipeline_engine/inference/face_recognition.py:25-33` - ArcFaceConfig
- `pipeline_engine/inference/face_recognition.py:141-197` - load_enrollment_database
- `pipeline_engine/inference/face_recognition.py:336-369` - identify()

### CameraManager Integration
- `pipeline_engine/ingestion/camera_manager.py:222-225` - Initial load
- `pipeline_engine/core/worker.py:690-705` - Hot reload on file change

### Commands for Test Enrollment (After Backend Start)
```bash
# 1. Prepare test image (clear frontal face)
# 2. Enroll via API
curl -X POST http://localhost:19146/api/v1/enrollment/persons \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -F "person_id=TEST-001" \
  -F "name=Test User" \
  -F "role=student" \
  -F "image=@test_face.jpg"

# 3. Verify database created
ls -la data/embeddings.npy*

# 4. Test reload
curl -X POST http://localhost:19146/api/v1/enrollment/reload \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"trigger": "manual"}'
```