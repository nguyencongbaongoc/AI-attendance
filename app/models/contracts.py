"""
Model contracts for Windows native AI attendance system.

Defines the structured metadata for model definitions including:
- Model identity
- Model file information
- SHA256 hash
- Model format
- Input shape
- Output contract
- Preprocessing
- Normalization
- Alignment requirements
- Postprocessing
- Embedding dimension
- Thresholds
- Provider requirements
- Model version
- Dataset compatibility metadata

This module does NOT perform inference.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator


class ModelFormat(str, Enum):
    """Supported model formats."""
    
    ONNX = "onnx"
    PYTORCH = "pytorch"
    TENSORRT = "tensorrt"
    OPENVINO = "openvino"
    UNKNOWN = "unknown"


class ModelProvider(str, Enum):
    """Supported model runtime providers."""
    
    ONNXRUNTIME = "onnxruntime"
    ONNXRUNTIME_CUDA = "onnxruntime-cuda"
    PYTORCH = "pytorch"
    ULTRALYTICS = "ultralytics"
    TENSORRT = "tensorrt"
    OPENVINO = "openvino"
    UNKNOWN = "unknown"


class HashStatus(str, Enum):
    """Status of model file hash verification."""
    
    VERIFIED = "verified"  # File exists and hash matches expected
    MISSING = "missing"  # File does not exist
    HASH_MISMATCH = "hash_mismatch"  # File exists but hash does not match
    NOT_VERIFIED = "not_verified"  # File exists but no expected hash to compare
    NO_EXPECTED_HASH = "no_expected_hash"  # No expected hash recorded


class ModelStatus(str, Enum):
    """Overall status of a model in the registry."""
    
    AVAILABLE = "available"  # Model file exists and is verified
    MISSING = "missing"  # Model file does not exist
    CORRUPT = "corrupt"  # Model file exists but hash mismatch
    UNVERIFIED = "unverified"  # Model file exists but cannot verify


class PreprocessingConfig(BaseModel):
    """
    Preprocessing configuration for a model.
    
    Describes how to transform input data before inference.
    """
    
    # Input dimensions
    input_height: int = Field(..., description="Expected input height in pixels")
    input_width: int = Field(..., description="Expected input width in pixels")
    input_channels: int = Field(default=3, description="Number of input channels")
    
    # Resize behavior
    resize_mode: str = Field(
        default="fit",
        description="Resize mode: 'fit', 'crop', 'pad', 'stretch'"
    )
    preserve_aspect_ratio: bool = Field(
        default=True,
        description="Whether to preserve aspect ratio during resize"
    )
    
    # Padding configuration
    padding_value: int = Field(default=0, description="Value to use for padding")
    padding_mode: str = Field(
        default="constant",
        description="Padding mode: 'constant', 'reflect', 'edge'"
    )
    
    # Channel order
    channel_order: str = Field(
        default="RGB",
        description="Expected channel order: 'RGB', 'BGR', etc."
    )
    
    # Data type
    dtype: str = Field(default="float32", description="Expected input data type")
    
    # Normalization
    normalization_mean: Optional[List[float]] = Field(
        default=None,
        description="Mean values for normalization (per channel)"
    )
    normalization_std: Optional[List[float]] = Field(
        default=None,
        description="Std values for normalization (per channel)"
    )
    normalization_scale: Optional[float] = Field(
        default=None,
        description="Scale factor (e.g., 1/255.0)"
    )
    
    # Alignment requirements
    alignment: Optional[int] = Field(
        default=None,
        description="Alignment requirement in pixels (e.g., 32)"
    )
    
    # Additional preprocessing notes
    notes: Optional[str] = Field(
        default=None,
        description="Additional preprocessing notes or requirements"
    )
    
    # Verification status
    verified: bool = Field(
        default=False,
        description="Whether preprocessing config is verified from actual model"
    )
    
    def get_input_shape(self, batch_size: int = 1) -> Tuple[int, int, int, int]:
        """Get the full input shape as (batch, channels, height, width)."""
        return (batch_size, self.input_channels, self.input_height, self.input_width)
    
    def get_input_shape_nchw(self, batch_size: int = 1) -> Tuple[int, int, int, int]:
        """Get input shape in NCHW format."""
        return (batch_size, self.input_channels, self.input_height, self.input_width)
    
    def get_input_shape_nhwc(self, batch_size: int = 1) -> Tuple[int, int, int, int]:
        """Get input shape in NHWC format."""
        return (batch_size, self.input_height, self.input_width, self.input_channels)


class OutputContract(BaseModel):
    """
    Output contract for a model.
    
    Describes what the model outputs and how to interpret it.
    """
    
    # Output description
    output_type: str = Field(
        ...,
        description="Type of output: 'embedding', 'detection', 'landmarks', 'classification', 'pose'"
    )
    
    # Embedding-specific
    embedding_dimension: Optional[int] = Field(
        default=None,
        description="Dimension of embedding vector (if output_type is 'embedding')"
    )
    
    # Detection-specific
    num_classes: Optional[int] = Field(
        default=None,
        description="Number of detection classes (if output_type is 'detection')"
    )
    num_keypoints: Optional[int] = Field(
        default=None,
        description="Number of keypoints per detection (if applicable)"
    )
    
    # Landmark-specific
    num_landmarks: Optional[int] = Field(
        default=None,
        description="Number of landmarks (if output_type is 'landmarks')"
    )
    landmark_format: Optional[str] = Field(
        default=None,
        description="Format of landmarks: 'xy', 'xyz', 'normalized', etc."
    )
    
    # Pose-specific
    pose_keypoints: Optional[int] = Field(
        default=None,
        description="Number of pose keypoints (if output_type is 'pose')"
    )
    
    # Output tensor names (if known)
    output_names: Optional[List[str]] = Field(
        default=None,
        description="Names of output tensors (if known)"
    )
    
    # Output shapes (if known)
    output_shapes: Optional[List[Tuple[int, ...]]] = Field(
        default=None,
        description="Shapes of output tensors (if known)"
    )
    
    # Post-processing requirements
    postprocessing: Optional[str] = Field(
        default=None,
        description="Post-processing requirements (e.g., 'nms', 'softmax')"
    )
    
    # Verification status
    verified: bool = Field(
        default=False,
        description="Whether output contract is verified from actual model"
    )
    
    # Additional notes
    notes: Optional[str] = Field(
        default=None,
        description="Additional output contract notes"
    )


class ModelVersion(BaseModel):
    """
    Model version information.
    
    Used to track model identity and compatibility.
    """
    
    # Version identifier
    version: str = Field(
        default="1.0.0",
        description="Model version string"
    )
    
    # Model architecture
    architecture: Optional[str] = Field(
        default=None,
        description="Model architecture name (e.g., 'scrfd_10g', 'glintr100')"
    )
    
    # Training dataset
    training_dataset: Optional[str] = Field(
        default=None,
        description="Dataset used for training"
    )
    
    # Training date
    training_date: Optional[str] = Field(
        default=None,
        description="Date model was trained (ISO format)"
    )
    
    # Source
    source: Optional[str] = Field(
        default=None,
        description="Source of the model (e.g., 'insightface', 'ultralytics')"
    )
    
    # License
    license: Optional[str] = Field(
        default=None,
        description="License for the model"
    )
    
    # Contract version (for compatibility tracking)
    contract_version: str = Field(
        default="1.0",
        description="Version of the model contract schema"
    )
    
    # Preprocessing version
    preprocessing_version: str = Field(
        default="1.0",
        description="Version of preprocessing configuration"
    )


class DatasetCompatibility(BaseModel):
    """
    Dataset compatibility metadata.
    
    Used to ensure .npy artifacts are compatible with the model used for inference.
    
    Future .npy artifacts must record:
    - model_id
    - model_version
    - model_sha256
    - preprocessing_version
    - contract_version
    
    This prevents:
    - image .npy generated with model A
    - video .npy generated with model B
    - live inference using model C
    """
    
    # Model identifier
    model_id: str = Field(
        ...,
        description="Unique model identifier in the registry"
    )
    
    # Model version
    model_version: str = Field(
        ...,
        description="Model version string"
    )
    
    # Model SHA256 (first 16 chars for brevity)
    model_sha256_short: Optional[str] = Field(
        default=None,
        description="First 16 characters of model SHA256"
    )
    
    # Full SHA256
    model_sha256: Optional[str] = Field(
        default=None,
        description="Full SHA256 hash of model file"
    )
    
    # Preprocessing version
    preprocessing_version: str = Field(
        default="1.0",
        description="Version of preprocessing used"
    )
    
    # Contract version
    contract_version: str = Field(
        default="1.0",
        description="Version of model contract"
    )
    
    # Embedding dimension (for embedding models)
    embedding_dimension: Optional[int] = Field(
        default=None,
        description="Embedding dimension (if applicable)"
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "model_sha256_short": self.model_sha256_short,
            "model_sha256": self.model_sha256,
            "preprocessing_version": self.preprocessing_version,
            "contract_version": self.contract_version,
            "embedding_dimension": self.embedding_dimension,
        }
    
    def is_compatible_with(self, other: "DatasetCompatibility") -> bool:
        """
        Check if this compatibility info is compatible with another.
        
        Two artifacts are compatible if they use the same model and preprocessing.
        """
        return (
            self.model_id == other.model_id
            and self.model_version == other.model_version
            and self.preprocessing_version == other.preprocessing_version
            and self.contract_version == other.contract_version
        )


class ThresholdsConfig(BaseModel):
    """
    Threshold configuration for a model.
    
    Used for detection and recognition thresholds.
    """
    
    # Detection threshold
    confidence_threshold: Optional[float] = Field(
        default=None,
        description="Confidence threshold for detections"
    )
    
    # NMS threshold
    nms_threshold: Optional[float] = Field(
        default=None,
        description="Non-maximum suppression threshold"
    )
    
    # Recognition threshold
    recognition_threshold: Optional[float] = Field(
        default=None,
        description="Threshold for recognition/identification"
    )
    
    # Distance threshold (for face recognition)
    distance_threshold: Optional[float] = Field(
        default=None,
        description="Distance threshold for face recognition"
    )
    
    # Additional thresholds
    additional: Dict[str, float] = Field(
        default_factory=dict,
        description="Additional model-specific thresholds"
    )


class ModelDefinition(BaseModel):
    """
    Complete model definition for the registry.
    
    This is the single source of truth for all model metadata.
    """
    
    # Model identity
    model_id: str = Field(
        ...,
        description="Unique identifier for the model (e.g., 'scrfd', 'arcface')"
    )
    
    # Display name
    display_name: str = Field(
        ...,
        description="Human-readable name for the model"
    )
    
    # Description
    description: Optional[str] = Field(
        default=None,
        description="Description of the model's purpose"
    )
    
    # File information
    filename: str = Field(
        ...,
        description="Model filename (e.g., 'scrfd_10g_bnkps.onnx')"
    )
    
    # Model format
    format: ModelFormat = Field(
        ...,
        description="Model format (onnx, pytorch, etc.)"
    )
    
    # Expected SHA256 (reference hash from known evidence)
    expected_sha256: Optional[str] = Field(
        default=None,
        description="Expected SHA256 hash of the model file"
    )
    
    # Actual SHA256 (computed at runtime when file exists)
    actual_sha256: Optional[str] = Field(
        default=None,
        description="Actual SHA256 hash computed from the file"
    )
    
    # Model subdirectory (relative to models_dir)
    subdirectory: str = Field(
        ...,
        description="Subdirectory within models directory"
    )
    
    # Provider
    provider: ModelProvider = Field(
        ...,
        description="Runtime provider for the model"
    )
    
    # Preprocessing configuration
    preprocessing: PreprocessingConfig = Field(
        ...,
        description="Preprocessing configuration"
    )
    
    # Output contract
    output_contract: OutputContract = Field(
        ...,
        description="Output contract describing model outputs"
    )
    
    # Thresholds
    thresholds: Optional[ThresholdsConfig] = Field(
        default=None,
        description="Threshold configuration"
    )
    
    # Version information
    version: ModelVersion = Field(
        default_factory=ModelVersion,
        description="Model version information"
    )
    
    # Dataset compatibility
    dataset_compatibility: Optional[DatasetCompatibility] = Field(
        default=None,
        description="Dataset compatibility metadata"
    )
    
    # Tags for categorization
    tags: List[str] = Field(
        default_factory=list,
        description="Tags for categorizing the model"
    )
    
    # Whether this model is required for the system
    required: bool = Field(
        default=False,
        description="Whether this model is required for the system"
    )
    
    # Additional metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional model metadata"
    )
    
    def get_model_path(self, models_dir: str) -> str:
        """
        Get the full path to the model file.
        
        Args:
            models_dir: Root models directory path.
            
        Returns:
            Full path to the model file.
        """
        from pathlib import Path
        return str(Path(models_dir) / self.subdirectory / self.filename)
    
    def get_dataset_compatibility(self, sha256: Optional[str] = None) -> DatasetCompatibility:
        """
        Get dataset compatibility metadata for this model.
        
        Args:
            sha256: SHA256 hash to use (uses expected_sha256 if not provided).
            
        Returns:
            DatasetCompatibility instance.
        """
        return DatasetCompatibility(
            model_id=self.model_id,
            model_version=self.version.version,
            model_sha256=sha256 or self.expected_sha256,
            model_sha256_short=(sha256 or self.expected_sha256 or "")[:16] if (sha256 or self.expected_sha256) else None,
            preprocessing_version=self.version.preprocessing_version,
            contract_version=self.version.contract_version,
            embedding_dimension=self.output_contract.embedding_dimension,
        )
    
    model_config = {"use_enum_values": False}  # Keep enum values as enum instances
