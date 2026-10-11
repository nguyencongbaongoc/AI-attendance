"""
Model registry module for Windows native AI attendance system.

This module provides the single authoritative Model Registry for the entire project.
All pipelines (IMAGE → .npy, VIDEO → .npy, LIVE CAMERA → inference) must use this
same registry.

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

This module does NOT perform inference.
This module does NOT access cameras.
This module does NOT modify model files.
"""

from app.models.contracts import (
    # Enums
    ModelFormat,
    ModelProvider,
    HashStatus,
    ModelStatus,
    # Config classes
    PreprocessingConfig,
    OutputContract,
    ThresholdsConfig,
    ModelVersion,
    DatasetCompatibility,
    # Main model definition
    ModelDefinition,
)
from app.models.exceptions import (
    ModelError,
    ModelNotFoundError,
    ModelMissingError,
    ModelHashMismatchError,
    ModelNotVerifiedError,
)
from app.models.hashing import (
    compute_sha256,
    verify_sha256,
    compute_file_size,
    HashResult,
)
from app.models.registry import (
    ModelRegistry,
    get_model_registry,
    # Reference SHA256 values
    SCRFD_REFERENCE_SHA256,
    ARCFACE_REFERENCE_SHA256,
    LANDMARK_1K3D68_REFERENCE_SHA256,
    REID_REFERENCE_SHA256,
    YOLO11N_REFERENCE_SHA256,
    YOLO11N_POSE_REFERENCE_SHA256,
)


__all__ = [
    # Enums
    "ModelFormat",
    "ModelProvider",
    "HashStatus",
    "ModelStatus",
    # Config classes
    "PreprocessingConfig",
    "OutputContract",
    "ThresholdsConfig",
    "ModelVersion",
    "DatasetCompatibility",
    # Main model definition
    "ModelDefinition",
    # Exceptions
    "ModelError",
    "ModelNotFoundError",
    "ModelMissingError",
    "ModelHashMismatchError",
    "ModelNotVerifiedError",
    # Hashing
    "compute_sha256",
    "verify_sha256",
    "compute_file_size",
    "HashResult",
    # Registry
    "ModelRegistry",
    "get_model_registry",
    # Reference SHA256 values
    "SCRFD_REFERENCE_SHA256",
    "ARCFACE_REFERENCE_SHA256",
    "LANDMARK_1K3D68_REFERENCE_SHA256",
    "REID_REFERENCE_SHA256",
    "YOLO11N_REFERENCE_SHA256",
    "YOLO11N_POSE_REFERENCE_SHA256",
]