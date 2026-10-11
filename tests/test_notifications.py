"""
Phase 15 — Notification System Test Suite.

Tests the multi-channel notification dispatcher, providers, and fallback logic.
All tests run against mock/sandbox providers to prevent real API calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.notifications.base import (
    BaseNotificationProvider,
    NotificationChannel,
    NotificationPayload,
    NotificationResult,
    NotificationStatus,
)
from app.notifications.dispatcher import (
    NotificationDispatcher,
    DispatcherConfig,
    ChannelTier,
    FallbackPolicy,
    CooldownTracker,
    PersistentNotificationQueue,
    QueuedNotification,
    create_dispatcher_from_settings,
)
from app.notifications.zns_provider import ZaloZNSProvider, ZaloTokenInfo, ZaloZNSError
from app.notifications.sms_provider import ESMSProvider, SpeedSMSProvider, MockSMSProvider
from app.notifications.telegram_provider import TelegramProvider
from app.attendance.policy_engine.contract import PolicyEvent, PolicyType
from app.attendance.policy_engine.parent_registry import Parent, ParentRegistry


# Test fixtures
@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def sample_payload():
    """Create a sample notification payload."""
    return NotificationPayload(
        event_id="TEST-EVENT-001",
        event_type="morning_absence",
        student_id="SV001",
        student_name="Nguyễn Văn An",
        recipient_id="PAR001",
        recipient_name="Nguyễn Thị Bình",
        recipient_phone="+84901234567",
        recipient_telegram_chat_id="123456789",
        message="Test notification message",
        occurred_at=datetime.utcnow().timestamp(),
        evidence={"camera_name": "Main Gate"},
    )


@pytest.fixture
def sample_policy_event():
    """Create a sample policy event."""
    return PolicyEvent(
        event_id="PEV-test123",
        student_id="SV001",
        policy_type=PolicyType.MORNING_ABSENCE,
        occurred_at=datetime.utcnow().timestamp(),
        effective_at=datetime.utcnow().timestamp(),
        source_attendance_event_id="ATT-test456",
        evidence={"student_name": "Nguyễn Văn An", "camera_name": "Main Gate"},
    )


# ============================================================================
# Base Provider Tests
# ============================================================================

class TestNotificationPayload:
    """Test NotificationPayload creation and idempotency keys."""
    
    def test_idempotency_key_morning_absence(self):
        payload = NotificationPayload(
            event_id="TEST-001",
            event_type="morning_absence",
            student_id="SV001",
            student_name="Test",
            recipient_id="PAR001",
            recipient_name="Parent",
            recipient_phone="+84901234567",
            message="Test",
            occurred_at=1702281600,  # 2023-12-11 08:00:00 UTC
        )
        assert payload.idempotency_key == "2023-12-11:SV001:morning_absence"
    
    def test_idempotency_key_long_exit_with_out_time(self):
        payload = NotificationPayload(
            event_id="TEST-002",
            event_type="long_exit",
            student_id="SV001",
            student_name="Test",
            recipient_id="PAR001",
            recipient_name="Parent",
            recipient_phone="+84901234567",
            message="Test",
            occurred_at=1702281600,
            evidence={"out_time": "14:30"},
        )
        assert payload.idempotency_key == "2023-12-11:SV001:long_exit:14:30"
    
    def test_idempotency_key_missing_checkout(self):
        payload = NotificationPayload(
            event_id="TEST-003",
            event_type="missing_checkout",
            student_id="SV001",
            student_name="Test",
            recipient_id="PAR001",
            recipient_name="Parent",
            recipient_phone="+84901234567",
            message="Test",
            occurred_at=1702281600,
        )
        assert payload.idempotency_key == "2023-12-11:SV001:missing_checkout"


class TestNotificationResult:
    """Test NotificationResult properties."""
    
    def test_is_success(self):
        payload = NotificationPayload(
            event_id="TEST", event_type="test", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        result = NotificationResult(
            payload=payload, status=NotificationStatus.SENT,
            channel=NotificationChannel.SMS, provider_name="test"
        )
        assert result.is_success is True
        
        result_failed = NotificationResult(
            payload=payload, status=NotificationStatus.FAILED,
            channel=NotificationChannel.SMS, provider_name="test"
        )
        assert result_failed.is_success is False
    
    def test_is_retryable(self):
        payload = NotificationPayload(
            event_id="TEST", event_type="test", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        # Failed with attempts < max -> retryable
        result = NotificationResult(
            payload=payload, status=NotificationStatus.FAILED,
            channel=NotificationChannel.SMS, provider_name="test",
            attempt=1, max_attempts=3
        )
        assert result.is_retryable is True
        
        # Failed with attempts >= max -> not retryable
        result_max = NotificationResult(
            payload=payload, status=NotificationStatus.FAILED,
            channel=NotificationChannel.SMS, provider_name="test",
            attempt=3, max_attempts=3
        )
        assert result_max.is_retryable is False
        
        # Rate limited -> retryable
        result_rl = NotificationResult(
            payload=payload, status=NotificationStatus.RATE_LIMITED,
            channel=NotificationChannel.SMS, provider_name="test",
            attempt=1, max_attempts=3
        )
        assert result_rl.is_retryable is True
    
    def test_is_terminal_failure(self):
        payload = NotificationPayload(
            event_id="TEST", event_type="test", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        result = NotificationResult(
            payload=payload, status=NotificationStatus.FAILED,
            channel=NotificationChannel.SMS, provider_name="test",
            attempt=3, max_attempts=3
        )
        assert result.is_terminal_failure is True


# ============================================================================
# Cooldown Tracker Tests
# ============================================================================

class TestCooldownTracker:
    """Test cooldown tracking functionality."""
    
    def test_cooldown_not_in_cooldown_initially(self, temp_db):
        tracker = CooldownTracker(temp_db)
        assert tracker.is_in_cooldown("SV001", "morning_absence", 300) is False
        assert tracker.get_remaining_cooldown("SV001", "morning_absence", 300) is None
    
    def test_cooldown_after_record(self, temp_db):
        tracker = CooldownTracker(temp_db)
        tracker.record_send("SV001", "morning_absence")
        
        assert tracker.is_in_cooldown("SV001", "morning_absence", 300) is True
        remaining = tracker.get_remaining_cooldown("SV001", "morning_absence", 300)
        assert remaining is not None
        assert 295 <= remaining <= 300  # ~5 minutes
    
    def test_cooldown_expired(self, temp_db):
        tracker = CooldownTracker(temp_db)
        tracker.record_send("SV001", "morning_absence")
        
        # Manually update timestamp to past
        import sqlite3
        with sqlite3.connect(temp_db) as conn:
            past = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "Z"
            conn.execute(
                "UPDATE cooldowns SET last_sent_at = ? WHERE student_id = ? AND event_type = ?",
                (past, "SV001", "morning_absence")
            )
            conn.commit()
        
        assert tracker.is_in_cooldown("SV001", "morning_absence", 300) is False
    
    def test_different_student_no_cooldown(self, temp_db):
        tracker = CooldownTracker(temp_db)
        tracker.record_send("SV001", "morning_absence")
        
        # Different student should not be in cooldown
        assert tracker.is_in_cooldown("SV002", "morning_absence", 300) is False
    
    def test_different_event_type_no_cooldown(self, temp_db):
        tracker = CooldownTracker(temp_db)
        tracker.record_send("SV001", "morning_absence")
        
        # Different event type should not be in cooldown
        assert tracker.is_in_cooldown("SV001", "long_exit", 300) is False


# ============================================================================
# Persistent Queue Tests
# ============================================================================

class TestPersistentNotificationQueue:
    """Test persistent notification queue operations."""
    
    def test_enqueue_and_get_pending(self, temp_db):
        queue = PersistentNotificationQueue(temp_db)
        
        payload = NotificationPayload(
            event_id="TEST-001", event_type="morning_absence",
            student_id="SV001", student_name="Test",
            recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        queued = queue.enqueue(payload)
        assert queued is not None
        assert queued.idempotency_key == payload.idempotency_key
        assert queued.status == NotificationStatus.PENDING
    
    def test_duplicate_enqueue_returns_none(self, temp_db):
        queue = PersistentNotificationQueue(temp_db)
        
        payload = NotificationPayload(
            event_id="TEST-001", event_type="morning_absence",
            student_id="SV001", student_name="Test",
            recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        queue.enqueue(payload)
        duplicate = queue.enqueue(payload)
        assert duplicate is None
    
    def test_get_pending_returns_queued(self, temp_db):
        queue = PersistentNotificationQueue(temp_db)
        
        payload = NotificationPayload(
            event_id="TEST-001", event_type="morning_absence",
            student_id="SV001", student_name="Test",
            recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        queue.enqueue(payload)
        pending = queue.get_pending(10)
        
        assert len(pending) == 1
        assert pending[0].idempotency_key == payload.idempotency_key
    
    def test_update_status(self, temp_db):
        queue = PersistentNotificationQueue(temp_db)
        
        payload = NotificationPayload(
            event_id="TEST-001", event_type="morning_absence",
            student_id="SV001", student_name="Test",
            recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        queued = queue.enqueue(payload)
        assert queue.update_status(queued.id, NotificationStatus.SENT)
        
        # Verify by getting again
        pending = queue.get_pending(10)
        assert len(pending) == 0  # No longer pending
    
    def test_queue_stats(self, temp_db):
        queue = PersistentNotificationQueue(temp_db)
        
        payload = NotificationPayload(
            event_id="TEST-001", event_type="morning_absence",
            student_id="SV001", student_name="Test",
            recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        queue.enqueue(payload)
        stats = queue.get_stats()
        
        assert stats.get("pending", 0) == 1


# ============================================================================
# Mock Provider Tests
# ============================================================================

class TestMockSMSProvider:
    """Test Mock SMS provider for testing."""
    
    @pytest.mark.asyncio
    async def test_mock_sms_success(self):
        provider = MockSMSProvider(success_rate=1.0)
        
        payload = NotificationPayload(
            event_id="TEST", event_type="test", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        result = await provider.send_notification(payload)
        assert result.is_success is True
        assert result.provider_name == "mock_sms"
    
    @pytest.mark.asyncio
    async def test_mock_sms_failure(self):
        provider = MockSMSProvider(success_rate=0.0)
        
        payload = NotificationPayload(
            event_id="TEST", event_type="test", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
        )
        
        result = await provider.send_notification(payload)
        assert result.is_success is False
        assert result.status == NotificationStatus.FAILED
    
    @pytest.mark.asyncio
    async def test_mock_health_check(self):
        provider = MockSMSProvider()
        health = await provider.health_check()
        assert health["healthy"] is True
        assert health["provider"] == "mock_sms"


# ============================================================================
# Zalo ZNS Provider Tests (Mocked)
# ============================================================================

class TestZaloZNSProvider:
    """Test Zalo ZNS provider with mocked HTTP calls."""
    
    @pytest.fixture
    def zns_provider(self):
        return ZaloZNSProvider(
            app_id="test_app_id",
            secret_key="test_secret_key",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
        )
    
    def test_normalize_phone_for_zns(self, zns_provider):
        # Test various formats
        assert zns_provider._normalize_phone_for_zns("0901234567") == "84901234567"
        assert zns_provider._normalize_phone_for_zns("+84901234567") == "84901234567"
        assert zns_provider._normalize_phone_for_zns("84901234567") == "84901234567"
        assert zns_provider._normalize_phone_for_zns("090 123 4567") == "84901234567"
    
    def test_generate_signature(self, zns_provider):
        sig = zns_provider._generate_signature("test_data")
        assert len(sig) == 64  # SHA256 hex
        # Verify deterministic
        assert sig == zns_provider._generate_signature("test_data")
    
    def test_build_zns_payload(self, zns_provider):
        payload = NotificationPayload(
            event_id="TEST", event_type="morning_absence", student_id="SV001",
            student_name="Nguyễn Văn An", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="0901234567", message="Test", occurred_at=1702281600,
            evidence={"camera_name": "Main Gate"}
        )
        
        zns_payload = zns_provider._build_zns_payload(payload, "test_template")
        
        assert zns_payload["phone"] == "84901234567"
        assert zns_payload["template_id"] == "test_template"
        assert "student_name" in zns_payload["template_data"]
        assert zns_payload["template_data"]["student_name"] == "Nguyễn Văn An"
        assert "timestamp" in zns_payload["template_data"]
    
    @pytest.mark.asyncio
    async def test_send_notification_no_template(self, zns_provider):
        # Mock token validation to succeed
        zns_provider._token_info = ZaloTokenInfo(
            access_token="valid_token", refresh_token="rt", expires_at=time.time() + 3600
        )
        
        payload = NotificationPayload(
            event_id="TEST", event_type="unknown_event", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="0901234567", message="Test"
        )
        
        result = await zns_provider.send_notification(payload)
        assert result.status == NotificationStatus.FAILED
        assert "No template configured" in result.error_message


# ============================================================================
# SMS Provider Tests
# ============================================================================

class TestESMSProvider:
    """Test eSMS provider phone normalization."""
    
    @pytest.fixture
    def esms_provider(self):
        return ESMSProvider(
            api_key="test_key", secret_key="test_secret",
            brandname="TEST", sandbox=True
        )
    
    def test_normalize_phone_for_esms(self, esms_provider):
        assert esms_provider._normalize_phone_for_esms("0901234567") == "84901234567"
        assert esms_provider._normalize_phone_for_esms("+84901234567") == "84901234567"
        assert esms_provider._normalize_phone_for_esms("84901234567") == "84901234567"
    
    def test_build_sms_content(self, esms_provider):
        payload = NotificationPayload(
            event_id="TEST", event_type="morning_absence", student_id="SV001",
            student_name="Nguyễn Văn An", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test", occurred_at=1702281600,
            evidence={"camera_name": "Main Gate"}
        )
        
        content = esms_provider._build_sms_content(payload)
        assert "[TEST]" in content
        assert "VANG MAT" in content
        assert "Nguyễn Văn An" in content
        assert "Main Gate" in content


class TestSpeedSMSProvider:
    """Test SpeedSMS provider phone normalization."""
    
    @pytest.fixture
    def speedsms_provider(self):
        return SpeedSMSProvider(
            api_token="test_token", brandname="TEST", sandbox=True
        )
    
    def test_normalize_phone_for_speedsms(self, speedsms_provider):
        assert speedsms_provider._normalize_phone_for_speedsms("0901234567") == "84901234567"
        assert speedsms_provider._normalize_phone_for_speedsms("+84901234567") == "84901234567"


# ============================================================================
# Telegram Provider Tests
# ============================================================================

class TestTelegramProvider:
    """Test Telegram provider wrapper."""
    
    @pytest.fixture
    def telegram_provider(self):
        return TelegramProvider(bot_token="123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
    
    @pytest.mark.asyncio
    async def test_send_notification_no_chat_id(self, telegram_provider):
        payload = NotificationPayload(
            event_id="TEST", event_type="test", student_id="SV001",
            student_name="Test", recipient_id="PAR001", recipient_name="Parent",
            recipient_phone="+84901234567", message="Test"
            # No telegram_chat_id
        )
        
        result = await telegram_provider.send_notification(payload)
        assert result.status == NotificationStatus.NO_RECIPIENT
        assert "No Telegram chat_id" in result.error_message


# ============================================================================
# Dispatcher Tests
# ============================================================================

class TestNotificationDispatcher:
    """Test the main notification dispatcher."""
    
    @pytest.fixture
    def mock_providers(self):
        """Create mock providers for testing."""
        providers = {
            "zalo_zns_official": MockSMSProvider(name="zalo_zns_official", success_rate=0.0),  # Always fail for fallback test
            "esms_vn": MockSMSProvider(name="esms_vn", success_rate=1.0),
            "speedsms_vn": MockSMSProvider(name="speedsms_vn", success_rate=1.0),
            "telegram_bot": MockSMSProvider(name="telegram_bot", success_rate=1.0),
        }
        # Fix channel for mocks
        for p in providers.values():
            p.channel = NotificationChannel.ZALO_ZNS if "zalo" in p.name else \
                       NotificationChannel.SMS if "sms" in p.name or "esms" in p.name or "speed" in p.name else \
                       NotificationChannel.TELEGRAM
        return providers
    
    @pytest.fixture
    def mock_parent_registry(self):
        """Create a mock parent registry."""
        registry = MagicMock(spec=ParentRegistry)
        parent = Parent(
            parent_id="PAR001",
            parent_name="Test Parent",
            telegram_chat_id="123456789",
            telegram_enabled=True,
        )
        # Add phone attribute using object.__setattr__ since Parent is frozen
        object.__setattr__(parent, "phone", "+84901234567")
        object.__setattr__(parent, "is_active", True)
        registry.get_notification_recipients.return_value = [parent]
        return registry
    
    @pytest.fixture
    def dispatcher_config(self, temp_db):
        return DispatcherConfig(
            queue_db_path=temp_db.replace(".db", "_queue.db"),
            cooldown_db_path=temp_db.replace(".db", "_cooldown.db"),
            tiers=[
                ChannelTier(
                    channel=NotificationChannel.ZALO_ZNS,
                    providers=["zalo_zns_official"],
                    fallback_policy=FallbackPolicy.IMMEDIATE,
                    cooldown_seconds=60,
                ),
                ChannelTier(
                    channel=NotificationChannel.SMS,
                    providers=["esms_vn"],
                    fallback_policy=FallbackPolicy.IMMEDIATE,
                    cooldown_seconds=60,
                ),
                ChannelTier(
                    channel=NotificationChannel.TELEGRAM,
                    providers=["telegram_bot"],
                    fallback_policy=FallbackPolicy.NO_FALLBACK,
                    cooldown_seconds=60,
                ),
            ],
            poll_interval=0.1,  # Fast polling for tests
        )
    
    @pytest.mark.asyncio
    async def test_dispatcher_enqueue_and_process(self, dispatcher_config, mock_providers, mock_parent_registry, temp_db):
        cooldown_tracker = CooldownTracker(dispatcher_config.cooldown_db_path)
        queue = PersistentNotificationQueue(dispatcher_config.queue_db_path)
        
        dispatcher = NotificationDispatcher(
            config=dispatcher_config,
            providers=mock_providers,
            parent_registry=mock_parent_registry,
            cooldown_tracker=cooldown_tracker,
            queue=queue,
        )
        
        await dispatcher.start()
        
        # Create policy event
        event = PolicyEvent(
            event_id="PEV-test123",
            student_id="SV001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=datetime.utcnow().timestamp(),
            effective_at=datetime.utcnow().timestamp(),
            source_attendance_event_id="ATT-test456",
            evidence={"student_name": "Nguyễn Văn An", "camera_name": "Main Gate"},
        )
        
        # Dispatch event
        ids = dispatcher.dispatch_event(event)
        assert len(ids) == 1
        
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Check stats
        stats = dispatcher.get_stats()
        assert stats["enqueued"] == 1
        assert stats["sent"] == 1
        
        await dispatcher.stop()
    
    @pytest.mark.asyncio
    async def test_dispatcher_fallback_on_failure(self, dispatcher_config, mock_providers, mock_parent_registry, temp_db):
        # Make first provider fail
        mock_providers["zalo_zns_official"].success_rate = 0.0
        
        cooldown_tracker = CooldownTracker(dispatcher_config.cooldown_db_path)
        queue = PersistentNotificationQueue(dispatcher_config.queue_db_path)
        
        dispatcher = NotificationDispatcher(
            config=dispatcher_config,
            providers=mock_providers,
            parent_registry=mock_parent_registry,
            cooldown_tracker=cooldown_tracker,
            queue=queue,
        )
        
        await dispatcher.start()
        
        event = PolicyEvent(
            event_id="PEV-test456",
            student_id="SV002",
            policy_type=PolicyType.LONG_EXIT,
            occurred_at=datetime.utcnow().timestamp(),
            effective_at=datetime.utcnow().timestamp(),
            source_attendance_event_id="ATT-test789",
            evidence={"student_name": "Test Student", "out_time": "14:30"},
        )
        
        ids = dispatcher.dispatch_event(event)
        assert len(ids) == 1
        
        # Wait for processing with fallback
        await asyncio.sleep(1.0)
        
        stats = dispatcher.get_stats()
        # Should have fallen back to SMS
        assert stats["fallback_count"] >= 1
        
        await dispatcher.stop()
    
    @pytest.mark.asyncio
    async def test_dispatcher_cooldown_prevents_spam(self, dispatcher_config, mock_providers, mock_parent_registry, temp_db):
        cooldown_tracker = CooldownTracker(dispatcher_config.cooldown_db_path)
        queue = PersistentNotificationQueue(dispatcher_config.queue_db_path)
        
        dispatcher = NotificationDispatcher(
            config=dispatcher_config,
            providers=mock_providers,
            parent_registry=mock_parent_registry,
            cooldown_tracker=cooldown_tracker,
            queue=queue,
        )
        
        await dispatcher.start()
        
        event = PolicyEvent(
            event_id="PEV-test789",
            student_id="SV003",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=datetime.utcnow().timestamp(),
            effective_at=datetime.utcnow().timestamp(),
            source_attendance_event_id="ATT-test000",
            evidence={"student_name": "Test Student"},
        )
        
        # First event - should enqueue
        ids1 = dispatcher.dispatch_event(event)
        assert len(ids1) == 1
        
        # Wait for processing so cooldown is recorded
        await asyncio.sleep(0.5)
        
        # Second event same student/type - should be skipped due to cooldown
        event2 = PolicyEvent(
            event_id="PEV-test790",
            student_id="SV003",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=datetime.utcnow().timestamp() + 10,
            effective_at=datetime.utcnow().timestamp() + 10,
            source_attendance_event_id="ATT-test001",
            evidence={"student_name": "Test Student"},
        )
        
        ids2 = dispatcher.dispatch_event(event2)
        assert len(ids2) == 0  # Skipped due to cooldown
        
        stats = dispatcher.get_stats()
        assert stats["skipped_cooldown"] == 1
        
        await dispatcher.stop()


# ============================================================================
# Phone Normalization Tests
# ============================================================================

class TestPhoneNormalization:
    """Test phone number normalization across providers."""
    
    @pytest.mark.parametrize("input_phone,expected", [
        ("0901234567", "84901234567"),
        ("+84901234567", "84901234567"),
        ("84901234567", "84901234567"),
        ("090 123 4567", "84901234567"),
        ("090-123-4567", "84901234567"),
        ("(090) 123-4567", "84901234567"),
    ])
    def test_esms_normalization(self, input_phone, expected):
        provider = ESMSProvider("key", "secret", sandbox=True)
        assert provider._normalize_phone_for_esms(input_phone) == expected
    
    @pytest.mark.parametrize("input_phone,expected", [
        ("0901234567", "84901234567"),
        ("+84901234567", "84901234567"),
        ("84901234567", "84901234567"),
    ])
    def test_speedsms_normalization(self, input_phone, expected):
        provider = SpeedSMSProvider("token", sandbox=True)
        assert provider._normalize_phone_for_speedsms(input_phone) == expected
    
    @pytest.mark.parametrize("input_phone,expected", [
        ("0901234567", "84901234567"),
        ("+84901234567", "84901234567"),
        ("84901234567", "84901234567"),
    ])
    def test_zns_normalization(self, input_phone, expected):
        provider = ZaloZNSProvider("app_id", "secret")
        assert provider._normalize_phone_for_zns(input_phone) == expected


# ============================================================================
# Integration Tests
# ============================================================================

class TestDispatcherIntegration:
    """Integration tests for the complete notification flow."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_mock_flow(self, temp_db):
        """Test complete flow from event to delivery with all mocks."""
        
        # Setup
        config = DispatcherConfig(
            queue_db_path=temp_db.replace(".db", "_queue.db"),
            cooldown_db_path=temp_db.replace(".db", "_cooldown.db"),
            tiers=[
                ChannelTier(
                    channel=NotificationChannel.SMS,
                    providers=["mock_sms_1", "mock_sms_2"],
                    fallback_policy=FallbackPolicy.IMMEDIATE,
                ),
            ],
        )
        
        providers = {
            "mock_sms_1": MockSMSProvider(name="mock_sms_1", success_rate=1.0),
            "mock_sms_2": MockSMSProvider(name="mock_sms_2", success_rate=1.0),
        }
        for p in providers.values():
            p.channel = NotificationChannel.SMS
        
        mock_registry = MagicMock()
        parent = Parent(
            parent_id="PAR001",
            parent_name="Parent",
            telegram_chat_id="123456789",
            telegram_enabled=True,
        )
        object.__setattr__(parent, "phone", "+84901234567")
        object.__setattr__(parent, "is_active", True)
        mock_registry.get_notification_recipients.return_value = [parent]
        
        cooldown_tracker = CooldownTracker(config.cooldown_db_path)
        queue = PersistentNotificationQueue(config.queue_db_path)
        
        dispatcher = NotificationDispatcher(
            config=config, providers=providers, parent_registry=mock_registry,
            cooldown_tracker=cooldown_tracker, queue=queue
        )
        
        await dispatcher.start()
        
        # Create event
        event = PolicyEvent(
            event_id="PEV-integration-001",
            student_id="SV001",
            policy_type=PolicyType.MORNING_ABSENCE,
            occurred_at=datetime.utcnow().timestamp(),
            effective_at=datetime.utcnow().timestamp(),
            source_attendance_event_id="ATT-001",
            evidence={"student_name": "Integration Test Student"},
        )
        
        # Dispatch
        ids = dispatcher.dispatch_event(event)
        assert len(ids) == 1
        
        # Process
        await asyncio.sleep(0.5)
        
        stats = dispatcher.get_stats()
        assert stats["enqueued"] == 1
        assert stats["sent"] == 1
        assert stats["failed"] == 0
        
        await dispatcher.stop()


# ============================================================================
# Run tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])