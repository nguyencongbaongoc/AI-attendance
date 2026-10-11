"""
PipelineEngine Control Client

Receives control commands from Legacy Backend and executes them on the PipelineEngine.
Aligned with Legacy Backend contract (Phase 0.2.6).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from pipeline_engine.core.engine import PipelineEngine, EngineState
from pipeline_engine.config import load_pipeline_config, PipelineConfig

logger = logging.getLogger(__name__)


@dataclass
class ControlClientConfig:
    """Configuration for control client."""
    backend_base_url: str = "http://localhost:19146"
    worker_id: str = "pipeline_engine_1"
    api_key: Optional[str] = None
    poll_interval: float = 2.0
    timeout: float = 5.0
    max_retries: int = 3


# Canonical action names matching Legacy Backend
class Action(str):
    """Control actions - MUST match Legacy Backend ControlAction enum."""
    START_WORKER = "START_WORKER"
    STOP_WORKER = "STOP_WORKER"
    RESTART_WORKER = "RESTART_WORKER"
    ENABLE_CAMERA = "ENABLE_CAMERA"
    DISABLE_CAMERA = "DISABLE_CAMERA"
    GET_STATUS = "GET_STATUS"


class ControlResult(str):
    """Control action result - MUST match Legacy Backend ControlRequestStatus."""
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class ControlRequest:
    """Incoming control request - matches Legacy Backend ControlRequest schema."""
    request_id: str
    action: str
    target: str  # "worker" or "camera"
    target_id: str
    idempotency_key: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ControlResponse:
    """Control action response - matches Legacy Backend ControlResponse schema."""
    success: bool
    action: str
    worker_id: str
    status: str  # PENDING, ACCEPTED, RUNNING, COMPLETED, FAILED, REJECTED, EXPIRED
    request_id: str
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class PipelineEngineControlServer:
    """
    Receives and executes control commands from Legacy Backend.
    
    Polls Legacy Backend for pending commands and executes them on the PipelineEngine.
    Contract aligned with Legacy Backend (Phase 0.2.6).
    """
    
    def __init__(self, engine: PipelineEngine, config: Optional[ControlClientConfig] = None):
        self.engine = engine
        self.config = config or ControlClientConfig()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._processed_keys: set = set()  # For idempotency
        self._processed_keys_lock = asyncio.Lock()
        
        # Action handlers - using canonical action names
        self._action_handlers = {
            Action.START_WORKER: self._handle_start_worker,
            Action.STOP_WORKER: self._handle_stop_worker,
            Action.RESTART_WORKER: self._handle_restart_worker,
            Action.ENABLE_CAMERA: self._handle_enable_camera,
            Action.DISABLE_CAMERA: self._handle_disable_camera,
            Action.GET_STATUS: self._handle_get_status,
        }
        
    async def start(self) -> None:
        """Start the control server."""
        if self._task is not None:
            return
            
        # Load API key from environment if not set
        if not self.config.api_key:
            self.config.api_key = os.environ.get("AI_CONTROL_API_KEY")
            
        self._client = httpx.AsyncClient(
            base_url=self.config.backend_base_url,
            timeout=httpx.Timeout(self.config.timeout),
            headers={"X-API-Key": self.config.api_key} if self.config.api_key else {},
        )
        
        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"Control server started for worker {self.config.worker_id}")
        
    async def stop(self) -> None:
        """Stop the control server."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
                
        if self._client:
            await self._client.aclose()
            
        logger.info("Control server stopped")
        
    async def _poll_loop(self) -> None:
        """Poll Legacy Backend for pending commands."""
        while not self._stop_event.is_set():
            try:
                await self._poll_commands()
            except Exception as e:
                logger.error(f"Control poll error: {e}")
                
            await asyncio.sleep(self.config.poll_interval)
            
    async def _poll_commands(self) -> None:
        """Poll for pending commands from Legacy Backend."""
        try:
            # GET /api/v1/ai/control/pending?worker_id=...
            response = await self._client.get(
                "/api/v1/ai/control/pending",
                params={"worker_id": self.config.worker_id},
            )
            
            if response.status_code == 200:
                data = response.json()
                # Backend returns {"worker_id": "...", "requests": [...]}
                requests = data.get("requests", [])
                
                for req in requests:
                    await self._execute_command(req)
                    
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
            
    async def _execute_command(self, cmd: Dict[str, Any]) -> None:
        """Execute a single control command."""
        try:
            request = ControlRequest(
                request_id=cmd["request_id"],
                action=cmd["action"],
                target=cmd["target"],
                target_id=cmd["target_id"],
                parameters=cmd.get("parameters", {}),
                idempotency_key=cmd["idempotency_key"],
                timestamp=cmd.get("timestamp", time.time()),
            )
            
            # Check idempotency
            async with self._processed_keys_lock:
                if request.idempotency_key in self._processed_keys:
                    logger.info(f"Duplicate control request ignored: {request.idempotency_key}")
                    return
                    
            # Validate action against canonical enum
            if request.action not in self._action_handlers:
                logger.warning(f"Unknown action: {request.action}")
                return
                
            # Execute action
            handler = self._action_handlers[request.action]
            response = await handler(request)
            
            # Mark as processed (only on success)
            async with self._processed_keys_lock:
                self._processed_keys.add(request.idempotency_key)
                
            # Send response back to backend
            await self._send_response(response)
            
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            
    async def _send_response(self, response: ControlResponse) -> None:
        """Send response back to Legacy Backend.
        
        Uses the canonical action name from the original request (response.action)
        which matches the backend's expected path format.
        """
        try:
            # Use the action from response (which came from the original request)
            # This matches the backend's expected path: /api/v1/ai/control/{ACTION}/response
            await self._client.post(
                f"/api/v1/ai/control/{response.action}/response",
                json={
                    "request_id": response.request_id,
                    "action": response.action,
                    "worker_id": response.worker_id,
                    "status": response.status,
                    "timestamp": response.timestamp,
                    "details": response.details,
                    "error": response.error,
                }
            )
        except Exception as e:
            logger.error(f"Failed to send control response: {e}")
            
    # Action handlers - using canonical action names
    async def _handle_start_worker(self, request: ControlRequest) -> ControlResponse:
        """Handle START_WORKER action."""
        try:
            if self.engine.state in (EngineState.RUNNING, EngineState.STARTING):
                return ControlResponse(
                    success=False,
                    action=Action.START_WORKER,
                    worker_id=self.config.worker_id,
                    status=ControlResult.FAILED,
                    request_id=request.request_id,
                    timestamp=time.time(),
                    error="Worker already running",
                )
                
            success = self.engine.start()
            
            return ControlResponse(
                success=success,
                action=Action.START_WORKER,
                worker_id=self.config.worker_id,
                status=ControlResult.COMPLETED if success else ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=None if success else self.engine.metrics.last_error,
            )
        except Exception as e:
            return ControlResponse(
                success=False,
                action=Action.START_WORKER,
                worker_id=self.config.worker_id,
                status=ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=str(e),
            )
            
    async def _handle_stop_worker(self, request: ControlRequest) -> ControlResponse:
        """Handle STOP_WORKER action."""
        try:
            graceful = request.parameters.get("graceful", True)
            timeout = request.parameters.get("timeout", 30.0)
            
            if self.engine.state in (EngineState.STOPPED, EngineState.STOPPING):
                return ControlResponse(
                    success=True,
                    action=Action.STOP_WORKER,
                    worker_id=self.config.worker_id,
                    status=ControlResult.COMPLETED,
                    request_id=request.request_id,
                    timestamp=time.time(),
                    details={"note": "Already stopped"},
                )
                
            self.engine.stop(timeout=timeout)
            
            return ControlResponse(
                success=True,
                action=Action.STOP_WORKER,
                worker_id=self.config.worker_id,
                status=ControlResult.COMPLETED,
                request_id=request.request_id,
                timestamp=time.time(),
                details={"graceful": graceful},
            )
        except Exception as e:
            return ControlResponse(
                success=False,
                action=Action.STOP_WORKER,
                worker_id=self.config.worker_id,
                status=ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=str(e),
            )
            
    async def _handle_restart_worker(self, request: ControlRequest) -> ControlResponse:
        """Handle RESTART_WORKER action."""
        try:
            graceful = request.parameters.get("graceful", True)
            timeout = request.parameters.get("timeout", 30.0)
            
            self.engine.stop(timeout=timeout)
            await asyncio.sleep(1.0)
            success = self.engine.start()
            
            return ControlResponse(
                success=success,
                action=Action.RESTART_WORKER,
                worker_id=self.config.worker_id,
                status=ControlResult.COMPLETED if success else ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=None if success else self.engine.metrics.last_error,
            )
        except Exception as e:
            return ControlResponse(
                success=False,
                action=Action.RESTART_WORKER,
                worker_id=self.config.worker_id,
                status=ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=str(e),
            )
            
    async def _handle_enable_camera(self, request: ControlRequest) -> ControlResponse:
        """Handle ENABLE_CAMERA action."""
        try:
            camera_id = request.parameters.get("camera_id") or request.target_id
            
            if not self.engine.camera_manager:
                return ControlResponse(
                    success=False,
                    action=Action.ENABLE_CAMERA,
                    worker_id=self.config.worker_id,
                    status=ControlResult.FAILED,
                    request_id=request.request_id,
                    timestamp=time.time(),
                    error="Camera manager not initialized",
                )
                
            # TODO: Implement actual camera enable logic
            # For now, acknowledge
            return ControlResponse(
                success=True,
                action=Action.ENABLE_CAMERA,
                worker_id=self.config.worker_id,
                status=ControlResult.ACCEPTED,
                request_id=request.request_id,
                timestamp=time.time(),
                details={"camera_id": camera_id, "note": "Enable requested"},
            )
        except Exception as e:
            return ControlResponse(
                success=False,
                action=Action.ENABLE_CAMERA,
                worker_id=self.config.worker_id,
                status=ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=str(e),
            )
            
    async def _handle_disable_camera(self, request: ControlRequest) -> ControlResponse:
        """Handle DISABLE_CAMERA action."""
        try:
            camera_id = request.parameters.get("camera_id") or request.target_id
            
            if not self.engine.camera_manager:
                return ControlResponse(
                    success=False,
                    action=Action.DISABLE_CAMERA,
                    worker_id=self.config.worker_id,
                    status=ControlResult.FAILED,
                    request_id=request.request_id,
                    timestamp=time.time(),
                    error="Camera manager not initialized",
                )
                
            # TODO: Implement actual camera disable logic
            # For now, acknowledge
            return ControlResponse(
                success=True,
                action=Action.DISABLE_CAMERA,
                worker_id=self.config.worker_id,
                status=ControlResult.ACCEPTED,
                request_id=request.request_id,
                timestamp=time.time(),
                details={"camera_id": camera_id, "note": "Disable requested"},
            )
        except Exception as e:
            return ControlResponse(
                success=False,
                action=Action.DISABLE_CAMERA,
                worker_id=self.config.worker_id,
                status=ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=str(e),
            )
            
    async def _handle_get_status(self, request: ControlRequest) -> ControlResponse:
        """Handle GET_STATUS action."""
        try:
            status_details = {
                "worker_state": self.engine.state.value if hasattr(self.engine.state, 'value') else str(self.engine.state),
                "uptime_seconds": getattr(self.engine.metrics, 'uptime_seconds', 0.0),
            }
            
            if self.engine.camera_manager:
                cameras = {}
                for cam_id in self.engine.camera_manager.get_camera_list():
                    cam_state = self.engine.camera_manager.get_camera_state(cam_id)
                    metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
                    cameras[cam_id] = {
                        "state": cam_state.value if hasattr(cam_state, 'value') else str(cam_state),
                        "tracks_active": metrics.tracks_active if metrics else 0,
                        "decode_fps": metrics.decode_fps if metrics else 0.0,
                        "inference_fps": metrics.inference_fps if metrics else 0.0,
                    }
                status_details["cameras"] = cameras
            
            return ControlResponse(
                success=True,
                action=Action.GET_STATUS,
                worker_id=self.config.worker_id,
                status=ControlResult.COMPLETED,
                request_id=request.request_id,
                timestamp=time.time(),
                details=status_details,
            )
        except Exception as e:
            return ControlResponse(
                success=False,
                action=Action.GET_STATUS,
                worker_id=self.config.worker_id,
                status=ControlResult.FAILED,
                request_id=request.request_id,
                timestamp=time.time(),
                error=str(e),
            )


def create_control_server(engine: PipelineEngine, config: Optional[ControlClientConfig] = None) -> PipelineEngineControlServer:
    """Factory function to create control server."""
    return PipelineEngineControlServer(engine, config)


async def setup_control_integration(engine: PipelineEngine, config: Optional[ControlClientConfig] = None) -> PipelineEngineControlServer:
    """Set up control integration for PipelineEngine."""
    server = create_control_server(engine, config)
    await server.start()
    return server