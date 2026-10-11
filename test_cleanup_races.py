"""
Phase 9.4.2 — Cleanup Race Tests (D1-D5).

Tests cleanup races with shared context architecture.
"""

import sys
import os
import time
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reuse SharedContextManager and SharedContextDecoder from previous test
import torch
import ctypes
import av
import PyNvVideoCodec as nvc
from app.streaming.pynvvideocodec_frame_adapter import create_pynvvideocodec_frame_adapter
from app.data.input_adapter import VideoInfo, WatchdogFrame

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

nvcuda = ctypes.CDLL('nvcuda.dll')

def cuda_check(result, func_name):
    if result != 0:
        raise RuntimeError(f"{func_name} failed with error {result}")
    return result

class SharedContextManager:
    """Manages shared CUDA context for multiple decoders."""
    
    def __init__(self, gpu_device=0):
        self.gpu_device = gpu_device
        self.ctx = None
        self.dev = ctypes.c_int(gpu_device)
        self.ref_count = 0
        self._lock = threading.Lock()
    
    def acquire(self):
        with self._lock:
            if self.ref_count == 0:
                nvcuda.cuInit(0)
                self.ctx = ctypes.c_void_p()
                result = nvcuda.cuDevicePrimaryCtxRetain(ctypes.byref(self.ctx), self.dev)
                cuda_check(result, "cuDevicePrimaryCtxRetain")
                result = nvcuda.cuCtxSetCurrent(self.ctx)
                cuda_check(result, "cuCtxSetCurrent")
                logger.info(f"Shared context acquired: {self.ctx.value}")
            self.ref_count += 1
            return self.ctx
    
    def release(self):
        with self._lock:
            self.ref_count -= 1
            if self.ref_count == 0 and self.ctx:
                nvcuda.cuCtxSetCurrent(ctypes.c_void_p(0))
                result = nvcuda.cuDevicePrimaryCtxRelease(self.dev)
                cuda_check(result, "cuDevicePrimaryCtxRelease")
                logger.info("Shared context released")
                self.ctx = None
    
    def get_context(self):
        return self.ctx


