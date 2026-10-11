"""
Phase 37C — Exit Session Persistence.

Persistent storage for exit sessions to survive application restarts.
Ensures that active >30-minute exit sessions are not lost on restart.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config.settings import load_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExitSession:
    """Persistent exit session record."""
    session_id: str
    student_id: str
    out_timestamp: float
    out_event_id: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    resolved_at: Optional[str] = None
    resolved_event_id: Optional[str] = None
    resolution_type: Optional[str] = None  # "short_exit", "long_exit", "timeout"
    is_active: bool = True
    
    def __post_init__(self):
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.student_id:
            raise ValueError("student_id is required")
        if not self.out_timestamp:
            raise ValueError("out_timestamp is required")
        if not self.out_event_id:
            raise ValueError("out_event_id is required")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "out_timestamp": self.out_timestamp,
            "out_event_id": self.out_event_id,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "resolved_event_id": self.resolved_event_id,
            "resolution_type": self.resolution_type,
            "is_active": self.is_active,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExitSession":
        return cls(
            session_id=data["session_id"],
            student_id=data["student_id"],
            out_timestamp=data["out_timestamp"],
            out_event_id=data["out_event_id"],
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            resolved_at=data.get("resolved_at"),
            resolved_event_id=data.get("resolved_event_id"),
            resolution_type=data.get("resolution_type"),
            is_active=data.get("is_active", True),
        )


class ExitSessionStore:
    """
    Persistent exit session store using SQLite.
    
    Provides:
    - Session creation on OUT event
    - Session resolution on IN event or timeout
    - Recovery of active sessions on restart
    - Cleanup of old resolved sessions
    """
    
    def __init__(self, db_path: str = "data/exit_sessions.db", cleanup_days: int = 30):
        self.db_path = db_path
        self.cleanup_days = cleanup_days
        self._lock = threading.RLock()
        self._init_db()
    
    def close(self) -> None:
        """Close the store - no persistent connections to close, but provided for interface consistency."""
        pass
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            # Disable WAL mode to avoid Windows file locking issues
            conn.execute("PRAGMA journal_mode=DELETE")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exit_sessions (
                    session_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    out_timestamp REAL NOT NULL,
                    out_event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_event_id TEXT,
                    resolution_type TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exit_student ON exit_sessions (student_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exit_active ON exit_sessions (is_active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exit_created ON exit_sessions (created_at)")
            
            conn.commit()
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        import secrets
        return f"EXIT-{secrets.token_urlsafe(12)}"
    
    def create_session(
        self,
        student_id: str,
        out_timestamp: float,
        out_event_id: str,
    ) -> ExitSession:
        """
        Create a new exit session.
        
        Args:
            student_id: Student identifier
            out_timestamp: Unix timestamp of OUT event
            out_event_id: Attendance event ID for the OUT
            
        Returns:
            Created ExitSession
        """
        session_id = self._generate_session_id()
        now = datetime.utcnow().isoformat() + "Z"
        
        session = ExitSession(
            session_id=session_id,
            student_id=student_id,
            out_timestamp=out_timestamp,
            out_event_id=out_event_id,
            created_at=now,
            is_active=True,
        )
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO exit_sessions (
                        session_id, student_id, out_timestamp, out_event_id,
                        created_at, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    session.session_id,
                    session.student_id,
                    session.out_timestamp,
                    session.out_event_id,
                    session.created_at,
                    1 if session.is_active else 0,
                ))
                conn.commit()
        
        logger.info(f"Created exit session {session_id} for student {student_id}")
        return session
    
    def get_active_session(self, student_id: str) -> Optional[ExitSession]:
        """Get active exit session for a student."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM exit_sessions
                    WHERE student_id = ? AND is_active = 1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (student_id,))
                row = cursor.fetchone()
                
                if row:
                    return ExitSession.from_dict(dict(row))
                return None
    
    def get_session(self, session_id: str) -> Optional[ExitSession]:
        """Get exit session by ID."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM exit_sessions WHERE session_id = ?", (session_id,))
                row = cursor.fetchone()
                
                if row:
                    return ExitSession.from_dict(dict(row))
                return None
    
    def get_all_active_sessions(self) -> List[ExitSession]:
        """Get all active exit sessions (for recovery on startup)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM exit_sessions
                    WHERE is_active = 1
                    ORDER BY created_at
                """)
                return [ExitSession.from_dict(dict(row)) for row in cursor.fetchall()]
    
    def resolve_session(
        self,
        session_id: str,
        resolved_event_id: str,
        resolution_type: str,
    ) -> bool:
        """
        Resolve an exit session.
        
        Args:
            session_id: Session to resolve
            resolved_event_id: Attendance event ID that resolved it (IN event)
            resolution_type: "short_exit", "long_exit", or "timeout"
            
        Returns:
            True if session was found and resolved
        """
        now = datetime.utcnow().isoformat() + "Z"
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE exit_sessions
                    SET is_active = 0, resolved_at = ?, resolved_event_id = ?, resolution_type = ?
                    WHERE session_id = ? AND is_active = 1
                """, (now, resolved_event_id, resolution_type, session_id))
                conn.commit()
                return cursor.rowcount > 0
    
    def resolve_session_by_student(
        self,
        student_id: str,
        resolved_event_id: str,
        resolution_type: str,
    ) -> Optional[ExitSession]:
        """
        Resolve the active exit session for a student.
        
        Returns:
            The resolved session, or None if no active session
        """
        session = self.get_active_session(student_id)
        if session:
            self.resolve_session(session.session_id, resolved_event_id, resolution_type)
            # Return updated session
            return self.get_session(session.session_id)
        return None
    
    def cleanup_old_sessions(self) -> int:
        """Clean up old resolved sessions. Returns count of deleted sessions."""
        cutoff = (datetime.utcnow() - timedelta(days=self.cleanup_days)).isoformat() + "Z"
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM exit_sessions
                    WHERE is_active = 0 AND resolved_at IS NOT NULL AND resolved_at < ?
                """, (cutoff,))
                conn.commit()
                return cursor.rowcount
    
    def get_stats(self) -> Dict[str, int]:
        """Get session statistics."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT is_active, COUNT(*) FROM exit_sessions
                    GROUP BY is_active
                """)
                stats = {f"active_{row[0]}": row[1] for row in cursor.fetchall()}
                
                cursor = conn.execute("""
                    SELECT resolution_type, COUNT(*) FROM exit_sessions
                    WHERE resolution_type IS NOT NULL
                    GROUP BY resolution_type
                """)
                for row in cursor.fetchall():
                    stats[f"resolved_{row[0]}"] = row[1]
                
                return stats


def create_exit_session_store(db_path: str = "data/exit_sessions.db", cleanup_days: int = 30) -> ExitSessionStore:
    """Factory function to create ExitSessionStore."""
    return ExitSessionStore(db_path, cleanup_days)


def create_exit_session_store_from_settings() -> ExitSessionStore:
    """Create ExitSessionStore from application settings."""
    settings = load_settings()
    return ExitSessionStore(
        db_path=settings.exit_session.db_path,
        cleanup_days=settings.exit_session.cleanup_days,
    )