# Phase 23 — Raw IN/OUT Event Engine Acceptance Report

**Timestamp:** 2026-08-22T03:32:23.304848Z
**Verdict:** PASS
**Duration:** 13.33s

## Summary

- Unit Tests: ✅ PASS
- Integration Tests: ✅ PASS
- Acceptance Checks: 14 passed, 0 failed

## Acceptance Checks

- [OK] raw_event_contract
- [OK] immutability
- [OK] deterministic_event_identity
- [OK] idempotency
- [OK] direction_preservation
- [OK] timestamp_preservation
- [OK] geometry_version
- [OK] provenance
- [OK] camera_isolation
- [OK] global_observation_preservation
- [OK] serialization
- [OK] determinism
- [OK] bounded_state
- [OK] phase22_integration

## Detailed Results

### Raw Event Contract
- Exists: True
- Enums Valid: True
- Frozen Dataclass: True

### Immutability
- Immutable: True

### Deterministic Event Identity
- Deterministic: True
- Format: RIE-04c055800f036b2f
- Camera Isolation: True
- Track Isolation: True
- Geometry Version Isolation: True

### Idempotency
- Idempotent: True
- Duplicate Count: 1
- Successful Count: 1
- Event Count: 1

### Direction Preservation
- Preserved: True
- IN Count: 1
- OUT Count: 1

### Timestamp Preservation
- Preserved: True
- Original: 1234567890.123456
- Preserved: 1234567890.123456
- Created At Preserved: True

### Geometry Version
- Preserved: True
- Version: 3
- Config Hash: 2302d113da873236

### Provenance
- Preserved: True

### Camera Isolation
- Isolated: True
- CAM1 Events: 1
- CAM2 Events: 1
- Event IDs Distinct: True

### GlobalObservation Preservation
- Preserved: True
- GO ID: GO-INTEGRATION-123

### Serialization
- Round-trip: True
- Dict Round-trip: True
- JSON Round-trip: True

### Determinism
- Deterministic: True

### Bounded State
- Bounded: True
- Processed IDs: 50
- Events: 50
- Clear Works: True

### Phase 22 Integration
- Integrated: True
- Crossing Engine: CrossingEngine
- Raw Engine: RawEventEngine

## Known Limitations

- Identity certainty defaults to UNKNOWN - Phase 21 integration for KNOWN/AMBIGUOUS not yet implemented
- No cross-camera fusion in Phase 23 (by design - Phase 24 scope)
- No attendance state machine (by design - Phase 24 scope)
- Bounded memory relies on manual clear() - no automatic eviction policy

## Phase 24 Readiness

- raw_events_preserved_independently: True
- no_state_collapsing: True
- deterministic_ids: True
- provenance_complete: True
- ready_for_resolution_layer: True

## Pytest Output

