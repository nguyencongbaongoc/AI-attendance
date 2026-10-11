"""
Phase 20 — Model Contracts and Preprocessing Contracts.

Defines contracts for model preprocessing, input/output formats, and validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class ModelType(Enum):
    """Supported model types."""
    DETECTION = "detection"
    RECOGNITION = "recognition"
    LANDMARK = "landmark"
    REID = "reid"
    POSE = "pose"
    SEGMENTATION = "segmentation"
    CLASSIFICATION = "classification"
    UNKNOWN = "unknown"


class ModelFramework(Enum):
    """Supported model frameworks."""
    ONNX = "onnx"
    PYTORCH = "pytorch"
    TENSORRT = "tensorrt"
    OPENVINO = "openvino"
    TFLITE = "tflite"
    UNKNOWN = "unknown"


class ColorSpace(Enum):
    """Supported color spaces."""
    RGB = "rgb"
    BGR = "bgr"
    GRAY = "gray"
    YUV = "yuv"
    HSV = "hsv"
    UNKNOWN = "unknown"


class ChannelOrder(Enum):
    """Supported channel orders."""
    RGB = "rgb"
    BGR = "bgr"
    GRAY = "gray"
    RGBA = "rgba"
    BGRA = "bgra"
    CHW = "chw"
    HWC = "hwc"
    UNKNOWN = "unknown"


class ResizeMode(Enum):
    """Supported resize modes."""
    LETTERBOX = "letterbox"
    FIT = "fit"
    CROP = "crop"
    STRETCH = "stretch"
    NONE = "none"


class PaddingMode(Enum):
    """Supported padding modes."""
    CONSTANT = "constant"
    REFLECT = "reflect"
    REPLICATE = "replicate"
    SYMMETRIC = "symmetric"
    EDGE = "edge"


class PreprocessingVersion(Enum):
    """Supported preprocessing versions."""
    V1 = 1
    V2 = 2


class TensorLayout(Enum):
    """Supported tensor layouts."""
    NCHW = "nchw"
    NHWC = "nhwc"
    CHW = "chw"
    HWC = "hwc"
    UNKNOWN = "unknown"


@dataclass
class ModelPreprocessingContract:
    """
    Contract defining preprocessing requirements for a model.
    
    This ensures consistent preprocessing across the pipeline.
    """
    # Model identification
    model_id: str
    model_type: ModelType
    framework: ModelFramework
    
    # Input specifications (GPU preprocessing fields)
    color_space: ColorSpace = ColorSpace.RGB
    tensor_layout: TensorLayout = TensorLayout.NCHW
    dtype: str = "float32"
    resize_mode: ResizeMode = ResizeMode.LETTERBOX
    input_height: int = 640
    input_width: int = 640
    padding_value: int = 114
    normalization_scale: Optional[float] = 1.0 / 255.0
    normalization_mean: Optional[Tuple[float, float, float]] = (0.485, 0.456, 0.406)
    normalization_std: Optional[Tuple[float, float, float]] = (0.229, 0.224, 0.225)
    target_shape: Tuple[int, ...] = (1, 3, 640, 640)
    model_sha256: str = ""
    preprocessing_version: int = 1
    contract_version: int = 1
    
    # Legacy fields (for backward compatibility with CPU preprocessing)
    input_shape: Tuple[int, int, int] = (3, 640, 640)  # (C, H, W)
    input_dtype: str = "float32"
    input_range: Tuple[float, float] = (0.0, 1.0)
    input_format: str = "RGB"
    mean: Tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: Tuple[float, float, float] = (0.229, 0.224, 0.225)
    keep_aspect_ratio: bool = True
    
    # Output specifications
    output_names: List[str] = field(default_factory=list)
    output_shapes: Dict[str, Tuple[int, ...]] = field(default_factory=dict)
    
    # Post-processing
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.45
    max_detections: int = 100
    
    # Metadata
    version: str = "1.0"
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "model_id": self.model_id,
            "model_type": self.model_type.value,
            "framework": self.framework.value,
            "input_shape": list(self.input_shape),
            "input_dtype": self.input_dtype,
            "input_range": list(self.input_range),
            "input_format": self.input_format,
            "mean": list(self.mean),
            "std": list(self.std),
            "resize_mode": self.resize_mode,
            "keep_aspect_ratio": self.keep_aspect_ratio,
            "output_names": self.output_names,
            "output_shapes": {k: list(v) for k, v in self.output_shapes.items()},
            "confidence_threshold": self.confidence_threshold,
            "nms_threshold": self.nms_threshold,
            "max_detections": self.max_detections,
            "version": self.version,
            "description": self.description,
            "input_height": self.input_height,
            "input_width": self.input_width,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelPreprocessingContract":
        """Create from dictionary."""
        return cls(
            model_id=data["model_id"],
            model_type=ModelType(data.get("model_type", "unknown")),
            framework=ModelFramework(data.get("framework", "unknown")),
            input_shape=tuple(data.get("input_shape", [3, 640, 640])),
            input_dtype=data.get("input_dtype", "float32"),
            input_range=tuple(data.get("input_range", [0.0, 1.0])),
            input_format=data.get("input_format", "RGB"),
            mean=tuple(data.get("mean", [0.485, 0.456, 0.406])),
            std=tuple(data.get("std", [0.229, 0.224, 0.225])),
            resize_mode=data.get("resize_mode", "letterbox"),
            keep_aspect_ratio=data.get("keep_aspect_ratio", True),
            output_names=data.get("output_names", []),
            output_shapes={k: tuple(v) for k, v in data.get("output_shapes", {}).items()},
            confidence_threshold=data.get("confidence_threshold", 0.5),
            nms_threshold=data.get("nms_threshold", 0.45),
            max_detections=data.get("max_detections", 100),
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
        )


@dataclass
class ModelContract:
    """
    Complete model contract including preprocessing and runtime info.
    """
    # Model identification
    model_id: str
    model_type: ModelType
    framework: ModelFramework
    
    # File paths
    model_path: str
    config_path: Optional[str] = None
    
    # Preprocessing contract
    preprocessing: Optional[ModelPreprocessingContract] = None
    
    # Runtime configuration
    device: str = "cuda:0"
    batch_size: int = 1
    num_threads: int = 4
    
    # Performance
    warmup_runs: int = 3
    benchmark_runs: int = 100
    
    # Metadata
    version: str = "1.0"
    author: str = ""
    license: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "model_id": self.model_id,
            "model_type": self.model_type.value,
            "framework": self.framework.value,
            "model_path": self.model_path,
            "config_path": self.config_path,
            "preprocessing": self.preprocessing.to_dict() if self.preprocessing else None,
            "device": self.device,
            "batch_size": self.batch_size,
            "num_threads": self.num_threads,
            "warmup_runs": self.warmup_runs,
            "benchmark_runs": self.benchmark_runs,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelContract":
        """Create from dictionary."""
        preprocessing = None
        if data.get("preprocessing"):
            preprocessing = ModelPreprocessingContract.from_dict(data["preprocessing"])
        
        return cls(
            model_id=data["model_id"],
            model_type=ModelType(data.get("model_type", "unknown")),
            framework=ModelFramework(data.get("framework", "unknown")),
            model_path=data["model_path"],
            config_path=data.get("config_path"),
            preprocessing=preprocessing,
            device=data.get("device", "cuda:0"),
            batch_size=data.get("batch_size", 1),
            num_threads=data.get("num_threads", 4),
            warmup_runs=data.get("warmup_runs", 3),
            benchmark_runs=data.get("benchmark_runs", 100),
            version=data.get("version", "1.0"),
            author=data.get("author", ""),
            license=data.get("license", ""),
            tags=data.get("tags", []),
        )


# Registry of known model contracts
_MODEL_CONTRACTS: Dict[str, ModelContract] = {}


def register_model_contract(contract: ModelContract) -> None:
    """Register a model contract."""
    _MODEL_CONTRACTS[contract.model_id] = contract


def get_model_contract(model_id: str) -> Optional[ModelContract]:
    """Get a model contract by ID."""
    return _MODEL_CONTRACTS.get(model_id)


def list_model_contracts() -> List[ModelContract]:
    """List all registered model contracts."""
    return list(_MODEL_CONTRACTS.values())


def create_default_contracts() -> Dict[str, ModelContract]:
    """Create default model contracts for common models."""
    contracts = {}
    
    # SCRFD Face Detection
    scrfd_preprocessing = ModelPreprocessingContract(
        model_id="scrfd_10g",
        model_type=ModelType.DETECTION,
        framework=ModelFramework.ONNX,
        input_shape=(3, 640, 640),
        input_dtype="float32",
        input_range=(0.0, 1.0),
        input_format="RGB",
        mean=(0.485, 0.456, 0.406),
        std=(0.229, 0.224, 0.225),
        resize_mode="letterbox",
        keep_aspect_ratio=True,
        output_names=["output0", "output1", "output2"],
        confidence_threshold=0.5,
        nms_threshold=0.45,
        max_detections=100,
    )
    contracts["scrfd_10g"] = ModelContract(
        model_id="scrfd_10g",
        model_type=ModelType.DETECTION,
        framework=ModelFramework.ONNX,
        model_path="models/scrfd/scrfd_10g.onnx",
        preprocessing=scrfd_preprocessing,
    )
    
    # ArcFace Recognition
    arcface_preprocessing = ModelPreprocessingContract(
        model_id="arcface_r100",
        model_type=ModelType.RECOGNITION,
        framework=ModelFramework.ONNX,
        input_shape=(3, 112, 112),
        input_dtype="float32",
        input_range=(-1.0, 1.0),
        input_format="RGB",
        mean=(0.5, 0.5, 0.5),
        std=(0.5, 0.5, 0.5),
        resize_mode="crop",
        keep_aspect_ratio=True,
        output_names=["output"],
        confidence_threshold=0.0,
        nms_threshold=0.0,
        max_detections=1,
    )
    contracts["arcface_r100"] = ModelContract(
        model_id="arcface_r100",
        model_type=ModelType.RECOGNITION,
        framework=ModelFramework.ONNX,
        model_path="models/arcface/arcface_r100.onnx",
        preprocessing=arcface_preprocessing,
    )
    
    
    # SCRFD Face Detection (model_id="scrfd" for FaceDetector compatibility)
    scrfd_preprocessing = ModelPreprocessingContract(
        model_id="scrfd",
        model_type=ModelType.DETECTION,
        framework=ModelFramework.ONNX,
        input_shape=(3, 640, 640),
        input_dtype="float32",
        input_range=(0.0, 1.0),
        input_format="RGB",
        mean=(0.485, 0.456, 0.406),
        std=(0.229, 0.224, 0.225),
        resize_mode="letterbox",
        keep_aspect_ratio=True,
        output_names=["output0", "output1", "output2"],
        confidence_threshold=0.5,
        nms_threshold=0.45,
        max_detections=100,
    )
    contracts["scrfd"] = ModelContract(
        model_id="scrfd",
        model_type=ModelType.DETECTION,
        framework=ModelFramework.ONNX,
        model_path="models/scrfd/scrfd_10g.onnx",
        preprocessing=scrfd_preprocessing,
    )

# YOLO Person Detection
    yolo_person_preprocessing = ModelPreprocessingContract(
        model_id="yolo_person",
        model_type=ModelType.DETECTION,
        framework=ModelFramework.PYTORCH,
        input_shape=(3, 640, 640),
        input_dtype="float32",
        input_range=(0.0, 1.0),
        input_format="RGB",
        mean=(0.0, 0.0, 0.0),
        std=(1.0, 1.0, 1.0),
        resize_mode="letterbox",
        keep_aspect_ratio=True,
        output_names=["output0"],
        confidence_threshold=0.5,
        nms_threshold=0.45,
        max_detections=100,
    )
    contracts["yolo_person"] = ModelContract(
        model_id="yolo_person",
        model_type=ModelType.DETECTION,
        framework=ModelFramework.PYTORCH,
        model_path="models/yolo/yolo11n.pt",
        preprocessing=yolo_person_preprocessing,
    )
    
    # ReID Person Embedding
    reid_preprocessing = ModelPreprocessingContract(
        model_id="reid",
        model_type=ModelType.REID,
        framework=ModelFramework.ONNX,
        input_shape=(3, 256, 128),
        input_dtype="float32",
        input_range=(0.0, 1.0),
        input_format="RGB",
        mean=(0.485, 0.456, 0.406),
        std=(0.229, 0.224, 0.225),
        resize_mode="fit",
        keep_aspect_ratio=True,
        output_names=["output"],
        confidence_threshold=0.0,
        nms_threshold=0.0,
        max_detections=1,
    )
    contracts["reid"] = ModelContract(
        model_id="reid",
        model_type=ModelType.REID,
        framework=ModelFramework.ONNX,
        model_path="models/reid/resnet50_reid.onnx",
        preprocessing=reid_preprocessing,
    )
    
    # ArcFace alias for model registry compatibility
    arcface_preprocessing = ModelPreprocessingContract(
        model_id="arcface",
        model_type=ModelType.RECOGNITION,
        framework=ModelFramework.ONNX,
        input_shape=(3, 112, 112),
        input_dtype="float32",
        input_range=(-1.0, 1.0),
        input_format="RGB",
        mean=(0.5, 0.5, 0.5),
        std=(0.5, 0.5, 0.5),
        resize_mode="crop",
        keep_aspect_ratio=True,
        output_names=["output"],
        confidence_threshold=0.0,
        nms_threshold=0.0,
        max_detections=1,
    )
    contracts["arcface"] = ModelContract(
        model_id="arcface",
        model_type=ModelType.RECOGNITION,
        framework=ModelFramework.ONNX,
        model_path="models/arcface/glintr100.onnx",
        preprocessing=arcface_preprocessing,
    )
    
    # Register all
    for contract in contracts.values():
        register_model_contract(contract)
    
    return contracts


# Initialize default contracts on import
create_default_contracts()