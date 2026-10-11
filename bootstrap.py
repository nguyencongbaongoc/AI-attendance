"""
Bootstrap - Single entry point for AI Attendance Pipeline Engine.

Handles environment validation, service startup, pipeline initialization,
health verification, and graceful shutdown.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

import torch

from pipeline_engine.config import load_pipeline_config
from pipeline_engine.core.engine import PipelineEngine, EngineState

# Phase 17: Storage lifecycle services
from app.storage import (
    start_storage_services,
    stop_storage_services,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bootstrap")


class BootstrapError(Exception):
    """Bootstrap error."""
    pass


class EnvironmentValidator:
    """Validates runtime environment before starting pipeline."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.config = None
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate_all(self) -> bool:
        """Run all validation checks."""
        logger.info("Validating environment...")
        
        self._validate_python()
        self._validate_cuda()
        self._validate_dependencies()
        self._validate_config()
        self._validate_models()
        self._validate_cameras()
        self._validate_mediamtx()
        self._validate_ffmpeg()
        self._validate_directories()
        
        if self.warnings:
            for w in self.warnings:
                logger.warning(f"Validation warning: {w}")
        
        if self.errors:
            for e in self.errors:
                logger.error(f"Validation error: {e}")
            return False
        
        logger.info("Environment validation PASSED")
        return True
    
    def _validate_python(self) -> None:
        """Validate Python version."""
        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 10):
            self.errors.append(f"Python 3.10+ required, found {version.major}.{version.minor}")
        else:
            logger.info(f"Python {version.major}.{version.minor}.{version.micro} OK")
    
    def _validate_cuda(self) -> None:
        """Validate CUDA availability."""
        if not torch.cuda.is_available():
            self.errors.append("CUDA not available - GPU required for pipeline")
            return
        
        device_count = torch.cuda.device_count()
        logger.info(f"CUDA available: {device_count} device(s)")
        
        for i in range(device_count):
            props = torch.cuda.get_device_properties(i)
            vram_gb = props.total_memory / (1024**3)
            logger.info(f"  GPU {i}: {props.name} ({vram_gb:.1f} GB VRAM)")
        
        # Check VRAM budget
        if self.config:
            budget_mb = self.config.gpu.get("vram_budget_mb", 4096)
            for i in range(device_count):
                allocated = torch.cuda.memory_allocated(i) / (1024**2)
                reserved = torch.cuda.memory_reserved(i) / (1024**2)
                free = (torch.cuda.get_device_properties(i).total_memory - reserved) / (1024**2)
                if free < budget_mb:
                    self.warnings.append(
                        f"GPU {i}: Only {free:.0f}MB free, budget is {budget_mb}MB"
                    )
    
    def _validate_dependencies(self) -> None:
        """Validate required Python packages."""
        required = {
            "torch": "2.0+",
            "onnxruntime": "1.15+",
            "av": "10+",
            "numpy": "1.24+",
            "cv2": "4.8+",
            "fastapi": "0.100+",
            "uvicorn": "0.23+",
            "pydantic": "2.0+",
            "yaml": "6.0+",
            "tensorrt": "8.0+",
        }
        
        for pkg, min_ver in required.items():
            try:
                mod = __import__(pkg)
                ver = getattr(mod, "__version__", "unknown")
                logger.info(f"  {pkg}: {ver} OK")
            except ImportError:
                if pkg == "tensorrt":
                    self.warnings.append(f"Optional package not found: {pkg} (need {min_ver}) - TensorRT engine support may be limited")
                else:
                    self.errors.append(f"Missing required package: {pkg} (need {min_ver})")
    
    def _validate_config(self) -> None:
        """Load and validate configuration."""
        try:
            self.config = load_pipeline_config(self.config_path)
            logger.info(f"Configuration loaded from {self.config_path or 'default'}")
        except Exception as e:
            self.errors.append(f"Configuration load failed: {e}")
    
    def _validate_models(self) -> None:
        """Validate model files exist."""
        if not self.config:
            return
        
        models = self.config.models or {}
        required_models = ["scrfd", "arcface", "yolo"]
        
        for model_name in required_models:
            model_config = models.get(model_name, {})
            model_path = model_config.get("path", "")
            if not model_path:
                self.errors.append(f"Model {model_name}: path not configured")
                continue
            
            # Check for .engine first, then .onnx fallback
            engine_path = Path(model_path)
            onnx_path = engine_path.with_suffix('.onnx')
            
            if engine_path.exists():
                size_mb = engine_path.stat().st_size / (1024**2)
                logger.info(f"  Model {model_name}: {engine_path} ({size_mb:.1f} MB) OK [TensorRT]")
            elif onnx_path.exists():
                size_mb = onnx_path.stat().st_size / (1024**2)
                logger.info(f"  Model {model_name}: {onnx_path} ({size_mb:.1f} MB) OK [ONNX Runtime]")
            else:
                self.errors.append(f"Model {model_name}: not found at {engine_path} or {onnx_path}")
        
        # Optional models
        for model_name in ["reid", "pose"]:
            model_config = models.get(model_name, {})
            if model_config.get("enabled", False):
                model_path = model_config.get("path", "")
                if model_path:
                    engine_path = Path(model_path)
                    onnx_path = engine_path.with_suffix('.onnx')
                    if engine_path.exists():
                        size_mb = engine_path.stat().st_size / (1024**2)
                        logger.info(f"  Optional model {model_name}: {engine_path} ({size_mb:.1f} MB) OK [TensorRT]")
                    elif onnx_path.exists():
                        size_mb = onnx_path.stat().st_size / (1024**2)
                        logger.info(f"  Optional model {model_name}: {onnx_path} ({size_mb:.1f} MB) OK [ONNX Runtime]")
                    else:
                        self.warnings.append(f"Optional model {model_name}: not found at {engine_path} or {onnx_path}")
    
    def _validate_cameras(self) -> None:
        """Validate camera configuration and connectivity."""
        if not self.config:
            return
        
        cameras = self.config.cameras or {}
        if not cameras:
            self.warnings.append("No cameras configured")
            return
        
        import cv2
        
        for camera_id, cam_config in cameras.items():
            if not cam_config.get("enabled", True):
                logger.info(f"  Camera {camera_id}: disabled")
                continue
            
            url = cam_config.get("input", {}).get("url", "")
            if not url:
                self.errors.append(f"Camera {camera_id}: no input URL")
                continue
            
            logger.info(f"  Camera {camera_id}: {url}")
            
            # Quick connectivity test (non-blocking) - WARNING only, do not fail preflight
            try:
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret:
                        h, w = frame.shape[:2]
                        logger.info(f"    Connected: {w}x{h} OK")
                    else:
                        self.warnings.append(f"Camera {camera_id}: connected but no frames (will retry at runtime)")
                else:
                    self.warnings.append(f"Camera {camera_id}: connection failed - marking OFFLINE/RETRYING (will retry at runtime)")
            except Exception as e:
                self.warnings.append(f"Camera {camera_id}: validation error: {e} (will retry at runtime)")
    
    def _validate_mediamtx(self) -> None:
        """Validate MediaMTX availability."""
        # Check if MediaMTX binary exists
        mediamtx_path = Path("mediamtx/mediamtx.exe")
        if not mediamtx_path.exists():
            self.warnings.append(f"MediaMTX binary not found at {mediamtx_path}")
        
        # Check if MediaMTX is running
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            result = sock.connect_ex(("localhost", 8554))
            sock.close()
            
            if result == 0:
                logger.info("MediaMTX: Running on port 8554")
            else:
                self.warnings.append("MediaMTX: Not running on port 8554 (will need to start)")
        except Exception:
            self.warnings.append("MediaMTX: Could not check status")
    
    def _validate_ffmpeg(self) -> None:
        """Validate FFmpeg availability."""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                version_line = result.stdout.decode().split("\n")[0]
                logger.info(f"FFmpeg: {version_line}")
            else:
                self.warnings.append("FFmpeg: not found in PATH")
        except FileNotFoundError:
            self.warnings.append("FFmpeg: not found in PATH")
        except Exception as e:
            self.warnings.append(f"FFmpeg: check failed: {e}")
    
    def _validate_directories(self) -> None:
        """Validate required directories exist or can be created."""
        if not self.config:
            return
        
        paths = self.config.paths or {}
        required_dirs = [
            paths.get("data_dir", "data"),
            paths.get("logs_dir", "logs"),
            paths.get("recordings_dir", "recordings"),
            # Phase 17: Evidence storage directories
            "app/static/evidence/snapshots",
            "app/static/evidence/clips",
            "app/data/backups",
        ]
        
        for dir_path in required_dirs:
            path = Path(dir_path)
            try:
                path.mkdir(parents=True, exist_ok=True)
                logger.info(f"Directory {path}: OK")
            except Exception as e:
                self.errors.append(f"Cannot create directory {path}: {e}")


