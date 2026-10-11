"""
Phase 37B/37C — Telegram Bot Integration.

Telegram Bot for parent notifications.
Uses a single project bot token (configured via environment).
Sends private messages to individual parent chat_ids.

Phase 37C additions:
- Startup validation for TELEGRAM_BOT_TOKEN
- Controlled live test mechanism (TELEGRAM_LIVE_TEST)
- Secure token handling (never in logs/source)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp

from app.attendance.policy_engine.contract import PolicyEvent, PolicyType
from app.attendance.policy_engine.parent_registry import Parent, ParentRegistry, NotificationPreference
from app.config.settings import load_settings

logger = logging.getLogger(__name__)


class TelegramConfigError(Exception):
    """Raised when Telegram configuration is invalid."""
    pass


def validate_bot_token(token: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Telegram bot token format.
    
    Telegram bot tokens have format: <bot_id>:<auth_token>
    where bot_id is numeric and auth_token is alphanumeric with hyphens/underscores.
    
    Returns:
        (is_valid, error_message)
    """
    if not token:
        return False, "Token is empty"
    
    # Basic format check: numeric_id:alphanumeric_string
    pattern = r'^\d+:[A-Za-z0-9_-]{35,}$'
    if not re.match(pattern, token):
        return False, "Token format invalid (expected: <bot_id>:<auth_token>)"
    
    # Check bot_id is reasonable (Telegram bot IDs are typically 8-10 digits)
    bot_id_str = token.split(':')[0]
    try:
        bot_id = int(bot_id_str)
        if bot_id <= 0:
            return False, "Bot ID must be positive"
    except ValueError:
        return False, "Bot ID must be numeric"
    
    return True, None


