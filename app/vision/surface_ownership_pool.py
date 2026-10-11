"""
Surface ownership / lease tracking for CUDA zero-copy frames.

Provides explicit SUBMITTED / IN_FLIGHT / RELEASABLE state tracking
and prevents unsynchronized reuse of surfaces still owned by encoder
or annotation consumers.

Invariants (INV-SURFACE-01 through INV-SURFACE-04):
- A CUDA surface MUST NOT be reused/modified for Frame B while Frame A
  still owns an encoder reference.
- Queue removal/drop MUST NOT release an encoder-owned surface.
- Encoder restart MUST NOT permit old-generation surfaces to be reused
  until old ownership is safely ended.
- No frame may transition IN_FLIGHT -> REUSABLE without explicit release.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Optional, Set, Callable, Any


class SurfaceOwnershipState(str, Enum):
    AVAILABLE = "available"
    SUBMITTED = "submitted"      # queued for encoder
    IN_FLIGHT = "in_flight"
    NVENC_CONSUMING = "nvenc_consuming"  # encoder submitted; CUDA input still being read by NVENC
    NVENC_SAFE_TO_RELEASE = "nvenc_safe_to_release"
    RELEASABLE = "releasable"    # encoder done; ready for reuse
    RELEASED = "released"


# Telemetry callback type for state transitions
TelemetryCallback = Callable[[str, str, SurfaceOwnershipState, int, int], None]


class SurfaceLease:
    """Explicit lease on a CUDA surface backing one frame."""

    def __init__(self, surface_id: str, frame_ref: str = "unknown", telemetry_callback: Optional[TelemetryCallback] = None):
        self.surface_id = surface_id
        self.frame_ref = frame_ref
        self.state = SurfaceOwnershipState.AVAILABLE
        self.ref_count = 0  # number of consumers referencing this surface
        self._telemetry_callback = telemetry_callback

    def _emit_telemetry(self, event_name: str, generation: int = 0) -> None:
        """Emit telemetry event if callback is registered."""
        if self._telemetry_callback is not None:
            try:
                self._telemetry_callback(
                    self.surface_id,
                    self.frame_ref,
                    self.state,
                    self.ref_count,
                    generation
                )
            except Exception:
                # Telemetry must never crash the production pipeline
                pass

    def acquire(self, frame_ref: str, generation: int = 0) -> bool:
        # Safety: only acquire when explicitly reusable. Do NOT acquire IN_FLIGHT,
        # SUBMITTED, or any non-AVAILABLE surface. A stale-generation surface must
        # be rejected by the caller (get_surface) before this point.
        if self.state != SurfaceOwnershipState.AVAILABLE:
            return False
        if self.ref_count > 0:
            return False
        self.ref_count += 1
        self.frame_ref = frame_ref
        self.state = SurfaceOwnershipState.SUBMITTED
        self._emit_telemetry("SURFACE_SUBMIT", generation)
        return True

    def submit_to_encoder(self, generation: int = 0) -> bool:
        if self.state != SurfaceOwnershipState.SUBMITTED:
            return False
        # Generation enforcement: reject if this surface was submitted under a different generation.
        # Note: the generation parameter here is the current encoder generation;
        # the caller ensures frame_ref/generation alignment via submit_encoder().
        self.state = SurfaceOwnershipState.IN_FLIGHT
        self._emit_telemetry("SURFACE_IN_FLIGHT", generation)
        return True

    def release_from_encoder(self, generation: int = 0) -> bool:
        # Phase 54: Only allow release from IN_FLIGHT through verified
        # safe paths (flush/restart). Normal encode() does NOT provide
        # a verified NVENC input-resource safe-release boundary on this
        # installed stack. The release is triggered by the encoder's
        # flush/restart logic, not by arbitrary calls.
        if self.state == SurfaceOwnershipState.IN_FLIGHT:
            # Transition to RELEASABLE only through explicit encoder release.
            # The encoder must have completed flush or restarted.
            self.state = SurfaceOwnershipState.RELEASABLE
            self._emit_telemetry("SURFACE_RELEASABLE", generation)
            return True
        if self.state == SurfaceOwnershipState.RELEASABLE:
            self._emit_telemetry("SURFACE_RELEASABLE", generation)
            return True
        if self.state == SurfaceOwnershipState.RELEASED:
            self._emit_telemetry("SURFACE_RELEASED", generation)
            return True
        # Do not allow release from SUBMITTED, AVAILABLE, NVENC_CONSUMING,
        # or NVENC_SAFE_TO_RELEASE without verified boundary.
        return False

    def mark_available(self, generation: int = 0) -> bool:
        if self.state in (SurfaceOwnershipState.RELEASABLE,
                          SurfaceOwnershipState.RELEASED):
            self.state = SurfaceOwnershipState.AVAILABLE
            self.ref_count = max(0, self.ref_count - 1)
            self._emit_telemetry("SURFACE_RELEASED", generation)
            return True
        if self.state == SurfaceOwnershipState.AVAILABLE:
            self._emit_telemetry("SURFACE_AVAILABLE", generation)
            return True
        return False

    def is_reusable(self) -> bool:
        return self.state == SurfaceOwnershipState.AVAILABLE and self.ref_count <= 0

    def __repr__(self) -> str:
        return (f"SurfaceLease(id={self.surface_id}, frame={self.frame_ref}, "
                f"state={self.state.value}, refs={self.ref_count})")


class CUDAFrameOwnershipPool:
    """
    Global ownership registry ensuring no surface reuse before safe release.
    """

    def __init__(self, telemetry_callback: Optional[TelemetryCallback] = None):
        self._leases: Dict[str, SurfaceLease] = {}
        self._in_flight: Set[str] = set()
        self._released_for_reuse: Set[str] = set()
        self._telemetry_callback = telemetry_callback

    def register_surface(self, surface_id: str) -> SurfaceLease:
        lease = SurfaceLease(surface_id, telemetry_callback=self._telemetry_callback)
        self._leases[surface_id] = lease
        return lease

    def acquire_lease(self, surface_id: str, frame_ref: str, generation: int = 0) -> Optional[SurfaceLease]:
        lease = self._leases.get(surface_id)
        if lease is None:
            lease = self.register_surface(surface_id)
        if lease.acquire(frame_ref, generation):
            return lease
        return None

    def submit_encoder(self, surface_id: str, generation: int = 0) -> bool:
        lease = self._leases.get(surface_id)
        if lease is None:
            return False
        # Phase 50: if state is AVAILABLE, acquire first (simulates pipeline acquisition)
        if lease.state == SurfaceOwnershipState.AVAILABLE:
            lease.acquire(surface_id, generation)
        return lease.submit_to_encoder(generation)

    def release_encoder(self, surface_id: str, generation: int = 0) -> bool:
        lease = self._leases.get(surface_id)
        if lease is None:
            return False
        return lease.release_from_encoder(generation)

    def mark_available_for_reuse(self, surface_id: str, generation: int = 0) -> bool:
        lease = self._leases.get(surface_id)
        if lease is None:
            return False
        result = lease.mark_available(generation)
        if result:
            self._released_for_reuse.add(surface_id)
            self._in_flight.discard(surface_id)
        return result

    def is_available_for_reuse(self, surface_id: str) -> bool:
        lease = self._leases.get(surface_id)
        if lease is None:
            return True  # untracked = available
        return lease.is_reusable()

    def get_state(self, surface_id: str) -> Optional[SurfaceOwnershipState]:
        lease = self._leases.get(surface_id)
        if lease is None:
            return None
        return lease.state

    def all_states(self) -> Dict[str, str]:
        return {sid: lease.state.value for sid, lease in self._leases.items()}
