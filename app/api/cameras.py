"""
Cameras and Crossing Line Management REST API.

Provides endpoints for:
- POST /api/v1/cameras/{cam_id}/line (and alias /api/v1/line): Save crossing line and sync dynamically
- GET /api/v1/cameras/{cam_id}/line: Retrieve current crossing line
- GET /api/v1/recordings: List saved recordings and evidence snapshots/clips
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query, status

from pipeline_engine.ingestion.camera_manager import get_camera_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cameras"])


class LineConfigRequest(BaseModel):
    """Payload for updating camera crossing line."""
    cam_id: Optional[str] = Field(default=None, description="Camera ID (e.g. cam1, cam2)")
    line: List[List[float]] = Field(..., description="[[x1, y1], [x2, y2]] normalized 0..1 or pixel coords")
    direction: str = Field(default="IN->OUT", description="Crossing direction semantics: IN->OUT, OUT->IN, side_a_to_b_in")


def _sync_line_to_pipeline_yaml(cam_id: str, p1: tuple[int, int], p2: tuple[int, int], direction: str) -> bool:
    """Persist updated line coordinates into pipeline_engine/config/pipeline.yaml."""
    yaml_path = Path("pipeline_engine/config/pipeline.yaml")
    if not yaml_path.exists():
        logger.warning(f"pipeline.yaml not found at {yaml_path}")
        return False
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        norm_id = cam_id.lower().replace("-", "").strip()
        semantics = "side_a_to_b_in" if "IN" in direction else "side_b_to_a_in"

        if "cameras" in data and isinstance(data["cameras"], dict):
            matched = False
            for cid in data["cameras"]:
                if cid.lower().replace("-", "").strip() == norm_id:
                    if "geometry" not in data["cameras"][cid] or not isinstance(data["cameras"][cid]["geometry"], dict):
                        data["cameras"][cid]["geometry"] = {}
                    data["cameras"][cid]["geometry"]["line_start"] = [int(p1[0]), int(p1[1])]
                    data["cameras"][cid]["geometry"]["line_end"] = [int(p2[0]), int(p2[1])]
                    data["cameras"][cid]["geometry"]["direction_semantics"] = semantics
                    matched = True
                    break
            if matched:
                with open(yaml_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, sort_keys=False)
                logger.info(f"Persisted new crossing line for {cam_id} into {yaml_path}")
                return True
    except Exception as e:
        logger.error(f"Failed to update {yaml_path}: {e}")
    return False


def _process_line_save(cam_id: str, req: LineConfigRequest) -> Dict[str, Any]:
    """Convert coordinates, dynamically update AttendanceEngine, and persist to pipeline.yaml."""
    coords = req.line
    if len(coords) < 2 or len(coords[0]) < 2 or len(coords[1]) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Line must contain two coordinate pairs: [[x1, y1], [x2, y2]]"
        )

    x1, y1 = coords[0][0], coords[0][1]
    x2, y2 = coords[1][0], coords[1][1]

    # Convert normalized (0.0 to 1.0) to native 4K (3840x2160)
    native_w, native_h = 3840, 2160
    if 0.0 <= x1 <= 1.0 and 0.0 <= x2 <= 1.0 and 0.0 <= y1 <= 1.0 and 0.0 <= y2 <= 1.0:
        px1 = round(x1 * native_w)
        py1 = round(y1 * native_h)
        px2 = round(x2 * native_w)
        py2 = round(y2 * native_h)
    else:
        px1 = round(x1)
        py1 = round(y1)
        px2 = round(x2)
        py2 = round(y2)

    semantics = "side_a_to_b_in" if "IN" in req.direction else "side_b_to_a_in"

    # 1. Dynamically update live crossing line in CameraManager / AttendanceEngine
    cm = get_camera_manager()
    cm_updated = False
    try:
        cm_updated = cm.update_crossing_line(
            camera_id=cam_id,
            p1=(px1, py1),
            p2=(px2, py2),
            direction_semantics=semantics
        )
    except Exception as e:
        logger.warning(f"Could not update live CameraManager: {e}")

    # 2. Persist updated line coordinates into pipeline.yaml
    yaml_saved = _sync_line_to_pipeline_yaml(cam_id, (px1, py1), (px2, py2), req.direction)

    return {
        "status": "success",
        "cam_id": cam_id,
        "line": [[px1, py1], [px2, py2]],
        "pixel_line": [[px1, py1], [px2, py2]],
        "normalized_line": [[round(px1 / native_w, 4), round(py1 / native_h, 4)], [round(px2 / native_w, 4), round(py2 / native_h, 4)]],
        "direction": req.direction,
        "live_engine_updated": cm_updated,
        "yaml_persisted": yaml_saved,
        "message": f"Crossing line for {cam_id} successfully updated and persisted."
    }


@router.post("/api/v1/cameras/{cam_id}/line")
async def save_camera_line(cam_id: str, req: LineConfigRequest):
    """Update crossing line for a specific camera."""
    return _process_line_save(cam_id, req)


@router.post("/api/v1/line")
async def save_line_alias(req: LineConfigRequest):
    """Alias endpoint for updating crossing line."""
    cam_id = req.cam_id or "cam1"
    return _process_line_save(cam_id, req)


@router.get("/api/v1/cameras/{cam_id}/line")
async def get_camera_line(cam_id: str):
    """Retrieve current crossing line for a camera."""
    norm_id = cam_id.lower().replace("-", "").strip()
    yaml_path = Path("pipeline_engine/config/pipeline.yaml")
    if yaml_path.exists():
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cams = data.get("cameras", {})
            for cid, ccfg in cams.items():
                if cid.lower().replace("-", "").strip() == norm_id:
                    geom = ccfg.get("geometry", {})
                    p1 = geom.get("line_start", [0, 1080])
                    p2 = geom.get("line_end", [3840, 1080])
                    direction = geom.get("direction_semantics", "side_a_to_b_in")
                    return {
                        "cam_id": cid,
                        "line": [p1, p2],
                        "normalized_line": [[p1[0] / 3840, p1[1] / 2160], [p2[0] / 3840, p2[1] / 2160]],
                        "direction": "IN->OUT" if "a_to_b" in direction else "OUT->IN"
                    }
        except Exception as e:
            logger.warning(f"Error reading line from pipeline.yaml: {e}")

    # Default fallback
    return {
        "cam_id": cam_id,
        "line": [[0, 1080], [3840, 1080]],
        "normalized_line": [[0.0, 0.5], [1.0, 0.5]],
        "direction": "IN->OUT"
    }


@router.get("/api/v1/line")
async def get_line_alias(cam_id: str = "cam1"):
    """Alias endpoint for retrieving crossing line."""
    return await get_camera_line(cam_id)


@router.get("/api/v1/recordings")
async def list_recordings(camera_id: Optional[str] = Query(default=None)):
    """
    List recordings and evidence clips/snapshots.
    Scans `recordings/` and `app/static/evidence/`.
    """
    items = []
    
    # 1. Scan recordings/
    recordings_dir = Path("recordings")
    if recordings_dir.exists():
        for path in recordings_dir.rglob("*.mp4"):
            cam = "cam1" if "cam1" in path.parts or "cam1" in path.name.lower() else ("cam2" if "cam2" in path.parts or "cam2" in path.name.lower() else "cam1")
            if camera_id and cam != camera_id.lower():
                continue
            stat = path.stat()
            items.append({
                "id": path.stem,
                "camera_id": cam,
                "filename": path.name,
                "url": f"/recordings/{path.relative_to(recordings_dir).as_posix()}",
                "type": "video",
                "size_bytes": stat.st_size,
                "timestamp": stat.st_mtime,
                "date_formatted": Path(path).parent.name
            })

    # 2. Scan app/static/evidence/
    evidence_dir = Path("app/static/evidence")
    if evidence_dir.exists():
        for path in evidence_dir.rglob("*.*"):
            if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".mp4"):
                continue
            cam = "cam1" if "cam1" in path.name.lower() else ("cam2" if "cam2" in path.name.lower() else "cam1")
            if camera_id and cam != camera_id.lower():
                continue
            stat = path.stat()
            rel_url = f"/static/evidence/{path.relative_to(evidence_dir).as_posix()}"
            items.append({
                "id": path.stem,
                "camera_id": cam,
                "filename": path.name,
                "url": rel_url,
                "type": "video" if path.suffix.lower() == ".mp4" else "snapshot",
                "size_bytes": stat.st_size,
                "timestamp": stat.st_mtime,
                "date_formatted": Path(path).parent.name
            })

    # Sort descending by timestamp
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    return {"total": len(items), "recordings": items}


@router.get("/api/v1/recordings/{recording_id}/events")
async def get_recording_events(recording_id: str):
    """
    Retrieve real correlated attendance events for a specific recording.
    Matches camera_id, time window, and calculates interactive timeline seek offsets.
    """
    clean_id = Path(recording_id).stem
    recordings_dir = Path("recordings")
    found_file = None
    if recordings_dir.exists():
        for p in recordings_dir.rglob("*.mp4"):
            if p.stem == clean_id or clean_id in p.name:
                found_file = p
                break

    cam_id = "cam1"
    if "cam2" in clean_id.lower() or (found_file and "cam2" in found_file.parts):
        cam_id = "cam2"

    if not (found_file and found_file.exists()):
        return {
            "recording_id": clean_id,
            "camera_id": cam_id,
            "video_start_timestamp": None,
            "duration_seconds": 0.0,
            "total": 0,
            "events": []
        }

    stat = found_file.stat()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})", found_file.name)
    if m:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                      int(m.group(4)), int(m.group(5)), int(m.group(6)))
        start_ts = dt.timestamp()
    else:
        start_ts = stat.st_mtime

    duration = 60.0
    try:
        import cv2
        cap = cv2.VideoCapture(str(found_file))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if frames > 0 and fps > 0:
            duration = frames / fps
        cap.release()
    except Exception:
        pass

    end_ts = start_ts + duration

    # Query real events from school.db and attendance.db
    db_path = Path("app/data/attendance.db")
    school_db = Path("app/data/school.db")

    student_map = {}
    if school_db.exists():
        try:
            with sqlite3.connect(school_db) as s_conn:
                for s_id, name, cid in s_conn.execute("SELECT student_id, full_name, class_id FROM students").fetchall():
                    student_map[s_id] = (name, cid)
        except Exception as e:
            logger.warning(f"Error loading student_map from school.db: {e}")

    events = []
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                # Strictly query attendance_records by camera_id and timestamp window [start_ts, end_ts]
                rows = cur.execute("""
                    SELECT attendance_record_id, identity_candidate, identity_confidence,
                           direction, event_timestamp, snapshot_face_url, video_clip_url
                    FROM attendance_records
                    WHERE camera_id = :cam COLLATE NOCASE
                      AND event_timestamp >= :start_ts
                      AND event_timestamp <= :end_ts
                    ORDER BY event_timestamp ASC
                """, {"cam": cam_id, "start_ts": start_ts, "end_ts": end_ts}).fetchall()

                for r in rows:
                    sid = r["identity_candidate"] or "UNKNOWN"
                    sname, sclass = student_map.get(sid, (sid, "N/A"))
                    ev_ts = float(r["event_timestamp"])
                    offset_sec = max(0.0, min(duration, ev_ts - start_ts))
                    direction = (r["direction"] or "in").lower()
                    crop = r["snapshot_face_url"]

                    events.append({
                        "id": r["attendance_record_id"],
                        "student_id": sid,
                        "student_name": sname,
                        "class_id": sclass,
                        "camera_id": cam_id,
                        "event_type": "IN" if direction == "in" else "OUT",
                        "direction": direction,
                        "timestamp": ev_ts,
                        "time_str": datetime.fromtimestamp(ev_ts).strftime("%H:%M:%S"),
                        "confidence": round(float(r["identity_confidence"] or 0.0), 2),
                        "evidence_snapshot_path": crop,
                        "evidence_clip_path": r["video_clip_url"] or f"/recordings/{found_file.relative_to(recordings_dir).as_posix()}",
                        "offset_seconds": round(offset_sec, 2),
                    })
        except Exception as e:
            logger.error(f"Error querying recording events: {e}")

    return {
        "recording_id": clean_id,
        "camera_id": cam_id,
        "video_start_timestamp": start_ts,
        "duration_seconds": round(duration, 2),
        "total": len(events),
        "events": events
    }

