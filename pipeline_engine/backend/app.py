"""
Backend API - FastAPI application for pipeline control and monitoring.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipeline_engine.core.engine import PipelineEngine, EngineState, get_engine
from pipeline_engine.config import load_pipeline_config, get_config

logger = logging.getLogger(__name__)


# Request/Response models
class PipelineControlRequest(BaseModel):
    action: str  # start, stop, restart
    camera_id: Optional[str] = None


class CameraConfigUpdate(BaseModel):
    camera_id: str
    config: Dict[str, Any]


class LineGeometryUpdate(BaseModel):
    camera_id: str
    line_start: List[float]
    line_end: List[float]
    direction_semantics: str = "side_a_to_b_in"


class PipelineStatusResponse(BaseModel):
    state: str
    uptime_seconds: float
    cameras_total: int
    cameras_running: int
    cameras_healthy: int
    total_frames_processed: int
    total_attendance_events: int
    gpu_memory_mb: float
    gpu_utilization_pct: float
    errors: int
    last_error: str


class CameraStatusResponse(BaseModel):
    camera_id: str
    state: str
    rtsp_state: str
    frames_received: int
    frames_decoded: int
    frames_dropped: int
    inference_count: int
    tracks_active: int
    attendance_events: int
    encode_fps: float
    publish_fps: float
    end_to_end_latency_ms: float
    gpu_memory_mb: float
    last_error: str
    uptime_seconds: float


class AttendanceEventResponse(BaseModel):
    event_id: str
    camera_id: str
    track_id: int
    direction: str
    crossing_point: List[float]
    timestamp: float
    frame_index: int
    person_id: Optional[str]
    person_name: Optional[str]
    identity_confidence: float


class HealthResponse(BaseModel):
    status: str
    checks: Dict[str, bool]


# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()
engine: Optional[PipelineEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global engine
    
    logger.info("Starting Pipeline Engine API...")
    
    # Load config and initialize engine
    config = load_pipeline_config()
    engine = PipelineEngine()
    engine.load_config()
    engine.initialize()
    
    # Register health callback for WebSocket broadcasts
    def health_callback(health: Dict[str, Any]):
        import asyncio
        asyncio.create_task(manager.broadcast({"type": "health", "data": health}))
    
    engine.register_health_callback(health_callback)
    
    yield
    
    logger.info("Shutting down Pipeline Engine API...")
    if engine:
        engine.stop()


app = FastAPI(
    title="AI Attendance Pipeline API",
    description="Control and monitoring API for GPU-first video pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health endpoints
@app.get("/api/v1/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/api/v1/health/ready", response_model=HealthResponse)
async def readiness():
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    checks = {
        "engine_initialized": engine is not None,
        "config_loaded": engine.config is not None,
        "cuda_available": False,
    }
    
    try:
        import torch
        checks["cuda_available"] = torch.cuda.is_available()
    except Exception:
        pass
    
    all_ready = all(checks.values())
    return HealthResponse(
        status="ready" if all_ready else "not_ready",
        checks=checks,
    )


@app.get("/api/v1/health/system", response_model=PipelineStatusResponse)
async def system_health():
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    metrics = engine.metrics
    return PipelineStatusResponse(
        state=metrics.state.value,
        uptime_seconds=metrics.uptime_seconds,
        cameras_total=metrics.cameras_total,
        cameras_running=metrics.cameras_running,
        cameras_healthy=metrics.cameras_healthy,
        total_frames_processed=metrics.total_frames_processed,
        total_attendance_events=metrics.total_attendance_events,
        gpu_memory_mb=metrics.gpu_memory_mb,
        gpu_utilization_pct=metrics.gpu_utilization_pct,
        errors=metrics.errors,
        last_error=metrics.last_error,
    )


# Pipeline control
@app.post("/api/v1/pipeline/control")
async def pipeline_control(request: PipelineControlRequest):
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    action = request.action.lower()
    camera_id = request.camera_id
    
    if action == "start":
        if camera_id:
            success = engine.camera_manager.start_camera(camera_id)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to start camera {camera_id}")
            return {"status": "started", "camera_id": camera_id}
        else:
            success = engine.start()
            if not success:
                raise HTTPException(status_code=400, detail="Failed to start pipeline")
            return {"status": "started"}
    
    elif action == "stop":
        if camera_id:
            success = engine.camera_manager.stop_camera(camera_id)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to stop camera {camera_id}")
            return {"status": "stopped", "camera_id": camera_id}
        else:
            engine.stop()
            return {"status": "stopped"}
    
    elif action == "restart":
        if camera_id:
            success = engine.camera_manager.restart_camera(camera_id)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to restart camera {camera_id}")
            return {"status": "restarted", "camera_id": camera_id}
        else:
            success = engine.restart()
            if not success:
                raise HTTPException(status_code=400, detail="Failed to restart pipeline")
            return {"status": "restarted"}
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


@app.get("/api/v1/pipeline/status", response_model=PipelineStatusResponse)
async def pipeline_status():
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    metrics = engine.metrics
    return PipelineStatusResponse(
        state=metrics.state.value,
        uptime_seconds=metrics.uptime_seconds,
        cameras_total=metrics.cameras_total,
        cameras_running=metrics.cameras_running,
        cameras_healthy=metrics.cameras_healthy,
        total_frames_processed=metrics.total_frames_processed,
        total_attendance_events=metrics.total_attendance_events,
        gpu_memory_mb=metrics.gpu_memory_mb,
        gpu_utilization_pct=metrics.gpu_utilization_pct,
        errors=metrics.errors,
        last_error=metrics.last_error,
    )


@app.get("/api/v1/pipeline/config")
async def pipeline_config():
    global engine
    if not engine or not engine.config:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # Return sanitized config (no sensitive data)
    config = engine.config.model_dump()
    return config


# Camera endpoints
@app.get("/api/v1/cameras")
async def list_cameras():
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    cameras = engine.camera_manager.get_camera_list()
    return {"cameras": cameras}


@app.get("/api/v1/cameras/{camera_id}", response_model=CameraStatusResponse)
async def get_camera(camera_id: str):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    metrics = engine.camera_manager.get_camera_metrics(camera_id)
    if not metrics:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    
    state = engine.camera_manager.get_camera_state(camera_id)
    
    return CameraStatusResponse(
        camera_id=camera_id,
        state=state.value if state else "unknown",
        rtsp_state=metrics.rtsp_state.value,
        frames_received=metrics.frames_received,
        frames_decoded=metrics.frames_decoded,
        frames_dropped=metrics.frames_dropped,
        inference_count=metrics.inference_count,
        tracks_active=metrics.tracks_active,
        attendance_events=metrics.attendance_events,
        encode_fps=metrics.encode_fps,
        publish_fps=metrics.publish_fps,
        end_to_end_latency_ms=metrics.end_to_end_latency_ms,
        gpu_memory_mb=metrics.gpu_memory_mb,
        last_error=metrics.last_error,
        uptime_seconds=metrics.uptime_seconds,
    )


@app.get("/api/v1/cameras/{camera_id}/health")
async def camera_health(camera_id: str):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    healthy = engine.camera_manager.is_camera_healthy(camera_id)
    state = engine.camera_manager.get_camera_state(camera_id)
    
    return {
        "camera_id": camera_id,
        "healthy": healthy,
        "state": state.value if state else "unknown",
    }


@app.post("/api/v1/cameras/{camera_id}/start")
async def start_camera(camera_id: str):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    success = engine.camera_manager.start_camera(camera_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to start camera {camera_id}")
    
    return {"status": "started", "camera_id": camera_id}


@app.post("/api/v1/cameras/{camera_id}/stop")
async def stop_camera(camera_id: str):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    success = engine.camera_manager.stop_camera(camera_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to stop camera {camera_id}")
    
    return {"status": "stopped", "camera_id": camera_id}


@app.post("/api/v1/cameras/{camera_id}/restart")
async def restart_camera(camera_id: str):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    success = engine.camera_manager.restart_camera(camera_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to restart camera {camera_id}")
    
    return {"status": "restarted", "camera_id": camera_id}


@app.put("/api/v1/cameras/{camera_id}/config")
async def update_camera_config(camera_id: str, request: CameraConfigUpdate):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    success = engine.camera_manager.update_camera_config(camera_id, request.config)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to update camera {camera_id} config")
    
    return {"status": "updated", "camera_id": camera_id}


# Attendance endpoints
@app.get("/api/v1/attendance/events", response_model=List[AttendanceEventResponse])
async def get_attendance_events(
    camera_id: Optional[str] = None,
    person_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = 100,
):
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # This would need access to attendance engine
    # For now return empty list
    return []


@app.get("/api/v1/attendance/daily/{date}")
async def get_daily_attendance(date: str):
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # This would query attendance store
    return {"date": date, "records": []}


@app.get("/api/v1/attendance/export")
async def export_attendance(
    camera_id: Optional[str] = None,
    person_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
):
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    # Export to JSON
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        # Would call attendance_engine.export_events(f.name, ...)
        pass
    
    return {"message": "Export not fully implemented"}


# Line geometry endpoints
@app.get("/api/v1/geometry/lines")
async def list_lines():
    global engine
    if not engine or not engine.config:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    lines = {}
    for cam_id, cam_config in engine.config.cameras.items():
        geom = cam_config.get("geometry", {})
        lines[cam_id] = {
            "line_start": geom.get("line_start", [0, 1080]),
            "line_end": geom.get("line_end", [3840, 1080]),
            "direction_semantics": geom.get("direction_semantics", "side_a_to_b_in"),
        }
    
    return {"lines": lines}


@app.get("/api/v1/geometry/lines/{camera_id}")
async def get_line(camera_id: str):
    global engine
    if not engine or not engine.config:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    cam_config = engine.config.cameras.get(camera_id)
    if not cam_config:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    
    geom = cam_config.get("geometry", {})
    return {
        "camera_id": camera_id,
        "line_start": geom.get("line_start", [0, 1080]),
        "line_end": geom.get("line_end", [3840, 1080]),
        "direction_semantics": geom.get("direction_semantics", "side_a_to_b_in"),
    }


@app.put("/api/v1/geometry/lines/{camera_id}")
async def update_line(camera_id: str, request: LineGeometryUpdate):
    global engine
    if not engine or not engine.camera_manager:
        raise HTTPException(status_code=503, detail="Camera manager not initialized")
    
    success = engine.camera_manager.update_camera_config(camera_id, {
        "geometry": {
            "line_start": request.line_start,
            "line_end": request.line_end,
            "direction_semantics": request.direction_semantics,
        }
    })
    
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to update line for camera {camera_id}")
    
    return {"status": "updated", "camera_id": camera_id}


# Model endpoints
@app.get("/api/v1/models")
async def list_models():
    global engine
    if not engine or not engine.config:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    models = {}
    for name, config in engine.config.models.items():
        models[name] = {
            "path": config.get("path", ""),
            "enabled": config.get("enabled", True),
        }
    
    return {"models": models}


@app.get("/api/v1/models/status")
async def models_status():
    # Would check actual model loading status
    return {"models": {}}


# Video endpoints
@app.get("/api/v1/video/streams")
async def list_streams():
    global engine
    if not engine or not engine.config:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    streams = {}
    for cam_id, cam_config in engine.config.cameras.items():
        if cam_config.get("enabled", True):
            output = cam_config.get("output", {})
            streams[cam_id] = {
                "input_url": cam_config.get("input", {}).get("url", ""),
                "output_url": f"rtsp://localhost:8554/{output.get('path', f'live/{cam_id}-ai')}",
                "codec": "h264",
                "width": cam_config.get("encode", {}).get("width", 3840),
                "height": cam_config.get("encode", {}).get("height", 2160),
                "fps": cam_config.get("encode", {}).get("fps", 30),
            }
    
    return {"streams": streams}


# WebSocket endpoint
@app.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle incoming messages if needed
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


# Metrics endpoint
@app.get("/api/v1/metrics")
async def metrics():
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    
    health = engine.get_health()
    return health


# Root
@app.get("/")
async def root():
    return {
        "service": "AI Attendance Pipeline API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/health/system",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "pipeline_engine.backend.app:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
    )