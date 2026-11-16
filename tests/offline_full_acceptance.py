"""
Autonomous Offline Full Acceptance Test Suite (Phase 3: Gates 1-4).

Executes 100% offline (no live RTSP streams or hardware cameras required):
- Gate 1: Graphify Integrity (0 broken links, 0 orphan DOM IDs, 0 legacy mismatches, 0 syntax/import errors)
- Gate 2: TensorRT & Vision Math (TensorRTExecutor init + CUDA sync, unletterbox, single-sigmoid [0, 1], pixel IoU)
- Gate 3: Tracker, Attendance & SQLite WAL (50 frames stationary + line crossing + 20 concurrent SQLite WAL writes)
- Gate 4: FastAPI IPC & WebSocket Loopback (< 50ms end-to-end delivery)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.runtime.cuda  # noqa: E402, F401 - register CUDA/TensorRT DLL directories on Windows
import torch  # noqa: E402


def gate_1_graphify_integrity() -> Dict[str, Any]:
    print("\n=== GATE 1: Graphify Full-Stack Integrity ===")
    from scripts.graphify_audit import run_audit

    report = run_audit()
    summary = report["summary"]
    print(f"Summary: {json.dumps(summary)}")

    assert summary["syntax_errors_count"] == 0, f"Syntax errors: {report['syntax_errors']}"
    assert summary["broken_imports_count"] == 0, f"Broken imports: {report['broken_imports']}"
    assert summary["broken_links_count"] == 0, f"Broken links: {report['broken_links']}"
    assert summary["orphan_dom_ids_count"] == 0, f"Orphan DOM IDs: {report['orphan_dom_ids']}"
    assert summary["legacy_variable_mismatches_count"] == 0, f"Legacy mismatches: {report['legacy_variable_mismatches']}"
    assert summary["passed"] is True
    print("[PASS] Gate 1 passed: 0 broken links, 0 orphan DOM IDs, 0 legacy mismatches, 0 syntax/import errors")
    return summary


def gate_2_tensorrt_and_vision_math() -> Dict[str, Any]:
    print("\n=== GATE 2: TensorRT & Vision Math ===")
    from pipeline_engine.inference.tensorrt_engine import TensorRTExecutor
    from pipeline_engine.inference.person_detection import YOLOPersonDetector, YOLOConfig
    from pipeline_engine.memory.gpu_frame import GPUFrame, PixelFormat, CUDAContext, letterbox_resize_cuda
    from pipeline_engine.tracking.tracker import Tracker, compute_iou

    assert torch.cuda.is_available(), "CUDA GPU is required for Gate 2"

    # 2.1 TensorRTExecutor initialization, CUDA stream sync, and destroy()
    engine_path = REPO_ROOT / "models" / "yolo" / "yolo11n_fp16.engine"
    assert engine_path.exists(), f"Missing TensorRT engine: {engine_path}"

    stream = torch.cuda.Stream(device=0)
    executor = TensorRTExecutor(str(engine_path), device_id=0, cuda_stream=stream)
    assert executor.initialize(), f"TensorRTExecutor failed: {executor._last_error}"
    input_name = executor._input_names[0]
    dummy_input = torch.rand((1, 3, 640, 640), dtype=torch.float32, device="cuda:0")
    outputs = executor.infer({input_name: dummy_input})
    assert outputs, "TensorRT inference returned empty outputs"
    for name, out_tensor in outputs.items():
        assert torch.isfinite(out_tensor).all(), f"Non-finite values in TensorRT output {name}"
    executor.destroy()
    assert executor._initialized is False
    print(f"[PASS] Gate 2.1: TensorRTExecutor init + CUDA sync + destroy OK ({engine_path.name})")

    # 2.2 Synthetic GPUFrame 3840x2160 letterbox + unletterboxing precision check
    gpu_frame = GPUFrame.create_empty("CAM1", frame_id=1, width=3840, height=2160, pixel_format=PixelFormat.NV12)
    assert gpu_frame.camera_id == "cam1", "GPUFrame.camera_id must normalize to lowercase"
    assert gpu_frame.frame_sequence == 1

    fake_img = torch.zeros((1, 3, 2160, 3840), dtype=torch.float32, device="cuda:0")
    resized, pad_info = letterbox_resize_cuda(fake_img, (640, 640))
    assert resized.shape == (1, 3, 640, 640)
    assert abs(pad_info["scale"] - (640.0 / 3840.0)) < 1e-6

    detector = YOLOPersonDetector(str(engine_path), config=YOLOConfig(confidence_threshold=0.4), device_id=0, cuda_stream=stream)
    # Test exact unletterboxing inverse
    # Original bbox: (1200, 540, 2400, 1620) in 3840x2160
    # scale = 1/6, pad_left = 0, pad_top = 140
    scale = pad_info["scale"]
    pad_left = pad_info["pad_left"]
    pad_top = pad_info["pad_top"]
    mx1, my1 = 1200 * scale + pad_left, 540 * scale + pad_top
    mx2, my2 = 2400 * scale + pad_left, 1620 * scale + pad_top
    ux1, uy1, ux2, uy2 = detector._convert_bbox_to_original(
        mx1, my1, mx2, my2, scale, pad_left, pad_top, pad_info["new_width"], pad_info["new_height"], 3840, 2160
    )
    assert abs(ux1 - 1200.0) < 1.0 and abs(uy1 - 540.0) < 1.0
    assert abs(ux2 - 2400.0) < 1.0 and abs(uy2 - 1620.0) < 1.0
    gpu_frame.release()
    print("[PASS] Gate 2.2: 4K letterbox_resize_cuda & exact unletterboxing verified")

    # 2.3 Single-sigmoid vs already-probability YOLO outputs check
    # Case A: Model already emits probabilities in [0, 1] (0.90 must NOT be sigmoided to ~0.71)
    raw_probs = torch.zeros((1, 84, 8400), dtype=torch.float32, device="cuda:0")
    raw_probs[0, 0, 0] = (mx1 + mx2) / 2.0
    raw_probs[0, 1, 0] = (my1 + my2) / 2.0
    raw_probs[0, 2, 0] = mx2 - mx1
    raw_probs[0, 3, 0] = my2 - my1
    raw_probs[0, 4, 0] = 0.90  # person class already probability
    dets_prob = detector._parse_outputs(raw_probs, 3840, 2160, pad_info, frame_id=7, camera_id="CAM1")
    assert len(dets_prob) == 1, f"Expected 1 detection, got {len(dets_prob)}"
    assert abs(dets_prob[0].confidence - 0.90) < 1e-4, f"Double-sigmoid detected! conf={dets_prob[0].confidence}"
    assert dets_prob[0].camera_id == "cam1" and dets_prob[0].frame_sequence == 7

    # Case B: Raw logits (contains values > 1.01 or < -0.01) -> single sigmoid applied cleanly into [0, 1]
    raw_logits = torch.full((1, 84, 8400), -5.0, dtype=torch.float32, device="cuda:0")
    raw_logits[0, 0, 0] = (mx1 + mx2) / 2.0
    raw_logits[0, 1, 0] = (my1 + my2) / 2.0
    raw_logits[0, 2, 0] = mx2 - mx1
    raw_logits[0, 3, 0] = my2 - my1
    raw_logits[0, 4, 0] = 2.5  # sigmoid(2.5) ~= 0.9241
    dets_logit = detector._parse_outputs(raw_logits, 3840, 2160, pad_info, frame_id=8, camera_id="cam1")
    assert len(dets_logit) == 1
    assert 0.92 < dets_logit[0].confidence < 0.93, f"Expected sigmoid(2.5)~0.924, got {dets_logit[0].confidence}"
    assert 0.0 <= dets_logit[0].confidence <= 1.0
    print("[PASS] Gate 2.3: Single-sigmoid probability bounds [0, 1] verified")

    # 2.4 Pixel-space IoU verification
    b1 = (1000.0, 500.0, 1400.0, 1500.0)  # area 400 x 1000 = 400,000
    b2 = (1200.0, 500.0, 1600.0, 1500.0)  # overlap 200 x 1000 = 200,000, union = 600,000 -> IoU = 1/3
    iou = compute_iou(b1, b2)
    assert abs(iou - (1.0 / 3.0)) < 1e-5, f"Expected IoU 0.3333, got {iou}"
    iou_mat = Tracker._calculate_iou_batch(np.array([b1]), np.array([b2]))
    assert abs(float(iou_mat[0, 0]) - (1.0 / 3.0)) < 1e-5
    print("[PASS] Gate 2.4: Pixel-space IoU calculation verified (IoU=0.3333)")

    return {"trt_engine": engine_path.name, "iou": round(iou, 4)}


def gate_3_tracker_attendance_and_wal() -> Dict[str, Any]:
    print("\n=== GATE 3: Tracker (50 frames), Attendance Line Crossing & SQLite WAL ===")
    from pipeline_engine.inference.person_detection import PersonDetection
    from pipeline_engine.inference.face_detection import FaceDetection
    from pipeline_engine.inference.face_recognition import FaceEmbedding
    from pipeline_engine.tracking.tracker import Tracker, TrackingConfig
    from pipeline_engine.attendance.attendance_engine import (
        AttendanceEngine,
        AttendanceStore,
        CrossingDirection,
        CrossingEvent,
    )
    from app.attendance.contract import AttendanceRecord, IdentityCertainty
    from app.attendance.storage import AttendanceStorage, StorageConfig

    tmp_dir = Path(tempfile.mkdtemp(prefix="gate3_wal_"))
    try:
        # 3.1 Run 50 synthetic frames: 1 stationary person + 1 person gradually crossing line
        # Create a mock recognizer so Track receives canonical identity_candidate ("Nguyen Van A")
        class MockRecognizer:
            _enrollment_metadata = {"HS001": {"name": "Nguyen Van A"}}

            def identify(self, emb, top_k=1):
                return [("HS001", 0.91)]

        tracker = Tracker(config=TrackingConfig(min_iou_threshold=0.25), recognizer=MockRecognizer())
        att_engine = AttendanceEngine()
        att_engine._store = AttendanceStore(str(tmp_dir / "events.db"))
        # Configure cam1 line horizontally at y=1620 (side_b_to_a_in or y=1700->1500 with side_a_to_b_in):
        # Verify gradual multi-frame crossing (moving 10px per frame across y=1620 from y=1750 to y=1260)
        att_engine.update_camera_line("cam1", (576.0, 1620.0), (3264.0, 1620.0), "side_a_to_b_in")

        stationary_tid = None
        mover_tid = None
        crossing_events: List[CrossingEvent] = []
        base_ts = 1730000000.0

        for frame_idx in range(1, 51):
            ts = base_ts + frame_idx * 0.033
            # Track A: Stationary sitting person around (500, 800, 700, 1300) -> center (600, 1050)
            det_stat = PersonDetection(
                bbox=(500.0 + (frame_idx % 2), 800.0, 700.0 + (frame_idx % 2), 1300.0),
                confidence=0.95,
                detection_id=f"stat_{frame_idx}",
                frame_index=frame_idx,
                source_id="cam1",
            )
            # Track B: Moving slowly upward from center y=1750 -> y=1260 (-10px/frame, crosses y=1620 at frame 14!)
            cy = 1750.0 - (frame_idx - 1) * 10.0
            det_move = PersonDetection(
                bbox=(1800.0, cy - 200.0, 2000.0, cy + 200.0),
                confidence=0.94,
                detection_id=f"move_{frame_idx}",
                frame_index=frame_idx,
                source_id="cam1",
            )
            face_move = FaceDetection(
                bbox=(1850.0, cy - 160.0, 1950.0, cy - 80.0),
                confidence=0.96,
                landmarks5=[(1880.0, cy - 130.0), (1920.0, cy - 130.0), (1900.0, cy - 110.0), (1880.0, cy - 95.0), (1920.0, cy - 95.0)],
                detection_id=f"face_{frame_idx}",
                frame_index=frame_idx,
                source_id="cam1",
            )
            emb_move = FaceEmbedding(
                embedding=torch.ones(512),
                raw_embedding=torch.ones(512),
                raw_norm=1.0,
                inference_time_ms=1.0,
                detection_id=face_move.detection_id,
                frame_index=frame_idx,
                source_id="cam1",
            )

            res = tracker.process_frame(
                person_detections=[det_stat, det_move],
                face_detections=[face_move],
                face_embeddings={face_move.detection_id: emb_move},
                body_embeddings={},
                camera_id="CAM1",
                timestamp=ts,
            )
            assert res.camera_id == "cam1"
            assert res.frame_sequence == frame_idx

            for t in res.get_active_tracks():
                if t.center[0] < 1000:
                    stationary_tid = t.track_id
                    if frame_idx == 50:
                        assert t.is_stationary(), f"Stationary track did not satisfy is_stationary(): age={t.age}, prev={t._prev_center}, cur={t.center}"
                else:
                    mover_tid = t.track_id

            evs = att_engine.process_tracks(res)
            crossing_events.extend(evs)

        assert stationary_tid is not None and mover_tid is not None and stationary_tid != mover_tid
        assert len(crossing_events) == 1, f"Expected exactly 1 IN crossing event for gradual trajectory, got {len(crossing_events)}"
        ce = crossing_events[0]
        assert ce.direction == CrossingDirection.IN
        assert ce.camera_id == "cam1"
        assert ce.identity_candidate == "Nguyen Van A", f"Unexpected identity_candidate: {ce.identity_candidate}"
        cam_counts = att_engine.get_camera_counts("cam1")
        assert cam_counts["in"] == 1 and cam_counts["out"] == 0, f"Unexpected counts: {cam_counts}"
        print(f"[PASS] Gate 3.1: 50 frames stationary persisted (track={stationary_tid}) + multi-frame line crossing IN (identity={ce.identity_candidate})")

        # 3.2 20 Concurrent threads writing SQLite WAL simultaneously (AttendanceStore & AttendanceStorage)
        store = AttendanceStore(str(tmp_dir / "concurrent_events.db"))
        storage = AttendanceStorage(StorageConfig(database_path=tmp_dir / "concurrent_records.db"))
        errors: List[str] = []
        barrier = threading.Barrier(20)

        def worker_write(idx: int):
            try:
                barrier.wait(timeout=5.0)
                ev = CrossingEvent(
                    event_id=f"CONC-CE-{idx}",
                    camera_id="CAM1",
                    track_id=idx,
                    direction=CrossingDirection.IN,
                    crossing_point=(1900.0, 1620.0),
                    timestamp=base_ts + idx,
                    frame_index=idx,
                    previous_position=(1900.0, 1700.0),
                    current_position=(1900.0, 1540.0),
                    person_id=f"HS{idx:03d}",
                    person_name=f"Student {idx}",
                    identity_confidence=0.92,
                )
                ok_store = store.store_event(ev)
                if not ok_store:
                    errors.append(f"store_event returned False for {idx}")

                rec = AttendanceRecord(
                    attendance_record_id=f"AR-CONC-{idx}",
                    identity_certainty=IdentityCertainty.KNOWN,
                    identity_candidate=f"Student {idx}",
                    identity_confidence=0.92,
                    direction=CrossingDirection.IN,
                    event_timestamp=base_ts + idx,
                    event_frame_index=idx,
                    camera_id="cam1",
                    local_track_id=str(idx),
                    source_raw_event_id=f"RAW-{idx}",
                    source_resolution_id=f"RES-{idx}",
                    previous_state="outside",
                    new_state="inside",
                )
                ok_storage = storage.insert(rec)
                if not ok_storage:
                    errors.append(f"storage.insert returned False for {idx}")
            except Exception as exc:
                errors.append(f"Thread {idx} exception: {exc}")

        threads = [threading.Thread(target=worker_write, args=(i,)) for i in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=15.0)

        storage.close()
        assert not errors, f"Concurrent SQLite WAL write failures: {errors}"
        stored_events = store.get_events(limit=100)
        assert len(stored_events) == 20, f"Expected 20 stored events, got {len(stored_events)}"
        print("[PASS] Gate 3.2: 20 concurrent SQLite WAL threads succeeded with 0 database is locked errors")
        return {"crossings": len(crossing_events), "concurrent_writes": len(stored_events)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def gate_4_fastapi_ipc_and_ws_loopback() -> Dict[str, Any]:
    print("\n=== GATE 4: FastAPI IPC -> WebSocket Loopback (< 50ms) ===")
    import httpx
    import uvicorn
    import websockets
    from app.main import app

    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until server starts accepting connections
    deadline = time.perf_counter() + 10.0
    while not server.started:
        assert time.perf_counter() < deadline, "Uvicorn failed to start within 10s"
        time.sleep(0.05)

    async def run_loopback() -> float:
        ws_url = f"ws://127.0.0.1:{port}/api/v1/stream/metadata/cam1?api_key=dev_admin_key_2026"
        ingest_url = f"http://127.0.0.1:{port}/api/v1/stream/metadata/ingest"

        canonical_payload = {
            "camera_id": "cam1",
            "frame_sequence": 100,
            "timestamp": time.time(),
            "persons": [
                {
                    "track_id": 1,
                    "bbox": [0.22, 0.18, 0.58, 0.88],
                    "confidence": 0.94,
                    "identity_candidate": "Nguyen Van A",
                    "identity_confidence": 0.89,
                    "state": "active",
                }
            ],
            "counts": {"in": 1, "out": 0},
        }

        async def recv_metadata(ws) -> Dict[str, Any]:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                parsed = json.loads(raw)
                if parsed.get("type") == "metadata":
                    return parsed

        async with websockets.connect(ws_url) as ws:
            welcome_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            welcome = json.loads(welcome_raw)
            assert welcome["type"] == "welcome" and welcome["camera_id"] == "cam1"

            async with httpx.AsyncClient(timeout=2.0) as client:
                # Warm up broadcaster/HTTP client once before latency measurement
                warm_resp = await client.post(ingest_url, json=canonical_payload)
                assert warm_resp.status_code == 200
                warm_msg = await recv_metadata(ws)
                assert warm_msg["data"]["frame_sequence"] == 100

                # Measure canonical payload round-trip latency
                canonical_payload["frame_sequence"] = 101
                t0 = time.perf_counter()
                resp = await client.post(ingest_url, json=canonical_payload)
                assert resp.status_code == 200
                msg = await recv_metadata(ws)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert msg["type"] == "metadata"
        data = msg["data"]
        assert data["camera_id"] == "cam1"
        assert data["frame_sequence"] == 101
        assert data["counts"] == {"in": 1, "out": 0}
        assert len(data["persons"]) == 1
        p = data["persons"][0]
        assert p["track_id"] == 1
        assert p["bbox"] == [0.22, 0.18, 0.58, 0.88]
        assert abs(p["confidence"] - 0.94) < 1e-3
        assert p["identity_candidate"] == "Nguyen Van A"
        assert abs(p["identity_confidence"] - 0.89) < 1e-3
        assert p["state"] == "active"
        assert elapsed_ms < 50.0, f"IPC -> WS loopback exceeded 50ms: {elapsed_ms:.2f}ms"
        return elapsed_ms

    try:
        latency_ms = asyncio.run(run_loopback())
        print(f"[PASS] Gate 4 passed: IPC -> WS canonical loopback delivered in {latency_ms:.2f}ms (< 50ms)")
        return {"loopback_ms": round(latency_ms, 2), "port": port}
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


def main() -> int:
    start = time.perf_counter()
    results = {
        "gate_1": gate_1_graphify_integrity(),
        "gate_2": gate_2_tensorrt_and_vision_math(),
        "gate_3": gate_3_tracker_attendance_and_wal(),
        "gate_4": gate_4_fastapi_ipc_and_ws_loopback(),
    }
    total_s = time.perf_counter() - start
    print(f"\nALL OFFLINE ACCEPTANCE GATES (1-4) PASSED in {total_s:.2f}s")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
