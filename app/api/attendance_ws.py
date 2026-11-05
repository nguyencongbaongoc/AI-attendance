"""
Phase 6 + Phase 7 — Attendance WebSocket Real-time Event Delivery with Security Hardening.

Provides authenticated WebSocket endpoint for real-time attendance events.
Integrates with AttendanceEngine for event push on record creation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config.settings import load_settings
from app.attendance.contract import AttendanceRecord, AttendanceDirection, IdentityCertainty
from app.security.api_key_cache import get_api_key_cache
from app.logging.logger import get_logger, log_failure

# Use structlog logger for structured audit logging
audit_logger = get_logger("app.security.audit")

# Use structlog logger for structured observability
logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/attendance", tags=["attendance"])


# =============================================================================
# Security: Audit Logging
# =============================================================================

def _get_correlation_id() -> str:
    """Get correlation ID from structlog context."""
    import structlog.contextvars
    ctx = structlog.contextvars.get_contextvars()
    return ctx.get("request_id", "unknown")


def _audit_log(event_type: str, outcome: str, actor: str, resource: str, details: dict = None, 
               failure_class: str = None, failure_reason: str = None, retry_state: str = "none"):
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
    if failure_class:
        audit_data["failure_class"] = failure_class
    if failure_reason:
        audit_data["failure_reason"] = failure_reason
    if retry_state != "none":
        audit_data["retry_state"] = retry_state
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
# Authentication
# =============================================================================

async def verify_attendance_ws_key(
    request: Request,
    api_key: str = Query(..., alias="api_key"),
) -> bool:
    """Verify API key for attendance WebSocket connection with audit logging."""
    client_id = _get_client_identifier(request)
    cache = get_api_key_cache()
    
    admin_key = cache.get("ADMIN_API_KEY")
    worker_key = cache.get("AI_WORKER_API_KEY")
    
    if not admin_key and not worker_key:
        _audit_log("ws_authentication", "failure", client_id, "attendance_ws", 
                   {"reason": "keys_not_configured"},
                   failure_class="AuthenticationError", failure_reason="keys_not_configured")
        logger.error("Neither ADMIN_API_KEY nor AI_WORKER_API_KEY configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attendance WebSocket API keys not configured"
        )
    
    valid_keys = [k for k in [admin_key, worker_key] if k]
    if not any(secrets.compare_digest(api_key, k) for k in valid_keys):
        _audit_log("ws_authentication", "failure", client_id, "attendance_ws", 
                   {"reason": "invalid_key"},
                   failure_class="AuthenticationError", failure_reason="invalid_key")
        logger.warning("Invalid API key for attendance WebSocket")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    
    _audit_log("ws_authentication", "success", client_id, "attendance_ws", 
               {"key_type": "ADMIN_API_KEY" if secrets.compare_digest(api_key, admin_key or "") else "AI_WORKER_API_KEY"})
    return True


# =============================================================================
# Connection State
# =============================================================================

class AttendanceConnectionState:
    """Tracks state for a single attendance WebSocket connection."""
    
    def __init__(self, connection_id: str, websocket: WebSocket, api_key: str):
        self.connection_id = connection_id
        self.websocket = websocket
        self.api_key = api_key
        self.connected_at = time.time()
        self.last_ping_at: Optional[float] = None
        self.last_pong_at: Optional[float] = None
        self.last_event_seq: int = 0
        self.is_healthy: bool = True
        self.subscriptions: Set[str] = {"attendance.created"}
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


# =============================================================================
# Connection Manager
# =============================================================================

class AttendanceConnectionManager:
    """Manages WebSocket connections for real-time attendance events."""
    
    def __init__(self):
        self.active_connections: Dict[str, AttendanceConnectionState] = {}
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval = 10.0
        self._stale_threshold = 30.0
        self._event_sequence: int = 0
        self._max_reconnect_attempts = 5
        self._reconnect_base_delay = 1.0
        self._reconnect_max_delay = 30.0
    
    async def connect(self, websocket: WebSocket, api_key: str) -> str:
        """Accept a new WebSocket connection and return connection ID."""
        await websocket.accept()
        connection_id = str(uuid.uuid4())[:8]
        state = AttendanceConnectionState(connection_id, websocket, api_key)
        self.active_connections[connection_id] = state
        logger.info(f"Attendance WebSocket connected [{connection_id}]. Total: {len(self.active_connections)}")
        
        # Send welcome message with connection info
        welcome = {
            "type": "welcome",
            "connection_id": connection_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "seq": self._event_sequence,
            "server_time": time.time(),
        }
        await self.send_personal_message(welcome, websocket)
        
        # Start heartbeat task if not running
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        return connection_id
    
    def disconnect(self, connection_id: str):
        """Remove a WebSocket connection."""
        state = self.active_connections.pop(connection_id, None)
        if state:
            from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
            log_failure(
                logger, "WebSocket disconnected", "attendance_ws", "disconnect",
                "WebSocketDisconnect", "client_disconnected",
                retry_state="none",
                correlation_id=_get_correlation_id(),
                connection_id=connection_id,
            )
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Send a message to a specific WebSocket."""
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception as e:
            logger.warning(f"Failed to send message to WebSocket: {e}")
            # Find and disconnect the connection
            for conn_id, state in self.active_connections.items():
                if state.websocket == websocket:
                    self.disconnect(conn_id)
                    break
    
    async def broadcast(self, message: Dict[str, Any], subscription_filter: Optional[str] = None):
        """Broadcast a message to all connected WebSockets with optional subscription filter."""
        if not self.active_connections:
            return
        
        self._event_sequence += 1
        message["seq"] = self._event_sequence
        message["timestamp"] = message.get("timestamp", datetime.utcnow().isoformat() + "Z")
        message_text = json.dumps(message, default=str)
        disconnected = set()
        
        for connection_id, state in self.active_connections.items():
            # Check subscription filter
            if subscription_filter and subscription_filter not in state.subscriptions:
                continue
            
            try:
                await state.websocket.send_text(message_text)
                state.last_event_seq = self._event_sequence
            except Exception as e:
                logger.warning(f"Failed to broadcast to [{connection_id}]: {e}")
                disconnected.add(connection_id)
        
        # Clean up disconnected connections
        for conn_id in disconnected:
            self.disconnect(conn_id)
    
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
                        from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
                        log_failure(
                            logger, "WebSocket stale", "attendance_ws", "heartbeat",
                            "WebSocketStale", "no_pong_timeout",
                            retry_state="none",
                            correlation_id=_get_correlation_id(),
                            connection_id=connection_id,
                            stale_threshold=self._stale_threshold,
                        )
                        stale_connections.append(connection_id)
                
                # Clean up stale connections
                for conn_id in stale_connections:
                    self.disconnect(conn_id)
                    
            except Exception as e:
                logger.error(f"Error in attendance heartbeat loop: {e}")
            
            await asyncio.sleep(self._heartbeat_interval)
    
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
                "latency_ms": state.get_latency_ms(),
                "is_healthy": state.is_healthy,
                "subscriptions": list(state.subscriptions),
            })
        return stats


