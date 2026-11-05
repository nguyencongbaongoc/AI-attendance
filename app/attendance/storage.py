"""
Phase 25 — Attendance Storage Backend.

SQLite-based persistence layer for AttendanceRecord.
Supports insert, idempotent insert, query, chronological retrieval, filtering.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field
from app.attendance.contract import AttendanceRecord, validate_attendance_record

# Shared connection for SQLite WAL mode
_global_connection: Optional[sqlite3.Connection] = None
_global_connection_lock = threading.Lock()


def _get_attendance_db_path() -> Path:
    """Get the canonical attendance database path.
    
    Always returns <repo_root>/app/data/attendance.db regardless of CWD.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "app" / "data" / "attendance.db"


def migrate_attendance_schema(db_path: str) -> None:
    """Ensure evidence URL columns exist in the attendance table (idempotent)."""
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        # Verify table exists first
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attendance_records'")
        if not cursor.fetchone():
            return

        cursor.execute("PRAGMA table_info(attendance_records)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        required_columns = [
            ("snapshot_face_url", "TEXT"),
            ("snapshot_scene_url", "TEXT"),
            ("video_clip_url", "TEXT"),
        ]

        for col_name, col_type in required_columns:
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE attendance_records ADD COLUMN {col_name} {col_type}")
        conn.commit()


@dataclass
class StorageConfig:
    """Configuration for attendance storage."""
    database_path: Path = field(default_factory=_get_attendance_db_path)
    enable_wal: bool = True
    foreign_keys: bool = True
    busy_timeout_ms: int = 5000


