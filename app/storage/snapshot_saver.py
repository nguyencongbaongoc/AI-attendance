"""
Phase 17A WP2 — Asynchronous GPU SnapshotSaver.

Non-blocking snapshot extraction from GPU tensors to JPEG files.
- Slices face crops directly on GPU tensor
- Asynchronously copies to host via non-blocking CUDA stream
- Dispatches JPEG compression and disk write to ThreadPoolExecutor
- Target: < 0.8ms overhead to AI vision frame loop
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import torch

from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract, nv12_cuda_to_bgr_cuda

logger = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    """Result of snapshot saving operation."""
    face_url: Optional[str] = None
    scene_url: Optional[str] = None
    face_path: Optional[str] = None
    scene_path: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: float = 0.0


class AsyncSnapshotSaver:
    """
    Asynchronous GPU snapshot saver with zero hot-path I/O blocking.
    
    Architecture:
    1. GPU tensor slicing (face crop) - runs on CUDA stream
    2. Non-blocking CUDA -> CPU copy - async stream download
    3. JPEG encoding + disk write - ThreadPoolExecutor (2 workers)
    4. Returns relative URIs for database storage
    """
    
    def __init__(
        self,
        base_dir: str = "app/static/evidence/snapshots",
        max_workers: int = 2,
        jpeg_quality: int = 90,
        device_id: int = 0,
    ):
        self.base_dir = Path(base_dir)
        self.max_workers = max_workers
        self.jpeg_quality = jpeg_quality
        self.device_id = device_id
        self.device = torch.device(f"cuda:{device_id}")
        
        # CUDA stream for async operations
        self._cuda_stream = torch.cuda.Stream(device=self.device)
        
        # Thread pool for CPU-bound JPEG encoding and disk I/O
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="snapshot_saver"
        )
        
        # Ensure base directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"AsyncSnapshotSaver initialized: base_dir={base_dir}, workers={max_workers}")
    
    def _get_daily_dir(self) -> Path:
        """Get today's date-based directory."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        daily_dir = self.base_dir / date_str
        daily_dir.mkdir(parents=True, exist_ok=True)
        return daily_dir
    
    def _generate_paths(self, camera_id: str, event_id: str) -> Tuple[Path, Path]:
        """Generate face and scene snapshot paths."""
        daily_dir = self._get_daily_dir()
        face_path = daily_dir / f"{camera_id}_{event_id}_face.jpg"
        scene_path = daily_dir / f"{camera_id}_{event_id}_scene.jpg"
        return face_path, scene_path
    
    def _get_relative_uri(self, path: Path) -> str:
        """Convert absolute path to relative URI for database storage."""
        # Return path relative to app/static for web serving
        try:
            return str(path.relative_to("app/static"))
        except ValueError:
            # Fallback if not under app/static
            return str(path)
    
    def save_snapshot_async(
        self,
        gpu_frame: GPUFrameContract,
        face_bbox: Optional[Tuple[int, int, int, int]],  # (x1, y1, x2, y2)
        camera_id: str,
        event_id: str,
        save_scene: bool = True,
    ) -> asyncio.Future:
        """
        Save snapshots asynchronously - returns Future with SnapshotResult.
        
        This is the main entry point called from the AI vision loop.
        It returns immediately (< 0.1ms) while work happens in background.
        """
        loop = asyncio.get_event_loop()
        
        # Submit the CPU-bound work to thread pool
        future = loop.run_in_executor(
            self._executor,
            self._save_snapshot_sync,
            gpu_frame,
            face_bbox,
            camera_id,
            event_id,
            save_scene,
        )
        
        return future
    
    def _save_snapshot_sync(
        self,
        gpu_frame: GPUFrameContract,
        face_bbox: Optional[Tuple[int, int, int, int]],
        camera_id: str,
        event_id: str,
        save_scene: bool,
    ) -> SnapshotResult:
        """
        Synchronous snapshot saving (runs in thread pool).
        
        This does the actual GPU->CPU copy, JPEG encoding, and disk write.
        """
        start_time = time.perf_counter()
        
        try:
            face_path, scene_path = self._generate_paths(camera_id, event_id)
            face_url = None
            scene_url = None
            
            # Convert NV12 to BGR on GPU (single operation)
            y_tensor, uv_tensor = gpu_frame.get_tensors()
            bgr_tensor = nv12_cuda_to_bgr_cuda(y_tensor, uv_tensor)  # (H, W, 3) on GPU
            
            # Extract face crop if bbox provided
            face_crop = None
            if face_bbox is not None:
                x1, y1, x2, y2 = face_bbox
                h, w = bgr_tensor.shape[:2]
                
                # Clamp to frame bounds
                x1 = max(0, min(x1, w - 1))
                y1 = max(0, min(y1, h - 1))
                x2 = max(x1 + 1, min(x2, w))
                y2 = max(y1 + 1, min(y2, h))
                
                # Crop on GPU tensor (zero-copy slice)
                face_crop = bgr_tensor[y1:y2, x1:x2]
                
                # Async copy to CPU
                face_cpu = self._cuda_tensor_to_cpu_async(face_crop)
                
                # Save face JPEG
                if face_cpu is not None and face_cpu.size > 0:
                    cv2.imwrite(
                        str(face_path),
                        face_cpu,
                        [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                    )
                    face_url = self._get_relative_uri(face_path)
                    logger.debug(f"Saved face snapshot: {face_url}")
            
            # Save scene (full frame) if requested
            if save_scene:
                # Async copy full frame to CPU
                scene_cpu = self._cuda_tensor_to_cpu_async(bgr_tensor)
                
                if scene_cpu is not None and scene_cpu.size > 0:
                    cv2.imwrite(
                        str(scene_path),
                        scene_cpu,
                        [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                    )
                    scene_url = self._get_relative_uri(scene_path)
                    logger.debug(f"Saved scene snapshot: {scene_url}")
            
            processing_time = (time.perf_counter() - start_time) * 1000
            
            return SnapshotResult(
                face_url=face_url,
                scene_url=scene_url,
                face_path=str(face_path) if face_url else None,
                scene_path=str(scene_path) if scene_url else None,
                processing_time_ms=processing_time,
            )
            
        except Exception as e:
            logger.error(f"Snapshot save failed for {camera_id}/{event_id}: {e}")
            return SnapshotResult(
                error=str(e),
                processing_time_ms=(time.perf_counter() - start_time) * 1000,
            )
    
    def _cuda_tensor_to_cpu_async(self, tensor: torch.Tensor) -> Optional[np.ndarray]:
        """
        Copy CUDA tensor to CPU asynchronously using non-blocking stream.
        
        Returns numpy array on CPU or None if failed.
        """
        try:
            # Record event on compute stream
            event = torch.cuda.Event(enable_timing=False)
            event.record(self._cuda_stream)
            
            # Copy to CPU on the async stream
            with torch.cuda.stream(self._cuda_stream):
                cpu_tensor = tensor.detach().to("cpu", non_blocking=True)
            
            # Synchronize the event to ensure copy is complete
            event.synchronize()
            
            # Convert to numpy
            return cpu_tensor.numpy()
            
        except Exception as e:
            logger.error(f"CUDA to CPU copy failed: {e}")
            return None
    
    def save_snapshot_blocking(
        self,
        gpu_frame: GPUFrameContract,
        face_bbox: Optional[Tuple[int, int, int, int]],
        camera_id: str,
        event_id: str,
        save_scene: bool = True,
    ) -> SnapshotResult:
        """
        Blocking version for testing/debugging.
        
        Runs synchronously in the calling thread.
        """
        return self._save_snapshot_sync(gpu_frame, face_bbox, camera_id, event_id, save_scene)
    
    def shutdown(self, wait: bool = True):
        """Shutdown the thread pool executor."""
        logger.info("Shutting down AsyncSnapshotSaver...")
        self._executor.shutdown(wait=wait)
        if torch.cuda.is_available():
            torch.cuda.synchronize(self.device)


# Global instance
_snapshot_saver: Optional[AsyncSnapshotSaver] = None


def get_snapshot_saver(
    base_dir: str = "app/static/evidence/snapshots",
    max_workers: int = 2,
    jpeg_quality: int = 90,
    device_id: int = 0,
) -> AsyncSnapshotSaver:
    """Get or create the global snapshot saver instance."""
    global _snapshot_saver
    if _snapshot_saver is None:
        _snapshot_saver = AsyncSnapshotSaver(
            base_dir=base_dir,
            max_workers=max_workers,
            jpeg_quality=jpeg_quality,
            device_id=device_id,
        )
    return _snapshot_saver


def shutdown_snapshot_saver():
    """Shutdown the global snapshot saver."""
    global _snapshot_saver
    if _snapshot_saver is not None:
        _snapshot_saver.shutdown()
        _snapshot_saver = None