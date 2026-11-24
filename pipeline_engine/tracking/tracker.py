"""
Tracking System - Geometry-based tracking with identity fusion.

Operates in ORIGINAL_FRAME coordinate space. Integrates face recognition
and person ReID for identity continuity.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum

import numpy as np
import torch

from pipeline_engine.inference.face_detection import FaceDetection
from pipeline_engine.inference.person_detection import PersonDetection
from pipeline_engine.inference.face_recognition import FaceEmbedding
from pipeline_engine.config import get_config

logger = logging.getLogger(__name__)

try:
    from attendance_core import batch_iou_and_match_rs as _batch_iou_and_match_rs
    _HAS_RUST_TRACKING = True
except ImportError:
    _batch_iou_and_match_rs = None
    _HAS_RUST_TRACKING = False


class TrackLifecycleState(str, Enum):
    """Track lifecycle states."""
    NEW = "new"
    ACTIVE = "active"
    LOST = "lost"
    CLOSED = "closed"


@dataclass
class Track:
    """A tracked person/face over time with identity."""
    track_id: int
    source_frame_id: str
    frame_index: int
    timestamp: float
    
    # Bounding box in original frame coordinates
    bbox_original_frame: Tuple[float, float, float, float]
    
    # Face detection info (optional)
    face_detection_id: Optional[str] = None
    face_bbox: Optional[Tuple[float, float, float, float]] = None
    face_confidence: float = 0.0
    face_landmarks5: Optional[List[Tuple[float, float]]] = None
    
    # Identity info
    person_id: Optional[str] = None          # Enrolled person ID from face recognition
    person_name: Optional[str] = None        # Display name
    embedding: Optional[np.ndarray] = None   # Face embedding for ReID fallback
    embedding_similarity: float = 0.0
    identity_confidence: float = 0.0         # Confidence in identity assignment
    identity_source: str = "unknown"         # "face_recognition", "reid", "unknown"
    
    # NEW: Live embeddings (P2.1, P2.2, P2.3)
    face_embedding: Optional[np.ndarray] = None      # 512D ArcFace embedding
    face_quality: float = 0.0                        # Face quality score 0-1
    face_model_id: str = ""                          # Model identifier
    face_model_sha256: str = ""                      # Model hash
    body_embedding: Optional[np.ndarray] = None      # 2048D ReID embedding
    body_quality: float = 0.0                        # Body quality score 0-1
    body_model_id: str = ""                          # Model identifier
    body_model_sha256: str = ""                      # Model hash
    
    # Tracking info
    confidence: float = 1.0
    lifecycle_state: TrackLifecycleState = TrackLifecycleState.NEW
    age: int = 0
    hits: int = 1
    missed_frames: int = 0
    last_seen: float = 0.0
    
    # Provenance
    person_provenance: Optional[str] = None
    face_provenance: Optional[str] = None
    coordinate_space: str = "original_frame"
    
    # NEW: Global identity (P2.6, P3.1)
    global_person_id: Optional[str] = None           # Canonical Person ID from GIS
    identity_state: str = "unknown"                  # UNKNOWN | CANDIDATE | PROVISIONAL | CONFIRMED | CONFLICT | REACQUIRED
    identity_updated_at: float = 0.0                 # Timestamp of last identity update
    face_verified: bool = False                      # Strict Face-First Acquisition gate
    pending_global_id: Optional[str] = None          # Anonymous cross-cam token (e.g., "G-01")
    bridged_from_cam: Optional[str] = None           # Source cam ID if bridged via GIS BodyReID
    unmatched_face_frames: int = 0                   # Consecutive clear frontal-face frames < 0.50
    
    # NEW: Embedding accumulation (P2.4)
    face_embeddings_history: Optional[List[Any]] = None  # History of face embeddings
    body_embeddings_history: Optional[List[Any]] = None  # History of body embeddings
    avg_face_embedding: Optional[Any] = None             # Running average face embedding
    avg_body_embedding: Optional[Any] = None             # Running average body embedding
    max_face_quality: float = 0.0                    # Max face quality seen
    max_body_quality: float = 0.0                    # Max body quality seen
    embedding_count: int = 0                         # Number of embeddings accumulated
    stationary_frames: int = 0                       # Consecutive stationary frames
    _prev_center: Optional[Tuple[float, float]] = field(default=None, repr=False)

    @property
    def camera_id(self) -> str:
        cid = self.source_frame_id.lower().strip()
        if cid.startswith("cam_cam"):
            cid = cid[4:]
        return cid

    @property
    def frame_sequence(self) -> int:
        return self.frame_index

    @property
    def time_since_update(self) -> int:
        return int(self.missed_frames)

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return self.bbox_original_frame

    @property
    def identity_candidate(self) -> Optional[str]:
        return self.person_name or self.person_id

    @property
    def state(self) -> str:
        return self.lifecycle_state.value
    
    @property
    def width(self) -> float:
        return self.bbox_original_frame[2] - self.bbox_original_frame[0]
    
    @property
    def height(self) -> float:
        return self.bbox_original_frame[3] - self.bbox_original_frame[1]
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def center(self) -> Tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_original_frame
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def foot_center(self) -> Tuple[float, float]:
        x1, _, x2, y2 = self.bbox_original_frame
        return ((x1 + x2) * 0.5, float(y2))
    
    @property
    def is_active(self) -> bool:
        return self.lifecycle_state == TrackLifecycleState.ACTIVE
    
    @property
    def is_new(self) -> bool:
        return self.lifecycle_state == TrackLifecycleState.NEW
    
    @property
    def is_lost(self) -> bool:
        return self.lifecycle_state == TrackLifecycleState.LOST
    
    @property
    def is_closed(self) -> bool:
        return self.lifecycle_state == TrackLifecycleState.CLOSED
    
    @property
    def is_identified(self) -> bool:
        return self.person_id is not None and self.identity_confidence > 0.5

    def is_stationary(self, velocity_threshold: float = 5.0) -> bool:
        """Check if track represents a stationary person (e.g., sitting at desk).

        A track is considered stationary if:
        - Age >= 30 frames (established track) or stationary_frames >= 10
        - Missed frames == 0 (consistently detected)
        - Low pixel displacement between consecutive frames
        """
        if self.missed_frames > 0:
            return False
        if self.age < 30 and self.stationary_frames < 10:
            return False
        if self._prev_center is None:
            return self.stationary_frames >= 10

        current_center = self.center
        dx = current_center[0] - self._prev_center[0]
        dy = current_center[1] - self._prev_center[1]
        velocity = math.hypot(dx, dy)

        # Stationary if displacement < 5 pixels/frame in original-frame pixel space
        return velocity < velocity_threshold or self.stationary_frames >= 10

    def _update_stationary_check(self) -> None:
        """Update stationary tracking state based on previous frame center."""
        current_center = self.center
        if self._prev_center is not None:
            dist = math.hypot(
                current_center[0] - self._prev_center[0],
                current_center[1] - self._prev_center[1],
            )
            if dist < 5.0:
                self.stationary_frames += 1
            else:
                self.stationary_frames = 0
        else:
            self._prev_center = current_center

    def to_tlbr(self) -> np.ndarray:
        """Return bounding box in TLBR format."""
        return np.array(self.bbox_original_frame)

    @property
    def matched_name(self) -> Optional[str]:
        """Matched face/person name or None."""
        return self.person_name

    @property
    def matched_id(self) -> Optional[str]:
        """Matched person ID or None."""
        return self.person_id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "bbox": self.bbox_original_frame,
            "confidence": self.confidence,
            "lifecycle_state": self.lifecycle_state.value,
            "age": self.age,
            "hits": self.hits,
            "missed_frames": self.missed_frames,
            "time_since_update": self.missed_frames,
            "person_id": self.person_id,
            "person_name": self.person_name,
            "identity_confidence": self.identity_confidence,
            "identity_source": self.identity_source,
            "face_verified": self.face_verified,
            "pending_global_id": self.pending_global_id,
            "bridged_from_cam": self.bridged_from_cam,
            "unmatched_face_frames": self.unmatched_face_frames,
            "center": self.center,
        }


@dataclass
class TrackingConfig:
    """Configuration for tracking."""
    min_iou_threshold: float = 0.20
    match_thresh: float = 0.80
    track_buffer: int = 45
    max_age: int = 45
    max_lost_frames: int = 45
    high_det_thresh: float = 0.38
    low_det_thresh: float = 0.18
    inner_box_ioa_threshold: float = 0.55
    max_active_tracks: int = 50
    max_lost_tracks: int = 30
    max_new_tracks: int = 10
    use_face_association: bool = True
    face_center_weight: float = 0.5
    # Identity fusion & strict Face-First Identity Acquisition
    camera_role: str = "frontal"  # "frontal" | "side_profile"
    face_recognition_priority: bool = True
    reid_fallback_enabled: bool = False
    reid_similarity_threshold: float = 0.7
    identity_confidence_threshold: float = 0.5
    min_face_conf: float = 0.55
    min_face_size_px: float = 34.0
    face_upper_box_ratio: float = 0.55
    min_person_width_px: float = 75.0
    max_person_aspect_ratio: float = 4.0
    face_verify_min_sim: float = 0.56
    fused_verify_min_score: float = 0.62
    face_fusion_weight: float = 0.75
    body_fusion_weight: float = 0.25
    unregistered_face_min_frames: int = 5
    unregistered_face_max_sim: float = 0.50
    handoff_ttl_seconds: float = 15.0
    handoff_min_body_sim: float = 0.68
    handoff_min_margin: float = 0.08


@dataclass
class TrackingResult:
    """Result of tracking for a single frame."""
    source_frame_id: str
    frame_index: int
    timestamp: float
    tracks: List[Track] = field(default_factory=list)
    new_tracks: List[Track] = field(default_factory=list)
    closed_tracks: List[Track] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.source_frame_id = str(self.source_frame_id).lower().strip()

    @property
    def camera_id(self) -> str:
        return self.source_frame_id

    @property
    def frame_sequence(self) -> int:
        return self.frame_index

    @property
    def time_since_update(self) -> int:
        return int(self.missed_frames)
    
    def get_active_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.is_active or t.is_new]
    
    def get_identified_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.is_identified]


def compute_iou(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float],
    frame_w: float = 3840.0,
    frame_h: float = 2160.0
) -> float:
    """Compute Intersection over Union of two bboxes.
    
    Handles both normalized [0,1] and pixel coordinate spaces automatically.
    If both bboxes have max coordinate <= 1.01, evaluates in unit space.
    Otherwise denormalizes to pixel coordinates.
    """
    x1_1, y1_1, x2_1, y2_1 = bbox1[:4]
    x1_2, y1_2, x2_2, y2_2 = bbox2[:4]
    
    # Detect coordinate space: if both boxes are normalized, compute in unit space
    max_coord1 = max(x1_1, y1_1, x2_1, y2_1)
    max_coord2 = max(x1_2, y1_2, x2_2, y2_2)
    
    if max_coord1 <= 1.01 and max_coord2 <= 1.01:
        # Both normalized - compute directly in [0,1] space
        scale_w = scale_h = 1.0
    else:
        # At least one in pixel space - denormalize both to pixel coordinates
        scale_w = frame_w
        scale_h = frame_h
        if max_coord1 <= 1.01:
            x1_1, y1_1, x2_1, y2_1 = x1_1 * frame_w, y1_1 * frame_h, x2_1 * frame_w, y2_1 * frame_h
        if max_coord2 <= 1.01:
            x1_2, y1_2, x2_2, y2_2 = x1_2 * frame_w, y1_2 * frame_h, x2_2 * frame_w, y2_2 * frame_h
    
    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    
    if x2_i <= x1_i or y2_i <= y1_i:
        return 0.0
    
    inter_w = max(0.0, x2_i - x1_i)
    inter_h = max(0.0, y2_i - y1_i)
    intersection = inter_w * inter_h
    
    area1 = max(0.0, x2_1 - x1_1) * max(0.0, y2_1 - y1_1)
    area2 = max(0.0, x2_2 - x1_2) * max(0.0, y2_2 - y1_2)
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0.0


def compute_ioa(
    inner_bbox: Tuple[float, float, float, float],
    outer_bbox: Tuple[float, float, float, float],
    frame_w: float = 3840.0,
    frame_h: float = 2160.0,
) -> float:
    """Compute Intersection over Area of inner_bbox inside outer_bbox."""
    x1_1, y1_1, x2_1, y2_1 = inner_bbox[:4]
    x1_2, y1_2, x2_2, y2_2 = outer_bbox[:4]

    max_coord1 = max(x1_1, y1_1, x2_1, y2_1)
    max_coord2 = max(x1_2, y1_2, x2_2, y2_2)
    if not (max_coord1 <= 1.01 and max_coord2 <= 1.01):
        if max_coord1 <= 1.01:
            x1_1, y1_1, x2_1, y2_1 = x1_1 * frame_w, y1_1 * frame_h, x2_1 * frame_w, y2_1 * frame_h
        if max_coord2 <= 1.01:
            x1_2, y1_2, x2_2, y2_2 = x1_2 * frame_w, y1_2 * frame_h, x2_2 * frame_w, y2_2 * frame_h

    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    if x2_i <= x1_i or y2_i <= y1_i:
        return 0.0

    intersection = (x2_i - x1_i) * (y2_i - y1_i)
    inner_area = max(0.0, x2_1 - x1_1) * max(0.0, y2_1 - y1_1)
    return intersection / inner_area if inner_area > 1e-6 else 0.0


def suppress_inner_duplicate_boxes(
    person_detections: List[PersonDetection],
    active_tracks: Optional[List[Track]] = None,
    ioa_threshold: float = 0.55,
) -> List[PersonDetection]:
    """Suppress smaller duplicate person detections contained inside larger ones (IoA >= threshold).

    Preserves legitimate side-by-side crossings when both boxes strongly match distinct active tracks
    and the smaller box is comparable in size (>= 45% area of the larger box).
    """
    if len(person_detections) <= 1:
        return person_detections

    def _best_track_id(bbox: Tuple[float, float, float, float]) -> Optional[int]:
        if not active_tracks:
            return None
        best_tid: Optional[int] = None
        best_iou = 0.30
        for tr in active_tracks:
            iou = compute_iou(bbox, tr.bbox_original_frame)
            if iou >= best_iou:
                best_iou = iou
                best_tid = tr.track_id
        return best_tid

    sorted_dets = sorted(
        person_detections,
        key=lambda d: (float(d.area), float(d.confidence)),
        reverse=True,
    )
    kept: List[PersonDetection] = []
    kept_track_ids: List[Optional[int]] = []

    for det in sorted_dets:
        det_tid = _best_track_id(det.bbox)
        det_area = max(1e-6, float(det.area))
        suppressed = False
        for k_det, k_tid in zip(kept, kept_track_ids):
            ioa = compute_ioa(det.bbox, k_det.bbox)
            if ioa >= ioa_threshold:
                k_area = max(1e-6, float(k_det.area))
                distinct_active = (
                    ioa < 0.72
                    and det_tid is not None
                    and k_tid is not None
                    and det_tid != k_tid
                    and det_area >= 0.45 * k_area
                )
                if not distinct_active:
                    suppressed = True
                    break
        if not suppressed:
            kept.append(det)
            kept_track_ids.append(det_tid)

    return kept


def compute_track_detection_score(
    track: Track,
    person_detection: PersonDetection,
    config: TrackingConfig,
    face_detection: Optional[FaceDetection] = None,
) -> Tuple[float, Dict[str, float]]:
    """
    Compute association score between a track and a person detection.
    
    Uses deterministic geometric matching + face association bonus.
    """
    track_bbox = track.bbox_original_frame
    det_bbox = person_detection.bbox
    
    # IoU score - pass frame dimensions for denormalization
    iou_score = compute_iou(track_bbox, det_bbox, 3840.0, 2160.0)
    
    # Center distance score
    frame_w, frame_h = 3840, 2160  # Default, could be from frame metadata
    frame_diagonal = np.sqrt(frame_w**2 + frame_h**2)
    track_center = track.center
    det_center = person_detection.center
    center_dist = np.sqrt((track_center[0] - det_center[0])**2 + (track_center[1] - det_center[1])**2)
    center_dist_score = max(0.0, 1.0 - center_dist / frame_diagonal)
    
    # Area ratio score
    track_area = track.area
    det_area = person_detection.area
    if track_area > 0 and det_area > 0:
        area_ratio = min(track_area, det_area) / max(track_area, det_area)
    else:
        area_ratio = 0.0
    
    # Face association bonus
    face_bonus = 0.0
    if config.use_face_association and face_detection:
        # Check if face center is inside both track and detection bboxes
        face_center = face_detection.center
        track_contains = (
            track_bbox[0] <= face_center[0] <= track_bbox[2] and
            track_bbox[1] <= face_center[1] <= track_bbox[3]
        )
        det_contains = (
            det_bbox[0] <= face_center[0] <= det_bbox[2] and
            det_bbox[1] <= face_center[1] <= det_bbox[3]
        )
        if track_contains and det_contains:
            face_bonus = config.face_center_weight
    
    # Weighted total score
    weights = (0.35, 0.2, 0.15, 0.3)  # IoU, center_dist, area_ratio, face_bonus
    total_score = (
        weights[0] * iou_score +
        weights[1] * center_dist_score +
        weights[2] * area_ratio +
        weights[3] * face_bonus
    )
    
    components = {
        "iou": iou_score,
        "center_distance": center_dist_score,
        "area_ratio": area_ratio,
        "face_bonus": face_bonus,
    }
    
    return total_score, components


def solve_track_assignment(
    tracks: List[Track],
    person_detections: List[PersonDetection],
    face_detections: Optional[List[FaceDetection]] = None,
    config: Optional[TrackingConfig] = None,
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """Solve two-stage ByteTrack-style assignment between tracks and person detections."""
    if config is None:
        config = TrackingConfig()

    num_tracks = len(tracks)
    num_detections = len(person_detections)
    high_indices = [
        di for di, d in enumerate(person_detections)
        if float(getattr(d, "confidence", 1.0)) >= config.high_det_thresh
    ]
    low_indices = [
        di for di, d in enumerate(person_detections)
        if config.low_det_thresh <= float(getattr(d, "confidence", 1.0)) < config.high_det_thresh
    ]

    if num_tracks == 0 or num_detections == 0:
        return [], list(range(num_tracks)), high_indices

    face_lookup = {fd.detection_id: fd for fd in face_detections} if face_detections else {}

    iou_matrix = np.zeros((num_tracks, num_detections), dtype=np.float32)
    score_matrix = np.zeros((num_tracks, num_detections), dtype=np.float32)
    for ti, track in enumerate(tracks):
        for di, det in enumerate(person_detections):
            iou_matrix[ti, di] = compute_iou(track.bbox_original_frame, det.bbox, 1920.0, 1080.0)
            face_det = face_lookup.get(det.detection_id) if face_lookup else None
            score, _ = compute_track_detection_score(track, det, config, face_det)
            score_matrix[ti, di] = score

    # Prioritize active tracks before lost tracks, deterministically ordered by track_id
    track_order = sorted(
        range(num_tracks),
        key=lambda ti: (tracks[ti].missed_frames, tracks[ti].track_id),
    )

    track_assigned = [False] * num_tracks
    detection_assigned = [False] * num_detections
    assignments: List[Tuple[int, int]] = []
    min_stage1_iou = max(0.05, 1.0 - float(config.match_thresh))

    # Stage 1: Associate high-confidence detections with all active & buffered tracks
    for ti in track_order:
        best_di = -1
        best_rank = -1.0
        for di in high_indices:
            if detection_assigned[di]:
                continue
            iou = float(iou_matrix[ti, di])
            score = float(score_matrix[ti, di])
            if iou >= min_stage1_iou or (iou >= 0.08 and score >= 0.30):
                rank = 0.65 * iou + 0.35 * score
                if rank > best_rank:
                    best_rank = rank
                    best_di = di
        if best_di >= 0:
            assignments.append((ti, best_di))
            track_assigned[ti] = True
            detection_assigned[best_di] = True

    # Stage 2: Second-stage low-score association keeps exiting/partially-occluded tracks alive
    if low_indices:
        for ti in track_order:
            if track_assigned[ti] or tracks[ti].missed_frames > 5:
                continue
            best_di = -1
            best_iou = 0.12
            for di in low_indices:
                if detection_assigned[di]:
                    continue
                iou = float(iou_matrix[ti, di])
                if iou >= best_iou:
                    best_iou = iou
                    best_di = di
            if best_di >= 0:
                assignments.append((ti, best_di))
                track_assigned[ti] = True
                detection_assigned[best_di] = True

    unmatched_tracks = [ti for ti in range(num_tracks) if not track_assigned[ti]]
    unmatched_detections = [di for di in high_indices if not detection_assigned[di]]
    return assignments, unmatched_tracks, unmatched_detections


def find_face_for_person(
    person_detection: PersonDetection,
    face_detections: List[FaceDetection],
) -> Optional[FaceDetection]:
    """Find face detection associated with person detection (prioritizing upper 55% of box)."""
    person_bbox = person_detection.bbox
    px1, py1, px2, py2 = person_bbox[:4]
    upper_y = py1 + 0.55 * max(0.0, py2 - py1)

    best_face = None
    best_score = -1.0

    for face in face_detections:
        face_center = face.center
        if px1 <= face_center[0] <= px2 and py1 <= face_center[1] <= py2:
            in_upper = 1.0 if face_center[1] <= upper_y else 0.0
            rank = in_upper * 2.0 + float(face.confidence)
            if rank > best_score:
                best_score = rank
                best_face = face

    return best_face


def _resolve_display_name(recognizer: Optional[Any], student_id: Optional[str]) -> Optional[str]:
    """Return mapped display name if student_id is actively enrolled, else None."""
    if recognizer is None or not student_id:
        return None
    lock = getattr(recognizer, "_lock", None)
    if lock is not None:
        with lock:
            identities = set(getattr(recognizer, "identities", []))
            meta_lookup = getattr(recognizer, "metadata_lookup", {}) or {}
            enroll_meta = getattr(recognizer, "_enrollment_metadata", {}) or {}
    else:
        identities = set(getattr(recognizer, "identities", []))
        meta_lookup = getattr(recognizer, "metadata_lookup", {}) or {}
        enroll_meta = getattr(recognizer, "_enrollment_metadata", {}) or {}
    if student_id not in identities:
        return None
    meta = meta_lookup.get(student_id) or enroll_meta.get(student_id) or {}
    name = meta.get("name")
    if not name or str(name).strip() == str(student_id).strip():
        return None
    return str(name).strip()


def _compute_face_scores(
    recognizer: Optional[Any],
    face_embedding: Optional[FaceEmbedding],
) -> Dict[str, float]:
    """Compute cosine similarity against all enrolled ArcFace identities."""
    if recognizer is None or face_embedding is None:
        return {}
    lock = getattr(recognizer, "_lock", None)
    if lock is not None:
        with lock:
            matrix = getattr(recognizer, "embeddings_matrix", None)
            identities = list(getattr(recognizer, "identities", []))
    else:
        matrix = getattr(recognizer, "embeddings_matrix", None)
        identities = list(getattr(recognizer, "identities", []))
    if matrix is None or not identities or matrix.shape[0] != len(identities):
        return {}
    sims = torch.matmul(matrix, face_embedding.embedding).detach().cpu().numpy()
    return {identities[i]: float(sims[i]) for i in range(len(identities))}


def _compute_frontal_pose_score(face_detection: Optional[FaceDetection]) -> float:
    """Estimate frontalness in [0.0, 1.0] from 5 facial landmarks."""
    if not face_detection or not getattr(face_detection, "landmarks5", None):
        return 1.0
    lm = face_detection.landmarks5
    if len(lm) != 5:
        return 1.0
    eye_dist = abs(float(lm[1][0]) - float(lm[0][0]))
    if eye_dist <= 1.0:
        return 1.0
    nose_off = abs(float(lm[2][0]) - (float(lm[0][0]) + float(lm[1][0])) * 0.5)
    return max(0.0, min(1.0, 1.0 - 2.0 * (nose_off / eye_dist)))


def _is_non_sliver_person_box(
    person_bbox: Tuple[float, float, float, float],
    config: TrackingConfig,
) -> bool:
    """Return True if person bbox is wide enough and not a doorway-edge arm sliver."""
    px1, py1, px2, py2 = person_bbox[:4]
    pw = max(0.0, float(px2) - float(px1))
    ph = max(0.0, float(py2) - float(py1))
    if pw < config.min_person_width_px:
        return False
    if (ph / max(pw, 1.0)) > config.max_person_aspect_ratio:
        return False
    return True


def _passes_strict_face_gate(
    person_bbox: Tuple[float, float, float, float],
    face_detection: Optional[FaceDetection],
    config: TrackingConfig,
) -> bool:
    """Strict Face-First gate: genuine visible face (>= 34x34, conf >= 0.55, upper 55%) + non-sliver person."""
    if face_detection is None:
        return False
    if not _is_non_sliver_person_box(person_bbox, config):
        return False
    scrfd_conf = float(getattr(face_detection, "confidence", 0.0))
    if scrfd_conf < config.min_face_conf:
        return False
    fx1, fy1, fx2, fy2 = face_detection.bbox[:4]
    fw = float(fx2) - float(fx1)
    fh = float(fy2) - float(fy1)
    if fw < config.min_face_size_px or fh < config.min_face_size_px:
        return False
    fcx = (float(fx1) + float(fx2)) * 0.5
    fcy = (float(fy1) + float(fy2)) * 0.5
    px1, py1, px2, py2 = [float(v) for v in person_bbox[:4]]
    if not (px1 <= fcx <= px2):
        return False
    upper_limit_y = py1 + config.face_upper_box_ratio * max(0.0, py2 - py1)
    if not (py1 <= fcy <= upper_limit_y):
        return False
    return True


def _resolve_track_identity(
    track_id: int,
    camera_id: str,
    timestamp: float,
    person_bbox: Tuple[float, float, float, float],
    prev_person_id: Optional[str],
    prev_person_name: Optional[str],
    prev_conf: float,
    prev_source: str,
    prev_emb: Optional[np.ndarray],
    prev_face_verified: bool,
    prev_pending_global_id: Optional[str],
    prev_bridged_from_cam: Optional[str],
    prev_unmatched_face_frames: int,
    face_embedding: Optional[FaceEmbedding],
    face_detection: Optional[FaceDetection],
    body_vec: Optional[np.ndarray],
    recognizer: Optional[Any],
    reid_detector: Optional[Any],
    locked_identities: Dict[int, Dict[str, Any]],
    track_consensus: Dict[int, Dict[str, Dict[str, Any]]],
    locked_sids_in_frame: set,
    config: TrackingConfig,
    gis: Optional[Any] = None,
) -> Tuple[Optional[str], Optional[str], float, str, Optional[np.ndarray], bool, Optional[str], Optional[str], int]:
    """Strict Face-First Identity Acquisition + Asymmetric Cross-Cam BodyReID Bridge."""
    strict_face_ok = _passes_strict_face_gate(person_bbox, face_detection, config)
    face_scores = _compute_face_scores(recognizer, face_embedding) if strict_face_ok else {}
    body_scores = (
        reid_detector.match_body(body_vec)
        if reid_detector is not None and body_vec is not None and hasattr(reid_detector, "match_body")
        else {}
    )
    frontal_score = _compute_frontal_pose_score(face_detection)
    scrfd_conf = float(getattr(face_detection, "confidence", 0.0)) if face_detection is not None else 0.0

    # Also verify via Rust GalleryIndexRs when available
    rust_top1: Optional[Tuple[str, float]] = None
    if strict_face_ok and face_embedding is not None and recognizer is not None and hasattr(recognizer, "identify_top1_cpu"):
        try:
            q_np = face_embedding.embedding.detach().cpu().numpy()
            rust_top1 = recognizer.identify_top1_cpu(q_np, threshold=config.face_verify_min_sim)
        except Exception:
            rust_top1 = None

    # 1. Track is already locked (face-verified or cross-cam bridged): preserve identity to border
    if track_id in locked_identities:
        lock_info = locked_identities[track_id]
        sid = lock_info["student_id"]
        fname = lock_info["full_name"]
        lconf = float(lock_info["locked_confidence"])
        src = str(lock_info.get("source", "face_verified_lock"))
        is_face_verified = bool(lock_info.get("face_verified", False))
        bridged_from = lock_info.get("bridged_from_cam")
        emb_out = face_embedding.embedding.detach().cpu().numpy() if face_embedding is not None else prev_emb

        raw_fsim = face_scores.get(sid, 0.0)
        if strict_face_ok and raw_fsim >= config.face_verify_min_sim and frontal_score >= 0.20:
            bsim = body_scores.get(sid, raw_fsim)
            fused = config.face_fusion_weight * raw_fsim + config.body_fusion_weight * bsim
            if fused >= config.fused_verify_min_score:
                lock_info["locked_confidence"] = max(lconf, float(fused))
                lock_info["face_verified"] = True
                lconf = lock_info["locked_confidence"]
                is_face_verified = True
                if reid_detector is not None and body_vec is not None and hasattr(reid_detector, "update_prototype_ema"):
                    reid_detector.update_prototype_ema(sid, body_vec, alpha=0.10)
                if gis is not None and body_vec is not None and hasattr(gis, "publish_face_verified"):
                    gis.publish_face_verified(
                        student_id=sid,
                        full_name=fname,
                        body_embedding=body_vec,
                        source_cam_id=camera_id,
                        source_track_id=track_id,
                        confidence=lconf,
                        timestamp=timestamp,
                        handoff_ttl=config.handoff_ttl_seconds,
                        min_sim=config.handoff_min_body_sim,
                        min_margin=config.handoff_min_margin,
                    )
        return sid, fname, lconf, src, emb_out, is_face_verified, None, bridged_from, 0

    # 2. Check if an anonymous Pending Track #G-XX on this camera was retroactively backfilled by GIS
    if gis is not None and prev_pending_global_id and hasattr(gis, "get_resolved_pending"):
        resolved_pt = gis.get_resolved_pending(camera_id, track_id)
        if resolved_pt is not None and resolved_pt.resolved_student_id:
            sid = resolved_pt.resolved_student_id
            fname = resolved_pt.resolved_full_name or _resolve_display_name(recognizer, sid) or sid
            rconf = float(resolved_pt.resolved_confidence or 0.70)
            src_cam = resolved_pt.resolved_from_cam
            locked_identities[track_id] = {
                "student_id": sid,
                "full_name": fname,
                "locked_confidence": rconf,
                "source": "retroactive_backfill",
                "face_verified": False,
                "bridged_from_cam": src_cam,
            }
            return sid, fname, rconf, "retroactive_backfill", prev_emb, False, prev_pending_global_id, src_cam, 0

    # 3. Strict Visible-Face Gate -> ArcFace (512D + Rust GalleryIndexRs) + BodyReID fusion
    best_raw_fsim = max(face_scores.values()) if face_scores else 0.0
    if strict_face_ok and face_scores and frontal_score >= 0.20:
        best_cand: Optional[Tuple[str, str, float, float]] = None
        for sid, raw_fsim in face_scores.items():
            if raw_fsim < config.face_verify_min_sim:
                continue
            # Require Rust GalleryIndexRs agreement when top-1 exists
            if rust_top1 is not None and rust_top1[0] != sid and raw_fsim < rust_top1[1]:
                continue
            fname = _resolve_display_name(recognizer, sid)
            if fname is None:
                continue
            bsim = body_scores.get(sid, raw_fsim)
            fused = config.face_fusion_weight * raw_fsim + config.body_fusion_weight * bsim
            if sid in locked_sids_in_frame and fused < 0.80:
                continue
            if best_cand is None or fused > best_cand[2]:
                best_cand = (sid, fname, float(fused), float(raw_fsim))

        if best_cand is not None and best_cand[2] >= config.fused_verify_min_score:
            sid, fname, fused, raw_fsim = best_cand
            entry = track_consensus.setdefault(track_id, {}).setdefault(sid, {"hits": 0, "best_score": 0.0})
            entry["hits"] += 1
            entry["best_score"] = max(entry["best_score"], fused)
            out_emb = face_embedding.embedding.detach().cpu().numpy() if face_embedding is not None else prev_emb

            if entry["hits"] >= 2 or raw_fsim >= 0.62:
                locked_identities[track_id] = {
                    "student_id": sid,
                    "full_name": fname,
                    "locked_confidence": entry["best_score"],
                    "source": "face_verified_lock",
                    "face_verified": True,
                    "bridged_from_cam": None,
                }
                if reid_detector is not None and body_vec is not None and hasattr(reid_detector, "update_prototype_ema"):
                    reid_detector.update_prototype_ema(sid, body_vec, alpha=0.15)
                if gis is not None and body_vec is not None and hasattr(gis, "publish_face_verified"):
                    gis.publish_face_verified(
                        student_id=sid,
                        full_name=fname,
                        body_embedding=body_vec,
                        source_cam_id=camera_id,
                        source_track_id=track_id,
                        confidence=entry["best_score"],
                        timestamp=timestamp,
                        handoff_ttl=config.handoff_ttl_seconds,
                        min_sim=config.handoff_min_body_sim,
                        min_margin=config.handoff_min_margin,
                    )
                return sid, fname, entry["best_score"], "face_verified_lock", out_emb, True, None, None, 0

            # First verified hit (0.56 <= face_sim < 0.62): mark face_verified=True while building lock
            if gis is not None and body_vec is not None and hasattr(gis, "publish_face_verified"):
                gis.publish_face_verified(
                    student_id=sid,
                    full_name=fname,
                    body_embedding=body_vec,
                    source_cam_id=camera_id,
                    source_track_id=track_id,
                    confidence=fused,
                    timestamp=timestamp,
                    handoff_ttl=config.handoff_ttl_seconds,
                    min_sim=config.handoff_min_body_sim,
                    min_margin=config.handoff_min_margin,
                )
            return sid, fname, fused, "face_verified", out_emb, True, None, None, 0

    # Track consecutive clear frontal-face frames where face_sim < 0.50 (for genuine unregistered guest label)
    next_unmatched = prev_unmatched_face_frames
    if strict_face_ok and face_embedding is not None:
        fx1, fy1, fx2, fy2 = face_detection.bbox[:4]
        fw, fh = float(fx2) - float(fx1), float(fy2) - float(fy1)
        if (
            scrfd_conf >= 0.70
            and fw >= 44.0
            and fh >= 44.0
            and frontal_score >= 0.45
            and best_raw_fsim < config.unregistered_face_max_sim
            and config.camera_role != "side_profile"
        ):
            next_unmatched += 1
        elif best_raw_fsim >= config.face_verify_min_sim:
            next_unmatched = 0

    # 4. NEVER assign an enrolled identity from static BodyReID alone.
    #    Only allow cross-camera BodyReID bridge when camera_role == "side_profile" (or via GIS handoff buffer).
    if config.camera_role == "side_profile" and gis is not None and body_vec is not None and _is_non_sliver_person_box(person_bbox, config):
        # Direction A: Forward Handoff (query only subjects face-verified within last 15.0s on other cameras)
        if hasattr(gis, "query_forward_handoff"):
            bridge = gis.query_forward_handoff(
                target_cam_id=camera_id,
                body_embedding=body_vec,
                timestamp=timestamp,
                ttl_seconds=config.handoff_ttl_seconds,
                min_sim=config.handoff_min_body_sim,
                min_margin=config.handoff_min_margin,
                exclude_sids=locked_sids_in_frame,
            )
            if bridge is not None:
                sid = bridge["student_id"]
                fname = bridge["full_name"]
                bconf = float(bridge["confidence"])
                src_cam = bridge["source_cam_id"]
                locked_identities[track_id] = {
                    "student_id": sid,
                    "full_name": fname,
                    "locked_confidence": bconf,
                    "source": "cross_cam_bridge",
                    "face_verified": False,
                    "bridged_from_cam": src_cam,
                }
                return sid, fname, bconf, "cross_cam_bridge", prev_emb, False, None, src_cam, 0

        # Direction B: No prior face match anywhere within 15s -> hold safely as Pending Track #G-XX
        if hasattr(gis, "register_or_update_pending_track"):
            is_border_clipped = float(person_bbox[0]) <= 15.0 or float(person_bbox[2]) >= 1905.0
            pt = gis.register_or_update_pending_track(
                cam_id=camera_id,
                local_track_id=track_id,
                body_embedding=body_vec,
                timestamp=timestamp,
                update_embedding=(not is_border_clipped),
            )
            if pt is not None:
                if pt.resolved_student_id is not None:
                    sid = pt.resolved_student_id
                    fname = pt.resolved_full_name or _resolve_display_name(recognizer, sid) or sid
                    rconf = float(pt.resolved_confidence or 0.70)
                    src_cam = pt.resolved_from_cam
                    locked_identities[track_id] = {
                        "student_id": sid,
                        "full_name": fname,
                        "locked_confidence": rconf,
                        "source": "retroactive_backfill",
                        "face_verified": False,
                        "bridged_from_cam": src_cam,
                    }
                    return sid, fname, rconf, "retroactive_backfill", prev_emb, False, pt.pending_id, src_cam, 0
                return None, None, 0.0, "pending_face", prev_emb, False, pt.pending_id, None, next_unmatched

    # 5. Unverified pre-face track: emit awaiting_face or unregistered_guest (>= 5 clear face frames < 0.50)
    out_src = "unregistered_guest" if next_unmatched >= config.unregistered_face_min_frames else "awaiting_face"
    return None, None, 0.0, out_src, prev_emb, False, prev_pending_global_id, None, next_unmatched


def update_tracks(
    previous_tracks: List[Track],
    person_detections: List[PersonDetection],
    face_detections: List[FaceDetection],
    face_embeddings: Dict[str, FaceEmbedding],  # detection_id -> embedding
    body_embeddings: Dict[str, BodyEmbedding],  # detection_id -> embedding
    recognizer: Optional[Any] = None,  # ArcFaceRecognizer for identification
    frame_index: int = 0,
    timestamp: float = 0.0,
    config: Optional[TrackingConfig] = None,
    reid_detector: Optional[Any] = None,
    locked_track_identities: Optional[Dict[int, Dict[str, Any]]] = None,
    track_consensus: Optional[Dict[int, Dict[str, Dict[str, Any]]]] = None,
    gis: Optional[Any] = None,
    camera_id: str = "cam1",
) -> Tuple[List[Track], List[Track], List[Track]]:
    """
    Update existing tracks with new detections.
    
    Performs multi-modal Face + Body ReID resolution with sticky track identity locking.
    """
    if config is None:
        config = TrackingConfig()
    if locked_track_identities is None:
        locked_track_identities = {}
    if track_consensus is None:
        track_consensus = {}
    
    # Separate active/lost tracks from closed
    active_lost_tracks = [t for t in previous_tracks if not t.is_closed]
    closed_tracks = [t for t in previous_tracks if t.is_closed]

    # Inner Duplicate Box Suppression (IoA >= 0.55) before track assignment
    filtered_detections = suppress_inner_duplicate_boxes(
        person_detections,
        active_tracks=[t for t in active_lost_tracks if t.is_active or t.is_new],
        ioa_threshold=config.inner_box_ioa_threshold,
    )

    # Two-stage ByteTrack assignment
    assignments, unmatched_track_indices, unmatched_detection_indices = solve_track_assignment(
        active_lost_tracks, filtered_detections, face_detections, config
    )

    active_frame_tids = {active_lost_tracks[ti].track_id for ti, _ in assignments}
    
    updated_tracks = []
    new_tracks = []
    newly_closed = []
    
    # Update matched tracks
    for track_idx, det_idx in assignments:
        track = active_lost_tracks[track_idx]
        detection = filtered_detections[det_idx]
        face_detection = find_face_for_person(detection, face_detections)
        
        # Get face embedding if available
        face_embedding = None
        if face_detection and face_detection.detection_id in face_embeddings:
            face_embedding = face_embeddings[face_detection.detection_id]
        
        # Get body embedding if available (for ReID)
        body_embedding = None
        if detection.detection_id in body_embeddings:
            body_embedding = body_embeddings[detection.detection_id]
        
        # NEW: GIS integration - get global person ID
        global_person_id = track.global_person_id
        identity_state = track.identity_state
        
        # NEW: Update live embeddings on track
        face_quality = 0.0
        body_quality = 0.0
        face_model_id = "arcface_r100"
        face_model_sha256 = ""
        body_model_id = "resnet50_reid"
        body_model_sha256 = ""
        
        # Initialize embedding accumulation fields
        face_embeddings_history = list(track.face_embeddings_history) if track.face_embeddings_history else []
        body_embeddings_history = list(track.body_embeddings_history) if track.body_embeddings_history else []
        avg_face_embedding = track.avg_face_embedding
        avg_body_embedding = track.avg_body_embedding
        max_face_quality = track.max_face_quality
        max_body_quality = track.max_body_quality
        embedding_count = track.embedding_count
        
        if face_embedding:
            face_quality = face_embedding.face_quality
            max_face_quality = max(max_face_quality, face_quality)
            
            # Accumulate face embedding
            face_emb = face_embedding.embedding.cpu()
            face_embeddings_history.append(face_emb)
            # Keep only last 50 embeddings
            if len(face_embeddings_history) > 50:
                face_embeddings_history = face_embeddings_history[-50:]
            
            # Update running average
            if avg_face_embedding is None:
                avg_face_embedding = face_emb
            else:
                # Exponential moving average with alpha=0.1
                avg_face_embedding = 0.9 * avg_face_embedding + 0.1 * face_emb
                # Renormalize
                norm = torch.norm(avg_face_embedding)
                if norm > 0:
                    avg_face_embedding = avg_face_embedding / norm
        
        matched_body_np = track.body_embedding
        if body_embedding is not None:
            body_quality = getattr(body_embedding, "body_quality", 1.0)
            max_body_quality = max(max_body_quality, body_quality)
            
            # Accumulate body embedding
            raw_emb = getattr(body_embedding, "embedding", body_embedding)
            body_emb = raw_emb.detach().cpu() if hasattr(raw_emb, "detach") else (raw_emb.cpu() if hasattr(raw_emb, "cpu") else torch.as_tensor(raw_emb))
            matched_body_np = body_emb.numpy()
            body_embeddings_history.append(body_emb)
            # Keep only last 50 embeddings
            if len(body_embeddings_history) > 50:
                body_embeddings_history = body_embeddings_history[-50:]
            
            # Update running average
            if avg_body_embedding is None:
                avg_body_embedding = body_emb
            else:
                # Exponential moving average with alpha=0.1
                avg_body_embedding = 0.9 * avg_body_embedding + 0.1 * body_emb
                # Renormalize
                norm = torch.norm(avg_body_embedding)
                if norm > 0:
                    avg_body_embedding = avg_body_embedding / norm

        locked_sids_other = {
            info["student_id"]
            for tid, info in locked_track_identities.items()
            if tid in active_frame_tids and tid != track.track_id
        }
        resolved_body_vec = matched_body_np
        if avg_body_embedding is not None:
            avg_np = (
                avg_body_embedding.detach().cpu().numpy()
                if hasattr(avg_body_embedding, "detach")
                else np.asarray(avg_body_embedding, dtype=np.float32)
            )
            avg_norm = float(np.linalg.norm(avg_np))
            if avg_norm > 1e-12:
                resolved_body_vec = (avg_np / avg_norm).astype(np.float32)

        (
            person_id,
            person_name,
            identity_confidence,
            identity_source,
            embedding,
            face_verified,
            pending_global_id,
            bridged_from_cam,
            unmatched_face_frames,
        ) = _resolve_track_identity(
            track_id=track.track_id,
            camera_id=camera_id,
            timestamp=timestamp,
            person_bbox=detection.bbox,
            prev_person_id=track.person_id,
            prev_person_name=track.person_name,
            prev_conf=track.identity_confidence,
            prev_source=track.identity_source,
            prev_emb=track.embedding,
            prev_face_verified=track.face_verified,
            prev_pending_global_id=track.pending_global_id,
            prev_bridged_from_cam=track.bridged_from_cam,
            prev_unmatched_face_frames=track.unmatched_face_frames,
            face_embedding=face_embedding,
            face_detection=face_detection,
            body_vec=resolved_body_vec,
            recognizer=recognizer,
            reid_detector=reid_detector,
            locked_identities=locked_track_identities,
            track_consensus=track_consensus,
            locked_sids_in_frame=locked_sids_other,
            config=config,
            gis=gis,
        )
        
        embedding_count += 1
        
        updated_track = Track(
            track_id=track.track_id,
            source_frame_id=track.source_frame_id,
            frame_index=frame_index,
            timestamp=timestamp,
            bbox_original_frame=detection.bbox,
            confidence=detection.confidence,
            lifecycle_state=TrackLifecycleState.ACTIVE,
            age=track.age + 1,
            hits=track.hits + 1,
            missed_frames=0,
            last_seen=timestamp,
            person_id=person_id,
            person_name=person_name,
            identity_confidence=identity_confidence,
            identity_source=identity_source,
            embedding=embedding,
            # NEW: Live embeddings
            face_embedding=face_embedding.embedding.cpu().numpy() if face_embedding else None,
            face_quality=face_quality,
            face_model_id=face_model_id,
            face_model_sha256=face_model_sha256,
            body_embedding=matched_body_np,
            body_quality=body_quality,
            body_model_id=body_model_id,
            body_model_sha256=body_model_sha256,
            face_detection_id=face_detection.detection_id if face_detection else None,
            face_bbox=face_detection.bbox if face_detection else None,
            face_confidence=face_detection.confidence if face_detection else 0.0,
            face_landmarks5=face_detection.landmarks5 if face_detection else None,
            person_provenance=detection.detection_id,
            face_provenance=face_detection.detection_id if face_detection else None,
            # NEW: Embedding accumulation (P2.4)
            face_embeddings_history=face_embeddings_history,
            body_embeddings_history=body_embeddings_history,
            avg_face_embedding=avg_face_embedding,
            avg_body_embedding=avg_body_embedding,
            max_face_quality=max_face_quality,
            max_body_quality=max_body_quality,
            embedding_count=embedding_count,
            # NEW: GIS integration (P3.11)
            global_person_id=global_person_id,
            identity_state=identity_state,
            face_verified=face_verified,
            pending_global_id=pending_global_id,
            bridged_from_cam=bridged_from_cam,
            unmatched_face_frames=unmatched_face_frames,
            stationary_frames=track.stationary_frames,
            _prev_center=track.center,
        )
        updated_track._update_stationary_check()
        updated_tracks.append(updated_track)
    
    # Age unmatched tracks into LOST (kept in track_buffer for re-association, omitted from active display)
    base_buffer = max(int(config.track_buffer), int(config.max_lost_frames))
    for track_idx in unmatched_track_indices:
        track = active_lost_tracks[track_idx]

        allowed_misses = base_buffer * 3 if track.is_stationary() else base_buffer
        next_missed = track.missed_frames + 1

        aged_track = Track(
            track_id=track.track_id,
            source_frame_id=track.source_frame_id,
            frame_index=frame_index,
            timestamp=timestamp,
            bbox_original_frame=track.bbox_original_frame,
            confidence=track.confidence,
            lifecycle_state=(
                TrackLifecycleState.CLOSED if next_missed >= allowed_misses
                else TrackLifecycleState.LOST
            ),
            age=track.age,
            hits=track.hits,
            missed_frames=next_missed,
            last_seen=track.last_seen,
            person_id=track.person_id,
            person_name=track.person_name,
            identity_confidence=track.identity_confidence,
            identity_source=track.identity_source,
            embedding=track.embedding,
            face_detection_id=track.face_detection_id,
            face_bbox=track.face_bbox,
            face_confidence=track.face_confidence,
            face_landmarks5=track.face_landmarks5,
            person_provenance=track.person_provenance,
            face_provenance=track.face_provenance,
            # Preserve embedding accumulation fields
            face_embeddings_history=track.face_embeddings_history,
            body_embeddings_history=track.body_embeddings_history,
            avg_face_embedding=track.avg_face_embedding,
            avg_body_embedding=track.avg_body_embedding,
            max_face_quality=track.max_face_quality,
            max_body_quality=track.max_body_quality,
            embedding_count=track.embedding_count,
            face_embedding=track.face_embedding,
            face_quality=track.face_quality,
            face_model_id=track.face_model_id,
            face_model_sha256=track.face_model_sha256,
            body_embedding=track.body_embedding,
            body_quality=track.body_quality,
            body_model_id=track.body_model_id,
            body_model_sha256=track.body_model_sha256,
            # Preserve GIS fields
            global_person_id=track.global_person_id,
            identity_state=track.identity_state,
            face_verified=track.face_verified,
            pending_global_id=track.pending_global_id,
            bridged_from_cam=track.bridged_from_cam,
            unmatched_face_frames=track.unmatched_face_frames,
            stationary_frames=track.stationary_frames,
            _prev_center=track.center,
        )

        if aged_track.missed_frames >= allowed_misses:
            aged_track.lifecycle_state = TrackLifecycleState.CLOSED
            newly_closed.append(aged_track)
        else:
            updated_tracks.append(aged_track)

    # Create new tracks for unmatched high-score detections (skip any inner sub-box)
    matched_active_boxes = [t.bbox_original_frame for t in updated_tracks if t.is_active]
    for det_idx in unmatched_detection_indices:
        detection = filtered_detections[det_idx]
        if any(compute_ioa(detection.bbox, mb) >= config.inner_box_ioa_threshold for mb in matched_active_boxes):
            continue
        face_detection = find_face_for_person(detection, face_detections)

        face_quality = 0.0
        body_quality = 0.0
        face_model_id = "arcface_r100"
        face_model_sha256 = ""
        body_model_id = "resnet50_reid"
        body_model_sha256 = ""

        face_embedding = None
        body_embedding = None

        if face_detection and face_detection.detection_id in face_embeddings:
            face_embedding = face_embeddings[face_detection.detection_id]
            face_quality = float(getattr(face_embedding, "face_quality", getattr(face_detection, "confidence", 1.0)))

        # Get body embedding if available (keyed by person detection_id or face fallback)
        raw_body = None
        body_emb_tensor = None
        if detection.detection_id in body_embeddings:
            raw_body = body_embeddings[detection.detection_id]
        elif face_detection and face_detection.detection_id in body_embeddings:
            raw_body = body_embeddings[face_detection.detection_id]
        if raw_body is not None:
            body_quality = getattr(raw_body, "body_quality", 1.0)
            emb_val = getattr(raw_body, "embedding", raw_body)
            if hasattr(emb_val, "detach"):
                body_emb_tensor = emb_val.detach().cpu()
                body_embedding = body_emb_tensor.numpy()
            elif hasattr(emb_val, "cpu"):
                body_emb_tensor = emb_val.cpu()
                body_embedding = body_emb_tensor.numpy()
            else:
                body_embedding = emb_val
                body_emb_tensor = torch.as_tensor(emb_val)

        # Generate unique monotonic track ID (must account for new_tracks created in same frame)
        max_existing_id = max(
            [t.track_id for t in previous_tracks]
            + [t.track_id for t in new_tracks]
            + [0]
        )
        track_id = max_existing_id + 1

        locked_sids_other = {
            info["student_id"]
            for tid, info in locked_track_identities.items()
            if tid in active_frame_tids
        }
        (
            person_id,
            person_name,
            identity_confidence,
            identity_source,
            embedding,
            face_verified,
            pending_global_id,
            bridged_from_cam,
            unmatched_face_frames,
        ) = _resolve_track_identity(
            track_id=track_id,
            camera_id=camera_id,
            timestamp=timestamp,
            person_bbox=detection.bbox,
            prev_person_id=None,
            prev_person_name=None,
            prev_conf=0.0,
            prev_source="unknown",
            prev_emb=None,
            prev_face_verified=False,
            prev_pending_global_id=None,
            prev_bridged_from_cam=None,
            prev_unmatched_face_frames=0,
            face_embedding=face_embedding,
            face_detection=face_detection,
            body_vec=body_embedding,
            recognizer=recognizer,
            reid_detector=reid_detector,
            locked_identities=locked_track_identities,
            track_consensus=track_consensus,
            locked_sids_in_frame=locked_sids_other,
            config=config,
            gis=gis,
        )

        new_track = Track(
            track_id=track_id,
            source_frame_id=detection.source_id.lower().strip() or "cam1",
            frame_index=frame_index,
            timestamp=timestamp,
            bbox_original_frame=detection.bbox,
            confidence=detection.confidence,
            lifecycle_state=TrackLifecycleState.NEW,
            age=1,
            hits=1,
            missed_frames=0,
            last_seen=timestamp,
            person_id=person_id,
            person_name=person_name,
            identity_confidence=identity_confidence,
            identity_source=identity_source,
            embedding=embedding,
            # NEW: Live embeddings
            face_embedding=face_embedding.embedding.cpu().numpy() if face_embedding is not None else None,
            face_quality=face_quality,
            face_model_id=face_model_id,
            face_model_sha256=face_model_sha256,
            body_embedding=body_embedding,
            body_quality=body_quality,
            body_model_id=body_model_id,
            body_model_sha256=body_model_sha256,
            face_detection_id=face_detection.detection_id if face_detection else None,
            face_bbox=face_detection.bbox if face_detection else None,
            face_confidence=face_detection.confidence if face_detection else 0.0,
            face_landmarks5=face_detection.landmarks5 if face_detection else None,
            person_provenance=detection.detection_id,
            face_provenance=face_detection.detection_id if face_detection else None,
            # NEW: Embedding accumulation (P2.4)
            face_embeddings_history=[face_embedding.embedding.cpu()] if face_embedding is not None else [],
            body_embeddings_history=[body_emb_tensor] if body_emb_tensor is not None else [],
            avg_face_embedding=face_embedding.embedding.cpu() if face_embedding is not None else None,
            avg_body_embedding=body_emb_tensor,
            max_face_quality=face_quality,
            max_body_quality=body_quality,
            embedding_count=1 if face_embedding is not None else 0,
            # NEW: GIS integration (P3.11)
            global_person_id=None,  # Will be assigned by GIS
            identity_state="unknown",
            face_verified=face_verified,
            pending_global_id=pending_global_id,
            bridged_from_cam=bridged_from_cam,
            unmatched_face_frames=unmatched_face_frames,
        )
        new_track._update_stationary_check()
        new_tracks.append(new_track)
        updated_tracks.append(new_track)
    
    # Deduplicate any overlapping active/new track where one bbox is heavily contained (>= 72% IoA)
    current_visible = [
        t for t in updated_tracks
        if (t.is_active or t.is_new) and t.missed_frames == 0
    ]
    current_visible.sort(
        key=lambda t: (bool(t.face_verified), float(t.area), int(t.hits)),
        reverse=True,
    )
    kept_visible: List[Track] = []
    for tr in current_visible:
        if any(compute_ioa(tr.bbox_original_frame, kv.bbox_original_frame) >= 0.72 for kv in kept_visible):
            tr.lifecycle_state = TrackLifecycleState.CLOSED
            newly_closed.append(tr)
        else:
            kept_visible.append(tr)

    # Enforce memory bounds
    active_tracks = [t for t in updated_tracks if t.is_active]
    lost_tracks = [t for t in updated_tracks if t.is_lost]
    new_tracks_list = [t for t in updated_tracks if t.is_new]
    
    active_tracks.sort(key=lambda t: t.track_id)
    lost_tracks.sort(key=lambda t: t.track_id)
    new_tracks_list.sort(key=lambda t: t.track_id)
    
    if len(active_tracks) > config.max_active_tracks:
        excess = active_tracks[config.max_active_tracks:]
        active_tracks = active_tracks[:config.max_active_tracks]
        for t in excess:
            t.lifecycle_state = TrackLifecycleState.CLOSED
            newly_closed.append(t)
    
    if len(lost_tracks) > config.max_lost_tracks:
        excess = lost_tracks[config.max_lost_tracks:]
        lost_tracks = lost_tracks[:config.max_lost_tracks]
        for t in excess:
            t.lifecycle_state = TrackLifecycleState.CLOSED
            newly_closed.append(t)
    
    # Clean up sticky identity state for closed tracks
    for closed_t in newly_closed:
        locked_track_identities.pop(closed_t.track_id, None)
        track_consensus.pop(closed_t.track_id, None)

    # Combine all tracks
    final_tracks = active_tracks + lost_tracks + new_tracks_list + closed_tracks + newly_closed
    
    return final_tracks, new_tracks, newly_closed


class Tracker:
    """
    Main tracker class managing track state across frames.
    """
    
    def __init__(
        self,
        config: Optional[TrackingConfig] = None,
        recognizer: Optional[Any] = None,
        reid_detector: Optional[Any] = None,
        gis: Optional[Any] = None,
    ):
        self.config = config or TrackingConfig()
        self.recognizer = recognizer
        self.reid_detector = reid_detector
        self.gis = gis
        self._tracks: List[Track] = []
        self._next_track_id = 1
        self._frame_index = 0
        self._locked_track_identities: Dict[int, Dict[str, Any]] = {}
        self._track_consensus: Dict[int, Dict[str, Dict[str, Any]]] = {}
    
    def update(
        self,
        person_detections: List[PersonDetection],
        face_detections: Optional[List[FaceDetection]] = None,
        face_embeddings: Optional[Dict[str, FaceEmbedding]] = None,
        body_embeddings: Optional[Dict[str, Any]] = None,
        camera_id: str = "cam1",
        timestamp: float = 0.0,
    ) -> TrackingResult:
        """Run inner-box suppression + two-stage ByteTrack association for one frame."""
        self._frame_index += 1
        norm_cam = camera_id.lower().strip()

        updated_tracks, new_tracks, closed_tracks = update_tracks(
            previous_tracks=self._tracks,
            person_detections=person_detections,
            face_detections=face_detections or [],
            face_embeddings=face_embeddings or {},
            body_embeddings=body_embeddings or {},
            recognizer=self.recognizer,
            frame_index=self._frame_index,
            timestamp=timestamp,
            config=self.config,
            reid_detector=self.reid_detector,
            locked_track_identities=self._locked_track_identities,
            track_consensus=self._track_consensus,
            gis=self.gis,
            camera_id=norm_cam,
        )

        self._tracks = updated_tracks

        return TrackingResult(
            source_frame_id=norm_cam,
            frame_index=self._frame_index,
            timestamp=timestamp,
            tracks=updated_tracks,
            new_tracks=new_tracks,
            closed_tracks=closed_tracks,
        )

    def apply_backfill(
        self,
        track_id: int,
        student_id: str,
        full_name: str,
        confidence: float,
        source_cam_id: Optional[str] = None,
    ) -> None:
        """Retroactively lock a pending track identity from cross-camera GIS confirmation."""
        tid = int(track_id)
        self._locked_track_identities[tid] = {
            "student_id": student_id,
            "full_name": full_name,
            "locked_confidence": float(confidence),
            "source": "retroactive_backfill",
            "face_verified": False,
            "bridged_from_cam": source_cam_id,
        }
        for tr in self._tracks:
            if tr.track_id == tid:
                tr.person_id = student_id
                tr.person_name = full_name
                tr.identity_confidence = float(confidence)
                tr.identity_source = "retroactive_backfill"
                tr.bridged_from_cam = source_cam_id

    def process_frame(
        self,
        person_detections: List[PersonDetection],
        face_detections: List[FaceDetection],
        face_embeddings: Dict[str, FaceEmbedding],
        body_embeddings: Dict[str, Any],
        camera_id: str,
        timestamp: float,
    ) -> TrackingResult:
        """Process a single frame and return tracking result."""
        return self.update(
            person_detections=person_detections,
            face_detections=face_detections,
            face_embeddings=face_embeddings,
            body_embeddings=body_embeddings,
            camera_id=camera_id,
            timestamp=timestamp,
        )

    @staticmethod
    def _calculate_iou_batch(bboxes1: np.ndarray, bboxes2: np.ndarray) -> np.ndarray:
        """Vectorized pixel-space IoU matrix between (N, 4) and (M, 4) [x1, y1, x2, y2] arrays."""
        if len(bboxes1) == 0 or len(bboxes2) == 0:
            return np.zeros((len(bboxes1), len(bboxes2)), dtype=np.float32)
        b1_arr = np.ascontiguousarray(bboxes1, dtype=np.float32)
        b2_arr = np.ascontiguousarray(bboxes2, dtype=np.float32)
        if _HAS_RUST_TRACKING and _batch_iou_and_match_rs is not None:
            iou_mat, _, _, _ = _batch_iou_and_match_rs(b1_arr, b2_arr, 0.0)
            return iou_mat
        b1 = b1_arr[:, None, :]
        b2 = b2_arr[None, :, :]
        inter_x1 = np.maximum(b1[..., 0], b2[..., 0])
        inter_y1 = np.maximum(b1[..., 1], b2[..., 1])
        inter_x2 = np.minimum(b1[..., 2], b2[..., 2])
        inter_y2 = np.minimum(b1[..., 3], b2[..., 3])
        inter_w = np.maximum(0.0, inter_x2 - inter_x1)
        inter_h = np.maximum(0.0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        area1 = np.maximum(0.0, b1[..., 2] - b1[..., 0]) * np.maximum(0.0, b1[..., 3] - b1[..., 1])
        area2 = np.maximum(0.0, b2[..., 2] - b2[..., 0]) * np.maximum(0.0, b2[..., 3] - b2[..., 1])
        union = area1 + area2 - inter_area
        return np.where(union > 0.0, inter_area / np.maximum(union, 1e-12), 0.0).astype(np.float32)

    @staticmethod
    def match_iou_batch(
        bboxes1: np.ndarray,
        bboxes2: np.ndarray,
        iou_thresh: float = 0.3,
    ) -> Tuple[np.ndarray, List[Tuple[int, int]], List[int], List[int]]:
        """Compute IoU matrix and greedy assignment via Rust kernel (with Python fallback)."""
        b1 = np.ascontiguousarray(bboxes1, dtype=np.float32)
        b2 = np.ascontiguousarray(bboxes2, dtype=np.float32)
        if _HAS_RUST_TRACKING and _batch_iou_and_match_rs is not None:
            return _batch_iou_and_match_rs(b1, b2, float(iou_thresh))
        iou = SimpleTracker._calculate_iou_batch(b1, b2)
        n, m = iou.shape
        det_assigned = [False] * m
        track_assigned = [False] * n
        matches: List[Tuple[int, int]] = []
        for i in range(n):
            best_j = -1
            best_iou = float(iou_thresh)
            for j in range(m):
                if det_assigned[j]:
                    continue
                val = float(iou[i, j])
                if val >= iou_thresh and (best_j == -1 or val > best_iou):
                    best_iou = val
                    best_j = j
            if best_j >= 0:
                det_assigned[best_j] = True
                track_assigned[i] = True
                matches.append((i, best_j))
        unmatched_tracks = [i for i in range(n) if not track_assigned[i]]
        unmatched_dets = [j for j in range(m) if not det_assigned[j]]
        return iou, matches, unmatched_tracks, unmatched_dets
    
    def get_active_tracks(self) -> List[Track]:
        return [t for t in self._tracks if t.is_active or t.is_new]
    
    def get_all_tracks(self) -> List[Track]:
        return self._tracks.copy()
    
    def reset(self) -> None:
        self._tracks.clear()
        self._next_track_id = 1
        self._frame_index = 0
        self._locked_track_identities.clear()
        self._track_consensus.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        active = len([t for t in self._tracks if t.is_active])
        lost = len([t for t in self._tracks if t.is_lost])
        closed = len([t for t in self._tracks if t.is_closed])
        identified = len([t for t in self._tracks if t.is_identified])
        
        return {
            "total_tracks": len(self._tracks),
            "active": active,
            "lost": lost,
            "closed": closed,
            "identified": identified,
            "frame_index": self._frame_index,
        }


if __name__ == "__main__":
    # Quick test
    from pipeline_engine.inference.face_detection import FaceDetection
    from pipeline_engine.inference.person_detection import PersonDetection
    from pipeline_engine.inference.face_recognition import FaceEmbedding
    import torch
    
    config = TrackingConfig()
    tracker = Tracker(config)
    
    # Create test detections
    person_det = PersonDetection(
        bbox=(1000, 500, 1200, 900),
        confidence=0.9,
        detection_id="det_1",
        frame_index=1,
        source_id="cam1",
    )
    
    face_det = FaceDetection(
        bbox=(1050, 550, 1150, 650),
        confidence=0.95,
        landmarks5=[(1080, 580), (1120, 580), (1100, 600), (1070, 620), (1130, 620)],
        detection_id="face_1",
        frame_index=1,
        source_id="cam1",
    )
    
    # Mock face embedding
    embedding = FaceEmbedding(
        embedding=torch.randn(512, device='cuda') if torch.cuda.is_available() else torch.randn(512),
        raw_embedding=torch.randn(512),
        raw_norm=1.0,
        inference_time_ms=1.0,
        detection_id="face_1",
        frame_index=1,
        source_id="cam1",
    )
    
    result = tracker.process_frame(
        person_detections=[person_det],
        face_detections=[face_det],
        face_embeddings={"face_1": embedding},
        camera_id="cam1",
        timestamp=time.time(),
    )
    
    print(f"Tracking result: {len(result.tracks)} tracks, {len(result.new_tracks)} new")
    for t in result.tracks:
        print(f"  Track {t.track_id}: {t.lifecycle_state.value}, id={t.person_id}")
    
    print("Tracker test passed!")