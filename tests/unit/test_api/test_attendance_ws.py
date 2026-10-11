"""
Phase 6 — Unit Tests for Attendance WebSocket and Event Delivery.

Tests for WebSocket connection, authentication, event delivery, and retry logic.
"""

import pytest
import asyncio
import json
import time
from datetime import datetime
from fractions import Fraction
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

from app.api.attendance_ws import (
    AttendanceConnectionManager,
    AttendanceConnectionState,
    EventDeliveryClient,
    verify_attendance_ws_key,
)
from app.attendance.contract import (
    AttendanceRecord,
    AttendanceDirection,
    IdentityCertainty,
)


def create_mock_request(client_host: str = "127.0.0.1", forwarded_for: str = None) -> Request:
    """Create a mock Request object for testing."""
    mock_request = MagicMock(spec=Request)
    mock_request.client = MagicMock()
    mock_request.client.host = client_host
    if forwarded_for:
        mock_request.headers = {"X-Forwarded-For": forwarded_for}
    else:
        mock_request.headers = {}
    return mock_request


class TestAttendanceConnectionState:
    """Tests for AttendanceConnectionState."""
    
    def test_initial_state(self):
        """Test initial connection state."""
        mock_ws = MagicMock()
        state = AttendanceConnectionState("test-123", mock_ws, "api-key-123")
        
        assert state.connection_id == "test-123"
        assert state.websocket == mock_ws
        assert state.api_key == "api-key-123"
        assert state.connected_at > 0
        assert state.last_ping_at is None
        assert state.last_pong_at is None
        assert state.last_event_seq == 0
        assert state.is_healthy is True
        assert state.subscriptions == {"attendance.created"}
    
    def test_update_ping_pong(self):
        """Test ping/pong timestamp updates."""
        mock_ws = MagicMock()
        state = AttendanceConnectionState("test-123", mock_ws, "api-key-123")
        
        before_ping = time.time()
        state.update_ping()
        assert state.last_ping_at is not None
        assert state.last_ping_at >= before_ping
        
        before_pong = time.time()
        state.update_pong()
        assert state.last_pong_at is not None
        assert state.last_pong_at >= before_pong
    
    def test_get_latency_ms(self):
        """Test latency calculation."""
        mock_ws = MagicMock()
        state = AttendanceConnectionState("test-123", mock_ws, "api-key-123")
        
        # No latency if no ping/pong
        assert state.get_latency_ms() is None
        
        # With ping and pong
        state.update_ping()
        time.sleep(0.001)  # Small delay
        state.update_pong()
        latency = state.get_latency_ms()
        assert latency is not None
        assert latency >= 1.0  # At least 1ms
    
    def test_is_stale(self):
        """Test stale connection detection."""
        mock_ws = MagicMock()
        state = AttendanceConnectionState("test-123", mock_ws, "api-key-123")
        
        # Fresh connection should not be stale
        assert not state.is_stale(30.0)
        
        # Old connection without pong should be stale
        state.connected_at = time.time() - 40
        assert state.is_stale(30.0)
        
        # Recent pong should not be stale
        state.last_pong_at = time.time() - 5
        assert not state.is_stale(30.0)
        
        # Old pong should be stale
        state.last_pong_at = time.time() - 40
        assert state.is_stale(30.0)


