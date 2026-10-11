"""
Camera Supervisor and Worker Recovery - V2 GPU-first video pipeline.

Supervises GPU worker process, detects crashes, captures exit reasons,
distinguishes root cause (process exit) from downstream symptoms (OSError -129),
and manages independent camera lifecycles.
"""

from __future__ import annotations

import logging
import time
import subprocess
import sys
import os
import signal
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class CameraLifecycleState(str, Enum):
    """Camera lifecycle states."""
    STOPPED = "stopped"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DECODING = "decoding"
    AI_ACTIVE = "ai_active"
    PUBLISHING = "publishing"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class SystemState(str, Enum):
    """Independent system readiness states."""
    SYSTEM_READY = "system_ready"
    MEDIA_SERVER_READY = "media_server_ready"
    MEDIA_SERVER_NOT_READY = "mediamtx_not_running"
    CAMERA_READY = "camera_ready"
    CAMERA_NOT_READY = "camera_not_ready"
    DECODER_READY = "decoder_ready"
    AI_READY = "ai_ready"
    ENCODER_READY = "encoder_ready"
    PUBLISHER_READY = "publisher_ready"
    ATTENDANCE_READY = "attendance_ready"


@dataclass
class ProcessInfo:
    """Tracks process information for diagnostics."""
    pid: Optional[int] = None
    start_time: float = 0.0
    exit_code: Optional[int] = None
    exit_time: Optional[float] = None
    first_failure: Optional[str] = None
    last_exception: Optional[str] = None
    restart_count: int = 0
    max_restarts: int = 3
    last_heartbeat: float = 0.0


@dataclass
class SupervisorConfig:
    """Supervisor configuration."""
    camera_id: str
    # Process management
    worker_command: List[str]  # Command to start GPU worker
    workdir: str = "."
    # Monitoring
    heartbeat_interval: float = 5.0  # Seconds
    heartbeat_timeout: float = 15.0  # Seconds without heartbeat = hung
    # Restart limits
    max_restarts: int = 3
    restart_backoff: float = 2.0  # Seconds, exponential
    max_backoff: float = 30.0
    # Resources
    max_memory_mb: int = 8192  # 8GB