# Global connection manager
attendance_manager = AttendanceConnectionManager()


# =============================================================================
# Event Delivery Client
# =============================================================================

class EventDeliveryClient:
    """Client for delivering attendance events to WebSocket connections.
    
    Used by AttendanceEngine to push events after persistence.
    """
    
    def __init__(self, manager: AttendanceConnectionManager):
        self.manager = manager
        self._sent_event_ids: Set[str] = set()  # For idempotency
        self._max_sent_cache = 10000
        self._retry_queue: asyncio.Queue = asyncio.Queue()
        self._retry_task: Optional[asyncio.Task] = None
        self._max_retries = 3
        self._base_retry_delay = 1.0
    
    async def start(self):
        """Start the retry processor."""
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(self._retry_processor())
    
    async def stop(self):
        """Stop the retry processor."""
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
    
    def _check_idempotency(self, attendance_record_id: str) -> bool:
        """Check if event was already sent (idempotency)."""
        if attendance_record_id in self._sent_event_ids:
            logger.debug(f"Duplicate attendance event suppressed: {attendance_record_id}")
            return True
        
        # Add to cache
        self._sent_event_ids.add(attendance_record_id)
        
        # Limit cache size
        if len(self._sent_event_ids) > self._max_sent_cache:
            # Remove oldest entries (simple FIFO - in production use LRU)
            to_remove = len(self._sent_event_ids) - self._max_sent_cache
            for _ in range(to_remove):
                self._sent_event_ids.pop()
        
        return False
    
    async def push_attendance_event(self, record: AttendanceRecord) -> bool:
        """Push an attendance event to all connected WebSocket clients.
        
        Returns True if event was sent (or already sent), False on failure.
        """
        try:
            # Idempotency check
            if self._check_idempotency(record.attendance_record_id):
                return True  # Already sent, not an error
            
            # Build event message
            message = self._build_event_message(record)
            
            # Broadcast to all connections subscribed to attendance events
            await self.manager.broadcast(message, subscription_filter="attendance.created")
            
            logger.debug(f"Pushed attendance event: {record.attendance_record_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to push attendance event {record.attendance_record_id}: {e}")
            # Queue for retry
            await self._queue_for_retry(record)
            return False
    
    def _build_event_message(self, record: AttendanceRecord) -> Dict[str, Any]:
        """Build WebSocket message from AttendanceRecord."""
        return {
            "type": "attendance.created",
            "event": {
                "attendance_record_id": record.attendance_record_id,
                "source_resolution_id": record.source_resolution_id,
                "person_id": record.identity_candidate,
                "person_name": f"Person {record.identity_candidate or record.local_track_id}",
                "camera_id": record.camera_id,
                "local_track_id": record.local_track_id,
                "global_observation_id": record.global_observation_id or "",
                "direction": record.direction.value if hasattr(record.direction, "value") else record.direction,
                "identity_certainty": record.identity_certainty.value if hasattr(record.identity_certainty, "value") else record.identity_certainty,
                "identity_candidate": record.identity_candidate,
                "identity_confidence": float(record.identity_confidence or 0.0),
                "event_timestamp": float(record.event_timestamp),
                "timestamp_iso": datetime.utcfromtimestamp(record.event_timestamp).isoformat() + "Z",
                "attendance_state": record.new_state,
                # GIS evidence fields
                "face_evidence_ref": record.face_evidence_ref,
                "body_evidence_ref": record.body_evidence_ref,
                "face_quality": float(record.face_quality or 0.0),
                "body_quality": float(record.body_quality or 0.0),
                "association_method": record.association_method,
                "conflict_flag": record.conflict_flag,
                "provisional_person_id": record.provisional_person_id,
                "identity_state": record.identity_state,
                # Provenance
                "source_raw_event_id": record.source_raw_event_id,
                "source_crossing_event_id": record.source_crossing_event_id,
                "geometry_version": record.geometry_version,
                "geometry_config_hash": record.geometry_config_hash,
                "resolver_version": record.resolver_version,
                "resolver_config_hash": record.resolver_config_hash,
            }
        }
    
    async def _queue_for_retry(self, record: AttendanceRecord):
        """Queue event for retry delivery."""
        retry_data = {
            "record": record,
            "attempts": 0,
            "next_retry": time.time() + self._base_retry_delay,
        }
        try:
            self._retry_queue.put_nowait(retry_data)
        except asyncio.QueueFull:
            logger.error(f"Retry queue full, dropping event {record.attendance_record_id}")
    
    async def _retry_processor(self):
        """Process retry queue with exponential backoff."""
        while True:
            try:
                retry_data = await self._retry_queue.get()
                
                record = retry_data["record"]
                attempts = retry_data["attempts"]
                next_retry = retry_data["next_retry"]
                
                # Wait until retry time
                wait_time = max(0, next_retry - time.time())
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                if attempts >= self._max_retries:
                    from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
                    log_failure(
                        logger, "Event delivery failed after retries", "attendance_ws", "push_event",
                        "DeliveryFailed", "max_retries_exceeded",
                        retry_state="exhausted",
                        correlation_id=_get_correlation_id(),
                        attendance_record_id=record.attendance_record_id,
                        attempts=attempts,
                    )
                    continue
                
                # Try to send again
                success = await self.push_attendance_event(record)
                if success:
                    from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
                    logger.info(
                        "Event delivery retry successful",
                        component="attendance_ws",
                        action="push_event",
                        result="success",
                        failure_class="DeliveryRetry",
                        failure_reason="retry_succeeded",
                        retry_state="success",
                        attendance_record_id=record.attendance_record_id,
                        attempts=attempts,
                        correlation_id=_get_correlation_id(),
                    )
                else:
                    from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
                    log_failure(
                        logger, "Event delivery retry", "attendance_ws", "push_event",
                        "DeliveryRetry", "delivery_failed",
                        retry_state="retrying",
                        correlation_id=_get_correlation_id(),
                        attendance_record_id=record.attendance_record_id,
                        attempt=attempts + 1,
                        max_retries=self._max_retries,
                    )
                    # Re-queue with exponential backoff
                    delay = self._base_retry_delay * (2 ** attempts)
                    retry_data["attempts"] = attempts + 1
                    retry_data["next_retry"] = time.time() + delay
                    await self._retry_queue.put(retry_data)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
                log_failure(
                    logger, "Error in retry processor", "attendance_ws", "retry_processor",
                    "RetryProcessorError", str(e),
                    retry_state="none",
                    correlation_id=_get_correlation_id(),
                )
                await asyncio.sleep(1.0)


