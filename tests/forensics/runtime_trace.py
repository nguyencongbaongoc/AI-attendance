#!/usr/bin/env python3
"""
Phase 11.3 — Runtime Trace Tool.
Real-time tracing of frame flow through the canonical pipeline with
timestamp correlation, latency measurement, and anomaly detection.
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
from typing import Any, Callable, Dict, List, Optional, Set

import numpy as np

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.config.settings import load_settings
from app.data.frame import CanonicalFrame
from app.streaming.camera_runtime_manager import create_camera_runtime_manager
from app.streaming.health import StreamHealthMonitor, create_health_monitor
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract

logger = logging.getLogger(__name__)


@dataclass
class TraceEvent:
    """Single trace event in the pipeline."""
    trace_id: str
    camera_id: str
    stage: str  # input, decode, preprocess, ai, annotation, contract, encode, publish, output
    timestamp: float
    frame_index: int
    pts: int
    dts: int
    width: int
    height: int
    pixel_format: str
    latency_us: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameTrace:
    """Complete trace for a single frame across all stages."""
    trace_id: str
    camera_id: str
    events: List[TraceEvent] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    total_latency_us: float = 0.0
    anomalies: List[str] = field(default_factory=list)
    
    def add_event(self, event: TraceEvent) -> None:
        self.events.append(event)
        if not self.start_time or event.timestamp < self.start_time:
            self.start_time = event.timestamp
        if not self.end_time or event.timestamp > self.end_time:
            self.end_time = event.timestamp
        self.total_latency_us = (self.end_time - self.start_time) * 1_000_000
    
    def get_stage_latency(self, from_stage: str, to_stage: str) -> float:
        """Get latency between two stages in microseconds."""
        from_event = next((e for e in self.events if e.stage == from_stage), None)
        to_event = next((e for e in self.events if e.stage == to_stage), None)
        if from_event and to_event:
            return (to_event.timestamp - from_event.timestamp) * 1_000_000
        return -1.0


class PipelineTracer:
    """
    Real-time pipeline tracer for frame flow analysis.
    
    Instruments the canonical pipeline to trace frame identity,
    timestamps, and latency at each stage.
    """
    
    STAGES = [
        "input",
        "decode", 
        "preprocess",
        "ai",
        "annotation",
        "contract",
        "encode",
        "publish",
        "output",
    ]
    
    def __init__(
        self,
        camera_ids: List[str] = None,
        sample_rate: int = 1,  # Trace 1 in N frames
        max_traces: int = 1000,
        output_dir: Path = None,
    ):
        self.camera_ids = camera_ids or ["CAM1", "CAM2"]
        self.sample_rate = sample_rate
        self.max_traces = max_traces
        self.output_dir = output_dir or REPO_ROOT / "artifacts" / "phase11" / "forensics" / "traces"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self._running = False
        self._traces: Dict[str, FrameTrace] = {}
        self._trace_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._frame_counters: Dict[str, int] = {cid: 0 for cid in self.camera_ids}
        self._sample_counters: Dict[str, int] = {cid: 0 for cid in self.camera_ids}
        self._active_trace_ids: Dict[str, str] = {}  # camera_id -> current trace_id
        
        # Pipeline components
        self._camera_managers: Dict[str, Any] = {}
        self._health_monitor: Optional[StreamHealthMonitor] = None
        
        # Statistics
        self._stats: Dict[str, Dict[str, Any]] = {cid: {
            "traces_started": 0,
            "traces_completed": 0,
            "traces_dropped": 0,
            "stage_counts": {stage: 0 for stage in self.STAGES},
            "stage_latencies_us": {stage: [] for stage in self.STAGES},
            "anomalies": 0,
        } for cid in self.camera_ids}
        
        # Threading
        self._processor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def instrument_pipeline(self, camera_id: str, manager: Any) -> None:
        """Instrument a camera runtime manager for tracing."""
        if not manager:
            return
        
        # Instrument ingestion worker (input -> decode)
        if manager._ingestion_worker:
            original_callback = manager._ingestion_worker._frame_callback
            
            def traced_callback(frame: CanonicalFrame):
                self._on_frame_stage(camera_id, "input", frame)
                self._on_frame_stage(camera_id, "decode", frame)
                if original_callback:
                    original_callback(frame)
            
            manager._ingestion_worker._frame_callback = traced_callback
        
        # Instrument detection pipeline (preprocess -> ai -> annotation)
        if manager._detection_pipeline:
            original_process = manager._detection_pipeline.process_frame
            
            def traced_process(frame: CanonicalFrame):
                self._on_frame_stage(camera_id, "preprocess", frame)
                original_process(frame)
                self._on_frame_stage(camera_id, "ai", frame)
                self._on_frame_stage(camera_id, "annotation", frame)
            
            manager._detection_pipeline.process_frame = traced_process
        
        # Instrument publisher (contract -> encode -> publish -> output)
        if manager._annotated_publisher:
            original_submit = manager._annotated_publisher.submit
            
            def traced_submit(frame_data: GPUFrameContract, detections=None, lines=None, regions=None):
                self._on_frame_contract_stage(camera_id, "contract", frame_data)
                self._on_frame_contract_stage(camera_id, "encode", frame_data)
                result = original_submit(frame_data, detections, lines, regions)
                self._on_frame_contract_stage(camera_id, "publish", frame_data)
                self._on_frame_contract_stage(camera_id, "output", frame_data)
                return result
            
            manager._annotated_publisher.submit = traced_submit
        
        logger.info(f"[TRACE] Instrumented pipeline for {camera_id}")
    
    def _on_frame_stage(self, camera_id: str, stage: str, frame: CanonicalFrame) -> None:
        """Record a trace event for a frame at a pipeline stage."""
        if not self._should_sample(camera_id):
            return
        
        trace_id = self._get_or_create_trace_id(camera_id)
        if not trace_id:
            return
        
        event = TraceEvent(
            trace_id=trace_id,
            camera_id=camera_id,
            stage=stage,
            timestamp=time.time(),
            frame_index=frame.metadata.frame_index,
            pts=frame.metadata.pts or -1,
            dts=frame.metadata.dts or -1,
            width=frame.width,
            height=frame.height,
            pixel_format=frame.metadata.pixel_format.value if frame.metadata.pixel_format else "unknown",
            metadata={
                "source_id": frame.metadata.source_id,
                "time_base": str(frame.metadata.time_base) if frame.metadata.time_base else "",
            }
        )
        
        self._trace_queue.put(event)
        self._stats[camera_id]["stage_counts"][stage] += 1
    
    def _on_frame_contract_stage(self, camera_id: str, stage: str, frame_data: GPUFrameContract) -> None:
        """Record a trace event for GPUFrameContract stages."""
        if not self._should_sample(camera_id):
            return
        
        trace_id = self._get_or_create_trace_id(camera_id)
        if not trace_id:
            return
        
        event = TraceEvent(
            trace_id=trace_id,
            camera_id=camera_id,
            stage=stage,
            timestamp=time.time(),
            frame_index=frame_data.frame_id,
            pts=frame_data.pts or -1,
            dts=frame_data.dts or -1,
            width=frame_data.width,
            height=frame_data.height,
            pixel_format=frame_data.pixel_format,
            metadata={
                "cuda_memory_ref": str(frame_data.cuda_memory_ref is not None),
                "device_id": frame_data.device_id,
            }
        )
        
        self._trace_queue.put(event)
        self._stats[camera_id]["stage_counts"][stage] += 1
    
    def _should_sample(self, camera_id: str) -> bool:
        """Determine if this frame should be traced based on sample rate."""
        self._sample_counters[camera_id] += 1
        return self._sample_counters[camera_id] % self.sample_rate == 0
    
    def _get_or_create_trace_id(self, camera_id: str) -> Optional[str]:
        """Get or create a trace ID for the current frame."""
        if camera_id not in self._active_trace_ids:
            if len(self._traces) >= self.max_traces:
                # Drop oldest trace
                oldest = min(self._traces.keys(), key=lambda k: self._traces[k].start_time)
                del self._traces[oldest]
                self._stats[camera_id]["traces_dropped"] += 1
            
            trace_id = f"{camera_id}_{uuid.uuid4().hex[:8]}"
            self._traces[trace_id] = FrameTrace(
                trace_id=trace_id,
                camera_id=camera_id,
            )
            self._active_trace_ids[camera_id] = trace_id
            self._stats[camera_id]["traces_started"] += 1
            return trace_id
        
        return self._active_trace_ids[camera_id]
    
    def start(self) -> None:
        """Start the trace processor."""
        self._running = True
        self._stop_event.clear()
        self._processor_thread = threading.Thread(target=self._process_traces, daemon=True)
        self._processor_thread.start()
        logger.info("[TRACE] Pipeline tracer started")
    
    def stop(self) -> None:
        """Stop the trace processor."""
        self._running = False
        self._stop_event.set()
        if self._processor_thread:
            self._processor_thread.join(timeout=5.0)
        logger.info("[TRACE] Pipeline tracer stopped")
    
    def _process_traces(self) -> None:
        """Process trace events from the queue."""
        while not self._stop_event.is_set():
            try:
                event = self._trace_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            trace = self._traces.get(event.trace_id)
            if trace:
                trace.add_event(event)
                
                # Check for anomalies
                self._check_anomalies(trace, event)
                
                # If this is the output stage, mark trace as complete
                if event.stage == "output":
                    self._stats[event.camera_id]["traces_completed"] += 1
                    # Keep trace for a bit longer for analysis, then clean up
                    # In production, we'd use a proper cleanup strategy
    
    def _check_anomalies(self, trace: FrameTrace, event: TraceEvent) -> None:
        """Check for anomalies in the trace."""
        anomalies = []
        
        # Check for missing stages
        stages_seen = {e.stage for e in trace.events}
        expected_stages = set(self.STAGES[:self.STAGES.index(event.stage) + 1])
        missing = expected_stages - stages_seen
        if missing:
            anomalies.append(f"missing_stages: {missing}")
        
        # Check for timestamp regression
        if len(trace.events) > 1:
            prev_event = trace.events[-2]
            if event.timestamp < prev_event.timestamp:
                anomalies.append(f"timestamp_regression: {prev_event.stage} -> {event.stage}")
        
        # Check for PTS/DTS anomalies
        if event.pts > 0 and trace.events:
            for prev_event in trace.events:
                if prev_event.pts > 0 and event.pts < prev_event.pts:
                    anomalies.append(f"pts_regression: {prev_event.pts} -> {event.pts}")
                    break
        
        # Check for dimension changes
        if trace.events:
            first_event = trace.events[0]
            if event.width != first_event.width or event.height != first_event.height:
                anomalies.append(f"dimension_change: {first_event.width}x{first_event.height} -> {event.width}x{event.height}")
        
        if anomalies:
            trace.anomalies.extend(anomalies)
            self._stats[trace.camera_id]["anomalies"] += len(anomalies)
            logger.warning(f"[TRACE] Anomalies in {trace.trace_id}: {anomalies}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get tracing statistics."""
        return {
            "camera_stats": self._stats,
            "active_traces": len(self._traces),
            "queue_size": self._trace_queue.qsize(),
        }
    
    def export_traces(self, output_path: Path = None) -> List[Dict[str, Any]]:
        """Export traces to JSON."""
        output = []
        for trace in self._traces.values():
            if trace.events:
                trace_data = {
                    "trace_id": trace.trace_id,
                    "camera_id": trace.camera_id,
                    "start_time": trace.start_time,
                    "end_time": trace.end_time,
                    "total_latency_us": trace.total_latency_us,
                    "anomalies": trace.anomalies,
                    "events": [
                        {
                            "stage": e.stage,
                            "timestamp": e.timestamp,
                            "frame_index": e.frame_index,
                            "pts": e.pts,
                            "dts": e.dts,
                            "width": e.width,
                            "height": e.height,
                            "pixel_format": e.pixel_format,
                            "latency_us": e.latency_us,
                        }
                        for e in trace.events
                    ],
                    "stage_latencies": {
                        f"{self.STAGES[i]}->{self.STAGES[i+1]}": trace.get_stage_latency(
                            self.STAGES[i], self.STAGES[i+1]
                        )
                        for i in range(len(self.STAGES) - 1)
                    },
                }
                output.append(trace_data)
        
        if output_path:
            import json
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2, default=str)
            logger.info(f"[TRACE] Exported {len(output)} traces to {output_path}")
        
        return output