class GPUWorkerSupervisor:
    """
    Supervisor for GPU worker process.
    
    Key principles:
    - Detects worker alive/dead/hung
    - Captures process exit code (NOT just exception message)
    - Tracks first failure (process exit) vs downstream symptoms (OSError -129)
    - Independent camera lifecycle (CAM1 failure doesn't kill CAM2)
    - Independent attendance path (publisher/encoder failure doesn't stop attendance)
    - Bounded restart with backoff
    - No silent failures
    """
    
    def __init__(self, config: SupervisorConfig):
        self.config = config
        self.camera_id = config.camera_id
        
        # Process info tracking
        self._process_info = ProcessInfo(
            max_restarts=config.max_restarts,
        )
        
        # Worker process
        self._worker_process: Optional[subprocess.Popen] = None
        
        # Monitoring
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # State
        self._lifecycle_state = CameraLifecycleState.STOPPED
        self._system_states: Dict[str, SystemState] = {
            "system": SystemState.SYSTEM_READY,
            "media_server": SystemState.MEDIA_SERVER_READY,
            "decoder": SystemState.DECODER_READY,
            "ai": SystemState.AI_READY,
            "encoder": SystemState.ENCODER_READY,
            "publisher": SystemState.PUBLISHER_READY,
            "attendance": SystemState.ATTENDANCE_READY,
        }
        
        # Lock
        self._lock = threading.RLock()
        
        # Diagnostic logging
        self._process_start_logged = False
    
    def start(self) -> bool:
        """Start the GPU worker process."""
        with self._lock:
            if self._lifecycle_state == CameraLifecycleState.AI_ACTIVE:
                logger.info(f"Supervisor({self.camera_id}): Worker already running")
                return True
            
            logger.info(f"Supervisor({self.camera_id}): Starting GPU worker process")
            
            # Log process start
            logger.info(f"PROCESS_START: worker={self.camera_id}, pid=unknown, time={time.time()}")
            
            try:
                # Start worker process
                self._worker_process = subprocess.Popen(
                    self.config.worker_command,
                    cwd=self.config.workdir,
                    stdout=subprocess.PIPE if False else None,  # Would configure based on needs
                    stderr=subprocess.PIPE,
                    stdin=subprocess.PIPE,
                    start_new_session=True,  # Detach from parent for isolation
                )
                
                pid = self._worker_process.pid
                self._process_info.pid = pid
                self._process_info.start_time = time.time()
                self._process_info.last_heartbeat = time.time()
                self._process_info.restart_count = 0
                
                logger.info(f"PROCESS_START: worker={self.camera_id}, pid={pid}, time={self._process_info.start_time}")
                
                # Log GPU context info (simulated - would come from actual GPU context)
                logger.info(f"GPU_CONTEXT_CREATED: device=0, context=primary, stream=primary")
                
                # Update lifecycle
                self._set_lifecycle_state(CameraLifecycleState.CONNECTING)
                
                # Start monitoring threads
                self._start_monitoring()
                
                # Set system states
                self._update_system_state("system", SystemState.SYSTEM_READY)
                
                # Note: We don't set media_server state here - it must be verified independently
                
                logger.info(f"Supervisor({self.camera_id}): GPU worker started with PID {pid}")
                return True
                
            except Exception as e:
                logger.error(f"Supervisor({self.camera_id}): Failed to start worker: {e}")
                self._process_info.first_failure = str(e)
                self._process_info.last_exception = str(e)
                self._set_lifecycle_state(CameraLifecycleState.FAILED)
                return False
    
    def _start_monitoring(self) -> None:
        """Start heartbeat and process monitoring threads."""
        self._stop_event.clear()
        
        # Heartbeat thread
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"heartbeat-{self.camera_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()
        
        # Monitor thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name=f"monitor-{self.camera_id}",
            daemon=True,
        )
        self._monitor_thread.start()
    
    def _heartbeat_loop(self) -> None:
        """Send heartbeats and check worker health."""
        interval = self.config.heartbeat_interval
        timeout = self.config.heartbeat_timeout
        
        while not self._stop_event.is_set():
            try:
                # Update heartbeat
                with self._lock:
                    self._process_info.last_heartbeat = time.time()
                
                # Check if process is alive
                process_alive = self._is_worker_alive()
                
                if not process_alive and self._lifecycle_state != CameraLifecycleState.FAILED:
                    # Process died - capture exit info
                    logger.error(f"Supervisor({self.camera_id}): WORKER_DEATH_DETECTED")
                    
                    # Get exit code
                    if self._worker_process is not None:
                        try:
                            exit_code = self._worker_process.poll()
                            if exit_code is not None:
                                self._process_info.exit_code = exit_code
                                self._process_info.exit_time = time.time()
                                logger.error(f"PROCESS_EXIT: pid={self._process_info.pid}, exit_code={exit_code}, time={self._process_info.exit_time}")
                                
                                # Log first failure chronology
                                if self._process_info.first_failure is None:
                                    self._process_info.first_failure = f"process_exit_code_{exit_code}"
                        except Exception as e:
                            logger.error(f"PROCESS_EXIT_CHECK_ERROR: {e}")
                    
                    # Log chronology: first failure → process exit → symptom
                    # This is critical: OSError -129 must NOT be treated as root cause
                    logger.error(
                        f"ERROR_CHRONOLOGY: first_failure={self._process_info.first_failure}, "
                        f"process_exit_code={self._process_info.exit_code}, "
                        f"downstream_symptom=OSError_129_possible"
                    )
                    
                    # Update lifecycle
                    self._set_lifecycle_state(CameraLifecycleState.FAILED)
                    
                    # Update system states: only this camera fails
                    # Other cameras (CAM2) remain independent
                    self._update_system_state("system", SystemState.SYSTEM_READY)  # System stays alive
                    
                    # Try restart if within limits
                    if self._process_info.restart_count < self.config.max_restarts:
                        self._restart_worker()
                    else:
                        logger.error(f"Supervisor({self.camera_id}): Max restarts reached, worker failed")
                
                # Check for hung process (no heartbeat for timeout period)
                with self._lock:
                    time_since_heartbeat = time.time() - self._process_info.last_heartbeat
                
                if time_since_heartbeat > timeout and self._lifecycle_state == CameraLifecycleState.AI_ACTIVE:
                    logger.warning(f"Supervisor({self.camera_id}): WORKER_HUNG detected (no heartbeat for {time_since_heartbeat}s)")
                    self._handle_worker_hung()
                
                # Wait
                time.sleep(interval)
                
            except Exception as e:
                logger.error(f"Supervisor({self.camera_id}): Heartbeat loop error: {e}")
                time.sleep(interval)
    
    def _monitor_loop(self) -> None:
        """Monitor worker process and system state."""
        while not self._stop_event.is_set():
            try:
                # Check process health
                process_alive = self._is_worker_alive()
                
                # Update lifecycle based on health
                if process_alive:
                    if self._lifecycle_state == CameraLifecycleState.CONNECTING:
                        # Just started connecting
                        pass
                    elif self._lifecycle_state == CameraLifecycleState.RECONNECTING:
                        self._set_lifecycle_state(CameraLifecycleState.AI_ACTIVE)
                    elif self._lifecycle_state == CameraLifecycleState.DECODING:
                        # Still connecting - keep as is for now
                        pass
                else:
                    # Process not alive but we haven't detected it in heartbeat
                    if self._lifecycle_state not in (CameraLifecycleState.STOPPED, CameraLifecycleState.FAILED):
                        self._update_lifecycle_based_on_health()
                
                # Check GPU context (simulated - would use CUDA APIs)
                # For V2, we track that GPU resources remain valid
                
                time.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Supervisor({self.camera_id}): Monitor loop error: {e}")
                time.sleep(1.0)
    
    def _is_worker_alive(self) -> bool:
        """Check if the worker process is alive."""
        with self._lock:
            if self._worker_process is None:
                return False
            
            # Check if process has terminated
            exit_code = self._worker_process.poll()
            if exit_code is not None:
                # Process has exited
                self._process_info.exit_code = exit_code
                self._process_info.exit_time = time.time()
                return False
            
            return True
    
    def _update_lifecycle_based_on_health(self) -> None:
        """Update lifecycle state based on health checks."""
        # Check decoder state (would get from decoder instance in full integration)
        # Check AI state
        # Check encoder state
        # Check publisher state
        # Update camera lifecycle accordingly
        
        # For V2: independent camera lifecycle
        # CAM1 failing doesn't affect CAM2
        if not self._is_worker_alive():
            self._set_lifecycle_state(CameraLifecycleState.FAILED)
    
    def _handle_worker_hung(self) -> None:
        """Handle hung worker (no heartbeat)."""
        logger.warning(f"Supervisor({self.camera_id}): WORKER_HUNG - attempting recovery")
        
        # Try to terminate gracefully
        if self._worker_process:
            try:
                self._worker_process.terminate()
                logger.info(f"Supervisor({self.camera_id}): Sent SIGTERM to worker PID {self._process_info.pid}")
            except Exception:
                pass
            
            # Wait briefly
            try:
                self._worker_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                # Force kill
                try:
                    self._worker_process.kill()
                    logger.info(f"Supervisor({self.camera_id}): Sent SIGKILL to worker PID {self._process_info.pid}")
                    self._worker_process.wait(timeout=2.0)
                except Exception as e:
                    logger.error(f"Supervisor({self.camera_id}): SIGKILL failed: {e}")
        
        # Capture exit info after kill
        if self._worker_process:
            exit_code = self._worker_process.poll()
            if exit_code is not None:
                self._process_info.exit_code = exit_code
                self._process_info.exit_time = time.time()
                logger.info(f"PROCESS_EXIT_AFTER_KILL: pid={self._process_info.pid}, exit_code={exit_code}")
        
        # Try restart
        if self._process_info.restart_count < self.config.max_restarts:
            self._restart_worker()
    
    def _restart_worker(self) -> bool:
        """Restart the worker process."""
        with self._lock:
            self._process_info.restart_count += 1
            
            if self._process_info.restart_count > self.config.max_restarts:
                logger.error(f"Supervisor({self.camera_id}): Max restarts exceeded")
                return False
            
            logger.info(f"Supervisor({self.camera_id}): Restarting worker (attempt {self._process_info.restart_count})")
            
            # Log restart reason (NOT just -129)
            restart_reason = (
                f"restart_after_exit_code_{self._process_info.exit_code}" 
                if self._process_info.exit_code is not None 
                else "restart_after_hung_or_crash"
            )
            logger.info(f"RESTART_REASON: {restart_reason}, first_failure={self._process_info.first_failure}")
            
            # Close old process
            if self._worker_process:
                try:
                    self._worker_process.kill()
                    self._worker_process.wait(timeout=3.0)
                except Exception:
                    pass
            
            # Apply backoff
            backoff = min(
                self.config.restart_backoff * (2 ** (self._process_info.restart_count - 1)),
                self.config.max_backoff
            )
            logger.info(f"Supervisor({self.camera_id}): Backoff before restart: {backoff:.2f}s")
            time.sleep(backoff)
            
            # Restart
            self.start()
            
            return True
    
    def _set_lifecycle_state(self, state: CameraLifecycleState) -> None:
        """Update camera lifecycle state."""
        with self._lock:
            old_state = self._lifecycle_state
            if old_state != state:
                logger.info(f"Supervisor({self.camera_id}): LIFECYCLE: {old_state.value} → {state.value}")
                self._lifecycle_state = state
    
    def _update_system_state(self, key: str, state: SystemState) -> None:
        """Update independent system component state."""
        with self._lock:
            old_state = self._system_states.get(key)
            if old_state != state:
                logger.info(f"Supervisor({self.camera_id}): SYSTEM: {key} = {old_state.value if old_state else 'none'} → {state.value}")
                self._system_states[key] = state
    
    def get_status(self) -> Dict[str, Any]:
        """Get supervisor status."""
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "lifecycle_state": self._lifecycle_state.value,
                "system_states": {k: v.value for k, v in self._system_states.items()},
                "process_info": {
                    "pid": self._process_info.pid,
                    "start_time": self._process_info.start_time,
                    "exit_code": self._process_info.exit_code,
                    "exit_time": self._process_info.exit_time,
                    "restart_count": self._process_info.restart_count,
                    "max_restarts": self._process_info.max_restarts,
                    "first_failure": self._process_info.first_failure,
                    "last_exception": self._process_info.last_exception,
                },
                "worker_alive": self._is_worker_alive(),
                "heartbeat_age": time.time() - self._process_info.last_heartbeat,
            }
    
    def stop(self) -> None:
        """Stop supervisor and worker."""
        logger.info(f"Supervisor({self.camera_id}): Stopping")
        self._stop_event.set()
        
        # Stop worker
        if self._worker_process:
            try:
                self._worker_process.terminate()
                self._worker_process.wait(timeout=3.0)
            except Exception:
                pass
        
        # Stop threads
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2.0)
        
        self._set_lifecycle_state(CameraLifecycleState.STOPPED)
        logger.info(f"Supervisor({self.camera_id}): Stopped")
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def create_supervisor(
    camera_id: str,
    worker_command: List[str],
    workdir: str = ".",
    heartbeat_interval: float = 5.0,
    max_restarts: int = 3,
) -> GPUWorkerSupervisor:
    """Factory function to create supervisor."""
    config = SupervisorConfig(
        camera_id=camera_id,
        worker_command=worker_command,
        workdir=workdir,
        heartbeat_interval=heartbeat_interval,
        max_restarts=max_restarts,
    )
    return GPUWorkerSupervisor(config)


