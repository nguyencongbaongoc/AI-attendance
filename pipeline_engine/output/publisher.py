"""
MediaMTX Publisher - Publishes H.264 packets to external MediaMTX.

Manages RTSP publishing connection, health monitoring, and reconnection.
"""

from __future__ import annotations

import logging
import threading
import time
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Any, List, Dict, Tuple
from enum import Enum
from queue import Queue, Empty

import av

logger = logging.getLogger(__name__)


class PublisherState(str, Enum):
    """Publisher lifecycle states."""
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    PUBLISHING = "publishing"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    MEDIA_SERVER_NOT_AVAILABLE = "mediamtx_not_running"


@dataclass
class PublisherConfig:
    """Configuration for MediaMTX publisher."""
    camera_id: str
    # MediaMTX connection info
    mediamtx_host: str = "localhost"
    mediamtx_port: int = 8554
    mediamtx_path: str = "/stream"
    # Publisher settings
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 10
    # Packet buffer
    max_packet_buffer: int = 50
    # Health check
    health_check_interval: float = 10.0


@dataclass
class PublisherMetrics:
    """Publisher metrics."""
    packets_published: int = 0
    packets_dropped: int = 0
    reconnect_attempts: int = 0
    connection_time: float = 0.0
    state: PublisherState = PublisherState.STOPPED
    last_publish_time: float = 0.0
    bytes_published: int = 0
    media_server_available: bool = False


