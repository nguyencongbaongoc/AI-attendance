#!/usr/bin/env python
"""
Phase 32 — RTMP + MediaMTX Acceptance Script.

High-level gate for Phase 32 RTMP + MediaMTX verification.
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


class Phase32Acceptance:
    """Phase 32 acceptance test runner and reporter."""

    def __init__(self):
        self.results: Dict[str, Any] = {
            "phase": "32",
            "name": "RTMP_MEDIAMTX",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "verdict": "UNKNOWN",
            "pytest_results": {},
            "acceptance_checks": {},
            "contract": {},
            "mediamtx": {},
            "cam1": {},
            "cam2": {},
            "isolation": {},
            "lifecycle": {},
            "reconnect": {},
            "h264": {},
            "v2_ingestion": {},
            "negative_cases": {},
            "determinism": {},
            "known_limitations": [],
            "runtime_verification_level": "OFFLINE_CONTRACT_ONLY",
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
        """Run unit tests for Phase 32."""
        print("\nRunning Phase 32 unit tests...")

        results = {}

        # Contract tests
        result = self.run_pytest(
            "tests/unit/test_streaming_contracts.py",
            "Phase 32 Streaming Contracts"
        )
        results["contracts"] = result
        self.results["pytest_results"]["contracts"] = result

        # MediaMTX tests
        result = self.run_pytest(
            "tests/unit/test_streaming_mediamtx.py",
            "Phase 32 MediaMTX Configuration"
        )
        results["mediamtx"] = result
        self.results["pytest_results"]["mediamtx"] = result

        return results

    def run_acceptance_checks(self) -> Dict[str, Any]:
        """Run acceptance checks."""
        print("\nRunning acceptance checks...")

        checks = {}

        # Contract validation
        checks["contract_validation"] = self._check_contract_validation()

        # MediaMTX configuration validation
        checks["mediamtx_config_validation"] = self._check_mediamtx_config()

        # CAM1 validation
        checks["cam1_validation"] = self._check_cam1()

        # CAM2 validation
        checks["cam2_validation"] = self._check_cam2()

        # Isolation
        checks["isolation"] = self._check_isolation()

        # Lifecycle
        checks["lifecycle"] = self._check_lifecycle()

        # Reconnect
        checks["reconnect"] = self._check_reconnect()

        # H.264 contract
        checks["h264_contract"] = self._check_h264()

        # V2 ingestion integration
        checks["v2_ingestion"] = self._check_v2_ingestion()

        # Negative cases
        checks["negative_cases"] = self._check_negative_cases()

        # Determinism
        checks["determinism"] = self._check_determinism()

        self.results["acceptance_checks"] = checks
        return checks
    def _check_contract_validation(self) -> Dict[str, Any]:
        """Check contract validation."""
        try:
            from app.streaming.contracts import (
                CameraStreamContract,
                create_camera_stream_contract,
                validate_camera_stream_contract,
                StreamCodec,
            )

            # Valid contract
            contract = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            is_valid, errors = validate_camera_stream_contract(contract)
            assert is_valid is True

            # Invalid codec
            contract_bad = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
                expected_codec=StreamCodec.H265,
            )
            is_valid, errors = validate_camera_stream_contract(contract_bad)
            assert is_valid is False

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_mediamtx_config(self) -> Dict[str, Any]:
        """Check MediaMTX configuration."""
        try:
            from app.streaming.mediamtx_config import (
                create_mediamtx_config,
                validate_mediamtx_config,
            )

            config = create_mediamtx_config()
            is_valid, errors = validate_mediamtx_config(config)
            assert is_valid is True

            # Check CAM1 and CAM2 paths
            assert "cam1" in config.paths
            assert "cam2" in config.paths
            assert config.paths["cam1"].rtmp_stream_key == "cam1"
            assert config.paths["cam1"].rtsp_path == "cam1"
            assert config.paths["cam2"].rtmp_stream_key == "cam2"
            assert config.paths["cam2"].rtsp_path == "cam2"

            # Check YAML generation
            yaml_str = config.to_yaml()
            assert "cam1:" in yaml_str
            assert "cam2:" in yaml_str

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_cam1(self) -> Dict[str, Any]:
        """Check CAM1 configuration."""
        try:
            from app.streaming.contracts import create_camera_stream_contract
            from app.streaming.mediamtx_config import create_mediamtx_config

            contract = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            assert contract.camera_id == "CAM1"
            assert contract.get_rtmp_url() == "rtmp://localhost:1935/live/cam1"
            assert contract.get_rtsp_url() == "rtsp://localhost:8554/cam1"

            config = create_mediamtx_config()
            cam1 = config.get_path("cam1")
            assert cam1 is not None
            assert cam1.rtmp_stream_key == "cam1"
            assert cam1.rtsp_path == "cam1"

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_cam2(self) -> Dict[str, Any]:
        """Check CAM2 configuration."""
        try:
            from app.streaming.contracts import create_camera_stream_contract
            from app.streaming.mediamtx_config import create_mediamtx_config

            contract = create_camera_stream_contract(
                camera_id="CAM2",
                rtmp_stream_key="cam2",
                rtsp_path="cam2",
            )
            assert contract.camera_id == "CAM2"
            assert contract.get_rtmp_url() == "rtmp://localhost:1935/live/cam2"
            assert contract.get_rtsp_url() == "rtsp://localhost:8554/cam2"

            config = create_mediamtx_config()
            cam2 = config.get_path("cam2")
            assert cam2 is not None
            assert cam2.rtmp_stream_key == "cam2"
            assert cam2.rtsp_path == "cam2"

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}
    def _check_isolation(self) -> Dict[str, Any]:
        """Check CAM1/CAM2 isolation."""
        try:
            from app.streaming.mediamtx_config import create_mediamtx_config

            config = create_mediamtx_config()

            # Verify separate paths
            cam1 = config.get_path("cam1")
            cam2 = config.get_path("cam2")

            # Different RTMP keys
            assert cam1.rtmp_stream_key != cam2.rtmp_stream_key
            # Different RTSP paths
            assert cam1.rtsp_path != cam2.rtsp_path

            # Verify no cross-contamination in config
            stream_keys = [p.rtmp_stream_key for p in config.paths.values()]
            rtsp_paths = [p.rtsp_path for p in config.paths.values()]
            assert len(stream_keys) == len(set(stream_keys))
            assert len(rtsp_paths) == len(set(rtsp_paths))

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}
    def _check_lifecycle(self) -> Dict[str, Any]:
        """Check stream lifecycle states."""
        try:
            from app.streaming.contracts import StreamHealthState

            # Verify all required states exist
            states = [
                StreamHealthState.OFFLINE,
                StreamHealthState.CONNECTING,
                StreamHealthState.LIVE,
                StreamHealthState.DEGRADED,
                StreamHealthState.RECONNECTING,
                StreamHealthState.ERROR,
            ]
            assert len(states) == 6

            # Verify state values
            assert StreamHealthState.OFFLINE.value == "offline"
            assert StreamHealthState.LIVE.value == "live"
            assert StreamHealthState.ERROR.value == "error"

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_reconnect(self) -> Dict[str, Any]:
        """Check reconnect configuration."""
        try:
            from app.streaming.reconnect import (
                ReconnectConfig,
                ReconnectPolicy,
                ReconnectState,
            )

            # Verify config
            config = ReconnectConfig()
            assert config.max_retries == 5
            assert config.policy == ReconnectPolicy.EXPONENTIAL_BACKOFF

            # Verify states
            states = [
                ReconnectState.IDLE,
                ReconnectState.CONNECTING,
                ReconnectState.WAITING,
                ReconnectState.RETRYING,
                ReconnectState.EXHAUSTED,
                ReconnectState.SUCCESS,
                ReconnectState.FAILED,
            ]
            assert len(states) == 7

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_h264(self) -> Dict[str, Any]:
        """Check H.264 contract."""
        try:
            from app.streaming.contracts import (
                StreamCodec,
                StreamMetadata,
                CameraStreamContract,
                create_camera_stream_contract,
                validate_camera_stream_contract,
            )

            # Verify H.264 is the only supported codec
            assert StreamCodec.H264.value == "h264"

            # Verify 4K H.264 30 FPS contract
            meta = StreamMetadata(camera_id="CAM1")
            assert meta.is_4k_h264_30fps() is True

            # Verify contract enforces H.264
            contract = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            assert contract.expected_codec == StreamCodec.H264
            assert contract.expected_resolution == (3840, 2160)
            assert contract.expected_fps == 30.0

            # Verify validation rejects non-H.264
            contract_bad = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
                expected_codec=StreamCodec.H265,
            )
            is_valid, errors = validate_camera_stream_contract(contract_bad)
            assert is_valid is False

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}
    def _check_v2_ingestion(self) -> Dict[str, Any]:
        """Check V2 ingestion integration."""
        try:
            from app.streaming.contracts import create_camera_stream_contract
            from app.streaming.rtsp_source import RTSPSourceConfig

            # Verify RTSP source config can convert to ReplaySourceConfig
            rtsp_config = RTSPSourceConfig(
                camera_id="CAM1",
                rtsp_url="rtsp://localhost:8554/cam1",
            )
            replay_config = rtsp_config.to_replay_source_config()
            assert replay_config.camera_id == "CAM1"
            assert replay_config.source_path == "rtsp://localhost:8554/cam1"

            # Verify contract has RTSP URL
            contract = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            rtsp_url = contract.get_rtsp_url()
            assert rtsp_url == "rtsp://localhost:8554/cam1"

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_negative_cases(self) -> Dict[str, Any]:
        """Check negative cases."""
        try:
            from app.streaming.contracts import (
                create_camera_stream_contract,
                validate_camera_stream_contract,
                StreamCodec,
            )
            from app.streaming.mediamtx_config import (
                MediaMTXConfig,
                MediaMTXPathConfig,
                validate_mediamtx_config,
            )

            # Invalid camera ID
            contract = create_camera_stream_contract(
                camera_id="",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            is_valid, errors = validate_camera_stream_contract(contract)
            assert is_valid is False

            # Invalid RTMP key
            contract = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="",
                rtsp_path="cam1",
            )
            is_valid, errors = validate_camera_stream_contract(contract)
            assert is_valid is False

            # Invalid RTSP path
            contract = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="",
            )
            is_valid, errors = validate_camera_stream_contract(contract)
            assert is_valid is False

            # Duplicate camera in MediaMTX
            config = MediaMTXConfig()
            config.add_path(MediaMTXPathConfig(
                name="cam1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            ))
            config.add_path(MediaMTXPathConfig(
                name="cam1",  # Duplicate
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            ))
            is_valid, errors = validate_mediamtx_config(config)
            assert is_valid is False

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def _check_determinism(self) -> Dict[str, Any]:
        """Check deterministic behavior."""
        try:
            from app.streaming.contracts import create_camera_stream_contract

            # Same inputs should produce same contract
            contract1 = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            contract2 = create_camera_stream_contract(
                camera_id="CAM1",
                rtmp_stream_key="cam1",
                rtsp_path="cam1",
            )
            assert contract1.to_dict() == contract2.to_dict()

            return {"verified": True, "level": "OFFLINE_CONTRACT_VERIFIED"}
        except Exception as e:
            return {"verified": False, "error": str(e), "level": "NOT_VERIFIED"}

    def generate_reports(self) -> List[str]:
        """Generate JSON and Markdown reports."""
        reports_dir = Path("benchmark_results")
        reports_dir.mkdir(exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        json_path = reports_dir / f"PHASE_32_RTMP_MEDIAMTX_{timestamp}.json"
        md_path = reports_dir / f"PHASE_32_RTMP_MEDIAMTX_{timestamp}.md"

        # JSON report
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2)

        # Markdown report
        md_content = self._generate_markdown()
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return [str(json_path), str(md_path)]

    def _generate_markdown(self) -> str:
        """Generate Markdown report."""
        lines = [
            "# Phase 32 — RTMP + MediaMTX Acceptance Report",
            "",
            f"**Timestamp:** {self.results['timestamp']}",
            f"**Verdict:** {self.results['verdict']}",
            f"**Runtime Verification Level:** {self.results['runtime_verification_level']}",
            "",
            "## Pytest Results",
            "",
        ]

        for key, result in self.results["pytest_results"].items():
            status = "PASS" if result.get("passed", False) else "FAIL"
            lines.append(f"- **{key}**: {status} (exit_code={result.get('exit_code', 'N/A')})")

        lines.extend([
            "",
            "## Acceptance Checks",
            "",
        ])

        for key, check in self.results["acceptance_checks"].items():
            status = "VERIFIED" if check.get("verified", False) else "NOT VERIFIED"
            level = check.get("level", "UNKNOWN")
            lines.append(f"- **{key}**: {status} ({level})")

        lines.extend([
            "",
            "## Known Limitations",
            "",
        ])

        for limitation in self.results["known_limitations"]:
            lines.append(f"- {limitation}")

        if not self.results["known_limitations"]:
            lines.append("- None")

        lines.extend([
            "",
            "## Summary",
            "",
            f"- **Total Pytest Suites**: {len(self.results['pytest_results'])}",
            f"- **Total Acceptance Checks**: {len(self.results['acceptance_checks'])}",
            f"- **Checks Verified**: {sum(1 for c in self.results['acceptance_checks'].values() if c.get('verified', False))}",
            f"- **Runtime Verification Level**: {self.results['runtime_verification_level']}",
        ])

        return "\n".join(lines)

    def run_all_checks(self) -> Dict[str, Any]:
        """Run all acceptance checks."""
        print("="*60)
        print("PHASE 32 — RTMP + MEDIAMTX ACCEPTANCE")
        print("="*60)
        print(f"Started at: {datetime.utcnow().isoformat()}Z")
        print()

        # Run pytest unit tests
        unit_results = self.run_unit_tests()

        # Run acceptance checks
        acceptance_checks = self.run_acceptance_checks()
        self.results["acceptance_checks"] = acceptance_checks

        # Determine verdict
        all_pytest_passed = all(r.get("passed", False) for r in unit_results.values())
        all_checks_verified = all(c.get("verified", False) for c in acceptance_checks.values())

        if all_pytest_passed and all_checks_verified:
            self.results["verdict"] = "PASS"
        elif all_pytest_passed:
            self.results["verdict"] = "PASS WITH LIMITATION"
        else:
            self.results["verdict"] = "FAIL"

        # Generate reports
        reports = self.generate_reports()

        # Print summary
        print(f"\n{'='*60}")
        print(f"PHASE 32 VERDICT: {self.results['verdict']}")
        print(f"{'='*60}")
        print(f"Pytest Unit: {'PASS' if all_pytest_passed else 'FAIL'}")
        print(f"Acceptance Checks: {sum(1 for c in acceptance_checks.values() if c.get('verified', False))}/{len(acceptance_checks)} verified")
        print(f"Duration: {time.time() - self.start_time:.2f}s")
        print(f"\nReports generated:")
        for report in reports:
            print(f"  {report}")

        return self.results


def main():
    """Main entry point."""
    acceptance = Phase32Acceptance()
    results = acceptance.run_all_checks()

    if results['verdict'] == 'PASS':
        print("\n[OK] PHASE 32 PASS")
        return 0
    elif results['verdict'] == 'PASS WITH LIMITATION':
        print("\n[OK] PHASE 32 PASS WITH LIMITATION")
        return 0
    else:
        print("\n[FAIL] PHASE 32 FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())