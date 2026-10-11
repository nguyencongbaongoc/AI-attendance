"""
Phase 44.X.4-R3.3 — Supervised RTSP Source.

Thin adapter that adds the capture watchdog from
app.streaming.capture_watchdog to the existing VideoFrameIterator so
that a blocked cv2.VideoCapture.read() can be force-torn-down from a
supervisor thread.

Public surface:
    * SupervisedRTSPSource wraps a VideoFrameIterator + CaptureWatchdog
    * open() builds the underlying VideoFrameIterator and starts the
      watchdog thread
    * get_next_frame() returns frames with no risk of blocking forever:
      if the watchdog forces teardown, get_next_frame() raises
      RTSPCaptureStalledError so the caller can reconnect
    * reconnect() tears the iterator + watchdog down, sleeps the
      configured retry_interval, and reopens
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, Optional

from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.data.input_adapter import VideoFrameIterator, VideoInfo
from app.streaming.capture_watchdog import (
    CaptureWatchdog,
    CaptureWatchdogConfig,
)
from app.video.pynvcodec.gpu_frame_contract import GPUFrameContract
from app.video.pynvcodec.frame_contract import FrameContract

logger = logging.getLogger(__name__)


class RTSPCaptureStalledError(Exception):
    """Raised when the watchdog forced a teardown due to a stalled read."""

    def __init__(self, camera_id: str, stall_seconds: float) -> None:
        super().__init__(
            f"RTSP capture stalled for {stall_seconds:.2f}s on camera "
            f"{camera_id}"
        )
        self.camera_id = camera_id
        self.stall_seconds = stall_seconds


@dataclass(frozen=True)
class SupervisedRTSPSourceConfig:
    camera_id: str
    rtsp_url: str
    decoder: str = "pynvvideocodec"  # Canonical: PyNvVideoCodec NVDEC (production default Phase 9.3+)
    nvdec_gpu_device: int = 0
    use_pts: bool = True
    max_queue_size: int = 10
    expected_codec: str = "h264"
    expected_width: int = 3840
    expected_height: int = 2160
    expected_fps: float = 30.0
    # CAMERA OPEN TIMEOUT = exactly 10 seconds (PART C requirement)
    stall_timeout_seconds: float = 6.0
    retry_interval: float = 2.0
    max_retries: int = 5
    worker_join_timeout: float = 3.0
    min_teardown_interval_seconds: float = 1.0
    max_consecutive_teardowns: int = 5
    teardown_backoff_seconds: float = 2.0


class SupervisedRTSPSource:
    """
    RTSP source wrapper that supervises cv2.VideoCapture.read() with an
    independent watchdog thread so that a blocked read() can be broken.
    """

    def __init__(
        self,
        config: SupervisedRTSPSourceConfig,
        on_stall: Optional[Callable[[Dict[str, Any]], None]] = None,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.camera_id = config.camera_id
        self._time = time_func
        self._on_stall = on_stall

        # Force RTSP-over-TCP for stability.
        rtsp_url = config.rtsp_url
        if "transport=" not in rtsp_url:
            separator = "&" if "?" in rtsp_url else "?"
            rtsp_url = f"{rtsp_url}{separator}transport=tcp"
        self.rtsp_url = rtsp_url

        self._iterator: Optional[VideoFrameIterator] = None
        self._info: Optional[VideoInfo] = None

        wd_config = CaptureWatchdogConfig(
            stall_timeout_seconds=config.stall_timeout_seconds,
            worker_join_timeout=config.worker_join_timeout,
            min_teardown_interval_seconds=config.min_teardown_interval_seconds,
            max_consecutive_teardowns=config.max_consecutive_teardowns,
            teardown_backoff_seconds=config.teardown_backoff_seconds,
        )
        self._watchdog = CaptureWatchdog(
            config=wd_config,
            camera_id=config.camera_id,
            on_stall=on_stall,
            time_func=time_func,
        )

        self._opened = False
        self._frame_count = 0
        self._read_iter: Optional[Iterator[Any]] = None
        self._read_thread: Optional[threading.Thread] = None
        self._read_thread_stop = threading.Event()
        self._next_frame: Optional[CanonicalFrame] = None
        self._next_frame_ready = threading.Event()
        self._next_frame_lock = threading.Lock()
        self._start_time: Optional[float] = None
        self._reconnect_count = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ open
    def open(self) -> VideoInfo:
        with self._lock:
            if self._opened:
                return self._info  # type: ignore[return-value]

            logger.info(
                "SupervisedRTSPSource(%s): opening %s",
                self.camera_id,
                self.rtsp_url,
            )
            self._iterator = VideoFrameIterator(
                self.rtsp_url,
                decoder=self.config.decoder,
                nvdec_gpu_device=self.config.nvdec_gpu_device,
                camera_id=self.camera_id,
            )
            self._info = self._iterator.info

            # Start the watchdog and the read thread.
            self._watchdog.claim_ownership()
            self._read_thread_stop.clear()
            self._next_frame_ready.clear()
            self._read_thread = threading.Thread(
                target=self._read_loop,
                name=f"rtsp-read-{self.camera_id}",
                daemon=True,
            )
            self._read_thread.start()
            self._watchdog.set_worker_thread(self._read_thread)
            self._watchdog.start_watchdog()

            self._opened = True
            self._frame_count = 0
            self._start_time = self._time()

            return self._info

    # ----------------------------------------------------------- read thread
    def _read_loop(self) -> None:
        assert self._iterator is not None
        try:
            # Single owner of the iterator. Stops on stop_event or
            # when the iterator ends.
            for frame in self._iterator.iter_with_watchdog(
                self._watchdog,
                self._watchdog.stop_event,
            ):
                if self._read_thread_stop.is_set():
                    return
                if frame.stalled:
                    return
                canonical = self._to_canonical(frame)
                with self._next_frame_lock:
                    self._next_frame = canonical
                    self._next_frame_ready.set()
        except Exception as e:  # noqa: BLE001
            logger.error(
                "SupervisedRTSPSource(%s): read loop crashed: %s",
                self.camera_id,
                e,
            )

    def _to_canonical(self, frame: Any) -> CanonicalFrame:
        # Minimal runtime instrumentation for contract verification (not synthetic/mock/replay)
        data_type_str = str(type(frame.data).__name__)
        data_has_ndim = hasattr(frame.data, "ndim")
        data_has_shape = hasattr(frame.data, "shape")
        data_has_dtype = hasattr(frame.data, "dtype")
        data_is_dict = isinstance(frame.data, dict)
        # Minimal runtime instrumentation for contract verification (not synthetic/mock/replay; adapter_contract identity preserved)
        adapter_contract_ref = getattr(frame.data, "adapter_contract", None) if isinstance(frame.data, dict) else None
        logger.info(
            "[BOOT-GPU] SupervisedRTSPSource(%s) input: input_type=%s is_dict=%s adapter_contract_present=%s adapter_contract_type=%s",
            self.camera_id,
            data_type_str,
            data_is_dict,
            adapter_contract_ref is not None,
            type(adapter_contract_ref).__name__ if adapter_contract_ref is not None else "None",
        )
        receive_time = self._time()
        if self._start_time is None:
            self._start_time = receive_time
        live_timestamp = receive_time - self._start_time

        # Determine actual frame dimensions / pixel format based on data type
        # Contract normalization: handle adapter GPUFrameContract (GPU NV12), numpy (CPU BGR),
        # and WatchdogFrame dict (synthetic GPU contract from decoder wrapper)
        original_width = 0
        original_height = 0
        pixel_fmt_str = "unknown"
        dtype_str = "uint8"

        data_is_gpu_frame_contract = GPUFrameContract is not None and isinstance(frame.data, GPUFrameContract)

        if data_is_gpu_frame_contract:
            # Production adapter GPU contract (PyAV NVDEC -> GPUFrameContract)
            fc = frame.data
            original_width = int(fc.width) if hasattr(fc, "width") else self.config.expected_width
            original_height = int(fc.height) if hasattr(fc, "height") else self.config.expected_height
            pixel_fmt_str = str(fc.pixel_format) if hasattr(fc, "pixel_format") else "nv12"
            dtype_str = "uint8"
            logger.info(
                "[BOOT-GPU] SupervisedRTSPSource(%s) GPUFrameContract: width=%d height=%d fmt=%s device=%d",
                self.camera_id, original_width, original_height, pixel_fmt_str, getattr(fc, "device_id", 0),
            )
        elif isinstance(frame.data, dict):
            # WatchdogFrame / synthetic GPU contract from PyAV NVDEC decoder wrapper
            original_width = int(frame.data.get("width", self.config.expected_width))
            original_height = int(frame.data.get("height", self.config.expected_height))
            fmt_label = frame.data.get("format", "nv12_cuda")
            pixel_fmt_str = fmt_label if isinstance(fmt_label, str) else "nv12"
            dtype_str = "uint8"
            logger.info(
                "[BOOT-GPU] SupervisedRTSPSource(%s) WatchdogFrame dict: width=%d height=%d fmt=%s keys=%d",
                self.camera_id, original_width, original_height, pixel_fmt_str, len(frame.data),
            )
        elif hasattr(frame.data, "ndim") and hasattr(frame.data, "shape"):
            # CPU numpy array (OpenCV software path — should NOT be selected in production)
            original_width = int(frame.data.shape[1]) if frame.data.ndim >= 2 else 0
            original_height = int(frame.data.shape[0]) if frame.data.ndim >= 1 else 0
            pixel_fmt_str = "bgr"
            dtype_str = str(getattr(frame.data, "dtype", "uint8"))
            logger.info(
                "[BOOT-GPU] SupervisedRTSPSource(%s) CPU array: ndim=%s shape=%s",
                self.camera_id, getattr(frame.data, "ndim", "N/A"), str(getattr(frame.data, "shape", "N/A")),
            )
        else:
            # Unknown native reference — try best-effort extraction without crashing
            original_width = int(getattr(frame.data, "width", self.config.expected_width))
            original_height = int(getattr(frame.data, "height", self.config.expected_height))
            pixel_fmt_str = "unknown"
            dtype_str = "uint8"
            logger.info(
                "[BOOT-GPU] SupervisedRTSPSource(%s) unknown data type: %s",
                self.camera_id, data_type_str,
            )

        # Common extra metadata for all frame types
        extra = {
            "pts": frame.pts,
            "camera_id": self.camera_id,
            "wall_clock_receive_time": receive_time,
            "rtsp_url": self.rtsp_url,
        }
        # Build FrameMetadata from extracted values
        pixel_format = PixelFormat(pixel_fmt_str) if pixel_fmt_str in [f.value for f in PixelFormat] else PixelFormat.BGR
        metadata = FrameMetadata(
            source_type=SourceType.VIDEO,
            source_id=self.rtsp_url,
            frame_index=frame.frame_index,
            timestamp=live_timestamp,
            timestamp_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            original_width=original_width,
            original_height=original_height,
            pixel_format=pixel_format,
            dtype=dtype_str,
            source_fps=self.config.expected_fps,
            source_duration=0.0,
            source_frame_count=0,
            extra=extra,
        )
        # Determine canonical payload: adapter FrameContract takes precedence over wrapper dict
        adapter_contract_from_data = None
        if isinstance(frame.data, dict):
            adapter_contract_from_data = frame.data.get("adapter_contract", None)
            log_marker(f"TO_CANONICAL_DICT_KEYS={list(frame.data.keys()) if isinstance(frame.data, dict) else 'N/A'} ADAPTER_FROM_DICT={adapter_contract_from_data is not None} ADAPTER_FROM_DICT_TYPE={type(adapter_contract_from_data).__name__ if adapter_contract_from_data is not None else 'None'} ADAPTER_FROM_DICT_ID={id(adapter_contract_from_data) if adapter_contract_from_data is not None else 'None'}")
        else:
            adapter_contract_attr = getattr(frame.data, 'adapter_contract', None)
            log_marker(f"TO_CANONICAL_NON_DICT_TYPE={type(frame.data).__name__} NON_DICT_ADAPTER_ATTR={adapter_contract_attr is not None} NON_DICT_ADAPTER_ATTR_TYPE={type(adapter_contract_attr).__name__ if adapter_contract_attr is not None else 'None'} NON_DICT_ADAPTER_ATTR_ID={id(adapter_contract_attr) if adapter_contract_attr is not None else 'None'}")

        # If adapter FrameContract present (real NVDEC output from adapter), use it directly as CanonicalFrame.data
        if adapter_contract_from_data is not None and FrameContract is not None and isinstance(adapter_contract_from_data, FrameContract):
            canonical_payload = adapter_contract_from_data
            log_marker(f"TO_CANONICAL_PAYLOAD=FrameContract_direct_from_dict TYPE={type(canonical_payload).__name__} ID={id(canonical_payload)}")
        elif FrameContract is not None and isinstance(frame.data, FrameContract):
            canonical_payload = frame.data
            log_marker(f"TO_CANONICAL_PAYLOAD=FrameContract_direct TYPE={type(canonical_payload).__name__} ID={id(canonical_payload)}")
        else:
            # For synthetic wrapper dict or CPU array: preserve as-is (contract normalization handled by consumer contract)
            canonical_payload = frame.data
            if isinstance(canonical_payload, dict):
                log_marker(f"TO_CANONICAL_PAYLOAD=preserved_dict KEYS={list(canonical_payload.keys())} ID={id(canonical_payload)}")
            else:
                log_marker(f"TO_CANONICAL_PAYLOAD=preserved_other TYPE={type(canonical_payload).__name__} ID={id(canonical_payload)}")

        canonical = CanonicalFrame(
            data=canonical_payload,
            metadata=metadata,
            conversions_applied={},
        )
        log_marker(f"TO_CANONICAL_OUTPUT_TYPE={type(canonical).__name__} OUTPUT_ID={id(canonical)} OUTPUT_DATA_TYPE={type(canonical.data).__name__} OUTPUT_DATA_ID={id(canonical.data)} OUTPUT_DATA_KEYS={list(canonical.data.keys()) if isinstance(canonical.data, dict) else 'N/A'}")
        return canonical

    # -------------------------------------------------------- public access
    def get_next_frame(
        self, timeout: float = 5.0
    ) -> Optional[CanonicalFrame]:
        """
        Return the next frame, blocking up to `timeout` seconds.

        Raises RTSPCaptureStalledError if the watchdog had to force a
        teardown because read() was blocked too long.
        """
        with self._lock:
            if not self._opened:
                self.open()

        # If the watchdog already forced a teardown (no frames yet), raise.
        if self._watchdog.teardown_requested:
            with self._next_frame_lock:
                self._next_frame = None
                self._next_frame_ready.clear()
            raise RTSPCaptureStalledError(
                self.camera_id, 0.0
            )

        # Wait for the next frame.
        got = self._next_frame_ready.wait(timeout=timeout)
        if not got:
            # Timed out: if the watchdog forced teardown, raise.
            if self._watchdog.teardown_requested:
                raise RTSPCaptureStalledError(
                    self.camera_id,
                    float(self.config.stall_timeout_seconds),
                )
            return None

        with self._next_frame_lock:
            frame = self._next_frame
            self._next_frame = None
            self._next_frame_ready.clear()

        if frame is None:
            return None

        self._frame_count += 1
        return frame

    def reconnect(self) -> bool:
        """Tear down everything and re-open."""
        with self._lock:
            self._stop_internal()
            time.sleep(self.config.retry_interval)
            try:
                self._reconnect_count += 1
                self.open()
                return True
            except Exception as e:  # noqa: BLE001
                logger.error(
                    "SupervisedRTSPSource(%s): reconnect failed: %s",
                    self.camera_id,
                    e,
                )
                return False

    def _stop_internal(self) -> None:
        if not self._opened:
            return
        
        stop_start_time = time.time()
        logger.info(
            "[H2K][STOP_INTERNAL_START] camera=%s timestamp=%.6f",
            self.camera_id,
            stop_start_time,
        )
        
        self._read_thread_stop.set()
        self._watchdog.stop_event.set()
        
        if self._read_thread and self._read_thread.is_alive():
            read_join_start = time.time()
            alive_before = self._read_thread.is_alive()
            logger.info(
                "[H2K][READ_JOIN_START] camera=%s timestamp=%.6f alive_before=%s",
                self.camera_id,
                read_join_start,
                alive_before,
            )
            self._read_thread.join(timeout=2.0)
            read_join_end = time.time()
            alive_after = self._read_thread.is_alive()
            logger.info(
                "[H2K][READ_JOIN_END] camera=%s timestamp=%.6f elapsed_ms=%.2f alive_after=%s",
                self.camera_id,
                read_join_end,
                (read_join_end - read_join_start) * 1000.0,
                alive_after,
            )
        
        watchdog_join_start = time.time()
        alive_before_wd = self._watchdog._watchdog_thread.is_alive() if self._watchdog._watchdog_thread else False
        logger.info(
            "[H2K][WATCHDOG_JOIN_START] camera=%s timestamp=%.6f alive_before=%s",
            self.camera_id,
            watchdog_join_start,
            alive_before_wd,
        )
        self._watchdog.stop_watchdog()
        watchdog_join_end = time.time()
        alive_after_wd = self._watchdog._watchdog_thread.is_alive() if self._watchdog._watchdog_thread else False
        logger.info(
            "[H2K][WATCHDOG_JOIN_END] camera=%s timestamp=%.6f elapsed_ms=%.2f alive_after=%s",
            self.camera_id,
            watchdog_join_end,
            (watchdog_join_end - watchdog_join_start) * 1000.0,
            alive_after_wd,
        )
        
        if self._iterator is not None:
            try:
                self._iterator.close()
            except Exception:  # noqa: BLE001
                pass
            self._iterator = None
        try:
            self._watchdog.release_ownership()
        except Exception:  # noqa: BLE001
            pass
        self._opened = False
        
        logger.info(
            "[H2K][STOP_INTERNAL_END] camera=%s timestamp=%.6f",
            self.camera_id,
            time.time(),
        )

    def close(self) -> None:
        with self._lock:
            self._stop_internal()

    # ----------------------------------------------------------- properties
    @property
    def is_opened(self) -> bool:
        return self._opened

    @property
    def frames_produced(self) -> int:
        return self._frame_count

    @property
    def fps(self) -> Optional[float]:
        return self._info.fps if self._info else None

    @property
    def resolution(self) -> Optional[tuple]:
        if self._info:
            return (self._info.width, self._info.height)
        return None

    @property
    def watchdog_metrics(self) -> Dict[str, Any]:
        return self._watchdog.get_metrics()

    def __enter__(self) -> "SupervisedRTSPSource":
        self.open()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def create_supervised_rtsp_source(
    config: SupervisedRTSPSourceConfig,
    on_stall: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> SupervisedRTSPSource:
    return SupervisedRTSPSource(config=config, on_stall=on_stall)