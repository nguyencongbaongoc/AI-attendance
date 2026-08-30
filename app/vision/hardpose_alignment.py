"""
Phase 15 — 1K3D68 Hard-Pose Assisted ArcFace Alignment Implementation.

Implements the hard-pose alignment pipeline:
- 1K3D68 landmark inference (reuses Phase 7)
- Pose estimation from 3D landmarks
- Landmark/pose validation
- Geometric alignment correction (similarity transform)
- Normal vs Hard-Pose routing
- ArcFace compatibility (Phase 12 contract)
- Phase 14 matching compatibility

This module does NOT access cameras.
This module does NOT implement identity matching.
This module does NOT implement attendance.
"""

from __future__ import annotations

import time
import cv2
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from app.vision.landmarks import (
    LandmarkDetector,
    LandmarkResult,
    LandmarkCoordinateSpace,
    create_landmark_detector,
    LandmarkError,
)
from app.vision.hardpose_contract import (
    PoseState,
    PoseThresholds,
    PoseEstimation,
    AlignmentTransform,
    HardPoseAlignmentResult,
    HardPoseConfig,
    classify_pose,
    validate_landmarks_for_pose,
    get_default_hardpose_config,
    ARC_FACE_TARGET_5POINTS,
)
from app.vision.arcface_inference import (
    create_arcface_inference,
    ArcFaceInference,
    ArcFaceInferenceResult,
)
from app.vision.recognition_contract import (
    ArcFaceInputContract,
    get_arcface_input_contract,
)
from app.vision.crop import FaceCrop, validate_crop_for_landmark


@dataclass(frozen=True)
class NormalAlignmentResult:
    """Result of normal (non-hard-pose) alignment."""
    aligned_face_bgr: np.ndarray
    used_1k3d68: bool = False
    total_time_ms: float = 0.0
    source_crop_id: str = ""
    source_frame_index: int = 0
    source_id: str = ""
    
    def __post_init__(self):
        if self.aligned_face_bgr.shape != (112, 112, 3):
            raise ValueError(f"aligned_face_bgr must be (112, 112, 3), got {self.aligned_face_bgr.shape}")
        if self.aligned_face_bgr.dtype != np.uint8:
            raise ValueError(f"aligned_face_bgr must be uint8, got {self.aligned_face_bgr.dtype}")


@dataclass(frozen=True)
class HardPosePipelineResult:
    """
    Unified result from hard-pose pipeline.
    
    Either NormalAlignmentResult or HardPoseAlignmentResult.
    Both produce 112x112 BGR uint8 image ready for ArcFace.
    """
    # The aligned face (112x112 BGR uint8)
    aligned_face_bgr: np.ndarray
    
    # Whether 1K3D68 was used
    used_1k3d68: bool
    
    # Pose estimation (None for normal alignment)
    pose_estimation: Optional[PoseEstimation] = None
    
    # Alignment transform (None for normal alignment)
    alignment_transform: Optional[AlignmentTransform] = None
    
    # Processing times
    total_time_ms: float = 0.0
    landmark_time_ms: float = 0.0
    alignment_time_ms: float = 0.0
    arcface_time_ms: float = 0.0
    
    # Provenance
    source_crop_id: str = ""
    source_frame_index: int = 0
    source_id: str = ""
    
    # ArcFace inference result (if run)
    arcface_result: Optional[ArcFaceInferenceResult] = None
    
    def __post_init__(self):
        if self.aligned_face_bgr.shape != (112, 112, 3):
            raise ValueError(f"aligned_face_bgr must be (112, 112, 3), got {self.aligned_face_bgr.shape}")
        if self.aligned_face_bgr.dtype != np.uint8:
            raise ValueError(f"aligned_face_bgr must be uint8, got {self.aligned_face_bgr.dtype}")


class HardPoseAlignmentError(Exception):
    """Exception raised when hard-pose alignment fails."""
    
    def __init__(
        self,
        message: str,
        pose_state: Optional[PoseState] = None,
        crop_id: Optional[str] = None,
        frame_index: Optional[int] = None,
    ):
        super().__init__(message)
        self.pose_state = pose_state
        self.crop_id = crop_id
        self.frame_index = frame_index


