"""
Phase 3.1 - GPU Memory / VRAM Safety

Supports:
- Explicit device selection
- Memory reporting
- Safe cleanup
- Avoiding duplicate model residency
- Avoiding accidental model recreation
- Clear ownership/lifetime

Target hardware: NVIDIA GTX 1660 Ti (~6 GB VRAM)
Does NOT reserve entire GPU or create permanent allocations.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class VRAMSnapshot:
    """Single VRAM measurement snapshot."""
    timestamp: float
    allocated_mb: float
    reserved_mb: float
    total_mb: float
    free_mb: float
    utilization_pct: float
    peak_allocated_mb: float = 0.0


@dataclass
class VRAMBudget:
    """VRAM budget configuration."""
    device_index: int = 0
    total_vram_mb: float = 6000.0  # GTX 1660 Ti ~6GB
    safety_margin_mb: float = 500.0  # Keep 500MB free
    max_utilization_pct: float = 85.0  # Alert threshold
    warning_utilization_pct: float = 75.0  # Warning threshold
    
    @property
    def max_allocated_mb(self) -> float:
        return self.total_vram_mb * (self.max_utilization_pct / 100.0)
    
    @property
    def warning_allocated_mb(self) -> float:
        return self.total_vram_mb * (self.warning_utilization_pct / 100.0)


class VRAMMonitor:
    """
    Continuous VRAM monitoring with alerting and budget enforcement.
    """
    
    def __init__(self, budget: Optional[VRAMBudget] = None):
        self.budget = budget or VRAMBudget()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._snapshots: List[VRAMSnapshot] = []
        self._max_snapshots = 1000  # Keep last 1000 snapshots
        self._peak_allocated_mb = 0.0
        self._callbacks: List[callable] = []
        self._alert_fired = False
        self._warning_fired = False
    
    def start(self, interval_seconds: float = 1.0) -> None:
        """Start monitoring VRAM."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                args=(interval_seconds,),
                name="VRAMMonitor",
                daemon=True
            )
            self._monitor_thread.start()
            logger.info(f"VRAMMonitor: Started on device {self.budget.device_index}")
    
    def stop(self) -> None:
        """Stop monitoring VRAM."""
        with self._lock:
            self._running = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
        logger.info("VRAMMonitor: Stopped")
    
    def _monitor_loop(self, interval_seconds: float) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                snapshot = self.take_snapshot()
                with self._lock:
                    self._snapshots.append(snapshot)
                    if len(self._snapshots) > self._max_snapshots:
                        self._snapshots.pop(0)
                    
                    if snapshot.allocated_mb > self._peak_allocated_mb:
                        self._peak_allocated_mb = snapshot.allocated_mb
                    
                    # Check thresholds
                    if not self._alert_fired and snapshot.utilization_pct >= self.budget.max_utilization_pct:
                        self._alert_fired = True
                        logger.warning(f"VRAMMonitor: ALERT - VRAM utilization {snapshot.utilization_pct:.1f}% >= {self.budget.max_utilization_pct}%")
                        for cb in self._callbacks:
                            try:
                                cb("ALERT", snapshot)
                            except Exception:
                                pass
                    
                    elif not self._warning_fired and snapshot.utilization_pct >= self.budget.warning_utilization_pct:
                        self._warning_fired = True
                        logger.warning(f"VRAMMonitor: WARNING - VRAM utilization {snapshot.utilization_pct:.1f}% >= {self.budget.warning_utilization_pct}%")
                        for cb in self._callbacks:
                            try:
                                cb("WARNING", snapshot)
                            except Exception:
                                pass
                    
                    # Reset alerts if usage drops
                    if self._alert_fired and snapshot.utilization_pct < self.budget.max_utilization_pct - 5:
                        self._alert_fired = False
                    if self._warning_fired and snapshot.utilization_pct < self.budget.warning_utilization_pct - 5:
                        self._warning_fired = False
                        
            except Exception as e:
                logger.error(f"VRAMMonitor: Monitoring error: {e}")
            
            time.sleep(interval_seconds)
    
    def take_snapshot(self) -> VRAMSnapshot:
        """Take a single VRAM measurement snapshot."""
        try:
            import torch
            idx = self.budget.device_index
            if torch.cuda.is_available() and idx < torch.cuda.device_count():
                allocated = torch.cuda.memory_allocated(idx) / (1024 * 1024)
                reserved = torch.cuda.memory_reserved(idx) / (1024 * 1024)
                total = torch.cuda.get_device_properties(idx).total_memory / (1024 * 1024)
                free = total - reserved
                utilization = (reserved / total) * 100.0
                
                return VRAMSnapshot(
                    timestamp=time.time(),
                    allocated_mb=allocated,
                    reserved_mb=reserved,
                    total_mb=total,
                    free_mb=free,
                    utilization_pct=utilization,
                    peak_allocated_mb=self._peak_allocated_mb,
                )
        except Exception as e:
            logger.error(f"VRAMMonitor: Snapshot failed: {e}")
        
        return VRAMSnapshot(
            timestamp=time.time(),
            allocated_mb=0.0,
            reserved_mb=0.0,
            total_mb=self.budget.total_vram_mb,
            free_mb=self.budget.total_vram_mb,
            utilization_pct=0.0,
        )
    
    def get_current(self) -> VRAMSnapshot:
        """Get current VRAM snapshot."""
        with self._lock:
            if self._snapshots:
                return self._snapshots[-1]
            return self.take_snapshot()
    
    def get_peak(self) -> float:
        """Get peak allocated VRAM."""
        with self._lock:
            return self._peak_allocated_mb
    
    def get_stats(self) -> Dict[str, Any]:
        """Get VRAM statistics."""
        with self._lock:
            current = self.get_current()
            return {
                "current": {
                    "allocated_mb": current.allocated_mb,
                    "reserved_mb": current.reserved_mb,
                    "total_mb": current.total_mb,
                    "free_mb": current.free_mb,
                    "utilization_pct": current.utilization_pct,
                },
                "peak": {
                    "allocated_mb": self._peak_allocated_mb,
                },
                "budget": {
                    "total_mb": self.budget.total_vram_mb,
                    "max_allowed_mb": self.budget.max_allocated_mb,
                    "warning_threshold_mb": self.budget.warning_allocated_mb,
                },
                "alerts": {
                    "alert_fired": self._alert_fired,
                    "warning_fired": self._warning_fired,
                },
                "snapshots_count": len(self._snapshots),
            }
    
    def register_callback(self, callback: callable) -> None:
        """Register callback for alerts."""
        self._callbacks.append(callback)
    
    def is_over_budget(self) -> bool:
        """Check if current usage exceeds budget."""
        current = self.get_current()
        return current.allocated_mb >= self.budget.max_allocated_mb
    
    def get_available_mb(self) -> float:
        """Get available VRAM for new allocations."""
        current = self.get_current()
        return max(0.0, self.budget.max_allocated_mb - current.allocated_mb)


