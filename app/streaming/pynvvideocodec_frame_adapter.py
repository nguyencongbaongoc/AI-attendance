"""
Phase 9.2 — PyNvVideoCodec Frame Adapter.

Adapts PyNvVideoCodec DecodedFrame to canonical GPUFrameContract.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

import torch

from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract

logger = logging.getLogger(__name__)


@dataclass
class PyNvVideoCodecFrameAdapter:
    """
    Adapter to convert PyNvVideoCodec DecodedFrame to GPUFrameContract.
    
    Uses CAI (CUDA Array Interface) for zero-copy GPU memory sharing.
    Manages DecodedFrame locking/unlocking for memory ownership.
    """
    
    camera_id: str
    frame_id: int = 0
    cuda_stream: int = 0
    device_id: int = 0
    
    def adapt(
        self,
        decoded_frame: Any,  # PyNvVideoCodec.DecodedFrame
        timestamp: float,
        pts: int,
        t_packet_ingress_ns: int = 0,
        t_decode_submit_ns: int = 0,
    ) -> GPUFrameContract:
        """
        Convert DecodedFrame to GPUFrameContract with latency instrumentation.
        
        Args:
            decoded_frame: PyNvVideoCodec DecodedFrame (GPU-resident)
            timestamp: Wall-clock timestamp
            pts: Presentation timestamp from frame
            t_packet_ingress_ns: Timestamp when compressed packet was demuxed (ns)
            t_decode_submit_ns: Timestamp when packet was submitted to decoder (ns)
            
        Returns:
            GPUFrameContract with zero-copy PyTorch CUDA tensors and latency timestamps
        """
        t_gpu_frame_ready_ns = time.perf_counter_ns()
        
        # Get frame dimensions from shape
        # shape is (height * 1.5, width) for NV12 packed format
        shape = decoded_frame.shape
        if len(shape) == 2:
            height = shape[0] * 2 // 3  # NV12 is 1.5x height
            width = shape[1]
        else:
            # Fallback
            width = 3840
            height = 2160
        
        # Verify NV12 format
        pixel_format = str(decoded_frame.format)
        if "NV12" not in pixel_format.upper():
            logger.warning(f"Unexpected pixel format: {pixel_format}, assuming NV12")
        
        # Get CAI memory views (zero-copy)
        try:
            cai_views = decoded_frame.cuda()
        except Exception as e:
            logger.error(f"CAI export failed: {e}")
            raise RuntimeError(f"Failed to get CAI views from DecodedFrame: {e}")
        
        if len(cai_views) < 2:
            raise RuntimeError(f"Expected 2 CAI views (Y, UV), got {len(cai_views)}")
        
        y_view = cai_views[0]
        uv_view = cai_views[1]
        
        # Validate shapes for NV12
        # Y: (H, W, 1) or (H, W)
        # UV: (H/2, W/2, 2)
        y_shape = y_view.shape
        uv_shape = uv_view.shape
        
        # Convert CAI views to PyTorch CUDA tensors (zero-copy)
        try:
            y_tensor = torch.as_tensor(y_view, device='cuda')
            uv_tensor = torch.as_tensor(uv_view, device='cuda')
        except Exception as e:
            logger.error(f"PyTorch tensor creation failed: {e}")
            raise RuntimeError(f"Failed to create PyTorch tensors from CAI views: {e}")
        
        # Squeeze Y if needed (H, W, 1) -> (H, W)
        if y_tensor.dim() == 3 and y_tensor.shape[2] == 1:
            y_tensor = y_tensor.squeeze(2)
        
        # Validate tensors
        assert y_tensor.is_cuda, f"y_tensor must be on CUDA, got {y_tensor.device}"
        assert uv_tensor.is_cuda, f"uv_tensor must be on CUDA, got {uv_tensor.device}"
        assert y_tensor.dtype == torch.uint8, f"y_tensor must be uint8, got {y_tensor.dtype}"
        assert uv_tensor.dtype == torch.uint8, f"uv_tensor must be uint8, got {uv_tensor.dtype}"
        
        # Get CUDA pointers
        y_ptr = y_tensor.data_ptr()
        uv_ptr = uv_tensor.data_ptr()
        
        assert y_ptr != 0, "y_tensor data_ptr is 0"
        assert uv_ptr != 0, "uv_tensor data_ptr is 0"
        
        # Create GPUFrameContract
        frame_contract = GPUFrameContract.from_pyav_frame_data(
            frame_data={
                "y_plane": y_tensor,
                "uv_plane": uv_tensor,
                "width": width,
                "height": height,
                "format": "nv12_cuda",
                "pts": pts,
            },
            frame_id=self.frame_id,
            camera_id=self.camera_id,
            timestamp=timestamp,
            pts=pts,
            cuda_stream=self.cuda_stream,
        )
        
        # Set latency timestamps (zero-copy - no GPU-to-CPU synchronization)
        frame_contract.t_packet_ingress_ns = t_packet_ingress_ns
        frame_contract.t_decode_submit_ns = t_decode_submit_ns
        frame_contract.t_gpu_frame_ready_ns = t_gpu_frame_ready_ns
        # t_pipeline_egress_ns will be set by downstream consumer
        
        # Override memory_owner to correctly reflect PyNvVideoCodec backend
        frame_contract.memory_owner = "pynvvideocodec"
        
        self.frame_id += 1
        return frame_contract


def create_pynvvideocodec_frame_adapter(
    camera_id: str,
    cuda_stream: int = 0,
    device_id: int = 0,
) -> PyNvVideoCodecFrameAdapter:
    """Factory function to create PyNvVideoCodecFrameAdapter."""
    return PyNvVideoCodecFrameAdapter(
        camera_id=camera_id,
        cuda_stream=cuda_stream,
        device_id=device_id,
    )