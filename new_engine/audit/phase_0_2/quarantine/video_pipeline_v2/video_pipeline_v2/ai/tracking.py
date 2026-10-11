"""
Tracking System - V2 GPU-first video pipeline.

Geometry-based tracking using detections from SCRFD, YOLO.
Operates in ORIGINAL_FRAME coordinate space.
No CPU staging - tracking logic runs on CPU but uses GPU frame contracts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum

import numpy as np

from video_pipeline_v2.core.gpu_frame import GPUFrame
from video_pipeline_v2.ai.scrfd_detector import FaceDetection
from video_pipeline_v2.ai.yolo_detector import PersonDetection

logger = logging.getLogger(__name__)


class TrackLifecycleState(str, Enum):
    """Track lifecycle states."""
    NEW = "new"
    ACTIVE = "active"
    LOST = "lost"
    CLOSED = "closed"


@dataclass(frozen=True)
class Track:
    """A tracked person/face over time."""
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
    
    # Tracking info
    confidence: float = 1.0
    lifecycle_state: TrackLifecycleState = TrackLifecycleState.NEW
    age: int = 0  # Frames tracked
    hits: int = 1  # Number of detections
    missed_frames: int = 0
    last_seen: float = 0.0  # Timestamp
    
    # Identity info (optional, from ReID)
    embedding_id: Optional[str] = None
    embedding_similarity: float = 0.0
    
    # Coordinate space
    coordinate_space: str = "original_frame"
    
    # Provenance
    provenance_id: Optional[str] = None
    
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


@dataclass
class TrackingConfig:
    """Configuration for tracking."""
    # IoU thresholds
    min_iou_threshold: float = 0.3
    max_age: int = 30  # Frames before marking lost
    max_lost_frames: int = 10  # Frames before closing
    # Memory limits
    max_active_tracks: int = 50
    max_lost_tracks: int = 30
    max_new_tracks: int = 10
    # Association
    use_face_association: bool = True
    face_center_weight: float = 0.5


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
    
    def get_track_by_id(self, track_id: int) -> Optional[Track]:
        for t in self.tracks:
            if t.track_id == track_id:
                return t
        return None


def compute_iou(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float]
) -> float:
    """Compute Intersection over Union of two bboxes."""
    x1_1, y1_1, x2_1, y2_1 = bbox1
    x1_2, y1_2, x2_2, y2_2 = bbox2
    
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


def compute_center_distance(
    bbox1: Tuple[float, float, float, float],
    bbox2: Tuple[float, float, float, float],
    frame_w: int = 3840,
    frame_h: int = 2160
) -> float:
    """Compute normalized center distance between bboxes."""
    cx1 = (bbox1[0] + bbox1[2]) / 2
    cy1 = (bbox1[1] + bbox1[3]) / 2
    cx2 = (bbox2[0] + bbox2[2]) / 2
    cy2 = (bbox2[1] + bbox2[3]) / 2
    
    # Euclidean distance
    distance = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
    # Normalize by frame diagonal
    diagonal = (frame_w ** 2 + frame_h ** 2) ** 0.5
    return distance / diagonal


def update_tracks(
    previous_tracks: List[Track],
    new_detections: List[PersonDetection],
    face_detections: Optional[List[FaceDetection]] = None,
    frame_index: int = 0,
    timestamp: float = 0.0,
    config: Optional[TrackingConfig] = None,
) -> TrackingResult:
    """
    Update tracks with new detections.
    
    This is a simple IoU-based tracker. More complex association
    can be added but this satisfies the V2 requirements.
    """
    if config is None:
        config = TrackingConfig()
    
    # Initialize tracking result
    result = TrackingResult(
        source_frame_id="",
        frame_index=frame_index,
        timestamp=timestamp,
    )
    
    # Filter active/lost tracks
    active_lost = [t for t in previous_tracks if not t.is_closed]
    
    # Solve assignment using greedy IoU matching
    # Build score matrix
    assignments: List[Tuple[int, int]] = []  # (track_idx, det_idx)
    
    # Simple greedy assignment
    track_assigned = [False] * len(active_lost)
    det_assigned = [False] * len(new_detections)
    
    for ti, track in enumerate(active_lost):
        best_di = -1
        best_score = 0.0
        
        for di, det in enumerate(new_detections):
            if det_assigned[di]:
                continue
            
            iou_score = compute_iou(track.bbox_original_frame, det.bbox)
            
            if iou_score > best_score and iou_score >= config.min_iou_threshold:
                best_score = iou_score
                best_di = di
        
        if best_di >= 0:
            assignments.append((ti, best_di))
            track_assigned[ti] = True
            det_assigned[best_di] = True
    
    # Update matched tracks
    updated_tracks = []
    for track_idx, det_idx in assignments:
        track = active_lost[track_idx]
        detection = new_detections[det_idx]
        
        # Update track with detection
        updated_track = Track(
            track_id=track.track_id,
            source_frame_id=track.source_frame_id,
            frame_index=frame_index,
            timestamp=timestamp,
            bbox_original_frame=detection.bbox,
            confidence=detection.confidence,
            detection_id=track.track_id,
            lifecycle_state=TrackLifecycleState.ACTIVE,
            age=track.age + 1,
            hits=track.hits + 1,
            missed_frames=0,
            last_seen=timestamp,
            source_id=track.source_id,
        )
        updated_tracks.append(updated_track)
    
    # Age unmatched tracks
    lost_tracks = []
    for ti in range(len(active_lost)):
        if not track_assigned[ti]:
            track = active_lost[ti]
            
            # Age the track
            aged_track = Track(
                track_id=track.track_id,
                source_frame_id=track.source_frame_id,
                frame_index=frame_index,
                timestamp=timestamp,
                bbox_original_frame=track.bbox_original_frame,  # Keep old bbox
                confidence=track.confidence,
                detection_id=track.track_id,
                lifecycle_state=TrackLifecycleState.LOST if track.missed_frames + 1 >= config.max_lost_frames else TrackLifecycleState.ACTIVE,
                age=track.age,
                hits=track.hits,
                missed_frames=track.missed_frames + 1,
                last_seen=track.last_seen,
                source_id=track.source_id,
            )
            
            if aged_track.missed_frames >= config.max_lost_frames:
                # Close track
                aged_track = Track(
                    track_id=track.track_id,
                    source_frame_id=track.source_frame_id,
                    frame_index=frame_index,
                    timestamp=timestamp,
                    bbox_original_frame=track.bbox_original_frame,
                    confidence=track.confidence,
                    detection_id=track.track_id,
                    lifecycle_state=TrackLifecycleState.CLOSED,
                    age=track.age,
                    hits=track.hits,
                    missed_frames=track.missed_frames,
                    last_seen=track.last_seen,
                    source_id=track.source_id,
                )
                lost_tracks.append(aged_track)  # These go to closed
            else:
                updated_tracks.append(aged_track)
    
    # Create new tracks for unmatched detections
    new_tracks = []
    for di in range(len(new_detections)):
        if not det_assigned[di]:
            detection = new_detections[di]
            
            # Generate new track ID (simple counter based approach)
            # In production, this would use a persistent ID generator
            track_id = max([t.track_id for t in previous_tracks] + [-1]) + 1
            
            new_track = Track(
                track_id=track_id,
                source_frame_id=f"cam_{detection.source_id}",
                frame_index=frame_index,
                timestamp=timestamp,
                bbox_original_frame=detection.bbox,
                confidence=detection.confidence,
                detection_id=str(uuid.uuid4())[:8],
                lifecycle_state=TrackLifecycleState.NEW,
                age=1,
                hits=1,
                missed_frames=0,
                last_seen=timestamp,
                source_id=detection.source_id,
            )
            new_tracks.append(new_track)
            updated_tracks.append(new_track)
    
    # Combine results
    result.source_frame_id = previous_tracks[0].source_frame_id if previous_tracks else ""
    result.tracks = updated_tracks
    result.new_tracks = new_tracks
    
    # Add previously closed tracks that are still closed
    result.closed_tracks = lost_tracks
    
    return result


def track_frame_deterministic(
    previous_tracks: List[Track],
    new_detections: List[PersonDetection],
    face_detections: Optional[List[FaceDetection]] = None,
    frame_index: int = 0,
    timestamp: float = 0.0,
    config: Optional[TrackingConfig] = None,
) -> TrackingResult:
    """
    Main tracking entry point.
    Updates tracks based on new detections.
    """
    return update_tracks(
        previous_tracks, new_detections, face_detections,
        frame_index, timestamp, config
    )


if __name__ == "__main__":
    print("Tracking module loaded successfully!")
    print(f"Track lifecycle states: {[s.value for s in TrackLifecycleState]}")