#!/usr/bin/env python3
"""
Phase 43 — Windows Bootstrap Orchestrator (Stabilized).

Main entry point for service orchestration:
- MediaMTX
- FastAPI/Uvicorn Backend
- Figma/Vite Frontend

This module owns all service startup, supervision, and shutdown.
Uses Python subprocess.Popen directly - no nested .bat/.cmd launchers.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add repository root to path for imports
REPO_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(REPO_ROOT))

from app.bootstrap.port_discovery import find_coordinated_ports
from app.bootstrap.startup_validation import run_startup_validation, print_validation_report


@dataclass
class ServiceProcess:
    """Represents a managed service process."""
    name: str
    process: subprocess.Popen
    port: Optional[int] = None
    health_url: Optional[str] = None
    cwd: Optional[Path] = None
    stdout_log: List[str] = field(default_factory=list)
    stderr_log: List[str] = field(default_factory=list)
    critical: bool = True  # If True, process exit triggers shutdown


class BootstrapOrchestrator:
    """Orchestrates the complete AI Attendance System startup."""

    def __init__(self):
        self.repo_root = REPO_ROOT
        self.venv_python = self.repo_root / ".venv2" / "Scripts" / "python.exe"
        self.services: List[ServiceProcess] = []
        self.shutdown_event = threading.Event()
        self.backend_port: Optional[int] = None
        self.frontend_port: Optional[int] = None
        self._stdout_threads: List[threading.Thread] = []
        self._stderr_threads: List[threading.Thread] = []

    def run(self) -> int:
        """Main orchestration entry point."""
        print("=" * 60)
        print("AI Attendance System - Bootstrap Orchestrator (Phase 43)")
        print("=" * 60)
        print(f"Repository root: {self.repo_root}")
        print()

        # Step 0: Preflight checks for Python interpreter and virtual environment
        if not self._preflight_checks():
            return 106

        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()

        try:
            # Step 1: Run startup validation
            if not self._run_startup_validation():
                return 1

            # Step 2: Discover dynamic ports
            if not self._discover_ports():
                return 1

            # Step 3: Start MediaMTX (non-critical)
            if not self._start_mediamtx():
                return 1

            # Step 4: Start Backend (critical)
            if not self._start_backend():
                return 1

            # Step 5: Start Frontend (critical)
            if not self._start_frontend():
                return 1

            # Step 6: Verify all services
            if not self._verify_services():
                return 1

            # Step 7: Print service URLs and supervise
            self._print_service_urls()
            self._supervise_services()

            return 0

        except KeyboardInterrupt:
            print("\n[INFO] Received interrupt signal")
            return self._shutdown()
        except Exception as e:
            print(f"[ERROR] Bootstrap failed: {e}")
            import traceback
            traceback.print_exc()
            return self._shutdown()

    def _preflight_checks(self) -> bool:
        """Perform preflight checks for Python interpreter and virtual environment."""
        print("[INFO] Running preflight checks...")
        print(f"[INFO]   Expected Python: {self.venv_python}")
        print(f"[INFO]   Repository root: {self.repo_root}")

        # Check 1: Python executable exists
        if not self.venv_python.exists():
            print(f"[ERROR] Python executable not found: {self.venv_python}")
            return False
        print(f"[OK]   Python executable exists: {self.venv_python}")

        # Check 2: pyvenv.cfg exists
        pyvenv_cfg = self.repo_root / ".venv2" / "pyvenv.cfg"
        if not pyvenv_cfg.exists():
            print(f"[ERROR] pyvenv.cfg not found: {pyvenv_cfg}")
            return False
        print(f"[OK]   pyvenv.cfg exists: {pyvenv_cfg}")

        # Check 3: Python executable is inside the expected .venv
        try:
            venv_scripts = (self.repo_root / ".venv2" / "Scripts").resolve()
            python_exe = self.venv_python.resolve()
            if not str(python_exe).startswith(str(venv_scripts)):
                print(f"[ERROR] Python executable is not inside expected .venv: {python_exe}")
                return False
            print(f"[OK]   Python executable is inside expected .venv")
        except Exception as e:
            print(f"[ERROR] Failed to verify Python executable location: {e}")
            return False

        # Check 4: Python can execute normally and get version info
        try:
            result = subprocess.run(
                [str(self.venv_python), "-c", "import sys; print(sys.version); print(sys.prefix); print(sys.base_prefix)"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                print(f"[ERROR] Python execution failed: {result.stderr}")
                return False
            
            output_lines = result.stdout.strip().split('\n')
            python_version = output_lines[0] if output_lines else "unknown"
            sys_prefix = output_lines[1] if len(output_lines) > 1 else "unknown"
            sys_base_prefix = output_lines[2] if len(output_lines) > 2 else "unknown"
            
            print(f"[OK]   Python executes normally")
            print(f"[INFO]   Python version: {python_version}")
            print(f"[INFO]   sys.prefix: {sys_prefix}")
            print(f"[INFO]   sys.base_prefix: {sys_base_prefix}")
            
            # Verify it's actually a virtual environment
            if sys_prefix == sys_base_prefix:
                print(f"[WARN] Python does not appear to be running in a virtual environment (sys.prefix == sys.base_prefix)")
            else:
                print(f"[OK]   Virtual environment confirmed (sys.prefix != sys.base_prefix)")
                
        except subprocess.TimeoutExpired:
            print(f"[ERROR] Python execution timed out")
            return False
        except Exception as e:
            print(f"[ERROR] Failed to execute Python: {e}")
            return False

        # Check 5: Repository root is resolved correctly
        try:
            resolved_root = self.repo_root.resolve()
            print(f"[OK]   Repository root resolved: {resolved_root}")
        except Exception as e:
            print(f"[ERROR] Failed to resolve repository root: {e}")
            return False

        print("[INFO] Preflight checks passed")
        print()
        return True

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            print(f"\n[INFO] Received signal {signum}")
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Windows-specific: also handle CTRL_BREAK_EVENT
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)

    def _run_startup_validation(self) -> bool:
        """Run startup validation checks."""
        print("[INFO] Running startup validation...")
        report = run_startup_validation()
        print_validation_report(report)

        if report.overall_status == "fail":
            print("[ERROR] Startup validation failed")
            return False

        print("[INFO] Startup validation passed")
        print()
        return True

    def _discover_ports(self) -> bool:
        """Discover coordinated backend and frontend ports."""
        print("[INFO] Discovering available ports...")
        try:
            self.backend_port, self.frontend_port = find_coordinated_ports()
            print(f"[INFO] Backend port:  {self.backend_port} (range 10000-19999)")
            print(f"[INFO] Frontend port: {self.frontend_port} (range 20000-29999)")
            print()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to discover ports: {e}")
            return False

    def _start_mediamtx(self) -> bool:
        """Start MediaMTX process (non-critical)."""
        mediamtx_exe = self.repo_root / "mediamtx" / "mediamtx.exe"
        mediamtx_config = self.repo_root / "mediamtx" / "mediamtx.yml"

        if not mediamtx_exe.exists():
            print(f"[WARN] MediaMTX not found at: {mediamtx_exe} - continuing without MediaMTX")
            return True  # Not fatal

        if not mediamtx_config.exists():
            print(f"[WARN] MediaMTX config not found at: {mediamtx_config} - continuing without MediaMTX")
            return True  # Not fatal

        print(f"[INFO] Starting MediaMTX...")
        print(f"[INFO]   Executable: {mediamtx_exe}")
        print(f"[INFO]   Config:     {mediamtx_config}")

        try:
            # Use subprocess.Popen with explicit arguments (no shell)
            proc = subprocess.Popen(
                [str(mediamtx_exe), str(mediamtx_config)],
                cwd=str(self.repo_root / "mediamtx"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

            service = ServiceProcess(
                name="MediaMTX",
                process=proc,
                cwd=self.repo_root / "mediamtx",
                critical=False,  # MediaMTX is non-critical
            )
            self.services.append(service)

            # Start log capture threads
            self._start_log_capture(service)

            # Give MediaMTX a moment to start
            time.sleep(2)

            # Check if process is still alive
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                print(f"[WARN] MediaMTX exited (code: {proc.returncode}) - continuing without MediaMTX")
                if stderr:
                    stderr_text = stderr.decode('utf-8', errors='replace')[:500]
                    print(f"[WARN] MediaMTX stderr: {stderr_text}")
                # MediaMTX is not fatal for bootstrap - continue without it
                self.services = [s for s in self.services if s.name != "MediaMTX"]
                print()
                return True

            print(f"[INFO] MediaMTX started (PID: {proc.pid})")
            print()
            return True

        except Exception as e:
            print(f"[ERROR] Failed to start MediaMTX: {e}")
            return False

    def _start_backend(self) -> bool:
        """Start FastAPI/Uvicorn backend (critical)."""
        if not self.venv_python.exists():
            print(f"[ERROR] Virtual environment Python not found: {self.venv_python}")
            return False

        print(f"[INFO] Starting Backend API...")
        print(f"[INFO]   Host: 0.0.0.0")
        print(f"[INFO]   Port: {self.backend_port}")

        try:
            # Prepare environment
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self.repo_root)

            proc = subprocess.Popen(
                [
                    str(self.venv_python),
                    "-m", "uvicorn",
                    "app.main:app",
                    "--host", "0.0.0.0",
                    "--port", str(self.backend_port),
                    "--log-level", "info",
                ],
                cwd=str(self.repo_root),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

            service = ServiceProcess(
                name="Backend",
                process=proc,
                port=self.backend_port,
                health_url=f"http://localhost:{self.backend_port}/api/v1/health/system",
                cwd=self.repo_root,
                critical=True,
            )
            self.services.append(service)

            # Start log capture threads
            self._start_log_capture(service)

            # Give backend time to start
            time.sleep(3)

            # Check if process is still alive
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                print(f"[ERROR] Backend exited unexpectedly (code: {proc.returncode})")
                if stderr:
                    print(f"[ERROR] stderr: {stderr.decode('utf-8', errors='replace')[:500]}")
                return False

            print(f"[INFO] Backend started (PID: {proc.pid})")
            print()
            return True

        except Exception as e:
            print(f"[ERROR] Failed to start Backend: {e}")
            return False

    def _start_frontend(self) -> bool:
        """Start Figma/Vite frontend (critical)."""
        figma_dir = self.repo_root / "figma"
        package_json = figma_dir / "package.json"

        if not package_json.exists():
            print(f"[WARN] Figma frontend not found at: {figma_dir} - continuing without frontend")
            return True  # Not fatal

        print(f"[INFO] Starting Figma Frontend...")
        print(f"[INFO]   Host: 0.0.0.0")
        print(f"[INFO]   Port: {self.frontend_port}")

        # Determine package manager - prefer pnpm
        pnpm_path = self._find_executable("pnpm")
        npm_path = self._find_executable("npm")

        if pnpm_path:
            pkg_manager = "pnpm"
            pkg_args = [str(pnpm_path), "dev", "--", "--port", str(self.frontend_port)]
        elif npm_path:
            pkg_manager = "npm"
            pkg_args = [str(npm_path), "run", "dev", "--", "--port", str(self.frontend_port)]
        else:
            print("[ERROR] Neither pnpm nor npm found. Please install Node.js.")
            return False

        print(f"[INFO] Using {pkg_manager} for frontend")

        try:
            # Prepare environment with backend URL propagation
            env = os.environ.copy()
            env["VITE_API_BASE_URL"] = f"http://localhost:{self.backend_port}"
            env["VITE_WS_BASE_URL"] = f"ws://localhost:{self.backend_port}"
            env["PORT"] = str(self.frontend_port)

            # On Windows, pnpm/npm are .cmd files and require shell=True
            use_shell = sys.platform == "win32"

            proc = subprocess.Popen(
                pkg_args,
                cwd=str(figma_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=use_shell,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

            service = ServiceProcess(
                name="Frontend",
                process=proc,
                port=self.frontend_port,
                health_url=f"http://localhost:{self.frontend_port}/",
                cwd=figma_dir,
                critical=True,
            )
            self.services.append(service)

            # Start log capture threads
            self._start_log_capture(service)

            # Give frontend time to start (Vite takes longer)
            time.sleep(5)

            # Check if process is still alive
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                print(f"[ERROR] Frontend exited unexpectedly (code: {proc.returncode})")
                if stderr:
                    print(f"[ERROR] stderr: {stderr.decode('utf-8', errors='replace')[:500]}")
                return False

            print(f"[INFO] Frontend started (PID: {proc.pid})")
            print()
            return True

        except Exception as e:
            print(f"[ERROR] Failed to start Frontend: {e}")
            return False

    def _find_executable(self, name: str) -> Optional[Path]:
        """Find executable in PATH."""
        # Check common locations
        paths_to_check = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "pnpm" / f"{name}.exe",
            Path(os.environ.get("APPDATA", "")) / "npm" / f"{name}.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "nodejs" / f"{name}.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "nodejs" / f"{name}.exe",
        ]

        for path in paths_to_check:
            if path.exists():
                return path

        # Try using where command
        try:
            result = subprocess.run(
                ["where", name],
                capture_output=True,
                text=True,
                shell=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip().split('\n')[0])
        except Exception:
            pass

        return None

    def _start_log_capture(self, service: ServiceProcess) -> None:
        """Start background threads to capture stdout/stderr for diagnostics."""
        def capture_stream(stream, log_list: List[str], stream_name: str):
            try:
                for line in iter(stream.readline, b''):
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace').rstrip()
                    log_list.append(decoded)
                    # Keep only last 100 lines to avoid memory issues
                    if len(log_list) > 100:
                        log_list.pop(0)
            except Exception:
                pass

        if service.process.stdout:
            t = threading.Thread(target=capture_stream, args=(service.process.stdout, service.stdout_log, "stdout"), daemon=True)
            t.start()
            self._stdout_threads.append(t)

        if service.process.stderr:
            t = threading.Thread(target=capture_stream, args=(service.process.stderr, service.stderr_log, "stderr"), daemon=True)
            t.start()
            self._stderr_threads.append(t)

    def _verify_services(self) -> bool:
        """Verify all services are healthy."""
        print("[INFO] Verifying services...")

        all_healthy = True

        for service in self.services:
            if service.health_url:
                healthy = self._check_http_health(service.health_url, service.name)
                if not healthy:
                    all_healthy = False
            else:
                # For services without HTTP health check, just verify process is alive
                if service.process.poll() is not None:
                    print(f"[ERROR] {service.name} process has exited")
                    all_healthy = False
                else:
                    print(f"[OK]   {service.name} process alive (PID: {service.process.pid})")

        if not all_healthy:
            print("[ERROR] Service verification failed")
            return False

        print("[INFO] All services verified healthy")
        print()
        return True

    def _check_http_health(self, url: str, service_name: str, max_retries: int = 15, retry_delay: float = 1.0) -> bool:
        """Check HTTP health endpoint with retries."""
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        print(f"[OK]   {service_name} health check passed: {url}")
                        return True
            except urllib.error.HTTPError as e:
                if e.code == 200:
                    print(f"[OK]   {service_name} health check passed: {url}")
                    return True
            except Exception:
                pass

            if attempt < max_retries - 1:
                time.sleep(retry_delay)

        print(f"[ERROR] {service_name} health check failed after {max_retries} attempts: {url}")
        return False

    def _print_service_urls(self) -> None:
        """Print service URLs."""
        print("=" * 60)
        print("AI Attendance System - Services Started")
        print("=" * 60)
        if self.backend_port:
            print(f"Backend API:  http://localhost:{self.backend_port}")
            print(f"API Docs:     http://localhost:{self.backend_port}/docs")
            print(f"Health API:   http://localhost:{self.backend_port}/api/v1/health/system")
            print(f"WebSocket:    ws://localhost:{self.backend_port}/api/v1/health/ws")
            print(f"SSE:          http://localhost:{self.backend_port}/api/v1/health/stream")
        if self.frontend_port:
            print(f"Frontend UI:  http://localhost:{self.frontend_port}")
        print("=" * 60)
        print()
        print("Press Ctrl+C to stop all services...")
        print()

    def _supervise_services(self) -> None:
        """Supervise running services until shutdown."""
        print("[INFO] Entering supervision loop...")

        while not self.shutdown_event.is_set():
            # Check all service processes
            for service in self.services:
                exit_code = service.process.poll()
                if exit_code is not None:
                    if service.critical:
                        print(f"[ERROR] Critical service {service.name} exited unexpectedly (code: {exit_code})")
                        self._print_service_logs(service)
                        self.shutdown_event.set()
                        return
                    else:
                        print(f"[WARN] Non-critical service {service.name} exited (code: {exit_code})")
                        self._print_service_logs(service)
                        # Remove non-critical service from supervision
                        self.services = [s for s in self.services if s.name != service.name]

            # Sleep before next check
            self.shutdown_event.wait(timeout=2.0)

        print("[INFO] Shutdown requested")

    def _print_service_logs(self, service: ServiceProcess) -> None:
        """Print captured logs for a failed service."""
        if service.stdout_log:
            print(f"[INFO] {service.name} stdout (last 20 lines):")
            for line in service.stdout_log[-20:]:
                print(f"  {line}")
        if service.stderr_log:
            print(f"[INFO] {service.name} stderr (last 20 lines):")
            for line in service.stderr_log[-20:]:
                print(f"  {line}")

    def _shutdown(self) -> int:
        """Gracefully shutdown all services."""
        print("[INFO] Stopping services...")

        # Terminate in reverse order (frontend, backend, mediamtx)
        for service in reversed(self.services):
            print(f"[INFO] Stopping {service.name} (PID: {service.process.pid})...")
            try:
                if sys.platform == "win32":
                    # On Windows, use taskkill for process groups
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(service.process.pid)],
                        capture_output=True,
                        timeout=10,
                    )
                else:
                    service.process.terminate()

                # Wait for graceful shutdown
                try:
                    service.process.wait(timeout=5)
                    print(f"[INFO] {service.name} stopped gracefully")
                except subprocess.TimeoutExpired:
                    print(f"[WARN] {service.name} did not stop gracefully, forcing...")
                    service.process.kill()
                    service.process.wait()
                    print(f"[INFO] {service.name} force stopped")
            except Exception as e:
                print(f"[WARN] Error stopping {service.name}: {e}")

        print("[INFO] All services stopped")
        return 0


def main() -> int:
    """Main entry point."""
    orchestrator = BootstrapOrchestrator()
    return orchestrator.run()


if __name__ == "__main__":
    sys.exit(main())
