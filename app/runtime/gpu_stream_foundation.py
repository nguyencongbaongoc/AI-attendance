"""
Phase 3.1 - Stream Foundation

Creates only the minimum abstraction needed for later phases.
Does NOT aggressively introduce asynchronous CUDA streams.
Correctness takes priority over overlap.
Does NOT change synchronization semantics.
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class CUDAStreamAbstraction:
    """
    Minimal CUDA stream abstraction.
    If current architecture exposes a CUDA stream, inspect it.
    Otherwise, provide a placeholder for future phases.
    """

    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self.stream_available = False
        self.stream_handle = None
        self.stream_name = f"stream_device_{device_index}_default"
        self._inspect_existing()

    def _inspect_existing(self):
        # Inspect whether a CUDA stream is already exposed by architecture
        # Phase 3.1: inspect only; do not change synchronization
        try:
            import torch
            if torch.cuda.is_available():
                # Check if current stream exists; do not create
                current_stream = torch.cuda.current_stream()
                device_idx = current_stream.device
                self.stream_available = True
                self.stream_handle = current_stream
            else:
                self.stream_available = False
        except Exception as exc:
            logger.debug("CUDA stream inspection failed: %s", exc)
            self.stream_available = False

    def get_stream_handle(self):
        return self.stream_handle

    def is_available(self) -> bool:
        return self.stream_available

    def get_report(self) -> Dict[str, Any]:
        return {
            "stream_available": self.stream_available,
            "device_index": self.device_index,
            "stream_name": self.stream_name,
            "synchronization_semantics_changed": False,
            "note": "Phase 3.1: no aggressive async stream introduction; correctness priority",
        }
