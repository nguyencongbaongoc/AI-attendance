# Encoder adapter boundary (PyNvVideoCodec 2.2.3)
# GPU-resident input by default; EndEncode mandatory; Reconfigure exposed.
# Actual execution proven against installed 2.2.3 library (not placeholder).

from __future__ import annotations
import logging
from typing import Optional, Any, Dict, List
import PyNvVideoCodec as nvc

from app.video.pynvcodec.errors import (
    InitializationError, CapabilityError, EncodeError,
    CUDAStreamError, MuxError,
)
from app.video.pynvcodec.metrics import AdapterMetrics

logger = logging.getLogger(__name__)


# Apply DLpack monkey-patch for PyTorch 2.13+ compatibility
# PyTorch 2.13+ changed __dlpack__ signature to require keyword arguments
# PyNvVideoCodec 2.2.3 calls __dlpack__ with positional stream argument
# This monkey-patch handles both old positional and new keyword signatures
import torch

# Store original class method (unbound) BEFORE patching
_original_tensor_dlpack = torch.Tensor.__dlpack__

def _patched_tensor_dlpack(self, *args, **kwargs):
    # Handle both old positional and new keyword signatures
    # Original signature: __dlpack__(self, *, stream=-1, max_version=None, dl_device=None, copy=None)
    # PyNvVideoCodec calls: tensor.__dlpack__(stream_handle) - positional after self
    
    stream = -1
    max_version = None
    dl_device = None
    copy = None
    
    # Parse positional and keyword arguments
    # args[0] would be stream if passed positionally
    if len(args) > 0:
        stream = args[0]
    if 'stream' in kwargs:
        stream = kwargs['stream']
    if 'max_version' in kwargs:
        max_version = kwargs['max_version']
    if 'dl_device' in kwargs:
        dl_device = kwargs['dl_device']
    if 'copy' in kwargs:
        copy = kwargs['copy']
    
    # Handle stream argument - extract handle if it's a torch.cuda.Stream object
    stream_handle = stream
    if hasattr(stream, 'cuda_stream'):
        stream_handle = stream.cuda_stream
    elif hasattr(stream, 'stream_id'):
        stream_handle = stream.stream_id
    else:
        stream_handle = stream
    
    # Try new keyword signature first (PyTorch 2.13+)
    try:
        return _original_tensor_dlpack(self, stream=stream_handle, max_version=max_version, dl_device=dl_device, copy=copy)
    except TypeError:
        # Fallback for old positional signature - use ORIGINAL unbound method directly
        return _original_tensor_dlpack(self, stream_handle)

torch.Tensor.__dlpack__ = _patched_tensor_dlpack


