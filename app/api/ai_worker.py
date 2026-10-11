"""
Phase 0.2.6 + Phase 7 — AI Worker Integration API with Security Hardening.

REST endpoints for PipelineEngine (AI Worker) integration with Legacy Backend.
Provides event ingestion, health reporting, and control endpoints.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, validator

from app.attendance.contract import AttendanceDirection, IdentityCertainty
from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.in_out.raw_event import RawInOutEvent, RawEventDirection, RawEventType
from app.in_out.contract import IdentityCertainty as RawIdentityCertainty
from app.in_out.resolver import RepeatedInOutResolver, create_repeated_in_out_resolver
from app.config.settings import load_settings
from fractions import Fraction
from app.logging.logger import get_logger, log_failure

# Use structlog logger for structured audit logging
audit_logger = get_logger("app.security.audit")

# Use structlog logger for structured observability
logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ai-worker"])


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
        "outcome": outcome,  # success, failure, rejected
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
        # Redact any sensitive fields
        safe_details = {}
        for k, v in details.items():
            if any(sensitive in k.lower() for sensitive in ["key", "token", "secret", "password", "credential"]):
                safe_details[k] = "***REDACTED***"
            else:
                safe_details[k] = v
        audit_data["details"] = safe_details
    
    # Use structured logging
    audit_logger.info(f"Security audit: {event_type} - {outcome}", **audit_data)


def _get_client_identifier(request: Request) -> str:
    """Extract client identifier for audit logging."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# =============================================================================
# Dependency: API Key Verification (with caching and audit logging)
# =============================================================================

async def verify_ai_worker_key(request: Request, x_api_key: str = Header(..., alias="X-API-Key")):
    """Verify AI Worker API key with audit logging."""
    client_id = _get_client_identifier(request)
    expected = get_api_key_cache().get("AI_WORKER_API_KEY")
    
    if not expected:
        _audit_log("authentication", "failure", client_id, "ai_worker_key", 
                   {"reason": "key_not_configured", "key_type": "AI_WORKER_API_KEY"},
                   failure_class="AuthenticationError", failure_reason="key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Worker API key not configured"
        )
    
    if not secrets.compare_digest(x_api_key, expected):
        _audit_log("authentication", "failure", client_id, "ai_worker_key", 
                   {"reason": "invalid_key", "key_type": "AI_WORKER_API_KEY"},
                   failure_class="AuthenticationError", failure_reason="invalid_key")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AI Worker API key")
    
    _audit_log("authentication", "success", client_id, "ai_worker_key", {"key_type": "AI_WORKER_API_KEY"})
    return True


async def verify_ai_control_key(request: Request, x_api_key: str = Header(..., alias="X-API-Key")):
    """Verify AI Control API key with audit logging."""
    client_id = _get_client_identifier(request)
    expected = get_api_key_cache().get("AI_CONTROL_API_KEY")
    
    if not expected:
        _audit_log("authentication", "failure", client_id, "ai_control_key", 
                   {"reason": "key_not_configured", "key_type": "AI_CONTROL_API_KEY"},
                   failure_class="AuthenticationError", failure_reason="key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Control API key not configured"
        )
    
    if not secrets.compare_digest(x_api_key, expected):
        _audit_log("authentication", "failure", client_id, "ai_control_key", 
                   {"reason": "invalid_key", "key_type": "AI_CONTROL_API_KEY"},
                   failure_class="AuthenticationError", failure_reason="invalid_key")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AI Control API key")
    
    _audit_log("authentication", "success", client_id, "ai_control_key", {"key_type": "AI_CONTROL_API_KEY"})
    return True