### Unit Tests
```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-7.4.4, pluggy-1.6.0 -- C:\Users\Nguyen Cong Thong\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: c:\Users\Nguyen Cong Thong\Desktop\AI attendance
plugins: anyio-4.14.2, cov-4.1.0, mock-3.15.1
collecting ... collected 76 items

tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_creation_minimal PASSED [  1%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_creation_out_direction PASSED [  2%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_zone_entry PASSED [  3%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_immutability PASSED [  5%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_serialization_roundtrip PASSED [  6%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_json_serialization PASSED [  7%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_empty_event_id PASSED [  9%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_empty_camera_id PASSED [ 10%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_invalid_direction PASSED [ 11%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_negative_timestamp PASSED [ 13%]
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_invalid_schema_version PASSED [ 14%]
tests/unit/test_raw_in_out_event.py::TestDeterministicEventId::test_same_inputs_produce_same_id PASSED [ 15%]
tests/unit/test_raw_in_out_event.py::TestDeterministicEventId::test_different_camera_produces_different_id PASSED [ 17%]
tests/unit/test_raw_in_out_event.py::TestDeterministicEventId::test_different_track_produces_different_id PASSED [ 18%]
tests/unit/test_raw_in_out_event.py::TestDeterministicEventId::test_different_crossing_event_produces_different_id PASSED [ 19%]
tests/unit/test_raw_in_out_event.py::TestDeterministicEventId::test_different_geometry_version_produces_different_id PASSED [ 21%]
tests/unit/test_raw_in_out_event.py::TestDeterministicEventId::test_different_geometry_hash_produces_different_id PASSED [ 22%]
tests/unit/test_raw_in_out_event.py::TestDirectionMapping::test_in_direction_preserved PASSED [ 23%]
tests/unit/test_raw_in_out_event.py::TestDirectionMapping::test_out_direction_preserved PASSED [ 25%]
tests/unit/test_raw_in_out_event.py::TestDirectionMapping::test_event_type_mapping PASSED [ 26%]
tests/unit/test_raw_in_out_event.py::TestIdentityExtraction::test_identity_defaults_to_unknown PASSED [ 27%]
tests/unit/test_raw_in_out_event.py::TestIdentityExtraction::test_identity_preserves_global_observation_ref PASSED [ 28%]
tests/unit/test_raw_in_out_event.py::TestIdentityExtraction::test_identity_none_when_no_global_observation PASSED [ 30%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_engine_creation PASSED [ 31%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_process_single_crossing_event PASSED [ 32%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_process_multiple_crossing_events PASSED [ 34%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_idempotent_processing PASSED [ 35%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_idempotent_reconstructed_event PASSED [ 36%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_camera_isolation PASSED [ 38%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_chronological_ordering PASSED [ 39%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_equal_timestamp_tiebreaking PASSED [ 40%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_historical_events_remain_independent PASSED [ 42%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_rejects_invalid_crossing_event PASSED [ 43%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_rejects_missing_direction PASSED [ 44%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_rejects_missing_camera_id PASSED [ 46%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_rejects_negative_timestamp PASSED [ 47%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_rejects_missing_geometry_config PASSED [ 48%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_rejects_missing_geometry_hash PASSED [ 50%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_engine_clear PASSED [ 51%]
tests/unit/test_raw_in_out_event.py::TestRawEventEngine::test_has_event PASSED [ 52%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_valid_event PASSED [ 53%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_missing_event_id PASSED [ 55%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_missing_camera_id PASSED [ 56%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_missing_local_track_id PASSED [ 57%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_invalid_direction PASSED [ 59%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_negative_timestamp PASSED [ 60%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_missing_geometry_hash PASSED [ 61%]
tests/unit/test_raw_in_out_event.py::TestValidation::test_validate_missing_geometry_version PASSED [ 63%]
tests/unit/test_raw_in_out_event.py::TestFactoryFunctions::test_process_crossing_events_to_raw PASSED [ 64%]
tests/unit/test_raw_in_out_event.py::TestFactoryFunctions::test_create_raw_events_from_crossing_engine PASSED [ 65%]
tests/unit/test_raw_in_out_event.py::TestFactoryFunctions::test_create_integrated_pipeline PASSED [ 67%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_crossing_event_id PASSED [ 68%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_geometry_version PASSED [ 69%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_geometry_hash PASSED [ 71%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_camera_id PASSED [ 72%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_local_track_id PASSED [ 73%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_global_observation_id PASSED [ 75%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_timestamp PASSED [ 76%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_trajectory_points PASSED [ 77%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_provenance_preserves_config_snapshot PASSED [ 78%]
tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_geometry_version_immutable_across_config_changes PASSED [ 80%]
tests/unit/test_raw_in_out_event.py::TestDeterminism::test_repeated_execution_produces_same_results PASSED [ 81%]
tests/unit/test_raw_in_out_event.py::TestDeterminism::test_no_random_event_ids PASSED [ 82%]
tests/unit/test_raw_in_out_event.py::TestDeterminism::test_no_wall_clock_dependency PASSED [ 84%]
tests/unit/test_raw_in_out_event.py::TestBoundedMemory::test_engine_does_not_retain_unbounded_history PASSED [ 85%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_crossing_engine_to_raw_engine_pipeline PASSED [ 86%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_direction_preserved_through_pipeline PASSED [ 88%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_timestamp_preserved_through_pipeline PASSED [ 89%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_camera_id_preserved_through_pipeline PASSED [ 90%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_local_track_id_preserved_through_pipeline PASSED [ 92%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_global_observation_id_preserved_through_pipeline PASSED [ 93%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_geometry_id_version_preserved_through_pipeline PASSED [ 94%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_source_crossing_event_id_preserved PASSED [ 96%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_provenance_preserved_through_pipeline PASSED [ 97%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_deterministic_event_id_through_pipeline PASSED [ 98%]
tests/unit/test_raw_in_out_event.py::TestPhase22Integration::test_duplicate_processing_idempotent_through_pipeline PASSED [100%]

============================== warnings summary ===============================
tests/unit/test_raw_in_out_event.py: 66 warnings
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\geometry\contract.py:360: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

tests/unit/test_raw_in_out_event.py: 66 warnings
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\geometry\contract.py:361: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_serialization_roundtrip
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_json_serialization
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\in_out\contract.py:227: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),

tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_empty_event_id
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_empty_camera_id
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_invalid_direction
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_negative_timestamp
tests/unit/test_raw_in_out_event.py::TestRawInOutEventContract::test_raw_event_validation_rejects_invalid_schema_version
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\in_out\contract.py:105: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

tests/unit/test_raw_in_out_event.py::TestProvenanceChain::test_geometry_version_immutable_across_config_changes
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\geometry\contract.py:490: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    updated_at=datetime.utcnow().isoformat() + "Z",

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
====================== 76 passed, 140 warnings in 3.56s =======================

```

