"""
Phase 37B — Unit Tests for Parent Registry.
"""

from __future__ import annotations

import pytest
import tempfile
import os
import uuid
from datetime import datetime, timedelta

from app.attendance.policy_engine.parent_registry import (
    ParentRegistry,
    Parent,
    StudentParentLink,
    LinkCode,
    LinkCodeStatus,
    NotificationPreference,
    create_parent_registry,
)


class TestParentRegistry:
    """Tests for ParentRegistry."""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file path (not an open file)."""
        # Use a unique path in temp directory without keeping file handle open
        db_path = os.path.join(tempfile.gettempdir(), f"test_parent_registry_{uuid.uuid4().hex}.db")
        yield db_path
        # Cleanup
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except PermissionError:
                # On Windows, the file might still be locked briefly
                pass
    
    @pytest.fixture
    def registry(self, temp_db):
        """Create a parent registry with temp database."""
        return ParentRegistry(temp_db)
    
    def test_create_parent(self, registry):
        parent = registry.create_parent(
            parent_name="John Doe",
            telegram_chat_id="123456789",
            telegram_enabled=True,
            notification_preferences=NotificationPreference.ALL,
        )
        
        assert parent.parent_id.startswith("PAR-")
        assert parent.parent_name == "John Doe"
        assert parent.telegram_chat_id == "123456789"
        assert parent.telegram_enabled is True
        assert parent.notification_preferences == NotificationPreference.ALL
    
    def test_get_parent(self, registry):
        parent = registry.create_parent("Jane Smith")
        retrieved = registry.get_parent(parent.parent_id)
        
        assert retrieved is not None
        assert retrieved.parent_id == parent.parent_id
        assert retrieved.parent_name == "Jane Smith"
    
    def test_get_parent_not_found(self, registry):
        retrieved = registry.get_parent("PAR-nonexistent")
        assert retrieved is None
    
    def test_get_parent_by_chat_id(self, registry):
        parent = registry.create_parent("Bob Wilson", telegram_chat_id="987654321")
        retrieved = registry.get_parent_by_chat_id("987654321")
        
        assert retrieved is not None
        assert retrieved.parent_id == parent.parent_id
    
    def test_update_parent(self, registry):
        parent = registry.create_parent("Original Name")
        
        updated = registry.update_parent(
            parent.parent_id,
            parent_name="Updated Name",
            telegram_chat_id="111222333",
            telegram_enabled=False,
            notification_preferences=NotificationPreference.MORNING_ABSENCE_ONLY,
        )
        
        assert updated is not None
        assert updated.parent_name == "Updated Name"
        assert updated.telegram_chat_id == "111222333"
        assert updated.telegram_enabled is False
        assert updated.notification_preferences == NotificationPreference.MORNING_ABSENCE_ONLY
    
    def test_delete_parent(self, registry):
        parent = registry.create_parent("To Delete")
        result = registry.delete_parent(parent.parent_id)
        
        assert result is True
        assert registry.get_parent(parent.parent_id) is None
    
    def test_list_parents(self, registry):
        registry.create_parent("Parent 1")
        registry.create_parent("Parent 2")
        registry.create_parent("Parent 3")
        
        parents = registry.list_parents()
        assert len(parents) == 3
    
    def test_link_student_parent(self, registry):
        parent = registry.create_parent("Test Parent")
        
        link = registry.link_student_parent(
            student_id="HS001",
            parent_id=parent.parent_id,
            relationship="parent",
            is_primary=True,
        )
        
        assert link.link_id.startswith("LNK-")
        assert link.student_id == "HS001"
        assert link.parent_id == parent.parent_id
        assert link.is_primary is True
    
    def test_link_student_parent_invalid_parent(self, registry):
        with pytest.raises(ValueError):
            registry.link_student_parent("HS001", "PAR-nonexistent")
    
    def test_get_student_parents(self, registry):
        parent1 = registry.create_parent("Parent 1")
        parent2 = registry.create_parent("Parent 2")
        
        registry.link_student_parent("HS001", parent1.parent_id, is_primary=True)
        registry.link_student_parent("HS001", parent2.parent_id, is_primary=False)
        
        parents = registry.get_student_parents("HS001")
        assert len(parents) == 2
        # Primary should come first
        assert parents[0].parent_id == parent1.parent_id
    
    def test_get_parent_students(self, registry):
        parent = registry.create_parent("Test Parent")
        
        registry.link_student_parent("HS001", parent.parent_id)
        registry.link_student_parent("HS002", parent.parent_id)
        registry.link_student_parent("HS003", parent.parent_id)
        
        students = registry.get_parent_students(parent.parent_id)
        assert len(students) == 3
        assert "HS001" in students
        assert "HS002" in students
        assert "HS003" in students
    
    def test_get_student_primary_parent(self, registry):
        parent1 = registry.create_parent("Primary Parent")
        parent2 = registry.create_parent("Secondary Parent")
        
        registry.link_student_parent("HS001", parent1.parent_id, is_primary=True)
        registry.link_student_parent("HS001", parent2.parent_id, is_primary=False)
        
        primary = registry.get_student_primary_parent("HS001")
        assert primary is not None
        assert primary.parent_id == parent1.parent_id
    
    def test_unlink_student_parent(self, registry):
        parent = registry.create_parent("Test Parent")
        registry.link_student_parent("HS001", parent.parent_id)
        
        result = registry.unlink_student_parent("HS001", parent.parent_id)
        assert result is True
        
        parents = registry.get_student_parents("HS001")
        assert len(parents) == 0
    
    def test_create_link_code(self, registry):
        link_code = registry.create_link_code("HS001", expires_in_hours=24)
        
        assert link_code.code is not None
        assert "-" in link_code.code  # Format: XXXX-XXXX
        assert link_code.student_id == "HS001"
        assert link_code.status == LinkCodeStatus.ACTIVE
        assert link_code.expires_at is not None
    
    def test_validate_link_code_success(self, registry):
        link_code = registry.create_link_code("HS001")
        
        validated = registry.validate_link_code(link_code.code, "123456789")
        
        assert validated is not None
        assert validated.status == LinkCodeStatus.USED
        assert validated.used_by_chat_id == "123456789"
        assert validated.used_at is not None
    
    def test_validate_link_code_invalid(self, registry):
        validated = registry.validate_link_code("INVALID-CODE", "123456789")
        assert validated is None
    
    def test_validate_link_code_expired(self, registry):
        # Create expired link code
        link_code = registry.create_link_code("HS001", expires_in_hours=-1)
        
        validated = registry.validate_link_code(link_code.code, "123456789")
        assert validated is None
    
    def test_validate_link_code_already_used(self, registry):
        link_code = registry.create_link_code("HS001")
        
        # Use it once
        registry.validate_link_code(link_code.code, "123456789")
        
        # Try to use again
        validated = registry.validate_link_code(link_code.code, "987654321")
        assert validated is None
    
    def test_get_link_code(self, registry):
        link_code = registry.create_link_code("HS001")
        retrieved = registry.get_link_code(link_code.code)
        
        assert retrieved is not None
        assert retrieved.code == link_code.code
        assert retrieved.status == LinkCodeStatus.ACTIVE
    
    def test_revoke_link_code(self, registry):
        link_code = registry.create_link_code("HS001")
        result = registry.revoke_link_code(link_code.code)
        
        assert result is True
        retrieved = registry.get_link_code(link_code.code)
        assert retrieved.status == LinkCodeStatus.REVOKED
    
    def test_cleanup_expired_codes(self, registry):
        # Create some expired codes
        registry.create_link_code("HS001", expires_in_hours=-1)
        registry.create_link_code("HS002", expires_in_hours=-1)
        # Create active code
        registry.create_link_code("HS003", expires_in_hours=24)
        
        cleaned = registry.cleanup_expired_codes()
        assert cleaned == 2
    
    def test_get_notification_recipients(self, registry):
        # Create parents with different preferences
        parent_all = registry.create_parent(
            "Parent All",
            telegram_chat_id="111",
            notification_preferences=NotificationPreference.ALL,
        )
        parent_morning = registry.create_parent(
            "Parent Morning",
            telegram_chat_id="222",
            notification_preferences=NotificationPreference.MORNING_ABSENCE_ONLY,
        )
        parent_none = registry.create_parent(
            "Parent None",
            telegram_chat_id="333",
            notification_preferences=NotificationPreference.NONE,
        )
        parent_no_chat = registry.create_parent(
            "Parent No Chat",
            notification_preferences=NotificationPreference.ALL,
        )
        
        registry.link_student_parent("HS001", parent_all.parent_id)
        registry.link_student_parent("HS001", parent_morning.parent_id)
        registry.link_student_parent("HS001", parent_none.parent_id)
        registry.link_student_parent("HS001", parent_no_chat.parent_id)
        
        # Test morning absence - should get parent_all and parent_morning
        recipients = registry.get_notification_recipients("HS001", "morning_absence")
        assert len(recipients) == 2
        chat_ids = {p.telegram_chat_id for p in recipients}
        assert "111" in chat_ids
        assert "222" in chat_ids
        
        # Test long exit - should only get parent_all
        recipients = registry.get_notification_recipients("HS001", "long_exit")
        assert len(recipients) == 1
        assert recipients[0].telegram_chat_id == "111"
        
        # Test missing checkout - should only get parent_all
        recipients = registry.get_notification_recipients("HS001", "missing_checkout")
        assert len(recipients) == 1
        assert recipients[0].telegram_chat_id == "111"
    
    def test_get_chat_id_for_student_policy(self, registry):
        parent = registry.create_parent("Test Parent", telegram_chat_id="123456789")
        registry.link_student_parent("HS001", parent.parent_id)
        
        chat_ids = registry.get_chat_id_for_student_policy("HS001", "morning_absence")
        assert chat_ids == ["123456789"]


class TestParentModel:
    """Tests for Parent model."""
    
    def test_parent_creation(self):
        parent = Parent(
            parent_id="PAR-test123",
            parent_name="Test Parent",
            telegram_chat_id="123456789",
            telegram_enabled=True,
            notification_preferences=NotificationPreference.ALL,
        )
        
        assert parent.parent_id == "PAR-test123"
        assert parent.parent_name == "Test Parent"
    
    def test_parent_serialization(self):
        parent = Parent(
            parent_id="PAR-test123",
            parent_name="Test Parent",
            telegram_chat_id="123456789",
        )
        
        data = parent.to_dict()
        parent2 = Parent.from_dict(data)
        
        assert parent2.parent_id == parent.parent_id
        assert parent2.parent_name == parent.parent_name
        assert parent2.telegram_chat_id == parent.telegram_chat_id
    
    def test_parent_validation(self):
        with pytest.raises(ValueError):
            Parent(parent_id="", parent_name="Test")
        with pytest.raises(ValueError):
            Parent(parent_id="PAR-test", parent_name="")


class TestStudentParentLinkModel:
    """Tests for StudentParentLink model."""
    
    def test_link_creation(self):
        link = StudentParentLink(
            link_id="LNK-test123",
            student_id="HS001",
            parent_id="PAR-test456",
            relationship="guardian",
            is_primary=True,
        )
        
        assert link.link_id == "LNK-test123"
        assert link.student_id == "HS001"
        assert link.parent_id == "PAR-test456"
        assert link.relationship == "guardian"
        assert link.is_primary is True
    
    def test_link_serialization(self):
        link = StudentParentLink(
            link_id="LNK-test123",
            student_id="HS001",
            parent_id="PAR-test456",
        )
        
        data = link.to_dict()
        link2 = StudentParentLink.from_dict(data)
        
        assert link2.link_id == link.link_id
        assert link2.student_id == link.student_id
        assert link2.parent_id == link.parent_id


class TestLinkCodeModel:
    """Tests for LinkCode model."""
    
    def test_link_code_creation(self):
        code = LinkCode(
            code="ABCD-EFGH",
            student_id="HS001",
            parent_id="PAR-test",
            status=LinkCodeStatus.ACTIVE,
        )
        
        assert code.code == "ABCD-EFGH"
        assert code.student_id == "HS001"
        assert code.parent_id == "PAR-test"
        assert code.status == LinkCodeStatus.ACTIVE
    
    def test_link_code_is_valid(self):
        # Active, not expired
        code = LinkCode(
            code="ABCD-EFGH",
            student_id="HS001",
            status=LinkCodeStatus.ACTIVE,
            expires_at=(datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z",
        )
        assert code.is_valid() is True
        
        # Expired
        code_expired = LinkCode(
            code="ABCD-EFGH",
            student_id="HS001",
            status=LinkCodeStatus.ACTIVE,
            expires_at=(datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z",
        )
        assert code_expired.is_valid() is False
        
        # Used
        code_used = LinkCode(
            code="ABCD-EFGH",
            student_id="HS001",
            status=LinkCodeStatus.USED,
        )
        assert code_used.is_valid() is False
    
    def test_link_code_serialization(self):
        code = LinkCode(
            code="ABCD-EFGH",
            student_id="HS001",
        )
        
        data = code.to_dict()
        code2 = LinkCode.from_dict(data)
        
        assert code2.code == code.code
        assert code2.student_id == code.student_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])