async def verify_admin_key(request: Request, x_api_key: str = Header(..., alias="X-API-Key")):
    """Verify Admin API key for enrollment operations with audit logging."""
    client_id = _get_client_identifier(request)
    expected = get_api_key_cache().get("ADMIN_API_KEY")
    
    if not expected:
        _audit_log("authentication", "failure", client_id, "admin_key", 
                   {"reason": "key_not_configured", "key_type": "ADMIN_API_KEY"},
                   failure_class="AuthenticationError", failure_reason="key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured"
        )
    
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        _audit_log("authentication", "failure", client_id, "admin_key", 
                   {"reason": "invalid_key", "key_type": "ADMIN_API_KEY"},
                   failure_class="AuthenticationError", failure_reason="invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Admin API key"
        )
    
    _audit_log("authentication", "success", client_id, "admin_key", {"key_type": "ADMIN_API_KEY"})
    return True


def get_api_key_cache():
    """Get API key cache - imported from security to avoid circular imports."""
    from app.security.api_key_cache import get_api_key_cache as _get_cache
    return _get_cache()


# =============================================================================
# Pydantic Models
# =============================================================================

class TimeBase(BaseModel):
    """Stream time base."""
    num: int = 1
    den: int = 90000


class CrossingPoint(BaseModel):
    """Crossing point coordinates."""
    x: float
    y: float


class Position(BaseModel):
    """Track position."""
    x: float
    y: float


class CameraState(BaseModel):
    """Camera state for health reporting."""
    state: str
    last_frame_timestamp: float
    decode_fps: float
    inference_fps: float
    track_count: int


class ModelReadiness(BaseModel):
    """Model readiness status."""
    scrfd: bool
    arcface: bool
    yolo: bool


class CrossingEventRequest(BaseModel):
    """CrossingEvent from PipelineEngine."""
    event_id: str = Field(..., description="Globally unique event ID, stable across retries")
    camera_id: str = Field(..., description="Camera identifier")
    track_id: int = Field(..., description="Local track ID")
    direction: str = Field(..., description="Crossing direction: 'in' or 'out'")
    event_type: str = Field(default="line_crossing", description="Event type")
    crossing_point: Optional[CrossingPoint] = None
    timestamp: float = Field(..., description="Unix timestamp (seconds)")
    frame_index: int = Field(..., description="Frame index in stream")
    previous_position: Optional[Position] = None
    current_position: Optional[Position] = None
    person_id: Optional[str] = None
    person_name: Optional[str] = None
    identity_confidence: Optional[float] = None
    stream_epoch: int = Field(..., description="Stream session epoch (increments on reconnect)")
    pts: int = Field(..., description="Presentation timestamp from container")
    time_base: TimeBase = Field(default_factory=TimeBase, description="Stream time base")
    capture_timestamp: float = Field(..., description="Wall-clock at frame capture")
    processing_timestamp: float = Field(..., description="Wall-clock at AI processing complete")
    model_version: str = Field(..., description="Model versions used")
    enrollment_version: str = Field(..., description="Enrollment database version")
    provenance: str = Field(default="pipeline_engine_v1", description="Provenance identifier")
    schema_version: str = Field(default="1.0", description="Schema version")

    @validator("direction")
    def validate_direction(cls, v):
        if v not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")
        return v


class CrossingEventResponse(BaseModel):
    """Response for event ingestion."""
    success: bool
    event_id: str
    source_resolution_id: Optional[str] = None
    status: str
    message: str


class AIWorkerHealthRequest(BaseModel):
    """AI Worker health heartbeat."""
    worker_id: str = Field(..., description="Worker identifier")
    worker_version: str = Field(..., description="Worker software version")
    state: str = Field(..., description="Worker state: starting, initializing, ready, degraded, failed, stopping, stopped")
    timestamp: float = Field(..., description="Unix timestamp")
    sequence_number: int = Field(..., description="Monotonically increasing sequence number")
    camera_states: Dict[str, CameraState] = Field(default_factory=dict)
    model_readiness: ModelReadiness = Field(default_factory=lambda: ModelReadiness(scrfd=False, arcface=False, yolo=False))
    gpu_provider: str = Field(default="CUDAExecutionProvider")
    queue_depth: int = 0
    processing_latency_ms: float = 0.0
    dropped_frames: int = 0
    stream_epochs: Dict[str, int] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class AIWorkerHealthResponse(BaseModel):
    """Health acknowledgment response."""
    success: bool
    worker_id: str
    acknowledged: bool
    server_timestamp: float
    sequence_number: int
    commands: List[str] = Field(default_factory=list)
    stale_threshold_seconds: float = 30.0


