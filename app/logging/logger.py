"""
Centralized logging foundation for Windows native AI attendance system.

Requirements:
- Console logging
- File logging
- Log levels
- Timestamps
- Structured context where practical
- Domain-specific logging (CAMERA, AI, ATTENDANCE, POLICY, TELEGRAM)
- Secret filtering (never log tokens, credentials, chat_ids)

Phase 37C additions:
- Structured logging for CAMERA, AI, ATTENDANCE, POLICY, TELEGRAM
- Secret filtering for tokens, credentials, chat_ids
- JSON structured output for production
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

import structlog


# Global flag to track if logging has been configured
_logging_configured = False

# Secret patterns to filter from logs
_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r'(TELEGRAM_BOT_TOKEN|BOT_TOKEN|TOKEN|SECRET|PASSWORD|API_KEY|CHAT_ID)\s*[:=]\s*\S+', re.IGNORECASE),
    re.compile(r'\b\d+:[A-Za-z0-9_-]{35,}\b'),  # Telegram bot token pattern
    re.compile(r'chat_id\s*[:=]\s*\d+', re.IGNORECASE),
    re.compile(r'telegram_chat_id\s*[:=]\s*\d+', re.IGNORECASE),
]

# Domain-specific logger names
DOMAIN_LOGGERS = {
    "camera": "app.camera",
    "ai": "app.ai",
    "attendance": "app.attendance",
    "policy": "app.policy",
    "telegram": "app.telegram",
}


class SecretFilter(logging.Filter):
    """Filter to remove secrets from log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for pattern in _SECRET_PATTERNS:
                # Only use \1 replacement if pattern has capturing groups
                if pattern.groups > 0:
                    record.msg = pattern.sub(r'\1=***REDACTED***', record.msg)
                else:
                    record.msg = pattern.sub('***REDACTED***', record.msg)
        if hasattr(record, 'args') and record.args:
            # Filter args if they contain secrets
            filtered_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    filtered = arg
                    for pattern in _SECRET_PATTERNS:
                        if pattern.groups > 0:
                            filtered = pattern.sub(r'\1=***REDACTED***', filtered)
                        else:
                            filtered = pattern.sub('***REDACTED***', filtered)
                    filtered_args.append(filtered)
                else:
                    filtered_args.append(arg)
            record.args = tuple(filtered_args)
        return True


def _create_secret_filtering_processor():
    """Create a structlog processor that filters secrets from log entries."""
    def filter_secrets(logger, method_name, event_dict):
        # Filter sensitive keys
        sensitive_keys = {
            'bot_token', 'token', 'secret', 'password', 'api_key', 
            'chat_id', 'telegram_chat_id', 'authorization', 'cookie'
        }
        for key in list(event_dict.keys()):
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                event_dict[key] = "***REDACTED***"
            # Also filter values that look like tokens
            if isinstance(event_dict[key], str):
                for pattern in _SECRET_PATTERNS:
                    if pattern.search(event_dict[key]):
                        event_dict[key] = "***REDACTED***"
                        break
        return event_dict
    return filter_secrets


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    json_format: bool = False,
    console: bool = True,
) -> None:
    """
    Configure centralized logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file. If None, file logging is disabled.
        json_format: If True, use JSON format for structured logging.
        console: If True, enable console logging.
    """
    global _logging_configured

    if _logging_configured:
        return

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure standard library logging
    handlers = []

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.addFilter(SecretFilter())
        handlers.append(console_handler)

    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Use rotating file handler to prevent unbounded growth
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.addFilter(SecretFilter())
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,  # Override any existing configuration
    )

    # Configure structlog with secret filtering
    secret_filter = _create_secret_filtering_processor()
    
    if json_format:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                secret_filter,
                structlog.processors.JSONRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                secret_filter,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    _logging_configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__ of the calling module).

    Returns:
        Structured logger instance.
    """
    if not _logging_configured:
        # Auto-configure with defaults if not already configured
        setup_logging()

    return structlog.get_logger(name)


def get_domain_logger(domain: str) -> structlog.stdlib.BoundLogger:
    """
    Get a domain-specific logger with pre-bound domain context.
    
    Args:
        domain: One of 'camera', 'ai', 'attendance', 'policy', 'telegram'
        
    Returns:
        Structured logger with domain context bound.
    """
    if domain not in DOMAIN_LOGGERS:
        raise ValueError(f"Unknown domain: {domain}. Valid domains: {list(DOMAIN_LOGGERS.keys())}")
    
    logger = get_logger(DOMAIN_LOGGERS[domain])
    return logger.bind(domain=domain)


def get_logger_with_context(name: str, **context) -> structlog.stdlib.BoundLogger:
    """
    Get a logger with pre-bound context.

    Args:
        name: Logger name.
        **context: Key-value pairs to bind as context.

    Returns:
        Structured logger with bound context.
    """
    logger = get_logger(name)
    return logger.bind(**context)


class LoggingContext:
    """
    Context manager for temporarily binding context to all loggers.

    Usage:
        with LoggingContext(request_id="abc123", user_id=42):
            logger.info("Processing request")
    """

    def __init__(self, **context):
        self.context = context
        self._tokens = []

    def __enter__(self):
        # Bind context to structlog's thread-local context
        for key, value in self.context.items():
            token = structlog.contextvars.bind_contextvars(**{key: value})
            self._tokens.append(token)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Unbind context
        for token in self._tokens:
            structlog.contextvars.unbind_contextvars(token)


# Convenience function for quick setup
def quick_setup(log_level: str = "INFO", log_dir: Optional[Path] = None) -> None:
    """
    Quick logging setup with sensible defaults.

    Args:
        log_level: Logging level.
        log_dir: Optional directory for log files. If provided, creates
                 a timestamped log file in that directory.
    """
    log_file = None
    if log_dir:
        from datetime import datetime
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"app_{timestamp}.log"

    setup_logging(log_level=log_level, log_file=log_file, json_format=False, console=True)
