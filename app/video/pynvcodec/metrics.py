# Metrics adapter (observable — real values only)

from __future__ import annotations
from typing import Dict, Any
from collections import deque


class AdapterMetrics:
    def __init__(self) -> None:
        self.decode_fps: float = 0.0
        self.encode_fps: float = 0.0
        self.input_fps: float = 0.0
        self.dropped_frames: int = 0
        self.decode_latency_ms: float = 0.0
        self.encode_latency_ms: float = 0.0
        self.queue_depth: int = 0
        self.vram_usage_mb: float = 0.0
        self.gpu_memory_alloc_mb: float = 0.0
        self.cuda_stream_id: int = 0
        self.decode_backend: str = "legacy"
        self.encode_backend: str = "legacy"
        self.pixel_format: str = ""
        self.resolution_str: str = ""
        self.fallback_count: int = 0
        self.reconnect_count: int = 0
        self.last_error: str = ""
        self.decode_calls: int = 0
        self.decode_errors: int = 0
        self.packets_submitted: int = 0
        self.decoded_frames: int = 0
        self.frame_shape_str: str = ""

    def record_fallback(self, reason: str) -> None:
        self.fallback_count += 1
        self.last_error = reason

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()
