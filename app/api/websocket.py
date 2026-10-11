"""
Phase 37C + Phase 7 — WebSocket/SSE Real-time Transport for Health Monitoring with Security Hardening.

Provides real-time health updates via WebSocket and Server-Sent Events.
Includes reconnect handling, stale-event detection, heartbeat mechanism, and authentication.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config.settings import load_settings
from app.runtime import collect_runtime_snapshot
from app.streaming.health_events import HealthEvent, HealthEventType
from app.streaming.shared_health import get_shared_health_monitor
from app.attendance.policy_engine.parent_registry import create_parent_registry
from app.attendance.policy_engine.telegram_bot import (
    create_notification_queue,
    create_telegram_bot,
)
from app.attendance.policy_engine.exit_session import create_exit_session_store_from_settings
from app.security.api_key_cache import get_api_key_cache
from app.logging.logger import get_logger

# Use structlog logger for structured audit logging
audit_logger = get_logger("app.security.audit")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/health", tags=["health"])


def get_health_monitor():
    """Get the shared health monitor for the backend process."""
    return get_shared_health_monitor()


# =============================================================================
# Security: Audit Logging
# =============================================================================

def _get_correlation_id() -> str:
    """Get correlation ID from structlog context."""
    import structlog.contextvars
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id", "unknown")


def _audit_log(event_type: str, outcome: str, actor: str, resource: str, details: dict = None):
    """Log security audit events with structured data (no secrets)."""
    audit_data = {
        "audit": True,
        "event_type": event_type,
        "outcome": outcome,
        "actor": actor,
        "resource": resource,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "correlation_id": _get_correlation_id(),
    }
    if details:
        safe_details = {}
        for k, v in details.items():
            if any(sensitive in k.lower() for sensitive in ["key", "token", "secret", "password", "credential"]):
                safe_details[k] = "***REDACTED***"
            else:
                safe_details[k] = v
        audit_data["details"] = safe_details
    
    audit_logger.info(f"Security audit: {event_type} - {outcome}", **audit_data)


def _get_client_identifier(request: Request) -> str:
    """Extract client identifier for audit logging."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# Health WebSocket Authentication
# =============================================================================

async def verify_health_ws_key(
    request: Request,
    api_key: str = Query(..., alias="api_key"),
) -> bool:
    """Verify API key for health WebSocket connection with audit logging."""
    client_id = _get_client_identifier(request)
    cache = get_api_key_cache()
    
    # Health WS accepts ADMIN_API_KEY only (more restrictive)
    admin_key = cache.get("ADMIN_API_KEY")
    
    if not admin_key:
        _audit_log("ws_authentication", "failure", client_id, "health_ws", 
                   {"reason": "admin_key_not_configured"})
        logger.error("ADMIN_API_KEY not configured for health WebSocket")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Health WebSocket API key not configured"
        )
    
    if not secrets.compare_digest(api_key, admin_key):
        _audit_log("ws_authentication", "failure", client_id, "health_ws", 
                   {"reason": "invalid_key"})
        logger.warning("Invalid API key for health WebSocket")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    
    _audit_log("ws_authentication", "success", client_id, "health_ws", 
               {"key_type": "ADMIN_API_KEY"})
    return True


# Connection state tracking
class ConnectionState:
    """Tracks state for a single WebSocket connection."""
    
    def __init__(self, connection_id: str, websocket: WebSocket):
        self.connection_id = connection_id
        self.websocket = websocket
        self.connected_at = time.time()
        self.last_ping_at: Optional[float] = None
        self.last_pong_at: Optional[float] = None
        self.last_event_seq: int = 0
        self.missed_events: int = 0
        self.is_healthy: bool = True
        self.reconnect_attempts: int = 0
        self.client_info: Dict[str, Any] = {}
    
    def update_ping(self):
        self.last_ping_at = time.time()
    
    def update_pong(self):
        self.last_pong_at = time.time()
    
    def get_latency_ms(self) -> Optional[float]:
        if self.last_ping_at and self.last_pong_at:
            return (self.last_pong_at - self.last_ping_at) * 1000
        return None
    
    def is_stale(self, threshold_seconds: float = 30.0) -> bool:
        if self.last_pong_at is None:
            return (time.time() - self.connected_at) > threshold_seconds
        return (time.time() - self.last_pong_at) > threshold_seconds


