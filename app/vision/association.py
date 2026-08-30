"""
Phase 10 — Person ↔ Face Association Engine.

This module implements the deterministic offline association layer between
YOLO11n person detections and face detector detections.

All association operates in ORIGINAL_FRAME coordinates (3840x2160).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.data.frame import CanonicalFrame
from app.vision.association_contract import (
    AssociationResult,
    AssociationStatus,
    PersonFaceAssociation,
    create_association_from_detections,
)
from app.vision.association_geometry import (
    AMBIGUITY_MARGIN,
    AssociationScore,
    compute_association_score,
    face_center_in_person,
    intersection_over_face,
    is_ambiguous,
    validate_bbox_4k,
    validate_coordinate_space,
)
from app.vision.detector_contract import FaceDetectionContract


@dataclass
class AssociationConfig:
    """Configuration for association behavior."""
    
    # Score weights (must sum to 1.0)
    score_weights: Tuple[float, float, float, float, float] = (0.3, 0.25, 0.2, 0.15, 0.1)
    
    # Ambiguity margin
    ambiguity_margin: float = AMBIGUITY_MARGIN
    
    # Minimum score to consider association valid
    min_association_score: float = 0.3
    
    # Require face center in person bbox for ASSOCIATED status
    require_center_containment: bool = True
    
    # Allow partial face outside person bbox
    allow_partial_face: bool = True


class CoordinateSpaceError(ValueError):
    """Raised when coordinate space validation fails."""
    pass


class AssociationError(Exception):
    """Raised when association fails."""
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
        if not validate_bbox_4k(det.bbox):
            raise CoordinateSpaceError(
                f"Person detection {i} bbox {det.bbox} invalid for 4K ORIGINAL_FRAME"
            )
        # Check for zero-area bbox
        x1, y1, x2, y2 = det.bbox
        if x2 <= x1 or y2 <= y1:
            raise CoordinateSpaceError(
                f"Person detection {i} bbox {det.bbox} has zero or negative area"
            )
        if getattr(det, 'coordinate_space', 'original_frame') != 'original_frame':
            raise CoordinateSpaceError(
                f"Person detection {i} coordinate_space is "
                f"'{getattr(det, 'coordinate_space', 'unknown')}', expected 'original_frame'"
            )
    
    for i, det in enumerate(face_detections):
        if not validate_bbox_4k(det.bbox):
            raise CoordinateSpaceError(
                f"Face detection {i} bbox {det.bbox} invalid for 4K ORIGINAL_FRAME"
            )
        # Check for zero-area bbox
        x1, y1, x2, y2 = det.bbox
        if x2 <= x1 or y2 <= y1:
            raise CoordinateSpaceError(
                f"Face detection {i} bbox {det.bbox} has zero or negative area"
            )
        if det.coordinate_space != 'original_frame':
            raise CoordinateSpaceError(
                f"Face detection {i} coordinate_space is "
                f"'{det.coordinate_space}', expected 'original_frame'"
            )


def compute_score_matrix(
    person_detections: List[Any],
    face_detections: List[FaceDetectionContract],
    config: AssociationConfig,
) -> Tuple[np.ndarray, List[List[AssociationScore]]]:
    """
    Compute association score matrix between all person-face pairs.
    
    Args:
        person_detections: List of person detections
        face_detections: List of face detections
        config: Association configuration
        
    Returns:
        Tuple of (score_matrix, score_details)
        - score_matrix: 2D array [num_faces, num_persons] with total scores
        - score_details: 2D list of AssociationScore objects
    """
    num_faces = len(face_detections)
    num_persons = len(person_detections)
    
    score_matrix = np.zeros((num_faces, num_persons), dtype=np.float32)
    score_details = [[None for _ in range(num_persons)] for _ in range(num_faces)]
    
    for fi, face_det in enumerate(face_detections):
        for pi, person_det in enumerate(person_detections):
            score = compute_association_score(
                face_det.bbox,
                person_det.bbox,
                weights=config.score_weights,
            )
            score_matrix[fi, pi] = score.total_score
            score_details[fi][pi] = score
    
    return score_matrix, score_details


def solve_assignment(
    score_matrix: np.ndarray,
    score_details: List[List[AssociationScore]],
    config: AssociationConfig,
) -> List[Tuple[int, int, AssociationStatus, float, str]]:
    """
    Solve global assignment between faces and persons.
    
    Uses greedy assignment with ambiguity detection.
    For each face, find best person. If multiple faces map to same person,
    resolve by highest score. Mark ambiguous cases.
    
    Args:
        score_matrix: [num_faces, num_persons] association scores
        score_details: Detailed score breakdowns
        config: Association configuration
        
    Returns:
        List of (face_idx, person_idx, status, score, reason) tuples
    """
    num_faces, num_persons = score_matrix.shape
    
    # Track assignments
    face_assigned = [False] * num_faces
    person_assigned = [False] * num_persons
    assignments = []
    
    # For each face, find best person
    face_best = []
    for fi in range(num_faces):
        if num_persons == 0:
            face_best.append((-1, 0.0, None))
            continue
        
        best_pi = int(np.argmax(score_matrix[fi]))
        best_score = float(score_matrix[fi, best_pi])
        second_best = 0.0
        if num_persons > 1:
            sorted_scores = np.sort(score_matrix[fi])[::-1]
            second_best = float(sorted_scores[1])
        
        face_best.append((best_pi, best_score, score_details[fi][best_pi]))
    
    # Sort faces by best score (highest first) for greedy assignment
    face_order = sorted(range(num_faces), key=lambda fi: face_best[fi][1], reverse=True)
    
    for fi in face_order:
        best_pi, best_score, best_detail = face_best[fi]
        
        if best_pi == -1 or best_score < config.min_association_score:
            # No valid person for this face
            assignments.append((fi, -1, AssociationStatus.UNASSOCIATED_FACE, 0.0, "no_valid_person"))
            continue
        
        # Check if person already assigned
        if person_assigned[best_pi]:
            # Check if this face has a better claim
            # Find which face is currently assigned to this person
            current_fi = None
            for a_fi, a_pi, a_status, _, _ in assignments:
                if a_pi == best_pi and a_status == AssociationStatus.ASSOCIATED:
                    current_fi = a_fi
                    break
            
            if current_fi is not None:
                current_score = face_best[current_fi][1]
                if best_score > current_score + config.ambiguity_margin:
                    # This face has a clearly better claim - reassign
                    # Mark previous as unassociated
                    for idx, (a_fi, a_pi, a_status, a_score, a_reason) in enumerate(assignments):
                        if a_fi == current_fi and a_pi == best_pi:
                            assignments[idx] = (a_fi, -1, AssociationStatus.UNASSOCIATED_FACE, 0.0, "reassigned_to_better_match")
                            break
                    person_assigned[best_pi] = False
                else:
                    # Ambiguous - both faces have similar scores
                    assignments.append((fi, best_pi, AssociationStatus.AMBIGUOUS, best_score, "person_already_assigned_similar_score"))
                    continue
        
        # Check center containment requirement
        if config.require_center_containment:
            # We need access to the actual bboxes - this is a limitation of this approach
            # The score_detail has the info we need
            if best_detail and best_detail.containment_score < 1.0:
                # Face center not in person bbox
                if not config.allow_partial_face:
                    assignments.append((fi, best_pi, AssociationStatus.UNASSOCIATED_FACE, best_score, "face_center_outside_person"))
                    continue
                # Allow partial but mark reason
                reason = "face_center_outside_person_partial_allowed"
            else:
                reason = "center_contained"
        else:
            reason = "center_not_required"
        
        # Check ambiguity with second best
        second_best = 0.0
        if num_persons > 1:
            sorted_scores = np.sort(score_matrix[fi])[::-1]
            second_best = float(sorted_scores[1])
        
        if is_ambiguous(best_score, second_best, config.ambiguity_margin):
            assignments.append((fi, best_pi, AssociationStatus.AMBIGUOUS, best_score, f"ambiguous_margin_{config.ambiguity_margin}"))
        else:
            assignments.append((fi, best_pi, AssociationStatus.ASSOCIATED, best_score, reason))
            face_assigned[fi] = True
            person_assigned[best_pi] = True
    
    # Add unassociated persons (only if they don't already have an unassociated face entry)
    for pi in range(num_persons):
        if not person_assigned[pi]:
            # Check if there's already an unassociated face for this person
            has_unassociated_face = any(a_pi == pi and a_status == AssociationStatus.UNASSOCIATED_FACE for a_fi, a_pi, a_status, _, _ in assignments)
            if not has_unassociated_face:
                assignments.append((-1, pi, AssociationStatus.UNASSOCIATED_PERSON, 0.0, "no_matching_face"))
    
    return assignments


def associate_detections(
    person_detections: List[Any],
    face_detections: List[FaceDetectionContract],
    frame: CanonicalFrame,
    config: Optional[AssociationConfig] = None,
) -> AssociationResult:
    """
    Associate person detections with face detections.
    
    This is the main entry point for the association layer.
    
    Args:
        person_detections: List of person detections (PersonDetectionContract or compatible)
        face_detections: List of face detections (FaceDetectionContract)
        frame: Source canonical frame (must be 3840x2160)
        config: Optional association configuration
        
    Returns:
        AssociationResult with all associations and unmatched detections
        
    Raises:
        CoordinateSpaceError: If detections not in ORIGINAL_FRAME space
        AssociationError: If association fails
    """
    if config is None:
        config = AssociationConfig()
    
    # Validate frame is 4K
    if frame.width != 3840 or frame.height != 2160:
        raise AssociationError(
            f"Frame must be 3840x2160, got {frame.width}x{frame.height}"
        )
    
    # Validate coordinate spaces
    validate_detections_coordinate_space(person_detections, face_detections)
    
    # Compute score matrix
    score_matrix, score_details = compute_score_matrix(
        person_detections, face_detections, config
    )
    
    # Solve assignment
    assignments = solve_assignment(score_matrix, score_details, config)
    
    # Build association objects
    associations = []
    unmatched_persons = []
    unmatched_faces = []
    
    for fi, pi, status, score, reason in assignments:
        if fi >= 0 and pi >= 0:
            # Matched pair
            face_det = face_detections[fi]
            person_det = person_detections[pi]
            
            assoc = create_association_from_detections(
                person_detection=person_det,
                face_detection=face_det,
                frame=frame,
                association_status=status,
                association_score=score,
                geometry_reason=reason,
            )
            associations.append(assoc)
            
        elif fi >= 0 and pi == -1:
            # Unmatched face
            face_det = face_detections[fi]
            assoc = create_association_from_detections(
                person_detection=None,  # Will be handled specially
                face_detection=face_det,
                frame=frame,
                association_status=AssociationStatus.UNASSOCIATED_FACE,
                association_score=0.0,
                geometry_reason=reason,
            )
            # Override person fields for unmatched face
            assoc = PersonFaceAssociation(
                association_id=assoc.association_id,
                source_frame_id=assoc.source_frame_id,
                frame_index=assoc.frame_index,
                person_detection_id="",
                person_bbox=(0.0, 0.0, 0.0, 0.0),
                person_confidence=0.0,
                person_model_id="",
                person_model_sha256="",
                face_detection_id=assoc.face_detection_id,
                face_bbox=assoc.face_bbox,
                face_confidence=assoc.face_confidence,
                face_landmarks5=assoc.face_landmarks5,
                face_model_id=assoc.face_model_id,
                face_model_sha256=assoc.face_model_sha256,
                association_status=AssociationStatus.UNASSOCIATED_FACE,
                association_score=0.0,
                geometry_reason=reason,
                coordinate_space="original_frame",
                person_provenance=None,
                face_provenance=assoc.face_provenance,
            )
            associations.append(assoc)
            unmatched_faces.append(face_det.to_dict())
            
        elif fi == -1 and pi >= 0:
            # Unmatched person
            person_det = person_detections[pi]
            assoc = PersonFaceAssociation(
                association_id=f"unassoc_person_{pi}",
                source_frame_id=frame.metadata.source_id,
                frame_index=frame.metadata.frame_index,
                person_detection_id=getattr(person_det, 'detection_id', ''),
                person_bbox=person_det.bbox,
                person_confidence=person_det.confidence,
                person_model_id=person_det.model_id,
                person_model_sha256=person_det.model_sha256,
                face_detection_id="",
                face_bbox=(0.0, 0.0, 0.0, 0.0),
                face_confidence=0.0,
                face_landmarks5=[],
                face_model_id="",
                face_model_sha256="",
                association_status=AssociationStatus.UNASSOCIATED_PERSON,
                association_score=0.0,
                geometry_reason=reason,
                coordinate_space="original_frame",
                person_provenance=getattr(person_det, 'provenance', None),
                face_provenance=None,
            )
            associations.append(assoc)
            unmatched_persons.append(person_det.to_dict() if hasattr(person_det, 'to_dict') else {
                "bbox": person_det.bbox,
                "confidence": person_det.confidence,
                "model_id": person_det.model_id,
            })
    
    return AssociationResult(
        source_frame_id=frame.metadata.source_id,
        frame_index=frame.metadata.frame_index,
        associations=associations,
        unmatched_persons=unmatched_persons,
        unmatched_faces=unmatched_faces,
    )


def associate_detections_deterministic(
    person_detections: List[Any],
    face_detections: List[FaceDetectionContract],
    frame: CanonicalFrame,
    config: Optional[AssociationConfig] = None,
    num_runs: int = 3,
) -> AssociationResult:
    """
    Run association multiple times with shuffled inputs to verify determinism.
    
    Args:
        person_detections: List of person detections
        face_detections: List of face detections
        frame: Source canonical frame
        config: Optional association configuration
        num_runs: Number of runs with shuffled inputs
        
    Returns:
        AssociationResult from first run (all runs should be identical)
        
    Raises:
        AssociationError: If results differ between runs
    """
    if config is None:
        config = AssociationConfig()
    
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
        
        result = associate_detections(shuffled_persons, shuffled_faces, frame, config)
        results.append(result)
    
    # Verify all results are identical
    first = results[0]
    for i, result in enumerate(results[1:], 1):
        if len(first.associations) != len(result.associations):
            raise AssociationError(f"Run {i} has different number of associations")
        
        # Sort associations by face_detection_id (and person_detection_id for unassociated faces)
        # to ensure consistent comparison regardless of list order
        def assoc_key(a):
            return (a.face_detection_id or "", a.person_detection_id or "")
        
        first_sorted = sorted(first.associations, key=assoc_key)
        result_sorted = sorted(result.associations, key=assoc_key)
        
        for a1, a2 in zip(first_sorted, result_sorted):
            if a1.association_status != a2.association_status:
                raise AssociationError(f"Run {i} status differs: {a1.association_status} vs {a2.association_status}")
            if abs(a1.association_score - a2.association_score) > 1e-6:
                raise AssociationError(f"Run {i} score differs: {a1.association_score} vs {a2.association_score}")
            if a1.person_detection_id != a2.person_detection_id:
                raise AssociationError(f"Run {i} person_id differs")
            if a1.face_detection_id != a2.face_detection_id:
                raise AssociationError(f"Run {i} face_id differs")
    
    return first
