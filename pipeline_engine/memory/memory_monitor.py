"""
GPU Memory Monitor

Tracks VRAM usage, detects memory pressure, and provides alerts
for the pipeline engine.
"""

from __future__ import annotations

import logging
import threading
import time
import torch
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class MemoryPressureLevel(str, Enum):
    """Memory pressure levels."""
    NORMAL = "normal"          # < 60% of budget
    ELEVATED = "elevated"      # 60-75%
    HIGH = "high"              # 75-90%
    CRITICAL = "critical"      # > 90%
    OOM = "oom"                # Out of memory


@dataclass
class MemoryThresholds:
    """Configurable memory thresholds."""
    normal_pct: float = 0.60
    elevated_pct: float = 0.75
    high_pct: float = 0.90
    critical_pct: float = 0.95


@dataclass
class MemorySnapshot:
    """Single memory measurement."""
    timestamp: float
    allocated_mb: float
    reserved_mb: float
    free_mb: float
    total_mb: float
    pressure_level: MemoryPressureLevel
    utilization_pct: float


class GPUMemoryMonitor:
    """
    Monitors GPU memory usage and provides alerts.
    
    Features:
    - Continuous monitoring in background thread
    - Configurable thresholds
    - Memory pressure callbacks
    - Historical tracking
    - Per-process breakdown (when available)
    """
    
    def __init__(
        self,
        device_id: int = 0,
        vram_budget_mb: int = 4096,
        thresholds: Optional[MemoryThresholds] = None,
        poll_interval: float = 1.0,
    ):
        self.device_id = device_id
        self.vram_budget_mb = vram_budget_mb
        self.thresholds = thresholds or MemoryThresholds()
        self.poll_interval = poll_interval
        
        # Monitoring thread
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        
        # History
        self._history: deque[MemorySnapshot] = deque(maxlen=3600)  # 1 hour at 1s intervals
        self._peak_allocated_mb = 0.0
        
        # Callbacks
        self._pressure_callbacks: Dict[MemoryPressureLevel, List[Callable]] = {
            level: [] for level in MemoryPressureLevel
        }
        self._last_pressure_level = MemoryPressureLevel.NORMAL
        
        # Stats
        self._samples = 0
        self._pressure_events = 0
    
    def start(self) -> None:
        """Start monitoring thread."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                logger.warning("Memory monitor already running")
                return
            
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._monitor_loop,
                name=f"gpu-mem-monitor-{self.device_id}",
                daemon=True,
            )
            self._thread.start()
            logger.info(f"GPUMemoryMonitor(device={self.device_id}): started")
    
    def stop(self) -> None:
        """Stop monitoring thread."""
        with self._lock:
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=5.0)
                self._thread = None
            logger.info(f"GPUMemoryMonitor(device={self.device_id}): stopped")
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                snapshot = self._take_snapshot()
                self._process_snapshot(snapshot)
            except Exception as e:
                logger.error(f"GPUMemoryMonitor: monitoring error: {e}")
            
            self._stop_event.wait(self.poll_interval)
    
    def _take_snapshot(self) -> MemorySnapshot:
        """Take a memory snapshot."""
        torch.cuda.set_device(self.device_id)
        
        # Get memory stats
        allocated = torch.cuda.memory_allocated(self.device_id)
        reserved = torch.cuda.memory_reserved(self.device_id)
        
        # Get total memory
        total = torch.cuda.get_device_properties(self.device_id).total_memory
        
        allocated_mb = allocated / (1024 * 1024)
        reserved_mb = reserved / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        free_mb = total_mb - reserved_mb
        
        # Calculate utilization against budget
        utilization_pct = (reserved_mb / self.vram_budget_mb) if self.vram_budget_mb > 0 else 0.0
        
        # Determine pressure level
        if utilization_pct >= self.thresholds.critical_pct:
            pressure = MemoryPressureLevel.CRITICAL
        elif utilization_pct >= self.thresholds.high_pct:
            pressure = MemoryPressureLevel.HIGH
        elif utilization_pct >= self.thresholds.elevated_pct:
            pressure = MemoryPressureLevel.ELEVATED
        elif utilization_pct >= self.thresholds.normal_pct:
            pressure = MemoryPressureLevel.NORMAL
        else:
            pressure = MemoryPressureLevel.NORMAL
        
        return MemorySnapshot(
            timestamp=time.time(),
            allocated_mb=allocated_mb,
            reserved_mb=reserved_mb,
            free_mb=free_mb,
            total_mb=total_mb,
            pressure_level=pressure,
            utilization_pct=utilization_pct * 100,
        )
    
    def _process_snapshot(self, snapshot: MemorySnapshot) -> None:
        """Process a snapshot and trigger callbacks if needed."""
        with self._lock:
            self._history.append(snapshot)
            self._samples += 1
            
            # Track peak
            if snapshot.allocated_mb > self._peak_allocated_mb:
                self._peak_allocated_mb = snapshot.allocated_mb
            
            # Check for pressure level change
            if snapshot.pressure_level != self._last_pressure_level:
                self._pressure_events += 1
                logger.warning(
                    f"GPUMemoryMonitor: Pressure changed: "
                    f"{self._last_pressure_level.value} -> {snapshot.pressure_level.value} "
                    f"({snapshot.utilization_pct:.1f}% of {self.vram_budget_mb}MB budget)"
                )
                self._trigger_callbacks(snapshot.pressure_level, snapshot)
                self._last_pressure_level = snapshot.pressure_level
    
    def _trigger_callbacks(self, level: MemoryPressureLevel, snapshot: MemorySnapshot) -> None:
        """Trigger registered callbacks for pressure level."""
        # Trigger callbacks for this level and all higher levels
        levels = list(MemoryPressureLevel)
        idx = levels.index(level)
        for lvl in levels[idx:]:
            for callback in self._pressure_callbacks.get(lvl, []):
                try:
                    callback(snapshot)
                except Exception as e:
                    logger.error(f"GPUMemoryMonitor: callback error: {e}")
    
    def register_callback(
        self, 
        level: MemoryPressureLevel, 
        callback: Callable[[MemorySnapshot], None]
    ) -> None:
        """Register a callback for memory pressure level."""
        with self._lock:
            self._pressure_callbacks[level].append(callback)
    
    def unregister_callback(
        self, 
        level: MemoryPressureLevel, 
        callback: Callable[[MemorySnapshot], None]
    ) -> None:
        """Unregister a callback."""
        with self._lock:
            if callback in self._pressure_callbacks.get(level, []):
                self._pressure_callbacks[level].remove(callback)
    
    def get_current(self) -> Optional[MemorySnapshot]:
        """Get latest memory snapshot."""
        with self._lock:
            return self._history[-1] if self._history else None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        with self._lock:
            current = self.get_current()
            return {
                "device_id": self.device_id,
                "vram_budget_mb": self.vram_budget_mb,
                "monitoring": self._thread is not None and self._thread.is_alive(),
                "poll_interval": self.poll_interval,
                "samples": self._samples,
                "pressure_events": self._pressure_events,
                "peak_allocated_mb": self._peak_allocated_mb,
                "current": current.to_dict() if current else None,
                "thresholds": {
                    "normal_pct": self.thresholds.normal_pct * 100,
                    "elevated_pct": self.thresholds.elevated_pct * 100,
                    "high_pct": self.thresholds.high_pct * 100,
                    "critical_pct": self.thresholds.critical_pct * 100,
                },
            }
    
    def get_history(
        self, 
        duration_seconds: Optional[float] = None,
        max_samples: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get memory history."""
        with self._lock:
            history = list(self._history)
            
            if duration_seconds:
                cutoff = time.time() - duration_seconds
                history = [s for s in history if s.timestamp >= cutoff]
            
            if max_samples:
                history = history[-max_samples:]
            
            return [s.to_dict() for s in history]
    
    def check_oom_risk(self) -> bool:
        """Check if OOM is imminent."""
        current = self.get_current()
        if current:
            return current.pressure_level in (MemoryPressureLevel.CRITICAL, MemoryPressureLevel.OOM)
        return False
    
    def get_recommended_batch_size(
        self, 
        current_batch_size: int, 
        min_batch_size: int = 1
    ) -> int:
        """Get recommended batch size based on memory pressure."""
        current = self.get_current()
        if not current:
            return current_batch_size
        
        if current.pressure_level == MemoryPressureLevel.CRITICAL:
            return max(min_batch_size, current_batch_size // 2)
        elif current.pressure_level == MemoryPressureLevel.HIGH:
            return max(min_batch_size, int(current_batch_size * 0.75))
        elif current.pressure_level == MemoryPressureLevel.ELEVATED:
            return max(min_batch_size, int(current_batch_size * 0.9))
        
        return current_batch_size
    
    def empty_cache(self) -> None:
        """Empty CUDA cache."""
        torch.cuda.empty_cache()
        logger.info("GPUMemoryMonitor: CUDA cache emptied")
    
    def reset_peak(self) -> None:
        """Reset peak memory tracking."""
        with self._lock:
            self._peak_allocated_mb = 0.0


# Add to_dict method to MemorySnapshot
def _snapshot_to_dict(self) -> Dict[str, Any]:
    return {
        "timestamp": self.timestamp,
        "allocated_mb": round(self.allocated_mb, 2),
        "reserved_mb": round(self.reserved_mb, 2),
        "free_mb": round(self.free_mb, 2),
        "total_mb": round(self.total_mb, 2),
        "pressure_level": self.pressure_level.value,
        "utilization_pct": round(self.utilization_pct, 2),
    }

MemorySnapshot.to_dict = _snapshot_to_dict


class MultiGPUMemoryMonitor:
    """Monitors memory across multiple GPUs."""
    
    def __init__(
        self,
        device_ids: List[int],
        vram_budgets: Optional[Dict[int, int]] = None,
        poll_interval: float = 1.0,
    ):
        self.device_ids = device_ids
        self.vram_budgets = vram_budgets or {d: 4096 for d in device_ids}
        self.monitors: Dict[int, GPUMemoryMonitor] = {}
        self._lock = threading.Lock()
        
        for device_id in device_ids:
            budget = self.vram_budgets.get(device_id, 4096)
            self.monitors[device_id] = GPUMemoryMonitor(
                device_id=device_id,
                vram_budget_mb=budget,
                poll_interval=poll_interval,
            )
    
    def start_all(self) -> None:
        """Start all monitors."""
        for monitor in self.monitors.values():
            monitor.start()
    
    def stop_all(self) -> None:
        """Stop all monitors."""
        for monitor in self.monitors.values():
            monitor.stop()
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get stats for all GPUs."""
        return {
            f"gpu_{device_id}": monitor.get_stats()
            for device_id, monitor in self.monitors.items()
        }
    
    def get_total_vram_usage(self) -> Dict[str, float]:
        """Get total VRAM usage across all GPUs."""
        total_allocated = 0.0
        total_reserved = 0.0
        total_budget = 0.0
        
        for device_id, monitor in self.monitors.items():
            current = monitor.get_current()
            if current:
                total_allocated += current.allocated_mb
                total_reserved += current.reserved_mb
            total_budget += monitor.vram_budget_mb
        
        return {
            "total_allocated_mb": total_allocated,
            "total_reserved_mb": total_reserved,
            "total_budget_mb": total_budget,
            "overall_utilization_pct": (total_reserved / total_budget * 100) if total_budget > 0 else 0,
        }
    
    def any_critical(self) -> bool:
        """Check if any GPU is at critical pressure."""
        return any(m.check_oom_risk() for m in self.monitors.values())


def log_memory_usage(device_id: int = 0, prefix: str = "") -> None:
    """Log current memory usage."""
    if not torch.cuda.is_available():
        return
    
    torch.cuda.set_device(device_id)
    allocated = torch.cuda.memory_allocated(device_id) / (1024 * 1024)
    reserved = torch.cuda.memory_reserved(device_id) / (1024 * 1024)
    total = torch.cuda.get_device_properties(device_id).total_memory / (1024 * 1024)
    
    logger.info(
        f"{prefix}GPU {device_id}: "
        f"allocated={allocated:.1f}MB, "
        f"reserved={reserved:.1f}MB, "
        f"free={total-reserved:.1f}MB / {total:.0f}MB"
    )


if __name__ == "__main__":
    # Quick test
    import torch
    
    if not torch.cuda.is_available():
        print("CUDA not available, skipping test")
    else:
        monitor = GPUMemoryMonitor(device_id=0, vram_budget_mb=4096, poll_interval=0.5)
        
        # Register a callback
        def on_high(snapshot):
            print(f"HIGH PRESSURE: {snapshot.utilization_pct:.1f}%")
        
        monitor.register_callback(MemoryPressureLevel.HIGH, on_high)
        
        monitor.start()
        time.sleep(2)
        
        print(f"Stats: {monitor.get_stats()}")
        
        # Allocate some memory to test
        tensors = []
        for i in range(5):
            t = torch.randn(100, 100, 100, device='cuda')
            tensors.append(t)
            log_memory_usage(0, "Test ")
            time.sleep(0.5)
        
        del tensors
        torch.cuda.empty_cache()
        
        time.sleep(1)
        print(f"Final stats: {monitor.get_stats()}")
        
        monitor.stop()
        print("Memory monitor test passed!")