class ControlRequestStatus(str):
    """Control request status."""
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ControlAction(str):
    """Supported control actions."""
    START_WORKER = "START_WORKER"
    STOP_WORKER = "STOP_WORKER"
    RESTART_WORKER = "RESTART_WORKER"
    ENABLE_CAMERA = "ENABLE_CAMERA"
    DISABLE_CAMERA = "DISABLE_CAMERA"
    GET_STATUS = "GET_STATUS"


class ControlTarget(str):
    """Control target type."""
    WORKER = "worker"
    CAMERA = "camera"


class ControlRequest(BaseModel):
    """Control request from Legacy Backend to PipelineEngine."""
    request_id: str = Field(..., description="Unique request identifier")
    action: str = Field(..., description="Control action")
    target: str = Field(..., description="Target: worker or camera")
    target_id: str = Field(..., description="Worker ID or camera ID")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(..., description="Idempotency key for deduplication")
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(..., description="Request expiration timestamp")


class ControlResponse(BaseModel):
    """PipelineEngine response to control request."""
    success: bool
    action: str
    worker_id: str
    status: str  # ACCEPTED, RUNNING, COMPLETED, FAILED, REJECTED, EXPIRED
    request_id: str
    timestamp: float
    details: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PendingControlRequests(BaseModel):
    """Pending control requests response."""
    worker_id: str
    requests: List[ControlRequest]


# =============================================================================
# Health State Management
# =============================================================================

VALID_WORKER_STATES = {"starting", "initializing", "ready", "degraded", "failed", "stopping", "stopped"}

@dataclass
class WorkerHealthState:
    """Worker health state with generation tracking."""
    worker_id: str
    worker_version: str
    reported_state: str
    health_status: str  # "healthy", "degraded", "unhealthy", "stale", "unknown"
    last_report_timestamp: float
    last_sequence: int
    generation_id: int  # Increments on worker restart (sequence reset)
    camera_states: Dict[str, CameraState] = field(default_factory=dict)
    model_readiness: ModelReadiness = field(default_factory=lambda: ModelReadiness(scrfd=False, arcface=False, yolo=False))
    gpu_provider: str = "CUDAExecutionProvider"
    queue_depth: int = 0
    processing_latency_ms: float = 0.0
    dropped_frames: int = 0
    stream_epochs: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    state_updated_at: float = field(default_factory=time.time)


# In-memory health state store
_worker_health_states: Dict[str, WorkerHealthState] = {}


def _validate_health_request(health: AIWorkerHealthRequest, worker_state: Optional[WorkerHealthState]) -> tuple[bool, str, int]:
    """
    Validate health request sequence and generation.
    
    Returns: (is_valid, error_message, new_generation_id)
    """
    # Validate state enum
    if health.state not in VALID_WORKER_STATES:
        return False, f"Invalid state '{health.state}'. Valid: {sorted(VALID_WORKER_STATES)}", 0
    
    if worker_state is None:
        # First report for this worker - sequence must be 1
        if health.sequence_number != 1:
            return False, f"First report must have sequence_number=1, got {health.sequence_number}", 1
        return True, "", 1
    
    # Check for worker restart (sequence reset to 1 after having higher sequences)
    # This MUST come before the duplicate check
    if health.sequence_number == 1 and worker_state.last_sequence > 1:
        # Worker restarted - new generation
        new_generation = worker_state.generation_id + 1
        from app.middleware.correlation_id import get_correlation_id as _get_correlation_id
        log_failure(
            logger, "Worker restarted", "ai_worker", "health_check",
            "WorkerRestart", "sequence_reset",
            retry_state="none",
            correlation_id=_get_correlation_id(),
            worker_id=health.worker_id,
            generation=new_generation,
            previous_generation=worker_state.generation_id,
        )
        return True, "", new_generation
    
    # Check for duplicate or stale sequence (same or lower than last)
    if health.sequence_number <= worker_state.last_sequence:
        return False, f"Stale or duplicate sequence: got {health.sequence_number}, last was {worker_state.last_sequence}", worker_state.generation_id
    
    # Normal sequence validation - must be exactly next sequence
    expected_sequence = worker_state.last_sequence + 1
    if health.sequence_number != expected_sequence:
        return False, f"Sequence gap: got {health.sequence_number}, expected {expected_sequence}", worker_state.generation_id
    
    return True, "", worker_state.generation_id


