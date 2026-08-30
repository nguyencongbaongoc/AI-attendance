"""
Phase 23 — Raw IN/OUT Event Engine.

Converts validated Phase 22 CrossingEvents into immutable RawInOutEvents.
Preserves full provenance chain. Does NOT implement resolution logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.geometry.crossing import CrossingEvent, CrossingDirection, CrossingEventType
from app.geometry.contract import GeometryConfigSnapshot
from app.in_out.contract import (
    RawInOutEvent,
    RawEventCreationResult,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
    generate_deterministic_event_id,
    validate_crossing_event_for_raw_creation,
)


def map_crossing_direction(direction: CrossingDirection) -> RawEventDirection:
    """Map Phase 22 CrossingDirection to Phase 23 RawEventDirection."""
    if direction == CrossingDirection.IN:
        return RawEventDirection.IN
    elif direction == CrossingDirection.OUT:
        return RawEventDirection.OUT
    else:
        # Should not happen with valid CrossingEvent
        return RawEventDirection.IN


def map_crossing_event_type(event_type: CrossingEventType) -> RawEventType:
    """Map Phase 22 CrossingEventType to Phase 23 RawEventType."""
    mapping = {
        CrossingEventType.LINE_CROSSING: RawEventType.LINE_CROSSING,
        CrossingEventType.ZONE_ENTRY: RawEventType.ZONE_ENTRY,
        CrossingEventType.ZONE_EXIT: RawEventType.ZONE_EXIT,
    }
    return mapping.get(event_type, RawEventType.LINE_CROSSING)


def extract_identity_info(crossing_event: CrossingEvent) -> Dict[str, Any]:
    """
    Extract identity information from CrossingEvent.
    
    Preserves whatever identity evidence is available upstream.
    Does NOT force an identity - UNKNOWN/AMBIGUOUS/INSUFFICIENT are valid.
    """
    # CrossingEvent doesn't directly contain identity info,
    # but it may have global_observation_id which links to Phase 21
    # For now, we preserve the reference and mark as UNKNOWN
    # Future integration can enrich this from GlobalObservation
    
    return {
        "identity_certainty": IdentityCertainty.UNKNOWN,
        "identity_candidate": None,
        "identity_confidence": 0.0,
        "identity_evidence_ref": crossing_event.global_observation_id,
    }


def create_raw_in_out_event(crossing_event: CrossingEvent) -> RawEventCreationResult:
    """
    Create a RawInOutEvent from a validated CrossingEvent.
    
    This is the core Phase 23 conversion function.
    Rejects invalid inputs. Preserves all provenance.
    """
    # Validate input
    validation_error = validate_crossing_event_for_raw_creation(crossing_event)
    if validation_error:
        return RawEventCreationResult.failure_result(
            error=validation_error,
            rejection_reason="invalid_crossing_event"
        )
    
    # Extract geometry info from snapshot
    geom_snapshot = crossing_event.geometry_config
    geometry_id = geom_snapshot.config_hash  # Use config_hash as geometry_id
    geometry_version = geom_snapshot.version
    geometry_config_hash = geom_snapshot.config_hash
    
    # Generate deterministic event ID
    event_id = generate_deterministic_event_id(
        camera_id=crossing_event.camera_id,
        local_track_id=crossing_event.local_track_id,
        source_crossing_event_id=crossing_event.event_id,
        geometry_version=geometry_version,
        geometry_config_hash=geometry_config_hash,
    )
    
    # Map direction (preserve exactly from Phase 22)
    direction = map_crossing_direction(crossing_event.direction)
    
    # Map event type
    event_type = map_crossing_event_type(crossing_event.event_type)
    
    # Extract identity info
    identity_info = extract_identity_info(crossing_event)
    
    # Convert trajectory points to serializable format
    trajectory_points = []
    for tp in crossing_event.trajectory_points:
        trajectory_points.append({
            "track_id": tp.track_id,
            "frame_index": tp.frame_index,
            "timestamp": tp.timestamp,
            "position": tp.position.to_dict(),
            "bbox": list(tp.bbox),
            "camera_id": tp.camera_id,
            "global_observation_id": tp.global_observation_id,
        })
    
    # Build RawInOutEvent
    raw_event = RawInOutEvent(
        event_id=event_id,
        camera_id=crossing_event.camera_id,
        geometry_id=geometry_id,
        geometry_version=geometry_version,
        geometry_config_hash=geometry_config_hash,
        local_track_id=crossing_event.local_track_id,
        global_observation_id=crossing_event.global_observation_id,
        event_type=event_type,
        direction=direction,
        crossing_point_x=crossing_event.crossing_point.x,
        crossing_point_y=crossing_event.crossing_point.y,
        crossing_timestamp=crossing_event.crossing_timestamp,
        crossing_frame_index=crossing_event.current_frame_index,
        previous_position_x=crossing_event.previous_position.x if crossing_event.previous_position else None,
        previous_position_y=crossing_event.previous_position.y if crossing_event.previous_position else None,
        current_position_x=crossing_event.current_position.x if crossing_event.current_position else None,
        current_position_y=crossing_event.current_position.y if crossing_event.current_position else None,
        previous_frame_index=crossing_event.previous_frame_index,
        current_frame_index=crossing_event.current_frame_index,
        previous_timestamp=crossing_event.previous_timestamp,
        current_timestamp=crossing_event.current_timestamp,
        crossing_distance=crossing_event.crossing_distance,
        side_transition=crossing_event.side_transition,
        identity_certainty=identity_info["identity_certainty"],
        identity_candidate=identity_info["identity_candidate"],
        identity_confidence=identity_info["identity_confidence"],
        identity_evidence_ref=identity_info["identity_evidence_ref"],
        source_crossing_event_id=crossing_event.event_id,
        trajectory_points=trajectory_points,
        config_snapshot=crossing_event.config_snapshot,
        event_schema_version="1.0",
        created_at=crossing_event.created_at,  # Preserve original creation time
    )
    
    return RawEventCreationResult.success_result(raw_event)


@dataclass
class RawEventEngine:
    """
    Raw IN/OUT Event Engine.
    
    Processes CrossingEvents and produces RawInOutEvents.
    Maintains idempotency through deterministic event IDs.
    Does NOT implement attendance state or resolution logic.
    """
    
    def __init__(self):
        self._processed_event_ids: set = set()  # For idempotency tracking
        self._events: List[RawInOutEvent] = []
        self._stats = {
            "total_processed": 0,
            "successful": 0,
            "rejected": 0,
            "duplicates": 0,
        }
    
    def process_crossing_event(self, crossing_event: CrossingEvent) -> RawEventCreationResult:
        """
        Process a single CrossingEvent into a RawInOutEvent.
        
        Idempotent: same CrossingEvent always produces same RawInOutEvent.
        """
        self._stats["total_processed"] += 1
        
        # Validate
        validation_error = validate_crossing_event_for_raw_creation(crossing_event)
        if validation_error:
            self._stats["rejected"] += 1
            return RawEventCreationResult.failure_result(
                error=validation_error,
                rejection_reason="invalid_crossing_event"
            )
        
        # Generate deterministic event ID for idempotency check
        geom_snapshot = crossing_event.geometry_config
        event_id = generate_deterministic_event_id(
            camera_id=crossing_event.camera_id,
            local_track_id=crossing_event.local_track_id,
            source_crossing_event_id=crossing_event.event_id,
            geometry_version=geom_snapshot.version,
            geometry_config_hash=geom_snapshot.config_hash,
        )
        
        # Check for duplicate
        if event_id in self._processed_event_ids:
            self._stats["duplicates"] += 1
            # Return existing event (idempotent)
            existing = next((e for e in self._events if e.event_id == event_id), None)
            if existing:
                return RawEventCreationResult.success_result(existing)
            # Should not happen, but fallback
            return RawEventCreationResult.failure_result(
                error="Duplicate event ID but event not found",
                rejection_reason="internal_error"
            )
        
        # Create the raw event
        result = create_raw_in_out_event(crossing_event)
        
        if result.success and result.event:
            self._processed_event_ids.add(event_id)
            self._events.append(result.event)
            self._stats["successful"] += 1
        else:
            self._stats["rejected"] += 1
        
        return result
    
    def process_crossing_events(self, crossing_events: List[CrossingEvent]) -> List[RawEventCreationResult]:
        """Process multiple CrossingEvents."""
        return [self.process_crossing_event(ce) for ce in crossing_events]
    
    def get_events(self) -> List[RawInOutEvent]:
        """Get all successfully created raw events (chronological order)."""
        # Sort by crossing_timestamp for deterministic ordering
        return sorted(self._events, key=lambda e: (e.crossing_timestamp, e.event_id))
    
    def get_events_by_camera(self, camera_id: str) -> List[RawInOutEvent]:
        """Get raw events for a specific camera."""
        return [e for e in self.get_events() if e.camera_id == camera_id]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return dict(self._stats)
    
    def clear(self) -> None:
        """Clear all state (for testing)."""
        self._processed_event_ids.clear()
        self._events.clear()
        for key in self._stats:
            self._stats[key] = 0
    
    def has_event(self, event_id: str) -> bool:
        """Check if an event ID has been processed."""
        return event_id in self._processed_event_ids


def create_raw_event_engine() -> RawEventEngine:
    """Factory function to create a RawEventEngine."""
    return RawEventEngine()