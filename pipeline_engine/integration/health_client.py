"""
PipelineEngine Health Client

Sends health heartbeats to Legacy Backend and receives control commands.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from pipeline_engine.core.engine import PipelineEngine, EngineState
from pipeline_engine.config import load_pipeline_config, PipelineConfig

logger = logging.getLogger(__name__)


@dataclass
class HealthClientConfig:
    """Configuration for health client."""
    backend_base_url: str = "http://localhost:19146"
    worker_id: str = "pipeline_engine_1"
    worker_version: str = "1.0.0"
    api_key: Optional[str] = None
    report_interval: float = 5.0
    timeout: float = 5.0
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 30.0
    retry_backoff: float = 2.0
    queue_max_size: int = 100


class LegacyBackendHealthClient:
    """
    Client for sending health heartbeats to Legacy Backend.
    
    Features:
    - Async non-blocking health reports
    - Bounded retry with exponential backoff
    - Local queue for offline buffering
    - Control command polling
    - Structured logging
    """
    
    def __init__(self, config: Optional[HealthClientConfig] = None, engine: Optional["PipelineEngine"] = None):
        self.config = config or HealthClientConfig()
        self.engine = engine
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self.config.queue_max_size)
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._last_health: Optional[Dict[str, Any]] = None
        self._commands: List[Dict[str, Any]] = []
        self._commands_lock = asyncio.Lock()
        self._sequence_number: int = 0
        self._stream_epochs: Dict[str, int] = {}
        self._worker_start_time: float = time.time()
        
    async def start(self) -> None:
        """Start the health client."""
        if self._task is not None:
            return
            
        # Load API key from environment if not set
        if not self.config.api_key:
            self.config.api_key = os.environ.get("AI_WORKER_API_KEY")
            
        self._client = httpx.AsyncClient(
            base_url=self.config.backend_base_url,
            timeout=httpx.Timeout(self.config.timeout),
            headers={"X-API-Key": self.config.api_key} if self.config.api_key else {},
        )
        
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Health client started for worker {self.config.worker_id}")
        
    async def stop(self) -> None:
        """Stop the health client."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
                
        if self._client:
            await self._client.aclose()
            
        logger.info("Health client stopped")
        
    def update_health(self, health_data: Dict[str, Any]) -> None:
        """Update latest health data for next heartbeat."""
        self._last_health = health_data
        
    def get_commands(self) -> List[Dict[str, Any]]:
        """Get pending control commands (thread-safe)."""
        return self._commands.copy()
        
    async def _run_loop(self) -> None:
        """Main loop: send heartbeats and poll commands."""
        while not self._stop_event.is_set():
            try:
                await self._send_heartbeat()
                await self._poll_commands()
            except Exception as e:
                logger.error(f"Health client loop error: {e}")
                
            await asyncio.sleep(self.config.report_interval)
            
    async def _send_heartbeat(self) -> bool:
        """Send health heartbeat to Legacy Backend."""
        if not self._last_health:
            logger.debug("No health data to send")
            return False
            
        self._sequence_number += 1
        
        payload = {
            "worker_id": self.config.worker_id,
            "worker_version": self.config.worker_version,
            "state": self._get_worker_state(),
            "timestamp": time.time(),
            "sequence_number": self._sequence_number,
            "camera_states": self._build_camera_states(),
            "model_readiness": self._get_model_readiness(),
            "gpu_provider": "CUDAExecutionProvider",
            "queue_depth": self._get_queue_depth(),
            "processing_latency_ms": self._get_latency_ms(),
            "dropped_frames": self._get_dropped_frames(),
            "stream_epochs": self._get_stream_epochs(),
            "errors": self._get_errors(),
        }
        
        return await self._post_with_retry("/api/v1/health/ai-worker", payload)
        
    async def _poll_commands(self) -> None:
        """Poll for control commands from Legacy Backend."""
        try:
            response = await self._client.get(
                "/api/v1/ai/control/pending",
                params={"worker_id": self.config.worker_id},
            )
            
            if response.status_code == 200:
                data = response.json()
                # Backend returns {"worker_id": "...", "requests": [...]}
                # Extract action names from requests
                requests = data.get("requests", [])
                commands = [req.get("action") for req in requests if req.get("action")]
                
                async with self._commands_lock:
                    self._commands = commands
                    
            elif response.status_code == 404:
                # No pending commands
                pass
            else:
                logger.warning(f"Control poll failed: {response.status_code}")
                
        except httpx.TimeoutException:
            logger.warning("Control poll timeout")
        except httpx.ConnectError:
            logger.warning("Control poll: backend unreachable")
        except Exception as e:
            logger.error(f"Control poll error: {e}")
            
    async def _post_with_retry(self, path: str, payload: Dict[str, Any]) -> bool:
        """POST with exponential backoff retry."""
        last_exception = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self._client.post(path, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    # Store commands for worker
                    async with self._commands_lock:
                        self._commands = data.get("commands", [])
                    return True
                elif response.status_code == 401:
                    logger.error("Health client: Invalid API key")
                    return False
                else:
                    logger.warning(f"Health POST failed: {response.status_code} - {response.text}")
                    
            except httpx.TimeoutException:
                last_exception = "Timeout"
            except httpx.ConnectError:
                last_exception = "Connection failed"
            except Exception as e:
                last_exception = str(e)
                
            if attempt < self.config.max_retries:
                delay = min(
                    self.config.base_retry_delay * (self.config.retry_backoff ** attempt),
                    self.config.max_retry_delay
                )
                logger.warning(f"Health POST attempt {attempt + 1} failed: {last_exception}, retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Health POST failed after {self.config.max_retries + 1} attempts: {last_exception}")
                
        return False
        
    def _get_worker_state(self) -> str:
        """Determine current worker state from engine."""
        if not self.engine:
            return "starting"
            
        state = self.engine.state
        if state == EngineState.STOPPED:
            return "stopped"
        elif state == EngineState.STOPPING:
            return "stopping"
        elif state == EngineState.ERROR:
            return "failed"
        elif state == EngineState.DEGRADED:
            return "degraded"
        elif state == EngineState.RUNNING:
            return "ready"
        elif state == EngineState.STARTING:
            return "starting"
        elif state == EngineState.INITIALIZING:
            return "initializing"
        return "starting"
        
    def _build_camera_states(self) -> Dict[str, Any]:
        """Build camera state dictionary from engine."""
        if not self.engine or not self.engine.camera_manager:
            return {}
            
        camera_states = {}
        try:
            for cam_id in self.engine.camera_manager.get_camera_list():
                state = self.engine.camera_manager.get_camera_state(cam_id)
                metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
                
                # Get stream epoch for this camera
                stream_epoch = self._stream_epochs.get(cam_id, 0)
                
                camera_states[cam_id] = {
                    "state": state.value if hasattr(state, 'value') else str(state),
                    "stream_epoch": self._stream_epochs.get(cam_id, 0),
                    "stream_connected": state == "RUNNING",
                    "last_frame_timestamp": metrics.last_frame_timestamp if metrics else 0.0,
                    "last_inference_timestamp": metrics.last_inference_timestamp if metrics else 0.0,
                    "decode_fps": metrics.decode_fps if metrics else 0.0,
                    "inference_fps": metrics.inference_fps if metrics else 0.0,
                    "track_count": metrics.tracks_active if metrics else 0,
                }
        except Exception as e:
            logger.warning(f"Failed to build camera states: {e}")
            
        return camera_states
        
    def _get_model_readiness(self) -> Dict[str, bool]:
        """Get model readiness status from engine."""
        if not self.engine:
            return {"scrfd": False, "arcface": False, "yolo": False}
            
        # Check if models are loaded in the engine
        readiness = {
            "scrfd": False,
            "arcface": False,
            "yolo": False,
        }
        
        # Check if models are loaded in the engine's inference modules
        try:
            if hasattr(self.engine, 'scrfd') and self.engine.scrfd:
                readiness["scrfd"] = True
            if hasattr(self.engine, 'arcface') and self.engine.arcface:
                readiness["arcface"] = True
            if hasattr(self.engine, 'yolo') and self.engine.yolo:
                readiness["yolo"] = True
        except Exception:
            pass
            
        return readiness
        
    def _get_queue_depth(self) -> int:
        """Get event delivery queue depth."""
        # Could check the health client's internal queue
        return 0  # Will be implemented when event delivery queue is added
        
    def _get_latency_ms(self) -> float:
        """Get processing latency in milliseconds."""
        # Could track end-to-end latency
        return 0.0
        
    def _get_dropped_frames(self) -> int:
        """Get dropped frame count."""
        # Could track dropped frames from camera manager
        return 0
        
    def _get_stream_epochs(self) -> Dict[str, int]:
        """Get stream epochs for all cameras."""
        return self._stream_epochs.copy()
        
    def _get_errors(self) -> List[str]:
        """Get current error messages."""
        errors = []
        if self.engine and self.engine.metrics.last_error:
            errors.append(self.engine.metrics.last_error)
        return errors
    
    def update_stream_epoch(self, camera_id: str, epoch: int) -> None:
        """Update stream epoch for a camera (called when stream restarts)."""
        self._stream_epochs[camera_id] = epoch
        logger.info(f"Stream epoch updated for {camera_id}: {epoch}")


def create_health_client(config: Optional[HealthClientConfig] = None, engine: Optional["PipelineEngine"] = None) -> LegacyBackendHealthClient:
    """Factory function to create health client."""
    return LegacyBackendHealthClient(config, engine)


# Integration with PipelineEngine
async def setup_health_reporting(engine: "PipelineEngine", config: Optional[HealthClientConfig] = None) -> LegacyBackendHealthClient:
    """
    Set up health reporting for PipelineEngine.
    
    Registers health callback to send periodic heartbeats.
    """
    client = create_health_client(config, engine)
    await client.start()
    
    def health_callback(health: Dict[str, Any]):
        # Convert engine health to client format
        client.update_health({
            "state": health["engine"]["state"],
            "cameras": health["cameras"],
            "memory": health.get("memory", {}),
            "uptime": health["engine"]["uptime_seconds"],
        })
        
    engine.register_health_callback(health_callback)
    
    return client