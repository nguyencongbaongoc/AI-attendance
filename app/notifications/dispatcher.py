"""
Phase 15 — Notification Dispatcher.

Orchestrates multi-channel notification delivery with tiered fallback,
deduplication, cooldown, and persistent queue management.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationChannel,
    NotificationPayload,
    NotificationResult,
    NotificationStatus,
)
from app.attendance.policy_engine.contract import PolicyEvent
from app.attendance.policy_engine.parent_registry import Parent, ParentRegistry
from app.config.settings import load_settings

logger = logging.getLogger(__name__)


class DispatcherStatus(str, Enum):
    """Dispatcher operational status."""
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class FallbackPolicy(str, Enum):
    """Fallback behavior when a channel fails."""
    IMMEDIATE = "immediate"       # Try next tier immediately
    RETRY_THEN_FALLBACK = "retry_then_fallback"  # Exhaust retries then fallback
    NO_FALLBACK = "no_fallback"   # No fallback, mark as failed


@dataclass(frozen=True)
class ChannelTier:
    """Defines a tier in the fallback hierarchy."""
    channel: NotificationChannel
    providers: List[str]  # Provider names in priority order
    fallback_policy: FallbackPolicy = FallbackPolicy.IMMEDIATE
    cooldown_seconds: int = 0  # Minimum interval between sends to same recipient


@dataclass
class DispatcherConfig:
    """Configuration for the notification dispatcher."""
    # Tier hierarchy (Tier 1 = highest priority)
    tiers: List[ChannelTier] = field(default_factory=lambda: [
        ChannelTier(
            channel=NotificationChannel.ZALO_ZNS,
            providers=["zalo_zns_official"],
            fallback_policy=FallbackPolicy.IMMEDIATE,
            cooldown_seconds=300,  # 5 minutes
        ),
        ChannelTier(
            channel=NotificationChannel.SMS,
            providers=["esms_vn", "speedsms_vn"],
            fallback_policy=FallbackPolicy.RETRY_THEN_FALLBACK,
            cooldown_seconds=300,
        ),
        ChannelTier(
            channel=NotificationChannel.TELEGRAM,
            providers=["telegram_bot"],
            fallback_policy=FallbackPolicy.NO_FALLBACK,
            cooldown_seconds=60,
        ),
    ])
    
    # Queue settings
    queue_db_path: str = "data/notification_queue.db"
    max_queue_size: int = 10000
    max_retries: int = 3
    base_retry_delay: float = 10.0
    max_retry_delay: float = 3600.0
    
    # Cooldown settings (prevent spam)
    cooldown_db_path: str = "data/notification_cooldown.db"
    default_cooldown_seconds: int = 300  # 5 minutes
    per_event_cooldown: Dict[str, int] = field(default_factory=lambda: {
        "morning_absence": 86400,  # 24 hours
        "long_exit": 300,          # 5 minutes
        "missing_checkout": 3600,  # 1 hour
    })
    
    # Worker settings
    poll_interval: float = 5.0
    batch_size: int = 10
    max_concurrent_sends: int = 5
    
    # Alerting
    alert_on_queue_depth: int = 1000
    alert_on_failure_rate: float = 0.1  # 10%
    
    def get_cooldown_for_event(self, event_type: str) -> int:
        return self.per_event_cooldown.get(event_type, self.default_cooldown_seconds)


class CooldownTracker:
    """
    Tracks notification cooldowns per student/event type to prevent spam.
    
    Uses SQLite for persistence across restarts.
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    student_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    last_sent_at TEXT NOT NULL,
                    PRIMARY KEY (student_id, event_type)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cooldown_student ON cooldowns (student_id)")
            conn.commit()
    
    def is_in_cooldown(self, student_id: str, event_type: str, cooldown_seconds: int) -> bool:
        """Check if a student is in cooldown for a specific event type."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT last_sent_at FROM cooldowns WHERE student_id = ? AND event_type = ?",
                    (student_id, event_type)
                )
                row = cursor.fetchone()
                
                if not row:
                    return False
                
                last_sent = datetime.fromisoformat(row["last_sent_at"].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = (now - last_sent).total_seconds()
                return elapsed < cooldown_seconds
    
    def record_send(self, student_id: str, event_type: str) -> None:
        """Record a notification send for cooldown tracking."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                conn.execute("""
                    INSERT OR REPLACE INTO cooldowns (student_id, event_type, last_sent_at)
                    VALUES (?, ?, ?)
                """, (student_id, event_type, now))
                conn.commit()
    
    def get_remaining_cooldown(self, student_id: str, event_type: str, cooldown_seconds: int) -> Optional[int]:
        """Get remaining cooldown seconds, or None if not in cooldown."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT last_sent_at FROM cooldowns WHERE student_id = ? AND event_type = ?",
                    (student_id, event_type)
                )
                row = cursor.fetchone()
                
                if not row:
                    return None
                
                last_sent = datetime.fromisoformat(row["last_sent_at"].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                elapsed = (now - last_sent).total_seconds()
                remaining = int(cooldown_seconds - elapsed)
                return max(0, remaining) if remaining > 0 else None


@dataclass
class QueuedNotification:
    """Notification queued for delivery with full context."""
    payload: NotificationPayload
    id: str = field(default_factory=lambda: f"NOTIF-{secrets.token_urlsafe(12)}")
    current_tier_index: int = 0
    current_provider_index: int = 0
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    last_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
    last_result: Optional[NotificationResult] = None
    status: NotificationStatus = NotificationStatus.PENDING
    
    @property
    def idempotency_key(self) -> str:
        return self.payload.idempotency_key


class PersistentNotificationQueue:
    """
    Persistent SQLite-backed notification queue with retry logic.
    """
    
    def __init__(
        self,
        db_path: str,
        max_queue_size: int = 10000,
        max_retries: int = 3,
        base_retry_delay: float = 10.0,
        max_retry_delay: float = 3600.0,
    ):
        self.db_path = db_path
        self.max_queue_size = max_queue_size
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.max_retry_delay = max_retry_delay
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_queue (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    payload_json TEXT NOT NULL,
                    current_tier_index INTEGER DEFAULT 0,
                    current_provider_index INTEGER DEFAULT 0,
                    attempts INTEGER DEFAULT 0,
                    max_attempts INTEGER DEFAULT 3,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    last_attempt_at TEXT,
                    last_error TEXT,
                    last_result_json TEXT,
                    next_retry_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON notification_queue (status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_idempotency ON notification_queue (idempotency_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_next_retry ON notification_queue (next_retry_at)")
            conn.commit()
    
    def _generate_id(self) -> str:
        import secrets
        return f"NOTIF-{secrets.token_urlsafe(12)}"
    
    def enqueue(self, payload: NotificationPayload) -> Optional[QueuedNotification]:
        """Add a notification to the queue. Returns None if duplicate."""
        import json
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Check for duplicate
                cursor = conn.execute(
                    "SELECT id FROM notification_queue WHERE idempotency_key = ?",
                    (payload.idempotency_key,)
                )
                if cursor.fetchone():
                    logger.debug(f"Duplicate notification skipped: {payload.idempotency_key}")
                    return None
                
                # Check queue size
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM notification_queue WHERE status IN ('pending', 'sending', 'retry')"
                )
                if cursor.fetchone()[0] >= self.max_queue_size:
                    logger.error(f"Notification queue full")
                    return None
                
                # Create queued notification
                queued = QueuedNotification(
                    payload=payload,
                )
                
                conn.execute("""
                    INSERT INTO notification_queue (
                        id, idempotency_key, payload_json, current_tier_index,
                        current_provider_index, attempts, max_attempts, status,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    queued.id,
                    payload.idempotency_key,
                    json.dumps(payload.__dict__, default=str),
                    0, 0, 0, self.max_retries,
                    NotificationStatus.PENDING.value,
                    queued.created_at,
                ))
                conn.commit()
        
        logger.info(f"Enqueued notification {queued.id} for {payload.student_id} ({payload.event_type})")
        return queued
    
    def get_pending(self, limit: int = 100) -> List[QueuedNotification]:
        """Get notifications ready for processing."""
        import json
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                now = datetime.utcnow().isoformat() + "Z"
                cursor = conn.execute("""
                    SELECT * FROM notification_queue
                    WHERE status IN ('pending', 'retry')
                    AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    ORDER BY created_at
                    LIMIT ?
                """, (now, limit))
                
                results = []
                for row in cursor.fetchall():
                    payload_data = json.loads(row["payload_json"])
                    # Convert datetime strings back to datetime objects for payload
                    payload = NotificationPayload(**payload_data)
                    
                    queued = QueuedNotification(
                        id=row["id"],
                        payload=payload,
                        current_tier_index=row["current_tier_index"],
                        current_provider_index=row["current_provider_index"],
                        attempts=row["attempts"],
                        max_attempts=row["max_attempts"],
                        status=NotificationStatus(row["status"]),
                        created_at=row["created_at"],
                        last_attempt_at=row["last_attempt_at"],
                        last_error=row["last_error"],
                        last_result=NotificationResult(**json.loads(row["last_result_json"])) if row["last_result_json"] else None,
                    )
                    results.append(queued)
                return results
    
    def update_status(
        self,
        notification_id: str,
        status: NotificationStatus,
        error: Optional[str] = None,
        result: Optional[NotificationResult] = None,
        next_retry_at: Optional[str] = None,
        increment_tier: bool = False,
        increment_provider: bool = False,
    ) -> bool:
        """Update notification status after send attempt."""
        import json
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.utcnow().isoformat() + "Z"
                
                # Get current state
                cursor = conn.execute(
                    "SELECT current_tier_index, current_provider_index, attempts FROM notification_queue WHERE id = ?",
                    (notification_id,)
                )
                row = cursor.fetchone()
                if not row:
                    return False
                
                tier_idx, provider_idx, attempts = row
                
                if increment_tier:
                    tier_idx += 1
                    provider_idx = 0
                elif increment_provider:
                    provider_idx += 1
                
                conn.execute("""
                    UPDATE notification_queue
                    SET status = ?, last_attempt_at = ?, last_error = ?,
                        last_result_json = ?, next_retry_at = ?,
                        current_tier_index = ?, current_provider_index = ?,
                        attempts = ?
                    WHERE id = ?
                """, (
                    status.value, now, error,
                    json.dumps(result.__dict__, default=str) if result else None,
                    next_retry_at,
                    tier_idx, provider_idx,
                    attempts + 1,
                    notification_id,
                ))
                conn.commit()
                return True
    
    def get_stats(self) -> Dict[str, int]:
        """Get queue statistics."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT status, COUNT(*) FROM notification_queue GROUP BY status
                """)
                return {row[0]: row[1] for row in cursor.fetchall()}


class NotificationDispatcher:
    """
    Main dispatcher orchestrating multi-channel notification delivery.
    
    Features:
    - Tiered fallback (ZNS -> SMS -> Telegram)
    - Per-student cooldown to prevent spam
    - Persistent queue with retry logic
    - Asynchronous non-blocking delivery
    - Provider health monitoring
    """
    
    def __init__(
        self,
        config: DispatcherConfig,
        providers: Dict[str, BaseNotificationProvider],
        parent_registry: ParentRegistry,
        cooldown_tracker: CooldownTracker,
        queue: PersistentNotificationQueue,
    ):
        self.config = config
        self.providers = providers
        self.parent_registry = parent_registry
        self.cooldown_tracker = cooldown_tracker
        self.queue = queue
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self.status = DispatcherStatus.STOPPED
        self._stats = {
            "total_enqueued": 0,
            "total_sent": 0,
            "total_failed": 0,
            "total_skipped_cooldown": 0,
            "total_fallback": 0,
        }
    
    async def start(self) -> None:
        """Start the dispatcher worker."""
        if self._running:
            return
        
        self._running = True
        self.status = DispatcherStatus.RUNNING
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_sends)
        self._task = asyncio.create_task(self._worker_loop())
        logger.info("Notification dispatcher started")
    
    async def stop(self) -> None:
        """Stop the dispatcher worker."""
        self._running = False
        self.status = DispatcherStatus.STOPPING
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Close provider sessions
        for provider in self.providers.values():
            if hasattr(provider, 'close'):
                await provider.close()
        self.status = DispatcherStatus.STOPPED
        logger.info("Notification dispatcher stopped")
    
    def dispatch_event(self, event: PolicyEvent) -> List[str]:
        """
        Process a policy event and enqueue notifications for all recipients.
        
        Called synchronously from the attendance policy engine.
        Returns list of notification IDs enqueued.
        """
        if not event.is_notification_type:
            return []
        
        # Get recipients
        recipients = self.parent_registry.get_notification_recipients(
            event.student_id,
            event.policy_type.value,
        )
        
        if not recipients:
            logger.warning(f"No recipients for student {event.student_id} event {event.policy_type.value}")
            return []
        
        # Get student name from evidence or use ID
        student_name = event.evidence.get("student_name", f"Student {event.student_id}")
        date_str = datetime.fromtimestamp(event.occurred_at).strftime("%Y-%m-%d")
        
        # Import template function
        from app.attendance.policy_engine.templates import create_notification_message
        
        # Create message
        message = create_notification_message(
            policy_type=event.policy_type.value,
            student_name=student_name,
            student_id=event.student_id,
            date=date_str,
            evidence=event.evidence,
        )
        
        # Check cooldown and enqueue for each recipient
        enqueued_ids = []
        cooldown_seconds = self.config.get_cooldown_for_event(event.policy_type.value)
        
        for parent in recipients:
            # Check cooldown
            if self.cooldown_tracker.is_in_cooldown(event.student_id, event.policy_type.value, cooldown_seconds):
                self._stats["total_skipped_cooldown"] += 1
                logger.info(f"Skipped notification for {event.student_id} - in cooldown")
                continue
            
            # Build payload
            payload = NotificationPayload(
                event_id=event.event_id,
                event_type=event.policy_type.value,
                student_id=event.student_id,
                student_name=student_name,
                recipient_id=parent.parent_id,
                recipient_name=parent.parent_name,
                recipient_phone=getattr(parent, 'phone', '') or "",
                recipient_telegram_chat_id=getattr(parent, 'telegram_chat_id', None),
                message=message,
                occurred_at=event.occurred_at,
                effective_at=event.effective_at,
                evidence=event.evidence,
                metadata={
                    "parent_relationship": getattr(parent, 'relationship_type', "guardian"),
                    "is_primary": getattr(parent, 'is_primary', False),
                },
                # Phase 17: Include evidence URLs if available
                snapshot_face_url=event.evidence.get("snapshot_face_url"),
                snapshot_scene_url=event.evidence.get("snapshot_scene_url"),
                video_clip_url=event.evidence.get("video_clip_url"),
            )
            
            # Enqueue
            queued = self.queue.enqueue(payload)
            if queued:
                enqueued_ids.append(queued.id)
                self._stats["total_enqueued"] += 1
        
        return enqueued_ids
    
    async def _worker_loop(self) -> None:
        """Main worker loop processing the queue."""
        while self._running:
            try:
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in dispatcher worker loop: {e}")
            
            await asyncio.sleep(self.config.poll_interval)
    
    async def _process_batch(self) -> None:
        """Process a batch of pending notifications."""
        if not self.providers:
            return
        
        notifications = self.queue.get_pending(self.config.batch_size)
        
        # Process concurrently with semaphore
        tasks = [self._process_notification(n) for n in notifications]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _process_notification(self, queued: QueuedNotification) -> None:
        """Process a single queued notification through the tier hierarchy."""
        async with self._semaphore:
            tier_idx = queued.current_tier_index
            provider_idx = queued.current_provider_index
            
            # Check if we've exhausted all tiers
            if tier_idx >= len(self.config.tiers):
                logger.error(f"Exhausted all tiers for notification {queued.id}")
                self.queue.update_status(queued.id, NotificationStatus.FAILED, "All tiers exhausted")
                self._stats["total_failed"] += 1
                return
            
            tier = self.config.tiers[tier_idx]
            
            # Check if we've exhausted providers in this tier
            if provider_idx >= len(tier.providers):
                # Move to next tier based on fallback policy
                if tier.fallback_policy == FallbackPolicy.IMMEDIATE:
                    self.queue.update_status(queued.id, NotificationStatus.PENDING, increment_tier=True)
                    self._stats["total_fallback"] += 1
                    logger.info(f"Notification {queued.id} falling back to tier {tier_idx + 2}")
                elif tier.fallback_policy == FallbackPolicy.RETRY_THEN_FALLBACK:
                    # Check if we should retry current provider or move on
                    if queued.attempts < queued.max_attempts:
                        # Retry current provider
                        pass  # Will retry same provider
                    else:
                        # Move to next tier
                        self.queue.update_status(queued.id, NotificationStatus.PENDING, increment_tier=True)
                        self._stats["total_fallback"] += 1
                return
            
            # Get current provider
            provider_name = tier.providers[provider_idx]
            provider = self.providers.get(provider_name)
            
            if not provider or not provider.is_enabled:
                logger.warning(f"Provider {provider_name} not available, trying next")
                self.queue.update_status(queued.id, NotificationStatus.PENDING, increment_provider=True)
                return
            
            # Check rate limit
            rate_limit = provider._check_rate_limit(queued.payload.recipient_id)
            if rate_limit:
                next_retry = datetime.utcnow() + timedelta(seconds=rate_limit)
                self.queue.update_status(
                    queued.id,
                    NotificationStatus.RETRY,
                    next_retry_at=next_retry.isoformat() + "Z",
                    error=f"Rate limited, retry after {rate_limit}s"
                )
                return
            
            # Check cooldown (double-check at send time)
            cooldown_seconds = tier.cooldown_seconds
            if self.cooldown_tracker.is_in_cooldown(
                queued.payload.student_id,
                queued.payload.event_type,
                cooldown_seconds
            ):
                self.queue.update_status(queued.id, NotificationStatus.SKIPPED_COOLDOWN)
                self._stats["total_skipped_cooldown"] += 1
                return
            
            # Send notification
            try:
                result = await provider.send_notification(queued.payload)
                
                if result.is_success:
                    # Mark sent and record cooldown
                    self.queue.update_status(queued.id, NotificationStatus.SENT, result=result)
                    provider._clear_rate_limit(queued.payload.recipient_id)
                    self.cooldown_tracker.record_send(queued.payload.student_id, queued.payload.event_type)
                    self._stats["total_sent"] += 1
                    logger.info(f"Notification {queued.id} sent via {provider_name}")
                else:
                    # Handle failure
                    await self._handle_send_failure(queued, provider, result, tier)
                    
            except Exception as e:
                logger.error(f"Exception sending notification {queued.id}: {e}")
                await self._handle_send_failure(queued, provider, None, tier, str(e))
    
    async def _handle_send_failure(
        self,
        queued: QueuedNotification,
        provider: BaseNotificationProvider,
        result: Optional[NotificationResult],
        tier: ChannelTier,
        error: Optional[str] = None,
    ) -> None:
        """Handle a failed send attempt with retry/fallback logic."""
        error_msg = error or (result.error_message if result else "Unknown error")
        
        # Check if rate limited
        if result and result.status == NotificationStatus.RATE_LIMITED and result.retry_after_seconds:
            next_retry = datetime.utcnow() + timedelta(seconds=result.retry_after_seconds)
            provider._set_rate_limit(queued.payload.recipient_id, result.retry_after_seconds)
            self.queue.update_status(
                queued.id,
                NotificationStatus.RETRY,
                error=error_msg,
                result=result,
                next_retry_at=next_retry.isoformat() + "Z",
            )
            return
        
        provider_idx = queued.current_provider_index
        
        # Check retry limits
        if queued.attempts + 1 >= queued.max_attempts:
            # Exhausted retries for this provider
            if provider_idx + 1 < len(tier.providers):
                # Try next provider in same tier
                self.queue.update_status(
                    queued.id,
                    NotificationStatus.RETRY,
                    error=error_msg,
                    result=result,
                    increment_provider=True,
                )
            elif tier.fallback_policy != FallbackPolicy.NO_FALLBACK:
                # Move to next tier
                self.queue.update_status(
                    queued.id,
                    NotificationStatus.RETRY,
                    error=error_msg,
                    result=result,
                    increment_tier=True,
                )
                self._stats["total_fallback"] += 1
            else:
                # No more options
                self.queue.update_status(queued.id, NotificationStatus.FAILED, error_msg, result)
                self._stats["total_failed"] += 1
        else:
            # Check if we should fallback immediately based on policy
            if tier.fallback_policy == FallbackPolicy.IMMEDIATE:
                # Immediate fallback to next tier/provider on any failure
                if provider_idx + 1 < len(tier.providers):
                    self.queue.update_status(
                        queued.id,
                        NotificationStatus.RETRY,
                        error=error_msg,
                        result=result,
                        increment_provider=True,
                    )
                elif tier.fallback_policy != FallbackPolicy.NO_FALLBACK:
                    self.queue.update_status(
                        queued.id,
                        NotificationStatus.RETRY,
                        error=error_msg,
                        result=result,
                        increment_tier=True,
                    )
                    self._stats["total_fallback"] += 1
                else:
                    self.queue.update_status(queued.id, NotificationStatus.FAILED, error_msg, result)
                    self._stats["total_failed"] += 1
            else:
                # Retry same provider with backoff
                delay = provider._calculate_retry_delay(queued.attempts + 1)
                next_retry = datetime.utcnow() + timedelta(seconds=delay)
                self.queue.update_status(
                    queued.id,
                    NotificationStatus.RETRY,
                    error=error_msg,
                    result=result,
                    next_retry_at=next_retry.isoformat() + "Z",
                )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics."""
        queue_stats = self.queue.get_stats()
        return {
            "status": self.status.value,
            "enqueued": self._stats["total_enqueued"],
            "sent": self._stats["total_sent"],
            "failed": self._stats["total_failed"],
            "skipped_cooldown": self._stats["total_skipped_cooldown"],
            "fallback_count": self._stats["total_fallback"],
            "queue": queue_stats,
            "providers": {name: p.is_enabled for name, p in self.providers.items()},
        }
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check for alert conditions."""
        alerts = []
        stats = self.get_stats()
        
        # Queue depth
        queue_depth = sum(
            stats["queue"].get(s, 0) for s in ["pending", "retry", "sending"]
        )
        if queue_depth > self.config.alert_on_queue_depth:
            alerts.append({
                "severity": "warning",
                "type": "queue_depth",
                "message": f"Queue depth {queue_depth} exceeds threshold {self.config.alert_on_queue_depth}",
            })
        
        # Failure rate
        total_processed = stats["sent"] + stats["failed"]
        if total_processed > 10:
            failure_rate = stats["failed"] / total_processed
            if failure_rate > self.config.alert_on_failure_rate:
                alerts.append({
                    "severity": "warning",
                    "type": "high_failure_rate",
                    "message": f"Failure rate {failure_rate:.1%} exceeds threshold {self.config.alert_on_failure_rate:.1%}",
                })
        
        return alerts


def create_dispatcher_from_settings(
    parent_registry: ParentRegistry,
    config: Optional[DispatcherConfig] = None,
) -> NotificationDispatcher:
    """
    Factory to create dispatcher from settings.
    
    Instantiates providers based on configuration and environment variables.
    """
    settings = load_settings()
    config = config or DispatcherConfig()
    
    providers = {}
    
    # Telegram Bot (Tier 3)
    if settings.telegram.bot_token:
        from app.notifications.telegram_provider import TelegramProvider
        providers["telegram_bot"] = TelegramProvider(
            bot_token=settings.telegram.bot_token,
        )
    
    # Zalo ZNS (Tier 1)
    if hasattr(settings, 'zalo') and settings.zalo.app_id and settings.zalo.secret_key:
        from app.notifications.zns_provider import ZaloZNSProvider
        providers["zalo_zns_official"] = ZaloZNSProvider(
            app_id=settings.zalo.app_id,
            secret_key=settings.zalo.secret_key,
            access_token=settings.zalo.access_token if hasattr(settings.zalo, 'access_token') else None,
        )
    
    # SMS - eSMS (Tier 2)
    if hasattr(settings, 'esms') and settings.esms.api_key and settings.esms.secret_key:
        from app.notifications.sms_provider import ESMSProvider
        providers["esms_vn"] = ESMSProvider(
            api_key=settings.esms.api_key,
            secret_key=settings.esms.secret_key,
            brandname=settings.esms.brandname if hasattr(settings.esms, 'brandname') else None,
        )
    
    # SMS - SpeedSMS (Tier 2)
    if hasattr(settings, 'speedsms') and settings.speedsms.api_token:
        from app.notifications.sms_provider import SpeedSMSProvider
        providers["speedsms_vn"] = SpeedSMSProvider(
            api_token=settings.speedsms.api_token,
        )
    
    # Create components
    cooldown_tracker = CooldownTracker(config.cooldown_db_path)
    queue = PersistentNotificationQueue(
        db_path=config.queue_db_path,
        max_queue_size=config.max_queue_size,
        max_retries=config.max_retries,
        base_retry_delay=config.base_retry_delay,
        max_retry_delay=config.max_retry_delay,
    )
    
    return NotificationDispatcher(
        config=config,
        providers=providers,
        parent_registry=parent_registry,
        cooldown_tracker=cooldown_tracker,
        queue=queue,
    )