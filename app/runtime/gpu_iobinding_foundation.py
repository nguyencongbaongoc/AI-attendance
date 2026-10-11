"""
Phase 3.1 - I/O Binding Foundation

Inspect existing ONNX Runtime I/O Binding implementation.
Determine whether current code actually binds GPU input/output.
Create clean foundation/API for future I/O Binding usage.
Phase 3.1 may add helpers/interfaces but must NOT force all models
onto I/O Binding yet. Actual migration in later phases.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class IOBindingCapability:
    """
    Reports whether I/O binding is capable for the current runtime.
    Does not claim GPU execution merely from provider registration.
    """

    def __init__(self):
        self.iobinding_available = False
        self.ortvalue_available = False
        self.gpu_input_bindable = False
        self.gpu_output_bindable = False
        self.hidden_cpu_copy_risk = "POSSIBLE"  # Not proven safe yet
        self.current_code_analysis = {}

    def inspect_current_code(self, module_path: Optional[str] = None) -> Dict[str, Any]:
        # Inspect the existing code (gpu_inference.py, etc.)
        analysis = {
            "iobinding_api_exists": False,
            "ortvalue_exists": False,
            "uses_ortvalue_outputs": False,
            "uses_cuda_io_binding": False,
            "hidden_cpu_copy_risk": "POSSIBLE",
        }
        # Check runtime capabilities only
        try:
            import onnxruntime as ort
            analysis["iobinding_api_exists"] = hasattr(ort, "IOBinding")
            analysis["ortvalue_exists"] = hasattr(ort, "OrtValue")
        except Exception:
            pass
        self.current_code_analysis = analysis
        return analysis

    def detect_capabilities(self) -> Dict[str, Any]:
        try:
            import onnxruntime as ort
            self.iobinding_available = hasattr(ort, "IOBinding")
            self.ortvalue_available = hasattr(ort, "OrtValue")
            # For Phase 3.1, capability is reported; actual GPU binding
            # is NOT forced. Actual execution assignment remains UNPROVEN.
            self.gpu_input_bindable = self.iobinding_available and self.ortvalue_available
            self.gpu_output_bindable = self.gpu_input_bindable
        except Exception as exc:
            logger.debug("I/O Binding capability detection failed: %s", exc)
            self.iobinding_available = False
            self.ortvalue_available = False
            self.gpu_input_bindable = False
            self.gpu_output_bindable = False
        return self.get_report()

    def get_report(self) -> Dict[str, Any]:
        return {
            "iobinding_available": self.iobinding_available,
            "ortvalue_available": self.ortvalue_available,
            "gpu_input_bindable": self.gpu_input_bindable,
            "gpu_output_bindable": self.gpu_output_bindable,
            "hidden_cpu_copy_risk": self.hidden_cpu_copy_risk,
            "cuda_memory_bindable": "UNPROVEN",  # Not verified at node level
            "current_code_analysis": self.current_code_analysis,
        }
