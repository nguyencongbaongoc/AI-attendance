"""
MediaMTX Readiness Checker - Extracted for testability.
This is the core readiness logic separated from BootstrapOrchestrator.
"""

import time
import requests
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable
from av.codec.hwaccel import HWAccel


@dataclass
class CameraReadinessState:
    """Per-camera readiness tracking."""
    path_name: str
    ready: bool = False
    has_h264: bool = False
    last_bytes: int = 0
    consecutive_increases: int = 0
    stable_since: Optional[float] = None
    publisher_stable: bool = False
    rtsp_verified: bool = False
    rtsp_verified_at: Optional[float] = None
    post_rtsp_stable: bool = False
    bytes_history: List[tuple] = field(default_factory=list)
    _last_logged_publisher_stable: bool = False


class MediaMTXReadinessChecker:
    """
    Standalone MediaMTX readiness checker.
    
    Can be used by BootstrapOrchestrator and tested independently.
    """
    
    def __init__(
        self,
        api_port: int,
        rtsp_port: int,
        time_func: Callable[[], float] = time.time,
        sleep_func: Callable[[float], None] = time.sleep,
        log_func: Callable[[str], None] = print,
    ):
        self.api_port = api_port
        self.rtsp_port = rtsp_port
        self._time = time_func
        self._sleep = sleep_func
        self._log = log_func
        
        # Configuration
        self.consecutive_required = 5
        self.min_bytes_progress_interval = 5.0
        self.min_publisher_stable_time = 30.0
        self.min_post_rtsp_stable_time = 5.0
        self.stabilization_delay = 0.5
        self.per_camera_publisher_timeout = 90.0
        self.rtsp_verification_window = 30.0
        
    def wait_ready(self, max_wait: float = 180.0) -> bool:
        """
        Wait for MediaMTX to be fully ready.
        
        Returns True if both cameras reach FULLY_READY state.
        Returns False on any timeout or failure.
        """
        # Initialize per-camera state
        cam_states = {
            "live/cam1": CameraReadinessState("live/cam1"),
            "live/cam2": CameraReadinessState("live/cam2"),
        }
        
        # Timeout deadlines
        global_start = self._time()
        global_deadline = global_start + max_wait
        per_camera_publisher_deadline = global_start + self.per_camera_publisher_timeout
        rtsp_deadline: Optional[float] = None
        
        # Phase tracking
        publisher_layer_ready = False
        rtsp_phase_started = False
        
        self._log(f"[BOOT] MediaMTX readiness: global_timeout={max_wait}s, per_camera_publisher_timeout={self.per_camera_publisher_timeout}s")
        self._log(f"[BOOT] Required: both cameras publisher_stable ({self.min_publisher_stable_time}s) + RTSP verified + {self.min_post_rtsp_stable_time}s post-RTSP stable")
        
        while self._time() < global_deadline:
            current_time = self._time()
            elapsed = current_time - global_start
            
            try:
                # Check MediaMTX API endpoint
                resp = requests.get(f"http://127.0.0.1:{self.api_port}/v3/paths/list", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    paths = [item.get("name", "") for item in items]
                    
                    # Check per-camera publisher deadlines
                    for cam_state in cam_states.values():
                        if not cam_state.publisher_stable and current_time > per_camera_publisher_deadline:
                            self._log_camera_state(cam_state, "PUBLISHER_TIMEOUT")
                            self._log(f"[BOOT] MediaMTX readiness: FAIL - {cam_state.path_name} publisher timeout (stable_for={(current_time - cam_state.stable_since) if cam_state.stable_since else 0:.1f}s < {self.min_publisher_stable_time}s)")
                            return False
                    
                    # Step 1: Update publisher readiness for each camera
                    all_publisher_stable = True
                    for required_path in ("live/cam1", "live/cam2"):
                        cam_state = cam_states[required_path]
                        path_info = next((item for item in items if item.get("name") == required_path), None)
                        
                        if path_info is None:
                            # Path not present yet - reset state
                            if cam_state.ready:
                                self._log(f"[BOOT] {required_path}: LOST - path disappeared from API")
                                self._reset_camera_publisher_state(cam_state)
                            all_publisher_stable = False
                            continue
                        
                        # Update basic info
                        cam_state.ready = path_info.get("ready", False)
                        tracks = path_info.get("tracks", [])
                        bytes_received = path_info.get("bytesReceived", 0)
                        cam_state.last_bytes = bytes_received
                        cam_state.has_h264 = any("H264" in t.upper() or "H.264" in t.upper() or "264" in t.upper() for t in tracks)
                        
                        # Track bytes history (keep last 5 samples)
                        cam_state.bytes_history.append((current_time, bytes_received))
                        cam_state.bytes_history = cam_state.bytes_history[-5:]
                        
                        # Check bytes increasing
                        bytes_increasing = False
                        if len(cam_state.bytes_history) >= 2:
                            if cam_state.bytes_history[-1][1] > cam_state.bytes_history[-2][1]:
                                cam_state.consecutive_increases += 1
                            else:
                                cam_state.consecutive_increases = 0
                                cam_state.stable_since = None
                            
                            if cam_state.consecutive_increases >= self.consecutive_required:
                                bytes_increasing = True
                                if cam_state.stable_since is None:
                                    cam_state.stable_since = current_time
                        else:
                            cam_state.consecutive_increases = 0
                            cam_state.stable_since = None
                        
                        # Stall detection
                        time_since_progress = 0.0
                        if cam_state.bytes_history:
                            time_since_progress = current_time - cam_state.bytes_history[0][0]
                        if time_since_progress > self.min_bytes_progress_interval and cam_state.consecutive_increases == 0:
                            self._log(f"[BOOT] {required_path}: STALLED - no bytes progress for {time_since_progress:.1f}s (bytesReceived={bytes_received})")
                            cam_state.consecutive_increases = 0
                            cam_state.stable_since = None
                        
                        # Check publisher stability
                        if bytes_increasing and cam_state.stable_since is not None:
                            stable_duration = current_time - cam_state.stable_since
                            if stable_duration >= self.min_publisher_stable_time:
                                cam_state.publisher_stable = True
                        
                        # Log current state (every 5 seconds to avoid spam)
                        if int(elapsed) % 5 == 0 or cam_state.publisher_stable != cam_state._last_logged_publisher_stable:
                            stable_for = f"{current_time - cam_state.stable_since:.1f}s" if cam_state.stable_since else "N/A"
                            self._log(f"[BOOT] {required_path}: ready={cam_state.ready}, h264={cam_state.has_h264}, bytes={bytes_received}, consecutive={cam_state.consecutive_increases}, stable_for={stable_for}, publisher_stable={cam_state.publisher_stable}, rtsp_verified={cam_state.rtsp_verified}")
                            cam_state._last_logged_publisher_stable = cam_state.publisher_stable
                        
                        if not cam_state.publisher_stable:
                            all_publisher_stable = False
                    
                    # Step 2: Check if publisher layer is ready
                    if all_publisher_stable and not publisher_layer_ready:
                        cam1_state = cam_states["live/cam1"]
                        cam2_state = cam_states["live/cam2"]
                        self._log(f"[BOOT] Publisher layer READY: CAM1 stable, CAM2 stable")
                        self._log(f"[BOOT] CAM1 publisher stability: PASS (stable_for={current_time - cam1_state.stable_since:.1f}s)")
                        self._log(f"[BOOT] CAM2 publisher stability: PASS (stable_for={current_time - cam2_state.stable_since:.1f}s)")
                        self._log("[BOOT] All publisher readiness checks: PASS")
                        publisher_layer_ready = True
                        rtsp_deadline = current_time + self.rtsp_verification_window
                        rtsp_phase_started = True
                    
                    # Step 3: RTSP verification phase
                    if publisher_layer_ready:
                        if rtsp_phase_started:
                            self._log(f"[BOOT] Checking RTSP handshake (deadline in {rtsp_deadline - current_time:.1f}s)...")
                            rtsp_phase_started = False
                        
                        all_rtsp_ready = True
                        for required_path in ("live/cam1", "live/cam2"):
                            cam_state = cam_states[required_path]
                            
                            if cam_state.rtsp_verified and cam_state.post_rtsp_stable:
                                continue  # Already fully ready
                            
                            if not cam_state.rtsp_verified:
                                # Attempt RTSP handshake
                                rtsp_url = f"rtsp://127.0.0.1:{self.rtsp_port}/{required_path}?transport=tcp"
                                
                                try:
                                    import av
                                    
                                    hw = HWAccel(
                                        device_type="cuda",
                                        is_hw_owned=True,
                                        allow_software_fallback=False
                                    )
                                    
                                    container = av.open(
                                        rtsp_url,
                                        format="rtsp",
                                        options={"rtsp_transport": "tcp"},
                                        hwaccel=hw,
                                        timeout=5.0
                                    )
                                    
                                    video_stream = None
                                    for s in container.streams:
                                        if s.type == "video":
                                            video_stream = s
                                            break
                                    
                                    if video_stream is None:
                                        raise RuntimeError(f"No video stream in {rtsp_url}")
                                    
                                    if video_stream.codec_context.name.lower() != "h264":
                                        raise RuntimeError(f"Expected H.264, got {video_stream.codec_context.name}")
                                    
                                    frame_read = False
                                    for frame in container.decode(video=0):
                                        frame_read = True
                                        break
                                    
                                    container.close()
                                    
                                    if not frame_read:
                                        raise RuntimeError(f"No frames decoded from {rtsp_url}")
                                    
                                    cam_state.rtsp_verified = True
                                    cam_state.rtsp_verified_at = current_time
                                    self._log(f"[BOOT] RTSP {required_path}: HANDSHAKE OK (H.264, {video_stream.width}x{video_stream.height}, frame read)")
                                    
                                except Exception as e:
                                    self._log(f"[BOOT] RTSP {required_path}: HANDSHAKE FAILED ({type(e).__name__}: {e})")
                                    all_rtsp_ready = False
                            
                            # Check post-RTSP stability
                            if cam_state.rtsp_verified and cam_state.rtsp_verified_at is not None:
                                post_rtsp_duration = current_time - cam_state.rtsp_verified_at
                                if post_rtsp_duration >= self.min_post_rtsp_stable_time:
                                    cam_state.post_rtsp_stable = True
                                    self._log(f"[BOOT] RTSP {required_path}: POST-RTSP STABLE ({post_rtsp_duration:.1f}s)")
                                else:
                                    all_rtsp_ready = False
                        
                        # Check if RTSP deadline exceeded
                        if rtsp_deadline and current_time > rtsp_deadline:
                            self._log_both_cameras(cam_states, "RTSP_TIMEOUT")
                            self._log(f"[BOOT] MediaMTX readiness: FAIL - RTSP verification timeout")
                            return False
                        
                        if all_rtsp_ready:
                            self._log("[BOOT] All RTSP readiness checks: PASS")
                            self._log(f"[BOOT] MediaMTX readiness: PASS")
                            self._log(f"[BOOT] CAM1: FULLY_READY")
                            self._log(f"[BOOT] CAM2: FULLY_READY")
                            self._sleep(self.stabilization_delay)
                            return True
                        
            except Exception as e:
                self._log(f"[BOOT] MediaMTX readiness check error: {e}")
            
            self._sleep(1.0)
        
        # Global timeout reached
        self._log_both_cameras(cam_states, "GLOBAL_TIMEOUT")
        self._log(f"[BOOT] MediaMTX readiness: FAIL - Global timeout after {max_wait}s")
        return False
    
    def _reset_camera_publisher_state(self, cam_state: CameraReadinessState) -> None:
        """Reset publisher-related state for a camera."""
        cam_state.ready = False
        cam_state.has_h264 = False
        cam_state.consecutive_increases = 0
        cam_state.stable_since = None
        cam_state.publisher_stable = False
        cam_state.bytes_history = []
    
    def _log_camera_state(self, cam_state: CameraReadinessState, reason: str) -> None:
        """Log detailed state for a single camera."""
        stable_for = f"{(self._time() - cam_state.stable_since):.1f}s" if cam_state.stable_since else "N/A"
        self._log(f"[BOOT] {cam_state.path_name} [{reason}]: ready={cam_state.ready}, h264={cam_state.has_h264}, bytes={cam_state.last_bytes}, consecutive={cam_state.consecutive_increases}, stable_for={stable_for}, publisher_stable={cam_state.publisher_stable}, rtsp_verified={cam_state.rtsp_verified}")
    
    def _log_both_cameras(self, cam_states: Dict[str, CameraReadinessState], reason: str) -> None:
        """Log detailed state for both cameras."""
        for path_name in ("live/cam1", "live/cam2"):
            self._log_camera_state(cam_states[path_name], reason)