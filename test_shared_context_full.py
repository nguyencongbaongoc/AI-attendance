"""
Phase 9.4.2 — Full Pipeline Test with Shared Context.

Tests concurrent decoders with full pipeline (demuxer, reader, frames).
"""

import sys
import os
import time
import threading
import ctypes
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import PyNvVideoCodec as nvc
import torch
import av

from app.streaming.decoder_backend import (
    DecoderBackendConfig,
    PyNvVideoCodecBackendConfig,
)
from app.streaming.pynvvideocodec_frame_adapter import create_pynvvideocodec_frame_adapter
from app.data.input_adapter import VideoInfo, WatchdogFrame

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# CUDA Driver API
nvcuda = ctypes.CDLL('nvcuda.dll')

def cuda_check(result, func_name):
    if result != 0:
        raise RuntimeError(f"{func_name} failed with error {result}")
    return result

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
        """Initialize decoder with shared context."""
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
        logger.info(f"[{self.cam_id}] Decoder created")
        
        # Frame adapter
        self._frame_adapter = create_pynvvideocodec_frame_adapter(
            camera_id=self.cam_id,
            cuda_stream=self.cuda_stream.cuda_stream,
            device_id=0,
        )
        logger.info(f"[{self.cam_id}] Frame adapter created")
    
    def _open_demuxer(self):
        """Open RTSP demuxer."""
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
        """Open decoder and start reader thread."""
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
            width=self.width,
            height=self.height,
            fps=self.fps,
            frame_count=0,
            duration=0.0,
            codec="h264",
            pixel_format="cuda",
            path=self.rtsp_url,
        )
        
        logger.info(f"[{self.cam_id}] Opened: {self.width}x{self.height}@{self.fps}fps")
        return info
    
    def _reader_loop(self):
        """Reader loop - demux, decode, push frames."""
        try:
            for packet in self._container.demux(self._stream):
                if self._stop_event.is_set():
                    break
                
                if packet.is_corrupt:
                    continue
                
                # Create PyNvVideoCodec packet
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
                
                # Decode
                try:
                    decoded_frames = self._decoder.Decode(pnv_packet)
                except Exception as e:
                    logger.error(f"[{self.cam_id}] Decode failed: {e}")
                    self._error = e
                    continue
                
                # Process frames
                for decoded_frame in decoded_frames:
                    if self._stop_event.is_set():
                        break
                    
                    timestamp = time.time()
                    pts = decoded_frame.getPTS()
                    
                    # Adapt to GPUFrameContract
                    try:
                        frame_contract = self._frame_adapter.adapt(
                            decoded_frame=decoded_frame,
                            timestamp=timestamp,
                            pts=pts,
                        )
                    except Exception as e:
                        logger.error(f"[{self.cam_id}] Frame adaptation failed: {e}")
                        try:
                            self._decoder.UnlockFrame(0)
                        except:
                            pass
                        continue
                    
                    # Create watchdog frame
                    wframe = WatchdogFrame(
                        data=frame_contract,
                        frame_index=self._frame_index,
                        timestamp=timestamp,
                        pts=pts,
                        stalled=False,
                    )
                    
                    # Latest-wins queue
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
                    
                    # Unlock
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
        """Get next frame."""
        try:
            return self._frame_queue.get(timeout=1.0)
        except __import__('queue').Empty:
            return None
    
    def close(self):
        """Close decoder."""
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


class SharedContextManager:
    """Manages shared CUDA context for multiple decoders."""
    
    def __init__(self, gpu_device=0):
        self.gpu_device = gpu_device
        self.ctx = None
        self.dev = ctypes.c_int(gpu_device)
        self.ref_count = 0
        self._lock = threading.Lock()
    
    def acquire(self):
        """Acquire shared context (reference counted)."""
        with self._lock:
            if self.ref_count == 0:
                # Initialize CUDA driver
                nvcuda.cuInit(0)
                
                # Retain primary context
                self.ctx = ctypes.c_void_p()
                result = nvcuda.cuDevicePrimaryCtxRetain(ctypes.byref(self.ctx), self.dev)
                cuda_check(result, "cuDevicePrimaryCtxRetain")
                logger.info(f"Shared context acquired: {self.ctx.value}")
                
                # Set as current for main thread
                result = nvcuda.cuCtxSetCurrent(self.ctx)
                cuda_check(result, "cuCtxSetCurrent")
            
            self.ref_count += 1
            return self.ctx
    
    def release(self):
        """Release shared context."""
        with self._lock:
            self.ref_count -= 1
            if self.ref_count == 0 and self.ctx:
                # Pop current
                nvcuda.cuCtxSetCurrent(ctypes.c_void_p(0))
                # Release
                result = nvcuda.cuDevicePrimaryCtxRelease(self.dev)
                cuda_check(result, "cuDevicePrimaryCtxRelease")
                logger.info("Shared context released")
                self.ctx = None
    
    def get_context(self):
        return self.ctx