# Global event delivery client
_event_delivery_client: Optional[EventDeliveryClient] = None


def get_event_delivery_client() -> EventDeliveryClient:
    """Get or create the global event delivery client."""
    global _event_delivery_client
    if _event_delivery_client is None:
        _event_delivery_client = EventDeliveryClient(attendance_manager)
    return _event_delivery_client


# =============================================================================
# WebSocket Endpoint
# =============================================================================

@router.websocket("/ws")
async def attendance_websocket_endpoint(
    websocket: WebSocket,
    api_key: str = Query(..., alias="api_key"),
):
    """WebSocket endpoint for real-time attendance events with authentication."""
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
        await verify_attendance_ws_key(mock_request, api_key)
    except HTTPException:
        structlog.contextvars.unbind_contextvars(token)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid API key")
        return
    
    connection_id = await attendance_manager.connect(websocket, api_key)
    state = attendance_manager.active_connections.get(connection_id)
    
    # Send welcome message with correlation ID
    welcome = {
        "type": "welcome",
        "connection_id": connection_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "seq": attendance_manager._event_sequence,
        "server_time": time.time(),
        "correlation_id": correlation_id,
    }
    await attendance_manager.send_personal_message(welcome, websocket)
    
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
                    await attendance_manager.send_personal_message({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "seq": attendance_manager._event_sequence,
                        "correlation_id": correlation_id,
                    }, websocket)
                
                elif msg_type == "pong":
                    # Client responded to our ping
                    if state:
                        state.update_pong()
                
                elif msg_type == "sync":
                    # Client requesting full sync (e.g., after reconnect)
                    snapshot = await _get_attendance_snapshot()
                    snapshot["seq"] = attendance_manager._event_sequence
                    snapshot["type"] = "sync_response"
                    snapshot["correlation_id"] = correlation_id
                    await attendance_manager.send_personal_message(snapshot, websocket)
                
                elif msg_type == "ack":
                    # Client acknowledging receipt of event
                    ack_seq = msg.get("seq", 0)
                    if state and ack_seq > state.last_event_seq:
                        state.last_event_seq = ack_seq
                
                elif msg_type == "subscribe":
                    # Client subscribing to specific event types
                    event_types = msg.get("events", ["attendance.created"])
                    if state:
                        state.subscriptions = set(event_types)
                    await attendance_manager.send_personal_message({
                        "type": "subscribed",
                        "events": event_types,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "correlation_id": correlation_id,
                    }, websocket)
                    
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from attendance WS [{connection_id}]: {data[:100]}")
                
    except WebSocketDisconnect:
        from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
        log_failure(
            logger, "WebSocket disconnected", "attendance_ws", "disconnect",
            "WebSocketDisconnect", "client_disconnected",
            retry_state="none",
            correlation_id=_get_correlation_id(),
            connection_id=connection_id,
        )
        attendance_manager.disconnect(connection_id)
    except Exception as e:
        from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
        log_failure(
            logger, "Attendance WebSocket error", "attendance_ws", "endpoint",
            "WebSocketError", str(e),
            retry_state="none",
            correlation_id=_get_correlation_id(),
            connection_id=connection_id,
        )
        attendance_manager.disconnect(connection_id)
    finally:
        structlog.contextvars.unbind_contextvars(token)


