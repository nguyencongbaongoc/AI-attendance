"""
GPU Synchronization Primitives

Provides explicit synchronization between pipeline stages to ensure
correct GPU memory access ordering and prevent race conditions.
"""

from __future__ import annotations

import threading
import time
import torch
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
from contextlib import contextmanager
from collections import defaultdict


class SyncPrimitive(str, Enum):
    """Types of synchronization primitives."""
    CUDA_STREAM = "cuda_stream"
    CUDA_EVENT = "cuda_event"
    THREAD_EVENT = "thread_event"
    BARRIER = "barrier"


@dataclass
class SyncPoint:
    """A synchronization point in the pipeline."""
    name: str
    stage: str
    # For CUDA synchronization
    cuda_event: Optional[torch.cuda.Event] = None
    # For thread synchronization
    thread_event: Optional[threading.Event] = None
    # Callback when sync point is reached
    callback: Optional[Callable[[], None]] = None
    
    def __post_init__(self):
        if self.cuda_event is None:
            self.cuda_event = torch.cuda.Event(enable_timing=True)
        if self.thread_event is None:
            self.thread_event = threading.Event()


class CUDASyncManager:
    """
    Manages CUDA stream and event synchronization across pipeline stages.
    
    Each camera gets its own CUDA stream to enable parallel processing.
    Events are used to synchronize between stages on the same stream
    or across streams.
    """
    
    def __init__(self, device_id: int = 0, num_streams: int = 4):
        self.device_id = device_id
        torch.cuda.set_device(device_id)
        
        # Create streams for different pipeline stages
        self._streams: Dict[str, torch.cuda.Stream] = {}
        self._default_stream = torch.cuda.current_stream(device_id)
        
        # Pre-create common streams
        stream_names = ["decode", "preprocess", "inference", "tracking", "annotation", "encode"]
        for name in stream_names:
            self._streams[name] = torch.cuda.Stream(device=device_id)
        
        # Events for synchronization
        self._events: Dict[str, torch.cuda.Event] = {}
        self._event_lock = threading.Lock()
        
        # Timing records
        self._timings: Dict[str, List[float]] = defaultdict(list)
    
    def get_stream(self, name: str) -> torch.cuda.Stream:
        """Get a named CUDA stream."""
        if name not in self._streams:
            self._streams[name] = torch.cuda.Stream(device=self.device_id)
        return self._streams[name]
    
    def get_default_stream(self) -> torch.cuda.Stream:
        """Get the default CUDA stream."""
        return self._default_stream
    
    def record_event(self, event_name: str, stream: Optional[torch.cuda.Stream] = None) -> torch.cuda.Event:
        """Record a CUDA event on a stream."""
        with self._event_lock:
            if event_name not in self._events:
                self._events[event_name] = torch.cuda.Event(enable_timing=True)
            event = self._events[event_name]
        
        target_stream = stream or self._default_stream
        event.record(target_stream)
        return event
    
    def wait_event(self, event_name: str, stream: Optional[torch.cuda.Stream] = None) -> None:
        """Wait for a CUDA event on a stream."""
        with self._event_lock:
            if event_name not in self._events:
                raise ValueError(f"Event {event_name} not recorded")
            event = self._events[event_name]
        
        target_stream = stream or self._default_stream
        target_stream.wait_event(event)
    
    def synchronize_stream(self, stream: torch.cuda.Stream) -> None:
        """Synchronize a CUDA stream."""
        stream.synchronize()
    
    def synchronize_device(self) -> None:
        """Synchronize the entire device."""
        torch.cuda.synchronize(self.device_id)
    
    def measure_interval(
        self, 
        start_event: str, 
        end_event: str, 
        stream: Optional[torch.cuda.Stream] = None
    ) -> float:
        """Measure time between two events in milliseconds."""
        with self._event_lock:
            if start_event not in self._events or end_event not in self._events:
                raise ValueError("Both events must be recorded")
            start = self._events[start_event]
            end = self._events[end_event]
        
        # Ensure end event is complete
        if stream:
            stream.wait_event(end)
        else:
            end.synchronize()
        
        elapsed = start.elapsed_time(end)
        self._timings[f"{start_event}->{end_event}"].append(elapsed)
        return elapsed
    
    def get_timing_stats(self, interval_name: str) -> Dict[str, float]:
        """Get timing statistics for an interval."""
        timings = self._timings.get(interval_name, [])
        if not timings:
            return {}
        
        import numpy as np
        return {
            "count": len(timings),
            "mean_ms": float(np.mean(timings)),
            "min_ms": float(np.min(timings)),
            "max_ms": float(np.max(timings)),
            "p50_ms": float(np.percentile(timings, 50)),
            "p95_ms": float(np.percentile(timings, 95)),
            "p99_ms": float(np.percentile(timings, 99)),
        }
    
    def clear_timings(self) -> None:
        """Clear all timing records."""
        self._timings.clear()


