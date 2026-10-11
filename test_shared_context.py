"""
Phase 9.4.2 — Shared Context Experiment (Fixed).

Tests whether explicit shared CUDA context allows concurrent decoders.
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

def init_cuda():
    """Initialize CUDA driver."""
    result = nvcuda.cuInit(0)
    cuda_check(result, "cuInit")
    logger.info("CUDA driver initialized")

def create_explicit_context():
    """Create an explicit CUDA context using primary context."""
    dev = ctypes.c_int(0)
    ctx = ctypes.c_void_p()
    
    # Retain primary context
    result = nvcuda.cuDevicePrimaryCtxRetain(ctypes.byref(ctx), dev)
    cuda_check(result, "cuDevicePrimaryCtxRetain")
    logger.info(f"Primary context retained: {ctx.value}")
    
    # Set as current
    result = nvcuda.cuCtxSetCurrent(ctx)
    cuda_check(result, "cuCtxSetCurrent")
    logger.info(f"Context set as current: {ctx.value}")
    
    return ctx, dev

def release_explicit_context(ctx, dev):
    """Release the explicit context."""
    # Pop current
    result = nvcuda.cuCtxSetCurrent(ctypes.c_void_p(0))
    # Release
    result = nvcuda.cuDevicePrimaryCtxRelease(dev)
    cuda_check(result, "cuDevicePrimaryCtxRelease")
    logger.info("Primary context released")

def create_decoder_with_context(ctx_handle, stream_handle, cam_id):
    """Create a decoder with explicit context and stream."""
    logger.info(f"[{cam_id}] Creating decoder with context={ctx_handle}, stream={stream_handle}")
    
    decoder = nvc.CreateDecoder(
        gpuid=0,
        codec=nvc.cudaVideoCodec.H264,
        cudacontext=ctx_handle,  # Explicit context!
        cudastream=stream_handle,
        usedevicememory=1,
        enableasyncallocations=1,
        maxwidth=3840,
        maxheight=2160,
        outputColorType=nvc.OutputColorType.NATIVE,
        enableSEIMessage=0,
        latency=nvc.DisplayDecodeLatencyType.NATIVE,
        enableDecodeStats=0,
    )
    logger.info(f"[{cam_id}] Decoder created successfully")
    return decoder

def test_shared_context_decoders():
    """Test: Create shared context, then two decoders with it."""
    logger.info("=" * 60)
    logger.info("TEST: Shared Explicit Context with Two Decoders")
    logger.info("=" * 60)
    
    # Initialize CUDA first
    init_cuda()
    
    # Step 1: Create explicit context
    ctx, dev = create_explicit_context()
    
    try:
        # Step 2: Create two PyTorch streams on the same device
        device = torch.device('cuda:0')
        stream1 = torch.cuda.Stream(device=device)
        stream2 = torch.cuda.Stream(device=device)
        logger.info(f"Stream 1: {stream1.cuda_stream}")
        logger.info(f"Stream 2: {stream2.cuda_stream}")
        
        # Step 3: Create first decoder
        decoder1 = create_decoder_with_context(ctx.value, stream1.cuda_stream, "CAM1")
        
        # Step 4: Create second decoder (same context, different stream)
        decoder2 = create_decoder_with_context(ctx.value, stream2.cuda_stream, "CAM2")
        
        logger.info("SUCCESS: Both decoders created with shared context!")
        
        # Cleanup
        decoder1 = None
        decoder2 = None
        logger.info("Decoders released")
        
    finally:
        release_explicit_context(ctx, dev)
    
    return True

def test_concurrent_init_with_shared_context():
    """Test concurrent initialization using shared context."""
    logger.info("=" * 60)
    logger.info("TEST: Concurrent Init with Shared Context (Threaded)")
    logger.info("=" * 60)
    
    # Initialize CUDA first
    init_cuda()
    
    # Create shared context in main thread
    ctx, dev = create_explicit_context()
    
    try:
        device = torch.device('cuda:0')
        stream1 = torch.cuda.Stream(device=device)
        stream2 = torch.cuda.Stream(device=device)
        
        results = {}
        
        def init_decoder(cam_id, stream_handle):
            try:
                # Set context in this thread
                nvcuda.cuCtxSetCurrent(ctx)
                
                decoder = create_decoder_with_context(ctx.value, stream_handle, cam_id)
                results[cam_id] = {"success": True, "decoder": decoder}
            except Exception as e:
                logger.error(f"[{cam_id}] Failed: {e}")
                results[cam_id] = {"success": False, "error": str(e)}
        
        # Run concurrently
        t1 = threading.Thread(target=init_decoder, args=("CAM1", stream1.cuda_stream))
        t2 = threading.Thread(target=init_decoder, args=("CAM2", stream2.cuda_stream))
        
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        
        logger.info(f"Results: {results}")
        
    finally:
        release_explicit_context(ctx, dev)

def main():
    logger.info("PHASE 9.4.2 — SHARED CONTEXT EXPERIMENT")
    logger.info("=" * 60)
    
    try:
        # Test 1: Sequential with shared context
        logger.info("\n>>> TEST 1: Sequential Shared Context")
        test_shared_context_decoders()
        
        time.sleep(2)
        
        # Test 2: Concurrent init with shared context
        logger.info("\n>>> TEST 2: Concurrent Init with Shared Context")
        test_concurrent_init_with_shared_context()
        
    except Exception as e:
        logger.error(f"Experiment failed: {e}", exc_info=True)
        return 1
    
    logger.info("=" * 60)
    logger.info("SHARED CONTEXT EXPERIMENT COMPLETE")
    logger.info("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())