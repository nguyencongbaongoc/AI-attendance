"""
Phase 15 — Telegram Provider Wrapper.

Wraps the existing TelegramBot to conform to the BaseNotificationProvider interface.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationChannel,
    NotificationPayload,
    NotificationResult,
    NotificationStatus,
)

logger = logging.getLogger(__name__)


class TelegramProvider(BaseNotificationProvider):
    """
    Telegram Provider wrapping the existing TelegramBot.
    
    Adapts the Phase 37B/37C TelegramBot to the new provider interface.
    """
    
    def __init__(
        self,
        bot_token: str,
        api_base_url: str = "https://api.telegram.org/bot",
        timeout: int = 30,
        max_retries: int = 3,
        base_retry_delay: float = 10.0,
        max_retry_delay: float = 300.0,
    ):
        super().__init__(
            name="telegram_bot",
            channel=NotificationChannel.TELEGRAM,
            max_retries=max_retries,
            base_retry_delay=base_retry_delay,
            max_retry_delay=max_retry_delay,
            timeout=timeout,
        )
        
        self.bot_token = bot_token
        self.api_base_url = api_base_url
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_send_time: Dict[str, float] = {}
        self._min_interval_seconds = 1.0
    
    @property
    def provider_name(self) -> str:
        return "telegram_bot"
    
    async def _get_session(self) -> aiohttp.ClientSession:
        import aiohttp
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session
    
    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def send_notification(self, payload: NotificationPayload) -> NotificationResult:
        """Send message via Telegram Bot API with rich media support."""
        if not self.is_enabled:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.DISABLED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="Provider disabled",
            )
        
        # Get chat ID - prefer Telegram chat ID, fallback to phone (not supported directly)
        chat_id = payload.recipient_telegram_chat_id
        if not chat_id:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.NO_RECIPIENT,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="No Telegram chat_id available for recipient",
            )
        
        # Rate limiting per chat
        import time
        now = time.time()
        last_time = self._last_send_time.get(chat_id, 0)
        if now - last_time < self._min_interval_seconds:
            await asyncio.sleep(self._min_interval_seconds - (now - last_time))
        
        try:
            session = await self._get_session()
            
            # Check if we have a face snapshot to send as photo
            base_url = "http://localhost:8000"  # Should be configurable
            photo_url = None
            if payload.snapshot_face_url:
                photo_url = f"{base_url}/{payload.snapshot_face_url}"
            elif payload.snapshot_scene_url:
                photo_url = f"{base_url}/{payload.snapshot_scene_url}"
            
            if photo_url:
                # Send photo with caption
                url = f"{self.api_base_url}{self.bot_token}/sendPhoto"
                message_data = {
                    "chat_id": chat_id,
                    "photo": photo_url,
                    "caption": payload.message,
                    "parse_mode": "HTML",
                }
            else:
                # Send text message only
                url = f"{self.api_base_url}{self.bot_token}/sendMessage"
                message_data = {
                    "chat_id": chat_id,
                    "text": payload.message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
            
            async with session.post(url, json=message_data) as response:
                self._last_send_time[chat_id] = time.time()
                
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        return NotificationResult(
                            payload=payload,
                            status=NotificationStatus.SENT,
                            channel=self.channel,
                            provider_name=self.provider_name,
                            provider_response=data,
                            sent_at=datetime.utcnow().isoformat() + "Z",
                        )
                    else:
                        error = data.get("description", "Unknown error")
                        logger.error(f"Telegram API error: {error}")
                        return NotificationResult(
                            payload=payload,
                            status=NotificationStatus.FAILED,
                            channel=self.channel,
                            provider_name=self.provider_name,
                            provider_response=data,
                            error_message=error,
                        )
                
                elif response.status == 429:
                    # Rate limited
                    retry_after = 1
                    try:
                        data = await response.json()
                        retry_after = data.get("parameters", {}).get("retry_after", 1)
                    except:
                        pass
                    logger.warning(f"Telegram rate limited, retry after {retry_after}s")
                    return NotificationResult(
                        payload=payload,
                        status=NotificationStatus.RATE_LIMITED,
                        channel=self.channel,
                        provider_name=self.provider_name,
                        error_message=f"RATE_LIMITED:{retry_after}",
                        retry_after_seconds=retry_after,
                    )
                
                else:
                    error_text = await response.text()
                    logger.error(f"Telegram HTTP error {response.status}: {error_text}")
                    return NotificationResult(
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        channel=self.channel,
                        provider_name=self.provider_name,
                        error_message=f"HTTP {response.status}: {error_text}",
                    )
        
        except asyncio.TimeoutError:
            logger.error(f"Timeout sending Telegram message to {chat_id}")
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="TIMEOUT",
            )
        except Exception as e:
            logger.error(f"Error sending Telegram message to {chat_id}: {e}")
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message=str(e),
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Telegram bot health."""
        try:
            session = await self._get_session()
            url = f"{self.api_base_url}{self.bot_token}/getMe"
            
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        bot_info = data["result"]
                        return {
                            "healthy": True,
                            "provider": self.provider_name,
                            "bot_username": bot_info.get("username"),
                            "bot_id": bot_info.get("id"),
                            "can_join_groups": bot_info.get("can_join_groups", False),
                            "can_read_all_group_messages": bot_info.get("can_read_all_group_messages", False),
                        }
                
                return {
                    "healthy": False,
                    "provider": self.provider_name,
                    "error": f"Health check failed: {response.status}",
                }
                
        except Exception as e:
            return {
                "healthy": False,
                "provider": self.provider_name,
                "error": str(e),
            }


def create_telegram_provider_from_settings() -> Optional[TelegramProvider]:
    """Create Telegram provider from settings if configured."""
    from app.config.settings import load_settings
    
    settings = load_settings()
    
    if not settings.telegram.bot_token:
        return None
    
    return TelegramProvider(
        bot_token=settings.telegram.bot_token,
    )