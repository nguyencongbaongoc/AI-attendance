# Phase 16 — Adaptive Person/Face Crop Validation Report

**Timestamp:** 2026-08-20T20:52:55.507900

**Verdict:** PASS

**Tests:** 15/15 passed

**Source Resolution:** 3840×2160

**Model Input Resolution:** 640×640

## Test Results

- [PASS] **crop_contract** (0.1ms): Crop contract and provenance validated
- [PASS] **bbox_restoration** (0.2ms): Bbox restoration (Phase 9 formula) validated
- [PASS] **dynamic_person_crop** (135.0ms): Dynamic person crop from ORIGINAL_FRAME validated
- [PASS] **face_detection_input** (3.4ms): Face detection input coordinate restoration validated
- [PASS] **dynamic_face_crop** (131.7ms): Dynamic face crop from ORIGINAL_FRAME validated
- [PASS] **padding_behavior** (54.8ms): Padding behavior (pixels and ratio) validated
- [PASS] **small_face_handling** (52.5ms): Small face handling validated - crops preserved, not rejected
- [PASS] **boundary_cases** (64.7ms): All boundary cases handled correctly (no crash, valid clipped crops)
- [PASS] **multiple_people** (141.4ms): Multiple people receive independent dynamic crops
- [PASS] **4k_source_preservation** (140.2ms): 4K source preservation proven - crops come from ORIGINAL_FRAME, not 640x640 tensor
- [PASS] **determinism** (135.4ms): Deterministic behavior validated across repeated runs
- [PASS] **memory_safety** (464.4ms): Memory safety validated - no unbounded accumulation
- [PASS] **phase15_compatibility** (136.1ms): Phase 15 compatibility validated - output feeds pose/alignment/ArcFace
- [PASS] **negative_geometry** (58.4ms): All negative geometry cases rejected correctly
- [PASS] **safety_offline_only** (5.1ms): Safety verified - no camera/streaming/attendance code in adaptive_crop.py

## Key Validations

- **Crop Contract:** {'person_padding': {'pad_pixels': None, 'pad_ratio': 0.15}, 'face_padding': {'pad_pixels': None, 'pad_ratio': 0.2}, 'min_person_crop_width': 32, 'min_person_crop_height': 32, 'min_face_crop_width': 16, 'min_face_crop_height': 16, 'min_person_for_face_detection': 48}

- **BBox Restoration:** {'formula': 'bbox_original = (bbox_model - padding) / scale_factor', 'phase9_reused': True}

- **Dynamic Person Crop:** {'source': 'ORIGINAL_FRAME', 'padding': '15% ratio', 'dynamic_sizing': True}

- **Dynamic Face Crop:** {'source': 'ORIGINAL_FRAME', 'padding': '20% ratio', 'preferred_path': True}

- **Boundary Handling:** {'all_edges_tested': True, 'corners_tested': True, 'clipping_works': True}

- **4K Source Proof:** {'exact_pixel_match': True, 'no_640x640_tensor_used': True}

- **Provenance:** {'full_chain_tracked': True, 'serialization_works': True}

- **Determinism:** {'crop_deterministic': True, 'bbox_compute_deterministic': True}

- **Memory Safety:** {'bounded': True, 'no_accumulation': True, 'explicit_release': True}

- **Phase 15 Compatibility:** {'output_feeds_phase15': True, 'arcface_ready': True}

- **Negative Tests:** {'all_rejected': True, 'count': 7}

- **Safety:** {'offline_only': True, 'no_camera_access': True}

## Limitations

- Synthetic noise input - no accuracy claims on real data
- Face detection on person crop uses simulated coordinates
- Phase 15 integration tested conceptually, not end-to-end

## Readiness for Phase 17: True