class TestAttendanceConnectionManager:
    """Tests for AttendanceConnectionManager."""
    
    @pytest.fixture
    def manager(self):
        """Create a fresh manager for each test."""
        return AttendanceConnectionManager()
    
    @pytest.mark.asyncio
    async def test_connect_disconnect(self, manager):
        """Test connection and disconnection."""
        mock_ws = AsyncMock()
        
        conn_id = await manager.connect(mock_ws, "test-key")
        
        assert conn_id in manager.active_connections
        assert len(manager.active_connections) == 1
        
        state = manager.active_connections[conn_id]
        assert state.connection_id == conn_id
        assert state.api_key == "test-key"
        
        manager.disconnect(conn_id)
        
        assert conn_id not in manager.active_connections
        assert len(manager.active_connections) == 0
    
    @pytest.mark.asyncio
    async def test_broadcast(self, manager):
        """Test broadcasting messages."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        
        conn_id1 = await manager.connect(mock_ws1, "key1")
        conn_id2 = await manager.connect(mock_ws2, "key2")
        
        message = {"type": "test", "data": "hello"}
        await manager.broadcast(message)
        
        # Both connections should receive the message
        mock_ws1.send_text.assert_called()
        mock_ws2.send_text.assert_called()
        
        # Check message content
        call_args1 = mock_ws1.send_text.call_args[0][0]
        sent_msg = json.loads(call_args1)
        assert sent_msg["type"] == "test"
        assert sent_msg["data"] == "hello"
        assert "seq" in sent_msg
        assert "timestamp" in sent_msg
    
    @pytest.mark.asyncio
    async def test_broadcast_with_subscription_filter(self, manager):
        """Test broadcasting with subscription filter."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        
        conn_id1 = await manager.connect(mock_ws1, "key1")
        conn_id2 = await manager.connect(mock_ws2, "key2")
        
        # Reset mock to clear welcome message calls
        mock_ws1.reset_mock()
        mock_ws2.reset_mock()
        
        # Subscribe conn2 to different event type
        manager.active_connections[conn_id2].subscriptions = {"other.event"}
        
        message = {"type": "test", "data": "hello"}
        await manager.broadcast(message, subscription_filter="attendance.created")
        
        # Only conn1 should receive (has attendance.created subscription)
        mock_ws1.send_text.assert_called()
        mock_ws2.send_text.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_broadcast_cleans_disconnected(self, manager):
        """Test that broadcast cleans up failed connections."""
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        
        conn_id1 = await manager.connect(mock_ws1, "key1")
        conn_id2 = await manager.connect(mock_ws2, "key2")
        
        # Make ws2 fail
        mock_ws2.send_text.side_effect = Exception("Connection lost")
        
        message = {"type": "test"}
        await manager.broadcast(message)
        
        # conn2 should be disconnected
        assert conn_id2 not in manager.active_connections
        assert conn_id1 in manager.active_connections
    
    def test_get_connection_stats(self, manager):
        """Test connection statistics."""
        stats = manager.get_connection_stats()
        
        assert stats["total_connections"] == 0
        assert stats["connections"] == []


class TestEventDeliveryClient:
    """Tests for EventDeliveryClient."""
    
    @pytest.fixture
    def manager(self):
        return AttendanceConnectionManager()
    
    @pytest.fixture
    def client(self, manager):
        return EventDeliveryClient(manager)
    
    @pytest.fixture
    def sample_record(self):
        """Create a sample AttendanceRecord."""
        return AttendanceRecord(
            attendance_record_id="ATT-test123",
            identity_certainty=IdentityCertainty.KNOWN,
            identity_candidate="student_001",
            identity_confidence=0.95,
            identity_evidence_ref="GO-456",
            face_evidence_ref="FE-001",
            body_evidence_ref="BE-001",
            face_quality=0.9,
            body_quality=0.85,
            association_method="fused",  # Valid value: fused, face_only, body_only, geometric
            conflict_flag=False,
            provisional_person_id=None,
            identity_state="confirmed",
            direction=AttendanceDirection.IN,
            event_timestamp=1787446800.0,
            event_frame_index=100,
            camera_id="CAM1",
            local_track_id="track_001",
            global_observation_id="GO-456",
            source_raw_event_id="RIE-abc",
            source_resolution_id="RES-xyz",
            source_crossing_event_id="CE-001",
            geometry_version=1,
            geometry_config_hash="geom_hash",
            resolver_version="1.0",
            resolver_config_hash="config_hash",
            previous_state="unknown",
            new_state="inside",
            stream_epoch=0,
            pts=0,
            time_base=Fraction(1, 90000),
            capture_timestamp=1787446800.0,
            processing_timestamp=1787446800.1,
            model_version="v1.0",
            enrollment_version="v1.0",
            attendance_schema_version="1.1",
            created_at="2026-01-01T00:00:00Z",
            persisted_at="2026-01-01T00:00:00Z",
        )
    
    @pytest.mark.asyncio
    async def test_push_attendance_event(self, client, sample_record):
        """Test pushing attendance event."""
        # Add a mock connection
        mock_ws = AsyncMock()
        conn_id = await client.manager.connect(mock_ws, "test-key")
        
        result = await client.push_attendance_event(sample_record)
        
        assert result is True
        mock_ws.send_text.assert_called()
        
        # Check message structure
        call_args = mock_ws.send_text.call_args[0][0]
        msg = json.loads(call_args)
        assert msg["type"] == "attendance.created"
        assert msg["event"]["attendance_record_id"] == "ATT-test123"
        assert msg["event"]["person_id"] == "student_001"
        assert msg["event"]["camera_id"] == "CAM1"
        assert msg["event"]["direction"] == "in"
        assert "seq" in msg
    
    @pytest.mark.asyncio
    async def test_idempotency(self, client, sample_record):
        """Test that duplicate events are suppressed."""
        mock_ws = AsyncMock()
        await client.manager.connect(mock_ws, "test-key")
        
        # Reset mock to clear welcome message call
        mock_ws.reset_mock()
        
        # First push
        result1 = await client.push_attendance_event(sample_record)
        assert result1 is True
        assert mock_ws.send_text.call_count == 1
        
        # Second push with same record ID
        result2 = await client.push_attendance_event(sample_record)
        assert result2 is True  # Returns True but doesn't send
        assert mock_ws.send_text.call_count == 1  # Still only 1 call
    
    @pytest.mark.asyncio
    async def test_build_event_message(self, client, sample_record):
        """Test event message building."""
        message = client._build_event_message(sample_record)
        
        assert message["type"] == "attendance.created"
        assert "event" in message
        assert message["event"]["attendance_record_id"] == "ATT-test123"
        assert message["event"]["face_evidence_ref"] == "FE-001"
        assert message["event"]["body_evidence_ref"] == "BE-001"
        assert message["event"]["identity_state"] == "confirmed"
    
    @pytest.mark.asyncio
    async def test_retry_queue(self, client, sample_record):
        """Test retry queue functionality."""
        # Start client to activate retry processor
        await client.start()
        
        # Queue for retry
        await client._queue_for_retry(sample_record)
        
        # Stop client
        await client.stop()


