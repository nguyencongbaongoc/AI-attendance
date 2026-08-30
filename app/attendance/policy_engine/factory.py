"""
Phase 37B/37C — Factory for creating complete policy engine stack.

Provides a single entry point to create all Phase 37B/37C components.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.attendance.timetable import Timetable
from app.attendance.calendar import CalendarEngine, CalendarConfig
from app.attendance.daily_resolver import DailyExpectedResolver, IdentityResolver, DayResolver
from app.attendance.engine import AttendanceEngine, create_attendance_engine_with_resolvers
from app.attendance.policy import AttendancePolicy
from app.attendance.repository import AttendanceRepository
from app.attendance.policy_engine.engine import (
    AttendancePolicyEngine,
    PolicyEngineConfig,
    create_attendance_policy_engine,
)
from app.attendance.policy_engine.parent_registry import (
    ParentRegistry,
    create_parent_registry,
)
from app.attendance.policy_engine.telegram_bot import (
    TelegramBot,
    NotificationQueue,
    TelegramWorker,
    create_telegram_bot,
    create_notification_queue,
    create_telegram_worker,
)
from app.attendance.policy_engine.excel_integration import (
    PolicyExcelExporter,
    PolicyExcelExporterConfig,
    create_policy_excel_exporter,
)
from app.attendance.policy_engine.templates import create_notification_message
from app.attendance.policy_engine.exit_session import ExitSessionStore, create_exit_session_store_from_settings
from app.replay.fusion import GlobalObservation


class PolicyEngineStack:
    """
    Complete Phase 37B/37C policy engine stack.
    
    Contains all components needed for production attendance policy evaluation,
    parent notification, Excel reporting, and exit session persistence.
    """
    
    def __init__(
        self,
        timetable: Timetable,
        calendar_engine: CalendarEngine,
        daily_resolver: DailyExpectedResolver,
        attendance_engine: AttendanceEngine,
        policy_engine: AttendancePolicyEngine,
        parent_registry: ParentRegistry,
        telegram_bot: TelegramBot,
        notification_queue: NotificationQueue,
        telegram_worker: TelegramWorker,
        excel_exporter: PolicyExcelExporter,
        exit_session_store: ExitSessionStore,
    ):
        self.timetable = timetable
        self.calendar_engine = calendar_engine
        self.daily_resolver = daily_resolver
        self.attendance_engine = attendance_engine
        self.policy_engine = policy_engine
        self.parent_registry = parent_registry
        self.telegram_bot = telegram_bot
        self.notification_queue = notification_queue
        self.telegram_worker = telegram_worker
        self.excel_exporter = excel_exporter
        self.exit_session_store = exit_session_store
    
    async def start(self) -> None:
        """Start all background workers."""
        await self.telegram_worker.start()
    
    async def stop(self) -> None:
        """Stop all background workers."""
        await self.telegram_worker.stop()
    
    def process_policy_events(self, policy_events: List) -> List[Dict[str, Any]]:
        """
        Process policy events through notification pipeline.
        
        Args:
            policy_events: List of PolicyEvents from policy engine
            
        Returns:
            List of notification records created
        """
        notification_records = []
        
        for event in policy_events:
            if not event.is_notification_type:
                continue
            
            # Get recipients
            recipients = self.parent_registry.get_notification_recipients(
                event.student_id,
                event.policy_type.value,
            )
            
            if not recipients:
                # No recipients - mark event as having no recipient
                # (In practice, you'd update the event state)
                continue
            
            # Get student name from evidence or use ID
            student_name = event.evidence.get("student_name", f"Student {event.student_id}")
            date_str = datetime.fromtimestamp(event.occurred_at).strftime("%Y-%m-%d")
            
            # Create message
            message = create_notification_message(
                policy_type=event.policy_type.value,
                student_name=student_name,
                student_id=event.student_id,
                date=date_str,
                evidence=event.evidence,
            )
            
            # Enqueue for each recipient
            for parent in recipients:
                notification = self.notification_queue.enqueue_notification(
                    event=event,
                    parent=parent,
                    message=message,
                )
                if notification:
                    notification_records.append(notification.to_dict())
        
        return notification_records
    
    def export_daily_report(
        self,
        target_date: date,
        output_path: str,
        policy_events: List,
        notification_records: List[Dict[str, Any]],
    ) -> Any:
        """
        Export daily attendance report with policy events.
        
        Args:
            target_date: Date to export
            output_path: Output file path
            policy_events: Policy events for the date
            notification_records: Notification records for the date
            
        Returns:
            DailyExportResult
        """
        from app.attendance.daily_excel import DailyExportRequest
        
        request = DailyExportRequest(
            date=target_date,
            output_path=output_path,
            timetable=self.timetable,
        )
        
        return self.excel_exporter.export_daily_with_policy(
            request=request,
            policy_events=policy_events,
            notification_records=notification_records,
        )


def create_policy_engine_stack(
    timetable: Timetable,
    calendar_config: Optional[CalendarConfig] = None,
    enrollment_person_ids: Optional[List[str]] = None,
    enrollment_embeddings: Optional[Any] = None,
    enrollment_metadata: Optional[Dict[str, Any]] = None,
    attendance_policy: Optional[AttendancePolicy] = None,
    policy_config: Optional[PolicyEngineConfig] = None,
    parent_registry_db: str = "data/parent_registry.db",
    notification_queue_db: str = "data/notification_queue.db",
    telegram_bot_token: Optional[str] = None,
    excel_config: Optional[PolicyExcelExporterConfig] = None,
) -> PolicyEngineStack:
    """
    Create complete Phase 37B policy engine stack.
    
    This is the main factory function that creates all components
    with proper wiring.
    
    Args:
        timetable: Phase 26/37A Timetable
        calendar_config: Calendar configuration (optional, uses defaults)
        enrollment_person_ids: List of enrolled person IDs
        enrollment_embeddings: Enrollment embeddings array
        enrollment_metadata: Enrollment metadata
        attendance_policy: Attendance policy (optional, uses defaults)
        policy_config: Policy engine configuration (optional, uses defaults)
        parent_registry_db: Path to parent registry database
        notification_queue_db: Path to notification queue database
        telegram_bot_token: Telegram bot token (optional, reads from env)
        excel_config: Excel exporter configuration (optional, uses defaults)
        
    Returns:
        PolicyEngineStack with all components initialized
    """
    # Create calendar engine
    calendar_engine = CalendarEngine(calendar_config or CalendarConfig())
    
    # Create daily resolver
    daily_resolver = DailyExpectedResolver(
        timetable=timetable,
        calendar_engine=calendar_engine,
        enrollment_person_ids=enrollment_person_ids,
    )
    
    # Create attendance engine with resolvers
    attendance_engine, identity_resolver, day_resolver, daily_resolver_with_identity = (
        create_attendance_engine_with_resolvers(
            policy=attendance_policy or AttendancePolicy(policy_id="default"),
            timetable=timetable,
            calendar_engine=calendar_engine,
            enrollment_person_ids=enrollment_person_ids or [],
            enrollment_embeddings=enrollment_embeddings,
            enrollment_metadata=enrollment_metadata,
        )
    )
    
    # Attach identity resolver to daily resolver for convenience
    daily_resolver.identity_resolver = identity_resolver
    
    # Create policy engine
    policy_engine = create_attendance_policy_engine(
        timetable=timetable,
        calendar_engine=calendar_engine,
        daily_resolver=daily_resolver,
        attendance_engine=attendance_engine,
        config=policy_config,
    )
    
    # Create parent registry
    parent_registry = create_parent_registry(parent_registry_db)
    
    # Create Telegram bot
    telegram_bot = create_telegram_bot(telegram_bot_token)
    
    # Create notification queue
    notification_queue = create_notification_queue(
        parent_registry=parent_registry,
        telegram_bot=telegram_bot,
        db_path=notification_queue_db,
    )
    
    # Create Telegram worker
    telegram_worker = create_telegram_worker(
        notification_queue=notification_queue,
        telegram_bot=telegram_bot,
    )
    
    # Create Excel exporter
    excel_exporter = create_policy_excel_exporter(
        repository=attendance_engine.repository,
        config=excel_config,
    )
    
    # Create exit session store
    exit_session_store = create_exit_session_store_from_settings()
    
    return PolicyEngineStack(
        timetable=timetable,
        calendar_engine=calendar_engine,
        daily_resolver=daily_resolver,
        attendance_engine=attendance_engine,
        policy_engine=policy_engine,
        parent_registry=parent_registry,
        telegram_bot=telegram_bot,
        notification_queue=notification_queue,
        telegram_worker=telegram_worker,
        excel_exporter=excel_exporter,
        exit_session_store=exit_session_store,
    )


def create_default_attendance_policy(policy_id: str = "production") -> AttendancePolicy:
    """Create a default attendance policy for production use."""
    return AttendancePolicy(
        policy_id=policy_id,
        policy_version="1.0",
        unknown_identity_policy="unresolved",
        ambiguous_identity_policy="pending_review",
        duplicate_decision_policy="ignore",
        session_finalization_policy="event_based",
        default_entry_window_seconds=300,      # 5 minutes
        default_late_tolerance_seconds=600,    # 10 minutes
        default_exit_window_seconds=300,       # 5 minutes
    )


def create_default_policy_config() -> PolicyEngineConfig:
    """Create default policy engine configuration."""
    return PolicyEngineConfig(
        morning_absence_check_seconds=27000,    # 07:30
        exit_threshold_seconds=1800,            # 30 minutes
        default_departure_check_seconds=63000,  # 17:30
        timezone="Asia/Bangkok",
    )


def create_default_excel_config() -> PolicyExcelExporterConfig:
    """Create default Excel exporter configuration."""
    return PolicyExcelExporterConfig(
        include_policy_events_sheet=True,
        include_notification_status_sheet=True,
        include_policy_summary_sheet=True,
    )