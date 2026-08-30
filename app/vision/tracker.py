"""
Phase 11 — Person/Face Tracker Implementation.

This module implements a deterministic geometry-based tracker on top of
Phase 9 (PersonDetection) + Phase 10 (PersonFaceAssociation) contracts.

All tracking operates in ORIGINAL_FRAME coordinates (3840x2160).

CRITICAL:
- track_id is NOT identity. It means "same observed person across frames".
- No ArcFace, no 1K3D68, no identity recognition, no attendance, no IN/OUT.
- Deterministic geometry-based matching only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.frame import CanonicalFrame
from app.vision.association_contract import AssociationResult, PersonFaceAssociation
from app.vision.association_geometry import (
    bbox_intersection,
    face_center_distance_to_person,
    face_center_in_person,
    intersection_area,
    intersection_over_face,
    iou,
)
from app.vision.detector_contract import FaceDetectionContract
from app.vision.track_contract import (
    Track,
    TrackLifecycleState,
    TrackerConfig,
    TrackingResult,
    age_track_without_detection,
    create_track_from_person_detection,
    update_track_from_person_detection,
)


class TrackingError(Exception):
    """Raised when tracking fails."""
    pass


class CoordinateSpaceError(ValueError):
    """Raised when coordinate space validation fails."""
    pass


def validate_detections_coordinate_space(
    person_detections: List[Any],
    face_detections: List[FaceDetectionContract],
) -> None:
    """
    Validate all detections are in ORIGINAL_FRAME space and 4K boundaries.
    
    Args:
        person_detections: List of person detections
        face_detections: List of face detections
        
    Raises:
        CoordinateSpaceError: If any detection has invalid coordinate space
    """
    for i, det in enumerate(person_detections):
        x1, y1, x2, y2 = det.bbox
        if not all(np.isfinite([x1, y1, x2, y2])):
            raise CoordinateSpaceError(
                f"Person detection {i} bbox {det.bbox} has non-finite coordinates"
            )
        if x2 <= x1 or y2 <= y1:
            raise CoordinateSpaceError(
                f"Person detection {i} bbox {det.bbox} has zero or negative area"
            )
        if x1 < 0 or y1 < 0 or x2 > 3840 or y2 > 2160:
            raise CoordinateSpaceError(
                f"Person detection {i} bbox {det.bbox} exceeds 4K boundaries (3840x2160)"
            )
        if getattr(det, 'coordinate_space', 'original_frame') != 'original_frame':
            raise CoordinateSpaceError(
                f"Person detection {i} coordinate_space is "
                f"'{getattr(det, 'coordinate_space', 'unknown')}', expected 'original_frame'"
            )
    
    for i, det in enumerate(face_detections):
        x1, y1, x2, y2 = det.bbox
        if not all(np.isfinite([x1, y1, x2, y2])):
            raise CoordinateSpaceError(
                f"Face detection {i} bbox {det.bbox} has non-finite coordinates"
            )
        if x2 <= x1 or y2 <= y1:
            raise CoordinateSpaceError(
                f"Face detection {i} bbox {det.bbox} has zero or negative area"
            )
        if x1 < 0 or y1 < 0 or x2 > 3840 or y2 > 2160:
            raise CoordinateSpaceError(
                f"Face detection {i} bbox {det.bbox} exceeds 4K boundaries (3840x2160)"
            )
        if det.coordinate_space != 'original_frame':
            raise CoordinateSpaceError(
                f"Face detection {i} coordinate_space is "
                f"'{det.coordinate_space}', expected 'original_frame'"
            )


def compute_track_detection_score(
    track: Track,
    person_detection: Any,
    config: TrackerConfig,
) -> Tuple[float, Dict[str, float]]:
    """
    Compute association score between a track and a person detection.
    
    Uses deterministic geometric matching:
    - IoU between track bbox and detection bbox
    - Center distance
    - Area ratio
    
    Args:
        track: Existing track
        person_detection: New person detection
        config: Tracker configuration
        
    Returns:
        Tuple of (total_score, score_components)
    """
    track_bbox = track.bbox_original_frame
    det_bbox = person_detection.bbox
    
    # IoU score
    iou_score = iou(track_bbox, det_bbox)
    
    # Center distance score (normalized by frame diagonal)
    frame_diagonal = np.sqrt(3840**2 + 2160**2)  # ~4400
    center_dist = face_center_distance_to_person(track_bbox, det_bbox)
    center_dist_score = max(0.0, 1.0 - center_dist / frame_diagonal)
    
    # Area ratio score (penalize large size changes)
    track_area = track.area
    det_area = (det_bbox[2] - det_bbox[0]) * (det_bbox[3] - det_bbox[1])
    if track_area > 0 and det_area > 0:
        area_ratio = min(track_area, det_area) / max(track_area, det_area)
    else:
        area_ratio = 0.0
    
    # Containment score (how much of track is in detection and vice versa)
    inter_area = intersection_area(track_bbox, det_bbox)
    containment_track_in_det = inter_area / track_area if track_area > 0 else 0.0
    containment_det_in_track = inter_area / det_area if det_area > 0 else 0.0
    containment_score = (containment_track_in_det + containment_det_in_track) / 2
    
    # Weighted total score
    weights = (0.4, 0.25, 0.2, 0.15)  # IoU, center_dist, area_ratio, containment
    total_score = (
        weights[0] * iou_score +
        weights[1] * center_dist_score +
        weights[2] * area_ratio +
        weights[3] * containment_score
    )
    
    components = {
        "iou": iou_score,
        "center_distance": center_dist_score,
        "area_ratio": area_ratio,
        "containment": containment_score,
    }
    
    return total_score, components


def solve_track_assignment(
    tracks: List[Track],
    person_detections: List[Any],
    associations: List[PersonFaceAssociation],
    config: TrackerConfig,
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """
    Solve global assignment between existing tracks and new person detections.
    
    Uses greedy assignment with deterministic ordering (by track_id).
    
    Args:
        tracks: List of existing tracks (active + lost)
        person_detections: List of new person detections
        associations: Phase 10 association results for face attachment
        config: Tracker configuration
        
    Returns:
        Tuple of (assignments, unmatched_track_indices, unmatched_detection_indices)
        - assignments: List of (track_idx, detection_idx) pairs
        - unmatched_track_indices: Indices of tracks not assigned
        - unmatched_detection_indices: Indices of detections not assigned
    """
    num_tracks = len(tracks)
    num_detections = len(person_detections)
    
    if num_tracks == 0 or num_detections == 0:
        return [], list(range(num_tracks)), list(range(num_detections))
    
    # Build score matrix [num_tracks, num_detections]
    score_matrix = np.zeros((num_tracks, num_detections), dtype=np.float32)
    score_details = [[None for _ in range(num_detections)] for _ in range(num_tracks)]
    
    for ti, track in enumerate(tracks):
        for di, det in enumerate(person_detections):
            score, components = compute_track_detection_score(track, det, config)
            score_matrix[ti, di] = score
            score_details[ti][di] = components
    
    # Greedy assignment with deterministic ordering
    # Sort tracks by track_id for deterministic behavior
    track_order = sorted(range(num_tracks), key=lambda ti: tracks[ti].track_id)
    
    track_assigned = [False] * num_tracks
    detection_assigned = [False] * num_detections
    assignments = []
    
    for ti in track_order:
        track = tracks[ti]
        
        # Find best detection for this track
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
    
    # Unmatched tracks and detections
    unmatched_tracks = [ti for ti in range(num_tracks) if not track_assigned[ti]]
    unmatched_detections = [di for di in range(num_detections) if not detection_assigned[di]]
    
    return assignments, unmatched_tracks, unmatched_detections


def find_association_for_person(
    person_detection: Any,
    associations: List[PersonFaceAssociation],
) -> Optional[PersonFaceAssociation]:
    """
    Find the association for a specific person detection.
    
    Args:
        person_detection: Person detection to find association for
        associations: List of all associations from Phase 10
        
    Returns:
        Matching association or None
    """
    person_det_id = getattr(person_detection, 'detection_id', '')
    
    for assoc in associations:
        if assoc.person_detection_id == person_det_id:
            return assoc
    
    return None


def update_tracks(
    tracks: List[Track],
    person_detections: List[Any],
    associations: List[PersonFaceAssociation],
    frame: CanonicalFrame,
    config: TrackerConfig,
) -> Tuple[List[Track], List[Track], List[Track]]:
    """
    Update existing tracks with new detections.
    
    Args:
        tracks: Current list of tracks (active + lost)
        person_detections: New person detections
        associations: Phase 10 association results
        frame: Current frame
        config: Tracker configuration
        
    Returns:
        Tuple of (updated_tracks, new_tracks, closed_tracks)
    """
    # Separate active/lost tracks from closed
    active_lost_tracks = [t for t in tracks if not t.is_closed]
    closed_tracks = [t for t in tracks if t.is_closed]
    
    # Solve assignment
    assignments, unmatched_track_indices, unmatched_detection_indices = solve_track_assignment(
        active_lost_tracks, person_detections, associations, config
    )
    
    updated_tracks = []
    new_tracks = []
    newly_closed = []
    
    # Update matched tracks
    for track_idx, det_idx in assignments:
        track = active_lost_tracks[track_idx]
        detection = person_detections[det_idx]
        association = find_association_for_person(detection, associations)
        
        updated_track = update_track_from_person_detection(
            track, detection, frame, association
        )
        updated_tracks.append(updated_track)
    
    # Age unmatched tracks
    for track_idx in unmatched_track_indices:
        track = active_lost_tracks[track_idx]
        aged_track = age_track_without_detection(track, frame, config)
        
        if aged_track.is_closed:
            newly_closed.append(aged_track)
        else:
            updated_tracks.append(aged_track)
    
    # Create new tracks for unmatched detections
    for det_idx in unmatched_detection_indices:
        detection = person_detections[det_idx]
        association = find_association_for_person(detection, associations)
        
        new_track = create_track_from_person_detection(detection, frame, association)
        new_tracks.append(new_track)
        updated_tracks.append(new_track)
    
    # Keep previously closed tracks (they stay closed)
    all_tracks = updated_tracks + closed_tracks + newly_closed
    
    # Enforce memory bounds
    active_tracks = [t for t in all_tracks if t.is_active]
    lost_tracks = [t for t in all_tracks if t.is_lost]
    closed_tracks_all = [t for t in all_tracks if t.is_closed]
    new_tracks_all = [t for t in all_tracks if t.is_new]
    
    # Sort by track_id for deterministic ordering
    active_tracks.sort(key=lambda t: t.track_id)
    lost_tracks.sort(key=lambda t: t.track_id)
    new_tracks_all.sort(key=lambda t: t.track_id)
    
    # Trim if exceeding bounds
    if len(active_tracks) > config.max_active_tracks:
        # Close oldest active tracks
        excess = active_tracks[config.max_active_tracks:]
        active_tracks = active_tracks[:config.max_active_tracks]
        for t in excess:
            # Create closed version
            closed = Track(
                track_id=t.track_id,
                source_frame_id=t.source_frame_id,
                frame_index=t.frame_index,
                timestamp=t.timestamp,
                bbox_original_frame=t.bbox_original_frame,
                confidence=t.confidence,
                lifecycle_state=TrackLifecycleState.CLOSED,
                age=t.age,
                hits=t.hits,
                missed_frames=t.missed_frames,
                last_seen=t.last_seen,
                face_detection_id=t.face_detection_id,
                face_bbox=t.face_bbox,
                face_confidence=t.face_confidence,
                face_landmarks5=t.face_landmarks5,
                face_model_id=t.face_model_id,
                face_model_sha256=t.face_model_sha256,
                person_provenance=t.person_provenance,
                face_provenance=t.face_provenance,
                coordinate_space="original_frame",
            )
            closed_tracks_all.append(closed)
            newly_closed.append(closed)
    
    if len(lost_tracks) > config.max_lost_tracks:
        # Close oldest lost tracks
        excess = lost_tracks[config.max_lost_tracks:]
        lost_tracks = lost_tracks[:config.max_lost_tracks]
        for t in excess:
            closed = Track(
                track_id=t.track_id,
                source_frame_id=t.source_frame_id,
                frame_index=t.frame_index,
                timestamp=t.timestamp,
                bbox_original_frame=t.bbox_original_frame,
                confidence=t.confidence,
                lifecycle_state=TrackLifecycleState.CLOSED,
                age=t.age,
                hits=t.hits,
                missed_frames=t.missed_frames,
                last_seen=t.last_seen,
                face_detection_id=t.face_detection_id,
                face_bbox=t.face_bbox,
                face_confidence=t.face_confidence,
                face_landmarks5=t.face_landmarks5,
                face_model_id=t.face_model_id,
                face_model_sha256=t.face_model_sha256,
                person_provenance=t.person_provenance,
                face_provenance=t.face_provenance,
                coordinate_space="original_frame",
            )
            closed_tracks_all.append(closed)
            newly_closed.append(closed)
    
    # Combine all tracks in deterministic order: active, lost, new, closed
    final_tracks = active_tracks + lost_tracks + new_tracks_all + closed_tracks_all
    
    return final_tracks, new_tracks_all, newly_closed


def track_frame(
    person_detections: List[Any],
    face_detections: List[FaceDetectionContract],
    associations: AssociationResult,
    frame: CanonicalFrame,
    previous_tracks: List[Track],
    config: Optional[TrackerConfig] = None,
) -> TrackingResult:
    """
    Main tracking entry point for a single frame.
    
    Args:
        person_detections: List of person detections from YOLO11n
        face_detections: List of face detections from SCRFD
        associations: Phase 10 association result
        frame: Current canonical frame (must be 3840x2160)
        previous_tracks: Tracks from previous frame
        config: Optional tracker configuration
        
    Returns:
        TrackingResult with updated tracks
        
    Raises:
        CoordinateSpaceError: If detections not in ORIGINAL_FRAME space
        TrackingError: If tracking fails
    """
    if config is None:
        config = TrackerConfig()
    
    # Validate frame is 4K
    if frame.width != 3840 or frame.height != 2160:
        raise TrackingError(
            f"Frame must be 3840x2160, got {frame.width}x{frame.height}"
        )
    
    # Validate coordinate spaces
    validate_detections_coordinate_space(person_detections, face_detections)
    
    # Update tracks
    updated_tracks, new_tracks, closed_tracks = update_tracks(
        previous_tracks,
        person_detections,
        associations.associations,
        frame,
        config,
    )
    
    return TrackingResult(
        source_frame_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        timestamp=frame.metadata.timestamp,
        tracks=updated_tracks,
        new_tracks=new_tracks,
        closed_tracks=closed_tracks,
    )


def track_frame_deterministic(
    person_detections: List[Any],
    face_detections: List[FaceDetectionContract],
    associations: AssociationResult,
    frame: CanonicalFrame,
    previous_tracks: List[Track],
    config: Optional[TrackerConfig] = None,
    num_runs: int = 3,
) -> TrackingResult:
    """
    Run tracking multiple times with shuffled inputs to verify determinism.
    
    Since track IDs are now deterministic from bbox, we don't need to reset counters.
    We just verify that shuffled inputs produce the same results.
    
    Args:
        person_detections: List of person detections
        face_detections: List of face detections
        associations: Phase 10 association result
        frame: Current canonical frame
        previous_tracks: Tracks from previous frame
        config: Optional tracker configuration
        num_runs: Number of runs with shuffled inputs
        
    Returns:
        TrackingResult from first run (all runs should be identical)
        
    Raises:
        TrackingError: If results differ between runs
    """
    if config is None:
        config = TrackerConfig()
    
    results = []
    
    for run in range(num_runs):
        # Shuffle inputs (but keep track of original indices)
        import random
        rng = random.Random(42 + run)  # Deterministic shuffle per run
        
        person_indices = list(range(len(person_detections)))
        face_indices = list(range(len(face_detections)))
        
        rng.shuffle(person_indices)
        rng.shuffle(face_indices)
        
        shuffled_persons = [person_detections[i] for i in person_indices]
        shuffled_faces = [face_detections[i] for i in face_indices]
        
        # Need to also shuffle associations to match
        # For simplicity, we just run with shuffled detections
        # The association result should be recomputed for shuffled inputs
        # But for determinism test, we use the same associations
        
        result = track_frame(
            shuffled_persons, shuffled_faces, associations, frame, previous_tracks, config
        )
        results.append(result)
    
    # Verify all results are identical
    first = results[0]
    for i, result in enumerate(results[1:], 1):
        if len(first.tracks) != len(result.tracks):
            raise TrackingError(f"Run {i} has different number of tracks")
        
        # Sort tracks by track_id for comparison
        first_sorted = sorted(first.tracks, key=lambda t: t.track_id)
        result_sorted = sorted(result.tracks, key=lambda t: t.track_id)
        
        for t1, t2 in zip(first_sorted, result_sorted):
            if t1.track_id != t2.track_id:
                raise TrackingError(f"Run {i} track_id differs: {t1.track_id} vs {t2.track_id}")
            if t1.lifecycle_state != t2.lifecycle_state:
                raise TrackingError(f"Run {i} lifecycle differs: {t1.lifecycle_state} vs {t2.lifecycle_state}")
            if abs(t1.confidence - t2.confidence) > 1e-6:
                raise TrackingError(f"Run {i} confidence differs")
            if t1.face_detection_id != t2.face_detection_id:
                raise TrackingError(f"Run {i} face_detection_id differs")
    
    return first