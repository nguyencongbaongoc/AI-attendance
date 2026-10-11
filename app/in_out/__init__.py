"""
Phase 23/24 — IN/OUT Event Engine Package.

Phase 23: Raw IN/OUT Event Engine
Canonical flow: Phase 22 CrossingEvent -> Phase 23 Raw IN/OUT Event Engine -> immutable RawInOutEvent
Phase 23 answers: "Did a validated crossing produce an IN or OUT raw event?"

Phase 24: Repeated IN/OUT Resolver
Canonical flow: Phase 23 RawInOutEvent -> Phase 24 RepeatedInOutResolver -> Derived transitions/state
Phase 24 answers: "What is the person's current attendance state after resolving repeated events?"
"""

from app.in_out.contract import (
    RawInOutEvent,
    RawEventCreationResult,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
    generate_deterministic_event_id,
    validate_crossing_event_for_raw_creation,
)

from app.in_out.raw_event import (
    RawEventEngine,
    create_raw_event_engine,
    create_raw_in_out_event,
)

from app.in_out.factory import (
    create_raw_event_engine_from_crossing_engine,
    process_crossing_events_to_raw,
    create_raw_events_from_crossing_engine,
    create_integrated_pipeline,
    process_tracks_through_pipeline,
)

from app.in_out.resolver_config import (
    ResolverConfig,
    InitialOutPolicy,
    OutOfOrderPolicy,
    EqualTimestampPolicy,
    create_default_resolver_config,
    create_strict_resolver_config,
    create_permissive_resolver_config,
)

from app.in_out.resolver_contract import (
    ResolvedTransition,
    TrackResolutionState,
    ResolutionResult,
    DerivedState,
    TransitionType,
    ResolutionStatus,
    generate_resolution_id,
    generate_config_hash,
)

from app.in_out.resolver import (
    RepeatedInOutResolver,
    create_repeated_in_out_resolver,
    resolve_raw_events,
)

__all__ = [
    # Phase 23 Contract
    "RawInOutEvent",
    "RawEventCreationResult",
    "RawEventDirection",
    "RawEventType",
    "IdentityCertainty",
    "generate_deterministic_event_id",
    "validate_crossing_event_for_raw_creation",
    
    # Phase 23 Engine
    "RawEventEngine",
    "create_raw_event_engine",
    "create_raw_in_out_event",
    
    # Phase 23 Factory
    "create_raw_event_engine_from_crossing_engine",
    "process_crossing_events_to_raw",
    "create_raw_events_from_crossing_engine",
    "create_integrated_pipeline",
    "process_tracks_through_pipeline",
    
    # Phase 24 Resolver Config
    "ResolverConfig",
    "InitialOutPolicy",
    "OutOfOrderPolicy",
    "EqualTimestampPolicy",
    "create_default_resolver_config",
    "create_strict_resolver_config",
    "create_permissive_resolver_config",
    
    # Phase 24 Resolver Contract
    "ResolvedTransition",
    "TrackResolutionState",
    "ResolutionResult",
    "DerivedState",
    "TransitionType",
    "ResolutionStatus",
    "generate_resolution_id",
    "generate_config_hash",
    
    # Phase 24 Resolver
    "RepeatedInOutResolver",
    "create_repeated_in_out_resolver",
    "resolve_raw_events",
]

__version__ = "1.0"
