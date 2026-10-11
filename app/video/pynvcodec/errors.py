# PyNvVideoCodec adapter error contract (2.2.3)

from __future__ import annotations


class AdapterBaseError(Exception):
    """Base exception for PyNvVideoCodec adapter errors."""
    pass


class InitializationError(AdapterBaseError):
    """Raised when decoder/encoder initialization fails."""
    pass


class CapabilityError(AdapterBaseError):
    """Raised when hardware capability check fails."""
    pass


class StreamError(AdapterBaseError):
    """Raised when stream operation fails."""
    pass


class DecodeError(AdapterBaseError):
    """Raised when decode operation fails."""
    pass


class SurfaceError(AdapterBaseError):
    """Raised when surface allocation/management fails."""
    pass


class DLPackError(AdapterBaseError):
    """Raised when DLPack interop fails."""
    pass


class CUDAStreamError(AdapterBaseError):
    """Raised when CUDA stream operations fail."""
    pass


class EncodeError(AdapterBaseError):
    """Raised when encode operation fails."""
    pass


class TimestampError(AdapterBaseError):
    """Raised when timestamp handling fails."""
    pass


class MuxError(AdapterBaseError):
    """Raised when mux operations fail."""
    pass


class RecoveryError(AdapterBaseError):
    """Raised when recovery operation fails."""
    pass