class GPUVRAMSafety:
    """
    VRAM safety layer. No aggressive optimization in Phase 3.1.
    Provides reporting, safe cleanup, and duplicate-prevention guidance.
    """
    
    def __init__(self, preferred_device_index: int = 0):
        self.device_index = preferred_device_index
        self.total_vram_mb = 0
        self.resident_models: Dict[str, int] = {}  # model_key -> device_index
        self._monitor: Optional[VRAMMonitor] = None

    def start_monitoring(self, interval_seconds: float = 1.0) -> VRAMMonitor:
        """Start VRAM monitoring."""
        budget = VRAMBudget(device_index=self.device_index)
        try:
            import torch
            if torch.cuda.is_available() and self.device_index < torch.cuda.device_count():
                budget.total_vram_mb = torch.cuda.get_device_properties(self.device_index).total_memory / (1024 * 1024)
        except Exception:
            pass
        
        self._monitor = VRAMMonitor(budget)
        self._monitor.start(interval_seconds)
        return self._monitor
    
    def stop_monitoring(self) -> None:
        """Stop VRAM monitoring."""
        if self._monitor:
            self._monitor.stop()
            self._monitor = None

    def measure_before_after(self, label: str = "session_init") -> Dict[str, Any]:
        """Measure VRAM before/after an operation (conceptual markers)."""
        report = {"label": label, "device_index": self.device_index, "before_mb": 0, "after_mb": 0, "delta_mb": 0}
        try:
            import torch
            idx = self.device_index
            if torch.cuda.is_available() and idx < torch.cuda.device_count():
                before = torch.cuda.memory_allocated(idx) // (1024 * 1024)
                after = before  # No forced allocation in this phase
                report["before_mb"] = before
                report["after_mb"] = after
                report["delta_mb"] = after - before
                report["total_vram_mb"] = torch.cuda.get_device_properties(idx).total_memory // (1024 * 1024)
                report["reserved_mb"] = torch.cuda.memory_reserved(idx) // (1024 * 1024)
        except Exception as exc:
            report["measurement_error"] = str(exc)
        return report

    def register_model_residency(self, model_key: str, device_index: int = -1) -> Dict[str, Any]:
        idx = device_index if device_index >= 0 else self.device_index
        existing = self.resident_models.get(model_key)
        report = {
            "model_key": model_key,
            "requested_device": idx,
            "duplicate": existing is not None,
        }
        if existing is None:
            self.resident_models[model_key] = idx
            report["action"] = "registered"
        else:
            report["action"] = "existing_reused"
        return report

    def cleanup(self) -> Dict[str, Any]:
        count_before = len(self.resident_models)
        return {"tracked_models_before_cleanup": count_before, "note": "Conservative cleanup: no forced GPU clear"}

    def get_report(self) -> Dict[str, Any]:
        report = {
            "device_index": self.device_index,
            "tracked_model_keys": list(self.resident_models.keys()),
            "duplicate_prevention_active": True,
        }
        if self._monitor:
            report["monitor"] = self._monitor.get_stats()
        return report
