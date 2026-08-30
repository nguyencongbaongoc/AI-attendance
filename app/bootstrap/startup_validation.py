"""
Phase 37C — Startup Validation for Critical Components.

Validates all production-critical components at startup and provides
clear diagnostics for missing/invalid configuration.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config.settings import load_settings

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    component: str
    check: str
    status: str  # "pass", "fail", "warn", "skip"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass
class StartupValidationReport:
    """Complete startup validation report."""
    overall_status: str = "pending"  # "pass", "fail", "warn", "pending"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    results: List[ValidationResult] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    
    def add_result(self, result: ValidationResult) -> None:
        self.results.append(result)
    
    def finalize(self) -> None:
        """Calculate summary statistics."""
        self.summary = {
            "total": len(self.results),
            "pass": sum(1 for r in self.results if r.status == "pass"),
            "fail": sum(1 for r in self.results if r.status == "fail"),
            "warn": sum(1 for r in self.results if r.status == "warn"),
            "skip": sum(1 for r in self.results if r.status == "skip"),
        }
        
        # Determine overall status
        if self.summary["fail"] > 0:
            self.overall_status = "fail"
        elif self.summary["warn"] > 0:
            self.overall_status = "warn"
        else:
            self.overall_status = "pass"


class StartupValidator:
    """
    Validates all critical components at startup.
    
    Checks:
    - Configuration files and environment variables
    - Database connectivity and schema
    - Model files and directories
    - Camera/streaming configuration
    - Telegram bot configuration
    - GPU/CUDA availability
    - Directory permissions
    """
    
    def __init__(self):
        self.settings = load_settings()
        self.report = StartupValidationReport()
    
    def run_all_validations(self) -> StartupValidationReport:
        """Run all validation checks."""
        logger.info("Starting startup validation...")
        
        # Configuration validation
        self._validate_configuration()
        
        # Directory validation
        self._validate_directories()
        
        # Database validation
        self._validate_databases()
        
        # Model validation
        self._validate_models()
        
        # Camera/streaming validation
        self._validate_camera_config()
        
        # Telegram validation
        self._validate_telegram()
        
        # GPU/CUDA validation
        self._validate_gpu()
        
        # Permissions validation
        self._validate_permissions()
        
        self.report.finalize()
        logger.info(f"Startup validation complete: {self.report.overall_status.upper()}")
        logger.info(f"Summary: {self.report.summary}")
        
        return self.report
    
    def _add_result(self, component: str, check: str, status: str, message: str, details: Dict[str, Any] = None) -> None:
        """Add a validation result."""
        self.report.add_result(ValidationResult(
            component=component,
            check=check,
            status=status,
            message=message,
            details=details or {},
        ))
    
    def _validate_configuration(self) -> None:
        """Validate configuration files and environment."""
        # Check .env file exists
        env_path = Path(".env")
        if env_path.exists():
            self._add_result("config", "env_file", "pass", ".env file found", {"path": str(env_path.absolute())})
        else:
            self._add_result("config", "env_file", "warn", ".env file not found (using defaults)", {"path": str(env_path.absolute())})
        
        # Check config.yaml exists
        config_path = Path("config.yaml")
        if config_path.exists():
            self._add_result("config", "config_file", "pass", "config.yaml found", {"path": str(config_path.absolute())})
        else:
            self._add_result("config", "config_file", "warn", "config.yaml not found (using defaults)", {"path": str(config_path.absolute())})
        
        # Validate critical settings
        critical_settings = [
            ("paths.data_dir", self.settings.paths.data_dir, "Data directory"),
            ("paths.models_dir", self.settings.paths.models_dir, "Models directory"),
            ("paths.logs_dir", self.settings.paths.logs_dir, "Logs directory"),
            ("parent_registry.db_path", self.settings.parent_registry.db_path, "Parent registry DB"),
            ("notification_queue.db_path", self.settings.notification_queue.db_path, "Notification queue DB"),
            ("exit_session.db_path", self.settings.exit_session.db_path, "Exit sessions DB"),
        ]
        
        for setting_name, setting_value, description in critical_settings:
            if setting_value:
                self._add_result("config", f"setting_{setting_name}", "pass", f"{description} configured", {"value": str(setting_value)})
            else:
                self._add_result("config", f"setting_{setting_name}", "fail", f"{description} NOT configured", {"setting": setting_name})
    
    def _validate_directories(self) -> None:
        """Validate required directories exist and are writable."""
        directories = [
            (self.settings.paths.data_dir, "data", True),
            (self.settings.paths.models_dir, "models", True),
            (self.settings.paths.logs_dir, "logs", True),
            (self.settings.paths.recordings_dir, "recordings", False),
            (self.settings.paths.benchmark_results_dir, "benchmark_results", False),
        ]
        
        for dir_path, name, required in directories:
            path = Path(dir_path)
            exists = path.exists()
            writable = False
            
            if exists:
                try:
                    test_file = path / ".write_test"
                    test_file.touch()
                    test_file.unlink()
                    writable = True
                except Exception:
                    writable = False
            
            if not exists and required:
                self._add_result("directories", f"dir_{name}", "fail", f"Required directory missing: {name}", {"path": str(path), "exists": exists})
            elif not exists and not required:
                self._add_result("directories", f"dir_{name}", "warn", f"Optional directory missing: {name}", {"path": str(path), "exists": exists})
            elif exists and not writable:
                self._add_result("directories", f"dir_{name}", "fail", f"Directory not writable: {name}", {"path": str(path), "exists": exists, "writable": writable})
            else:
                self._add_result("directories", f"dir_{name}", "pass", f"Directory OK: {name}", {"path": str(path), "exists": exists, "writable": writable})
    
    def _validate_databases(self) -> None:
        """Validate database files and connectivity."""
        databases = [
            (self.settings.parent_registry.db_path, "parent_registry", True),
            (self.settings.notification_queue.db_path, "notification_queue", True),
            (self.settings.exit_session.db_path, "exit_sessions", True),
        ]
        
        for db_path, name, required in databases:
            path = Path(db_path)
            exists = path.exists()
            
            if not exists and required:
                self._add_result("databases", f"db_{name}", "warn", f"Database file will be created on first use: {name}", {"path": str(path), "exists": exists})
            elif not exists and not required:
                self._add_result("databases", f"db_{name}", "skip", f"Optional database not present: {name}", {"path": str(path), "exists": exists})
            else:
                # Try to connect and verify schema
                try:
                    import sqlite3
                    with sqlite3.connect(db_path) as conn:
                        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                        tables = [row[0] for row in cursor.fetchall()]
                    self._add_result("databases", f"db_{name}", "pass", f"Database accessible: {name}", {"path": str(path), "tables": tables})
                except Exception as e:
                    self._add_result("databases", f"db_{name}", "fail", f"Database connection failed: {name}", {"path": str(path), "error": str(e)})
    
    def _validate_models(self) -> None:
        """Validate model files exist."""
        model_dirs = {
            "scrfd": self.settings.models.scrfd_dir,
            "arcface": self.settings.models.arcface_dir,
            "landmark": self.settings.models.landmark_dir,
            "reid": self.settings.models.reid_dir,
            "yolo": self.settings.models.yolo_dir,
        }
        
        for name, dir_path in model_dirs.items():
            path = Path(dir_path)
            exists = path.exists()
            
            if exists:
                # Check for model files
                model_files = list(path.glob("*.onnx")) + list(path.glob("*.pt")) + list(path.glob("*.bin"))
                if model_files:
                    self._add_result("models", f"model_{name}", "pass", f"Model files found: {name}", {"path": str(path), "files": [f.name for f in model_files]})
                else:
                    self._add_result("models", f"model_{name}", "warn", f"Model directory exists but no model files: {name}", {"path": str(path)})
            else:
                self._add_result("models", f"model_{name}", "fail", f"Model directory missing: {name}", {"path": str(path)})
    
    def _validate_camera_config(self) -> None:
        """Validate camera/streaming configuration."""
        cameras = [
            ("CAM1", self.settings.cameras.cam1_enabled, self.settings.cameras.cam1_rtmp_key, self.settings.cameras.cam1_rtsp_path),
            ("CAM2", self.settings.cameras.cam2_enabled, self.settings.cameras.cam2_rtmp_key, self.settings.cameras.cam2_rtsp_path),
        ]
        
        for name, enabled, rtmp_key, rtsp_path in cameras:
            if enabled:
                self._add_result("camera", f"camera_{name.lower()}", "pass", f"Camera enabled: {name}", {
                    "enabled": enabled,
                    "rtmp_key": rtmp_key,
                    "rtsp_path": rtsp_path,
                })
            else:
                self._add_result("camera", f"camera_{name.lower()}", "skip", f"Camera disabled: {name}", {"enabled": enabled})
        
        # MediaMTX config
        self._add_result("camera", "mediamtx_ports", "pass", "MediaMTX ports configured", {
            "rtmp_port": self.settings.cameras.mediamtx_rtmp_port,
            "rtsp_port": self.settings.cameras.mediamtx_rtsp_port,
            "api_port": self.settings.cameras.mediamtx_api_port,
        })
    
    def _validate_telegram(self) -> None:
        """Validate Telegram bot configuration."""
        bot_token = self.settings.telegram.bot_token
        
        if not bot_token:
            self._add_result("telegram", "bot_token", "warn", "TELEGRAM_BOT_TOKEN not configured (notifications disabled)", {
                "configured": False,
                "source": "environment" if os.environ.get("TELEGRAM_BOT_TOKEN") else "none",
            })
        else:
            # Validate token format
            from app.attendance.policy_engine.telegram_bot import validate_bot_token
            is_valid, error = validate_bot_token(bot_token)
            if is_valid:
                self._add_result("telegram", "bot_token", "pass", "TELEGRAM_BOT_TOKEN format valid", {
                    "configured": True,
                    "format_valid": True,
                })
            else:
                self._add_result("telegram", "bot_token", "fail", f"TELEGRAM_BOT_TOKEN format invalid: {error}", {
                    "configured": True,
                    "format_valid": False,
                    "error": error,
                })
        
        # Live test config
        if self.settings.telegram.live_test_enabled:
            if self.settings.telegram.live_test_chat_id:
                self._add_result("telegram", "live_test", "pass", "Live test configured", {
                    "enabled": True,
                    "test_chat_id": self.settings.telegram.live_test_chat_id,
                })
            else:
                self._add_result("telegram", "live_test", "fail", "Live test enabled but TELEGRAM_TEST_CHAT_ID not set", {
                    "enabled": True,
                    "test_chat_id": None,
                })
        else:
            self._add_result("telegram", "live_test", "skip", "Live test disabled", {"enabled": False})
    
    def _validate_gpu(self) -> None:
        """Validate GPU/CUDA availability."""
        try:
            from app.runtime import collect_runtime_snapshot
            snapshot = collect_runtime_snapshot()
            
            if snapshot.torch_cuda_available:
                self._add_result("gpu", "cuda_available", "pass", "CUDA available", {
                    "gpu_name": snapshot.nvidia_gpu_name,
                    "driver_version": snapshot.nvidia_driver_version,
                    "cuda_version": snapshot.cuda_runtime_version,
                })
            else:
                self._add_result("gpu", "cuda_available", "warn", "CUDA not available (will use CPU fallback)", {
                    "torch_cuda_available": False,
                })
            
            if snapshot.cuda_ep_registered:
                self._add_result("gpu", "cuda_ep", "pass", "ONNX Runtime CUDA EP registered", {})
            else:
                self._add_result("gpu", "cuda_ep", "warn", "ONNX Runtime CUDA EP not registered", {})
            
            if snapshot.ffmpeg_available:
                self._add_result("gpu", "nvdec", "pass", "FFmpeg/NVDEC available", {
                    "ffmpeg_version": snapshot.ffmpeg_version,
                })
            else:
                self._add_result("gpu", "nvdec", "warn", "FFmpeg/NVDEC not available", {})
                
        except Exception as e:
            self._add_result("gpu", "gpu_check", "fail", f"GPU validation failed: {e}", {"error": str(e)})
    
    def _validate_permissions(self) -> None:
        """Validate file/directory permissions."""
        # Check write access to data directory
        data_dir = Path(self.settings.paths.data_dir)
        try:
            test_file = data_dir / ".permission_test"
            test_file.touch()
            test_file.unlink()
            self._add_result("permissions", "data_dir_write", "pass", "Data directory writable", {"path": str(data_dir)})
        except Exception as e:
            self._add_result("permissions", "data_dir_write", "fail", f"Data directory not writable: {e}", {"path": str(data_dir), "error": str(e)})
        
        # Check logs directory
        logs_dir = Path(self.settings.paths.logs_dir)
        try:
            test_file = logs_dir / ".permission_test"
            test_file.touch()
            test_file.unlink()
            self._add_result("permissions", "logs_dir_write", "pass", "Logs directory writable", {"path": str(logs_dir)})
        except Exception as e:
            self._add_result("permissions", "logs_dir_write", "fail", f"Logs directory not writable: {e}", {"path": str(logs_dir), "error": str(e)})


def run_startup_validation() -> StartupValidationReport:
    """Run startup validation and return report."""
    validator = StartupValidator()
    return validator.run_all_validations()


def print_validation_report(report: StartupValidationReport) -> None:
    """Print validation report to console."""
    print("\n" + "=" * 60)
    print("STARTUP VALIDATION REPORT")
    print("=" * 60)
    print(f"Timestamp: {report.timestamp}")
    print(f"Overall Status: {report.overall_status.upper()}")
    print(f"Summary: {report.summary}")
    print("-" * 60)
    
    for result in report.results:
        status_icon = {
            "pass": "[PASS]",
            "fail": "[FAIL]",
            "warn": "[WARN]",
            "skip": "[SKIP]",
        }.get(result.status, "[?]")
        
        print(f"{status_icon} [{result.component}] {result.check}: {result.message}")
        if result.details:
            for key, value in result.details.items():
                print(f"    {key}: {value}")
    
    print("=" * 60)


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    
    report = run_startup_validation()
    print_validation_report(report)
    
    # Exit with appropriate code
    if report.overall_status == "fail":
        sys.exit(1)
    elif report.overall_status == "warn":
        sys.exit(0)  # Warnings don't block startup
    else:
        sys.exit(0)