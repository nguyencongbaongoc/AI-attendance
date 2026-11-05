import sqlite3
from pathlib import Path

repo_root = Path('.').resolve()
db_path = repo_root / 'app' / 'data' / 'attendance.db'
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Drop and recreate the table with correct constraint
cursor.execute('DROP TABLE IF EXISTS attendance_records')
conn.commit()

# Recreate with correct constraint
sql = """CREATE TABLE IF NOT EXISTS attendance_records (
    attendance_record_id TEXT PRIMARY KEY,
    identity_certainty TEXT NOT NULL,
    identity_candidate TEXT,
    identity_confidence REAL NOT NULL DEFAULT 0.0,
    identity_evidence_ref TEXT,
    face_evidence_ref TEXT,
    body_evidence_ref TEXT,
    face_quality REAL NOT NULL DEFAULT 0.0,
    body_quality REAL NOT NULL DEFAULT 0.0,
    association_method TEXT NOT NULL DEFAULT '',
    conflict_flag BOOLEAN NOT NULL DEFAULT 0,
    provisional_person_id TEXT,
    identity_state TEXT NOT NULL DEFAULT 'unknown',
    snapshot_face_url TEXT,
    snapshot_scene_url TEXT,
    video_clip_url TEXT,
    direction TEXT NOT NULL,
    event_timestamp REAL NOT NULL,
    event_frame_index INTEGER NOT NULL DEFAULT -1,
    camera_id TEXT NOT NULL,
    local_track_id TEXT NOT NULL,
    global_observation_id TEXT,
    source_raw_event_id TEXT NOT NULL,
    source_resolution_id TEXT NOT NULL UNIQUE,
    source_crossing_event_id TEXT,
    geometry_version INTEGER NOT NULL DEFAULT 0,
    geometry_config_hash TEXT NOT NULL DEFAULT '',
    resolver_version TEXT NOT NULL DEFAULT '1.0',
    resolver_config_hash TEXT NOT NULL DEFAULT '',
    previous_state TEXT NOT NULL,
    new_state TEXT NOT NULL,
    stream_epoch INTEGER NOT NULL DEFAULT 0,
    pts INTEGER NOT NULL DEFAULT 0,
    time_base_num INTEGER NOT NULL DEFAULT 1,
    time_base_den INTEGER NOT NULL DEFAULT 90000,
    capture_timestamp REAL NOT NULL DEFAULT 0.0,
    processing_timestamp REAL NOT NULL DEFAULT 0.0,
    model_version TEXT NOT NULL DEFAULT '',
    enrollment_version TEXT NOT NULL DEFAULT '',
    attendance_schema_version TEXT NOT NULL DEFAULT '1.1',
    created_at TEXT NOT NULL,
    persisted_at TEXT NOT NULL,
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
);"""

cursor.execute(sql)
conn.commit()
print('Table recreated with correct constraint')