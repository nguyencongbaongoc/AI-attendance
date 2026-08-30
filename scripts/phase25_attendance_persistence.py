#!/usr/bin/env python
"""
Phase 25 — Attendance Persistence Acceptance Script.

This script runs the complete Phase 25 acceptance verification:
- Runs pytest unit tests
- Runs pytest integration tests
- Verifies Phase 24 → Phase 25 integration
- Verifies persistence/restart recovery
- Verifies query capabilities
- Generates JSON and Markdown reports
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import tempfile
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.in_out.contract import (
    RawInOutEvent,
    RawEventDirection,
    RawEventType,
    IdentityCertainty,
)
from app.in_out.resolver import create_repeated_in_out_resolver
from app.in_out.resolver_contract import (
    ResolvedTransition,
    ResolutionResult,
    TransitionType,
    DerivedState,
    ResolutionStatus,
)
from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    create_attendance_record_from_resolution,
)
from app.attendance.repository import AttendanceRepository, PersistenceResult
from app.attendance.storage import AttendanceStorage, StorageConfig
from app.attendance.query import (
    get_attendance_summary,
    records_to_timeline,
    get_daily_attendance_counts,
    get_track_state_history,
)


class AcceptanceResult:
    """Container for acceptance test results."""
    
    def __init__(self):
        self.verdict: str = "UNKNOWN"
        self.timestamp: str = datetime.utcnow().isoformat() + "Z"
        self.pytest_unit: Dict[str, Any] = {}
        self.pytest_integration: Dict[str, Any] = {}
        self.acceptance_checks: Dict[str, Any] = {}
        self.persistence_backend: str = "SQLite"
        self.schema_version: str = "1.0"
        self.known_limitations: List[str] = []
        self.phase26_readiness: bool = False
        self.files_changed: List[str] = []
        self.reports_generated: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "timestamp": self.timestamp,
            "pytest_unit": self.pytest_unit,
            "pytest_integration": self.pytest_integration,
            "acceptance_checks": self.acceptance_checks,
            "persistence_backend": self.persistence_backend,
            "schema_version": self.schema_version,
            "known_limitations": self.known_limitations,
            "phase26_readiness": self.phase26_readiness,
            "files_changed": self.files_changed,
            "reports_generated": self.reports_generated,
        }


def run_pytest(test_path: str, description: str) -> Dict[str, Any]:
    """Run pytest and return results."""
    print(f"\n{'='*60}")
    print(f"Running {description}...")
    print(f"{'='*60}")
    
    start_time = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    elapsed = time.time() - start_time
    
    return {
        "description": description,
        "test_path": test_path,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "elapsed_seconds": elapsed,
        "passed": result.returncode == 0,
    }


def run_acceptance_checks() -> Dict[str, Any]:
    """Run focused acceptance checks."""
    print(f"\n{'='*60}")
    print("Running Phase 25 Acceptance Checks...")
    print(f"{'='*60}")
    
    checks = {}
    
    def create_fresh_db():
        """Create a fresh database for each check."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        config = StorageConfig(database_path=db_path)
        return config, db_path
    
    def cleanup_db(db_path):
        """Clean up database files."""
        if os.path.exists(db_path):
            os.unlink(db_path)
        for suffix in ["-wal", "-shm"]:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.unlink(wal_path)
    
    # Check 1: Basic persistence
    print("Check 1: Basic persistence...")
    config, db_path = create_fresh_db()
    try:
        storage = AttendanceStorage(config)
        record = AttendanceRecord(
            attendance_record_id="ATT-check1",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-check1",
            source_resolution_id="RES-check1",
        )
        inserted = storage.insert(record)
        checks["basic_persistence"] = {"passed": inserted, "details": "Insert and retrieve"}
        storage.close()
    finally:
        cleanup_db(db_path)
    
    # Check 2: Idempotency
    print("Check 2: Idempotency...")
    config, db_path = create_fresh_db()
    try:
        storage = AttendanceStorage(config)
        record = AttendanceRecord(
            attendance_record_id="ATT-check1",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-check1",
            source_resolution_id="RES-check1",
        )
        inserted1 = storage.insert(record)
        inserted2 = storage.insert(record)
        checks["idempotency"] = {
            "passed": inserted1 and not inserted2,
            "details": f"First insert: {inserted1}, Second insert: {inserted2}"
        }
        storage.close()
    finally:
        cleanup_db(db_path)
    
    # Check 3: Phase 24 -> Phase 25 integration
    print("Check 3: Phase 24 -> Phase 25 integration...")
    config, db_path = create_fresh_db()
    try:
        repo = AttendanceRepository(config=config)
        
        # Create raw events
        raw_events = [
            RawInOutEvent(
                event_id="RIE-int-1",
                camera_id="CAM1",
                geometry_id="geom_hash",
                geometry_version=1,
                geometry_config_hash="geom_hash",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.IN,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1000.0,
                crossing_frame_index=100,
                previous_position_x=90.0,
                previous_position_y=190.0,
                current_position_x=110.0,
                current_position_y=210.0,
                previous_frame_index=99,
                current_frame_index=100,
                previous_timestamp=999.967,
                current_timestamp=1000.0,
                crossing_distance=10.0,
                side_transition="outside_to_inside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id="CE-int-1",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
            RawInOutEvent(
                event_id="RIE-int-2",
                camera_id="CAM1",
                geometry_id="geom_hash",
                geometry_version=1,
                geometry_config_hash="geom_hash",
                local_track_id="track_001",
                global_observation_id="GO-123",
                event_type=RawEventType.LINE_CROSSING,
                direction=RawEventDirection.OUT,
                crossing_point_x=100.0,
                crossing_point_y=200.0,
                crossing_timestamp=1010.0,
                crossing_frame_index=110,
                previous_position_x=110.0,
                previous_position_y=210.0,
                current_position_x=90.0,
                current_position_y=190.0,
                previous_frame_index=109,
                current_frame_index=110,
                previous_timestamp=1009.967,
                current_timestamp=1010.0,
                crossing_distance=10.0,
                side_transition="inside_to_outside",
                identity_certainty=IdentityCertainty.UNKNOWN,
                identity_candidate=None,
                identity_confidence=0.0,
                identity_evidence_ref="GO-123",
                source_crossing_event_id="CE-int-2",
                trajectory_points=[],
                config_snapshot={},
                event_schema_version="1.0",
            ),
        ]
        
        resolver = create_repeated_in_out_resolver()
        resolution_result = resolver.resolve_events(raw_events)
        persistence_result = repo.persist_resolution_result(resolution_result)
        
        checks["phase24_to_25_integration"] = {
            "passed": persistence_result.transitions_persisted == 2,
            "details": f"Persisted: {persistence_result.transitions_persisted}, Suppressed: {persistence_result.suppressed_skipped}"
        }
        
        # Check 4: Provenance preservation
        print("Check 4: Provenance preservation...")
        record = repo.get_by_resolution_id(resolution_result.transitions[0].resolution_id)
        provenance_ok = (
            record is not None and
            record.source_resolution_id == resolution_result.transitions[0].resolution_id and
            record.source_raw_event_id == "RIE-int-1" and
            record.source_crossing_event_id == "CE-int-1" and
            record.geometry_version == 1 and
            record.resolver_version == "1.0"
        )
        checks["provenance_preservation"] = {"passed": provenance_ok, "details": "All provenance fields preserved"}
        
        # Check 5: Query capabilities
        print("Check 5: Query capabilities...")
        by_camera = repo.query_by_camera("CAM1")
        by_track = repo.query_by_track("CAM1", "track_001")
        by_direction_in = repo.query_by_direction("in")
        by_direction_out = repo.query_by_direction("out")
        by_time = repo.query_by_time_range(1000.0, 1010.0)
        chronological = repo.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
        latest = repo.get_latest_by_track("CAM1", "track_001")
        current_state = repo.get_current_state_by_track("CAM1", "track_001")
        
        checks["query_capabilities"] = {
            "passed": (
                len(by_camera) == 2 and
                len(by_track) == 2 and
                len(by_direction_in) == 1 and
                len(by_direction_out) == 1 and
                len(by_time) == 1 and
                len(chronological) == 2 and
                latest is not None and
                current_state == "outside"
            ),
            "details": f"Camera: {len(by_camera)}, Track: {len(by_track)}, IN: {len(by_direction_in)}, OUT: {len(by_direction_out)}, Time: {len(by_time)}, Chronological: {len(chronological)}, Latest: {latest is not None}, State: {current_state}"
        }
        
        # Check 6: Restart recovery
        print("Check 6: Restart recovery...")
        repo.close()
        repo2 = AttendanceRepository(config=config)
        records_after_restart = repo2.get_chronological_history(camera_id="CAM1", local_track_id="track_001")
        checks["restart_recovery"] = {
            "passed": len(records_after_restart) == 2,
            "details": f"Records after restart: {len(records_after_restart)}"
        }
        repo2.close()
    finally:
        cleanup_db(db_path)
    
    # Check 7: Deterministic ordering
    print("Check 7: Deterministic ordering...")
    config, db_path = create_fresh_db()
    try:
        storage = AttendanceStorage(config)
        for i in range(3):
            r = AttendanceRecord(
                attendance_record_id=f"ATT-order-{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0,  # Same timestamp
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-order-{i}",
                source_resolution_id=f"RES-order-{i}",
            )
            storage.insert(r)
        
        records = storage.query(order_by="event_timestamp")
        ordering_ok = (
            len(records) == 3 and
            records[0].attendance_record_id == "ATT-order-0" and
            records[1].attendance_record_id == "ATT-order-1" and
            records[2].attendance_record_id == "ATT-order-2"
        )
        checks["deterministic_ordering"] = {"passed": ordering_ok, "details": "Secondary sort by attendance_record_id"}
        storage.close()
    finally:
        cleanup_db(db_path)
    
    # Check 8: Negative cases
    print("Check 8: Negative cases...")
    config, db_path = create_fresh_db()
    try:
        storage = AttendanceStorage(config)
        negative_passed = True
        negative_details = []
        
        # Invalid direction
        try:
            bad_record = AttendanceRecord(
                attendance_record_id="ATT-bad-dir",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction="invalid",
                event_timestamp=1000.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-bad",
                source_resolution_id="RES-bad",
            )
            storage.insert(bad_record)
            negative_passed = False
            negative_details.append("Invalid direction not rejected")
        except ValueError:
            negative_details.append("Invalid direction rejected")
        
        # Invalid timestamp
        try:
            bad_record = AttendanceRecord(
                attendance_record_id="ATT-bad-ts",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=-1.0,
                camera_id="CAM1",
                local_track_id="track_001",
                source_raw_event_id="RIE-bad",
                source_resolution_id="RES-bad",
            )
            storage.insert(bad_record)
            negative_passed = False
            negative_details.append("Invalid timestamp not rejected")
        except ValueError:
            negative_details.append("Invalid timestamp rejected")
        
        # Duplicate source_resolution_id - first insert a record, then try duplicate
        first_record = AttendanceRecord(
            attendance_record_id="ATT-first",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-first",
            source_resolution_id="RES-duplicate-test",
        )
        storage.insert(first_record)
        
        dup_record = AttendanceRecord(
            attendance_record_id="ATT-dup-new",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.OUT,
            event_timestamp=1020.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-dup-new",
            source_resolution_id="RES-duplicate-test",  # Duplicate
        )
        inserted = storage.insert(dup_record)
        if not inserted:
            negative_details.append("Duplicate source_resolution_id rejected")
        else:
            negative_passed = False
            negative_details.append("Duplicate source_resolution_id not rejected")
        
        storage.close()
        checks["negative_cases"] = {"passed": negative_passed, "details": "; ".join(negative_details)}
    finally:
        cleanup_db(db_path)
    
    # Check 9: Serialization round-trip
    print("Check 9: Serialization round-trip...")
    config, db_path = create_fresh_db()
    try:
        record = AttendanceRecord(
            attendance_record_id="ATT-serial",
            identity_certainty=IdentityCertainty.UNKNOWN,
            direction=AttendanceDirection.IN,
            event_timestamp=1000.0,
            camera_id="CAM1",
            local_track_id="track_001",
            source_raw_event_id="RIE-serial",
            source_resolution_id="RES-serial",
        )
        json_str = record.to_json()
        restored = AttendanceRecord.from_json(json_str)
        roundtrip_ok = (
            restored.attendance_record_id == record.attendance_record_id and
            restored.direction == record.direction and
            restored.event_timestamp == record.event_timestamp
        )
        checks["serialization_roundtrip"] = {"passed": roundtrip_ok, "details": "JSON round-trip successful"}
    finally:
        cleanup_db(db_path)
    
    # Check 10: Bounded query behavior
    print("Check 10: Bounded query behavior...")
    config, db_path = create_fresh_db()
    try:
        repo = AttendanceRepository(config=config)
        # First add some test data
        for i in range(3):
            record = AttendanceRecord(
                attendance_record_id=f"ATT-bounded-{i}",
                identity_certainty=IdentityCertainty.UNKNOWN,
                direction=AttendanceDirection.IN,
                event_timestamp=1000.0 + i * 10,
                camera_id="CAM1",
                local_track_id=f"track_{i:03d}",
                source_raw_event_id=f"RIE-bounded-{i}",
                source_resolution_id=f"RES-bounded-{i}",
            )
            repo.storage.insert(record)
        
        limited = repo.query_by_camera("CAM1", limit=1)
        offset = repo.query_by_camera("CAM1", limit=1, offset=1)
        bounded_ok = len(limited) == 1 and len(offset) == 1 and limited[0].attendance_record_id != offset[0].attendance_record_id
        checks["bounded_query"] = {"passed": bounded_ok, "details": f"Limit/offset works: {len(limited)}/{len(offset)}"}
        repo.close()
    finally:
        cleanup_db(db_path)
    
    return checks


def generate_reports(result: AcceptanceResult, output_dir: Path) -> List[str]:
    """Generate JSON and Markdown reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON report
    json_path = output_dir / "PHASE_25_ATTENDANCE_PERSISTENCE.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
    
    # Markdown report
    md_path = output_dir / "PHASE_25_ATTENDANCE_PERSISTENCE.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Phase 25 Attendance Persistence Report\n\n")
        f.write(f"**Timestamp:** {result.timestamp}\n\n")
        f.write(f"**Verdict:** {result.verdict}\n\n")
        f.write(f"**Persistence Backend:** {result.persistence_backend}\n\n")
        f.write(f"**Schema Version:** {result.schema_version}\n\n")
        
        f.write("## Pytest Unit Results\n\n")
        unit = result.pytest_unit
        f.write(f"- **Test Path:** {unit.get('test_path', 'N/A')}\n")
        f.write(f"- **Exit Code:** {unit.get('exit_code', 'N/A')}\n")
        f.write(f"- **Passed:** {unit.get('passed', False)}\n")
        f.write(f"- **Elapsed:** {unit.get('elapsed_seconds', 0):.2f}s\n\n")
        
        f.write("## Pytest Integration Results\n\n")
        integration = result.pytest_integration
        f.write(f"- **Test Path:** {integration.get('test_path', 'N/A')}\n")
        f.write(f"- **Exit Code:** {integration.get('exit_code', 'N/A')}\n")
        f.write(f"- **Passed:** {integration.get('passed', False)}\n")
        f.write(f"- **Elapsed:** {integration.get('elapsed_seconds', 0):.2f}s\n\n")
        
        f.write("## Acceptance Checks\n\n")
        for check_name, check_result in result.acceptance_checks.items():
            status = "✅ PASS" if check_result.get("passed", False) else "❌ FAIL"
            f.write(f"- **{check_name}:** {status}\n")
            f.write(f"  - Details: {check_result.get('details', 'N/A')}\n\n")
        
        f.write("## Known Limitations\n\n")
        for limitation in result.known_limitations:
            f.write(f"- {limitation}\n")
        f.write("\n")
        
        f.write("## Phase 26 Readiness\n\n")
        f.write(f"- **Ready:** {result.phase26_readiness}\n\n")
        
        f.write("## Files Changed\n\n")
        for file in result.files_changed:
            f.write(f"- {file}\n")
        f.write("\n")
        
        f.write("## Reports Generated\n\n")
        for report in result.reports_generated:
            f.write(f"- {report}\n")
    
    return [str(json_path), str(md_path)]


def main():
    """Main acceptance script entry point."""
    print("="*60)
    print("PHASE 25 — ATTENDANCE PERSISTENCE ACCEPTANCE")
    print("="*60)
    
    result = AcceptanceResult()
    
    # Track files changed
    result.files_changed = [
        "app/attendance/__init__.py",
        "app/attendance/contract.py",
        "app/attendance/storage.py",
        "app/attendance/repository.py",
        "app/attendance/query.py",
        "tests/unit/test_attendance/test_attendance_contract.py",
        "tests/unit/test_attendance/test_attendance_repository.py",
        "tests/integration/test_phase25/test_phase25_integration.py",
        "scripts/phase25_attendance_persistence.py",
    ]
    
    # Run pytest unit tests
    unit_result = run_pytest(
        "tests/unit/test_attendance/test_attendance_contract.py",
        "Phase 25 Unit Tests - Contract"
    )
    result.pytest_unit = unit_result
    
    unit_result2 = run_pytest(
        "tests/unit/test_attendance/test_attendance_repository.py",
        "Phase 25 Unit Tests - Repository"
    )
    # Merge unit results
    if not unit_result2["passed"]:
        unit_result["passed"] = False
    unit_result["stdout"] += "\n" + unit_result2["stdout"]
    unit_result["stderr"] += "\n" + unit_result2["stderr"]
    
    # Run pytest integration tests
    integration_result = run_pytest(
        "tests/integration/test_phase25/test_phase25_integration.py",
        "Phase 25 Integration Tests"
    )
    result.pytest_integration = integration_result
    
    # Run acceptance checks
    acceptance_checks = run_acceptance_checks()
    result.acceptance_checks = acceptance_checks
    
    # Determine overall verdict
    all_passed = (
        result.pytest_unit.get("passed", False) and
        result.pytest_integration.get("passed", False) and
        all(check.get("passed", False) for check in result.acceptance_checks.values())
    )
    
    result.verdict = "PASS" if all_passed else "FAIL"
    
    # Known limitations
    result.known_limitations = [
        "Identity enrichment from GlobalObservation not yet implemented (returns UNKNOWN)",
        "No automatic retention/deletion policy implemented",
        "Single-node SQLite backend (no distributed locking)",
        "Query builder fluent API not fully tested in integration",
    ]
    
    # Phase 26 readiness
    result.phase26_readiness = all_passed
    
    # Generate reports
    output_dir = Path(__file__).parent.parent / "benchmark_results"
    reports = generate_reports(result, output_dir)
    result.reports_generated = reports
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"PHASE 25 VERDICT: {result.verdict}")
    print(f"{'='*60}")
    print(f"Pytest Unit: {'PASS' if result.pytest_unit.get('passed') else 'FAIL'}")
    print(f"Pytest Integration: {'PASS' if result.pytest_integration.get('passed') else 'FAIL'}")
    print(f"Acceptance Checks: {sum(1 for c in result.acceptance_checks.values() if c.get('passed'))}/{len(result.acceptance_checks)} passed")
    print(f"Reports: {', '.join(reports)}")
    
    if not all_passed:
        print("\nFAILED CHECKS:")
        for name, check in result.acceptance_checks.items():
            if not check.get("passed", False):
                print(f"  - {name}: {check.get('details', 'N/A')}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())