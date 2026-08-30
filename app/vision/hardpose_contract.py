"""
Phase 15 — 1K3D68 Hard-Pose Assisted ArcFace Contract.

Defines the model-independent contract for hard-pose face alignment using 1K3D68.
This module does NOT perform inference.
This module does NOT access cameras.
This module does NOT implement identity matching.
1K3D68 = geometric pose/alignment assistance ONLY.
ArcFace = identity embedding.
Phase 14 = identity matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
import numpy as np


class PoseState(Enum):
    """Face pose classification state."""
    NORMAL = "NORMAL"           # Acceptable for normal alignment
    HARD_POSE = "HARD_POSE"     # Requires 1K3D68 geometric correction
    INVALID = "INVALID"         # Cannot be processed (unusable pose/landmarks)


@dataclass(frozen=True)
class PoseThresholds:
    """
    Configurable thresholds for pose classification.
    
    These are engineering parameters, not production accuracy claims.
    All angles in degrees.
    """
    # Yaw thresholds (left/right rotation)
    yaw_normal_max: float = 25.0      # |yaw| <= 25° -> NORMAL
    yaw_hard_max: float = 60.0        # 25° < |yaw| <= 60° -> HARD_POSE
    # |yaw| > 60° -> INVALID
    
    # Pitch thresholds (up/down rotation)
    pitch_normal_max: float = 20.0    # |pitch| <= 20° -> NORMAL
    pitch_hard_max: float = 45.0      # 20° < |pitch| <= 45° -> HARD_POSE
    # |pitch| > 45° -> INVALID
    
    # Roll thresholds (in-plane rotation)
    roll_normal_max: float = 30.0     # |roll| <= 30° -> NORMAL
    roll_hard_max: float = 60.0       # 30° < |roll| <= 60° -> HARD_POSE
    # |roll| > 60° -> INVALID
    
    # Landmark quality thresholds
    min_valid_landmarks: int = 60     # Minimum valid landmarks for HARD_POSE
    max_landmark_distance: float = 192.0  # Max coordinate value in model input space
    
    def __post_init__(self):
        """Validate thresholds after initialization."""
        if not (0 <= self.yaw_normal_max <= self.yaw_hard_max <= 90):
            raise ValueError("Invalid yaw thresholds: 0 <= normal_max <= hard_max <= 90")
        if not (0 <= self.pitch_normal_max <= self.pitch_hard_max <= 90):
            raise ValueError("Invalid pitch thresholds: 0 <= normal_max <= hard_max <= 90")
        if not (0 <= self.roll_normal_max <= self.roll_hard_max <= 90):
            raise ValueError("Invalid roll thresholds: 0 <= normal_max <= hard_max <= 90")
        if not (0 < self.min_valid_landmarks <= 68):
            raise ValueError("min_valid_landmarks must be in (0, 68]")
        if self.max_landmark_distance <= 0:
            raise ValueError("max_landmark_distance must be positive")


@dataclass(frozen=True)
class PoseEstimation:
    """
    3D pose estimation from 1K3D68 landmarks.
    
    Coordinate space: MODEL_INPUT_RELATIVE (0-192)
    """
    # Euler angles in degrees
    yaw: float
    pitch: float
    roll: float
    
    # Landmark validity
    valid_landmark_count: int
    total_landmarks: int = 68
    
    # Coordinate space of input landmarks
    coordinate_space: str = "model_input_relative"
    
    # Pose state classification
    state: PoseState = PoseState.NORMAL
    
    # Provenance
    model_id: str = "landmark_1k3d68"
    model_sha256: str = ""
    
    def __post_init__(self):
        """Validate pose estimation after initialization."""
        if not isinstance(self.state, PoseState):
            raise ValueError(f"state must be PoseState enum, got {type(self.state)}")
        if not (0 <= self.valid_landmark_count <= self.total_landmarks):
            raise ValueError(f"valid_landmark_count must be in [0, {self.total_landmarks}]")
        if not np.isfinite(self.yaw) or not np.isfinite(self.pitch) or not np.isfinite(self.roll):
            raise ValueError("Pose angles must be finite")


@dataclass(frozen=True)
class AlignmentTransform:
    """
    Geometric alignment transform from 1K3D68 landmarks to 112x112 ArcFace input.
    
    This is the explicit bridge: 1K3D68 landmarks -> 2D coordinates -> transform -> corrected image.
    """
    # Source landmarks used for alignment (indices into 68 landmarks)
    source_landmark_indices: List[int]
    
    # Source landmark coordinates in model input space (0-192)
    source_landmarks: List[Tuple[float, float]]
    
    # Target landmark coordinates in 112x112 output space
    target_landmarks: List[Tuple[float, float]]
    
    # Transform type
    transform_type: str = "similarity"  # "similarity" or "affine"
    
    # Transform matrix (2x3 for affine, 2x3 for similarity)
    transform_matrix: List[List[float]] = field(default_factory=list)
    
    # Interpolation method
    interpolation: str = "INTER_LINEAR"
    
    # Output size
    output_size: Tuple[int, int] = (112, 112)
    
    # Provenance
    model_id: str = "landmark_1k3d68"
    model_sha256: str = ""
    
    def __post_init__(self):
        """Validate alignment transform after initialization."""
        if len(self.source_landmark_indices) != len(self.source_landmarks):
            raise ValueError("source_landmark_indices and source_landmarks must have same length")
        if len(self.source_landmarks) != len(self.target_landmarks):
            raise ValueError("source_landmarks and target_landmarks must have same length")
        if len(self.source_landmarks) < 2:
            raise ValueError("At least 2 landmarks required for alignment")
        if self.transform_type not in ("similarity", "affine"):
            raise ValueError(f"transform_type must be 'similarity' or 'affine', got {self.transform_type}")
        if self.output_size != (112, 112):
            raise ValueError(f"output_size must be (112, 112), got {self.output_size}")


@dataclass(frozen=True)
class HardPoseAlignmentResult:
    """
    Result of hard-pose alignment process.
    
    Contains the aligned face image ready for ArcFace inference.
    """
    # Aligned face image (BGR, 112x112, uint8) - ready for ArcFace preprocessing
    aligned_face_bgr: np.ndarray
    
    # Pose estimation that triggered hard-pose path
    pose_estimation: PoseEstimation
    
    # Alignment transform applied
    alignment_transform: AlignmentTransform
    
    # Whether 1K3D68 was used (True for HARD_POSE, False for NORMAL)
    used_1k3d68: bool
    
    # Processing time
    total_time_ms: float
    landmark_time_ms: float = 0.0
    alignment_time_ms: float = 0.0
    
    # Provenance
    source_crop_id: str = ""
    source_frame_index: int = 0
    source_id: str = ""
    
    def __post_init__(self):
        """Validate alignment result after initialization."""
        if self.aligned_face_bgr.shape != (112, 112, 3):
            raise ValueError(f"aligned_face_bgr must be (112, 112, 3), got {self.aligned_face_bgr.shape}")
        if self.aligned_face_bgr.dtype != np.uint8:
            raise ValueError(f"aligned_face_bgr must be uint8, got {self.aligned_face_bgr.dtype}")
        if not isinstance(self.pose_estimation, PoseEstimation):
            raise ValueError("pose_estimation must be PoseEstimation")
        if not isinstance(self.alignment_transform, AlignmentTransform):
            raise ValueError("alignment_transform must be AlignmentTransform")
        if not np.isfinite(self.total_time_ms) or self.total_time_ms < 0:
            raise ValueError("total_time_ms must be non-negative finite")


@dataclass(frozen=True)
class HardPoseConfig:
    """
    Configuration for hard-pose alignment pipeline.
    """
    # Pose classification thresholds
    pose_thresholds: PoseThresholds = field(default_factory=PoseThresholds)
    
    # 1K3D68 model settings
    landmark_model_id: str = "landmark_1k3d68"
    landmark_providers: Tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider")
    min_crop_dimension: int = 32
    
    # Alignment settings
    # These are the 5 landmark indices from 68-point 1K3D68 that correspond to the 5 ArcFace target points
    # 36=left eye outer, 39=left eye inner -> left eye center
    # 42=right eye inner, 45=right eye outer -> right eye center
    # 30=nose tip
    # 48=left mouth corner
    # 54=right mouth corner
    alignment_landmark_indices: List[int] = field(default_factory=lambda: [
        36, 39, 42, 45, 30  # 5 indices: left eye corners, right eye corners, nose tip
    ])
    
    # Target landmarks for 112x112 (standard ArcFace alignment points)
    # These are the 5-point landmarks used by ArcFace training
    target_landmarks_112: List[Tuple[float, float]] = field(default_factory=lambda: [
        (38.2946, 51.6963),   # Left eye center
        (73.5318, 51.5014),   # Right eye center
        (56.0252, 71.7366),   # Nose tip
        (41.5493, 92.3655),   # Left mouth corner
        (70.7299, 92.2041),   # Right mouth corner
    ])
    
    # ArcFace inference settings (reuse Phase 12)
    arcface_providers: Tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider")
    
    # Validation
    validate_landmarks: bool = True
    validate_aligned_face: bool = True
    
    def __post_init__(self):
        """Validate config after initialization."""
        if not isinstance(self.pose_thresholds, PoseThresholds):
            raise ValueError("pose_thresholds must be PoseThresholds")
        # alignment_landmark_indices must match target_landmarks_112 length
        # Each alignment index corresponds to one target landmark point
        if len(self.alignment_landmark_indices) != len(self.target_landmarks_112):
            raise ValueError("alignment_landmark_indices must match target_landmarks_112 length")
        if len(self.target_landmarks_112) != 5:
            raise ValueError("target_landmarks_112 must have exactly 5 points for ArcFace alignment")
        if any(idx < 0 or idx >= 68 for idx in self.alignment_landmark_indices):
            raise ValueError("alignment_landmark_indices must be in [0, 67]")


# Global default instances
DEFAULT_POSE_THRESHOLDS = PoseThresholds()
DEFAULT_HARDPOSE_CONFIG = HardPoseConfig()


def get_default_pose_thresholds() -> PoseThresholds:
    """Get default pose classification thresholds."""
    return DEFAULT_POSE_THRESHOLDS


def get_default_hardpose_config() -> HardPoseConfig:
    """Get default hard-pose alignment configuration."""
    return DEFAULT_HARDPOSE_CONFIG


def classify_pose(
    yaw: float,
    pitch: float,
    roll: float,
    valid_landmark_count: int,
    thresholds: Optional[PoseThresholds] = None,
) -> PoseState:
    """
    Classify face pose based on Euler angles and landmark quality.
    
    This is the deterministic pose decision function.
    
    Args:
        yaw: Yaw angle in degrees (positive = left turn)
        pitch: Pitch angle in degrees (positive = up)
        roll: Roll angle in degrees (positive = counter-clockwise)
        valid_landmark_count: Number of valid (finite, in-range) landmarks
        thresholds: Pose classification thresholds (default: DEFAULT_POSE_THRESHOLDS)
        
    Returns:
        PoseState: NORMAL, HARD_POSE, or INVALID
    """
    if thresholds is None:
        thresholds = DEFAULT_POSE_THRESHOLDS
    
    # Check landmark count first
    if valid_landmark_count < thresholds.min_valid_landmarks:
        return PoseState.INVALID
    
    # Check absolute angles
    abs_yaw = abs(yaw)
    abs_pitch = abs(pitch)
    abs_roll = abs(roll)
    
    # Check INVALID conditions (exceeds hard limits)
    if abs_yaw > thresholds.yaw_hard_max:
        return PoseState.INVALID
    if abs_pitch > thresholds.pitch_hard_max:
        return PoseState.INVALID
    if abs_roll > thresholds.roll_hard_max:
        return PoseState.INVALID
    
    # Check HARD_POSE conditions (exceeds normal limits but within hard limits)
    if abs_yaw > thresholds.yaw_normal_max:
        return PoseState.HARD_POSE
    if abs_pitch > thresholds.pitch_normal_max:
        return PoseState.HARD_POSE
    if abs_roll > thresholds.roll_normal_max:
        return PoseState.HARD_POSE
    
    # Otherwise NORMAL
    return PoseState.NORMAL


def validate_landmarks_for_pose(
    landmarks: List[Tuple[float, float, float]],
    coordinate_space: str = "model_input_relative",
    max_coordinate: float = 192.0,
) -> Tuple[int, List[bool]]:
    """
    Validate landmarks for pose estimation.
    
    Returns:
        (valid_count, validity_mask)
    """
    if len(landmarks) != 68:
        raise ValueError(f"Expected 68 landmarks, got {len(landmarks)}")
    
    validity_mask = []
    valid_count = 0
    
    for x, y, z in landmarks:
        is_valid = (
            np.isfinite(x) and np.isfinite(y) and np.isfinite(z) and
            0 <= x <= max_coordinate and
            0 <= y <= max_coordinate
        )
        validity_mask.append(is_valid)
        if is_valid:
            valid_count += 1
    
    return valid_count, validity_mask


# Standard 5-point landmark indices for ArcFace alignment (from 68-point 1K3D68)
# These correspond to: left eye, right eye, nose, left mouth, right mouth
ARC_FACE_5POINT_INDICES = [36, 39, 42, 45, 30, 48, 54]
# Note: 1K3D68 uses 68 points, we select 5 key points for similarity transform
# Standard indices: 36=left eye outer, 39=left eye inner, 42=right eye inner, 45=right eye outer
# 30=nose tip, 48=left mouth, 54=right mouth
# For similarity transform we need at least 2 points, typically use eye centers + nose + mouth
# We'll use the 5-point subset that matches ArcFace training

# Actually for similarity transform we need exactly 2-3 point pairs
# Let's use: left eye center, right eye center, nose tip, mouth center
# 1K3D68 indices: 
# Left eye: 36-41 (6 points), center ~ (36+39)/2
# Right eye: 42-47 (6 points), center ~ (42+45)/2
# Nose: 30 (tip)
# Mouth: 48 (left), 54 (right), center ~ (48+54)/2

# For 5-point alignment matching ArcFace training:
# We'll compute eye centers from the 68 points
def get_arcface_5point_indices() -> List[int]:
    """Get the 5 landmark indices used for ArcFace alignment from 68-point landmarks."""
    # These are the indices we'll use to compute the 5 alignment points
    # We return the raw indices; the alignment code computes centers
    return [36, 39, 42, 45, 30, 48, 54]


# Target 5-point landmarks for 112x112 ArcFace input (standard from ArcFace training)
ARC_FACE_TARGET_5POINTS = [
    (38.2946, 51.6963),   # Left eye center
    (73.5318, 51.5014),   # Right eye center
    (56.0252, 71.7366),   # Nose tip
    (41.5493, 92.3655),   # Left mouth corner
    (70.7299, 92.2041),   # Right mouth corner
]