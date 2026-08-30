# Phase 10 — Person ↔ Face Association

## Summary

**Status: PASS**

Phase 10 implements the deterministic offline association layer between YOLO11n person detections and face detector detections (SCRFD). All association operates in ORIGINAL_FRAME coordinates (3840×2160).

## Test Results

| Metric | Value |
|--------|-------|
| Tests Passed | 563 |
| Tests Skipped | 5 |
| Tests Failed | 0 |
| Errors | 0 |
| Duration | 71.39s |

## Association Layer Components

### Core Modules
- `app/vision/association.py` — Main association engine
- `app/vision/association_contract.py` — Model-independent contracts
- `app/vision/association_geometry.py` — Geometry primitives

### Contracts
- `PersonFaceAssociation` — Canonical association result
- `AssociationResult` — Complete frame-level result with summary
- `AssociationStatus` — Enum: ASSOCIATED, UNASSOCIATED_FACE, UNASSOCIATED_PERSON, AMBIGUOUS
- `AssociationScore` — Decomposed scoring components

### Geometry Primitives
- `bbox_area`, `bbox_intersection`, `intersection_area`
- `iou`, `intersection_over_face`
- `face_center_in_person`, `face_center_distance_to_person`
- `bbox_containment`, `clip_bbox_to_frame`
- `validate_bbox_4k`, `validate_coordinate_space`

### Scoring Components (weights sum to 1.0)
1. **containment_score** (0.3): Face center inside person bbox
2. **intersection_ratio** (0.25): Intersection over face area
3. **iou_score** (0.2): IoU between face and person
4. **distance_score** (0.15): Inverse distance from face center to person
5. **area_ratio_score** (0.1): Face area / person area (penalize oversized faces)

### Assignment Algorithm
- Greedy assignment with ambiguity detection
- Faces sorted by best score (highest first)
- Person reassignment if new face has clearly better claim (> ambiguity_margin)
- Ambiguity margin: 0.05 (configurable)

## Test Coverage

### Geometry Primitives (10 tests)
- BBox area, intersection, IoU, intersection-over-face
- Face center containment, distance to person
- BBox containment, clipping to frame
- 4K boundary validation, coordinate space validation

### Association Scoring (4 tests)
- Perfect match (face fully inside person)
- No overlap
- Partial overlap
- Ambiguity detection

### Contract Validation (5 tests)
- Valid association creation
- Invalid coordinate space rejection
- Invalid bbox boundaries rejection
- Invalid confidence rejection
- Missing model identity rejection

### Coordinate Space Validation (5 tests)
- Valid 4K coordinates accepted
- Model input coordinates rejected
- Normalized coordinates rejected
- Out-of-bounds bbox rejected
- Non-4K frame rejected

### One Person / One Face (3 tests)
- Single person + single face → ASSOCIATED
- Mismatched person/face → both UNASSOCIATED
- Reverse mismatch → both UNASSOCIATED

### Multiple Persons / Faces (3 tests)
- Two persons + two faces → correct pairing
- Shuffled input order → deterministic result
- Three persons + three faces → correct pairing

### Multiple Faces in One Person (1 test)
- Two faces in one person bbox → one ASSOCIATED, one AMBIGUOUS/UNASSOCIATED

### Overlapping Persons (1 test)
- Face in overlap region → AMBIGUOUS

### Partial Face Outside Person (2 tests)
- Face center inside, bbox extends outside → ASSOCIATED (partial allowed)
- Face center outside, partial not allowed → UNASSOCIATED_FACE

### Edge Cases (8 tests)
- Face at image boundary
- Tiny face (20×20)
- Large face (larger than person)
- Zero-area bbox rejected
- Equal scores → AMBIGUOUS
- Near-equal scores → AMBIGUOUS/ASSOCIATED

### Global Assignment (2 tests)
- Two faces compete for one person → best match wins
- Assignment independent of input order

### Unmatched Detections (2 tests)
- Person without face → preserved as UNASSOCIATED_PERSON
- Face without person → preserved as UNASSOCIATED_FACE

### Provenance (1 test)
- DetectorProvenance preserved through association

### Determinism (2 tests)
- Repeated runs identical
- Shuffled inputs produce identical results

### Invalid Input Rejection (4 tests)
- NaN bbox rejected
- Inf bbox rejected
- Negative bbox rejected
- Face model_input coordinates rejected

### Memory Safety (1 test)
- 20 frames processed, memory bounded (< 300 MB)

### Safety Boundary (1 test)
- No forbidden imports (cv2.VideoCapture, rtmp://, rtsp://, ffmpeg, MediaMTX)

### Association Result (2 tests)
- Summary counts correct
- Serialization to dict

### Configuration (2 tests)
- Custom weights
- Custom ambiguity margin

### No Identity (2 tests)
- No ArcFace/1K3D68/identity recognition references
- No tracking dependencies (kalman, deepsort, bytetrack)

## Safety Verification

| Check | Result |
|-------|--------|
| Camera access | NO |
| MediaMTX started | NO |
| RTSP access | NO |
| RTMP access | NO |
| Live FFmpeg streaming | NO |
| Persistent workers | NO |
| Unbounded queues | NO |
| Tracking implemented | NO |
| ArcFace used | NO |
| 1K3D68 used | NO |
| Identity matching | NO |
| IN/OUT logic | NO |
| Attendance logic | NO |
| Schedule logic | NO |
| Excel export | NO |
| Stranger logic | NO |
| Model weights modified | NO |

## Files Created

### Source Code
- `app/vision/association.py` (484 lines)
- `app/vision/association_contract.py` (338 lines)
- `app/vision/association_geometry.py` (457 lines)

### Tests
- `tests/unit/test_association.py` (1301 lines, 60 tests)

## Phase Boundary Compliance

Phase 10 does NOT implement:
- ArcFace identity recognition
- 1K3D68 landmark detection
- Attendance logic
- IN/OUT line crossing
- Schedule management
- Excel export
- Camera/RTSP/RTMP streaming
- MediaMTX
- Tracking (Kalman, DeepSort, ByteTrack)
- Database or API
- UI

## Acceptance Criteria

✅ All 60 unit tests pass  
✅ Full regression: 563 passed, 5 skipped, 0 failed  
✅ Safety boundary verified (22 safety tests pass across project)  
✅ No camera/streaming access  
✅ No identity/tracking dependencies  
✅ Memory bounded  
✅ Deterministic  
✅ Model-independent contracts  
✅ ORIGINAL_FRAME coordinates enforced  
✅ Provenance preserved  

## Verdict

**PHASE 10 = PASS**

Ready for Phase 11 — Person/Face Tracking.