def estimate_pose_from_landmarks(
    landmarks: List[Tuple[float, float, float]],
    coordinate_space: str = "model_input_relative",
) -> Tuple[float, float, float]:
    """
    Estimate 3D pose (yaw, pitch, roll) from 68 3D landmarks.
    
    Uses a simplified PnP approach with known 3D face model.
    For 1K3D68, the Z coordinates give depth information.
    
    Args:
        landmarks: 68 3D landmarks (x, y, z) in model input space (0-192)
        coordinate_space: Coordinate space of landmarks
        
    Returns:
        (yaw, pitch, roll) in degrees
    """
    if len(landmarks) != 68:
        raise ValueError(f"Expected 68 landmarks, got {len(landmarks)}")
    
    # Convert to numpy array
    pts_3d = np.array(landmarks, dtype=np.float32)  # (68, 3)
    
    # Use key landmarks for pose estimation
    # Nose tip (30), left eye corners (36, 39), right eye corners (42, 45), mouth corners (48, 54)
    # We'll use a simplified approach: compute pose from eye-nose-mouth geometry
    
    # Key points indices
    nose_tip_idx = 30
    left_eye_outer_idx = 36
    left_eye_inner_idx = 39
    right_eye_inner_idx = 42
    right_eye_outer_idx = 45
    left_mouth_idx = 48
    right_mouth_idx = 54
    
    # Get 2D coordinates (x, y)
    nose_tip = pts_3d[nose_tip_idx, :2]
    left_eye_outer = pts_3d[left_eye_outer_idx, :2]
    left_eye_inner = pts_3d[left_eye_inner_idx, :2]
    right_eye_inner = pts_3d[right_eye_inner_idx, :2]
    right_eye_outer = pts_3d[right_eye_outer_idx, :2]
    left_mouth = pts_3d[left_mouth_idx, :2]
    right_mouth = pts_3d[right_mouth_idx, :2]
    
    # Compute eye centers
    left_eye_center = (left_eye_outer + left_eye_inner) / 2
    right_eye_center = (right_eye_inner + right_eye_outer) / 2
    mouth_center = (left_mouth + right_mouth) / 2
    
    # Eye vector
    eye_vector = right_eye_center - left_eye_center
    eye_distance = np.linalg.norm(eye_vector)
    
    if eye_distance < 1e-6:
        return 0.0, 0.0, 0.0
    
    # Roll: angle of eye line
    roll = np.degrees(np.arctan2(eye_vector[1], eye_vector[0]))
    
    # Yaw: based on nose position relative to eye centers
    eye_center = (left_eye_center + right_eye_center) / 2
    nose_offset_x = nose_tip[0] - eye_center[0]
    # Normalize by eye distance
    yaw = np.degrees(np.arcsin(np.clip(nose_offset_x / (eye_distance * 0.5), -1.0, 1.0)))
    
    # Pitch: use the ratio of nose-eye distance to eye-mouth distance
    # In frontal face, nose is roughly 1/3 down from eyes to mouth
    eye_center = (left_eye_center + right_eye_center) / 2
    eye_to_nose_y = nose_tip[1] - eye_center[1]
    eye_to_mouth_y = mouth_center[1] - eye_center[1]
    if eye_to_mouth_y > 1e-6:
        nose_ratio = eye_to_nose_y / eye_to_mouth_y
        # Frontal: nose_ratio ~ 0.33 (nose 1/3 down from eyes to mouth)
        # Looking up: nose moves up, nose_ratio decreases
        # Looking down: nose moves down, nose_ratio increases
        # Map ratio to pitch: 0.33 -> 0°, 0.2 -> +20°, 0.5 -> -20°
        pitch = (0.33 - nose_ratio) * 60.0  # Rough scaling
    else:
        pitch = 0.0
    
    return float(yaw), float(pitch), float(roll)

