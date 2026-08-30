"""
Phase 37C — Operational CLI Tools.

Provides safe operational commands for production monitoring and management.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from app.config.settings import load_settings
from app.attendance.policy_engine.parent_registry import ParentRegistry, create_parent_registry
from app.attendance.policy_engine.telegram_bot import (
    TelegramBot, NotificationQueue, TelegramWorker,
    create_telegram_bot, create_notification_queue, create_telegram_worker
)

console = Console()


@click.group()
def cli():
    """AI Attendance System - Operational Tools"""
    pass


@cli.command()
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def health(output_format: str):
    """Check system health status."""
    settings = load_settings()
    
    health_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "system": "healthy",
        "components": {}
    }
    
    # Check database files
    db_checks = {
        "parent_registry": Path(settings.parent_registry.db_path).exists(),
        "notification_queue": Path(settings.notification_queue.db_path).exists(),
        "exit_sessions": Path(settings.exit_session.db_path).exists(),
    }
    
    health_data["components"]["databases"] = db_checks
    
    # Check Telegram configuration
    health_data["components"]["telegram"] = {
        "configured": bool(settings.telegram.bot_token),
        "live_test_enabled": settings.telegram.live_test_enabled,
    }
    
    # Check directories
    dir_checks = {
        "data": Path(settings.paths.data_dir).exists(),
        "logs": Path(settings.paths.logs_dir).exists(),
        "models": Path(settings.paths.models_dir).exists(),
    }
    health_data["components"]["directories"] = dir_checks
    
    # Overall health
    all_healthy = all(db_checks.values()) and all(dir_checks.values())
    health_data["system"] = "healthy" if all_healthy else "degraded"
    
    if output_format == 'json':
        console.print_json(json.dumps(health_data, indent=2))
    else:
        table = Table(title="System Health Check")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")
        
        for db_name, exists in db_checks.items():
            table.add_row(f"Database: {db_name}", "✓ OK" if exists else "✗ MISSING", settings.parent_registry.db_path if db_name == "parent_registry" else "")
        
        for dir_name, exists in dir_checks.items():
            table.add_row(f"Directory: {dir_name}", "✓ OK" if exists else "✗ MISSING", "")
        
        tg = health_data["components"]["telegram"]
        table.add_row("Telegram Bot", "✓ Configured" if tg["configured"] else "✗ Not Configured", 
                      f"Live test: {'enabled' if tg['live_test_enabled'] else 'disabled'}")
        
        console.print(table)
        console.print(f"\nOverall: [bold {'green' if all_healthy else 'yellow'}]{health_data['system'].upper()}[/bold]")


@cli.command()
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def status(output_format: str):
    """Show detailed system status."""
    settings = load_settings()
    
    # Parent registry stats
    parent_registry = create_parent_registry(settings.parent_registry.db_path)
    parents = parent_registry.list_parents()
    
    # Notification queue stats
    notification_queue = create_notification_queue(
        parent_registry=parent_registry,
        telegram_bot=create_telegram_bot(settings.telegram.bot_token),
        db_path=settings.notification_queue.db_path,
    )
    queue_stats = notification_queue.get_queue_stats()
    
    status_data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "parents_count": len(parents),
        "queue_stats": queue_stats,
        "configuration": {
            "telegram_configured": bool(settings.telegram.bot_token),
            "live_test_enabled": settings.telegram.live_test_enabled,
            "health_monitoring": settings.health_monitoring.enabled,
            "observability": settings.observability.structured_logging,
        }
    }
    
    if output_format == 'json':
        console.print_json(json.dumps(status_data, indent=2))
    else:
        console.print(Panel.fit(f"[bold]System Status[/bold] - {status_data['timestamp']}"))
        
        console.print(f"\n[cyan]Parents:[/cyan] {len(parents)}")
        for p in parents:
            console.print(f"  - {p.parent_name} ({p.parent_id}) - Chat: {p.telegram_chat_id or 'N/A'} - Pref: {p.notification_preferences.value}")
        
        table = Table(title="Notification Queue")
        table.add_column("Status", style="cyan")
        table.add_column("Count", style="green")
        for status, count in queue_stats.items():
            table.add_row(status, str(count))
        console.print(table)


@cli.command()
@click.option('--chat-id', required=True, help='Test chat ID to send message to')
@click.option('--message', default='Test message from AI Attendance System', help='Test message content')
def telegram_test(chat_id: str, message: str):
    """Send a controlled test message via Telegram (requires TELEGRAM_LIVE_TEST=true)."""
    settings = load_settings()
    
    if not settings.telegram.live_test_enabled:
        console.print("[red]Error:[/red] Live test not enabled. Set TELEGRAM_LIVE_TEST=true and TELEGRAM_TEST_CHAT_ID")
        sys.exit(1)
    
    if not settings.telegram.bot_token:
        console.print("[red]Error:[/red] TELEGRAM_BOT_TOKEN not configured")
        sys.exit(1)
    
    if chat_id != settings.telegram.live_test_chat_id:
        console.print("[red]Error:[/red] Chat ID does not match configured test chat ID")
        sys.exit(1)
    
    async def send_test():
        bot = create_telegram_bot(settings.telegram.bot_token)
        success, error = await bot.send_message(chat_id, message)
        await bot.close()
        
        if success:
            console.print(f"[green]✓[/green] Test message sent successfully to {chat_id}")
        else:
            console.print(f"[red]✗[/red] Failed to send test message: {error}")
            sys.exit(1)
    
    asyncio.run(send_test())


@cli.command()
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def timetable_validate(output_format: str):
    """Validate timetable data integrity."""
    # This would connect to the actual timetable storage
    console.print("[yellow]Timetable validation not yet implemented - requires timetable storage backend[/yellow]")


@cli.command()
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def parent_validate(output_format: str):
    """Validate parent registry data integrity."""
    settings = load_settings()
    parent_registry = create_parent_registry(settings.parent_registry.db_path)
    
    parents = parent_registry.list_parents()
    issues = []
    
    for parent in parents:
        if not parent.telegram_chat_id and parent.telegram_enabled:
            issues.append(f"Parent {parent.parent_id} ({parent.parent_name}) has telegram_enabled but no chat_id")
        
        # Check links
        students = parent_registry.get_parent_students(parent.parent_id)
        if not students:
            issues.append(f"Parent {parent.parent_id} has no linked students")
    
    result = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "parents_checked": len(parents),
        "issues_found": len(issues),
        "issues": issues
    }
    
    if output_format == 'json':
        console.print_json(json.dumps(result, indent=2))
    else:
        console.print(Panel.fit(f"[bold]Parent Registry Validation[/bold]"))
        console.print(f"Parents checked: {len(parents)}")
        console.print(f"Issues found: {len(issues)}")
        for issue in issues:
            console.print(f"  [yellow]⚠[/yellow] {issue}")
        if not issues:
            console.print("[green]✓ All validations passed[/green]")


@cli.command()
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def notification_status(output_format: str):
    """Show notification queue status and metrics."""
    settings = load_settings()
    parent_registry = create_parent_registry(settings.parent_registry.db_path)
    notification_queue = create_notification_queue(
        parent_registry=parent_registry,
        telegram_bot=create_telegram_bot(settings.telegram.bot_token),
        db_path=settings.notification_queue.db_path,
    )
    
    stats = notification_queue.get_queue_stats()
    
    # Get recent notifications
    pending = notification_queue.get_pending_notifications(limit=20)
    
    result = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "queue_stats": stats,
        "pending_count": len(pending),
        "recent_pending": [n.to_dict() for n in pending]
    }
    
    if output_format == 'json':
        console.print_json(json.dumps(result, indent=2))
    else:
        table = Table(title="Notification Queue Status")
        table.add_column("Status", style="cyan")
        table.add_column("Count", style="green")
        for status, count in stats.items():
            table.add_row(status, str(count))
        console.print(table)
        
        if pending:
            console.print(f"\n[cyan]Recent Pending ({len(pending)}):[/cyan]")
            for n in pending[:10]:
                console.print(f"  - {n.notification_id}: {n.student_id} / {n.notification_type} ({n.status.value})")


@cli.command()
@click.option('--notification-id', help='Specific notification ID to retry (optional)')
@click.option('--all-failed', is_flag=True, help='Retry all failed notifications')
def notification_retry(notification_id: Optional[str], all_failed: bool):
    """Retry failed notifications."""
    settings = load_settings()
    parent_registry = create_parent_registry(settings.parent_registry.db_path)
    notification_queue = create_notification_queue(
        parent_registry=parent_registry,
        telegram_bot=create_telegram_bot(settings.telegram.bot_token),
        db_path=settings.notification_queue.db_path,
    )
    
    if notification_id:
        # Retry specific notification
        notif = notification_queue.get_notification(notification_id)
        if notif:
            # Reset to pending for retry
            import sqlite3
            with sqlite3.connect(settings.notification_queue.db_path) as conn:
                conn.execute("""
                    UPDATE notifications 
                    SET status = 'pending', last_error = NULL, attempts = 0
                    WHERE notification_id = ?
                """, (notification_id,))
                conn.commit()
            console.print(f"[green]✓[/green] Notification {notification_id} reset for retry")
        else:
            console.print(f"[red]✗[/red] Notification {notification_id} not found")
    elif all_failed:
        # Reset all failed to pending
        import sqlite3
        with sqlite3.connect(settings.notification_queue.db_path) as conn:
            cursor = conn.execute("""
                UPDATE notifications 
                SET status = 'pending', last_error = NULL, attempts = 0
                WHERE status = 'failed'
            """)
            conn.commit()
            console.print(f"[green]✓[/green] Reset {cursor.rowcount} failed notifications for retry")
    else:
        console.print("[yellow]Specify --notification-id or --all-failed[/yellow]")

@cli.command()
@click.option('--format', 'output_format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def database_check(output_format: str):
    """Check database integrity and connectivity."""
    settings = load_settings()
    
    checks = []
    
    # Parent registry
    try:
        parent_registry = create_parent_registry(settings.parent_registry.db_path)
        parents = parent_registry.list_parents()
        checks.append({"database": "parent_registry", "status": "ok", "records": len(parents), "path": settings.parent_registry.db_path})
    except Exception as e:
        checks.append({"database": "parent_registry", "status": "error", "error": str(e), "path": settings.parent_registry.db_path})
    
    # Notification queue
    try:
        parent_registry = create_parent_registry(settings.parent_registry.db_path)
        notification_queue = create_notification_queue(
            parent_registry=parent_registry,
            telegram_bot=create_telegram_bot(settings.telegram.bot_token),
            db_path=settings.notification_queue.db_path,
        )
        stats = notification_queue.get_queue_stats()
        total = sum(stats.values())
        checks.append({"database": "notification_queue", "status": "ok", "records": total, "path": settings.notification_queue.db_path})
    except Exception as e:
        checks.append({"database": "notification_queue", "status": "error", "error": str(e), "path": settings.notification_queue.db_path})
    
    # Exit sessions
    try:
        exit_db = Path(settings.exit_session.db_path)
        if exit_db.exists():
            import sqlite3
            with sqlite3.connect(exit_db) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM exit_sessions")
                count = cursor.fetchone()[0]
            checks.append({"database": "exit_sessions", "status": "ok", "records": count, "path": str(exit_db)})
        else:
            checks.append({"database": "exit_sessions", "status": "not_found", "records": 0, "path": str(exit_db)})
    except Exception as e:
        checks.append({"database": "exit_sessions", "status": "error", "error": str(e), "path": settings.exit_session.db_path})
    
    result = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "checks": checks
    }
    
    if output_format == 'json':
        console.print_json(json.dumps(result, indent=2))
    else:
        table = Table(title="Database Integrity Check")
        table.add_column("Database", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Records", style="yellow")
        table.add_column("Path / Error")
        
        for check in checks:
            status_style = "green" if check["status"] == "ok" else "red" if check["status"] == "error" else "yellow"
            table.add_row(
                check["database"],
                f"[{status_style}]{check['status']}[/{status_style}]",
                str(check.get("records", "N/A")),
                check.get("path", check.get("error", ""))
            )
        console.print(table)


if __name__ == "__main__":
    cli()