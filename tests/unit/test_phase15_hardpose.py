"""
Phase 15 — 1K3D68 Hard-Pose Assisted ArcFace Unit Tests.

Tests cover:
- Hard-pose contract (PoseState, PoseThresholds, PoseEstimation, AlignmentTransform)
- Pose classification (NORMAL, HARD_POSE, INVALID)
- Landmark validation
- Pose estimation from landmarks
- Similarity transform computation
- 5-point landmark extraction
- Normal vs Hard-Pose routing
- ArcFace compatibility
- Determinism
- Provenance preservation
- Safety (offline only)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import numpy as np
import pytest

from app.vision.hardpose_contract import (
    PoseState,
    PoseThresholds,
    PoseEstimation,
    AlignmentTransform,
    HardPoseAlignmentResult,
    HardPoseConfig,
    classify_pose,
    validate_landmarks_for_pose,
    get_default_pose_thresholds,
    get_default_hardpose_config,
    ARC_FACE_TARGET_5POINTS,
)
from app.vision.hardpose_alignment import (
    estimate_pose_from_landmarks,
    extract_5point_landmarks,
)
from app.vision.hardpose_alignment import (
    HardPoseAligner,
    HardPosePipelineResult,
    HardPoseAlignmentError,
    NormalAlignmentResult,
    compute_similarity_transform,
    compute_affine_transform,
    apply_alignment_transform,
    create_hardpose_aligner,
)
from app.vision.landmarks import LandmarkResult, LandmarkCoordinateSpace, LandmarkError
from app.vision.crop import FaceCrop
from app.data.frame import SourceType


class TestPoseState:
    """Tests for PoseState enum."""
    
    def test_pose_states_exist(self):
        """Test that all required pose states exist."""
        assert PoseState.NORMAL.value == "NORMAL"
        assert PoseState.HARD_POSE.value == "HARD_POSE"
        assert PoseState.INVALID.value == "INVALID"
    
    def test_pose_state_values(self):
        """Test pose state string values."""
        assert str(PoseState.NORMAL) == "PoseState.NORMAL"
        assert PoseState.NORMAL.value == "NORMAL"
        assert PoseState.HARD_POSE.value == "HARD_POSE"
        assert PoseState.INVALID.value == "INVALID"


class TestPoseThresholds:
    """Tests for PoseThresholds configuration."""
    
    def test_default_thresholds(self):
        """Test default threshold values."""
        thresholds = PoseThresholds()
        
        assert thresholds.yaw_normal_max == 25.0
        assert thresholds.yaw_hard_max == 60.0
        assert thresholds.pitch_normal_max == 20.0
        assert thresholds.pitch_hard_max == 45.0
        assert thresholds.roll_normal_max == 30.0
        assert thresholds.roll_hard_max == 60.0
        assert thresholds.min_valid_landmarks == 60
        assert thresholds.max_landmark_distance == 192.0
    
    def test_custom_thresholds(self):
        """Test custom threshold values."""
        thresholds = PoseThresholds(
            yaw_normal_max=30.0,
            yaw_hard_max=70.0,
            pitch_normal_max=25.0,
            pitch_hard_max=50.0,
            roll_normal_max=35.0,
            roll_hard_max=65.0,
            min_valid_landmarks=50,
            max_landmark_distance=200.0,
        )
        
        assert thresholds.yaw_normal_max == 30.0
        assert thresholds.yaw_hard_max == 70.0
        assert thresholds.min_valid_landmarks == 50
    
    def test_invalid_yaw_thresholds(self):
        """Test that invalid yaw thresholds raise ValueError."""
        with pytest.raises(ValueError, match="Invalid yaw thresholds"):
            PoseThresholds(yaw_normal_max=30.0, yaw_hard_max=20.0)  # normal > hard
    
    def test_invalid_pitch_thresholds(self):
        """Test that invalid pitch thresholds raise ValueError."""
        with pytest.raises(ValueError, match="Invalid pitch thresholds"):
            PoseThresholds(pitch_normal_max=30.0, pitch_hard_max=20.0)
    
    def test_invalid_roll_thresholds(self):
        """Test that invalid roll thresholds raise ValueError."""
        with pytest.raises(ValueError, match="Invalid roll thresholds"):
            PoseThresholds(roll_normal_max=30.0, roll_hard_max=20.0)
    
    def test_invalid_min_landmarks(self):
        """Test that invalid min_valid_landmarks raises ValueError."""
        with pytest.raises(ValueError, match="min_valid_landmarks must be in"):
            PoseThresholds(min_valid_landmarks=0)
        
        with pytest.raises(ValueError, match="min_valid_landmarks must be in"):
            PoseThresholds(min_valid_landmarks=69)
    
    def test_invalid_max_distance(self):
        """Test that invalid max_landmark_distance raises ValueError."""
        with pytest.raises(ValueError, match="max_landmark_distance must be positive"):
            PoseThresholds(max_landmark_distance=0)


class TestPoseEstimation:
    """Tests for PoseEstimation dataclass."""
    
    def test_valid_pose_estimation(self):
        """Test creating valid pose estimation."""
        pose = PoseEstimation(
            yaw=10.0,
            pitch=5.0,
            roll=2.0,
            valid_landmark_count=68,
            state=PoseState.NORMAL,
            model_sha256="abc123",
        )
        
        assert pose.yaw == 10.0
        assert pose.pitch == 5.0
        assert pose.roll == 2.0
        assert pose.valid_landmark_count == 68
        assert pose.state == PoseState.NORMAL
        assert pose.model_sha256 == "abc123"
    
    def test_invalid_state_type(self):
        """Test that non-PoseState state raises ValueError."""
        with pytest.raises(ValueError, match="state must be PoseState enum"):
            PoseEstimation(
                yaw=0.0, pitch=0.0, roll=0.0,
                valid_landmark_count=68,
                state="NORMAL",  # String instead of enum
            )
    
    def test_invalid_landmark_count(self):
        """Test that invalid landmark count raises ValueError."""
        with pytest.raises(ValueError, match="valid_landmark_count must be in"):
            PoseEstimation(
                yaw=0.0, pitch=0.0, roll=0.0,
                valid_landmark_count=70,  # > 68
                state=PoseState.NORMAL,
            )
    
    def test_non_finite_angles(self):
        """Test that non-finite angles raise ValueError."""
        with pytest.raises(ValueError, match="Pose angles must be finite"):
            PoseEstimation(
                yaw=float('nan'), pitch=0.0, roll=0.0,
                valid_landmark_count=68,
                state=PoseState.NORMAL,
            )


class TestAlignmentTransform:
    """Tests for AlignmentTransform dataclass."""
    
    def test_valid_transform(self):
        """Test creating valid alignment transform."""
        transform = AlignmentTransform(
            source_landmark_indices=[36, 39, 42, 45, 30, 48, 54],
            source_landmarks=[(10.0, 20.0)] * 7,
            target_landmarks=[(30.0, 40.0)] * 7,
            transform_type="similarity",
            transform_matrix=[[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]],
        )
        
        assert len(transform.source_landmark_indices) == 7
        assert transform.transform_type == "similarity"
        assert transform.output_size == (112, 112)
    
    def test_mismatched_lengths(self):
        """Test that mismatched source/target lengths raise ValueError."""
        with pytest.raises(ValueError, match="must have same length"):
            AlignmentTransform(
                source_landmark_indices=[36, 39],
                source_landmarks=[(10.0, 20.0)] * 3,  # 3 vs 2
                target_landmarks=[(30.0, 40.0)] * 2,
            )
    
    def test_insufficient_landmarks(self):
        """Test that < 2 landmarks raises ValueError."""
        with pytest.raises(ValueError, match="At least 2 landmarks required"):
            AlignmentTransform(
                source_landmark_indices=[36],
                source_landmarks=[(10.0, 20.0)],
                target_landmarks=[(30.0, 40.0)],
            )
    
    def test_invalid_transform_type(self):
        """Test that invalid transform type raises ValueError."""
        with pytest.raises(ValueError, match="transform_type must be"):
            AlignmentTransform(
                source_landmark_indices=[36, 39],
                source_landmarks=[(10.0, 20.0), (30.0, 40.0)],
                target_landmarks=[(30.0, 40.0), (50.0, 60.0)],
                transform_type="projective",  # Invalid
            )
    
    def test_invalid_output_size(self):
        """Test that invalid output size raises ValueError."""
        with pytest.raises(ValueError, match="output_size must be"):
            AlignmentTransform(
                source_landmark_indices=[36, 39],
                source_landmarks=[(10.0, 20.0), (30.0, 40.0)],
                target_landmarks=[(30.0, 40.0), (50.0, 60.0)],
                output_size=(224, 224),  # Wrong size
            )


class TestHardPoseAlignmentResult:
    """Tests for HardPoseAlignmentResult dataclass."""
    
    def test_valid_result(self):
        """Test creating valid hard-pose alignment result."""
        aligned_face = np.random.randint(0, 256, (112, 112, 3), dtype=np.uint8)
        pose = PoseEstimation(
            yaw=30.0, pitch=10.0, roll=5.0,
            valid_landmark_count=65,
            state=PoseState.HARD_POSE,
        )
        # AlignmentTransform expects source_landmark_indices and source_landmarks to have same length
        transform = AlignmentTransform(
            source_landmark_indices=[36, 39, 42, 45, 30],  # 5 indices to match 5 points
            source_landmarks=[(10.0, 20.0)] * 5,
            target_landmarks=ARC_FACE_TARGET_5POINTS,
        )
        
        result = HardPoseAlignmentResult(
            aligned_face_bgr=aligned_face,
            pose_estimation=pose,
            alignment_transform=transform,
            used_1k3d68=True,
            total_time_ms=50.0,
            landmark_time_ms=30.0,
            alignment_time_ms=20.0,
            source_crop_id="crop123",
            source_frame_index=0,
            source_id="test.jpg",
        )
        
        assert result.used_1k3d68 is True
        assert result.pose_estimation.state == PoseState.HARD_POSE
        assert result.aligned_face_bgr.shape == (112, 112, 3)
    
    def test_invalid_aligned_face_shape(self):
        """Test that wrong aligned face shape raises ValueError."""
        aligned_face = np.random.randint(0, 256, (224, 224, 3), dtype=np.uint8)
        pose = PoseEstimation(yaw=0.0, pitch=0.0, roll=0.0, valid_landmark_count=68, state=PoseState.NORMAL)
        transform = AlignmentTransform(
            source_landmark_indices=[36, 39],
            source_landmarks=[(10.0, 20.0), (30.0, 40.0)],
            target_landmarks=[(30.0, 40.0), (50.0, 60.0)],
        )
        
        with pytest.raises(ValueError, match="aligned_face_bgr must be"):
            HardPoseAlignmentResult(
                aligned_face_bgr=aligned_face,
                pose_estimation=pose,
                alignment_transform=transform,
                used_1k3d68=True,
                total_time_ms=50.0,
            )
    
    def test_invalid_aligned_face_dtype(self):
        """Test that wrong aligned face dtype raises ValueError."""
        aligned_face = np.random.rand(112, 112, 3).astype(np.float32)
        pose = PoseEstimation(yaw=0.0, pitch=0.0, roll=0.0, valid_landmark_count=68, state=PoseState.NORMAL)
        transform = AlignmentTransform(
            source_landmark_indices=[36, 39],
            source_landmarks=[(10.0, 20.0), (30.0, 40.0)],
            target_landmarks=[(30.0, 40.0), (50.0, 60.0)],
        )
        
        with pytest.raises(ValueError, match="aligned_face_bgr must be uint8"):
            HardPoseAlignmentResult(
                aligned_face_bgr=aligned_face,
                pose_estimation=pose,
                alignment_transform=transform,
                used_1k3d68=True,
                total_time_ms=50.0,
            )


class TestClassifyPose:
    """Tests for classify_pose function."""
    
    def test_normal_pose_frontal(self):
        """Test frontal face classified as NORMAL."""
        state = classify_pose(yaw=0.0, pitch=0.0, roll=0.0, valid_landmark_count=68)
        assert state == PoseState.NORMAL
    
    def test_normal_pose_small_angles(self):
        """Test small angles classified as NORMAL."""
        state = classify_pose(yaw=10.0, pitch=5.0, roll=10.0, valid_landmark_count=68)
        assert state == PoseState.NORMAL
    
    def test_normal_pose_at_boundary(self):
        """Test angles at normal boundary classified as NORMAL."""
        state = classify_pose(yaw=25.0, pitch=20.0, roll=30.0, valid_landmark_count=68)
        assert state == PoseState.NORMAL
    
    def test_hard_pose_yaw(self):
        """Test yaw exceeding normal but within hard -> HARD_POSE."""
        state = classify_pose(yaw=30.0, pitch=0.0, roll=0.0, valid_landmark_count=68)
        assert state == PoseState.HARD_POSE
    
    def test_hard_pose_pitch(self):
        """Test pitch exceeding normal but within hard -> HARD_POSE."""
        state = classify_pose(yaw=0.0, pitch=25.0, roll=0.0, valid_landmark_count=68)
        assert state == PoseState.HARD_POSE
    
    def test_hard_pose_roll(self):
        """Test roll exceeding normal but within hard -> HARD_POSE."""
        state = classify_pose(yaw=0.0, pitch=0.0, roll=35.0, valid_landmark_count=68)
        assert state == PoseState.HARD_POSE
    
    def test_hard_pose_at_boundary(self):
        """Test angles at hard boundary classified as HARD_POSE."""
        state = classify_pose(yaw=60.0, pitch=45.0, roll=60.0, valid_landmark_count=68)
        assert state == PoseState.HARD_POSE
    
    def test_invalid_yaw_exceeds_hard(self):
        """Test yaw exceeding hard limit -> INVALID."""
        state = classify_pose(yaw=65.0, pitch=0.0, roll=0.0, valid_landmark_count=68)
        assert state == PoseState.INVALID
    
    def test_invalid_pitch_exceeds_hard(self):
        """Test pitch exceeding hard limit -> INVALID."""
        state = classify_pose(yaw=0.0, pitch=50.0, roll=0.0, valid_landmark_count=68)
        assert state == PoseState.INVALID
    
    def test_invalid_roll_exceeds_hard(self):
        """Test roll exceeding hard limit -> INVALID."""
        state = classify_pose(yaw=0.0, pitch=0.0, roll=65.0, valid_landmark_count=68)
        assert state == PoseState.INVALID
    
    def test_invalid_insufficient_landmarks(self):
        """Test insufficient landmarks -> INVALID."""
        state = classify_pose(yaw=0.0, pitch=0.0, roll=0.0, valid_landmark_count=50)
        assert state == PoseState.INVALID
    
    def test_custom_thresholds(self):
        """Test classification with custom thresholds."""
        thresholds = PoseThresholds(
            yaw_normal_max=15.0,
            yaw_hard_max=45.0,
            pitch_normal_max=10.0,
            pitch_hard_max=30.0,
            roll_normal_max=15.0,
            roll_hard_max=45.0,
            min_valid_landmarks=55,
        )
        
        # With custom thresholds, 20° yaw is HARD_POSE
        state = classify_pose(yaw=20.0, pitch=0.0, roll=0.0, valid_landmark_count=68, thresholds=thresholds)
        assert state == PoseState.HARD_POSE
        
        # But 10° yaw is NORMAL
        state = classify_pose(yaw=10.0, pitch=0.0, roll=0.0, valid_landmark_count=68, thresholds=thresholds)
        assert state == PoseState.NORMAL
    
    def test_negative_angles(self):
        """Test that negative angles are handled correctly (absolute value used)."""
        state = classify_pose(yaw=-30.0, pitch=-25.0, roll=-35.0, valid_landmark_count=68)
        assert state == PoseState.HARD_POSE


class TestValidateLandmarksForPose:
    """Tests for validate_landmarks_for_pose function."""
    
    def test_all_valid_landmarks(self):
        """Test validation with all valid landmarks."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        valid_count, mask = validate_landmarks_for_pose(landmarks)
        
        assert valid_count == 68
        assert all(mask)
    
    def test_some_invalid_landmarks(self):
        """Test validation with some NaN landmarks."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        landmarks[0] = (float('nan'), 0.0, 0.0)
        landmarks[1] = (0.0, float('inf'), 0.0)
        
        valid_count, mask = validate_landmarks_for_pose(landmarks)
        
        assert valid_count == 66
        assert not mask[0]
        assert not mask[1]
        assert all(mask[2:])
    
    def test_out_of_range_landmarks(self):
        """Test validation with out-of-range coordinates."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        landmarks[0] = (200.0, 0.0, 0.0)  # x > 192
        landmarks[1] = (0.0, -10.0, 0.0)  # y < 0
        
        valid_count, mask = validate_landmarks_for_pose(landmarks, max_coordinate=192.0)
        
        assert valid_count == 66
        assert not mask[0]
        assert not mask[1]
    
    def test_wrong_landmark_count(self):
        """Test that wrong number of landmarks raises ValueError."""
        landmarks = [(float(i), float(i), float(i)) for i in range(67)]
        
        with pytest.raises(ValueError, match="Expected 68 landmarks"):
            validate_landmarks_for_pose(landmarks)