def validate_chat_id(chat_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate Telegram chat ID format.
    
    Chat IDs can be:
    - Positive integers (private chats)
    - Negative integers (groups/supergroups)
    - Channel usernames (starting with @)
    
    Returns:
        (is_valid, error_message)
    """
    if not chat_id:
        return False, "Chat ID is empty"
    
    # Channel username
    if chat_id.startswith('@'):
        if len(chat_id) < 2:
            return False, "Invalid channel username"
        return True, None
    
    # Numeric chat ID
    try:
        chat_id_int = int(chat_id)
        if chat_id_int == 0:
            return False, "Chat ID cannot be zero"
    except ValueError:
        return False, "Chat ID must be numeric or @username"
    
    return True, None


class TelegramConfigError(Exception):
    """Raised when Telegram configuration is invalid."""
    pass


class TelegramSendStatus(str, Enum):
    """Status of a Telegram send attempt."""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    RETRY = "retry"
    FAILED = "failed"
    DISABLED = "disabled"
    NO_RECIPIENT = "no_recipient"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True)
class NotificationRecord:
    """Record of a notification send attempt."""
    notification_id: str
    idempotency_key: str
    event_id: str
    student_id: str
    parent_id: str
    telegram_chat_id: str
    notification_type: str
    message: str
    status: TelegramSendStatus = TelegramSendStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    sent_at: Optional[str] = None
    last_error: Optional[str] = None
    last_attempt_at: Optional[str] = None
    
    def __post_init__(self):
        if not self.notification_id:
            raise ValueError("notification_id is required")
        if not self.idempotency_key:
            raise ValueError("idempotency_key is required")
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.student_id:
            raise ValueError("student_id is required")
        if not self.parent_id:
            raise ValueError("parent_id is required")
        if not self.telegram_chat_id:
            raise ValueError("telegram_chat_id is required")
        if not self.notification_type:
            raise ValueError("notification_type is required")
        if not self.message:
            raise ValueError("message is required")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "idempotency_key": self.idempotency_key,
            "event_id": self.event_id,
            "student_id": self.student_id,
            "parent_id": self.parent_id,
            "telegram_chat_id": self.telegram_chat_id,
            "notification_type": self.notification_type,
            "message": self.message,
            "status": self.status.value,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
            "sent_at": self.sent_at,
            "last_error": self.last_error,
            "last_attempt_at": self.last_attempt_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NotificationRecord":
        return cls(
            notification_id=data["notification_id"],
            idempotency_key=data["idempotency_key"],
            event_id=data["event_id"],
            student_id=data["student_id"],
            parent_id=data["parent_id"],
            telegram_chat_id=data["telegram_chat_id"],
            notification_type=data["notification_type"],
            message=data["message"],
            status=TelegramSendStatus(data.get("status", "pending")),
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 3),
            created_at=data.get("created_at", datetime.utcnow().isoformat() + "Z"),
            sent_at=data.get("sent_at"),
            last_error=data.get("last_error"),
            last_attempt_at=data.get("last_attempt_at"),
        )


class TelegramBot:
    """
    Telegram Bot client for sending notifications.
    
    Uses a single bot token (from environment variable TELEGRAM_BOT_TOKEN).
    Sends private messages to individual parent chat_ids.
    
    Phase 37C: Includes startup validation and controlled live test support.
    """
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        api_base_url: str = "https://api.telegram.org/bot",
        timeout: int = 30,
        validate_on_init: bool = True,
        strict_validation: bool = False,
    ):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        
        # Startup validation
        if validate_on_init:
            self._validate_startup_config(strict=strict_validation)
        
        self.api_base_url = api_base_url
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Rate limiting
        self._last_send_time: Dict[str, float] = {}  # chat_id -> timestamp
        self._min_interval_seconds = 1.0  # Minimum 1 second between messages to same chat
        
        # Bot info cache
        self._bot_info: Optional[Dict[str, Any]] = None
        
        # Live test configuration
        settings = load_settings()
        self._live_test_enabled = settings.telegram.live_test_enabled
        self._live_test_chat_id = settings.telegram.live_test_chat_id
    
    def _validate_startup_config(self, strict: bool = False) -> None:
        """Validate Telegram configuration at startup.
        
        Args:
            strict: If True, raise exception on invalid token. If False, only warn.
        """
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured - Telegram notifications disabled")
            return
        
        # Validate token format
        is_valid, error = validate_bot_token(self.bot_token)
        if not is_valid:
            logger.error(f"Invalid TELEGRAM_BOT_TOKEN format: {error}")
            if strict:
                raise TelegramConfigError(f"Invalid TELEGRAM_BOT_TOKEN: {error}")
            else:
                logger.warning("Token format validation failed but continuing (strict=False)")
        
        logger.info("TELEGRAM_BOT_TOKEN format validated successfully")
    
    async def validate_token_live(self) -> Tuple[bool, Optional[str]]:
        """
        Validate token by making a live API call to Telegram.
        
        Returns:
            (is_valid, error_message)
        """
        if not self.bot_token:
            return False, "Bot token not configured"
        
        try:
            bot_info = await self.get_me()
            if bot_info:
                logger.info(f"Telegram bot validated: @{bot_info.get('username', 'unknown')} (ID: {bot_info.get('id')})")
                return True, None
            else:
                return False, "Failed to get bot info from Telegram API"
        except Exception as e:
            logger.error(f"Live token validation failed: {e}")
            return False, str(e)
    
    async def send_live_test_message(self, chat_id: Optional[str] = None, message: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Send a controlled live test message.
        
        Only works when TELEGRAM_LIVE_TEST=true and chat_id matches configured test chat.
        
        Args:
            chat_id: Target chat ID (must match configured test chat if live test enabled)
            message: Test message content
            
        Returns:
            (success, error_message)
        """
        settings = load_settings()
        
        # Check if live test is enabled
        if not settings.telegram.live_test_enabled:
            return False, "Live test not enabled (set TELEGRAM_LIVE_TEST=true)"
        
        # Validate chat_id matches configured test chat
        test_chat_id = settings.telegram.live_test_chat_id
        if not test_chat_id:
            return False, "TELEGRAM_TEST_CHAT_ID not configured"
        
        if chat_id != test_chat_id:
            logger.warning(f"Live test chat_id mismatch: expected {test_chat_id}, got {chat_id}")
            return False, "Chat ID does not match configured test chat"
        
        # Use default test message if not provided
        if not message:
            message = (
                "🧪 <b>AI Attendance System - Live Test</b>\n\n"
                "This is a controlled test message from the Telegram notification system.\n"
                f"Timestamp: {datetime.utcnow().isoformat()}Z\n"
                "If you received this, the notification pipeline is working correctly."
            )
        
        # Send the test message
        success, error = await self.send_message(chat_id, message)
        
        if success:
            logger.info(f"Live test message sent successfully to {chat_id}")
        else:
            logger.error(f"Live test message failed: {error}")
        
        return success, error
    
    def get_startup_status(self) -> Dict[str, Any]:
        """Get startup configuration status for health checks."""
        return {
            "configured": bool(self.bot_token),
            "token_valid_format": validate_bot_token(self.bot_token)[0] if self.bot_token else False,
            "live_test_enabled": self._live_test_enabled,
            "live_test_chat_id": self._live_test_chat_id,
            "api_base_url": self.api_base_url,
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def get_me(self) -> Optional[Dict[str, Any]]:
        """Get bot information."""
        if not self.bot_token:
            return None
        
        if self._bot_info:
            return self._bot_info
        
        try:
            session = await self._get_session()
            url = f"{self.api_base_url}{self.bot_token}/getMe"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        self._bot_info = data["result"]
                        return self._bot_info
                logger.error(f"Failed to get bot info: {response.status}")
        except Exception as e:
            logger.error(f"Error getting bot info: {e}")
        return None
    
    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        Send a message to a chat.
        
        Returns:
            (success, error_message)
        """
        if not self.bot_token:
            return False, "Bot token not configured"
        
        # Rate limiting per chat
        now = time.time()
        last_time = self._last_send_time.get(chat_id, 0)
        if now - last_time < self._min_interval_seconds:
            await asyncio.sleep(self._min_interval_seconds - (now - last_time))
        
        try:
            session = await self._get_session()
            url = f"{self.api_base_url}{self.bot_token}/sendMessage"
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
            
            async with session.post(url, json=payload) as response:
                self._last_send_time[chat_id] = time.time()
                
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        return True, None
                    else:
                        error = data.get("description", "Unknown error")
                        logger.error(f"Telegram API error: {error}")
                        return False, error
                
                elif response.status == 429:
                    # Rate limited
                    retry_after = 1
                    try:
                        data = await response.json()
                        retry_after = data.get("parameters", {}).get("retry_after", 1)
                    except:
                        pass
                    logger.warning(f"Rate limited, retry after {retry_after}s")
                    return False, f"RATE_LIMITED:{retry_after}"
                
                else:
                    error_text = await response.text()
                    logger.error(f"Telegram HTTP error {response.status}: {error_text}")
                    return False, f"HTTP {response.status}: {error_text}"
        
        except asyncio.TimeoutError:
            logger.error(f"Timeout sending message to {chat_id}")
            return False, "TIMEOUT"
        except Exception as e:
            logger.error(f"Error sending message to {chat_id}: {e}")
            return False, str(e)
    
    def is_configured(self) -> bool:
        """Check if bot is configured."""
        return bool(self.bot_token)


class NotificationQueue:
    """
    Bounded notification queue with persistence.
    
    Manages notification records, deduplication, retry logic, and rate limiting.
    """
    
    def __init__(
        self,
        parent_registry: ParentRegistry,
        telegram_bot: TelegramBot,
        db_path: str = "data/notification_queue.db",
        max_queue_size: int = 10000,
        max_retries: int = 3,
        base_retry_delay: float = 60.0,  # seconds
        max_retry_delay: float = 3600.0,  # 1 hour
    ):
        self.parent_registry = parent_registry
        self.telegram_bot = telegram_bot
        self.db_path = db_path
        self.max_queue_size = max_queue_size
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.max_retry_delay = max_retry_delay
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize notification queue database."""
        import os
        import sqlite3
        
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            # Disable WAL mode to avoid Windows file locking issues
            conn.execute("PRAGMA journal_mode=DELETE")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    event_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    telegram_chat_id TEXT NOT NULL,
                    notification_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 3,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    last_error TEXT,
                    last_attempt_at TEXT
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_status ON notifications (status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_idempotency ON notifications (idempotency_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_event ON notifications (event_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_student ON notifications (student_id)")
            
            conn.commit()
    
    def _generate_notification_id(self) -> str:
        """Generate unique notification ID."""
        import secrets
        return f"NOTIF-{secrets.token_urlsafe(12)}"
    
    def enqueue_notification(
        self,
        event: PolicyEvent,
        parent: Parent,
        message: str,
    ) -> Optional[NotificationRecord]:
        """
        Enqueue a notification for sending.
        
        Returns None if:
        - Duplicate (idempotency key already exists)
        - Parent's notification preferences don't include this notification type
        - Queue is full
        """
        idempotency_key = event.idempotency_key
        notification_type = event.policy_type.value
        
        # Check parent's notification preferences
        if not self._should_notify_parent(parent, notification_type):
            logger.debug(f"Parent {parent.parent_id} does not want {notification_type} notifications (preference: {parent.notification_preferences.value})")
            return None
        
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Check for existing notification with same idempotency key
                cursor = conn.execute(
                    "SELECT * FROM notifications WHERE idempotency_key = ?",
                    (idempotency_key,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Already exists - return existing record
                    logger.debug(f"Duplicate notification skipped: {idempotency_key}")
                    return NotificationRecord.from_dict({
                        "notification_id": existing[0],
                        "idempotency_key": existing[1],
                        "event_id": existing[2],
                        "student_id": existing[3],
                        "parent_id": existing[4],
                        "telegram_chat_id": existing[5],
                        "notification_type": existing[6],
                        "message": existing[7],
                        "status": existing[8],
                        "attempts": existing[9],
                        "max_attempts": existing[10],
                        "created_at": existing[11],
                        "sent_at": existing[12],
                        "last_error": existing[13],
                        "last_attempt_at": existing[14],
                    })
                
                # Check queue size
                cursor = conn.execute("SELECT COUNT(*) FROM notifications WHERE status IN ('pending', 'sending', 'retry')")
                queue_count = cursor.fetchone()[0]
                
                if queue_count >= self.max_queue_size:
                    logger.error(f"Notification queue full ({queue_count}/{self.max_queue_size})")
                    return None
                
                # Create new notification record
                notification = NotificationRecord(
                    notification_id=self._generate_notification_id(),
                    idempotency_key=idempotency_key,
                    event_id=event.event_id,
                    student_id=event.student_id,
                    parent_id=parent.parent_id,
                    telegram_chat_id=parent.telegram_chat_id or "",
                    notification_type=notification_type,
                    message=message,
                    status=TelegramSendStatus.PENDING,
                    max_attempts=self.max_retries,
                )
                
                conn.execute("""
                    INSERT INTO notifications (
                        notification_id, idempotency_key, event_id, student_id,
                        parent_id, telegram_chat_id, notification_type, message,
                        status, attempts, max_attempts, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    notification.notification_id,
                    notification.idempotency_key,
                    notification.event_id,
                    notification.student_id,
                    notification.parent_id,
                    notification.telegram_chat_id,
                    notification.notification_type,
                    notification.message,
                    notification.status.value,
                    notification.attempts,
                    notification.max_attempts,
                    notification.created_at,
                ))
                conn.commit()
        
        logger.info(f"Enqueued notification {notification.notification_id} for {event.student_id} ({notification_type})")
        return notification
    
    def _should_notify_parent(self, parent: Parent, notification_type: str) -> bool:
        """Check if parent should receive this notification type based on preferences."""
        if not parent.telegram_enabled:
            return False
        if not parent.telegram_chat_id:
            return False
        
        pref = parent.notification_preferences
        if pref == NotificationPreference.NONE:
            return False
        elif pref == NotificationPreference.ALL:
            return True
        elif pref == NotificationPreference.MORNING_ABSENCE_ONLY and notification_type == "morning_absence":
            return True
        elif pref == NotificationPreference.LONG_EXIT_ONLY and notification_type == "long_exit":
            return True
        elif pref == NotificationPreference.MISSING_CHECKOUT_ONLY and notification_type == "missing_checkout":
            return True
        
        return False
    
    def get_pending_notifications(self, limit: int = 100) -> List[NotificationRecord]:
        """Get pending notifications ready for sending."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM notifications
                    WHERE status IN ('pending', 'retry')
                    AND (last_attempt_at IS NULL OR 
                         datetime(last_attempt_at) < datetime('now', '-' || 
                             CASE 
                                 WHEN attempts = 0 THEN '0 seconds'
                                 WHEN attempts = 1 THEN '60 seconds'
                                 WHEN attempts = 2 THEN '300 seconds'
                                 ELSE '3600 seconds'
                             END))
                    ORDER BY created_at
                    LIMIT ?
                """, (limit,))
                
                return [NotificationRecord.from_dict(dict(row)) for row in cursor.fetchall()]
    
    def mark_sending(self, notification_id: str) -> bool:
        """Mark notification as currently sending."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.utcnow().isoformat() + "Z"
                cursor = conn.execute("""
                    UPDATE notifications
                    SET status = ?, last_attempt_at = ?, attempts = attempts + 1
                    WHERE notification_id = ? AND status IN ('pending', 'retry')
                """, (TelegramSendStatus.SENDING.value, now, notification_id))
                conn.commit()
                return cursor.rowcount > 0
    
    def mark_sent(self, notification_id: str) -> bool:
        """Mark notification as successfully sent."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.utcnow().isoformat() + "Z"
                cursor = conn.execute("""
                    UPDATE notifications
                    SET status = ?, sent_at = ?, last_error = NULL
                    WHERE notification_id = ?
                """, (TelegramSendStatus.SENT.value, now, notification_id))
                conn.commit()
                return cursor.rowcount > 0
    
    def mark_failed(self, notification_id: str, error: str) -> bool:
        """Mark notification as failed (will retry if attempts < max)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Get current attempts
                cursor = conn.execute(
                    "SELECT attempts, max_attempts FROM notifications WHERE notification_id = ?",
                    (notification_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return False
                
                attempts, max_attempts = row
                
                if attempts >= max_attempts:
                    # Max retries exceeded - mark as permanently failed
                    cursor = conn.execute("""
                        UPDATE notifications
                        SET status = ?, last_error = ?
                        WHERE notification_id = ?
                    """, (TelegramSendStatus.FAILED.value, error, notification_id))
                else:
                    # Schedule for retry
                    cursor = conn.execute("""
                        UPDATE notifications
                        SET status = ?, last_error = ?
                        WHERE notification_id = ?
                    """, (TelegramSendStatus.RETRY.value, error, notification_id))
                
                conn.commit()
                return cursor.rowcount > 0
    
    def mark_rate_limited(self, notification_id: str, retry_after: int) -> bool:
        """Mark notification as rate limited (will retry after delay)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # For rate limiting, we keep it as retry but the worker will handle the delay
                cursor = conn.execute("""
                    UPDATE notifications
                    SET status = ?, last_error = ?
                    WHERE notification_id = ?
                """, (TelegramSendStatus.RETRY.value, f"RATE_LIMITED:{retry_after}", notification_id))
                conn.commit()
                return cursor.rowcount > 0
    
    def get_notification(self, notification_id: str) -> Optional[NotificationRecord]:
        """Get notification by ID."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM notifications WHERE notification_id = ?", (notification_id,))
                row = cursor.fetchone()
                if row:
                    return NotificationRecord.from_dict(dict(row))
                return None
    
    def get_notification_by_idempotency_key(self, idempotency_key: str) -> Optional[NotificationRecord]:
        """Get notification by idempotency key."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT * FROM notifications WHERE idempotency_key = ?", (idempotency_key,))
                row = cursor.fetchone()
                if row:
                    return NotificationRecord.from_dict(dict(row))
                return None
    
    def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT status, COUNT(*) FROM notifications
                    GROUP BY status
                """)
                stats = {row[0]: row[1] for row in cursor.fetchall()}
                
                # Ensure all statuses present
                for status in TelegramSendStatus:
                    if status.value not in stats:
                        stats[status.value] = 0
                
                return stats
    
    def get_detailed_metrics(self) -> Dict[str, Any]:
        """Get detailed queue metrics for monitoring."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # Basic stats
                stats = self.get_queue_stats()
                
                # Enqueue rate (last hour)
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM notifications
                    WHERE created_at > datetime('now', '-1 hour')
                """)
                enqueue_rate_1h = cursor.fetchone()[0]
                
                # Dequeue rate (last hour)
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM notifications
                    WHERE sent_at > datetime('now', '-1 hour')
                """)
                dequeue_rate_1h = cursor.fetchone()[0]
                
                # Average latency for sent notifications
                cursor = conn.execute("""
                    SELECT AVG(julianday(sent_at) - julianday(created_at)) * 86400
                    FROM notifications
                    WHERE status = 'sent' AND sent_at IS NOT NULL
                """)
                avg_latency = cursor.fetchone()[0] or 0
                
                # P95 latency
                cursor = conn.execute("""
                    SELECT (julianday(sent_at) - julianday(created_at)) * 86400 as latency
                    FROM notifications
                    WHERE status = 'sent' AND sent_at IS NOT NULL
                    ORDER BY latency
                """)
                latencies = [row[0] for row in cursor.fetchall()]
                p95_latency = 0
                if latencies:
                    idx = int(len(latencies) * 0.95)
                    p95_latency = latencies[min(idx, len(latencies) - 1)]
                
                # Oldest pending age
                cursor = conn.execute("""
                    SELECT MIN(julianday('now') - julianday(created_at)) * 86400
                    FROM notifications
                    WHERE status IN ('pending', 'retry', 'sending')
                """)
                oldest_pending_age = cursor.fetchone()[0] or 0
                
                # Retry count
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM notifications
                    WHERE attempts > 0
                """)
                retry_count = cursor.fetchone()[0]
                
                # Failed count
                failed_count = stats.get('failed', 0)
                
                # Rate limited count
                rate_limited_count = stats.get('rate_limited', 0)
                
                return {
                    "queue_stats": stats,
                    "enqueue_rate_1h": enqueue_rate_1h,
                    "dequeue_rate_1h": dequeue_rate_1h,
                    "avg_latency_seconds": round(avg_latency, 2),
                    "p95_latency_seconds": round(p95_latency, 2),
                    "oldest_pending_age_seconds": round(oldest_pending_age, 2),
                    "retry_count": retry_count,
                    "failed_count": failed_count,
                    "rate_limited_count": rate_limited_count,
                    "queue_depth": stats.get('pending', 0) + stats.get('retry', 0) + stats.get('sending', 0),
                    "max_queue_size": self.max_queue_size,
                    "queue_utilization_percent": round(
                        (stats.get('pending', 0) + stats.get('retry', 0) + stats.get('sending', 0)) / self.max_queue_size * 100, 2
                    ) if self.max_queue_size > 0 else 0,
                }
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check for alert conditions and return list of alerts."""
        alerts = []
        metrics = self.get_detailed_metrics()
        
        # Queue continuously growing
        if metrics["queue_utilization_percent"] > 80:
            alerts.append({
                "severity": "warning",
                "type": "queue_growing",
                "message": f"Queue utilization at {metrics['queue_utilization_percent']}%",
                "metric": "queue_utilization_percent",
                "value": metrics["queue_utilization_percent"],
                "threshold": 80,
            })
        
        if metrics["queue_utilization_percent"] > 95:
            alerts.append({
                "severity": "critical",
                "type": "queue_critical",
                "message": f"Queue critically full at {metrics['queue_utilization_percent']}%",
                "metric": "queue_utilization_percent",
                "value": metrics["queue_utilization_percent"],
                "threshold": 95,
            })
        
        # Repeated Telegram failure
        if metrics["failed_count"] > 10:
            alerts.append({
                "severity": "warning",
                "type": "telegram_failures",
                "message": f"High failure count: {metrics['failed_count']} failed notifications",
                "metric": "failed_count",
                "value": metrics["failed_count"],
                "threshold": 10,
            })
        
        # Excessive retry
        if metrics["retry_count"] > 100:
            alerts.append({
                "severity": "warning",
                "type": "excessive_retry",
                "message": f"High retry count: {metrics['retry_count']} retried notifications",
                "metric": "retry_count",
                "value": metrics["retry_count"],
                "threshold": 100,
            })
        
        # Worker stopped (no dequeue activity for 5 minutes)
        if metrics["dequeue_rate_1h"] == 0 and metrics["queue_depth"] > 0:
            alerts.append({
                "severity": "critical",
                "type": "worker_stopped",
                "message": "Notification worker appears stopped - no messages sent in last hour",
                "metric": "dequeue_rate_1h",
                "value": 0,
                "threshold": 1,
            })
        
        # Database unavailable (would be caught by exception, but check queue depth)
        if metrics["queue_depth"] > 0 and metrics["dequeue_rate_1h"] == 0:
            alerts.append({
                "severity": "warning",
                "type": "database_unavailable",
                "message": "Possible database issue - queue not draining",
                "metric": "queue_depth",
                "value": metrics["queue_depth"],
            })
        
        return alerts
    
    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up old sent/failed notifications."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
                cursor = conn.execute("""
                    DELETE FROM notifications
                    WHERE status IN ('sent', 'failed') AND created_at < ?
                """, (cutoff,))
                conn.commit()
                return cursor.rowcount


class TelegramWorker:
    """
    Background worker for processing notification queue.
    
    Runs asynchronously, sends notifications via Telegram bot,
    handles retries, rate limiting, and deduplication.
    """
    
    def __init__(
        self,
        notification_queue: NotificationQueue,
        telegram_bot: TelegramBot,
        poll_interval: float = 5.0,  # seconds
        batch_size: int = 10,
    ):
        self.notification_queue = notification_queue
        self.telegram_bot = telegram_bot
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Telegram worker started")
    
    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.telegram_bot.close()
        logger.info("Telegram worker stopped")
    
    async def _run_loop(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    async def _process_batch(self) -> None:
        """Process a batch of pending notifications."""
        if not self.telegram_bot.is_configured():
            logger.debug("Telegram bot not configured, skipping batch")
            return
        
        notifications = self.notification_queue.get_pending_notifications(self.batch_size)
        
        for notification in notifications:
            if not self._running:
                break
            
            await self._send_notification(notification)
    
    async def _send_notification(self, notification: NotificationRecord) -> None:
        """Send a single notification."""
        # Mark as sending
        self.notification_queue.mark_sending(notification.notification_id)
        
        try:
            success, error = await self.telegram_bot.send_message(
                chat_id=notification.telegram_chat_id,
                text=notification.message,
            )
            
            if success:
                self.notification_queue.mark_sent(notification.notification_id)
                logger.info(f"Notification {notification.notification_id} sent successfully")
            else:
                if error and error.startswith("RATE_LIMITED:"):
                    retry_after = int(error.split(":")[1])
                    self.notification_queue.mark_rate_limited(notification.notification_id, retry_after)
                    logger.warning(f"Rate limited for {notification.notification_id}, retry after {retry_after}s")
                else:
                    self.notification_queue.mark_failed(notification.notification_id, error or "Unknown error")
                    logger.error(f"Failed to send notification {notification.notification_id}: {error}")
        
        except Exception as e:
            self.notification_queue.mark_failed(notification.notification_id, str(e))
            logger.error(f"Exception sending notification {notification.notification_id}: {e}")


def create_telegram_bot(bot_token: Optional[str] = None) -> TelegramBot:
    """Factory function to create TelegramBot."""
    return TelegramBot(bot_token=bot_token)


def create_notification_queue(
    parent_registry: ParentRegistry,
    telegram_bot: TelegramBot,
    db_path: str = "data/notification_queue.db",
) -> NotificationQueue:
    """Factory function to create NotificationQueue."""
    return NotificationQueue(parent_registry, telegram_bot, db_path)


def create_telegram_worker(
    notification_queue: NotificationQueue,
    telegram_bot: TelegramBot,
) -> TelegramWorker:
    """Factory function to create TelegramWorker."""
    return TelegramWorker(notification_queue, telegram_bot)