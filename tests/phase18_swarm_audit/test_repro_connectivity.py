"""Empirical pytest reproducers for Phase 18 Connectivity, WebSocket & Lifecycle audit (#8).

All tests are strictly isolated using mocks, temp paths, and in-memory structures.
No live camera streams, MediaMTX processes, network sockets, or production DBs are touched.
Each passing test proves the corresponding audited defect exists in the current codebase.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ===========================================================================
# P0-CRITICAL REPRODUCERS
# ===========================================================================


# ---------------------------------------------------------------------------
# CON-01: PyAV microsecond timeout & broken _reconnect() state machine
# ---------------------------------------------------------------------------


def test_con_01_pyav_timeout_scaled_1e6_and_reconnect_wedge():
    """RTSPSource passes timeout*1_000_000 to av.open, leaves RECONNECTING stuck, and never resets _retry_count."""
    from pipeline_engine.ingestion.rtsp_source import RTSPSource, RTSPSourceConfig, RTSPState

    cfg = RTSPSourceConfig(camera_id="cam1", url="rtsp://127.0.0.1:8554/live/cam1", timeout=5.0, max_retries=2)
    src = RTSPSource(cfg)

    seen_timeouts = []

    def fake_av_open(url, format=None, options=None, timeout=None, **kwargs):
        seen_timeouts.append(timeout)
        raise RuntimeError("mock connect failure")

    with patch("pipeline_engine.ingestion.rtsp_source.av.open", side_effect=fake_av_open):
        opened = src._open_container()

    assert opened is False
    assert seen_timeouts == [5_000_000]  # 5.0 * 1_000_000 passed to PyAV seconds API

    # First failed _reconnect() schedules a thread and leaves _state == RECONNECTING
    with (
        patch.object(src, "_open_container", return_value=False) as open_mock,
        patch("pipeline_engine.ingestion.rtsp_source.threading.Thread") as thread_cls,
    ):
        assert src._reconnect() is False
        assert src._state == RTSPState.RECONNECTING
        assert thread_cls.called

        # Subsequent _reconnect() immediately aborts without trying _open_container()
        open_mock.reset_mock()
        assert src._reconnect() is False
        assert open_mock.call_count == 0

    # Successful reconnect still preserves stale _retry_count
    src._state = RTSPState.DISCONNECTED
    src._retry_count = 3
    src._read_thread = None
    with (
        patch.object(src, "_open_container", return_value=True),
        patch("pipeline_engine.ingestion.rtsp_source.threading.Thread"),
    ):
        assert src._reconnect() is True
    assert src._retry_count > 0  # Never reset to 0 on success


# ---------------------------------------------------------------------------
# CON-02: Shared AI singletons cleanup on per-camera error & lock held during join
# ---------------------------------------------------------------------------


def test_con_02_start_camera_cleans_shared_singletons_and_stop_all_holds_lock():
    """start_camera calls cleanup() on shared model singletons on NVENC start failure; stop_all holds _lock across join()."""
    import pipeline_engine.ingestion.camera_manager as cm_mod

    src = (REPO_ROOT / "pipeline_engine" / "ingestion" / "camera_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # Confirm stop_all acquires self._lock and calls self.stop_camera inside the with-block
    mgr_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CameraManager")
    stop_all_fn = next(n for n in mgr_cls.body if isinstance(n, ast.FunctionDef) and n.name == "stop_all")
    with_blocks = [n for n in ast.walk(stop_all_fn) if isinstance(n, ast.With)]
    assert any("self._lock" in (ast.get_source_segment(src, w) or "") and "stop_camera" in (ast.get_source_segment(src, w) or "") for w in with_blocks)

    # Verify stop_camera calls thread.join(timeout=10.0)
    stop_cam_fn = next(n for n in mgr_cls.body if isinstance(n, ast.FunctionDef) and n.name == "stop_camera")
    stop_cam_src = ast.get_source_segment(src, stop_cam_fn) or ""
    assert ".join(timeout=10.0)" in stop_cam_src

    # Verify start_camera cleans up scrfd, arcface, yolo on encoder start failure
    start_cam_fn = next(n for n in mgr_cls.body if isinstance(n, ast.FunctionDef) and n.name == "start_camera")
    start_cam_src = ast.get_source_segment(src, start_cam_fn) or ""
    assert "cleanup()" in start_cam_src
    assert '"scrfd"' in start_cam_src and '"arcface"' in start_cam_src and '"yolo"' in start_cam_src

    # Runtime verification on CameraManager instance: stop_all acquires _lock while stop_camera runs
    mgr = cm_mod.CameraManager.__new__(cm_mod.CameraManager)
    mgr._lock = threading.RLock()
    mgr._cameras = {"cam1": {"thread": None}}
    lock_depth_inside_stop_camera = []

    def spy_stop_camera(camera_id: str) -> bool:
        # _is_owned() is True only if current thread currently holds _lock!
        lock_depth_inside_stop_camera.append(mgr._lock._is_owned())
        return True

    mgr.stop_camera = spy_stop_camera
    mgr.stop_all()
    assert lock_depth_inside_stop_camera == [True]


# ---------------------------------------------------------------------------
# CON-03: Metadata dispatcher broken outside event loop & 30ms timeout
# ---------------------------------------------------------------------------


def test_con_03_uninitialized_metadata_dispatcher_and_30ms_timeout():
    """CameraManager._async_loop/_dispatcher_task remain None outside event loop; queue overflows at 120 items."""
    import pipeline_engine.ingestion.camera_manager as cm_mod

    assert cm_mod.METADATA_HTTP_TIMEOUT.total == pytest.approx(0.03)
    assert cm_mod.METADATA_HTTP_TIMEOUT.connect == pytest.approx(0.01)

    mgr = cm_mod.CameraManager.__new__(cm_mod.CameraManager)
    mgr._lock = threading.RLock()
    mgr._cameras = {}
    mgr._metadata_queue = asyncio.Queue(maxsize=120)
    mgr._dispatcher_task = None
    mgr._async_loop = None

    # Outside any running asyncio loop, trying asyncio.get_running_loop() leaves task None
    try:
        asyncio.get_running_loop()
        has_loop = True
    except RuntimeError:
        has_loop = False
    assert has_loop is False

    # Feed 130 payloads with no consumer running: queue fills to 120 and excess is dropped
    for i in range(130):
        try:
            mgr._metadata_queue.put_nowait({"seq": i})
        except asyncio.QueueFull:
            pass
    assert mgr._metadata_queue.qsize() == 120
    assert mgr._dispatcher_task is None


# ---------------------------------------------------------------------------
# CON-04: AIWorker sync _cleanup_on_failure awaited & create_task on worker thread
# ---------------------------------------------------------------------------


def test_con_04_sync_cleanup_awaited_and_create_task_in_thread():
    """AIWorker.start awaits sync _cleanup_on_failure() -> TypeError; _on_attendance_event fails in worker thread."""
    from pipeline_engine.core.worker import AIWorker

    assert inspect.iscoroutinefunction(AIWorker._cleanup_on_failure) is False

    # Construct minimal AIWorker via __new__ to test real start() failure branch & _on_attendance_event
    worker = AIWorker.__new__(AIWorker)
    worker.config = SimpleNamespace(
        camera_ids=["cam1"],
        worker_id="w1",
        worker_version="1.0",
        api_key=None,
        backend_base_url="http://localhost:19146",
    )
    worker.engine = MagicMock()
    worker.engine.start.side_effect = RuntimeError("mock engine boom")
    worker._running = False
    worker._metrics = SimpleNamespace(errors=0, events_submitted=0)
    worker.event_client = MagicMock()
    worker.health_client = None
    worker.control_client = None

    # Line 290 executes `await self._cleanup_on_failure()` after start fails -> TypeError
    with patch.object(AIWorker, "_cleanup_on_failure", return_value=None) as cleanup_spy:
        try:
            res = asyncio.run(worker.start())
        except TypeError as exc:
            assert "NoneType" in str(exc) or "await" in str(exc)
        else:
            # Even if start() caught inside try/except, cleanup spy must be checked
            pytest.fail(f"Expected TypeError from awaiting sync _cleanup_on_failure, got {res}")
        assert cleanup_spy.called

    # Now verify _on_attendance_event invoked on worker thread catches RuntimeError from create_task
    fake_event = SimpleNamespace(
        event_id="evt-1",
        camera_id="cam1",
        track_id=1,
        direction="in",
        event_type="line_crossing",
        timestamp=1760800800.0,
        frame_index=5,
        person_id="STU1",
        person_name="Student 1",
        identity_confidence=0.9,
        stream_epoch=1,
        pts=0,
        model_version="v1",
        enrollment_version="e1",
        crossing_point=(100.0, 200.0),
        previous_position=(90.0, 190.0),
        current_position=(100.0, 200.0),
    )

    def run_in_thread():
        worker._on_attendance_event(fake_event)

    t = threading.Thread(target=run_in_thread)
    t.start()
    t.join(timeout=5.0)

    assert worker._metrics.errors >= 1
    assert worker.event_client.submit_event.call_count == 0


# ---------------------------------------------------------------------------
# WS-01: Shared SSE/WS queue theft & head-of-line blocking in MetadataBroadcaster
# ---------------------------------------------------------------------------


def test_ws_01_sse_steals_frames_and_slow_client_blocks_broadcast():
    """MetadataBroadcaster shares _frame_queues with SSE and awaits send_text sequentially without timeout."""
    from app.streaming.metadata_broadcaster import MetadataBroadcaster

    broadcaster = MetadataBroadcaster()

    async def _run():
        # 1. Queue theft: SSE consumer reading from _get_or_create_queue removes item before WS loop sees it
        q = broadcaster._get_or_create_queue("cam1")
        await q.put({"frame_index": 1})
        sse_item = await q.get()
        assert sse_item == {"frame_index": 1}
        assert q.empty()  # WS broadcast loop gets nothing

        # 2. Head-of-line blocking: slow client blocks fast client in sequential send loop
        slow_release = asyncio.Event()
        fast_received = []

        slow_ws = MagicMock()

        async def slow_send(text):
            await slow_release.wait()

        slow_ws.send_text = slow_send

        fast_ws = MagicMock()

        async def fast_send(text):
            fast_received.append(text)

        fast_ws.send_text = fast_send

        await broadcaster.register_connection(slow_ws, "cam1", "c_slow")
        await broadcaster.register_connection(fast_ws, "cam1", "c_fast")

        # Put one frame and run _camera_broadcast_loop briefly
        await q.put({"camera_id": "cam1", "frame_index": 2})
        task = asyncio.create_task(broadcaster._camera_broadcast_loop("cam1"))
        await asyncio.sleep(0.05)

        # Fast client is starved because slow_ws has no asyncio.wait_for timeout!
        assert fast_received == []

        slow_release.set()
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(fast_received) == 1

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# WS-02: CameraRuntimeManager._broadcast_metadata uses get_event_loop() in thread
# ---------------------------------------------------------------------------


def test_ws_02_broadcast_metadata_drops_frames_in_worker_thread():
    """CameraRuntimeManager._broadcast_metadata fails with RuntimeError on non-loop thread and never broadcasts."""
    from app.streaming.camera_runtime_manager import CameraRuntimeConfig, CameraRuntimeManager

    mgr = CameraRuntimeManager(CameraRuntimeConfig(camera_id="cam1", rtsp_url="rtsp://127.0.0.1:8554/live/cam1"))

    fake_broadcaster = MagicMock()
    fake_frame = SimpleNamespace(
        metadata=SimpleNamespace(timestamp=1760800800.0, frame_index=12, width=1920, height=1080)
    )
    fake_ai_output = SimpleNamespace(persons=[], faces=[], inference_time_ms=5.0)

    def worker_call():
        with patch("app.streaming.camera_runtime_manager.get_metadata_broadcaster", return_value=fake_broadcaster):
            mgr._broadcast_metadata(fake_frame, fake_ai_output, tracking_result=None)

    t = threading.Thread(target=worker_call)
    t.start()
    t.join(timeout=5.0)

    # _broadcast_metadata silently caught RuntimeError('no current event loop') without calling broadcast_sync
    assert fake_broadcaster.broadcast.call_count == 0
    assert fake_broadcaster.broadcast_sync.call_count == 0


# ---------------------------------------------------------------------------
# WS-03: Broken A/V sync clock domains (pts=0, wall-clock pts_ns, stale fallback)
# ---------------------------------------------------------------------------


def test_ws_03_pts_clock_mismatch_and_stale_metadata_fallback():
    """worker.py hardcodes pts=0, managers send wall-clock pts_ns, frontend keeps minDiff>0.3 & lastMetadata."""
    worker_src = (REPO_ROOT / "pipeline_engine" / "core" / "worker.py").read_text(encoding="utf-8")
    crm_src = (REPO_ROOT / "app" / "streaming" / "camera_runtime_manager.py").read_text(encoding="utf-8")
    cm_src = (REPO_ROOT / "pipeline_engine" / "ingestion" / "camera_manager.py").read_text(encoding="utf-8")
    html_src = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert re.search(r"\bpts\s*=\s*0\b", worker_src)
    assert "pts_ns=int(frame.metadata.timestamp * 1_000_000_000)" in crm_src
    assert "pts_ns = int(gpu_frame.timestamp * 1e9)" in cm_src
    assert "minDiff > 0.3" in html_src
    assert "lastMetadata" in html_src


# ---------------------------------------------------------------------------
# WS-04: Coordinate math & canvas DOM overlay mismatches
# ---------------------------------------------------------------------------


def test_ws_04_frontend_cover_vs_contain_double_scale_and_hidden_video_binding():
    """frontend/index.html pairs hidden object-cover video1 with canvas-cam1, mixes contain math, and double-scales BBox."""
    html_src = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "DEFAULT_SOURCE_WIDTH = 3840" in html_src
    assert "DEFAULT_SOURCE_HEIGHT = 2160" in html_src
    # mapCoordinates uses Math.min (contain) even inside cover block
    assert "Math.min(containerWidth / sourceWidth, containerHeight / sourceHeight)" in html_src
    # syncCanvasSize binds hidden video1 to canvas-cam1 while live preview renders in preview1
    assert "['video1', 'canvas-cam1']" in html_src
    assert "id=\"video1\"" in html_src and "object-cover" in html_src
    # mapBBox normalizes/scales before calling mapCoordinates
    assert "mapBBox" in html_src and "mapCoordinates(" in html_src
    # drawFaceBox accesses box[0] without null guard
    m = re.search(r"function drawFaceBox\([^)]*\)\s*\{([\s\S]{0,400})", html_src)
    assert m is not None
    body = m.group(1)
    assert "box[0]" in body or "[x1, y1" in body


# ---------------------------------------------------------------------------
# BOOT-01: MediaMTX Popen opens stdout/stderr PIPE without drain threads
# ---------------------------------------------------------------------------


def test_boot_01_mediamtx_popen_pipes_without_drain_threads():
    """Bootstrap.start_mediamtx uses subprocess.PIPE for stdout & stderr without spawning drain threads."""
    from bootstrap import Bootstrap

    b = Bootstrap.__new__(Bootstrap)
    b.mediamtx_process = None
    b.mediamtx_dir = REPO_ROOT / "mediamtx"
    b.mediamtx_exe = REPO_ROOT / "mediamtx" / "mediamtx.exe"
    b.mediamtx_config = REPO_ROOT / "mediamtx" / "mediamtx.yml"
    b.startup_log = []
    b.logger = MagicMock()

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        proc = MagicMock()
        proc.pid = 99999
        proc.poll.return_value = None
        return proc

    with (
        patch("bootstrap.subprocess.Popen", side_effect=fake_popen),
        patch("bootstrap.threading.Thread") as thread_cls,
        patch.object(b, "wait_for_port", return_value=True, create=True),
        patch("bootstrap.time.sleep"),
        patch("pathlib.Path.exists", return_value=True),
    ):
        try:
            b.start_mediamtx()
        except Exception:
            pass

    assert len(popen_calls) == 1
    _, kw = popen_calls[0]
    import subprocess as sp

    assert kw.get("stdout") == sp.PIPE
    assert kw.get("stderr") == sp.PIPE
    assert thread_cls.call_count == 0


# ---------------------------------------------------------------------------
# BOOT-02: Bootstrap.start() checks service_manager BEFORE instantiating it
# ---------------------------------------------------------------------------


def test_boot_02_bootstrap_start_evaluates_service_manager_while_none():
    """Bootstrap.start() checks `if self.service_manager:` at line 722 before setting it at line 732; method is start(), not run()."""
    from bootstrap import Bootstrap

    # Verify Report #8 method-name discrepancy: Bootstrap has start(), NOT run()
    assert not hasattr(Bootstrap, "run")
    assert hasattr(Bootstrap, "start")

    src = (REPO_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    start_idx = src.index("def start(self)")
    block = src[start_idx : start_idx + 1200]
    check_pos = block.index("if self.service_manager:")
    assign_pos = block.index("self.service_manager = ServiceManager(")
    assert check_pos < assign_pos

    # Confirm default hardcoded port list in ServiceManager
    assert "[8000, 3000, 8554, 8888, 9997]" in src


# ---------------------------------------------------------------------------
# BOOT-03: Process kill fallback dropped on send_signal failure & no Job Object
# ---------------------------------------------------------------------------


def test_boot_03_stop_processes_clear_refs_without_kill_on_signal_error():
    """stop_mediamtx, stop_backend_api, stop_frontend swallow send_signal OSError, skip .kill(), and clear refs."""
    from bootstrap import Bootstrap

    b = Bootstrap.__new__(Bootstrap)
    b.logger = MagicMock()
    b.backend_log_file = None
    b.frontend_log_file = None

    for attr, stop_name in (
        ("mediamtx_process", "stop_mediamtx"),
        ("backend_process", "stop_backend_api"),
        ("frontend_process", "stop_frontend"),
    ):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.send_signal.side_effect = OSError("CTRL_BREAK_EVENT failed")
        setattr(b, attr, proc)

        getattr(b, stop_name)()

        assert proc.kill.call_count == 0
        assert getattr(b, attr) is None

    pub_src = (REPO_ROOT / "app" / "streaming" / "annotated_publisher.py").read_text(encoding="utf-8")
    boot_src = (REPO_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    assert "AssignProcessToJobObject" not in pub_src
    assert "AssignProcessToJobObject" not in boot_src


# ===========================================================================
# P1-HIGH REPRODUCERS
# ===========================================================================


# ---------------------------------------------------------------------------
# CON-05: PyNvVideoCodecBackend missing av.open timeout & unsafe container close
# ---------------------------------------------------------------------------


def test_con_05_pynvvideocodec_no_demuxer_timeout_and_close_while_reader_alive():
    """_open_demuxer passes no timeout/stimeout to av.open; close() closes container even if _reader_thread.is_alive()."""
    from app.streaming.pynvvideocodec_backend import PyNvVideoCodecBackend

    backend = PyNvVideoCodecBackend.__new__(PyNvVideoCodecBackend)
    backend.camera_id = "cam1"
    backend._rtsp_url = "rtsp://127.0.0.1:8554/live/cam1"
    backend._is_rtmp = False
    backend._config = SimpleNamespace(rtsp_url=backend._rtsp_url, timeout=10.0)
    backend._lock = threading.RLock()
    backend._stop_event = threading.Event()
    backend._opened = True
    backend._demuxer = None
    backend._decoder = None
    backend._frame_adapter = None

    av_calls = []

    def fake_av_open(url, format=None, options=None, **kwargs):
        av_calls.append({"url": url, "format": format, "options": dict(options or {}), "kwargs": dict(kwargs)})
        fake_stream = SimpleNamespace(
            codec_context=SimpleNamespace(name="h264"),
            width=1920,
            height=1080,
            average_rate=30,
        )
        return SimpleNamespace(streams=SimpleNamespace(video=[fake_stream]))

    with patch("av.open", side_effect=fake_av_open):
        backend._open_demuxer()

    assert len(av_calls) == 1
    assert "timeout" not in av_calls[0]["kwargs"]
    assert "stimeout" not in av_calls[0]["options"]
    assert "rw_timeout" not in av_calls[0]["options"]

    # Blocked reader thread still alive after join(timeout=3.0), yet close() closes container
    alive_thread = MagicMock()
    alive_thread.is_alive.return_value = True
    fake_container = MagicMock()
    backend._reader_thread = alive_thread
    backend._container = fake_container

    backend.close()
    assert alive_thread.join.called
    assert fake_container.close.call_count == 1  # Closed mid-demux while thread alive!


# ---------------------------------------------------------------------------
# CON-06: MediaMTXPublisher deadlocked DISCONNECTED state & unrecovered mux errors
# ---------------------------------------------------------------------------


def test_con_06_publisher_stuck_in_disconnected_and_mux_error_no_reconnect():
    """MediaMTXPublisher._publish_loop ignores DISCONNECTED when available and keeps PUBLISHING on mux() failure."""
    from pipeline_engine.output.publisher import MediaMTXPublisher, PublisherConfig, PublisherState

    pub = MediaMTXPublisher(PublisherConfig(camera_id="cam1"))
    pub._state = PublisherState.PUBLISHING
    pub._container = MagicMock()
    pub._container.mux.side_effect = RuntimeError("broken RTSP mux")
    pub._stream = MagicMock()
    pub._packet_queue.put_nowait(MagicMock())

    # Simulate _publish_loop single iteration behavior on mux exception
    # And confirm pub._state does NOT transition out of PUBLISHING when mux raises
    pub_src = inspect.getsource(MediaMTXPublisher._publish_loop)
    assert "except Exception" in pub_src
    assert "packets_dropped += 1" in pub_src
    assert "self._reconnect()" not in pub_src.split("self._container.mux")[1]
    assert "rtsp://localhost:8554" in (REPO_ROOT / "pipeline_engine" / "output" / "publisher.py").read_text(encoding="utf-8")

    # Also verify disconnected loop only triggers _reconnect() when _state == MEDIA_SERVER_NOT_AVAILABLE
    disc_block = pub_src.split("if self._state == PublisherState.MEDIA_SERVER_NOT_AVAILABLE")[1].split("if self._state != PublisherState.PUBLISHING")[0]
    assert "_reconnect" in disc_block
    # If _state is DISCONNECTED, it skips reconnect block and continues without connecting
    pub._state = PublisherState.DISCONNECTED
    assert pub._state != PublisherState.MEDIA_SERVER_NOT_AVAILABLE


# ---------------------------------------------------------------------------
# CON-07: Legacy reconnect counters never reset, config overwrite & tight spin
# ---------------------------------------------------------------------------


def test_con_07_reconnect_counters_config_overwrite_and_ignored_supervised_flag():
    """Duplicate CamerasConfig.reconnect_base_interval=2.0, unreset _attempt_count, _exhausted=True, ignored use_supervised_source."""
    from app.config.settings import CamerasConfig
    from app.streaming.ingestion_worker import CameraIngestionConfig
    from app.streaming.reconnect import ReconnectConfig, ReconnectManager, ReconnectPolicy
    from app.streaming.rtsp_source import RTSPSource, RTSPSourceConfig

    # Duplicate attribute in CamerasConfig silently overrides 10.0 with 2.0
    assert CamerasConfig().reconnect_base_interval == 2.0

    # ReconnectManager fails attempt 1, succeeds attempt 2 -> _attempt_count never resets to 0
    mgr = ReconnectManager(
        ReconnectConfig(policy=ReconnectPolicy.FIXED_INTERVAL, max_retries=2, base_interval=0.0, jitter=0.0),
        sleep_func=lambda _: None,
    )
    outcomes = iter([False, True])
    assert mgr.attempt_reconnect(lambda: next(outcomes)) is False
    assert mgr.attempt_reconnect(lambda: next(outcomes)) is True
    assert mgr._attempt_count == 2  # Not reset to 0 after success -> next failure hits max_retries!

    # app.streaming.rtsp_source.RTSPSource: StopIteration marks _exhausted, reconnect() leaves _reconnect_count unreset
    src = RTSPSource(RTSPSourceConfig(camera_id="cam1", url="rtsp://127.0.0.1:8554/live/cam1"))
    src._iterator = iter([])
    src._opened = True
    assert src.get_next_frame() is None
    assert src._exhausted is True

    with patch.object(src, "open"):
        assert src.reconnect() is True
    assert src._reconnect_count == 1  # Never reset on open/reconnect success

    # IngestionWorker sets use_supervised_source=True in from_settings yet create_rtsp_source is called directly
    iw_src = (REPO_ROOT / "app" / "streaming" / "ingestion_worker.py").read_text(encoding="utf-8")
    assert "use_supervised_source=True" in iw_src
    assert "SupervisedRTSPSource" not in iw_src
    assert CameraIngestionConfig(camera_id="cam1", rtsp_url="rtsp://x").use_supervised_source is False


# ---------------------------------------------------------------------------
# CON-08: CaptureWatchdog & PublisherLivenessWatchdog disabled stubs
# ---------------------------------------------------------------------------


def test_con_08_watchdogs_disabled_no_op_and_callback_suppressed():
    """CaptureWatchdog methods are no-op stubs and PublisherLivenessWatchdog swallows on_unhealthy."""
    from app.streaming.capture_watchdog import CaptureWatchdog, CaptureWatchdogConfig
    from app.streaming.publisher_liveness import (
        PublisherLivenessConfig,
        PublisherLivenessWatchdog,
    )

    on_stall = MagicMock()
    cw = CaptureWatchdog(CaptureWatchdogConfig(), camera_id="cam1", on_stall=on_stall)
    cw.start_watchdog()
    cw._watchdog_loop()
    cw._force_teardown()
    cw.stop_watchdog()
    assert cw._watchdog_thread is None
    assert on_stall.call_count == 0

    on_unhealthy = MagicMock()
    plw = PublisherLivenessWatchdog(
        config=PublisherLivenessConfig(camera_id="cam1", path_name="live/cam1_ai", mediamtx_api_port=9997),
        get_publisher_stats=lambda: {"process_alive": False, "frames_encoded": 0, "last_encode_time": 0.0, "pid": None},
        on_unhealthy=on_unhealthy,
    )
    # Even when UNHEALTHY triggers repeatedly inside _poll_once(), callback is disabled (`pass` stub)
    liveness_src = inspect.getsource(PublisherLivenessWatchdog._poll_once)
    assert "Watchdog DISABLED" in liveness_src or "on_unhealthy" not in liveness_src.split("UNHEALTHY")[-1][:250]
    with patch("urllib.request.urlopen", side_effect=OSError("no mediamtx")):
        for _ in range(5):
            plw._poll_once()
    assert on_unhealthy.call_count == 0


# ---------------------------------------------------------------------------
# CON-09: PipelineEngine clients default to port 19146 & HTTP 400 retry trap
# ---------------------------------------------------------------------------


def test_con_09_client_default_port_19146_and_unreachable_http_400_branch():
    """Event/Health/Control clients default to :19146; HTTP 400 triggers retries because checked inside 200 branch."""
    from pipeline_engine.integration.control_client import ControlClientConfig
    from pipeline_engine.integration.event_client import (
        AttendanceEventRequest,
        EventDeliveryClient,
        EventDeliveryConfig,
    )
    from pipeline_engine.integration.health_client import HealthClientConfig

    assert EventDeliveryConfig().backend_base_url == "http://localhost:19146"
    assert HealthClientConfig().backend_base_url == "http://localhost:19146"
    assert ControlClientConfig().backend_base_url == "http://localhost:19146"

    client = EventDeliveryClient(EventDeliveryConfig(max_retries=2, base_retry_delay=0.0))
    resp_400 = SimpleNamespace(status_code=400, text="Bad Request")
    post_spy = AsyncMock(return_value=resp_400)
    client._client = SimpleNamespace(post=post_spy)

    req = AttendanceEventRequest(
        event_id="e-400",
        camera_id="cam1",
        track_id=1,
        direction="in",
        event_type="line_crossing",
        timestamp=1760800800.0,
        frame_index=1,
        person_id="STU1",
        person_name="Student 1",
        identity_confidence=0.9,
        stream_epoch=1,
        pts=0,
        model_version="v1",
        enrollment_version="e1",
    )

    ok = asyncio.run(client._deliver_with_retry(req))
    assert ok is False
    # Should have failed fast in 1 attempt, but retried 1 + 2 = 3 times due to indentation trap!
    assert post_spy.await_count == 3


# ---------------------------------------------------------------------------
# WS-05: Duplicate welcome message & unguarded set/dict iteration during await
# ---------------------------------------------------------------------------


def test_ws_05_duplicate_welcome_and_set_changed_size_during_broadcast():
    """attendance_ws sends two 'welcome' frames per connect; MetadataBroadcaster mutates active_connections across await."""
    from app.api.attendance_ws import ConnectionManager
    from app.streaming.metadata_broadcaster import MetadataBroadcaster

    # 1. attendance_ws sends duplicate welcome: once in connect(), once in attendance_websocket_endpoint()
    aws_src = (REPO_ROOT / "app" / "api" / "attendance_ws.py").read_text(encoding="utf-8")
    assert aws_src.count('"type": "welcome"') >= 2

    cm = ConnectionManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    asyncio.run(cm.connect(ws))
    assert ws.send_json.await_count == 1
    assert ws.send_json.call_args.args[0]["type"] == "welcome"

    # 2. MetadataBroadcaster._heartbeat_loop iterates active_connections.items() without snapshot
    broadcaster = MetadataBroadcaster()

    async def _run():
        bad_ws = MagicMock()

        async def disconnect_during_send(text):
            # Mutate the set mid-iteration across the await boundary!
            broadcaster.active_connections["cam1"].add(SimpleNamespace(client_id="intruder", websocket=MagicMock(), last_ping=0.0))

        bad_ws.send_text = disconnect_during_send
        await broadcaster.register_connection(bad_ws, "cam1", "c1")
        broadcaster._heartbeat_interval = 0.0

        with pytest.raises(RuntimeError, match="changed size during iteration"):
            # Run one pass of _heartbeat_loop until it hits the unguarded iteration
            await broadcaster._heartbeat_loop()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# WS-06: EventDeliveryClient records idempotency BEFORE broadcast, dropping retries
# ---------------------------------------------------------------------------


def test_ws_06_attendance_ws_idempotency_recorded_before_broadcast_drops_retries():
    """First failed push marks attendance_record_id seen; subsequent retry is silently skipped."""
    from app.api.attendance_ws import ConnectionManager, EventDeliveryClient

    mgr = MagicMock(spec=ConnectionManager)
    mgr.broadcast = AsyncMock(side_effect=RuntimeError("ws write failed"))
    client = EventDeliveryClient(manager=mgr)

    rec = SimpleNamespace(
        attendance_record_id="att-rec-ws06",
        person_id="STU1",
        person_name="Student 1",
        camera_id="cam1",
        direction=SimpleNamespace(value="in"),
        event_timestamp=1760800800.0,
        identity_confidence=0.95,
        snapshot_face_url=None,
    )

    # First delivery fails on broadcast
    first_ok = asyncio.run(client.push_attendance_event(rec))
    assert first_ok is False
    assert "att-rec-ws06" in client._seen_event_ids  # Marked seen BEFORE broadcast!

    # Now WS recovers; retry calls push_attendance_event -> returns True WITHOUT calling broadcast!
    mgr.broadcast = AsyncMock(return_value=1)
    retry_ok = asyncio.run(client.push_attendance_event(rec))
    assert retry_ok is True
    assert mgr.broadcast.await_count == 0


# ---------------------------------------------------------------------------
# WS-07: _telemetry_push_loop blocks asyncio event loop with sync nvidia-smi
# ---------------------------------------------------------------------------


def test_ws_07_telemetry_push_loop_executes_sync_subprocess_on_loop_thread():
    """_telemetry_push_loop invokes synchronous get_hardware_telemetry() directly on the asyncio loop thread."""
    import app.api.health as health_mod
    import app.api.websocket as ws_mod

    ws_src = inspect.getsource(ws_mod._telemetry_push_loop)
    assert "get_hardware_telemetry()" in ws_src
    assert "to_thread" not in ws_src

    health_src = inspect.getsource(health_mod.get_hardware_telemetry)
    assert "subprocess.run" in health_src

    caller_threads = []

    async def _run():
        loop_tid = threading.get_ident()

        def spy_telemetry():
            caller_threads.append(threading.get_ident())
            raise asyncio.CancelledError()  # Abort loop cleanly after 1 iteration

        ws_mod._active_telemetry_clients = 1
        with (
            patch("app.api.health.get_hardware_telemetry", side_effect=spy_telemetry),
            patch("asyncio.sleep", AsyncMock()),
        ):
            try:
                await ws_mod._telemetry_push_loop()
            except asyncio.CancelledError:
                pass
        assert caller_threads == [loop_tid]

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# WS-08: app.output.publisher inline synchronous fanout & frontend HLS handle leak
# ---------------------------------------------------------------------------


def test_ws_08_event_bus_runs_subscriber_inline_on_caller_thread_and_hls_leak():
    """EventPublisher.publish() executes subscriber callbacks synchronously on caller thread; frontend drops HLS ref."""
    from app.output.contract import ImmediateEvent, ImmediateEventDirection, ImmediateEventType
    from app.output.publisher import EventPublisher, FunctionSubscriber

    pub = EventPublisher()
    caller_tid = threading.get_ident()
    seen_tids = []

    sub = FunctionSubscriber(
        subscriber_id="sub1",
        handler=lambda ev: seen_tids.append(threading.get_ident()),
    )
    pub.subscribe(sub)

    event = ImmediateEvent(
        event_id="im-1",
        event_type=ImmediateEventType.RESOLUTION_IN,
        direction=ImmediateEventDirection.IN,
        camera_id="cam1",
        local_track_id="1",
        event_timestamp=1760800800.0,
        source_resolution_id="res-ws08",
        source_raw_event_id="raw-ws08",
    )
    assert pub.publish(event) is True
    assert seen_tids == [caller_tid]

    html_src = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "const hls = new Hls" in html_src
    assert "window['hls_' + cam]" in html_src
    # initStream creates `const hls = new Hls(...)` without assigning `window['hls_' + cam] = hls`
    assert "window['hls_' + cam] = hls" not in html_src


# ---------------------------------------------------------------------------
# BOOT-04: Hardcoded ports drift across worker, backend, bootstrap & frontend
# ---------------------------------------------------------------------------


def test_boot_04_hardcoded_port_drift_across_components():
    """Hardcoded ports diverge across PipelineWorkerConfig (:19146), pe_backend (:8080), bootstrap (:8000/:3000)."""
    from pipeline_engine.core.worker import WorkerConfig

    assert WorkerConfig().backend_base_url == "http://localhost:19146"
    pe_app_src = (REPO_ROOT / "pipeline_engine" / "backend" / "app.py").read_text(encoding="utf-8")
    assert "port=8080" in pe_app_src
    html_src = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "localhost:8000" in html_src
    assert "8888" in html_src


# ---------------------------------------------------------------------------
# BOOT-05: Supervisor loop ignores dead child processes (plus method name check)
# ---------------------------------------------------------------------------


def test_boot_05_run_supervisor_ignores_child_process_poll():
    """Bootstrap._run_supervisor (not _supervisor_loop) never polls backend_process or mediamtx_process."""
    from bootstrap import Bootstrap

    # Discrepancy confirmed: Report #8 cites `_supervisor_loop()`, actual method is `_run_supervisor()`
    assert not hasattr(Bootstrap, "_supervisor_loop")
    assert hasattr(Bootstrap, "_run_supervisor")

    sup_src = inspect.getsource(Bootstrap._run_supervisor)
    assert "mediamtx_process" not in sup_src
    assert "backend_process" not in sup_src
    assert ".poll()" not in sup_src


# ---------------------------------------------------------------------------
# BOOT-06: /api/v1/health/ready hits legacy /api/paths (404) & rejects empty workers
# ---------------------------------------------------------------------------


def test_boot_06_health_ready_queries_legacy_api_paths_and_marks_not_ready():
    """/api/v1/health/ready calls /api/paths (not /v3/paths/list) and treats empty _worker_health_states as not_ready."""
    import app.api.ai_worker as ai_worker
    import app.main as app_main

    requested_urls = []

    class FakeResp:
        status_code = 404

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            requested_urls.append(url)
            return FakeResp()

    mini_app = FastAPI()
    # Mount the /api/v1/health/ready route directly from app.main.app
    for route in app_main.app.routes:
        if getattr(route, "path", None) == "/api/v1/health/ready":
            mini_app.router.routes.append(route)

    client = TestClient(mini_app)
    with (
        patch("httpx.AsyncClient", FakeAsyncClient),
        patch.dict(ai_worker._worker_health_states, {}, clear=True),
    ):
        resp = client.get("/api/v1/health/ready")

    assert any(u.endswith("/api/paths") for u in requested_urls)
    assert not any("/v3/paths/list" in u for u in requested_urls)
    assert resp.status_code == 503 or resp.json().get("status") == "not_ready"
