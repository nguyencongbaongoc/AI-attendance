#!/usr/bin/env python
"""
Phase 18 — Temporal Identity Evidence Validation.

This script validates the temporal identity evidence aggregation:
- IdentityEvidence contract with provenance
- IdentityHypothesis contract with state
- Time semantics (source_pts, capture_timestamp, monotonic_timestamp, processing_timestamp)
- Bounded evidence window (max_samples, max_duration, eviction)
- Quality-aware aggregation (GOOD > MARGINAL > UNUSABLE excluded)
- Candidate aggregation per identity
- Temporal consistency (A A A A vs A B A B)
- Ambiguity handling (CONFIDENT / SUPPORTED / AMBIGUOUS / INSUFFICIENT)
- Best evidence tracking (but not equated with final identity)
- Track isolation (camera_id + track_id partitioning)
- Duplicate evidence handling (idempotency)
- Out-of-order timestamp handling
- Track finalization (active, lost, finalized)
- Determinism (5 repeated identical runs)
- Negative cases (empty, all unusable, single marginal, conflicting candidates, etc.)
- Memory safety (bounded evidence, no accumulation)
- Phase 17 compatibility
- Offline-only safety

CRITICAL RULES:
- NO camera access
- NO MediaMTX, RTMP, RTSP, FFmpeg streaming
- NO real images - synthetic inputs only
- NO accuracy claims from synthetic noise
- 4K-ONLY: source resolution locked to 3840x2160
- ORIGINAL_FRAME is the source of truth
"""

from __future__ import annotations

import gc
import json
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.config.paths import get_project_paths
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat
from app.vision.adaptive_crop import (
    CropCoordinateSpace,
    CropProvenance,
    PaddingPolicy,
    AdaptiveCropContract,
    AdaptiveCropResult,
    DEFAULT_CROP_CONTRACT,
    DEFAULT_PERSON_PADDING,
    DEFAULT_FACE_PADDING,
    crop_person_from_frame,
    crop_face_from_frame,
    crop_multiple_persons,
)
from app.vision.face_quality import (
    QualityClass,
    MetricStatus,
    QualityMetric,
    QualityThresholds,
    DEFAULT_QUALITY_THRESHOLDS,
    FaceQualityResult,
    QualityProvenance,
    FaceQualityAssessor,
    create_quality_assessor,
)
from app.vision.hardpose_contract import PoseState
from app.vision.temporal_evidence import (
    TimestampSource,
    TemporalTimestamp,
    IdentityEvidence,
    HypothesisState,
    CandidateSupport,
    IdentityHypothesis,
    EvidenceWindowConfig,
    DEFAULT_WINDOW_CONFIG,
    TemporalEvidenceAggregator,
    create_temporal_aggregator,
)


# =============================================================================
# PHASE 18 CONTRACTS AND DATA STRUCTURES
# =============================================================================

@dataclass
class ValidationResult:
    """Result of a single validation test."""
    test_name: str
    passed: bool
    duration_ms: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class Phase18Report:
    """Complete Phase 18 validation report."""
    timestamp: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    results: List[Dict[str, Any]]
    verdict: str
    time_contract: Dict[str, Any]
    evidence_contract: Dict[str, Any]
    window_policy: Dict[str, Any]
    quality_weighting: Dict[str, Any]
    candidate_aggregation: Dict[str, Any]
    temporal_consistency: Dict[str, Any]
    ambiguity: Dict[str, Any]
    deduplication: Dict[str, Any]
    out_of_order_handling: Dict[str, Any]
    track_isolation: Dict[str, Any]
    determinism: Dict[str, Any]
    memory_safety: Dict[str, Any]
    phase17_compatibility: Dict[str, Any]
    offline_safety: Dict[str, Any]
    limitations: List[str]
    readiness_for_phase19: bool


# =============================================================================
# SYNTHETIC TEST DATA GENERATION
# =============================================================================

SYNTHETIC_SEED = 42

