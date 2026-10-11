"""
RTSP Source - Camera ingestion from RTSP streams.

Handles RTSP connection, packet reading, reconnection, and health monitoring.
"""

from __future__ import annotations

import logging
import threading
import time
import socket
from dataclasses import dataclass, field
from typing import Optional, Iterator, Any, Dict, List
from enum import Enum
from queue import Queue, Empty

import av

from pipeline_engine.memory.gpu_frame import GPUFrame
from pipeline_engine.config import get_camera_config

logger = logging.getLogger(__name__)


class RTSPState(str, Enum):
    """RTSP connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    READING = "reading"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class RTSPSourceConfig:
    """Configuration for RTSP source."""
    camera_id: str
    url: str
    transport: str = "tcp"          # tcp, udp, udp_multicast
    timeout: float = 10.0           # Connection timeout
    read_timeout: float = 5.0       # Read timeout
    buffer_size: int = 1024 * 1024  # Socket buffer
    # Reconnection
    reconnect_enabled: bool = True
    max_retries: int = 5
    base_interval: float = 2.0
    max_interval: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: float = 0.1
    # Health
    stale_threshold: float = 5.0
    degraded_threshold: float = 2.0
    # Readiness
    readiness_enabled: bool = True
    readiness_timeout: float = 30.0
    min_bytes_progress_interval: float = 5.0
    consecutive_increases_required: int = 3


@dataclass
class RTSPSourceMetrics:
    """RTSP source metrics."""
    camera_id: str
    state: RTSPState = RTSPState.DISCONNECTED
    bytes_received: int = 0
    packets_received: int = 0
    frames_decoded: int = 0
    errors: int = 0
    reconnects: int = 0
    last_packet_time: float = 0.0
    last_frame_time: float = 0.0
    current_bitrate_kbps: float = 0.0
    readiness_passed: bool = False
    consecutive_bytes_increases: int = 0
    last_bytes_check: float = 0.0
    last_bytes_value: int = 0


class RTSPSource:
    """
    RTSP stream source with automatic reconnection and health monitoring.
    
    Reads compressed packets from RTSP stream and provides them
    to the decoder. Does NOT decode - just packet transport.
    """
    
    def __init__(self, config: RTSPSourceConfig):
        self.config = config
        self.camera_id = config.camera_id
        
        # Connection
        self._container: Optional[av.container.InputContainer] = None
        self._stream: Optional[av.stream.Stream] = None
        self._state = RTSPState.DISCONNECTED
        self._metrics = RTSPSourceMetrics(camera_id=config.camera_id)
        
        # Threading
        self._stop_event = threading.Event()
        self._read_thread: Optional[threading.Thread] = None
        self._packet_queue: Queue = Queue(maxsize=32)
        
        # Reconnection
        self._retry_count = 0
        self._reconnect_event = threading.Event()
        
        # Stats
        self._lock = threading.RLock()
        self._last_bitrate_calc = time.time()
        self._bytes_at_last_calc = 0
    
    @property
    def state(self) -> RTSPState:
        return self._state
    
    @property
    def metrics(self) -> RTSPSourceMetrics:
        with self._lock:
            return self._metrics
    
    def _set_state(self, state: RTSPState) -> None:
        with self._lock:
            old = self._state
            self._state = state
            self._metrics.state = state
            if old != state:
                logger.info(f"RTSPSource({self.camera_id}): {old.value} -> {state.value}")
    
    def _build_ffmpeg_options(self) -> Dict[str, str]:
        """Build FFmpeg options for RTSP connection."""
        # Ensure None values get defaults
        timeout = self.config.timeout if self.config.timeout is not None else 10.0
        read_timeout = self.config.read_timeout if self.config.read_timeout is not None else 5.0
        buffer_size = self.config.buffer_size if self.config.buffer_size is not None else 1024 * 1024
        
        options = {
            "rtsp_transport": self.config.transport or "tcp",
            "stimeout": str(int(timeout * 1_000_000)),  # microseconds
            "rw_timeout": str(int(read_timeout * 1_000_000)),
            "buffer_size": str(buffer_size),
            "max_delay": "500000",  # 500ms max delay
            "reorder_queue_size": "0",
        }
        return options
    
    def _open_container(self) -> None:
        """Open RTSP container with FFmpeg."""
        options = self._build_ffmpeg_options()
        
        logger.info(f"RTSPSource({self.camera_id}): Connecting to {self.config.url}")
        
        self._container = av.open(
            self.config.url,
            format="rtsp",
            options=options,
            timeout=int(self.config.timeout * 1_000_000),
        )
        
        # Find video stream
        video_streams = [s for s in self._container.streams if s.type == "video"]
        if not video_streams:
            raise RuntimeError(f"No video stream found in {self.config.url}")
        
        self._stream = video_streams[0]
        # Handle case where average_rate is None (common for RTSP)
        avg_rate = self._stream.average_rate
        if avg_rate is not None:
            fps = float(avg_rate)
        else:
            # Try to get framerate from codec context
            fps = float(self._stream.codec_context.framerate) if self._stream.codec_context.framerate else 30.0
        
        logger.info(
            f"RTSPSource({self.camera_id}): Connected - "
            f"{self._stream.width}x{self._stream.height} "
            f"@{fps:.1f}fps "
            f"codec={self._stream.codec_context.name}"
        )
    
    def start(self) -> bool:
        """Start RTSP source."""
        with self._lock:
            if self._state in (RTSPState.CONNECTED, RTSPState.READING):
                logger.warning(f"RTSPSource({self.camera_id}): Already started")
                return True
            
            self._set_state(RTSPState.CONNECTING)
            
            try:
                self._open_container()
                self._stop_event.clear()
                
                self._read_thread = threading.Thread(
                    target=self._read_loop,
                    name=f"rtsp-read-{self.camera_id}",
                    daemon=True,
                )
                self._read_thread.start()
                
                self._metrics.readiness_passed = False
                self._metrics.consecutive_bytes_increases = 0
                self._metrics.last_bytes_check = time.time()
                self._metrics.last_bytes_value = 0
                
                self._set_state(RTSPState.READING)
                logger.info(f"RTSPSource({self.camera_id}): Started successfully")
                return True
                
            except Exception as e:
                self._metrics.errors += 1
                self._set_state(RTSPState.ERROR)
                logger.error(f"RTSPSource({self.camera_id}): Start failed: {e}")
                return False
    
    def _read_loop(self) -> None:
        """Read packets from RTSP stream."""
        try:
            for packet in self._container.demux(self._stream):
                if self._stop_event.is_set():
                    break
                
                if packet.size <= 0:
                    continue
                
                # Update metrics
                with self._lock:
                    self._metrics.bytes_received += packet.size
                    self._metrics.packets_received += 1
                    self._metrics.last_packet_time = time.time()
                
                # Readiness check
                self._check_readiness()
                
                # Queue packet
                try:
                    self._packet_queue.put_nowait(packet)
                except Exception:
                    # Queue full, drop oldest
                    try:
                        self._packet_queue.get_nowait()
                    except Empty:
                        pass
                    try:
                        self._packet_queue.put_nowait(packet)
                    except Exception:
                        pass
                
                # Calculate bitrate periodically
                self._update_bitrate()
                
        except av.error.FFmpegError as e:
            logger.error(f"RTSPSource({self.camera_id}): FFmpeg error: {e}")
            with self._lock:
                self._metrics.errors += 1
        except Exception as e:
            logger.error(f"RTSPSource({self.camera_id}): Read loop error: {e}")
            with self._lock:
                self._metrics.errors += 1
        finally:
            logger.debug(f"RTSPSource({self.camera_id}): Read loop exited")
            self._handle_read_loop_exit()
    
    def _check_readiness(self) -> None:
        """Check readiness gate based on bytes progress."""
        if not self.config.readiness_enabled:
            self._metrics.readiness_passed = True
            return
        
        with self._lock:
            now = time.time()
            if now - self._metrics.last_bytes_check >= self.config.min_bytes_progress_interval:
                if self._metrics.bytes_received > self._metrics.last_bytes_value:
                    self._metrics.consecutive_bytes_increases += 1
                else:
                    self._metrics.consecutive_bytes_increases = 0
                
                self._metrics.last_bytes_value = self._metrics.bytes_received
                self._metrics.last_bytes_check = now
                
                if self._metrics.consecutive_bytes_increases >= self.config.consecutive_increases_required:
                    self._metrics.readiness_passed = True
                    logger.debug(f"RTSPSource({self.camera_id}): Readiness gate PASSED")
    
    def _update_bitrate(self) -> None:
        """Calculate current bitrate."""
        now = time.time()
        if now - self._last_bitrate_calc >= 1.0:  # Every second
            with self._lock:
                bytes_delta = self._metrics.bytes_received - self._bytes_at_last_calc
                time_delta = now - self._last_bitrate_calc
                if time_delta > 0:
                    self._metrics.current_bitrate_kbps = (bytes_delta * 8) / (time_delta * 1000)
                self._bytes_at_last_calc = self._metrics.bytes_received
                self._last_bitrate_calc = now
    
    def _handle_read_loop_exit(self) -> None:
        """Handle read loop exit - attempt reconnect."""
        with self._lock:
            if self._stop_event.is_set():
                self._set_state(RTSPState.STOPPED)
                return
            
            if self.config.reconnect_enabled and self._retry_count < self.config.max_retries:
                self._schedule_reconnect()
            else:
                self._set_state(RTSPState.ERROR)
    
    def _schedule_reconnect(self) -> None:
        """Schedule a reconnection attempt."""
        self._retry_count += 1
        self._metrics.reconnects += 1
        
        interval = min(
            self.config.base_interval * (self.config.backoff_multiplier ** (self._retry_count - 1)),
            self.config.max_interval,
        )
        # Add jitter
        import random
        interval *= (1 + random.uniform(-self.config.jitter, self.config.jitter))
        
        logger.info(
            f"RTSPSource({self.camera_id}): Scheduling reconnect "
            f"attempt {self._retry_count}/{self.config.max_retries} in {interval:.1f}s"
        )
        
        def delayed_reconnect():
            time.sleep(interval)
            if not self._stop_event.is_set():
                self._reconnect()
        
        threading.Thread(target=delayed_reconnect, daemon=True).start()
    
    def _reconnect(self) -> bool:
        """Attempt to reconnect."""
        with self._lock:
            if self._state == RTSPState.RECONNECTING:
                return False
            
            self._set_state(RTSPState.RECONNECTING)
            self._close_internal()
        
        try:
            self._open_container()
            
            with self._lock:
                self._stop_event.clear()
                self._read_thread = threading.Thread(
                    target=self._read_loop,
                    name=f"rtsp-read-{self.camera_id}",
                    daemon=True,
                )
                self._read_thread.start()
                
                self._metrics.readiness_passed = False
                self._metrics.consecutive_bytes_increases = 0
                self._metrics.last_bytes_check = time.time()
                self._metrics.last_bytes_value = 0
            
            self._set_state(RTSPState.READING)
            logger.info(f"RTSPSource({self.camera_id}): Reconnected successfully")
            return True
            
        except Exception as e:
            logger.error(f"RTSPSource({self.camera_id}): Reconnect failed: {e}")
            with self._lock:
                self._metrics.errors += 1
            self._schedule_reconnect()
            return False
    
    def _close_internal(self) -> None:
        """Close container and clear queue."""
        self._stop_event.set()
        
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=3.0)
        
        if self._container:
            try:
                self._container.close()
            except Exception as e:
                logger.debug(f"RTSPSource({self.camera_id}): Close error: {e}")
            finally:
                self._container = None
                self._stream = None
        
        # Clear queue
        while True:
            try:
                self._packet_queue.get_nowait()
            except Empty:
                break
    
    def stop(self) -> None:
        """Stop RTSP source."""
        with self._lock:
            if self._state == RTSPState.STOPPED:
                return
            
            logger.info(f"RTSPSource({self.camera_id}): Stopping")
            self._close_internal()
            self._set_state(RTSPState.STOPPED)
            logger.info(f"RTSPSource({self.camera_id}): Stopped")
    
    def get_packet(self, timeout: float = 1.0) -> Optional[av.Packet]:
        """Get next packet from queue."""
        try:
            return self._packet_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def iter_packets(self) -> Iterator[av.Packet]:
        """Iterate packets from stream."""
        while self._state == RTSPState.READING:
            packet = self.get_packet(1.0)
            if packet is None:
                continue
            yield packet
    
    def get_queue_depth(self) -> int:
        return self._packet_queue.qsize()
    
    def get_stream_info(self) -> Dict[str, Any]:
        """Get stream information."""
        with self._lock:
            info = {
                "camera_id": self.camera_id,
                "url": self.config.url,
                "state": self._state.value,
            }
            if self._stream:
                info.update({
                    "width": self._stream.width,
                    "height": self._stream.height,
                    "codec": self._stream.codec_context.name,
                    "fps": float(self._stream.average_rate) if self._stream.average_rate else 0,
                    "time_base": float(self._stream.time_base) if self._stream.time_base else 0,
                })
            return info
    
    def is_healthy(self) -> bool:
        """Check if source is healthy."""
        with self._lock:
            if self._state != RTSPState.READING:
                return False
            
            now = time.time()
            if now - self._metrics.last_packet_time > self.config.stale_threshold:
                return False
            
            return True
    
    def is_degraded(self) -> bool:
        """Check if source is degraded."""
        with self._lock:
            if self._state != RTSPState.READING:
                return True
            
            now = time.time()
            if now - self._metrics.last_packet_time > self.config.degraded_threshold:
                return True
            
            return False
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def create_rtsp_source(camera_id: str, config: Optional[Dict[str, Any]] = None) -> RTSPSource:
    """Factory function to create RTSP source from pipeline config."""
    if config is None:
        from pipeline_engine.config import get_config
        config = get_config()
    
    cam_config = get_camera_config(config, camera_id)
    
    rtsp_config = RTSPSourceConfig(
        camera_id=camera_id,
        url=cam_config.get("input", {}).get("url", f"rtsp://localhost:8554/live/{camera_id}"),
        transport=cam_config.get("input", {}).get("transport", "tcp"),
        timeout=cam_config.get("input", {}).get("timeout_seconds", 10.0),
        reconnect_enabled=cam_config.get("reconnect", {}).get("enabled", True),
        max_retries=cam_config.get("reconnect", {}).get("max_retries", 5),
        base_interval=cam_config.get("reconnect", {}).get("base_interval_seconds", 2.0),
        max_interval=cam_config.get("reconnect", {}).get("max_interval_seconds", 60.0),
        backoff_multiplier=cam_config.get("reconnect", {}).get("backoff_multiplier", 2.0),
        jitter=cam_config.get("reconnect", {}).get("jitter", 0.1),
        stale_threshold=cam_config.get("health", {}).get("stale_threshold_seconds", 5.0),
        degraded_threshold=cam_config.get("health", {}).get("degraded_threshold_seconds", 2.0),
        readiness_enabled=cam_config.get("readiness", {}).get("enabled", True),
        readiness_timeout=cam_config.get("readiness", {}).get("timeout_seconds", 30.0),
        min_bytes_progress_interval=cam_config.get("readiness", {}).get("min_bytes_progress_interval", 5.0),
        consecutive_increases_required=cam_config.get("readiness", {}).get("consecutive_increases_required", 3),
    )
    
    return RTSPSource(rtsp_config)


if __name__ == "__main__":
    # Test with a local file or RTSP stream
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = "rtsp://localhost:8554/live/cam1"
    
    config = RTSPSourceConfig(camera_id="test", url=url)
    source = RTSPSource(config)
    
    if source.start():
        print("RTSP source started!")
        count = 0
        for packet in source.iter_packets():
            print(f"Packet {count}: size={packet.size}, pts={packet.pts}, stream={packet.stream.index}")
            count += 1
            if count >= 10:
                break
        source.stop()
        print(f"Received {count} packets")
        print(f"Metrics: {source.metrics}")
    else:
        print("Failed to start RTSP source")