### Integration Tests
```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-7.4.4, pluggy-1.6.0 -- C:\Users\Nguyen Cong Thong\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: c:\Users\Nguyen Cong Thong\Desktop\AI attendance
plugins: anyio-4.14.2, cov-4.1.0, mock-3.15.1
collecting ... collected 18 items

tests/integration/test_phase23_integration.py::TestPhase22Integration::test_crossing_engine_produces_events_convertible_to_raw PASSED [  5%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_manual_crossing_event_conversion PASSED [ 11%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_multiple_cameras_independent_raw_events PASSED [ 16%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_direction_preserved_from_phase22 PASSED [ 22%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_timestamp_preserved_from_phase22 PASSED [ 27%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_geometry_version_preserved_from_phase22 PASSED [ 33%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_source_crossing_event_id_preserved PASSED [ 38%]
tests/integration/test_phase23_integration.py::TestPhase22Integration::test_provenance_chain_preserved PASSED [ 44%]
tests/integration/test_phase23_integration.py::TestPhase21Integration::test_global_observation_id_preserved PASSED [ 50%]
tests/integration/test_phase23_integration.py::TestPhase21Integration::test_unknown_identity_supported PASSED [ 55%]
tests/integration/test_phase23_integration.py::TestPhase21Integration::test_ambiguous_identity_supported PASSED [ 61%]
tests/integration/test_phase23_integration.py::TestPhase21Integration::test_no_rerun_of_phase21_fusion PASSED [ 66%]
tests/integration/test_phase23_integration.py::TestFactoryIntegration::test_create_integrated_pipeline PASSED [ 72%]
tests/integration/test_phase23_integration.py::TestFactoryIntegration::test_process_tracks_through_pipeline PASSED [ 77%]
tests/integration/test_phase23_integration.py::TestEndToEndScenarios::test_in_out_sequence_preserved PASSED [ 83%]
tests/integration/test_phase23_integration.py::TestEndToEndScenarios::test_out_of_order_input_handled PASSED [ 88%]
tests/integration/test_phase23_integration.py::TestEndToEndScenarios::test_equal_timestamp_deterministic_ordering PASSED [ 94%]
tests/integration/test_phase23_integration.py::TestEndToEndScenarios::test_zone_and_line_events_coexist PASSED [100%]

============================== warnings summary ===============================
tests/integration/test_phase23_integration.py: 20 warnings
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\geometry\contract.py:360: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

tests/integration/test_phase23_integration.py: 20 warnings
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\geometry\contract.py:361: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

tests/integration/test_phase23_integration.py::TestPhase21Integration::test_global_observation_id_preserved
tests/integration/test_phase23_integration.py::TestPhase21Integration::test_no_rerun_of_phase21_fusion
  c:\Users\Nguyen Cong Thong\Desktop\AI attendance\app\replay\fusion.py:193: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 18 passed, 42 warnings in 3.61s =======================

```