class SharedContextDecoder:
    """Decoder using explicit shared CUDA context."""
    
    def __init__(self, cam_id, rtsp_url, shared_ctx, stream, width=3840, height=2160, fps=30.0):
        self.cam_id = cam_id
        self.rtsp_url = rtsp_url
        self.shared_ctx = shared_ctx
        self.cuda_stream = stream
        self.width = width
        self.height = height
        self.fps = fps
        
        self._decoder = None
        self._container = None
        self._stream = None
        self._frame_adapter = None
        self._frame_queue = None
        self._stop_event = threading.Event()
        self._reader_thread = None
        self._frame_index = 0
        self._lock = threading.RLock()
        self._opened = False
        self._error = None
    
    def initialize(self):
        logger.info(f"[{self.cam_id}] Initializing with shared context {self.shared_ctx.value}")
        self._decoder = nvc.CreateDecoder(
            gpuid=0,
            codec=nvc.cudaVideoCodec.H264,
            cudacontext=self.shared_ctx.value,
            cudastream=self.cuda_stream.cuda_stream,
            usedevicememory=1,
            enableasyncallocations=1,
            maxwidth=self.width,
            maxheight=self.height,
            outputColorType=nvc.OutputColorType.NATIVE,
            enableSEIMessage=0,
            latency=nvc.DisplayDecodeLatencyType.NATIVE,
            enableDecodeStats=0,
        )
        self._frame_adapter = create_pynvvideocodec_frame_adapter(
            camera_id=self.cam_id,
            cuda_stream=self.cuda_stream.cuda_stream,
            device_id=0,
        )
        logger.info(f"[{self.cam_id}] Decoder created")
    
    def _open_demuxer(self):
        logger.info(f"[{self.cam_id}] Opening demuxer for {self.rtsp_url}")
        options = {"rtsp_transport": "tcp"}
        self._container = av.open(
            self.rtsp_url,
            format="rtsp",
            options=options,
        )
        self._stream = self._container.streams.video[0]
        self.width = self._stream.width or self.width
        self.height = self._stream.height or self.height
        self.fps = float(self._stream.average_rate) if self._stream.average_rate else self.fps
        logger.info(f"[{self.cam_id}] Stream: {self.width}x{self.height}@{self.fps}fps")
    
    def open(self):
        if self._decoder is None:
            self.initialize()
        self._open_demuxer()
        self._frame_queue = __import__('queue').Queue(maxsize=10)
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"shared-ctx-reader-{self.cam_id}",
            daemon=True,
        )
        self._reader_thread.start()
        self._opened = True
        self._frame_index = 0
        self._error = None
        info = VideoInfo(
            width=self.width, height=self.height, fps=self.fps,
            frame_count=0, duration=0.0, codec="h264",
            pixel_format="cuda", path=self.rtsp_url,
        )
        logger.info(f"[{self.cam_id}] Opened: {self.width}x{self.height}@{self.fps}fps")
        return info
    
    def _reader_loop(self):
        try:
            for packet in self._container.demux(self._stream):
                if self._stop_event.is_set():
                    break
                if packet.is_corrupt:
                    continue
                pnv_packet = nvc.PacketData()
                pnv_packet.bsl = packet.size
                pnv_packet.bsl_data = packet.buffer_ptr
                pnv_packet.pts = packet.pts if packet.pts is not None else 0
                pnv_packet.dts = packet.dts if packet.dts is not None else 0
                pnv_packet.duration = packet.duration if packet.duration is not None else 0
                pnv_packet.decode_flag = 0
                pnv_packet.key = 1 if packet.is_keyframe else 0
                pnv_packet.is_video = 1
                pnv_packet.stream_index = 0
                try:
                    decoded_frames = self._decoder.Decode(pnv_packet)
                except Exception as e:
                    logger.error(f"[{self.cam_id}] Decode failed: {e}")
                    self._error = e
                    continue
                for decoded_frame in decoded_frames:
                    if self._stop_event.is_set():
                        break
                    timestamp = time.time()
                    pts = decoded_frame.getPTS()
                    try:
                        frame_contract = self._frame_adapter.adapt(
                            decoded_frame=decoded_frame, timestamp=timestamp, pts=pts)
                    except Exception as e:
                        logger.error(f"[{self.cam_id}] Frame adaptation failed: {e}")
                        try:
                            self._decoder.UnlockFrame(0)
                        except:
                            pass
                        continue
                    wframe = WatchdogFrame(
                        data=frame_contract, frame_index=self._frame_index,
                        timestamp=timestamp, pts=pts, stalled=False)
                    try:
                        self._frame_queue.put_nowait(wframe)
                    except __import__('queue').Full:
                        try:
                            self._frame_queue.get_nowait()
                        except __import__('queue').Empty:
                            pass
                        try:
                            self._frame_queue.put_nowait(wframe)
                        except __import__('queue').Full:
                            pass
                    self._frame_index += 1
                    try:
                        self._decoder.UnlockFrame(0)
                    except Exception as e:
                        logger.debug(f"[{self.cam_id}] UnlockFrame error: {e}")
        except av.error.FFmpegError as e:
            logger.error(f"[{self.cam_id}] Demux error: {e}")
            self._error = e
        except Exception as e:
            logger.error(f"[{self.cam_id}] Reader loop error: {e}")
            self._error = e
        finally:
            logger.debug(f"[{self.cam_id}] Reader loop exited")
    
    def get_frame(self):
        try:
            return self._frame_queue.get(timeout=1.0)
        except __import__('queue').Empty:
            return None
    
    def close(self):
        with self._lock:
            if not self._opened and self._decoder is None:
                return
            logger.info(f"[{self.cam_id}] Closing")
            self._stop_event.set()
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=3.0)
            if self._container:
                try:
                    self._container.close()
                except Exception as e:
                    logger.debug(f"[{self.cam_id}] Container close error: {e}")
                finally:
                    self._container = None
                    self._stream = None
            self._decoder = None
            self._frame_adapter = None
            self._opened = False
            logger.info(f"[{self.cam_id}] Closed")
    
    def health(self):
        return {
            "camera_id": self.cam_id,
            "backend": "pynvvideocodec-shared",
            "opened": self._opened,
            "frame_index": self._frame_index,
            "queue_size": self._frame_queue.qsize() if self._frame_queue else 0,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "error": str(self._error) if self._error else None,
        }


def create_decoder(cam_id, url, ctx_manager, stream):
    """Helper to create and open a decoder."""
    decoder = SharedContextDecoder(cam_id, url, ctx_manager.get_context(), stream)
    decoder.initialize()
    return decoder


# ==================== D1-D5 TESTS ====================

