"""
Phase 15 — SMS Gateway Providers Implementation.

Supports Vietnamese SMS aggregators:
- eSMS.vn (Enterprise SMS)
- SpeedSMS.vn (SpeedSMS)

Both providers support Brandname SMS for OTP/notifications.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
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


class SMSProviderError(Exception):
    """Base exception for SMS provider errors."""
    def __init__(self, message: str, error_code: Optional[str] = None, response: Optional[Dict] = None):
        super().__init__(message)
        self.error_code = error_code
        self.response = response


class SMSRateLimitError(SMSProviderError):
    """Rate limit exceeded."""
    pass


class SMSQuotaError(SMSProviderError):
    """Credit/quota exhausted."""
    pass


class SMSInvalidPhoneError(SMSProviderError):
    """Invalid phone number format."""
    pass


class ESMSProvider(BaseNotificationProvider):
    """
    eSMS.vn Provider for Vietnamese SMS delivery.
    
    API Documentation: https://esms.vn/developer
    Supports Brandname SMS (CSKH/Care) for notifications.
    """
    
    BASE_URL = "https://api.esms.vn/MainService.svc/json"
    
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        brandname: Optional[str] = None,
        max_retries: int = 3,
        base_retry_delay: float = 10.0,
        max_retry_delay: float = 300.0,
        timeout: int = 30,
        sandbox: bool = True,  # Use sandbox by default for safety
    ):
        super().__init__(
            name="esms_vn",
            channel=NotificationChannel.SMS,
            max_retries=max_retries,
            base_retry_delay=base_retry_delay,
            max_retry_delay=max_retry_delay,
            timeout=timeout,
        )
        
        self.api_key = api_key
        self.secret_key = secret_key
        self.brandname = brandname or "AI-ATTEND"
        self.sandbox = sandbox
        self._session: Optional[aiohttp.ClientSession] = None
        
        # eSMS requires timestamp + signature for authentication
        self._last_timestamp = 0
    
    @property
    def provider_name(self) -> str:
        return "esms_vn"
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session
    
    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _generate_timestamp(self) -> str:
        """Generate timestamp for eSMS API (milliseconds since epoch)."""
        # Ensure monotonic timestamps
        current = int(time.time() * 1000)
        if current <= self._last_timestamp:
            current = self._last_timestamp + 1
        self._last_timestamp = current
        return str(current)
    
    def _generate_signature(self, timestamp: str, payload: str = "") -> str:
        """Generate SHA256 signature for eSMS API."""
        import hashlib
        # Signature = SHA256(API_KEY + SECRET_KEY + TIMESTAMP + PAYLOAD)
        data = self.api_key + self.secret_key + timestamp + payload
        return hashlib.sha256(data.encode('utf-8')).hexdigest().upper()
    
    def _normalize_phone_for_esms(self, phone: str) -> str:
        """
        Normalize phone for eSMS API.
        
        eSMS expects: 84xxxxxxxxx (no +, no leading 0)
        """
        digits = ''.join(filter(str.isdigit, phone))
        
        if digits.startswith("84"):
            return digits
        elif digits.startswith("0"):
            return "84" + digits[1:]
        elif len(digits) == 9 and digits[0] in "35789":
            return "84" + digits
        else:
            return digits
    
    def _build_sms_content(self, payload: NotificationPayload) -> str:
        """Build SMS content from notification payload."""
        # eSMS Brandname SMS has 160 char limit (70 for Unicode)
        # Use concise format
        event_labels = {
            "morning_absence": "VANG MAT",
            "long_exit": "RA VE SOM",
            "missing_checkout": "QUEN CHECKOUT",
        }
        
        label = event_labels.get(payload.event_type, "THONG BAO")
        time_str = datetime.fromtimestamp(payload.occurred_at).strftime("%H:%M %d/%m")
        
        # Format: [AI-ATTEND] Label: StudentName at Time. Details...
        content = f"[{self.brandname}] {label}: {payload.student_name} luc {time_str}"
        
        # Add optional details
        if "camera_name" in payload.evidence:
            content += f" tai {payload.evidence['camera_name']}"
        if "out_time" in payload.evidence:
            content += f" ra {payload.evidence['out_time']}"
        
        # Truncate to 160 chars for ASCII SMS
        if len(content) > 160:
            content = content[:157] + "..."
        
        return content
    
    async def send_notification(self, payload: NotificationPayload) -> NotificationResult:
        """Send SMS via eSMS API."""
        if not self.is_enabled:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.DISABLED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="Provider disabled",
            )
        
        # Normalize phone
        phone = self._normalize_phone_for_esms(payload.recipient_phone)
        
        # Validate phone format for Vietnam
        if not (phone.startswith("84") and len(phone) == 11 and phone[2] in "35789"):
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message=f"Invalid phone format for Vietnam: {phone}",
            )
        
        # Build SMS content
        content = self._build_sms_content(payload)
        
        # Prepare request
        timestamp = self._generate_timestamp()
        sms_payload = {
            "Phone": phone,
            "Content": content,
            "ApiKey": self.api_key,
            "SecretKey": self.secret_key,
            "SmsType": 2,  # Brandname SMS (CSKH)
            "Brandname": self.brandname,
            "IsUnicode": 0,  # ASCII for longer messages
            "RequestId": payload.idempotency_key[:50],  # Max 50 chars
        }
        
        # Generate signature
        payload_str = f"Phone={phone}&Content={content}&ApiKey={self.api_key}&SecretKey={self.secret_key}&SmsType=2&Brandname={self.brandname}&IsUnicode=0"
        signature = self._generate_signature(timestamp, payload_str)
        
        session = await self._get_session()
        url = f"{self.BASE_URL}/SendMultipleMessage_V4_post_json/"
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # Add auth params to URL
        params = {
            "ApiKey": self.api_key,
            "SecretKey": self.secret_key,
            "Timestamp": timestamp,
            "Signature": signature,
        }
        
        try:
            async with session.post(url, json=sms_payload, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # eSMS response format
                    if data.get("CodeResult") == "100":
                        # Success
                        return NotificationResult(
                            payload=payload,
                            status=NotificationStatus.SENT,
                            channel=self.channel,
                            provider_name=self.provider_name,
                            provider_response=data,
                            sent_at=datetime.utcnow().isoformat() + "Z",
                        )
                    else:
                        # Error
                        error_msg = data.get("ErrorMessage", "Unknown error")
                        code = data.get("CodeResult", "unknown")
                        
                        status = NotificationStatus.FAILED
                        if code in ("101", "102"):  # Invalid phone
                            status = NotificationStatus.FAILED
                        elif code == "112":  # Quota exceeded
                            status = NotificationStatus.FAILED
                        elif code in ("115", "116"):  # Rate limit
                            status = NotificationStatus.RATE_LIMITED
                        
                        return NotificationResult(
                            payload=payload,
                            status=status,
                            channel=self.channel,
                            provider_name=self.provider_name,
                            provider_response=data,
                            error_message=f"eSMS {code}: {error_msg}",
                        )
                else:
                    text = await response.text()
                    return NotificationResult(
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        channel=self.channel,
                        provider_name=self.provider_name,
                        error_message=f"HTTP {response.status}: {text}",
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
            logger.error(f"eSMS send error: {e}")
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message=str(e),
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check eSMS account balance and health."""
        try:
            session = await self._get_session()
            url = f"{self.BASE_URL}/GetBalance/"
            
            timestamp = self._generate_timestamp()
            params = {
                "ApiKey": self.api_key,
                "SecretKey": self.secret_key,
                "Timestamp": timestamp,
            }
            
            payload_str = f"ApiKey={self.api_key}&SecretKey={self.secret_key}"
            signature = self._generate_signature(timestamp, payload_str)
            params["Signature"] = signature
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("CodeResult") == "100":
                        balance = data.get("Balance", 0)
                        return {
                            "healthy": True,
                            "provider": self.provider_name,
                            "balance": balance,
                            "currency": "VND",
                            "brandname": self.brandname,
                        }
                
                return {
                    "healthy": False,
                    "provider": self.provider_name,
                    "error": f"Balance check failed: {response.status}",
                }
                
        except Exception as e:
            return {
                "healthy": False,
                "provider": self.provider_name,
                "error": str(e),
            }