class TestEstimatePoseFromLandmarks:
    """Tests for estimate_pose_from_landmarks function."""
    
    def test_frontal_face_pose(self):
        """Test pose estimation for frontal face."""
        # Create synthetic frontal face landmarks
        landmarks = self._create_frontal_landmarks()
        
        yaw, pitch, roll = estimate_pose_from_landmarks(landmarks)
        
        # Frontal face should have near-zero angles
        assert abs(yaw) < 5.0
        assert abs(pitch) < 5.0
        assert abs(roll) < 5.0
    
    def test_yaw_rotation(self):
        """Test pose estimation with yaw rotation."""
        landmarks = self._create_frontal_landmarks()
        # Simulate yaw by moving nose tip horizontally
        landmarks = list(landmarks)
        landmarks[30] = (landmarks[30][0] + 20.0, landmarks[30][1], landmarks[30][2])  # Move nose right
        
        yaw, pitch, roll = estimate_pose_from_landmarks(landmarks)
        
        # Nose moved right -> positive yaw (left turn from camera perspective)
        assert yaw > 0
    
    def test_pitch_rotation(self):
        """Test pose estimation with pitch rotation."""
        landmarks = self._create_frontal_landmarks()
        # Simulate pitch by moving nose up
        landmarks = list(landmarks)
        landmarks[30] = (landmarks[30][0], landmarks[30][1] - 15.0, landmarks[30][2])  # Move nose up
        
        yaw, pitch, roll = estimate_pose_from_landmarks(landmarks)
        
        # Nose up -> positive pitch
        assert pitch > 0
    
    def test_roll_rotation(self):
        """Test pose estimation with roll rotation."""
        landmarks = self._create_frontal_landmarks()
        # Simulate roll by rotating eyes
        landmarks = list(landmarks)
        # Rotate eye centers around center
        center_x = 96.0
        center_y = 96.0
        angle = np.radians(30)
        for idx in [36, 39, 42, 45]:
            x, y, z = landmarks[idx]
            dx = x - center_x
            dy = y - center_y
            new_x = center_x + dx * np.cos(angle) - dy * np.sin(angle)
            new_y = center_y + dx * np.sin(angle) + dy * np.cos(angle)
            landmarks[idx] = (new_x, new_y, z)
        
        yaw, pitch, roll = estimate_pose_from_landmarks(landmarks)
        
        # Should detect roll
        assert abs(roll) > 10.0
    
    def _create_frontal_landmarks(self) -> List[Tuple[float, float, float]]:
        """Create synthetic frontal face landmarks."""
        landmarks = [(0.0, 0.0, 0.0)] * 68
        
        # Set key landmarks to realistic frontal face positions
        # Eyes at same y level (horizontal)
        landmarks[36] = (70.0, 80.0, 0.0)   # Left eye outer
        landmarks[39] = (85.0, 80.0, 0.0)   # Left eye inner
        landmarks[42] = (107.0, 80.0, 0.0)  # Right eye inner
        landmarks[45] = (122.0, 80.0, 0.0)  # Right eye outer
        # Nose tip at 1/3 down from eyes to mouth (frontal pose)
        # Eyes at y=80, mouth at y=120, so 1/3 down = 80 + 40/3 = 93.33
        landmarks[30] = (96.0, 93.33, 10.0)  # Nose tip
        # Mouth below nose, centered
        landmarks[48] = (80.0, 120.0, 0.0)   # Left mouth
        landmarks[54] = (112.0, 120.0, 0.0)  # Right mouth
        
        return landmarks


