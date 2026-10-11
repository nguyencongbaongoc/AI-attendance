"""
Phase 44.X.4 — Canonical Annotation Renderer.

Pure visualizer for AI results. Does NOT run inference, does NOT mutate the
input frame, does NOT participate in detection/tracking/identity/crossing.

Consumes the post-inference DetectionOverlayItem / LineOverlayItem /
RegionOverlayItem dicts (already produced by DetectionPipeline) and draws
them onto a copy of frame.data, returning the annotated BGR ndarray.

Coordinate space:
    The renderer expects ORIGINAL_FRAME coordinates (the same space used by
    the YOLO/SCRFD/association/tracker pipeline and exposed via
    DetectionOverlayItem.bbox / LineOverlayItem vertices / RegionOverlayItem
    vertices). No rescaling is performed here.

Safety:
    annotate_frame(...) always returns a new ndarray; frame_data is never
    modified. The detection pipeline continues to use its own copy /
    non-mutating read of frame_data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


_BGR_CYAN: Tuple[int, int, int] = (255, 255, 0)
_BGR_GREEN: Tuple[int, int, int] = (0, 255, 0)
_BGR_RED: Tuple[int, int, int] = (0, 0, 255)
_BGR_AMBER: Tuple[int, int, int] = (0, 165, 255)
_BGR_WHITE: Tuple[int, int, int] = (255, 255, 255)
_BGR_BLACK: Tuple[int, int, int] = (0, 0, 0)


def _clamp_bbox(
    bbox: Sequence[float],
    width: int,
    height: int,
) -> Optional[Tuple[int, int, int, int]]:
    """Clamp a (x1, y1, x2, y2) bbox to the frame interior. Returns None if empty."""
    if not bbox or len(bbox) < 4:
        return None
    x1 = int(max(0, min(width - 1, round(float(bbox[0])))))
    y1 = int(max(0, min(height - 1, round(float(bbox[1])))))
    x2 = int(max(0, min(width - 1, round(float(bbox[2])))))
    y2 = int(max(0, min(height - 1, round(float(bbox[3])))))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _font_scale_for_frame(height: int) -> float:
    """Pick a font scale proportional to the frame height."""
    if height <= 0:
        return 0.5
    return max(0.4, min(2.0, height / 1080.0))


def _line_thickness_for_frame(height: int) -> int:
    if height <= 0:
        return 2
    return max(2, min(5, height // 540))


def annotate_frame(
    frame_data: np.ndarray,
    detections: Optional[List[Dict[str, Any]]] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    regions: Optional[List[Dict[str, Any]]] = None,
    camera_id: Optional[str] = None,
) -> np.ndarray:
    """
    Render detection/line/region overlays onto a copy of frame_data.

    The input frame_data is NEVER modified; a new BGR ndarray is returned.

    The renderer assumes BGR pixel order (the canonical frame output of the
    RTSP source decoder). If a grayscale or RGB array is passed it is
    converted to BGR for the duration of the draw and returned as-is shape
    (i.e. the rendered output is always the same shape as the input).
    """
    if frame_data is None or not isinstance(frame_data, np.ndarray):
        raise ValueError("annotate_frame requires a numpy ndarray frame_data")

    # Always draw on a copy so the original frame is preserved.
    if frame_data.ndim == 2:
        canvas = cv2_gray_to_bgr(frame_data)
    elif frame_data.shape[2] == 3:
        canvas = frame_data.copy()
    else:
        canvas = frame_data[:, :, :3].copy()

    height, width = canvas.shape[:2]
    font_scale = _font_scale_for_frame(height)
    thickness = _line_thickness_for_frame(height)
    text_thickness = max(1, thickness - 1)

    try:
        import cv2  # local import to keep the renderer module testable without cv2

        if regions:
            _draw_regions(canvas, regions, cv2)

        if lines:
            _draw_lines(canvas, lines, cv2)

        if detections:
            _draw_detections(canvas, detections, cv2, font_scale, thickness, text_thickness)

        if camera_id:
            _draw_camera_tag(canvas, camera_id, cv2, font_scale, text_thickness)
    except Exception as e:  # noqa: BLE001 - renderer must never break the pipeline
        logger.error("AnnotationRenderer: draw failed: %s", e)

    return canvas


def _draw_detections(
    canvas: np.ndarray,
    detections: List[Dict[str, Any]],
    cv2: Any,
    font_scale: float,
    thickness: int,
    text_thickness: int,
) -> None:
    height, width = canvas.shape[:2]
    for det in detections:
        bbox = det.get("bbox") if isinstance(det, dict) else None
        if not bbox:
            continue
        clamped = _clamp_bbox(bbox, width, height)
        if clamped is None:
            continue
        x1, y1, x2, y2 = clamped

        identity_certainty = (det.get("identity_certainty") or "unknown") if isinstance(det, dict) else "unknown"
        if identity_certainty == "known":
            color = _BGR_CYAN
        elif identity_certainty in ("ambiguous", "insufficient"):
            color = _BGR_AMBER
        else:
            color = _BGR_GREEN

        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)

        label = det.get("label") or det.get("track_id") or "Person"
        if isinstance(det.get("person_id"), str) and det.get("person_id"):
            label = det["person_id"]
        confidence = det.get("confidence")
        if isinstance(confidence, (int, float)) and confidence > 0:
            text = f"{label} {int(round(float(confidence) * 100))}%"
        else:
            text = str(label)

        (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness)
        ty1 = max(0, y1 - th - baseline - 4)
        ty2 = ty1 + th + baseline + 4
        tx2 = min(width, x1 + tw + 8)
        tx1 = max(0, x2 - tw - 8)
        if ty2 - ty1 > 0 and tx2 - tx1 > 0:
            cv2.rectangle(canvas, (tx1, ty1), (tx2, ty2), color, -1)
            text_color = _BGR_BLACK
            cv2.putText(
                canvas,
                text,
                (tx1 + 4, ty2 - baseline - 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                text_color,
                text_thickness,
                cv2.LINE_AA,
            )


def _draw_lines(
    canvas: np.ndarray,
    lines: List[Dict[str, Any]],
    cv2: Any,
) -> None:
    height, width = canvas.shape[:2]
    for line in lines:
        if not isinstance(line, dict):
            continue
        if line.get("enabled") is False:
            continue
        start = line.get("start") or {}
        end = line.get("end") or {}
        if not (isinstance(start, dict) and isinstance(end, dict)):
            continue
        try:
            x1 = int(max(0, min(width - 1, round(float(start.get("x", 0))))))
            y1 = int(max(0, min(height - 1, round(float(start.get("y", 0))))))
            x2 = int(max(0, min(width - 1, round(float(end.get("x", 0))))))
            y2 = int(max(0, min(height - 1, round(float(end.get("y", 0))))))
        except (TypeError, ValueError):
            continue
        color = _BGR_GREEN
        cv2.line(canvas, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)


def _draw_regions(
    canvas: np.ndarray,
    regions: List[Dict[str, Any]],
    cv2: Any,
) -> None:
    height, width = canvas.shape[:2]
    overlay = canvas.copy()
    for region in regions:
        if not isinstance(region, dict):
            continue
        if region.get("enabled") is False:
            continue
        vertices = region.get("vertices")
        if not vertices:
            continue
        pts = []
        for v in vertices:
            if not isinstance(v, dict):
                continue
            try:
                x = int(max(0, min(width - 1, round(float(v.get("x", 0))))))
                y = int(max(0, min(height - 1, round(float(v.get("y", 0))))))
            except (TypeError, ValueError):
                continue
            pts.append((x, y))
        if len(pts) < 3:
            continue
        pts_arr = np.asarray(pts, dtype=np.int32)
        cv2.fillPoly(overlay, [pts_arr], _BGR_CYAN)
    cv2.addWeighted(overlay, 0.15, canvas, 0.85, 0, canvas)


def _draw_camera_tag(
    canvas: np.ndarray,
    camera_id: str,
    cv2: Any,
    font_scale: float,
    text_thickness: int,
) -> None:
    height, width = canvas.shape[:2]
    text = f"{camera_id}  AI"
    (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_thickness)
    margin = 12
    x2 = width - margin
    y2 = height - margin
    x1 = x2 - tw - 12
    y1 = y2 - th - baseline - 8
    cv2.rectangle(canvas, (x1, y1), (x2, y2), _BGR_BLACK, -1)
    cv2.putText(
        canvas,
        text,
        (x1 + 6, y2 - baseline - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        _BGR_WHITE,
        text_thickness,
        cv2.LINE_AA,
    )


def cv2_gray_to_bgr(gray: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