def _update_worker_health(health: AIWorkerHealthRequest, generation_id: int) -> WorkerHealthState:
    """Update or create worker health state."""
    now = time.time()
    
    # Determine health status based on reported state and staleness
    if health.state in ("ready", "initializing", "starting"):
        health_status = "healthy"
    elif health.state == "degraded":
        health_status = "degraded"
    elif health.state in ("failed", "stopping", "stopped"):
        health_status = "unhealthy"
    else:
        health_status = "unknown"
    
    state = WorkerHealthState(
        worker_id=health.worker_id,
        worker_version=health.worker_version,
        reported_state=health.state,
        health_status=health_status,
        last_report_timestamp=health.timestamp,
        last_sequence=health.sequence_number,
        generation_id=generation_id,
        camera_states=health.camera_states,
        model_readiness=health.model_readiness,
        gpu_provider=health.gpu_provider,
        queue_depth=health.queue_depth,
        processing_latency_ms=health.processing_latency_ms,
        dropped_frames=health.dropped_frames,
        stream_epochs=health.stream_epochs,
        errors=health.errors,
        state_updated_at=now,
    )
    
    _worker_health_states[health.worker_id] = state
    return state


def _check_stale_workers(threshold_seconds: float = 30.0) -> List[str]:
    """Check for stale workers and update their health status."""
    now = time.time()
    stale_workers = []
    for worker_id, state in _worker_health_states.items():
        if now - state.last_report_timestamp > threshold_seconds:
            if state.health_status != "stale":
                state.health_status = "stale"
                state.state_updated_at = now
                stale_workers.append(worker_id)
                logger.warning(f"Worker {worker_id} marked as stale (last report: {now - state.last_report_timestamp:.1f}s ago)")
    return stale_workers


# =============================================================================
# Control State Management
# =============================================================================

@dataclass
class PendingControlRequest:
    """Pending control request with metadata."""
    request: ControlRequest
    status: str = ControlRequestStatus.PENDING
    created_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    completed_at: Optional[float] = None
    response: Optional[ControlResponse] = None


# In-memory storage for pending control requests
_pending_control_requests: Dict[str, PendingControlRequest] = {}
# Idempotency key storage
_processed_idempotency_keys: Dict[str, ControlResponse] = {}


def _cleanup_expired_requests():
    """Remove expired control requests."""
    now = time.time()
    expired_keys = [
        key for key, req in _pending_control_requests.items()
        if req.request.expires_at < now
    ]
    for key in expired_keys:
        del _pending_control_requests[key]


# =============================================================================
# Global Instances
# =============================================================================

_repository: Optional[AttendanceRepository] = None
_resolver: Optional[RepeatedInOutResolver] = None


def get_repository() -> AttendanceRepository:
    """Get or create the global attendance repository."""
    global _repository
    if _repository is None:
        _repository = create_attendance_repository()
    return _repository


def get_resolver() -> RepeatedInOutResolver:
    """Get or create the resolver."""
    global _resolver
    if _resolver is None:
        _resolver = create_repeated_in_out_resolver()
    return _resolver


# =============================================================================
# Endpoint 1: Attendance Event Ingestion
# =============================================================================

