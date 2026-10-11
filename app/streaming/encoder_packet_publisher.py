#!/usr/bin/env python
"""
Integration contract layer: adapter packets -> FFmpeg stdin (no CPU BGR / no synthetic packets).
Uses adapter packets (Dict {data: bytes}) and feeds them directly to FFmpeg as elementary H.264 bitstream.
No PyAV, no CPU BGR, no synthetic packets, no replay.

Phase 12.2: Added comprehensive instrumentation for A/B benchmark.
"""
from __future__ import annotations
import logging
import subprocess
import threading
import time
import os
import statistics
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class BridgePacketMetrics:
    """Metrics for packet-level operations."""
    packets_submitted: int = 0
    packets_accepted: int = 0
    packets_failed: int = 0
    total_bytes_submitted: int = 0
    total_bytes_accepted: int = 0
    packet_sizes: deque = field(default_factory=lambda: deque(maxlen=10000))
    write_latencies_ms: deque = field(default_factory=lambda: deque(maxlen=10000))
    queue_depth: int = 0
    queue_high_water_mark: int = 0
    ordering_errors: int = 0
    pts_discontinuities: int = 0
    last_pts: Optional[int] = None
    last_dts: Optional[int] = None


@dataclass
class BridgePipeMetrics:
    """Metrics for pipe-level operations."""
    write_operations: int = 0
    total_bytes_written: int = 0
    write_durations_ms: deque = field(default_factory=lambda: deque(maxlen=10000))
    blocking_events: int = 0
    blocking_duration_ms: float = 0.0
    max_blocking_duration_ms: float = 0.0
    eagain_events: int = 0
    broken_pipe_events: int = 0
    pipe_closure_events: int = 0
    backpressure_events: int = 0


@dataclass
class BridgeProcessMetrics:
    """Metrics for FFmpeg process."""
    cpu_percent_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    ram_mb_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    thread_count_samples: deque = field(default_factory=lambda: deque(maxlen=1000))
    context_switches: int = 0
    process_restarts: int = 0


@dataclass
class BridgeMetrics:
    """Complete metrics for the bridge."""
    packet: BridgePacketMetrics = field(default_factory=BridgePacketMetrics)
    pipe: BridgePipeMetrics = field(default_factory=BridgePipeMetrics)
    process: BridgeProcessMetrics = field(default_factory=BridgeProcessMetrics)
    started_at: float = 0.0
    last_report_at: float = 0.0