class ServiceManager:
    """Manages external services (MediaMTX, Backend API, Frontend)."""
    
    def __init__(self, config: Any):
        self.config = config
        self.mediamtx_process: Optional[subprocess.Popen] = None
        self._mediamtx_started_by_us = False
        self.backend_process: Optional[subprocess.Popen] = None
        self._backend_started_by_us = False
        self.frontend_process: Optional[subprocess.Popen] = None
        self._frontend_started_by_us = False
    
    def start_mediamtx(self) -> bool:
        """Start MediaMTX if not running."""
        # Check if already running
        if self._is_mediamtx_running():
            logger.info("MediaMTX already running")
            return True
        
        # Resolve absolute paths
        ROOT_DIR = Path(__file__).parent.resolve()
        mediamtx_exe = (ROOT_DIR / "mediamtx" / "mediamtx.exe").resolve()
        mediamtx_config = (ROOT_DIR / "mediamtx" / "mediamtx.yml").resolve()
        
        # Fallback to root config if not found in mediamtx/
        if not mediamtx_config.exists():
            mediamtx_config = (ROOT_DIR / "mediamtx.yml").resolve()
        
        if not mediamtx_exe.exists():
            logger.error(f"MediaMTX binary not found: {mediamtx_exe}")
            return False
        
        if not mediamtx_config.exists():
            logger.error(f"MediaMTX config not found: {mediamtx_config}")
            return False
        
        try:
            logger.info("Starting MediaMTX...")
            self.mediamtx_process = subprocess.Popen(
                [str(mediamtx_exe), str(mediamtx_config)],
                cwd=str(ROOT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            )
            self._mediamtx_started_by_us = True
            
            # Wait for startup - check API health
            logger.info("Waiting for MediaMTX API to become healthy...")
            for i in range(30):
                time.sleep(0.5)
                if self._is_mediamtx_api_healthy():
                    logger.info("MediaMTX started successfully with API healthy")
                    return True
            
            logger.error("MediaMTX failed to start API within 15 seconds")
            self.stop_mediamtx()
            return False
            
        except Exception as e:
            logger.error(f"Failed to start MediaMTX: {e}")
            return False
    
    def stop_mediamtx(self) -> None:
        """Stop MediaMTX if we started it."""
        if self.mediamtx_process and self._mediamtx_started_by_us:
            logger.info("Stopping MediaMTX...")
            try:
                if os.name == 'nt':
                    self.mediamtx_process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.mediamtx_process.terminate()
                self.mediamtx_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.mediamtx_process.kill()
                self.mediamtx_process.wait()
            except Exception as e:
                logger.error(f"Error stopping MediaMTX: {e}")
            finally:
                self.mediamtx_process = None
                self._mediamtx_started_by_us = False
    
    def _is_mediamtx_running(self) -> bool:
        """Check if MediaMTX is running."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex(("localhost", 8554))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _is_mediamtx_api_healthy(self) -> bool:
        """Check if MediaMTX API is healthy and paths are configured."""
        try:
            import requests
            resp = requests.get("http://127.0.0.1:9997/v3/paths/list", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                # Check that our required paths are configured
                paths = [item['name'] for item in data.get('items', [])]
                required = ['live/cam1', 'live/cam2', 'live/cam1-ai', 'live/cam2-ai']
                for req in required:
                    if req not in paths:
                        return False
                return True
            return False
        except Exception:
            return False
    
    def start_backend_api(self) -> bool:
        """Start Backend API (Uvicorn) if not running."""
        backend_config = self.config.backend if self.config else {}
        host = backend_config.get("host", "0.0.0.0")
        port = backend_config.get("port", 8000)
        
        # Check if already running
        if self._is_backend_running(host, port):
            logger.info(f"Backend API already running on {host}:{port}")
            return True
        
        try:
            logger.info(f"Starting Backend API on {host}:{port}...")
            self.backend_process = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "app.main:app",
                    "--host", host,
                    "--port", str(port),
                    "--log-level", "info"
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            )
            self._backend_started_by_us = True
            
            # Wait for health endpoint
            health_url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}/api/v1/health/live"
            for i in range(30):
                time.sleep(0.5)
                if self._is_backend_healthy(health_url):
                    logger.info(f"Backend API started successfully on {host}:{port}")
                    return True
            
            logger.error(f"Backend API failed to become healthy within 15 seconds")
            self.stop_backend_api()
            return False
            
        except Exception as e:
            logger.error(f"Failed to start Backend API: {e}")
            return False
    
    def stop_backend_api(self) -> None:
        """Stop Backend API if we started it."""
        if self.backend_process and self._backend_started_by_us:
            logger.info("Stopping Backend API...")
            try:
                if os.name == 'nt':
                    self.backend_process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.backend_process.terminate()
                self.backend_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.backend_process.kill()
                self.backend_process.wait()
            except Exception as e:
                logger.error(f"Error stopping Backend API: {e}")
            finally:
                self.backend_process = None
                self._backend_started_by_us = False
    
    def _is_backend_running(self, host: str, port: int) -> bool:
        """Check if Backend API port is open."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((host if host != '0.0.0.0' else '127.0.0.1', port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _is_backend_healthy(self, health_url: str) -> bool:
        """Check if Backend API health endpoint responds."""
        try:
            import requests
            resp = requests.get(health_url, timeout=2)
            return resp.status_code == 200
        except Exception:
            return False
    
    def start_frontend(self) -> bool:
        """Start Frontend Web Server if not running."""
        frontend_config = self.config.frontend if self.config else {}
        if not frontend_config.get("enabled", True):
            logger.info("Frontend disabled by config")
            return True
        
        # Check if frontend build exists
        build_path = Path(frontend_config.get("build_path", "frontend/dist"))
        if not build_path.exists():
            logger.warning(f"Frontend build not found at {build_path}, skipping")
            return True
        
        # Check if already running
        port = 3000
        if self._is_frontend_running(port):
            logger.info(f"Frontend already running on port {port}")
            return True
        
        try:
            logger.info(f"Starting Frontend Web Server on port {port}...")
            self.frontend_process = subprocess.Popen(
                [
                    sys.executable, "-m", "http.server", str(port),
                    "--directory", str(build_path)
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            )
            self._frontend_started_by_us = True
            
            # Wait for startup
            for i in range(10):
                time.sleep(0.5)
                if self._is_frontend_running(port):
                    logger.info(f"Frontend Web Server started successfully on port {port}")
                    return True
            
            logger.error(f"Frontend Web Server failed to start within 5 seconds")
            self.stop_frontend()
            return False
            
        except Exception as e:
            logger.error(f"Failed to start Frontend Web Server: {e}")
            return False
    
    def stop_frontend(self) -> None:
        """Stop Frontend Web Server if we started it."""
        if self.frontend_process and self._frontend_started_by_us:
            logger.info("Stopping Frontend Web Server...")
            try:
                if os.name == 'nt':
                    self.frontend_process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.frontend_process.terminate()
                self.frontend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.frontend_process.kill()
                self.frontend_process.wait()
            except Exception as e:
                logger.error(f"Error stopping Frontend Web Server: {e}")
            finally:
                self.frontend_process = None
                self._frontend_started_by_us = False
    
    def _is_frontend_running(self, port: int) -> bool:
        """Check if Frontend Web Server port is open."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result == 0
        except Exception:
            return False


class Bootstrap:
    """
    Main bootstrap class - orchestrates complete system startup.
    """
    
    def __init__(
        self,
        config_path: Optional[Path] = None,
        no_mediamtx: bool = False,
        no_frontend: bool = False,
        no_backend: bool = False,
        camera_ids: Optional[List[str]] = None,
    ):
        self.config_path = config_path
        self.no_mediamtx = no_mediamtx
        self.no_frontend = no_frontend
        self.no_backend = no_backend
        self.camera_ids = camera_ids
        
        self.validator = EnvironmentValidator(config_path)
        self.service_manager: Optional[ServiceManager] = None
        self.engine: Optional[PipelineEngine] = None
        self._shutdown_requested = False
    
    def run_check(self) -> int:
        """Run environment check only."""
        if self.validator.validate_all():
            logger.info("Environment check PASSED")
            return 0
        else:
            logger.error("Environment check FAILED")
            return 1
    
    def run_diagnostics(self) -> int:
        """Run full diagnostics."""
        logger.info("Running diagnostics...")
        
        if not self.validator.validate_all():
            return 1
        
        # Additional runtime diagnostics
        self._run_runtime_diagnostics()
        return 0
    
    def _run_runtime_diagnostics(self) -> None:
        """Run runtime diagnostics."""
        logger.info("Runtime diagnostics:")
        
        # GPU info
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                allocated = torch.cuda.memory_allocated(i) / (1024**2)
                reserved = torch.cuda.memory_reserved(i) / (1024**2)
                logger.info(f"  GPU {i}: {props.name}")
                logger.info(f"    Allocated: {allocated:.0f} MB")
                logger.info(f"    Reserved: {reserved:.0f} MB")
                logger.info(f"    Total: {props.total_memory / (1024**2):.0f} MB")
        
        # Camera connectivity
        if self.validator.config:
            import cv2
            for cam_id, cam_config in self.validator.config.cameras.items():
                if not cam_config.get("enabled", True):
                    continue
                url = cam_config.get("input", {}).get("url", "")
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    logger.info(f"  Camera {cam_id}: {w}x{h} @ {fps:.1f}fps")
                else:
                    logger.info(f"  Camera {cam_id}: NOT CONNECTED")
        
        # MediaMTX paths
        try:
            import requests
            resp = requests.get("http://localhost:9997/v3/paths/list", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    logger.info(f"  MediaMTX path: {item['name']} - ready={item['ready']}")
        except Exception:
            logger.info("  MediaMTX API: not accessible")
    
    def start(self) -> int:
        """Start the complete pipeline."""
        logger.info("=" * 60)
        logger.info("AI Attendance Pipeline Engine - Starting")
        logger.info("=" * 60)
        
        # Step 1: Validate environment
        if not self.validator.validate_all():
            logger.error("Environment validation FAILED")
            return 1
        
        # Step 2: Start MediaMTX if needed
        if not self.no_mediamtx:
            self.service_manager = ServiceManager(self.validator.config)
            if not self.service_manager.start_mediamtx():
                logger.error("Failed to start MediaMTX")
                return 1
        
        # Step 3: Start Backend API if not disabled
        if not self.no_backend and self.service_manager:
            if not self.service_manager.start_backend_api():
                logger.error("Failed to start Backend API")
                return 1
        
        # Step 4: Start Frontend if not disabled
        if not self.no_frontend and self.service_manager:
            if not self.service_manager.start_frontend():
                logger.warning("Frontend start failed (non-blocking)")
        
        # Step 5: Start storage lifecycle services (Phase 17)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        logger.info("Starting storage lifecycle services (Retention, Disk Watchdog, DB Maintenance)...")
        loop.run_until_complete(start_storage_services(
            retention_interval_seconds=3600.0,   # 1 hour
            disk_check_interval_seconds=60.0,    # 1 minute
            backup_interval_hours=24.0,          # Daily
            vacuum_interval_days=7,              # Weekly
        ))
        
        # Step 6: Initialize and start pipeline engine
        try:
            self.engine = PipelineEngine(self.config_path)
            self.engine.load_config()
            
            # Filter cameras if specified
            if self.camera_ids:
                self._filter_cameras()
            
            if not self.engine.initialize():
                logger.error("Pipeline engine initialization failed")
                return 1
            
            if not self.engine.start():
                logger.error("Pipeline engine start failed")
                return 1
            
        except Exception as e:
            logger.error(f"Pipeline engine error: {e}")
            return 1
        
        # Step 7: Verify health
        if not self._verify_health():
            logger.error("Health verification failed")
            return 1
        
        logger.info("=" * 60)
        logger.info("Pipeline STARTED successfully")
        logger.info("=" * 60)
        self._print_status()
        
        # Step 8: Run supervisor loop
        return self._run_supervisor()
    
    def _filter_cameras(self) -> None:
        """Filter camera config to only specified cameras."""
        if not self.engine.config or not self.camera_ids:
            return
        
        filtered = {}
        for cam_id in self.camera_ids:
            if cam_id in self.engine.config.cameras:
                filtered[cam_id] = self.engine.config.cameras[cam_id]
            else:
                logger.warning(f"Camera {cam_id} not in config, ignoring")
        
        self.engine.config.cameras = filtered
        logger.info(f"Filtered to cameras: {list(filtered.keys())}")
    
    def _verify_health(self) -> bool:
        """Verify pipeline health after startup."""
        logger.info("Verifying pipeline health...")
        
        # Wait for cameras to be ready
        max_wait = 30
        start = time.time()
        
        while time.time() - start < max_wait:
            if not self.engine or not self.engine.camera_manager:
                return False
            
            cameras = self.engine.camera_manager.get_camera_list()
            if not cameras:
                logger.warning("No cameras configured")
                return True
            
            all_ready = True
            for cam_id in cameras:
                state = self.engine.camera_manager.get_camera_state(cam_id)
                if state != EngineState.RUNNING:
                    all_ready = False
                    break
            
            if all_ready:
                logger.info("All cameras RUNNING")
                return True
            
            time.sleep(1)
        
        logger.warning("Health verification timeout - some cameras may not be ready")
        return True  # Continue anyway
    
    def _print_status(self) -> None:
        """Print current status."""
        if not self.engine:
            return
        
        metrics = self.engine.metrics
        logger.info(f"State: {metrics.state.value}")
        logger.info(f"Cameras: {metrics.cameras_healthy}/{metrics.cameras_running}/{metrics.cameras_total}")
        logger.info(f"Frames: {metrics.total_frames_processed}")
        logger.info(f"Events: {metrics.total_attendance_events}")
        logger.info(f"GPU: {metrics.gpu_memory_mb:.0f}MB ({metrics.gpu_utilization_pct:.1f}%)")
        
        # Camera details
        for cam_id in self.engine.camera_manager.get_camera_list():
            cam_metrics = self.engine.camera_manager.get_camera_metrics(cam_id)
            if cam_metrics:
                logger.info(f"  {cam_id}: {cam_metrics.frames_received} frames, "
                           f"{cam_metrics.tracks_active} tracks, "
                           f"{cam_metrics.attendance_events} events")
    
    def _run_supervisor(self) -> int:
        """Run supervisor loop until shutdown."""
        logger.info("Entering supervisor loop (Ctrl+C to stop)...")
        
        # Install signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self._shutdown_requested = True
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)
        
        # Status printing interval - 30 seconds
        last_status = 0
        status_interval = 30.0
        last_events = 0
        
        try:
            while not self._shutdown_requested:
                time.sleep(1)
                
                # Print status periodically (compact single-line heartbeat)
                if time.time() - last_status >= status_interval:
                    if self.engine:
                        metrics = self.engine.metrics
                        vram_mb = metrics.gpu_memory_mb
                        vram_pct = metrics.gpu_utilization_pct
                        total_frames = metrics.total_frames_processed
                        total_events = metrics.total_attendance_events
                        cam_ok = metrics.cameras_healthy
                        cam_total = metrics.cameras_total
                        state = metrics.state.value
                        
                        logger.info(
                            f"[HEARTBEAT] State: {state.upper()} | Cams: {cam_ok}/{cam_total} | "
                            f"Frames: {total_frames} | GPU: {vram_mb:.0f}MB ({vram_pct:.1f}%) | "
                            f"Events: {total_events}"
                        )
                        
                        # If new events occurred, log them individually
                        if total_events > last_events:
                            new_events = total_events - last_events
                            logger.info(f"  -> {new_events} new attendance event(s)")
                            last_events = total_events
                    
                    last_status = time.time()
                
                # Check engine health
                if self.engine and self.engine.state == EngineState.ERROR:
                    logger.error("Pipeline engine entered ERROR state")
                    break
        
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Supervisor error: {e}")
            return 1
        finally:
            self.stop()
        
        return 0
    
    def stop(self) -> None:
        """Stop the pipeline gracefully."""
        logger.info("Shutting down...")
        
        # Stop in reverse order: Engine -> Frontend -> Backend -> MediaMTX
        if self.engine:
            self.engine.stop()
        
        if self.service_manager:
            self.service_manager.stop_frontend()
            self.service_manager.stop_backend_api()
            self.service_manager.stop_mediamtx()
        
        # Stop storage lifecycle services (Phase 17)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        logger.info("Stopping storage lifecycle services...")
        loop.run_until_complete(stop_storage_services())
        
        logger.info("Shutdown complete")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AI Attendance Pipeline Engine Bootstrap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bootstrap.py                    # Start full pipeline
  python bootstrap.py --check            # Environment check only
  python bootstrap.py --diagnostics      # Run diagnostics
  python bootstrap.py --camera cam1      # Start only cam1
  python bootstrap.py --no-mediamtx      # Don't manage MediaMTX
  python bootstrap.py --stop             # Stop running pipeline
        """
    )
    
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to pipeline.yaml configuration",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run environment check only",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Run full diagnostics",
    )
    parser.add_argument(
        "--camera",
        action="append",
        dest="cameras",
        help="Camera ID to start (can specify multiple)",
    )
    parser.add_argument(
        "--no-mediamtx",
        action="store_true",
        help="Don't start/manage MediaMTX (assume external)",
    )
    parser.add_argument(
        "--no-frontend",
        action="store_true",
        help="Don't start frontend",
    )
    parser.add_argument(
        "--no-backend",
        action="store_true",
        help="Don't start backend API",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    
    args = parser.parse_args()
    
    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    bootstrap = Bootstrap(
        config_path=args.config,
        no_mediamtx=args.no_mediamtx,
        no_frontend=args.no_frontend,
        no_backend=args.no_backend,
        camera_ids=args.cameras,
    )
    
    if args.check:
        return bootstrap.run_check()
    elif args.diagnostics:
        return bootstrap.run_diagnostics()
    else:
        return bootstrap.start()


if __name__ == "__main__":
    sys.exit(main())