class MediaMTXPublisher:
    """
    MediaMTX publisher using PyAV RTSP output.
    
    Actually uses PyAV's RTSP muxer to publish directly to MediaMTX.
    This is simpler and more reliable than raw socket publishing.
    """
    
    def __init__(self, config: PublisherConfig):
        self.config = config
        self.camera_id = config.camera_id
        
        self._state = PublisherState.STOPPED
        self._metrics = PublisherMetrics()
        
        # PyAV container for RTSP output
        self._container = None
        self._stream = None
        
        # Threading
        self._publish_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._packet_queue: Queue = Queue(maxsize=config.max_packet_buffer)
        
        # Lock
        self._lock = threading.RLock()
        
        # FFmpeg process (alternative approach)
        self._ffmpeg_process: Optional[subprocess.Popen] = None
    
    @property
    def state(self) -> PublisherState:
        return self._state
    
    @property
    def metrics(self) -> PublisherMetrics:
        with self._lock:
            return self._metrics
    
    def _set_state(self, state: PublisherState) -> None:
        with self._lock:
            old_state = self._state
            self._state = state
            self._metrics.state = state
            if old_state != state:
                logger.info(f"MediaMTXPublisher({self.camera_id}): {old_state.value} → {state.value}")
    
    def _detect_media_server(self) -> bool:
        """Detect if MediaMTX is running on the configured host/port."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex((self.config.mediamtx_host, self.config.mediamtx_port))
            sock.close()
            
            available = result == 0
            if available:
                logger.info(f"MediaMTXPublisher({self.camera_id}): MediaMTX detected at {self.config.mediamtx_host}:{self.config.mediamtx_port}")
            else:
                logger.info(f"MediaMTXPublisher({self.camera_id}): MediaMTX NOT running at {self.config.mediamtx_host}:{self.config.mediamtx_port}")
            
            return available
        except Exception as e:
            logger.debug(f"MediaMTXPublisher({self.camera_id}): MediaMTX detection error: {e}")
            return False
    
    def start(self) -> bool:
        """Start publisher - connects to existing MediaMTX."""
        with self._lock:
            if self._state in (PublisherState.CONNECTED, PublisherState.PUBLISHING, PublisherState.RECONNECTING):
                logger.info(f"MediaMTXPublisher({self.camera_id}): Already connected or reconnecting")
                return True
            
            # Detect MediaMTX
            available = self._detect_media_server()
            self._metrics.media_server_available = available
            
            if not available:
                self._set_state(PublisherState.MEDIA_SERVER_NOT_AVAILABLE)
                logger.info(f"MediaMTXPublisher({self.camera_id}): MediaMTX not available")
                return False
            
            self._set_state(PublisherState.CONNECTING)
            
            # Try to connect
            connected = self._connect()
            
            if connected:
                self._metrics.connection_time = time.time()
                self._metrics.reconnect_attempts = 0
                
                # Start publish thread
                self._stop_event.clear()
                self._publish_thread = threading.Thread(
                    target=self._publish_loop,
                    name=f"publisher-{self.camera_id}",
                    daemon=True,
                )
                self._publish_thread.start()
                
                self._set_state(PublisherState.PUBLISHING)
                logger.info(f"MediaMTXPublisher({self.camera_id}): Started publishing to {self.config.mediamtx_host}:{self.config.mediamtx_port}{self.config.mediamtx_path}")
                return True
            else:
                self._metrics.reconnect_attempts += 1
                self._set_state(PublisherState.DISCONNECTED)
                logger.warning(f"MediaMTXPublisher({self.camera_id}): Connection failed")
                return False
    
    def _connect(self) -> bool:
        """Initialize PyAV RTSP output container."""
        try:
            url = f"rtsp://{self.config.mediamtx_host}:{self.config.mediamtx_port}{self.config.mediamtx_path}"
            
            self._container = av.open(
                url,
                mode='w',
                format='rtsp',
                options={
                    'rtsp_transport': 'tcp',
                },
            )
            
            # The stream will be created when first frame is submitted
            logger.info(f"MediaMTXPublisher({self.camera_id}): RTSP output opened to {url}")
            return True
            
        except Exception as e:
            logger.error(f"MediaMTXPublisher({self.camera_id}): Connection error: {e}")
            return False
    
    def submit_packet(self, packet_data: bytes) -> bool:
        """Submit a compressed packet to the publisher."""
        if self._state == PublisherState.STOPPED:
            self.start()
        
        if self._state not in (PublisherState.PUBLISHING, PublisherState.CONNECTED):
            self._metrics.packets_dropped += 1
            return False
        
        try:
            self._packet_queue.put_nowait(packet_data)
            return True
        except Exception:
            self._metrics.packets_dropped += 1
            # Drop oldest
            try:
                self._packet_queue.get_nowait()
            except Empty:
                pass
            try:
                self._packet_queue.put_nowait(packet_data)
                return True
            except Exception:
                return False
    
    def submit_av_packet(self, packet: Any) -> bool:
        """Submit a PyAV packet directly."""
        if self._state == PublisherState.STOPPED:
            self.start()
        
        if self._state not in (PublisherState.PUBLISHING, PublisherState.CONNECTED):
            self._metrics.packets_dropped += 1
            return False
        
        try:
            self._packet_queue.put_nowait(packet)
            return True
        except Exception:
            self._metrics.packets_dropped += 1
            return False
    
    def _publish_loop(self) -> None:
        """Publish loop - sends packets to MediaMTX via PyAV."""
        import av
        
        while not self._stop_event.is_set():
            try:
                # Check MediaMTX availability
                available = self._detect_media_server()
                self._metrics.media_server_available = available
                
                if not available:
                    self._set_state(PublisherState.MEDIA_SERVER_NOT_AVAILABLE)
                    logger.info(f"MediaMTXPublisher({self.camera_id}): MediaMTX unavailable")
                    time.sleep(self.config.reconnect_interval)
                    continue
                
                if self._state == PublisherState.MEDIA_SERVER_NOT_AVAILABLE:
                    self._set_state(PublisherState.RECONNECTING)
                    if self._connect():
                        self._set_state(PublisherState.PUBLISHING)
                        logger.info(f"MediaMTXPublisher({self.camera_id}): Reconnected to MediaMTX")
                    else:
                        self._set_state(PublisherState.DISCONNECTED)
                        time.sleep(self.config.reconnect_interval)
                        continue
                
                # Process packets
                try:
                    packet = self._packet_queue.get(timeout=0.1)
                    
                    if self._container is None:
                        continue
                    
                    # Mux packet
                    try:
                        self._container.mux(packet)
                        self._metrics.packets_published += 1
                        self._metrics.bytes_published += packet.size if hasattr(packet, 'size') else len(packet)
                        self._metrics.last_publish_time = time.time()
                    except Exception as mux_exc:
                        logger.error(f"MediaMTXPublisher({self.camera_id}): Mux error: {mux_exc}")
                        self._metrics.packets_dropped += 1
                        
                except Empty:
                    continue
                    
            except Exception as e:
                logger.error(f"MediaMTXPublisher({self.camera_id}): Publish loop error: {e}")
                time.sleep(0.5)
        
        logger.debug(f"MediaMTXPublisher({self.camera_id}): Publish loop exited")
    
    def reconnect(self) -> bool:
        """Attempt to reconnect to MediaMTX."""
        with self._lock:
            self._set_state(PublisherState.RECONNECTING)
            
            connected = self._connect()
            
            if connected:
                self._metrics.reconnect_attempts = 0
                self._set_state(PublisherState.PUBLISHING)
                logger.info(f"MediaMTXPublisher({self.camera_id}): Reconnected to MediaMTX")
                return True
            else:
                self._metrics.reconnect_attempts += 1
                self._set_state(PublisherState.DISCONNECTED)
                logger.info(f"MediaMTXPublisher({self.camera_id}): Reconnect failed")
                return False
    
    def stop(self) -> None:
        """Stop the publisher."""
        with self._lock:
            if self._state == PublisherState.STOPPED:
                return
            
            logger.info(f"MediaMTXPublisher({self.camera_id}): Stopping")
            self._stop_event.set()
            
            if self._publish_thread and self._publish_thread.is_alive():
                self._publish_thread.join(timeout=3.0)
            
            # Close container
            if self._container:
                try:
                    self._container.close()
                except Exception:
                    pass
                finally:
                    self._container = None
                    self._stream = None
            
            # Clear queue
            while not self._packet_queue.empty():
                try:
                    self._packet_queue.get_nowait()
                except Empty:
                    pass
            
            self._set_state(PublisherState.STOPPED)
            logger.info(f"MediaMTXPublisher({self.camera_id}): Stopped")
    
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "state": self._state.value,
                "packets_published": self._metrics.packets_published,
                "packets_dropped": self._metrics.packets_dropped,
                "bytes_published": self._metrics.bytes_published,
                "reconnect_attempts": self._metrics.reconnect_attempts,
                "media_server_available": self._metrics.media_server_available,
                "queue_depth": self._packet_queue.qsize(),
                "last_publish_time": self._metrics.last_publish_time,
                "mediamtx_host": self.config.mediamtx_host,
                "mediamtx_port": self.config.mediamtx_port,
                "mediamtx_path": self.config.mediamtx_path,
            }
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class FFmpegPublisher:
    """
    Alternative publisher using FFmpeg subprocess for RTSP publishing.
    
    More robust for some scenarios, uses stdin for packet input.
    """
    
    def __init__(self, config: PublisherConfig):
        self.config = config
        self.camera_id = config.camera_id
        self._process: Optional[subprocess.Popen] = None
        self._state = PublisherState.STOPPED
        self._metrics = PublisherMetrics()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
    
    def start(self) -> bool:
        """Start FFmpeg publisher."""
        with self._lock:
            if self._state != PublisherState.STOPPED:
                return True
            
            # Check MediaMTX
            if not self._detect_media_server():
                self._state = PublisherState.MEDIA_SERVER_NOT_AVAILABLE
                return False
            
            url = f"rtsp://{self.config.mediamtx_host}:{self.config.mediamtx_port}{self.config.mediamtx_path}"
            
            # FFmpeg command for H.264 passthrough to RTSP
            cmd = [
                "ffmpeg",
                "-y",
                "-f", "h264",
                "-i", "pipe:0",
                "-c", "copy",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                url,
            ]
            
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                
                self._state = PublisherState.PUBLISHING
                self._metrics.connection_time = time.time()
                
                # Start stderr reader
                threading.Thread(target=self._read_stderr, daemon=True).start()
                
                logger.info(f"FFmpegPublisher({self.camera_id}): Started publishing to {url}")
                return True
                
            except Exception as e:
                logger.error(f"FFmpegPublisher({self.camera_id}): Start failed: {e}")
                return False
    
    def _read_stderr(self) -> None:
        """Read FFmpeg stderr for error detection."""
        if self._process and self._process.stderr:
            for line in iter(self._process.stderr.readline, b''):
                if self._stop_event.is_set():
                    break
                logger.debug(f"FFmpegPublisher({self.camera_id}): {line.decode().strip()}")
    
    def submit_packet(self, packet_data: bytes) -> bool:
        """Submit packet to FFmpeg stdin."""
        with self._lock:
            if self._state != PublisherState.PUBLISHING or not self._process:
                self._metrics.packets_dropped += 1
                return False
            
            try:
                self._process.stdin.write(packet_data)
                self._process.stdin.flush()
                self._metrics.packets_published += 1
                self._metrics.bytes_published += len(packet_data)
                self._metrics.last_publish_time = time.time()
                return True
            except Exception as e:
                logger.error(f"FFmpegPublisher({self.camera_id}): Write error: {e}")
                self._metrics.packets_dropped += 1
                return False
    
    def stop(self) -> None:
        """Stop FFmpeg publisher."""
        with self._lock:
            if self._state == PublisherState.STOPPED:
                return
            
            logger.info(f"FFmpegPublisher({self.camera_id}): Stopping")
            self._stop_event.set()
            
            if self._process:
                try:
                    if self._process.stdin:
                        self._process.stdin.close()
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
                finally:
                    self._process = None
            
            self._state = PublisherState.STOPPED
            logger.info(f"FFmpegPublisher({self.camera_id}): Stopped")
    
    def _detect_media_server(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex((self.config.mediamtx_host, self.config.mediamtx_port))
            sock.close()
            return result == 0
        except Exception:
            return False


def create_publisher(
    camera_id: str,
    config: Optional[Dict[str, Any]] = None,
    use_ffmpeg: bool = False,
) -> MediaMTXPublisher:
    """Factory function to create publisher."""
    if config is None:
        from pipeline_engine.config import get_config, get_camera_config
        config = get_camera_config(get_config(), camera_id)
    
    output_config = config.get("output", {})
    
    publisher_config = PublisherConfig(
        camera_id=camera_id,
        mediamtx_host="localhost",
        mediamtx_port=8554,
        mediamtx_path=f"/{output_config.get('path', f'live/{camera_id}-ai')}",
    )
    
    if use_ffmpeg:
        return FFmpegPublisher(publisher_config)
    else:
        return MediaMTXPublisher(publisher_config)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    publisher = create_publisher("test_cam")
    
    if publisher.start():
        print("Publisher started!")
        print(f"Metrics: {publisher.get_metrics()}")
        
        # Submit test packet
        test_packet = b"\x00\x00\x00\x01\x09\x10"  # Minimal H.264 header
        result = publisher.submit_packet(test_packet)
        print(f"Packet submitted: {result}")
        
        time.sleep(2)
        publisher.stop()
        print("Publisher test completed!")
    else:
        print("Publisher start failed (expected without running MediaMTX)")