@router.post(
    "/attendance/events",
    response_model=CrossingEventResponse,
    dependencies=[Depends(verify_ai_worker_key)],
    summary="Ingest attendance crossing event from AI Worker",
)
async def ingest_attendance_event(event: CrossingEventRequest) -> CrossingEventResponse:
    """
    Ingest a crossing event from PipelineEngine (AI Worker).
    
    Flow:
    1. Validate CrossingEvent schema
    2. Create RawInOutEvent (Phase 23)
    3. Submit to Phase 24 Resolver
    4. Return source_resolution_id immediately
    5. Async: Resolver → AttendanceRecord (Phase 25)
    """
    try:
        # Convert to RawInOutEvent (Phase 23) - using correct field mapping
        # Use deterministic geometry config based on camera_id
        geometry_id = f"{event.camera_id}_line"
        geometry_version = 1
        geometry_config_hash = "default"
        
        # Extract time_base
        time_base = Fraction(event.time_base.num, event.time_base.den)
        
        raw_event = RawInOutEvent(
            event_id=event.event_id,
            camera_id=event.camera_id,
            geometry_id=geometry_id,
            geometry_version=geometry_version,
            geometry_config_hash=geometry_config_hash,
            local_track_id=str(event.track_id),
            global_observation_id=None,
            event_type=RawEventType.LINE_CROSSING,
            direction=RawEventDirection.IN if event.direction == "in" else RawEventDirection.OUT,
            crossing_point_x=event.crossing_point.x if event.crossing_point else (event.current_position.x if event.current_position else 0.0),
            crossing_point_y=event.crossing_point.y if event.crossing_point else (event.current_position.y if event.current_position else 0.0),
            crossing_timestamp=event.timestamp,
            crossing_frame_index=event.frame_index,
            previous_position_x=event.previous_position.x if event.previous_position else None,
            previous_position_y=event.previous_position.y if event.previous_position else None,
            current_position_x=event.current_position.x if event.current_position else None,
            current_position_y=event.current_position.y if event.current_position else None,
            previous_frame_index=event.frame_index - 1,
            current_frame_index=event.frame_index,
            previous_timestamp=event.timestamp - 0.033,  # Approx 30fps
            current_timestamp=event.timestamp,
            crossing_distance=0.0,
            side_transition="SIDE_A->SIDE_B",
            identity_certainty=RawIdentityCertainty.KNOWN if event.person_id else RawIdentityCertainty.UNKNOWN,
            identity_candidate=event.person_id,
            identity_confidence=event.identity_confidence or 0.0,
            identity_evidence_ref=None,
            # NEW: Metadata fields propagated from CrossingEventRequest
            stream_epoch=event.stream_epoch,
            pts=event.pts,
            time_base=time_base,
            capture_timestamp=event.capture_timestamp,
            processing_timestamp=event.processing_timestamp,
            model_version=event.model_version,
            enrollment_version=event.enrollment_version,
            source_crossing_event_id=event.event_id,
            trajectory_points=[],
            config_snapshot={},
            event_schema_version="1.1",
            created_at=datetime.utcnow().isoformat() + "Z",
        )
        
        # Submit to resolver (Phase 24)
        resolver = get_resolver()
        resolution_result = resolver.resolve_single(raw_event)
        
        # Get the source_resolution_id from the transition
        source_resolution_id = resolution_result.resolution_id
        
        logger.info(f"Event {event.event_id} ingested, resolution: {source_resolution_id}")
        
        return CrossingEventResponse(
            success=True,
            event_id=event.event_id,
            source_resolution_id=source_resolution_id,
            status="accepted",
            message="Event queued for resolution"
        )
        
    except ValueError as e:
        logger.warning(f"Invalid event {event.event_id}: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to ingest event {event.event_id}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Event ingestion failed: {e}")


# =============================================================================
# Endpoint 2: AI Worker Health
# =============================================================================