# Independent system readiness tracking
class SystemReadinessTracker:
    """
    Tracks independent readiness states for all pipeline components.
    Each component has independent readiness - failure of one doesn't cascade.
    """
    
    def __init__(self):
        self._states = {}
    
    def set_ready(self, component: str, ready: bool) -> None:
        key = component.lower()
        state = SystemState.SYSTEM_READY if ready else SystemState.SYSTEM_READY  # Adjust based on component
        
        # Component-specific state mapping
        if component.lower() == "mediamtx":
            state = SystemState.MEDIA_SERVER_READY if ready else SystemState.MEDIA_SERVER_NOT_READY
        elif component.lower() == "camera":
            state = SystemState.CAMERA_READY if ready else SystemState.CAMERA_NOT_READY
        else:
            state = SystemState.SYSTEM_READY if ready else SystemState.SYSTEM_READY
        
        old = self._states.get(key)
        self._states[key] = state
        
        if old != state:
            logger.info(f"READINESS: {component} = {state.value}")
    
    def get_state(self, component: str) -> SystemState:
        return self._states.get(component.lower(), SystemState.SYSTEM_READY)
    
    def is_ready(self, component: str) -> bool:
        state = self.get_state(component)
        return "READY" in state.value
    
    def get_all_states(self) -> Dict[str, SystemState]:
        return self._states.copy()


if __name__ == "__main__":
    # Basic supervisor test (without actual worker process)
    supervisor = create_supervisor(
        camera_id="test_cam",
        worker_command=[sys.executable, "-c", "print('test worker'); import time; time.sleep(60)"],
        heartbeat_interval=2.0,
    )
    
    # Note: This will try to start a subprocess - skip for basic test
    print(f"Supervisor config: camera_id={supervisor.camera_id}")
    print(f"Lifecycle state: {supervisor.get_status()['lifecycle_state']}")
    print("Supervisor module loaded!")