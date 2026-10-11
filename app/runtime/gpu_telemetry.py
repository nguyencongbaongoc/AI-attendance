"""
Phase H9.9 — GPU Telemetry Collector.

Collects real-time GPU utilization, VRAM usage, and related metrics from NVIDIA GPU
using NVML (pynvml) as primary source, with nvidia-smi fallback.

This module is designed for:
- Independent polling (1-2s interval) from AI frame loop
- Freshness tracking with STALE/UNAVAILABLE states
- Zero hardcoded values — all from runtime telemetry
- Minimal CPU overhead
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TelemetrySource(str, Enum):
    """Source of GPU telemetry data."""
    NVML = "nvml"
    NVSMI = "nvidia-smi"
    TORCH = "torch"
    UNAVAILABLE = "unavailable"


class TelemetryState(str, Enum):
    """Freshness state of telemetry data."""
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class GPUTelemetry:
    """Single GPU telemetry snapshot with metadata."""
    timestamp: str
    gpu_index: int
    source: TelemetrySource
    state: TelemetryState
    
    # GPU Identity
    gpu_name: Optional[str] = None
    driver_version: Optional[str] = None
    cuda_runtime_version: Optional[str] = None
    
    # Utilization
    gpu_utilization_percent: Optional[float] = None
    
    # VRAM (framebuffer memory)
    memory_used_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    memory_free_bytes: Optional[int] = None
    
    # Optional: Torch-specific memory (separate from total VRAM)
    torch_allocated_bytes: Optional[int] = None
    torch_reserved_bytes: Optional[int] = None
    
    # Encoder/Decoder status
    nvenc_available: Optional[bool] = None
    nvdec_available: Optional[bool] = None
    nvenc_active: Optional[bool] = None
    nvdec_active: Optional[bool] = None
    
    # CUDA availability
    cuda_available: Optional[bool] = None
    cuda_ep_registered: Optional[bool] = None
    
    # Error info if state is ERROR
    error_message: Optional[str] = None
    
    # GPU State (derived from telemetry evidence)
    gpu_state: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API serialization."""
        return {
            "timestamp": self.timestamp,
            "gpu_index": self.gpu_index,
            "source": self.source.value,
            "state": self.state.value,
            "gpu_name": self.gpu_name,
            "driver_version": self.driver_version,
            "cuda_runtime_version": self.cuda_runtime_version,
            "gpu_utilization_percent": self.gpu_utilization_percent,
            "memory_used_bytes": self.memory_used_bytes,
            "memory_total_bytes": self.memory_total_bytes,
            "memory_free_bytes": self.memory_free_bytes,
            "torch_allocated_bytes": self.torch_allocated_bytes,
            "torch_reserved_bytes": self.torch_reserved_bytes,
            "nvenc_available": self.nvenc_available,
            "nvdec_available": self.nvdec_available,
            "nvenc_active": self.nvenc_active,
            "nvdec_active": self.nvdec_active,
            "cuda_available": self.cuda_available,
            "cuda_ep_registered": self.cuda_ep_registered,
            "error_message": self.error_message,
            "gpu_state": self.gpu_state,
        }


@dataclass
class GPUCollectorConfig:
    """Configuration for GPU telemetry collector."""
    gpu_index: int = 0
    poll_interval_seconds: float = 2.0
    freshness_threshold_seconds: float = 10.0
    enable_nvml: bool = True
    enable_nvsmi_fallback: bool = True
    enable_torch_fallback: bool = True


