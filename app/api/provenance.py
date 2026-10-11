"""
Phase 44.X.4-R3.3-FIX — Real Provenance Endpoint.

Exposes the actual runtime provenance chain (Frame/Detection → Track →
CrossingEvent → RawInOutEvent → ResolvedTransition → AttendanceRecord) for
the most recently persisted AttendanceRecord. The data is sourced from
real persisted records via the AttendanceRepository plus the live
runtime/health snapshot. No synthetic values are produced.

Honest "unavailable" markers are emitted for stages whose identity is not
persisted in the current system (Frame/Detection/Track/CrossingEvent).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.attendance import get_repository
from app.api.health import GPUStatusResponse
from app.attendance.contract import AttendanceRecord
from app.attendance.repository import AttendanceRepository
from app.models.contracts import ModelDefinition
from app.runtime import collect_runtime_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/provenance", tags=["provenance"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ProvenanceNode(BaseModel):
    """A single node in the real runtime provenance chain.

    `available` is False when the current system does not persist a stable
    identity for that stage; the UI MUST render it as an explicit
    "Unavailable / Not exposed" state, never as a fabricated value.
    """

    stage: str
    label: str
    kind: str
    id: Optional[str] = None
    description: str
    available: bool
    camera_id: Optional[str] = None
    timestamp: Optional[str] = None
    extras: Dict[str, Any] = Field(default_factory=dict)


class ModelIdentity(BaseModel):
    """Real model identity, sourced from app/runtime + app/models/registry.

    `name` is the real configured model. `source` points to the file path
    surfaced by the runtime snapshot when available.
    """

    person_detector: Dict[str, str]
    face_detector: Dict[str, str]
    face_embedding: Dict[str, str]
    person_reid: Dict[str, str]
    face_landmark: Dict[str, str]


class SystemState(BaseModel):
    camera_ids: List[str]
    active_camera_ids: List[str]
    inactive_camera_ids: List[str]
    gpu_name: str
    gpu_available: bool
    python_version: str
    platform: str
    architecture: str
    venv_active: bool
    overall_status: Optional[str] = None


class ProvenanceResponse(BaseModel):
    has_data: bool
    source: str
    selected_record: Optional[Dict[str, Any]] = None
    chain: List[ProvenanceNode]
    models: ModelIdentity
    system: SystemState
    note: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _camera_ids_from_health(repository: AttendanceRepository) -> List[str]:
    """Discover real camera IDs.

    Prefer cameras that have at least one persisted attendance record.
    Falls back to the live health monitor if no records exist yet.
    """
    try:
        distinct_cameras = repository.storage.get_distinct_camera_ids()
        if distinct_cameras:
            return sorted(distinct_cameras)
    except Exception as exc:  # noqa: BLE001
        logger.debug("storage.get_distinct_camera_ids failed: %s", exc)

    try:
        from app.streaming.shared_health import get_shared_health_monitor

        monitor = get_shared_health_monitor()
        return sorted(monitor.cameras.keys())
    except Exception as exc:  # noqa: BLE001
        logger.debug("shared_health_monitor unavailable: %s", exc)

    return []


def _active_camera_ids(camera_ids: List[str]) -> List[str]:
    """Determine which cameras are currently live via the health monitor."""
    if not camera_ids:
        return []
    try:
        from app.streaming.shared_health import get_shared_health_monitor

        monitor = get_shared_health_monitor()
        results = monitor.check_all_health()
        return sorted(
            cam_id
            for cam_id in camera_ids
            if cam_id in results and results[cam_id].state.value == "live"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("check_all_health unavailable: %s", exc)
        return []


def _latest_record(repository: AttendanceRepository) -> Optional[AttendanceRecord]:
    """Return the most recently persisted AttendanceRecord (or None)."""
    try:
        records = repository.storage.query(limit=1, order_by="event_timestamp", desc=True)
        if records:
            return records[0]
    except Exception as exc:  # noqa: BLE001
        logger.debug("query latest attendance record failed: %s", exc)
    return None


def _build_chain(record: Optional[AttendanceRecord]) -> List[ProvenanceNode]:
    """Build the real runtime chain.

    Stages marked `available=False` are honest "not persisted" markers.
    """
    if record is None:
        return [
            ProvenanceNode(
                stage="frame",
                label="Frame",
                kind="source",
                description="Raw frame captured from the camera.",
                available=False,
            ),
            ProvenanceNode(
                stage="detection",
                label="Detection",
                kind="process",
                description="Person detection (YOLO11n).",
                available=False,
            ),
            ProvenanceNode(
                stage="track",
                label="Track",
                kind="process",
                description="Per-camera tracker output.",
                available=False,
            ),
            ProvenanceNode(
                stage="crossing_event",
                label="CrossingEvent",
                kind="event",
                description="Geometry crossing event (Phase 22).",
                available=False,
            ),
            ProvenanceNode(
                stage="raw_in_out_event",
                label="RawInOutEvent",
                kind="event",
                description="Raw in/out event (Phase 23).",
                available=False,
            ),
            ProvenanceNode(
                stage="resolved_transition",
                label="ResolvedTransition",
                kind="event",
                description="Resolved transition (Phase 24).",
                available=False,
            ),
            ProvenanceNode(
                stage="attendance_record",
                label="AttendanceRecord",
                kind="record",
                description="No persisted attendance record available.",
                available=False,
            ),
        ]

    event_iso: Optional[str] = None
    if record.event_timestamp:
        from datetime import datetime

        event_iso = (
            datetime.utcfromtimestamp(record.event_timestamp).isoformat() + "Z"
        )

    return [
        ProvenanceNode(
            stage="frame",
            label="Frame",
            kind="source",
            id=None,
            description=(
                f"Raw frame from camera '{record.camera_id}' at event time."
            ),
            available=False,
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={"reason": "Raw frames are not persisted in the current system."},
        ),
        ProvenanceNode(
            stage="detection",
            label="Detection",
            kind="process",
            id=None,
            description="Person bounding box produced by YOLO11n.",
            available=False,
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={"reason": "Detection outputs are not persisted."},
        ),
        ProvenanceNode(
            stage="track",
            label="Track",
            kind="process",
            id=record.local_track_id,
            description=(
                f"Local tracker track for camera '{record.camera_id}'."
            ),
            available=True,
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={"local_track_id": record.local_track_id},
        ),
        ProvenanceNode(
            stage="crossing_event",
            label="CrossingEvent",
            kind="event",
            id=record.source_crossing_event_id,
            description="Geometry crossing event (Phase 22).",
            available=bool(record.source_crossing_event_id),
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={
                "persisted": bool(record.source_crossing_event_id),
                "source": "AttendanceRecord.source_crossing_event_id",
            },
        ),
        ProvenanceNode(
            stage="raw_in_out_event",
            label="RawInOutEvent",
            kind="event",
            id=record.source_raw_event_id,
            description="Raw in/out event (Phase 23).",
            available=bool(record.source_raw_event_id),
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={"source": "AttendanceRecord.source_raw_event_id"},
        ),
        ProvenanceNode(
            stage="resolved_transition",
            label="ResolvedTransition",
            kind="event",
            id=record.source_resolution_id,
            description="Resolved transition (Phase 24).",
            available=bool(record.source_resolution_id),
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={
                "previous_state": record.previous_state,
                "new_state": record.new_state,
                "source": "AttendanceRecord.source_resolution_id",
            },
        ),
        ProvenanceNode(
            stage="attendance_record",
            label="AttendanceRecord",
            kind="record",
            id=record.attendance_record_id,
            description="Persisted attendance record (Phase 25).",
            available=True,
            camera_id=record.camera_id,
            timestamp=event_iso,
            extras={
                "direction": record.direction.value,
                "identity_certainty": record.identity_certainty.value,
                "identity_candidate": record.identity_candidate,
                "global_observation_id": record.global_observation_id,
                "resolver_version": record.resolver_version,
                "attendance_schema_version": record.attendance_schema_version,
                "persisted_at": record.persisted_at,
            },
        ),
    ]


def _build_model_identity() -> ModelIdentity:
    """Return real model identity from the configured registry.

    The source of truth is app/models/registry.py. Filenames and
    display names are returned verbatim — never substituted with
    alternative model names.
    """
    from app.models.registry import get_model_registry

    registry = get_model_registry()
    runtime = collect_runtime_snapshot()
    model_avail = runtime.model_availability or {}

    def _entry(model_id: str, fallback_name: str, fallback_filename: str) -> Dict[str, str]:
        defn: Optional[ModelDefinition] = None
        try:
            defn = registry.get(model_id)
        except Exception:  # noqa: BLE001
            defn = None
        if defn is not None:
            return {
                "model_id": defn.model_id,
                "display_name": defn.display_name,
                "filename": defn.filename,
                "format": defn.format.value,
                "availability": model_avail.get(model_id, "unknown"),
            }
        return {
            "model_id": model_id,
            "display_name": fallback_name,
            "filename": fallback_filename,
            "format": "unknown",
            "availability": model_avail.get(model_id, "unknown"),
        }

    return ModelIdentity(
        person_detector=_entry(
            "yolo_person",
            fallback_name="YOLO11n Person Detector",
            fallback_filename="yolo11n.pt",
        ),
        face_detector=_entry(
            "scrfd",
            fallback_name="SCRFD Face Detector",
            fallback_filename="scrfd_10g_bnkps.onnx",
        ),
        face_embedding=_entry(
            "arcface",
            fallback_name="ArcFace Face Recognition",
            fallback_filename="arcface_r100.onnx",
        ),
        person_reid=_entry(
            "reid",
            fallback_name="ResNet50 ReID",
            fallback_filename="resnet50_reid.onnx",
        ),
        face_landmark=_entry(
            "landmark_1k3d68",
            fallback_name="1K3D68 Face Landmark",
            fallback_filename="1k3d68.onnx",
        ),
    )


def _build_system_state(camera_ids: List[str], active_ids: List[str]) -> SystemState:
    runtime = collect_runtime_snapshot()
    gpu = GPUStatusResponse(
        gpu_name=runtime.nvidia_gpu_name or "Unknown",
        driver_version=runtime.nvidia_driver_version or "Unknown",
        cuda_runtime_version=runtime.cuda_runtime_version or "Unknown",
        cuda_toolkit_version=runtime.cuda_toolkit_version or "Unknown",
        cudnn_version=runtime.cudnn_version or "Unknown",
        pytorch_version=runtime.pytorch_version or "Unknown",
        pytorch_cuda_version=runtime.pytorch_cuda_version or "Unknown",
        torch_cuda_available=runtime.torch_cuda_available,
        onnxruntime_version=runtime.onnxruntime_version or "Unknown",
        cuda_ep_registered=runtime.cuda_ep_registered,
        nvdec_available=runtime.ffmpeg_available,
        model_availability=runtime.model_availability or {},
    )
    inactive = [c for c in camera_ids if c not in set(active_ids)]
    return SystemState(
        camera_ids=camera_ids,
        active_camera_ids=active_ids,
        inactive_camera_ids=inactive,
        gpu_name=gpu.gpu_name,
        gpu_available=bool(runtime.torch_cuda_available),
        python_version=runtime.python_version,
        platform=runtime.windows_version,
        architecture=runtime.architecture,
        venv_active=runtime.venv_active,
        overall_status=None,
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("", response_model=ProvenanceResponse)
async def get_provenance() -> ProvenanceResponse:
    """Return the real runtime provenance chain.

    The chain is anchored to the most recently persisted
    `AttendanceRecord`. If no record exists, the endpoint returns
    `has_data=False` with honest "unavailable" markers and the live
    system/model state so the UI never shows fabricated values.
    """
    repository = get_repository()
    record = _latest_record(repository)
    camera_ids = _camera_ids_from_health(repository)
    active_ids = _active_camera_ids(camera_ids)

    chain = _build_chain(record)
    models = _build_model_identity()
    system = _build_system_state(camera_ids, active_ids)

    selected: Optional[Dict[str, Any]] = None
    if record is not None:
        selected = {
            "attendance_record_id": record.attendance_record_id,
            "camera_id": record.camera_id,
            "local_track_id": record.local_track_id,
            "global_observation_id": record.global_observation_id,
            "source_raw_event_id": record.source_raw_event_id,
            "source_resolution_id": record.source_resolution_id,
            "source_crossing_event_id": record.source_crossing_event_id,
            "direction": record.direction.value,
            "identity_certainty": record.identity_certainty.value,
            "identity_candidate": record.identity_candidate,
            "event_timestamp": record.event_timestamp,
            "persisted_at": record.persisted_at,
            "previous_state": record.previous_state,
            "new_state": record.new_state,
            "resolver_version": record.resolver_version,
            "attendance_schema_version": record.attendance_schema_version,
        }

    note = (
        "Chain derived from the most recently persisted AttendanceRecord. "
        "Stages without a stable persisted identity are returned as "
        "`available=false` and the UI renders them as 'Unavailable / Not exposed'."
    )

    return ProvenanceResponse(
        has_data=record is not None,
        source="AttendanceRepository + app.runtime.collect_runtime_snapshot",
        selected_record=selected,
        chain=chain,
        models=models,
        system=system,
        note=note,
    )


@router.get("/records/{record_id}", response_model=ProvenanceResponse)
async def get_provenance_for_record(record_id: str) -> ProvenanceResponse:
    """Return the real provenance chain for a specific AttendanceRecord."""
    repository = get_repository()
    record = repository.get_by_id(record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Attendance record {record_id} not found",
        )

    camera_ids = _camera_ids_from_health(repository)
    active_ids = _active_camera_ids(camera_ids)

    chain = _build_chain(record)
    models = _build_model_identity()
    system = _build_system_state(camera_ids, active_ids)

    selected = {
        "attendance_record_id": record.attendance_record_id,
        "camera_id": record.camera_id,
        "local_track_id": record.local_track_id,
        "global_observation_id": record.global_observation_id,
        "source_raw_event_id": record.source_raw_event_id,
        "source_resolution_id": record.source_resolution_id,
        "source_crossing_event_id": record.source_crossing_event_id,
        "direction": record.direction.value,
        "identity_certainty": record.identity_certainty.value,
        "identity_candidate": record.identity_candidate,
        "event_timestamp": record.event_timestamp,
        "persisted_at": record.persisted_at,
        "previous_state": record.previous_state,
        "new_state": record.new_state,
        "resolver_version": record.resolver_version,
        "attendance_schema_version": record.attendance_schema_version,
    }

    return ProvenanceResponse(
        has_data=True,
        source="AttendanceRepository.get_by_id + app.runtime.collect_runtime_snapshot",
        selected_record=selected,
        chain=chain,
        models=models,
        system=system,
        note="Chain for explicit AttendanceRecord.",
    )