class EncoderPacketToPublisherBridge:
    """
    Minimal adapter-to-publisher contract layer.
    Receives adapter packet dictionaries and feeds them to an FFmpeg subprocess
    as an elementary H.264 stream (no CPU BGR conversion, no re-encode when possible).
    
    Phase 12.2: Added comprehensive instrumentation for performance benchmarking.
    Phase 12.1: Added RTSP connection monitoring and automatic reconnection.
    """

    def __init__(
        self, 
        rtsp_url: str = "rtsp://localhost:8554/live/cam1-ai", 
        width: int = 384, 
        height: int = 216, 
        fps: float = 15.0,
        enable_instrumentation: bool = True,
        auto_reconnect: bool = True,
        reconnect_interval: float = 2.0,
        max_reconnect_attempts: int = 10,
    ):
        self.rtsp_url = rtsp_url
        self.width = width
        self.height = height
        self.fps = fps
        self.enable_instrumentation = enable_instrumentation
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.proc: Optional[subprocess.Popen] = None
        self.started = False
        self.pid: Optional[int] = None
        self._reconnect_attempts = 0
        self._reconnecting = False
        self._reconnect_lock = threading.Lock()
        self._stop_reconnect = threading.Event()
        self._reconnect_thread: Optional[threading.Thread] = None
        
        # Instrumentation
        self._metrics = BridgeMetrics()
        self._metrics.started_at = time.time()
        self._metrics.last_report_at = time.time()
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        
        # Internal packet queue for backpressure measurement
        self._packet_queue: deque = deque(maxlen=1000)
        self._queue_lock = threading.Lock()

    def start(self, bitrate_kbps: int = 2500, gop_seconds: float = 1.0) -> bool:
        return self._start_ffmpeg(bitrate_kbps, gop_seconds)

    def _start_ffmpeg(self, bitrate_kbps: int = 2500, gop_seconds: float = 1.0) -> bool:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            # Input as H.264 elementary stream directly (adapter packets are real H.264 bytes)
            # Use copy mode to pass through H.264 without re-encoding
            # -use_wallclock_as_timestamps 1 uses wall clock for timestamps
            "-use_wallclock_as_timestamps", "1",
            "-fflags", "+genpts",
            "-f", "h264",
            "-framerate", str(int(self.fps)),
            "-i", "pipe:0",
            "-an",
            # Pass through without re-encoding (copy mode)
            "-c:v", "copy",
            "-muxdelay", "0",
            "-muxpreload", "0",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            self.rtsp_url,
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env={**os.environ, "AV_LOG_FORCE_NOCOLOR": "1"},
            )
            self.started = True
            self.pid = self.proc.pid
            logger.info("EncoderPacketBridge: started pid=%d url=%s", self.pid, self.rtsp_url)
            
            # Start stderr drain thread
            threading.Thread(
                target=self._drain_stderr,
                name=f"adapter-bridge-stderr-{self.pid}",
                daemon=True,
            ).start()
            
            # Start process monitoring thread if instrumentation enabled
            if self.enable_instrumentation:
                self._stop_monitor.clear()
                self._monitor_thread = threading.Thread(
                    target=self._monitor_process,
                    name=f"adapter-bridge-monitor-{self.pid}",
                    daemon=True,
                )
                self._monitor_thread.start()
            
            return True
        except Exception as e:
            logger.error("EncoderPacketBridge: failed to start FFmpeg: %s", e)
            return False

    def _reconnect_ffmpeg(self) -> bool:
        """Attempt to reconnect FFmpeg process."""
        if not self.auto_reconnect:
            return False
            
        with self._reconnect_lock:
            if self._reconnecting:
                logger.debug("EncoderPacketBridge: reconnect already in progress")
                return False
            
            if self._reconnect_attempts >= self.max_reconnect_attempts:
                logger.error("EncoderPacketBridge: max reconnect attempts reached (%d)", 
                            self.max_reconnect_attempts)
                return False
            
            self._reconnecting = True
            self._reconnect_attempts += 1
            
        try:
            logger.info("EncoderPacketBridge: attempting reconnect (attempt %d/%d)", 
                       self._reconnect_attempts, self.max_reconnect_attempts)
            
            # Close existing process if any
            if self.proc:
                try:
                    if self.proc.stdin and not self.proc.stdin.closed:
                        self.proc.stdin.close()
                except Exception:
                    pass
                try:
                    self.proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
            
            # Wait before reconnecting
            time.sleep(self.reconnect_interval)
            
            # Start new FFmpeg process
            success = self._start_ffmpeg()
            if success:
                self._reconnect_attempts = 0  # Reset on success
                logger.info("EncoderPacketBridge: reconnect successful")
            else:
                logger.error("EncoderPacketBridge: reconnect failed")
            return success
        finally:
            self._reconnecting = False

    def submit_packet_bytes(self, packet_bytes: bytes) -> int:
        if not self.started or self.proc is None or self.proc.stdin is None:
            # Try to reconnect if auto_reconnect is enabled
            if self.auto_reconnect and not self._reconnecting:
                self._attempt_reconnect_async()
            return 0
        if self.proc.poll() is not None:
            logger.warning("Adapter bridge: FFmpeg process died unexpectedly.")
            # Try to reconnect
            if self.auto_reconnect:
                self._attempt_reconnect_async()
            return 0
        
        write_start = time.perf_counter()
        try:
            self.proc.stdin.write(packet_bytes)
            write_duration_ms = (time.perf_counter() - write_start) * 1000
            
            if self.enable_instrumentation:
                with self._lock:
                    self._metrics.packet.packets_submitted += 1
                    self._metrics.packet.packets_accepted += 1
                    self._metrics.packet.total_bytes_submitted += len(packet_bytes)
                    self._metrics.packet.total_bytes_accepted += len(packet_bytes)
                    self._metrics.packet.packet_sizes.append(len(packet_bytes))
                    self._metrics.packet.write_latencies_ms.append(write_duration_ms)
                    self._metrics.packet.queue_depth = len(self._packet_queue)
                    if self._metrics.packet.queue_depth > self._metrics.packet.queue_high_water_mark:
                        self._metrics.packet.queue_high_water_mark = self._metrics.packet.queue_depth
                    
                    self._metrics.pipe.write_operations += 1
                    self._metrics.pipe.total_bytes_written += len(packet_bytes)
                    self._metrics.pipe.write_durations_ms.append(write_duration_ms)
            
            return len(packet_bytes)
        except BrokenPipeError as exc:
            if self.enable_instrumentation:
                with self._lock:
                    self._metrics.packet.packets_failed += 1
                    self._metrics.pipe.broken_pipe_events += 1
            logger.error("Adapter bridge: stdin write failed (broken pipe): %s", exc)
            # Try to reconnect
            if self.auto_reconnect:
                self._attempt_reconnect_async()
            return 0
        except OSError as exc:
            if self.enable_instrumentation:
                with self._lock:
                    self._metrics.packet.packets_failed += 1
                    if exc.errno == 11 or exc.errno == 35:  # EAGAIN / EWOULDBLOCK
                        self._metrics.pipe.eagain_events += 1
                    self._metrics.pipe.blocking_events += 1
            logger.error("Adapter bridge: stdin write failed: %s", exc)
            # Try to reconnect
            if self.auto_reconnect:
                self._attempt_reconnect_async()
            return 0

    def _attempt_reconnect_async(self):
        """Attempt reconnection in a background thread."""
        if self._reconnecting:
            return
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_ffmpeg,
            name=f"adapter-bridge-reconnect-{self.pid}",
            daemon=True,
        )
        self._reconnect_thread.start()

    def submit_adapter_packets(self, packets: List[Dict[str, Any]]) -> int:
        total_bytes = 0
        for pkt in packets:
            data = pkt.get("data", b"")
            if isinstance(data, (bytes, bytearray)):
                total_bytes += self.submit_packet_bytes(bytes(data))
            else:
                # Packet dict format verified: must contain bytes; skip non-bytes defensively
                logger.warning("Adapter bridge: packet 'data' is not bytes; skipped.")
        return total_bytes

    def submit_bitstream_bytes(self, bitstream_bytes: bytes) -> int:
        return self.submit_packet_bytes(bitstream_bytes)

    def close(self) -> None:
        self._stop_monitor.set()
        self._stop_reconnect.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=5.0)
        
        if self.proc is not None:
            try:
                if self.proc.stdin and not self.proc.stdin.closed:
                    self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.started = False
            logger.info("EncoderPacketBridge: stopped pid=%s", self.pid)

    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics snapshot."""
        with self._lock:
            m = self._metrics
            now = time.time()
            elapsed = now - m.started_at
            
            # Calculate percentiles for write latencies
            write_latencies = list(m.pipe.write_durations_ms)
            packet_latencies = list(m.packet.write_latencies_ms)
            packet_sizes = list(m.packet.packet_sizes)
            
            def percentile(data: List[float], p: float) -> float:
                if not data:
                    return 0.0
                sorted_data = sorted(data)
                idx = int(len(sorted_data) * p / 100)
                return sorted_data[min(idx, len(sorted_data) - 1)]
            
            return {
                "bridge_uptime_seconds": elapsed,
                "camera": self.rtsp_url,
                "pid": self.pid,
                "started": self.started,
                "ffmpeg_alive": self.proc.poll() is None if self.proc else False,
                
                # Packet metrics
                "packets_per_second": m.packet.packets_accepted / elapsed if elapsed > 0 else 0,
                "bytes_per_second": m.packet.total_bytes_accepted / elapsed if elapsed > 0 else 0,
                "avg_packet_size_bytes": statistics.mean(packet_sizes) if packet_sizes else 0,
                "max_packet_size_bytes": max(packet_sizes) if packet_sizes else 0,
                "min_packet_size_bytes": min(packet_sizes) if packet_sizes else 0,
                "p50_write_latency_ms": percentile(packet_latencies, 50),
                "p95_write_latency_ms": percentile(packet_latencies, 95),
                "p99_write_latency_ms": percentile(packet_latencies, 99),
                "max_write_latency_ms": max(packet_latencies) if packet_latencies else 0,
                "queue_high_water_mark": m.packet.queue_high_water_mark,
                "current_queue_depth": m.packet.queue_depth,
                "packets_failed": m.packet.packets_failed,
                
                # Pipe metrics
                "total_write_operations": m.pipe.write_operations,
                "total_bytes_written": m.pipe.total_bytes_written,
                "p50_pipe_write_ms": percentile(write_latencies, 50),
                "p95_pipe_write_ms": percentile(write_latencies, 95),
                "p99_pipe_write_ms": percentile(write_latencies, 99),
                "max_pipe_write_ms": max(write_latencies) if write_latencies else 0,
                "blocking_events": m.pipe.blocking_events,
                "total_blocking_duration_ms": m.pipe.blocking_duration_ms,
                "max_blocking_duration_ms": m.pipe.max_blocking_duration_ms,
                "eagain_events": m.pipe.eagain_events,
                "broken_pipe_events": m.pipe.broken_pipe_events,
                "pipe_closure_events": m.pipe.pipe_closure_events,
                "backpressure_events": m.pipe.backpressure_events,
                
                # Process metrics
                "avg_cpu_percent": statistics.mean(m.process.cpu_percent_samples) if m.process.cpu_percent_samples else 0,
                "peak_cpu_percent": max(m.process.cpu_percent_samples) if m.process.cpu_percent_samples else 0,
                "avg_ram_mb": statistics.mean(m.process.ram_mb_samples) if m.process.ram_mb_samples else 0,
                "peak_ram_mb": max(m.process.ram_mb_samples) if m.process.ram_mb_samples else 0,
                "thread_count": m.process.thread_count_samples[-1] if m.process.thread_count_samples else 0,
                "process_restarts": m.process.process_restarts,
            }

    def _monitor_process(self) -> None:
        """Monitor FFmpeg process CPU and memory usage."""
        import psutil
        try:
            process = psutil.Process(self.pid)
            while not self._stop_monitor.is_set() and self.started:
                try:
                    if not process.is_running():
                        break
                    cpu = process.cpu_percent(interval=0.1)
                    mem = process.memory_info().rss / (1024 * 1024)  # MB
                    threads = process.num_threads()
                    
                    with self._lock:
                        self._metrics.process.cpu_percent_samples.append(cpu)
                        self._metrics.process.ram_mb_samples.append(mem)
                        self._metrics.process.thread_count_samples.append(threads)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break
                time.sleep(1.0)
        except Exception as e:
            logger.debug("Process monitor error: %s", e)

    def _drain_stderr(self) -> None:
        if self.proc is None or self.proc.stderr is None:
            return
        try:
            for line in iter(self.proc.stderr.readline, b""):
                if not line:
                    break
                msg = line.decode("utf-8", errors="replace").rstrip()
                if msg:
                    logger.debug("AdapterBridge-FFmpeg: %s", msg)
                    # Track pipe closure events
                    if "broken pipe" in msg.lower() or "connection reset" in msg.lower():
                        with self._lock:
                            self._metrics.pipe.pipe_closure_events += 1
        except Exception:
            pass

    def reset_metrics(self) -> None:
        """Reset all metrics (useful for test isolation)."""
        with self._lock:
            self._metrics = BridgeMetrics()
            self._metrics.started_at = time.time()
            self._metrics.last_report_at = time.time()