# WebSocket connection manager with reconnect and stale-event handling
class ConnectionManager:
    """Manages WebSocket connections for real-time health updates."""
    
    def __init__(self):
        self.active_connections: Dict[str, ConnectionState] = {}
        self._broadcast_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._interval_seconds = 5.0
        self._heartbeat_interval = 10.0
        self._stale_threshold = 30.0
        self._event_sequence: int = 0
        self._max_reconnect_attempts = 5
        self._reconnect_base_delay = 1.0
        self._reconnect_max_delay = 30.0
        self._health_event_task: Optional[asyncio.Task] = None
        self._health_event_queue: asyncio.Queue = asyncio.Queue()
    
    def set_health_monitor_callback(self):
        """Subscribe to health monitor events for real-time propagation."""
        monitor = get_health_monitor()
        # Wrap the synchronous callback to push to async queue
        def on_health_event(event: HealthEvent):
            try:
                self._health_event_queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Health event queue full, dropping event")
        
        # We can't modify the monitor's callback after creation,
        # so we need to initialize the monitor with our callback
        # This is handled at startup in bootstrap.py
        pass
    
    async def _health_event_processor(self):
        """Process health events from the queue and broadcast them immediately."""
        while True:
            try:
                event = await self._health_event_queue.get()
                
                # Convert HealthEvent to broadcast message
                message = {
                    "type": "health_event",
                    "event": event.to_dict(),
                    "timestamp": event.timestamp,
                }
                
                # Broadcast immediately with sequence number
                await self.broadcast(message)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing health event: {e}")
    
    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection and return connection ID."""
        await websocket.accept()
        connection_id = str(uuid.uuid4())[:8]
        state = ConnectionState(connection_id, websocket)
        self.active_connections[connection_id] = state
        logger.info(f"WebSocket connected [{connection_id}]. Total connections: {len(self.active_connections)}")
        
        # Send initial health snapshot with sequence number
        snapshot = await self.get_health_snapshot()
        snapshot["seq"] = self._event_sequence
        snapshot["connection_id"] = connection_id
        await self.send_personal_message(snapshot, websocket)
        
        # Start broadcast task if not running
        if self._broadcast_task is None or self._broadcast_task.done():
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        
        # Start heartbeat task if not running
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # Start health event processor if not running
        if self._health_event_task is None or self._health_event_task.done():
            self._health_event_task = asyncio.create_task(self._health_event_processor())
        
        return connection_id
    
    def disconnect(self, connection_id: str):
        """Remove a WebSocket connection."""
        state = self.active_connections.pop(connection_id, None)
        if state:
            logger.info(f"WebSocket disconnected [{connection_id}]. Total connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send message to WebSocket: {e}")
            # Find and disconnect the connection
            for conn_id, state in self.active_connections.items():
                if state.websocket == websocket:
                    self.disconnect(conn_id)
                    break
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected WebSockets with sequence number."""
        if not self.active_connections:
            return
        
        self._event_sequence += 1
        message["seq"] = self._event_sequence
        message_text = json.dumps(message)
        disconnected = set()
        
        for connection_id, state in self.active_connections.items():
            try:
                await state.websocket.send_text(message_text)
                # Track sequence for stale detection
                state.last_event_seq = self._event_sequence
            except Exception as e:
                logger.warning(f"Failed to broadcast to WebSocket [{connection_id}]: {e}")
                disconnected.add(connection_id)
        
        # Clean up disconnected connections
        for conn_id in disconnected:
            self.disconnect(conn_id)
    
    async def _broadcast_loop(self):
        """Periodically broadcast health updates to all connections."""
        while self.active_connections:
            try:
                snapshot = await self.get_health_snapshot()
                await self.broadcast(snapshot)
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
            
            await asyncio.sleep(self._interval_seconds)
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat/ping to all connections and detect stale connections."""
        while self.active_connections:
            try:
                current_time = time.time()
                stale_connections = []
                
                for connection_id, state in self.active_connections.items():
                    # Send ping
                    state.update_ping()
                    try:
                        await state.websocket.send_text(json.dumps({
                            "type": "ping",
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "seq": self._event_sequence,
                        }))
                    except Exception as e:
                        logger.warning(f"Failed to send ping to [{connection_id}]: {e}")
                        stale_connections.append(connection_id)
                        continue
                    
                    # Check for stale connections
                    if state.is_stale(self._stale_threshold):
                        logger.warning(f"Connection [{connection_id}] is stale (no pong for {self._stale_threshold}s)")
                        stale_connections.append(connection_id)
                
                # Clean up stale connections
                for conn_id in stale_connections:
                    self.disconnect(conn_id)
                    
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
            
            await asyncio.sleep(self._heartbeat_interval)
    
    async def get_health_snapshot(self) -> Dict[str, Any]:
        """Get current health snapshot for broadcasting."""
        settings = load_settings()
        monitor = get_health_monitor()
        
        # Check camera health
        camera_results = monitor.check_all_health()
        cameras = {}
        for cam_id, result in camera_results.items():
            # Get the snapshot for inference_active
            snap = monitor.get_snapshot(cam_id)
            cameras[cam_id] = {
                "camera_id": result.camera_id,
                "state": result.state.value,
                "timestamp": result.timestamp,
                "message": result.message,
                "frames_received": result.details.get("frames_received", 0),
                "frames_dropped": result.details.get("frames_dropped", 0),
                "total_errors": result.details.get("total_errors", 0),
                "uptime_seconds": result.details.get("uptime_seconds", 0.0),
                "current_resolution": result.details.get("current_resolution"),
                "current_fps": result.details.get("current_fps"),
                "current_codec": result.details.get("current_codec"),
                "last_frame_time": result.last_successful_time,
                "reconnect_count": result.reconnect_count,
                "consecutive_failures": result.consecutive_failures,
                "inference_active": snap.inference_active if snap else False,
            }
        
        # Get GPU/runtime status
        runtime_snapshot = collect_runtime_snapshot()
        gpu = {
            "gpu_name": runtime_snapshot.nvidia_gpu_name or "Unknown",
            "driver_version": runtime_snapshot.nvidia_driver_version or "Unknown",
            "cuda_runtime_version": runtime_snapshot.cuda_runtime_version or "Unknown",
            "cuda_toolkit_version": runtime_snapshot.cuda_toolkit_version or "Unknown",
            "cudnn_version": runtime_snapshot.cudnn_version or "Unknown",
            "pytorch_version": runtime_snapshot.pytorch_version or "Unknown",
            "pytorch_cuda_version": runtime_snapshot.pytorch_cuda_version or "Unknown",
            "torch_cuda_available": runtime_snapshot.torch_cuda_available,
            "onnxruntime_version": runtime_snapshot.onnxruntime_version or "Unknown",
            "cuda_ep_registered": runtime_snapshot.cuda_ep_registered,
            "nvdec_available": runtime_snapshot.ffmpeg_available,
            "model_availability": runtime_snapshot.model_availability,
        }
        
        # Check component health
        components = []
        
        # Database checks
        import os
        db_checks = {
            "parent_registry": {"path": settings.parent_registry.db_path},
            "notification_queue": {"path": settings.notification_queue.db_path},
            "exit_sessions": {"path": settings.exit_session.db_path},
        }
        
        for db_name, db_info in db_checks.items():
            exists = os.path.exists(db_info["path"])
            components.append({
                "component": f"database.{db_name}",
                "status": "healthy" if exists else "unhealthy",
                "message": "Database file exists" if exists else "Database file missing",
                "details": {"path": db_info["path"], "exists": exists},
            })
        
        # Telegram configuration
        tg_configured = bool(settings.telegram.bot_token)
        components.append({
            "component": "telegram",
            "status": "healthy" if tg_configured else "degraded",
            "message": "Telegram bot configured" if tg_configured else "Telegram bot not configured",
            "details": {
                "configured": tg_configured,
                "live_test_enabled": settings.telegram.live_test_enabled,
            },
        })
        
        # Directory checks
        dir_checks = {
            "data": settings.paths.data_dir,
            "logs": settings.paths.logs_dir,
            "models": settings.paths.models_dir,
        }
        for dir_name, dir_path in dir_checks.items():
            exists = os.path.exists(dir_path)
            components.append({
                "component": f"directory.{dir_name}",
                "status": "healthy" if exists else "unhealthy",
                "message": "Directory exists" if exists else "Directory missing",
                "details": {"path": str(dir_path), "exists": exists},
            })
        
        # GPU health
        gpu_healthy = runtime_snapshot.torch_cuda_available and runtime_snapshot.cuda_ep_registered
        components.append({
            "component": "gpu",
            "status": "healthy" if gpu_healthy else "degraded",
            "message": "GPU/CUDA available" if gpu_healthy else "GPU/CUDA not fully available",
            "details": {
                "torch_cuda": runtime_snapshot.torch_cuda_available,
                "cuda_ep": runtime_snapshot.cuda_ep_registered,
                "nvdec": runtime_snapshot.ffmpeg_available,
            },
        })
        
        # Camera health summary
        healthy_cams = sum(1 for c in cameras.values() if c["state"] == "live")
        total_cams = len(cameras)
        if healthy_cams == total_cams:
            cam_status = "healthy"
            cam_message = f"All {total_cams} cameras healthy"
        elif healthy_cams > 0:
            cam_status = "degraded"
            cam_message = f"{healthy_cams}/{total_cams} cameras healthy"
        else:
            cam_status = "unhealthy"
            cam_message = "No cameras healthy"
        
        components.append({
            "component": "cameras",
            "status": cam_status,
            "message": cam_message,
            "details": {"healthy": healthy_cams, "total": total_cams},
        })
        
        # Overall status
        statuses = [c["status"] for c in components]
        if all(s == "healthy" for s in statuses):
            overall = "healthy"
        elif any(s == "unhealthy" for s in statuses):
            overall = "unhealthy"
        else:
            overall = "degraded"
        
        # Queue metrics
        queue_metrics = {}
        try:
            parent_registry = create_parent_registry(settings.parent_registry.db_path)
            notification_queue = create_notification_queue(
                parent_registry=parent_registry,
                telegram_bot=create_telegram_bot(settings.telegram.bot_token),
                db_path=settings.notification_queue.db_path,
            )
            queue_stats = notification_queue.get_queue_stats()
            queue_metrics = {
                "queue_stats": queue_stats,
                "total_pending": queue_stats.get("pending", 0),
                "total_sent": queue_stats.get("sent", 0),
                "total_failed": queue_stats.get("failed", 0),
            }
        except Exception as e:
            queue_metrics = {"error": str(e)}
        
        # Database metrics
        database_metrics = {}
        try:
            parent_registry = create_parent_registry(settings.parent_registry.db_path)
            parents = parent_registry.list_parents()
            database_metrics["parent_registry"] = {
                "total_parents": len(parents),
                "parents_with_chat_id": sum(1 for p in parents if p.telegram_chat_id),
            }
            
            exit_store = create_exit_session_store_from_settings()
            exit_stats = exit_store.get_stats()
            database_metrics["exit_sessions"] = exit_stats
        except Exception as e:
            database_metrics["error"] = str(e)
        
        return {
            "type": "health_update",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "overall_status": overall,
            "components": components,
            "cameras": cameras,
            "gpu": gpu,
            "queue_metrics": queue_metrics,
            "database_metrics": database_metrics,
            "runtime": {
                "python_version": runtime_snapshot.python_version,
                "platform": runtime_snapshot.windows_version,
                "architecture": runtime_snapshot.architecture,
                "venv_active": runtime_snapshot.venv_active,
            },
        }
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Get statistics about active connections."""
        stats = {
            "total_connections": len(self.active_connections),
            "connections": [],
        }
        for conn_id, state in self.active_connections.items():
            stats["connections"].append({
                "connection_id": conn_id,
                "connected_duration_seconds": time.time() - state.connected_at,
                "last_event_seq": state.last_event_seq,
                "missed_events": state.missed_events,
                "latency_ms": state.get_latency_ms(),
                "is_healthy": state.is_healthy,
                "reconnect_attempts": state.reconnect_attempts,
            })
        return stats


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str = Query(..., alias="api_key"),
):
    """WebSocket endpoint for real-time health updates with authentication and reconnect handling."""
    # Create a mock request object for audit logging
    class MockRequest:
        def __init__(self, ws: WebSocket):
            self.headers = ws.headers
            self.client = ws.client
    
    mock_request = MockRequest(websocket)
    
    # Extract or generate correlation ID from headers
    correlation_id = mock_request.headers.get("X-Request-ID")
    if not correlation_id:
        import uuid
        correlation_id = str(uuid.uuid4())
    
    # Bind correlation ID for this connection
    import structlog.contextvars
    token = structlog.contextvars.bind_contextvars(request_id=correlation_id)
    
    # Verify API key
    try:
        await verify_health_ws_key(mock_request, api_key)
    except HTTPException:
        structlog.contextvars.unbind_contextvars(token)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid API key")
        return
    
    connection_id = await manager.connect(websocket)
    state = manager.active_connections.get(connection_id)
    
    # Send welcome message with correlation ID
    welcome = {
        "type": "welcome",
        "connection_id": connection_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "seq": manager._event_sequence,
        "correlation_id": correlation_id,
    }
    await manager.send_personal_message(welcome, websocket)
    
    try:
        while True:
            # Keep connection alive, handle incoming messages
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")
                
                if msg_type == "ping":
                    # Respond to ping with pong
                    if state:
                        state.update_pong()
                    await manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "seq": manager._event_sequence,
                        "correlation_id": correlation_id,
                    }, websocket)
                
                elif msg_type == "pong":
                    # Client responded to our ping
                    if state:
                        state.update_pong()
                
                elif msg_type == "sync":
                    # Client requesting full sync (e.g., after reconnect)
                    snapshot = await manager.get_health_snapshot()
                    snapshot["seq"] = manager._event_sequence
                    snapshot["type"] = "sync_response"
                    snapshot["correlation_id"] = correlation_id
                    await manager.send_personal_message(snapshot, websocket)
                
                elif msg_type == "ack":
                    # Client acknowledging receipt of event
                    ack_seq = msg.get("seq", 0)
                    if state and ack_seq > state.last_event_seq:
                        state.last_event_seq = ack_seq
                
                elif msg_type == "subscribe":
                    # Client subscribing to specific event types
                    event_types = msg.get("events", ["health_update"])
                    if state:
                        state.client_info["subscriptions"] = event_types
                    await manager.send_personal_message({
                        "type": "subscribed",
                        "events": event_types,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "correlation_id": correlation_id,
                    }, websocket)
                    
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from [{connection_id}]: {data[:100]}")
                
    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"WebSocket error [{connection_id}]: {e}")
        manager.disconnect(connection_id)
    finally:
        structlog.contextvars.unbind_contextvars(token)


