"""
Phase 23 — Factory functions for Raw IN/OUT Event Engine.

Provides convenient entry points for creating and configuring the engine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.geometry.crossing import CrossingEngine, CrossingEvent, create_crossing_engine
from app.geometry.contract import CameraGeometryConfig
from app.in_out.contract import RawInOutEvent, RawEventCreationResult
from app.in_out.raw_event import RawEventEngine, create_raw_event_engine


def create_raw_event_engine_from_crossing_engine(
    crossing_engine: CrossingEngine,
) -> RawEventEngine:
    """
    Create a RawEventEngine that shares the same configuration as a CrossingEngine.
    
    This is a convenience function for Phase 22 integration.
    """
    return create_raw_event_engine()


def process_crossing_events_to_raw(
    crossing_events: List[CrossingEvent],
    engine: Optional[RawEventEngine] = None,
) -> List[RawEventCreationResult]:
    """
    Convenience function to process a list of CrossingEvents into RawInOutEvents.
    
    Args:
        crossing_events: List of CrossingEvents from Phase 22
        engine: Optional existing RawEventEngine (creates new if None)
        
    Returns:
        List of RawEventCreationResult
    """
    if engine is None:
        engine = create_raw_event_engine()
    
    return engine.process_crossing_events(crossing_events)


def create_raw_events_from_crossing_engine(
    crossing_engine: CrossingEngine,
    raw_engine: Optional[RawEventEngine] = None,
) -> List[RawInOutEvent]:
    """
    Extract all CrossingEvents from a CrossingEngine and convert to RawInOutEvents.
    
    Args:
        crossing_engine: Phase 22 CrossingEngine with processed events
        raw_engine: Optional existing RawEventEngine
        
    Returns:
        List of successfully created RawInOutEvents
    """
    if raw_engine is None:
        raw_engine = create_raw_event_engine()
    
    crossing_events = crossing_engine.get_events()
    results = raw_engine.process_crossing_events(crossing_events)
    
    return [r.event for r in results if r.success and r.event]


def create_integrated_pipeline(
    geometry_config: CameraGeometryConfig,
) -> tuple[CrossingEngine, RawEventEngine]:
    """
    Create an integrated Phase 22 + Phase 23 pipeline.
    
    Returns:
        Tuple of (CrossingEngine, RawEventEngine)
    """
    crossing_engine = create_crossing_engine(geometry_config)
    raw_engine = create_raw_event_engine()
    return crossing_engine, raw_engine


def process_tracks_through_pipeline(
    tracks: List[Any],
    geometry_config: CameraGeometryConfig,
    frame_index: int,
    timestamp: float,
    global_observation_map: Optional[Dict[str, str]] = None,
) -> List[RawInOutEvent]:
    """
    Complete pipeline: tracks -> CrossingEvents -> RawInOutEvents.
    
    This is the main integration point for Phase 22 + Phase 23.
    
    Args:
        tracks: List of Track objects
        geometry_config: Camera geometry configuration
        frame_index: Current frame index
        timestamp: Current timestamp
        global_observation_map: Optional map of track_id -> global_observation_id
        
    Returns:
        List of RawInOutEvents produced
    """
    from app.geometry.crossing import process_tracks_for_crossings
    
    # Phase 22: Generate CrossingEvents
    crossing_events = process_tracks_for_crossings(
        tracks=tracks,
        geometry_config=geometry_config,
        frame_index=frame_index,
        timestamp=timestamp,
        global_observation_map=global_observation_map,
    )
    
    # Phase 23: Convert to RawInOutEvents
    raw_engine = create_raw_event_engine()
    results = raw_engine.process_crossing_events(crossing_events)
    
    return [r.event for r in results if r.success and r.event]


__all__ = [
    "create_raw_event_engine_from_crossing_engine",
    "process_crossing_events_to_raw",
    "create_raw_events_from_crossing_engine",
    "create_integrated_pipeline",
    "process_tracks_through_pipeline",
]