class SpeedSMSProvider(BaseNotificationProvider):
    """
    SpeedSMS.vn Provider for Vietnamese SMS delivery.
    
    API Documentation: https://speedsms.vn/developer
    Simple token-based authentication.
    """
    
    BASE_URL = "https://api.speedsms.vn"
    
    def __init__(
        self,
        api_token: str,
        brandname: Optional[str] = None,
        max_retries: int = 3,
        base_retry_delay: float = 10.0,
        max_retry_delay: float = 300.0,
        timeout: int = 30,
        sandbox: bool = True,
    ):
        super().__init__(
            name="speedsms_vn",
            channel=NotificationChannel.SMS,
            max_retries=max_retries,
            base_retry_delay=base_retry_delay,
            max_retry_delay=max_retry_delay,
            timeout=timeout,
        )
        
        self.api_token = api_token
        self.brandname = brandname or "AI-ATTEND"
        self.sandbox = sandbox
        self._session: Optional[aiohttp.ClientSession] = None
    
    @property
    def provider_name(self) -> str:
        return "speedsms_vn"
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session
    
    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _normalize_phone_for_speedsms(self, phone: str) -> str:
        """
        Normalize phone for SpeedSMS API.
        
        SpeedSMS expects: 84xxxxxxxxx (no +, no leading 0)
        """
        digits = ''.join(filter(str.isdigit, phone))
        
        if digits.startswith("84"):
            return digits
        elif digits.startswith("0"):
            return "84" + digits[1:]
        elif len(digits) == 9 and digits[0] in "35789":
            return "84" + digits
        else:
            return digits
    
    def _build_sms_content(self, payload: NotificationPayload) -> str:
        """Build SMS content for SpeedSMS."""
        event_labels = {
            "morning_absence": "VANG MAT",
            "long_exit": "RA VE SOM",
            "missing_checkout": "QUEN CHECKOUT",
        }
        
        label = event_labels.get(payload.event_type, "THONG BAO")
        time_str = datetime.fromtimestamp(payload.occurred_at).strftime("%H:%M %d/%m")
        
        content = f"[{self.brandname}] {label}: {payload.student_name} luc {time_str}"
        
        if "camera_name" in payload.evidence:
            content += f" tai {payload.evidence['camera_name']}"
        if "out_time" in payload.evidence:
            content += f" ra {payload.evidence['out_time']}"
        
        if len(content) > 160:
            content = content[:157] + "..."
        
        return content
    
    async def send_notification(self, payload: NotificationPayload) -> NotificationResult:
        """Send SMS via SpeedSMS API."""
        if not self.is_enabled:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.DISABLED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message="Provider disabled",
            )
        
        phone = self._normalize_phone_for_speedsms(payload.recipient_phone)
        
        if not (phone.startswith("84") and len(phone) == 11 and phone[2] in "35789"):
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message=f"Invalid phone format for Vietnam: {phone}",
            )
        
        content = self._build_sms_content(payload)
        
        session = await self._get_session()
        url = f"{self.BASE_URL}/sms/send"
        
        # SpeedSMS uses Basic Auth with api_token as username
        import base64
        auth = base64.b64encode(f"{self.api_token}:x".encode()).decode()
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        }
        
        sms_data = {
            "to": [phone],
            "content": content,
            "brandname": self.brandname,
            "unicode": False,  # ASCII
        }
        
        if self.sandbox:
            sms_data["sandbox"] = 1
        
        try:
            async with session.post(url, json=sms_data, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get("status") == "success":
                        return NotificationResult(
                            payload=payload,
                            status=NotificationStatus.SENT,
                            channel=self.channel,
                            provider_name=self.provider_name,
                            provider_response=data,
                            sent_at=datetime.utcnow().isoformat() + "Z",
                        )
                    else:
                        error_msg = data.get("message", "Unknown error")
                        return NotificationResult(
                            payload=payload,
                            status=NotificationStatus.FAILED,
                            channel=self.channel,
                            provider_name=self.provider_name,
                            provider_response=data,
                            error_message=f"SpeedSMS: {error_msg}",
                        )
                else:
                    text = await response.text()
                    return NotificationResult(
                        payload=payload,
                        status=NotificationStatus.FAILED,
                        channel=self.channel,
                        provider_name=self.provider_name,
                        error_message=f"HTTP {response.status}: {text}",
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
            logger.error(f"SpeedSMS send error: {e}")
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                error_message=str(e),
            )
    
    async def health_check(self) -> Dict[str, Any]:
        """Check SpeedSMS account balance."""
        try:
            session = await self._get_session()
            url = f"{self.BASE_URL}/user/info"
            
            import base64
            auth = base64.b64encode(f"{self.api_token}:x".encode()).decode()
            
            headers = {"Authorization": f"Basic {auth}"}
            
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "success":
                        user_info = data.get("data", {})
                        return {
                            "healthy": True,
                            "provider": self.provider_name,
                            "balance": user_info.get("balance", 0),
                            "currency": "VND",
                            "brandname": self.brandname,
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


class MockSMSProvider(BaseNotificationProvider):
    """
    Mock SMS provider for testing without real API calls.
    
    Simulates various responses for testing fallback and retry logic.
    """
    
    def __init__(
        self,
        name: str = "mock_sms",
        success_rate: float = 1.0,
        delay_seconds: float = 0.1,
        **kwargs,
    ):
        super().__init__(
            name=name,
            channel=NotificationChannel.SMS,
            **kwargs,
        )
        self.success_rate = success_rate
        self.delay_seconds = delay_seconds
        self.call_log: List[Dict] = []
    
    @property
    def provider_name(self) -> str:
        return self.name
    
    async def send_notification(self, payload: NotificationPayload) -> NotificationResult:
        """Simulate SMS send with configurable success rate."""
        import random
        
        self.call_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "payload_id": payload.idempotency_key,
            "phone": payload.recipient_phone,
        })
        
        await asyncio.sleep(self.delay_seconds)
        
        if random.random() < self.success_rate:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.SENT,
                channel=self.channel,
                provider_name=self.provider_name,
                provider_response={"mock": True, "message_id": f"MOCK-{int(time.time())}"},
                sent_at=datetime.utcnow().isoformat() + "Z",
            )
        else:
            return NotificationResult(
                payload=payload,
                status=NotificationStatus.FAILED,
                channel=self.channel,
                provider_name=self.provider_name,
                provider_response={"mock": True, "error": "Simulated failure"},
                error_message="Mock provider simulated failure",
            )
    
    async def health_check(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "provider": self.provider_name,
            "mock": True,
            "success_rate": self.success_rate,
            "calls_made": len(self.call_log),
        }


def create_esms_provider_from_settings() -> Optional[ESMSProvider]:
    """Create eSMS provider from settings if configured."""
    from app.config.settings import load_settings
    
    settings = load_settings()
    
    if not hasattr(settings, 'esms') or not settings.esms.api_key or not settings.esms.secret_key:
        return None
    
    return ESMSProvider(
        api_key=settings.esms.api_key,
        secret_key=settings.esms.secret_key,
        brandname=getattr(settings.esms, 'brandname', None),
        sandbox=getattr(settings.esms, 'sandbox', True),
    )


def create_speedsms_provider_from_settings() -> Optional[SpeedSMSProvider]:
    """Create SpeedSMS provider from settings if configured."""
    from app.config.settings import load_settings
    
    settings = load_settings()
    
    if not hasattr(settings, 'speedsms') or not settings.speedsms.api_token:
        return None
    
    return SpeedSMSProvider(
        api_token=settings.speedsms.api_token,
        brandname=getattr(settings.speedsms, 'brandname', None),
        sandbox=getattr(settings.speedsms, 'sandbox', True),
    )