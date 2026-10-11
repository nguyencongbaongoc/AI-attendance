"""
Phase 18 — Temporal Identity Evidence Aggregation.

This module implements bounded temporal evidence aggregation for identity hypotheses.
It consumes Phase 17 FaceQualityResult and produces IdentityHypothesis.

CRITICAL ARCHITECTURE RULES:
- Does NOT replace detector, crop, tracking, ArcFace, identity matching, or attendance logic
- Consumes Phase 17 quality (GOOD/MARGINAL/UNUSABLE) instead of duplicating quality calculation
- Bounded evidence window (configurable max_samples, max_duration)
- Quality-aware aggregation: GOOD > MARGINAL > UNUSABLE (excluded)
- Candidate aggregation per identity with temporal consistency
- Explicit ambiguity states: CONFIDENT / SUPPORTED / AMBIGUOUS / INSUFFICIENT
- Track isolation: evidence partitioned by (camera_id, track_id)
- Deterministic: same evidence + config + ordering = same hypothesis
- Offline-only: no camera, streaming, or live pipeline dependencies
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.face_quality import FaceQualityResult, QualityClass, QualityProvenance

logger = logging.getLogger(__name__)


# =============================================================================
# TIME CONTRACT
# =============================================================================

class TimestampSource(str, Enum):
    """Source of timestamp for temporal ordering."""
    SOURCE_PTS = "source_pts"           # Presentation timestamp from source
    CAPTURE_TIMESTAMP = "capture_timestamp"  # Camera capture timestamp
    MONOTONIC_TIMESTAMP = "monotonic_timestamp"  # System monotonic clock
    PROCESSING_TIMESTAMP = "processing_timestamp"  # Processing completion time
    NOT_AVAILABLE = "not_available"     # No timestamp available


@dataclass(frozen=True)
class TemporalTimestamp:
    """
    Explicit timestamp with source attribution.
    
    Temporal ordering MUST prefer source/capture time over processing time.
    """
    value: float  # Unix timestamp in seconds
    source: TimestampSource
    
    def __lt__(self, other: "TemporalTimestamp") -> bool:
        return self.value < other.value
    
    def __le__(self, other: "TemporalTimestamp") -> bool:
        return self.value <= other.value
    
    def __gt__(self, other: "TemporalTimestamp") -> bool:
        return self.value > other.value
    
    def __ge__(self, other: "TemporalTimestamp") -> bool:
        return self.value >= other.value
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source.value,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalTimestamp":
        return cls(
            value=data["value"],
            source=TimestampSource(data["source"]),
        )
    
    @classmethod
    def not_available(cls) -> "TemporalTimestamp":
        return cls(value=0.0, source=TimestampSource.NOT_AVAILABLE)


# =============================================================================
# IDENTITY EVIDENCE CONTRACT
# =============================================================================

@dataclass(frozen=True)
class IdentityEvidence:
    """
    Single-frame identity evidence with full provenance to ORIGINAL_FRAME.
    
    Trace chain:
    IdentityEvidence
        ↓
    FaceQualityResult
        ↓
    AdaptiveCropResult
        ↓
    Original Frame
    """
    
    # Evidence identification (must be provided explicitly for determinism)
    evidence_id: str
    
    # Frame identification
    frame_id: str = ""
    camera_id: str = ""
    track_id: str = ""
    
    # Temporal ordering (prefer source/capture time)
    timestamp: TemporalTimestamp = field(default_factory=TemporalTimestamp.not_available)
    
    # Identity candidate
    identity_candidate: str = ""  # Enrolled identity ID or "unknown"
    similarity: float = 0.0       # Cosine similarity [0, 1] from ArcFace matching
    
    # Quality from Phase 17
    quality_class: QualityClass = QualityClass.UNUSABLE
    quality_metrics_ref: Optional[Dict[str, Any]] = None  # Reference to quality metrics
    
    # Pose from Phase 15 (via Phase 17 provenance)
    pose_state: Optional[str] = None  # NORMAL, HARD_POSE, INVALID
    
    # Full provenance chain
    provenance: Optional[QualityProvenance] = None
    
    def __post_init__(self):
        if not isinstance(self.quality_class, QualityClass):
            raise ValueError(f"quality_class must be QualityClass, got {type(self.quality_class)}")
        if not 0.0 <= self.similarity <= 1.0:
            raise ValueError(f"similarity must be in [0, 1], got {self.similarity}")
        if not self.evidence_id:
            raise ValueError("evidence_id must be provided")
    
    @property
    def is_eligible(self) -> bool:
        """Check if evidence is eligible for identity aggregation."""
        return self.quality_class == QualityClass.GOOD
    
    @property
    def is_marginal(self) -> bool:
        """Check if evidence is marginal quality."""
        return self.quality_class == QualityClass.MARGINAL
    
    @property
    def is_unusable(self) -> bool:
        """Check if evidence is unusable."""
        return self.quality_class == QualityClass.UNUSABLE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "frame_id": self.frame_id,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "timestamp": self.timestamp.to_dict(),
            "identity_candidate": self.identity_candidate,
            "similarity": self.similarity,
            "quality_class": self.quality_class.value,
            "quality_metrics_ref": self.quality_metrics_ref,
            "pose_state": self.pose_state,
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }
    
    @classmethod
    def from_face_quality_result(
        cls,
        face_quality: FaceQualityResult,
        identity_candidate: str,
        similarity: float,
        frame_id: str,
        camera_id: str,
        track_id: str,
        timestamp: Optional[TemporalTimestamp] = None,
    ) -> "IdentityEvidence":
        """Create IdentityEvidence from Phase 17 FaceQualityResult."""
        prov = face_quality.provenance
        
        return cls(
            evidence_id=f"ev_{uuid.uuid4().hex[:8]}",
            frame_id=frame_id,
            camera_id=camera_id,
            track_id=track_id,
            timestamp=timestamp or TemporalTimestamp.not_available(),
            identity_candidate=identity_candidate,
            similarity=similarity,
            quality_class=face_quality.quality_class,
            quality_metrics_ref={
                m.name: {"measurement": m.measurement, "status": m.status.value}
                for m in face_quality.metrics
            },
            pose_state=prov.pose_state if prov else None,
            provenance=prov,
        )


# =============================================================================
# IDENTITY HYPOTHESIS CONTRACT
# =============================================================================

class HypothesisState(str, Enum):
    """State of identity hypothesis."""
    CONFIDENT = "confident"       # Strong evidence, single dominant candidate
    SUPPORTED = "supported"       # Evidence supports candidate but not dominant
    AMBIGUOUS = "ambiguous"       # Multiple candidates with similar support
    INSUFFICIENT = "insufficient" # Not enough eligible evidence


@dataclass(frozen=True)
class CandidateSupport:
    """Support metrics for a single identity candidate."""
    candidate_id: str
    evidence_count: int
    eligible_evidence_count: int
    marginal_evidence_count: int
    weighted_score: float
    best_similarity: float
    temporal_span: float  # seconds
    first_timestamp: Optional[TemporalTimestamp]
    last_timestamp: Optional[TemporalTimestamp]
    supporting_evidence_ids: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "evidence_count": self.evidence_count,
            "eligible_evidence_count": self.eligible_evidence_count,
            "marginal_evidence_count": self.marginal_evidence_count,
            "weighted_score": self.weighted_score,
            "best_similarity": self.best_similarity,
            "temporal_span": self.temporal_span,
            "first_timestamp": self.first_timestamp.to_dict() if self.first_timestamp else None,
            "last_timestamp": self.last_timestamp.to_dict() if self.last_timestamp else None,
            "supporting_evidence_ids": self.supporting_evidence_ids,
        }


@dataclass(frozen=True)
class IdentityHypothesis:
    """
    Temporal identity hypothesis from bounded evidence window.
    
    This is NOT a final attendance decision.
    This is NOT a calibrated probability.
    This IS a deterministic aggregation of temporal evidence.
    """
    
    # Hypothesis identification (deterministic based on content)
    hypothesis_id: str = ""
    
    # Track identification
    camera_id: str = ""
    track_id: str = ""
    
    # Primary candidate
    candidate_identity: str = ""
    
    # Evidence counts
    evidence_count: int = 0
    eligible_evidence_count: int = 0
    
    # Aggregation scores
    weighted_score: float = 0.0
    best_similarity: float = 0.0
    
    # Temporal span
    temporal_span: float = 0.0
    first_timestamp: Optional[TemporalTimestamp] = None
    last_timestamp: Optional[TemporalTimestamp] = None
    
    # State
    state: HypothesisState = HypothesisState.INSUFFICIENT
    
    # Ambiguity
    ambiguity_margin: float = 0.0  # Gap between top-1 and top-2 candidate scores
    competing_candidates: List[CandidateSupport] = field(default_factory=list)
    
    # Best evidence reference
    best_evidence_id: Optional[str] = None
    best_evidence_similarity: float = 0.0
    best_evidence_quality: Optional[QualityClass] = None
    
    # All candidate supports
    all_candidates: List[CandidateSupport] = field(default_factory=list)
    
    # Configuration used
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not isinstance(self.state, HypothesisState):
            raise ValueError(f"state must be HypothesisState, got {type(self.state)}")
        if not self.hypothesis_id:
            # Generate deterministic ID based on content
            import hashlib
            content = f"{self.camera_id}_{self.track_id}_{self.candidate_identity}_{self.evidence_count}_{self.eligible_evidence_count}_{self.weighted_score}_{self.state.value}"
            object.__setattr__(self, 'hypothesis_id', f"hyp_{hashlib.md5(content.encode()).hexdigest()[:8]}")
    
    @property
    def is_confident(self) -> bool:
        return self.state == HypothesisState.CONFIDENT
    
    @property
    def is_supported(self) -> bool:
        return self.state == HypothesisState.SUPPORTED
    
    @property
    def is_ambiguous(self) -> bool:
        return self.state == HypothesisState.AMBIGUOUS
    
    @property
    def is_insufficient(self) -> bool:
        return self.state == HypothesisState.INSUFFICIENT
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "candidate_identity": self.candidate_identity,
            "evidence_count": self.evidence_count,
            "eligible_evidence_count": self.eligible_evidence_count,
            "weighted_score": self.weighted_score,
            "best_similarity": self.best_similarity,
            "temporal_span": self.temporal_span,
            "first_timestamp": self.first_timestamp.to_dict() if self.first_timestamp else None,
            "last_timestamp": self.last_timestamp.to_dict() if self.last_timestamp else None,
            "state": self.state.value,
            "ambiguity_margin": self.ambiguity_margin,
            "competing_candidates": [c.to_dict() for c in self.competing_candidates],
            "best_evidence_id": self.best_evidence_id,
            "best_evidence_similarity": self.best_evidence_similarity,
            "best_evidence_quality": self.best_evidence_quality.value if self.best_evidence_quality else None,
            "all_candidates": [c.to_dict() for c in self.all_candidates],
            "config_snapshot": self.config_snapshot,
        }


# =============================================================================
# EVIDENCE WINDOW CONFIGURATION
# =============================================================================

@dataclass(frozen=True)
class EvidenceWindowConfig:
    """
    Configuration for bounded evidence window.
    
    All values must be configurable, deterministic, and serializable.
    """
    # Maximum number of evidence samples to retain
    max_samples: int = 100
    
    # Maximum temporal duration in seconds
    max_duration: float = 30.0
    
    # Quality weights (engineering defaults, not production calibrated)
    good_weight: float = 1.0
    marginal_weight: float = 0.3
    unusable_weight: float = 0.0  # UNUSABLE excluded from aggregation
    
    # Minimum eligible evidence for hypothesis
    min_eligible_evidence: int = 3
    
    # Minimum temporal span for hypothesis (seconds)
    min_temporal_span: float = 1.0
    
    # Ambiguity margin threshold (gap between top-1 and top-2)
    ambiguity_margin: float = 0.15
    
    # Minimum support count for CONFIDENT state
    min_confident_support: int = 5
    
    # Deduplication: reject duplicate evidence_id
    reject_duplicates: bool = True
    
    # Out-of-order timestamp policy
    # "sort" = sort by source timestamp, "reject" = reject out-of-order, "accept" = accept arrival order
    out_of_order_policy: str = "sort"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_samples": self.max_samples,
            "max_duration": self.max_duration,
            "good_weight": self.good_weight,
            "marginal_weight": self.marginal_weight,
            "unusable_weight": self.unusable_weight,
            "min_eligible_evidence": self.min_eligible_evidence,
            "min_temporal_span": self.min_temporal_span,
            "ambiguity_margin": self.ambiguity_margin,
            "min_confident_support": self.min_confident_support,
            "reject_duplicates": self.reject_duplicates,
            "out_of_order_policy": self.out_of_order_policy,
        }


DEFAULT_WINDOW_CONFIG = EvidenceWindowConfig()


# =============================================================================
# TEMPORAL EVIDENCE AGGREGATOR
# =============================================================================

class TemporalEvidenceAggregator:
    """
    Bounded temporal evidence aggregator for identity hypotheses.
    
    Maintains a sliding window of evidence per (camera_id, track_id).
    Aggregates quality-aware evidence into IdentityHypothesis.
    """
    
    def __init__(
        self,
        config: EvidenceWindowConfig = DEFAULT_WINDOW_CONFIG,
    ):
        """
        Initialize the temporal evidence aggregator.
        
        Args:
            config: Evidence window configuration.
        """
        self.config = config
        
        # Evidence storage: (camera_id, track_id) -> List[IdentityEvidence]
        self._evidence_windows: Dict[Tuple[str, str], List[IdentityEvidence]] = {}
        
        # Track seen evidence IDs for deduplication
        self._seen_evidence_ids: set = set()
    
    def add_evidence(
        self,
        evidence: IdentityEvidence,
    ) -> bool:
        """
        Add evidence to the temporal window.
        
        Args:
            evidence: IdentityEvidence to add.
            
        Returns:
            True if evidence was added, False if rejected (duplicate or invalid).
        """
        # Deduplication
        if self.config.reject_duplicates:
            if evidence.evidence_id in self._seen_evidence_ids:
                logger.debug(f"Rejected duplicate evidence: {evidence.evidence_id}")
                return False
            self._seen_evidence_ids.add(evidence.evidence_id)
        
        # Validate evidence
        if not self._validate_evidence(evidence):
            return False
        
        # Get or create window
        key = (evidence.camera_id, evidence.track_id)
        if key not in self._evidence_windows:
            self._evidence_windows[key] = []
        
        window = self._evidence_windows[key]
        
        # Handle out-of-order timestamps
        if self.config.out_of_order_policy == "sort":
            # Insert in sorted order by timestamp
            insert_idx = len(window)
            for i, ev in enumerate(window):
                if evidence.timestamp < ev.timestamp:
                    insert_idx = i
                    break
            window.insert(insert_idx, evidence)
        elif self.config.out_of_order_policy == "reject":
            # Check if new evidence is older than last in window
            if window and evidence.timestamp < window[-1].timestamp:
                logger.debug(f"Rejected out-of-order evidence: {evidence.evidence_id}")
                return False
            else:
                window.append(evidence)
        else:
            # "accept" policy: append as-is (default)
            window.append(evidence)
        
        # Enforce bounds
        self._enforce_bounds(window)
        
        return True
    
    def _validate_evidence(self, evidence: IdentityEvidence) -> bool:
        """Validate evidence before adding."""
        if not evidence.camera_id or not evidence.track_id:
            logger.warning("Evidence missing camera_id or track_id")
            return False
        if not evidence.identity_candidate:
            logger.warning("Evidence missing identity_candidate")
            return False
        if not 0.0 <= evidence.similarity <= 1.0:
            logger.warning(f"Invalid similarity: {evidence.similarity}")
            return False
        return True
    
    def _handle_out_of_order(
        self,
        window: List[IdentityEvidence],
        new_evidence: IdentityEvidence,
    ) -> Tuple[List[IdentityEvidence], bool]:
        """Handle out-of-order timestamp insertion.
        
        Returns:
            Tuple of (window, inserted) where inserted is True if evidence was inserted.
        """
        if self.config.out_of_order_policy == "reject":
            # Check if new evidence is older than last in window
            if window and new_evidence.timestamp < window[-1].timestamp:
                logger.debug(f"Rejected out-of-order evidence: {new_evidence.evidence_id}")
                return window, False
        elif self.config.out_of_order_policy == "sort":
            # Insert in sorted order by timestamp
            # Find insertion point
            insert_idx = len(window)
            for i, ev in enumerate(window):
                if new_evidence.timestamp < ev.timestamp:
                    insert_idx = i
                    break
            window.insert(insert_idx, new_evidence)
            return window, True
        # "accept" policy: append as-is (default)
        return window, False
    
    def _enforce_bounds(self, window: List[IdentityEvidence]) -> None:
        """Enforce max_samples and max_duration bounds."""
        # Enforce max_samples (keep most recent)
        if len(window) > self.config.max_samples:
            # Remove oldest
            removed = window[:-self.config.max_samples]
            for ev in removed:
                self._seen_evidence_ids.discard(ev.evidence_id)
            window[:] = window[-self.config.max_samples:]
        
        # Enforce max_duration
        if window and self.config.max_duration > 0:
            # Find cutoff timestamp
            latest_ts = max(ev.timestamp.value for ev in window)
            cutoff = latest_ts - self.config.max_duration
            
            # Keep only evidence within duration
            # Store evidence IDs to remove before filtering
            to_remove = [ev for ev in window if ev.timestamp.value < cutoff]
            for ev in to_remove:
                self._seen_evidence_ids.discard(ev.evidence_id)
            window[:] = [ev for ev in window if ev.timestamp.value >= cutoff]
    
    def compute_hypothesis(
        self,
        camera_id: str,
        track_id: str,
    ) -> IdentityHypothesis:
        """
        Compute identity hypothesis from current evidence window.
        
        Args:
            camera_id: Camera identifier.
            track_id: Track identifier.
            
        Returns:
            IdentityHypothesis for the track.
        """
        key = (camera_id, track_id)
        window = self._evidence_windows.get(key, [])
        
        if not window:
            return IdentityHypothesis(
                camera_id=camera_id,
                track_id=track_id,
                state=HypothesisState.INSUFFICIENT,
                config_snapshot=self.config.to_dict(),
            )
        
        # Sort by timestamp for temporal consistency
        sorted_window = sorted(window, key=lambda e: e.timestamp.value)
        
        # Aggregate by candidate
        candidate_evidence: Dict[str, List[IdentityEvidence]] = {}
        for ev in sorted_window:
            if ev.identity_candidate not in candidate_evidence:
                candidate_evidence[ev.identity_candidate] = []
            candidate_evidence[ev.identity_candidate].append(ev)
        
        # Compute support for each candidate
        candidate_supports = []
        for candidate_id, evidences in candidate_evidence.items():
            support = self._compute_candidate_support(candidate_id, evidences)
            candidate_supports.append(support)
        
        # Sort by weighted_score descending
        candidate_supports.sort(key=lambda c: c.weighted_score, reverse=True)
        
        if not candidate_supports:
            return IdentityHypothesis(
                camera_id=camera_id,
                track_id=track_id,
                state=HypothesisState.INSUFFICIENT,
                config_snapshot=self.config.to_dict(),
            )
        
        # Primary candidate
        primary = candidate_supports[0]
        
        # Determine state
        state = self._determine_state(primary, candidate_supports)
        
        # Compute ambiguity margin
        ambiguity_margin = 0.0
        if len(candidate_supports) >= 2:
            ambiguity_margin = primary.weighted_score - candidate_supports[1].weighted_score
        
        # Find best evidence
        best_evidence = max(sorted_window, key=lambda e: e.similarity)
        
        # Temporal span
        first_ts = sorted_window[0].timestamp
        last_ts = sorted_window[-1].timestamp
        temporal_span = last_ts.value - first_ts.value if first_ts.value > 0 and last_ts.value > 0 else 0.0
        
        return IdentityHypothesis(
            camera_id=camera_id,
            track_id=track_id,
            candidate_identity=primary.candidate_id,
            evidence_count=len(sorted_window),
            eligible_evidence_count=primary.eligible_evidence_count,
            weighted_score=primary.weighted_score,
            best_similarity=primary.best_similarity,
            temporal_span=temporal_span,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            state=state,
            ambiguity_margin=ambiguity_margin,
            competing_candidates=candidate_supports[1:3],  # Top 2 competitors
            best_evidence_id=best_evidence.evidence_id,
            best_evidence_similarity=best_evidence.similarity,
            best_evidence_quality=best_evidence.quality_class,
            all_candidates=candidate_supports,
            config_snapshot=self.config.to_dict(),
        )
    
    def _compute_candidate_support(
        self,
        candidate_id: str,
        evidences: List[IdentityEvidence],
    ) -> CandidateSupport:
        """Compute support metrics for a candidate."""
        eligible = [e for e in evidences if e.is_eligible]
        marginal = [e for e in evidences if e.is_marginal]
        unusable = [e for e in evidences if e.is_unusable]
        
        # Weighted score: GOOD * good_weight + MARGINAL * marginal_weight
        weighted_score = (
            len(eligible) * self.config.good_weight +
            len(marginal) * self.config.marginal_weight
        )
        
        # Best similarity from eligible evidence
        best_similarity = 0.0
        if eligible:
            best_similarity = max(e.similarity for e in eligible)
        elif marginal:
            best_similarity = max(e.similarity for e in marginal)
        elif unusable:
            best_similarity = max(e.similarity for e in unusable)
        
        # Temporal span
        first_ts = evidences[0].timestamp
        last_ts = evidences[-1].timestamp
        temporal_span = last_ts.value - first_ts.value if first_ts.value > 0 and last_ts.value > 0 else 0.0
        
        return CandidateSupport(
            candidate_id=candidate_id,
            evidence_count=len(evidences),
            eligible_evidence_count=len(eligible),
            marginal_evidence_count=len(marginal),
            weighted_score=weighted_score,
            best_similarity=best_similarity,
            temporal_span=temporal_span,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            supporting_evidence_ids=[e.evidence_id for e in evidences],
        )
    
    def _determine_state(
        self,
        primary: CandidateSupport,
        all_candidates: List[CandidateSupport],
    ) -> HypothesisState:
        """Determine hypothesis state from candidate supports."""
        # INSUFFICIENT: not enough eligible evidence or temporal span
        if primary.eligible_evidence_count < self.config.min_eligible_evidence:
            return HypothesisState.INSUFFICIENT
        if primary.temporal_span < self.config.min_temporal_span:
            return HypothesisState.INSUFFICIENT
        
        # AMBIGUOUS: close competition
        if len(all_candidates) >= 2:
            runner_up = all_candidates[1]
            if primary.weighted_score - runner_up.weighted_score < self.config.ambiguity_margin:
                return HypothesisState.AMBIGUOUS
        
        # CONFIDENT: strong support
        if primary.eligible_evidence_count >= self.config.min_confident_support:
            return HypothesisState.CONFIDENT
        
        # SUPPORTED: some evidence but not confident
        return HypothesisState.SUPPORTED
    
    def finalize_track(
        self,
        camera_id: str,
        track_id: str,
    ) -> IdentityHypothesis:
        """
        Finalize hypothesis for a track that has ended.
        
        Does NOT create attendance events.
        """
        hypothesis = self.compute_hypothesis(camera_id, track_id)
        
        # Clear window after finalization
        key = (camera_id, track_id)
        if key in self._evidence_windows:
            for ev in self._evidence_windows[key]:
                self._seen_evidence_ids.discard(ev.evidence_id)
            del self._evidence_windows[key]
        
        return hypothesis
    
    def get_window_size(self, camera_id: str, track_id: str) -> int:
        """Get current evidence window size for a track."""
        key = (camera_id, track_id)
        return len(self._evidence_windows.get(key, []))
    
    def clear_track(self, camera_id: str, track_id: str) -> None:
        """Clear evidence window for a track without finalizing."""
        key = (camera_id, track_id)
        if key in self._evidence_windows:
            for ev in self._evidence_windows[key]:
                self._seen_evidence_ids.discard(ev.evidence_id)
            del self._evidence_windows[key]
    
    def clear_all(self) -> None:
        """Clear all evidence windows."""
        self._evidence_windows.clear()
        self._seen_evidence_ids.clear()


def create_temporal_aggregator(
    config: Optional[EvidenceWindowConfig] = None,
) -> TemporalEvidenceAggregator:
    """
    Factory function to create a TemporalEvidenceAggregator.
    
    Args:
        config: Optional custom configuration (uses defaults if None).
        
    Returns:
        TemporalEvidenceAggregator instance.
    """
    if config is None:
        config = DEFAULT_WINDOW_CONFIG
    return TemporalEvidenceAggregator(config=config)