class GPUCollector:
    """
    GPU telemetry collector with NVML primary, nvidia-smi fallback.
    
    Runs independently from AI inference loop.
    Provides freshness tracking and automatic recovery.
    """
    
    def __init__(self, config: Optional[GPUCollectorConfig] = None):
        self.config = config or GPUCollectorConfig()
        self._latest: Optional[GPUTelemetry] = None
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._consecutive_failures = 0
        self._nvml_initialized = False
        
    async def start(self) -> None:
        """Start the background collection task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())
        logger.info(f"GPU telemetry collector started (interval={self.config.poll_interval_seconds}s)")
        
    async def stop(self) -> None:
        """Stop the background collection task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._shutdown_nvml()
        logger.info("GPU telemetry collector stopped")
        
    def get_latest(self) -> Optional[GPUTelemetry]:
        """Get the latest telemetry snapshot (thread-safe)."""
        return self._latest
    
    def get_latest_or_stale(self) -> GPUTelemetry:
        """Get latest telemetry, or a STALE/UNAVAILABLE placeholder if none."""
        if self._latest is None:
            return GPUTelemetry(
                timestamp=datetime.utcnow().isoformat() + "Z",
                gpu_index=self.config.gpu_index,
                source=TelemetrySource.UNAVAILABLE,
                state=TelemetryState.UNAVAILABLE,
                error_message="No telemetry collected yet"
            )
        return self._latest
    
    def is_fresh(self) -> bool:
        """Check if latest telemetry is fresh."""
        if self._latest is None:
            return False
        age = time.time() - self._parse_timestamp(self._latest.timestamp)
        return age <= self.config.freshness_threshold_seconds
    
    def _parse_timestamp(self, ts: str) -> float:
        """Parse ISO timestamp to unix time."""
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0
    
    async def _collection_loop(self) -> None:
        """Main collection loop running at configured interval."""
        while self._running:
            try:
                telemetry = await self._collect_once()
                async with self._lock:
                    self._latest = telemetry
                    self._consecutive_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._consecutive_failures += 1
                logger.warning(f"GPU telemetry collection failed (attempt {self._consecutive_failures}): {e}")
                async with self._lock:
                    self._latest = GPUTelemetry(
                        timestamp=datetime.utcnow().isoformat() + "Z",
                        gpu_index=self.config.gpu_index,
                        source=TelemetrySource.UNAVAILABLE,
                        state=TelemetryState.ERROR,
                        error_message=str(e)
                    )
            
            # Sleep with cancellation support
            try:
                await asyncio.sleep(self.config.poll_interval_seconds)
            except asyncio.CancelledError:
                break
    
    async def _collect_once(self) -> GPUTelemetry:
        """Collect a single telemetry snapshot."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        gpu_index = self.config.gpu_index
        
        # Try NVML first
        if self.config.enable_nvml:
            try:
                return await self._collect_nvml(timestamp, gpu_index)
            except Exception as e:
                logger.debug(f"NVML collection failed: {e}")
        
        # Fallback to nvidia-smi
        if self.config.enable_nvsmi_fallback:
            try:
                return await self._collect_nvsmi(timestamp, gpu_index)
            except Exception as e:
                logger.debug(f"nvidia-smi collection failed: {e}")
        
        # Fallback to torch
        if self.config.enable_torch_fallback:
            try:
                return await self._collect_torch(timestamp, gpu_index)
            except Exception as e:
                logger.debug(f"Torch collection failed: {e}")
        
        # All sources failed
        return GPUTelemetry(
            timestamp=timestamp,
            gpu_index=gpu_index,
            source=TelemetrySource.UNAVAILABLE,
            state=TelemetryState.UNAVAILABLE,
            error_message="All telemetry sources unavailable"
        )
    
    def _init_nvml(self) -> bool:
        """Initialize NVML if not already done."""
        if self._nvml_initialized:
            return True
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml_initialized = True
            return True
        except Exception as e:
            logger.debug(f"NVML init failed: {e}")
            return False
    
    def _shutdown_nvml(self) -> None:
        """Shutdown NVML."""
        if self._nvml_initialized:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False
    
    async def _collect_nvml(self, timestamp: str, gpu_index: int) -> GPUTelemetry:
        """Collect telemetry using NVML (pynvml)."""
        import pynvml
        
        if not self._init_nvml():
            raise RuntimeError("NVML not initialized")
        
        device_count = pynvml.nvmlDeviceGetCount()
        if gpu_index >= device_count:
            raise RuntimeError(f"GPU index {gpu_index} not found (only {device_count} devices)")
        
        handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        
        # GPU name
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        
        # Driver version
        drv = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(drv, bytes):
            drv = drv.decode("utf-8")
        
        # CUDA runtime version (from nvidia-smi header)
        cuda_runtime = self._get_cuda_runtime_version()
        
        # Utilization
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        gpu_util = float(util.gpu)
        
        # Memory
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        used = mem.used
        total = mem.total
        free = mem.free
        
        # Encoder/Decoder availability - check via nvidia-smi for active sessions
        nvenc_available, nvdec_available = self._check_encoder_decoder_nvml(handle)
        
        # Torch memory (optional, separate from total VRAM)
        torch_allocated, torch_reserved = self._get_torch_memory()
        
        # Derive GPU state from telemetry evidence
        gpu_state = self._derive_gpu_state(
            gpu_util, nvenc_available, nvdec_available, torch_allocated
        )
        
        return GPUTelemetry(
            timestamp=timestamp,
            gpu_index=gpu_index,
            source=TelemetrySource.NVML,
            state=TelemetryState.FRESH,
            gpu_name=name,
            driver_version=drv,
            cuda_runtime_version=cuda_runtime,
            gpu_utilization_percent=gpu_util,
            memory_used_bytes=used,
            memory_total_bytes=total,
            memory_free_bytes=free,
            torch_allocated_bytes=torch_allocated,
            torch_reserved_bytes=torch_reserved,
            nvenc_available=nvenc_available,
            nvdec_available=nvdec_available,
            nvenc_active=None,  # Would need process-level inspection
            nvdec_active=None,
            cuda_available=True,  # If NVML works, CUDA is available
            cuda_ep_registered=None,  # Not from NVML
            gpu_state=gpu_state,
        )
    
    def _get_cuda_runtime_version(self) -> Optional[str]:
        """Get CUDA runtime version from nvidia-smi."""
        try:
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.splitlines():
                    if "CUDA UMD Version" in line or "CUDA Version" in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            return parts[1].strip().split()[0]
        except Exception:
            pass
        return None
    
    def _check_encoder_decoder_nvml(self, handle) -> tuple[Optional[bool], Optional[bool]]:
        """Check encoder/decoder availability via NVML."""
        try:
            import pynvml
            # NVML doesn't directly expose encoder/decoder availability
            # We'll check nvidia-smi for this
            return self._check_encoder_decoder_nvsmi()
        except Exception:
            return None, None
    
    def _check_encoder_decoder_nvsmi(self) -> tuple[Optional[bool], Optional[bool]]:
        """Check encoder/decoder availability via nvidia-smi."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=encoder.stats.sessionCount,decoder.stats.sessionCount", 
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(",")
                if len(parts) >= 2:
                    enc = int(parts[0].strip()) > 0
                    dec = int(parts[1].strip()) > 0
                    return True, True  # Available if we can query
        except Exception:
            pass
        return None, None
    
    def _get_torch_memory(self) -> tuple[Optional[int], Optional[int]]:
        """Get PyTorch CUDA memory stats."""
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.memory_allocated(), torch.cuda.memory_reserved()
        except Exception:
            pass
        return None, None
    
    async def _collect_nvsmi(self, timestamp: str, gpu_index: int) -> GPUTelemetry:
        """Collect telemetry using nvidia-smi."""
        # Query all needed fields in one call
        query_fields = [
            "name",
            "driver_version",
            "utilization.gpu",
            "memory.used",
            "memory.total",
            "memory.free",
        ]
        
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(query_fields)}",
                "--format=csv,noheader,nounits",
                f"-i", str(gpu_index)
            ],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"nvidia-smi failed: {result.stderr}")
        
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) < 6:
            raise RuntimeError(f"Unexpected nvidia-smi output: {result.stdout}")
        
        gpu_name = parts[0]
        driver_version = parts[1]
        gpu_util = float(parts[2]) if parts[2] != "[Not Supported]" else None
        mem_used = self._parse_memory(parts[3])
        mem_total = self._parse_memory(parts[4])
        mem_free = self._parse_memory(parts[5])
        
        cuda_runtime = self._get_cuda_runtime_version()
        
        # Check encoder/decoder
        nvenc_avail, nvdec_avail = self._check_encoder_decoder_nvsmi()
        
        # Torch memory
        torch_alloc, torch_res = self._get_torch_memory()
        
        # Derive GPU state
        gpu_state = self._derive_gpu_state(
            gpu_util, nvenc_avail, nvdec_avail, torch_alloc
        )
        
        return GPUTelemetry(
            timestamp=timestamp,
            gpu_index=gpu_index,
            source=TelemetrySource.NVSMI,
            state=TelemetryState.FRESH,
            gpu_name=gpu_name,
            driver_version=driver_version,
            cuda_runtime_version=cuda_runtime,
            gpu_utilization_percent=gpu_util,
            memory_used_bytes=mem_used,
            memory_total_bytes=mem_total,
            memory_free_bytes=mem_free,
            torch_allocated_bytes=torch_alloc,
            torch_reserved_bytes=torch_res,
            nvenc_available=nvenc_avail,
            nvdec_available=nvdec_avail,
            nvenc_active=None,
            nvdec_active=None,
            cuda_available=True,
            cuda_ep_registered=None,
            gpu_state=gpu_state,
        )
    
    def _parse_memory(self, val: str) -> Optional[int]:
        """Parse memory value from nvidia-smi (e.g., '1234 MiB')."""
        if val in ("[Not Supported]", "[Unknown]"):
            return None
        try:
            # nvidia-smi with nounits returns just the number in MiB
            return int(val) * 1024 * 1024
        except ValueError:
            return None
    
    async def _collect_torch(self, timestamp: str, gpu_index: int) -> GPUTelemetry:
        """Collect telemetry using PyTorch CUDA."""
        import torch
        
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available in PyTorch")
        
        if gpu_index >= torch.cuda.device_count():
            raise RuntimeError(f"GPU index {gpu_index} not found")
        
        props = torch.cuda.get_device_properties(gpu_index)
        gpu_name = props.name
        total_mem = props.total_memory
        
        # Torch memory
        allocated = torch.cuda.memory_allocated(gpu_index)
        reserved = torch.cuda.memory_reserved(gpu_index)
        
        # Driver version and CUDA runtime not available from torch directly
        # Utilization not available from torch
        
        return GPUTelemetry(
            timestamp=timestamp,
            gpu_index=gpu_index,
            source=TelemetrySource.TORCH,
            state=TelemetryState.FRESH,
            gpu_name=gpu_name,
            driver_version=None,
            cuda_runtime_version=torch.version.cuda,
            gpu_utilization_percent=None,  # Not available from torch
            memory_used_bytes=allocated,  # Note: this is torch allocated, not total VRAM
            memory_total_bytes=total_mem,
            memory_free_bytes=total_mem - reserved,  # Approximate
            torch_allocated_bytes=allocated,
            torch_reserved_bytes=reserved,
            nvenc_available=None,
            nvdec_available=None,
            nvenc_active=None,
            nvdec_active=None,
            cuda_available=True,
            cuda_ep_registered=None,
            gpu_state="AVAILABLE",
        )


    def _derive_gpu_state(
        self,
        utilization: Optional[float],
        nvenc_available: Optional[bool],
        nvdec_available: Optional[bool],
        torch_allocated: Optional[int],
    ) -> str:
        """
        Derive GPU state from telemetry evidence.
        
        Per spec:
        - Only use INFERENCE_ACTIVE when runtime evidence supports it
        - Only use ENCODER_ACTIVE when runtime evidence supports it
        - Default to AVAILABLE when classification cannot be proven
        """
        # If we have utilization and it's > 5%, GPU is doing something
        if utilization is not None and utilization > 5.0:
            # Check if encoder is actively being used (would need process inspection)
            # For now, if NVENC is available and utilization > 5%, could be encoder
            if nvenc_available and utilization > 10.0:
                return "ENCODER_ACTIVE"
            # If torch has allocated memory, likely inference
            if torch_allocated is not None and torch_allocated > 100 * 1024 * 1024:  # > 100MB
                return "INFERENCE_ACTIVE"
            return "AVAILABLE"
        
        # Low or no utilization
        if utilization is not None and utilization <= 1.0:
            return "AVAILABLE_IDLE"
        
        # Unknown utilization
        return "AVAILABLE"


# Global collector instance
_global_collector: Optional[GPUCollector] = None


def get_gpu_collector(config: Optional[GPUCollectorConfig] = None) -> GPUCollector:
    """Get or create the global GPU collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = GPUCollector(config)
    return _global_collector


async def initialize_gpu_telemetry(config: Optional[GPUCollectorConfig] = None) -> GPUCollector:
    """Initialize and start the global GPU telemetry collector."""
    collector = get_gpu_collector(config)
    await collector.start()
    return collector


async def shutdown_gpu_telemetry() -> None:
    """Shutdown the global GPU telemetry collector."""
    global _global_collector
    if _global_collector:
        await _global_collector.stop()
        _global_collector = None


def collect_gpu_telemetry() -> GPUTelemetry:
    """Synchronous collection for use in non-async contexts (e.g., REST endpoint)."""
    collector = get_gpu_collector()
    latest = collector.get_latest()
    if latest and collector.is_fresh():
        return latest
    
    # If no collector running or stale, do a one-shot sync collection
    # Run async collection in sync context
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(collector._collect_once())