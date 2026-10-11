"""
Phase 15 — Base Notification Provider Interface.

Abstract base class defining the contract for all notification providers.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class NotificationStatus(str, Enum):
    """Status of a notification delivery attempt."""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    RETRY = "retry"
    DISABLED = "disabled"
    NO_RECIPIENT = "no_recipient"
    RATE_LIMITED = "rate_limited"
    SKIPPED_COOLDOWN = "skipped_cooldown"


class NotificationChannel(str, Enum):
    """Supported notification channels."""
    ZALO_ZNS = "zalo_zns"
    SMS = "sms"
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class NotificationPayload:
    """
    Immutable notification payload containing all data needed for delivery.
    
    This is the canonical representation passed between the dispatcher and providers.
    """
    # Event identification
    event_id: str
    event_type: str  # "morning_absence", "long_exit", "missing_checkout"
    
    # Student information
    student_id: str
    student_name: str
    
    # Recipient information
    recipient_id: str  # Parent/guardian ID
    recipient_name: str
    recipient_phone: str  # E.164 format: +84901234567
    recipient_telegram_chat_id: Optional[str] = None
    
    # Message content
    message: str = ""
    template_variables: Dict[str, str] = field(default_factory=dict)
    
    # Timing
    occurred_at: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    effective_at: float = field(default_factory=lambda: datetime.utcnow().timestamp())
    
    # Idempotency
    idempotency_key: str = ""
    
    # Metadata
    evidence: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Phase 17: Evidence URLs (relative paths under /static/evidence)
    snapshot_face_url: Optional[str] = None
    snapshot_scene_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    
    def __post_init__(self):
        if not self.idempotency_key:
            from datetime import datetime
            dt = datetime.fromtimestamp(self.occurred_at)
            date_str = dt.strftime("%Y-%m-%d")
            if self.event_type == "long_exit":
                out_time = self.evidence.get("out_time", "")
                if out_time:
                    object.__setattr__(self, "idempotency_key", f"{date_str}:{self.student_id}:{self.event_type}:{out_time}")
                else:
                    object.__setattr__(self, "idempotency_key", f"{date_str}:{self.student_id}:{self.event_type}")
            else:
                object.__setattr__(self, "idempotency_key", f"{date_str}:{self.student_id}:{self.event_type}")


@dataclass(frozen=True)
class NotificationResult:
    """
    Result of a notification delivery attempt.
    
    Immutable record capturing success/failure and provider-specific details.
    """
    payload: NotificationPayload
    status: NotificationStatus
    channel: NotificationChannel
    provider_name: str
    provider_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    attempt: int = 1
    max_attempts: int = 3
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    sent_at: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    
    @property
    def is_success(self) -> bool:
        return self.status == NotificationStatus.SENT
    
    @property
    def is_retryable(self) -> bool:
        return self.status in (NotificationStatus.FAILED, NotificationStatus.RATE_LIMITED) and self.attempt < self.max_attempts
    
    @property
    def is_terminal_failure(self) -> bool:
        return self.status == NotificationStatus.FAILED and self.attempt >= self.max_attempts


class BaseNotificationProvider(ABC):
    """
    Abstract base class for all notification providers.
    
    Providers implement channel-specific delivery logic while adhering to
    the common interface for retry, rate limiting, and error handling.
    """
    
    def __init__(
        self,
        name: str,
        channel: NotificationChannel,
        max_retries: int = 3,
        base_retry_delay: float = 10.0,
        max_retry_delay: float = 300.0,
        timeout: int = 30,
    ):
        self.name = name
        self.channel = channel
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.max_retry_delay = max_retry_delay
        self.timeout = timeout
        self._enabled = True
        self._rate_limit_state: Dict[str, float] = {}  # recipient -> next_allowed_time
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'zalo_zns_official', 'esms_vn')."""
        pass
    
    @property
    def is_enabled(self) -> bool:
        return self._enabled
    
    def enable(self) -> None:
        self._enabled = True
    
    def disable(self) -> None:
        self._enabled = False
    
    @abstractmethod
    async def send_notification(self, payload: NotificationPayload) -> NotificationResult:
        """
        Send a notification to the specified recipient.
        
        Args:
            payload: Notification payload with all delivery information
            
        Returns:
            NotificationResult with delivery status and provider response
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on the provider.
        
        Returns:
            Dict with health status, quota/balance if applicable
        """
        pass
    
    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[int] = None) -> float:
        """Calculate retry delay with exponential backoff."""
        if retry_after:
            return float(retry_after)
        
        delay = self.base_retry_delay * (2 ** (attempt - 1))
        return min(delay, self.max_retry_delay)
    
    def _check_rate_limit(self, recipient_id: str) -> Optional[int]:
        """Check if recipient is rate limited. Returns retry_after seconds if limited."""
        import time
        next_allowed = self._rate_limit_state.get(recipient_id, 0)
        now = time.time()
        if now < next_allowed:
            return int(next_allowed - now) + 1
        return None
    
    def _set_rate_limit(self, recipient_id: str, retry_after: int) -> None:
        """Set rate limit for recipient."""
        import time
        self._rate_limit_state[recipient_id] = time.time() + retry_after
    
    def _clear_rate_limit(self, recipient_id: str) -> None:
        """Clear rate limit for recipient after successful send."""
        self._rate_limit_state.pop(recipient_id, None)
    
    def get_channel_name(self) -> str:
        return self.channel.value
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, channel={self.channel.value}, enabled={self._enabled})"