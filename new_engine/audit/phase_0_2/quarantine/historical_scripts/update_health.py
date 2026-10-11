from pathlib import Path

content = Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/app/streaming/health.py').read_text(encoding='utf-8')

old = '''class StreamHealthMonitor:
    """
    Monitors health of camera streams.
    
    Provides explicit health states with diagnostic information.
    Does not use wall-clock-dependent logic in deterministic tests.
    """
    
    def __init__(
        self,
        stale_threshold_seconds: float = 5.0,
        degraded_threshold_seconds: float = 2.0,
    ):
        self.stale_threshold = stale_threshold_seconds
        self.degraded_threshold = degraded_threshold_seconds
        
        self._snapshots: Dict[str, StreamHealthSnapshot] = {}
        self._start_times: Dict[str, float] = {}
        self._last_check_results: Dict[str, HealthCheckResult] = {}'''

new = '''class StreamHealthMonitor:
    """
    Monitors health of camera streams.
    
    Provides explicit health states with diagnostic information.
    Does not use wall-clock-dependent logic in deterministic tests.
    
    Phase 33 additions:
    - Frame freshness monitoring
    - Stale frame detection
    - Health event generation
    - Live runtime health tracking
    """
    
    def __init__(
        self,
        stale_threshold_seconds: float = 5.0,
        degraded_threshold_seconds: float = 2.0,
        frame_timeout_seconds: float = 10.0,
        max_consecutive_missing_frames: int = 30,
        event_callback: Optional[Callable[[HealthEvent], None]] = None,
        time_func: Optional[Callable[[], float]] = None,
    ):
        self.stale_threshold = stale_threshold_seconds
        self.degraded_threshold = degraded_threshold_seconds
        self.frame_timeout = frame_timeout_seconds
        self.max_consecutive_missing_frames = max_consecutive_missing_frames
        self._event_callback = event_callback
        self._time_func = time_func or time.time
        
        self._snapshots: Dict[str, StreamHealthSnapshot] = {}
        self._start_times: Dict[str, float] = {}
        self._last_check_results: Dict[str, HealthCheckResult] = {}
        self._event_counter: Dict[str, int] = {}
        self._last_frame_indices: Dict[str, int] = {}
        self._consecutive_missing_frames: Dict[str, int] = {}'''

if old in content:
    content = content.replace(old, new)
    Path('C:/Users/Nguyen Cong Thong/Desktop/AI attendance/app/streaming/health.py').write_text(content, encoding='utf-8')
    print('Replaced successfully')
else:
    print('Old text not found')
    idx = content.find('class StreamHealthMonitor:')
    print(repr(content[idx:idx+400]))