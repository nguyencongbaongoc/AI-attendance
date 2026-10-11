"""
Phase H.10-C — GPU BGR to NV12 Converter.

GPU-accelerated BGR24 → NV12 color space conversion for direct GPU → NVENC
pipeline. This eliminates the full-frame BGR24 (24.9 MiB at 4K) CPU download
that was required by the H.10-B "direct" path.

Architecture:
    GPU BGR tensor (H, W, 3) uint8
        │
        ▼
    GPU BGR → YUV420 conversion (BT.601 matrix on GPU)
        │
        ▼
    GPU Y plane (H, W) + GPU UV plane (H/2, W/2, 2) interleaved
        │
        ▼
    GPU NV12 packed tensor (H*3/2, W) uint8
        │
        ▼
    CPU transfer of NV12 (12.5 MiB at 4K = 50% of BGR24)
        │
        ▼
    FFmpeg stdin pipe → h264_nvenc

The 50% size reduction of NV12 vs BGR24 is a structural improvement.
The conversion itself is GPU-accelerated via PyTorch tensor ops.

Per-camera isolation: each camera_id has its own converter instance.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


@dataclass
class BGRToNV12Config:
    """Configuration for GPU BGR→NV12 conversion."""
    gpu_device: int = 0
    # BT.601 coefficients (standard for SD/HD video)
    use_bt601: bool = True
    # Enable YUV range adjustment (16-235 for Y, 16-240 for UV)
    studio_range: bool = False


@dataclass
class BGRToNV12Metrics:
    """Metrics for GPU BGR→NV12 conversion."""
    frames_converted: int = 0
    total_time_ms: float = 0.0
    bytes_input: int = 0
    bytes_output: int = 0
    errors: int = 0


class GPUBGRToNV12Converter:
    """
    GPU-accelerated BGR24 → NV12 converter.

    Converts a GPU BGR tensor (H, W, 3) uint8 to NV12 packed format
    (H*3/2, W) uint8. The Y plane is full resolution; the UV plane
    is subsampled 2x and interleaved.

    Per-camera isolation: one converter per camera_id.
    Thread-safe via internal lock.
    """

    __slots__ = (
        "config",
        "metrics",
        "_lock",
        "_device",
        "_y_weight_r",
        "_y_weight_g",
        "_y_weight_b",
        "_u_weight_r",
        "_u_weight_g",
        "_u_weight_b",
        "_v_weight_r",
        "_v_weight_g",
        "_v_weight_b",
        "_y_offset",
        "_u_offset",
        "_v_offset",
        "_nv12_buffer",
        "_nv12_buffer_size",
        "_initialized",
    )

    def __init__(self, config: Optional[BGRToNV12Config] = None):
        self.config = config or BGRToNV12Config()
        self.metrics = BGRToNV12Metrics()
        self._lock = threading.Lock()
        self._device = None
        self._nv12_buffer: Optional[torch.Tensor] = None
        self._nv12_buffer_size: int = 0
        self._initialized = False
        self._init_gpu()

    def _init_gpu(self) -> None:
        """Initialize GPU resources and pre-compute conversion constants."""
        try:
            if not torch.cuda.is_available():
                logger.warning("GPUBGRToNV12Converter: CUDA not available")
                return

            self._device = torch.device(f"cuda:{self.config.gpu_device}")

            # BT.601 limited range coefficients
            # Y =  0.257*R + 0.504*G + 0.098*B + 16
            # U = -0.148*R - 0.291*G + 0.439*B + 128
            # V =  0.439*R - 0.368*G - 0.071*B + 128
            self._y_weight_r = torch.tensor(0.257, dtype=torch.float32, device=self._device)
            self._y_weight_g = torch.tensor(0.504, dtype=torch.float32, device=self._device)
            self._y_weight_b = torch.tensor(0.098, dtype=torch.float32, device=self._device)
            self._y_offset = torch.tensor(16.0, dtype=torch.float32, device=self._device)

            self._u_weight_r = torch.tensor(-0.148, dtype=torch.float32, device=self._device)
            self._u_weight_g = torch.tensor(-0.291, dtype=torch.float32, device=self._device)
            self._u_weight_b = torch.tensor(0.439, dtype=torch.float32, device=self._device)
            self._u_offset = torch.tensor(128.0, dtype=torch.float32, device=self._device)

            self._v_weight_r = torch.tensor(0.439, dtype=torch.float32, device=self._device)
            self._v_weight_g = torch.tensor(-0.368, dtype=torch.float32, device=self._device)
            self._v_weight_b = torch.tensor(-0.071, dtype=torch.float32, device=self._device)
            self._v_offset = torch.tensor(128.0, dtype=torch.float32, device=self._device)

            self._initialized = True
            logger.info(
                "GPUBGRToNV12Converter: initialized on %s (BT.601)",
                self._device,
            )
        except Exception as e:
            logger.error("GPUBGRToNV12Converter: init failed: %s", e)
            self._initialized = False

    def _ensure_nv12_buffer(self, size: int) -> torch.Tensor:
        """Ensure NV12 output buffer is large enough."""
        if self._nv12_buffer is None or self._nv12_buffer_size < size:
            if self._nv12_buffer is not None:
                del self._nv12_buffer
            self._nv12_buffer = torch.empty(size, dtype=torch.uint8, device=self._device)
            self._nv12_buffer_size = size
        return self._nv12_buffer

    def convert(
        self,
        bgr_gpu: torch.Tensor,
    ) -> Tuple[np.ndarray, int, int]:
        """
        Convert a GPU BGR tensor to NV12 packed format.

        Args:
            bgr_gpu: BGR tensor (H, W, 3) uint8 on GPU

        Returns:
            Tuple of (nv12_bytes, width, height) where nv12_bytes is
            a contiguous numpy uint8 array of size H*W*3/2 (NV12 packed:
            Y plane followed by interleaved UV plane).

        Raises:
            RuntimeError: if converter is not initialized or input is invalid
        """
        if not self._initialized:
            raise RuntimeError("GPUBGRToNV12Converter not initialized (CUDA unavailable?)")

        if bgr_gpu is None or bgr_gpu.numel() == 0:
            raise ValueError("Empty BGR tensor")

        if bgr_gpu.device != self._device:
            bgr_gpu = bgr_gpu.to(self._device, non_blocking=True)

        if bgr_gpu.dim() != 3 or bgr_gpu.shape[2] != 3:
            raise ValueError(f"Expected (H, W, 3) BGR tensor, got {bgr_gpu.shape}")

        t0 = time.perf_counter()

        H, W = bgr_gpu.shape[0], bgr_gpu.shape[1]

        with self._lock:
            try:
                # Split channels (BGR order in input)
                b = bgr_gpu[:, :, 0].float()
                g = bgr_gpu[:, :, 1].float()
                r = bgr_gpu[:, :, 2].float()

                # Y plane (full resolution)
                y = (
                    r * self._y_weight_r
                    + g * self._y_weight_g
                    + b * self._y_weight_b
                    + self._y_offset
                ).clamp(0, 255).to(torch.uint8)

                # U and V planes (full resolution first)
                u_full = (
                    r * self._u_weight_r
                    + g * self._u_weight_g
                    + b * self._u_weight_b
                    + self._u_offset
                ).clamp(0, 255).to(torch.uint8)

                v_full = (
                    r * self._v_weight_r
                    + g * self._v_weight_g
                    + b * self._v_weight_b
                    + self._v_offset
                ).clamp(0, 255).to(torch.uint8)

                # Subsample U and V by 2x (4:2:0 chroma subsampling)
                # Use average pooling for smooth subsampling
                u_sub = F.avg_pool2d(
                    u_full.float().unsqueeze(0).unsqueeze(0), 2
                ).squeeze(0).squeeze(0).to(torch.uint8)

                v_sub = F.avg_pool2d(
                    v_full.float().unsqueeze(0).unsqueeze(0), 2
                ).squeeze(0).squeeze(0).to(torch.uint8)

                # Interleave U and V into UV plane (H/2, W/2, 2)
                uv = torch.stack([u_sub, v_sub], dim=-1).reshape(-1)

                # Pack into NV12: Y then UV
                y_flat = y.reshape(-1)
                nv12_size = y_flat.numel() + uv.numel()
                nv12_gpu = self._ensure_nv12_buffer(nv12_size)
                nv12_gpu[:y_flat.numel()] = y_flat
                nv12_gpu[y_flat.numel():] = uv

                # Transfer to CPU as contiguous numpy array
                # This is the ONLY CPU transfer in the pipeline
                # Size: H*W*1.5 (vs H*W*3 for BGR24 = 50% reduction)
                nv12_cpu = nv12_gpu.cpu().numpy()
                assert nv12_cpu.flags['C_CONTIGUOUS']

                self.metrics.frames_converted += 1
                self.metrics.total_time_ms += (time.perf_counter() - t0) * 1000
                self.metrics.bytes_input = bgr_gpu.numel()
                self.metrics.bytes_output = nv12_cpu.nbytes

                return nv12_cpu, W, H

            except Exception as e:
                self.metrics.errors += 1
                logger.error("GPUBGRToNV12Converter: conversion failed: %s", e)
                raise

    def get_metrics(self) -> Dict[str, Any]:
        """Get converter metrics."""
        m = self.metrics
        avg_ms = m.total_time_ms / m.frames_converted if m.frames_converted > 0 else 0.0
        return {
            "frames_converted": m.frames_converted,
            "avg_time_ms": avg_ms,
            "bytes_input": m.bytes_input,
            "bytes_output": m.bytes_output,
            "errors": m.errors,
            "initialized": self._initialized,
            "gpu_device": str(self._device) if self._device else "none",
        }

    def reset(self) -> None:
        """Reset metrics and release buffers."""
        self.metrics = BGRToNV12Metrics()
        with self._lock:
            if self._nv12_buffer is not None:
                del self._nv12_buffer
                self._nv12_buffer = None
                self._nv12_buffer_size = 0


_CONVERTERS: Dict[str, GPUBGRToNV12Converter] = {}
_CONVERTERS_LOCK = threading.Lock()


def get_bgr_to_nv12_converter(
    camera_id: str,
    config: Optional[BGRToNV12Config] = None,
) -> GPUBGRToNV12Converter:
    """Get or create a per-camera BGR→NV12 converter."""
    global _CONVERTERS
    with _CONVERTERS_LOCK:
        if camera_id not in _CONVERTERS:
            _CONVERTERS[camera_id] = GPUBGRToNV12Converter(config)
        return _CONVERTERS[camera_id]


def reset_bgr_to_nv12_converters() -> None:
    """Reset all converters (for tests)."""
    global _CONVERTERS
    with _CONVERTERS_LOCK:
        for converter in _CONVERTERS.values():
            converter.reset()
        _CONVERTERS.clear()
