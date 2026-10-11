"""
Phase 37B — Production Attendance Policy Engine.

Canonical policy decision layer on top of Phase 37A timetable + Phase 26 attendance contracts.

Architecture:
    Timetable + DailyExpectedResolver + Attendance State + Raw/Resolved IN/OUT evidence
        ↓
    Attendance Policy Engine
        ↓
    Canonical Policy Event
        ↓
    Notification Queue
        ↓
    Telegram Worker
        ↓
    Parent Registry
        ↓
    telegram_chat_id

Excel is another consumer of canonical attendance/policy state.
Telegram MUST NOT calculate attendance.
Excel MUST NOT calculate attendance.
There must be ONE canonical policy decision.
"""