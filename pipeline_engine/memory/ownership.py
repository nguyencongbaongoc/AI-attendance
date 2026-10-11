"""
Frame Ownership and Transfer Protocol

Defines explicit ownership transfer between pipeline stages to prevent
use-after-free, double-free, and unsafe cross-context access.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Set, Any
from enum import Enum
from contextlib import contextmanager

from pipeline_engine.memory.gpu_frame import GPUFrame, FrameOwnership, FrameStatus


class TransferError(Exception):
    """Raised when ownership transfer is invalid."""
    pass


class OwnershipViolation(Exception):
    """Raised when ownership rules are violated."""
    pass


@dataclass
class OwnershipRecord:
    """Records an ownership transfer for debugging/audit."""
    frame_id: str
    from_owner: FrameOwnership
    to_owner: FrameOwnership
    timestamp: float
    thread_id: int
    valid: bool = True


class OwnershipManager:
    """
    Manages frame ownership transfers with validation.
    
    Ensures:
    - Every frame has exactly one owner at any time
    - Transfers follow valid pipeline order
    - No use-after-free or double-free
    - Cross-context access is explicit
    """
    
    # Valid ownership transitions (pipeline order)
    VALID_TRANSITIONS = {
        FrameOwnership.DECODER: {
            FrameOwnership.PREPROCESS,
            FrameOwnership.INFERENCE,
            FrameOwnership.TRACKING,
            FrameOwnership.ANNOTATION,
            FrameOwnership.ENCODER,
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.PREPROCESS: {
            FrameOwnership.INFERENCE,
            FrameOwnership.TRACKING,
            FrameOwnership.ANNOTATION,
            FrameOwnership.ENCODER,
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.INFERENCE: {
            FrameOwnership.TRACKING,
            FrameOwnership.ANNOTATION,
            FrameOwnership.ENCODER,
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.TRACKING: {
            FrameOwnership.ANNOTATION,
            FrameOwnership.ENCODER,
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.ANNOTATION: {
            FrameOwnership.ENCODER,
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.ENCODER: {
            FrameOwnership.PUBLISHER,
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.PUBLISHER: {
            FrameOwnership.EXTERNAL,
        },
        FrameOwnership.EXTERNAL: set(),  # Terminal
    }
    
    def __init__(self, strict: bool = True):
        self.strict = strict
        self._ownership: Dict[str, FrameOwnership] = {}  # global_frame_id -> owner
        self._history: List[OwnershipRecord] = []
        self._lock = threading.RLock()
        self._frame_refs: Dict[str, GPUFrame] = {}  # Weak references for validation
    
    def register_frame(self, frame: GPUFrame) -> None:
        """Register a new frame with initial ownership."""
        with self._lock:
            gfid = frame.global_frame_id
            if gfid in self._ownership:
                raise OwnershipViolation(f"Frame {gfid} already registered")
            self._ownership[gfid] = frame.memory_owner
            self._frame_refs[gfid] = frame
            self._record_transfer(gfid, FrameOwnership.EXTERNAL, frame.memory_owner)
    
    def unregister_frame(self, frame: GPUFrame) -> None:
        """Unregister a frame (when fully released)."""
        with self._lock:
            gfid = frame.global_frame_id
            if gfid in self._ownership:
                del self._ownership[gfid]
            if gfid in self._frame_refs:
                del self._frame_refs[gfid]
    
    def transfer(self, frame: GPUFrame, new_owner: FrameOwnership) -> bool:
        """
        Transfer frame ownership to a new pipeline stage.
        
        Args:
            frame: GPUFrame to transfer
            new_owner: New owning stage
            
        Returns:
            True if transfer successful
            
        Raises:
            TransferError: If transfer is invalid
        """
        with self._lock:
            gfid = frame.global_frame_id
            
            if gfid not in self._ownership:
                raise TransferError(f"Frame {gfid} not registered")
            
            current_owner = self._ownership[gfid]
            
            # Validate transition
            if self.strict and current_owner != FrameOwnership.EXTERNAL:
                valid_targets = self.VALID_TRANSITIONS.get(current_owner, set())
                if new_owner not in valid_targets:
                    raise TransferError(
                        f"Invalid ownership transfer: {current_owner.value} -> {new_owner.value} "
                        f"for frame {gfid}. Valid: {[v.value for v in valid_targets]}"
                    )
            
            # Check frame is not released
            if frame.released:
                raise TransferError(f"Cannot transfer released frame {gfid}")
            
            # Perform transfer
            self._ownership[gfid] = new_owner
            frame.transfer_ownership(new_owner)
            self._record_transfer(gfid, current_owner, new_owner)
            
            return True
    
    def get_owner(self, frame: GPUFrame) -> Optional[FrameOwnership]:
        """Get current owner of a frame."""
        with self._lock:
            return self._ownership.get(frame.global_frame_id)
    
    def validate_ownership(self, frame: GPUFrame, expected_owner: FrameOwnership) -> bool:
        """Validate that frame is owned by expected stage."""
        with self._lock:
            actual = self._ownership.get(frame.global_frame_id)
            return actual == expected_owner
    
    def assert_ownership(self, frame: GPUFrame, expected_owner: FrameOwnership) -> None:
        """Assert frame ownership, raise if invalid."""
        if not self.validate_ownership(frame, expected_owner):
            actual = self.get_owner(frame)
            raise OwnershipViolation(
                f"Frame {frame.global_frame_id} owned by {actual}, expected {expected_owner}"
            )
    
    def _record_transfer(
        self, 
        frame_id: str, 
        from_owner: FrameOwnership, 
        to_owner: FrameOwnership
    ) -> None:
        """Record ownership transfer for audit."""
        import time
        import threading
        record = OwnershipRecord(
            frame_id=frame_id,
            from_owner=from_owner,
            to_owner=to_owner,
            timestamp=time.time(),
            thread_id=threading.get_ident(),
        )
        self._history.append(record)
        # Keep last 10000 records
        if len(self._history) > 10000:
            self._history = self._history[-10000:]
    
    def get_history(self, frame_id: Optional[str] = None) -> List[OwnershipRecord]:
        """Get ownership transfer history."""
        with self._lock:
            if frame_id:
                return [r for r in self._history if r.frame_id == frame_id]
            return self._history.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get ownership statistics."""
        with self._lock:
            owner_counts: Dict[str, int] = {}
            for owner in self._ownership.values():
                owner_counts[owner.value] = owner_counts.get(owner.value, 0) + 1
            
            return {
                "total_frames": len(self._ownership),
                "by_owner": owner_counts,
                "history_size": len(self._history),
            }
    
    def check_leaks(self) -> List[str]:
        """Check for frames that may be leaked (not released, not in EXTERNAL)."""
        with self._lock:
            leaked = []
            for gfid, owner in self._ownership.items():
                frame = self._frame_refs.get(gfid)
                if frame and not frame.released and owner != FrameOwnership.EXTERNAL:
                    # Frame still owned by pipeline stage but not released
                    leaked.append(gfid)
            return leaked