@router.get("/stream")
async def sse_endpoint(
    request: Request,
    api_key: str = Query(..., alias="api_key"),
):
    """Server-Sent Events endpoint for real-time health updates with authentication and reconnect support."""
    # Extract or generate correlation ID from headers
    correlation_id = request.headers.get("X-Request-ID")
    if not correlation_id:
        import uuid
        correlation_id = str(uuid.uuid4())
    
    # Bind correlation ID for this request
    import structlog.contextvars
    token = structlog.contextvars.bind_contextvars(request_id=correlation_id)
    
    # Verify API key
    try:
        await verify_health_ws_key(request, api_key)
    except HTTPException:
        structlog.contextvars.unbind_contextvars(token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    
    async def event_generator():
        """Generate SSE events with sequence numbers for reconnect handling."""
        # Get client's last known sequence from query params or headers
        last_seq = 0
        try:
            last_seq = int(request.query_params.get("last_seq", "0"))
        except ValueError:
            pass
        
        # Send initial snapshot with correlation ID
        snapshot = await manager.get_health_snapshot()
        snapshot["seq"] = manager._event_sequence
        snapshot["correlation_id"] = correlation_id
        yield f"data: {json.dumps(snapshot)}\n\n"
        
        # Keep sending updates
        while True:
            if await request.is_disconnected():
                break
            
            try:
                snapshot = await manager.get_health_snapshot()
                # Only send if sequence has advanced (avoid duplicates)
                if snapshot.get("seq", 0) > last_seq:
                    snapshot["correlation_id"] = correlation_id
                    yield f"data: {json.dumps(snapshot)}\n\n"
                    last_seq = snapshot.get("seq", 0)
            except Exception as e:
                logger.error(f"Error generating SSE event: {e}")
                error_msg = {"type": "error", "message": str(e), "correlation_id": correlation_id}
                yield f"data: {json.dumps(error_msg)}\n\n"
            
            await asyncio.sleep(5.0)
    
    try:
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    finally:
        structlog.contextvars.unbind_contextvars(token)


class HealthSnapshotResponse(BaseModel):
    """Response model for health snapshot."""
    type: str
    timestamp: str
    overall_status: str
    components: List[Dict[str, Any]]
    cameras: Dict[str, Dict[str, Any]]
    gpu: Dict[str, Any]
    queue_metrics: Dict[str, Any]
    database_metrics: Dict[str, Any]
    runtime: Dict[str, Any]


@router.get("/snapshot", response_model=HealthSnapshotResponse)
async def get_health_snapshot():
    """Get a single health snapshot (for polling fallback)."""
    return await manager.get_health_snapshot()


@router.get("/connections")
async def get_connection_stats():
    """Get WebSocket connection statistics."""
    return manager.get_connection_stats()


@router.post("/ws/reconnect")
async def handle_reconnect(request: Request):
    """Handle explicit reconnect request from client."""
    data = await request.json()
    last_seq = data.get("last_seq", 0)
    connection_id = data.get("connection_id")
    
    # Get current snapshot
    snapshot = await manager.get_health_snapshot()
    snapshot["seq"] = manager._event_sequence
    snapshot["type"] = "reconnect_response"
    snapshot["missed_events"] = max(0, manager._event_sequence - last_seq)
    
    return snapshot
