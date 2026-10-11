"""
Phase 44.6/44.7 — Detection Pipeline for Camera Ingestion Workers.

Consumes frames from CameraIngestionWorker frame_callback, runs the
canonical pipeline (Person Detection -> Face Detection -> Association ->
Tracking -> Crossing -> Attendance) and emits DetectionSnapshot events
via the shared health monitor's event callback.

Phase 51 — Detection → Tracking contract fix:
- The face detector receives the CanonicalFrame (not frame.data) so that
  detector preprocessing/contract code can read frame.metadata.
- Person detections come from a YOLO person detector (the canonical
  source for person boxes in the live pipeline).
- Associations are produced from (person, face) detection pairs using
  the existing associate_detections contract.
- track_frame is called with the exact 5-argument signature
  (person_detections, face_detections, associations, frame, previous_tracks)
  so the metadata-bearing frame reaches the tracker.
- This module never bypasses or skips tracking.

Phase 44.X.4 — AI-Annotated Video Output:
- Adds an OPTIONAL `annotated_publisher` argument (no default behavior
  change when None). When provided, the existing DetectionOverlayItem /
  LineOverlayItem / RegionOverlayItem dicts that this pipeline already
  builds for the DetectionSnapshot event are also submitted to the
  publisher, which renders them onto a copy of frame.data and pushes an
  H.264 RTSP stream into MediaMTX. No AI inference is duplicated; no
  detection / tracking / identity / crossing logic is changed.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from app.config.settings import load_settings
from app.data.frame import CanonicalFrame
from app.geometry.contract import load_geometry_config
from app.geometry.crossing import CrossingEngine, create_crossing_engine
from app.in_out.raw_event import RawEventEngine, create_raw_event_engine
from app.in_out.resolver import RepeatedInOutResolver, create_repeated_in_out_resolver
from app.attendance.repository import AttendanceRepository, create_attendance_repository
from app.attendance.policy_engine.engine import AttendancePolicyEngine
from app.streaming.shared_health import get_shared_health_monitor
from app.streaming.health_events import (
    HealthEventType,
    create_detection_snapshot_event,
)
from app.vision.detector_factory import get_detector
from app.vision.tracker import TrackerConfig, track_frame
from app.vision.association import associate_detections, AssociationConfig
from app.vision.association_contract import AssociationResult
from app.vision.yolo_person_detector import get_person_detector, PersonDetection

logger = logging.getLogger(__name__)

def extract_yolo_input(frame) -> Any:
    """Explicit production adapter boundary."""
    # P8 FORENSIC INSTRUMENTATION (Section 5, 7, 11, 17)
    from artifacts.phase8_remediation.deep_forensic_instrument import capture_canonical_frame, capture_dict_payload, log_marker
    log_marker(f"PIPELINE_INPUT_TYPE={type(frame).__name__} PIPELINE_INPUT_ID={id(frame)}")
    data = frame.data
    log_marker(f"CANONICAL_DATA_TYPE={type(data).__name__} CANONICAL_DATA_ID={id(data)}")
    if isinstance(data, dict):
        capture_dict_payload(data, label="CANONICAL_DICT")
        # Inspect all possible adapter_contract paths per Section 6
        adapter_ref = data.get('adapter_contract', None)
        adapter_path = 'data.get("adapter_contract")'
        adapter_contract_type = type(adapter_ref).__name__ if adapter_ref is not None else 'None'
        adapter_contract_id = id(adapter_ref) if adapter_ref is not None else 'None'
        log_marker(
            f"CANONICAL_ADAPTER_PATH={adapter_path} CANONICAL_ADAPTER_TYPE={adapter_contract_type} CANONICAL_ADAPTER_ID={adapter_contract_id}"
        )
        # Nested search per Section 6 / 12
        nested_found = False
        for k in list(data.keys()):
            v = data.get(k)
            if isinstance(v, dict):
                for subk in list(v.keys()):
                    if subk == 'adapter_contract' or 'adapter_contract' in subk:
                        nested_ref = v.get(subk)
                        nested_path = f'data["{k}"]["{subk}"]'
                        nested_type = type(nested_ref).__name__ if nested_ref is not None else 'None'
                        nested_id = id(nested_ref) if nested_ref is not None else 'None'
                        log_marker(f"CANONICAL_NESTED_PATH={nested_path} CANONICAL_NESTED_TYPE={nested_type} CANONICAL_NESTED_ID={nested_id}")
                        nested_found = True
        if not nested_found and adapter_ref is None:
            log_marker("CANONICAL_ADAPTER_REF_MISSING=YES (not in top-level keys, no nested adapter_contract)")
        else:
            log_marker(f"CANONICAL_ADAPTER_REF_MISSING=NO adapter_contract_ref={adapter_ref is not None}")
    else:
        adapter_ref_attr = getattr(data, 'adapter_contract', None)
        adapter_attr_path = 'data.adapter_contract (attr)'
        adapter_attr_type = type(adapter_ref_attr).__name__ if adapter_ref_attr is not None else 'None'
        adapter_attr_id = id(adapter_ref_attr) if adapter_ref_attr is not None else 'None'
        log_marker(
            f"CANONICAL_ADAPTER_ATTR={adapter_attr_path} CANONICAL_ADAPTER_ATTR_TYPE={adapter_attr_type} CANONICAL_ADAPTER_ATTR_ID={adapter_attr_id}"
        )
    # Exact lookup path verification per Section 11
    lookup_path = None
    adapter_contract_ref_lookup = None
    try:
        from app.video.pynvcodec.frame_contract import FrameContract
    except Exception:
        FrameContract = None
    # Direct FrameContract
    if FrameContract is not None and isinstance(data, FrameContract):
        adapter_contract = data
        decoded_frame = adapter_contract.cuda_memory_ref
        if decoded_frame is not None and hasattr(decoded_frame, 'shape'):
            try:
                image_array = decoded_frame.nv12_to_rgb()
                return image_array
            except Exception:
                pass
        if hasattr(decoded_frame, 'nvcv_image'):
            return decoded_frame.nvcv_image
    # Dict wrapper
    if isinstance(data, dict):
        adapter_contract_ref = data.get('adapter_contract', None)
        if adapter_contract_ref is not None:
            # Direct extraction from adapter_contract_ref (FrameContract or DecodedFrame wrapper)
            if hasattr(adapter_contract_ref, 'cuda_memory_ref'):
                adapter_contract = adapter_contract_ref
                decoded_frame = adapter_contract.cuda_memory_ref
                if decoded_frame is not None and hasattr(decoded_frame, 'shape'):
                    try:
                        image_array = decoded_frame.nv12_to_rgb()
                        logger.info('[YOLO_CONVERSION] dict_wrapper adapter_contract=FrameContract decoded_shape=%s -> nv12_to_rgb type=%s', str(decoded_frame.shape), type(image_array).__name__)
                        return image_array
                    except Exception:
                        logger.info('[YOLO_CONVERSION] nv12_to_rgb failed: %s', str(Exception))
                if hasattr(decoded_frame, 'nvcv_image'):
                    logger.info('[YOLO_CONVERSION] dict_wrapper adapter_contract=FrameContract decoded_shape=%s -> nvcv_image type=%s', str(decoded_frame.shape), type(decoded_frame.nvcv_image).__name__)
                    return decoded_frame.nvcv_image
            # Direct DecodedFrame embedded in adapter_contract_ref
            if hasattr(adapter_contract_ref, 'nv12_to_rgb'):
                try:
                    image_array = adapter_contract_ref.nv12_to_rgb()
                    logger.info('[YOLO_CONVERSION] adapter_contract_ref direct nv12_to_rgb type=%s', type(image_array).__name__)
                    return image_array
                except Exception:
                    logger.info('[YOLO_CONVERSION] adapter_contract_ref direct nv12_to_rgb failed')
            if hasattr(adapter_contract_ref, 'shape') and hasattr(adapter_contract_ref, 'nvcv_image'):
                logger.info('[YOLO_CONVERSION] adapter_contract_ref direct nvcv_image type=%s', type(adapter_contract_ref.nvcv_image).__name__)
                return adapter_contract_ref.nvcv_image
        raise TypeError('CanonicalFrame.data dict wrapper conversion failed; adapter_contract_ref=%s type=%s' % (str(adapter_contract_ref) if adapter_contract_ref is not None else 'None', type(adapter_contract_ref).__name__ if adapter_contract_ref is not None else 'None'))
    # Array-like payload
    if hasattr(data, 'shape') and hasattr(data, 'ndim'):
        return data
    raise TypeError('Unsupported payload type for YOLO input: %s' % type(data).__name__)



@dataclass
class DetectionPipelineConfig:
    """Configuration for the detection pipeline."""
    camera_id: str
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.4
    tracker_config: Optional[TrackerConfig] = None
    association_config: Optional[AssociationConfig] = None
    emit_detection_events: bool = True
    
    # Attendance pipeline config
    enable_crossing: bool = True
    enable_attendance: bool = True
    enable_policy: bool = True
    enable_notification: bool = True


class DetectionPipeline:
    """
    Detection pipeline that processes frames from CameraIngestionWorker.
    
    Runs: SCRFD detection -> Tracking -> Association -> Identity -> Crossing -> Attendance -> Policy
    Emits: DetectionSnapshot events via health monitor callback
    """
    
    def __init__(
        self,
        config: DetectionPipelineConfig,
        health_event_callback: Optional[Callable] = None,
        annotated_publisher: Optional[Any] = None,
    ):
        self.config = config
        self.camera_id = config.camera_id
        self._health_event_callback = health_event_callback
        self._annotated_publisher = annotated_publisher
        self._face_detector = None
        self._person_detector = None
        self._tracker_state: List[Any] = []
        self._frame_count = 0
        self._running = False

        # Load geometry config for this camera
        self._geometry = load_geometry_config(self.camera_id)

        # Initialize crossing engine if geometry available
        self._crossing_engine = None
        if self._geometry and config.enable_crossing:
            self._crossing_engine = create_crossing_engine(self._geometry)

        # Initialize downstream attendance pipeline components
        self._raw_event_engine = None
        self._resolver = None
        self._attendance_repo = None
        self._policy_engine = None

        if config.enable_attendance:
            self._raw_event_engine = create_raw_event_engine()
            self._resolver = create_repeated_in_out_resolver()
            self._attendance_repo = create_attendance_repository()

        if config.enable_policy:
            # Policy engine requires timetable, calendar, daily_resolver, attendance_engine
            # These will be initialized lazily when needed
            pass

    def start(self) -> bool:
        """Initialize detectors and start pipeline."""
        try:
            # Create face detector (SCRFD)
            self._face_detector = get_detector(
                model_id="scrfd",
                confidence_threshold=self.config.confidence_threshold,
                nms_threshold=self.config.nms_threshold,
            )

            # Create person detector (YOLO) with fallback allowed
            self._person_detector = get_person_detector(
                model_id="yolo_person",
                confidence_threshold=self.config.confidence_threshold,
                allow_fallback=True,
            )

            # Initialize tracker
            if self.config.tracker_config is None:
                self.config.tracker_config = TrackerConfig()

            # Initialize association
            if self.config.association_config is None:
                self.config.association_config = AssociationConfig()

            self._running = True
            logger.info(f"DetectionPipeline started for {self.camera_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to start DetectionPipeline for {self.camera_id}: {e}")
            return False

    def stop(self) -> None:
        """Stop the pipeline."""
        self._running = False
        if self._face_detector:
            try:
                self._face_detector.close()
            except Exception:
                pass
            self._face_detector = None
        if self._person_detector:
            try:
                self._person_detector.cleanup()
            except Exception:
                pass
            self._person_detector = None
        # Preserve per-camera isolation: drop tracker state on stop
        self._tracker_state = []
        logger.info(f"DetectionPipeline stopped for {self.camera_id}")
    
    def process_frame(self, frame: CanonicalFrame) -> None:
        """Process a single frame through the detection pipeline."""
        # Optional forensic instrumentation (gracefully skip if not available)
        try:
            from artifacts.phase8_remediation.deep_forensic_instrument import capture_canonical_frame, log_marker
            log_marker(f"PIPELINE_PROCESS_FRAME_CAMERA={self.camera_id} FRAME_TYPE={type(frame).__name__} FRAME_ID={id(frame)} DATA_TYPE={type(frame.data).__name__} DATA_ID={id(frame.data)}")
            if isinstance(frame.data, dict):
                log_marker(f"PIPELINE_DICT_KEYS={list(frame.data.keys())}")
            capture_canonical_frame(frame, label="PIPELINE_PROCESS")
        except ImportError:
            pass  # Forensic instrumentation not available
        if not self._running or not self._face_detector or not self._person_detector:
            return

        self._frame_count += 1

        try:
            # Update inference active status in health monitor
            monitor = get_shared_health_monitor()
            monitor.set_inference_active(self.camera_id, True)

            start_time = time.time()

            # 1. Person detection (YOLO with face-based fallback) - receives
            #    the CanonicalFrame so that the detector can read frame.metadata
            #    for ORIG dimensions and produce ORIGINAL_FRAME-space bboxes.
            # GPU PATH: Pass frame directly to detector for GPU preprocessing
            person_detections: List[PersonDetection] = self._person_detector.detect(frame)

            # 2. Face detection (SCRFD) - same CanonicalFrame contract.
            # GPU PATH: Pass frame directly to detector for GPU preprocessing
            face_detections = self._face_detector.detect(frame)

            # If the face-based fallback is in use, derive person bboxes
            # from each face detection so that the canonical
            # person -> association -> tracking contract is satisfied.
            if not person_detections and self._person_detector.model_id == "face_based_person_fallback":
                person_detections = self._derive_person_from_faces(
                    face_detections, frame
                )

            # 3. Association (person ↔ face) - canonical, ORIGINAL_FRAME space.
            if self.config.association_config is None:
                self.config.association_config = AssociationConfig()
            association_result: AssociationResult = associate_detections(
                person_detections=list(person_detections),
                face_detections=list(face_detections),
                frame=frame,
                config=self.config.association_config,
            )

            # 4. Tracking - must be called with the exact 6-argument
            #    signature so the metadata-bearing CanonicalFrame reaches
            #    track_frame.
            tracking_result = None
            if self.config.tracker_config:
                tracking_result = track_frame(
                    list(person_detections),
                    list(face_detections),
                    association_result,
                    frame,
                    self._tracker_state or [],
                    self.config.tracker_config,
                )
                # Per-camera isolation: tracker state is per-DetectionPipeline
                self._tracker_state = list(tracking_result.tracks)

            # 5. Process crossing events if crossing engine is available
            crossing_events = []
            if self._crossing_engine and tracking_result:
                # Process only active tracks
                active_tracks = [t for t in tracking_result.tracks if t.is_active]
                for track in active_tracks:
                    events = self._crossing_engine.process_track(
                        track=track,
                        frame_index=self._frame_count,
                        timestamp=frame.metadata.timestamp,
                        global_observation_id=getattr(track, 'global_observation_id', None),
                    )
                    crossing_events.extend(events)

            # Feed crossing events into attendance pipeline
            if crossing_events and self._raw_event_engine and self._resolver and self._attendance_repo:
                # Convert crossing events to raw events
                raw_results = self._raw_event_engine.process_crossing_events(crossing_events)
                raw_events = [r.event for r in raw_results if r.success and r.event]

                if raw_events:
                    # Resolve to transitions
                    resolution_result = self._resolver.resolve_events(raw_events)

                    # Persist to attendance repository
                    persistence_result = self._attendance_repo.persist_resolution_result(resolution_result)

                    logger.debug(
                        f"{self.camera_id}: {len(crossing_events)} crossing events -> "
                        f"{len(raw_events)} raw events -> "
                        f"{resolution_result.accepted_transitions} transitions -> "
                        f"{persistence_result.transitions_persisted} persisted"
                    )

            # Build detection overlay items (in ORIGINAL_FRAME coordinates).
            # Use face detections for overlay (these are the visible identities).
            overlay_items = self._build_overlay_items(
                person_detections=list(person_detections),
                face_detections=list(face_detections),
                tracks=list(tracking_result.tracks) if tracking_result else [],
                frame=frame,
            )

            # Build geometry overlays (lines/regions) in ORIGINAL_FRAME coordinates
            lines, regions = self._build_geometry_overlays(frame)

            # Emit DetectionSnapshot event if callback available
            if self._health_event_callback and self.config.emit_detection_events:
                # Convert crossing events to dict format
                crossing_events_dict = [event.to_dict() for event in crossing_events]
                
                event = create_detection_snapshot_event(
                    event_id=str(uuid.uuid4())[:8],
                    camera_id=self.camera_id,
                    frame_index=self._frame_count,
                    timestamp=frame.metadata.timestamp,
                    frame_width=frame.width,
                    frame_height=frame.height,
                    detections=overlay_items,
                    lines=lines,
                    regions=regions,
                    crossing_events=crossing_events_dict,
                )
                self._health_event_callback(event)

            # Phase 44.X.4 — AI-Annotated Video Output.
            # Submit the canonical frame + the SAME overlay items we just
            # emitted to the DetectionSnapshot event. The publisher draws
            # them onto a copy of frame.data and pushes H.264 to MediaMTX.
            # We never re-run inference, never modify frame.data, and
            # never alter the existing detection / tracking results.
            if self._annotated_publisher is not None and frame.data is not None:
                try:
                    # Ensure we pass GPUFrameContract to publisher for GPU-native path
                    from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract
                    if isinstance(frame.data, GPUFrameContract):
                        self._annotated_publisher.submit(
                            frame_data=frame.data,
                            detections=overlay_items,
                            lines=lines,
                            regions=regions,
                        )
                    else:
                        logger.warning(
                            "%s: annotated publisher skipped - frame.data is not GPUFrameContract (type=%s)",
                            self.camera_id,
                            type(frame.data).__name__,
                        )
                except Exception as pub_err:  # noqa: BLE001
                    logger.warning(
                        "%s: annotated publisher submit failed: %s",
                        self.camera_id,
                        pub_err,
                    )

            inference_time_ms = (time.time() - start_time) * 1000
            logger.debug(f"{self.camera_id}: Frame {self._frame_count} processed in {inference_time_ms:.1f}ms, {len(overlay_items)} detections, {len(crossing_events)} crossing events")

        except Exception as e:
            logger.error(f"DetectionPipeline error for {self.camera_id}: {e}")
            monitor = get_shared_health_monitor()
            monitor.update_error(self.camera_id, str(e))
        finally:
            monitor.set_inference_active(self.camera_id, False)
    
    def _build_overlay_items(
        self,
        person_detections: List[Any],
        face_detections: List[Any],
        tracks: List[Any],
        frame: CanonicalFrame,
    ) -> List[Dict[str, Any]]:
        """
        Build DetectionOverlayItem list in ORIGINAL_FRAME coordinates.

        Phase 44.X.4-R3.1 contract:
          * Only real tracker outputs may produce "Track" overlays.
          * Each active track produces EXACTLY ONE Track overlay whose
            track_id is the real tracker local_track_id and whose bbox is
            the tracked PERSON bbox in ORIGINAL_FRAME coordinates.
          * Multiple face detections associated with the same track MUST
            NOT produce multiple Track overlays (the track is the unit).
          * Unassociated face detections MUST NOT produce a Track overlay.
            They may be emitted as a clearly distinct face-detection overlay
            (label "Face" / type "face_detection") for debugging, but never
            as a "Track" and never with a synthetic DET-* id.
          * The synthetic `DET-<camera>-<frame>-<idx>` Track-id path is
            REMOVED. Track labels are exclusively real tracker IDs.
          * camera_id / source_id / frame_index / coordinate space and
            camera isolation are preserved.
        """
        overlay_items: List[Dict[str, Any]] = []

        # Real, active tracks are the only source of "Track" overlays.
        active_tracks = [t for t in tracks if t.is_active]

        # Index of face_detection_id -> track for unassociated-face handling.
        face_to_track: Dict[str, Any] = {}
        for track in active_tracks:
            if track.face_detection_id:
                face_to_track[track.face_detection_id] = track

        for track in active_tracks:
            bbox = track.bbox_original_frame  # person bbox, ORIGINAL_FRAME
            overlay_items.append({
                "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                "track_id": track.track_id,
                "person_id": None,
                "label": f"Track {track.track_id}",
                "confidence": float(track.confidence),
                "identity_certainty": "unknown",
                "identity_confidence": 0.0,
            })

        # Optional: surface unassociated face detections as a clearly
        # distinct, NON-Track overlay so they remain visible for debugging
        # without ever being labeled or typed as a Track.
        for det in face_detections:
            detection_id = getattr(det, "detection_id", None)
            if detection_id and detection_id in face_to_track:
                # Belongs to a real track already emitted above.
                continue
            bbox = det.bbox
            person_id = getattr(det, "person_id", None)
            identity_certainty = getattr(det, "identity_certainty", "unknown")
            identity_confidence = getattr(det, "identity_confidence", 0.0)
            label = f"Person {person_id}" if person_id else "Face"
            overlay_items.append({
                "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                "track_id": None,
                "person_id": person_id,
                "label": label,
                "confidence": float(det.confidence),
                "identity_certainty": identity_certainty,
                "identity_confidence": float(identity_confidence),
            })

        return overlay_items
    
    def _build_geometry_overlays(self, frame: CanonicalFrame) -> tuple:
        """Build LineOverlayItem and RegionOverlayItem from geometry config."""
        lines = []
        regions = []
        
        if not self._geometry:
            return lines, regions
        
        # Build line overlay
        if self._geometry.line:
            line = self._geometry.line
            lines.append({
                "id": f"line-{self.camera_id}",
                "start": {"x": float(line.p1.x), "y": float(line.p1.y)},
                "end": {"x": float(line.p2.x), "y": float(line.p2.y)},
                "label": "Line",
                "direction": line.direction_semantics.value if line.direction_semantics else "side_a_to_b_in",
                "thickness": 2,
                "color": "#00FF00",
            })
        
        # Build region/zone overlay
        if self._geometry.zone:
            zone = self._geometry.zone
            regions.append({
                "id": f"zone-{self.camera_id}",
                "vertices": [
                    {"x": float(v.x), "y": float(v.y)} for v in zone.vertices
                ],
                "label": "Zone",
                "color": "#0000FF",
                "fill_opacity": 0.2,
            })
        
        return lines, regions

    def _derive_person_from_faces(
        self,
        face_detections: List[Any],
        frame: CanonicalFrame,
    ) -> List[PersonDetection]:
        """
        Derive a person bbox for each face detection by expanding the
        face bbox to a person-sized region. Used only when the YOLO
        person model is not available.

        The expansion is deterministic and uses the original frame
        metadata so the person bbox stays in ORIGINAL_FRAME space.
        """
        derived: List[PersonDetection] = []
        orig_w = float(frame.metadata.original_width or frame.width)
        orig_h = float(frame.metadata.original_height or frame.height)

        # Expansion factors chosen for a head-and-shoulders region at 4K
        expand_left = 0.6
        expand_right = 0.6
        expand_top = 1.4
        expand_bottom = 1.2
        min_w = 80.0
        min_h = 160.0

        for face in face_detections:
            fx1, fy1, fx2, fy2 = face.bbox
            face_w = max(1.0, float(fx2 - fx1))
            face_h = max(1.0, float(fy2 - fy1))
            cx = float(fx1 + fx2) / 2.0

            px1 = max(0.0, float(fx1) - face_w * expand_left)
            py1 = max(0.0, float(fy1) - face_h * expand_top)
            px2 = min(orig_w, float(fx2) + face_w * expand_right)
            py2 = min(orig_h, float(fy2) + face_h * expand_bottom)

            if (px2 - px1) < min_w:
                pad = (min_w - (px2 - px1)) / 2.0
                px1 = max(0.0, px1 - pad)
                px2 = min(orig_w, px2 + pad)
            if (py2 - py1) < min_h:
                pad = (min_h - (py2 - py1)) / 2.0
                py1 = max(0.0, py1 - pad)
                py2 = min(orig_h, py2 + pad)

            detection_id = getattr(face, "detection_id", None) or str(uuid.uuid4())[:12]
            derived.append(
                PersonDetection(
                    bbox=(px1, py1, px2, py2),
                    confidence=float(face.confidence),
                    class_id=0,
                    class_name="person",
                    coordinate_space="original_frame",
                    detection_id=f"p_{detection_id}",
                    model_id="face_based_person_fallback",
                    model_sha256="face_based_fallback_sha256_placeholder",
                    frame_index=frame.metadata.frame_index,
                    source_id=frame.metadata.source_id,
                    provenance=None,
                )
            )
        return derived


def create_detection_pipeline(
    camera_id: str,
    health_event_callback: Optional[Callable] = None,
    confidence_threshold: float = 0.5,
    nms_threshold: float = 0.4,
    annotated_publisher: Optional[Any] = None,
) -> DetectionPipeline:
    """Factory function to create a DetectionPipeline for a camera."""
    config = DetectionPipelineConfig(
        camera_id=camera_id,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
    )
    return DetectionPipeline(
        config,
        health_event_callback=health_event_callback,
        annotated_publisher=annotated_publisher,
    )