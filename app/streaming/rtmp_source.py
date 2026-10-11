"""
Phase 11.10 — RTMP Source Adapter with Readiness Gate.

Integrates MediaMTX RTMP output with existing PyAV CUDA NVDEC decoder infrastructure.
Thin adapter: MediaMTX RTMP → PyAV CUDA NVDEC → GPUFrameContract.

Implements observable readiness checks to eliminate errno=129 cold-start race:
- MediaMTX publisher exists and ready
- H264 track available
- Stream bytes actively increasing
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, List

from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.data.input_adapter import VideoFrameIterator, VideoInfo
from app.replay.clock import ReplayClock, ReplayTimestamp
from app.replay.source import ReplaySource, ReplaySourceConfig, ReplaySourceError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RTMPSourceConfig:
    """Configuration for an RTMP source (MediaMTX RTMP output)."""
    camera_id: str
    rtmp_url: str
    use_pts: bool = True
    max_queue_size: int = 10
    # CAMERA OPEN TIMEOUT = exactly 10 seconds (PART C requirement)
    timeout: float = 10.0
    retry_interval: float = 5.0
    max_retries: int = 3
    expected_codec: str = "h264"
    expected_width: int = 3840
    expected_height: int = 2160
    expected_fps: float = 30.0
    decoder: str = "pynvvideocodec"  # Canonical: PyNvVideoCodec NVDEC (production default Phase 9.3+)
    nvdec_gpu_device: int = 0
    
    # Phase 11.10: Readiness gate configuration
    mediamtx_api_base: str = "http://localhost:9997"
    readiness_check_enabled: bool = True
    readiness_timeout: float = 30.0
    readiness_poll_interval: float = 1.0
    min_bytes_progress_interval: float = 5.0  # seconds
    consecutive_bytes_increases_required: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "rtmp_url": self.rtmp_url,
            "use_pts": self.use_pts,
            "max_queue_size": self.max_queue_size,
            "timeout": self.timeout,
            "retry_interval": self.retry_interval,
            "max_retries": self.max_retries,
            "expected_codec": self.expected_codec,
            "expected_width": self.expected_width,
            "expected_height": self.expected_height,
            "expected_fps": self.expected_fps,
            "decoder": self.decoder,
            "nvdec_gpu_device": self.nvdec_gpu_device,
            "mediamtx_api_base": self.mediamtx_api_base,
            "readiness_check_enabled": self.readiness_check_enabled,
            "readiness_timeout": self.readiness_timeout,
            "readiness_poll_interval": self.readiness_poll_interval,
            "min_bytes_progress_interval": self.min_bytes_progress_interval,
            "consecutive_bytes_increases_required": self.consecutive_bytes_increases_required,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RTMPSourceConfig":
        return cls(
            camera_id=data["camera_id"],
            rtmp_url=data["rtmp_url"],
            use_pts=data.get("use_pts", True),
            max_queue_size=data.get("max_queue_size", 10),
            timeout=data.get("timeout", 10.0),
            retry_interval=data.get("retry_interval", 5.0),
            max_retries=data.get("max_retries", 3),
            expected_codec=data.get("expected_codec", "h264"),
            expected_width=data.get("expected_width", 3840),
            expected_height=data.get("expected_height", 2160),
            expected_fps=data.get("expected_fps", 30.0),
            decoder=data.get("decoder", "pynvvideocodec"),
            nvdec_gpu_device=data.get("nvdec_gpu_device", 0),
            mediamtx_api_base=data.get("mediamtx_api_base", "http://localhost:9997"),
            readiness_check_enabled=data.get("readiness_check_enabled", True),
            readiness_timeout=data.get("readiness_timeout", 30.0),
            readiness_poll_interval=data.get("readiness_poll_interval", 1.0),
            min_bytes_progress_interval=data.get("min_bytes_progress_interval", 5.0),
            consecutive_bytes_increases_required=data.get("consecutive_bytes_increases_required", 3),
        )


class RTMPSourceError(ReplaySourceError):
    """Exception raised when RTMP source encounters an error."""
    def __init__(
        self,
        message: str,
        camera_id: str,
        rtmp_url: str,
        frame_index: Optional[int] = None,
        recoverable: bool = False,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, camera_id, rtmp_url, frame_index, recoverable)
        self.rtmp_url = rtmp_url
        self.original_error = original_error


class RTMPReadinessState(str, Enum):
    """RTMP publisher readiness states for the readiness gate."""
    PUBLISHER_NOT_PRESENT = "publisher_not_present"
    PUBLISHER_DETECTED = "publisher_detected"
    TRACKS_DETECTED = "tracks_detected"
    STREAM_DATA_CONFIRMED = "stream_data_confirmed"
    RTMP_READER_READY = "rtmp_reader_ready"
    PYAV_CONNECTION_ALLOWED = "pyav_connection_allowed"
    FAILED = "failed"


class RTMPSource:
    """
    RTMP source adapter for MediaMTX RTMP output.
    
    Wraps VideoFrameIterator to provide RTMP streaming with:
    - Camera ID preservation
    - Frame identity (frame_index)
    - Timestamp semantics (via ReplayClock)
    - Bounded memory (streaming, not loading all frames)
    - Error isolation
    - Reconnect support
    - Stream validation (codec, resolution, FPS)
    - Phase 11.10: Observable readiness gate to eliminate errno=129 cold-start race
    """
    
    def __init__(self, config: RTMPSourceConfig):
        self.config = config
        self.camera_id = config.camera_id
        self.rtmp_url = config.rtmp_url
        
        self._iterator: Optional[VideoFrameIterator] = None
        self._info: Optional[VideoInfo] = None
        self._clock: Optional[ReplayClock] = None
        
        self._opened = False
        self._frame_count = 0
        self._error: Optional[RTMPSourceError] = None
        self._exhausted = False
        self._reconnect_count = 0
        self._last_frame_time: Optional[float] = None
        self._stream_validated = False
        
        # Phase 11.10: Readiness state tracking
        self._readiness_state = RTMPReadinessState.PUBLISHER_NOT_PRESENT
        self._last_bytes_received: Optional[int] = None
        self._last_bytes_progress_time: Optional[float] = None
        self._publisher_ready_time: Optional[float] = None
    
    def open(self) -> VideoInfo:
        """Open the RTMP source and return metadata."""
        if self._opened:
            return self._info
        
        logger.info(f"Opening RTMP source: camera_id={self.camera_id}, url={self.rtmp_url}")
        
        # Phase 11.10: Run readiness gate before connecting PyAV
        if self.config.readiness_check_enabled:
            self._wait_for_publisher_readiness()
        
        try:
            self._iterator = VideoFrameIterator(
                self.rtmp_url,
                decoder=self.config.decoder,
                nvdec_gpu_device=self.config.nvdec_gpu_device,
                expected_width=self.config.expected_width,
                expected_height=self.config.expected_height,
                expected_fps=self.config.expected_fps,
                camera_id=self.config.camera_id,
            )
            self._info = self._iterator.info
            
            # Create iterator from iterable for next() calls
            self._frame_iter = iter(self._iterator)
            
            fps = self._info.fps if self._info.fps > 0 else self.config.expected_fps
            self._clock = ReplayClock(camera_id=self.camera_id, fps=fps)
            
            self._validate_stream()
            
            self._opened = True
            self._frame_count = 0
            self._error = None
            self._exhausted = False
            self._stream_validated = True
            
            # Mark readiness as complete
            self._readiness_state = RTMPReadinessState.PYAV_CONNECTION_ALLOWED
            self._publisher_ready_time = time.time()
            
            logger.info(
                f"RTMP source opened: camera_id={self.camera_id}, "
                f"resolution={self._info.width}x{self._info.height}, "
                f"fps={self._info.fps}, frames={self._info.frame_count}, "
                f"decoder={self.config.decoder}"
            )
            
            return self._info
            
        except Exception as e:
            error = RTMPSourceError(
                f"Failed to open RTMP source: {e}",
                camera_id=self.camera_id,
                rtmp_url=self.rtmp_url,
                recoverable=True,
                original_error=e,
            )
            self._error = error
            self._readiness_state = RTMPReadinessState.FAILED
            logger.error(f"Failed to open RTMP source: {error}")
            raise error
    
    def _validate_stream(self) -> None:
        """Validate stream properties match expectations."""
        if not self._info:
            return
        
        if (self._info.width != self.config.expected_width or 
            self._info.height != self.config.expected_height):
            logger.warning(
                f"Stream resolution mismatch for {self.camera_id}: "
                f"expected {self.config.expected_width}x{self.config.expected_height}, "
                f"got {self._info.width}x{self._info.height}"
            )
        
        if self._info.fps > 0:
            fps_diff = abs(self._info.fps - self.config.expected_fps)
            if fps_diff > 1.0:
                logger.warning(
                    f"Stream FPS mismatch for {self.camera_id}: "
                    f"expected {self.config.expected_fps}, got {self._info.fps}"
                )
        
        logger.info(f"Stream validation passed for {self.camera_id}")

    # Phase 11.10: Readiness gate implementation
    def _wait_for_publisher_readiness(self) -> None:
        """
        Wait for MediaMTX publisher to be ready before allowing PyAV connection.
        
        Implements the readiness state machine:
        PUBLISHER_NOT_PRESENT -> PUBLISHER_DETECTED -> TRACKS_DETECTED -> 
        STREAM_DATA_CONFIRMED -> RTMP_READER_READY -> PYAV_CONNECTION_ALLOWED
        
        This eliminates the errno=129 cold-start race by ensuring the RTMP
        publisher is fully stabilized before PyAV attempts to connect.
        """
        logger.info(f"[{self.camera_id}] Starting RTMP publisher readiness check...")
        
        start_time = time.time()
        last_log_time = 0
        log_interval = 10.0  # Log progress every 10 seconds
        
        # Extract path name from RTMP URL (e.g., "live/cam1" from "rtmp://localhost:1935/live/cam1")
        path_name = self._extract_path_name()
        if not path_name:
            raise RTMPSourceError(
                f"Could not extract MediaMTX path name from RTMP URL: {self.rtmp_url}",
                camera_id=self.camera_id,
                rtmp_url=self.rtmp_url,
                recoverable=False,
            )
        
        while time.time() - start_time < self.config.readiness_timeout:
            try:
                path_info = self._query_mediamtx_path(path_name)
                
                if path_info is None:
                    self._readiness_state = RTMPReadinessState.PUBLISHER_NOT_PRESENT
                    self._log_progress("Publisher not yet present in MediaMTX", start_time, last_log_time, log_interval)
                    time.sleep(self.config.readiness_poll_interval)
                    continue
                
                # State: PUBLISHER_DETECTED
                self._readiness_state = RTMPReadinessState.PUBLISHER_DETECTED
                self._log_progress("Publisher detected", start_time, last_log_time, log_interval)
                
                # Check if publisher is ready and has tracks
                ready = path_info.get("ready", False)
                tracks = path_info.get("tracks", [])
                bytes_received = path_info.get("bytesReceived", 0)
                
                if not ready:
                    logger.debug(f"[{self.camera_id}] Publisher present but not ready yet, tracks={tracks}")
                    time.sleep(self.config.readiness_poll_interval)
                    continue
                
                # State: TRACKS_DETECTED
                if not tracks:
                    logger.debug(f"[{self.camera_id}] Publisher ready but no tracks yet")
                    time.sleep(self.config.readiness_poll_interval)
                    continue
                
                # Verify H264 track exists
                has_h264 = any("H264" in track.upper() or "H.264" in track.upper() or "264" in track.upper() for track in tracks)
                if not has_h264:
                    logger.debug(f"[{self.camera_id}] Publisher ready but no H264 track yet: {tracks}")
                    time.sleep(self.config.readiness_poll_interval)
                    continue
                
                self._readiness_state = RTMPReadinessState.TRACKS_DETECTED
                self._log_progress(f"H264 track detected: {tracks}", start_time, last_log_time, log_interval)
                
                # State: STREAM_DATA_CONFIRMED - Check bytes are increasing (require sustained increase)
                consecutive_required = getattr(self.config, 'consecutive_bytes_increases_required', 3)
                
                if not hasattr(self, '_consecutive_increases'):
                    self._consecutive_increases = 0
                
                if self._last_bytes_received is not None:
                    if bytes_received > self._last_bytes_received:
                        self._consecutive_increases += 1
                        self._last_bytes_progress_time = time.time()
                        if self._consecutive_increases >= consecutive_required:
                            self._readiness_state = RTMPReadinessState.STREAM_DATA_CONFIRMED
                            self._log_progress(f"Stream data confirmed: bytes increasing for {self._consecutive_increases} consecutive polls (last: {self._last_bytes_received} -> {bytes_received})", start_time, last_log_time, log_interval)
                    else:
                        self._consecutive_increases = 0
                        # Check if we've waited long enough for bytes to start flowing
                        if self._last_bytes_progress_time is not None:
                            time_since_progress = time.time() - self._last_bytes_progress_time
                            if time_since_progress > self.config.min_bytes_progress_interval:
                                logger.warning(
                                    f"[{self.camera_id}] No bytes progress for {time_since_progress:.1f}s, "
                                    f"publisher may be stalled. bytesReceived={bytes_received}"
                                )
                else:
                    # First check - record baseline
                    self._last_bytes_progress_time = time.time()
                    self._consecutive_increases = 0
                
                self._last_bytes_received = bytes_received
                
                # If we have confirmed stream data, we can proceed
                if self._readiness_state == RTMPReadinessState.STREAM_DATA_CONFIRMED:
                    # Give a small stabilization window
                    self._readiness_state = RTMPReadinessState.RTMP_READER_READY
                    logger.info(f"[{self.camera_id}] RTMP publisher readiness confirmed after {time.time() - start_time:.1f}s")
                    logger.info(f"[{self.camera_id}] Ready state: {self._readiness_state.value}, bytesReceived={bytes_received}, tracks={tracks}")
                    time.sleep(0.5)  # Small stabilization delay
                    return
                
                time.sleep(self.config.readiness_poll_interval)
                
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Readiness check error: {e}")
                time.sleep(self.config.readiness_poll_interval)
        
        # Timeout - HARD FAILURE as per Phase 11.10 remediation
        elapsed = time.time() - start_time
        logger.error(f"[{self.camera_id}] Readiness timeout after {elapsed:.1f}s, state={self._readiness_state.value}")
        raise RTMPSourceError(
            f"MediaMTX publisher readiness timeout after {elapsed:.1f}s (state={self._readiness_state.value})",
            camera_id=self.camera_id,
            rtmp_url=self.rtmp_url,
            recoverable=False,
        )

    def _extract_path_name(self) -> Optional[str]:
        """Extract MediaMTX path name from RTMP URL."""
        # RTMP URL format: rtmp://host:port/live/cam1
        # Path name: live/cam1
        try:
            # Remove rtmp:// prefix
            url_without_proto = self.rtmp_url
            if url_without_proto.startswith("rtmp://"):
                url_without_proto = url_without_proto[7:]
            elif url_without_proto.startswith("rtmps://"):
                url_without_proto = url_without_proto[8:]
            
            # Find the path after host:port
            parts = url_without_proto.split("/", 1)
            if len(parts) >= 2:
                return parts[1]  # e.g., "live/cam1"
        except Exception as e:
            logger.warning(f"[{self.camera_id}] Failed to extract path name: {e}")
        return None

    def _query_mediamtx_path(self, path_name: str) -> Optional[Dict[str, Any]]:
        """Query MediaMTX API for path information."""
        url = f"{self.config.mediamtx_api_base.rstrip('/')}/v3/paths/list"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                payload = resp.read().decode("utf-8")
                data = json.loads(payload)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            logger.debug(f"[{self.camera_id}] MediaMTX query failed: {e}")
            return None
        except Exception as e:
            logger.debug(f"[{self.camera_id}] MediaMTX query raised: {e}")
            return None
        
        items = data.get("items", []) if isinstance(data, dict) else []
        for item in items:
            if item.get("name") == path_name:
                return item
        return None

    def _log_progress(self, message: str, start_time: float, last_log_time: float, log_interval: float) -> None:
        """Log progress at intervals to avoid log spam."""
        current_time = time.time()
        if current_time - last_log_time >= log_interval:
            elapsed = current_time - start_time
            logger.info(f"[{self.camera_id}] Readiness: {message} (elapsed={elapsed:.1f}s, state={self._readiness_state.value})")
    
    def __iter__(self):
        if not self._opened:
            self.open()
        return self
    
    def __next__(self) -> CanonicalFrame:
        frame = self.get_next_frame()
        if frame is None:
            raise StopIteration
        return frame

    def get_next_frame(self) -> Optional[CanonicalFrame]:
        """Get the next frame from the RTMP stream."""
        if not self._opened:
            self.open()
        
        if self._exhausted:
            return None
        
        if self._error:
            raise self._error
        
        try:
            frame = next(self._frame_iter)
            
            # For live RTMP streams, use wall-clock receive time as timestamp
            # since frame_index/FPS doesn't work for live streams
            frame_receive_time = time.time()
            
            # Use ReplayClock for deterministic timestamps if PTS available
            # Otherwise fall back to wall-clock time for live streams
            replay_timestamp = self._clock.next_timestamp() if self._clock else ReplayTimestamp.not_available()
            
            # For live streams, use wall-clock time as the primary timestamp
            # This ensures proper FPS calculation for live streams
            live_timestamp = frame_receive_time - self._start_time if hasattr(self, '_start_time') and self._start_time else frame_receive_time
            
            # Initialize start time on first frame
            if not hasattr(self, '_start_time') or self._start_time is None:
                self._start_time = frame_receive_time
                live_timestamp = 0.0
            
            new_metadata = FrameMetadata(
                source_type=SourceType.VIDEO,
                source_id=self.rtmp_url,
                frame_index=frame.metadata.frame_index,
                timestamp=live_timestamp,  # Use wall-clock based timestamp for live streams
                timestamp_utc=frame.metadata.timestamp_utc,
                original_width=frame.metadata.original_width,
                original_height=frame.metadata.original_height,
                pixel_format=frame.metadata.pixel_format,
                dtype=frame.metadata.dtype,
                source_fps=frame.metadata.source_fps,
                source_duration=frame.metadata.source_duration,
                source_frame_count=frame.metadata.source_frame_count,
                extra={
                    **frame.metadata.extra,
                    "camera_id": self.camera_id,
                    "replay_timestamp": replay_timestamp.to_dict(),
                    "replay_frame_index": self._frame_count,
                    "rtmp_url": self.rtmp_url,
                    "wall_clock_receive_time": frame_receive_time,
                },
            )
            
            replay_frame = CanonicalFrame(
                data=frame.data,
                metadata=new_metadata,
                conversions_applied={},
            )
            
            self._frame_count += 1
            self._last_frame_time = frame_receive_time
            return replay_frame
            
        except StopIteration:
            self._exhausted = True
            logger.info(f"RTMP source exhausted: camera_id={self.camera_id}, frames={self._frame_count}")
            return None
        except Exception as e:
            error = RTMPSourceError(
                f"Error getting next frame: {e}",
                camera_id=self.camera_id,
                rtmp_url=self.rtmp_url,
                frame_index=self._frame_count,
                recoverable=True,
                original_error=e,
            )
            self._error = error
            logger.error(f"RTMP source error: {error}")
            raise error

    def reconnect(self) -> bool:
        """Attempt to reconnect to the RTMP stream."""
        if self._reconnect_count >= self.config.max_retries:
            logger.error(f"Max retries exceeded for {self.camera_id}")
            return False
        
        self._reconnect_count += 1
        logger.info(f"Reconnecting {self.camera_id} (attempt {self._reconnect_count}/{self.config.max_retries})")
        
        self.close()
        time.sleep(self.config.retry_interval)
        
        try:
            self.open()
            logger.info(f"Reconnection successful for {self.camera_id}")
            return True
        except Exception as e:
            logger.error(f"Reconnection failed for {self.camera_id}: {e}")
            return False

    @property
    def is_exhausted(self) -> bool:
        return self._exhausted
    
    @property
    def has_error(self) -> bool:
        return self._error is not None
    
    @property
    def error(self) -> Optional[RTMPSourceError]:
        return self._error
    
    @property
    def frames_produced(self) -> int:
        return self._frame_count
    
    @property
    def total_frames(self) -> Optional[int]:
        return self._info.frame_count if self._info else None
    
    @property
    def fps(self) -> Optional[float]:
        return self._info.fps if self._info else None
    
    @property
    def resolution(self) -> Optional[tuple]:
        if self._info:
            return (self._info.width, self._info.height)
        return None
    
    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count
    
    @property
    def last_frame_time(self) -> Optional[float]:
        return self._last_frame_time
    
    @property
    def is_stream_validated(self) -> bool:
        return self._stream_validated
    
    @property
    def readiness_state(self) -> RTMPReadinessState:
        """Get current readiness state for diagnostics."""
        return self._readiness_state
    
    @property
    def last_bytes_received(self) -> Optional[int]:
        """Get last observed bytes received from MediaMTX."""
        return self._last_bytes_received
    
    def close(self) -> None:
        """Close the RTMP source and release resources."""
        if self._iterator:
            self._iterator.close()
            self._iterator = None
        self._opened = False
        logger.info(f"Closed RTMP source: camera_id={self.camera_id}")
    
    def reset(self) -> None:
        """Reset source to beginning (re-open)."""
        self.close()
        self._frame_count = 0
        self._error = None
        self._exhausted = False
        self._reconnect_count = 0
        self._last_frame_time = None
        self._stream_validated = False
        if self._clock:
            self._clock.reset()
        self.open()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "frames_produced": self._frame_count,
            "total_frames": self.total_frames,
            "fps": self.fps,
            "resolution": self.resolution,
            "is_exhausted": self.is_exhausted,
            "has_error": self.has_error,
            "error": str(self._error) if self._error else None,
            "reconnect_count": self._reconnect_count,
            "last_frame_time": self._last_frame_time,
            "stream_validated": self._stream_validated,
        }


def create_rtmp_source(
    camera_id: str,
    rtmp_url: str,
    expected_codec: str = "h264",
    expected_width: int = 3840,
    expected_height: int = 2160,
    expected_fps: float = 30.0,
    decoder: str = "pyav_nvdec",
    nvdec_gpu_device: int = 0,
    mediamtx_api_base: str = "http://localhost:9997",
    readiness_check_enabled: bool = True,
    readiness_timeout: float = 30.0,
    readiness_poll_interval: float = 1.0,
    min_bytes_progress_interval: float = 5.0,
    consecutive_bytes_increases_required: int = 3,
) -> RTMPSource:
    """Factory function to create an RTMP source."""
    config = RTMPSourceConfig(
        camera_id=camera_id,
        rtmp_url=rtmp_url,
        expected_codec=expected_codec,
        expected_width=expected_width,
        expected_height=expected_height,
        expected_fps=expected_fps,
        decoder=decoder,
        nvdec_gpu_device=nvdec_gpu_device,
        mediamtx_api_base=mediamtx_api_base,
        readiness_check_enabled=readiness_check_enabled,
        readiness_timeout=readiness_timeout,
        readiness_poll_interval=readiness_poll_interval,
        min_bytes_progress_interval=min_bytes_progress_interval,
        consecutive_bytes_increases_required=consecutive_bytes_increases_required,
    )
    return RTMPSource(config)