class PipelineBarrier:
    """
    Barrier for synchronizing multiple pipeline stages.
    
    Allows stages to wait for each other at specific points.
    Useful for ensuring frame ordering or coordinating multi-camera processing.
    """
    
    def __init__(self, parties: int, timeout: float = 30.0):
        self.parties = parties
        self.timeout = timeout
        self._count = 0
        self._generation = 0
        self._lock = threading.Condition(threading.Lock())
        self._broken = False
    
    def wait(self) -> bool:
        """
        Wait for all parties to reach the barrier.
        
        Returns:
            True if barrier passed, False if timeout or broken
        """
        with self._lock:
            if self._broken:
                return False
            
            my_generation = self._generation
            self._count += 1
            
            try:
                if self._count == self.parties:
                    # Last party - release all
                    self._generation += 1
                    self._count = 0
                    self._lock.notify_all()
                    return True
                else:
                    # Wait for others
                    end_time = time.time() + self.timeout
                    while my_generation == self._generation and not self._broken:
                        remaining = end_time - time.time()
                        if remaining <= 0:
                            self._broken = True
                            self._lock.notify_all()
                            return False
                        self._lock.wait(remaining)
                    
                    if self._broken:
                        return False
                    return True
            except Exception:
                self._count -= 1
                self._lock.notify_all()
                raise
    
    def reset(self) -> None:
        """Reset the barrier."""
        with self._lock:
            self._count = 0
            self._generation += 1
            self._broken = False
    
    def break_barrier(self) -> None:
        """Break the barrier, releasing all waiting threads."""
        with self._lock:
            self._broken = True
            self._lock.notify_all()


class StageSynchronizer:
    """
    Synchronizes a linear pipeline of stages for a single frame.
    
    Each stage signals completion, next stage waits for previous.
    Uses CUDA events for GPU synchronization, thread events for CPU coordination.
    """
    
    def __init__(self, stage_names: List[str], cuda_sync: Optional[CUDASyncManager] = None):
        self.stage_names = stage_names
        self.cuda_sync = cuda_sync
        
        # Thread synchronization
        self._stage_events: Dict[str, threading.Event] = {
            name: threading.Event() for name in stage_names
        }
        self._stage_complete: Dict[str, bool] = {name: False for name in stage_names}
        self._lock = threading.Lock()
        
        # CUDA synchronization
        self._cuda_events: Dict[str, torch.cuda.Event] = {}
        if cuda_sync:
            for name in stage_names:
                self._cuda_events[name] = torch.cuda.Event(enable_timing=True)
        
        # Frame tracking
        self._current_frame_id: Optional[int] = None
    
    def start_frame(self, frame_id: int) -> None:
        """Mark start of a new frame."""
        with self._lock:
            self._current_frame_id = frame_id
            for name in self._stage_names:
                self._stage_events[name].clear()
                self._stage_complete[name] = False
    
    def complete_stage(self, stage_name: str, cuda_stream: Optional[torch.cuda.Stream] = None) -> None:
        """Mark a stage as complete for current frame."""
        if stage_name not in self._stage_names:
            raise ValueError(f"Unknown stage: {stage_name}")
        
        with self._lock:
            if self._stage_complete[stage_name]:
                return  # Already complete
            
            self._stage_complete[stage_name] = True
            self._stage_events[stage_name].set()
        
        # Record CUDA event if available
        if self.cuda_sync and cuda_stream:
            self.cuda_sync.record_event(f"{self._current_frame_id}:{stage_name}", cuda_stream)
    
    def wait_for_stage(self, stage_name: str, timeout: Optional[float] = None) -> bool:
        """Wait for a stage to complete."""
        if stage_name not in self._stage_names:
            raise ValueError(f"Unknown stage: {stage_name}")
        
        event = self._stage_events[stage_name]
        return event.wait(timeout) if timeout else event.wait()
    
    def wait_for_previous(self, current_stage: str, timeout: Optional[float] = None) -> bool:
        """Wait for the previous stage in pipeline order."""
        idx = self.stage_names.index(current_stage)
        if idx == 0:
            return True  # First stage, no previous
        prev_stage = self.stage_names[idx - 1]
        return self.wait_for_stage(prev_stage, timeout)
    
    def cuda_wait_previous(self, current_stage: str, stream: torch.cuda.Stream) -> None:
        """Wait for previous stage using CUDA event."""
        idx = self.stage_names.index(current_stage)
        if idx == 0:
            return
        prev_stage = self.stage_names[idx - 1]
        event_name = f"{self._current_frame_id}:{prev_stage}"
        self.cuda_sync.wait_event(event_name, stream)
    
    def get_status(self) -> Dict[str, Any]:
        """Get synchronization status."""
        with self._lock:
            return {
                "frame_id": self._current_frame_id,
                "stages": {
                    name: self._stage_complete[name] 
                    for name in self.stage_names
                },
            }


