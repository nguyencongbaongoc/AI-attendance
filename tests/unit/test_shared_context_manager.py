"""
Phase 9.4.3 — Unit Tests for Shared Context Manager.

Tests:
- One context per GPU
- Multiple decoder references
- Reference lifetime
- Final release
- Thread safety
- No premature destruction
"""

import pytest
import threading
import time
from app.streaming.cuda_context_manager import CUDAContextManager, SharedContextManager


class TestCUDAContextManager:
    """Tests for CUDAContextManager."""
    
    def test_singleton_per_gpu(self):
        """Test that only one instance exists per GPU device."""
        mgr1 = CUDAContextManager.get_instance(0)
        mgr2 = CUDAContextManager.get_instance(0)
        mgr3 = CUDAContextManager.get_instance(1)
        
        assert mgr1 is mgr2
        assert mgr1 is not mgr3
        assert mgr1.gpu_device == 0
        assert mgr3.gpu_device == 1
    
    def test_acquire_release_refcount(self):
        """Test reference counting on acquire/release."""
        mgr = CUDAContextManager.get_instance(0)
        
        # Initial state
        assert mgr.get_ref_count() == 0
        assert not mgr.is_acquired()
        
        # Acquire once
        handle1 = mgr.acquire()
        assert mgr.get_ref_count() == 1
        assert mgr.is_acquired()
        assert handle1.value > 0
        assert handle1.device == 0
        
        # Acquire again (should return same handle)
        handle2 = mgr.acquire()
        assert mgr.get_ref_count() == 2
        assert handle2 is handle1
        
        # Release once
        mgr.release()
        assert mgr.get_ref_count() == 1
        assert mgr.is_acquired()
        
        # Release again (should release context)
        mgr.release()
        assert mgr.get_ref_count() == 0
        assert not mgr.is_acquired()
    
    def test_get_context_handle(self):
        """Test getting context handle without changing ref count."""
        mgr = CUDAContextManager.get_instance(0)
        
        # Before acquire
        assert mgr.get_context_handle() is None
        
        # After acquire
        handle = mgr.acquire()
        retrieved = mgr.get_context_handle()
        assert retrieved is handle
        
        # After release
        mgr.release()
        assert mgr.get_context_handle() is None
    
    def test_force_release_all(self):
        """Test force release cleans up all references."""
        mgr = CUDAContextManager.get_instance(0)
        
        mgr.acquire()
        mgr.acquire()
        assert mgr.get_ref_count() == 2
        
        mgr.force_release_all()
        assert mgr.get_ref_count() == 0
        assert not mgr.is_acquired()
    
    def test_concurrent_acquire_release(self):
        """Test thread-safe acquire/release."""
        mgr = CUDAContextManager.get_instance(0)
        errors = []
        
        def acquire_release():
            try:
                for _ in range(10):
                    handle = mgr.acquire()
                    assert handle.value > 0
                    time.sleep(0.001)
                    mgr.release()
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=acquire_release) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert mgr.get_ref_count() == 0


class TestSharedContextManager:
    """Tests for SharedContextManager."""
    
    def test_context_acquire_release(self):
        """Test shared context acquire/release through high-level manager."""
        mgr = SharedContextManager(0)
        
        # Acquire context
        ctx_handle = mgr.acquire_context()
        assert ctx_handle.value > 0
        assert mgr.get_ref_count() == 1
        
        # Release context
        mgr.release_context()
        assert mgr.get_ref_count() == 0
    
    def test_create_release_stream(self):
        """Test per-camera stream creation and release."""
        mgr = SharedContextManager(0)
        
        mgr.acquire_context()
        
        # Create stream for camera
        stream1 = mgr.create_stream("cam1")
        assert stream1 > 0
        
        # Get existing stream
        retrieved = mgr.get_stream("cam1")
        assert retrieved == stream1
        
        # Release stream
        mgr.release_stream("cam1")
        assert mgr.get_stream("cam1") is None
        
        mgr.release_context()
    
    def test_independent_streams_per_camera(self):
        """Test each camera gets independent stream."""
        mgr = SharedContextManager(0)
        mgr.acquire_context()
        
        stream1 = mgr.create_stream("cam1")
        stream2 = mgr.create_stream("cam2")
        
        assert stream1 > 0
        assert stream2 > 0
        assert stream1 != stream2
        
        mgr.release_stream("cam1")
        mgr.release_stream("cam2")
        mgr.release_context()
    
    def test_context_manager_interface(self):
        """Test context manager protocol."""
        mgr = SharedContextManager(0)
        
        with mgr as ctx:
            handle = mgr.get_context_handle()
            assert handle is not None
            assert handle.value > 0
            assert mgr.get_ref_count() == 1
        
        # Context not auto-released on exit (managed by factory)
        assert mgr.get_ref_count() == 1
        
        # Manual release
        mgr.release_context()
        assert mgr.get_ref_count() == 0


class TestContextLifetime:
    """Tests for context lifetime management across decoders."""
    
    def test_context_survives_first_decoder_close(self):
        """Test context remains alive after first decoder releases it."""
        mgr = CUDAContextManager.get_instance(0)
        
        # Simulate decoder 1 acquiring
        handle1 = mgr.acquire()
        assert mgr.get_ref_count() == 1
        
        # Simulate decoder 2 acquiring
        handle2 = mgr.acquire()
        assert mgr.get_ref_count() == 2
        assert handle1 is handle2
        
        # Decoder 1 releases
        mgr.release()
        assert mgr.get_ref_count() == 1
        assert mgr.is_acquired()
        assert mgr.get_context_handle() is handle1
        
        # Decoder 2 releases
        mgr.release()
        assert mgr.get_ref_count() == 0
        assert not mgr.is_acquired()
    
    def test_premature_destruction_prevented(self):
        """Test context not destroyed while any decoder holds reference."""
        mgr = CUDAContextManager.get_instance(0)
        
        # Multiple acquires
        for _ in range(5):
            mgr.acquire()
        assert mgr.get_ref_count() == 5
        
        # Release 4
        for _ in range(4):
            mgr.release()
        assert mgr.get_ref_count() == 1
        assert mgr.is_acquired()
        
        # Final release
        mgr.release()
        assert mgr.get_ref_count() == 0
        assert not mgr.is_acquired()


class TestGPUIsolation:
    """Tests for GPU device isolation."""
    
    def test_separate_managers_per_gpu(self):
        """Test each GPU has independent context manager (skipped if single GPU)."""
        mgr0 = CUDAContextManager.get_instance(0)
        mgr1 = CUDAContextManager.get_instance(1)
        
        mgr0.acquire()
        assert mgr0.get_ref_count() == 1
        
        try:
            mgr1.acquire()
        except RuntimeError as e:
            if "error 101" in str(e):  # Invalid device - single GPU system
                pytest.skip("Single GPU system - cannot test multi-GPU isolation")
            raise
        
        assert mgr0.get_ref_count() == 1
        assert mgr1.get_ref_count() == 1
        
        # Release one shouldn't affect other
        mgr0.release()
        assert mgr0.get_ref_count() == 0
        assert mgr1.get_ref_count() == 1
        
        mgr1.release()
        assert mgr1.get_ref_count() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])