def test_d1_cam1_active_cam2_init():
    """D1: CAM1 active → initialize CAM2 → both active."""
    logger.info("=" * 60)
    logger.info("TEST D1: CAM1 active -> CAM2 init -> both active")
    logger.info("=" * 60)
    
    ctx_manager = SharedContextManager()
    ctx_manager.acquire()
    device = torch.device('cuda:0')
    
    try:
        # Start CAM1
        stream1 = torch.cuda.Stream(device=device)
        cam1 = create_decoder("CAM1", "rtsp://localhost:8554/live/cam1", ctx_manager, stream1)
        info1 = cam1.open()
        logger.info(f"CAM1 active: {info1.width}x{info1.height}")
        
        # Collect some frames
        for _ in range(5):
            cam1.get_frame()
            time.sleep(0.05)
        
        # Now initialize CAM2 while CAM1 is active
        logger.info("Initializing CAM2 while CAM1 is active...")
        stream2 = torch.cuda.Stream(device=device)
        cam2 = create_decoder("CAM2", "rtsp://localhost:8554/live/cam2", ctx_manager, stream2)
        info2 = cam2.open()
        logger.info(f"CAM2 active: {info2.width}x{info2.height}")
        
        # Both should be running
        time.sleep(3)
        
        frames1 = 0
        frames2 = 0
        for _ in range(10):
            wf = cam1.get_frame()
            if wf and not wf.stalled:
                frames1 += 1
            wf = cam2.get_frame()
            if wf and not wf.stalled:
                frames2 += 1
            time.sleep(0.05)
        logger.info(f"Frames: CAM1={frames1}, CAM2={frames2}")
        
        cam1.close()
        cam2.close()
        
        return frames1 > 0 and frames2 > 0
        
    finally:
        ctx_manager.release()


def test_d2_cam1_stop_then_cam2_init():
    """D2: CAM1 active → stop CAM1 → initialize CAM2."""
    logger.info("=" * 60)
    logger.info("TEST D2: CAM1 active -> stop CAM1 -> CAM2 init")
    logger.info("=" * 60)
    
    ctx_manager = SharedContextManager()
    ctx_manager.acquire()
    device = torch.device('cuda:0')
    
    try:
        # Start CAM1
        stream1 = torch.cuda.Stream(device=device)
        cam1 = create_decoder("CAM1", "rtsp://localhost:8554/live/cam1", ctx_manager, stream1)
        cam1.open()
        logger.info("CAM1 active")
        
        for _ in range(5):
            cam1.get_frame()
            time.sleep(0.05)
        
        # Stop CAM1
        logger.info("Stopping CAM1...")
        cam1.close()
        logger.info("CAM1 stopped")
        
        # Initialize CAM2
        logger.info("Initializing CAM2 after CAM1 stopped...")
        stream2 = torch.cuda.Stream(device=device)
        cam2 = create_decoder("CAM2", "rtsp://localhost:8554/live/cam2", ctx_manager, stream2)
        info2 = cam2.open()
        logger.info(f"CAM2 active: {info2.width}x{info2.height}")
        
        frames2 = 0
        for _ in range(10):
            wf = cam2.get_frame()
            if wf and not wf.stalled:
                frames2 += 1
            time.sleep(0.05)
        logger.info(f"CAM2 frames: {frames2}")
        
        cam2.close()
        return frames2 > 0
        
    finally:
        ctx_manager.release()


def test_d3_cam2_stop_then_cam1_init():
    """D3: CAM2 active → stop CAM2 → initialize CAM1."""
    logger.info("=" * 60)
    logger.info("TEST D3: CAM2 active -> stop CAM2 -> CAM1 init")
    logger.info("=" * 60)
    
    ctx_manager = SharedContextManager()
    ctx_manager.acquire()
    device = torch.device('cuda:0')
    
    try:
        # Start CAM2
        stream2 = torch.cuda.Stream(device=device)
        cam2 = create_decoder("CAM2", "rtsp://localhost:8554/live/cam2", ctx_manager, stream2)
        cam2.open()
        logger.info("CAM2 active")
        
        for _ in range(5):
            cam2.get_frame()
            time.sleep(0.05)
        
        # Stop CAM2
        logger.info("Stopping CAM2...")
        cam2.close()
        logger.info("CAM2 stopped")
        
        # Initialize CAM1
        logger.info("Initializing CAM1 after CAM2 stopped...")
        stream1 = torch.cuda.Stream(device=device)
        cam1 = create_decoder("CAM1", "rtsp://localhost:8554/live/cam1", ctx_manager, stream1)
        info1 = cam1.open()
        logger.info(f"CAM1 active: {info1.width}x{info1.height}")
        
        frames1 = 0
        for _ in range(10):
            wf = cam1.get_frame()
            if wf and not wf.stalled:
                frames1 += 1
            time.sleep(0.05)
        logger.info(f"CAM1 frames: {frames1}")
        
        cam1.close()
        return frames1 > 0
        
    finally:
        ctx_manager.release()