@router.post(
    "/health/ai-worker",
    response_model=AIWorkerHealthResponse,
    dependencies=[Depends(verify_ai_worker_key)],
    summary="AI Worker health heartbeat",
)
async def ai_worker_health(health: AIWorkerHealthRequest) -> AIWorkerHealthResponse:
    """
    Receive health heartbeat from AI Worker.
    
    Validates sequence, tracks generation, updates observable health state.
    Returns any pending control commands.
    """
    logger.debug(f"Health from {health.worker_id}: {health.state} (seq={health.sequence_number})")
    
    # Check for stale workers
    _check_stale_workers(30.0)
    
    # Get existing state
    existing_state = _worker_health_states.get(health.worker_id)
    
    # Validate sequence and generation
    is_valid, error_msg, generation_id = _validate_health_request(health, existing_state)
    if not is_valid:
        logger.warning(f"Health validation failed for {health.worker_id}: {error_msg}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    
    # Update health state
    worker_state = _update_worker_health(health, generation_id)
    
    # Get pending control commands for this worker
    pending_commands = []
    _cleanup_expired_requests()
    for pending in _pending_control_requests.values():
        if pending.request.target_id == health.worker_id:
            if pending.status == ControlRequestStatus.PENDING:
                pending_commands.append(pending.request.action)
                # Mark as acknowledged
                pending.status = ControlRequestStatus.ACCEPTED
                pending.acknowledged_at = time.time()
    
    return AIWorkerHealthResponse(
        success=True,
        worker_id=health.worker_id,
        acknowledged=True,
        server_timestamp=time.time(),
        sequence_number=health.sequence_number,
        commands=pending_commands,
        stale_threshold_seconds=30.0
    )


# =============================================================================
# Endpoint: GET /health/ai-worker/{worker_id} - Health Status Retrieval
# =============================================================================

@router.get(
    "/health/ai-worker/{worker_id}",
    response_model=AIWorkerHealthResponse,
    dependencies=[Depends(verify_ai_worker_key)],
    summary="Get AI Worker health status",
)
async def get_worker_health(worker_id: str) -> AIWorkerHealthResponse:
    """
    Retrieve current health status for a worker.
    """
    _check_stale_workers(30.0)
    
    state = _worker_health_states.get(worker_id)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker {worker_id} not found"
        )
    
    return AIWorkerHealthResponse(
        success=True,
        worker_id=state.worker_id,
        acknowledged=True,
        server_timestamp=time.time(),
        sequence_number=state.last_sequence,
        commands=[],  # Status retrieval doesn't return commands
        stale_threshold_seconds=30.0
    )


# =============================================================================
# Endpoint 3: AI Worker Control - Submit Request (Legacy Backend → PipelineEngine)
# =============================================================================

