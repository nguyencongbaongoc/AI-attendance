#!/usr/bin/env python
"""
Phase 33 — Live Health / Failover Acceptance Script.

High-level gate for Phase 33 live stream health monitoring and failover verification.
Runs pytest unit tests and generates JSON/Markdown reports.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
class Phase33Acceptance:
    """Phase 33 acceptance test runner and reporter."""

    def __init__(self):
        self.results: Dict[str, Any] = {
            "phase": "33",
            "name": "LIVE_HEALTH_FAILOVER",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "verdict": "UNKNOWN",
            "pytest_results": {},
            "acceptance_checks": {},
            "health_contract": {},
            "state_machine": {},
            "frame_freshness": {},
            "stale_frame_detection": {},
            "cam1_isolation": {},
            "cam2_isolation": {},
            "reconnect": {},
            "bounded_retry": {},
            "failure_injection": {},
            "recovery": {},
            "ffmpeg_health": {},
            "mediamtx_health": {},
            "h264_runtime": {},
            "k4_30_runtime": {},
            "determinism": {},
            "negative_cases": {},
            "regression": {},
            "known_limitations": [],
            "runtime_verification_level": "OFFLINE_VERIFIED",
        }
        self.start_time = time.time()

    def run_pytest(self, test_path: str, label: str) -> Dict[str, Any]:
        """Run pytest and capture results."""
        print(f"\n{'='*60}")
        print(f"Running {label}: {test_path}")
        print(f"{'='*60}")

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=300,
            )

            return {
                "label": label,
                "test_path": test_path,
                "exit_code": result.returncode,
                "passed": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "label": label,
                "test_path": test_path,
                "exit_code": -1,
                "passed": False,
                "stdout": "",
                "stderr": "TIMEOUT",
                "duration": 0,
            }
        except Exception as e:
            return {
                "label": label,
                "test_path": test_path,
                "exit_code": -1,
                "passed": False,
                "stdout": "",
                "stderr": str(e),
                "duration": 0,
            }

    def run_unit_tests(self) -> Dict[str, Any]:
        """Run unit tests for Phase 33."""
        print("\nRunning Phase 33 unit tests...")

        results = {}

        # Health events tests
        result = self.run_pytest(
            "tests/unit/test_streaming_health_events.py",
            "Phase 33 Health Events"
        )
def run_acceptance_checks(self) -> Dict[str, Any]:
        """Run acceptance checks for Phase 33."""
        print("\nRunning Phase 33 acceptance checks...")

        checks = {}

        # 1. Health contract verification
        checks["health_contract"] = self._check_health_contract()

        # 2. State machine verification
        checks["state_machine"] = self._check_state_machine()

        # 3. Frame freshness monitoring
        checks["frame_freshness"] = self._check_frame_freshness()

        # 4. Stale frame detection
        checks["stale_frame_detection"] = self._check_stale_frame_detection()

        # 5. CAM1 isolation
        checks["cam1_isolation"] = self._check_cam1_isolation()

        # 6. CAM2 isolation
        checks["cam2_isolation"] = self._check_cam2_isolation()

        # 7. Reconnect behavior
        checks["reconnect"] = self._check_reconnect()

        # 8. Bounded retry
        checks["bounded_retry"] = self._check_bounded_retry()

        # 9. Failure injection
        checks["failure_injection"] = self._check_failure_injection()

        # 10. Recovery
        checks["recovery"] = self._check_recovery()

        # 11. FFmpeg health
        checks["ffmpeg_health"] = self._check_ffmpeg_health()

        # 12. MediaMTX health
        checks["mediamtx_health"] = self._check_mediamtx_health()

        # 13. H.264 runtime
        checks["h264_runtime"] = self._check_h264_runtime()

        # 14. 4K30 runtime
        checks["k4_30_runtime"] = self._check_4k30_runtime()

        # 15. Determinism
        checks["determinism"] = self._check_determinism()

        # 16. Negative cases
        checks["negative_cases"] = self._check_negative_cases()

        # 17. Regression
        checks["regression"] = self._check_regression()

        return checks
        results["health_events"] = result
        self.results["pytest_results"]["health_events"] = result

        # Health monitor tests
        result = self.run_pytest(
            "tests/unit/test_streaming_health.py",
            "Phase 33 Health Monitor"
        )
        results["health_monitor"] = result
        self.results["pytest_results"]["health_monitor"] = result

        # Phase 32 regression tests
        result = self.run_pytest(
            "tests/unit/test_streaming_contracts.py",
            "Phase 32 Streaming Contracts (Regression)"
        )
        results["contracts_regression"] = result
        self.results["pytest_results"]["contracts_regression"] = result

        result = self.run_pytest(
            "tests/unit/test_streaming_mediamtx.py",
            "Phase 32 MediaMTX Config (Regression)"
        )
        results["mediamtx_regression"] = result
        self.results["pytest_results"]["mediamtx_regression"] = result

        return results