def test_d4_cam1_reconnect_while_cam2_active():
    """D4: CAM1 active → reconnect CAM1 while CAM2 remains active."""
    logger.info("=" * 60)
    logger.info("TEST D4: CAM1 reconnect while CAM2 active")
    logger.info("=" * 60)
    
    ctx_manager = SharedContextManager()
    ctx_manager.acquire()
    device = torch.device('cuda:0')
    
    try:
        # Start both
        stream1 = torch.cuda.Stream(device=device)
        stream2 = torch.cuda.Stream(device=device)
        
        cam1 = create_decoder("CAM1", "rtsp://localhost:8554/live/cam1", ctx_manager, stream1)
        cam1.open()
        
        cam2 = create_decoder("CAM2", "rtsp://localhost:8554/live/cam2", ctx_manager, stream2)
        cam2.open()
        
        logger.info("Both CAM1 and CAM2 active")
        time.sleep(2)
        
        # Reconnect CAM1 (close and reopen)
        logger.info("Reconnecting CAM1 while CAM2 stays active...")
        cam1.close()
        logger.info("CAM1 closed")
        
        # Recreate CAM1 with same context
        stream1_new = torch.cuda.Stream(device=device)
        cam1_new = create_decoder("CAM1", "rtsp://localhost:8554/live/cam1", ctx_manager, stream1_new)
        info1 = cam1_new.open()
        logger.info(f"CAM1 reconnected: {info1.width}x{info1.height}")
        
        # Both should work
        time.sleep(3)
        
        frames1 = 0
        frames2 = 0
        for _ in range(10):
            wf = cam1_new.get_frame()
            if wf and not wf.stalled:
                frames1 += 1
            wf = cam2.get_frame()
            if wf and not wf.stalled:
                frames2 += 1
            time.sleep(0.05)
        logger.info(f"Frames: CAM1={frames1}, CAM2={frames2}")
        
        cam1_new.close()
        cam2.close()
        
        return frames1 > 0 and frames2 > 0
        
    finally:
        ctx_manager.release()


def test_d5_cam2_reconnect_while_cam1_active():
    """D5: CAM2 active → reconnect CAM2 while CAM1 remains active."""
    logger.info("=" * 60)
    logger.info("TEST D5: CAM2 reconnect while CAM1 active")
    logger.info("=" * 60)
    
    ctx_manager = SharedContextManager()
    ctx_manager.acquire()
    device = torch.device('cuda:0')
    
    try:
        # Start both
        stream1 = torch.cuda.Stream(device=device)
        stream2 = torch.cuda.Stream(device=device)
        
        cam1 = create_decoder("CAM1", "rtsp://localhost:8554/live/cam1", ctx_manager, stream1)
        cam1.open()
        
        cam2 = create_decoder("CAM2", "rtsp://localhost:8554/live/cam2", ctx_manager, stream2)
        cam2.open()
        
        logger.info("Both CAM1 and CAM2 active")
        time.sleep(2)
        
        # Reconnect CAM2
        logger.info("Reconnecting CAM2 while CAM1 stays active...")
        cam2.close()
        logger.info("CAM2 closed")
        
        stream2_new = torch.cuda.Stream(device=device)
        cam2_new = create_decoder("CAM2", "rtsp://localhost:8554/live/cam2", ctx_manager, stream2_new)
        info2 = cam2_new.open()
        logger.info(f"CAM2 reconnected: {info2.width}x{info2.height}")
        
        time.sleep(3)
        
        frames1 = 0
        frames2 = 0
        for _ in range(10):
            wf = cam1.get_frame()
            if wf and not wf.stalled:
                frames1 += 1
            wf = cam2_new.get_frame()
            if wf and not wf.stalled:
                frames2 += 1
            time.sleep(0.05)
        logger.info(f"Frames: CAM1={frames1}, CAM2={frames2}")
        
        cam1.close()
        cam2_new.close()
        
        return frames1 > 0 and frames2 > 0
        
    finally:
        ctx_manager.release()


def main():
    logger.info("PHASE 9.4.2 — CLEANUP RACE TESTS (D1-D5)")
    logger.info("=" * 60)
    
    results = {}
    
    # D1
    logger.info("\n>>> D1")
    results["D1"] = test_d1_cam1_active_cam2_init()
    time.sleep(2)
    
    # D2
    logger.info("\n>>> D2")
    results["D2"] = test_d2_cam1_stop_then_cam2_init()
    time.sleep(2)
    
    # D3
    logger.info("\n>>> D3")
    results["D3"] = test_d3_cam2_stop_then_cam1_init()
    time.sleep(2)
    
    # D4
    logger.info("\n>>> D4")
    results["D4"] = test_d4_cam1_reconnect_while_cam2_active()
    time.sleep(2)
    
    # D5
    logger.info("\n>>> D5")
    results["D5"] = test_d5_cam2_reconnect_while_cam1_active()
    
    # Summary
    logger.info("=" * 60)
    logger.info("CLEANUP RACE TEST SUMMARY")
    logger.info("=" * 60)
    for test, passed in results.items():
        logger.info(f"{test}: {'PASS' if passed else 'FAIL'}")
    
    all_passed = all(results.values())
    logger.info(f"OVERALL: {'ALL PASS' if all_passed else 'SOME FAIL'}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())