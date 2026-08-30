"""
Phase 32 — Reconnect Logic.

Bounded reconnect behavior with deterministic state transitions.
No infinite tight retry loops. Injectable/mockable lifecycle logic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.streaming.contracts import StreamHealthState


class ReconnectPolicy(str, Enum):
    """Reconnect policy."""
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    FIXED_INTERVAL = "fixed_interval"
    IMMEDIATE = "immediate"
    NONE = "none"


@dataclass(frozen=True)
class ReconnectConfig:
    """Configuration for reconnect behavior."""
    policy: ReconnectPolicy = ReconnectPolicy.EXPONENTIAL_BACKOFF
    max_retries: int = 5
    base_interval: float = 2.0
    max_interval: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: float = 0.1
    timeout: float = 10.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy.value,
            "max_retries": self.max_retries,
            "base_interval": self.base_interval,
            "max_interval": self.max_interval,
            "backoff_multiplier": self.backoff_multiplier,
            "jitter": self.jitter,
            "timeout": self.timeout,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReconnectConfig":
        return cls(
            policy=ReconnectPolicy(data.get("policy", "exponential_backoff")),
            max_retries=data.get("max_retries", 5),
            base_interval=data.get("base_interval", 2.0),
            max_interval=data.get("max_interval", 60.0),
            backoff_multiplier=data.get("backoff_multiplier", 2.0),
            jitter=data.get("jitter", 0.1),
            timeout=data.get("timeout", 10.0),
        )


class ReconnectState(str, Enum):
    """Reconnect state machine states."""
    IDLE = "idle"
    CONNECTING = "connecting"
    WAITING = "waiting"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ReconnectAttempt:
    """Record of a reconnect attempt."""
    attempt_number: int
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0
    next_retry_in: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "timestamp": self.timestamp,
            "success": self.success,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "next_retry_in": self.next_retry_in,
        }
class ReconnectManager:
    """
    Manages bounded reconnect behavior for camera streams.
    
    Features:
    - No infinite tight retry loops
    - Bounded retry/backoff configuration
    - Deterministic state transitions
    - Reconnect failure is observable
    - Successful reconnect returns stream to LIVE
    - Per-camera isolation (reconnecting CAM1 doesn't affect CAM2)
    - Injectable/mockable for testing
    """
    
    def __init__(
        self,
        camera_id: str,
        config: ReconnectConfig,
        connect_func: Callable[[], bool],
        on_state_change: Optional[Callable[[ReconnectState], None]] = None,
        on_attempt: Optional[Callable[[ReconnectAttempt], None]] = None,
        time_func: Callable[[], float] = time.time,
        sleep_func: Callable[[float], None] = time.sleep,
    ):
        self.camera_id = camera_id
        self.config = config
        self._connect_func = connect_func
        self._on_state_change = on_state_change
        self._on_attempt = on_attempt
        self._time_func = time_func
        self._sleep_func = sleep_func
        
        self._state = ReconnectState.IDLE
        self._attempt_count = 0
        self._attempts: List[ReconnectAttempt] = []
        self._last_error: Optional[str] = None
        self._start_time: Optional[float] = None
    
    @property
    def state(self) -> ReconnectState:
        return self._state
    
    @property
    def attempt_count(self) -> int:
        return self._attempt_count
    
    @property
    def attempts(self) -> List[ReconnectAttempt]:
        return list(self._attempts)
    
    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    @property
    def is_reconnecting(self) -> bool:
        return self._state in (ReconnectState.CONNECTING, ReconnectState.WAITING, ReconnectState.RETRYING)
    
    @property
    def is_exhausted(self) -> bool:
        return self._state == ReconnectState.EXHAUSTED
    
    @property
    def is_success(self) -> bool:
        return self._state == ReconnectState.SUCCESS
    
    def _set_state(self, new_state: ReconnectState) -> None:
        """Set state and notify callback."""
        if self._state != new_state:
            self._state = new_state
            if self._on_state_change:
                self._on_state_change(new_state)
    
    def _calculate_next_interval(self, attempt: int) -> float:
        """Calculate next retry interval based on policy."""
        if self.config.policy == ReconnectPolicy.IMMEDIATE:
            return 0.0
        elif self.config.policy == ReconnectPolicy.FIXED_INTERVAL:
            interval = self.config.base_interval
        elif self.config.policy == ReconnectPolicy.EXPONENTIAL_BACKOFF:
            interval = self.config.base_interval * (self.config.backoff_multiplier ** (attempt - 1))
        else:
            interval = self.config.base_interval
        
        interval = min(interval, self.config.max_interval)
        
        import random
        jitter_range = interval * self.config.jitter
        interval += random.uniform(-jitter_range, jitter_range)
        
        return max(0.0, interval)
    
    def attempt_reconnect(self) -> bool:
        """Attempt a single reconnection."""
        if self._state == ReconnectState.EXHAUSTED:
            return False
        
        self._attempt_count += 1
        attempt_start = self._time_func()
        
        self._set_state(ReconnectState.CONNECTING)
        
        attempt = ReconnectAttempt(attempt_number=self._attempt_count)
        
        try:
            success = self._connect_func()
            
            attempt.duration_seconds = self._time_func() - attempt_start
            attempt.success = success
            
            if success:
                attempt.timestamp = datetime.utcnow().isoformat() + "Z"
                self._attempts.append(attempt)
                if self._on_attempt:
                    self._on_attempt(attempt)
                
                self._set_state(ReconnectState.SUCCESS)
                self._last_error = None
                return True
            else:
                attempt.error = "Connection failed"
                attempt.timestamp = datetime.utcnow().isoformat() + "Z"
                self._attempts.append(attempt)
                if self._on_attempt:
                    self._on_attempt(attempt)
                
                self._last_error = "Connection failed"
                
        except Exception as e:
            attempt.duration_seconds = self._time_func() - attempt_start
            attempt.success = False
            attempt.error = str(e)
            attempt.timestamp = datetime.utcnow().isoformat() + "Z"
            self._attempts.append(attempt)
            if self._on_attempt:
                self._on_attempt(attempt)
            
            self._last_error = str(e)
        
        if self._attempt_count >= self.config.max_retries:
            self._set_state(ReconnectState.EXHAUSTED)
            return False
        
        next_interval = self._calculate_next_interval(self._attempt_count)
        attempt.next_retry_in = next_interval
        
        self._set_state(ReconnectState.WAITING)
        
        if next_interval > 0:
            self._sleep_func(next_interval)
        
        self._set_state(ReconnectState.RETRYING)
        return False

    def run_until_success_or_exhausted(self) -> bool:
        """Run reconnection attempts until success or exhausted."""
        self._set_state(ReconnectState.CONNECTING)
        self._start_time = self._time_func()
        
        while not self.is_exhausted and not self.is_success:
            if self.attempt_reconnect():
                return True
        
        if self.is_exhausted:
            self._set_state(ReconnectState.FAILED)
        
        return self.is_success

    def reset(self) -> None:
        """Reset reconnect manager to initial state."""
        self._state = ReconnectState.IDLE
        self._attempt_count = 0
        self._attempts.clear()
        self._last_error = None
        self._start_time = None
    
    def get_status(self) -> Dict[str, Any]:
        """Get current reconnect status."""
        return {
            "camera_id": self.camera_id,
            "state": self._state.value,
            "attempt_count": self._attempt_count,
            "max_retries": self.config.max_retries,
            "last_error": self._last_error,
            "attempts": [a.to_dict() for a in self._attempts],
            "elapsed_seconds": (self._time_func() - self._start_time) if self._start_time else 0.0,
        }


def create_reconnect_manager(
    camera_id: str,
    connect_func: Callable[[], bool],
    config: Optional[ReconnectConfig] = None,
    on_state_change: Optional[Callable[[ReconnectState], None]] = None,
    on_attempt: Optional[Callable[[ReconnectAttempt], None]] = None,
) -> ReconnectManager:
    """Factory function to create a reconnect manager."""
    if config is None:
        config = ReconnectConfig()
    
    return ReconnectManager(
        camera_id=camera_id,
        config=config,
        connect_func=connect_func,
        on_state_change=on_state_change,
        on_attempt=on_attempt,
    )