class TestVerifyAttendanceWsKey:
    """Tests for WebSocket API key verification."""
    
    @pytest.mark.asyncio
    async def test_valid_admin_key(self):
        """Test valid admin API key."""
        import os
        os.environ["ADMIN_API_KEY"] = "admin-secret-123"
        
        try:
            # Need to invalidate cache first
            from app.security.api_key_cache import get_api_key_cache
            get_api_key_cache().invalidate_all()
            
            mock_request = create_mock_request()
            result = await verify_attendance_ws_key(mock_request, "admin-secret-123")
            assert result is True
        finally:
            del os.environ["ADMIN_API_KEY"]
    
    @pytest.mark.asyncio
    async def test_valid_worker_key(self):
        """Test valid worker API key."""
        import os
        os.environ["AI_WORKER_API_KEY"] = "worker-secret-456"
        
        try:
            from app.security.api_key_cache import get_api_key_cache
            get_api_key_cache().invalidate_all()
            
            mock_request = create_mock_request()
            result = await verify_attendance_ws_key(mock_request, "worker-secret-456")
            assert result is True
        finally:
            del os.environ["AI_WORKER_API_KEY"]
    
    @pytest.mark.asyncio
    async def test_invalid_key(self):
        """Test invalid API key."""
        import os
        os.environ["ADMIN_API_KEY"] = "admin-secret"
        os.environ["AI_WORKER_API_KEY"] = "worker-secret"
        
        try:
            from app.security.api_key_cache import get_api_key_cache
            get_api_key_cache().invalidate_all()
            
            mock_request = create_mock_request()
            with pytest.raises(HTTPException) as exc_info:
                await verify_attendance_ws_key(mock_request, "invalid-key")
            
            assert exc_info.value.status_code == 401
        finally:
            del os.environ["ADMIN_API_KEY"]
            del os.environ["AI_WORKER_API_KEY"]
    
    @pytest.mark.asyncio
    async def test_no_keys_configured(self):
        """Test when no keys are configured."""
        import os
        # Remove any existing keys
        for key in ["ADMIN_API_KEY", "AI_WORKER_API_KEY"]:
            if key in os.environ:
                del os.environ[key]
        
        from app.security.api_key_cache import get_api_key_cache
        get_api_key_cache().invalidate_all()
        
        mock_request = create_mock_request()
        with pytest.raises(HTTPException) as exc_info:
            await verify_attendance_ws_key(mock_request, "any-key")
        
        assert exc_info.value.status_code == 503


if __name__ == "__main__":
    pytest.main([__file__, "-v"])