class TestExtract5PointLandmarks:
    """Tests for extract_5point_landmarks function."""
    
    def test_extract_5points(self):
        """Test extraction of 5 key landmarks."""
        landmarks = [(float(i), float(i), float(i)) for i in range(68)]
        
        points_5 = extract_5point_landmarks(landmarks)
        
        assert len(points_5) == 5
        # Check they're 2D tuples
        for pt in points_5:
            assert len(pt) == 2
            assert isinstance(pt[0], float)
            assert isinstance(pt[1], float)
    
    def test_eye_centers_computed(self):
        """Test that eye centers are computed correctly."""
        landmarks = [(0.0, 0.0, 0.0)] * 68
        landmarks[36] = (10.0, 20.0, 0.0)  # Left outer
        landmarks[39] = (30.0, 20.0, 0.0)  # Left inner
        landmarks[42] = (50.0, 20.0, 0.0)  # Right inner
        landmarks[45] = (70.0, 20.0, 0.0)  # Right outer
        landmarks[30] = (40.0, 50.0, 10.0)  # Nose
        landmarks[48] = (20.0, 80.0, 0.0)  # Left mouth
        landmarks[54] = (60.0, 80.0, 0.0)  # Right mouth
        
        points_5 = extract_5point_landmarks(landmarks)
        
        # Left eye center = (10+30)/2, (20+20)/2 = (20, 20)
        assert points_5[0] == (20.0, 20.0)
        # Right eye center = (50+70)/2, (20+20)/2 = (60, 20)
        assert points_5[1] == (60.0, 20.0)
        # Nose = (40, 50)
        assert points_5[2] == (40.0, 50.0)
        # Left mouth = (20, 80)
        assert points_5[3] == (20.0, 80.0)
        # Right mouth = (60, 80)
        assert points_5[4] == (60.0, 80.0)


