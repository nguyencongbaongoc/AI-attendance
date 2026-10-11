"""
Phase 15 — Multi-Channel Notification Engine.

Provides an extensible notification dispatcher with support for:
- Zalo ZNS (Tier 1)
- SMS Gateways - eSMS/SpeedSMS (Tier 2)
- Telegram Bot (Tier 3 / Admin fallback)
"""

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationPayload,
    NotificationResult,
    NotificationStatus,
)
from app.notifications.dispatcher import NotificationDispatcher

__all__ = [
    "BaseNotificationProvider",
    "NotificationPayload",
    "NotificationResult",
    "NotificationStatus",
    "NotificationDispatcher",
]