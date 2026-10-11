"""
Phase 37B — Parent Registry.

Persistent parent registry for mapping students to parents and Telegram chat IDs.
Supports one parent with multiple students, and multiple parents per student (if needed).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.attendance.policy_engine.contract import PolicyEvent

logger = logging.getLogger(__name__)


class LinkCodeStatus(str, Enum):
    """Status of a parent link code."""
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class NotificationPreference(str, Enum):
    """Notification preferences for a parent."""
    ALL = "all"                    # All notification types
    MORNING_ABSENCE_ONLY = "morning_absence_only"
    LONG_EXIT_ONLY = "long_exit_only"
    MISSING_CHECKOUT_ONLY = "missing_checkout_only"
    NONE = "none"                  # Disabled


@dataclass(frozen=True)
class Parent:
    """Parent record."""
    parent_id: str
    parent_name: str
    telegram_chat_id: Optional[str] = None
    telegram_enabled: bool = True
    notification_preferences: NotificationPreference = NotificationPreference.ALL
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        if not self.parent_id:
            raise ValueError("parent_id is required")
        if not self.parent_name:
            raise ValueError("parent_name is required")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "parent_name": self.parent_name,
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_enabled": self.telegram_enabled,
            "notification_preferences": self.notification_preferences.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Parent":
        return cls(
            parent_id=data["parent_id"],
            parent_name=data["parent_name"],
            telegram_chat_id=data.get("telegram_chat_id"),
            telegram_enabled=data.get("telegram_enabled", True),
            notification_preferences=NotificationPreference(data.get("notification_preferences", "all")),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat() + "Z"),
        )


@dataclass(frozen=True)
class StudentParentLink:
    """Link between a student and a parent."""
    link_id: str
    student_id: str
    parent_id: str
    relationship: str = "parent"  # parent, guardian, emergency_contact, etc.
    is_primary: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def __post_init__(self):
        if not self.link_id:
            raise ValueError("link_id is required")
        if not self.student_id:
            raise ValueError("student_id is required")
        if not self.parent_id:
            raise ValueError("parent_id is required")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "link_id": self.link_id,
            "student_id": self.student_id,
            "parent_id": self.parent_id,
            "relationship": self.relationship,
            "is_primary": self.is_primary,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StudentParentLink":
        return cls(
            link_id=data["link_id"],
            student_id=data["student_id"],
            parent_id=data["parent_id"],
            relationship=data.get("relationship", "parent"),
            is_primary=data.get("is_primary", False),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
        )


@dataclass(frozen=True)
class LinkCode:
    """Parent linking code for Telegram bot /start command."""
    code: str
    student_id: str
    parent_id: Optional[str] = None  # If pre-assigned to a parent
    status: LinkCodeStatus = LinkCodeStatus.ACTIVE
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    expires_at: Optional[str] = None
    used_at: Optional[str] = None
    used_by_chat_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.code:
            raise ValueError("code is required")
        if not self.student_id:
            raise ValueError("student_id is required")
    
    def is_valid(self) -> bool:
        """Check if link code is still valid."""
        if self.status != LinkCodeStatus.ACTIVE:
            return False
        if self.expires_at:
            try:
                expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                now = datetime.now(expires.tzinfo)
                if now > expires:
                    return False
            except ValueError:
                pass
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "student_id": self.student_id,
            "parent_id": self.parent_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "used_at": self.used_at,
            "used_by_chat_id": self.used_by_chat_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkCode":
        return cls(
            code=data["code"],
            student_id=data["student_id"],
            parent_id=data.get("parent_id"),
            status=LinkCodeStatus(data.get("status", "active")),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            expires_at=data.get("expires_at"),
            used_at=data.get("used_at"),
            used_by_chat_id=data.get("used_by_chat_id"),
        )


class ParentRegistry:
    """
    Persistent parent registry using SQLite.
    
    Provides:
    - Parent CRUD operations
    - Student-Parent linking
    - Link code generation and validation
    - Telegram chat_id mapping
    - Notification preference management
    """
    
    def __init__(self, db_path: str = "data/parent_registry.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()
    
    def close(self) -> None:
        """Close the registry - no persistent connections to close, but provided for interface consistency."""
        pass
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            # Disable WAL mode to avoid Windows file locking issues
            conn.execute("PRAGMA journal_mode=DELETE")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parents (
                    parent_id TEXT PRIMARY KEY,
                    parent_name TEXT NOT NULL,
                    telegram_chat_id TEXT,
                    telegram_enabled INTEGER DEFAULT 1,
                    notification_preferences TEXT DEFAULT 'all',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS student_parent_links (
                    link_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    relationship TEXT DEFAULT 'parent',
                    is_primary INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (parent_id) REFERENCES parents (parent_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS link_codes (
                    code TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    parent_id TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    used_at TEXT,
                    used_by_chat_id TEXT
                )
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_student ON student_parent_links (student_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_parent ON student_parent_links (parent_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codes_student ON link_codes (student_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_codes_status ON link_codes (status)")
            
            conn.commit()
    
    def _generate_id(self, prefix: str) -> str:
        """Generate a unique ID."""
        return f"{prefix}-{secrets.token_urlsafe(8)}"
    
    def _generate_link_code(self) -> str:
        """Generate a secure, non-guessable link code."""
        # Format: XXXX-XXXX (8 chars, alphanumeric)
        return f"{secrets.token_urlsafe(4).upper()}-{secrets.token_urlsafe(4).upper()}"
    
    # =========================================================================
    # PARENT OPERATIONS
    # =========================================================================
    
    def create_parent(
        self,
        parent_name: str,
        telegram_chat_id: Optional[str] = None,
        telegram_enabled: bool = True,
        notification_preferences: NotificationPreference = NotificationPreference.ALL,
    ) -> Parent:
        """Create a new parent record."""
        parent_id = self._generate_id("PAR")
        now = datetime.utcnow().isoformat() + "Z"
        
        parent = Parent(
            parent_id=parent_id,
            parent_name=parent_name,
            telegram_chat_id=telegram_chat_id,
            telegram_enabled=telegram_enabled,
            notification_preferences=notification_preferences,
            created_at=now,
            updated_at=now,
        )
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO parents (parent_id, parent_name, telegram_chat_id, telegram_enabled, notification_preferences, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    parent.parent_id,
                    parent.parent_name,
                    parent.telegram_chat_id,
                    1 if parent.telegram_enabled else 0,
                    parent.notification_preferences.value,
                    parent.created_at,
                    parent.updated_at,
                ))
                conn.commit()
        
        logger.info(f"Created parent: {parent.parent_id} ({parent.parent_name})")
        return parent
    
    def get_parent(self, parent_id: str) -> Optional[Parent]:
        """Get parent by ID."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM parents WHERE parent_id = ?", (parent_id,))
                row = cursor.fetchone()
                
                if row:
                    return Parent.from_dict(dict(row))
                return None
    
    def get_parent_by_chat_id(self, chat_id: str) -> Optional[Parent]:
        """Get parent by Telegram chat ID."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM parents WHERE telegram_chat_id = ?", (chat_id,))
                row = cursor.fetchone()
                
                if row:
                    return Parent.from_dict(dict(row))
                return None
    
    def update_parent(
        self,
        parent_id: str,
        parent_name: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        telegram_enabled: Optional[bool] = None,
        notification_preferences: Optional[NotificationPreference] = None,
    ) -> Optional[Parent]:
        """Update parent record."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Get current
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM parents WHERE parent_id = ?", (parent_id,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                current = Parent.from_dict(dict(row))
                
                # Build updated parent
                updated = Parent(
                    parent_id=current.parent_id,
                    parent_name=parent_name if parent_name is not None else current.parent_name,
                    telegram_chat_id=telegram_chat_id if telegram_chat_id is not None else current.telegram_chat_id,
                    telegram_enabled=telegram_enabled if telegram_enabled is not None else current.telegram_enabled,
                    notification_preferences=notification_preferences if notification_preferences is not None else current.notification_preferences,
                    created_at=current.created_at,
                    updated_at=datetime.utcnow().isoformat() + "Z",
                )
                
                conn.execute("""
                    UPDATE parents
                    SET parent_name = ?, telegram_chat_id = ?, telegram_enabled = ?, notification_preferences = ?, updated_at = ?
                    WHERE parent_id = ?
                """, (
                    updated.parent_name,
                    updated.telegram_chat_id,
                    1 if updated.telegram_enabled else 0,
                    updated.notification_preferences.value,
                    updated.updated_at,
                    parent_id,
                ))
                conn.commit()
        
        logger.info(f"Updated parent: {parent_id}")
        return updated
    
    def delete_parent(self, parent_id: str) -> bool:
        """Delete a parent and all associated links."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Delete links first
                conn.execute("DELETE FROM student_parent_links WHERE parent_id = ?", (parent_id,))
                # Delete parent
                cursor = conn.execute("DELETE FROM parents WHERE parent_id = ?", (parent_id,))
                conn.commit()
                return cursor.rowcount > 0
    
    def list_parents(self) -> List[Parent]:
        """List all parents."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM parents ORDER BY created_at")
                return [Parent.from_dict(dict(row)) for row in cursor.fetchall()]
    
    # =========================================================================
    # STUDENT-PARENT LINK OPERATIONS
    # =========================================================================
    
    def link_student_parent(
        self,
        student_id: str,
        parent_id: str,
        relationship: str = "parent",
        is_primary: bool = False,
    ) -> StudentParentLink:
        """Create a link between a student and a parent."""
        # Verify parent exists
        parent = self.get_parent(parent_id)
        if not parent:
            raise ValueError(f"Parent {parent_id} not found")
        
        link_id = self._generate_id("LNK")
        now = datetime.utcnow().isoformat() + "Z"
        
        link = StudentParentLink(
            link_id=link_id,
            student_id=student_id,
            parent_id=parent_id,
            relationship=relationship,
            is_primary=is_primary,
            created_at=now,
        )
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # If this is primary, unset other primary links for this student
                if is_primary:
                    conn.execute("""
                        UPDATE student_parent_links
                        SET is_primary = 0
                        WHERE student_id = ?
                    """, (student_id,))
                
                conn.execute("""
                    INSERT INTO student_parent_links (link_id, student_id, parent_id, relationship, is_primary, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    link.link_id,
                    link.student_id,
                    link.parent_id,
                    link.relationship,
                    1 if link.is_primary else 0,
                    link.created_at,
                ))
                conn.commit()
        
        logger.info(f"Linked student {student_id} to parent {parent_id} ({relationship})")
        return link
    
    def get_student_parents(self, student_id: str) -> List[Parent]:
        """Get all parents linked to a student."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT p.* FROM parents p
                    JOIN student_parent_links l ON p.parent_id = l.parent_id
                    WHERE l.student_id = ?
                    ORDER BY l.is_primary DESC, l.created_at
                """, (student_id,))
                return [Parent.from_dict(dict(row)) for row in cursor.fetchall()]
    
    def get_parent_students(self, parent_id: str) -> List[str]:
        """Get all student IDs linked to a parent."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT student_id FROM student_parent_links WHERE parent_id = ?",
                    (parent_id,)
                )
                return [row[0] for row in cursor.fetchall()]
    
    def get_student_primary_parent(self, student_id: str) -> Optional[Parent]:
        """Get the primary parent for a student."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT p.* FROM parents p
                    JOIN student_parent_links l ON p.parent_id = l.parent_id
                    WHERE l.student_id = ? AND l.is_primary = 1
                    LIMIT 1
                """, (student_id,))
                row = cursor.fetchone()
                if row:
                    return Parent.from_dict(dict(row))
                return None
    
    def unlink_student_parent(self, student_id: str, parent_id: str) -> bool:
        """Remove a student-parent link."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM student_parent_links WHERE student_id = ? AND parent_id = ?",
                    (student_id, parent_id)
                )
                conn.commit()
                return cursor.rowcount > 0
    
    # =========================================================================
    # LINK CODE OPERATIONS
    # =========================================================================
    
    def create_link_code(
        self,
        student_id: str,
        parent_id: Optional[str] = None,
        expires_in_hours: int = 24,
    ) -> LinkCode:
        """Create a new link code for parent linking."""
        code = self._generate_link_code()
        now = datetime.utcnow()
        expires_at = (now + timedelta(hours=expires_in_hours)).isoformat() + "Z"
        
        link_code = LinkCode(
            code=code,
            student_id=student_id,
            parent_id=parent_id,
            status=LinkCodeStatus.ACTIVE,
            created_at=now.isoformat() + "Z",
            expires_at=expires_at,
        )
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO link_codes (code, student_id, parent_id, status, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    link_code.code,
                    link_code.student_id,
                    link_code.parent_id,
                    link_code.status.value,
                    link_code.created_at,
                    link_code.expires_at,
                ))
                conn.commit()
        
        logger.info(f"Created link code {code} for student {student_id}")
        return link_code
    
    def validate_link_code(self, code: str, chat_id: str) -> Optional[LinkCode]:
        """Validate and consume a link code."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM link_codes WHERE code = ?", (code,))
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                link_code = LinkCode.from_dict(dict(row))
                
                if not link_code.is_valid():
                    return None
                
                # Mark as used
                now = datetime.utcnow().isoformat() + "Z"
                conn.execute("""
                    UPDATE link_codes
                    SET status = ?, used_at = ?, used_by_chat_id = ?
                    WHERE code = ?
                """, (LinkCodeStatus.USED.value, now, chat_id, code))
                conn.commit()
                
                # Return updated link code
                return LinkCode(
                    code=link_code.code,
                    student_id=link_code.student_id,
                    parent_id=link_code.parent_id,
                    status=LinkCodeStatus.USED,
                    created_at=link_code.created_at,
                    expires_at=link_code.expires_at,
                    used_at=now,
                    used_by_chat_id=chat_id,
                )
    
    def get_link_code(self, code: str) -> Optional[LinkCode]:
        """Get link code by code (without consuming)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM link_codes WHERE code = ?", (code,))
                row = cursor.fetchone()
                
                if row:
                    return LinkCode.from_dict(dict(row))
                return None
    
    def revoke_link_code(self, code: str) -> bool:
        """Revoke a link code."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "UPDATE link_codes SET status = ? WHERE code = ?",
                    (LinkCodeStatus.REVOKED.value, code)
                )
                conn.commit()
                return cursor.rowcount > 0
    
    def cleanup_expired_codes(self) -> int:
        """Clean up expired link codes. Returns count of cleaned codes."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.utcnow().isoformat() + "Z"
                cursor = conn.execute("""
                    UPDATE link_codes
                    SET status = ?
                    WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < ?
                """, (LinkCodeStatus.EXPIRED.value, now))
                conn.commit()
                return cursor.rowcount
    
    # =========================================================================
    # NOTIFICATION ROUTING
    # =========================================================================
    
    def get_notification_recipients(
        self,
        student_id: str,
        policy_type: str,
    ) -> List[Parent]:
        """
        Get all parents who should receive a notification for a student and policy type.
        
        Respects notification preferences.
        """
        parents = self.get_student_parents(student_id)
        recipients = []
        
        for parent in parents:
            if not parent.telegram_enabled:
                continue
            if not parent.telegram_chat_id:
                continue
            
            # Check notification preferences
            pref = parent.notification_preferences
            if pref == NotificationPreference.NONE:
                continue
            elif pref == NotificationPreference.ALL:
                recipients.append(parent)
            elif pref == NotificationPreference.MORNING_ABSENCE_ONLY and policy_type == "morning_absence":
                recipients.append(parent)
            elif pref == NotificationPreference.LONG_EXIT_ONLY and policy_type == "long_exit":
                recipients.append(parent)
            elif pref == NotificationPreference.MISSING_CHECKOUT_ONLY and policy_type == "missing_checkout":
                recipients.append(parent)
        
        return recipients
    
    def get_chat_id_for_student_policy(
        self,
        student_id: str,
        policy_type: str,
    ) -> List[str]:
        """Get all Telegram chat IDs for a student and policy type."""
        recipients = self.get_notification_recipients(student_id, policy_type)
        return [p.telegram_chat_id for p in recipients if p.telegram_chat_id]


def create_parent_registry(db_path: str = "data/parent_registry.db") -> ParentRegistry:
    """Factory function to create ParentRegistry."""
    return ParentRegistry(db_path)