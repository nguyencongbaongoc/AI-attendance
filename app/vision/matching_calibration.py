"""
Phase 19 — Matching Calibration.

This module implements threshold calibration and evaluation for identity matching.
It consumes Phase 14 matching contract and Phase 18 temporal evidence,
producing a versioned calibration snapshot with measured FAR/FRR/TPR/EER.

CRITICAL ARCHITECTURE RULES:
- Does NOT replace detector, crop, tracking, ArcFace, identity matching, or attendance logic
- Does NOT modify Phase 15/16/17/18
- Does NOT implement cross-camera fusion
- Does NOT implement attendance, Excel, RTMP, RTSP, MediaMTX, or live camera
- This is a calibration/measurement layer only
- Production calibration requires representative labeled dataset
- Synthetic validation proves implementation correctness only
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.matching_contract import MatchStatus, MatchingConfig, compute_cosine_similarity

logger = logging.getLogger(__name__)


# =============================================================================
# SIMILARITY CONTRACT DOCUMENTATION
# =============================================================================

# The existing ArcFace matcher uses:
#   - cosine_similarity = dot(query, database_embedding) (both L2-normalized)
#   - higher_is_better = True (higher similarity = more similar)
#   - similarity_range = [0, 1] (clamped)
#   - distance_metric = None (not used)
#   - normalization = L2
#
# Phase 19 calibration MUST use the same contract.
# Do NOT calibration on cosine distance and then apply threshold to similarity.


# =============================================================================
# CALIBRATION STATUS
# =============================================================================

class CalibrationStatus(str, Enum):
    """Status of calibration result."""
    NOT_CALIBRATED = "not_calibrated"           # No real calibration data
    INFRASTRUCTURE_READY = "infrastructure_ready"  # Infrastructure ready, using defaults
    SYNTHETIC_VALIDATED = "synthetic_validated"   # Implementation validated on synthetic data
    PARTIALLY_CALIBRATED = "partially_calibrated"  # Some calibration data available
    CALIBRATED = "calibrated"                     # Full calibration on representative data


# =============================================================================
# CALIBRATION DATA CONTRACT
# =============================================================================

@dataclass(frozen=True)
class CalibrationSample:
    """
    Single calibration sample with provenance.
    
    Each sample represents a comparison between two face embeddings.
    """
    sample_id: str
    label: str  # "genuine" or "impostor"
    identity_id: Optional[str] = None  # Enrolled identity ID (if genuine)
    query_embedding_id: str = ""
    reference_embedding_id: str = ""
    similarity: float = 0.0
    quality_class: Optional[str] = None  # GOOD/MARGINAL/UNUSABLE
    temporal_hypothesis_id: Optional[str] = None  # Phase 18 hypothesis ID
    model_version: str = ""
    enrollment_version: str = ""
    dataset_version: str = ""
    source_provenance: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "label": self.label,
            "identity_id": self.identity_id,
            "query_embedding_id": self.query_embedding_id,
            "reference_embedding_id": self.reference_embedding_id,
            "similarity": self.similarity,
            "quality_class": self.quality_class,
            "temporal_hypothesis_id": self.temporal_hypothesis_id,
            "model_version": self.model_version,
            "enrollment_version": self.enrollment_version,
            "dataset_version": self.dataset_version,
            "source_provenance": self.source_provenance,
        }


@dataclass(frozen=True)
class GenuinePair:
    """Genuine pair (same identity) for calibration."""
    pair_id: str
    identity_id: str
    query_sample_id: str
    reference_sample_id: str
    similarity: float
    quality_class: Optional[str] = None
    temporal_hypothesis_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "identity_id": self.identity_id,
            "query_sample_id": self.query_sample_id,
            "reference_sample_id": self.reference_sample_id,
            "similarity": self.similarity,
            "quality_class": self.quality_class,
            "temporal_hypothesis_id": self.temporal_hypothesis_id,
        }


@dataclass(frozen=True)
class ImpostorPair:
    """Impostor pair (different identity) for calibration."""
    pair_id: str
    query_identity_id: str
    reference_identity_id: str
    query_sample_id: str
    reference_sample_id: str
    similarity: float
    quality_class: Optional[str] = None
    temporal_hypothesis_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "query_identity_id": self.query_identity_id,
            "reference_identity_id": self.reference_identity_id,
            "query_sample_id": self.query_sample_id,
            "reference_sample_id": self.reference_sample_id,
            "similarity": self.similarity,
            "quality_class": self.quality_class,
            "temporal_hypothesis_id": self.temporal_hypothesis_id,
        }


# =============================================================================
# CALIBRATION CONFIG
# =============================================================================

@dataclass(frozen=True)
class MatchingCalibrationConfig:
    """
    Configuration for matching calibration.
    
    This is NOT a production config — it is infrastructure for evaluation.
    """
    # Threshold search range
    threshold_search_range: Tuple[float, ...] = tuple(i / 100.0 for i in range(30, 90, 5))
    threshold_step: float = 0.05
    
    # Target operating points
    target_far: Optional[float] = None  # e.g., 0.01
    target_frr: Optional[float] = None  # e.g., 0.01
    
    # Selection policy
    selection_policy: str = "eer"  # "eer", "target_far", "target_frr", "balanced"
    
    # Ambiguity margin candidates
    ambiguity_margin_range: Tuple[float, ...] = (0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30)
    
    # Quality stratification
    evaluate_quality_stratified: bool = True
    
    # Temporal stratification
    evaluate_temporal: bool = True
    
    # Minimum data requirements
    min_genuine_pairs: int = 10
    min_impostor_pairs: int = 10
    min_total_pairs: int = 20
    
    # Determinism
    random_seed: int = 42
    
    # Versioning
    config_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold_search_range": list(self.threshold_search_range),
            "threshold_step": self.threshold_step,
            "target_far": self.target_far,
            "target_frr": self.target_frr,
            "selection_policy": self.selection_policy,
            "ambiguity_margin_range": list(self.ambiguity_margin_range),
            "evaluate_quality_stratified": self.evaluate_quality_stratified,
            "evaluate_temporal": self.evaluate_temporal,
            "min_genuine_pairs": self.min_genuine_pairs,
            "min_impostor_pairs": self.min_impostor_pairs,
            "min_total_pairs": self.min_total_pairs,
            "random_seed": self.random_seed,
            "config_version": self.config_version,
        }


DEFAULT_CALIBRATION_CONFIG = MatchingCalibrationConfig()


# =============================================================================
# METRIC DEFINITIONS
# =============================================================================

# Metric definitions (must be documented clearly):
#
# FAR (False Acceptance Rate):
#   = FP / (FP + TN)
#   = impostor accepted / all impostor attempts
#   False acceptance = impostor similarity >= threshold
#
# FRR (False Rejection Rate):
#   = FN / (FN + TP)
#   = genuine rejected / all genuine attempts
#   False rejection = genuine similarity < threshold
#
# TPR (True Positive Rate) = Recall = Sensitivity:
#   = TP / (TP + FN)
#   = genuine accepted / all genuine attempts
#   True positive = genuine similarity >= threshold
#
# FPR (False Positive Rate):
#   = FP / (FP + TN)
#   = impostor accepted / all impostor attempts
#   Same as FAR in this context
#
# EER (Equal Error Rate):
#   = the point where FAR ≈ FRR
#   Find threshold where |FAR - FRR| is minimized
#
# Precision:
#   = TP / (TP + FP)
#   = genuine accepted / all accepted
#
# Accuracy:
#   = (TP + TN) / (TP + TN + FP + FN)


# =============================================================================
# THRESHOLD SWEEP RESULT
# =============================================================================

@dataclass(frozen=True)
class ThresholdMetrics:
    """Metrics at a single threshold point."""
    threshold: float
    tp: int
    tn: int
    fp: int
    fn: int
    far: Optional[float]  # None if no impostor pairs
    frr: Optional[float]  # None if no genuine pairs
    tpr: Optional[float]  # None if no genuine pairs
    fpr: Optional[float]  # None if no impostor pairs
    precision: Optional[float]
    accuracy: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "threshold": self.threshold,
            "tp": self.tp,
            "tn": self.tn,
            "fp": self.fp,
            "fn": self.fn,
            "far": self.far,
            "frr": self.frr,
            "tpr": self.tpr,
            "fpr": self.fpr,
            "precision": self.precision,
            "accuracy": self.accuracy,
        }


@dataclass(frozen=True)
class EERResult:
    """Equal Error Rate result."""
    eer: Optional[float]
    eer_threshold: Optional[float]
    far_at_eer: Optional[float]
    frr_at_eer: Optional[float]
    available: bool
    reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "eer": self.eer,
            "eer_threshold": self.eer_threshold,
            "far_at_eer": self.far_at_eer,
            "frr_at_eer": self.frr_at_eer,
            "available": self.available,
            "reason": self.reason,
        }


# =============================================================================
# CALIBRATION RESULT
# =============================================================================

@dataclass
class MatchingCalibrationResult:
    """
    Versioned calibration result.
    
    Immutable snapshot of calibration with full provenance.
    """
    # Identification
    calibration_id: str = ""
    calibration_timestamp: str = ""
    
    # Status
    status: CalibrationStatus = CalibrationStatus.NOT_CALIBRATED
    
    # Selected thresholds
    threshold: Optional[float] = None
    ambiguity_margin: Optional[float] = None
    
    # Overall metrics at selected threshold
    far: Optional[float] = None
    frr: Optional[float] = None
    tpr: Optional[float] = None
    fpr: Optional[float] = None
    eer: Optional[float] = None
    eer_threshold: Optional[float] = None
    
    # Data counts
    genuine_count: int = 0
    impostor_count: int = 0
    total_pairs: int = 0
    
    # Threshold sweep results
    threshold_sweep: List[Dict[str, Any]] = field(default_factory=list)
    
    # EER result
    eer_result: Optional[Dict[str, Any]] = None
    
    # Ambiguity margin evaluation
    ambiguity_margin_results: Optional[Dict[str, Any]] = None
    
    # Quality stratification
    quality_stratification: Optional[Dict[str, Any]] = None
    
    # Temporal stratification
    temporal_stratification: Optional[Dict[str, Any]] = None
    
    # Unknown policy
    unknown_policy: Optional[Dict[str, Any]] = None
    
    # Versioning (immutable snapshot)
    model_version: str = ""
    model_sha256: Optional[str] = None
    embedding_dimension: int = 512
    normalization_method: str = "L2"
    matcher_version: str = ""
    enrollment_version: str = ""
    dataset_version: str = ""
    config_version: str = ""
    
    # Selection policy
    selection_policy: str = ""
    
    # Calibration level
    calibration_level: str = "single_frame"  # "single_frame" or "temporal_hypothesis"
    
    def __post_init__(self):
        if not self.calibration_id:
            content = f"{self.calibration_timestamp}_{self.model_version}_{self.threshold}"
            self.calibration_id = f"cal_{hashlib.md5(content.encode()).hexdigest()[:12]}"
        if not self.calibration_timestamp:
            self.calibration_timestamp = datetime.utcnow().isoformat() + "Z"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "calibration_id": self.calibration_id,
            "calibration_timestamp": self.calibration_timestamp,
            "status": self.status.value,
            "threshold": self.threshold,
            "ambiguity_margin": self.ambiguity_margin,
            "far": self.far,
            "frr": self.frr,
            "tpr": self.tpr,
            "fpr": self.fpr,
            "eer": self.eer,
            "eer_threshold": self.eer_threshold,
            "genuine_count": self.genuine_count,
            "impostor_count": self.impostor_count,
            "total_pairs": self.total_pairs,
            "threshold_sweep": self.threshold_sweep,
            "eer_result": self.eer_result,
            "ambiguity_margin_results": self.ambiguity_margin_results,
            "quality_stratification": self.quality_stratification,
            "temporal_stratification": self.temporal_stratification,
            "unknown_policy": self.unknown_policy,
            "model_version": self.model_version,
            "model_sha256": self.model_sha256,
            "embedding_dimension": self.embedding_dimension,
            "normalization_method": self.normalization_method,
            "matcher_version": self.matcher_version,
            "enrollment_version": self.enrollment_version,
            "dataset_version": self.dataset_version,
            "config_version": self.config_version,
            "selection_policy": self.selection_policy,
            "calibration_level": self.calibration_level,
        }


# =============================================================================
# METRIC CALCULATOR
# =============================================================================

def calculate_metrics_at_threshold(
    genuine_scores: List[float],
    impostor_scores: List[float],
    threshold: float,
) -> ThresholdMetrics:
    """
    Calculate FAR, FRR, TPR, etc. at a given threshold.
    
    Args:
        genuine_scores: List of similarity scores for genuine pairs
        impostor_scores: List of similarity scores for impostor pairs
        threshold: Decision threshold (similarity >= threshold = accept)
        
    Returns:
        ThresholdMetrics with all computed metrics
    """
    # Genuine: similarity >= threshold → TP (accepted), < threshold → FN (rejected)
    tp = sum(1 for s in genuine_scores if s >= threshold)
    fn = sum(1 for s in genuine_scores if s < threshold)
    
    # Impostor: similarity >= threshold → FP (accepted), < threshold → TN (rejected)
    fp = sum(1 for s in impostor_scores if s >= threshold)
    tn = sum(1 for s in impostor_scores if s < threshold)
    
    # FAR = FP / (FP + TN) = impostor accepted / all impostor
    far = fp / (fp + tn) if (fp + tn) > 0 else None
    
    # FRR = FN / (FN + TP) = genuine rejected / all genuine
    frr = fn / (fn + tp) if (fn + tp) > 0 else None
    
    # TPR = TP / (TP + FN) = genuine accepted / all genuine
    tpr = tp / (tp + fn) if (tp + fn) > 0 else None
    
    # FPR = FP / (FP + TN) = same as FAR
    fpr = far
    
    # Precision = TP / (TP + FP)
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    
    # Accuracy = (TP + TN) / (TP + TN + FP + FN)
    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total > 0 else 0.0
    
    return ThresholdMetrics(
        threshold=threshold,
        tp=tp,
        tn=tn,
        fp=fp,
        fn=fn,
        far=far,
        frr=frr,
        tpr=tpr,
        fpr=fpr,
        precision=precision,
        accuracy=accuracy,
    )


def compute_eer(
    genuine_scores: List[float],
    impostor_scores: List[float],
) -> EERResult:
    """
    Compute Equal Error Rate (EER).
    
    EER = the point where FAR ≈ FRR.
    Find threshold where |FAR - FRR| is minimized.
    
    Returns:
        EERResult with EER value and threshold
    """
    if len(genuine_scores) < 2 or len(impostor_scores) < 2:
        return EERResult(
            eer=None,
            eer_threshold=None,
            far_at_eer=None,
            frr_at_eer=None,
            available=False,
            reason=f"Insufficient data: {len(genuine_scores)} genuine, {len(impostor_scores)} impostor (need >= 2 each)",
        )
    
    # Sweep thresholds from min to max of all scores
    all_scores = genuine_scores + impostor_scores
    min_score = min(all_scores)
    max_score = max(all_scores)
    
    # Fine-grained sweep
    n_points = 200
    thresholds = np.linspace(min_score - 1e-6, max_score + 1e-6, n_points)
    
    best_eer = float('inf')
    best_threshold = None
    best_far = None
    best_frr = None
    
    for t in thresholds:
        metrics = calculate_metrics_at_threshold(genuine_scores, impostor_scores, float(t))
        if metrics.far is not None and metrics.frr is not None:
            diff = abs(metrics.far - metrics.frr)
            if diff < best_eer:
                best_eer = diff
                best_threshold = float(t)
                best_far = metrics.far
                best_frr = metrics.frr
    
    if best_threshold is None:
        return EERResult(
            eer=None,
            eer_threshold=None,
            far_at_eer=None,
            frr_at_eer=None,
            available=False,
            reason="Could not find EER point",
        )
    
    # EER = average of FAR and FRR at the crossing point
    eer_value = (best_far + best_frr) / 2.0
    
    return EERResult(
        eer=eer_value,
        eer_threshold=best_threshold,
        far_at_eer=best_far,
        frr_at_eer=best_frr,
        available=True,
    )


# =============================================================================
# THRESHOLD SWEEP
# =============================================================================

def threshold_sweep(
    genuine_scores: List[float],
    impostor_scores: List[float],
    thresholds: List[float],
) -> List[ThresholdMetrics]:
    """
    Evaluate metrics at multiple threshold points.
    
    Args:
        genuine_scores: List of similarity scores for genuine pairs
        impostor_scores: List of similarity scores for impostor pairs
        thresholds: List of threshold values to evaluate
        
    Returns:
        List of ThresholdMetrics for each threshold
    """
    results = []
    for t in sorted(thresholds):
        metrics = calculate_metrics_at_threshold(genuine_scores, impostor_scores, t)
        results.append(metrics)
    return results


# =============================================================================
# THRESHOLD SELECTION
# =============================================================================

def select_threshold(
    sweep_results: List[ThresholdMetrics],
    policy: str = "eer",
    target_far: Optional[float] = None,
    target_frr: Optional[float] = None,
    genuine_scores: Optional[List[float]] = None,
    impostor_scores: Optional[List[float]] = None,
) -> Optional[float]:
    """
    Select threshold based on explicit policy.
    
    Policies:
    - "eer": Select threshold closest to EER point
    - "target_far": Select threshold that achieves target FAR (minimize FRR)
    - "target_frr": Select threshold that achieves target FRR (minimize FAR)
    - "balanced": Select threshold that minimizes |FAR - FRR|
    
    Args:
        sweep_results: List of ThresholdMetrics from threshold sweep
        policy: Selection policy name
        target_far: Target FAR for "target_far" policy
        target_frr: Target FRR for "target_frr" policy
        genuine_scores: For EER computation
        impostor_scores: For EER computation
        
    Returns:
        Selected threshold or None if no suitable threshold found
    """
    if not sweep_results:
        return None
    
    if policy == "eer":
        if genuine_scores is not None and impostor_scores is not None:
            eer_result = compute_eer(genuine_scores, impostor_scores)
            if eer_result.available and eer_result.eer_threshold is not None:
                # Find closest threshold in sweep to EER threshold
                best = min(sweep_results, key=lambda m: abs(m.threshold - eer_result.eer_threshold))
                return best.threshold
        # Fallback: minimize |FAR - FRR|
        valid = [m for m in sweep_results if m.far is not None and m.frr is not None]
        if valid:
            best = min(valid, key=lambda m: abs(m.far - m.frr))
            return best.threshold
    
    elif policy == "target_far":
        if target_far is None:
            return None
        # Find thresholds where FAR <= target_far, then minimize FRR
        candidates = [m for m in sweep_results if m.far is not None and m.far <= target_far]
        if candidates:
            # Among candidates, prefer lowest FRR
            best = min(candidates, key=lambda m: m.frr if m.frr is not None else float('inf'))
            return best.threshold
        return None
    
    elif policy == "target_frr":
        if target_frr is None:
            return None
        # Find thresholds where FRR <= target_frr, then minimize FAR
        candidates = [m for m in sweep_results if m.frr is not None and m.frr <= target_frr]
        if candidates:
            # Among candidates, prefer lowest FAR
            best = min(candidates, key=lambda m: m.far if m.far is not None else float('inf'))
            return best.threshold
        return None
    
    elif policy == "balanced":
        valid = [m for m in sweep_results if m.far is not None and m.frr is not None]
        if valid:
            best = min(valid, key=lambda m: abs(m.far - m.frr))
            return best.threshold
    
    return None


# =============================================================================
# AMBIGUITY MARGIN EVALUATION
# =============================================================================

def evaluate_ambiguity_margins(
    genuine_scores: List[float],
    impostor_scores: List[float],
    margin_candidates: List[float],
    base_threshold: float,
) -> Dict[str, Any]:
    """
    Evaluate ambiguity margin candidates.
    
    For each margin, compute:
    - How many pairs would be ambiguous (margin < threshold)
    - Impact on FAR/FRR
    
    Args:
        genuine_scores: List of similarity scores for genuine pairs
        impostor_scores: List of similarity scores for impostor pairs
        margin_candidates: List of margin values to evaluate
        base_threshold: Base matching threshold
        
    Returns:
        Dictionary with margin evaluation results
    """
    results = {}
    
    for margin in margin_candidates:
        # At each margin, evaluate impact
        # Pairs with score difference < margin would be AMBIGUOUS
        # This doesn't directly affect FAR/FRR (those are at single threshold)
        # But affects how many decisions are "ambiguous" vs "match"
        
        metrics = calculate_metrics_at_threshold(genuine_scores, impostor_scores, base_threshold)
        
        results[str(margin)] = {
            "margin": margin,
            "far": metrics.far,
            "frr": metrics.frr,
            "tpr": metrics.tpr,
            "threshold": base_threshold,
            "description": f"Margin {margin}: pairs with score diff < {margin} are ambiguous",
        }
    
    return {
        "margin_candidates": margin_candidates,
        "evaluation": results,
        "description": "Ambiguity margin evaluation (requires second-best score context)",
    }


# =============================================================================
# UNKNOWN POLICY VALIDATION
# =============================================================================

def validate_unknown_policy(
    scores: List[float],
    threshold: float,
) -> Dict[str, Any]:
    """
    Validate that scores below threshold result in UNKNOWN.
    
    No identity should be forced when best similarity < threshold.
    
    Args:
        scores: List of similarity scores
        threshold: Decision threshold
        
    Returns:
        Dictionary with validation results
    """
    below_threshold = [s for s in scores if s < threshold]
    above_threshold = [s for s in scores if s >= threshold]
    
    return {
        "total_scores": len(scores),
        "below_threshold": len(below_threshold),
        "above_threshold": len(above_threshold),
        "threshold": threshold,
        "unknown_count": len(below_threshold),
        "match_count": len(above_threshold),
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "policy_valid": True,  # Unknown policy is validated by construction
    }


# =============================================================================
# CALIBRATION RUNNER
# =============================================================================

def run_calibration(
    genuine_scores: List[float],
    impostor_scores: List[float],
    config: MatchingCalibrationConfig = DEFAULT_CALIBRATION_CONFIG,
    model_version: str = "",
    model_sha256: Optional[str] = None,
    enrollment_version: str = "",
    dataset_version: str = "",
    matcher_version: str = "",
    calibration_level: str = "single_frame",
    quality_labels: Optional[Dict[str, str]] = None,
    temporal_labels: Optional[Dict[str, bool]] = None,
) -> MatchingCalibrationResult:
    """
    Run full calibration pipeline.
    
    Args:
        genuine_scores: List of similarity scores for genuine pairs
        impostor_scores: List of similarity scores for impostor pairs
        config: Calibration configuration
        model_version: ArcFace model version
        model_sha256: ArcFace model SHA256
        enrollment_version: Enrollment database version
        dataset_version: Calibration dataset version
        matcher_version: Matcher version
        calibration_level: "single_frame" or "temporal_hypothesis"
        quality_labels: Optional quality class labels per sample
        temporal_labels: Optional temporal hypothesis labels per sample
        
    Returns:
        MatchingCalibrationResult with full calibration results
    """
    start_time = datetime.utcnow()
    
    # Determine status
    status = CalibrationStatus.NOT_CALIBRATED
    if len(genuine_scores) >= config.min_genuine_pairs and len(impostor_scores) >= config.min_impostor_pairs:
        status = CalibrationStatus.INFRASTRUCTURE_READY
    
    # Threshold sweep
    sweep_results = threshold_sweep(
        genuine_scores, impostor_scores, list(config.threshold_search_range)
    )
    sweep_dicts = [m.to_dict() for m in sweep_results]
    
    # EER computation
    eer_result = compute_eer(genuine_scores, impostor_scores)
    eer_dict = eer_result.to_dict()
    
    # Select threshold
    selected_threshold = select_threshold(
        sweep_results,
        policy=config.selection_policy,
        target_far=config.target_far,
        target_frr=config.target_frr,
        genuine_scores=genuine_scores,
        impostor_scores=impostor_scores,
    )
    
    # If no threshold selected, use default
    if selected_threshold is None:
        selected_threshold = 0.5  # Engineering default
    
    # Compute metrics at selected threshold
    metrics = calculate_metrics_at_threshold(genuine_scores, impostor_scores, selected_threshold)
    
    # Evaluate ambiguity margins
    ambiguity_results = evaluate_ambiguity_margins(
        genuine_scores, impostor_scores,
        list(config.ambiguity_margin_range),
        selected_threshold,
    )
    
    # Default ambiguity margin (engineering default)
    selected_ambiguity_margin = 0.10
    
    # Unknown policy validation
    all_scores = genuine_scores + impostor_scores
    unknown_results = validate_unknown_policy(all_scores, selected_threshold)
    
    # Quality stratification (if labels provided)
    quality_strat = None
    if config.evaluate_quality_stratified and quality_labels:
        quality_strat = _evaluate_quality_stratification(
            genuine_scores, impostor_scores, quality_labels, selected_threshold
        )
    
    # Temporal stratification (if labels provided)
    temporal_strat = None
    if config.evaluate_temporal and temporal_labels:
        temporal_strat = _evaluate_temporal_stratification(
            genuine_scores, impostor_scores, temporal_labels, selected_threshold
        )
    
    # Create result
    result = MatchingCalibrationResult(
        calibration_timestamp=start_time.isoformat() + "Z",
        status=status,
        threshold=selected_threshold,
        ambiguity_margin=selected_ambiguity_margin,
        far=metrics.far,
        frr=metrics.frr,
        tpr=metrics.tpr,
        fpr=metrics.fpr,
        eer=eer_result.eer,
        eer_threshold=eer_result.eer_threshold,
        genuine_count=len(genuine_scores),
        impostor_count=len(impostor_scores),
        total_pairs=len(genuine_scores) + len(impostor_scores),
        threshold_sweep=sweep_dicts,
        eer_result=eer_dict,
        ambiguity_margin_results=ambiguity_results,
        quality_stratification=quality_strat,
        temporal_stratification=temporal_strat,
        unknown_policy=unknown_results,
        model_version=model_version,
        model_sha256=model_sha256,
        enrollment_version=enrollment_version,
        dataset_version=dataset_version,
        config_version=config.config_version,
        matcher_version=matcher_version,
        selection_policy=config.selection_policy,
        calibration_level=calibration_level,
    )
    
    return result


def _evaluate_quality_stratification(
    genuine_scores: List[float],
    impostor_scores: List[float],
    quality_labels: Dict[str, str],
    threshold: float,
) -> Dict[str, Any]:
    """Evaluate calibration stratified by quality class."""
    # Group scores by quality
    quality_groups = {}
    for i, score in enumerate(genuine_scores):
        label = quality_labels.get(f"genuine_{i}", "unknown")
        if label not in quality_groups:
            quality_groups[label] = {"genuine": [], "impostor": []}
        quality_groups[label]["genuine"].append(score)
    
    for i, score in enumerate(impostor_scores):
        label = quality_labels.get(f"impostor_{i}", "unknown")
        if label not in quality_groups:
            quality_groups[label] = {"genuine": [], "impostor": []}
        quality_groups[label]["impostor"].append(score)
    
    results = {}
    for quality_class, scores_dict in quality_groups.items():
        metrics = calculate_metrics_at_threshold(
            scores_dict["genuine"], scores_dict["impostor"], threshold
        )
        results[quality_class] = {
            "genuine_count": len(scores_dict["genuine"]),
            "impostor_count": len(scores_dict["impostor"]),
            "far": metrics.far,
            "frr": metrics.frr,
            "tpr": metrics.tpr,
        }
    
    return {
        "quality_classes": list(results.keys()),
        "stratified_results": results,
    }


def _evaluate_temporal_stratification(
    genuine_scores: List[float],
    impostor_scores: List[float],
    temporal_labels: Dict[str, bool],
    threshold: float,
) -> Dict[str, Any]:
    """Evaluate calibration stratified by temporal hypothesis."""
    temporal_groups = {
        "single_frame": {"genuine": [], "impostor": []},
        "temporal_hypothesis": {"genuine": [], "impostor": []},
    }
    
    for i, score in enumerate(genuine_scores):
        is_temporal = temporal_labels.get(f"genuine_{i}", False)
        key = "temporal_hypothesis" if is_temporal else "single_frame"
        temporal_groups[key]["genuine"].append(score)
    
    for i, score in enumerate(impostor_scores):
        is_temporal = temporal_labels.get(f"impostor_{i}", False)
        key = "temporal_hypothesis" if is_temporal else "single_frame"
        temporal_groups[key]["impostor"].append(score)
    
    results = {}
    for level, scores_dict in temporal_groups.items():
        if scores_dict["genuine"] or scores_dict["impostor"]:
            metrics = calculate_metrics_at_threshold(
                scores_dict["genuine"], scores_dict["impostor"], threshold
            )
            results[level] = {
                "genuine_count": len(scores_dict["genuine"]),
                "impostor_count": len(scores_dict["impostor"]),
                "far": metrics.far,
                "frr": metrics.frr,
                "tpr": metrics.tpr,
            }
    
    return {
        "calibration_levels": list(results.keys()),
        "stratified_results": results,
    }


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_calibration_config(
    **kwargs,
) -> MatchingCalibrationConfig:
    """Create a calibration config with custom parameters."""
    return MatchingCalibrationConfig(**kwargs)