def compute_similarity_transform(
    src_points: np.ndarray,  # (N, 2)
    dst_points: np.ndarray,  # (N, 2)
) -> np.ndarray:
    """
    Compute similarity transform (rotation + translation + uniform scale) from src to dst.
    
    Uses Umeyama's algorithm for least-squares similarity transform.
    The transform maps src to dst: dst = scale * R @ src + t
    
    Args:
        src_points: Source points (N, 2)
        dst_points: Destination points (N, 2)
        
    Returns:
        2x3 transformation matrix [scale*R | t]
    """
    if src_points.shape != dst_points.shape:
        raise ValueError("Source and destination points must have same shape")
    if src_points.shape[0] < 2:
        raise ValueError("At least 2 point pairs required")
    
    # Center the points
    src_mean = np.mean(src_points, axis=0)
    dst_mean = np.mean(dst_points, axis=0)
    
    src_centered = src_points - src_mean
    dst_centered = dst_points - dst_mean
    
    # Compute covariance matrix
    H = src_centered.T @ dst_centered
    
    # SVD
    U, S, Vt = np.linalg.svd(H)
    
    # Rotation matrix
    R = Vt.T @ U.T
    
    # Ensure proper rotation (no reflection)
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    
    # Scale (Umeyama's formula: sum of singular values / source variance)
    src_var = np.sum(src_centered ** 2)
    if src_var < 1e-10:
        scale = 1.0
    else:
        scale = np.sum(S) / src_var
    
    # Translation
    t = dst_mean - scale * (R @ src_mean)
    
    # Construct 2x3 matrix
    transform = np.zeros((2, 3), dtype=np.float32)
    transform[:2, :2] = scale * R
    transform[:2, 2] = t
    
    return transform


def compute_affine_transform(
    src_points: np.ndarray,  # (N, 2)
    dst_points: np.ndarray,  # (N, 2)
) -> np.ndarray:
    """
    Compute affine transform from src to dst (least squares).
    
    Args:
        src_points: Source points (N, 2), N >= 3
        dst_points: Destination points (N, 2)
        
    Returns:
        2x3 transformation matrix
    """
    if src_points.shape[0] < 3:
        raise ValueError("At least 3 point pairs required for affine transform")
    
    # Use OpenCV's estimateAffinePartial2D for robust estimation
    transform, _ = cv2.estimateAffinePartial2D(
        src_points.astype(np.float32),
        dst_points.astype(np.float32),
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
    )
    
    if transform is None:
        # Fallback to least squares
        # Solve: dst = src * A^T + t
        # [x' y'] = [x y 1] * [a b c; d e f]^T
        N = src_points.shape[0]
        A = np.hstack([src_points, np.ones((N, 1))])  # (N, 3)
        B = dst_points  # (N, 2)
        
        # Least squares: X = (A^T A)^-1 A^T B
        X = np.linalg.lstsq(A, B, rcond=None)[0]  # (3, 2)
        transform = X.T  # (2, 3)
    
    return transform.astype(np.float32)


