"""
Configuration foundation for Windows native AI attendance system.

Supports future sections for:
- runtime
- paths
- models
- cameras
- media
- inference
- tracking
- attendance
- stranger
- geometry
- storage
- monitoring

This module implements Phase 32 camera streaming configuration.
This module does NOT add automatic camera discovery.
This module does NOT add arbitrary RTSP fallback.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeConfig(BaseModel):
    """Runtime configuration section."""

    log_level: str = Field(default="INFO", description="Logging level")
    debug: bool = Field(default=False, description="Enable debug mode")


class PathsConfig(BaseModel):
    """Paths configuration section."""

    project_root: Path = Field(default_factory=lambda: Path.cwd(), description="Project root directory")
    config_dir: Path = Field(default_factory=lambda: Path.cwd() / "config", description="Configuration directory")
    models_dir: Path = Field(default_factory=lambda: Path.cwd() / "models", description="Models directory")
    logs_dir: Path = Field(default_factory=lambda: Path.cwd() / "logs", description="Logs directory")
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / "data", description="Data directory")
    recordings_dir: Path = Field(default_factory=lambda: Path.cwd() / "recordings", description="Recordings directory")
    benchmark_results_dir: Path = Field(
        default_factory=lambda: Path.cwd() / "benchmark_results", description="Benchmark results directory"
    )

    @field_validator("*", mode="before")
    @classmethod
    def resolve_paths(cls, v: Any) -> Path:
        """Resolve paths to absolute paths."""
        if isinstance(v, (str, Path)):
            return Path(v).resolve()
        return v


class ModelsConfig(BaseModel):
    """Models configuration section - placeholder for Phase 2."""

    scrfd_dir: Path = Field(default_factory=lambda: Path.cwd() / "models" / "scrfd", description="SCRFD models directory")
    arcface_dir: Path = Field(default_factory=lambda: Path.cwd() / "models" / "arcface", description="ArcFace models directory")
    landmark_dir: Path = Field(default_factory=lambda: Path.cwd() / "models" / "landmark", description="Landmark models directory")
    reid_dir: Path = Field(default_factory=lambda: Path.cwd() / "models" / "reid", description="ReID models directory")
    yolo_dir: Path = Field(default_factory=lambda: Path.cwd() / "models" / "yolo", description="YOLO models directory")


class CamerasConfig(BaseModel):
    """Cameras configuration section - Phase 32 streaming configuration."""
    
    # MediaMTX server settings
    mediamtx_rtmp_port: int = Field(default=1935, description="MediaMTX RTMP input port")
    mediamtx_rtsp_port: int = Field(default=8554, description="MediaMTX RTSP output port")
    mediamtx_api_port: int = Field(default=9997, description="MediaMTX API port")
    
    # Camera stream configurations (CAM1 and CAM2)
    cam1_rtmp_key: str = Field(default="cam1", description="CAM1 RTMP stream key")
    cam1_rtsp_path: str = Field(default="cam1", description="CAM1 RTSP output path")
    cam1_enabled: bool = Field(default=True, description="Enable CAM1")
    cam1_reconnect_enabled: bool = Field(default=True, description="Enable CAM1 reconnect")
    
    cam2_rtmp_key: str = Field(default="cam2", description="CAM2 RTMP stream key")
    cam2_rtsp_path: str = Field(default="cam2", description="CAM2 RTSP output path")
    cam2_enabled: bool = Field(default=True, description="Enable CAM2")
    cam2_reconnect_enabled: bool = Field(default=True, description="Enable CAM2 reconnect")
    
    # Stream validation
    expected_codec: str = Field(default="h264", description="Expected video codec")
    expected_width: int = Field(default=3840, description="Expected video width")
    expected_height: int = Field(default=2160, description="Expected video height")
    expected_fps: float = Field(default=30.0, description="Expected video FPS")
    
    # Health monitoring
    health_stale_threshold_seconds: float = Field(default=5.0, description="Seconds before stream considered stale")
    health_degraded_threshold_seconds: float = Field(default=2.0, description="Seconds before stream considered degraded")
    
    # Reconnect settings
    reconnect_max_retries: int = Field(default=5, description="Maximum reconnect attempts")
    reconnect_base_interval: float = Field(default=2.0, description="Base reconnect interval (seconds)")
    reconnect_max_interval: float = Field(default=60.0, description="Maximum reconnect interval (seconds)")
    reconnect_backoff_multiplier: float = Field(default=2.0, description="Exponential backoff multiplier")
    reconnect_jitter: float = Field(default=0.1, description="Jitter factor (0-1)")
    
    def get_cam1_rtsp_url(self, host: str = "localhost") -> str:
        """Get CAM1 RTSP URL."""
        return f"rtsp://{host}:{self.mediamtx_rtsp_port}/{self.cam1_rtsp_path}"
    
    def get_cam2_rtsp_url(self, host: str = "localhost") -> str:
        """Get CAM2 RTSP URL."""
        return f"rtsp://{host}:{self.mediamtx_rtsp_port}/{self.cam2_rtsp_path}"
    
    def get_cam1_rtmp_url(self, host: str = "localhost") -> str:
        """Get CAM1 RTMP URL."""
        return f"rtmp://{host}:{self.mediamtx_rtmp_port}/live/{self.cam1_rtmp_key}"
    
    def get_cam2_rtmp_url(self, host: str = "localhost") -> str:
        """Get CAM2 RTMP URL."""
        return f"rtmp://{host}:{self.mediamtx_rtmp_port}/live/{self.cam2_rtmp_key}"
    
    def to_mediamtx_config(self) -> "MediaMTXConfig":
        """Convert to MediaMTX configuration."""
        from app.streaming.mediamtx_config import MediaMTXConfig, MediaMTXPathConfig, create_mediamtx_config
        
        return create_mediamtx_config(
            cam1_rtmp_key=self.cam1_rtmp_key,
            cam1_rtsp_path=self.cam1_rtsp_path,
            cam2_rtmp_key=self.cam2_rtmp_key,
            cam2_rtsp_path=self.cam2_rtsp_path,
        )
    
    def to_reconnect_config(self) -> "ReconnectConfig":
        """Convert to ReconnectConfig."""
        from app.streaming.reconnect import ReconnectConfig, ReconnectPolicy
        
        return ReconnectConfig(
            policy=ReconnectPolicy.EXPONENTIAL_BACKOFF,
            max_retries=self.reconnect_max_retries,
            base_interval=self.reconnect_base_interval,
            max_interval=self.reconnect_max_interval,
            backoff_multiplier=self.reconnect_backoff_multiplier,
            jitter=self.reconnect_jitter,
        )
    
    def to_health_monitor_config(self) -> tuple[float, float]:
        """Get health monitor thresholds."""
        return (self.health_stale_threshold_seconds, self.health_degraded_threshold_seconds)


class MediaConfig(BaseModel):
    """Media configuration section - placeholder for future phases."""

    ffmpeg_path: Optional[str] = Field(default=None, description="Explicit FFmpeg path (optional)")
    
    # NVDEC Configuration (Phase 36D)
    nvdec_enabled: bool = Field(default=False, description="Enable NVDEC hardware decoding")
    nvdec_gpu_device: int = Field(default=0, description="GPU device ordinal for NVDEC")
    nvdec_surfaces: int = Field(default=32, description="NVDEC decode surfaces")


class InferenceConfig(BaseModel):
    """Inference configuration section - placeholder for future phases."""

    device: str = Field(default="auto", description="Inference device (auto, cpu, cuda)")
    batch_size: int = Field(default=1, description="Inference batch size")


class TrackingConfig(BaseModel):
    """Tracking configuration section - placeholder for future phases."""

    pass


class AttendanceConfig(BaseModel):
    """Attendance configuration section - placeholder for future phases."""

    pass


class StrangerConfig(BaseModel):
    """Stranger detection configuration section - placeholder for future phases."""

    pass


class GeometryConfig(BaseModel):
    """Geometry configuration section - placeholder for future phases."""

    pass


class StorageConfig(BaseModel):
    """Storage configuration section - placeholder for future phases."""

    pass


class MonitoringConfig(BaseModel):
    """Monitoring configuration section - placeholder for future phases."""

    pass


class TelegramConfig(BaseModel):
    """Telegram Bot configuration section - Phase 37B/37C."""

    bot_token: Optional[str] = Field(default=None, description="Telegram Bot Token (from environment)")
    api_base_url: str = Field(default="https://api.telegram.org/bot", description="Telegram API base URL")
    timeout: int = Field(default=30, description="Request timeout in seconds")
    min_interval_seconds: float = Field(default=1.0, description="Minimum interval between messages to same chat")
    
    # Live test configuration
    live_test_enabled: bool = Field(default=False, description="Enable controlled live test")
    live_test_chat_id: Optional[str] = Field(default=None, description="Dedicated test chat ID for live testing")
    
    # Worker configuration
    worker_poll_interval: float = Field(default=5.0, description="Worker poll interval in seconds")
    worker_batch_size: int = Field(default=10, description="Worker batch size")
    
    # Queue configuration
    queue_max_size: int = Field(default=10000, description="Maximum queue size")
    queue_max_retries: int = Field(default=3, description="Maximum retry attempts")
    queue_base_retry_delay: float = Field(default=60.0, description="Base retry delay in seconds")
    queue_max_retry_delay: float = Field(default=3600.0, description="Maximum retry delay in seconds")


class ParentRegistryConfig(BaseModel):
    """Parent Registry configuration section - Phase 37B/37C."""

    db_path: str = Field(default="data/parent_registry.db", description="Parent registry database path")
    link_code_expiry_hours: int = Field(default=24, description="Link code expiry in hours")
    link_code_format: str = Field(default="XXXX-XXXX", description="Link code format")


class NotificationQueueConfig(BaseModel):
    """Notification Queue configuration section - Phase 37B/37C."""

    db_path: str = Field(default="data/notification_queue.db", description="Notification queue database path")
    max_queue_size: int = Field(default=10000, description="Maximum queue size")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    base_retry_delay: float = Field(default=60.0, description="Base retry delay in seconds")
    max_retry_delay: float = Field(default=3600.0, description="Maximum retry delay in seconds")


class ExitSessionConfig(BaseModel):
    """Exit Session Persistence configuration section - Phase 37C."""

    db_path: str = Field(default="data/exit_sessions.db", description="Exit sessions database path")
    cleanup_days: int = Field(default=30, description="Cleanup old sessions after days")


class HealthMonitoringConfig(BaseModel):
    """Health Monitoring configuration section - Phase 37C."""

    enabled: bool = Field(default=True, description="Enable health monitoring")
    metrics_interval_seconds: float = Field(default=10.0, description="Metrics collection interval")
    alert_queue_growth_threshold: int = Field(default=1000, description="Alert when queue grows beyond this")
    alert_failure_rate_threshold: float = Field(default=0.1, description="Alert when failure rate exceeds this")
    alert_worker_stopped: bool = Field(default=True, description="Alert when worker stops")


class ObservabilityConfig(BaseModel):
    """Observability/Logging configuration section - Phase 37C."""

    structured_logging: bool = Field(default=True, description="Enable structured JSON logging")
    log_level: str = Field(default="INFO", description="Log level")
    log_secrets: bool = Field(default=False, description="Log secrets (NEVER enable in production)")
    metrics_enabled: bool = Field(default=True, description="Enable metrics collection")
    metrics_port: int = Field(default=9090, description="Metrics exposition port")


class OperationalToolsConfig(BaseModel):
    """Operational CLI/Tools configuration section - Phase 37C."""

    enabled: bool = Field(default=True, description="Enable operational tools")
    health_check_timeout: float = Field(default=5.0, description="Health check timeout in seconds")
    status_refresh_interval: float = Field(default=30.0, description="Status refresh interval in seconds")


class LoadTestConfig(BaseModel):
    """Load Testing configuration section - Phase 37C."""

    enabled: bool = Field(default=False, description="Enable load testing")
    students_count: int = Field(default=1000, description="Number of students for load test")
    parents_count: int = Field(default=100, description="Number of parents for load test")
    events_per_second: int = Field(default=100, description="Events per second for load test")
    duration_seconds: int = Field(default=60, description="Load test duration in seconds")


class FailureRecoveryConfig(BaseModel):
    """Failure/Recovery Testing configuration section - Phase 37C."""

    enabled: bool = Field(default=False, description="Enable failure/recovery testing")
    test_telegram_unavailable: bool = Field(default=True, description="Test Telegram unavailable scenario")
    test_database_unavailable: bool = Field(default=True, description="Test database unavailable scenario")
    test_worker_restart: bool = Field(default=True, description="Test worker restart scenario")
    test_app_restart_during_exit: bool = Field(default=True, description="Test app restart during active exit")
    test_ui_disconnect: bool = Field(default=True, description="Test UI disconnect scenario")
    test_websocket_reconnect: bool = Field(default=True, description="Test WebSocket/SSE reconnect")
    test_camera_unavailable: bool = Field(default=True, description="Test camera unavailable scenario")


class SecurityConfig(BaseModel):
    """Security configuration section - Phase 37C."""

    no_secrets_in_logs: bool = Field(default=True, description="Ensure no secrets in logs")
    token_env_only: bool = Field(default=True, description="Token only from environment")
    chat_id_exposure_protection: bool = Field(default=True, description="Protect chat IDs from unnecessary exposure")
    admin_authorization_required: bool = Field(default=True, description="Require authorization for admin operations")
    link_code_protection: bool = Field(default=True, description="Protect link codes")
    sql_parameterization: bool = Field(default=True, description="Enforce SQL parameterization")
    safe_file_import: bool = Field(default=True, description="Safe Excel/timetable import validation")


class Settings(BaseSettings):
    """
    Main settings class combining all configuration sections.

    Uses pydantic-settings for environment variable support.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    cameras: CamerasConfig = Field(default_factory=CamerasConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    tracking: TrackingConfig = Field(default_factory=TrackingConfig)
    attendance: AttendanceConfig = Field(default_factory=AttendanceConfig)
    stranger: StrangerConfig = Field(default_factory=StrangerConfig)
    geometry: GeometryConfig = Field(default_factory=GeometryConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    parent_registry: ParentRegistryConfig = Field(default_factory=ParentRegistryConfig)
    notification_queue: NotificationQueueConfig = Field(default_factory=NotificationQueueConfig)
    exit_session: ExitSessionConfig = Field(default_factory=ExitSessionConfig)
    health_monitoring: HealthMonitoringConfig = Field(default_factory=HealthMonitoringConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    operational_tools: OperationalToolsConfig = Field(default_factory=OperationalToolsConfig)
    load_test: LoadTestConfig = Field(default_factory=LoadTestConfig)
    failure_recovery: FailureRecoveryConfig = Field(default_factory=FailureRecoveryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    def ensure_directories(self) -> None:
        """Create all configured directories if they don't exist."""
        for attr_name in dir(self.paths):
            if not attr_name.startswith("_") and attr_name.endswith("_dir"):
                path = getattr(self.paths, attr_name)
                if isinstance(path, Path):
                    path.mkdir(parents=True, exist_ok=True)

        # Also create model subdirectories
        for attr_name in dir(self.models):
            if not attr_name.startswith("_") and attr_name.endswith("_dir"):
                path = getattr(self.models, attr_name)
                if isinstance(path, Path):
                    path.mkdir(parents=True, exist_ok=True)


def load_settings(config_file: Optional[Path] = None) -> Settings:
    """
    Load settings from configuration file and environment.

    Args:
        config_file: Optional path to YAML configuration file.

    Returns:
        Settings instance with all configuration loaded.
    """
    settings = Settings()

    if config_file and config_file.exists():
        import yaml

        with open(config_file, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}

        # Merge file config with settings
        for section_name, section_data in file_config.items():
            if hasattr(settings, section_name) and isinstance(section_data, dict):
                section_obj = getattr(settings, section_name)
                if hasattr(section_obj, "model_dump"):
                    # Update section with file config
                    current = section_obj.model_dump()
                    current.update(section_data)
                    setattr(settings, section_name, type(section_obj)(**current))

    return settings