"""
Phase 27 — Annotated Dual-Camera Replay Pipeline.

Integrates Phase 20 replay infrastructure with annotation contracts.
Provides deterministic offline forensic replay for CAM1/CAM2.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.data.frame import CanonicalFrame
from app.replay.clock import ReplayTimestamp
from app.replay.scheduler import ReplayScheduler, ReplaySchedulerConfig, create_scheduler
from app.replay.source import ReplaySource, ReplaySourceConfig
from app.replay.annotation import (
    AnnotationFrame,
    PersonAnnotation,
    FaceAnnotation,
    EventAnnotation,
    AttendanceAnnotation,
    GlobalObservationReference,
    AnnotationProvenance,
    BoundingBox,
    IdentityDisplayState,
    AttendanceDisplayState,
    EventDisplayType,
    generate_annotation_frame_id,
)
from app.replay.appearance import (
    AppearanceRecord,
    PersonSearchResult,
    generate_appearance_id,
)
from app.replay.fusion import (
    GlobalObservation,
    LocalObservationRef,
    AssociationState,
    CrossCameraFusionEngine,
    FusionConfig,
    DEFAULT_FUSION_CONFIG,
    build_local_observation_ref,
)
from app.in_out.resolver_contract import ResolvedTransition
from app.attendance.contract import AttendanceRecord
from app.attendance.engine import AttendanceDecision

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnnotatedReplayConfig:
    """Configuration for annotated replay."""
    scheduler_config: ReplaySchedulerConfig = field(default_factory=ReplaySchedulerConfig)
    fusion_config: FusionConfig = field(default_factory=lambda: DEFAULT_FUSION_CONFIG)
    include_person_annotations: bool = True
    include_face_annotations: bool = True
    include_event_annotations: bool = True
    include_attendance_annotations: bool = True
    include_global_observation_references: bool = True
    build_appearance_index: bool = True
    output_directory: str = "replay_output"
    save_annotation_frames: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheduler_config": self.scheduler_config.to_dict(),
            "fusion_config": self.fusion_config.to_dict(),
            "include_person_annotations": self.include_person_annotations,
            "include_face_annotations": self.include_face_annotations,
            "include_event_annotations": self.include_event_annotations,
            "include_attendance_annotations": self.include_attendance_annotations,
            "include_global_observation_references": self.include_global_observation_references,
            "build_appearance_index": self.build_appearance_index,
            "output_directory": self.output_directory,
            "save_annotation_frames": self.save_annotation_frames,
        }


@dataclass
class AnnotatedReplayState:
    """Runtime state for annotated replay."""
    frames_processed: int = 0
    frames_annotated: int = 0
    camera_tracks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    global_observations: List[GlobalObservation] = field(default_factory=list)
    appearance_index: Dict[str, List[AppearanceRecord]] = field(default_factory=dict)
    track_appearances: Dict[str, AppearanceRecord] = field(default_factory=dict)
    crossing_events: Dict[str, Any] = field(default_factory=dict)
    raw_events: Dict[str, Any] = field(default_factory=dict)
    resolved_transitions: Dict[str, ResolvedTransition] = field(default_factory=dict)
    attendance_decisions: Dict[str, AttendanceDecision] = field(default_factory=dict)
    attendance_records: Dict[str, AttendanceRecord] = field(default_factory=dict)
    annotation_frames: List[AnnotationFrame] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class AnnotatedReplayPipeline:
    """
    Annotated dual-camera replay pipeline.
    
    Integrates:
    - Phase 20: ReplayScheduler (source video -> frames)
    - Phase 21: CrossCameraFusionEngine (local tracks -> GlobalObservation)
    - Phase 22/23/24: Event references (crossing, raw IN/OUT, resolved transitions)
    - Phase 25: AttendanceRecord (persistence)
    - Phase 26: AttendanceDecision (decision engine)
    
    Produces:
    - AnnotationFrame (serializable annotated frames)
    - AppearanceRecord (person appearance index)
    - Full provenance chain
    """
    
    def __init__(
        self,
        source_configs: List[ReplaySourceConfig],
        config: Optional[AnnotatedReplayConfig] = None,
        crossing_events: Optional[Dict[str, Any]] = None,
        raw_events: Optional[Dict[str, Any]] = None,
        resolved_transitions: Optional[Dict[str, ResolvedTransition]] = None,
        attendance_decisions: Optional[Dict[str, AttendanceDecision]] = None,
        attendance_records: Optional[Dict[str, AttendanceRecord]] = None,
    ):
        self.source_configs = source_configs
        self.config = config or AnnotatedReplayConfig()
        
        self.crossing_events = crossing_events or {}
        self.raw_events = raw_events or {}
        self.resolved_transitions = resolved_transitions or {}
        self.attendance_decisions = attendance_decisions or {}
        self.attendance_records = attendance_records or {}
        
        self.scheduler = create_scheduler(source_configs, self.config.scheduler_config)
        self.fusion_engine = CrossCameraFusionEngine(self.config.fusion_config)
        self.state = AnnotatedReplayState()
        
        self.output_dir = Path(self.config.output_directory)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"AnnotatedReplayPipeline initialized with {len(source_configs)} sources")
    
    def run(self) -> AnnotatedReplayState:
        logger.info("Starting annotated replay...")
        
        for frame in self.scheduler:
            self._process_frame(frame)
        
        if self.config.fusion_config:
            global_observations = self.fusion_engine.associate_observations()
            self.state.global_observations.extend(global_observations)
            logger.info(f"Produced {len(global_observations)} global observations")
        
        if self.config.save_annotation_frames:
            self._save_annotation_frames()
        
        logger.info(
            f"Annotated replay complete: "
            f"{self.state.frames_processed} frames processed, "
            f"{self.state.frames_annotated} frames annotated, "
            f"{len(self.state.global_observations)} global observations, "
            f"{len(self.state.appearance_index)} persons indexed"
        )
        
        return self.state
    
    def _process_frame(self, frame: CanonicalFrame) -> None:
        self.state.frames_processed += 1
        
        camera_id = frame.metadata.extra.get("camera_id", "unknown")
        frame_index = frame.metadata.frame_index
        timestamp = frame.metadata.timestamp or 0.0
        timestamp_source = frame.metadata.extra.get("replay_timestamp", {}).get("source", "unknown")
        source_video_id = frame.metadata.extra.get("source_video_id", f"{camera_id}_video")
        
        annotation_frame = self._build_annotation_frame(
            frame=frame,
            camera_id=camera_id,
            frame_index=frame_index,
            timestamp=timestamp,
            timestamp_source=timestamp_source,
            source_video_id=source_video_id,
        )
        
        if annotation_frame:
            self.state.frames_annotated += 1
            self.state.annotation_frames.append(annotation_frame)
            
            if self.config.build_appearance_index:
                self._update_appearance_index(annotation_frame)
            
            if self.config.fusion_config:
                self._feed_fusion_engine(annotation_frame)
    
    def _build_annotation_frame(
        self,
        frame: CanonicalFrame,
        camera_id: str,
        frame_index: int,
        timestamp: float,
        timestamp_source: str,
        source_video_id: str,
    ) -> Optional[AnnotationFrame]:
        
        person_annotations = []
        face_annotations = []
        event_annotations = []
        attendance_annotations = []
        global_observation_references = []
        
        detections = frame.metadata.extra.get("detections", [])
        person_crops = frame.metadata.extra.get("person_crops", [])
        face_crops = frame.metadata.extra.get("face_crops", [])
        quality_results = frame.metadata.extra.get("quality_results", [])
        match_results = frame.metadata.extra.get("match_results", [])
        temporal_hypotheses = frame.metadata.extra.get("temporal_hypotheses", [])
        
        if self.config.include_person_annotations:
            for i, detection in enumerate(detections):
                bbox = detection.bbox
                person_bbox = BoundingBox(
                    x=bbox[0], y=bbox[1],
                    width=bbox[2] - bbox[0], height=bbox[3] - bbox[1]
                )
                
                local_track_id = f"track_{detection.detection_id}"
                
                global_obs_id = None
                for go in self.state.global_observations:
                    for obs in go.observations:
                        if obs.camera_id == camera_id and obs.local_track_id == local_track_id:
                            global_obs_id = go.global_observation_id
                            break
                
                identity_candidate = None
                identity_certainty = IdentityDisplayState.UNKNOWN
                identity_confidence = 0.0
                similarity = None
                
                if i < len(match_results) and match_results[i]:
                    match = match_results[i]
                    if hasattr(match, 'candidate_identity') and match.candidate_identity:
                        identity_candidate = match.candidate_identity
                        identity_confidence = getattr(match, 'similarity', 0.0)
                        similarity = identity_confidence
                        if identity_confidence >= 0.8:
                            identity_certainty = IdentityDisplayState.KNOWN
                        elif identity_confidence >= 0.5:
                            identity_certainty = IdentityDisplayState.AMBIGUOUS
                        else:
                            identity_certainty = IdentityDisplayState.INSUFFICIENT
                    else:
                        identity_certainty = IdentityDisplayState.UNKNOWN
                
                face_bbox = None
                face_quality_class = None
                face_quality_score = None
                face_quality_reasons = ()
                
                if i < len(face_crops) and face_crops[i]:
                    face_crop = face_crops[i]
                    if hasattr(face_crop, 'bbox_in_original'):
                        fb = face_crop.bbox_in_original
                        face_bbox = BoundingBox(x=fb[0], y=fb[1], width=fb[2]-fb[0], height=fb[3]-fb[1])
                
                if i < len(quality_results) and quality_results[i]:
                    qr = quality_results[i]
                    face_quality_class = getattr(qr, 'quality_class', None)
                    if face_quality_class and hasattr(face_quality_class, 'value'):
                        face_quality_class = face_quality_class.value
                    face_quality_score = getattr(qr, 'quality_score', None)
                    face_quality_reasons = tuple(getattr(qr, 'reasons', []))
                
                pose_state = None
                pose_angles = None
                if i < len(temporal_hypotheses) and temporal_hypotheses[i]:
                    hyp = temporal_hypotheses[i]
                    pose_state = getattr(hyp, 'pose_state', None)
                    pose_angles = getattr(hyp, 'pose_angles', None)
                
                attendance_state = None
                attendance_decision_id = None
                for decision in self.attendance_decisions.values():
                    if (decision.camera_id == camera_id and 
                        decision.local_track_id == local_track_id and
                        abs(decision.event_timestamp - timestamp) < 1.0):
                        attendance_state = AttendanceDisplayState(decision.new_attendance_state)
                        attendance_decision_id = decision.decision_id
                        break
                
                person_ann = PersonAnnotation(
                    bbox=person_bbox,
                    local_track_id=local_track_id,
                    global_observation_id=global_obs_id,
                    identity_candidate=identity_candidate,
                    identity_certainty=identity_certainty,
                    identity_confidence=identity_confidence,
                    similarity=similarity,
                    face_bbox=face_bbox,
                    face_quality_class=face_quality_class,
                    face_quality_score=face_quality_score,
                    face_quality_reasons=face_quality_reasons,
                    pose_state=pose_state,
                    pose_angles=pose_angles,
                    attendance_state=attendance_state,
                    attendance_decision_id=attendance_decision_id,
                    detection_id=detection.detection_id,
                    face_crop_id=f"face_{detection.detection_id}" if face_bbox else None,
                    track_provenance={"camera_id": camera_id, "frame_index": frame_index},
                )
                person_annotations.append(person_ann)
        
        if self.config.include_face_annotations:
            for i, face_crop in enumerate(face_crops):
                if not face_crop:
                    continue
                if hasattr(face_crop, 'bbox_in_original'):
                    fb = face_crop.bbox_in_original
                    face_bbox = BoundingBox(x=fb[0], y=fb[1], width=fb[2]-fb[0], height=fb[3]-fb[1])
                else:
                    continue
                
                detection = detections[i] if i < len(detections) else None
                quality_result = quality_results[i] if i < len(quality_results) else None
                match_result = match_results[i] if i < len(match_results) else None
                
                face_ann = FaceAnnotation(
                    bbox=face_bbox,
                    quality_class=quality_result.quality_class.value if quality_result and hasattr(quality_result.quality_class, 'value') else None,
                    quality_score=quality_result.quality_score if quality_result else None,
                    quality_reasons=tuple(quality_result.reasons) if quality_result and hasattr(quality_result, 'reasons') else (),
                    pose_state=None,
                    pose_angles=None,
                    identity_similarity=match_result.similarity if match_result and hasattr(match_result, 'similarity') else None,
                    identity_candidate=match_result.candidate_identity if match_result and hasattr(match_result, 'candidate_identity') else None,
                    detection_id=detection.detection_id if detection else None,
                    face_crop_id=f"face_{detection.detection_id}" if detection else None,
                    local_track_id=f"track_{detection.detection_id}" if detection else None,
                    global_observation_id=None,
                )
                face_annotations.append(face_ann)
        
        if self.config.include_event_annotations:
            for event_id, event in self.crossing_events.items():
                if (event.camera_id == camera_id and abs(event.timestamp - timestamp) < 0.5):
                    event_ann = EventAnnotation(
                        event_type=EventDisplayType.CROSSING,
                        event_id=event_id,
                        direction=event.direction.value if hasattr(event.direction, 'value') else str(event.direction),
                        timestamp=event.timestamp,
                        camera_id=camera_id,
                        local_track_id=event.local_track_id,
                        global_observation_id=event.global_observation_id,
                        crossing_event_id=event_id,
                        crossing_direction=event.direction.value if hasattr(event.direction, 'value') else str(event.direction),
                        geometry_version=event.geometry_version,
                        geometry_config_hash=event.geometry_config_hash,
                    )
                    event_annotations.append(event_ann)
            
            for event_id, event in self.raw_events.items():
                if (event.camera_id == camera_id and abs(event.timestamp - timestamp) < 0.5):
                    event_ann = EventAnnotation(
                        event_type=EventDisplayType.IN if event.direction.value == "in" else EventDisplayType.OUT,
                        event_id=event_id,
                        direction=event.direction.value,
                        timestamp=event.timestamp,
                        camera_id=camera_id,
                        local_track_id=event.local_track_id,
                        global_observation_id=event.global_observation_id,
                        raw_event_id=event_id,
                    )
                    event_annotations.append(event_ann)
            
            for res_id, resolution in self.resolved_transitions.items():
                if (resolution.camera_id == camera_id and abs(resolution.source_timestamp - timestamp) < 0.5):
                    event_ann = EventAnnotation(
                        event_type=EventDisplayType.IN if resolution.direction == "in" else EventDisplayType.OUT,
                        event_id=res_id,
                        direction=resolution.direction,
                        timestamp=resolution.source_timestamp,
                        camera_id=camera_id,
                        local_track_id=resolution.local_track_id,
                        global_observation_id=resolution.global_observation_id,
                        resolution_id=res_id,
                        previous_state=resolution.previous_state.value if hasattr(resolution.previous_state, 'value') else str(resolution.previous_state),
                        new_state=resolution.new_state.value if hasattr(resolution.new_state, 'value') else str(resolution.new_state),
                        resolver_version=resolution.resolver_version,
                        resolver_config_hash=resolution.resolver_config_hash,
                    )
                    event_annotations.append(event_ann)
        
        if self.config.include_attendance_annotations:
            for decision_id, decision in self.attendance_decisions.items():
                if (decision.camera_id == camera_id and abs(decision.event_timestamp - timestamp) < 0.5):
                    att_ann = AttendanceAnnotation(
                        attendance_state=AttendanceDisplayState(decision.new_attendance_state),
                        decision_reason=decision.decision_reason.value if hasattr(decision.decision_reason, 'value') else str(decision.decision_reason),
                        person_identity=decision.identity_candidate,
                        identity_certainty=IdentityDisplayState(decision.identity_certainty),
                        identity_confidence=decision.identity_confidence,
                        timetable_id=decision.timetable_id,
                        session_id=decision.session_id,
                        day=decision.day,
                        event_timestamp=decision.event_timestamp,
                        camera_id=decision.camera_id,
                        local_track_id=decision.local_track_id,
                        global_observation_id=decision.global_observation_id,
                        attendance_decision_id=decision.decision_id,
                        attendance_policy_id=decision.attendance_policy_id,
                        attendance_policy_version=decision.attendance_policy_version,
                        previous_attendance_state=decision.previous_attendance_state,
                        new_attendance_state=decision.new_attendance_state,
                    )
                    attendance_annotations.append(att_ann)
        
        if self.config.include_global_observation_references:
            for go in self.state.global_observations:
                relevant = False
                for obs in go.observations:
                    if obs.camera_id == camera_id and abs(obs.timestamp.value - timestamp) < 1.0:
                        relevant = True
                        break
                
                if relevant:
                    go_ref = GlobalObservationReference(
                        global_observation_id=go.global_observation_id,
                        association_state=go.association_state.value,
                        camera_ids=go.camera_ids,
                        local_track_ids=go.local_track_ids,
                        temporal_start=go.temporal_start.value,
                        temporal_end=go.temporal_end.value,
                        temporal_span=go.temporal_span,
                        primary_identity_candidate=go.primary_identity_candidate,
                        identity_confidence=go.identity_confidence,
                        identity_state=go.identity_state.value if go.identity_state else None,
                    )
                    global_observation_references.append(go_ref)
        
        provenance = AnnotationProvenance(
            source_video_id=source_video_id,
            camera_id=camera_id,
            source_frame_index=frame_index,
            source_timestamp=timestamp,
            annotation_schema_version="1.0",
        )
        
        annotation_frame = AnnotationFrame(
            camera_id=camera_id,
            frame_index=frame_index,
            timestamp=timestamp,
            timestamp_source=timestamp_source,
            source_frame_reference=f"{source_video_id}:{frame_index}",
            person_annotations=tuple(person_annotations),
            face_annotations=tuple(face_annotations),
            event_annotations=tuple(event_annotations),
            attendance_annotations=tuple(attendance_annotations),
            global_observation_references=tuple(global_observation_references),
            provenance=provenance,
            annotation_schema_version="1.0",
        )
        
        return annotation_frame
    
    def _feed_fusion_engine(self, annotation_frame: AnnotationFrame) -> None:
        """Feed person annotations to fusion engine for cross-camera association."""
        for person_ann in annotation_frame.person_annotations:
            # Create a minimal frame-like object for build_local_observation_ref
            # We need to create a LocalObservationRef from the person annotation
            from app.replay.fusion import LocalObservationRef
            from app.replay.clock import ReplayTimestamp
            
            obs_ref = LocalObservationRef(
                camera_id=annotation_frame.camera_id,
                local_track_id=person_ann.local_track_id,
                observation_id=f"{annotation_frame.camera_id}_{person_ann.local_track_id}_f{annotation_frame.frame_index}",
                frame_index=annotation_frame.frame_index,
                timestamp=ReplayTimestamp(value=annotation_frame.timestamp, source=annotation_frame.timestamp_source),
                detection_id=person_ann.detection_id,
                face_crop_id=person_ann.face_crop_id,
                quality_class=person_ann.face_quality_class,
                identity_hypothesis=None,
                identity_evidence=None,
            )
            self.fusion_engine.add_observation(obs_ref)
    
    def _update_appearance_index(self, annotation_frame: AnnotationFrame) -> None:
        """Update appearance index from annotation frame."""
        for person_ann in annotation_frame.person_annotations:
            track_key = f"{annotation_frame.camera_id}:{person_ann.local_track_id}"
            
            # Check if we have an existing appearance for this track
            if track_key in self.state.track_appearances:
                # Update end timestamp/frame
                existing = self.state.track_appearances[track_key]
                # Create updated appearance record
                updated = AppearanceRecord(
                    appearance_id=existing.appearance_id,
                    person_id=existing.person_id,
                    identity_certainty=existing.identity_certainty,
                    camera_id=existing.camera_id,
                    local_track_id=existing.local_track_id,
                    global_observation_id=existing.global_observation_id,
                    source_video_id=existing.source_video_id,
                    start_timestamp=existing.start_timestamp,
                    end_timestamp=annotation_frame.timestamp,
                    start_frame=existing.start_frame,
                    end_frame=annotation_frame.frame_index,
                    source_resolution_id=existing.source_resolution_id,
                    attendance_decision_id=existing.attendance_decision_id,
                    provenance=existing.provenance,
                    schema_version=existing.schema_version,
                )
                self.state.track_appearances[track_key] = updated
            else:
                # Create new appearance record
                appearance_id = generate_appearance_id(
                    source_video_id=annotation_frame.provenance.source_video_id,
                    camera_id=annotation_frame.camera_id,
                    local_track_id=person_ann.local_track_id,
                    start_timestamp=annotation_frame.timestamp,
                )
                
                # Determine person_id and identity_certainty
                person_id = person_ann.identity_candidate if person_ann.identity_certainty == IdentityDisplayState.KNOWN else None
                identity_certainty = person_ann.identity_certainty.value
                
                appearance = AppearanceRecord(
                    appearance_id=appearance_id,
                    person_id=person_id,
                    identity_certainty=identity_certainty,
                    camera_id=annotation_frame.camera_id,
                    local_track_id=person_ann.local_track_id,
                    global_observation_id=person_ann.global_observation_id,
                    source_video_id=annotation_frame.provenance.source_video_id,
                    start_timestamp=annotation_frame.timestamp,
                    end_timestamp=annotation_frame.timestamp,
                    start_frame=annotation_frame.frame_index,
                    end_frame=annotation_frame.frame_index,
                    source_resolution_id=None,
                    attendance_decision_id=person_ann.attendance_decision_id,
                    provenance={
                        "first_frame": annotation_frame.frame_index,
                        "first_timestamp": annotation_frame.timestamp,
                        "camera_id": annotation_frame.camera_id,
                    },
                )
                self.state.track_appearances[track_key] = appearance
                
                # Index by person_id if known
                if person_id:
                    if person_id not in self.state.appearance_index:
                        self.state.appearance_index[person_id] = []
                    self.state.appearance_index[person_id].append(appearance)
    
    def _save_annotation_frames(self) -> None:
        """Save annotation frames to JSON files."""
        for i, frame in enumerate(self.state.annotation_frames):
            output_path = self.output_dir / f"annotation_{frame.camera_id}_f{frame.frame_index:06d}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(frame.to_json())
        
        # Also save a summary
        summary_path = self.output_dir / "replay_summary.json"
        summary = {
            "frames_processed": self.state.frames_processed,
            "frames_annotated": self.state.frames_annotated,
            "global_observations": len(self.state.global_observations),
            "persons_indexed": len(self.state.appearance_index),
            "annotation_frames_saved": len(self.state.annotation_frames),
            "global_observations_detail": [go.to_dict() for go in self.state.global_observations],
            "appearance_index": {
                pid: [a.to_dict() for a in apps] 
                for pid, apps in self.state.appearance_index.items()
            },
        }
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(self.state.annotation_frames)} annotation frames to {self.output_dir}")
    
    def search_person_appearances(self, person_id: str) -> PersonSearchResult:
        """Search for all appearances of a person."""
        appearances = self.state.appearance_index.get(person_id, [])
        return PersonSearchResult(person_id=person_id, appearances=tuple(appearances))
    
    def get_appearance_by_track(self, camera_id: str, local_track_id: str) -> Optional[AppearanceRecord]:
        """Get appearance record by camera and local track."""
        track_key = f"{camera_id}:{local_track_id}"
        return self.state.track_appearances.get(track_key)
    
    def get_all_appearances(self) -> List[AppearanceRecord]:
        """Get all appearance records."""
        return list(self.state.track_appearances.values())
    
    def get_annotation_frames(self) -> List[AnnotationFrame]:
        """Get all annotation frames."""
        return list(self.state.annotation_frames)
    
    def get_global_observations(self) -> List[GlobalObservation]:
        """Get all global observations."""
        return list(self.state.global_observations)