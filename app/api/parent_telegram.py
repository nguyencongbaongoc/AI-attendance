"""
Phase 41A — Parent/Telegram API Endpoints.

REST endpoints for parent management and Telegram notification queue.
Integrates with existing ParentRegistry and NotificationQueue.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.attendance.policy_engine.parent_registry import (
    ParentRegistry,
    Parent,
    StudentParentLink,
    LinkCode,
    LinkCodeStatus,
    NotificationPreference,
    create_parent_registry,
)
from app.attendance.policy_engine.telegram_bot import (
    NotificationQueue,
    NotificationRecord,
    TelegramSendStatus,
    create_notification_queue,
    create_telegram_bot,
)
from app.config.settings import load_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["parent", "telegram"])

# Global instances
_parent_registry: Optional[ParentRegistry] = None
_notification_queue: Optional[NotificationQueue] = None


def get_parent_registry() -> ParentRegistry:
    """Get or create the global parent registry."""
    global _parent_registry
    if _parent_registry is None:
        settings = load_settings()
        _parent_registry = create_parent_registry(settings.parent_registry.db_path)
    return _parent_registry


def get_notification_queue() -> NotificationQueue:
    """Get or create the global notification queue."""
    global _notification_queue
    if _notification_queue is None:
        settings = load_settings()
        parent_registry = get_parent_registry()
        telegram_bot = create_telegram_bot(settings.telegram.bot_token)
        _notification_queue = create_notification_queue(
            parent_registry=parent_registry,
            telegram_bot=telegram_bot,
            db_path=settings.notification_queue.db_path,
        )
    return _notification_queue


# Pydantic models for API responses

class ParentResponse(BaseModel):
    """Parent response model."""
    parent_id: str
    student_id: str
    name: str
    phone: str
    telegram_chat_id: Optional[str] = None
    link_code: Optional[str] = None
    linked_at: Optional[str] = None
    created_at: str


class ParentCreate(BaseModel):
    """Parent creation model."""
    student_id: str
    name: str
    phone: str
    telegram_chat_id: Optional[str] = None
    link_code: Optional[str] = None


class ParentUpdate(BaseModel):
    """Parent update model."""
    student_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    link_code: Optional[str] = None


class LinkTelegramRequest(BaseModel):
    """Link Telegram request model."""
    link_code: str


class NotificationQueueStatsResponse(BaseModel):
    """Notification queue stats response model."""
    pending: int
    sent: int
    failed: int


# Parent endpoints

@router.get("/parents", response_model=List[ParentResponse])
async def get_parents():
    """Get all parents."""
    registry = get_parent_registry()
    parents = registry.list_parents()
    
    # Get student links for each parent
    result = []
    for parent in parents:
        students = registry.get_parent_students(parent.parent_id)
        student_id = students[0] if students else ""
        
        result.append(ParentResponse(
            parent_id=parent.parent_id,
            student_id=student_id,
            name=parent.parent_name,
            phone="",  # Not stored in current model
            telegram_chat_id=parent.telegram_chat_id,
            link_code=None,  # Would need to query link_codes table
            linked_at=parent.updated_at if parent.telegram_chat_id else None,
            created_at=parent.created_at,
        ))
    
    return result


@router.get("/parents/{parent_id}", response_model=ParentResponse)
async def get_parent(parent_id: str):
    """Get a specific parent by ID."""
    registry = get_parent_registry()
    parent = registry.get_parent(parent_id)
    
    if not parent:
        raise HTTPException(status_code=404, detail=f"Parent {parent_id} not found")
    
    students = registry.get_parent_students(parent_id)
    student_id = students[0] if students else ""
    
    return ParentResponse(
        parent_id=parent.parent_id,
        student_id=student_id,
        name=parent.parent_name,
        phone="",
        telegram_chat_id=parent.telegram_chat_id,
        link_code=None,
        linked_at=parent.updated_at if parent.telegram_chat_id else None,
        created_at=parent.created_at,
    )


@router.post("/parents", response_model=ParentResponse)
async def create_parent(parent: ParentCreate):
    """Create a new parent record."""
    registry = get_parent_registry()
    
    new_parent = registry.create_parent(
        parent_name=parent.name,
        telegram_chat_id=parent.telegram_chat_id,
        telegram_enabled=True,
    )
    
    # Link to student
    if parent.student_id:
        registry.link_student_parent(parent.student_id, new_parent.parent_id, is_primary=True)
    
    return ParentResponse(
        parent_id=new_parent.parent_id,
        student_id=parent.student_id,
        name=new_parent.parent_name,
        phone="",
        telegram_chat_id=new_parent.telegram_chat_id,
        link_code=None,
        linked_at=new_parent.updated_at if new_parent.telegram_chat_id else None,
        created_at=new_parent.created_at,
    )


@router.put("/parents/{parent_id}", response_model=ParentResponse)
async def update_parent(parent_id: str, parent_update: ParentUpdate):
    """Update a parent record."""
    registry = get_parent_registry()
    
    updated = registry.update_parent(
        parent_id=parent_id,
        parent_name=parent_update.name,
        telegram_chat_id=parent_update.telegram_chat_id,
        telegram_enabled=True,
    )
    
    if not updated:
        raise HTTPException(status_code=404, detail=f"Parent {parent_id} not found")
    
    students = registry.get_parent_students(parent_id)
    student_id = students[0] if students else ""
    
    return ParentResponse(
        parent_id=updated.parent_id,
        student_id=student_id,
        name=updated.parent_name,
        phone="",
        telegram_chat_id=updated.telegram_chat_id,
        link_code=None,
        linked_at=updated.updated_at if updated.telegram_chat_id else None,
        created_at=updated.created_at,
    )


@router.post("/parents/{parent_id}/link", response_model=Dict[str, bool])
async def link_parent_telegram(parent_id: str, request: LinkTelegramRequest):
    """Link a parent to Telegram using a link code."""
    registry = get_parent_registry()
    
    # Validate link code
    link_code = registry.validate_link_code(request.link_code, "")
    if not link_code:
        raise HTTPException(status_code=400, detail="Invalid or expired link code")
    
    # Get parent
    parent = registry.get_parent(parent_id)
    if not parent:
        raise HTTPException(status_code=404, detail=f"Parent {parent_id} not found")
    
    # Update parent with chat_id from link code
    # In a real implementation, the link code would be associated with a chat_id
    # For now, we'll just mark as linked
    registry.update_parent(
        parent_id=parent_id,
        telegram_chat_id=link_code.used_by_chat_id,
    )
    
    return {"success": True}


# Telegram/Queue endpoints

@router.get("/telegram/queue/stats", response_model=NotificationQueueStatsResponse)
async def get_notification_queue_stats():
    """Get notification queue statistics."""
    queue = get_notification_queue()
    stats = queue.get_queue_stats()
    
    return NotificationQueueStatsResponse(
        pending=stats.get("pending", 0),
        sent=stats.get("sent", 0),
        failed=stats.get("failed", 0),
    )