def test_full_pipeline_concurrent():
    """Test full pipeline with two concurrent cameras."""
    logger.info("=" * 60)
    logger.info("TEST: Full Pipeline - Two Concurrent Cameras")
    logger.info("=" * 60)
    
    # Create shared context manager
    ctx_manager = SharedContextManager(gpu_device=0)
    shared_ctx = ctx_manager.acquire()
    
    try:
        # Create two streams
        device = torch.device('cuda:0')
        stream1 = torch.cuda.Stream(device=device)
        stream2 = torch.cuda.Stream(device=device)
        
        # Create decoders
        cam1 = SharedContextDecoder("CAM1", "rtsp://localhost:8554/live/cam1", 
                                     shared_ctx, stream1)
        cam2 = SharedContextDecoder("CAM2", "rtsp://localhost:8554/live/cam2", 
                                     shared_ctx, stream2)
        
        # Initialize both
        logger.info("Initializing CAM1...")
        cam1.initialize()
        
        logger.info("Initializing CAM2...")
        cam2.initialize()
        
        logger.info("Both decoders initialized successfully!")
        
        # Open both
        logger.info("Opening CAM1...")
        info1 = cam1.open()
        
        logger.info("Opening CAM2...")
        info2 = cam2.open()
        
        logger.info("Both cameras opened! Running for 10 seconds...")
        
        # Collect frames for 10 seconds
        start = time.time()
        frames1 = 0
        frames2 = 0
        
        while time.time() - start < 10:
            wf1 = cam1.get_frame()
            if wf1 and not wf1.stalled:
                frames1 += 1
            
            wf2 = cam2.get_frame()
            if wf2 and not wf2.stalled:
                frames2 += 1
            
            time.sleep(0.01)
        
        logger.info(f"CAM1: {frames1} frames in {time.time()-start:.1f}s")
        logger.info(f"CAM2: {frames2} frames in {time.time()-start:.1f}s")
        
        # Close both
        logger.info("Closing CAM1...")
        cam1.close()
        
        logger.info("Closing CAM2...")
        cam2.close()
        
        # Check results
        success = frames1 > 0 and frames2 > 0
        logger.info(f"Result: {'PASS' if success else 'FAIL'}")
        
        return success
        
    finally:
        ctx_manager.release()


def test_sequential_with_shared_context():
    """Test sequential cameras with shared context (should still work)."""
    logger.info("=" * 60)
    logger.info("TEST: Sequential Cameras with Shared Context")
    logger.info("=" * 60)
    
    ctx_manager = SharedContextManager(gpu_device=0)
    shared_ctx = ctx_manager.acquire()
    
    try:
        device = torch.device('cuda:0')
        
        for cam_id, url in [("CAM1", "rtsp://localhost:8554/live/cam1"),
                            ("CAM2", "rtsp://localhost:8554/live/cam2")]:
            logger.info(f"--- Testing {cam_id} ---")
            
            stream = torch.cuda.Stream(device=device)
            cam = SharedContextDecoder(cam_id, url, shared_ctx, stream)
            
            cam.initialize()
            info = cam.open()
            
            frames = 0
            for i in range(10):
                wf = cam.get_frame()
                if wf and not wf.stalled:
                    frames += 1
                time.sleep(0.05)
            
            logger.info(f"{cam_id}: {frames} frames")
            cam.close()
            
            time.sleep(1)
        
        return True
        
    finally:
        ctx_manager.release()


def main():
    logger.info("PHASE 9.4.2 — FULL PIPELINE SHARED CONTEXT TEST")
    logger.info("=" * 60)
    
    # Test 1: Sequential
    logger.info("\n>>> TEST 1: Sequential with Shared Context")
    test_sequential_with_shared_context()
    
    time.sleep(2)
    
    # Test 2: Concurrent
    logger.info("\n>>> TEST 2: Concurrent Full Pipeline")
    success = test_full_pipeline_concurrent()
    
    logger.info("=" * 60)
    logger.info(f"FINAL RESULT: {'PASS' if success else 'FAIL'}")
    logger.info("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    import time
    sys.exit(main())