class AttendanceStorage:
    """
    SQLite-based attendance record storage.
    
    Provides:
    - Idempotent insert (by source_resolution_id)
    - Query by various filters
    - Chronological retrieval
    - Deterministic ordering
    - Transaction support
    - Thread-safe operations
    """
    
    SCHEMA_VERSION = 1
    
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS attendance_records (
        -- Primary key
        attendance_record_id TEXT PRIMARY KEY,
        
        -- Identity
        identity_certainty TEXT NOT NULL,
        identity_candidate TEXT,
        identity_confidence REAL NOT NULL DEFAULT 0.0,
        identity_evidence_ref TEXT,
        
        -- NEW: Explicit evidence references (P3.9)
        face_evidence_ref TEXT,
        body_evidence_ref TEXT,
        face_quality REAL NOT NULL DEFAULT 0.0,
        body_quality REAL NOT NULL DEFAULT 0.0,
        association_method TEXT NOT NULL DEFAULT '',
        conflict_flag BOOLEAN NOT NULL DEFAULT 0,
        provisional_person_id TEXT,
        identity_state TEXT NOT NULL DEFAULT 'unknown',
        
        -- Phase 17: Evidence storage URIs (relative paths under /static/evidence)
        snapshot_face_url TEXT,
        snapshot_scene_url TEXT,
        video_clip_url TEXT,
        
        -- Event details
        direction TEXT NOT NULL,
        event_timestamp REAL NOT NULL,
        event_frame_index INTEGER NOT NULL DEFAULT -1,
        
        -- Camera and track
        camera_id TEXT NOT NULL,
        local_track_id TEXT NOT NULL,
        global_observation_id TEXT,
        
        -- Source references (provenance)
        source_raw_event_id TEXT NOT NULL,
        source_resolution_id TEXT NOT NULL UNIQUE,  -- Idempotency key
        source_crossing_event_id TEXT,
        
        -- Geometry provenance
        geometry_version INTEGER NOT NULL DEFAULT 0,
        geometry_config_hash TEXT NOT NULL DEFAULT '',
        
        -- Resolver provenance
        resolver_version TEXT NOT NULL DEFAULT '1.0',
        resolver_config_hash TEXT NOT NULL DEFAULT '',
        
        -- Derived state
        previous_state TEXT NOT NULL,
        new_state TEXT NOT NULL,
        
        -- NEW: Metadata fields (P1.2c)
        stream_epoch INTEGER NOT NULL DEFAULT 0,
        pts INTEGER NOT NULL DEFAULT 0,
        time_base_num INTEGER NOT NULL DEFAULT 1,
        time_base_den INTEGER NOT NULL DEFAULT 90000,
        capture_timestamp REAL NOT NULL DEFAULT 0.0,
        processing_timestamp REAL NOT NULL DEFAULT 0.0,
        model_version TEXT NOT NULL DEFAULT '',
        enrollment_version TEXT NOT NULL DEFAULT '',
        
        -- Versioning
        attendance_schema_version TEXT NOT NULL DEFAULT '1.1',
        created_at TEXT NOT NULL,
        persisted_at TEXT NOT NULL,
        
        -- Indexes for common queries
        CONSTRAINT chk_direction CHECK (direction IN ('in', 'out')),
        CONSTRAINT chk_identity_certainty CHECK (identity_certainty IN ('known', 'unknown', 'ambiguous', 'insufficient')),
        CONSTRAINT chk_previous_state CHECK (previous_state IN ('unknown', 'inside', 'outside')),
        CONSTRAINT chk_new_state CHECK (new_state IN ('unknown', 'inside', 'outside')),
        CONSTRAINT chk_schema_version CHECK (attendance_schema_version IN ('1.0', '1.1')),
        CONSTRAINT chk_event_timestamp CHECK (event_timestamp >= 0),
        CONSTRAINT chk_geometry_version CHECK (geometry_version >= 0),
        CONSTRAINT chk_identity_state CHECK (identity_state IN ('unknown', 'candidate', 'provisional', 'confirmed', 'conflict', 'reacquired')),
        CONSTRAINT chk_association_method CHECK (association_method IN ('', 'fused', 'face_only', 'body_only', 'geometric')),
        CONSTRAINT chk_face_quality CHECK (face_quality >= 0.0 AND face_quality <= 1.0),
        CONSTRAINT chk_body_quality CHECK (body_quality >= 0.0 AND body_quality <= 1.0)
    );
    """
    
    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_attendance_camera_id ON attendance_records(camera_id);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_local_track_id ON attendance_records(local_track_id);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_global_observation_id ON attendance_records(global_observation_id);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_event_timestamp ON attendance_records(event_timestamp);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_direction ON attendance_records(direction);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_source_raw_event_id ON attendance_records(source_raw_event_id);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_source_resolution_id ON attendance_records(source_resolution_id);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_camera_timestamp ON attendance_records(camera_id, event_timestamp);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_track_timestamp ON attendance_records(local_track_id, event_timestamp);",
        # NEW indexes for GIS fields
        "CREATE INDEX IF NOT EXISTS idx_attendance_identity_candidate ON attendance_records(identity_candidate);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_identity_state ON attendance_records(identity_state);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_conflict_flag ON attendance_records(conflict_flag);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_face_evidence_ref ON attendance_records(face_evidence_ref);",
        "CREATE INDEX IF NOT EXISTS idx_attendance_body_evidence_ref ON attendance_records(body_evidence_ref);",
    ]
    
    def __init__(self, config: Optional[StorageConfig] = None):
        self.config = config or StorageConfig()
        self._local = threading.local()
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get shared database connection with WAL mode enabled.
        
        Uses a single global connection with check_same_thread=False to allow
        concurrent access from multiple threads while maintaining WAL mode.
        """
        global _global_connection
        with _global_connection_lock:
            if _global_connection is None:
                db_path = Path(self.config.database_path)
                db_path.parent.mkdir(parents=True, exist_ok=True)
                
                conn = sqlite3.connect(
                    str(db_path),
                    check_same_thread=False,
                    timeout=self.config.busy_timeout_ms / 1000.0,
                )
                conn.row_factory = sqlite3.Row
                
                if self.config.enable_wal:
                    conn.execute("PRAGMA journal_mode=WAL;")
                if self.config.foreign_keys:
                    conn.execute("PRAGMA foreign_keys=ON;")
                conn.execute(f"PRAGMA busy_timeout={self.config.busy_timeout_ms};")
                conn.execute("PRAGMA synchronous=NORMAL;")
                
                _global_connection = conn
            
            return _global_connection
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        # Run migration for existing databases (idempotent)
        migrate_attendance_schema(str(self.config.database_path))
        
        conn = self._get_connection()
        with self._transaction(conn) as cursor:
            cursor.execute(self.CREATE_TABLE_SQL)
            for index_sql in self.CREATE_INDEXES_SQL:
                cursor.execute(index_sql)
            
            # Create schema version table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
            """)
            
            # Check/set schema version
            cursor.execute("SELECT version FROM schema_version WHERE version = ?", (self.SCHEMA_VERSION,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))",
                    (self.SCHEMA_VERSION,)
                )
    
    @contextmanager
    def _transaction(self, conn: Optional[sqlite3.Connection] = None):
        """Context manager for database transactions."""
        if conn is None:
            conn = self._get_connection()
        
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    
    def close(self) -> None:
        """Close the database connection.
        
        Note: With global connection, we don't actually close it here
        as it's shared across all instances. The connection will be
        closed when the application shuts down.
        """
        # With global shared connection, we don't close per-instance
        # The global connection cleanup should happen at app shutdown
        pass
    
    def __enter__(self) -> "AttendanceStorage":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    def insert(self, record: AttendanceRecord) -> bool:
        """
        Insert an attendance record.
        
        Returns True if inserted, False if duplicate (idempotent).
        Raises ValueError if record is invalid.
        """
        # Validate record
        error = validate_attendance_record(record)
        if error:
            raise ValueError(f"Invalid attendance record: {error}")
        
        conn = self._get_connection()
        with self._transaction(conn) as cursor:
            try:
                cursor.execute("""
                    INSERT INTO attendance_records (
                        attendance_record_id,
                        identity_certainty,
                        identity_candidate,
                        identity_confidence,
                        identity_evidence_ref,
                        face_evidence_ref,
                        body_evidence_ref,
                        face_quality,
                        body_quality,
                        association_method,
                        conflict_flag,
                        provisional_person_id,
                        identity_state,
                        direction,
                        event_timestamp,
                        event_frame_index,
                        camera_id,
                        local_track_id,
                        global_observation_id,
                        source_raw_event_id,
                        source_resolution_id,
                        source_crossing_event_id,
                        geometry_version,
                        geometry_config_hash,
                        resolver_version,
                        resolver_config_hash,
                        previous_state,
                        new_state,
                        stream_epoch,
                        pts,
                        time_base_num,
                        time_base_den,
                        capture_timestamp,
                        processing_timestamp,
                        model_version,
                        enrollment_version,
                        attendance_schema_version,
                        created_at,
                        persisted_at,
                        -- Phase 17: Evidence storage URIs
                        snapshot_face_url,
                        snapshot_scene_url,
                        video_clip_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.attendance_record_id,
                    record.identity_certainty.value if hasattr(record.identity_certainty, 'value') else record.identity_certainty,
                    record.identity_candidate,
                    record.identity_confidence,
                    record.identity_evidence_ref,
                    record.face_evidence_ref,
                    record.body_evidence_ref,
                    record.face_quality,
                    record.body_quality,
                    record.association_method,
                    record.conflict_flag,
                    record.provisional_person_id,
                    record.identity_state,
                    record.direction.value if hasattr(record.direction, 'value') else record.direction,
                    record.event_timestamp,
                    record.event_frame_index,
                    record.camera_id,
                    record.local_track_id,
                    record.global_observation_id,
                    record.source_raw_event_id,
                    record.source_resolution_id,
                    record.source_crossing_event_id,
                    record.geometry_version,
                    record.geometry_config_hash,
                    record.resolver_version,
                    record.resolver_config_hash,
record.previous_state,
                    record.new_state,
                    record.stream_epoch,
                    record.pts,
                    record.time_base.numerator,
                    record.time_base.denominator,
                    record.capture_timestamp,
                    record.processing_timestamp,
                    record.model_version,
                    record.enrollment_version,
                    record.attendance_schema_version,
                    record.created_at,
                    record.persisted_at,
                    # Phase 17: Evidence storage URIs
                    record.snapshot_face_url,
                    record.snapshot_scene_url,
                    record.video_clip_url,
                ))
                return True
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed: attendance_records.source_resolution_id" in str(e):
                    # Duplicate source_resolution_id - idempotent
                    return False
                elif "UNIQUE constraint failed: attendance_records.attendance_record_id" in str(e):
                    # Duplicate attendance_record_id - also idempotent
                    return False
                raise
    
    def insert_many(self, records: List[AttendanceRecord]) -> Tuple[int, int]:
        """
        Insert multiple attendance records.
        
        Returns (inserted_count, duplicate_count).
        """
        inserted = 0
        duplicates = 0
        
        conn = self._get_connection()
        with self._transaction(conn) as cursor:
            for record in records:
                error = validate_attendance_record(record)
                if error:
                    raise ValueError(f"Invalid attendance record: {error}")
                
                try:
                    cursor.execute("""
                        INSERT INTO attendance_records (
                            attendance_record_id,
                            identity_certainty,
                            identity_candidate,
                            identity_confidence,
                            identity_evidence_ref,
                            face_evidence_ref,
                            body_evidence_ref,
                            face_quality,
                            body_quality,
                            association_method,
                            conflict_flag,
                            provisional_person_id,
                            identity_state,
                            direction,
                            event_timestamp,
                            event_frame_index,
                            camera_id,
                            local_track_id,
                            global_observation_id,
                            source_raw_event_id,
                            source_resolution_id,
                            source_crossing_event_id,
                            geometry_version,
                            geometry_config_hash,
                            resolver_version,
                            resolver_config_hash,
                            previous_state,
                            new_state,
                            stream_epoch,
                            pts,
                            time_base_num,
                            time_base_den,
                            capture_timestamp,
                            processing_timestamp,
                            model_version,
                            enrollment_version,
                            attendance_schema_version,
                            created_at,
                            persisted_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.attendance_record_id,
                        record.identity_certainty.value if hasattr(record.identity_certainty, 'value') else record.identity_certainty,
                        record.identity_candidate,
                        record.identity_confidence,
                        record.identity_evidence_ref,
                        record.face_evidence_ref,
                        record.body_evidence_ref,
                        record.face_quality,
                        record.body_quality,
                        record.association_method,
                        record.conflict_flag,
                        record.provisional_person_id,
                        record.identity_state,
                        record.direction.value if hasattr(record.direction, 'value') else record.direction,
                        record.event_timestamp,
                        record.event_frame_index,
                        record.camera_id,
                        record.local_track_id,
                        record.global_observation_id,
                        record.source_raw_event_id,
                        record.source_resolution_id,
                        record.source_crossing_event_id,
                        record.geometry_version,
                        record.geometry_config_hash,
                        record.resolver_version,
                        record.resolver_config_hash,
                        record.previous_state,
                        record.new_state,
                        record.stream_epoch,
                        record.pts,
                        record.time_base.numerator,
                        record.time_base.denominator,
                        record.capture_timestamp,
                        record.processing_timestamp,
                        record.model_version,
                        record.enrollment_version,
record.attendance_schema_version,
                        record.created_at,
                        record.persisted_at,
                        # Phase 17: Evidence storage URIs
                        record.snapshot_face_url,
                        record.snapshot_scene_url,
                        record.video_clip_url
                    ))
                    inserted += 1
                except sqlite3.IntegrityError as e:
                    if "UNIQUE constraint failed" in str(e):
                        duplicates += 1
                    else:
                        raise
        
        return inserted, duplicates
    
    def get_by_id(self, attendance_record_id: str) -> Optional[AttendanceRecord]:
        """Get attendance record by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM attendance_records WHERE attendance_record_id = ?",
                (attendance_record_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
            return None
        finally:
            cursor.close()
    
    def get_by_source_resolution_id(self, source_resolution_id: str) -> Optional[AttendanceRecord]:
        """Get attendance record by source resolution ID (idempotency key)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM attendance_records WHERE source_resolution_id = ?",
                (source_resolution_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
            return None
        finally:
            cursor.close()
    
    def exists_by_source_resolution_id(self, source_resolution_id: str) -> bool:
        """Check if a record exists for the given source resolution ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM attendance_records WHERE source_resolution_id = ?",
                (source_resolution_id,)
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()
    
    def _row_to_record(self, row: sqlite3.Row) -> AttendanceRecord:
        """Convert database row to AttendanceRecord."""
        from app.attendance.contract import IdentityCertainty, AttendanceDirection
        
        # Handle time_base
        time_base = Fraction(row["time_base_num"], row["time_base_den"]) if row["time_base_den"] != 0 else Fraction(1, 90000)
        
        return AttendanceRecord(
            attendance_record_id=row["attendance_record_id"],
            identity_certainty=IdentityCertainty(row["identity_certainty"]),
            identity_candidate=row["identity_candidate"],
            identity_confidence=row["identity_confidence"],
            identity_evidence_ref=row["identity_evidence_ref"],
            # NEW: Evidence fields
            face_evidence_ref=row["face_evidence_ref"],
            body_evidence_ref=row["body_evidence_ref"],
            face_quality=row["face_quality"],
            body_quality=row["body_quality"],
            association_method=row["association_method"],
            conflict_flag=bool(row["conflict_flag"]),
            provisional_person_id=row["provisional_person_id"],
            identity_state=row["identity_state"],
            direction=AttendanceDirection(row["direction"]),
            event_timestamp=row["event_timestamp"],
            event_frame_index=row["event_frame_index"],
            camera_id=row["camera_id"],
            local_track_id=row["local_track_id"],
            global_observation_id=row["global_observation_id"],
            source_raw_event_id=row["source_raw_event_id"],
            source_resolution_id=row["source_resolution_id"],
            source_crossing_event_id=row["source_crossing_event_id"],
            geometry_version=row["geometry_version"],
            geometry_config_hash=row["geometry_config_hash"],
            resolver_version=row["resolver_version"],
            resolver_config_hash=row["resolver_config_hash"],
            previous_state=row["previous_state"],
            new_state=row["new_state"],
            # NEW: Metadata fields
            stream_epoch=row["stream_epoch"],
            pts=row["pts"],
            time_base=time_base,
            capture_timestamp=row["capture_timestamp"],
            processing_timestamp=row["processing_timestamp"],
            model_version=row["model_version"],
            enrollment_version=row["enrollment_version"],
            attendance_schema_version=row["attendance_schema_version"],
            created_at=row["created_at"],
            persisted_at=row["persisted_at"],
            # Phase 17: Evidence storage URIs
            snapshot_face_url=row["snapshot_face_url"],
            snapshot_scene_url=row["snapshot_scene_url"],
            video_clip_url=row["video_clip_url"],
        )
    
    def query(
        self,
        camera_id: Optional[str] = None,
        local_track_id: Optional[str] = None,
        global_observation_id: Optional[str] = None,
        direction: Optional[str] = None,
        identity_certainty: Optional[str] = None,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order_by: str = "event_timestamp",
        order_desc: bool = False,
    ) -> List[AttendanceRecord]:
        """
        Query attendance records with filters.
        
        Args:
            camera_id: Filter by camera ID
            local_track_id: Filter by local track ID
            global_observation_id: Filter by global observation ID
            direction: Filter by direction ('in' or 'out')
            identity_certainty: Filter by identity certainty
            start_timestamp: Start of time range (inclusive) [start, end)
            end_timestamp: End of time range (exclusive) [start, end)
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Column to order by (event_timestamp, attendance_record_id, etc.)
            order_desc: Order descending if True
            
        Returns:
            List of AttendanceRecord objects
        """
        # Validate order_by to prevent SQL injection
        valid_order_columns = {
            "event_timestamp", "attendance_record_id", "camera_id", 
            "local_track_id", "direction", "created_at", "persisted_at"
        }
        if order_by not in valid_order_columns:
            order_by = "event_timestamp"
        
        # Build query
        conditions = []
        params = []
        
        if camera_id is not None:
            conditions.append("camera_id = ? COLLATE NOCASE")
            params.append(camera_id)
        
        if local_track_id is not None:
            conditions.append("local_track_id = ?")
            params.append(local_track_id)
        
        if global_observation_id is not None:
            conditions.append("global_observation_id = ?")
            params.append(global_observation_id)
        
        if direction is not None:
            if direction not in ("in", "out"):
                raise ValueError(f"Invalid direction: {direction}")
            conditions.append("direction = ?")
            params.append(direction)
        
        if identity_certainty is not None:
            if identity_certainty not in ("known", "unknown", "ambiguous", "insufficient"):
                raise ValueError(f"Invalid identity_certainty: {identity_certainty}")
            conditions.append("identity_certainty = ?")
            params.append(identity_certainty)
        
        if start_timestamp is not None:
            if start_timestamp < 0:
                raise ValueError("start_timestamp must be >= 0")
            conditions.append("event_timestamp >= ?")
            params.append(start_timestamp)
        
        if end_timestamp is not None:
            if end_timestamp < 0:
                raise ValueError("end_timestamp must be >= 0")
            conditions.append("event_timestamp < ?")
            params.append(end_timestamp)
        
        if start_timestamp is not None and end_timestamp is not None:
            if start_timestamp > end_timestamp:
                raise ValueError("start_timestamp must be <= end_timestamp")
            elif start_timestamp == end_timestamp:
                # Allow empty range [t, t) for exact timestamp queries
                pass
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        order_clause = f"ORDER BY {order_by} {'DESC' if order_desc else 'ASC'}"
        
        # Add secondary ordering for deterministic results
        if order_by != "attendance_record_id":
            order_clause += ", attendance_record_id ASC"
        
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        offset_clause = f"OFFSET {offset}" if offset > 0 else ""
        
        sql = f"""
            SELECT * FROM attendance_records
            {where_clause}
            {order_clause}
            {limit_clause}
            {offset_clause}
        """
        
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            cursor.close()
    
    def query_by_identity(
        self,
        identity_candidate: str,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[AttendanceRecord]:
        """Query attendance records by identity candidate."""
        conditions = ["identity_candidate = ?"]
        params = [identity_candidate]
        
        if start_timestamp is not None:
            conditions.append("event_timestamp >= ?")
            params.append(start_timestamp)
        
        if end_timestamp is not None:
            conditions.append("event_timestamp < ?")
            params.append(end_timestamp)
        
        where_clause = "WHERE " + " AND ".join(conditions)
        order_clause = "ORDER BY event_timestamp ASC, attendance_record_id ASC"
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        offset_clause = f"OFFSET {offset}" if offset > 0 else ""
        
        sql = f"""
            SELECT * FROM attendance_records
            {where_clause}
            {order_clause}
            {limit_clause}
            {offset_clause}
        """
        
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            cursor.close()
    
    def get_chronological_history(
        self,
        camera_id: Optional[str] = None,
        local_track_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[AttendanceRecord]:
        """Get chronological attendance history."""
        return self.query(
            camera_id=camera_id,
            local_track_id=local_track_id,
            order_by="event_timestamp",
            order_desc=False,
            limit=limit,
        )
    
    def get_latest_by_track(
        self,
        camera_id: str,
        local_track_id: str,
    ) -> Optional[AttendanceRecord]:
        """Get the latest attendance record for a specific track."""
        records = self.query(
            camera_id=camera_id,
            local_track_id=local_track_id,
            order_by="event_timestamp",
            order_desc=True,
            limit=1,
        )
        return records[0] if records else None
    
    def get_latest_by_global_observation(
        self,
        global_observation_id: str,
    ) -> Optional[AttendanceRecord]:
        """Get the latest attendance record for a global observation."""
        records = self.query(
            global_observation_id=global_observation_id,
            order_by="event_timestamp",
            order_desc=True,
            limit=1,
        )
        return records[0] if records else None
    
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
        conditions = []
        params = []
        
        if camera_id is not None:
            conditions.append("camera_id = ? COLLATE NOCASE")
            params.append(camera_id)
        
        if local_track_id is not None:
            conditions.append("local_track_id = ?")
            params.append(local_track_id)
        
        if global_observation_id is not None:
            conditions.append("global_observation_id = ?")
            params.append(global_observation_id)
        
        if direction is not None:
            conditions.append("direction = ?")
            params.append(direction)
        
        if identity_certainty is not None:
            conditions.append("identity_certainty = ?")
            params.append(identity_certainty)
        
        if start_timestamp is not None:
            conditions.append("event_timestamp >= ?")
            params.append(start_timestamp)
        
        if end_timestamp is not None:
            conditions.append("event_timestamp < ?")
            params.append(end_timestamp)
        
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        sql = f"SELECT COUNT(*) as count FROM attendance_records {where_clause}"
        
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row["count"] if row else 0
        finally:
            cursor.close()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            stats = {}
            
            # Total records
            cursor.execute("SELECT COUNT(*) as count FROM attendance_records")
            stats["total_records"] = cursor.fetchone()["count"]
            
            # By direction
            cursor.execute("""
                SELECT direction, COUNT(*) as count 
                FROM attendance_records 
                GROUP BY direction
            """)
            stats["by_direction"] = {row["direction"]: row["count"] for row in cursor.fetchall()}
            
            # By camera
            cursor.execute("""
                SELECT camera_id, COUNT(*) as count 
                FROM attendance_records 
                GROUP BY camera_id
            """)
            stats["by_camera"] = {row["camera_id"]: row["count"] for row in cursor.fetchall()}
            
            # By identity certainty
            cursor.execute("""
                SELECT identity_certainty, COUNT(*) as count 
                FROM attendance_records 
                GROUP BY identity_certainty
            """)
            stats["by_identity_certainty"] = {row["identity_certainty"]: row["count"] for row in cursor.fetchall()}
            
            # Date range
            cursor.execute("""
                SELECT MIN(event_timestamp) as min_ts, MAX(event_timestamp) as max_ts
                FROM attendance_records
            """)
            row = cursor.fetchone()
            stats["event_timestamp_range"] = {
                "min": row["min_ts"],
                "max": row["max_ts"],
            }
            
            return stats
        finally:
            cursor.close()
    
    def vacuum(self) -> None:
        """Vacuum the database to reclaim space."""
        conn = self._get_connection()
        conn.execute("VACUUM;")
    
    def backup(self, backup_path: str) -> None:
        """Create a backup of the database."""
        conn = self._get_connection()
        backup_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()


def close_global_connection() -> None:
    """Close the global shared database connection.
    
    Should be called at application shutdown.
    """
    global _global_connection
    with _global_connection_lock:
        if _global_connection is not None:
            try:
                _global_connection.close()
            except Exception:
                pass
            _global_connection = None


def create_attendance_storage(config: Optional[StorageConfig] = None) -> AttendanceStorage:
    """Factory function to create AttendanceStorage."""
    return AttendanceStorage(config)