def create_synthetic_4k_image(seed: int = SYNTHETIC_SEED) -> np.ndarray:
    """Create a deterministic synthetic 4K image (3840x2160)."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(2160, 3840, 3), dtype=np.uint8)


def create_sharp_face_crop(width: int = 112, height: int = 112, seed: int = SYNTHETIC_SEED) -> np.ndarray:
    """Create a synthetic sharp face crop with high-frequency content."""
    rng = np.random.default_rng(seed)
    crop = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    crop[height//3:2*height//3, width//3:2*width//3] = [200, 180, 160]
    return crop


def create_blurry_face_crop(width: int = 112, height: int = 112, seed: int = SYNTHETIC_SEED) -> np.ndarray:
    """Create a synthetic blurry face crop (low frequency)."""
    rng = np.random.default_rng(seed)
    base = rng.integers(100, 150, size=(height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            val = int(100 + 50 * (x / width) * (y / height))
            base[y, x] = [val, val, val]
    return base


def create_adaptive_face_crop(
    frame: np.ndarray,
    face_bbox_original: Tuple[float, float, float, float],
    person_crop_id: str = "person_crop_001",
    person_detection_id: str = "person_det_001",
    person_detection_confidence: float = 0.95,
    face_detection_id: str = "face_det_001",
    face_detection_confidence: float = 0.88,
    face_bbox_person_crop: Tuple[float, float, float, float] = (0, 0, 0, 0),
    padding_policy: PaddingPolicy = DEFAULT_FACE_PADDING,
    person_bbox_original: Tuple[float, float, float, float] = (0, 0, 0, 0),
) -> AdaptiveCropResult:
    """Create an AdaptiveCropResult for a face crop with full provenance."""
    frame_h, frame_w = frame.shape[:2]
    
    crop_image, crop_bbox, (crop_w, crop_h) = crop_face_from_frame(
        frame=frame,
        face_bbox_in_original=face_bbox_original,
        frame_width=frame_w,
        frame_height=frame_h,
        padding_policy=padding_policy,
    )
    
    provenance = CropProvenance(
        source_type="image",
        source_id="4k_test.jpg",
        frame_index=0,
        timestamp=None,
        original_frame_width=frame_w,
        original_frame_height=frame_h,
        person_detection_id=person_detection_id,
        person_detection_confidence=person_detection_confidence,
        face_detection_id=face_detection_id,
        face_detection_confidence=face_detection_confidence,
        person_model_id="yolo_person",
        face_model_id="scrfd",
        face_bbox_original=face_bbox_original,
        face_bbox_person_crop=face_bbox_person_crop,
        person_bbox_original=person_bbox_original,
    )
    
    return AdaptiveCropResult(
        data=crop_image,
        bbox_in_original=crop_bbox,
        bbox_in_source=face_bbox_original,
        source_space=CropCoordinateSpace.ORIGINAL_FRAME,
        crop_width=crop_w,
        crop_height=crop_h,
        source_frame_width=frame_w,
        source_frame_height=frame_h,
        provenance=provenance,
    )


def create_face_quality_result(
    quality_class: QualityClass = QualityClass.GOOD,
    detection_confidence: float = 0.9,
    pose_state: PoseState = PoseState.NORMAL,
    face_bbox_original: Tuple[float, float, float, float] = (1800.0, 900.0, 2000.0, 1100.0),
    sharp: bool = True,
) -> FaceQualityResult:
    """Create a FaceQualityResult for testing."""
    assessor = create_quality_assessor()
    frame = create_synthetic_4k_image()
    face_crop = create_adaptive_face_crop(frame, face_bbox_original)
    
    if sharp:
        face_crop.data = create_sharp_face_crop()
    else:
        face_crop.data = create_blurry_face_crop()
    face_crop.crop_width = face_crop.data.shape[1]
    face_crop.crop_height = face_crop.data.shape[0]
    
    landmarks = [(30.0, 40.0), (80.0, 40.0), (55.0, 60.0), (40.0, 80.0), (70.0, 80.0)]
    
    return assessor.assess(
        face_crop=face_crop,
        detection_confidence=detection_confidence,
        pose_state=pose_state,
        landmarks_5pt=landmarks,
    )


def create_identity_evidence(
    identity_candidate: str = "person_A",
    similarity: float = 0.85,
    quality_class: QualityClass = QualityClass.GOOD,
    camera_id: str = "CAM1",
    track_id: str = "track_001",
    frame_id: str = "frame_001",
    timestamp_value: float = 1000.0,
    timestamp_source: TimestampSource = TimestampSource.CAPTURE_TIMESTAMP,
    evidence_id: Optional[str] = None,
) -> IdentityEvidence:
    """Create an IdentityEvidence for testing with explicit quality class."""
    # Create a minimal provenance for testing
    provenance = QualityProvenance(
        source_type="image",
        source_id="4k_test.jpg",
        frame_index=0,
        timestamp=None,
        original_frame_width=3840,
        original_frame_height=2160,
        person_crop_id="person_crop_001",
        person_detection_id="person_det_001",
        person_detection_confidence=0.95,
        person_bbox_original=(1800.0, 900.0, 2000.0, 1100.0),
        face_crop_id="face_crop_001",
        face_detection_id="face_det_001",
        face_detection_confidence=0.88,
        face_bbox_original=(1800.0, 900.0, 2000.0, 1100.0),
        face_bbox_person_crop=(0.0, 0.0, 112.0, 112.0),
        person_model_id="yolo_person",
        face_model_id="scrfd",
        quality_assessor_version="1.0",
        quality_id="qual_test",
        pose_state="NORMAL" if quality_class == QualityClass.GOOD else "HARD_POSE" if quality_class == QualityClass.MARGINAL else "INVALID",
        pose_yaw=10.0,
        pose_pitch=5.0,
        pose_roll=2.0,
    )
    
    # Create metrics reference based on quality class
    if quality_class == QualityClass.GOOD:
        metrics_ref = {
            "face_width": {"measurement": 134.0, "status": "passed"},
            "face_height": {"measurement": 134.0, "status": "passed"},
            "face_area": {"measurement": 17956.0, "status": "passed"},
            "inter_eye_distance": {"measurement": 50.0, "status": "passed"},
            "detection_confidence": {"measurement": 0.9, "status": "passed"},
            "sharpness": {"measurement": 500.0, "status": "passed"},
            "brightness": {"measurement": 128.0, "status": "passed"},
            "boundary_contact": {"measurement": 0.0, "status": "passed"},
            "occlusion": {"measurement": 0.0, "status": "not_available"},
            "pose": {"measurement": 0.0, "status": "passed"},
        }
    elif quality_class == QualityClass.MARGINAL:
        metrics_ref = {
            "face_width": {"measurement": 134.0, "status": "passed"},
            "face_height": {"measurement": 134.0, "status": "passed"},
            "face_area": {"measurement": 17956.0, "status": "passed"},
            "inter_eye_distance": {"measurement": 50.0, "status": "passed"},
            "detection_confidence": {"measurement": 0.9, "status": "passed"},
            "sharpness": {"measurement": 50.0, "status": "failed"},
            "brightness": {"measurement": 128.0, "status": "passed"},
            "boundary_contact": {"measurement": 0.0, "status": "passed"},
            "occlusion": {"measurement": 0.0, "status": "not_available"},
            "pose": {"measurement": 1.0, "status": "failed"},
        }
    else:  # UNUSABLE
        metrics_ref = {
            "face_width": {"measurement": 32.0, "status": "failed"},
            "face_height": {"measurement": 32.0, "status": "failed"},
            "face_area": {"measurement": 1024.0, "status": "failed"},
            "inter_eye_distance": {"measurement": 0.0, "status": "not_available"},
            "detection_confidence": {"measurement": 0.4, "status": "failed"},
            "sharpness": {"measurement": 10.0, "status": "failed"},
            "brightness": {"measurement": 10.0, "status": "failed"},
            "boundary_contact": {"measurement": 0.5, "status": "failed"},
            "occlusion": {"measurement": 0.0, "status": "not_available"},
            "pose": {"measurement": 999.0, "status": "failed"},
        }
    
    timestamp = TemporalTimestamp(value=timestamp_value, source=timestamp_source)
    
    # Generate deterministic evidence_id if not provided
    if evidence_id is None:
        # Use a deterministic hash based on the parameters
        import hashlib
        key = f"{identity_candidate}_{camera_id}_{track_id}_{frame_id}_{timestamp_value}_{quality_class.value}"
        # Use 16 characters from hash to virtually eliminate collision probability
        evidence_id = f"ev_{hashlib.md5(key.encode()).hexdigest()[:16]}"
    
    return IdentityEvidence(
        evidence_id=evidence_id,
        frame_id=frame_id,
        camera_id=camera_id,
        track_id=track_id,
        timestamp=timestamp,
        identity_candidate=identity_candidate,
        similarity=similarity,
        quality_class=quality_class,
        quality_metrics_ref=metrics_ref,
        pose_state=provenance.pose_state,
        provenance=provenance,
    )


# =============================================================================
# VALIDATION TESTS
# =============================================================================

def test_time_contract() -> ValidationResult:
    """Test 1: Time contract - timestamp semantics."""
    start_time = time.perf_counter()
    
    try:
        # Test TimestampSource enum
        assert TimestampSource.SOURCE_PTS.value == "source_pts"
        assert TimestampSource.CAPTURE_TIMESTAMP.value == "capture_timestamp"
        assert TimestampSource.MONOTONIC_TIMESTAMP.value == "monotonic_timestamp"
        assert TimestampSource.PROCESSING_TIMESTAMP.value == "processing_timestamp"
        assert TimestampSource.NOT_AVAILABLE.value == "not_available"
        
        # Test TemporalTimestamp
        ts1 = TemporalTimestamp(value=1000.0, source=TimestampSource.CAPTURE_TIMESTAMP)
        ts2 = TemporalTimestamp(value=2000.0, source=TimestampSource.SOURCE_PTS)
        ts_na = TemporalTimestamp.not_available()
        
        assert ts1 < ts2
        assert ts_na.value == 0.0
        assert ts_na.source == TimestampSource.NOT_AVAILABLE
        
        # Test serialization
        ts_dict = ts1.to_dict()
        assert ts_dict["value"] == 1000.0
        assert ts_dict["source"] == "capture_timestamp"
        
        ts_restored = TemporalTimestamp.from_dict(ts_dict)
        assert ts_restored.value == 1000.0
        assert ts_restored.source == TimestampSource.CAPTURE_TIMESTAMP
        
        # Test ordering preference: source/capture > processing
        capture_ts = TemporalTimestamp(value=1000.0, source=TimestampSource.CAPTURE_TIMESTAMP)
        processing_ts = TemporalTimestamp(value=900.0, source=TimestampSource.PROCESSING_TIMESTAMP)
        # Capture time (1000) > processing time (900) for temporal ordering
        assert capture_ts > processing_ts
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="time_contract",
            passed=True,
            duration_ms=duration_ms,
            message="Time contract validated",
            details={
                "timestamp_sources": "validated",
                "temporal_timestamp": "validated",
                "serialization": "validated",
                "ordering_preference": "validated",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="time_contract",
            passed=False,
            duration_ms=duration_ms,
            message="Time contract test failed",
            error=str(e),
        )


def test_evidence_contract() -> ValidationResult:
    """Test 2: IdentityEvidence contract with provenance."""
    start_time = time.perf_counter()
    
    try:
        # Create evidence
        evidence = create_identity_evidence(
            identity_candidate="person_A",
            similarity=0.85,
            quality_class=QualityClass.GOOD,
            camera_id="CAM1",
            track_id="track_001",
        )
        
        # Test fields
        assert evidence.evidence_id.startswith("ev_")
        assert evidence.frame_id == "frame_001"
        assert evidence.camera_id == "CAM1"
        assert evidence.track_id == "track_001"
        assert evidence.identity_candidate == "person_A"
        assert evidence.similarity == 0.85
        assert evidence.quality_class == QualityClass.GOOD
        assert evidence.is_eligible is True
        assert evidence.is_marginal is False
        assert evidence.is_unusable is False
        assert evidence.provenance is not None
        
        # Test provenance chain
        prov = evidence.provenance
        assert prov.source_type == "image"
        assert prov.original_frame_width == 3840
        assert prov.original_frame_height == 2160
        assert prov.person_detection_id == "person_det_001"
        assert prov.face_detection_id == "face_det_001"
        
        # Test serialization
        ev_dict = evidence.to_dict()
        assert ev_dict["evidence_id"] == evidence.evidence_id
        assert ev_dict["quality_class"] == "good"
        assert ev_dict["provenance"] is not None
        
        # Test MARGINAL evidence
        marginal_ev = create_identity_evidence(quality_class=QualityClass.MARGINAL)
        assert marginal_ev.is_eligible is False
        assert marginal_ev.is_marginal is True
        
        # Test UNUSABLE evidence
        unusable_ev = create_identity_evidence(quality_class=QualityClass.UNUSABLE)
        assert unusable_ev.is_eligible is False
        assert unusable_ev.is_unusable is True
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="evidence_contract",
            passed=True,
            duration_ms=duration_ms,
            message="IdentityEvidence contract validated",
            details={
                "fields": "validated",
                "provenance_chain": "validated",
                "serialization": "validated",
                "quality_properties": "validated",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="evidence_contract",
            passed=False,
            duration_ms=duration_ms,
            message="IdentityEvidence contract test failed",
            error=str(e),
        )


def test_hypothesis_contract() -> ValidationResult:
    """Test 3: IdentityHypothesis contract with state."""
    start_time = time.perf_counter()
    
    try:
        # Test HypothesisState enum
        assert HypothesisState.CONFIDENT.value == "confident"
        assert HypothesisState.SUPPORTED.value == "supported"
        assert HypothesisState.AMBIGUOUS.value == "ambiguous"
        assert HypothesisState.INSUFFICIENT.value == "insufficient"
        
        # Create hypothesis
        hyp = IdentityHypothesis(
            camera_id="CAM1",
            track_id="track_001",
            candidate_identity="person_A",
            evidence_count=10,
            eligible_evidence_count=8,
            weighted_score=8.0,
            best_similarity=0.9,
            temporal_span=5.0,
            state=HypothesisState.CONFIDENT,
            ambiguity_margin=0.5,
            best_evidence_id="ev_123",
            best_evidence_similarity=0.9,
            best_evidence_quality=QualityClass.GOOD,
            config_snapshot=DEFAULT_WINDOW_CONFIG.to_dict(),
        )
        
        assert hyp.hypothesis_id.startswith("hyp_")
        assert hyp.camera_id == "CAM1"
        assert hyp.track_id == "track_001"
        assert hyp.candidate_identity == "person_A"
        assert hyp.is_confident is True
        assert hyp.is_supported is False
        assert hyp.is_ambiguous is False
        assert hyp.is_insufficient is False
        
        # Test serialization
        hyp_dict = hyp.to_dict()
        assert hyp_dict["state"] == "confident"
        assert hyp_dict["candidate_identity"] == "person_A"
        assert hyp_dict["config_snapshot"]["max_samples"] == 100
        
        # Test CandidateSupport
        ts = TemporalTimestamp(value=1000.0, source=TimestampSource.CAPTURE_TIMESTAMP)
        support = CandidateSupport(
            candidate_id="person_A",
            evidence_count=10,
            eligible_evidence_count=8,
            marginal_evidence_count=2,
            weighted_score=8.6,
            best_similarity=0.9,
            temporal_span=5.0,
            first_timestamp=ts,
            last_timestamp=ts,
            supporting_evidence_ids=["ev_1", "ev_2"],
        )
        
        support_dict = support.to_dict()
        assert support_dict["candidate_id"] == "person_A"
        assert support_dict["weighted_score"] == 8.6
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="hypothesis_contract",
            passed=True,
            duration_ms=duration_ms,
            message="IdentityHypothesis contract validated",
            details={
                "states": "validated",
                "fields": "validated",
                "serialization": "validated",
                "candidate_support": "validated",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="hypothesis_contract",
            passed=False,
            duration_ms=duration_ms,
            message="IdentityHypothesis contract test failed",
            error=str(e),
        )


def test_evidence_window_bounds() -> ValidationResult:
    """Test 4: Bounded evidence window (max_samples, max_duration, eviction)."""
    start_time = time.perf_counter()
    
    try:
        config = EvidenceWindowConfig(
            max_samples=5,
            max_duration=10.0,
            good_weight=1.0,
            marginal_weight=0.3,
        )
        aggregator = create_temporal_aggregator(config)
        
        # Add evidence up to max_samples
        for i in range(7):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        # Window should only keep max_samples (5)
        window_size = aggregator.get_window_size("CAM1", "track_001")
        assert window_size == 5, f"Expected 5, got {window_size}"
        
        # Test max_duration eviction
        config2 = EvidenceWindowConfig(
            max_samples=100,
            max_duration=5.0,
        )
        aggregator2 = create_temporal_aggregator(config2)
        
        # Add evidence spanning 20 seconds
        for i in range(10):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i * 2.0,  # 2 seconds apart
            )
            aggregator2.add_evidence(ev)
        
        # Only last 5 seconds should remain (latest at 1018, cutoff at 1013)
        window_size2 = aggregator2.get_window_size("CAM1", "track_001")
        assert window_size2 <= 5, f"Expected <=5, got {window_size2}"
        
        # Test finalization clears window
        hyp = aggregator.finalize_track("CAM1", "track_001")
        assert hyp.camera_id == "CAM1"
        assert hyp.track_id == "track_001"
        assert aggregator.get_window_size("CAM1", "track_001") == 0
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="evidence_window_bounds",
            passed=True,
            duration_ms=duration_ms,
            message="Bounded evidence window validated",
            details={
                "max_samples_enforced": True,
                "max_duration_enforced": True,
                "finalization_clears": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="evidence_window_bounds",
            passed=False,
            duration_ms=duration_ms,
            message="Evidence window bounds test failed",
            error=str(e),
        )


def test_quality_aware_aggregation() -> ValidationResult:
    """Test 5: Quality-aware aggregation (GOOD > MARGINAL > UNUSABLE excluded)."""
    start_time = time.perf_counter()
    
    try:
        config = EvidenceWindowConfig(
            max_samples=100,
            max_duration=30.0,
            good_weight=1.0,
            marginal_weight=0.3,
            unusable_weight=0.0,
        )
        aggregator = create_temporal_aggregator(config)
        
        # Add GOOD evidence
        for i in range(3):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
                quality_class=QualityClass.GOOD,
                similarity=0.85 + i * 0.02,
            )
            aggregator.add_evidence(ev)
        
        # Add MARGINAL evidence
        for i in range(2):
            ev = create_identity_evidence(
                frame_id=f"frame_m_{i}",
                timestamp_value=1003.0 + i,
                quality_class=QualityClass.MARGINAL,
                similarity=0.75,
            )
            aggregator.add_evidence(ev)
        
        # Add UNUSABLE evidence (should be excluded from weighted score)
        for i in range(2):
            ev = create_identity_evidence(
                frame_id=f"frame_u_{i}",
                timestamp_value=1005.0 + i,
                quality_class=QualityClass.UNUSABLE,
                similarity=0.60,
            )
            aggregator.add_evidence(ev)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        
        # Weighted score: 3 * 1.0 + 2 * 0.3 + 2 * 0.0 = 3.6
        assert hyp.weighted_score == 3.6, f"Expected 3.6, got {hyp.weighted_score}"
        assert hyp.eligible_evidence_count == 3
        assert hyp.evidence_count == 7
        
        # UNUSABLE should not contribute to weighted score
        # Best similarity should come from eligible (GOOD) evidence
        assert hyp.best_similarity >= 0.85
        
        # Test with custom weights
        config2 = EvidenceWindowConfig(
            good_weight=2.0,
            marginal_weight=0.5,
        )
        aggregator2 = create_temporal_aggregator(config2)
        
        for i in range(2):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
                quality_class=QualityClass.GOOD,
            )
            aggregator2.add_evidence(ev)
        
        ev = create_identity_evidence(
            frame_id="frame_m",
            timestamp_value=1002.0,
            quality_class=QualityClass.MARGINAL,
        )
        aggregator2.add_evidence(ev)
        
        hyp2 = aggregator2.compute_hypothesis("CAM1", "track_001")
        assert hyp2.weighted_score == 2 * 2.0 + 1 * 0.5 == 4.5
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="quality_aware_aggregation",
            passed=True,
            duration_ms=duration_ms,
            message="Quality-aware aggregation validated",
            details={
                "good_weight": True,
                "marginal_weight": True,
                "unusable_excluded": True,
                "custom_weights": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="quality_aware_aggregation",
            passed=False,
            duration_ms=duration_ms,
            message="Quality-aware aggregation test failed",
            error=str(e),
        )


def test_candidate_aggregation() -> ValidationResult:
    """Test 6: Candidate aggregation per identity."""
    start_time = time.perf_counter()
    
    try:
        aggregator = create_temporal_aggregator()
        
        # Add evidence for person_A
        for i in range(4):
            ev = create_identity_evidence(
                identity_candidate="person_A",
                frame_id=f"frame_A_{i}",
                timestamp_value=1000.0 + i,
                similarity=0.80 + i * 0.02,
            )
            aggregator.add_evidence(ev)
        
        # Add evidence for person_B
        for i in range(2):
            ev = create_identity_evidence(
                identity_candidate="person_B",
                frame_id=f"frame_B_{i}",
                timestamp_value=1004.0 + i,
                similarity=0.75,
            )
            aggregator.add_evidence(ev)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        
        # person_A should be primary (more evidence, higher weighted score)
        assert hyp.candidate_identity == "person_A"
        assert len(hyp.all_candidates) == 2
        assert hyp.all_candidates[0].candidate_id == "person_A"
        assert hyp.all_candidates[1].candidate_id == "person_B"
        
        # person_A: 4 GOOD = 4.0 weighted score
        # person_B: 2 GOOD = 2.0 weighted score
        assert hyp.all_candidates[0].weighted_score == 4.0
        assert hyp.all_candidates[1].weighted_score == 2.0
        
        # Test competing candidates
        assert len(hyp.competing_candidates) == 1
        assert hyp.competing_candidates[0].candidate_id == "person_B"
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="candidate_aggregation",
            passed=True,
            duration_ms=duration_ms,
            message="Candidate aggregation validated",
            details={
                "primary_candidate": "person_A",
                "competing_candidate": "person_B",
                "weighted_scores": "validated",
                "all_candidates_tracked": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="candidate_aggregation",
            passed=False,
            duration_ms=duration_ms,
            message="Candidate aggregation test failed",
            error=str(e),
        )


def test_temporal_consistency() -> ValidationResult:
    """Test 7: Temporal consistency (A A A A vs A B A B)."""
    start_time = time.perf_counter()
    
    try:
        # Test stable candidate: A A A A
        aggregator = create_temporal_aggregator()
        for i in range(4):
            ev = create_identity_evidence(
                identity_candidate="person_A",
                frame_id=f"frame_stable_{i}",
                timestamp_value=1000.0 + i,
                similarity=0.85,
            )
            aggregator.add_evidence(ev)
        
        hyp_stable = aggregator.compute_hypothesis("CAM1", "track_001")
        print(f"DEBUG stable: weighted_score={hyp_stable.all_candidates[0].weighted_score}, state={hyp_stable.state}, eligible={hyp_stable.eligible_evidence_count}")
        
        # Clear and test oscillating: A B A B
        # Use config with min_eligible_evidence=2 to allow AMBIGUOUS with 2 evidence per candidate
        config = EvidenceWindowConfig(min_eligible_evidence=2, ambiguity_margin=0.15)
        aggregator2 = create_temporal_aggregator(config)
        candidates = ["person_A", "person_B", "person_A", "person_B"]
        for i, cand in enumerate(candidates):
            ev = create_identity_evidence(
                identity_candidate=cand,
                frame_id=f"frame_osc_{i}",
                timestamp_value=1000.0 + i,
                similarity=0.85,
            )
            aggregator2.add_evidence(ev)
        
        hyp_oscillating = aggregator2.compute_hypothesis("CAM1", "track_001")
        print(f"DEBUG oscillating: primary_score={hyp_oscillating.all_candidates[0].weighted_score}, runner_up_score={hyp_oscillating.all_candidates[1].weighted_score}, state={hyp_oscillating.state}, margin={hyp_oscillating.ambiguity_margin}")
        
        # Stable should have higher weighted score for primary
        assert hyp_stable.all_candidates[0].weighted_score == 4.0, f"Expected 4.0, got {hyp_stable.all_candidates[0].weighted_score}"
        # Oscillating: each candidate has 2 evidence
        assert hyp_oscillating.all_candidates[0].weighted_score == 2.0, f"Expected 2.0, got {hyp_oscillating.all_candidates[0].weighted_score}"
        assert hyp_oscillating.all_candidates[1].weighted_score == 2.0, f"Expected 2.0, got {hyp_oscillating.all_candidates[1].weighted_score}"
        
        # Oscillating should be AMBIGUOUS (equal scores, margin < 0.15)
        assert hyp_oscillating.state == HypothesisState.AMBIGUOUS, f"Expected AMBIGUOUS, got {hyp_oscillating.state}"
        assert hyp_oscillating.ambiguity_margin < 0.15, f"Expected margin < 0.15, got {hyp_oscillating.ambiguity_margin}"
        
        # Stable with enough evidence should be CONFIDENT or SUPPORTED
        assert hyp_stable.state in (HypothesisState.CONFIDENT, HypothesisState.SUPPORTED), f"Expected CONFIDENT or SUPPORTED, got {hyp_stable.state}"
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="temporal_consistency",
            passed=True,
            duration_ms=duration_ms,
            message="Temporal consistency validated",
            details={
                "stable_candidate": "higher_score",
                "oscillating_candidates": "ambiguous",
                "ambiguity_margin": "validated",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        import traceback
        return ValidationResult(
            test_name="temporal_consistency",
            passed=False,
            duration_ms=duration_ms,
            message="Temporal consistency test failed",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        )


def test_ambiguity_handling() -> ValidationResult:
    """Test 8: Ambiguity handling (CONFIDENT / SUPPORTED / AMBIGUOUS / INSUFFICIENT)."""
    start_time = time.perf_counter()
    
    try:
        # Test INSUFFICIENT: no evidence
        aggregator = create_temporal_aggregator()
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.INSUFFICIENT
        
        # Test INSUFFICIENT: only UNUSABLE evidence
        aggregator.clear_all()
        for i in range(5):
            ev = create_identity_evidence(
                quality_class=QualityClass.UNUSABLE,
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.INSUFFICIENT
        assert hyp.eligible_evidence_count == 0
        
        # Test INSUFFICIENT: single MARGINAL
        aggregator.clear_all()
        ev = create_identity_evidence(
            quality_class=QualityClass.MARGINAL,
            frame_id="frame_0",
            timestamp_value=1000.0,
        )
        aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.INSUFFICIENT
        assert hyp.eligible_evidence_count == 0
        
        # Test SUPPORTED: 3 GOOD (min_eligible=3, min_confident=5)
        aggregator.clear_all()
        for i in range(3):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.SUPPORTED
        assert hyp.eligible_evidence_count == 3
        
        # Test CONFIDENT: 5 GOOD
        aggregator.clear_all()
        for i in range(5):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.CONFIDENT
        assert hyp.eligible_evidence_count == 5
        
        # Test AMBIGUOUS: two candidates with close scores
        aggregator.clear_all()
        config = EvidenceWindowConfig(ambiguity_margin=0.5)
        aggregator2 = create_temporal_aggregator(config)
        
        for i in range(3):
            ev = create_identity_evidence(
                identity_candidate="person_A",
                frame_id=f"frame_A_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator2.add_evidence(ev)
        for i in range(3):
            ev = create_identity_evidence(
                identity_candidate="person_B",
                frame_id=f"frame_B_{i}",
                timestamp_value=1003.0 + i,
            )
            aggregator2.add_evidence(ev)
        
        hyp = aggregator2.compute_hypothesis("CAM1", "track_001")
        # Both have 3.0 weighted score, margin = 0 < 0.5 -> AMBIGUOUS
        assert hyp.state == HypothesisState.AMBIGUOUS
        assert hyp.ambiguity_margin == 0.0
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="ambiguity_handling",
            passed=True,
            duration_ms=duration_ms,
            message="Ambiguity handling validated",
            details={
                "insufficient_empty": True,
                "insufficient_unusable": True,
                "insufficient_marginal": True,
                "supported": True,
                "confident": True,
                "ambiguous": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="ambiguity_handling",
            passed=False,
            duration_ms=duration_ms,
            message="Ambiguity handling test failed",
            error=str(e),
        )


def test_best_evidence_tracking() -> ValidationResult:
    """Test 9: Best evidence tracking (but not equated with final identity)."""
    start_time = time.perf_counter()
    
    try:
        aggregator = create_temporal_aggregator()
        
        # Add evidence with varying similarities
        similarities = [0.70, 0.85, 0.75, 0.90, 0.80]
        for i, sim in enumerate(similarities):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
                similarity=sim,
            )
            aggregator.add_evidence(ev)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        
        # Best evidence should be tracked
        assert hyp.best_evidence_id is not None
        assert hyp.best_evidence_similarity == 0.90  # Max similarity
        assert hyp.best_evidence_quality == QualityClass.GOOD
        
        # But hypothesis is not just the best sample
        # Weighted score considers all eligible evidence
        assert hyp.weighted_score == 5.0  # 5 GOOD * 1.0
        assert hyp.eligible_evidence_count == 5
        
        # Best sample != final identity (hypothesis has state, ambiguity, etc.)
        assert hyp.state != HypothesisState.INSUFFICIENT
        assert hasattr(hyp, 'ambiguity_margin')
        assert hasattr(hyp, 'competing_candidates')
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="best_evidence_tracking",
            passed=True,
            duration_ms=duration_ms,
            message="Best evidence tracking validated",
            details={
                "best_evidence_id": "tracked",
                "best_similarity": "tracked",
                "best_quality": "tracked",
                "not_equated_with_identity": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="best_evidence_tracking",
            passed=False,
            duration_ms=duration_ms,
            message="Best evidence tracking test failed",
            error=str(e),
        )


def test_track_isolation() -> ValidationResult:
    """Test 10: Track isolation (camera_id + track_id partitioning)."""
    start_time = time.perf_counter()
    
    try:
        aggregator = create_temporal_aggregator()
        
        # Add evidence for CAM1/track_001
        for i in range(3):
            ev = create_identity_evidence(
                camera_id="CAM1",
                track_id="track_001",
                frame_id=f"frame_1_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        # Add evidence for CAM1/track_002 (different track, same camera)
        for i in range(2):
            ev = create_identity_evidence(
                camera_id="CAM1",
                track_id="track_002",
                frame_id=f"frame_2_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        # Add evidence for CAM2/track_001 (different camera, same track id)
        for i in range(4):
            ev = create_identity_evidence(
                camera_id="CAM2",
                track_id="track_001",
                frame_id=f"frame_3_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        # Each should have independent windows
        assert aggregator.get_window_size("CAM1", "track_001") == 3
        assert aggregator.get_window_size("CAM1", "track_002") == 2
        assert aggregator.get_window_size("CAM2", "track_001") == 4
        
        # Hypotheses should be independent
        hyp1 = aggregator.compute_hypothesis("CAM1", "track_001")
        hyp2 = aggregator.compute_hypothesis("CAM1", "track_002")
        hyp3 = aggregator.compute_hypothesis("CAM2", "track_001")
        
        assert hyp1.evidence_count == 3
        assert hyp2.evidence_count == 2
        assert hyp3.evidence_count == 4
        
        # Finalizing one track shouldn't affect others
        aggregator.finalize_track("CAM1", "track_001")
        assert aggregator.get_window_size("CAM1", "track_001") == 0
        assert aggregator.get_window_size("CAM1", "track_002") == 2
        assert aggregator.get_window_size("CAM2", "track_001") == 4
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="track_isolation",
            passed=True,
            duration_ms=duration_ms,
            message="Track isolation validated",
            details={
                "same_camera_different_tracks": "isolated",
                "different_camera_same_track_id": "isolated",
                "finalization_independent": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="track_isolation",
            passed=False,
            duration_ms=duration_ms,
            message="Track isolation test failed",
            error=str(e),
        )


def test_duplicate_evidence() -> ValidationResult:
    """Test 11: Duplicate evidence handling (idempotency)."""
    start_time = time.perf_counter()
    
    try:
        config = EvidenceWindowConfig(reject_duplicates=True)
        aggregator = create_temporal_aggregator(config)
        
        # Create evidence with specific ID
        ev = create_identity_evidence(
            frame_id="frame_0",
            timestamp_value=1000.0,
        )
        original_id = ev.evidence_id
        
        # Add first time
        result1 = aggregator.add_evidence(ev)
        assert result1 is True
        assert aggregator.get_window_size("CAM1", "track_001") == 1
        
        # Try to add same evidence again (same evidence_id)
        # Need to create new evidence with same ID - but evidence_id is auto-generated
        # So we test by adding the exact same object
        result2 = aggregator.add_evidence(ev)
        assert result2 is False  # Should be rejected
        assert aggregator.get_window_size("CAM1", "track_001") == 1
        
        # Test with reject_duplicates=False
        config2 = EvidenceWindowConfig(reject_duplicates=False)
        aggregator2 = create_temporal_aggregator(config2)
        
        result3 = aggregator2.add_evidence(ev)
        assert result3 is True
        result4 = aggregator2.add_evidence(ev)
        assert result4 is True  # Should be accepted
        assert aggregator2.get_window_size("CAM1", "track_001") == 2
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="duplicate_evidence",
            passed=True,
            duration_ms=duration_ms,
            message="Duplicate evidence handling validated",
            details={
                "reject_duplicates_true": "rejected",
                "reject_duplicates_false": "accepted",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="duplicate_evidence",
            passed=False,
            duration_ms=duration_ms,
            message="Duplicate evidence test failed",
            error=str(e),
        )


def test_out_of_order_timestamps() -> ValidationResult:
    """Test 12: Out-of-order timestamp handling."""
    start_time = time.perf_counter()
    
    try:
        # Test "sort" policy (default)
        config = EvidenceWindowConfig(out_of_order_policy="sort")
        aggregator = create_temporal_aggregator(config)
        
        # Add in order: t1, t3, t2
        ev1 = create_identity_evidence(frame_id="f1", timestamp_value=1000.0)
        ev3 = create_identity_evidence(frame_id="f3", timestamp_value=1002.0)
        ev2 = create_identity_evidence(frame_id="f2", timestamp_value=1001.0)
        
        aggregator.add_evidence(ev1)
        aggregator.add_evidence(ev3)
        aggregator.add_evidence(ev2)
        
        # Window should be sorted by timestamp
        window = aggregator._evidence_windows[("CAM1", "track_001")]
        timestamps = [ev.timestamp.value for ev in window]
        assert timestamps == [1000.0, 1001.0, 1002.0], f"Got {timestamps}"
        
        # Test "reject" policy
        config2 = EvidenceWindowConfig(out_of_order_policy="reject")
        aggregator2 = create_temporal_aggregator(config2)
        
        aggregator2.add_evidence(ev1)
        aggregator2.add_evidence(ev3)  # t=1002
        result = aggregator2.add_evidence(ev2)  # t=1001, older than last (1002)
        assert result is False  # Should be rejected
        assert aggregator2.get_window_size("CAM1", "track_001") == 2
        
        # Test "accept" policy
        config3 = EvidenceWindowConfig(out_of_order_policy="accept")
        aggregator3 = create_temporal_aggregator(config3)
        
        aggregator3.add_evidence(ev1)
        aggregator3.add_evidence(ev3)
        aggregator3.add_evidence(ev2)
        
        window3 = aggregator3._evidence_windows[("CAM1", "track_001")]
        timestamps3 = [ev.timestamp.value for ev in window3]
        assert timestamps3 == [1000.0, 1002.0, 1001.0]  # Arrival order preserved
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="out_of_order_timestamps",
            passed=True,
            duration_ms=duration_ms,
            message="Out-of-order timestamp handling validated",
            details={
                "sort_policy": "sorted",
                "reject_policy": "rejected",
                "accept_policy": "arrival_order",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="out_of_order_timestamps",
            passed=False,
            duration_ms=duration_ms,
            message="Out-of-order timestamps test failed",
            error=str(e),
        )


def test_track_finalization() -> ValidationResult:
    """Test 13: Track finalization (active, lost, finalized)."""
    start_time = time.perf_counter()
    
    try:
        aggregator = create_temporal_aggregator()
        
        # Active track: add evidence
        for i in range(5):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        # Compute hypothesis while active
        hyp_active = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp_active.evidence_count == 5
        assert hyp_active.state in (HypothesisState.SUPPORTED, HypothesisState.CONFIDENT)
        
        # Track lost: finalize
        hyp_final = aggregator.finalize_track("CAM1", "track_001")
        assert hyp_final.evidence_count == 5
        assert hyp_final.camera_id == "CAM1"
        assert hyp_final.track_id == "track_001"
        
        # Window should be cleared
        assert aggregator.get_window_size("CAM1", "track_001") == 0
        
        # Computing hypothesis after finalization returns INSUFFICIENT
        hyp_after = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp_after.state == HypothesisState.INSUFFICIENT
        assert hyp_after.evidence_count == 0
        
        # Track reconnect: new track_id should be independent
        for i in range(3):
            ev = create_identity_evidence(
                track_id="track_001_reconnect",
                frame_id=f"frame_r_{i}",
                timestamp_value=2000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        hyp_reconnect = aggregator.compute_hypothesis("CAM1", "track_001_reconnect")
        assert hyp_reconnect.evidence_count == 3
        # Old track should not be merged
        assert aggregator.get_window_size("CAM1", "track_001") == 0
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="track_finalization",
            passed=True,
            duration_ms=duration_ms,
            message="Track finalization validated",
            details={
                "active_track": "hypothesis_computed",
                "finalized_track": "window_cleared",
                "post_finalization": "insufficient",
                "reconnect_independent": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="track_finalization",
            passed=False,
            duration_ms=duration_ms,
            message="Track finalization test failed",
            error=str(e),
        )


def test_determinism() -> ValidationResult:
    """Test 14: Determinism (5 repeated identical runs)."""
    start_time = time.perf_counter()
    
    try:
        def run_aggregation():
            config = EvidenceWindowConfig(
                max_samples=100,
                max_duration=30.0,
                good_weight=1.0,
                marginal_weight=0.3,
                ambiguity_margin=0.15,
            )
            aggregator = create_temporal_aggregator(config)
            
            # Add identical evidence sequence
            for i in range(10):
                ev = create_identity_evidence(
                    identity_candidate="person_A" if i < 7 else "person_B",
                    frame_id=f"frame_{i}",
                    timestamp_value=1000.0 + i,
                    similarity=0.85 if i < 7 else 0.75,
                )
                result = aggregator.add_evidence(ev)
                print(f"DEBUG add_evidence i={i}: result={result}, evidence_id={ev.evidence_id}, quality={ev.quality_class}")
            
            # Debug: check window contents
            window = aggregator._evidence_windows.get(("CAM1", "track_001"), [])
            print(f"DEBUG window size: {len(window)}")
            for ev in window:
                print(f"  ev: id={ev.evidence_id}, candidate={ev.identity_candidate}, quality={ev.quality_class}, eligible={ev.is_eligible}")
            
            hyp = aggregator.compute_hypothesis("CAM1", "track_001")
            return hyp.to_dict()
        
        # Run 5 times
        results = [run_aggregation() for _ in range(5)]
        
        # Debug: print differences
        first = results[0]
        print(f"DEBUG first run: weighted_score={first.get('weighted_score')}, eligible={first.get('eligible_evidence_count')}, state={first.get('state')}")
        for i, r in enumerate(results[1:], 1):
            if r != first:
                print(f"DEBUG: Run {i} differs from run 0")
                for key in first:
                    if first[key] != r[key]:
                        print(f"  {key}: run0={first[key]}, run{i}={r[key]}")
                break
        
        # All should be identical
        first = results[0]
        for i, r in enumerate(results[1:], 1):
            assert r == first, f"Run {i} differs from run 0"
        
        # Verify key fields
        assert first["candidate_identity"] == "person_A"
        assert first["state"] in ("confident", "supported")
        # Primary candidate (person_A) has 7 GOOD evidence = 7.0 weighted_score
        # person_B has 3 GOOD evidence = 3.0 weighted_score
        # Hypothesis weighted_score is primary candidate's score = 7.0
        # Hypothesis eligible_evidence_count is primary candidate's eligible count = 7
        print(f"DEBUG: weighted_score={first['weighted_score']}, eligible={first['eligible_evidence_count']}")
        assert first["weighted_score"] == 7.0
        assert first["eligible_evidence_count"] == 7
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="determinism",
            passed=True,
            duration_ms=duration_ms,
            message="Determinism validated (5 identical runs)",
            details={
                "runs": 5,
                "identical_results": True,
                "candidate_identity": first["candidate_identity"],
                "state": first["state"],
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        import traceback
        return ValidationResult(
            test_name="determinism",
            passed=False,
            duration_ms=duration_ms,
            message="Determinism test failed",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        )

def test_negative_cases() -> ValidationResult:
    """Test 15: Negative cases."""
    start_time = time.perf_counter()
    
    try:
        aggregator = create_temporal_aggregator()
        
        # 1. Empty evidence
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.INSUFFICIENT
        assert hyp.evidence_count == 0
        
        # 2. All UNUSABLE
        aggregator.clear_all()
        for i in range(5):
            ev = create_identity_evidence(
                quality_class=QualityClass.UNUSABLE,
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.INSUFFICIENT
        assert hyp.eligible_evidence_count == 0
        assert hyp.weighted_score == 0.0
        
        # 3. Single MARGINAL
        aggregator.clear_all()
        ev = create_identity_evidence(
            quality_class=QualityClass.MARGINAL,
            frame_id="frame_0",
            timestamp_value=1000.0,
        )
        aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.INSUFFICIENT
        assert hyp.eligible_evidence_count == 0
        # When there's only MARGINAL evidence, there are no candidates with eligible evidence
        # So all_candidates might be empty or have 0 eligible
        if len(hyp.all_candidates) > 0:
            assert hyp.all_candidates[0].marginal_evidence_count == 1
        
        # 4. Conflicting candidates (A B A B)
        # Use config with min_eligible_evidence=2 to allow AMBIGUOUS with 2 evidence per candidate
        config = EvidenceWindowConfig(min_eligible_evidence=2, ambiguity_margin=0.15)
        aggregator2 = create_temporal_aggregator(config)
        for i, cand in enumerate(["person_A", "person_B", "person_A", "person_B"]):
            ev = create_identity_evidence(
                identity_candidate=cand,
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator2.add_evidence(ev)
        hyp = aggregator2.compute_hypothesis("CAM1", "track_001")
        assert hyp.state == HypothesisState.AMBIGUOUS
        assert len(hyp.all_candidates) == 2
        
        # 5. Duplicate evidence
        aggregator.clear_all()
        ev = create_identity_evidence(frame_id="frame_0", timestamp_value=1000.0)
        aggregator.add_evidence(ev)
        result = aggregator.add_evidence(ev)  # Same object
        assert result is False
        
        # 6. Out-of-order timestamps (reject policy)
        config = EvidenceWindowConfig(out_of_order_policy="reject")
        aggregator2 = create_temporal_aggregator(config)
        ev1 = create_identity_evidence(frame_id="f1", timestamp_value=1000.0)
        ev2 = create_identity_evidence(frame_id="f2", timestamp_value=1002.0)
        ev3 = create_identity_evidence(frame_id="f3", timestamp_value=1001.0)
        aggregator2.add_evidence(ev1)
        aggregator2.add_evidence(ev2)
        result = aggregator2.add_evidence(ev3)
        assert result is False
        
        # 7. Missing timestamp (NOT_AVAILABLE)
        aggregator.clear_all()
        ev = create_identity_evidence(
            frame_id="frame_0",
            timestamp_value=0.0,
            timestamp_source=TimestampSource.NOT_AVAILABLE,
        )
        aggregator.add_evidence(ev)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.temporal_span == 0.0
        
        # 8. Invalid similarity (constructor validation)
        aggregator.clear_all()
        try:
            ev = create_identity_evidence(similarity=1.5)  # Invalid
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # Expected
        
        try:
            ev = create_identity_evidence(similarity=-0.1)  # Invalid
            assert False, "Should have raised ValueError"
        except ValueError:
            pass  # Expected
        
        # Test that add_evidence also validates (for valid evidence objects)
        aggregator.clear_all()
        ev = create_identity_evidence(similarity=0.5)  # Valid
        result = aggregator.add_evidence(ev)
        assert result is True
        
        # Test that add_evidence rejects invalid similarity (if we could create such evidence)
        # This is tested by the constructor validation above
        
        # 9. Invalid track ID
        aggregator.clear_all()
        ev = create_identity_evidence(track_id="")
        result = aggregator.add_evidence(ev)
        assert result is False
        
        # 10. Invalid quality class (handled by constructor)
        # This would raise ValueError in IdentityEvidence.__post_init__
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="negative_cases",
            passed=True,
            duration_ms=duration_ms,
            message="Negative cases validated",
            details={
                "empty_evidence": True,
                "all_unusable": True,
                "single_marginal": True,
                "conflicting_candidates": True,
                "duplicate_evidence": True,
                "out_of_order_reject": True,
                "missing_timestamp": True,
                "invalid_similarity": True,
                "invalid_track_id": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        import traceback
        return ValidationResult(
            test_name="negative_cases",
            passed=False,
            duration_ms=duration_ms,
            message="Negative cases test failed",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        )

def test_memory_safety() -> ValidationResult:
    """Test 16: Memory safety (bounded evidence, no accumulation)."""
    start_time = time.perf_counter()
    
    try:
        config = EvidenceWindowConfig(
            max_samples=10,
            max_duration=5.0,
        )
        aggregator = create_temporal_aggregator(config)
        
        # Add many evidence over time
        for batch in range(20):
            for i in range(5):
                ev = create_identity_evidence(
                    frame_id=f"frame_{batch}_{i}",
                    timestamp_value=1000.0 + batch * 5.0 + i,
                )
                aggregator.add_evidence(ev)
            
            # Check window size never exceeds max_samples
            size = aggregator.get_window_size("CAM1", "track_001")
            assert size <= 10, f"Window size {size} exceeds max_samples 10"
        
        # Final window should be bounded
        final_size = aggregator.get_window_size("CAM1", "track_001")
        assert final_size <= 10
        
        # Test multiple tracks don't accumulate unbounded
        for track_idx in range(5):
            for i in range(3):
                ev = create_identity_evidence(
                    track_id=f"track_{track_idx}",
                    frame_id=f"frame_{track_idx}_{i}",
                    timestamp_value=1000.0 + i,
                )
                aggregator.add_evidence(ev)
        
        # Each track bounded
        for track_idx in range(5):
            size = aggregator.get_window_size("CAM1", f"track_{track_idx}")
            assert size <= 10
        
        # Clear all
        aggregator.clear_all()
        assert aggregator.get_window_size("CAM1", "track_001") == 0
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="memory_safety",
            passed=True,
            duration_ms=duration_ms,
            message="Memory safety validated",
            details={
                "max_samples_enforced": True,
                "max_duration_enforced": True,
                "multiple_tracks_bounded": True,
                "clear_all_works": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="memory_safety",
            passed=False,
            duration_ms=duration_ms,
            message="Memory safety test failed",
            error=str(e),
        )


def test_phase17_compatibility() -> ValidationResult:
    """Test 17: Phase 17 compatibility."""
    start_time = time.perf_counter()
    
    try:
        # Create Phase 17 quality assessor
        assessor = create_quality_assessor()
        frame = create_synthetic_4k_image()
        
        # Create face crop
        face_crop = create_adaptive_face_crop(
            frame=frame,
            face_bbox_original=(1800.0, 900.0, 2000.0, 1100.0),
        )
        face_crop.data = create_sharp_face_crop()
        face_crop.crop_width = face_crop.data.shape[1]
        face_crop.crop_height = face_crop.data.shape[0]
        
        # Assess quality
        face_quality = assessor.assess(
            face_crop=face_crop,
            detection_confidence=0.9,
            pose_state=PoseState.NORMAL,
            landmarks_5pt=[(30.0, 40.0), (80.0, 40.0), (55.0, 60.0), (40.0, 80.0), (70.0, 80.0)],
        )
        
        assert face_quality.quality_class == QualityClass.GOOD
        assert face_quality.evidence_eligible is True
        
        # Create IdentityEvidence from FaceQualityResult
        evidence = IdentityEvidence.from_face_quality_result(
            face_quality=face_quality,
            identity_candidate="person_A",
            similarity=0.88,
            frame_id="frame_001",
            camera_id="CAM1",
            track_id="track_001",
            timestamp=TemporalTimestamp(value=1000.0, source=TimestampSource.CAPTURE_TIMESTAMP),
        )
        
        # Verify provenance chain
        assert evidence.provenance is not None
        assert evidence.provenance.source_type == "image"
        assert evidence.provenance.original_frame_width == 3840
        assert evidence.provenance.original_frame_height == 2160
        assert evidence.provenance.person_detection_id == "person_det_001"
        assert evidence.provenance.face_detection_id == "face_det_001"
        assert evidence.quality_class == QualityClass.GOOD
        assert evidence.quality_metrics_ref is not None
        assert "face_width" in evidence.quality_metrics_ref
        assert "sharpness" in evidence.quality_metrics_ref
        assert "pose" in evidence.quality_metrics_ref
        
        # Add to aggregator
        aggregator = create_temporal_aggregator()
        aggregator.add_evidence(evidence)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.candidate_identity == "person_A"
        assert hyp.eligible_evidence_count == 1
        
        # Test with MARGINAL quality
        face_crop_marginal = create_adaptive_face_crop(
            frame=frame,
            face_bbox_original=(1800.0, 900.0, 2000.0, 1100.0),
        )
        face_crop_marginal.data = create_blurry_face_crop()
        face_crop_marginal.crop_width = face_crop_marginal.data.shape[1]
        face_crop_marginal.crop_height = face_crop_marginal.data.shape[0]
        
        face_quality_marginal = assessor.assess(
            face_crop=face_crop_marginal,
            detection_confidence=0.9,
            pose_state=PoseState.NORMAL,
        )
        
        # Should be MARGINAL due to low sharpness
        assert face_quality_marginal.quality_class == QualityClass.MARGINAL
        assert face_quality_marginal.evidence_eligible is False
        
        evidence_marginal = IdentityEvidence.from_face_quality_result(
            face_quality=face_quality_marginal,
            identity_candidate="person_A",
            similarity=0.88,
            frame_id="frame_002",
            camera_id="CAM1",
            track_id="track_001",
            timestamp=TemporalTimestamp(value=1001.0, source=TimestampSource.CAPTURE_TIMESTAMP),
        )
        
        assert evidence_marginal.is_eligible is False
        assert evidence_marginal.is_marginal is True
        
        aggregator.add_evidence(evidence_marginal)
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.eligible_evidence_count == 1
        assert hyp.all_candidates[0].marginal_evidence_count == 1
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="phase17_compatibility",
            passed=True,
            duration_ms=duration_ms,
            message="Phase 17 compatibility validated",
            details={
                "quality_consumption": "validated",
                "provenance_chain": "preserved",
                "good_eligible": True,
                "marginal_not_eligible": True,
                "metrics_reference": "preserved",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="phase17_compatibility",
            passed=False,
            duration_ms=duration_ms,
            message="Phase 17 compatibility test failed",
            error=str(e),
        )

def test_offline_safety() -> ValidationResult:
    """Test 18: Offline-only safety (no camera, streaming, attendance)."""
    start_time = time.perf_counter()
    
    try:
        # Verify no camera/streaming imports in temporal_evidence module
        import app.vision.temporal_evidence as te_module
        import inspect
        source = inspect.getsource(te_module)
        
        # Check for actual imports/usage, not variable names or docstrings
        forbidden_patterns = [
            "cv2.VideoCapture",
            "rtmp",
            "rtsp",
            "ffmpeg",
            "MediaMTX",
            "import streaming",
            "from streaming",
            "crossing",
            "schedule",
            "Excel",
        ]
        
        for forbidden in forbidden_patterns:
            assert forbidden.lower() not in source.lower(), f"Found forbidden import: {forbidden}"
        
        # Verify aggregator works without any camera/streaming
        aggregator = create_temporal_aggregator()
        
        # Add synthetic evidence
        for i in range(5):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp is not None
        assert hyp.state != HypothesisState.INSUFFICIENT
        
        # No attendance events created
        assert not hasattr(hyp, "attendance_event")
        assert not hasattr(hyp, "in_out")
        assert not hasattr(hyp, "crossing")
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="offline_safety",
            passed=True,
            duration_ms=duration_ms,
            message="Offline-only safety validated",
            details={
                "no_camera_imports": True,
                "no_streaming_imports": True,
                "no_attendance_logic": True,
                "synthetic_only": True,
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="offline_safety",
            passed=False,
            duration_ms=duration_ms,
            message="Offline safety test failed",
            error=str(e),
        )


def test_config_serialization() -> ValidationResult:
    """Test 19: Configuration serialization and validation."""
    start_time = time.perf_counter()
    
    try:
        config = EvidenceWindowConfig(
            max_samples=50,
            max_duration=15.0,
            good_weight=1.5,
            marginal_weight=0.4,
            min_eligible_evidence=2,
            min_temporal_span=0.5,
            ambiguity_margin=0.2,
            min_confident_support=3,
            reject_duplicates=False,
            out_of_order_policy="reject",
        )
        
        # Test serialization
        config_dict = config.to_dict()
        assert config_dict["max_samples"] == 50
        assert config_dict["max_duration"] == 15.0
        assert config_dict["good_weight"] == 1.5
        assert config_dict["marginal_weight"] == 0.4
        assert config_dict["min_eligible_evidence"] == 2
        assert config_dict["min_temporal_span"] == 0.5
        assert config_dict["ambiguity_margin"] == 0.2
        assert config_dict["min_confident_support"] == 3
        assert config_dict["reject_duplicates"] is False
        assert config_dict["out_of_order_policy"] == "reject"
        
        # Test config snapshot in hypothesis
        aggregator = create_temporal_aggregator(config)
        for i in range(3):
            ev = create_identity_evidence(
                frame_id=f"frame_{i}",
                timestamp_value=1000.0 + i,
            )
            aggregator.add_evidence(ev)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        assert hyp.config_snapshot == config_dict
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="config_serialization",
            passed=True,
            duration_ms=duration_ms,
            message="Configuration serialization validated",
            details={
                "serialization": "validated",
                "snapshot_in_hypothesis": True,
                "all_fields": "present",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="config_serialization",
            passed=False,
            duration_ms=duration_ms,
            message="Config serialization test failed",
            error=str(e),
        )

def test_full_pipeline_integration() -> ValidationResult:
    """Test 20: Full pipeline integration (Phase 16 → 17 → 18)."""
    start_time = time.perf_counter()
    
    try:
        # Phase 16: Create adaptive face crop
        frame = create_synthetic_4k_image()
        face_crop = create_adaptive_face_crop(
            frame=frame,
            face_bbox_original=(1800.0, 900.0, 2000.0, 1100.0),
            person_bbox_original=(1750.0, 850.0, 2050.0, 1150.0),
        )
        
        # Phase 17: Assess quality
        assessor = create_quality_assessor()
        face_crop.data = create_sharp_face_crop()
        face_crop.crop_width = face_crop.data.shape[1]
        face_crop.crop_height = face_crop.data.shape[0]
        
        face_quality = assessor.assess(
            face_crop=face_crop,
            detection_confidence=0.92,
            pose_state=PoseState.NORMAL,
            landmarks_5pt=[(30.0, 40.0), (80.0, 40.0), (55.0, 60.0), (40.0, 80.0), (70.0, 80.0)],
        )
        
        assert face_quality.quality_class == QualityClass.GOOD
        
        # Phase 18: Create evidence and aggregate
        evidence = IdentityEvidence.from_face_quality_result(
            face_quality=face_quality,
            identity_candidate="person_A",
            similarity=0.89,
            frame_id="frame_001",
            camera_id="CAM1",
            track_id="track_001",
            timestamp=TemporalTimestamp(value=1000.0, source=TimestampSource.CAPTURE_TIMESTAMP),
        )
        
        aggregator = create_temporal_aggregator()
        aggregator.add_evidence(evidence)
        
        # Add more evidence for same track
        for i in range(1, 5):
            face_crop2 = create_adaptive_face_crop(
                frame=frame,
                face_bbox_original=(1800.0 + i, 900.0 + i, 2000.0 + i, 1100.0 + i),
                person_bbox_original=(1750.0 + i, 850.0 + i, 2050.0 + i, 1150.0 + i),
            )
            face_crop2.data = create_sharp_face_crop(seed=SYNTHETIC_SEED + i)
            face_crop2.crop_width = face_crop2.data.shape[1]
            face_crop2.crop_height = face_crop2.data.shape[0]
            
            fq = assessor.assess(
                face_crop=face_crop2,
                detection_confidence=0.9,
                pose_state=PoseState.NORMAL,
                landmarks_5pt=[(30.0, 40.0), (80.0, 40.0), (55.0, 60.0), (40.0, 80.0), (70.0, 80.0)],
            )
            
            ev = IdentityEvidence.from_face_quality_result(
                face_quality=fq,
                identity_candidate="person_A",
                similarity=0.88 + i * 0.01,
                frame_id=f"frame_{i:03d}",
                camera_id="CAM1",
                track_id="track_001",
                timestamp=TemporalTimestamp(value=1000.0 + i, source=TimestampSource.CAPTURE_TIMESTAMP),
            )
            aggregator.add_evidence(ev)
        
        hyp = aggregator.compute_hypothesis("CAM1", "track_001")
        
        # Verify full pipeline
        assert hyp.candidate_identity == "person_A"
        assert hyp.evidence_count == 5
        assert hyp.eligible_evidence_count == 5
        assert hyp.state in (HypothesisState.SUPPORTED, HypothesisState.CONFIDENT)
        assert hyp.temporal_span == 4.0
        assert hyp.best_evidence_similarity >= 0.89
        
        # Verify provenance chain intact
        assert hyp.all_candidates[0].supporting_evidence_ids[0] == evidence.evidence_id
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="full_pipeline_integration",
            passed=True,
            duration_ms=duration_ms,
            message="Full pipeline integration validated",
            details={
                "phase16_crop": "created",
                "phase17_quality": "assessed",
                "phase18_evidence": "created",
                "phase18_hypothesis": "computed",
                "provenance_chain": "intact",
            },
        )
    
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        return ValidationResult(
            test_name="full_pipeline_integration",
            passed=False,
            duration_ms=duration_ms,
            message="Full pipeline integration test failed",
            error=str(e),
        )


# =============================================================================
# MAIN VALIDATION RUNNER
# =============================================================================

def run_all_tests() -> Phase18Report:
    """Run all Phase 18 validation tests."""
    tests = [
        test_time_contract,
        test_evidence_contract,
        test_hypothesis_contract,
        test_evidence_window_bounds,
        test_quality_aware_aggregation,
        test_candidate_aggregation,
        test_temporal_consistency,
        test_ambiguity_handling,
        test_best_evidence_tracking,
        test_track_isolation,
        test_duplicate_evidence,
        test_out_of_order_timestamps,
        test_track_finalization,
        test_determinism,
        test_negative_cases,
        test_memory_safety,
        test_phase17_compatibility,
        test_offline_safety,
        test_config_serialization,
        test_full_pipeline_integration,
    ]
    
    results = []
    passed = 0
    failed = 0
    skipped = 0
    
    for test_func in tests:
        print(f"Running {test_func.__name__}...")
        result = test_func()
        results.append(asdict(result))
        
        if result.passed:
            passed += 1
            print(f"  PASS: {result.message}")
        else:
            failed += 1
            print(f"  FAIL: {result.message}")
            if result.error:
                print(f"    Error: {result.error}")
    
    total = len(tests)
    verdict = "PASS" if failed == 0 else "FAIL"
    
    # Build report
    report = Phase18Report(
        timestamp=datetime.now().isoformat(),
        total_tests=total,
        passed_tests=passed,
        failed_tests=failed,
        skipped_tests=skipped,
        results=results,
        verdict=verdict,
        time_contract={"status": "validated" if passed > 0 else "failed"},
        evidence_contract={"status": "validated" if passed > 1 else "failed"},
        window_policy={"status": "validated" if passed > 3 else "failed"},
        quality_weighting={"status": "validated" if passed > 4 else "failed"},
        candidate_aggregation={"status": "validated" if passed > 5 else "failed"},
        temporal_consistency={"status": "validated" if passed > 6 else "failed"},
        ambiguity={"status": "validated" if passed > 7 else "failed"},
        deduplication={"status": "validated" if passed > 10 else "failed"},
        out_of_order_handling={"status": "validated" if passed > 11 else "failed"},
        track_isolation={"status": "validated" if passed > 9 else "failed"},
        determinism={"status": "validated" if passed > 13 else "failed"},
        memory_safety={"status": "validated" if passed > 15 else "failed"},
        phase17_compatibility={"status": "validated" if passed > 16 else "failed"},
        offline_safety={"status": "validated" if passed > 17 else "failed"},
        limitations=[
            "Synthetic data only - no production accuracy claims",
            "Quality weights are engineering defaults, not calibrated",
            "Hypothesis states are deterministic heuristics, not probabilities",
            "No cross-camera fusion (Phase 20/21)",
            "No attendance logic (Phase 22+)",
        ],
        readiness_for_phase19=(failed == 0),
    )
    
    return report


def main():
    """Main entry point."""
    print("=" * 60)
    print("Phase 18 — Temporal Identity Evidence Validation")
    print("=" * 60)
    
    report = run_all_tests()
    
    print("\n" + "=" * 60)
    print(f"VERDICT: {report.verdict}")
    print(f"Tests: {report.passed_tests}/{report.total_tests} passed")
    print("=" * 60)
    
    # Save JSON report
    output_dir = Path("benchmark_results")
    output_dir.mkdir(exist_ok=True)
    
    json_path = output_dir / "PHASE_18_TEMPORAL_IDENTITY_EVIDENCE.json"
    with open(json_path, "w") as f:
        json.dump(asdict(report), f, indent=2)
    print(f"JSON report saved to: {json_path}")
    
    # Save Markdown report
    md_path = output_dir / "PHASE_18_TEMPORAL_IDENTITY_EVIDENCE.md"
    with open(md_path, "w") as f:
        f.write(f"# Phase 18 — Temporal Identity Evidence Validation Report\n\n")
        f.write(f"**Timestamp:** {report.timestamp}\n\n")
        f.write(f"**Verdict:** {report.verdict}\n\n")
        f.write(f"**Total Tests:** {report.total_tests}\n")
        f.write(f"**Passed:** {report.passed_tests}\n")
        f.write(f"**Failed:** {report.failed_tests}\n")
        f.write(f"**Skipped:** {report.skipped_tests}\n\n")
        
        f.write("## Test Results\n\n")
        for r in report.results:
            status = "PASS" if r["passed"] else "FAIL"
            f.write(f"- {status} **{r['test_name']}** ({r['duration_ms']:.1f}ms): {r['message']}\n")
            if r["error"]:
                f.write(f"  - Error: {r['error']}\n")
        
        f.write("\n## Component Status\n\n")
        f.write(f"- Time Contract: {report.time_contract['status']}\n")
        f.write(f"- Evidence Contract: {report.evidence_contract['status']}\n")
        f.write(f"- Window Policy: {report.window_policy['status']}\n")
        f.write(f"- Quality Weighting: {report.quality_weighting['status']}\n")
        f.write(f"- Candidate Aggregation: {report.candidate_aggregation['status']}\n")
        f.write(f"- Temporal Consistency: {report.temporal_consistency['status']}\n")
        f.write(f"- Ambiguity: {report.ambiguity['status']}\n")
        f.write(f"- Deduplication: {report.deduplication['status']}\n")
        f.write(f"- Out-of-Order Handling: {report.out_of_order_handling['status']}\n")
        f.write(f"- Track Isolation: {report.track_isolation['status']}\n")
        f.write(f"- Determinism: {report.determinism['status']}\n")
        f.write(f"- Memory Safety: {report.memory_safety['status']}\n")
        f.write(f"- Phase 17 Compatibility: {report.phase17_compatibility['status']}\n")
        f.write(f"- Offline Safety: {report.offline_safety['status']}\n")
        
        f.write("\n## Limitations\n\n")
        for lim in report.limitations:
            f.write(f"- {lim}\n")
        
        f.write(f"\n## Readiness for Phase 19: {report.readiness_for_phase19}\n")
        
        f.write("\n---\n")
        f.write("*No production identity accuracy claim. Synthetic evidence only.*\n")
    
    print(f"Markdown report saved to: {md_path}")
    
    if report.failed_tests > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()