"""
Model registry for Windows native AI attendance system.

Provides a single authoritative Model Registry for the entire project.
All pipelines (IMAGE → .npy, VIDEO → .npy, LIVE CAMERA → inference)
must use this same registry.

This module does NOT perform inference.
This module does NOT access cameras.
This module does NOT modify model files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union

from app.config.paths import get_project_paths
from app.models.contracts import (
    ModelDefinition,
    ModelFormat,
    ModelProvider,
    ModelStatus,
    PreprocessingConfig,
    OutputContract,
    ThresholdsConfig,
    ModelVersion,
    DatasetCompatibility,
    HashStatus,
)
from app.models.exceptions import (
    ModelNotFoundError,
    ModelMissingError,
    ModelHashMismatchError,
    ModelNotVerifiedError,
)
from app.models.hashing import compute_sha256, verify_sha256, HashResult


# =============================================================================
# PRODUCTION MODEL DEFINITIONS
# =============================================================================

# Reference SHA256 values from legacy evidence
# These are REFERENCE values only until verified against actual files

SCRFD_REFERENCE_SHA256 = "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"
ARCFACE_REFERENCE_SHA256 = "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"
LANDMARK_1K3D68_REFERENCE_SHA256 = "df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc"
REID_REFERENCE_SHA256 = "09d398902020205dd4aa80495b2a8fceecd64ba610e6b72afc1f93965c9613d2"
YOLO11N_REFERENCE_SHA256 = "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1"
YOLO11N_POSE_REFERENCE_SHA256 = "869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0"


def _create_scrfd_definition() -> ModelDefinition:
    """Create SCRFD face detection model definition."""
    return ModelDefinition(
        model_id="scrfd",
        display_name="SCRFD Face Detector",
        description="SCRFD 10G face detection model with 5 keypoints per face",
        filename="scrfd_10g_bnkps.onnx",
        format=ModelFormat.ONNX,
        expected_sha256=SCRFD_REFERENCE_SHA256,
        subdirectory="scrfd",
        provider=ModelProvider.ONNXRUNTIME,
        preprocessing=PreprocessingConfig(
            input_height=640,
            input_width=640,
            input_channels=3,
            resize_mode="letterbox",
            preserve_aspect_ratio=True,
            padding_value=114,
            padding_mode="constant",
            channel_order="RGB",
            dtype="float32",
            normalization_mean=(0.485, 0.456, 0.406),
            normalization_std=(0.229, 0.224, 0.225),
            normalization_scale=1.0/255.0,
            alignment=None,
            notes="SCRFD 640x640 input with threshold 0.55 and NMS 0.45",
            verified=False,
        ),
        output_contract=OutputContract(
            output_type="detection",
            num_classes=1,  # Face class
            num_keypoints=5,  # 5 keypoints per face (eyes, nose, mouth corners)
            postprocessing="nms",
            notes="Face boxes with 5 keypoints",
            verified=False,
        ),
        thresholds=ThresholdsConfig(
            confidence_threshold=0.55,
            nms_threshold=0.45,
        ),
        version=ModelVersion(
            version="1.0.0",
            architecture="scrfd_10g",
            training_dataset="WIDERFace + custom",
            source="insightface",
            contract_version="1.0",
            preprocessing_version="1.0",
        ),
        tags=["face", "detection", "onnx"],
        required=True,
    )


def _create_arcface_definition() -> ModelDefinition:
    """Create ArcFace face recognition model definition."""
    return ModelDefinition(
        model_id="arcface",
        display_name="ArcFace Face Recognition",
        description="GLINT360K R100 ArcFace face recognition model for 512D embeddings",
        filename="glintr100.onnx",
        format=ModelFormat.ONNX,
        expected_sha256=ARCFACE_REFERENCE_SHA256,
        subdirectory="arcface",
        provider=ModelProvider.ONNXRUNTIME,
        preprocessing=PreprocessingConfig(
            input_height=112,
            input_width=112,
            input_channels=3,
            resize_mode="crop",
            preserve_aspect_ratio=False,
            padding_value=0,
            padding_mode="constant",
            channel_order="RGB",
            dtype="float32",
            normalization_mean=None,  # NOT_VERIFIED - not established in evidence
            normalization_std=None,  # NOT_VERIFIED - not established in evidence
            normalization_scale=None,  # NOT_VERIFIED - not established in evidence
            alignment=None,
            notes="ArcFace 112x112 input for 512D embedding",
            verified=False,
        ),
        output_contract=OutputContract(
            output_type="embedding",
            embedding_dimension=512,
            notes="512-dimensional face embedding",
            verified=False,
        ),
        thresholds=ThresholdsConfig(
            distance_threshold=0.6,  # Default threshold for face matching
        ),
        version=ModelVersion(
            version="1.0.0",
            architecture="glintr100",
            training_dataset="GLINT360K",
            source="insightface",
            contract_version="1.0",
            preprocessing_version="1.0",
        ),
        tags=["face", "recognition", "embedding", "onnx"],
        required=True,
    )


def _create_landmark_1k3d68_definition() -> ModelDefinition:
    """Create 1k3d68 landmark model definition."""
    return ModelDefinition(
        model_id="landmark_1k3d68",
        display_name="1K3D68 Face Landmark",
        description="3D face landmark model with 68 landmarks",
        filename="1k3d68.onnx",
        format=ModelFormat.ONNX,
        expected_sha256=LANDMARK_1K3D68_REFERENCE_SHA256,
        subdirectory="landmark",
        provider=ModelProvider.ONNXRUNTIME,
        preprocessing=PreprocessingConfig(
            input_height=192,
            input_width=192,
            input_channels=3,
            resize_mode="fit",
            preserve_aspect_ratio=True,
            padding_value=0,
            padding_mode="constant",
            channel_order="RGB",
            dtype="float32",
            normalization_mean=None,  # NOT_VERIFIED - not established in evidence
            normalization_std=None,  # NOT_VERIFIED - not established in evidence
            normalization_scale=None,  # NOT_VERIFIED - not established in evidence
            alignment=None,
            notes="1k3d68 192x192 input for 68 3D landmarks",
            verified=False,
        ),
        output_contract=OutputContract(
            output_type="landmarks",
            num_landmarks=68,
            landmark_format="xyz",  # 3D landmarks
            notes="68 3D face landmarks",
            verified=False,
        ),
        version=ModelVersion(
            version="1.0.0",
            architecture="1k3d68",
            training_dataset="300W-LP + AFLW",
            source="insightface",
            contract_version="1.0",
            preprocessing_version="1.0",
        ),
        tags=["face", "landmark", "3d", "onnx"],
        required=False,
    )


def _create_reid_definition() -> ModelDefinition:
    """Create ReID person re-identification model definition."""
    return ModelDefinition(
        model_id="reid",
        display_name="ResNet50 ReID",
        description="ResNet50-based person re-identification model for 2048D embeddings",
        filename="resnet50_reid.onnx",
        format=ModelFormat.ONNX,
        expected_sha256=REID_REFERENCE_SHA256,
        subdirectory="reid",
        provider=ModelProvider.ONNXRUNTIME,
        preprocessing=PreprocessingConfig(
            input_height=256,
            input_width=128,
            input_channels=3,
            resize_mode="fit",
            preserve_aspect_ratio=True,
            padding_value=0,
            padding_mode="constant",
            channel_order="RGB",
            dtype="float32",
            normalization_mean=None,  # NOT_VERIFIED - not established in evidence
            normalization_std=None,  # NOT_VERIFIED - not established in evidence
            normalization_scale=None,  # NOT_VERIFIED - not established in evidence
            alignment=None,
            notes="ReID 256x128 input for 2048D embedding",
            verified=False,
        ),
        output_contract=OutputContract(
            output_type="embedding",
            embedding_dimension=2048,
            notes="2048-dimensional person embedding",
            verified=False,
        ),
        version=ModelVersion(
            version="1.0.0",
            architecture="resnet50",
            training_dataset="Market-1501 + DukeMTMC",
            source="custom",
            contract_version="1.0",
            preprocessing_version="1.0",
        ),
        tags=["person", "reid", "embedding", "onnx"],
        required=False,
    )


def _create_yolo_person_definition() -> ModelDefinition:
    """Create YOLO person detection model definition."""
    return ModelDefinition(
        model_id="yolo_person",
        display_name="YOLO11n Person Detector",
        description="YOLO11n model for person detection",
        filename="yolo11n.pt",
        format=ModelFormat.PYTORCH,
        expected_sha256=YOLO11N_REFERENCE_SHA256,
        subdirectory="yolo",
        provider=ModelProvider.ULTRALYTICS,
        preprocessing=PreprocessingConfig(
            input_height=640,  # Default YOLO input size
            input_width=640,
            input_channels=3,
            resize_mode="fit",
            preserve_aspect_ratio=True,
            padding_value=0,
            padding_mode="constant",
            channel_order="RGB",
            dtype="float32",
            normalization_mean=None,  # NOT_VERIFIED - will be obtained from model
            normalization_std=None,  # NOT_VERIFIED - will be obtained from model
            normalization_scale=1.0 / 255.0,  # Standard YOLO normalization
            alignment=32,
            notes="YOLO11n person detection - input contract must be obtained from actual model",
            verified=False,
        ),
        output_contract=OutputContract(
            output_type="detection",
            num_classes=1,  # Person class only
            postprocessing="nms",
            notes="Person detection boxes - output contract must be obtained from actual model",
            verified=False,
        ),
        thresholds=ThresholdsConfig(
            confidence_threshold=0.5,  # Default, may need adjustment
            nms_threshold=0.45,
        ),
        version=ModelVersion(
            version="1.0.0",
            architecture="yolo11n",
            training_dataset="COCO",
            source="ultralytics",
            contract_version="1.0",
            preprocessing_version="1.0",
        ),
        tags=["person", "detection", "yolo", "pytorch"],
        required=False,
    )


def _create_yolo_pose_definition() -> ModelDefinition:
    """Create YOLO pose detection model definition."""
    return ModelDefinition(
        model_id="yolo_pose",
        display_name="YOLO11n-Pose",
        description="YOLO11n-pose model for human pose estimation",
        filename="yolo11n-pose.pt",
        format=ModelFormat.PYTORCH,
        expected_sha256=YOLO11N_POSE_REFERENCE_SHA256,
        subdirectory="yolo",
        provider=ModelProvider.ULTRALYTICS,
        preprocessing=PreprocessingConfig(
            input_height=640,  # Default YOLO input size
            input_width=640,
            input_channels=3,
            resize_mode="fit",
            preserve_aspect_ratio=True,
            padding_value=0,
            padding_mode="constant",
            channel_order="RGB",
            dtype="float32",
            normalization_mean=None,  # NOT_VERIFIED - will be obtained from model
            normalization_std=None,  # NOT_VERIFIED - will be obtained from model
            normalization_scale=1.0 / 255.0,  # Standard YOLO normalization
            alignment=32,
            notes="YOLO11n-pose - input contract must be obtained from actual model",
            verified=False,
        ),
        output_contract=OutputContract(
            output_type="pose",
            pose_keypoints=17,  # COCO 17 keypoints
            postprocessing="nms",
            notes="Person pose keypoints - output contract must be obtained from actual model",
            verified=False,
        ),
        thresholds=ThresholdsConfig(
            confidence_threshold=0.5,  # Default, may need adjustment
            nms_threshold=0.45,
        ),
        version=ModelVersion(
            version="1.0.0",
            architecture="yolo11n-pose",
            training_dataset="COCO",
            source="ultralytics",
            contract_version="1.0",
            preprocessing_version="1.0",
        ),
        tags=["person", "pose", "yolo", "pytorch"],
        required=False,
    )


# =============================================================================
# MODEL REGISTRY
# =============================================================================

class ModelRegistry:
    """
    Single authoritative model registry for the entire project.
    
    All pipelines must use this registry for model definitions:
    - IMAGE → .npy
    - VIDEO → .npy
    - LIVE CAMERA → inference
    
    There is ONE source of truth for:
    - model identity
    - model file
    - SHA256
    - model format
    - input shape
    - output contract
    - preprocessing
    - normalization
    - alignment requirements
    - postprocessing
    - embedding dimension
    - thresholds
    - provider requirements
    - model version
    """
    
    _instance: Optional["ModelRegistry"] = None
    _models: Dict[str, ModelDefinition] = {}
    _models_dir: Optional[Path] = None
    _initialized: bool = False
    
    def __new__(cls) -> "ModelRegistry":
        """Singleton pattern to ensure single registry instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the registry with production models."""
        if self._initialized:
            return
        
        self._models: Dict[str, ModelDefinition] = {}
        self._models_dir: Optional[Path] = None
        self._initialized = True
        
        # Register all production models
        self._register_production_models()
    
    def _register_production_models(self) -> None:
        """Register all production model definitions."""
        # Register SCRFD
        scrfd = _create_scrfd_definition()
        self._register(scrfd)
        
        # Register ArcFace
        arcface = _create_arcface_definition()
        self._register(arcface)
        
        # Register 1k3d68 landmark
        landmark = _create_landmark_1k3d68_definition()
        self._register(landmark)
        
        # Register ReID
        reid = _create_reid_definition()
        self._register(reid)
        
        # Register YOLO person
        yolo_person = _create_yolo_person_definition()
        self._register(yolo_person)
        
        # Register YOLO pose
        yolo_pose = _create_yolo_pose_definition()
        self._register(yolo_pose)
    
    def _register(self, model: ModelDefinition) -> None:
        """
        Register a model definition.
        
        Args:
            model: Model definition to register.
        """
        self._models[model.model_id] = model
    
    def set_models_dir(self, models_dir: Union[str, Path]) -> None:
        """
        Set the models directory path.
        
        Args:
            models_dir: Path to the models directory.
        """
        self._models_dir = Path(models_dir).resolve()
    
    def get_models_dir(self) -> Path:
        """
        Get the models directory path.
        
        Returns:
            Path to the models directory.
        """
        if self._models_dir is None:
            # Use project paths from Phase 1 configuration
            paths = get_project_paths()
            self._models_dir = paths.models_dir
        return self._models_dir
    
    def get(self, model_id: str) -> ModelDefinition:
        """
        Get a model definition by ID.
        
        Args:
            model_id: Unique model identifier.
            
        Returns:
            ModelDefinition for the requested model.
            
        Raises:
            ModelNotFoundError: If model_id is not registered.
        """
        if model_id not in self._models:
            raise ModelNotFoundError(model_id)
        return self._models[model_id]
    
    def get_model_path(self, model_id: str) -> Path:
        """
        Get the full path to a model file.
        
        Args:
            model_id: Unique model identifier.
            
        Returns:
            Path to the model file.
        """
        model = self.get(model_id)
        models_dir = self.get_models_dir()
        return Path(model.get_model_path(str(models_dir)))
    
    def get_all_models(self) -> Dict[str, ModelDefinition]:
        """
        Get all registered model definitions.
        
        Returns:
            Dictionary of model_id to ModelDefinition.
        """
        return dict(self._models)
    
    def get_model_ids(self) -> List[str]:
        """
        Get all registered model IDs.
        
        Returns:
            List of model IDs.
        """
        return list(self._models.keys())
    
    def is_registered(self, model_id: str) -> bool:
        """
        Check if a model is registered.
        
        Args:
            model_id: Model ID to check.
            
        Returns:
            True if model is registered, False otherwise.
        """
        return model_id in self._models
    
    def verify_model(self, model_id: str) -> HashResult:
        """
        Verify a model file's SHA256 hash.
        
        Args:
            model_id: Model ID to verify.
            
        Returns:
            HashResult with verification status.
        """
        model = self.get(model_id)
        model_path = self.get_model_path(model_id)
        
        return verify_sha256(model_path, model.expected_sha256)
    
    def get_model_status(self, model_id: str) -> ModelStatus:
        """
        Get the overall status of a model.
        
        Args:
            model_id: Model ID to check.
            
        Returns:
            ModelStatus indicating the model's availability.
        """
        hash_result = self.verify_model(model_id)
        
        if hash_result.is_missing():
            return ModelStatus.MISSING
        elif hash_result.is_mismatch():
            return ModelStatus.CORRUPT
        elif hash_result.is_verified():
            return ModelStatus.AVAILABLE
        else:
            return ModelStatus.UNVERIFIED
    
    def check_all_models(self) -> Dict[str, HashResult]:
        """
        Check all registered models.
        
        Returns:
            Dictionary mapping model_id to HashResult.
        """
        results = {}
        for model_id in self._models:
            results[model_id] = self.verify_model(model_id)
        return results
    
    def get_available_models(self) -> List[str]:
        """
        Get list of model IDs that are available (verified).
        
        Returns:
            List of available model IDs.
        """
        available = []
        for model_id in self._models:
            if self.get_model_status(model_id) == ModelStatus.AVAILABLE:
                available.append(model_id)
        return available
    
    def get_missing_models(self) -> List[str]:
        """
        Get list of model IDs that are missing.
        
        Returns:
            List of missing model IDs.
        """
        missing = []
        for model_id in self._models:
            if self.get_model_status(model_id) == ModelStatus.MISSING:
                missing.append(model_id)
        return missing
    
    def get_required_models(self) -> List[str]:
        """
        Get list of required model IDs.
        
        Returns:
            List of required model IDs.
        """
        required = []
        for model_id, model in self._models.items():
            if model.required:
                required.append(model_id)
        return required
    
    def get_embedding_models(self) -> List[str]:
        """
        Get list of embedding model IDs.
        
        Returns:
            List of embedding model IDs.
        """
        embedding = []
        for model_id, model in self._models.items():
            if model.output_contract.output_type == "embedding":
                embedding.append(model_id)
        return embedding
    
    def get_detection_models(self) -> List[str]:
        """
        Get list of detection model IDs.
        
        Returns:
            List of detection model IDs.
        """
        detection = []
        for model_id, model in self._models.items():
            if model.output_contract.output_type == "detection":
                detection.append(model_id)
        return detection
    
    def compute_actual_hash(self, model_id: str) -> str:
        """
        Compute the actual SHA256 hash of a model file.
        
        Args:
            model_id: Model ID to hash.
            
        Returns:
            SHA256 hash string.
            
        Raises:
            ModelMissingError: If the model file doesn't exist.
        """
        model_path = self.get_model_path(model_id)
        
        if not model_path.exists():
            model = self.get(model_id)
            raise ModelMissingError(
                model_id=model_id,
                expected_path=str(model_path),
            )
        
        return compute_sha256(model_path)
    
    def update_actual_hash(self, model_id: str) -> Optional[str]:
        """
        Update the actual_sha256 field for a model.
        
        Args:
            model_id: Model ID to update.
            
        Returns:
            The computed hash, or None if file doesn't exist.
        """
        model = self.get(model_id)
        model_path = self.get_model_path(model_id)
        
        if model_path.exists():
            actual_hash = compute_sha256(model_path)
            model.actual_sha256 = actual_hash
            return actual_hash
        
        return None
    
    def get_dataset_compatibility(self, model_id: str) -> DatasetCompatibility:
        """
        Get dataset compatibility metadata for a model.
        
        Args:
            model_id: Model ID.
            
        Returns:
            DatasetCompatibility instance.
        """
        model = self.get(model_id)
        
        # Try to use actual hash if available
        sha256 = model.actual_sha256 or model.expected_sha256
        
        return model.get_dataset_compatibility(sha256)
    
    def to_dict(self) -> Dict:
        """
        Export registry to dictionary for serialization.
        
        Returns:
            Dictionary representation of the registry.
        """
        return {
            "models_dir": str(self.get_models_dir()),
            "models": {
                model_id: model.model_dump()
                for model_id, model in self._models.items()
            },
        }
    
    @classmethod
    def reset(cls) -> None:
        """
        Reset the singleton instance (mainly for testing).
        """
        cls._instance = None
        cls._initialized = False


# Convenience function to get the registry instance
def get_model_registry() -> ModelRegistry:
    """
    Get the singleton ModelRegistry instance.
    
    Returns:
        ModelRegistry instance.
    """
    return ModelRegistry()
