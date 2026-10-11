"""
Packet Input - V2 GPU-first video pipeline.

Handles RTMP/RTSP compressed packet input without CPU frame decoding.
Produces compressed packets for NVDEC decoder.
"""

from __future__ import annotations

import logging
import threading
import queue
import time
import socket
import select
from dataclasses import dataclass, field
from typing import Optional, Any, Iterator, Dict, List
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PacketType(str, Enum):
    """Types of compressed packets."""
    H264_NAL = "h264_nal"
    H265_NAL = "h265_nal"
    AAC_ADTS = "aac_adts"
    UNKNOWN = "unknown"


@dataclass
class CompressedPacket:
    """Compressed video/audio packet for GPU decoder."""
    data: bytes
    pts: Optional[int] = None
    dts: Optional[int] = None
    packet_type: PacketType = PacketType.H264_NAL
    is_keyframe: bool = False
    stream_index: int = 0
    timestamp: float = 0.0  # Wall-clock receive time
    camera_id: str = ""
    sequence: int = 0
    
    def __len__(self) -> int:
        return len(self.data)


class PacketSource(ABC):
    """Abstract base for packet sources (RTMP, RTSP, file, etc.)."""
    
    @abstractmethod
    def open(self) -> None:
        """Open the source."""
        pass
    
    @abstractmethod
    def read_packet(self, timeout: float = 1.0) -> Optional[CompressedPacket]:
        """Read next packet. Returns None on timeout."""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the source."""
        pass
    
    @property
    @abstractmethod
    def is_open(self) -> bool:
        """Check if source is open."""
        pass


@dataclass
class RTSPSourceConfig:
    """Configuration for RTSP packet source."""
    camera_id: str
    rtsp_url: str
    transport: str = "tcp"  # tcp, udp, udp_multicast
    timeout: float = 10.0
    buffer_size: int = 1024 * 1024  # 1MB socket buffer
    rtsp_transport_options: Dict[str, str] = field(default_factory=dict)


class RTSPSource(PacketSource):
    """
    RTSP packet source using PyAV for protocol handling.
    Extracts compressed H.264 NAL units without decoding.
    """
    
    def __init__(self, config: RTSPSourceConfig):
        self.config = config
        self._container = None
        self._stream = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._packet_queue: "queue.Queue[CompressedPacket]" = queue.Queue(maxsize=100)
        self._packet_sequence = 0
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
    
    @property
    def url(self) -> str:
        """Return the RTSP URL for compatibility with decoder."""
        return self.config.rtsp_url
    
    def open(self) -> None:
        """Open RTSP connection and start packet reader."""
        import av
        
        with self._lock:
            if self._container is not None:
                return
            
            logger.info(f"RTSPSource({self.config.camera_id}): opening {self.config.rtsp_url}")
            
            options = {
                "rtsp_transport": self.config.transport,
                "buffer_size": str(self.config.buffer_size),
                **self.config.rtsp_transport_options,
            }
            
            self._container = av.open(
                self.config.rtsp_url,
                format="rtsp",
                options=options,
            )
            
            # Find video stream
            video_streams = [s for s in self._container.streams if s.type == "video"]
            if not video_streams:
                raise RuntimeError(f"No video stream found in {self.config.rtsp_url}")
            
            self._stream = video_streams[0]
            logger.info(f"RTSPSource({self.config.camera_id}): video stream {self._stream.index}, codec={self._stream.codec_context.name}")
            
            # Start reader thread
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"rtsp-reader-{self.config.camera_id}",
                daemon=True,
            )
            self._reader_thread.start()
    
    def _reader_loop(self) -> None:
        """Read packets from RTSP and queue them."""
        import av
        
        try:
            for packet in self._container.demux(self._stream):
                if self._stop_event.is_set():
                    break
                
                if packet.size <= 0:
                    continue
                
                # Check for keyframe
                is_keyframe = packet.is_keyframe
                
                # Create compressed packet
                comp_packet = CompressedPacket(
                    data=bytes(packet),
                    pts=packet.pts,
                    dts=packet.dts,
                    packet_type=PacketType.H264_NAL if "h264" in self._stream.codec_context.name.lower() else PacketType.H265_NAL,
                    is_keyframe=is_keyframe,
                    stream_index=packet.stream.index,
                    timestamp=time.time(),
                    camera_id=self.config.camera_id,
                    sequence=self._packet_sequence,
                )
                self._packet_sequence += 1
                
                # Queue with drop-oldest policy
                try:
                    self._packet_queue.put_nowait(comp_packet)
                except queue.Full:
                    try:
                        self._packet_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._packet_queue.put_nowait(comp_packet)
                    except queue.Full:
                        pass
                        
        except av.error.FFmpegError as e:
            logger.error(f"RTSPSource({self.config.camera_id}): FFmpeg error: {e}")
            self._error = e
        except Exception as e:
            logger.error(f"RTSPSource({self.config.camera_id}): Reader error: {e}")
            self._error = e
        finally:
            logger.debug(f"RTSPSource({self.config.camera_id}): Reader loop exited")
    
    def read_packet(self, timeout: float = 1.0) -> Optional[CompressedPacket]:
        """Read next compressed packet."""
        if not self.is_open:
            self.open()
        
        try:
            return self._packet_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def close(self) -> None:
        """Close RTSP connection."""
        with self._lock:
            self._stop_event.set()
            
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3.0)
            
            if self._container:
                try:
                    self._container.close()
                except Exception as e:
                    logger.debug(f"RTSPSource({self.config.camera_id}): Close error: {e}")
                finally:
                    self._container = None
                    self._stream = None
            
            # Clear queue
            while True:
                try:
                    self._packet_queue.get_nowait()
                except queue.Empty:
                    break
    
    @property
    def is_open(self) -> bool:
        return self._container is not None
    
    @property
    def error(self) -> Optional[Exception]:
        return self._error
    
    def get_queue_depth(self) -> int:
        return self._packet_queue.qsize()


@dataclass
class RTMPSourceConfig:
    """Configuration for RTMP packet source."""
    camera_id: str
    rtmp_url: str
    timeout: float = 10.0
    buffer_size: int = 1024 * 1024


class RTMPSource(PacketSource):
    """
    RTMP packet source using PyAV.
    Extracts compressed H.264 NAL units from FLV/RTMP stream.
    """
    
    def __init__(self, config: RTMPSourceConfig):
        self.config = config
        self._container = None
        self._stream = None
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._packet_queue: "queue.Queue[CompressedPacket]" = queue.Queue(maxsize=100)
        self._packet_sequence = 0
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
    
    @property
    def url(self) -> str:
        """Return the RTMP URL for compatibility with decoder."""
        return self.config.rtmp_url
    
    def open(self) -> None:
        """Open RTMP connection."""
        import av
        
        with self._lock:
            if self._container is not None:
                return
            
            logger.info(f"RTMPSource({self.config.camera_id}): opening {self.config.rtmp_url}")
            
            options = {
                "rtmp_buffer": "100",
            }
            
            self._container = av.open(
                self.config.rtmp_url,
                format="flv",
                options=options,
            )
            
            video_streams = [s for s in self._container.streams if s.type == "video"]
            if not video_streams:
                raise RuntimeError(f"No video stream found in {self.config.rtmp_url}")
            
            self._stream = video_streams[0]
            logger.info(f"RTMPSource({self.config.camera_id}): video stream {self._stream.index}, codec={self._stream.codec_context.name}")
            
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name=f"rtmp-reader-{self.config.camera_id}",
                daemon=True,
            )
            self._reader_thread.start()
    
    def _reader_loop(self) -> None:
        import av
        
        try:
            for packet in self._container.demux(self._stream):
                if self._stop_event.is_set():
                    break
                
                if packet.size <= 0:
                    continue
                
                is_keyframe = packet.is_keyframe
                
                comp_packet = CompressedPacket(
                    data=bytes(packet),
                    pts=packet.pts,
                    dts=packet.dts,
                    packet_type=PacketType.H264_NAL if "h264" in self._stream.codec_context.name.lower() else PacketType.H265_NAL,
                    is_keyframe=is_keyframe,
                    stream_index=packet.stream.index,
                    timestamp=time.time(),
                    camera_id=self.config.camera_id,
                    sequence=self._packet_sequence,
                )
                self._packet_sequence += 1
                
                try:
                    self._packet_queue.put_nowait(comp_packet)
                except queue.Full:
                    try:
                        self._packet_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._packet_queue.put_nowait(comp_packet)
                    except queue.Full:
                        pass
                        
        except av.error.FFmpegError as e:
            logger.error(f"RTMPSource({self.config.camera_id}): FFmpeg error: {e}")
            self._error = e
        except Exception as e:
            logger.error(f"RTMPSource({self.config.camera_id}): Reader error: {e}")
            self._error = e
        finally:
            logger.debug(f"RTMPSource({self.config.camera_id}): Reader loop exited")
    
    def read_packet(self, timeout: float = 1.0) -> Optional[CompressedPacket]:
        if not self.is_open:
            self.open()
        
        try:
            return self._packet_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def close(self) -> None:
        with self._lock:
            self._stop_event.set()
            
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3.0)
            
            if self._container:
                try:
                    self._container.close()
                except Exception as e:
                    logger.debug(f"RTMPSource({self.config.camera_id}): Close error: {e}")
                finally:
                    self._container = None
                    self._stream = None
            
            while True:
                try:
                    self._packet_queue.get_nowait()
                except queue.Empty:
                    break
    
    @property
    def is_open(self) -> bool:
        return self._container is not None
    
    @property
    def error(self) -> Optional[Exception]:
        return self._error
    
    def get_queue_depth(self) -> int:
        return self._packet_queue.qsize()


@dataclass
class FileSourceConfig:
    """Configuration for file packet source."""
    camera_id: str
    file_path: str
    loop: bool = False
    read_rate: float = 0.0  # 0 = as fast as possible


class FileSource(PacketSource):
    """File packet source for testing (reads compressed packets from file)."""
    
    def __init__(self, config: FileSourceConfig):
        self.config = config
        self._container = None
        self._stream = None
        self._packet_iter = None
        self._error: Optional[Exception] = None
        self._lock = threading.Lock()
        self._sequence = 0
    
    @property
    def url(self) -> str:
        """Return the file path as URL for compatibility with decoder."""
        return self.config.file_path
    
    def open(self) -> None:
        import av
        
        with self._lock:
            if self._container is not None:
                return
            
            logger.info(f"FileSource({self.config.camera_id}): opening {self.config.file_path}")
            
            self._container = av.open(self.config.file_path)
            video_streams = [s for s in self._container.streams if s.type == "video"]
            if not video_streams:
                raise RuntimeError(f"No video stream in {self.config.file_path}")
            self._stream = video_streams[0]
            self._packet_iter = self._container.demux(self._stream)
    
    def read_packet(self, timeout: float = 1.0) -> Optional[CompressedPacket]:
        if not self.is_open:
            self.open()
        
        import av
        
        try:
            packet = next(self._packet_iter)
        except StopIteration:
            if self.config.loop:
                self._container.seek(0)
                self._packet_iter = self._container.demux(self._stream)
                try:
                    packet = next(self._packet_iter)
                except StopIteration:
                    return None
            else:
                return None
        except Exception as e:
            self._error = e
            return None
        
        if packet.size <= 0:
            return self.read_packet(timeout)  # Recurse for next
        
        comp_packet = CompressedPacket(
            data=bytes(packet),
            pts=packet.pts,
            dts=packet.dts,
            packet_type=PacketType.H264_NAL if "h264" in self._stream.codec_context.name.lower() else PacketType.H265_NAL,
            is_keyframe=packet.is_keyframe,
            stream_index=packet.stream.index,
            timestamp=time.time(),
            camera_id=self.config.camera_id,
            sequence=self._sequence,
        )
        self._sequence += 1
        
        if self.config.read_rate > 0:
            time.sleep(1.0 / self.config.read_rate)
        
        return comp_packet
    
    def close(self) -> None:
        with self._lock:
            if self._container:
                try:
                    self._container.close()
                except Exception:
                    pass
                self._container = None
                self._stream = None
                self._packet_iter = None
    
    @property
    def is_open(self) -> bool:
        return self._container is not None
    
    @property
    def error(self) -> Optional[Exception]:
        return self._error


def create_packet_source(
    source_type: str,
    camera_id: str,
    url: str,
    **kwargs,
) -> PacketSource:
    """Factory function to create packet source."""
    source_type = source_type.lower()
    
    if source_type == "rtsp":
        config = RTSPSourceConfig(camera_id=camera_id, rtsp_url=url, **kwargs)
        return RTSPSource(config)
    elif source_type == "rtmp":
        config = RTMPSourceConfig(camera_id=camera_id, rtmp_url=url, **kwargs)
        return RTMPSource(config)
    elif source_type == "file":
        config = FileSourceConfig(camera_id=camera_id, file_path=url, **kwargs)
        return FileSource(config)
    else:
        raise ValueError(f"Unknown source type: {source_type}")


class PacketInput:
    """
    High-level packet input manager.
    Manages multiple packet sources and provides unified packet stream.
    """
    
    def __init__(self, camera_id: str, source_type: str, url: str, **kwargs):
        self.camera_id = camera_id
        self.source_type = source_type
        self.url = url
        self.source = create_packet_source(source_type, camera_id, url, **kwargs)
        self._running = False
        self._stats = {
            "packets_received": 0,
            "packets_dropped": 0,
            "keyframes": 0,
            "errors": 0,
            "start_time": 0.0,
        }
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """Start packet input."""
        with self._lock:
            if self._running:
                return
            self.source.open()
            self._running = True
            self._stats["start_time"] = time.time()
            logger.info(f"PacketInput({self.camera_id}): started")
    
    def read_packet(self, timeout: float = 1.0) -> Optional[CompressedPacket]:
        """Read next packet."""
        if not self._running:
            self.start()
        
        packet = self.source.read_packet(timeout)
        if packet:
            with self._lock:
                self._stats["packets_received"] += 1
                if packet.is_keyframe:
                    self._stats["keyframes"] += 1
        return packet
    
    def stop(self) -> None:
        """Stop packet input."""
        with self._lock:
            if not self._running:
                return
            self.source.close()
            self._running = False
            logger.info(f"PacketInput({self.camera_id}): stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            stats = self._stats.copy()
            stats["running"] = self._running
            stats["uptime"] = time.time() - stats["start_time"] if stats["start_time"] > 0 else 0
            stats["queue_depth"] = self.source.get_queue_depth() if hasattr(self.source, "get_queue_depth") else 0
            return stats
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    @property
    def error(self) -> Optional[Exception]:
        return self.source.error
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


if __name__ == "__main__":
    # Test with a local file
    import sys
    
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        source = create_packet_source("file", "test_cam", test_file)
        source.open()
        
        count = 0
        for _ in range(10):
            pkt = source.read_packet(2.0)
            if pkt:
                print(f"Packet {count}: {len(pkt.data)} bytes, keyframe={pkt.is_keyframe}, pts={pkt.pts}")
                count += 1
            else:
                break
        
        source.close()
        print(f"Read {count} packets")
    else:
        print("Usage: python packet_input.py <video_file>")