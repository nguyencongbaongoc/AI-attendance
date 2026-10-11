"""
Phase 9.2 — PyNvVideoCodec Backend B.

Direct PyNvVideoCodec NVDEC decoder for RTSP H.264 streams.
No PyAV intermediary - pure NVDEC path.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import torch

from app.data.input_adapter import VideoInfo, WatchdogFrame
from app.streaming.decoder_backend import DecoderBackend, PyNvVideoCodecBackendConfig
from app.streaming.pynvvideocodec_frame_adapter import PyNvVideoCodecFrameAdapter, create_pynvvideocodec_frame_adapter

logger = logging.getLogger(__name__)


try:
    import PyNvVideoCodec as nvc
    PYNVIDEOCODEC_AVAILABLE = True
except ImportError:
    PYNVIDEOCODEC_AVAILABLE = False
    nvc = None


class PyNvVideoCodecBackend(DecoderBackend):
    """
    Backend B: PyNvVideoCodec direct NVDEC decoder.
    
    Uses PyNvVideoCodec.CreateDemuxer + CreateDecoder for zero-copy GPU decoding.
    Supports explicit shared CUDA context for concurrent decoder operation.
    """
    
    def __init__(self, config: PyNvVideoCodecBackendConfig):
        if not PYNVIDEOCODEC_AVAILABLE:
            raise RuntimeError("PyNvVideoCodec not available. Install PyNvVideoCodec package.")
        
        super().__init__(config)
        self._config: PyNvVideoCodecBackendConfig = config
        self._demuxer = None
        self._container = None
        self._stream = None
        self._decoder = None
        self._frame_adapter = None
        self._width = config.expected_width
        self._height = config.expected_height
        self._fps = config.expected_fps
        self._codec = config.expected_codec
        self._rtsp_url = config.rtsp_url
        self._is_rtmp = config.rtsp_url.lower().startswith("rtmp://")
        self._cuda_stream = None
        self._shared_context_manager = None
    
    def initialize(self) -> None:
        """Initialize PyNvVideoCodec decoder and demuxer."""
        logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Initializing decoder on GPU {self._config.nvdec_gpu_device}")
        
        # Check if explicit shared context/stream provided
        use_shared_context = self._config.cuda_context is not None
        use_shared_stream = self._config.cuda_stream is not None
        
        if use_shared_context:
            # Use explicit shared context and stream
            ctx_handle = self._config.cuda_context
            stream_handle = self._config.cuda_stream
            
            logger.info(
                f"PyNvVideoCodecBackend({self.camera_id}): Using shared context={ctx_handle}, "
                f"stream={stream_handle}"
            )
            
            # For PyNvVideoCodec, we need to set the context as current on this thread
            # when creating the decoder
            import ctypes
            nvcuda = ctypes.CDLL('nvcuda.dll')
            ctx = ctypes.c_void_p(ctx_handle)
            result = nvcuda.cuCtxSetCurrent(ctx)
            if result != 0:
                logger.warning(f"PyNvVideoCodecBackend({self.camera_id}): cuCtxSetCurrent returned {result}")
        else:
            # Fallback: Create CUDA stream using PyTorch's default CUDA context
            import torch
            torch.cuda.init()
            device = torch.device(f'cuda:{self._config.nvdec_gpu_device}')
            
            # Use PyTorch's default CUDA context (0) for the decoder
            self._cuda_stream = torch.cuda.Stream(device=device)
            stream_handle = self._cuda_stream.cuda_stream
            
            logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Using default context (0), stream={stream_handle}")
        
        # Map latency mode
        latency_map = {
            "NATIVE": nvc.DisplayDecodeLatencyType.NATIVE,
            "LOW": nvc.DisplayDecodeLatencyType.LOW,
            "ZERO": nvc.DisplayDecodeLatencyType.ZERO,
        }
        latency = latency_map.get(self._config.latency_mode, nvc.DisplayDecodeLatencyType.NATIVE)
        
        # Map output color type
        color_type_map = {
            "NATIVE": nvc.OutputColorType.NATIVE,
            "RGB": nvc.OutputColorType.RGB,
            "RGBP": nvc.OutputColorType.RGBP,
        }
        output_color_type = color_type_map.get(self._config.output_color_type, nvc.OutputColorType.NATIVE)
        
        # Create decoder with CUDA stream
        cudacontext = self._config.cuda_context if use_shared_context else 0
        
        self._decoder = nvc.CreateDecoder(
            gpuid=self._config.nvdec_gpu_device,
            codec=nvc.cudaVideoCodec.H264,
            cudacontext=cudacontext,
            cudastream=stream_handle,
            usedevicememory=self._config.use_device_memory,
            enableasyncallocations=self._config.enable_async_allocations,
            maxwidth=self._config.expected_width,
            maxheight=self._config.expected_height,
            outputColorType=output_color_type,
            enableSEIMessage=self._config.enable_sei,
            latency=latency,
            enableDecodeStats=self._config.enable_decode_stats,
        )
        
        logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Decoder created with context={cudacontext}, stream={stream_handle}")
        
        # Create frame adapter with the stream handle
        self._frame_adapter = create_pynvvideocodec_frame_adapter(
            camera_id=self.camera_id,
            cuda_stream=stream_handle,
            device_id=self._config.nvdec_gpu_device,
        )
    
    def _open_demuxer(self) -> None:
        """Open demuxer for the RTSP stream using PyAV for packet extraction."""
        import av
        
        is_rtmp = self._rtsp_url.lower().startswith("rtmp://")
        is_rtsp = self._rtsp_url.lower().startswith("rtsp://")
        
        if is_rtsp or is_rtmp:
            # Network stream - use PyAV for demuxing
            format_name = "flv" if is_rtmp else "rtsp"
            options = {}
            if is_rtmp:
                options["rtmp_buffer"] = "100"
            else:
                options["rtsp_transport"] = "tcp"
            
            logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Opening demuxer for {self._rtsp_url}")
            
            # Open container for demuxing only (no hardware decoding)
            self._container = av.open(
                self._rtsp_url,
                format=format_name,
                options=options,
            )
            
            # Get video stream
            self._stream = self._container.streams.video[0]
            
            logger.info(
                f"PyNvVideoCodecBackend({self.camera_id}): Stream info - "
                f"codec={self._stream.codec_context.name}, "
                f"width={self._stream.width}, height={self._stream.height}, "
                f"pix_fmt={self._stream.codec_context.pix_fmt}"
            )
            
            self._width = self._stream.width or self._config.expected_width
            self._height = self._stream.height or self._config.expected_height
            self._fps = float(self._stream.average_rate) if self._stream.average_rate else self._config.expected_fps
            self._codec = self._stream.codec_context.name
            
            self._use_pynv_demuxer = False
        else:
            # Local file - use PyNvVideoCodec demuxer directly (works better)
            logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Opening local file with PyNvVideoCodec demuxer {self._rtsp_url}")
            
            self._pynv_demuxer = nvc.CreateDemuxer(self._rtsp_url)
            
            self._width = self._pynv_demuxer.Width()
            self._height = self._pynv_demuxer.Height()
            self._fps = self._pynv_demuxer.FrameRate()
            self._codec = "h264"  # Assuming H.264 for local files
            
            logger.info(
                f"PyNvVideoCodecBackend({self.camera_id}): Stream info - "
                f"width={self._width}, height={self._height}, fps={self._fps}"
            )
            
            self._use_pynv_demuxer = True
    
    def open(self) -> VideoInfo:
        """Open the RTSP source and start decode thread."""
        if self._decoder is None:
            self.initialize()
        
        # Open demuxer (PyAV container for packet extraction)
        self._open_demuxer()
        
        # Start reader thread
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"pynvvideocodec-reader-{self.camera_id}",
            daemon=True,
        )
        self._reader_thread.start()
        
        self._opened = True
        self._frame_index = 0
        self._error = None
        
        info = VideoInfo(
            width=self._width,
            height=self._height,
            fps=self._fps,
            frame_count=0,
            duration=0.0,
            codec=self._codec,
            pixel_format="cuda",  # GPU frames
            path=self._rtsp_url,
        )
        
        logger.info(
            f"PyNvVideoCodecBackend({self.camera_id}): Opened successfully "
            f"({self._width}x{self._height}@{self._fps}fps, "
            f"NVDEC gpu={self._config.nvdec_gpu_device})"
        )
        
        return info
    
    def _reader_loop(self) -> None:
        """Read packets from demuxer, decode with PyNvVideoCodec, push frames to queue."""
        import ctypes
        
        try:
            if self._use_pynv_demuxer:
                # Use PyNvVideoCodec demuxer directly
                while not self._stop_event.is_set():
                    packet = self._pynv_demuxer.Demux()
                    if packet.bsl == 0:
                        logger.info(f"PyNvVideoCodecBackend({self.camera_id}): EOF reached")
                        break
                    
                    # Decode packet
                    try:
                        decoded_frames = self._decoder.Decode(packet)
                    except Exception as e:
                        logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Decode failed: {e}")
                        self._error = e
                        continue
                    
                    # Process decoded frames
                    for decoded_frame in decoded_frames:
                        if self._stop_event.is_set():
                            break
                        
                        # Get frame timestamp
                        timestamp = time.time()
                        pts = decoded_frame.getPTS()
                        
                        # Latency instrumentation timestamps
                        t_packet_ingress_ns = time.perf_counter_ns()  # When packet was demuxed
                        t_decode_submit_ns = time.perf_counter_ns()   # When packet was submitted to decoder
                        
                        # Adapt to GPUFrameContract
                        try:
                            frame_contract = self._frame_adapter.adapt(
                                decoded_frame=decoded_frame,
                                timestamp=timestamp,
                                pts=pts,
                                t_packet_ingress_ns=t_packet_ingress_ns,
                                t_decode_submit_ns=t_decode_submit_ns,
                            )
                        except Exception as e:
                            logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Frame adaptation failed: {e}")
                            try:
                                self._decoder.UnlockFrame(0)
                            except Exception:
                                pass
                            continue
                        
                        # Create watchdog frame
                        wframe = WatchdogFrame(
                            data=frame_contract,
                            frame_index=self._frame_index,
                            timestamp=timestamp,
                            pts=pts,
                            stalled=False,
                        )
                        
                        # Latest-wins queue semantics
                        try:
                            self._frame_queue.put_nowait(wframe)
                        except queue.Full:
                            try:
                                self._frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                self._frame_queue.put_nowait(wframe)
                            except queue.Full:
                                pass
                        
                        self._frame_index += 1
                        
                        # Unlock frame after creating tensor references
                        try:
                            self._decoder.UnlockFrame(0)
                        except Exception as e:
                            logger.debug(f"PyNvVideoCodecBackend({self.camera_id}): UnlockFrame error: {e}")
            else:
                # Use PyAV container for demuxing (RTSP/RTMP)
                import av
                
                for packet in self._container.demux(self._stream):
                    if self._stop_event.is_set():
                        break
                    
                    if packet.is_corrupt:
                        continue
                    
                    # Create PyNvVideoCodec PacketData
                    # Use packet.buffer_ptr directly for zero-copy
                    pnv_packet = nvc.PacketData()
                    pnv_packet.bsl = packet.size
                    pnv_packet.bsl_data = packet.buffer_ptr
                    pnv_packet.pts = packet.pts if packet.pts is not None else 0
                    pnv_packet.dts = packet.dts if packet.dts is not None else 0
                    pnv_packet.duration = packet.duration if packet.duration is not None else 0
                    pnv_packet.decode_flag = 0
                    pnv_packet.key = 1 if packet.is_keyframe else 0
                    pnv_packet.is_video = 1
                    pnv_packet.stream_index = 0
                    
                    # Decode packet
                    try:
                        decoded_frames = self._decoder.Decode(pnv_packet)
                    except Exception as e:
                        logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Decode failed: {e}")
                        self._error = e
                        continue
                    
                    # Process decoded frames
                    for decoded_frame in decoded_frames:
                        if self._stop_event.is_set():
                            break
                        
                        # Get frame timestamp
                        timestamp = time.time()
                        pts = decoded_frame.getPTS()
                        
                        # Latency instrumentation timestamps
                        t_packet_ingress_ns = time.perf_counter_ns()  # When packet was demuxed
                        t_decode_submit_ns = time.perf_counter_ns()   # When packet was submitted to decoder
                        
                        # Adapt to GPUFrameContract
                        try:
                            frame_contract = self._frame_adapter.adapt(
                                decoded_frame=decoded_frame,
                                timestamp=timestamp,
                                pts=pts,
                                t_packet_ingress_ns=t_packet_ingress_ns,
                                t_decode_submit_ns=t_decode_submit_ns,
                            )
                        except Exception as e:
                            logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Frame adaptation failed: {e}")
                            try:
                                self._decoder.UnlockFrame(0)
                            except Exception:
                                pass
                            continue
                        
                        # Create watchdog frame
                        wframe = WatchdogFrame(
                            data=frame_contract,
                            frame_index=self._frame_index,
                            timestamp=timestamp,
                            pts=pts,
                            stalled=False,
                        )
                        
                        # Latest-wins queue semantics
                        try:
                            self._frame_queue.put_nowait(wframe)
                        except queue.Full:
                            try:
                                self._frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                self._frame_queue.put_nowait(wframe)
                            except queue.Full:
                                pass
                        
                        self._frame_index += 1
                        
                        # Unlock frame after creating tensor references
                        try:
                            self._decoder.UnlockFrame(0)
                        except Exception as e:
                            logger.debug(f"PyNvVideoCodecBackend({self.camera_id}): UnlockFrame error: {e}")
        
        except av.error.FFmpegError as e:
            logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Demux error: {e}")
            self._error = e
        except Exception as e:
            logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Reader loop error: {e}")
            self._error = e
        finally:
            logger.debug(f"PyNvVideoCodecBackend({self.camera_id}): Reader loop exited")
    
    def close(self) -> None:
        """Close backend and cleanup resources."""
        with self._lock:
            if not self._opened and self._decoder is None:
                return
            
            logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Closing")
            
            self._stop_event.set()
            
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3.0)
            
            if self._container:
                try:
                    self._container.close()
                except Exception as e:
                    logger.debug(f"PyNvVideoCodecBackend({self.camera_id}): Container close error: {e}")
                finally:
                    self._container = None
                    self._stream = None
            
            if getattr(self, '_pynv_demuxer', None):
                self._pynv_demuxer = None
            
            # Decoder cleanup - PyNvVideoCodec decoder doesn't have explicit close
            # but we release references
            self._decoder = None
            self._frame_adapter = None
            self._cuda_stream = None
            
            # Release shared context reference if we have one
            if self._shared_context_manager is not None:
                try:
                    self._shared_context_manager.release_stream(self.camera_id)
                    self._shared_context_manager.release_context()
                    logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Released shared context reference")
                except Exception as e:
                    logger.error(f"PyNvVideoCodecBackend({self.camera_id}): Error releasing shared context: {e}")
                finally:
                    self._shared_context_manager = None
            
            self._opened = False
            logger.info(f"PyNvVideoCodecBackend({self.camera_id}): Closed")
    
    def health(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "backend": "pynvvideocodec",
            "opened": self._opened,
            "frame_index": self._frame_index,
            "queue_size": self._frame_queue.qsize(),
            "width": self._width,
            "height": self._height,
            "fps": self._fps,
            "codec": self._codec,
            "error": str(self._error) if self._error else None,
        }


def create_pynvvideocodec_backend(config: PyNvVideoCodecBackendConfig) -> PyNvVideoCodecBackend:
    """Factory function to create PyNvVideoCodecBackend."""
    return PyNvVideoCodecBackend(config)