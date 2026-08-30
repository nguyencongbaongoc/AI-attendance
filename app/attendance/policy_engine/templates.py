"""
Phase 37B — Notification Message Templates.

Templates for parent notifications.
No internal IDs, no secrets, only human-readable information.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class NotificationTemplate:
    """Template for a notification message."""
    subject: str
    body: str
    
    def format(self, **kwargs) -> str:
        """Format the template with provided values."""
        return self.body.format(**kwargs)


# =============================================================================
# MORNING ABSENCE TEMPLATE
# =============================================================================

MORNING_ABSENCE_TEMPLATE = NotificationTemplate(
    subject="⚠️ Morning Absence Alert",
    body=(
        "📅 <b>Date:</b> {date}\n"
        "👤 <b>Student:</b> {student_name} ({student_id})\n"
        "🏫 <b>Expected Arrival:</b> {expected_entry_time}\n"
        "⏰ <b>Check Time:</b> {check_time}\n"
        "📍 <b>Status:</b> <b>ABSENT</b> - No check-in recorded\n\n"
        "📋 <b>Scheduled Sessions:</b>\n{sessions}\n\n"
        "Please contact the school if this is an error."
    ),
)


def format_morning_absence_message(
    student_name: str,
    student_id: str,
    date: str,
    check_time: str,
    expected_entry_time: str,
    sessions: List[Dict[str, Any]],
) -> str:
    """Format morning absence notification message."""
    sessions_text = ""
    for s in sessions:
        sessions_text += f"  • {s['class_name']} ({s['session_id']}) - Entry: {s['entry_time']}\n"
    
    return MORNING_ABSENCE_TEMPLATE.format(
        student_name=student_name,
        student_id=student_id,
        date=date,
        check_time=check_time,
        expected_entry_time=expected_entry_time,
        sessions=sessions_text.strip(),
    )


# =============================================================================
# LONG EXIT TEMPLATE
# =============================================================================

LONG_EXIT_TEMPLATE = NotificationTemplate(
    subject="⚠️ Extended Exit Alert",
    body=(
        "📅 <b>Date:</b> {date}\n"
        "👤 <b>Student:</b> {student_name} ({student_id})\n"
        "🚪 <b>Exit Time:</b> {out_time}\n"
        "⏱️ <b>Elapsed:</b> {elapsed_minutes} minutes\n"
        "📏 <b>Threshold:</b> {threshold_minutes} minutes\n"
        "📍 <b>Status:</b> <b>LONG EXIT</b> - Student has not returned\n\n"
        "Please check on your child's whereabouts."
    ),
)


def format_long_exit_message(
    student_name: str,
    student_id: str,
    date: str,
    out_time: str,
    elapsed_minutes: int,
    threshold_minutes: int,
) -> str:
    """Format long exit notification message."""
    return LONG_EXIT_TEMPLATE.format(
        student_name=student_name,
        student_id=student_id,
        date=date,
        out_time=out_time,
        elapsed_minutes=elapsed_minutes,
        threshold_minutes=threshold_minutes,
    )


# =============================================================================
# MISSING CHECKOUT TEMPLATE
# =============================================================================

MISSING_CHECKOUT_TEMPLATE = NotificationTemplate(
    subject="⚠️ Missing Checkout Alert",
    body=(
        "📅 <b>Date:</b> {date}\n"
        "👤 <b>Student:</b> {student_name} ({student_id})\n"
        "🕐 <b>Expected Departure:</b> {expected_departure_time}\n"
        "📍 <b>Status:</b> <b>MISSING CHECKOUT</b> - No check-out recorded\n\n"
        "📋 <b>Scheduled Sessions:</b>\n{sessions}\n\n"
        "Please contact the school if your child has already left."
    ),
)


def format_missing_checkout_message(
    student_name: str,
    student_id: str,
    date: str,
    expected_departure_time: str,
    sessions: List[Dict[str, Any]],
) -> str:
    """Format missing checkout notification message."""
    sessions_text = ""
    for s in sessions:
        sessions_text += f"  • {s['class_name']} ({s['session_id']}) - Exit: {s['exit_time']}\n"
    
    return MISSING_CHECKOUT_TEMPLATE.format(
        student_name=student_name,
        student_id=student_id,
        date=date,
        expected_departure_time=expected_departure_time,
        sessions=sessions_text.strip(),
    )


# =============================================================================
# MESSAGE FACTORY
# =============================================================================

def create_notification_message(
    policy_type: str,
    student_name: str,
    student_id: str,
    date: str,
    evidence: Dict[str, Any],
) -> str:
    """
    Factory function to create notification message from policy event evidence.
    
    Args:
        policy_type: Type of policy event
        student_name: Student's display name
        student_id: Student ID
        date: Date string (YYYY-MM-DD)
        evidence: Evidence dictionary from PolicyEvent
        
    Returns:
        Formatted message string
    """
    if policy_type == "morning_absence":
        return format_morning_absence_message(
            student_name=student_name,
            student_id=student_id,
            date=date,
            check_time=evidence.get("check_time", "N/A"),
            expected_entry_time=evidence.get("expected_entry_time", "N/A"),
            sessions=evidence.get("expected_sessions", []),
        )
    
    elif policy_type == "long_exit":
        elapsed_seconds = evidence.get("elapsed_seconds", 0)
        elapsed_minutes = elapsed_seconds // 60
        threshold_seconds = evidence.get("threshold_seconds", 1800)
        threshold_minutes = threshold_seconds // 60
        
        return format_long_exit_message(
            student_name=student_name,
            student_id=student_id,
            date=date,
            out_time=evidence.get("out_time", "N/A"),
            elapsed_minutes=elapsed_minutes,
            threshold_minutes=threshold_minutes,
        )
    
    elif policy_type == "missing_checkout":
        return format_missing_checkout_message(
            student_name=student_name,
            student_id=student_id,
            date=date,
            expected_departure_time=evidence.get("expected_departure_time", "N/A"),
            sessions=evidence.get("expected_sessions", []),
        )
    
    else:
        # Fallback generic message
        return (
            f"📅 <b>Date:</b> {date}\n"
            f"👤 <b>Student:</b> {student_name} ({student_id})\n"
            f"📍 <b>Event:</b> {policy_type.replace('_', ' ').title()}\n"
            f"Please check with the school for details."
        )


def get_student_display_name(student_id: str, person_name: Optional[str] = None) -> str:
    """Get display name for student."""
    if person_name:
        return person_name
    return f"Student {student_id}"