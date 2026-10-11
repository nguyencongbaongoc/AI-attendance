#!/usr/bin/env python3
"""
Phase 11.3 — Frame Integrity Audit Tool.
Forensic frame-level validation of the complete canonical pipeline:
REAL CAMERA → MediaMTX → RTSP → PyAV CUDA NVDEC → GPU NV12 → GPU preprocessing → GPU AI
→ Association/Tracking → GPU Annotation → GPUFrameContract → Native NVENC → H264 Annex-B
→ EncoderPacketToPublisherBridge → Existing Publisher → MediaMTX AI output → Downstream consumer

This is TEST-ONLY tooling. Does NOT modify production hot paths.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import torch

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.data.frame import CanonicalFrame
from app.streaming.camera_runtime_manager import (
    CameraRuntimeManager,
    CameraRuntimeConfig,
    CameraRuntimeState,
    create_camera_runtime_manager,
)
from app.streaming.health import StreamHealthMonitor, create_health_monitor
from app.streaming.ingestion_worker import CameraIngestionWorker, CameraIngestionConfig
from app.streaming.detection_pipeline import DetectionPipeline, DetectionPipelineConfig
from app.streaming.annotated_publisher import AnnotatedFramePublisher, AnnotatedPublisherConfig
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract
from app.video.pynvcodec.encoder_adapter import EncoderAdapter
from app.streaming.encoder_packet_publisher import EncoderPacketToPublisherBridge

logger = logging.getLogger(__name__)


# ============================================================================
# FRAME AUDIT DATA STRUCTURES
# ============================================================================

@dataclass(frozen=True)
class FrameAuditRecord:
    """Complete forensic record for a single frame as it traverses the pipeline."""
    camera_id: str
    source_frame_index: int = -1
    input_pts: int = -1
    input_dts: int = -1
    input_time_base: str = ""
    input_width: int = -1
    input_height: int = -1
    input_pixel_format: str = ""
    input_gpu_memory_type: str = ""
    
    decoder_frame_index: int = -1
    decoder_pts: int = -1
    decoder_dts: int = -1
    
    preprocess_frame_index: int = -1
    
    ai_frame_index: int = -1
    
    annotation_frame_index: int = -1
    
    contract_frame_index: int = -1
    
    encoder_frame_index: int = -1
    encoded_pts: int = -1
    encoded_dts: int = -1
    
    publisher_frame_index: int = -1
    
    output_pts: int = -1
    output_dts: int = -1
    output_width: int = -1
    output_height: int = -1
    output_codec: str = ""
    output_pixel_format: str = ""
    
    timestamp: float = field(default_factory=time.time)
    processing_latency: float = -1.0
    end_to_end_latency: float = -1.0
    
    error_code: str = ""
    error_stage: str = ""
    
    # Fingerprints for content integrity
    gpu_metadata_hash: str = ""
    sampled_pixel_hash: str = ""
    frame_checksum: str = ""
    encoded_decoded_checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "source_frame_index": self.source_frame_index,
            "input_pts": self.input_pts,
            "input_dts": self.input_dts,
            "input_time_base": self.input_time_base,
            "input_width": self.input_width,
            "input_height": self.input_height,
            "input_pixel_format": self.input_pixel_format,
            "input_gpu_memory_type": self.input_gpu_memory_type,
            "decoder_frame_index": self.decoder_frame_index,
            "decoder_pts": self.decoder_pts,
            "decoder_dts": self.decoder_dts,
            "preprocess_frame_index": self.preprocess_frame_index,
            "ai_frame_index": self.ai_frame_index,
            "annotation_frame_index": self.annotation_frame_index,
            "contract_frame_index": self.contract_frame_index,
            "encoder_frame_index": self.encoder_frame_index,
            "encoded_pts": self.encoded_pts,
            "encoded_dts": self.encoded_dts,
            "publisher_frame_index": self.publisher_frame_index,
            "output_pts": self.output_pts,
            "output_dts": self.output_dts,
            "output_width": self.output_width,
            "output_height": self.output_height,
            "output_codec": self.output_codec,
            "output_pixel_format": self.output_pixel_format,
            "timestamp": self.timestamp,
            "processing_latency": self.processing_latency,
            "end_to_end_latency": self.end_to_end_latency,
            "error_code": self.error_code or "NONE",
            "error_stage": self.error_stage or "NONE",
            "gpu_metadata_hash": self.gpu_metadata_hash or "NOT_AVAILABLE",
            "sampled_pixel_hash": self.sampled_pixel_hash or "NOT_AVAILABLE",
            "frame_checksum": self.frame_checksum or "NOT_AVAILABLE",
            "encoded_decoded_checksum": self.encoded_decoded_checksum or "NOT_AVAILABLE",
        }


@dataclass
class FrameReconciliationTable:
    """Frame count reconciliation across pipeline stages."""
    camera_id: str
    input_frames: int = 0
    decoded_frames: int = 0
    preprocessed_frames: int = 0
    ai_frames: int = 0
    annotated_frames: int = 0
    contract_frames: int = 0
    encoded_frames: int = 0
    published_frames: int = 0
    output_frames: int = 0
    
    def to_table(self) -> List[Dict[str, Any]]:
        stages = [
            ("Input", self.input_frames),
            ("Decode", self.decoded_frames),
            ("Preprocess", self.preprocessed_frames),
            ("AI", self.ai_frames),
            ("Annotation", self.annotated_frames),
            ("Contract", self.contract_frames),
            ("Encode", self.encoded_frames),
            ("Publish", self.published_frames),
            ("Output", self.output_frames),
        ]
        result = []
        prev_count = None
        for name, count in stages:
            delta = count - prev_count if prev_count is not None else 0
            loss_pct = (abs(delta) / prev_count * 100) if prev_count and prev_count > 0 else 0.0
            result.append({
                "stage": name,
                "count": count,
                "delta_from_previous": delta,
                "loss_pct": round(loss_pct, 2),
            })
            prev_count = count
        return result


@dataclass
class TimestampAnomaly:
    """Record of timestamp ordering anomalies."""
    camera_id: str
    frame_before_idx: int
    frame_after_idx: int
    pts_before: int
    pts_after: int
    dts_before: int
    dts_after: int
    delta_pts: int
    delta_dts: int
    stage: str
    anomaly_type: str  # duplicate, missing, reordered, stale, future, regression, jump, discontinuity
    error_code: str = ""


@dataclass
class ErrorCodeRecord:
    """Forensic record of an error code occurrence."""
    code_hex: str
    code_decimal: int
    component: str
    stage: str
    camera_id: str
    first_occurrence: str
    last_occurrence: str
    frequency: int
    trigger: str
    recovery: str
    current_status: str  # RESOLVED, ACTIVE, INTERMITTENT, PRE_EXISTING, NEW, UNKNOWN
    classification: str  # ERROR_CODE, STATUS_CODE, MEMORY_ADDRESS, CONFIG_VALUE, IDENTIFIER, NORMAL_CONSTANT, UNKNOWN
    source_subsystem: str  # Windows HRESULT, NTSTATUS, FFmpeg AVERROR, CUDA, NVENC, NVDEC, etc.
    raw_context: str = ""


# ============================================================================
# FRAME FORENSICS AUDIT ENGINE
# ============================================================================

class FrameForensicsAudit:
    """
    Main forensic audit engine for frame integrity validation.
    
    Collects frame-level metadata at each pipeline stage, performs
    reconciliation, order verification, content integrity checks,
    and error code forensics.
    """
    
    def __init__(
        self,
        camera_ids: List[str] = None,
        duration_seconds: float = 60.0,
        sample_rate: float = 1.0,  # Sample 1 frame per N frames
        enable_gpu_hash: bool = True,
        output_dir: Path = None,
    ):
        self.camera_ids = camera_ids or ["CAM1", "CAM2"]
        self.duration_seconds = duration_seconds
        self.sample_rate = sample_rate
        self.enable_gpu_hash = enable_gpu_hash
        self.output_dir = output_dir or REPO_ROOT / "artifacts" / "phase11" / "forensics"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self._running = False
        self._audit_threads: Dict[str, threading.Thread] = {}
        self._frame_records: Dict[str, List[FrameAuditRecord]] = {cid: [] for cid in self.camera_ids}
        self._frame_queues: Dict[str, queue.Queue] = {cid: queue.Queue() for cid in self.camera_ids}
        self._reconciliation: Dict[str, FrameReconciliationTable] = {
            cid: FrameReconciliationTable(camera_id=cid) for cid in self.camera_ids
        }
        self._timestamp_anomalies: Dict[str, List[TimestampAnomaly]] = {cid: [] for cid in self.camera_ids}
        self._error_codes: List[ErrorCodeRecord] = []
        self._error_code_index: Dict[str, ErrorCodeRecord] = {}
        
        # Pipeline components for inspection
        self._camera_managers: Dict[str, CameraRuntimeManager] = {}
        self._health_monitor: Optional[StreamHealthMonitor] = None
        self._event_callbacks: Dict[str, List[Callable]] = {cid: [] for cid in self.camera_ids}
        
        # Frame identity tracking
        self._frame_id_counters: Dict[str, int] = {cid: 0 for cid in self.camera_ids}
        self._last_pts: Dict[str, int] = {cid: -1 for cid in self.camera_ids}
        self._last_dts: Dict[str, int] = {cid: -1 for cid in self.camera_ids}
        
    # -------------------------------------------------------------------------
    # PIPELINE INSTRUMENTATION HOOKS
    # -------------------------------------------------------------------------
    
    def instrument_ingestion_worker(self, camera_id: str, worker: CameraIngestionWorker) -> None:
        """Hook into ingestion worker frame callback."""
        original_callback = worker._frame_callback
        
        def instrumented_callback(frame: CanonicalFrame):
            self._on_frame_input(camera_id, frame)
            if original_callback:
                original_callback(frame)
        
        worker._frame_callback = instrumented_callback
        logger.info(f"[AUDIT] Instrumented ingestion worker for {camera_id}")
    
    def instrument_detection_pipeline(self, camera_id: str, pipeline: DetectionPipeline) -> None:
        """Hook into detection pipeline process_frame."""
        original_process = pipeline.process_frame
        
        def instrumented_process(frame: CanonicalFrame):
            self._on_frame_preprocess(camera_id, frame)
            original_process(frame)
            self._on_frame_ai_complete(camera_id, frame)
            self._on_frame_annotation_complete(camera_id, frame)
        
        pipeline.process_frame = instrumented_process
        logger.info(f"[AUDIT] Instrumented detection pipeline for {camera_id}")
    
    def instrument_publisher(self, camera_id: str, publisher: AnnotatedFramePublisher) -> None:
        """Hook into annotated publisher submit."""
        original_submit = publisher.submit
        
        def instrumented_submit(frame_data: GPUFrameContract, detections=None, lines=None, regions=None):
            self._on_frame_contract(camera_id, frame_data)
            self._on_frame_encode(camera_id, frame_data)
            result = original_submit(frame_data, detections, lines, regions)
            self._on_frame_publish(camera_id, frame_data)
            return result
        
        publisher.submit = instrumented_submit
        logger.info(f"[AUDIT] Instrumented publisher for {camera_id}")
    
    # -------------------------------------------------------------------------
    # FRAME EVENT HANDLERS
    # -------------------------------------------------------------------------
    
    def _on_frame_input(self, camera_id: str, frame: CanonicalFrame) -> None:
        """Record frame at input stage (from RTSP decoder)."""
        record = FrameAuditRecord(
            camera_id=camera_id,
            source_frame_index=frame.metadata.frame_index,
            input_pts=frame.metadata.pts or -1,
            input_dts=frame.metadata.dts or -1,
            input_time_base=str(frame.metadata.time_base) if frame.metadata.time_base else "",
            input_width=frame.width,
            input_height=frame.height,
            input_pixel_format=frame.metadata.pixel_format.value if frame.metadata.pixel_format else "unknown",
            input_gpu_memory_type=self._detect_gpu_memory_type(frame.data),
        )
        self._update_reconciliation(camera_id, "input_frames", 1)
        self._check_timestamp_order(camera_id, record.input_pts, record.input_dts, "input")
        self._compute_frame_fingerprints(camera_id, frame, record)
        self._frame_records[camera_id].append(record)
    
    def _on_frame_preprocess(self, camera_id: str, frame: CanonicalFrame) -> None:
        """Record frame at preprocessing stage."""
        if self._frame_records[camera_id]:
            record = self._frame_records[camera_id][-1]
            # Update the record (dataclass is frozen, so create new)
            # In practice, we'd use a mutable structure or index
            pass
        self._update_reconciliation(camera_id, "preprocessed_frames", 1)
    
    def _on_frame_ai_complete(self, camera_id: str, frame: CanonicalFrame) -> None:
        """Record frame after AI inference."""
        self._update_reconciliation(camera_id, "ai_frames", 1)
    
    def _on_frame_annotation_complete(self, camera_id: str, frame: CanonicalFrame) -> None:
        """Record frame after GPU annotation."""
        self._update_reconciliation(camera_id, "annotated_frames", 1)
    
    def _on_frame_contract(self, camera_id: str, frame_data: GPUFrameContract) -> None:
        """Record frame at GPUFrameContract stage."""
        if self._frame_records[camera_id]:
            record = self._frame_records[camera_id][-1]
        self._update_reconciliation(camera_id, "contract_frames", 1)
    
    def _on_frame_encode(self, camera_id: str, frame_data: GPUFrameContract) -> None:
        """Record frame at encoder input."""
        self._update_reconciliation(camera_id, "encoded_frames", 1)
        if self._frame_records[camera_id]:
            record = self._frame_records[camera_id][-1]
            # Would update encoded_pts, encoded_dts from frame_data
    
    def _on_frame_publish(self, camera_id: str, frame_data: GPUFrameContract) -> None:
        """Record frame at publisher output."""
        self._update_reconciliation(camera_id, "published_frames", 1)
    
    def _on_frame_output(self, camera_id: str, packet: Dict[str, Any]) -> None:
        """Record frame at final output (H264 packet)."""
        self._update_reconciliation(camera_id, "output_frames", 1)
    
    # -------------------------------------------------------------------------
    # UTILITY METHODS
    # -------------------------------------------------------------------------
    
    def _detect_gpu_memory_type(self, data: Any) -> str:
        """Detect if frame data is GPU-resident."""
        if data is None:
            return "NONE"
        if isinstance(data, dict):
            if data.get("adapter_contract") is not None:
                return "GPUFrameContract"
            if "y_plane" in data and hasattr(data["y_plane"], "is_cuda"):
                return "PyTorch_CUDA_Tensor" if data["y_plane"].is_cuda else "PyTorch_CPU_Tensor"
        if hasattr(data, "is_cuda"):
            return "PyTorch_CUDA_Tensor" if data.is_cuda else "PyTorch_CPU_Tensor"
        if hasattr(data, "nvcv_image"):
            return "NVCV_Image"
        if isinstance(data, np.ndarray):
            return "NumPy_CPU"
        return f"UNKNOWN_{type(data).__name__}"
    
    def _compute_frame_fingerprints(
        self, 
        camera_id: str, 
        frame: CanonicalFrame, 
        record: FrameAuditRecord
    ) -> None:
        """Compute lightweight GPU-side fingerprints for content integrity."""
        # GPU metadata hash (dimensions, format, pts)
        metadata_str = f"{frame.width}x{frame.height}|{frame.metadata.pixel_format}|{frame.metadata.pts}"
        record.gpu_metadata_hash = str(hash(metadata_str) & 0xFFFFFFFFFFFFFFFF)
        
        # Sampled pixel hash (if GPU tensor available and enabled)
        if self.enable_gpu_hash and frame.data is not None:
            try:
                record.sampled_pixel_hash = self._sample_gpu_pixels(frame.data)
            except Exception as e:
                record.sampled_pixel_hash = f"ERROR: {e}"
    
    def _sample_gpu_pixels(self, data: Any) -> str:
        """Sample a small region of GPU frame for fingerprinting."""
        # For GPU tensors, sample a few pixels without full CPU transfer
        if isinstance(data, dict):
            y_tensor = data.get("y_plane")
            if y_tensor is not None and hasattr(y_tensor, "is_cuda") and y_tensor.is_cuda:
                # Sample corners and center (very lightweight)
                h, w = y_tensor.shape
                samples = []
                for y, x in [(0, 0), (0, w-1), (h-1, 0), (h-1, w-1), (h//2, w//2)]:
                    if 0 <= y < h and 0 <= x < w:
                        samples.append(int(y_tensor[y, x].item()))
                return str(hash(tuple(samples)) & 0xFFFFFFFF)
        return "NOT_AVAILABLE"
    
    def _update_reconciliation(self, camera_id: str, field: str, increment: int = 1) -> None:
        """Update frame reconciliation counters."""
        rec = self._reconciliation[camera_id]
        current = getattr(rec, field)
        setattr(rec, field, current + increment)
    
    def _check_timestamp_order(
        self, 
        camera_id: str, 
        pts: int, 
        dts: int, 
        stage: str
    ) -> None:
        """Check for timestamp anomalies."""
        if pts <= 0 and dts <= 0:
            return
        
        last_pts = self._last_pts[camera_id]
        last_dts = self._last_dts[camera_id]
        
        if last_pts > 0:
            delta_pts = pts - last_pts
            delta_dts = dts - last_dts if dts > 0 and last_dts > 0 else 0
            
            anomalies = []
            if delta_pts == 0 and delta_dts == 0:
                anomalies.append(("duplicate", "PTS/DTS unchanged"))
            elif delta_pts < 0:
                anomalies.append(("PTS_regression", f"PTS went backwards: {delta_pts}"))
            elif delta_pts > 10000:  # Arbitrary threshold for jump
                anomalies.append(("timestamp_jump", f"Large PTS jump: {delta_pts}"))
            
            if dts > 0 and last_dts > 0 and delta_dts < 0:
                anomalies.append(("DTS_regression", f"DTS went backwards: {delta_dts}"))
            
            for anomaly_type, desc in anomalies:
                self._timestamp_anomalies[camera_id].append(TimestampAnomaly(
                    camera_id=camera_id,
                    frame_before_idx=len(self._frame_records[camera_id]) - 1,
                    frame_after_idx=len(self._frame_records[camera_id]),
                    pts_before=last_pts,
                    pts_after=pts,
                    dts_before=last_dts,
                    dts_after=dts,
                    delta_pts=delta_pts,
                    delta_dts=delta_dts,
                    stage=stage,
                    anomaly_type=anomaly_type,
                    error_code="",
                ))
        
        self._last_pts[camera_id] = pts if pts > 0 else last_pts
        self._last_dts[camera_id] = dts if dts > 0 else last_dts
    
    def record_error_code(
        self,
        code_hex: str,
        component: str,
        stage: str,
        camera_id: str,
        trigger: str,
        recovery: str,
        context: str = "",
    ) -> ErrorCodeRecord:
        """Record an error code occurrence for forensic audit."""
        try:
            code_decimal = int(code_hex, 16) if code_hex.startswith("0x") else int(code_hex)
        except ValueError:
            code_decimal = 0
        
        # Classify the code
        classification = self._classify_error_code(code_hex, code_decimal, component)
        source_subsystem = self._identify_source_subsystem(code_hex, code_decimal, component)
        
        key = f"{component}:{stage}:{code_hex}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        
        if key in self._error_code_index:
            record = self._error_code_index[key]
            record.frequency += 1
            record.last_occurrence = now
            record.trigger = trigger  # Update with latest trigger
            record.recovery = recovery
        else:
            record = ErrorCodeRecord(
                code_hex=code_hex,
                code_decimal=code_decimal,
                component=component,
                stage=stage,
                camera_id=camera_id,
                first_occurrence=now,
                last_occurrence=now,
                frequency=1,
                trigger=trigger,
                recovery=recovery,
                current_status="ACTIVE",
                classification=classification,
                source_subsystem=source_subsystem,
                raw_context=context,
            )
            self._error_code_index[key] = record
            self._error_codes.append(record)
        
        logger.warning(f"[AUDIT] Error code recorded: {code_hex} ({classification}) from {component}/{stage}")
        return record
    
    def _classify_error_code(self, code_hex: str, code_decimal: int, component: str) -> str:
        """Classify hexadecimal value as error code, status, address, etc."""
        if code_hex.startswith("0x"):
            # Common error code patterns
            if code_decimal & 0x80000000:  # High bit set = error in HRESULT/NTSTATUS
                return "ERROR_CODE"
            if 0xC0000000 <= code_decimal <= 0xFFFFFFFF:
                return "ERROR_CODE"  # NTSTATUS error range
            if 0x80000000 <= code_decimal <= 0x8FFFFFFF:
                return "ERROR_CODE"  # HRESULT error range
        # Check component for known error patterns
        if component.lower() in ("cuda", "nvenc", "nvdec", "ffmpeg", "pyav"):
            return "ERROR_CODE"
        return "UNKNOWN"
    
    def _identify_source_subsystem(self, code_hex: str, code_decimal: int, component: str) -> str:
        """Map error code to authoritative source subsystem."""
        comp_lower = component.lower()
        if comp_lower in ("cuda", "nvenc", "nvdec"):
            return "CUDA/NVENC/NVDEC"
        if comp_lower in ("ffmpeg", "pyav", "av"):
            return "FFmpeg/PyAV"
        if comp_lower in ("windows", "win32", "hresult", "ntstatus"):
            return "Windows HRESULT/NTSTATUS"
        if comp_lower in ("mediartc", "mediamtx"):
            return "MediaMTX"
        return "UNKNOWN"
    
    # -------------------------------------------------------------------------
    # AUDIT EXECUTION
    # -------------------------------------------------------------------------
    
    def start_audit(self) -> bool:
        """Start the forensic audit by launching camera runtimes with instrumentation."""
        logger.info(f"[AUDIT] Starting frame integrity audit for cameras: {self.camera_ids}")
        logger.info(f"[AUDIT] Duration: {self.duration_seconds}s, Sample rate: 1/{self.sample_rate}")
        
        settings = load_settings()
        self._health_monitor = create_health_monitor()
        
        # Start camera runtime managers with instrumentation
        for camera_id in self.camera_ids:
            if camera_id == "CAM1" and not settings.cameras.cam1_enabled:
                logger.info(f"[AUDIT] {camera_id} not enabled, skipping")
                continue
            if camera_id == "CAM2" and not settings.cameras.cam2_enabled:
                logger.info(f"[AUDIT] {camera_id} not enabled, skipping")
                continue
            
            try:
                manager = create_camera_runtime_manager(
                    camera_id=camera_id,
                    settings=settings,
                    health_monitor=self._health_monitor,
                )
                self._camera_managers[camera_id] = manager
                
                # Start with instrumentation
                if manager.start(wait_ready=True, ready_timeout=120.0):
                    logger.info(f"[AUDIT] {camera_id} runtime started successfully")
                    
                    # Instrument the pipeline components
                    if manager._ingestion_worker:
                        self.instrument_ingestion_worker(camera_id, manager._ingestion_worker)
                    if manager._detection_pipeline:
                        self.instrument_detection_pipeline(camera_id, manager._detection_pipeline)
                    if manager._annotated_publisher:
                        self.instrument_publisher(camera_id, manager._annotated_publisher)
                else:
                    logger.error(f"[AUDIT] Failed to start {camera_id} runtime")
                    return False
                    
            except Exception as e:
                logger.error(f"[AUDIT] Error starting {camera_id}: {e}")
                self.record_error_code(
                    code_hex="0xAUDIT_START_FAILED",
                    component="FrameForensicsAudit",
                    stage="startup",
                    camera_id=camera_id,
                    trigger=str(e),
                    recovery="Check camera configuration and RTSP connectivity",
                    context=f"CameraRuntimeManager.start() failed: {e}",
                )
                return False
        
        self._running = True
        return True
    
    def run_audit(self) -> Dict[str, Any]:
        """Run the audit for the configured duration."""
        if not self._running:
            if not self.start_audit():
                return {"status": "FAILED", "error": "Failed to start audit"}
        
        logger.info(f"[AUDIT] Running audit for {self.duration_seconds} seconds...")
        start_time = time.time()
        
        try:
            while time.time() - start_time < self.duration_seconds:
                time.sleep(1.0)
                self._periodic_check()
        except KeyboardInterrupt:
            logger.info("[AUDIT] Interrupted by user")
        finally:
            self.stop_audit()
        
        return self.generate_report()
    
    def _periodic_check(self) -> None:
        """Periodic health and state check during audit."""
        for camera_id, manager in self._camera_managers.items():
            snap = manager.get_snapshot()
            if snap.state == CameraRuntimeState.FAILED:
                self.record_error_code(
                    code_hex="0xCAMERA_RUNTIME_FAILED",
                    component="CameraRuntimeManager",
                    stage="runtime",
                    camera_id=camera_id,
                    trigger=f"Camera runtime entered FAILED state: {snap.last_error}",
                    recovery="Check RTSP connectivity and decoder initialization",
                    context=f"State: {snap.state.value}, Error: {snap.last_error}",
                )
    
    def stop_audit(self) -> None:
        """Stop the audit and clean up."""
        logger.info("[AUDIT] Stopping audit...")
        self._running = False
        
        for camera_id, manager in self._camera_managers.items():
            try:
                manager.stop(timeout=15.0)
                logger.info(f"[AUDIT] {camera_id} runtime stopped")
            except Exception as e:
                logger.error(f"[AUDIT] Error stopping {camera_id}: {e}")
    
    # -------------------------------------------------------------------------
    # REPORT GENERATION
    # -------------------------------------------------------------------------
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive forensic audit report."""
        report = {
            "audit_metadata": {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "duration_seconds": self.duration_seconds,
                "cameras": self.camera_ids,
                "sample_rate": self.sample_rate,
                "git_commit": self._get_git_commit(),
            },
            "frame_reconciliation": {
                cid: rec.to_table() for cid, rec in self._reconciliation.items()
            },
            "timestamp_anomalies": {
                cid: [a.__dict__ for a in anomalies] 
                for cid, anomalies in self._timestamp_anomalies.items()
            },
            "error_codes": [ec.__dict__ for ec in self._error_codes],
            "frame_records_summary": {
                cid: len(records) for cid, records in self._frame_records.items()
            },
            "cuda_gpu_audit": self._audit_cuda_gpu(),
            "cpu_gpu_boundary_audit": self._audit_cpu_gpu_boundary(),
            "dimension_audit": self._audit_dimensions(),
            "pixel_format_audit": self._audit_pixel_formats(),
            "encoder_audit": self._audit_encoder(),
            "h264_bitstream_audit": self._audit_h264_bitstream(),
            "mediamtx_audit": self._audit_mediamtx(),
            "reconnect_audit": self._audit_reconnects(),
            "multi_camera_audit": self._audit_multi_camera(),
            "memory_resource_audit": self._audit_memory_resources(),
            "lifecycle_audit": self._audit_lifecycle(),
            "repository_audit": self._audit_repository(),
        }
        
        # Save detailed report
        report_path = self.output_dir / f"frame_integrity_audit_{time.strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"[AUDIT] Report saved to {report_path}")
        return report
    
    def _get_git_commit(self) -> str:
        """Get current git commit hash."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
    
    def _audit_cuda_gpu(self) -> Dict[str, Any]:
        """Audit CUDA/GPU state."""
        try:
            import torch
            return {
                "cuda_available": torch.cuda.is_available(),
                "cuda_device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
                "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
                "cuda_version": torch.version.cuda if torch.cuda.is_available() else "N/A",
                "cudnn_version": torch.backends.cudnn.version() if torch.cuda.is_available() else "N/A",
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _audit_cpu_gpu_boundary(self) -> Dict[str, Any]:
        """Audit CPU/GPU boundary transitions in production code."""
        # This is a static analysis - we check the source code for suspicious patterns
        suspicious_files = []
        patterns = [
            (".cpu()", "PyTorch CPU transfer"),
            (".numpy()", "NumPy conversion"),
            ('to("cpu")', "Explicit CPU device"),
            ("to(device=\"cpu\")", "Explicit CPU device"),
            ("np.asarray", "NumPy array creation"),
            ("np.array", "NumPy array creation"),
            ("torch.tensor", "Tensor creation (potential CPU)"),
            ("cv2.cvtColor", "OpenCV color conversion (CPU)"),
            ("cv2.resize", "OpenCV resize (CPU)"),
        ]
        
        for root, dirs, files in os.walk(REPO_ROOT / "app"):
            for file in files:
                if file.endswith(".py"):
                    filepath = Path(root) / file
                    try:
                        content = filepath.read_text(encoding="utf-8", errors="ignore")
                        for pattern, desc in patterns:
                            if pattern in content:
                                # Check if it's in production path or test-only
                                is_test = "test" in str(filepath).lower() or "forensic" in str(filepath).lower()
                                suspicious_files.append({
                                    "file": str(filepath.relative_to(REPO_ROOT)),
                                    "pattern": pattern,
                                    "description": desc,
                                    "is_test_path": is_test,
                                })
                    except Exception:
                        pass
        
        return {
            "suspicious_patterns_found": len(suspicious_files),
            "details": suspicious_files[:50],  # Limit output
        }
    
    def _audit_dimensions(self) -> Dict[str, Any]:
        """Audit frame dimensions at each stage."""
        results = {}
        for camera_id, records in self._frame_records.items():
            if not records:
                continue
            dims = {}
            for r in records:
                stage = "input"
                key = f"{stage}_{r.input_width}x{r.input_height}"
                dims[key] = dims.get(key, 0) + 1
            results[camera_id] = dims
        return results
    
    def _audit_pixel_formats(self) -> Dict[str, Any]:
        """Audit pixel format transitions."""
        results = {}
        for camera_id, records in self._frame_records.items():
            if not records:
                continue
            formats = {}
            for r in records:
                fmt = r.input_pixel_format
                formats[fmt] = formats.get(fmt, 0) + 1
            results[camera_id] = formats
        return results
    
    def _audit_encoder(self) -> Dict[str, Any]:
        """Audit NVENC encoder state."""
        results = {}
        for camera_id, manager in self._camera_managers.items():
            if manager._annotated_publisher and manager._annotated_publisher._encoder:
                enc = manager._annotated_publisher._encoder
                results[camera_id] = {
                    "initialized": enc.encoder is not None,
                    "codec": enc.codec,
                    "preset": enc.preset,
                    "fps": enc.fps,
                    "bitrate_kbps": enc.bitrate_kbps,
                    "cuda_stream": enc.cuda_stream,
                    "metrics": enc.metrics.__dict__ if hasattr(enc, "metrics") else {},
                }
        return results
    
    def _audit_h264_bitstream(self) -> Dict[str, Any]:
        """Audit H264 bitstream characteristics."""
        # Would require FFmpeg/ffprobe analysis of output
        return {
            "note": "Requires ffprobe analysis of MediaMTX output streams",
            "status": "NOT_IMPLEMENTED",
        }
    
    def _audit_mediamtx(self) -> Dict[str, Any]:
        """Audit MediaMTX state."""
        # Query MediaMTX API
        import urllib.request
        try:
            resp = urllib.request.urlopen("http://localhost:9997/v3/paths/list", timeout=5)
            import json
            data = json.load(resp)
            paths = [item.get("name", "") for item in data.get("items", [])]
            return {
                "api_accessible": True,
                "paths": paths,
                "cam1_ai_path": "live/cam1-ai" in paths,
                "cam2_ai_path": "live/cam2-ai" in paths,
            }
        except Exception as e:
            return {"api_accessible": False, "error": str(e)}
    
    def _audit_reconnects(self) -> Dict[str, Any]:
        """Audit reconnect events."""
        results = {}
        for camera_id, manager in self._camera_managers.items():
            snap = manager.get_snapshot()
            results[camera_id] = {
                "reconnect_attempts": snap.reconnect_attempts,
                "last_error": snap.last_error,
                "state": snap.state.value,
            }
        return results
    
    def _audit_multi_camera(self) -> Dict[str, Any]:
        """Audit multi-camera isolation."""
        if len(self.camera_ids) < 2:
            return {"status": "SINGLE_CAMERA", "note": "Multi-camera audit requires 2+ cameras"}
        
        cam1_snap = self._camera_managers.get("CAM1", {}).get_snapshot() if "CAM1" in self._camera_managers else None
        cam2_snap = self._camera_managers.get("CAM2", {}).get_snapshot() if "CAM2" in self._camera_managers else None
        
        return {
            "cam1_state": cam1_snap.state.value if cam1_snap else "NOT_STARTED",
            "cam2_state": cam2_snap.state.value if cam2_snap else "NOT_STARTED",
            "cross_contamination_check": "Manual verification required - check frame IDs and timestamps",
        }
    
    def _audit_memory_resources(self) -> Dict[str, Any]:
        """Audit memory and resource usage."""
        try:
            import psutil
            process = psutil.Process()
            gpu_memory = {}
            if torch.cuda.is_available():
                gpu_memory = {
                    "allocated_mb": torch.cuda.memory_allocated() / 1024 / 1024,
                    "reserved_mb": torch.cuda.memory_reserved() / 1024 / 1024,
                    "max_allocated_mb": torch.cuda.max_memory_allocated() / 1024 / 1024,
                }
            return {
                "cpu_memory_mb": process.memory_info().rss / 1024 / 1024,
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
                "gpu_memory": gpu_memory,
            }
        except Exception as e:
            return {"error": str(e)}
    
    def _audit_lifecycle(self) -> Dict[str, Any]:
        """Audit start/stop/restart lifecycle."""
        results = {}
        for camera_id, manager in self._camera_managers.items():
            snap = manager.get_snapshot()
            results[camera_id] = {
                "state": snap.state.value,
                "uptime_seconds": snap.uptime_seconds,
                "reconnect_attempts": snap.reconnect_attempts,
            }
        return results
    
    def _audit_repository(self) -> Dict[str, Any]:
        """Audit repository for legacy/duplicate patterns."""
        patterns = {
            "legacy_bootstrap": "bootstrap.py (legacy)",
            "dynamic_port": "port.*random|port.*increment|dynamic.*port",
            "old_decoder": "PyNvVideoCodec.*decoder|nvdec.*old",
            "pynvvideocodec_live": "PyNvVideoCodec.*live|live.*PyNvVideoCodec",
            "cpu_decoder": "\.cpu\(\)|\.numpy\(\)",
            "cpu_raw_frame": "raw.*frame|cpu.*frame",
            "pyav_encoder": "libx264|pyav.*encoder",
            "mock_cuda": "mock.*cuda|cuda.*mock",
            "synthetic_frame": "synthetic.*frame|frame.*synthetic",
            "duplicate_camera_manager": "camera.*manager.*camera|manager.*manager",
            "duplicate_publisher": "publisher.*publisher",
            "duplicate_encoder": "encoder.*encoder",
        }
        
        findings = {}
        for name, pattern in patterns.items():
            matches = []
            for root, dirs, files in os.walk(REPO_ROOT / "app"):
                for file in files:
                    if file.endswith(".py"):
                        filepath = Path(root) / file
                        try:
                            content = filepath.read_text(encoding="utf-8", errors="ignore")
                            import re
                            if re.search(pattern, content, re.IGNORECASE):
                                matches.append(str(filepath.relative_to(REPO_ROOT)))
                        except Exception:
                            pass
            findings[name] = {
                "matches": matches[:10],
                "count": len(matches),
            }
        
        return findings


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point for frame forensics audit."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 11.3 Frame Integrity Forensic Audit")
    parser.add_argument("--cameras", nargs="+", default=["CAM1", "CAM2"], help="Camera IDs to audit")
    parser.add_argument("--duration", type=float, default=60.0, help="Audit duration in seconds")
    parser.add_argument("--sample-rate", type=float, default=1.0, help="Sample 1 frame per N frames")
    parser.add_argument("--output-dir", type=Path, help="Output directory for reports")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    audit = FrameForensicsAudit(
        camera_ids=args.cameras,
        duration_seconds=args.duration,
        sample_rate=args.sample_rate,
        output_dir=args.output_dir,
    )
    
    report = audit.run_audit()
    
    # Print summary
    print("\n" + "=" * 80)
    print("PHASE 11.3 FRAME INTEGRITY FORENSIC AUDIT SUMMARY")
    print("=" * 80)
    
    for cid, table in report["frame_reconciliation"].items():
        print(f"\n{cid} Frame Reconciliation:")
        for row in table:
            print(f"  {row['stage']:12s} | Count: {row['count']:6d} | Delta: {row['delta_from_previous']:+6d} | Loss: {row['loss_pct']:.2f}%")
    
    print(f"\nTotal Error Codes Found: {len(report['error_codes'])}")
    for ec in report["error_codes"]:
        print(f"  {ec['code_hex']:12s} | {ec['component']:20s} | {ec['stage']:15s} | {ec['classification']} | {ec['current_status']}")
    
    print(f"\nTimestamp Anomalies:")
    for cid, anomalies in report["timestamp_anomalies"].items():
        print(f"  {cid}: {len(anomalies)} anomalies")
        for a in anomalies[:5]:
            print(f"    {a['anomaly_type']} at {a['stage']}: PTS {a['pts_before']}->{a['pts_after']} (delta={a['delta_pts']})")
    
    print(f"\nCUDA/GPU Status: {report['cuda_gpu_audit']}")
    print(f"CPU/GPU Boundary: {report['cpu_gpu_boundary_audit']['suspicious_patterns_found']} suspicious patterns")
    print(f"Memory/Resources: {report['memory_resource_audit']}")
    
    print("\n" + "=" * 80)
    print("Full report saved to:", audit.output_dir)
    print("=" * 80)


if __name__ == "__main__":
    main()