class MultiCameraSync:
    """
    Synchronization across multiple cameras.
    
    Ensures coordinated processing when needed (e.g., multi-camera tracking).
    """
    
    def __init__(self, camera_ids: List[str], cuda_sync: Optional[CUDASyncManager] = None):
        self.camera_ids = camera_ids
        self.cuda_sync = cuda_sync
        
        # Per-camera stage synchronizers
        self._syncs: Dict[str, StageSynchronizer] = {}
        
        # Cross-camera barriers
        self._frame_barriers: Dict[int, PipelineBarrier] = {}
        self._barrier_lock = threading.Lock()
    
    def get_sync(self, camera_id: str, stage_names: List[str]) -> StageSynchronizer:
        """Get or create synchronizer for a camera."""
        if camera_id not in self._syncs:
            self._syncs[camera_id] = StageSynchronizer(stage_names, self.cuda_sync)
        return self._syncs[camera_id]
    
    def create_frame_barrier(self, frame_id: int) -> PipelineBarrier:
        """Create a barrier for synchronizing all cameras at a frame."""
        with self._barrier_lock:
            barrier = PipelineBarrier(len(self.camera_ids))
            self._frame_barriers[frame_id] = barrier
            return barrier
    
    def wait_frame_barrier(self, frame_id: int, timeout: float = 30.0) -> bool:
        """Wait for all cameras to reach frame barrier."""
        with self._barrier_lock:
            barrier = self._frame_barriers.get(frame_id)
            if not barrier:
                return True  # No barrier created
            return barrier.wait()
    
    def cleanup_frame(self, frame_id: int) -> None:
        """Clean up synchronization objects for a frame."""
        with self._barrier_lock:
            if frame_id in self._frame_barriers:
                del self._frame_barriers[frame_id]


@contextmanager
def cuda_stream_context(stream: torch.cuda.Stream):
    """Context manager for CUDA stream."""
    previous = torch.cuda.current_stream()
    torch.cuda.set_stream(stream)
    try:
        yield stream
    finally:
        torch.cuda.set_stream(previous)


@contextmanager
def cuda_device_context(device_id: int):
    """Context manager for CUDA device."""
    previous = torch.cuda.current_device()
    torch.cuda.set_device(device_id)
    try:
        yield
    finally:
        torch.cuda.set_device(previous)


def synchronize_streams(streams: List[torch.cuda.Stream]) -> None:
    """Synchronize multiple CUDA streams."""
    for stream in streams:
        stream.synchronize()


def create_timed_section(name: str, stream: Optional[torch.cuda.Stream] = None):
    """Create a timed section using CUDA events."""
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)
    
    target_stream = stream or torch.cuda.current_stream()
    start_event.record(target_stream)
    
    class TimedSection:
        def __enter__(self):
            return self
        
        def __exit__(self, *args):
            end_event.record(target_stream)
            end_event.synchronize()
            elapsed = start_event.elapsed_time(end_event)
            print(f"[{name}] {elapsed:.2f} ms")
    
    return TimedSection()


if __name__ == "__main__":
    # Quick test
    import torch
    
    if not torch.cuda.is_available():
        print("CUDA not available, skipping test")
    else:
        sync = CUDASyncManager(device_id=0)
        
        # Test stream access
        decode_stream = sync.get_stream("decode")
        inference_stream = sync.get_stream("inference")
        print(f"Decode stream: {decode_stream}")
        print(f"Inference stream: {inference_stream}")
        
        # Test event recording
        event = sync.record_event("test_start", decode_stream)
        event2 = sync.record_event("test_end", decode_stream)
        
        # Test timing
        decode_stream.synchronize()
        elapsed = sync.measure_interval("test_start", "test_end")
        print(f"Interval: {elapsed:.2f} ms")
        
        # Test barrier
        barrier = PipelineBarrier(3)
        
        def worker(worker_id):
            print(f"Worker {worker_id} waiting...")
            result = barrier.wait()
            print(f"Worker {worker_id} released: {result}")
        
        import threading
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        print("Synchronization test passed!")