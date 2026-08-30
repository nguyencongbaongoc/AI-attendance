"""
Phase 37C — Health Monitoring API.

REST endpoints for system health, camera health, GPU status, and operational metrics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import load_settings
from app.runtime import collect_runtime_snapshot
from app.streaming.health import StreamHealthMonitor, create_health_monitor, StreamHealthState
from app.attendance.policy_engine.parent_registry import create_parent_registry
from app.attendance.policy_engine.telegram_bot import (
    create_notification_queue,
    create_telegram_bot,
    NotificationQueue,
)
from app.attendance.policy_engine.exit_session import create_exit_session_store_from_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/health", tags=["health"])

# Global health monitor instance (in production, this would be shared with the streaming pipeline)
_health_monitor: Optional[StreamHealthMonitor] = None


def get_health_monitor() -> StreamHealthMonitor:
    """Get or create the global health monitor."""
    global _health_monitor
    if _health_monitor is None:
        settings = load_settings()
        _health_monitor = create_health_monitor(
            stale_threshold_seconds=settings.cameras.health_stale_threshold_seconds,
            degraded_threshold_seconds=settings.cameras.health_degraded_threshold_seconds,
            frame_timeout_seconds=10.0,
        )
        _health_monitor.register_camera("CAM1")
        _health_monitor.register_camera("CAM2")
    return _health_monitor


# Pydantic models for API responses

class CameraHealthResponse(BaseModel):
    """Camera health status response."""
    camera_id: str
    state: str
    timestamp: str
    message: str
    frames_received: int
    frames_dropped: int
    total_errors: int
    uptime_seconds: float
    current_resolution: Optional[List[int]] = None
    current_fps: Optional[float] = None
    current_codec: Optional[str] = None
    last_frame_time: Optional[float] = None
    reconnect_count: int = 0
    consecutive_failures: int = 0


class GPUStatusResponse(BaseModel):
    """GPU/CUDA/NVDEC status response."""
    gpu_name: str
    driver_version: str
    cuda_runtime_version: str
    cuda_toolkit_version: str
    cudnn_version: str
    pytorch_version: str
    pytorch_cuda_version: str
    torch_cuda_available: bool
    onnxruntime_version: str
    cuda_ep_registered: bool
    nvdec_available: bool
    model_availability: Dict[str, str]


class SystemComponentHealth(BaseModel):
    """Health status for a system component."""
    component: str
    status: str  # healthy, degraded, unhealthy
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class SystemHealthResponse(BaseModel):
    """Overall system health response."""
    timestamp: str
    overall_status: str  # healthy, degraded, unhealthy
    components: List[SystemComponentHealth]
    cameras: Dict[str, CameraHealthResponse]
    gpu: GPUStatusResponse
    runtime: Dict[str, Any]


class MetricsResponse(BaseModel):
    """System metrics response."""
    timestamp: str
    camera_metrics: Dict[str, Dict[str, Any]]
    queue_metrics: Dict[str, Any]
    attendance_metrics: Dict[str, Any]
    policy_metrics: Dict[str, Any]
    telegram_metrics: Dict[str, Any]
    database_metrics: Dict[str, Any]


@router.get("/system", response_model=SystemHealthResponse)
async def get_system_health():
    """Get comprehensive system health status."""
    settings = load_settings()
    monitor = get_health_monitor()
    
    # Check camera health
    camera_results = monitor.check_all_health()
    cameras = {}
    for cam_id, result in camera_results.items():
        cameras[cam_id] = CameraHealthResponse(
            camera_id=result.camera_id,
            state=result.state.value,
            timestamp=result.timestamp,
            message=result.message,
            frames_received=result.details.get("frames_received", 0),
            frames_dropped=result.details.get("frames_dropped", 0),
            total_errors=result.details.get("total_errors", 0),
            uptime_seconds=result.details.get("uptime_seconds", 0.0),
            current_resolution=result.details.get("current_resolution"),
            current_fps=result.details.get("current_fps"),
            current_codec=result.details.get("current_codec"),
            last_frame_time=result.last_successful_time,
            reconnect_count=result.reconnect_count,
            consecutive_failures=result.consecutive_failures,
        )
    
    # Get GPU/runtime status
    runtime_snapshot = collect_runtime_snapshot()
    gpu = GPUStatusResponse(
        gpu_name=runtime_snapshot.nvidia_gpu_name or "Unknown",
        driver_version=runtime_snapshot.nvidia_driver_version or "Unknown",
        cuda_runtime_version=runtime_snapshot.cuda_runtime_version or "Unknown",
        cuda_toolkit_version=runtime_snapshot.cuda_toolkit_version or "Unknown",
        cudnn_version=runtime_snapshot.cudnn_version or "Unknown",
        pytorch_version=runtime_snapshot.pytorch_version or "Unknown",
        pytorch_cuda_version=runtime_snapshot.pytorch_cuda_version or "Unknown",
        torch_cuda_available=runtime_snapshot.torch_cuda_available,
        onnxruntime_version=runtime_snapshot.onnxruntime_version or "Unknown",
        cuda_ep_registered=runtime_snapshot.cuda_ep_registered,
        nvdec_available=runtime_snapshot.ffmpeg_available,
        model_availability=runtime_snapshot.model_availability,
    )
    
    # Check component health
    components = []
    
    # Database checks
    db_checks = {
        "parent_registry": {"path": settings.parent_registry.db_path},
        "notification_queue": {"path": settings.notification_queue.db_path},
        "exit_sessions": {"path": settings.exit_session.db_path},
    }
    
    for db_name, db_info in db_checks.items():
        import os
        exists = os.path.exists(db_info["path"])
        components.append(SystemComponentHealth(
            component=f"database.{db_name}",
            status="healthy" if exists else "unhealthy",
            message="Database file exists" if exists else "Database file missing",
            details={"path": db_info["path"], "exists": exists},
        ))
    
    # Telegram configuration
    tg_configured = bool(settings.telegram.bot_token)
    components.append(SystemComponentHealth(
        component="telegram",
        status="healthy" if tg_configured else "degraded",
        message="Telegram bot configured" if tg_configured else "Telegram bot not configured",
        details={
            "configured": tg_configured,
            "live_test_enabled": settings.telegram.live_test_enabled,
        },
    ))
    
    # Directory checks
    dir_checks = {
        "data": settings.paths.data_dir,
        "logs": settings.paths.logs_dir,
        "models": settings.paths.models_dir,
    }
    for dir_name, dir_path in dir_checks.items():
        import os
        exists = os.path.exists(dir_path)
        components.append(SystemComponentHealth(
            component=f"directory.{dir_name}",
            status="healthy" if exists else "unhealthy",
            message="Directory exists" if exists else "Directory missing",
            details={"path": str(dir_path), "exists": exists},
        ))
    
    # GPU health
    gpu_healthy = runtime_snapshot.torch_cuda_available and runtime_snapshot.cuda_ep_registered
    components.append(SystemComponentHealth(
        component="gpu",
        status="healthy" if gpu_healthy else "degraded",
        message="GPU/CUDA available" if gpu_healthy else "GPU/CUDA not fully available",
        details={
            "torch_cuda": runtime_snapshot.torch_cuda_available,
            "cuda_ep": runtime_snapshot.cuda_ep_registered,
            "nvdec": runtime_snapshot.ffmpeg_available,
        },
    ))
    
    # Camera health summary
    healthy_cams = sum(1 for c in cameras.values() if c.state == "live")
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
    
    components.append(SystemComponentHealth(
        component="cameras",
        status=cam_status,
        message=cam_message,
        details={"healthy": healthy_cams, "total": total_cams},
    ))
    
    # Overall status
    statuses = [c.status for c in components]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"
    
    return SystemHealthResponse(
        timestamp=datetime.utcnow().isoformat() + "Z",
        overall_status=overall,
        components=components,
        cameras=cameras,
        gpu=gpu,
        runtime={
            "python_version": runtime_snapshot.python_version,
            "platform": runtime_snapshot.windows_version,
            "architecture": runtime_snapshot.architecture,
            "venv_active": runtime_snapshot.venv_active,
        },
    )


@router.get("/cameras", response_model=Dict[str, CameraHealthResponse])
async def get_camera_health():
    """Get health status for all cameras."""
    monitor = get_health_monitor()
    camera_results = monitor.check_all_health()
    
    cameras = {}
    for cam_id, result in camera_results.items():
        cameras[cam_id] = CameraHealthResponse(
            camera_id=result.camera_id,
            state=result.state.value,
            timestamp=result.timestamp,
            message=result.message,
            frames_received=result.details.get("frames_received", 0),
            frames_dropped=result.details.get("frames_dropped", 0),
            total_errors=result.details.get("total_errors", 0),
            uptime_seconds=result.details.get("uptime_seconds", 0.0),
            current_resolution=result.details.get("current_resolution"),
            current_fps=result.details.get("current_fps"),
            current_codec=result.details.get("current_codec"),
            last_frame_time=result.last_successful_time,
            reconnect_count=result.reconnect_count,
            consecutive_failures=result.consecutive_failures,
        )
    
    return cameras


@router.get("/cameras/{camera_id}", response_model=CameraHealthResponse)
async def get_camera_health_by_id(camera_id: str):
    """Get health status for a specific camera."""
    monitor = get_health_monitor()
    result = monitor.check_health(camera_id)
    
    if not result:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    
    return CameraHealthResponse(
        camera_id=result.camera_id,
        state=result.state.value,
        timestamp=result.timestamp,
        message=result.message,
        frames_received=result.details.get("frames_received", 0),
        frames_dropped=result.details.get("frames_dropped", 0),
        total_errors=result.details.get("total_errors", 0),
        uptime_seconds=result.details.get("uptime_seconds", 0.0),
        current_resolution=result.details.get("current_resolution"),
        current_fps=result.details.get("current_fps"),
        current_codec=result.details.get("current_codec"),
        last_frame_time=result.last_successful_time,
        reconnect_count=result.reconnect_count,
        consecutive_failures=result.consecutive_failures,
    )


@router.get("/gpu", response_model=GPUStatusResponse)
async def get_gpu_status():
    """Get GPU/CUDA/NVDEC status."""
    runtime_snapshot = collect_runtime_snapshot()
    
    return GPUStatusResponse(
        gpu_name=runtime_snapshot.nvidia_gpu_name or "Unknown",
        driver_version=runtime_snapshot.nvidia_driver_version or "Unknown",
        cuda_runtime_version=runtime_snapshot.cuda_runtime_version or "Unknown",
        cuda_toolkit_version=runtime_snapshot.cuda_toolkit_version or "Unknown",
        cudnn_version=runtime_snapshot.cudnn_version or "Unknown",
        pytorch_version=runtime_snapshot.pytorch_version or "Unknown",
        pytorch_cuda_version=runtime_snapshot.pytorch_cuda_version or "Unknown",
        torch_cuda_available=runtime_snapshot.torch_cuda_available,
        onnxruntime_version=runtime_snapshot.onnxruntime_version or "Unknown",
        cuda_ep_registered=runtime_snapshot.cuda_ep_registered,
        nvdec_available=runtime_snapshot.ffmpeg_available,
        model_availability=runtime_snapshot.model_availability,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """Get system metrics."""
    settings = load_settings()
    monitor = get_health_monitor()
    
    # Camera metrics
    camera_results = monitor.check_all_health()
    camera_metrics = {}
    for cam_id, result in camera_results.items():
        camera_metrics[cam_id] = {
            "state": result.state.value,
            "frames_received": result.details.get("frames_received", 0),
            "frames_dropped": result.details.get("frames_dropped", 0),
            "total_errors": result.details.get("total_errors", 0),
            "uptime_seconds": result.details.get("uptime_seconds", 0.0),
            "current_fps": result.details.get("current_fps"),
            "current_resolution": result.details.get("current_resolution"),
            "current_codec": result.details.get("current_codec"),
        }
    
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
    
    # Attendance metrics (placeholder - would connect to actual attendance engine)
    attendance_metrics = {
        "total_students": 0,
        "present_today": 0,
        "absent_today": 0,
        "late_today": 0,
        "left_early_today": 0,
    }
    
    # Policy metrics (placeholder)
    policy_metrics = {
        "morning_absence_events": 0,
        "long_exit_events": 0,
        "missing_checkout_events": 0,
        "short_exit_events": 0,
        "deduplicated_events": 0,
    }
    
    # Telegram metrics (placeholder)
    telegram_metrics = {
        "worker_running": False,
        "messages_sent": 0,
        "messages_failed": 0,
        "last_send_time": None,
    }
    
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
    
    return MetricsResponse(
        timestamp=datetime.utcnow().isoformat() + "Z",
        camera_metrics=camera_metrics,
        queue_metrics=queue_metrics,
        attendance_metrics=attendance_metrics,
        policy_metrics=policy_metrics,
        telegram_metrics=telegram_metrics,
        database_metrics=database_metrics,
    )


@router.post("/cameras/{camera_id}/frame")
async def report_frame_received(
    camera_id: str,
    frame_index: int,
    timestamp: float,
    frame_size: int = 0,
    resolution: Optional[List[int]] = None,
    fps: Optional[float] = None,
    codec: Optional[str] = None,
):
    """Report a frame received (called by streaming pipeline)."""
    monitor = get_health_monitor()
    monitor.update_frame_received(
        camera_id=camera_id,
        frame_index=frame_index,
        timestamp=timestamp,
        frame_size=frame_size,
        resolution=tuple(resolution) if resolution else None,
        fps=fps,
        codec=codec,
    )
    return {"status": "ok"}


@router.post("/cameras/{camera_id}/error")
async def report_camera_error(camera_id: str, error: str):
    """Report a camera error (called by streaming pipeline)."""
    monitor = get_health_monitor()
    monitor.update_error(camera_id, error)
    return {"status": "ok"}


@router.post("/cameras/{camera_id}/reconnect")
async def report_reconnect_attempt(camera_id: str, attempt: int):
    """Report a reconnect attempt (called by streaming pipeline)."""
    monitor = get_health_monitor()
    monitor.update_reconnect(camera_id, attempt)
    return {"status": "ok"}


@router.post("/cameras/{camera_id}/reconnect/success")
async def report_reconnect_success(camera_id: str):
    """Report successful reconnection (called by streaming pipeline)."""
    monitor = get_health_monitor()
    monitor.update_reconnect_success(camera_id)
    return {"status": "ok"}


@router.post("/cameras/{camera_id}/reconnect/failed")
async def report_reconnect_failed(camera_id: str, reason: str):
    """Report failed reconnection (called by streaming pipeline)."""
    monitor = get_health_monitor()
    monitor.update_reconnect_failed(camera_id, reason)
    return {"status": "ok"}


# Queue metrics and alerts endpoints

class QueueMetricsResponse(BaseModel):
    """Detailed queue metrics response."""
    queue_stats: Dict[str, int]
    enqueue_rate_1h: int
    dequeue_rate_1h: int
    avg_latency_seconds: float
    p95_latency_seconds: float
    oldest_pending_age_seconds: float
    retry_count: int
    failed_count: int
    rate_limited_count: int
    queue_depth: int
    max_queue_size: int
    queue_utilization_percent: float


class AlertResponse(BaseModel):
    """Alert response."""
    severity: str
    type: str
    message: str
    metric: str
    value: float
    threshold: float


@router.get("/queue/metrics", response_model=QueueMetricsResponse)
async def get_queue_metrics():
    """Get detailed queue metrics for monitoring."""
    settings = load_settings()
    try:
        parent_registry = create_parent_registry(settings.parent_registry.db_path)
        notification_queue = create_notification_queue(
            parent_registry=parent_registry,
            telegram_bot=create_telegram_bot(settings.telegram.bot_token),
            db_path=settings.notification_queue.db_path,
        )
        metrics = notification_queue.get_detailed_metrics()
        return QueueMetricsResponse(**metrics)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/alerts", response_model=List[AlertResponse])
async def get_queue_alerts():
    """Get current queue alerts."""
    settings = load_settings()
    try:
        parent_registry = create_parent_registry(settings.parent_registry.db_path)
        notification_queue = create_notification_queue(
            parent_registry=parent_registry,
            telegram_bot=create_telegram_bot(settings.telegram.bot_token),
            db_path=settings.notification_queue.db_path,
        )
        alerts = notification_queue.check_alerts()
        return alerts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue/stats", response_model=Dict[str, int])
async def get_queue_stats():
    """Get basic queue statistics."""
    settings = load_settings()
    try:
        parent_registry = create_parent_registry(settings.parent_registry.db_path)
        notification_queue = create_notification_queue(
            parent_registry=parent_registry,
            telegram_bot=create_telegram_bot(settings.telegram.bot_token),
            db_path=settings.notification_queue.db_path,
        )
        return notification_queue.get_queue_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