def run_tracer(
    cameras: List[str] = None,
    duration: float = 30.0,
    sample_rate: int = 10,
    output_dir: Path = None,
) -> Dict[str, Any]:
    """Run the pipeline tracer for a specified duration."""
    import argparse
    
    tracer = PipelineTracer(
        camera_ids=cameras or ["CAM1", "CAM2"],
        sample_rate=sample_rate,
        output_dir=output_dir,
    )
    
    settings = load_settings()
    health_monitor = create_health_monitor()
    
    # Start camera runtimes
    for camera_id in tracer.camera_ids:
        if camera_id == "CAM1" and not settings.cameras.cam1_enabled:
            continue
        if camera_id == "CAM2" and not settings.cameras.cam2_enabled:
            continue
        
        manager = create_camera_runtime_manager(
            camera_id=camera_id,
            settings=settings,
            health_monitor=health_monitor,
        )
        tracer._camera_managers[camera_id] = manager
        
        if manager.start(wait_ready=True, ready_timeout=120.0):
            tracer.instrument_pipeline(camera_id, manager)
            logger.info(f"[TRACE] {camera_id} runtime started and instrumented")
        else:
            logger.error(f"[TRACE] Failed to start {camera_id}")
    
    tracer.start()
    
    try:
        logger.info(f"[TRACE] Running trace for {duration} seconds...")
        time.sleep(duration)
    except KeyboardInterrupt:
        logger.info("[TRACE] Interrupted")
    finally:
        tracer.stop()
        
        # Stop camera runtimes
        for camera_id, manager in tracer._camera_managers.items():
            manager.stop(timeout=15.0)
    
    # Export traces
    trace_output = tracer.output_dir / f"pipeline_traces_{time.strftime('%Y%m%d_%H%M%S')}.json"
    traces = tracer.export_traces(trace_output)
    
    stats = tracer.get_statistics()
    
    return {
        "traces": traces,
        "statistics": stats,
        "output_file": str(trace_output),
    }


if __name__ == "__main__":
    import argparse
    import time
    
    parser = argparse.ArgumentParser(description="Phase 11.3 Pipeline Tracer")
    parser.add_argument("--cameras", nargs="+", default=["CAM1", "CAM2"])
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--sample-rate", type=int, default=10)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--log-level", default="INFO")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    result = run_tracer(
        cameras=args.cameras,
        duration=args.duration,
        sample_rate=args.sample_rate,
        output_dir=args.output_dir,
    )
    
    print("\n" + "=" * 80)
    print("PIPELINE TRACE SUMMARY")
    print("=" * 80)
    
    for cam, stats in result["statistics"]["camera_stats"].items():
        print(f"\n{cam}:")
        print(f"  Traces started: {stats['traces_started']}")
        print(f"  Traces completed: {stats['traces_completed']}")
        print(f"  Traces dropped: {stats['traces_dropped']}")
        print(f"  Anomalies: {stats['anomalies']}")
        print(f"  Stage counts: {stats['stage_counts']}")
    
    print(f"\nTotal traces exported: {len(result['traces'])}")
    print(f"Output: {result['output_file']}")
    print("=" * 80)