class TestComputeSimilarityTransform:
    """Tests for compute_similarity_transform function."""
    
    def test_identity_transform(self):
        """Test similarity transform with identical points."""
        src = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], dtype=np.float32)
        dst = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], dtype=np.float32)
        
        transform = compute_similarity_transform(src, dst)
        
        # Should be identity (scale=1, rotation=0, translation=0)
        assert np.allclose(transform[:2, :2], np.eye(2), atol=1e-5)
        assert np.allclose(transform[:2, 2], [0.0, 0.0], atol=1e-5)
    
    def test_translation_only(self):
        """Test similarity transform with translation only."""
        src = np.array([[0.0, 0.0], [10.0, 0.0]], dtype=np.float32)
        dst = np.array([[5.0, 5.0], [15.0, 5.0]], dtype=np.float32)
        
        transform = compute_similarity_transform(src, dst)
        
        # Scale=1, rotation=0, translation=(5, 5)
        assert np.allclose(transform[:2, :2], np.eye(2), atol=1e-5)
        assert np.allclose(transform[:2, 2], [5.0, 5.0], atol=1e-5)
    
    def test_scale_and_rotation(self):
        """Test similarity transform with scale and rotation."""
        # Test that the transform correctly maps src to dst
        src = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], dtype=np.float32)
        # Simple case: scale=2, no rotation, translation=(10, 20)
        dst = np.array([[10.0, 20.0], [30.0, 20.0], [10.0, 40.0]], dtype=np.float32)
    
        transform = compute_similarity_transform(src, dst)
    
        # Apply transform to src and check it matches dst
        src_homo = np.hstack([src, np.ones((3, 1))])
        transformed = (transform @ src_homo.T).T
        assert np.allclose(transformed, dst, atol=1e-5)
    
        # Also test rotation case - 45 degree rotation, scale=1, no translation
        # For Umeyama algorithm with 3 points, test a case that works reliably
        src2 = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], dtype=np.float32)
        # 45 degree rotation: (x, y) -> (x*cos45 - y*sin45, x*sin45 + y*cos45)
        cos45 = np.cos(np.pi/4)
        sin45 = np.sin(np.pi/4)
        dst2 = np.array([
            [0.0, 0.0],
            [10*cos45, 10*sin45],
            [-10*sin45, 10*cos45]
        ], dtype=np.float32)
    
        transform2 = compute_similarity_transform(src2, dst2)
        src2_homo = np.hstack([src2, np.ones((3, 1))])
        transformed2 = (transform2 @ src2_homo.T).T
        assert np.allclose(transformed2, dst2, atol=1e-5)
    
    def test_insufficient_points(self):
        """Test that < 2 points raises ValueError."""
        src = np.array([[0.0, 0.0]], dtype=np.float32)
        dst = np.array([[5.0, 5.0]], dtype=np.float32)
        
        with pytest.raises(ValueError, match="At least 2 point pairs required"):
            compute_similarity_transform(src, dst)
    
    def test_shape_mismatch(self):
        """Test that shape mismatch raises ValueError."""
        src = np.array([[0.0, 0.0], [10.0, 0.0]], dtype=np.float32)
        dst = np.array([[5.0, 5.0]], dtype=np.float32)
        
        with pytest.raises(ValueError, match="must have same shape"):
            compute_similarity_transform(src, dst)


