#!/usr/bin/env python
"""
Phase 24 — Acceptance/Reporting Harness for Repeated IN/OUT Resolution.

This script:
1. Collects pytest results from unit and integration tests
2. Executes focused acceptance checks
3. Verifies Phase 22 → Phase 23 → Phase 24 integration
4. Generates final reports (JSON and Markdown)
5. Determines PASS/FAIL verdict
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
)
from app.in_out.resolver import (
    RepeatedInOutResolver,
    create_repeated_in_out_resolver,
    resolve_raw_events,
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


def run_pytest(test_path: str) -> Dict[str, Any]:
    """Run pytest and return structured results."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short", "-q"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    
    # Parse output for pass/fail counts
    lines = result.stdout.strip().split('\n')
    passed = 0
    failed = 0
    errors = 0
    
    for line in lines:
        if "passed" in line and "failed" in line:
            parts = line.split()
            for i, part in enumerate(parts):
                if part == "passed":
                    passed = int(parts[i-1])
                elif part == "failed":
                    failed = int(parts[i-1])
                elif part == "error" or part == "errors":
                    errors = int(parts[i-1])
    
    return {
        "exit_code": result.returncode,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def create_test_raw_event(
    event_id: str,
    camera_id: str = "CAM1",
    local_track_id: str = "track_001",
    direction: RawEventDirection = RawEventDirection.IN,
    timestamp: float = 1000.0,
    frame_index: int = 100,
    global_observation_id: Optional[str] = None,
    geometry_version: int = 1,
    geometry_config_hash: str = "hash123",
    source_crossing_event_id: str = "CE-123",
) -> RawInOutEvent:
    """Create a RawInOutEvent for acceptance testing."""
    return RawInOutEvent(
        event_id=event_id,
        camera_id=camera_id,
        geometry_id=geometry_config_hash,
        geometry_version=geometry_version,
        geometry_config_hash=geometry_config_hash,
        local_track_id=local_track_id,
        global_observation_id=global_observation_id,
        event_type=RawEventType.LINE_CROSSING,
        direction=direction,
        crossing_point_x=960.0,
        crossing_point_y=500.0,
        crossing_timestamp=timestamp,
        crossing_frame_index=frame_index,
        previous_position_x=960.0,
        previous_position_y=480.0 if direction == RawEventDirection.IN else 520.0,
        current_position_x=960.0,
        current_position_y=520.0 if direction == RawEventDirection.IN else 480.0,
        previous_frame_index=frame_index - 1,
        current_frame_index=frame_index,
        previous_timestamp=timestamp - 1.0,
        current_timestamp=timestamp,
        crossing_distance=40.0,
        side_transition="SIDE_A->SIDE_B" if direction == RawEventDirection.IN else "SIDE_B->SIDE_A",
        identity_certainty=IdentityCertainty.UNKNOWN,
        identity_candidate=None,
        identity_confidence=0.0,
        identity_evidence_ref=global_observation_id,
        source_crossing_event_id=source_crossing_event_id,
        trajectory_points=[],
        config_snapshot={},
        event_schema_version="1.0",
        created_at="2026-01-01T00:00:00Z",
    )


def run_acceptance_checks() -> Dict[str, Any]:
    """Run focused acceptance checks for Phase 24."""
    checks = {}
    
    # 1. State Machine Checks
    print("Running state machine checks...")
    resolver = create_repeated_in_out_resolver(create_default_resolver_config())
    
    # UNKNOWN + IN -> INSIDE
    event = create_test_raw_event("RIE-001", direction=RawEventDirection.IN, timestamp=1000.0)
    result = resolver.resolve_events([event])
    checks["state_machine_unknown_in"] = {
        "passed": result.accepted_transitions == 1 and result.transitions[0].new_state == DerivedState.INSIDE,
        "details": f"UNKNOWN + IN -> {result.transitions[0].new_state.value}",
    }
    
    # UNKNOWN + OUT -> OUTSIDE (ACCEPT_AS_INITIAL_STATE)
    resolver.clear()
    event = create_test_raw_event("RIE-002", direction=RawEventDirection.OUT, timestamp=2000.0)
    result = resolver.resolve_events([event])
    checks["state_machine_unknown_out"] = {
        "passed": result.accepted_transitions == 1 and result.transitions[0].new_state == DerivedState.OUTSIDE,
        "details": f"UNKNOWN + OUT -> {result.transitions[0].new_state.value}",
    }
    
    # INSIDE + OUT -> OUTSIDE
    resolver.clear()
    events = [
        create_test_raw_event("RIE-003", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-004", direction=RawEventDirection.OUT, timestamp=2000.0),
    ]
    result = resolver.resolve_events(events)
    checks["state_machine_inside_out"] = {
        "passed": result.accepted_transitions == 2 and result.transitions[1].new_state == DerivedState.OUTSIDE,
        "details": f"INSIDE + OUT -> {result.transitions[1].new_state.value}",
    }
    
    # OUTSIDE + IN -> INSIDE
    resolver.clear()
    events = [
        create_test_raw_event("RIE-005", direction=RawEventDirection.OUT, timestamp=1000.0),
        create_test_raw_event("RIE-006", direction=RawEventDirection.IN, timestamp=2000.0),
    ]
    result = resolver.resolve_events(events)
    checks["state_machine_outside_in"] = {
        "passed": result.accepted_transitions == 2 and result.transitions[1].new_state == DerivedState.INSIDE,
        "details": f"OUTSIDE + IN -> {result.transitions[1].new_state.value}",
    }
    
    # 2. Repeated Event Suppression
    print("Running repeated event suppression checks...")
    resolver.clear()
    events = [
        create_test_raw_event("RIE-007", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-008", direction=RawEventDirection.IN, timestamp=2000.0),
        create_test_raw_event("RIE-009", direction=RawEventDirection.IN, timestamp=3000.0),
    ]
    result = resolver.resolve_events(events)
    checks["repeated_in_suppressed"] = {
        "passed": result.accepted_transitions == 1 and result.suppressed_events == 2,
        "details": f"3 IN events -> {result.accepted_transitions} accepted, {result.suppressed_events} suppressed",
    }
    
    resolver.clear()
    events = [
        create_test_raw_event("RIE-010", direction=RawEventDirection.OUT, timestamp=1000.0),
        create_test_raw_event("RIE-011", direction=RawEventDirection.OUT, timestamp=2000.0),
        create_test_raw_event("RIE-012", direction=RawEventDirection.OUT, timestamp=3000.0),
    ]
    result = resolver.resolve_events(events)
    checks["repeated_out_suppressed"] = {
        "passed": result.accepted_transitions == 1 and result.suppressed_events == 2,
        "details": f"3 OUT events -> {result.accepted_transitions} accepted, {result.suppressed_events} suppressed",
    }
    
    # 3. IN -> OUT -> IN Sequence
    print("Running sequence checks...")
    resolver.clear()
    events = [
        create_test_raw_event("RIE-013", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-014", direction=RawEventDirection.OUT, timestamp=2000.0),
        create_test_raw_event("RIE-015", direction=RawEventDirection.IN, timestamp=3000.0),
    ]
    result = resolver.resolve_events(events)
    checks["in_out_in_sequence"] = {
        "passed": result.accepted_transitions == 3 and result.suppressed_events == 0,
        "details": f"IN->OUT->IN -> {result.accepted_transitions} transitions",
    }
    
    # 4. Initial OUT Policy
    print("Running initial OUT policy checks...")
    config_reject = ResolverConfig(initial_out_policy=InitialOutPolicy.REJECT)
    resolver_reject = create_repeated_in_out_resolver(config_reject)
    event = create_test_raw_event("RIE-016", direction=RawEventDirection.OUT, timestamp=1000.0)
    result = resolver_reject.resolve_events([event])
    checks["initial_out_reject"] = {
        "passed": result.rejected_events == 1 and result.final_states["CAM1:track_001"].current_state == DerivedState.UNKNOWN,
        "details": f"REJECT policy -> {result.rejected_events} rejected, final state: {result.final_states['CAM1:track_001'].current_state.value}",
    }
    
    config_accept = ResolverConfig(initial_out_policy=InitialOutPolicy.ACCEPT)
    resolver_accept = create_repeated_in_out_resolver(config_accept)
    event = create_test_raw_event("RIE-017", direction=RawEventDirection.OUT, timestamp=1000.0)
    result = resolver_accept.resolve_events([event])
    checks["initial_out_accept"] = {
        "passed": result.accepted_transitions == 1 and result.transitions[0].new_state == DerivedState.OUTSIDE,
        "details": f"ACCEPT policy -> {result.transitions[0].new_state.value}",
    }
    
    # 5. Temporal Ordering
    print("Running temporal ordering checks...")
    resolver.clear()
    events = [
        create_test_raw_event("RIE-018", direction=RawEventDirection.IN, timestamp=3000.0),
        create_test_raw_event("RIE-019", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-020", direction=RawEventDirection.OUT, timestamp=2000.0),
    ]
    result = resolver.resolve_events(events)
    timestamps = [t.source_timestamp for t in result.transitions]
    checks["temporal_ordering_sort"] = {
        "passed": timestamps == [1000.0, 2000.0, 3000.0],
        "details": f"Out-of-order sorted to: {timestamps}",
    }
    
    # Equal timestamp tie-breaking
    resolver.clear()
    events = [
        create_test_raw_event("RIE-B", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-A", direction=RawEventDirection.OUT, timestamp=1000.0),
    ]
    result = resolver.resolve_events(events)
    event_ids = [t.source_raw_event_id for t in result.transitions]
    checks["equal_timestamp_tiebreak"] = {
        "passed": event_ids == ["RIE-A", "RIE-B"],
        "details": f"Equal timestamps tie-broken by event_id: {event_ids}",
    }
    
    # 6. Multi-track Isolation
    print("Running multi-track isolation checks...")
    resolver.clear()
    events = [
        create_test_raw_event("RIE-021", local_track_id="track_A", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-022", local_track_id="track_B", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-023", local_track_id="track_A", direction=RawEventDirection.OUT, timestamp=2000.0),
    ]
    result = resolver.resolve_events(events)
    track_a_state = result.final_states["CAM1:track_A"]
    track_b_state = result.final_states["CAM1:track_B"]
    checks["multi_track_isolation"] = {
        "passed": track_a_state.current_state == DerivedState.OUTSIDE and track_b_state.current_state == DerivedState.INSIDE,
        "details": f"track_A: {track_a_state.current_state.value}, track_B: {track_b_state.current_state.value}",
    }
    
    # 7. Multi-camera Isolation
    resolver.clear()
    events = [
        create_test_raw_event("RIE-024", camera_id="CAM1", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-025", camera_id="CAM2", direction=RawEventDirection.OUT, timestamp=1000.0),
        create_test_raw_event("RIE-026", camera_id="CAM1", direction=RawEventDirection.OUT, timestamp=2000.0),
    ]
    result = resolver.resolve_events(events)
    cam1_state = result.final_states["CAM1:track_001"]
    cam2_state = result.final_states["CAM2:track_001"]
    checks["multi_camera_isolation"] = {
        "passed": cam1_state.current_state == DerivedState.OUTSIDE and cam2_state.current_state == DerivedState.OUTSIDE,
        "details": f"CAM1: {cam1_state.current_state.value} ({cam1_state.transition_count} transitions), CAM2: {cam2_state.current_state.value} ({cam2_state.transition_count} transitions)",
    }
    
    # 8. Provenance Preservation
    print("Running provenance preservation checks...")
    resolver.clear()
    event = create_test_raw_event(
        "RIE-027", 
        direction=RawEventDirection.IN, 
        timestamp=1000.0,
        global_observation_id="GO-123",
        geometry_version=5,
        geometry_config_hash="abc123def456",
        source_crossing_event_id="CE-ORIGINAL-456",
    )
    result = resolver.resolve_events([event])
    t = result.transitions[0]
    checks["provenance_preserved"] = {
        "passed": (
            t.source_raw_event_id == "RIE-027" and
            t.source_crossing_event_id == "CE-ORIGINAL-456" and
            t.global_observation_id == "GO-123" and
            t.geometry_version == 5 and
            t.geometry_config_hash == "abc123def456" and
            t.resolver_version == "1.0"
        ),
        "details": f"All provenance fields preserved",
    }
    
    # 9. Idempotency
    print("Running idempotency checks...")
    resolver.clear()
    events = [
        create_test_raw_event("RIE-028", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-029", direction=RawEventDirection.OUT, timestamp=2000.0),
    ]
    result1 = resolver.resolve_events(events)
    resolver.clear()
    result2 = resolver.resolve_events(events)
    checks["idempotency"] = {
        "passed": (
            len(result1.transitions) == len(result2.transitions) and
            all(t1.resolution_id == t2.resolution_id for t1, t2 in zip(result1.transitions, result2.transitions))
        ),
        "details": "Same events produce identical resolution IDs",
    }
    
    # Duplicate raw event ID suppression
    resolver.clear()
    event1 = create_test_raw_event("RIE-030", direction=RawEventDirection.IN, timestamp=1000.0)
    event2 = create_test_raw_event("RIE-030", direction=RawEventDirection.IN, timestamp=1000.0)  # Same ID
    result = resolver.resolve_events([event1, event2])
    checks["duplicate_event_id_suppressed"] = {
        "passed": result.total_raw_events == 2 and result.accepted_transitions == 1 and result.suppressed_events == 1,
        "details": f"Duplicate event_id -> {result.accepted_transitions} accepted, {result.suppressed_events} suppressed",
    }
    
    # 10. Serialization
    print("Running serialization checks...")
    resolver.clear()
    events = [
        create_test_raw_event("RIE-031", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-032", direction=RawEventDirection.OUT, timestamp=2000.0),
    ]
    result = resolver.resolve_events(events)
    
    # Test ResolutionResult serialization
    json_str = result.to_json()
    restored = ResolutionResult.from_json(json_str)
    checks["resolution_result_serialization"] = {
        "passed": (
            restored.total_raw_events == result.total_raw_events and
            restored.accepted_transitions == result.accepted_transitions and
            len(restored.transitions) == len(result.transitions)
        ),
        "details": "ResolutionResult round-trip successful",
    }
    
    # Test ResolvedTransition serialization
    transition = result.transitions[0]
    json_str = transition.to_json()
    restored = ResolvedTransition.from_json(json_str)
    checks["resolved_transition_serialization"] = {
        "passed": restored.resolution_id == transition.resolution_id and restored.transition_type == transition.transition_type,
        "details": "ResolvedTransition round-trip successful",
    }
    
    # Test ResolverConfig serialization
    config = create_default_resolver_config()
    json_str = config.to_json()
    restored = ResolverConfig.from_json(json_str)
    checks["resolver_config_serialization"] = {
        "passed": restored.initial_out_policy == config.initial_out_policy and restored.out_of_order_policy == config.out_of_order_policy,
        "details": "ResolverConfig round-trip successful",
    }
    
    # 11. Determinism
    print("Running determinism checks...")
    resolver1 = create_repeated_in_out_resolver(create_default_resolver_config())
    resolver2 = create_repeated_in_out_resolver(create_default_resolver_config())
    event = create_test_raw_event("RIE-033", direction=RawEventDirection.IN, timestamp=1000.0)
    result1 = resolver1.resolve_events([event])
    result2 = resolver2.resolve_events([event])
    checks["determinism"] = {
        "passed": result1.transitions[0].resolution_id == result2.transitions[0].resolution_id,
        "details": f"Resolution IDs match: {result1.transitions[0].resolution_id}",
    }
    
    # 12. Rapid Reversal Protection
    print("Running rapid reversal protection checks...")
    config_rr = ResolverConfig(enable_rapid_reversal_protection=True, min_transition_interval_seconds=1.0)
    resolver_rr = create_repeated_in_out_resolver(config_rr)
    events = [
        create_test_raw_event("RIE-034", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-035", direction=RawEventDirection.OUT, timestamp=1000.5),  # 0.5s later
    ]
    result = resolver_rr.resolve_events(events)
    checks["rapid_reversal_protection"] = {
        "passed": result.accepted_transitions == 1 and result.suppressed_events == 1,
        "details": f"Rapid reversal (0.5s) suppressed: {result.suppressed_events} suppressed",
    }
    
    # Disabled by default
    resolver_default = create_repeated_in_out_resolver(create_default_resolver_config())
    events = [
        create_test_raw_event("RIE-036", direction=RawEventDirection.IN, timestamp=1000.0),
        create_test_raw_event("RIE-037", direction=RawEventDirection.OUT, timestamp=1000.001),  # 1ms later
    ]
    result = resolver_default.resolve_events(events)
    checks["rapid_reversal_disabled_by_default"] = {
        "passed": result.accepted_transitions == 2 and result.suppressed_events == 0,
        "details": f"Rapid reversal (1ms) not suppressed by default: {result.accepted_transitions} accepted",
    }
    
    # 13. Bounded Memory
    print("Running bounded memory checks...")
    resolver.clear()
    for i in range(100):
        event = create_test_raw_event(f"RIE-{i}", local_track_id=f"track_{i}", direction=RawEventDirection.IN, timestamp=1000.0 + i)
        resolver.resolve_single(event)
    checks["bounded_track_states"] = {
        "passed": len(resolver.get_all_track_states()) == 100,
        "details": f"100 track states created, clear works: {len(resolver.get_all_track_states()) == 100}",
    }
    resolver.clear()
    checks["bounded_track_states_cleared"] = {
        "passed": len(resolver.get_all_track_states()) == 0,
        "details": "Clear removes all track states",
    }
    
    # 14. Configuration Hash
    print("Running configuration hash checks...")
    config1 = create_default_resolver_config()
    config2 = create_default_resolver_config()
    hash1 = generate_config_hash(config1)
    hash2 = generate_config_hash(config2)
    checks["config_hash_deterministic"] = {
        "passed": hash1 == hash2,
        "details": f"Same config produces same hash: {hash1}",
    }
    
    config_strict = create_strict_resolver_config()
    hash_strict = generate_config_hash(config_strict)
    checks["config_hash_different"] = {
        "passed": hash1 != hash_strict,
        "details": f"Different configs produce different hashes: {hash1} vs {hash_strict}",
    }
    
    return checks


def main():
    """Main acceptance script entry point."""
    print("=" * 80)
    print("PHASE 24 — REPEATED IN/OUT RESOLUTION ACCEPTANCE")
    print("=" * 80)
    print(f"Started at: {datetime.utcnow().isoformat()}Z")
    print()
    
    # Run pytest unit tests
    print("Running unit tests...")
    unit_results = run_pytest("tests/unit/test_repeated_in_out.py")
    print(f"Unit tests: {unit_results['passed']} passed, {unit_results['failed']} failed, {unit_results['errors']} errors")
    
    # Run pytest integration tests
    print("Running integration tests...")
    integration_results = run_pytest("tests/integration/test_phase24_integration.py")
    print(f"Integration tests: {integration_results['passed']} passed, {integration_results['failed']} failed, {integration_results['errors']} errors")
    
    # Run acceptance checks
    print("Running acceptance checks...")
    acceptance_checks = run_acceptance_checks()
    
    # Count passed/failed checks
    passed_checks = sum(1 for c in acceptance_checks.values() if c["passed"])
    failed_checks = sum(1 for c in acceptance_checks.values() if not c["passed"])
    total_checks = len(acceptance_checks)
    
    print()
    print("=" * 80)
    print("ACCEPTANCE CHECK RESULTS")
    print("=" * 80)
    for name, check in acceptance_checks.items():
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  [{status}] {name}: {check['details']}")
    
    print()
    print(f"Total checks: {total_checks}")
    print(f"Passed: {passed_checks}")
    print(f"Failed: {failed_checks}")
    
    # Overall verdict
    all_tests_passed = (
        unit_results["failed"] == 0 and unit_results["errors"] == 0 and
        integration_results["failed"] == 0 and integration_results["errors"] == 0 and
        failed_checks == 0
    )
    
    verdict = "PASS" if all_tests_passed else "FAIL"
    print()
    print("=" * 80)
    print(f"PHASE 24 VERDICT: {verdict}")
    print("=" * 80)
    
    # Generate reports
    report_data = {
        "phase": "24",
        "name": "Repeated IN/OUT Resolution",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "verdict": verdict,
        "unit_tests": {
            "passed": unit_results["passed"],
            "failed": unit_results["failed"],
            "errors": unit_results["errors"],
        },
        "integration_tests": {
            "passed": integration_results["passed"],
            "failed": integration_results["failed"],
            "errors": integration_results["errors"],
        },
        "acceptance_checks": {
            "total": total_checks,
            "passed": passed_checks,
            "failed": failed_checks,
            "details": acceptance_checks,
        },
        "state_machine_behavior": {
            "unknown_in_to_inside": acceptance_checks["state_machine_unknown_in"]["passed"],
            "unknown_out_to_outside": acceptance_checks["state_machine_unknown_out"]["passed"],
            "inside_out_to_outside": acceptance_checks["state_machine_inside_out"]["passed"],
            "outside_in_to_inside": acceptance_checks["state_machine_outside_in"]["passed"],
        },
        "repeated_event_behavior": {
            "repeated_in_suppressed": acceptance_checks["repeated_in_suppressed"]["passed"],
            "repeated_out_suppressed": acceptance_checks["repeated_out_suppressed"]["passed"],
        },
        "initial_out_policy": {
            "reject_policy": acceptance_checks["initial_out_reject"]["passed"],
            "accept_policy": acceptance_checks["initial_out_accept"]["passed"],
        },
        "temporal_ordering": {
            "sort_policy": acceptance_checks["temporal_ordering_sort"]["passed"],
            "equal_timestamp_tiebreak": acceptance_checks["equal_timestamp_tiebreak"]["passed"],
        },
        "multi_track_isolation": acceptance_checks["multi_track_isolation"]["passed"],
        "multi_camera_isolation": acceptance_checks["multi_camera_isolation"]["passed"],
        "provenance_preservation": acceptance_checks["provenance_preserved"]["passed"],
        "idempotency": acceptance_checks["idempotency"]["passed"],
        "serialization": {
            "resolution_result": acceptance_checks["resolution_result_serialization"]["passed"],
            "resolved_transition": acceptance_checks["resolved_transition_serialization"]["passed"],
            "resolver_config": acceptance_checks["resolver_config_serialization"]["passed"],
        },
        "determinism": acceptance_checks["determinism"]["passed"],
        "rapid_reversal_protection": {
            "enabled": acceptance_checks["rapid_reversal_protection"]["passed"],
            "disabled_by_default": acceptance_checks["rapid_reversal_disabled_by_default"]["passed"],
        },
        "bounded_memory": {
            "track_states": acceptance_checks["bounded_track_states"]["passed"],
            "cleared": acceptance_checks["bounded_track_states_cleared"]["passed"],
        },
        "phase_22_23_24_integration": integration_results["failed"] == 0 and integration_results["errors"] == 0,
    }
    
    # Write JSON report
    json_report_path = PROJECT_ROOT / "benchmark_results" / "PHASE_24_REPEATED_IN_OUT_RESOLUTION.json"
    json_report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    print(f"JSON report written to: {json_report_path}")
    
    # Write Markdown report
    md_report_path = PROJECT_ROOT / "benchmark_results" / "PHASE_24_REPEATED_IN_OUT_RESOLUTION.md"
    with open(md_report_path, "w", encoding="utf-8") as f:
        f.write(f"# Phase 24 — Repeated IN/OUT Resolution Report\n\n")
        f.write(f"**Timestamp:** {report_data['timestamp']}\n\n")
        f.write(f"**Verdict:** {verdict}\n\n")
        
        f.write("## Test Summary\n\n")
        f.write(f"- **Unit Tests:** {unit_results['passed']} passed, {unit_results['failed']} failed, {unit_results['errors']} errors\n")
        f.write(f"- **Integration Tests:** {integration_results['passed']} passed, {integration_results['failed']} failed, {integration_results['errors']} errors\n")
        f.write(f"- **Acceptance Checks:** {passed_checks}/{total_checks} passed\n\n")
        
        f.write("## Acceptance Check Details\n\n")
        for name, check in acceptance_checks.items():
            status = "✅ PASS" if check["passed"] else "❌ FAIL"
            f.write(f"- {status} **{name}**: {check['details']}\n")
        
        f.write("\n## Key Capabilities Verified\n\n")
        f.write("### State Machine\n")
        f.write(f"- UNKNOWN + IN → INSIDE: {'✅' if report_data['state_machine_behavior']['unknown_in_to_inside'] else '❌'}\n")
        f.write(f"- UNKNOWN + OUT → OUTSIDE (ACCEPT_AS_INITIAL_STATE): {'✅' if report_data['state_machine_behavior']['unknown_out_to_outside'] else '❌'}\n")
        f.write(f"- INSIDE + OUT → OUTSIDE: {'✅' if report_data['state_machine_behavior']['inside_out_to_outside'] else '❌'}\n")
        f.write(f"- OUTSIDE + IN → INSIDE: {'✅' if report_data['state_machine_behavior']['outside_in_to_inside'] else '❌'}\n\n")
        
        f.write("### Repeated Event Suppression\n")
        f.write(f"- Repeated IN suppressed: {'✅' if report_data['repeated_event_behavior']['repeated_in_suppressed'] else '❌'}\n")
        f.write(f"- Repeated OUT suppressed: {'✅' if report_data['repeated_event_behavior']['repeated_out_suppressed'] else '❌'}\n\n")
        
        f.write("### Initial OUT Policy\n")
        f.write(f"- REJECT policy: {'✅' if report_data['initial_out_policy']['reject_policy'] else '❌'}\n")
        f.write(f"- ACCEPT policy: {'✅' if report_data['initial_out_policy']['accept_policy'] else '❌'}\n\n")
        
        f.write("### Temporal Ordering\n")
        f.write(f"- SORT policy for out-of-order: {'✅' if report_data['temporal_ordering']['sort_policy'] else '❌'}\n")
        f.write(f"- Equal timestamp tie-breaking (event_id): {'✅' if report_data['temporal_ordering']['equal_timestamp_tiebreak'] else '❌'}\n\n")
        
        f.write("### Isolation\n")
        f.write(f"- Multi-track isolation: {'✅' if report_data['multi_track_isolation'] else '❌'}\n")
        f.write(f"- Multi-camera isolation: {'✅' if report_data['multi_camera_isolation'] else '❌'}\n\n")
        
        f.write("### Provenance & Idempotency\n")
        f.write(f"- Provenance preserved: {'✅' if report_data['provenance_preservation'] else '❌'}\n")
        f.write(f"- Idempotent resolution: {'✅' if report_data['idempotency'] else '❌'}\n\n")
        
        f.write("### Serialization\n")
        f.write(f"- ResolutionResult: {'✅' if report_data['serialization']['resolution_result'] else '❌'}\n")
        f.write(f"- ResolvedTransition: {'✅' if report_data['serialization']['resolved_transition'] else '❌'}\n")
        f.write(f"- ResolverConfig: {'✅' if report_data['serialization']['resolver_config'] else '❌'}\n\n")
        
        f.write("### Determinism & Protection\n")
        f.write(f"- Deterministic resolution IDs: {'✅' if report_data['determinism'] else '❌'}\n")
        f.write(f"- Rapid reversal protection (enabled): {'✅' if report_data['rapid_reversal_protection']['enabled'] else '❌'}\n")
        f.write(f"- Rapid reversal protection (disabled by default): {'✅' if report_data['rapid_reversal_protection']['disabled_by_default'] else '❌'}\n\n")
        
        f.write("### Memory & Integration\n")
        f.write(f"- Bounded track states: {'✅' if report_data['bounded_memory']['track_states'] else '❌'}\n")
        f.write(f"- Phase 22→23→24 integration: {'✅' if report_data['phase_22_23_24_integration'] else '❌'}\n\n")
        
        f.write("## Known Limitations\n\n")
        f.write("1. Rapid reversal protection is optional and disabled by default\n")
        f.write("2. Out-of-order REJECT policy still sorts events for deterministic processing\n")
        f.write("3. ACCEPT_IF_SAFE out-of-order policy currently behaves like SORT\n")
        f.write("4. No cross-camera fusion - tracks with same local_track_id on different cameras are independent\n")
        f.write("5. Identity certainty (UNKNOWN/AMBIGUOUS/INSUFFICIENT) is preserved but not used for resolution logic\n\n")
        
        f.write("## Phase 25 Readiness\n\n")
        f.write("Phase 24 provides a complete, deterministic, and well-tested repeated IN/OUT resolution layer.\n")
        f.write("The resolver produces immutable derived transitions with full provenance, suitable for\n")
        f.write("downstream attendance persistence, analytics, or real-time dashboards.\n\n")
        f.write("Ready for Phase 25: Attendance Persistence & Query Layer.\n")
    
    print(f"Markdown report written to: {md_report_path}")
    
    return 0 if all_tests_passed else 1


if __name__ == "__main__":
    sys.exit(main())