def apply_alignment_transform(
    image: np.ndarray,
    transform_matrix: np.ndarray,  # (2, 3)
    output_size: Tuple[int, int] = (112, 112),
    interpolation: int = cv2.INTER_LINEAR,
) -> np.ndarray:
    """
    Apply alignment transform to image.
    
    Args:
        image: Input image (H, W, 3) BGR uint8
        transform_matrix: 2x3 transformation matrix
        output_size: Output size (width, height)
        interpolation: OpenCV interpolation flag
        
    Returns:
        Transformed image (output_size[1], output_size[0], 3) BGR uint8
    """
    aligned = cv2.warpAffine(
        image,
        transform_matrix,
        output_size,
        flags=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return aligned


def extract_5point_landmarks(
    landmarks_68: List[Tuple[float, float, float]],
) -> List[Tuple[float, float]]:
    """
    Extract 5 key landmarks for ArcFace alignment from 68 3D landmarks.
    
    Computes:
    1. Left eye center (average of 36, 39)
    2. Right eye center (average of 42, 45)
    3. Nose tip (30)
    4. Left mouth corner (48)
    5. Right mouth corner (54)
    
    Args:
        landmarks_68: 68 3D landmarks (x, y, z)
        
    Returns:
        5 2D landmarks (x, y) in model input space
    """
    pts = np.array(landmarks_68, dtype=np.float32)  # (68, 3)
    
    # Left eye center
    left_eye = (pts[36, :2] + pts[39, :2]) / 2
    # Right eye center
    right_eye = (pts[42, :2] + pts[45, :2]) / 2
    # Nose tip
    nose = pts[30, :2]
    # Left mouth
    left_mouth = pts[48, :2]
    # Right mouth
    right_mouth = pts[54, :2]
    
    return [
        tuple(left_eye.astype(float)),
        tuple(right_eye.astype(float)),
        tuple(nose.astype(float)),
        tuple(left_mouth.astype(float)),
        tuple(right_mouth.astype(float)),
    ]


class HardPoseAligner:
    """
    Hard-pose face alignment pipeline.
    
    Integrates:
    - 1K3D68 landmark detection (Phase 7)
    - Pose estimation and classification
    - Landmark validation
    - Geometric alignment correction
    - ArcFace inference (Phase 12)
    """
    
    def __init__(self, config: Optional[HardPoseConfig] = None):
        """
        Initialize hard-pose aligner.
        
        Args:
            config: HardPoseConfig instance (default: DEFAULT_HARDPOSE_CONFIG)
        """
        if config is None:
            config = get_default_hardpose_config()
        
        self.config = config
        
        # Initialize 1K3D68 landmark detector
        self.landmark_detector = create_landmark_detector(
            model_id=config.landmark_model_id,
            providers=list(config.landmark_providers),
            min_crop_dimension=config.min_crop_dimension,
        )
        
        # Initialize ArcFace inference
        self.arcface_inference = create_arcface_inference(
            providers=list(config.arcface_providers),
        )
        
        # ArcFace input contract for validation
        self.arcface_input_contract = get_arcface_input_contract()
    
    def align_normal(self, crop: FaceCrop) -> NormalAlignmentResult:
        """
        Perform normal alignment (no 1K3D68) for frontal/near-frontal faces.
        
        Uses simple similarity transform based on face crop bbox.
        This is the fast path for NORMAL pose faces.
        
        Args:
            crop: Validated face crop
            
        Returns:
            NormalAlignmentResult with 112x112 aligned face
        """
        t0 = time.perf_counter()
        
        # Simple resize-based alignment for normal poses
        # The crop is already a face region, just resize to 112x112
        aligned = cv2.resize(
            crop.data,
            (112, 112),
            interpolation=cv2.INTER_LINEAR,
        )
        
        t1 = time.perf_counter()
        
        return NormalAlignmentResult(
            aligned_face_bgr=aligned,
            used_1k3d68=False,
            total_time_ms=(t1 - t0) * 1000,
            source_crop_id=crop.crop_id,
            source_frame_index=crop.frame_index,
            source_id=crop.source_id,
        )
    
    def align_hard_pose(self, crop: FaceCrop) -> HardPoseAlignmentResult:
        """
        Perform hard-pose alignment using 1K3D68 landmarks.
        
        Pipeline:
        1. Run 1K3D68 landmark detection
        2. Validate landmarks
        3. Estimate pose (yaw, pitch, roll)
        4. Classify pose state
        5. Extract 5-point landmarks for alignment
        6. Compute similarity transform to ArcFace target points
        7. Apply transform to get 112x112 aligned face
        
        Args:
            crop: Validated face crop
            
        Returns:
            HardPoseAlignmentResult with aligned face and full provenance
            
        Raises:
            HardPoseAlignmentError: If alignment fails
        """
        t_total_0 = time.perf_counter()
        
        # Step 1: 1K3D68 landmark detection
        t_landmark_0 = time.perf_counter()
        try:
            landmark_result = self.landmark_detector.detect(crop)
        except LandmarkError as e:
            raise HardPoseAlignmentError(
                f"Landmark detection failed: {e}",
                pose_state=PoseState.INVALID,
                crop_id=crop.crop_id,
                frame_index=crop.frame_index,
            )
        t_landmark_1 = time.perf_counter()
        landmark_time_ms = (t_landmark_1 - t_landmark_0) * 1000
        
        # Step 2: Validate landmarks
        if self.config.validate_landmarks:
            valid_count, validity_mask = validate_landmarks_for_pose(
                landmark_result.landmarks,
                coordinate_space=landmark_result.coordinate_space.value,
                max_coordinate=self.config.pose_thresholds.max_landmark_distance,
            )
            
            if valid_count < self.config.pose_thresholds.min_valid_landmarks:
                raise HardPoseAlignmentError(
                    f"Insufficient valid landmarks: {valid_count} < {self.config.pose_thresholds.min_valid_landmarks}",
                    pose_state=PoseState.INVALID,
                    crop_id=crop.crop_id,
                    frame_index=crop.frame_index,
                )
        else:
            valid_count = 68
            validity_mask = [True] * 68
        
        # Step 3: Estimate pose
        yaw, pitch, roll = estimate_pose_from_landmarks(
            landmark_result.landmarks,
            coordinate_space=landmark_result.coordinate_space.value,
        )
        
        # Step 4: Classify pose
        pose_state = classify_pose(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            valid_landmark_count=valid_count,
            thresholds=self.config.pose_thresholds,
        )
        
        if pose_state == PoseState.INVALID:
            raise HardPoseAlignmentError(
                f"Pose classified as INVALID: yaw={yaw:.1f}, pitch={pitch:.1f}, roll={roll:.1f}, valid_landmarks={valid_count}",
                pose_state=PoseState.INVALID,
                crop_id=crop.crop_id,
                frame_index=crop.frame_index,
            )
        
        # Create pose estimation object
        pose_estimation = PoseEstimation(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            valid_landmark_count=valid_count,
            total_landmarks=68,
            coordinate_space=landmark_result.coordinate_space.value,
            state=pose_state,
            model_id=landmark_result.model_id,
            model_sha256=landmark_result.model_sha256,
        )
        
        # Step 5: Extract 5-point landmarks for alignment
        t_align_0 = time.perf_counter()
        src_landmarks_5pt = extract_5point_landmarks(landmark_result.landmarks)
        src_points = np.array(src_landmarks_5pt, dtype=np.float32)
        dst_points = np.array(ARC_FACE_TARGET_5POINTS, dtype=np.float32)
        
        # Step 6: Compute similarity transform
        transform_matrix = compute_similarity_transform(src_points, dst_points)
        
        # Step 7: Apply transform to crop image
        aligned_face = apply_alignment_transform(
            crop.data,
            transform_matrix,
            output_size=(112, 112),
            interpolation=cv2.INTER_LINEAR,
        )
        t_align_1 = time.perf_counter()
        alignment_time_ms = (t_align_1 - t_align_0) * 1000
        
        # Validate aligned face
        if self.config.validate_aligned_face:
            if aligned_face.shape != (112, 112, 3):
                raise HardPoseAlignmentError(
                    f"Aligned face has wrong shape: {aligned_face.shape}",
                    pose_state=pose_state,
                    crop_id=crop.crop_id,
                    frame_index=crop.frame_index,
                )
            if aligned_face.dtype != np.uint8:
                raise HardPoseAlignmentError(
                    f"Aligned face has wrong dtype: {aligned_face.dtype}",
                    pose_state=pose_state,
                    crop_id=crop.crop_id,
                    frame_index=crop.frame_index,
                )
        
        # Create alignment transform record
        alignment_transform = AlignmentTransform(
            source_landmark_indices=self.config.alignment_landmark_indices,
            source_landmarks=src_landmarks_5pt,
            target_landmarks=ARC_FACE_TARGET_5POINTS,
            transform_type="similarity",
            transform_matrix=transform_matrix.tolist(),
            interpolation="INTER_LINEAR",
            output_size=(112, 112),
            model_id=landmark_result.model_id,
            model_sha256=landmark_result.model_sha256,
        )
        
        t_total_1 = time.perf_counter()
        total_time_ms = (t_total_1 - t_total_0) * 1000
        
        return HardPoseAlignmentResult(
            aligned_face_bgr=aligned_face,
            pose_estimation=pose_estimation,
            alignment_transform=alignment_transform,
            used_1k3d68=True,
            total_time_ms=total_time_ms,
            landmark_time_ms=landmark_time_ms,
            alignment_time_ms=alignment_time_ms,
            source_crop_id=crop.crop_id,
            source_frame_index=crop.frame_index,
            source_id=crop.source_id,
        )
    
    def align(self, crop: FaceCrop) -> HardPosePipelineResult:
        """
        Main alignment entry point: routes to normal or hard-pose alignment.
        
        For NORMAL pose: uses fast resize-based alignment
        For HARD_POSE: uses 1K3D68 geometric correction
        For INVALID: raises HardPoseAlignmentError
        
        Args:
            crop: Validated face crop
            
        Returns:
            HardPosePipelineResult with aligned face ready for ArcFace
            
        Raises:
            HardPoseAlignmentError: If face cannot be aligned (INVALID pose)
        """
        # First, we need to determine pose state
        # For this, we need landmarks. But we don't want to run 1K3D68 for NORMAL faces.
        # Strategy: Run a quick landmark detection to classify pose, then route.
        # Actually, the spec says: NORMAL -> normal alignment, HARD_POSE -> 1K3D68 -> alignment
        # So we need to run 1K3D68 first to classify, then decide.
        # But that means we always run 1K3D68. Let's optimize: run 1K3D68, classify, then align.
        
        # Run landmark detection first
        t_landmark_0 = time.perf_counter()
        try:
            landmark_result = self.landmark_detector.detect(crop)
        except LandmarkError as e:
            raise HardPoseAlignmentError(
                f"Landmark detection failed: {e}",
                pose_state=PoseState.INVALID,
                crop_id=crop.crop_id,
                frame_index=crop.frame_index,
            )
        t_landmark_1 = time.perf_counter()
        landmark_time_ms = (t_landmark_1 - t_landmark_0) * 1000
        
        # Validate landmarks
        if self.config.validate_landmarks:
            valid_count, validity_mask = validate_landmarks_for_pose(
                landmark_result.landmarks,
                coordinate_space=landmark_result.coordinate_space.value,
                max_coordinate=self.config.pose_thresholds.max_landmark_distance,
            )
        else:
            valid_count = 68
        
        # Estimate pose
        yaw, pitch, roll = estimate_pose_from_landmarks(
            landmark_result.landmarks,
            coordinate_space=landmark_result.coordinate_space.value,
        )
        
        # Classify pose
        pose_state = classify_pose(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            valid_landmark_count=valid_count,
            thresholds=self.config.pose_thresholds,
        )
        
        # Create pose estimation
        pose_estimation = PoseEstimation(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            valid_landmark_count=valid_count,
            total_landmarks=68,
            coordinate_space=landmark_result.coordinate_space.value,
            state=pose_state,
            model_id=landmark_result.model_id,
            model_sha256=landmark_result.model_sha256,
        )
        
        t_total_0 = time.perf_counter()
        
        # Use provenance from landmark_result (the actual processing result)
        source_crop_id = landmark_result.crop_id
        source_frame_index = landmark_result.frame_index
        source_id = landmark_result.source_id
        
        if pose_state == PoseState.NORMAL:
            # Fast path: normal alignment
            t_align_0 = time.perf_counter()
            aligned = cv2.resize(crop.data, (112, 112), interpolation=cv2.INTER_LINEAR)
            t_align_1 = time.perf_counter()
            alignment_time_ms = (t_align_1 - t_align_0) * 1000
            
            t_total_1 = time.perf_counter()
            total_time_ms = (t_total_1 - t_total_0) * 1000 + landmark_time_ms
            
            return HardPosePipelineResult(
                aligned_face_bgr=aligned,
                used_1k3d68=False,
                pose_estimation=pose_estimation,
                alignment_transform=None,
                total_time_ms=total_time_ms,
                landmark_time_ms=landmark_time_ms,
                alignment_time_ms=alignment_time_ms,
                source_crop_id=source_crop_id,
                source_frame_index=source_frame_index,
                source_id=source_id,
            )
        
        elif pose_state == PoseState.HARD_POSE:
            # Hard-pose path: geometric correction using 1K3D68 landmarks
            t_align_0 = time.perf_counter()
            
            # Extract 5-point landmarks
            src_landmarks_5pt = extract_5point_landmarks(landmark_result.landmarks)
            src_points = np.array(src_landmarks_5pt, dtype=np.float32)
            dst_points = np.array(ARC_FACE_TARGET_5POINTS, dtype=np.float32)
            
            # Compute similarity transform
            transform_matrix = compute_similarity_transform(src_points, dst_points)
            
            # Apply transform
            aligned_face = apply_alignment_transform(
                crop.data,
                transform_matrix,
                output_size=(112, 112),
                interpolation=cv2.INTER_LINEAR,
            )
            t_align_1 = time.perf_counter()
            alignment_time_ms = (t_align_1 - t_align_0) * 1000
            
            # Validate aligned face
            if self.config.validate_aligned_face:
                if aligned_face.shape != (112, 112, 3):
                    raise HardPoseAlignmentError(
                        f"Aligned face has wrong shape: {aligned_face.shape}",
                        pose_state=pose_state,
                        crop_id=source_crop_id,
                        frame_index=source_frame_index,
                    )
            
            # Create alignment transform record
            # Use the 5-point landmark indices for the transform record
            alignment_transform = AlignmentTransform(
                source_landmark_indices=[36, 39, 42, 45, 30, 48, 54][:5],  # First 5 indices that correspond to 5 points
                source_landmarks=src_landmarks_5pt,
                target_landmarks=ARC_FACE_TARGET_5POINTS,
                transform_type="similarity",
                transform_matrix=transform_matrix.tolist(),
                interpolation="INTER_LINEAR",
                output_size=(112, 112),
                model_id=landmark_result.model_id,
                model_sha256=landmark_result.model_sha256,
            )
            
            t_total_1 = time.perf_counter()
            total_time_ms = (t_total_1 - t_total_0) * 1000 + landmark_time_ms
            
            return HardPosePipelineResult(
                aligned_face_bgr=aligned_face,
                used_1k3d68=True,
                pose_estimation=pose_estimation,
                alignment_transform=alignment_transform,
                total_time_ms=total_time_ms,
                landmark_time_ms=landmark_time_ms,
                alignment_time_ms=alignment_time_ms,
                source_crop_id=source_crop_id,
                source_frame_index=source_frame_index,
                source_id=source_id,
            )
        
        else:  # INVALID
            raise HardPoseAlignmentError(
                f"Pose classified as INVALID: yaw={yaw:.1f}, pitch={pitch:.1f}, roll={roll:.1f}, valid_landmarks={valid_count}",
                pose_state=PoseState.INVALID,
                crop_id=crop.crop_id,
                frame_index=crop.frame_index,
            )
    
    def align_and_recognize(self, crop: FaceCrop) -> HardPosePipelineResult:
        """
        Complete pipeline: align face -> run ArcFace inference.
        
        Args:
            crop: Validated face crop
            
        Returns:
            HardPosePipelineResult with aligned face and ArcFace embedding
        """
        # Align
        result = self.align(crop)
        
        # Run ArcFace inference
        t_arcface_0 = time.perf_counter()
        arcface_result = self.arcface_inference.infer(result.aligned_face_bgr)
        t_arcface_1 = time.perf_counter()
        arcface_time_ms = (t_arcface_1 - t_arcface_0) * 1000
        
        # Update result with ArcFace inference
        return HardPosePipelineResult(
            aligned_face_bgr=result.aligned_face_bgr,
            used_1k3d68=result.used_1k3d68,
            pose_estimation=result.pose_estimation,
            alignment_transform=result.alignment_transform,
            total_time_ms=result.total_time_ms + arcface_time_ms,
            landmark_time_ms=result.landmark_time_ms,
            alignment_time_ms=result.alignment_time_ms,
            arcface_time_ms=arcface_time_ms,
            source_crop_id=result.source_crop_id,
            source_frame_index=result.source_frame_index,
            source_id=result.source_id,
            arcface_result=arcface_result,
        )


def create_hardpose_aligner(
    config: Optional[HardPoseConfig] = None,
) -> HardPoseAligner:
    """
    Factory function to create HardPoseAligner.
    
    Args:
        config: HardPoseConfig instance (default: DEFAULT_HARDPOSE_CONFIG)
        
    Returns:
        HardPoseAligner instance
    """
    return HardPoseAligner(config=config)