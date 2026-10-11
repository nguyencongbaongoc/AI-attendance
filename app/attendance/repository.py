"""
Phase 25 — Attendance Repository.

High-level interface for persisting and querying attendance records from Phase 24 resolutions.
Handles the Phase 24 → Phase 25 integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.attendance.contract import (
    AttendanceRecord,
    AttendanceRecordCreationResult,
    create_attendance_record_from_resolution,
    generate_attendance_record_id,
    validate_attendance_record,
)
from app.attendance.storage import AttendanceStorage, StorageConfig, create_attendance_storage
from app.in_out.resolver_contract import ResolvedTransition, ResolutionResult


@dataclass
class PersistenceResult:
    """Result of persisting a ResolutionResult."""
    total_resolutions: int = 0
    transitions_persisted: int = 0
    duplicates_skipped: int = 0
    suppressed_skipped: int = 0
    rejected_skipped: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class AttendanceRepository:
    """
    High-level repository for attendance persistence and query.
    
    Bridges Phase 24 ResolutionResult to Phase 25 AttendanceRecord storage.
    """
    
    def __init__(self, storage: Optional[AttendanceStorage] = None, config: Optional[StorageConfig] = None):
        self.storage = storage or create_attendance_storage(config)
    
    def persist_resolution_result(self, result: ResolutionResult) -> PersistenceResult:
        """
        Persist all transitions from a Phase 24 ResolutionResult.
        
        Only actual transitions (not suppressed/rejected) are persisted.
        Idempotent: duplicate source_resolution_id will be skipped.
        
        Args:
            result: ResolutionResult from Phase 24 resolver
            
        Returns:
            PersistenceResult with statistics
        """
        persistence_result = PersistenceResult()
        persistence_result.total_resolutions = len(result.transitions)
        
        for transition in result.transitions:
            # Skip non-transitions
            if not transition.is_transition:
                resolution_status_str = transition.resolution_status.value if hasattr(transition.resolution_status, 'value') else transition.resolution_status
                if resolution_status_str == "suppressed":
                    persistence_result.suppressed_skipped += 1
                elif resolution_status_str == "rejected":
                    persistence_result.rejected_skipped += 1
                else:
                    persistence_result.suppressed_skipped += 1  # out_of_order, etc.
                continue
            
            # Create attendance record from resolution
            creation_result = create_attendance_record_from_resolution(transition)
            
            if not creation_result.success:
                persistence_result.errors.append(
                    f"Failed to create record for {transition.resolution_id}: {creation_result.error}"
                )
                continue
            
            record = creation_result.record
            
            # Persist (idempotent)
            try:
                inserted = self.storage.insert(record)
                if inserted:
                    persistence_result.transitions_persisted += 1
                else:
                    persistence_result.duplicates_skipped += 1
            except ValueError as e:
                persistence_result.errors.append(
                    f"Failed to persist record for {transition.resolution_id}: {e}"
                )
        
        return persistence_result
    
    def persist_single_resolution(self, transition: ResolvedTransition) -> AttendanceRecordCreationResult:
        """
        Persist a single ResolvedTransition.
        
        Args:
            transition: Single ResolvedTransition from Phase 24
            
        Returns:
            AttendanceRecordCreationResult with the created record or error
        """
        # Create attendance record
        creation_result = create_attendance_record_from_resolution(transition)
        
        if not creation_result.success:
            return creation_result
        
        record = creation_result.record
        
        # Persist (idempotent)
        try:
            inserted = self.storage.insert(record)
            if not inserted:
                # Duplicate - fetch existing
                existing = self.storage.get_by_source_resolution_id(transition.resolution_id)
                if existing:
                    return AttendanceRecordCreationResult.success_result(existing)
            return creation_result
        except ValueError as e:
            return AttendanceRecordCreationResult.failure_result(
                error=str(e),
                rejection_reason="persistence_error"
            )
    
    def get_by_resolution_id(self, resolution_id: str) -> Optional[AttendanceRecord]:
        """Get attendance record by Phase 24 resolution ID."""
        return self.storage.get_by_source_resolution_id(resolution_id)
    
    def get_by_id(self, attendance_record_id: str) -> Optional[AttendanceRecord]:
        """Get attendance record by attendance record ID."""
        return self.storage.get_by_id(attendance_record_id)

    def exists_by_resolution_id(self, resolution_id: str) -> bool:
        """Check if attendance record exists for a resolution ID."""
        return self.storage.exists_by_source_resolution_id(resolution_id)
    
    # Query methods (delegate to storage with explicit naming)
    
    def query_by_camera(
        self,
        camera_id: str,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by camera."""
        return self.storage.query(
            camera_id=camera_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            offset=offset,
        )
    
    def query_by_track(
        self,
        camera_id: str,
        local_track_id: str,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by camera and local track."""
        return self.storage.query(
            camera_id=camera_id,
            local_track_id=local_track_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            offset=offset,
        )
    
    def query_by_global_observation(
        self,
        global_observation_id: str,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by global observation ID."""
        return self.storage.query(
            global_observation_id=global_observation_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            offset=offset,
        )
    
    def query_by_direction(
        self,
        direction: str,
        camera_id: Optional[str] = None,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by direction."""
        return self.storage.query(
            direction=direction,
            camera_id=camera_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            offset=offset,
        )
    
    def query_by_identity(
        self,
        identity_candidate: str,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by identity candidate."""
        return self.storage.query_by_identity(
            identity_candidate=identity_candidate,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            limit=limit,
            offset=offset,
        )
    
    def query_by_time_range(
        self,
        start_timestamp: float,
        end_timestamp: float,
        camera_id: Optional[str] = None,
        direction: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by time range [start, end)."""
        return self.storage.query(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            camera_id=camera_id,
            direction=direction,
            limit=limit,
            offset=offset,
        )
    
    def get_chronological_history(
        self,
        camera_id: Optional[str] = None,
        local_track_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[AttendanceRecord]:
        """Get chronological attendance history."""
        return self.storage.get_chronological_history(
            camera_id=camera_id,
            local_track_id=local_track_id,
            limit=limit,
        )
    
    def get_latest_by_track(
        self,
        camera_id: str,
        local_track_id: str,
    ) -> Optional[AttendanceRecord]:
        """Get the latest attendance record for a specific track."""
        return self.storage.get_latest_by_track(camera_id, local_track_id)
    
    def get_latest_by_global_observation(
        self,
        global_observation_id: str,
    ) -> Optional[AttendanceRecord]:
        """Get the latest attendance record for a global observation."""
        return self.storage.get_latest_by_global_observation(global_observation_id)
    
    def get_current_state_by_track(
        self,
        camera_id: str,
        local_track_id: str,
    ) -> Optional[str]:
        """
        Get the current derived state (INSIDE/OUTSIDE/UNKNOWN) for a track.
        
        Returns the new_state of the latest attendance record for the track.
        """
        latest = self.get_latest_by_track(camera_id, local_track_id)
        if latest:
            return latest.new_state
        return None
    
    def get_current_state_by_global_observation(
        self,
        global_observation_id: str,
    ) -> Optional[str]:
        """
        Get the current derived state for a global observation.
        
        Returns the new_state of the latest attendance record.
        """
        latest = self.get_latest_by_global_observation(global_observation_id)
        if latest:
            return latest.new_state
        return None
    
    def count(
        self,
        camera_id: Optional[str] = None,
        local_track_id: Optional[str] = None,
        global_observation_id: Optional[str] = None,
        direction: Optional[str] = None,
        identity_certainty: Optional[str] = None,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
    ) -> int:
        """Count records matching filters."""
        return self.storage.count(
            camera_id=camera_id,
            local_track_id=local_track_id,
            global_observation_id=global_observation_id,
            direction=direction,
            identity_certainty=identity_certainty,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get repository statistics."""
        return self.storage.get_stats()
    
    def close(self) -> None:
        """Close the repository."""
        self.storage.close()
    
    def __enter__(self) -> "AttendanceRepository":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def create_attendance_repository(
    storage: Optional[AttendanceStorage] = None,
    config: Optional[StorageConfig] = None,
) -> AttendanceRepository:
    """Factory function to create AttendanceRepository."""
    return AttendanceRepository(storage, config)