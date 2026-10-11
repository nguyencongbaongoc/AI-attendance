"""
Model exceptions for Windows native AI attendance system.

Provides model-specific error types for the registry.
"""

from __future__ import annotations

from typing import Optional

from app.errors import AppError


class ModelError(AppError):
    """Base error for model-related operations."""

    def __init__(
        self,
        message: str,
        model_id: Optional[str] = None,
        details: Optional[dict] = None
    ):
        super().__init__(message, details)
        self.model_id = model_id


class ModelNotFoundError(ModelError):
    """Raised when a model is not found in the registry."""

    def __init__(self, model_id: str, details: Optional[dict] = None):
        super().__init__(
            f"Model not found in registry: {model_id}",
            model_id=model_id,
            details=details
        )


class ModelMissingError(ModelError):
    """Raised when a model file is missing from disk."""

    def __init__(
        self,
        model_id: str,
        expected_path: str,
        details: Optional[dict] = None
    ):
        super().__init__(
            f"Model file missing: {expected_path}",
            model_id=model_id,
            details=details
        )
        self.expected_path = expected_path


class ModelHashMismatchError(ModelError):
    """Raised when a model file's hash does not match the expected hash."""

    def __init__(
        self,
        model_id: str,
        expected_hash: str,
        actual_hash: str,
        details: Optional[dict] = None
    ):
        super().__init__(
            f"Model hash mismatch for {model_id}: expected {expected_hash[:16]}..., got {actual_hash[:16]}...",
            model_id=model_id,
            details=details
        )
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


class ModelNotVerifiedError(ModelError):
    """Raised when a model cannot be verified (no expected hash available)."""

    def __init__(
        self,
        model_id: str,
        reason: str,
        details: Optional[dict] = None
    ):
        super().__init__(
            f"Model cannot be verified: {reason}",
            model_id=model_id,
            details=details
        )
        self.reason = reason