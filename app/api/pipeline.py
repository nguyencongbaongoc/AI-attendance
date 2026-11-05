"""
Pipeline & Worker Control REST API.

Provides operational endpoints for:
- POST /api/v1/pipeline/reload-gallery: Reload ArcFace embeddings (.npy) in real time
- POST /api/v1/pipeline/camera/{cam_id}/start: Start camera ingestion/pipeline
- POST /api/v1/pipeline/camera/{cam_id}/stop: Stop camera ingestion/pipeline
- POST /api/v1/pipeline/camera/{cam_id}/restart: Restart camera ingestion/pipeline
- POST /api/v1/pipeline/restart: Restart complete pipeline engine
- GET /api/v1/pipeline/status: Query current pipeline status
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from pipeline_engine.ingestion.camera_manager import get_camera_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.post("/reload-gallery")
async def reload_gallery():
    """
    Trigger ArcFaceRecognizer reload of .npy / database embeddings in all active cameras.
    """
    cm = get_camera_manager()
    try:
        count = cm.reload_gallery()
        logger.info(f"ArcFace embeddings gallery reloaded: {count} identities active")
        return {
            "status": "success",
            "count": count,
            "message": f"Successfully reloaded gallery with {count} embeddings."
        }
    except Exception as e:
        logger.error(f"Failed to reload gallery: {e}")
        return {
            "status": "error",
            "count": 0,
            "message": f"Gallery reload failed: {str(e)}"
        }


@router.post("/camera/{cam_id}/start")
async def start_camera(cam_id: str = Path(...)):
    """Start ingestion and AI pipeline for a camera."""
    cm = get_camera_manager()
    norm_id = cam_id.lower().replace("-", "").strip()
    try:
        success = cm.start_camera(norm_id)
        if not success:
            # Fallback to direct name
            success = cm.start_camera(cam_id)
        return {
            "status": "success" if success else "failed",
            "camera_id": cam_id,
            "action": "start",
            "message": f"Camera {cam_id} started successfully" if success else f"Failed to start camera {cam_id}"
        }
    except Exception as e:
        logger.error(f"Error starting camera {cam_id}: {e}")
        return {"status": "error", "camera_id": cam_id, "message": str(e)}


@router.post("/camera/{cam_id}/stop")
async def stop_camera(cam_id: str = Path(...)):
    """Stop ingestion and AI pipeline for a camera."""
    cm = get_camera_manager()
    norm_id = cam_id.lower().replace("-", "").strip()
    try:
        success = cm.stop_camera(norm_id)
        if not success:
            success = cm.stop_camera(cam_id)
        return {
            "status": "success" if success else "failed",
            "camera_id": cam_id,
            "action": "stop",
            "message": f"Camera {cam_id} stopped"
        }
    except Exception as e:
        logger.error(f"Error stopping camera {cam_id}: {e}")
        return {"status": "error", "camera_id": cam_id, "message": str(e)}


@router.post("/camera/{cam_id}/restart")
async def restart_camera(cam_id: str = Path(...)):
    """Restart ingestion and AI pipeline for a camera."""
    cm = get_camera_manager()
    norm_id = cam_id.lower().replace("-", "").strip()
    try:
        success = cm.restart_camera(norm_id)
        if not success:
            success = cm.restart_camera(cam_id)
        return {
            "status": "success" if success else "failed",
            "camera_id": cam_id,
            "action": "restart",
            "message": f"Camera {cam_id} restarted"
        }
    except Exception as e:
        logger.error(f"Error restarting camera {cam_id}: {e}")
        return {"status": "error", "camera_id": cam_id, "message": str(e)}


@router.post("/restart")
async def restart_pipeline():
    """Restart complete pipeline engine across all cameras."""
    cm = get_camera_manager()
    try:
        cm.stop_all()
        import time
        time.sleep(1.0)
        success = cm.start_all()
        return {
            "status": "success" if success else "failed",
            "action": "restart_pipeline",
            "message": "Complete pipeline restarted successfully."
        }
    except Exception as e:
        logger.error(f"Error restarting pipeline: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/status")
async def get_pipeline_status():
    """Get active pipeline status and metrics."""
    cm = get_camera_manager()
    return cm.get_all_metrics()

