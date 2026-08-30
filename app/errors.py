"""
Error model for Windows native AI attendance system.

Provides a small, consistent application error model distinguishing:
- ConfigurationError
- EnvironmentError
- DependencyError
- RuntimeError

This module does not over-engineer the error hierarchy.
"""

from __future__ import annotations

from typing import Optional


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConfigurationError(AppError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str, config_key: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(message, details)
        self.config_key = config_key


class EnvironmentError(AppError):
    """Raised when the runtime environment is invalid or unsupported."""

    def __init__(self, message: str, requirement: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(message, details)
        self.requirement = requirement


class DependencyError(AppError):
    """Raised when a required dependency is missing or incompatible."""

    def __init__(self, message: str, package: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(message, details)
        self.package = package


class RuntimeError(AppError):
    """Raised when a runtime operation fails."""

    def __init__(self, message: str, operation: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(message, details)
        self.operation = operation


# Convenience functions for common error patterns
def raise_config_error(message: str, config_key: Optional[str] = None, **details) -> None:
    """Raise a ConfigurationError with optional details."""
    raise ConfigurationError(message, config_key=config_key, details=details or None)


def raise_env_error(message: str, requirement: Optional[str] = None, **details) -> None:
    """Raise an EnvironmentError with optional details."""
    raise EnvironmentError(message, requirement=requirement, details=details or None)


def raise_dep_error(message: str, package: Optional[str] = None, **details) -> None:
    """Raise a DependencyError with optional details."""
    raise DependencyError(message, package=package, details=details or None)


def raise_runtime_error(message: str, operation: Optional[str] = None, **details) -> None:
    """Raise a RuntimeError with optional details."""
    raise RuntimeError(message, operation=operation, details=details or None)