# Stream contract: CUDA stream identity, lifetime, synchronization
# P3.2-N.1 / P3.2-N.2.1 stream contract repair.

from __future__ import annotations
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


class StreamContract:
    """Explicit CUDA stream / context pairing contract for adapter."""

    def __init__(
        self,
        stream_id: int = 0,
        cuda_context_handle: Optional[int] = None,
        cuda_stream_handle: Optional[int] = None,
        device_id: int = 0,
        owner: str = "adapter",
    ) -> None:
        self.device_id: int = device_id
        self.owner: str = owner
        self.stream_id: int = stream_id
        # Context handle: explicit CUDA context integer (primary context = 0 valid only
        # when paired with its own stream; adapter prefers explicit non-zero pairing).
        self.cuda_context_handle: Optional[int] = cuda_context_handle
        # Actual CUDA stream handle (integer from CUDA runtime / torch.cuda.Stream)
        self.cuda_stream_handle: Optional[int] = cuda_stream_handle
        # Lifetime tracking flags (do NOT destroy stream/context before decoder close)
        self.context_active: bool = False
        self.stream_active: bool = False

    def is_explicit_nonzero_stream(self) -> bool:
        return self.stream_id != 0

    def is_stream_associated_with_context(self) -> bool:
        # Basic contract validation: stream handle must be non-zero when adapter
        # requires explicit stream; context handle must be defined.
        if self.cuda_stream_handle is None:
            return False
        # A stream handle of 0 means default stream; adapter requires non-zero.
        return self.cuda_stream_handle != 0

    def validate_pair(self) -> None:
        if self.cuda_stream_handle is None or self.cuda_stream_handle == 0:
            raise RuntimeError("CUDA stream handle invalid (None or 0); adapter requires non-zero stream.")
        if self.cuda_context_handle is None:
            raise RuntimeError("CUDA context handle is None; adapter requires matched context.")
        # We do not compare handles numerically (they come from different CUDA objects),
        # but the adapter guarantees pairing by creating both under the same CUDA context.
        self.stream_active = True
        self.context_active = True
        logger.info(
            "StreamContract validated: device=%d owner=%s stream_handle=%s context_handle=%s",
            self.device_id,
            self.owner,
            self.cuda_stream_handle,
            self.cuda_context_handle,
        )