async def _get_attendance_snapshot() -> Dict[str, Any]:
    """Get current attendance snapshot for sync."""
    from app.attendance.repository import AttendanceRepository, create_attendance_repository
    
    repo = create_attendance_repository()
    stats = repo.get_stats()
    recent = repo.storage.query(limit=10, order_by="event_timestamp", order_desc=True)
    
    return {
        "type": "attendance_snapshot",
        "stats": stats,
        "recent_events": [
            {
                "attendance_record_id": r.attendance_record_id,
                "source_resolution_id": r.source_resolution_id,
                "person_id": r.identity_candidate,
                "camera_id": r.camera_id,
                "direction": r.direction.value if hasattr(r.direction, "value") else r.direction,
                "event_timestamp": r.event_timestamp,
                "identity_certainty": r.identity_certainty.value if hasattr(r.identity_certainty, "value") else r.identity_certainty,
                "identity_confidence": float(r.identity_confidence or 0.0),
            }
            for r in recent
        ],
    }


# =============================================================================
# REST Endpoints for WebSocket Management
# =============================================================================

@router.get("/ws/stats")
async def get_attendance_ws_stats():
    """Get WebSocket connection statistics."""
    return attendance_manager.get_connection_stats()


@router.post("/ws/reconnect")
async def handle_attendance_reconnect(request: Request):
    """Handle explicit reconnect request from client."""
    data = await request.json()
    last_seq = data.get("last_seq", 0)
    connection_id = data.get("connection_id")
    
    # Get current snapshot
    snapshot = await _get_attendance_snapshot()
    snapshot["seq"] = attendance_manager._event_sequence
    snapshot["type"] = "reconnect_response"
    snapshot["missed_events"] = max(0, attendance_manager._event_sequence - last_seq)
    
    return snapshot


# Need Request import
from fastapi import Request

__all__ = ["router", "attendance_manager", "get_event_delivery_client", "EventDeliveryClient"]