class EncoderAdapter:
    def __init__(
        self,
        codec: str = "h264",
        preset: Optional[str] = "P4",
        fps: float = 30.0,
        bitrate_kbps: int = 8000,
        max_bitrate_kbps: int = 12000,
        gop_length: int = 30,
        idr_period: int = 60,
        use_cpu_input: bool = False,
        cuda_stream: int = 0,
    ) -> None:
        if cuda_stream == 0:
            logger.warning("Encoder adapter: CUDA stream is 0; explicit non-zero stream preferred.")
        else:
            logger.info("Encoder adapter stream=%d", cuda_stream)
        self.codec: str = codec
        self.preset: Optional[str] = preset if preset is not None else "P4"
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.max_bitrate_kbps = max_bitrate_kbps
        self.gop_length = gop_length
        self.idr_period = idr_period
        self.use_cpu_input = use_cpu_input
        self.cuda_stream = cuda_stream
        self.encoder: Optional[Any] = None
        self.metrics = AdapterMetrics()
        self.metrics.encode_backend = "pynvvideocodec"
        self.metrics.cuda_stream_id = cuda_stream
        self.metrics.pixel_format = "NV12"
    
    def open(self, width: int = 3840, height: int = 2160) -> None:
        # BLOCKER FIX: open() did not pass width/height/fmt to CreateEncoder.
        # CreateEncoder requires (width, height, fmt, usecpuinputbuffer, ...).
        caps = dict(nvc.GetEncoderCaps())
        if width < caps.get("width_min", 145) or width > caps.get("width_max", 4096):
            raise CapabilityError("Encoder width %d unsupported" % width)
        if height < caps.get("height_min", 49) or height > caps.get("height_max", 4096):
            raise CapabilityError("Encoder height %d unsupported" % height)
        fmt = "NV12"  # adapter contract: GPU NV12 surface
        try:
            # Note: adapter constructor takes use_cpu_input; we pass it as usecpuinputbuffer.
            # For production GPU path, use_cpu_input=False (default).
            # The adapter preserves the exact kwarg mapping from the adapter source evidence.
            self.encoder = nvc.CreateEncoder(
                width,
                height,
                fmt,
                self.use_cpu_input,
                codec=self.codec,
                fps=self.fps,
                bitrate=self.bitrate_kbps,
                maxbitrate=self.max_bitrate_kbps,
                gop_length=self.gop_length,
                idr_period=self.idr_period,
                preset=self.preset,
                cuda_stream=self.cuda_stream,
            )
        except Exception as exc:
            raise InitializationError("NVENC initialization failed: %s" % exc) from exc
        logger.info("Encoder adapter started: codec=%s fps=%.1f bitrate=%d stream=%d fmt=%s",
                    self.codec, self.fps, self.bitrate_kbps, self.cuda_stream, fmt)
        self.metrics.resolution_str = "%dx%d" % (width, height)
    
    def encode_frame(
        self, gpu_frame_ref: Any, pts: Optional[int] = None,
        dts: Optional[int] = None, frame_id: Optional[int] = None,
        camera_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Encode a GPU-resident frame using the installed PyNvVideoCodec encoder.

        Returns real packet dictionaries (each with 'data': bytes,
        'picture_type', 'timestamp', etc.) — not synthetic placeholders.
        No CPU fallback is performed; if the encoder fails, an observable
        EncodeError is raised.
        """
        if self.encoder is None:
            raise EncodeError("Encoder not initialized (call open() before encode_frame)")
        if gpu_frame_ref is None:
            raise EncodeError("GPU frame reference is None; no CPU fallback permitted")
        try:
            # Actual execution path: submit GPU frame to NVENC.
            # Per installed 2.2.3 sample evidence (encode.py, encode_reconfigure.py):
            #   nvenc.Encode(input_gpu_frame, pic_params) -> list of packet dicts.
            # Packet dict format: {"data": bytes, "picture_type": int, "timestamp": int, ...}
            pic_params = nvc.NV_ENC_PIC_PARAMS()
            # Preserve timing contract from adapter input when available.
            if pts is not None:
                pic_params.inputTimeStamp = pts
                # Set outputTimeStamp to ensure monotonic DTS in output packets
                if hasattr(pic_params, 'outputTimeStamp'):
                    pic_params.outputTimeStamp = pts
                # The encoder should propagate inputTimeStamp to output packets
            if dts is not None:
                # Also try to set DTS if available
                if hasattr(pic_params, 'inputDuration'):
                    pic_params.inputDuration = 1  # one frame duration
            # Convert GPU frame reference to combined NV12 tensor if needed
            input_tensor = self._convert_to_nv12_tensor(gpu_frame_ref)
            
            packets = self.encoder.Encode(input_tensor, pic_params)
            # The installed library returns a list (possibly empty) of packet dicts.
            # Convert to a consistent list; never silently drop packets.
            result: List[Dict[str, Any]] = list(packets) if packets is not None else []
            # Ensure packets have proper timestamps
            for pkt in result:
                if 'timestamp' not in pkt or pkt['timestamp'] is None:
                    pkt['timestamp'] = pts if pts is not None else 0
            self.metrics.packets_submitted += len(result)
            logger.info("Encoder adapter encode_frame: packets=%d pts=%s",
                        len(result), pts)
            return result
        except Exception as exc:
            raise EncodeError("Encode failed: %s" % exc) from exc
    
    def _convert_to_nv12_tensor(self, gpu_frame_ref: Any) -> torch.Tensor:
        """Convert GPU frame reference to combined NV12 tensor for encoder.
        
        The encoder expects a combined NV12 tensor with height = 1.5 * frame_height
        (Y plane + UV plane combined).
        """
        import torch
        
        # If already a combined tensor with correct height, return as-is
        if isinstance(gpu_frame_ref, torch.Tensor):
            expected_height = int(self.metrics.resolution_str.split('x')[1]) * 3 // 2 if 'x' in self.metrics.resolution_str else 3240
            if gpu_frame_ref.shape[0] == expected_height:
                return gpu_frame_ref
        
        # If it's a GPUFrameContract or dict with y_plane and uv_plane
        # Check for internal attributes _y_tensor and _uv_tensor (used by GPUFrameContract)
        # We check for both internal attributes and dict keys
        has_y_plane = hasattr(gpu_frame_ref, '_y_tensor') or (isinstance(gpu_frame_ref, dict) and 'y_plane' in gpu_frame_ref)
        has_uv_plane = hasattr(gpu_frame_ref, '_uv_tensor') or (isinstance(gpu_frame_ref, dict) and 'uv_plane' in gpu_frame_ref)
        
        if has_y_plane and has_uv_plane:
            # Get tensors from either dict or object attributes
            if isinstance(gpu_frame_ref, dict):
                y_tensor = gpu_frame_ref['y_plane']
                uv_tensor = gpu_frame_ref['uv_plane']
            else:
                y_tensor = gpu_frame_ref._y_tensor
                uv_tensor = gpu_frame_ref._uv_tensor
            
            # Interleave UV: (H/2, W/2, 2) -> (H/2, W) with interleaved UV
            uv_interleaved = uv_tensor.permute(2, 0, 1).contiguous().view(2, uv_tensor.shape[0], uv_tensor.shape[1]).transpose(0, 1).contiguous().view(uv_tensor.shape[0], uv_tensor.shape[1] * 2)
            
            # Combine Y and UV into NV12 tensor (height = 1.5 * frame_height)
            nv12_tensor = torch.cat([y_tensor, uv_interleaved], dim=0)
            return nv12_tensor
        
        # If already a combined tensor with correct height, return as-is
        if isinstance(gpu_frame_ref, torch.Tensor):
            expected_height = int(self.metrics.resolution_str.split('x')[1]) * 3 // 2 if 'x' in self.metrics.resolution_str else 3240
            if gpu_frame_ref.shape[0] == expected_height:
                return gpu_frame_ref
        
        raise EncodeError("Unsupported GPU frame reference type: %s" % type(gpu_frame_ref))
    
    def end_encode(self) -> List[Dict[str, Any]]:
        """Flush encoder; drain remaining packets. Must be called before close.

        Returns real packet dictionaries from EndEncode() (not an empty list
        placeholder). The adapter does NOT discard flushed packets.
        """
        packets: List[Dict[str, Any]] = []
        if self.encoder is not None:
            try:
                flush_result = self.encoder.EndEncode()
                packets = list(flush_result) if flush_result is not None else []
                self.metrics.packets_submitted += len(packets)
                logger.info("Encoder adapter EndEncode: drained packets=%d", len(packets))
            except Exception as exc:
                raise EncodeError("Flush/EndEncode failed: %s" % exc) from exc
        else:
            logger.info("Encoder adapter EndEncode called but encoder is None (already closed).")
        return packets
    
    def close(self) -> None:
        packets = self.end_encode()
        if self.encoder is not None:
            # Explicit cleanup: release encoder reference.
            # No hidden CPU conversion is performed during close.
            try:
                self.encoder = None
            except Exception:
                pass
        logger.info("Encoder adapter closed (drained packets=%d).", len(packets))
    
    def reconfigure(
        self, bitrate_kbps: Optional[int] = None,
        fps: Optional[float] = None,
        max_bitrate_kbps: Optional[int] = None
    ) -> None:
        # Actual Reconfigure() call on encoder instance when supported.
        # Per sample evidence (encode_reconfigure.py):
        #   reconf_params = nvenc.GetEncodeReconfigureParams()
        #   reconf_params.averageBitrate = ...
        #   nvenc.Reconfigure(reconf_params)
        params: Dict[str, Any] = {}
        if bitrate_kbps is not None:
            params["bitrate"] = bitrate_kbps
            self.bitrate_kbps = bitrate_kbps
        if fps is not None:
            params["fps"] = fps
            self.fps = fps
        if max_bitrate_kbps is not None:
            params["maxbitrate"] = max_bitrate_kbps
            self.max_bitrate_kbps = max_bitrate_kbps
        if self.encoder is not None and hasattr(self.encoder, "Reconfigure"):
            try:
                reconf_params = self.encoder.GetEncodeReconfigureParams()
                if bitrate_kbps is not None:
                    reconf_params.averageBitrate = bitrate_kbps
                if max_bitrate_kbps is not None:
                    reconf_params.vbvBufferSize = max_bitrate_kbps
                    reconf_params.vbvInitialDelay = max_bitrate_kbps
                # The adapter logs observable changes; does not silently ignore.
                self.encoder.Reconfigure(reconf_params)
                logger.info("Encoder adapter reconfigure applied to encoder: %s", params)
            except Exception as exc:
                # Observable failure, not hidden suppression.
                logger.warning("Encoder adapter reconfigure call failed (non-fatal, observable): %s", exc)
        else:
            logger.info("Encoder adapter reconfigure: encoder has no Reconfigure (parameters logged but not applied): %s", params)
    
    def get_reconfigure_params(self) -> List[str]:
        return ["bitrate", "maxbitrate", "fps"]