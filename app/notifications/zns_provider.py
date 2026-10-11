"""
Phase 15 — Zalo ZNS Provider Implementation.

Official Zalo Notification Service integration for school-to-parent communication.
Supports Zalo Official Account (OA) authentication and template messaging.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import aiohttp

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationChannel,
    NotificationPayload,
    NotificationResult,
    NotificationStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class ZaloTokenInfo:
    """Zalo access token with expiry tracking."""
    access_token: str
    refresh_token: str
    expires_at: float  # Unix timestamp
    token_type: str = "Bearer"
    
    @property
    def is_expired(self) -> bool:
        # Refresh 5 minutes before actual expiry
        return time.time() >= (self.expires_at - 300)
    
    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and not self.is_expired


class ZaloZNSError(Exception):
    """Base exception for Zalo ZNS errors."""
    def __init__(self, message: str, error_code: Optional[str] = None, response: Optional[Dict] = None):
        super().__init__(message)
        self.error_code = error_code
        self.response = response


class ZaloZNSAuthError(ZaloZNSError):
    """Authentication/token errors."""
    pass


class ZaloZNSRateLimitError(ZaloZNSError):
    """Rate limit exceeded."""
    pass


class ZaloZNSQuotaError(ZaloZNSError):
    """Daily/monthly quota exceeded."""
    pass


class ZaloZNSProvider(BaseNotificationProvider):
    """
    Zalo ZNS (Zalo Notification Service) Provider.
    
    Integrates with Zalo Official Account API for sending template messages
    to users who have interacted with the OA.
    
    Documentation: https://developers.zalo.me/docs/official-account/zns
    """
    
    # Zalo API endpoints
    BASE_URL = "https://openapi.zalo.me/v3.0"
    OA_BASE_URL = "https://openapi.zalo.me/v2.0"
    
    # Template codes (configured in Zalo OA dashboard)
    TEMPLATE_CODES = {
        "morning_absence": "student_absence_morning",
        "long_exit": "student_exit_early", 
        "missing_checkout": "student_missing_checkout",
    }
    
    def __init__(
        self,
        app_id: str,
        secret_key: str,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        max_retries: int = 3,
        base_retry_delay: float = 10.0,
        max_retry_delay: float = 300.0,
        timeout: int = 30,
    ):
        super().__init__(
            name="zalo_zns_official",
            channel=NotificationChannel.ZALO_ZNS,
            max_retries=max_retries,
            base_retry_delay=base_retry_delay,
            max_retry_delay=max_retry_delay,
            timeout=timeout,
        )
        
        self.app_id = app_id
        self.secret_key = secret_key
        self._token_info: Optional[ZaloTokenInfo] = None
        self._session: Optional[aiohttp.ClientSession] = None
        
        # Initialize token if provided
        if access_token and refresh_token:
            # Assume 2 hour expiry if not specified
            self._token_info = ZaloTokenInfo(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=time.time() + 7200,
            )
        
        # Template ID mapping (loaded from config or OA dashboard)
        self._template_ids: Dict[str, str] = {}
    
    @property
    def provider_name(self) -> str:
        return "zalo_zns_official"
    
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
    
    def _generate_signature(self, data: str) -> str:
        """Generate HMAC-SHA256 signature for Zalo API requests."""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    async def _ensure_valid_token(self) -> str:
        """Ensure we have a valid access token, refreshing if necessary."""
        if self._token_info and self._token_info.is_valid:
            return self._token_info.access_token
        
        if self._token_info and self._token_info.is_expired:
            # Try to refresh
            try:
                await self._refresh_access_token()
                return self._token_info.access_token
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}")
        
        # Need full authentication
        await self._authenticate()
        return self._token_info.access_token
    
    async def _authenticate(self) -> None:
        """Authenticate with Zalo to get access token."""
        session = await self._get_session()
        
        # Zalo OA authentication endpoint
        url = f"{self.OA_BASE_URL}/oa/getaccesstoken"
        
        params = {
            "app_id": self.app_id,
            "grant_type": "client_credential",
        }
        
        # Generate signature
        param_str = f"app_id={self.app_id}&grant_type=client_credential"
        signature = self._generate_signature(param_str)
        params["mac"] = signature
        
        try:
            async with session.post(url, data=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("error") == 0:
                        self._token_info = ZaloTokenInfo(
                            access_token=data["access_token"],
                            refresh_token=data.get("refresh_token", ""),
                            expires_at=time.time() + data.get("expires_in", 7200),
                        )
                        logger.info("Zalo ZNS authentication successful")
                        return
                    else:
                        raise ZaloZNSAuthError(
                            f"Zalo auth failed: {data.get('message', 'Unknown error')}",
                            error_code=str(data.get("error")),
                            response=data
                        )
                else:
                    text = await response.text()
                    raise ZaloZNSAuthError(f"HTTP {response.status}: {text}")
                    
        except aiohttp.ClientError as e:
            raise ZaloZNSAuthError(f"Network error during auth: {e}")
    
    async def _refresh_access_token(self) -> None:
        """Refresh access token using refresh token."""
        if not self._token_info or not self._token_info.refresh_token:
            await self._authenticate()
            return
        
        session = await self._get_session()
        url = f"{self.OA_BASE_URL}/oa/refreshaccesstoken"
        
        params = {
            "app_id": self.app_id,
            "refresh_token": self._token_info.refresh_token,
            "grant_type": "refresh_token",
        }
        
        param_str = f"app_id={self.app_id}&refresh_token={self._token_info.refresh_token}&grant_type=refresh_token"
        signature = self._generate_signature(param_str)
        params["mac"] = signature
        
        try:
            async with session.post(url, data=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("error") == 0:
                        self._token_info = ZaloTokenInfo(
                            access_token=data["access_token"],
                            refresh_token=data.get("refresh_token", self._token_info.refresh_token),
                            expires_at=time.time() + data.get("expires_in", 7200),
                        )
                        logger.info("Zalo ZNS token refreshed successfully")
                        return
                    else:
                        raise ZaloZNSAuthError(
                            f"Token refresh failed: {data.get('message')}",
                            error_code=str(data.get("error"))
                        )
                else:
                    text = await response.text()
                    raise ZaloZNSAuthError(f"HTTP {response.status}: {text}")
                    
        except aiohttp.ClientError as e:
            raise ZaloZNSAuthError(f"Network error during token refresh: {e}")
    
    def _get_template_id(self, event_type: str) -> Optional[str]:
        """Get template ID for event type."""
        # First check cached mapping
        if event_type in self._template_ids:
            return self._template_ids[event_type]
        
        # Fall back to default template codes
        return self.TEMPLATE_CODES.get(event_type)
    
    def _build_zns_payload(
        self,
        payload: NotificationPayload,
        template_id: str,
    ) -> Dict[str, Any]:
        """
        Build ZNS API request payload.
        
        ZNS template format:
        {
            "phone": "84901234567",
            "template_id": "template_code",
            "template_data": {
                "student_name": "Nguyen Van A",
                "event_type": "IN",
                "timestamp": "2026-10-10 08:00:00",
                "camera_name": "Main Gate"
            }
        }
        """
        # Normalize phone to Zalo format (84xxxxxxxxx)
        phone = self._normalize_phone_for_zns(payload.recipient_phone)
        
        # Build template data from evidence and metadata
        template_data = {
            "student_name": payload.student_name,
            "event_type": payload.event_type.replace("_", " ").title(),
            "timestamp": datetime.fromtimestamp(payload.occurred_at).strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        # Add optional fields from evidence
        if "camera_name" in payload.evidence:
            template_data["camera_name"] = payload.evidence["camera_name"]
        if "out_time" in payload.evidence:
            template_data["out_time"] = payload.evidence["out_time"]
        if "threshold_minutes" in payload.evidence:
            template_data["threshold_minutes"] = str(payload.evidence["threshold_minutes"])
        
        return {
            "phone": phone,
            "template_id": template_id,
            "template_data": template_data,
        }
    
    def _normalize_phone_for_zns(self, phone: str) -> str:
        """
        Normalize phone number for ZNS API.
        
        ZNS expects format: 84xxxxxxxxx (no +, no leading 0)
        """
        # Remove all non-digits
        digits = ''.join(filter(str.isdigit, phone))
        
        # Handle Vietnamese formats
        if digits.startswith("84"):
            return digits
        elif digits.startswith("0"):
            return "84" + digits[1:]
        elif len(digits) == 9 and digits[0] in "35789":
            # Assume Vietnam mobile without country code
            return "84" + digits
        else:
            # Return as-is, let API validate
            return digits
    
    def _parse_zns_error(self, response: Dict[str, Any]) -> Exception:
        """Parse ZNS API error response into appropriate exception."""
        error_code = str(response.get("error", "unknown"))
        message = response.get("message", "Unknown error")
        
        # Error code mappings
        if error_code in ("-213", "-214", "-215"):
            # Token expired/invalid
            return ZaloZNSAuthError(message, error_code, response)
        elif error_code == "-202":
            # Rate limit
            return ZaloZNSRateLimitError(message, error_code, response)
        elif error_code in ("-301", "-302", "-303"):
            # Quota exceeded
            return ZaloZNSQuotaError(message, error_code, response)
        elif error_code == "-101":
            # Invalid phone
            return ZaloZNSError(message, error_code, response)
        else:
            return ZaloZNSError(message, error_code, response)
    
    async def send_notification(self, payload: NotificationPayload) -> NotificationResult:
        """Send ZNS template message."""
        if not self.is_enabled:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.DISABLED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="Provider disabled",
            )
        
        try:
            # Ensure valid token
            access_token = await self._ensure_valid_token()
            
            # Get template ID
            template_id = self._get_template_id(payload.event_type)
            if not template_id:
                return NotificationResult(
                    payload=payload,
                    status=NotificationStatus.FAILED,
                    channel=self.channel,
                    provider_name=self.provider_name,
                    error_message=f"No template configured for event type: {payload.event_type}",
                )
            
            # Build request
            zns_payload = self._build_zns_payload(payload, template_id)
            
            session = await self._get_session()
            url = f"{self.BASE_URL}/zns/send"
            
            headers = {
                "Content-Type": "application/json",
                "access_token": access_token,
            }
            
            # Generate signature for ZNS send
            import urllib.parse
            param_str = json.dumps(zns_payload, separators=(',', ':'), ensure_ascii=False)
            signature = self._generate_signature(param_str)
            headers["mac"] = signature
            
            async with session.post(url, json=zns_payload, headers=headers) as response:
                response_data = await response.json()
                
                if response.status == 200 and response_data.get("error") == 0:
                    # Success
                    return NotificationResult(
                        payload=payload,
                        status=NotificationStatus.SENT,
                        channel=self.channel,
                        provider_name=self.provider_name,
                        provider_response=response_data,
                        sent_at=datetime.utcnow().isoformat() + "Z",
                    )
                else:
                    # Parse error
                    error = self._parse_zns_error(response_data)
                    
                    if isinstance(error, ZaloZNSAuthError):
                        # Token might be stale, invalidate and retry once
                        self._token_info = None
                        if payload.metadata.get("_retry_count", 0) == 0:
                            payload.metadata["_retry_count"] = 1
                            return await self.send_notification(payload)
                    
                    status = NotificationStatus.FAILED
                    retry_after = None
                    
                    if isinstance(error, ZaloZNSRateLimitError):
                        status = NotificationStatus.RATE_LIMITED
                        retry_after = 60  # Default 60s
                    
                    return NotificationResult(
                        payload=payload,
                        status=status,
                        channel=self.channel,
                        provider_name=self.provider_name,
                        provider_response=response_data,
                        error_message=str(error),
                        retry_after_seconds=retry_after,
                    )
                    
        except asyncio.TimeoutError:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="TIMEOUT",
            )
        except Exception as e:
            logger.error(f"ZNS send error: {e}")
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message=str(e),
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check ZNS provider health and quota."""
        try:
            # Try to get token (will authenticate if needed)
            access_token = await self._ensure_valid_token()
            
            # Check quota/balance via OA info endpoint
            session = await self._get_session()
            url = f"{self.OA_BASE_URL}/oa/getoaInfo"
            
            params = {"access_token": access_token}
            signature = self._generate_signature(f"access_token={access_token}")
            params["mac"] = signature
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("error") == 0:
                        oa_info = data.get("data", {})
                        return {
                            "healthy": True,
                            "provider": self.provider_name,
                            "oa_name": oa_info.get("name", "Unknown"),
                            "follower_count": oa_info.get("follower_count", 0),
                            "daily_quota": oa_info.get("daily_quota", "Unknown"),
                            "used_quota": oa_info.get("used_quota", "Unknown"),
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
    
    async def test_send(
        self,
        phone: str,
        template_id: str,
        template_data: Dict[str, str],
    ) -> NotificationResult:
        """Send a test ZNS message (for development/verification)."""
        payload = NotificationPayload(
            event_id=f"TEST-{int(time.time())}",
            event_type="test",
            student_id="TEST",
            student_name="Test Student",
            recipient_id="TEST",
            recipient_name="Test Parent",
            recipient_phone=phone,
            message="Test message",
            evidence={},
        )
        
        # Override template ID for test
        original_get_template = self._get_template_id
        self._template_ids["test"] = template_id
        self._get_template_id = lambda t: template_id if t == "test" else original_get_template(t)
        
        try:
            return await self.send_notification(payload)
        finally:
            self._get_template_id = original_get_template


def create_zns_provider_from_settings() -> Optional[ZaloZNSProvider]:
    """Create ZNS provider from settings if configured."""
    from app.config.settings import load_settings
    
    settings = load_settings()
    
    if not hasattr(settings, 'zalo') or not settings.zalo.app_id or not settings.zalo.secret_key:
        return None
    
    return ZaloZNSProvider(
        app_id=settings.zalo.app_id,
        secret_key=settings.zalo.secret_key,
        access_token=getattr(settings.zalo, 'access_token', None),
        refresh_token=getattr(settings.zalo, 'refresh_token', None),
    )