@router.post(
    "/ai/control/{action}",
    response_model=Dict[str, Any],
    dependencies=[Depends(verify_admin_key)],
    summary="Submit control request to PipelineEngine",
)
async def submit_control_request(
    action: str,
    request: ControlRequest,
    http_request: Request,
    _: bool = Depends(verify_admin_key),
) -> Dict[str, Any]:
    """
    Submit a control request to PipelineEngine.
    
    Actions:
    - START_WORKER: Start AI worker
    - STOP_WORKER: Graceful stop
    - RESTART_WORKER: Restart worker
    - ENABLE_CAMERA: Enable camera stream
    - DISABLE_CAMERA: Disable camera stream
    - GET_STATUS: Get worker status
    """
    client_id = _get_client_identifier(http_request)
    
    valid_actions = {
        "START_WORKER", "STOP_WORKER", "RESTART_WORKER",
        "ENABLE_CAMERA", "DISABLE_CAMERA", "GET_STATUS"
    }
    
    if action not in valid_actions:
        _audit_log("worker_control", "failure", client_id, "control_request",
                   {"action": action, "reason": "invalid_action"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{action}'. Valid: START_WORKER, STOP_WORKER, RESTART_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS"
        )
    
    # Validate target
    if request.target not in ("worker", "camera"):
        _audit_log("worker_control", "failure", client_id, "control_request",
                   {"action": action, "reason": "invalid_target", "target": request.target})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target '{request.target}'. Valid: worker, camera"
        )
    
    # Validate camera_id for camera actions
    if request.target == "camera" and not request.target_id:
        _audit_log("worker_control", "failure", client_id, "control_request",
                   {"action": action, "reason": "missing_camera_id"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_id (camera_id) required for camera actions"
        )
    
    # Check idempotency
    if request.idempotency_key in _processed_idempotency_keys:
        logger.info(f"Duplicate control request ignored: {request.idempotency_key}")
        stored = _processed_idempotency_keys[request.idempotency_key]
        return {
            "success": True,
            "request_id": request.request_id,
            "status": "DUPLICATE",
            "message": "Duplicate request, returning stored response",
            "original_response": stored.dict()
        }
    
    # Cleanup expired requests
    _cleanup_expired_requests()
    
    # Create pending request
    pending = PendingControlRequest(
        request=request,
        status=ControlRequestStatus.PENDING,
        created_at=time.time()
    )
    
    _pending_control_requests[request.request_id] = pending
    _processed_idempotency_keys[request.idempotency_key] = ControlResponse(
        success=True,
        action=request.action,
        worker_id=request.target_id,
        status=ControlRequestStatus.PENDING,
        request_id=request.request_id,
        timestamp=time.time(),
        details={"message": "Request queued"}
    )
    
    _audit_log("worker_control", "success", client_id, "control_request",
               {"action": action, "target": request.target, "target_id": request.target_id, "request_id": request.request_id})
    
    logger.info(f"Control request queued: {request.action} for {request.target}/{request.target_id}")
    
    return {
        "success": True,
        "request_id": request.request_id,
        "status": "PENDING",
        "message": "Control request queued for PipelineEngine"
    }


# =============================================================================
# Endpoint: GET /ai/control/pending - PipelineEngine polls for pending requests
# =============================================================================

@router.get(
    "/ai/control/pending",
    response_model=PendingControlRequests,
    dependencies=[Depends(verify_ai_control_key)],
    summary="Get pending control requests for PipelineEngine",
)
async def get_pending_control_requests(
    worker_id: str = Query(..., description="Worker identifier"),
    limit: int = Query(50, ge=1, le=100, description="Maximum requests to return"),
    since: Optional[float] = Query(None, description="Only requests after this timestamp"),
    _: bool = Depends(verify_ai_control_key),
) -> PendingControlRequests:
    """
    Get pending control requests for a worker.
    
    PipelineEngine polls this endpoint to get pending control requests.
    """
    _cleanup_expired_requests()
    
    requests = []
    for pending in _pending_control_requests.values():
        if pending.request.target_id != worker_id:
            continue
        if pending.status in (ControlRequestStatus.EXPIRED, ControlRequestStatus.COMPLETED, ControlRequestStatus.FAILED, ControlRequestStatus.REJECTED):
            continue
        if pending.request.created_at < (time.time() - 300):  # 5 min default TTL
            continue
        
        requests.append(pending.request)
        if len(requests) >= limit:
            break
    
    return PendingControlRequests(
        worker_id=worker_id,
        requests=requests
    )


# =============================================================================
# Endpoint: POST /ai/control/{action}/response - PipelineEngine submits response
# =============================================================================

@router.post(
    "/ai/control/{action}/response",
    response_model=Dict[str, Any],
    dependencies=[Depends(verify_ai_control_key)],
    summary="PipelineEngine submits control response"
)
async def submit_control_response(
    action: str,
    response: ControlResponse,
    http_request: Request,
    _: bool = Depends(verify_ai_control_key),
) -> Dict[str, Any]:
    """
    PipelineEngine submits response to a control request.
    
    This endpoint is called by PipelineEngine after executing a control action.
    """
    client_id = _get_client_identifier(http_request)
    
    valid_actions = {"START_WORKER", "STOP_WORKER", "RESTART_WORKER", "ENABLE_CAMERA", "DISABLE_CAMERA", "GET_STATUS"}
    
    if action not in valid_actions:
        _audit_log("worker_control_response", "failure", client_id, "control_response",
                   {"action": action, "reason": "invalid_action"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{action}'. Valid: START_WORKER, STOP_WORKER, RESTART_WORKER, ENABLE_CAMERA, DISABLE_CAMERA, GET_STATUS"
        )
    
    # Validate path action matches body action
    if action != response.action:
        _audit_log("worker_control_response", "failure", client_id, "control_response",
                   {"action": action, "reason": "action_mismatch", "path_action": action, "body_action": response.action})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path action '{action}' does not match body action '{response.action}'"
        )
    
    if not response.request_id:
        _audit_log("worker_control_response", "failure", client_id, "control_response",
                   {"action": action, "reason": "missing_request_id"})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="request_id is required"
        )
    
    # Find pending request
    pending = _pending_control_requests.get(response.request_id)
    if not pending:
        _audit_log("worker_control_response", "failure", client_id, "control_response",
                   {"action": action, "reason": "request_not_found", "request_id": response.request_id})
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request {response.request_id} not found"
        )
    
    # Validate worker_id matches
    if pending.request.target_id != response.worker_id:
        _audit_log("worker_control_response", "failure", client_id, "control_response",
                   {"action": action, "reason": "worker_id_mismatch", 
                    "expected": pending.request.target_id, "got": response.worker_id})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Worker ID mismatch: request targets {pending.request.target_id}, response from {response.worker_id}"
        )
    
    # Update pending request
    pending.status = response.status
    if response.status in (ControlRequestStatus.COMPLETED, ControlRequestStatus.FAILED, ControlRequestStatus.REJECTED):
        pending.completed_at = time.time()
    pending.response = response
    
    _audit_log("worker_control_response", "success", client_id, "control_response",
               {"action": action, "request_id": response.request_id, "status": response.status})
    
    logger.info(f"Control response received: {response.action} for {response.request_id} - {response.status}")
    
    return {
        "success": True,
        "message": "Response recorded"
    }