class TestComputeAffineTransform:
    """Tests for compute_affine_transform function."""
    
    def test_affine_transform(self):
        """Test affine transform computation."""
        src = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], dtype=np.float32)
        dst = np.array([[5.0, 5.0], [15.0, 5.0], [5.0, 15.0]], dtype=np.float32)
        
        transform = compute_affine_transform(src, dst)
        
        # Apply transform
        src_homo = np.hstack([src, np.ones((3, 1))])
        transformed = (transform @ src_homo.T).T
        assert np.allclose(transformed, dst, atol=1e-5)
    
    def test_insufficient_points(self):
        """Test that < 3 points raises ValueError."""
        src = np.array([[0.0, 0.0], [10.0, 0.0]], dtype=np.float32)
        dst = np.array([[5.0, 5.0], [15.0, 5.0]], dtype=np.float32)
        
        with pytest.raises(ValueError, match="At least 3 point pairs required"):
            compute_affine_transform(src, dst)


class TestApplyAlignmentTransform:
    """Tests for apply_alignment_transform function."""
    
    def test_apply_transform(self):
        """Test applying alignment transform to image."""
        # Create test image
        image = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        
        # Identity transform
        transform = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
        
        aligned = apply_alignment_transform(image, transform, output_size=(112, 112))
        
        assert aligned.shape == (112, 112, 3)
        assert aligned.dtype == np.uint8
    
    def test_apply_translation(self):
        """Test applying translation transform."""
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        image[50, 50] = [255, 255, 255]  # White pixel at center
        
        # Translate by (10, 20)
        transform = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, 20.0]], dtype=np.float32)
        
        aligned = apply_alignment_transform(image, transform, output_size=(112, 112))
        
        # White pixel should move to (60, 70)
        assert aligned[70, 60, 0] == 255


# Module-level fixtures shared across all test classes
@pytest.fixture
def mock_landmark_detector():
    """Create a mock landmark detector."""
    mock = MagicMock()
    mock.detect = MagicMock()
    return mock

@pytest.fixture
def mock_arcface_inference():
    """Create a mock ArcFace inference."""
    mock = MagicMock()
    mock.infer = MagicMock()
    return mock

@pytest.fixture
def valid_crop():
    """Create a valid face crop."""
    crop_data = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    return FaceCrop(
        data=crop_data,
        crop_width=100,
        crop_height=100,
        source_type=SourceType.IMAGE,
        source_id="test.jpg",
        frame_index=0,
        timestamp=None,
        original_frame_width=640,
        original_frame_height=480,
        bbox=(100.0, 100.0, 200.0, 200.0),
        detection_confidence=0.9,
        detection_id="det123",
        crop_id="crop123",
    )

