"""
Tracking System - Geometry-based tracking with identity fusion.

Operates in ORIGINAL_FRAME coordinate space. Integrates face recognition
and person ReID for identity continuity.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum

import numpy as np

from pipeline_engine.inference.face_detection import FaceDetection
from pipeline_engine.inference.person_detection import PersonDetection
from pipeline_engine.inference.face_recognition import FaceEmbedding
from pipeline_engine.config import get_config

logger = logging.getLogger(__name__)


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
    
    # NEW: Embedding accumulation (P2.4)
    face_embeddings_history: List[torch.Tensor] = None  # History of face embeddings
    body_embeddings_history: List[torch.Tensor] = None  # History of body embeddings
    avg_face_embedding: Optional[torch.Tensor] = None  # Running average face embedding
    avg_body_embedding: Optional[torch.Tensor] = None  # Running average body embedding
    max_face_quality: float = 0.0                    # Max face quality seen
    max_body_quality: float = 0.0                    # Max body quality seen
    embedding_count: int = 0                         # Number of embeddings accumulated
    
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
            "person_id": self.person_id,
            "person_name": self.person_name,
            "identity_confidence": self.identity_confidence,
            "identity_source": self.identity_source,
            "center": self.center,
        }


@dataclass
class TrackingConfig:
    """Configuration for tracking."""
    min_iou_threshold: float = 0.3
    max_age: int = 30
    max_lost_frames: int = 10
    max_active_tracks: int = 50
    max_lost_tracks: int = 30
    max_new_tracks: int = 10
    use_face_association: bool = True
    face_center_weight: float = 0.5
    # Identity fusion
    face_recognition_priority: bool = True
    reid_fallback_enabled: bool = False
    reid_similarity_threshold: float = 0.7
    identity_confidence_threshold: float = 0.5


@dataclass
class TrackingResult:
    """Result of tracking for a single frame."""
    source_frame_id: str
    frame_index: int
    timestamp: float
    tracks: List[Track] = field(default_factory=list)
    new_tracks: List[Track] = field(default_factory=list)
    closed_tracks: List[Track] = field(default_factory=list)
    
    def get_active_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.is_active or t.is_new]
    
    def get_identified_tracks(self) -> List[Track]:
        return [t for t in self.tracks if t.is_identified]


def _to_pixel_coords(
    bbox: Tuple[float, float, float, float],
    frame_w: float,
    frame_h: float
) -> Tuple[float, float, float, float]:
    """Convert normalized coordinates [0,1] to pixel coordinates if needed."""
    x1, y1, x2, y2 = bbox[:4]
    if max(x1, y1, x2, y2) <= 1.01:
        return (x1 * frame_w, y1 * frame_h, x2 * frame_w, y2 * frame_h)
    return (x1, y1, x2, y2)


def compute_iou(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float],
    frame_w: float = 3840.0,
    frame_h: float = 2160.0
) -> float:
    """Compute Intersection over Union of two bboxes in pixel coordinate space."""
    # Denormalize if coordinates are in [0,1] range
    x1_1, y1_1, x2_1, y2_1 = _to_pixel_coords(bbox1, frame_w, frame_h)
    x1_2, y1_2, x2_2, y2_2 = _to_pixel_coords(bbox2, frame_w, frame_h)
    
    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    
    if x2_i <= x1_i or y2_i <= y1_i:
        return 0.0
    
    intersection = (x2_i - x1_i) * (y2_i - y1_i)
    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
    union = area1 + area2 - intersection
    
    return intersection / union if union > 0 else 0.0


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
    """
    Solve global assignment between existing tracks and new person detections.
    
    Uses greedy assignment with deterministic ordering (by track_id).
    """
    if config is None:
        config = TrackingConfig()
    
    num_tracks = len(tracks)
    num_detections = len(person_detections)
    
    if num_tracks == 0 or num_detections == 0:
        return [], list(range(num_tracks)), list(range(num_detections))
    
    # Build face detection lookup
    face_lookup = {}
    if face_detections:
        for fd in face_detections:
            face_lookup[fd.detection_id] = fd
    
    # Build score matrix [num_tracks, num_detections]
    score_matrix = np.zeros((num_tracks, num_detections), dtype=np.float32)
    
    for ti, track in enumerate(tracks):
        for di, det in enumerate(person_detections):
            face_det = face_lookup.get(det.detection_id) if face_lookup else None
            score, _ = compute_track_detection_score(track, det, config, face_det)
            score_matrix[ti, di] = score
    
    # Greedy assignment with deterministic ordering
    track_order = sorted(range(num_tracks), key=lambda ti: tracks[ti].track_id)
    
    track_assigned = [False] * num_tracks
    detection_assigned = [False] * num_detections
    assignments = []
    
    for ti in track_order:
        track = tracks[ti]
        
        best_di = -1
        best_score = 0.0
        
        for di in range(num_detections):
            if detection_assigned[di]:
                continue
            score = score_matrix[ti, di]
            if score > best_score and score >= config.min_iou_threshold:
                best_score = score
                best_di = di
        
        if best_di >= 0:
            assignments.append((ti, best_di))
            track_assigned[ti] = True
            detection_assigned[best_di] = True
    
    unmatched_tracks = [ti for ti in range(num_tracks) if not track_assigned[ti]]
    unmatched_detections = [di for di in range(num_detections) if not detection_assigned[di]]
    
    return assignments, unmatched_tracks, unmatched_detections


def find_face_for_person(
    person_detection: PersonDetection,
    face_detections: List[FaceDetection],
) -> Optional[FaceDetection]:
    """Find face detection associated with person detection."""
    # Simple spatial association: face center inside person bbox
    person_bbox = person_detection.bbox
    person_center = person_detection.center
    
    best_face = None
    best_score = 0.0
    
    for face in face_detections:
        face_center = face.center
        # Check if face center inside person bbox
        if (person_bbox[0] <= face_center[0] <= person_bbox[2] and
            person_bbox[1] <= face_center[1] <= person_bbox[3]):
            # Score by face confidence
            if face.confidence > best_score:
                best_score = face.confidence
                best_face = face
    
    return best_face


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
) -> Tuple[List[Track], List[Track], List[Track]]:
    """
    Update existing tracks with new detections.
    
    Also performs identity resolution using face recognition embeddings.
    """
    if config is None:
        config = TrackingConfig()
    
    # Separate active/lost tracks from closed
    active_lost_tracks = [t for t in previous_tracks if not t.is_closed]
    closed_tracks = [t for t in previous_tracks if t.is_closed]
    
    # Solve assignment
    assignments, unmatched_track_indices, unmatched_detection_indices = solve_track_assignment(
        active_lost_tracks, person_detections, face_detections, config
    )
    
    updated_tracks = []
    new_tracks = []
    newly_closed = []
    
    # Update matched tracks
    for track_idx, det_idx in assignments:
        track = active_lost_tracks[track_idx]
        detection = person_detections[det_idx]
        face_detection = find_face_for_person(detection, face_detections)
        
        # Get face embedding if available
        face_embedding = None
        if face_detection and face_detection.detection_id in face_embeddings:
            face_embedding = face_embeddings[face_detection.detection_id]
        
        # Get body embedding if available (for ReID)
        body_embedding = None
        if detection.detection_id in body_embeddings:
            body_embedding = body_embeddings[detection.detection_id]
        
        # Identity resolution
        person_id = track.person_id
        person_name = track.person_name
        identity_confidence = track.identity_confidence
        identity_source = track.identity_source
        embedding = track.embedding
        
        # NEW: GIS integration - get global person ID
        global_person_id = track.global_person_id
        identity_state = track.identity_state
        face_evidence_ref = None
        body_evidence_ref = None
        face_quality = 0.0
        body_quality = 0.0
        association_method = ""
        conflict_flag = False
        provisional_person_id = None
        
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
            
            if recognizer:
                matches = recognizer.identify(face_embedding.embedding, top_k=1)
                if matches:
                    person_id, similarity = matches[0]
                    if similarity >= config.identity_confidence_threshold:
                        identity_confidence = similarity
                        identity_source = "face_recognition"
                        meta = recognizer._enrollment_metadata.get(person_id, {})
                        person_name = meta.get("name", person_id)
                        embedding = face_embedding.embedding.cpu().numpy()
        
        if body_embedding:
            body_quality = body_embedding.body_quality
            max_body_quality = max(max_body_quality, body_quality)
            
            # Accumulate body embedding
            body_emb = body_embedding.embedding.cpu()
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
        
        embedding_count += 1
        
        # Fallback to ReID if enabled and no face recognition match
        if config.reid_fallback_enabled and track.embedding is not None and not face_embedding:
            pass
        
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
        )
        updated_tracks.append(updated_track)
    
    # Age unmatched tracks
    for track_idx in unmatched_track_indices:
        track = active_lost_tracks[track_idx]
        
        aged_track = Track(
            track_id=track.track_id,
            source_frame_id=track.source_frame_id,
            frame_index=frame_index,
            timestamp=timestamp,
            bbox_original_frame=track.bbox_original_frame,
            confidence=track.confidence,
            lifecycle_state=(
                TrackLifecycleState.LOST if track.missed_frames + 1 >= config.max_lost_frames 
                else TrackLifecycleState.ACTIVE
            ),
            age=track.age,
            hits=track.hits,
            missed_frames=track.missed_frames + 1,
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
        )
        
        if aged_track.missed_frames >= config.max_lost_frames:
            aged_track.lifecycle_state = TrackLifecycleState.CLOSED
            newly_closed.append(aged_track)
        else:
            updated_tracks.append(aged_track)
    
    # Create new tracks for unmatched detections
    for det_idx in unmatched_detection_indices:
        detection = person_detections[det_idx]
        face_detection = find_face_for_person(detection, face_detections)
        
        # Identity for new track
        person_id = None
        person_name = None
        identity_confidence = 0.0
        identity_source = "unknown"
        embedding = None
        
        face_quality = 0.0
        body_quality = 0.0
        face_model_id = "arcface_r100"
        face_model_sha256 = ""
        body_model_id = "resnet50_reid"
        body_model_sha256 = ""
        
        face_embedding = None
        body_embedding = None
        
        if face_detection and face_detection.detection_id in face_embeddings and recognizer:
            face_embedding = face_embeddings[face_detection.detection_id]
            face_quality = 1.0  # TODO: Calculate actual quality
            matches = recognizer.identify(face_embedding.embedding, top_k=1)
            if matches:
                person_id, similarity = matches[0]
                if similarity >= config.identity_confidence_threshold:
                    identity_confidence = similarity
                    identity_source = "face_recognition"
                    meta = recognizer._enrollment_metadata.get(person_id, {})
                    person_name = meta.get("name", person_id)
                    embedding = face_embedding.embedding.cpu().numpy()
        
        # Get body embedding if available
        if face_detection and face_detection.detection_id in body_embeddings:
            body_embedding = body_embeddings[face_detection.detection_id]
            body_quality = 1.0  # TODO: Calculate actual quality
        
        # Generate new track ID
        max_existing_id = max([t.track_id for t in previous_tracks] + [-1])
        track_id = max_existing_id + 1
        
        new_track = Track(
            track_id=track_id,
            source_frame_id=f"cam_{detection.source_id}",
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
            face_embedding=face_embedding.embedding.cpu().numpy() if (face_detection and face_detection.detection_id in face_embeddings) else None,
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
            face_embeddings_history=[face_embedding.embedding.cpu()] if (face_detection and face_detection.detection_id in face_embeddings) else [],
            body_embeddings_history=[body_embeddings[face_detection.detection_id].embedding.cpu()] if (face_detection and face_detection.detection_id in body_embeddings) else [],
            avg_face_embedding=face_embedding.embedding.cpu() if (face_detection and face_detection.detection_id in face_embeddings) else None,
            avg_body_embedding=body_embeddings[face_detection.detection_id].embedding.cpu() if (face_detection and face_detection.detection_id in body_embeddings) else None,
            max_face_quality=face_quality,
            max_body_quality=body_quality,
            embedding_count=1 if (face_detection and face_detection.detection_id in face_embeddings) else 0,
            # NEW: GIS integration (P3.11)
            global_person_id=None,  # Will be assigned by GIS
            identity_state="unknown",
        )
        new_tracks.append(new_track)
        updated_tracks.append(new_track)
    
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
    
    # Combine all tracks
    final_tracks = active_tracks + lost_tracks + new_tracks_list + closed_tracks + newly_closed
    
    return final_tracks, new_tracks, newly_closed


class Tracker:
    """
    Main tracker class managing track state across frames.
    """
    
    def __init__(self, config: Optional[TrackingConfig] = None, recognizer: Optional[Any] = None):
        self.config = config or TrackingConfig()
        self.recognizer = recognizer
        self._tracks: List[Track] = []
        self._next_track_id = 1
        self._frame_index = 0
    
    def process_frame(
        self,
        person_detections: List[PersonDetection],
        face_detections: List[FaceDetection],
        face_embeddings: Dict[str, FaceEmbedding],
        body_embeddings: Dict[str, BodyEmbedding],
        camera_id: str,
        timestamp: float,
    ) -> TrackingResult:
        """Process a single frame and return tracking result."""
        self._frame_index += 1
        
        updated_tracks, new_tracks, closed_tracks = update_tracks(
            previous_tracks=self._tracks,
            person_detections=person_detections,
            face_detections=face_detections,
            face_embeddings=face_embeddings,
            body_embeddings=body_embeddings,
            recognizer=self.recognizer,
            frame_index=self._frame_index,
            timestamp=timestamp,
            config=self.config,
        )
        
        self._tracks = updated_tracks
        
        return TrackingResult(
            source_frame_id=camera_id,
            frame_index=self._frame_index,
            timestamp=timestamp,
            tracks=updated_tracks,
            new_tracks=new_tracks,
            closed_tracks=closed_tracks,
        )
    
    def get_active_tracks(self) -> List[Track]:
        return [t for t in self._tracks if t.is_active or t.is_new]
    
    def get_all_tracks(self) -> List[Track]:
        return self._tracks.copy()
    
    def reset(self) -> None:
        self._tracks.clear()
        self._next_track_id = 1
        self._frame_index = 0
    
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