"""
Global Identity Service - Core service for cross-camera identity management.

Manages global person identities, cross-camera matching, and identity lifecycle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.identity.models import (
    ConflictResolution,
    ConflictType,
    EvidenceType,
    GISConfig,
    GlobalPersonID,
    IdentityConflict,
    IdentityEvidence,
    IdentityState,
    TrackRef,
    cosine_similarity,
    detect_conflict,
    generate_conflict_id,
    generate_evidence_id,
    generate_global_person_id,
    load_gis_config,
    weighted_fusion,
)
from app.vision.track_contract import Track

logger = logging.getLogger(__name__)


@dataclass
class FaceMatcher:
    """Cross-camera face matcher using ArcFace embeddings."""
    config: GISConfig

    def match(self, embedding: np.ndarray, gallery: Dict[str, GlobalPersonID]) -> List[Tuple[str, float]]:
        """Match face embedding against global gallery."""
        matches = []
        for person_id, person in gallery.items():
            if person.face_embedding is not None:
                similarity = cosine_similarity(embedding, person.face_embedding)
                if similarity >= self.config.face_match_threshold:
                    matches.append((person_id, similarity))
        
        # Sort by similarity descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def find_best_match(self, embedding: np.ndarray, gallery: Dict[str, GlobalPersonID]) -> Optional[Tuple[str, float]]:
        """Find the best face match above threshold."""
        matches = self.match(embedding, gallery)
        if matches:
            return matches[0]
        return None


@dataclass
class BodyMatcher:
    """Cross-camera body matcher using ReID embeddings."""
    config: GISConfig

    def match(self, embedding: np.ndarray, gallery: Dict[str, GlobalPersonID]) -> List[Tuple[str, float]]:
        """Match body embedding against global gallery."""
        matches = []
        for person_id, person in gallery.items():
            if person.body_embedding is not None:
                similarity = cosine_similarity(embedding, person.body_embedding)
                if similarity >= self.config.body_match_threshold:
                    matches.append((person_id, similarity))
        
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def find_best_match(self, embedding: np.ndarray, gallery: Dict[str, GlobalPersonID]) -> Optional[Tuple[str, float]]:
        """Find the best body match above threshold."""
        matches = self.match(embedding, gallery)
        if matches:
            return matches[0]
        return None


@dataclass
class FusionEngine:
    """Face+Body evidence fusion with conflict detection."""
    config: GISConfig

    def fuse(
        self,
        face_match: Optional[Tuple[str, float]],
        body_match: Optional[Tuple[str, float]],
    ) -> Tuple[Optional[str], float, Optional[ConflictType], Optional[ConflictResolution]]:
        """
        Fuse face and body match results.
        
        Returns:
            Tuple of (person_id, fused_score, conflict_type, resolution_hint)
        """
        # If only one modality available, use that
        if face_match and not body_match:
            return face_match[0], face_match[1], None, None
        if body_match and not face_match:
            return body_match[0], body_match[1], None, None
        
        # If neither available
        if not face_match and not body_match:
            return None, 0.0, None, None
        
        # Both available - check if they agree on person_id
        face_person, face_score = face_match
        body_person, body_score = body_match
        
        if face_person == body_person:
            # Agreement - fuse scores
            fused = weighted_fusion(face_score, body_score, self.config.face_weight, self.config.body_weight)
            return face_person, fused, None, None
        else:
            # Disagreement - conflict
            conflict = detect_conflict(face_score, body_score, self.config.conflict_threshold)
            
            # Determine resolution hint
            resolution = None
            if face_score > body_score:
                resolution = ConflictResolution.ACCEPT_FACE
            elif body_score > face_score:
                resolution = ConflictResolution.ACCEPT_BODY
            
            # Return the higher scoring match with conflict flag
            if face_score >= body_score:
                return face_person, face_score, conflict, resolution
            else:
                return body_person, body_score, conflict, resolution


class IdentityLifecycle:
    """Manages identity state transitions."""
    
    def __init__(self, config: GISConfig):
        self.config = config

    def determine_initial_state(
        self,
        face_match: Optional[Tuple[str, float]],
        body_match: Optional[Tuple[str, float]],
    ) -> IdentityState:
        """Determine initial state for a new track."""
        if face_match or body_match:
            return IdentityState.CANDIDATE
        return IdentityState.UNKNOWN

    def evaluate_state_transition(
        self,
        current_state: IdentityState,
        person: GlobalPersonID,
        face_match: Optional[Tuple[str, float]],
        body_match: Optional[Tuple[str, float]],
        conflict_type: Optional[ConflictType],
    ) -> IdentityState:
        """Evaluate if state should transition."""
        
        # Conflict always leads to CONFLICT state
        if conflict_type:
            return IdentityState.CONFLICT
        
        evidence_count = len(person.camera_tracks)
        age = time.time() - person.created_at
        
        if current_state == IdentityState.CANDIDATE:
            if evidence_count >= self.config.provisional_min_evidence and age >= self.config.provisional_min_duration_seconds:
                return IdentityState.PROVISIONAL
            return IdentityState.CANDIDATE
        
        elif current_state == IdentityState.PROVISIONAL:
            if evidence_count >= self.config.confirmed_min_evidence and age >= self.config.confirmed_min_duration_seconds:
                return IdentityState.CONFIRMED
            return IdentityState.PROVISIONAL
        
        elif current_state == IdentityState.CONFIRMED:
            return IdentityState.CONFIRMED
        
        return current_state

    def evaluate_reacquisition(
        self,
        lost_person: GlobalPersonID,
        new_embedding: np.ndarray,
        embedding_type: EvidenceType,
    ) -> bool:
        """Check if a new track reacquires a lost identity."""
        if embedding_type == EvidenceType.FACE_EMBEDDING and lost_person.face_embedding is not None:
            similarity = cosine_similarity(new_embedding, lost_person.face_embedding)
            return similarity >= self.config.reacquisition_similarity_threshold
        elif embedding_type == EvidenceType.BODY_EMBEDDING and lost_person.body_embedding is not None:
            similarity = cosine_similarity(new_embedding, lost_person.body_embedding)
            return similarity >= self.config.reacquisition_similarity_threshold
        return False


class GlobalIdentityService:
    """
    Global Identity Service - manages cross-camera person identities.
    
    Responsibilities:
    - Track registration and embedding updates
    - Cross-camera face and body matching
    - Face+Body evidence fusion
    - Identity lifecycle management (CANDIDATE → PROVISIONAL → CONFIRMED)
    - Conflict detection and persistence
    - Reacquisition handling
    """
    
    def __init__(self, config: Optional[GISConfig] = None):
        self.config = config or load_gis_config()
        
        # In-memory stores (in production, backed by database)
        self._global_persons: Dict[str, GlobalPersonID] = {}
        self._track_identity: Dict[Tuple[str, str], TrackRef] = {}  # (camera_id, local_track_id) -> TrackRef
        self._conflicts: Dict[str, IdentityConflict] = {}
        self._evidence_store: Dict[str, IdentityEvidence] = {}
        
        # Components
        self._face_matcher = FaceMatcher(self.config)
        self._body_matcher = BodyMatcher(self.config)
        self._fusion = FusionEngine(self.config)
        self._lifecycle = IdentityLifecycle(self.config)
        
        # Statistics
        self._stats = {
            "tracks_registered": 0,
            "tracks_updated": 0,
            "crossings_resolved": 0,
            "conflicts_detected": 0,
            "reacquisitions": 0,
        }

    def register_track(self, camera_id: str, track: Track) -> Tuple[str, IdentityState]:
        """
        Register a new local track and assign global identity.
        
        Returns:
            Tuple of (global_person_id, identity_state)
        """
        track_key = (camera_id, str(track.track_id))
        
        # Check if track already registered
        if track_key in self._track_identity:
            logger.warning(f"Track {track_key} already registered")
            existing = self._track_identity[track_key]
            return existing.global_person_id, existing.identity_state
        
        # Extract embeddings from track
        face_embedding = getattr(track, 'face_embedding', None)
        body_embedding = getattr(track, 'body_embedding', None)
        face_quality = getattr(track, 'face_quality', 0.0)
        body_quality = getattr(track, 'body_quality', 0.0)
        
        # Try to match against existing global persons
        gallery = self._global_persons
        
        face_match = None
        body_match = None
        
        if face_embedding is not None:
            face_match = self._face_matcher.find_best_match(face_embedding, gallery)
        
        if body_embedding is not None:
            body_match = self._body_matcher.find_best_match(body_embedding, gallery)
        
        # Fuse results
        person_id, fused_score, conflict_type, resolution_hint = self._fusion.fuse(face_match, body_match)
        
        # Determine identity state
        initial_state = self._lifecycle.determine_initial_state(face_match, body_match)
        
        if person_id is None:
            # No match - create new global person
            person_id = generate_global_person_id()
            initial_state = IdentityState.UNKNOWN
            logger.info(f"Created new global person: {person_id}")
        
        # Get or create global person
        if person_id not in self._global_persons:
            self._global_persons[person_id] = GlobalPersonID(
                person_id=person_id,
                created_at=time.time(),
                updated_at=time.time(),
                state=initial_state,
            )
        
        person = self._global_persons[person_id]
        
        # Update person with new evidence
        person.updated_at = time.time()
        person.camera_count = len(person.camera_tracks) + 1
        
        if face_embedding is not None:
            person.face_embedding = self._update_aggregate_embedding(person.face_embedding, face_embedding, face_quality)
        
        if body_embedding is not None:
            person.body_embedding = self._update_aggregate_embedding(person.body_embedding, body_embedding, body_quality)
        
        # Store evidence
        if face_embedding is not None:
            evidence = IdentityEvidence(
                evidence_id=generate_evidence_id(),
                global_person_id=person_id,
                camera_id=camera_id,
                local_track_id=str(track.track_id),
                evidence_type=EvidenceType.FACE_EMBEDDING,
                embedding=face_embedding,
                quality_score=face_quality,
                timestamp=time.time(),
                frame_index=track.frame_index,
                model_id="arcface_r100",
                model_sha256="",
            )
            self._evidence_store[evidence.evidence_id] = evidence
        
        if body_embedding is not None:
            evidence = IdentityEvidence(
                evidence_id=generate_evidence_id(),
                global_person_id=person_id,
                camera_id=camera_id,
                local_track_id=str(track.track_id),
                evidence_type=EvidenceType.BODY_EMBEDDING,
                embedding=body_embedding,
                quality_score=body_quality,
                timestamp=time.time(),
                frame_index=track.frame_index,
                model_id="resnet50_reid",
                model_sha256="",
            )
            self._evidence_store[evidence.evidence_id] = evidence
        
        # Register track-identity mapping
        track_ref = TrackRef(
            camera_id=camera_id,
            local_track_id=str(track.track_id),
            global_person_id=person_id,
            identity_state=initial_state,
            face_similarity=face_match[1] if face_match else 0.0,
            body_similarity=body_match[1] if body_match else 0.0,
            assigned_at=time.time(),
            updated_at=time.time(),
        )
        self._track_identity[track_key] = track_ref
        
        # Update person's camera_tracks
        if camera_id not in person.camera_tracks:
            person.camera_tracks[camera_id] = []
        person.camera_tracks[camera_id].append(track_ref)
        
        # Handle conflict if detected
        if conflict_type:
            self._create_conflict(
                person_id_1=face_match[0] if face_match else person_id,
                person_id_2=body_match[0] if body_match else person_id,
                conflict_type=conflict_type,
                face_similarity=face_match[1] if face_match else 0.0,
                body_similarity=body_match[1] if body_match else 0.0,
            )
        
        self._stats["tracks_registered"] += 1
        
        return person_id, initial_state

    def update_track(self, camera_id: str, track: Track) -> IdentityState:
        """
        Update an existing track with new embeddings.
        
        Returns:
            Updated identity state
        """
        track_key = (camera_id, str(track.track_id))
        
        if track_key not in self._track_identity:
            # Track not registered yet - register it
            return self.register_track(camera_id, track)[1]
        
        track_ref = self._track_identity[track_key]
        person_id = track_ref.global_person_id
        
        if person_id not in self._global_persons:
            logger.error(f"Global person {person_id} not found for track {track_key}")
            return IdentityState.UNKNOWN
        
        person = self._global_persons[person_id]
        
        # Extract embeddings
        face_embedding = getattr(track, 'face_embedding', None)
        body_embedding = getattr(track, 'body_embedding', None)
        face_quality = getattr(track, 'face_quality', 0.0)
        body_quality = getattr(track, 'body_quality', 0.0)
        
        # Store evidence
        if face_embedding is not None:
            evidence = IdentityEvidence(
                evidence_id=generate_evidence_id(),
                global_person_id=person_id,
                camera_id=camera_id,
                local_track_id=str(track.track_id),
                evidence_type=EvidenceType.FACE_EMBEDDING,
                embedding=face_embedding,
                quality_score=face_quality,
                timestamp=time.time(),
                frame_index=track.frame_index,
                model_id="arcface_r100",
                model_sha256="",
            )
            self._evidence_store[evidence.evidence_id] = evidence
            person.face_embedding = self._update_aggregate_embedding(person.face_embedding, face_embedding, face_quality)
        
        if body_embedding is not None:
            evidence = IdentityEvidence(
                evidence_id=generate_evidence_id(),
                global_person_id=person_id,
                camera_id=camera_id,
                local_track_id=str(track.track_id),
                evidence_type=EvidenceType.BODY_EMBEDDING,
                embedding=body_embedding,
                quality_score=body_quality,
                timestamp=time.time(),
                frame_index=track.frame_index,
                model_id="resnet50_reid",
                model_sha256="",
            )
            self._evidence_store[evidence.evidence_id] = evidence
            person.body_embedding = self._update_aggregate_embedding(person.body_embedding, body_embedding, body_quality)
        
        # Update track reference
        track_ref.updated_at = time.time()
        track_ref.face_similarity = getattr(track, 'face_similarity', track_ref.face_similarity)
        track_ref.body_similarity = getattr(track, 'body_similarity', track_ref.body_similarity)
        
        person.updated_at = time.time()
        self._stats["tracks_updated"] += 1
        
        # Re-evaluate lifecycle state
        gallery = {pid: p for pid, p in self._global_persons.items() if pid != person_id}
        gallery[person_id] = person
        
        face_match = None
        body_match = None
        
        if face_embedding is not None:
            face_match = self._face_matcher.find_best_match(face_embedding, gallery)
        
        if body_embedding is not None:
            body_match = self._body_matcher.find_best_match(body_embedding, gallery)
        
        _, _, conflict_type, _ = self._fusion.fuse(face_match, body_match)
        new_state = self._lifecycle.evaluate_state_transition(
            track_ref.identity_state, person, face_match, body_match, conflict_type
        )
        
        track_ref.identity_state = new_state
        person.state = new_state
        
        if conflict_type:
            self._create_conflict(
                person_id_1=face_match[0] if face_match else person_id,
                person_id_2=body_match[0] if body_match else person_id,
                conflict_type=conflict_type,
                face_similarity=face_match[1] if face_match else 0.0,
                body_similarity=body_match[1] if body_match else 0.0,
            )
        
        return new_state

    def resolve_crossing(self, camera_id: str, local_track_id: str) -> Tuple[str, IdentityState]:
        """
        Resolve identity for a crossing event.
        
        Returns:
            Tuple of (global_person_id, identity_state)
        """
        track_key = (camera_id, str(local_track_id))
        
        if track_key not in self._track_identity:
            logger.warning(f"Track {track_key} not registered in GIS")
            return "", IdentityState.UNKNOWN
        
        track_ref = self._track_identity[track_key]
        self._stats["crossings_resolved"] += 1
        
        return track_ref.global_person_id, track_ref.identity_state

    def get_identity_state(self, global_person_id: str) -> Optional[IdentityState]:
        """Get current identity state for a global person."""
        if global_person_id in self._global_persons:
            return self._global_persons[global_person_id].state
        return None

    def get_conflicts(self) -> List[IdentityConflict]:
        """Get all unresolved conflicts."""
        return [c for c in self._conflicts.values() if c.resolution == ConflictResolution.PENDING]

    def resolve_conflict(self, conflict_id: str, resolution: ConflictResolution, resolved_by: str) -> bool:
        """Resolve a conflict manually."""
        if conflict_id not in self._conflicts:
            return False
        
        conflict = self._conflicts[conflict_id]
        conflict.resolution = resolution
        conflict.resolved_at = time.time()
        conflict.resolved_by = resolved_by
        
        # Update affected persons
        for pid in [conflict.person_id_1, conflict.person_id_2]:
            if pid in self._global_persons:
                self._global_persons[pid].conflict_count += 1
                self._global_persons[pid].state = IdentityState.CONFIRMED
        
        return True

    def handle_track_loss(self, camera_id: str, local_track_id: str) -> None:
        """Handle track loss - mark for potential reacquisition."""
        track_key = (camera_id, str(local_track_id))
        
        if track_key in self._track_identity:
            track_ref = self._track_identity[track_key]
            track_ref.identity_state = IdentityState.TEMPORARILY_LOST
            logger.info(f"Track {track_key} marked as TEMPORARILY_LOST")

    def handle_track_reacquisition(
        self,
        camera_id: str,
        new_track: Track,
        max_gap_seconds: Optional[float] = None,
    ) -> Tuple[str, IdentityState]:
        """
        Handle track reacquisition - compare with lost tracks.
        
        Returns:
            Tuple of (global_person_id, identity_state)
        """
        track_key = (camera_id, str(new_track.track_id))
        
        # Check if this is a new track
        if track_key in self._track_identity:
            return self.update_track(camera_id, new_track)
        
        # Look for recently lost tracks
        max_gap = max_gap_seconds or self.config.reacquisition_max_gap_seconds
        current_time = time.time()
        
        for (cam_id, track_id), track_ref in list(self._track_identity.items()):
            if track_ref.identity_state == IdentityState.TEMPORARILY_LOST:
                time_gap = current_time - track_ref.updated_at
                if time_gap <= max_gap:
                    # Check embedding similarity for reacquisition
                    face_embedding = getattr(new_track, 'face_embedding', None)
                    body_embedding = getattr(new_track, 'body_embedding', None)
                    
                    person_id = track_ref.global_person_id
                    if person_id in self._global_persons:
                        person = self._global_persons[person_id]
                        
                        reacquired = False
                        if face_embedding is not None:
                            reacquired = self._lifecycle.evaluate_reacquisition(person, face_embedding, EvidenceType.FACE_EMBEDDING)
                        
                        if not reacquired and body_embedding is not None:
                            reacquired = self._lifecycle.evaluate_reacquisition(person, body_embedding, EvidenceType.BODY_EMBEDDING)
                        
                        if reacquired:
                            # Reassign track
                            del self._track_identity[(cam_id, track_id)]
                            track_ref.camera_id = camera_id
                            track_ref.local_track_id = str(new_track.track_id)
                            track_ref.identity_state = IdentityState.REACQUIRED
                            track_ref.updated_at = current_time
                            self._track_identity[track_key] = track_ref
                            
                            # Update person
                            if face_embedding is not None:
                                person.face_embedding = self._update_aggregate_embedding(person.face_embedding, face_embedding, getattr(new_track, 'face_quality', 0.0))
                            if body_embedding is not None:
                                person.body_embedding = self._update_aggregate_embedding(person.body_embedding, body_embedding, getattr(new_track, 'body_quality', 0.0))
                            person.updated_at = current_time
                            
                            self._stats["reacquisitions"] += 1
                            logger.info(f"Track reacquired: {track_key} -> {person_id} (REACQUIRED)")
                            
                            return person_id, IdentityState.REACQUIRED
        
        # No reacquisition - register as new
        return self.register_track(camera_id, new_track)

    def _update_aggregate_embedding(
        self,
        current: Optional[np.ndarray],
        new: np.ndarray,
        quality: float,
    ) -> np.ndarray:
        """Update aggregate embedding with quality-weighted average."""
        if current is None:
            return new.copy()
        
        # Quality-weighted average
        total_quality = 1.0 + quality
        return (current + new * quality) / total_quality

    def _create_conflict(
        self,
        person_id_1: str,
        person_id_2: str,
        conflict_type: ConflictType,
        face_similarity: float,
        body_similarity: float,
    ) -> None:
        """Create and store a conflict."""
        if person_id_1 == person_id_2:
            return
        
        conflict_id = generate_conflict_id()
        conflict = IdentityConflict(
            conflict_id=conflict_id,
            person_id_1=person_id_1,
            person_id_2=person_id_2,
            conflict_type=conflict_type,
            face_similarity=face_similarity,
            body_similarity=body_similarity,
            detected_at=time.time(),
        )
        
        self._conflicts[conflict_id] = conflict
        
        # Update persons
        for pid in [person_id_1, person_id_2]:
            if pid in self._global_persons:
                self._global_persons[pid].conflict_count += 1
                self._global_persons[pid].state = IdentityState.CONFLICT
        
        self._stats["conflicts_detected"] += 1
        logger.warning(f"Conflict detected: {conflict_id} between {person_id_1} and {person_id_2} (type: {conflict_type.value})")

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        return {
            **self._stats,
            "global_persons": len(self._global_persons),
            "tracked_tracks": len(self._track_identity),
            "conflicts_total": len(self._conflicts),
            "evidence_stored": len(self._evidence_store),
        }

    def get_global_person(self, person_id: str) -> Optional[GlobalPersonID]:
        """Get global person by ID."""
        return self._global_persons.get(person_id)

    def list_global_persons(self) -> List[GlobalPersonID]:
        """List all global persons."""
        return list(self._global_persons.values())

    def clear(self) -> None:
        """Clear all state (for testing)."""
        self._global_persons.clear()
        self._track_identity.clear()
        self._conflicts.clear()
        self._evidence_store.clear()
        for key in self._stats:
            self._stats[key] = 0


def create_global_identity_service(config: Optional[GISConfig] = None) -> GlobalIdentityService:
    """Factory function to create GlobalIdentityService."""
    return GlobalIdentityService(config)