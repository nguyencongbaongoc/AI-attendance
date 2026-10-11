"""
AI Model Contracts - V2 GPU-first video pipeline.

Defines input/output contracts for all AI models to ensure
consistent GPU tensor formats and prevent silent failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Optional, List, Dict, Any
from enum import Enum


class ModelPrecision(str, Enum):
    FP32 = "fp32"
    FP16 = "fp16"
    INT8 = "int8"


@dataclass(frozen=True)
class ModelInputContract:
    """Defines expected input tensor format for a model."""
    name: str
    shape: Tuple[int, ...]  # e.g., (1, 3, 640, 640) for NCHW
    dtype: str = "float32"  # float32, float16, uint8
    layout: str = "NCHW"  # NCHW, NHWC
    device: str = "cuda"
    value_range: Tuple[float, float] = (0.0, 1.0)  # Expected normalized range
    mean: Optional[Tuple[float, ...]] = None  # For normalization
    std: Optional[Tuple[float, ...]] = None
    
    def validate(self, tensor: Any) -> Tuple[bool, str]:
        """Validate tensor matches contract."""
        import torch
        
        if not isinstance(tensor, torch.Tensor):
            return False, f"Expected torch.Tensor, got {type(tensor)}"
        
        if tensor.device.type != self.device:
            return False, f"Expected device {self.device}, got {tensor.device}"
        
        if tensor.dtype != getattr(torch, self.dtype):
            return False, f"Expected dtype {self.dtype}, got {tensor.dtype}"
        
        if tensor.shape != self.shape:
            # Allow batch dimension flexibility
            if len(tensor.shape) == len(self.shape) and tensor.shape[1:] == self.shape[1:]:
                pass  # Batch size can vary
            else:
                return False, f"Expected shape {self.shape}, got {tensor.shape}"
        
        return True, "OK"


@dataclass(frozen=True)
class ModelOutputContract:
    """Defines expected output tensor format for a model."""
    name: str
    shape: Tuple[int, ...]  # e.g., (1, 512) for embeddings
    dtype: str = "float32"
    layout: str = "NCHW"
    device: str = "cuda"
    postprocess: Optional[str] = None  # e.g., "l2_normalize", "sigmoid", "softmax"
    
    def validate(self, tensor: Any) -> Tuple[bool, str]:
        import torch
        
        if not isinstance(tensor, torch.Tensor):
            return False, f"Expected torch.Tensor, got {type(tensor)}"
        
        if tensor.device.type != self.device:
            return False, f"Expected device {self.device}, got {tensor.device}"
        
        if tensor.dtype != getattr(torch, self.dtype):
            return False, f"Expected dtype {self.dtype}, got {tensor.dtype}"
        
        if tensor.shape != self.shape:
            if len(tensor.shape) == len(self.shape) and tensor.shape[1:] == self.shape[1:]:
                pass
            else:
                return False, f"Expected shape {self.shape}, got {tensor.shape}"
        
        return True, "OK"


# === Predefined Model Contracts ===

SCRFD_INPUT = ModelInputContract(
    name="scrfd_input",
    shape=(1, 3, 640, 640),
    dtype="float32",
    layout="NCHW",
    device="cuda",
    value_range=(0.0, 1.0),
    mean=(0.485, 0.456, 0.406),
    std=(0.229, 0.224, 0.225),
)

SCRFD_OUTPUTS = [
    ModelOutputContract(name="score_8", shape=(1, 2, 80, 80), dtype="float32", device="cuda"),
    ModelOutputContract(name="score_16", shape=(1, 2, 40, 40), dtype="float32", device="cuda"),
    ModelOutputContract(name="score_32", shape=(1, 2, 20, 20), dtype="float32", device="cuda"),
    ModelOutputContract(name="bbox_8", shape=(1, 2, 80, 80, 4), dtype="float32", device="cuda"),
    ModelOutputContract(name="bbox_16", shape=(1, 2, 40, 40, 4), dtype="float32", device="cuda"),
    ModelOutputContract(name="bbox_32", shape=(1, 2, 20, 20, 4), dtype="float32", device="cuda"),
    ModelOutputContract(name="kps_8", shape=(1, 2, 80, 80, 10), dtype="float32", device="cuda"),
    ModelOutputContract(name="kps_16", shape=(1, 2, 40, 40, 10), dtype="float32", device="cuda"),
    ModelOutputContract(name="kps_32", shape=(1, 2, 20, 20, 10), dtype="float32", device="cuda"),
]

ARCFACE_INPUT = ModelInputContract(
    name="arcface_input",
    shape=(1, 3, 112, 112),
    dtype="float32",
    layout="NCHW",
    device="cuda",
    value_range=(-1.0, 1.0),  # After normalization: (x - 127.5) / 128.0
    mean=(127.5, 127.5, 127.5),
    std=(128.0, 128.0, 128.0),
)

ARCFACE_OUTPUT = ModelOutputContract(
    name="arcface_output",
    shape=(1, 512),
    dtype="float32",
    device="cuda",
    postprocess="l2_normalize",
)

YOLO_INPUT = ModelInputContract(
    name="yolo_input",
    shape=(1, 3, 640, 640),
    dtype="float32",
    layout="NCHW",
    device="cuda",
    value_range=(0.0, 1.0),
)

# YOLO output varies by model version - define as flexible
YOLO_OUTPUT = ModelOutputContract(
    name="yolo_output",
    shape=(1, -1, -1),  # Dynamic: (batch, num_boxes, 85) for YOLOv8
    dtype="float32",
    device="cuda",
)

REID_INPUT = ModelInputContract(
    name="reid_input",
    shape=(1, 3, 256, 128),  # Typical ReID input
    dtype="float32",
    layout="NCHW",
    device="cuda",
    value_range=(0.0, 1.0),
)

REID_OUTPUT = ModelOutputContract(
    name="reid_output",
    shape=(1, 2048),  # ResNet50 ReID embedding
    dtype="float32",
    device="cuda",
    postprocess="l2_normalize",
)


class ModelContractRegistry:
    """Registry of model contracts for validation."""
    
    _contracts: Dict[str, Dict[str, Any]] = {
        "scrfd": {
            "input": SCRFD_INPUT,
            "outputs": SCRFD_OUTPUTS,
        },
        "arcface": {
            "input": ARCFACE_INPUT,
            "output": ARCFACE_OUTPUT,
        },
        "yolo": {
            "input": YOLO_INPUT,
            "output": YOLO_OUTPUT,
        },
        "reid": {
            "input": REID_INPUT,
            "output": REID_OUTPUT,
        },
    }
    
    @classmethod
    def get(cls, model_name: str) -> Dict[str, Any]:
        """Get contracts for a model."""
        if model_name not in cls._contracts:
            raise ValueError(f"Unknown model: {model_name}. Available: {list(cls._contracts.keys())}")
        return cls._contracts[model_name]
    
    @classmethod
    def validate_input(cls, model_name: str, tensor: Any) -> Tuple[bool, str]:
        """Validate input tensor for a model."""
        contracts = cls.get(model_name)
        return contracts["input"].validate(tensor)
    
    @classmethod
    def validate_output(cls, model_name: str, tensor: Any, output_name: str = "default") -> Tuple[bool, str]:
        """Validate output tensor for a model."""
        contracts = cls.get(model_name)
        
        if "outputs" in contracts:
            # Multiple outputs - find by name
            for out in contracts["outputs"]:
                if out.name == output_name:
                    return out.validate(tensor)
            return False, f"Output {output_name} not found in model {model_name}"
        else:
            return contracts["output"].validate(tensor)


if __name__ == "__main__":
    import torch
    
    # Test SCRFD contract
    test_tensor = torch.randn(1, 3, 640, 640, device="cuda", dtype=torch.float32)
    valid, msg = ModelContractRegistry.validate_input("scrfd", test_tensor)
    print(f"SCRFD input validation: {valid} - {msg}")
    
    # Test ArcFace contract
    test_tensor = torch.randn(1, 3, 112, 112, device="cuda", dtype=torch.float32)
    valid, msg = ModelContractRegistry.validate_input("arcface", test_tensor)
    print(f"ArcFace input validation: {valid} - {msg}")
    
    # Test output validation
    test_output = torch.randn(1, 512, device="cuda", dtype=torch.float32)
    valid, msg = ModelContractRegistry.validate_output("arcface", test_output)
    print(f"ArcFace output validation: {valid} - {msg}")
    
    print("Model contracts validated!")