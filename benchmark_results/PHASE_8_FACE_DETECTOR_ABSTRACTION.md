# Phase 8 - Face Detector Abstraction Report

**Timestamp:** 2026-08-18T17:29:56.221703
**Final Verdict:** PASS

---

## Files Created

- `app/vision/detector_contract.py`
- `app/vision/scrfd_adapter.py`
- `app/vision/retinaface_adapter.py`
- `app/vision/detector_factory.py`
- `tests/unit/test_detector_contract.py`

## Files Modified

- `app/vision/__init__.py`

---

## FaceDetector Contract

### FaceDetectionContract

**Fields:**
- bbox (Tuple[float, float, float, float])
- confidence (float)
- landmarks5 (List[Tuple[float, float]])
- coordinate_space (str) - always "original_frame"
- source_frame_id (str)
- detector_model_id (str)
- detector_model_version (str)
- detector_model_sha256 (str)
- provenance (DetectorProvenance)
- detection_id (str)

**Validation Rules:**
- bbox coordinates must be finite
- confidence must be in [0.0, 1.0]
- exactly 5 landmarks required
- landmark coordinates must be finite
- coordinate_space must be "original_frame"
- detector_model_id is required
- detector_model_sha256 is required

**Properties:** width, height, area, center

**Methods:** to_dict()

### FaceDetectorInterface

**Abstract Properties:**
- model_id (str)
- model_version (str)
- model_sha256 (str)
- status (DetectorStatus)
- preprocessing_contract (ModelPreprocessingContract)

**Abstract Methods:**
- detect(frame: CanonicalFrame) -> List[FaceDetectionContract]
- cleanup() -> None

**Context Manager:** __enter__, __exit__

### DetectorProvenance

**Fields:**
- source_type, source_id, frame_index, timestamp
- detector_model_id, detector_model_version, detector_model_sha256
- detection_id

---

## SCRFD Adapter

- **Status:** ACTIVE
- **Model ID:** scrfd
- **Input Size:** 640x640
- **Preprocessing Contract:** SCRFD_CONTRACT (640x640, RGB, LETTERBOX, float32)
- **Model Registry Identity:** Preserved - uses existing ModelRegistry
- **SHA256 Verification:** Preserved - uses existing verify_sha256

**Preserves:**
- bbox (original frame coordinates)
- confidence
- 5-point landmarks (original frame coordinates)
- coordinate space (original_frame)
- provenance (source frame, detector model identity)
- model identity (model_id, version, sha256)

---

## RetinaFace Adapter (Placeholder)

- **Status:** NOT_IMPLEMENTED
- **Model ID:** retinaface
- **Input Size:** TBD
- **Behavior:** Explicitly raises RetinaFaceNotImplementedError on detect() and preprocessing_contract access
- **No Silent Fallback:** True
- **Future Implementation:** Will define its own preprocessing contract when implemented

---

## Model-Specific Preprocessing

| Model | Input Size | Color Space | Resize Mode | Normalization |
|-------|------------|-------------|-------------|---------------|
| SCRFD | 640x640 | RGB | LETTERBOX | NOT_VERIFIED |
| RetinaFace | TBD | TBD | TBD | TBD |
| 1K3D68 | 192x192 | RGB | LETTERBOX | NOT_VERIFIED |
| ArcFace | 112x112 | RGB | CROP | NOT_VERIFIED |

- **Model-specific preprocessing:** True
- **Global image size imposed:** False

---

## Downstream Independence

- **Verified:** True
- **No SCRFD leaks:** True
- **Generic contract used:** True

**Downstream Components:**
- FaceCrop (uses FaceDetectionContract.bbox, landmarks5, coordinate_space)
- LandmarkDetector (uses FaceCrop)
- QualityAssessor (uses FaceCrop, FaceDetectionContract.confidence, LandmarkResult)
- FaceSample (uses FaceDetectionContract, FaceCrop, LandmarkResult, FaceQuality)

---

## Test Results

- **Total Tests:** 47
- **Passed:** 47
- **Failed:** 0

**Test Categories:**
- DetectorProvenance (2 tests)
- FaceDetectionContract (11 tests)
- DetectorModelId (3 tests)
- DetectorStatus (3 tests)
- SCRFDAdapter (6 tests)
- RetinaFaceAdapter (6 tests)
- DetectorFactory (5 tests)
- DownstreamCompatibility (5 tests)
- NegativeCases (6 tests)

---

## Regression Results

- **Total Tests:** 503
- **Passed:** 503
- **Skipped:** 5
- **Failed:** 0
- **No New Regressions:** True

---

## Safety Results

- Camera Access: False
- Mediamtx Started: False
- Rtsp Rtmp Accessed: False
- Persistent Workers: False
- Unbounded Queues: False
- Attendance Logic: False
- In Out Logic: False
- Stranger Logic: False
- Model Weights Modified: False
- **All Passed:** True

---

## Known Phase 7R.3 Limitations

- SCRFD coordinate restoration has known issues (Phase 7R.3 frozen)
- SCRFD CUDA stress/runtime stability not resolved
- SCRFD production acceptance pending
- These are NOT fixed in Phase 8 - Phase 8 only establishes the interface

---

## Readiness for Phase 9

**Ready:** True

---

## Detector Selection

**Status:** OPEN - SCRFD vs RetinaFace decision deferred to evidence-based A/B testing

---

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| 1. FaceDetector interface exists | [PASS] |
| 2. FaceDetection contract is model-independent | [PASS] |
| 3. SCRFD accessible through common interface | [PASS] |
| 4. SCRFD remains configured at 640x640 | [PASS] |
| 5. Coordinate space is explicit | [PASS] |
| 6. Five-point landmarks preserved | [PASS] |
| 7. Provenance preserved | [PASS] |
| 8. Model identity preserved | [PASS] |
| 9. Downstream depends on generic contract | [PASS] |
| 10. No SCRFD-specific implementation leaks downstream | [PASS] |
| 11. RetinaFace can be added without redesign | [PASS] |
| 12. Tests pass | [PASS] (47/47) |
| 13. No new regression introduced | [PASS] (503/503) |
| 14. Safety checks pass | [PASS] |

---

**Phase 8 establishes the interface. It does NOT decide which detector wins.**
**The future decision must be evidence-based: SCRFD vs RetinaFace using the SAME detector contract and SAME downstream pipeline.**