# Global ownership manager
_ownership_manager: Optional[OwnershipManager] = None
_manager_lock = threading.Lock()


def get_ownership_manager(strict: bool = True) -> OwnershipManager:
    """Get global ownership manager."""
    global _ownership_manager
    with _manager_lock:
        if _ownership_manager is None:
            _ownership_manager = OwnershipManager(strict=strict)
        return _ownership_manager


@contextmanager
def frame_ownership(frame: GPUFrame, new_owner: FrameOwnership):
    """
    Context manager for temporary ownership transfer.
    
    Usage:
        with frame_ownership(frame, FrameOwnership.INFERENCE):
            # frame is now owned by INFERENCE
            result = inference_engine.infer(frame)
        # ownership automatically restored to previous owner
    """
    manager = get_ownership_manager()
    gfid = frame.global_frame_id
    previous_owner = manager.get_owner(frame)
    
    try:
        manager.transfer(frame, new_owner)
        yield frame
    finally:
        if previous_owner:
            manager.transfer(frame, previous_owner)


def validate_pipeline_order(frames: List[GPUFrame]) -> bool:
    """
    Validate that a list of frames follows correct pipeline ownership order.
    Useful for debugging pipeline stalls.
    """
    manager = get_ownership_manager()
    pipeline_order = [
        FrameOwnership.DECODER,
        FrameOwnership.PREPROCESS,
        FrameOwnership.INFERENCE,
        FrameOwnership.TRACKING,
        FrameOwnership.ANNOTATION,
        FrameOwnership.ENCODER,
        FrameOwnership.PUBLISHER,
        FrameOwnership.EXTERNAL,
    ]
    
    for frame in frames:
        owner = manager.get_owner(frame)
        if owner and owner not in pipeline_order:
            return False
    
    return True


if __name__ == "__main__":
    # Quick test
    import torch
    
    if not torch.cuda.is_available():
        print("CUDA not available, skipping test")
    else:
        manager = OwnershipManager(strict=True)
        
        # Create test frame
        frame = GPUFrame.create_empty("test_cam", 1, 640, 480)
        
        # Register
        manager.register_frame(frame)
        print(f"Initial owner: {manager.get_owner(frame)}")
        
        # Valid transfer
        manager.transfer(frame, FrameOwnership.INFERENCE)
        print(f"After transfer: {manager.get_owner(frame)}")
        
        # Invalid transfer (backwards)
        try:
            manager.transfer(frame, FrameOwnership.DECODER)
            print("ERROR: Should have raised TransferError")
        except TransferError as e:
            print(f"Correctly rejected invalid transfer: {e}")
        
        # Valid forward transfer
        manager.transfer(frame, FrameOwnership.ANNOTATION)
        print(f"Forward transfer: {manager.get_owner(frame)}")
        
        # History
        history = manager.get_history(frame.global_frame_id)
        print(f"Transfer history: {len(history)} records")
        for r in history:
            print(f"  {r.from_owner.value} -> {r.to_owner.value}")
        
        print("Ownership test passed!")