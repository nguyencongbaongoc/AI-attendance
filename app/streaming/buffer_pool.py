"""
Phase R3.14-H.8.4 — Per-Camera Annotation Buffer Pool.

This module owns one reusable (H, W, 3) BGR ndarray per camera_id so that
the annotation renderer can draw in place instead of allocating a fresh
BGR canvas on every frame.

Design contract (from H.7 §6.3, §6.6, §11.4):

  * Per-camera ownership. cam1 buffers are NEVER shared with cam2.
  * Pre-allocated, lazily resized. A buffer is allocated on first use for
    a camera/resolution. If a new frame arrives with a different shape
    (resolution change), the buffer is reallocated to match.
  * Thread safety. Each camera's pipeline runs in its own ingestion
    thread. A single ``threading.Lock`` per camera buffer is acquired
    twice per frame for sub-second windows; cost is negligible.
  * No aliasing back to the caller. ``get_buffer()`` returns a
    *pre-allocated canvas*; the caller is expected to draw on it, then
    copy it into a fresh ndarray (``np.empty_like(canvas).copy()`` or
    equivalent) before returning it to any consumer that may hold the
    reference across frames (e.g. the FFmpeg pipeline).

H.7 §6.5 invariants preserved by the pool:
  - Original ``frame_data`` is NEVER mutated.
  - All annotation geometry (bbox clamp, font scale, line thickness) is
    computed from the frame shape and applied to the buffer.
  - Track IDs, crossing line, region fill, resolution-change handling
    are unchanged.
  - Camera isolation is preserved (one pool entry per camera_id).
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class _CameraBuffers:
    """Per-camera reusable buffers.

    Attributes:
        canvas: BGR (H, W, 3) uint8 ndarray used as the working canvas.
        lock:   threading.Lock guarding allocation/resize.
    """

    __slots__ = ("canvas", "lock", "shape")

    def __init__(self, shape: Tuple[int, int, int]):
        h, w = shape[0], shape[1]
        self.canvas: np.ndarray = np.empty((h, w, 3), dtype=np.uint8)
        self.lock: threading.Lock = threading.Lock()
        self.shape: Tuple[int, int, int] = shape

    def ensure_shape(self, shape: Tuple[int, int, int]) -> None:
        """Reallocate the canvas if the requested shape differs."""
        if shape == self.shape:
            return
        h, w = shape[0], shape[1]
        self.canvas = np.empty((h, w, 3), dtype=np.uint8)
        self.shape = shape


class CameraBufferPool:
    """Per-process pool of reusable per-camera annotation buffers.

    Usage::

        pool = get_camera_buffer_pool()
        cam1 = pool.get_buffer("CAM1", (1080, 1920, 3))
        # draw on cam1 in place ...
        result = np.empty_like(cam1)
        np.copyto(result, cam1)
        # result is the safe-to-hold ndarray; cam1 may be mutated next
        # frame.

    The pool itself does NOT own the per-frame ``result`` ndarray; the
    caller (annotation_renderer / annotated_publisher) is responsible
    for producing a fresh ndarray from the canvas before handing it
    downstream.
    """

    def __init__(self) -> None:
        self._buffers: Dict[str, _CameraBuffers] = {}
        self._global_lock = threading.Lock()

    def get_buffer(
        self, camera_id: str, shape: Tuple[int, int, int]
    ) -> np.ndarray:
        """Return the canvas ndarray for ``camera_id``, allocating if
        needed and resizing on shape change.

        The caller MUST treat the returned ndarray as a borrowed
        reference: do not retain it across frames.
        """
        if len(shape) != 3 or shape[2] != 3:
            raise ValueError(
                f"CameraBufferPool requires (H, W, 3) shape, got {shape}"
            )
        # Fast path: camera known and shape matches.
        bufs = self._buffers.get(camera_id)
        if bufs is not None:
            with bufs.lock:
                if bufs.shape == shape:
                    return bufs.canvas
                bufs.ensure_shape(shape)
                return bufs.canvas
        # Slow path: allocate a new per-camera buffer.
        with self._global_lock:
            bufs = self._buffers.get(camera_id)
            if bufs is None:
                bufs = _CameraBuffers(shape)
                self._buffers[camera_id] = bufs
                logger.info(
                    "CameraBufferPool: allocated buffer for %s shape=%s",
                    camera_id, shape,
                )
            else:
                with bufs.lock:
                    bufs.ensure_shape(shape)
            with bufs.lock:
                return bufs.canvas

    def reset_camera(self, camera_id: str) -> None:
        """Release the per-camera buffer (e.g. on pipeline stop)."""
        with self._global_lock:
            bufs = self._buffers.pop(camera_id, None)
        if bufs is not None:
            with bufs.lock:
                bufs.canvas = None  # type: ignore[assignment]

    def reset_all(self) -> None:
        """Release all per-camera buffers."""
        with self._global_lock:
            cams = list(self._buffers.keys())
            self._buffers.clear()
        for cam_id in cams:
            logger.info("CameraBufferPool: released buffer for %s", cam_id)

    def stats(self) -> Dict[str, Tuple[int, int, int]]:
        """Return {camera_id: shape} for diagnostics."""
        with self._global_lock:
            return {
                cam_id: bufs.shape
                for cam_id, bufs in self._buffers.items()
            }


# Process-singleton pool.
_POOL: Optional[CameraBufferPool] = None
_POOL_LOCK = threading.Lock()


def get_camera_buffer_pool() -> CameraBufferPool:
    """Return the process-singleton CameraBufferPool."""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = CameraBufferPool()
    return _POOL


def reset_camera_buffer_pool() -> None:
    """Drop the process-singleton (used in tests)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.reset_all()
        _POOL = None
