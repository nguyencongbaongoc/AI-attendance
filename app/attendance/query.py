"""
Phase 25 — Attendance Query Utilities.

Additional query helpers and result formatting for attendance records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.attendance.contract import AttendanceRecord, AttendanceDirection, IdentityCertainty
from app.attendance.repository import AttendanceRepository


@dataclass
class AttendanceQueryResult:
    """Structured query result with metadata."""
    records: List[AttendanceRecord]
    total_count: int
    limit: Optional[int]
    offset: int
    filters_applied: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "total_count": self.total_count,
            "limit": self.limit,
            "offset": self.offset,
            "filters_applied": self.filters_applied,
        }


@dataclass
class AttendanceSummary:
    """Summary statistics for attendance records."""
    total_records: int
    in_count: int
    out_count: int
    by_camera: Dict[str, int]
    by_identity_certainty: Dict[str, int]
    by_direction: Dict[str, int]
    timestamp_range: Dict[str, Optional[float]]
    unique_tracks: int
    unique_cameras: int
    unique_global_observations: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_records": self.total_records,
            "in_count": self.in_count,
            "out_count": self.out_count,
            "by_camera": self.by_camera,
            "by_identity_certainty": self.by_identity_certainty,
            "by_direction": self.by_direction,
            "timestamp_range": self.timestamp_range,
            "unique_tracks": self.unique_tracks,
            "unique_cameras": self.unique_cameras,
            "unique_global_observations": self.unique_global_observations,
        }


class AttendanceQueryBuilder:
    """
    Fluent query builder for attendance records.
    
    Provides a chainable API for building complex queries.
    """
    
    def __init__(self, repository: AttendanceRepository):
        self.repository = repository
        self._camera_id: Optional[str] = None
        self._local_track_id: Optional[str] = None
        self._global_observation_id: Optional[str] = None
        self._direction: Optional[str] = None
        self._identity_certainty: Optional[str] = None
        self._identity_candidate: Optional[str] = None
        self._start_timestamp: Optional[float] = None
        self._end_timestamp: Optional[float] = None
        self._limit: Optional[int] = None
        self._offset: int = 0
        self._order_by: str = "event_timestamp"
        self._order_desc: bool = False
    
    def camera(self, camera_id: str) -> "AttendanceQueryBuilder":
        self._camera_id = camera_id
        return self
    
    def track(self, camera_id: str, local_track_id: str) -> "AttendanceQueryBuilder":
        self._camera_id = camera_id
        self._local_track_id = local_track_id
        return self
    
    def global_observation(self, global_observation_id: str) -> "AttendanceQueryBuilder":
        self._global_observation_id = global_observation_id
        return self
    
    def direction(self, direction: str) -> "AttendanceQueryBuilder":
        if direction not in ("in", "out"):
            raise ValueError(f"Invalid direction: {direction}")
        self._direction = direction
        return self
    
    def identity_certainty(self, certainty: str) -> "AttendanceQueryBuilder":
        if certainty not in ("known", "unknown", "ambiguous", "insufficient"):
            raise ValueError(f"Invalid identity_certainty: {certainty}")
        self._identity_certainty = certainty
        return self
    
    def identity_candidate(self, candidate: str) -> "AttendanceQueryBuilder":
        self._identity_candidate = candidate
        return self
    
    def time_range(self, start: float, end: float) -> "AttendanceQueryBuilder":
        if start < 0 or end < 0:
            raise ValueError("Timestamps must be >= 0")
        if start >= end:
            raise ValueError("start must be < end")
        self._start_timestamp = start
        self._end_timestamp = end
        return self
    
    def since(self, timestamp: float) -> "AttendanceQueryBuilder":
        if timestamp < 0:
            raise ValueError("Timestamp must be >= 0")
        self._start_timestamp = timestamp
        return self
    
    def until(self, timestamp: float) -> "AttendanceQueryBuilder":
        if timestamp < 0:
            raise ValueError("Timestamp must be >= 0")
        self._end_timestamp = timestamp
        return self
    
    def limit(self, limit: int) -> "AttendanceQueryBuilder":
        if limit < 1:
            raise ValueError("Limit must be >= 1")
        self._limit = limit
        return self
    
    def offset(self, offset: int) -> "AttendanceQueryBuilder":
        if offset < 0:
            raise ValueError("Offset must be >= 0")
        self._offset = offset
        return self
    
    def order_by(self, column: str, desc: bool = False) -> "AttendanceQueryBuilder":
        valid_columns = {
            "event_timestamp", "attendance_record_id", "camera_id", 
            "local_track_id", "direction", "created_at", "persisted_at"
        }
        if column not in valid_columns:
            raise ValueError(f"Invalid order_by column: {column}")
        self._order_by = column
        self._order_desc = desc
        return self
    
    def execute(self) -> List[AttendanceRecord]:
        """Execute the query and return records."""
        if self._identity_candidate:
            return self.repository.query_by_identity(
                identity_candidate=self._identity_candidate,
                start_timestamp=self._start_timestamp,
                end_timestamp=self._end_timestamp,
                limit=self._limit,
                offset=self._offset,
            )
        
        return self.repository.storage.query(
            camera_id=self._camera_id,
            local_track_id=self._local_track_id,
            global_observation_id=self._global_observation_id,
            direction=self._direction,
            identity_certainty=self._identity_certainty,
            start_timestamp=self._start_timestamp,
            end_timestamp=self._end_timestamp,
            limit=self._limit,
            offset=self._offset,
            order_by=self._order_by,
            order_desc=self._order_desc,
        )
    
    def execute_with_metadata(self) -> AttendanceQueryResult:
        """Execute the query and return structured result with metadata."""
        records = self.execute()
        
        # Get total count (without limit/offset)
        total_count = self.repository.count(
            camera_id=self._camera_id,
            local_track_id=self._local_track_id,
            global_observation_id=self._global_observation_id,
            direction=self._direction,
            identity_certainty=self._identity_certainty,
            start_timestamp=self._start_timestamp,
            end_timestamp=self._end_timestamp,
        )
        
        filters = {}
        if self._camera_id:
            filters["camera_id"] = self._camera_id
        if self._local_track_id:
            filters["local_track_id"] = self._local_track_id
        if self._global_observation_id:
            filters["global_observation_id"] = self._global_observation_id
        if self._direction:
            filters["direction"] = self._direction
        if self._identity_certainty:
            filters["identity_certainty"] = self._identity_certainty
        if self._identity_candidate:
            filters["identity_candidate"] = self._identity_candidate
        if self._start_timestamp is not None:
            filters["start_timestamp"] = self._start_timestamp
        if self._end_timestamp is not None:
            filters["end_timestamp"] = self._end_timestamp
        
        return AttendanceQueryResult(
            records=records,
            total_count=total_count,
            limit=self._limit,
            offset=self._offset,
            filters_applied=filters,
        )
    
    def count(self) -> int:
        """Get count of matching records."""
        return self.repository.count(
            camera_id=self._camera_id,
            local_track_id=self._local_track_id,
            global_observation_id=self._global_observation_id,
            direction=self._direction,
            identity_certainty=self._identity_certainty,
            start_timestamp=self._start_timestamp,
            end_timestamp=self._end_timestamp,
        )


def create_query_builder(repository: AttendanceRepository) -> AttendanceQueryBuilder:
    """Factory function to create a query builder."""
    return AttendanceQueryBuilder(repository)


def get_attendance_summary(repository: AttendanceRepository) -> AttendanceSummary:
    """Get a comprehensive summary of all attendance records."""
    stats = repository.get_stats()
    
    # Get unique counts
    all_records = repository.get_chronological_history(limit=None)
    
    unique_tracks = set()
    unique_cameras = set()
    unique_global_observations = set()
    
    for record in all_records:
        unique_tracks.add((record.camera_id, record.local_track_id))
        unique_cameras.add(record.camera_id)
        if record.global_observation_id:
            unique_global_observations.add(record.global_observation_id)
    
    return AttendanceSummary(
        total_records=stats["total_records"],
        in_count=stats["by_direction"].get("in", 0),
        out_count=stats["by_direction"].get("out", 0),
        by_camera=stats["by_camera"],
        by_identity_certainty=stats["by_identity_certainty"],
        by_direction=stats["by_direction"],
        timestamp_range=stats["event_timestamp_range"],
        unique_tracks=len(unique_tracks),
        unique_cameras=len(unique_cameras),
        unique_global_observations=len(unique_global_observations),
    )


def format_timestamp(timestamp: float) -> str:
    """Format a Unix timestamp as ISO 8601 UTC string."""
    return datetime.utcfromtimestamp(timestamp).isoformat() + "Z"


def parse_timestamp(iso_string: str) -> float:
    """Parse an ISO 8601 UTC string to Unix timestamp."""
    return datetime.fromisoformat(iso_string.replace("Z", "+00:00")).timestamp()


def records_to_timeline(records: List[AttendanceRecord]) -> List[Dict[str, Any]]:
    """
    Convert attendance records to a timeline format.
    
    Each entry contains the event and the resulting state.
    """
    timeline = []
    for record in records:
        timeline.append({
            "timestamp": record.event_timestamp,
            "timestamp_iso": format_timestamp(record.event_timestamp),
            "attendance_record_id": record.attendance_record_id,
            "camera_id": record.camera_id,
            "local_track_id": record.local_track_id,
            "global_observation_id": record.global_observation_id,
            "direction": record.direction.value,
            "previous_state": record.previous_state,
            "new_state": record.new_state,
            "identity_certainty": record.identity_certainty.value,
            "identity_candidate": record.identity_candidate,
            "source_resolution_id": record.source_resolution_id,
            "source_raw_event_id": record.source_raw_event_id,
        })
    return timeline


def get_daily_attendance_counts(
    repository: AttendanceRepository,
    camera_id: Optional[str] = None,
    days: int = 30,
) -> Dict[str, Dict[str, int]]:
    """
    Get daily attendance counts (IN/OUT) for the last N days.
    
    Returns dict mapping date string to {"in": count, "out": count}.
    """
    import time
    
    now = time.time()
    day_seconds = 86400
    start_time = now - (days * day_seconds)
    
    records = repository.query_by_time_range(
        start_timestamp=start_time,
        end_timestamp=now,
        camera_id=camera_id,
        limit=None,
    )
    
    daily_counts: Dict[str, Dict[str, int]] = {}
    
    for record in records:
        date_str = datetime.utcfromtimestamp(record.event_timestamp).strftime("%Y-%m-%d")
        if date_str not in daily_counts:
            daily_counts[date_str] = {"in": 0, "out": 0}
        daily_counts[date_str][record.direction.value] += 1
    
    return daily_counts


def get_track_state_history(
    repository: AttendanceRepository,
    camera_id: str,
    local_track_id: str,
) -> List[Dict[str, Any]]:
    """
    Get the complete state transition history for a track.
    
    Returns list of state changes with timestamps.
    """
    records = repository.query_by_track(camera_id, local_track_id)
    
    history = []
    for record in records:
        history.append({
            "timestamp": record.event_timestamp,
            "timestamp_iso": format_timestamp(record.event_timestamp),
            "direction": record.direction.value,
            "previous_state": record.previous_state,
            "new_state": record.new_state,
            "attendance_record_id": record.attendance_record_id,
            "source_resolution_id": record.source_resolution_id,
        })
    
    return history