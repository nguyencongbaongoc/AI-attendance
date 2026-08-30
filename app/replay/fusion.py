"""
Phase 21 — Cross-Camera Identity / Observation Fusion.

Associates observations from independent camera-local tracks into a canonical
GlobalObservation when the evidence supports that they represent the same
cross-camera occurrence.

IMPORTANT:
- LocalTrack != GlobalObservation
- DO NOT simply merge local track IDs across cameras
- GlobalObservation represents a cross-camera observed occurrence
- It is NOT required to be a permanent global track
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from app.data.frame import CanonicalFrame
from app.replay.clock import ReplayTimestamp
from app.vision.temporal_evidence import (
    IdentityEvidence,
    IdentityHypothesis,
    HypothesisState,
    TemporalTimestamp,
    TimestampSource,
)

logger = logging.getLogger(__name__)


# =============================================================================
# ASSOCIATION STATES
# =============================================================================

class AssociationState(str, Enum):
    """Explicit association outcomes."""
    ASSOCIATED = "associated"              # Evidence supports cross-camera association
    NOT_ASSOCIATED = "not_associated"      # Evidence contradicts association
    AMBIGUOUS = "ambiguous"                # Multiple candidates with similar support
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # Not enough evidence to decide


# =============================================================================
# ASSOCIATION EVIDENCE
# =============================================================================

@dataclass(frozen=True)
class AssociationEvidence:
    """
    Evidence supporting or contradicting a cross-camera association.
    
    Each dimension is explicit and explainable.
    """
    # Timestamp compatibility
    timestamp_delta: float = 0.0           # Absolute time difference (seconds)
    timestamp_compatible: bool = False     # Within configured tolerance
    timestamp_tolerance: float = 1.0       # Configured tolerance
    
    # Geometry compatibility (when available)
    geometry_compatible: Optional[bool] = None  # None = unavailable
    geometry_confidence: float = 0.0
    geometry_provenance: Optional[str] = None
    
    # Direction compatibility (when available)
    direction_compatible: Optional[bool] = None  # None = unavailable
    direction_confidence: float = 0.0
    direction_provenance: Optional[str] = None
    
    # Track continuity
    track_continuity_score: float = 0.0    # How well local tracks align
    track_provenance: Dict[str, Any] = field(default_factory=dict)
    
    # Identity evidence
    identity_evidence_support: float = 0.0  # Combined identity support
    identity_candidates: List[str] = field(default_factory=list)
    identity_provenance: Dict[str, Any] = field(default_factory=dict)
    
    # Camera provenance
    camera_ids: Tuple[str, ...] = ()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_delta": self.timestamp_delta,
            "timestamp_compatible": self.timestamp_compatible,
            "timestamp_tolerance": self.timestamp_tolerance,
            "geometry_compatible": self.geometry_compatible,
            "geometry_confidence": self.geometry_confidence,
            "geometry_provenance": self.geometry_provenance,
            "direction_compatible": self.direction_compatible,
            "direction_confidence": self.direction_confidence,
            "direction_provenance": self.direction_provenance,
            "track_continuity_score": self.track_continuity_score,
            "track_provenance": self.track_provenance,
            "identity_evidence_support": self.identity_evidence_support,
            "identity_candidates": self.identity_candidates,
            "identity_provenance": self.identity_provenance,
            "camera_ids": self.camera_ids,
        }


# =============================================================================
# LOCAL OBSERVATION REFERENCE
# =============================================================================

@dataclass(frozen=True)
class LocalObservationRef:
    """
    Reference to a camera-local observation that contributes to a GlobalObservation.
    
    Preserves full provenance chain:
    GlobalObservation -> LocalObservationRef -> LocalTrack -> Camera -> Frame/Time -> Identity Evidence
    """
    camera_id: str
    local_track_id: str
    observation_id: str
    frame_index: int
    timestamp: ReplayTimestamp
    detection_id: Optional[str] = None
    face_crop_id: Optional[str] = None
    quality_class: Optional[str] = None
    identity_hypothesis: Optional[IdentityHypothesis] = None
    identity_evidence: Optional[IdentityEvidence] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "local_track_id": self.local_track_id,
            "observation_id": self.observation_id,
            "frame_index": self.frame_index,
            "timestamp": self.timestamp.to_dict(),
            "detection_id": self.detection_id,
            "face_crop_id": self.face_crop_id,
            "quality_class": self.quality_class,
            "identity_hypothesis": self.identity_hypothesis.to_dict() if self.identity_hypothesis else None,
            "identity_evidence": self.identity_evidence.to_dict() if self.identity_evidence else None,
        }


# =============================================================================
# GLOBAL OBSERVATION CONTRACT
# =============================================================================

@dataclass(frozen=True)
class GlobalObservation:
    """
    Canonical cross-camera observed occurrence.
    
    Represents an association of camera-local observations that evidence
    suggests represent the same real-world occurrence across cameras.
    
    NOT a permanent global track - just a bounded cross-camera observation.
    """
    # Stable unique identifier
    global_observation_id: str
    
    # Contributing camera-local observations
    observations: Tuple[LocalObservationRef, ...]
    
    # Association decision
    association_state: AssociationState
    association_evidence: AssociationEvidence
    
    # Temporal interval (min/max across contributing observations)
    temporal_start: ReplayTimestamp
    temporal_end: ReplayTimestamp
    temporal_span: float
    
    # Contributing cameras
    camera_ids: Tuple[str, ...]
    
    # Local track identifiers (preserved, NOT merged)
    local_track_ids: Tuple[str, ...]  # Format: "CAM1:track_A17", "CAM2:track_B04"
    
    # Identity evidence summary
    primary_identity_candidate: Optional[str] = None
    identity_confidence: float = 0.0
    identity_state: Optional[HypothesisState] = None
    
    # Configuration/version for reproducibility
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    model_versions: Dict[str, str] = field(default_factory=dict)
    
    # Creation metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    version: str = "1.0"
    
    def __post_init__(self):
        if not self.global_observation_id:
            raise ValueError("global_observation_id must be provided")
        if not self.observations:
            raise ValueError("observations must not be empty")
        if not isinstance(self.association_state, AssociationState):
            raise ValueError(f"association_state must be AssociationState, got {type(self.association_state)}")
    
    @property
    def is_associated(self) -> bool:
        return self.association_state == AssociationState.ASSOCIATED
    
    @property
    def is_ambiguous(self) -> bool:
        return self.association_state == AssociationState.AMBIGUOUS
    
    @property
    def is_insufficient(self) -> bool:
        return self.association_state == AssociationState.INSUFFICIENT_EVIDENCE
    
    @property
    def is_not_associated(self) -> bool:
        return self.association_state == AssociationState.NOT_ASSOCIATED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "global_observation_id": self.global_observation_id,
            "observations": [obs.to_dict() for obs in self.observations],
            "association_state": self.association_state.value,
            "association_evidence": self.association_evidence.to_dict(),
            "temporal_start": self.temporal_start.to_dict(),
            "temporal_end": self.temporal_end.to_dict(),
            "temporal_span": self.temporal_span,
            "camera_ids": list(self.camera_ids),
            "local_track_ids": list(self.local_track_ids),
            "primary_identity_candidate": self.primary_identity_candidate,
            "identity_confidence": self.identity_confidence,
            "identity_state": self.identity_state.value if self.identity_state else None,
            "config_snapshot": self.config_snapshot,
            "model_versions": self.model_versions,
            "created_at": self.created_at,
            "version": self.version,
        }


# =============================================================================
# FUSION CONFIGURATION
# =============================================================================

@dataclass(frozen=True)
class FusionConfig:
    """
    Configuration for cross-camera fusion.
    
    All values must be configurable, deterministic, and serializable.
    """
    # Timestamp association
    timestamp_tolerance: float = 1.0       # Max time delta for association (seconds)
    timestamp_policy: str = "strict"       # "strict" = require timestamps, "lenient" = allow not_available
    
    # Geometry association (when available)
    geometry_enabled: bool = False         # Requires calibrated camera relationship
    geometry_tolerance: float = 0.5        # Normalized distance tolerance
    
    # Direction association (when available)
    direction_enabled: bool = True
    direction_tolerance_degrees: float = 45.0  # Max angle difference
    
    # Track continuity
    track_continuity_weight: float = 0.3
    
    # Identity evidence
    identity_weight: float = 0.5
    min_identity_similarity: float = 0.4
    
    # Association thresholds
    association_threshold: float = 0.6     # Minimum combined score for ASSOCIATED
    ambiguity_margin: float = 0.15         # Gap between top candidates for AMBIGUOUS
    min_evidence_for_association: int = 2  # Minimum observations from different cameras
    
    # Bounded memory
    max_observation_window: int = 100      # Max observations to retain per camera
    max_temporal_window: float = 30.0      # Max temporal span (seconds)
    max_global_observations: int = 1000    # Max global observations to retain
    
    # Out-of-order handling
    out_of_order_policy: str = "sort"      # "sort", "reject", "accept"
    
    # Deduplication
    reject_duplicates: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_tolerance": self.timestamp_tolerance,
            "timestamp_policy": self.timestamp_policy,
            "geometry_enabled": self.geometry_enabled,
            "geometry_tolerance": self.geometry_tolerance,
            "direction_enabled": self.direction_enabled,
            "direction_tolerance_degrees": self.direction_tolerance_degrees,
            "track_continuity_weight": self.track_continuity_weight,
            "identity_weight": self.identity_weight,
            "min_identity_similarity": self.min_identity_similarity,
            "association_threshold": self.association_threshold,
            "ambiguity_margin": self.ambiguity_margin,
            "min_evidence_for_association": self.min_evidence_for_association,
            "max_observation_window": self.max_observation_window,
            "max_temporal_window": self.max_temporal_window,
            "max_global_observations": self.max_global_observations,
            "out_of_order_policy": self.out_of_order_policy,
            "reject_duplicates": self.reject_duplicates,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FusionConfig":
        return cls(**data)


DEFAULT_FUSION_CONFIG = FusionConfig()


# =============================================================================
# OBSERVATION BUILDER (from Phase 20 pipeline results)
# =============================================================================

def build_local_observation_ref(
    frame: CanonicalFrame,
    local_track_id: str,
    detection_id: Optional[str] = None,
    face_crop_id: Optional[str] = None,
    quality_class: Optional[str] = None,
    identity_hypothesis: Optional[IdentityHypothesis] = None,
    identity_evidence: Optional[IdentityEvidence] = None,
) -> LocalObservationRef:
    """
    Build a LocalObservationRef from a Phase 20 CanonicalFrame and associated data.
    
    Args:
        frame: CanonicalFrame from replay pipeline
        local_track_id: Camera-local track identifier
        detection_id: Face detection ID
        face_crop_id: Face crop ID
        quality_class: Face quality class (GOOD/MARGINAL/UNUSABLE)
        identity_hypothesis: Temporal identity hypothesis
        identity_evidence: Identity evidence
        
    Returns:
        LocalObservationRef with full provenance
    """
    camera_id = frame.metadata.extra.get("camera_id", "unknown")
    frame_index = frame.metadata.frame_index
    timestamp = frame.metadata.extra.get("replay_timestamp", {})
    replay_timestamp = ReplayTimestamp(
        value=timestamp.get("value", frame.metadata.timestamp or 0.0),
        source=timestamp.get("source", "frame_metadata")
    )
    
    observation_id = f"{camera_id}_{local_track_id}_f{frame_index}"
    
    return LocalObservationRef(
        camera_id=camera_id,
        local_track_id=local_track_id,
        observation_id=observation_id,
        frame_index=frame_index,
        timestamp=replay_timestamp,
        detection_id=detection_id,
        face_crop_id=face_crop_id,
        quality_class=quality_class,
        identity_hypothesis=identity_hypothesis,
        identity_evidence=identity_evidence,
    )


# =============================================================================
# CROSS-CAMERA ASSOCIATION ENGINE
# =============================================================================

class CrossCameraFusionEngine:
    """
    Cross-camera observation fusion engine.
    
    Consumes camera-local observations and produces GlobalObservations
    when evidence supports cross-camera association.
    
    Key principles:
    - LocalTrack != GlobalObservation (preserves camera-local identity)
    - Evidence-based association (timestamp, geometry, direction, track, identity)
    - Explicit association states (ASSOCIATED, NOT_ASSOCIATED, AMBIGUOUS, INSUFFICIENT_EVIDENCE)
    - Full provenance preservation
    - Deterministic: same inputs + config = same outputs
    - Bounded memory with explicit eviction policy
    - N-camera capable (not hardcoded to 2)
    """
    
    def __init__(self, config: FusionConfig = DEFAULT_FUSION_CONFIG):
        """
        Initialize the fusion engine.
        
        Args:
            config: Fusion configuration
        """
        self.config = config
        
        # Observation windows per camera: camera_id -> List[LocalObservationRef]
        self._observation_windows: Dict[str, List[LocalObservationRef]] = {}
        
        # Global observations produced
        self._global_observations: List[GlobalObservation] = []
        
        # Track seen observation IDs for deduplication
        self._seen_observation_ids: Set[str] = set()
        
        # Track local track IDs per camera for continuity
        self._camera_tracks: Dict[str, Set[str]] = {}
        
        logger.info("CrossCameraFusionEngine initialized")
    
    def add_observation(self, observation: LocalObservationRef) -> bool:
        """
        Add a camera-local observation to the fusion engine.
        
        Args:
            observation: LocalObservationRef to add
            
        Returns:
            True if added, False if rejected (duplicate or invalid)
        """
        # Deduplication
        if self.config.reject_duplicates:
            if observation.observation_id in self._seen_observation_ids:
                logger.debug(f"Rejected duplicate observation: {observation.observation_id}")
                return False
            self._seen_observation_ids.add(observation.observation_id)
        
        # Validate observation
        if not self._validate_observation(observation):
            return False
        
        # Get or create window for this camera
        camera_id = observation.camera_id
        if camera_id not in self._observation_windows:
            self._observation_windows[camera_id] = []
            self._camera_tracks[camera_id] = set()
        
        window = self._observation_windows[camera_id]
        
        # Handle out-of-order timestamps
        if self.config.out_of_order_policy == "sort":
            # Insert in sorted order by timestamp
            insert_idx = len(window)
            for i, obs in enumerate(window):
                if observation.timestamp < obs.timestamp:
                    insert_idx = i
                    break
            window.insert(insert_idx, observation)
        elif self.config.out_of_order_policy == "reject":
            # Check if new observation is older than last in window
            if window and observation.timestamp < window[-1].timestamp:
                logger.debug(f"Rejected out-of-order observation: {observation.observation_id}")
                return False
            else:
                window.append(observation)
        else:
            # "accept" policy: append as-is
            window.append(observation)
        
        # Track local track IDs
        self._camera_tracks[camera_id].add(observation.local_track_id)
        
        # Enforce bounds
        self._enforce_bounds(camera_id)
        
        return True
    
    def _validate_observation(self, observation: LocalObservationRef) -> bool:
        """Validate observation before adding."""
        if not observation.camera_id or not observation.local_track_id:
            logger.warning("Observation missing camera_id or local_track_id")
            return False
        if observation.timestamp.value < 0:
            logger.warning(f"Invalid timestamp: {observation.timestamp.value}")
            return False
        return True
    
    def _enforce_bounds(self, camera_id: str) -> None:
        """Enforce max_observation_window and max_temporal_window bounds."""
        window = self._observation_windows.get(camera_id, [])
        
        # Enforce max_observation_window (keep most recent)
        if len(window) > self.config.max_observation_window:
            removed = window[:-self.config.max_observation_window]
            for obs in removed:
                self._seen_observation_ids.discard(obs.observation_id)
            window[:] = window[-self.config.max_observation_window:]
        
        # Enforce max_temporal_window
        if window and self.config.max_temporal_window > 0:
            latest_ts = max(obs.timestamp.value for obs in window)
            cutoff = latest_ts - self.config.max_temporal_window
            
            to_remove = [obs for obs in window if obs.timestamp.value < cutoff]
            for obs in to_remove:
                self._seen_observation_ids.discard(obs.observation_id)
            window[:] = [obs for obs in window if obs.timestamp.value >= cutoff]
    
    def associate_observations(
        self,
        camera_ids: Optional[List[str]] = None,
    ) -> List[GlobalObservation]:
        """
        Perform cross-camera association on current observation windows.
        
        Args:
            camera_ids: Optional list of camera IDs to consider (default: all)
            
        Returns:
            List of GlobalObservation objects produced
        """
        if camera_ids is None:
            camera_ids = list(self._observation_windows.keys())
        
        if len(camera_ids) < 2:
            logger.debug("Need at least 2 cameras for cross-camera association")
            return []
        
        # Collect all observations from specified cameras
        all_observations = []
        for cam_id in camera_ids:
            all_observations.extend(self._observation_windows.get(cam_id, []))
        
        if len(all_observations) < self.config.min_evidence_for_association:
            logger.debug(f"Insufficient observations for association: {len(all_observations)}")
            return []
        
        # Sort by timestamp for deterministic processing
        all_observations.sort(key=lambda o: (o.timestamp.value, o.camera_id, o.observation_id))
        
        # Group observations by temporal proximity
        temporal_groups = self._group_by_temporal_proximity(all_observations)
        
        global_observations = []
        
        for group in temporal_groups:
            # Try to associate observations within this temporal group
            global_obs = self._associate_group(group)
            if global_obs:
                global_observations.append(global_obs)
                self._global_observations.append(global_obs)
        
        # Enforce global observation bounds
        self._enforce_global_bounds()
        
        return global_observations
    
    def _group_by_temporal_proximity(
        self,
        observations: List[LocalObservationRef],
    ) -> List[List[LocalObservationRef]]:
        """
        Group observations by temporal proximity.
        
        Observations within timestamp_tolerance of each other are grouped.
        """
        if not observations:
            return []
        
        groups = []
        current_group = [observations[0]]
        
        for obs in observations[1:]:
            # Check if this observation is within tolerance of the group's time range
            group_min_ts = min(o.timestamp.value for o in current_group)
            group_max_ts = max(o.timestamp.value for o in current_group)
            
            if (obs.timestamp.value - group_min_ts <= self.config.timestamp_tolerance and
                obs.timestamp.value - group_max_ts <= self.config.timestamp_tolerance):
                current_group.append(obs)
            else:
                groups.append(current_group)
                current_group = [obs]
        
        if current_group:
            groups.append(current_group)
        
        return groups
    
    def _associate_group(
        self,
        observations: List[LocalObservationRef],
    ) -> Optional[GlobalObservation]:
        """
        Attempt to associate a group of temporally proximate observations.
        
        Returns GlobalObservation if association succeeds, None otherwise.
        """
        # Must have observations from at least 2 different cameras
        camera_ids = set(obs.camera_id for obs in observations)
        if len(camera_ids) < 2:
            return None
        
        # Compute association evidence for all camera pairs
        camera_pairs = self._get_camera_pairs(observations)
        
        best_association = None
        best_score = 0.0
        
        for cam1, cam2 in camera_pairs:
            obs1_list = [o for o in observations if o.camera_id == cam1]
            obs2_list = [o for o in observations if o.camera_id == cam2]
            
            # Try all combinations of observations from the two cameras
            for obs1 in obs1_list:
                for obs2 in obs2_list:
                    evidence = self._compute_association_evidence(obs1, obs2)
                    score = self._compute_association_score(evidence)
                    
                    if score > best_score:
                        best_score = score
                        best_association = (obs1, obs2, evidence)
        
        if best_association is None:
            return None
        
        obs1, obs2, evidence = best_association
        
        # Determine association state
        if best_score >= self.config.association_threshold:
            state = AssociationState.ASSOCIATED
        elif best_score >= self.config.association_threshold - self.config.ambiguity_margin:
            state = AssociationState.AMBIGUOUS
        else:
            state = AssociationState.INSUFFICIENT_EVIDENCE
        
        # Check for competing associations (ambiguity)
        competing_scores = []
        for cam1, cam2 in camera_pairs:
            obs1_list = [o for o in observations if o.camera_id == cam1]
            obs2_list = [o for o in observations if o.camera_id == cam2]
            for o1 in obs1_list:
                for o2 in obs2_list:
                    if (o1, o2) != (obs1, obs2):
                        ev = self._compute_association_evidence(o1, o2)
                        sc = self._compute_association_score(ev)
                        competing_scores.append(sc)
        
        if competing_scores:
            max_competing = max(competing_scores)
            if best_score - max_competing < self.config.ambiguity_margin:
                state = AssociationState.AMBIGUOUS
        
        # Build GlobalObservation
        all_obs = [obs1, obs2]
        # Add any other observations from other cameras in the group
        for obs in observations:
            if obs not in all_obs:
                all_obs.append(obs)
        
        # Sort for deterministic ID generation
        all_obs.sort(key=lambda o: (o.camera_id, o.local_track_id, o.frame_index))
        
        global_obs_id = self._generate_global_observation_id(all_obs)
        
        # Temporal interval
        timestamps = [o.timestamp.value for o in all_obs]
        temporal_start = ReplayTimestamp(value=min(timestamps), source="fusion_min")
        temporal_end = ReplayTimestamp(value=max(timestamps), source="fusion_max")
        temporal_span = max(timestamps) - min(timestamps)
        
        # Local track IDs (preserved, NOT merged)
        local_track_ids = tuple(f"{o.camera_id}:{o.local_track_id}" for o in all_obs)
        
        # Identity evidence summary
        primary_identity = None
        identity_confidence = 0.0
        identity_state = None
        
        if evidence.identity_candidates:
            primary_identity = evidence.identity_candidates[0]
            identity_confidence = evidence.identity_evidence_support
            # Map to hypothesis state
            if identity_confidence >= 0.8:
                identity_state = HypothesisState.CONFIDENT
            elif identity_confidence >= 0.5:
                identity_state = HypothesisState.SUPPORTED
            elif identity_confidence > 0:
                identity_state = HypothesisState.AMBIGUOUS
            else:
                identity_state = HypothesisState.INSUFFICIENT
        
        return GlobalObservation(
            global_observation_id=global_obs_id,
            observations=tuple(all_obs),
            association_state=state,
            association_evidence=evidence,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            temporal_span=temporal_span,
            camera_ids=tuple(sorted(camera_ids)),
            local_track_ids=local_track_ids,
            primary_identity_candidate=primary_identity,
            identity_confidence=identity_confidence,
            identity_state=identity_state,
            config_snapshot=self.config.to_dict(),
            model_versions={
                "fusion": "1.0",
                "temporal_evidence": "1.0",
            },
        )
    
    def _get_camera_pairs(
        self,
        observations: List[LocalObservationRef],
    ) -> List[Tuple[str, str]]:
        """Get all unique camera pairs from observations."""
        camera_ids = sorted(set(obs.camera_id for obs in observations))
        pairs = []
        for i in range(len(camera_ids)):
            for j in range(i + 1, len(camera_ids)):
                pairs.append((camera_ids[i], camera_ids[j]))
        return pairs
    
    def _compute_association_evidence(
        self,
        obs1: LocalObservationRef,
        obs2: LocalObservationRef,
    ) -> AssociationEvidence:
        """Compute association evidence between two observations."""
        # Timestamp compatibility
        timestamp_delta = abs(obs1.timestamp.value - obs2.timestamp.value)
        timestamp_compatible = timestamp_delta <= self.config.timestamp_tolerance
        
        # Geometry compatibility (unavailable by default)
        geometry_compatible = None
        geometry_confidence = 0.0
        geometry_provenance = "unavailable"
        
        if self.config.geometry_enabled:
            # Would require calibrated camera relationship
            geometry_compatible = False
            geometry_provenance = "not_calibrated"
        
        # Direction compatibility (unavailable by default)
        direction_compatible = None
        direction_confidence = 0.0
        direction_provenance = "unavailable"
        
        if self.config.direction_enabled:
            # Would require direction vectors from tracking
            direction_compatible = None
            direction_provenance = "not_available"
        
        # Track continuity
        track_continuity_score = 0.0
        track_provenance = {
            "track1": f"{obs1.camera_id}:{obs1.local_track_id}",
            "track2": f"{obs2.camera_id}:{obs2.local_track_id}",
        }
        
        # Identity evidence
        identity_evidence_support = 0.0
        identity_candidates = []
        identity_provenance = {}
        
        # Check if both observations have identity hypotheses
        if obs1.identity_hypothesis and obs2.identity_hypothesis:
            hyp1 = obs1.identity_hypothesis
            hyp2 = obs2.identity_hypothesis
            
            if hyp1.candidate_identity and hyp2.candidate_identity:
                if hyp1.candidate_identity == hyp2.candidate_identity:
                    # Same identity candidate - strong support
                    identity_evidence_support = min(hyp1.weighted_score, hyp2.weighted_score) / 10.0
                    identity_candidates = [hyp1.candidate_identity]
                    identity_provenance = {
                        "hypothesis1": hyp1.hypothesis_id,
                        "hypothesis2": hyp2.hypothesis_id,
                        "similarity1": hyp1.best_similarity,
                        "similarity2": hyp2.best_similarity,
                    }
                else:
                    # Different identity candidates - contradiction
                    identity_evidence_support = 0.0
                    identity_candidates = [hyp1.candidate_identity, hyp2.candidate_identity]
                    identity_provenance = {
                        "hypothesis1": hyp1.hypothesis_id,
                        "hypothesis2": hyp2.hypothesis_id,
                        "conflict": True,
                    }
        
        return AssociationEvidence(
            timestamp_delta=timestamp_delta,
            timestamp_compatible=timestamp_compatible,
            timestamp_tolerance=self.config.timestamp_tolerance,
            geometry_compatible=geometry_compatible,
            geometry_confidence=geometry_confidence,
            geometry_provenance=geometry_provenance,
            direction_compatible=direction_compatible,
            direction_confidence=direction_confidence,
            direction_provenance=direction_provenance,
            track_continuity_score=track_continuity_score,
            track_provenance=track_provenance,
            identity_evidence_support=identity_evidence_support,
            identity_candidates=identity_candidates,
            identity_provenance=identity_provenance,
            camera_ids=(obs1.camera_id, obs2.camera_id),
        )
    
    def _compute_association_score(self, evidence: AssociationEvidence) -> float:
        """Compute combined association score from evidence."""
        score = 0.0
        
        # Timestamp component (primary signal)
        if evidence.timestamp_compatible:
            # Linear decay within tolerance
            timestamp_score = 1.0 - (evidence.timestamp_delta / evidence.timestamp_tolerance)
            score += timestamp_score * 1.0  # Timestamp is primary signal
        
        # Geometry component (if available)
        if evidence.geometry_compatible is not None:
            if evidence.geometry_compatible:
                score += evidence.geometry_confidence * 0.2
            else:
                score -= 0.2  # Penalty for geometry conflict
        
        # Direction component (if available)
        if evidence.direction_compatible is not None:
            if evidence.direction_compatible:
                score += evidence.direction_confidence * 0.1
            else:
                score -= 0.1  # Penalty for direction conflict
        
        # Track continuity component
        score += evidence.track_continuity_score * self.config.track_continuity_weight
        
        # Identity evidence component
        score += evidence.identity_evidence_support * self.config.identity_weight
        
        return max(0.0, min(1.0, score))
    
    def _generate_global_observation_id(
        self,
        observations: List[LocalObservationRef],
    ) -> str:
        """Generate deterministic global observation ID."""
        # Create deterministic content from observations
        content_parts = []
        for obs in observations:
            content_parts.append(f"{obs.camera_id}:{obs.local_track_id}:{obs.frame_index}:{obs.timestamp.value}")
        
        content = "|".join(content_parts)
        hash_digest = hashlib.md5(content.encode()).hexdigest()[:12]
        return f"GO-{hash_digest}"
    
    def _enforce_global_bounds(self) -> None:
        """Enforce max_global_observations bound."""
        if len(self._global_observations) > self.config.max_global_observations:
            # Remove oldest global observations
            excess = len(self._global_observations) - self.config.max_global_observations
            self._global_observations = self._global_observations[excess:]
    
    def get_global_observations(self) -> List[GlobalObservation]:
        """Get all global observations produced so far."""
        return list(self._global_observations)
    
    def get_observation_window_size(self, camera_id: str) -> int:
        """Get current observation window size for a camera."""
        return len(self._observation_windows.get(camera_id, []))
    
    def clear_camera_window(self, camera_id: str) -> None:
        """Clear observation window for a camera."""
        if camera_id in self._observation_windows:
            for obs in self._observation_windows[camera_id]:
                self._seen_observation_ids.discard(obs.observation_id)
            self._observation_windows[camera_id].clear()
            self._camera_tracks[camera_id].clear()
    
    def clear_all(self) -> None:
        """Clear all observation windows and global observations."""
        self._observation_windows.clear()
        self._camera_tracks.clear()
        self._seen_observation_ids.clear()
        self._global_observations.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "cameras": list(self._observation_windows.keys()),
            "observation_window_sizes": {
                cam: len(obs) for cam, obs in self._observation_windows.items()
            },
            "total_observations": sum(len(obs) for obs in self._observation_windows.values()),
            "global_observations_count": len(self._global_observations),
            "seen_observation_ids": len(self._seen_observation_ids),
            "camera_tracks": {
                cam: list(tracks) for cam, tracks in self._camera_tracks.items()
            },
            "config": self.config.to_dict(),
        }


def create_fusion_engine(config: Optional[FusionConfig] = None) -> CrossCameraFusionEngine:
    """
    Factory function to create a CrossCameraFusionEngine.
    
    Args:
        config: Optional custom configuration (uses defaults if None).
        
    Returns:
        CrossCameraFusionEngine instance.
    """
    if config is None:
        config = DEFAULT_FUSION_CONFIG
    return CrossCameraFusionEngine(config=config)