@pytest.fixture
def frontal_landmarks():
    """Create frontal face landmarks."""
    landmarks = []
    for i in range(68):
        x = 96.0 + (i % 10) * 2 - 10
        y = 96.0 + (i // 10) * 2 - 10
        z = 0.0
        landmarks.append((x, y, z))
    
    # Set key landmarks
    landmarks[36] = (70.0, 80.0, 0.0)
    landmarks[39] = (85.0, 80.0, 0.0)
    landmarks[42] = (107.0, 80.0, 0.0)
    landmarks[45] = (122.0, 80.0, 0.0)
    landmarks[30] = (96.0, 100.0, 10.0)
    landmarks[48] = (80.0, 120.0, 0.0)
    landmarks[54] = (112.0, 120.0, 0.0)
    
    return landmarks

@pytest.fixture
def yaw_landmarks():
    """Create landmarks with yaw rotation (30 degrees - within HARD_POSE range)."""
    landmarks = _create_frontal_landmarks_module()
    landmarks = list(landmarks)
    # Move nose to create ~30 degree yaw (within HARD_POSE range of 25-60)
    # eye_center_x ~ 96, eye_distance ~ 37, need nose_offset_x = sin(30°) * 37 * 0.5 = 0.5 * 18.5 = 9.25
    landmarks[30] = (landmarks[30][0] + 10.0, landmarks[30][1], landmarks[30][2])
    return landmarks

def _create_frontal_landmarks_module():
    landmarks = []
    for i in range(68):
        x = 96.0 + (i % 10) * 2 - 10
        y = 96.0 + (i // 10) * 2 - 10
        z = 0.0
        landmarks.append((x, y, z))
    landmarks[36] = (70.0, 80.0, 0.0)
    landmarks[39] = (85.0, 80.0, 0.0)
    landmarks[42] = (107.0, 80.0, 0.0)
    landmarks[45] = (122.0, 80.0, 0.0)
    landmarks[30] = (96.0, 100.0, 10.0)
    landmarks[48] = (80.0, 120.0, 0.0)
    landmarks[54] = (112.0, 120.0, 0.0)
    return landmarks

class TestHardPoseAligner:
    """Tests for HardPoseAligner class."""
    
    def _create_frontal_landmarks(self):
        landmarks = []
        for i in range(68):
            x = 96.0 + (i % 10) * 2 - 10
            y = 96.0 + (i // 10) * 2 - 10
            z = 0.0
            landmarks.append((x, y, z))
        landmarks[36] = (70.0, 80.0, 0.0)
        landmarks[39] = (85.0, 80.0, 0.0)
        landmarks[42] = (107.0, 80.0, 0.0)
        landmarks[45] = (122.0, 80.0, 0.0)
        landmarks[30] = (96.0, 100.0, 10.0)
        landmarks[48] = (80.0, 120.0, 0.0)
        landmarks[54] = (112.0, 120.0, 0.0)
        return landmarks
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_align_normal_pose(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test alignment of normal pose face (should use fast path)."""
        # Setup mock landmark detector
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Align
        result = aligner.align(valid_crop)
        
        # Verify
        assert isinstance(result, HardPosePipelineResult)
        assert result.used_1k3d68 is False  # Normal pose -> no 1K3D68 alignment
        assert result.aligned_face_bgr.shape == (112, 112, 3)
        assert result.pose_estimation.state == PoseState.NORMAL
        assert result.alignment_transform is None
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_align_hard_pose_yaw(self, mock_arcface, mock_landmark_detector, valid_crop, yaw_landmarks):
        """Test alignment of hard-pose face (yaw > 25°)."""
        # Setup mock landmark detector
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=yaw_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Align
        result = aligner.align(valid_crop)
        
        # Verify
        assert isinstance(result, HardPosePipelineResult)
        assert result.used_1k3d68 is True  # Hard pose -> 1K3D68 alignment used
        assert result.aligned_face_bgr.shape == (112, 112, 3)
        assert result.pose_estimation.state == PoseState.HARD_POSE
        assert result.alignment_transform is not None
        assert result.alignment_transform.transform_type == "similarity"
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_align_invalid_pose(self, mock_arcface, mock_landmark_detector, valid_crop):
        """Test alignment of invalid pose face (should raise error)."""
        # Create landmarks with extreme yaw
        landmarks = self._create_frontal_landmarks()
        landmarks = list(landmarks)
        landmarks[30] = (landmarks[30][0] + 80.0, landmarks[30][1], landmarks[30][2])  # Extreme yaw
        
        # Setup mock landmark detector
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Align should raise error
        with pytest.raises(HardPoseAlignmentError, match="INVALID"):
            aligner.align(valid_crop)
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_align_landmark_detection_failure(self, mock_arcface, mock_landmark_detector, valid_crop):
        """Test alignment when landmark detection fails."""
        # Setup mock landmark detector to raise error
        mock_detector = MagicMock()
        mock_detector.detect.side_effect = LandmarkError("Detection failed", model_id="landmark_1k3d68")
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Align should raise error
        with pytest.raises(HardPoseAlignmentError, match="Landmark detection failed"):
            aligner.align(valid_crop)
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_align_and_recognize(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test complete align + recognize pipeline."""
        # Setup mock landmark detector
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface_result = MagicMock()
        mock_arcface_result.normalized_embedding = np.random.rand(1, 512).astype(np.float32)
        mock_arcface_result.raw_embedding = np.random.rand(1, 512).astype(np.float32)
        mock_arcface_result.raw_norm = 10.0
        mock_arcface_result.inference_time_ms = 5.0
        mock_arcface_result.provider = "CPUExecutionProvider"
        mock_arcface_instance.infer.return_value = mock_arcface_result
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Align and recognize
        result = aligner.align_and_recognize(valid_crop)
        
        # Verify
        assert result.arcface_result is not None
        assert result.arcface_time_ms > 0
        assert result.total_time_ms > result.arcface_time_ms


class TestDeterminism:
    """Tests for determinism of hard-pose pipeline."""
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_deterministic_alignment(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test that same input produces same output."""
        # Setup mock landmark detector
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Run alignment twice
        result1 = aligner.align(valid_crop)
        result2 = aligner.align(valid_crop)
        
        # Results should be identical (deterministic)
        assert np.array_equal(result1.aligned_face_bgr, result2.aligned_face_bgr)
        assert result1.pose_estimation.yaw == result2.pose_estimation.yaw
        assert result1.pose_estimation.pitch == result2.pose_estimation.pitch
        assert result1.pose_estimation.roll == result2.pose_estimation.roll
        assert result1.used_1k3d68 == result2.used_1k3d68
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_deterministic_hard_pose(self, mock_arcface, mock_landmark_detector, valid_crop, yaw_landmarks):
        """Test that hard-pose alignment is deterministic."""
        # Setup mock landmark detector
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=yaw_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Setup mock ArcFace
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        # Create aligner
        aligner = create_hardpose_aligner()
        
        # Run alignment twice
        result1 = aligner.align(valid_crop)
        result2 = aligner.align(valid_crop)
        
        # Results should be identical
        assert np.array_equal(result1.aligned_face_bgr, result2.aligned_face_bgr)
        assert result1.alignment_transform.transform_matrix == result2.alignment_transform.transform_matrix


class TestProvenance:
    """Tests for provenance preservation."""
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_provenance_preserved_normal(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test that provenance is preserved in normal alignment."""
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=5,
            source_id="video.mp4",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align(valid_crop)
        
        assert result.source_crop_id == "crop123"
        assert result.source_frame_index == 5
        assert result.source_id == "video.mp4"
        assert result.pose_estimation.model_id == "landmark_1k3d68"
        assert result.pose_estimation.model_sha256 == "abc123"
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_provenance_preserved_hard_pose(self, mock_arcface, mock_landmark_detector, valid_crop, yaw_landmarks):
        """Test that provenance is preserved in hard-pose alignment."""
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=yaw_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="def456",
            crop_id="crop456",
            frame_index=10,
            source_id="image.jpg",
            inference_time_ms=15.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align(valid_crop)
        
        assert result.source_crop_id == "crop456"
        assert result.source_frame_index == 10
        assert result.source_id == "image.jpg"
        assert result.pose_estimation.model_id == "landmark_1k3d68"
        assert result.pose_estimation.model_sha256 == "def456"
        assert result.alignment_transform.model_id == "landmark_1k3d68"
        assert result.alignment_transform.model_sha256 == "def456"


class TestArcFaceCompatibility:
    """Tests for ArcFace compatibility (Phase 12 contract)."""
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_aligned_face_satisfies_arcface_contract(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test that aligned face satisfies ArcFace input contract."""
        from app.vision.recognition_contract import get_arcface_input_contract
        
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align(valid_crop)
        
        # Validate against ArcFace input contract
        contract = get_arcface_input_contract()
        is_valid, error = contract.validate_input(
            contract.preprocess(result.aligned_face_bgr)
        )
        
        assert is_valid, f"Aligned face failed ArcFace contract: {error}"
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_hard_pose_aligned_face_satisfies_arcface_contract(self, mock_arcface, mock_landmark_detector, valid_crop, yaw_landmarks):
        """Test that hard-pose aligned face satisfies ArcFace input contract."""
        from app.vision.recognition_contract import get_arcface_input_contract
        
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=yaw_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align(valid_crop)
        
        # Validate against ArcFace input contract
        contract = get_arcface_input_contract()
        is_valid, error = contract.validate_input(
            contract.preprocess(result.aligned_face_bgr)
        )
        
        assert is_valid, f"Hard-pose aligned face failed ArcFace contract: {error}"


class TestPhase14Compatibility:
    """Tests for Phase 14 matching compatibility."""
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_embedding_compatible_with_phase14(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test that final embedding is compatible with Phase 14 matching."""
        from app.vision.matching_contract import validate_query_embedding
        
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        # Mock ArcFace to return valid embedding
        mock_arcface_instance = MagicMock()
        mock_arcface_result = MagicMock()
        # Create valid L2-normalized embedding
        embedding = np.random.rand(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)
        mock_arcface_result.normalized_embedding = embedding.reshape(1, 512)
        mock_arcface_result.raw_embedding = embedding.reshape(1, 512)
        mock_arcface_result.raw_norm = 1.0
        mock_arcface_result.inference_time_ms = 5.0
        mock_arcface_result.provider = "CPUExecutionProvider"
        mock_arcface_instance.infer.return_value = mock_arcface_result
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align_and_recognize(valid_crop)
        
        # Validate against Phase 14 query embedding contract
        is_valid, error = validate_query_embedding(result.arcface_result.normalized_embedding.flatten())
        
        assert is_valid, f"Embedding failed Phase 14 contract: {error}"


class TestNormalPoseRegression:
    """Tests for normal-pose regression (ensure normal faces don't use 1K3D68 unnecessarily)."""
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_normal_faces_use_fast_path(self, mock_arcface, mock_landmark_detector, valid_crop, frontal_landmarks):
        """Test that normal faces use fast resize path, not 1K3D68 geometric correction."""
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=frontal_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align(valid_crop)
        
        # Normal pose should NOT use 1K3D68 for alignment (only for pose classification)
        assert result.used_1k3d68 is False
        assert result.alignment_transform is None
        # But landmark detection WAS run for pose classification
        assert result.pose_estimation is not None
        assert result.landmark_time_ms > 0
    
    @patch('app.vision.hardpose_alignment.create_landmark_detector')
    @patch('app.vision.hardpose_alignment.create_arcface_inference')
    def test_hard_pose_faces_use_geometric_correction(self, mock_arcface, mock_landmark_detector, valid_crop, yaw_landmarks):
        """Test that hard-pose faces use 1K3D68 geometric correction."""
        mock_detector = MagicMock()
        mock_landmark_result = LandmarkResult(
            landmarks=yaw_landmarks,
            coordinate_space=LandmarkCoordinateSpace.MODEL_INPUT_RELATIVE,
            model_id="landmark_1k3d68",
            model_sha256="abc123",
            crop_id="crop123",
            frame_index=0,
            source_id="test.jpg",
            inference_time_ms=10.0,
        )
        mock_detector.detect.return_value = mock_landmark_result
        mock_landmark_detector.return_value = mock_detector
        
        mock_arcface_instance = MagicMock()
        mock_arcface.return_value = mock_arcface_instance
        
        aligner = create_hardpose_aligner()
        result = aligner.align(valid_crop)
        
        # Hard pose SHOULD use 1K3D68 for alignment
        assert result.used_1k3d68 is True
        assert result.alignment_transform is not None
        assert result.alignment_transform.transform_type == "similarity"


class TestSafety:
    """Tests for safety (offline only, no camera/streaming)."""
    
    def test_no_camera_imports(self):
        """Test that module doesn't import camera-related modules."""
        import app.vision.hardpose_alignment as hardpose_module
        import app.vision.hardpose_contract as hardpose_contract
        
        # Check source code for forbidden imports (actual import statements, not comments/docstrings)
        import inspect
        import ast
        
        source_alignment = inspect.getsource(hardpose_module)
        source_contract = inspect.getsource(hardpose_contract)
        
        # Parse AST to find actual imports
        def get_imports(source):
            tree = ast.parse(source)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
            return imports
        
        imports_alignment = get_imports(source_alignment)
        imports_contract = get_imports(source_contract)
        
        forbidden = [
            'camera', 'rtsp', 'rtmp',
            'mediamtx', 'ffmpeg',
            'attendance', 'schedule',
            'excel', 'in_out',
        ]
        
        for term in forbidden:
            # Check if any import contains the forbidden term
            for imp in imports_alignment:
                assert term.lower() not in imp.lower(), f"Found forbidden import '{term}' in hardpose_alignment: {imp}"
            for imp in imports_contract:
                assert term.lower() not in imp.lower(), f"Found forbidden import '{term}' in hardpose_contract: {imp}"
    
    def test_no_live_streaming_code(self):
        """Test that no live streaming code exists."""
        import inspect
        import app.vision.hardpose_alignment as hardpose_module
        
        source = inspect.getsource(hardpose_module)
        
        # Should not have streaming-related patterns
        assert 'while True' not in source or 'frame' not in source.lower()
        assert 'cv2.VideoCapture' not in source
        assert 'cv2.imshow' not in source


class TestHardPoseConfig:
    """Tests for HardPoseConfig."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = HardPoseConfig()
        
        assert isinstance(config.pose_thresholds, PoseThresholds)
        assert config.landmark_model_id == "landmark_1k3d68"
        assert config.min_crop_dimension == 32
        assert len(config.alignment_landmark_indices) == 5
        assert len(config.target_landmarks_112) == 5
        assert len(config.alignment_landmark_indices) == len(config.target_landmarks_112)
        assert config.arcface_providers == ("CUDAExecutionProvider", "CPUExecutionProvider")
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = HardPoseConfig(
            pose_thresholds=PoseThresholds(yaw_normal_max=15.0),
            landmark_providers=("CPUExecutionProvider",),
            min_crop_dimension=64,
        )
        
        assert config.pose_thresholds.yaw_normal_max == 15.0
        assert config.landmark_providers == ("CPUExecutionProvider",)
        assert config.min_crop_dimension == 64
    
    def test_invalid_alignment_indices_length(self):
        """Test that mismatched alignment indices/targets raises ValueError."""
        with pytest.raises(ValueError, match="must match target_landmarks_112 length"):
            HardPoseConfig(
                alignment_landmark_indices=[36, 39, 42],  # 3 indices
                target_landmarks_112=[(0, 0)] * 5,  # 5 targets
            )
    
    def test_invalid_alignment_indices_range(self):
        """Test that out-of-range alignment indices raises ValueError."""
        with pytest.raises(ValueError, match="must be in \\[0, 67\\]"):
            HardPoseConfig(
                alignment_landmark_indices=[36, 39, 42, 45, 70],  # 70 > 67
                target_landmarks_112=[(0, 0)] * 5,  # 5 targets to match 5 indices
            )


class TestFactoryFunctions:
    """Tests for factory functions."""
    
    @patch('app.vision.hardpose_alignment.HardPoseAligner')
    def test_create_hardpose_aligner(self, mock_aligner_class):
        """Test factory function."""
        mock_aligner = MagicMock()
        mock_aligner_class.return_value = mock_aligner
        
        aligner = create_hardpose_aligner()
        
        mock_aligner_class.assert_called_once()
        assert aligner == mock_aligner
    
    def test_get_default_pose_thresholds(self):
        """Test get_default_pose_thresholds function."""
        thresholds = get_default_pose_thresholds()
        assert isinstance(thresholds, PoseThresholds)
        assert thresholds.yaw_normal_max == 25.0
    
    def test_get_default_hardpose_config(self):
        """Test get_default_hardpose_config function."""
        config = get_default_hardpose_config()
        assert isinstance(config, HardPoseConfig)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])