# =============================================================================
# Endpoint: GET /ai/control/history - Completed command history
# =============================================================================

@router.get(
    "/ai/control/history",
    dependencies=[Depends(verify_admin_key)],
    summary="Get control command history"
)
async def get_control_history(
    worker_id: Optional[str] = Query(None, description="Filter by worker ID"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    since: Optional[float] = Query(None, description="Only records after this timestamp"),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    _: bool = Depends(verify_admin_key),
) -> Dict[str, Any]:
    """
    Get control command history including completed/failed/expired requests.
    Admin only.
    """
    _cleanup_expired_requests()
    
    results = []
    for pending in _pending_control_requests.values():
        if worker_id and pending.request.target_id != worker_id:
            continue
        if status_filter and pending.status != status_filter:
            continue
        if since and pending.created_at < since:
            continue
        
        results.append({
            "request_id": pending.request.request_id,
            "action": pending.request.action,
            "target": pending.request.target,
            "target_id": pending.request.target_id,
            "status": pending.status,
            "created_at": pending.created_at,
            "acknowledged_at": pending.acknowledged_at,
            "completed_at": pending.completed_at,
            "response": pending.response.dict() if pending.response else None,
        })
        if len(results) >= limit:
            break
    
    # Sort by created_at descending
    results.sort(key=lambda x: x["created_at"], reverse=True)
    
    return {
        "total": len(results),
        "records": results
    }


# =============================================================================
# Endpoint: GET /ai/control/status - Control system status
# =============================================================================

@router.get(
    "/ai/control/status",
    dependencies=[Depends(verify_ai_control_key)],
    summary="Get control system status"
)
async def get_control_status(
    _: bool = Depends(verify_ai_control_key),
) -> Dict[str, Any]:
    """Get control system status."""
    _cleanup_expired_requests()
    
    total_pending = len([r for r in _pending_control_requests.values() if r.status == "PENDING"])
    total_processed = len(_processed_idempotency_keys)
    
    return {
        "pending_requests": total_pending,
        "processed_requests": total_processed,
        "idempotency_keys": len(_processed_idempotency_keys)
    }


# =============================================================================
# Module exports
# =============================================================================

__all__ = ["router"]