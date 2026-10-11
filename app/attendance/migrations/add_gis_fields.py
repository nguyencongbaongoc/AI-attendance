"""
Phase 3 — Database Migration for GIS and Metadata Fields.

Adds new columns to attendance_records table and creates GIS tables.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _get_attendance_db_path() -> Path:
    """Get the canonical attendance database path.
    
    Always returns <repo_root>/app/data/attendance.db regardless of CWD.
    """
    # Migrations file is at app/attendance/migrations/, so go up 4 levels
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / "app" / "data" / "attendance.db"


@dataclass
class MigrationConfig:
    """Configuration for migration."""
    database_path: Path = _get_attendance_db_path()
    enable_wal: bool = True
    foreign_keys: bool = True
    busy_timeout_ms: int = 5000


class MigrationManager:
    """Manages database migrations for attendance system."""

    def __init__(self, config: Optional[MigrationConfig] = None):
        self.config = config or MigrationConfig()
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
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

            self._local.connection = conn

        return self._local.connection

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
        """Close the database connection."""
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            self._local.connection.close()
            self._local.connection = None

    def column_exists(self, table: str, column: str) -> bool:
        """Check if a column exists in a table."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            return column in columns
        finally:
            cursor.close()

    def table_exists(self, table: str) -> bool:
        """Check if a table exists."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()

    def run_migration(self) -> bool:
        """Run all pending migrations."""
        conn = self._get_connection()
        
        try:
            with self._transaction(conn) as cursor:
                # Phase 1: Add metadata columns to attendance_records
                self._add_metadata_columns(cursor)
                
                # Phase 2: Add GIS evidence columns to attendance_records
                self._add_gis_evidence_columns(cursor)
                
                # Phase 3: Create GIS tables
                self._create_gis_tables(cursor)
                
            print("All migrations applied successfully!")
            return True
            
        except Exception as e:
            print(f"Migration failed: {e}")
            raise

    def _add_metadata_columns(self, cursor: sqlite3.Cursor) -> None:
        """Add metadata columns to attendance_records table."""
        columns_to_add = [
            ("stream_epoch", "INTEGER NOT NULL DEFAULT 0"),
            ("pts", "INTEGER NOT NULL DEFAULT 0"),
            ("time_base_num", "INTEGER NOT NULL DEFAULT 1"),
            ("time_base_den", "INTEGER NOT NULL DEFAULT 90000"),
            ("capture_timestamp", "REAL NOT NULL DEFAULT 0.0"),
            ("processing_timestamp", "REAL NOT NULL DEFAULT 0.0"),
            ("model_version", "TEXT NOT NULL DEFAULT ''"),
            ("enrollment_version", "TEXT NOT NULL DEFAULT ''"),
        ]
        
        for column_name, column_def in columns_to_add:
            if not self.column_exists("attendance_records", column_name):
                print(f"Adding column: {column_name}")
                cursor.execute(f"ALTER TABLE attendance_records ADD COLUMN {column_name} {column_def}")
            else:
                print(f"Column already exists: {column_name}")

    def _add_gis_evidence_columns(self, cursor: sqlite3.Cursor) -> None:
        """Add GIS evidence columns to attendance_records table."""
        columns_to_add = [
            ("face_evidence_ref", "TEXT"),
            ("body_evidence_ref", "TEXT"),
            ("face_quality", "REAL NOT NULL DEFAULT 0.0"),
            ("body_quality", "REAL NOT NULL DEFAULT 0.0"),
            ("association_method", "TEXT NOT NULL DEFAULT ''"),
            ("conflict_flag", "BOOLEAN NOT NULL DEFAULT 0"),
            ("provisional_person_id", "TEXT"),
            ("identity_state", "TEXT NOT NULL DEFAULT 'unknown'"),
        ]
        
        for column_name, column_def in columns_to_add:
            if not self.column_exists("attendance_records", column_name):
                print(f"Adding column: {column_name}")
                cursor.execute(f"ALTER TABLE attendance_records ADD COLUMN {column_name} {column_def}")
            else:
                print(f"Column already exists: {column_name}")

        # Add new indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_attendance_identity_candidate ON attendance_records(identity_candidate);",
            "CREATE INDEX IF NOT EXISTS idx_attendance_identity_state ON attendance_records(identity_state);",
            "CREATE INDEX IF NOT EXISTS idx_attendance_conflict_flag ON attendance_records(conflict_flag);",
            "CREATE INDEX IF NOT EXISTS idx_attendance_face_evidence_ref ON attendance_records(face_evidence_ref);",
            "CREATE INDEX IF NOT EXISTS idx_attendance_body_evidence_ref ON attendance_records(body_evidence_ref);",
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)

    def _create_gis_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create Global Identity Service tables."""
        
        # global_persons table
        if not self.table_exists("global_persons"):
            print("Creating table: global_persons")
            cursor.execute("""
                CREATE TABLE global_persons (
                    person_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    face_embedding BLOB,
                    body_embedding BLOB,
                    evidence_score REAL DEFAULT 0.0,
                    camera_count INTEGER DEFAULT 0,
                    conflict_count INTEGER DEFAULT 0
                );
            """)
            
            # Indexes for global_persons
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_persons_state ON global_persons(state);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_global_persons_updated_at ON global_persons(updated_at);")
        else:
            print("Table already exists: global_persons")

        # track_global_identity table
        if not self.table_exists("track_global_identity"):
            print("Creating table: track_global_identity")
            cursor.execute("""
                CREATE TABLE track_global_identity (
                    camera_id TEXT NOT NULL,
                    local_track_id TEXT NOT NULL,
                    global_person_id TEXT NOT NULL,
                    identity_state TEXT NOT NULL,
                    face_similarity REAL,
                    body_similarity REAL,
                    assigned_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (camera_id, local_track_id),
                    FOREIGN KEY (global_person_id) REFERENCES global_persons(person_id)
                );
            """)
            
            # Indexes for track_global_identity
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_track_global_identity_person ON track_global_identity(global_person_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_track_global_identity_state ON track_global_identity(identity_state);")
        else:
            print("Table already exists: track_global_identity")

        # identity_conflicts table
        if not self.table_exists("identity_conflicts"):
            print("Creating table: identity_conflicts")
            cursor.execute("""
                CREATE TABLE identity_conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    person_id_1 TEXT NOT NULL,
                    person_id_2 TEXT NOT NULL,
                    conflict_type TEXT NOT NULL,
                    face_similarity REAL,
                    body_similarity REAL,
                    detected_at REAL NOT NULL,
                    resolved_at REAL,
                    resolution TEXT,
                    resolved_by TEXT
                );
            """)
            
            # Indexes for identity_conflicts
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_conflicts_person1 ON identity_conflicts(person_id_1);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_conflicts_person2 ON identity_conflicts(person_id_2);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_conflicts_type ON identity_conflicts(conflict_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_conflicts_detected_at ON identity_conflicts(detected_at);")
        else:
            print("Table already exists: identity_conflicts")

        # identity_evidence table
        if not self.table_exists("identity_evidence"):
            print("Creating table: identity_evidence")
            cursor.execute("""
                CREATE TABLE identity_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    global_person_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    local_track_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    quality_score REAL,
                    timestamp REAL NOT NULL,
                    frame_index INTEGER,
                    model_id TEXT,
                    model_sha256 TEXT,
                    FOREIGN KEY (global_person_id) REFERENCES global_persons(person_id)
                );
            """)
            
            # Indexes for identity_evidence
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_evidence_person ON identity_evidence(global_person_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_evidence_camera_track ON identity_evidence(camera_id, local_track_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_evidence_type ON identity_evidence(evidence_type);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_identity_evidence_timestamp ON identity_evidence(timestamp);")
        else:
            print("Table already exists: identity_evidence")

    def validate_migration(self) -> bool:
        """Validate that all migrations were applied correctly."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            # Check attendance_records columns
            cursor.execute("PRAGMA table_info(attendance_records)")
            columns = {row[1] for row in cursor.fetchall()}
            
            required_columns = {
                "stream_epoch", "pts", "time_base_num", "time_base_den",
                "capture_timestamp", "processing_timestamp", "model_version", "enrollment_version",
                "face_evidence_ref", "body_evidence_ref", "face_quality", "body_quality",
                "association_method", "conflict_flag", "provisional_person_id", "identity_state"
            }
            
            missing = required_columns - columns
            if missing:
                print(f"Missing columns in attendance_records: {missing}")
                return False
            
            # Check GIS tables
            required_tables = {"global_persons", "track_global_identity", "identity_conflicts", "identity_evidence"}
            for table in required_tables:
                if not self.table_exists(table):
                    print(f"Missing table: {table}")
                    return False
            
            print("Migration validation passed!")
            return True
            
        except Exception as e:
            print(f"Validation failed: {e}")
            return False
        finally:
            cursor.close()


def run_migration(config: Optional[MigrationConfig] = None) -> bool:
    """Run the Phase 3 database migration."""
    manager = MigrationManager(config)
    try:
        manager.run_migration()
        return manager.validate_migration()
    finally:
        manager.close()


def rollback_migration(config: Optional[MigrationConfig] = None) -> bool:
    """Rollback the Phase 3 database migration (DROP new columns/tables)."""
    manager = MigrationManager(config)
    conn = manager._get_connection()
    
    try:
        with manager._transaction(conn) as cursor:
            # Drop GIS tables
            for table in ["identity_evidence", "identity_conflicts", "track_global_identity", "global_persons"]:
                if manager.table_exists(table):
                    print(f"Dropping table: {table}")
                    cursor.execute(f"DROP TABLE {table}")
            
            # Note: SQLite doesn't support DROP COLUMN directly
            # For production, you would need to recreate the table
            print("Warning: Cannot drop columns from attendance_records in SQLite without table recreation")
            
        print("Rollback completed (tables dropped, columns preserved)")
        return True
        
    except Exception as e:
        print(f"Rollback failed: {e}")
        raise
    finally:
        manager.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        print("Running rollback...")
        rollback_migration()
    else:
        print("Running migration...")
        run_migration()