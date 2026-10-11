#!/usr/bin/env python3
"""
Phase 11.3 — Error Code Forensic Audit Tool.
Searches the complete repository and runtime logs for 0x error codes and
other error patterns, classifies them, and correlates with pipeline stages.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger(__name__)


@dataclass
class ErrorCodeFinding:
    """Single error code occurrence with context."""
    file_path: str
    line_number: int
    code_hex: str
    code_decimal: int
    context_line: str
    surrounding_lines: List[str]
    classification: str  # ERROR_CODE, STATUS_CODE, MEMORY_ADDRESS, CONFIG_VALUE, IDENTIFIER, NORMAL_CONSTANT, UNKNOWN
    source_subsystem: str  # Windows HRESULT, NTSTATUS, FFmpeg AVERROR, CUDA, NVENC, NVDEC, etc.
    is_runtime_log: bool = False
    camera_id: Optional[str] = None
    stage: Optional[str] = None


@dataclass
class ErrorCodeCorrelation:
    """Correlated error code across multiple occurrences."""
    code_hex: str
    code_decimal: int
    total_occurrences: int
    source_files: List[str]
    runtime_logs: List[str]
    classification: str
    source_subsystem: str
    first_seen: str
    last_seen: str
    status: str  # RESOLVED, ACTIVE, INTERMITTENT, PRE_EXISTING, NEW, UNKNOWN
    cameras_affected: Set[str] = field(default_factory=set)
    stages_affected: Set[str] = field(default_factory=set)
    triggers: List[str] = field(default_factory=list)
    recoveries: List[str] = field(default_factory=list)


class ErrorCodeAuditor:
    """
    Comprehensive error code forensic auditor.
    
    Searches for:
    - 0x hexadecimal patterns (0xC..., 0x8..., 0xD..., etc.)
    - Named error constants (CUDA_ERROR_*, NV_ENC_ERR_*, AVERROR_*, HRESULT_*, etc.)
    - Common error keywords (ERROR, FAILED, TIMEOUT, ACCESS_VIOLATION, etc.)
    
    Classifies each occurrence and correlates across the codebase and logs.
    """
    
    # Known error code patterns by subsystem
    SUBSYSTEM_PATTERNS = {
        "Windows HRESULT": [
            r"0x8[0-9A-Fa-f]{7}",  # HRESULT error range
            r"HRESULT",
            r"E_",
            r"S_",
            r"S_OK",
            r"E_FAIL",
            r"E_INVALIDARG",
            r"E_OUTOFMEMORY",
            r"E_POINTER",
            r"E_NOTIMPL",
        ],
        "Windows NTSTATUS": [
            r"0xC[0-9A-Fa-f]{7}",  # NTSTATUS error range
            r"STATUS_",
            r"NTSTATUS",
        ],
        "FFmpeg/PyAV": [
            r"AVERROR",
            r"AVERROR_EOF",
            r"AVERROR_EAGAIN",
            r"AVERROR_ENOMEM",
            r"AVERROR_EINVAL",
            r"AVERROR_EIO",
            r"Errno 129",
            r"Error number -129",
            r"EAGAIN",
        ],
        "CUDA": [
            r"CUDA_ERROR",
            r"cudaError",
            r"CUresult",
            r"cudaSuccess",
            r"cudaErrorInvalidValue",
            r"cudaErrorOutOfMemory",
            r"cudaErrorNotReady",
            r"cudaErrorIllegalAddress",
            r"cudaErrorLaunchFailure",
        ],
        "NVENC": [
            r"NV_ENC_ERR_",
            r"NV_ENC_SUCCESS",
            r"NV_ENC_ERR_INVALID_PARAM",
            r"NV_ENC_ERR_OUT_OF_MEMORY",
            r"NV_ENC_ERR_ENCODER_BUSY",
            r"NV_ENC_ERR_UNSUPPORTED_PARAM",
            r"NV_ENC_ERR_INVALID_PTR",
            r"NV_ENC_ERR_ENCODER_NOT_INITIALIZED",
        ],
        "NVDEC": [
            r"NV_DEC_ERR_",
            r"NV_DEC_SUCCESS",
            r"cuvidError",
        ],
        "DirectX/DXGI": [
            r"DXGI_ERROR_",
            r"D3D11_ERROR_",
            r"D3D12_ERROR_",
        ],
        "MediaMTX": [
            r"mediamtx",
            r"MediaMTX",
        ],
        "Python/PyAV": [
            r"PyAV",
            r"av\.error",
            r"FFmpegError",
        ],
        "OS/Network": [
            r"WinError",
            r"WSAGetLastError",
            r"GetLastError",
            r"errno",
            r"EAGAIN",
            r"EWOULDBLOCK",
            r"ECONNREFUSED",
            r"ETIMEDOUT",
        ],
    }
    
    # Classification patterns
    CLASSIFICATION_PATTERNS = {
        "ERROR_CODE": [
            r"0x[C8][0-9A-Fa-f]{7}",  # HRESULT/NTSTATUS error range
            r"ERROR",
            r"FAILED",
            r"ERR_",
            r"CUDA_ERROR",
            r"NV_ENC_ERR",
            r"AVERROR",
        ],
        "STATUS_CODE": [
            r"STATUS_",
            r"NTSTATUS",
            r"HRESULT",
        ],
        "MEMORY_ADDRESS": [
            r"0x[0-9A-Fa-f]{12,}",  # Long hex addresses
        ],
        "CONFIG_VALUE": [
            r"0x[0-9A-Fa-f]{1,8}\s*[=:]",
            r"=\s*0x[0-9A-Fa-f]{1,8}",
        ],
        "IDENTIFIER": [
            r"0x[0-9A-Fa-f]{4,8}\b",  # Medium hex identifiers
        ],
        "NORMAL_CONSTANT": [
            r"0x[0-9A-Fa-f]{1,4}\b",  # Small hex constants
            r"0x[0-9A-Fa-f]{8}\b",    # 32-bit constants
        ],
    }
    
    def __init__(self, repo_root: Path = None, log_dirs: List[Path] = None):
        self.repo_root = repo_root or REPO_ROOT
        self.log_dirs = log_dirs or [
            self.repo_root / "logs",
            self.repo_root / "artifacts",
        ]
        self.findings: List[ErrorCodeFinding] = []
        self.correlations: Dict[str, ErrorCodeCorrelation] = {}
        
    def audit_repository(self) -> List[ErrorCodeFinding]:
        """Search source code for error code patterns."""
        logger.info(f"[AUDIT] Scanning repository: {self.repo_root}")
        
        # Hex patterns to search
        hex_patterns = [
            r"0x[C8D][0-9A-Fa-f]{7}",  # Common error code ranges
            r"0x[0-9A-Fa-f]{8}",        # 32-bit hex
            r"0x[0-9A-Fa-f]{4,}",       # 16+ bit hex
        ]
        
        # Keyword patterns
        keyword_patterns = [
            r"CUDA_ERROR_\w+",
            r"NV_ENC_ERR_\w+",
            r"NV_DEC_ERR_\w+",
            r"AVERROR_\w+",
            r"HRESULT_\w+",
            r"STATUS_\w+",
            r"WinError\s*\(",
            r"GetLastError\s*\(",
            r"EAGAIN",
            r"ACCESS_VIOLATION",
            r"TIMEOUT",
            r"\bERROR\b",
            r"\bFAILED\b",
            r"\bFAILURE\b",
        ]
        
        all_patterns = hex_patterns + keyword_patterns
        
        for root, dirs, files in os.walk(self.repo_root):
            # Skip virtual environments and cache directories
            if any(skip in root for skip in [".venv", "__pycache__", ".git", "Video_Codec_SDK"]):
                continue
                
            for file in files:
                if not file.endswith((".py", ".cpp", ".h", ".hpp", ".c", ".cu", ".json", ".yml", ".yaml", ".md")):
                    continue
                    
                filepath = Path(root) / file
                self._scan_file(filepath, all_patterns)
        
        logger.info(f"[AUDIT] Found {len(self.findings)} occurrences in repository")
        return self.findings
    
    def audit_runtime_logs(self) -> List[ErrorCodeFinding]:
        """Search runtime logs for error codes."""
        logger.info(f"[AUDIT] Scanning runtime logs in: {self.log_dirs}")
        
        patterns = [
            r"0x[C8D][0-9A-Fa-f]{7}",
            r"0x[0-9A-Fa-f]{8}",
            r"CUDA_ERROR_\w+",
            r"NV_ENC_ERR_\w+",
            r"NV_DEC_ERR_\w+",
            r"AVERROR_\w+",
            r"Errno 129",
            r"Error number -129",
            r"EAGAIN",
            r"TIMEOUT",
            r"ACCESS_VIOLATION",
            r"\bERROR\b",
            r"\bFAILED\b",
        ]
        
        for log_dir in self.log_dirs:
            if not log_dir.exists():
                continue
            for root, dirs, files in os.walk(log_dir):
                for file in files:
                    if file.endswith((".log", ".txt", ".out", ".err")):
                        filepath = Path(root) / file
                        self._scan_file(filepath, patterns, is_runtime_log=True)
        
        logger.info(f"[AUDIT] Found {len([f for f in self.findings if f.is_runtime_log])} occurrences in runtime logs")
        return [f for f in self.findings if f.is_runtime_log]
    
    def _scan_file(self, filepath: Path, patterns: List[str], is_runtime_log: bool = False) -> None:
        """Scan a single file for patterns."""
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            
            for i, line in enumerate(lines):
                for pattern in patterns:
                    matches = list(re.finditer(pattern, line, re.IGNORECASE))
                    for match in matches:
                        code_hex = match.group(0)
                        # Try to extract hex code
                        hex_match = re.search(r"0x[0-9A-Fa-f]+", code_hex)
                        if hex_match:
                            code_hex = hex_match.group(0)
                            try:
                                code_decimal = int(code_hex, 16)
                            except ValueError:
                                code_decimal = 0
                        else:
                            # Keyword match - assign pseudo-code
                            code_hex = f"KEYWORD_{code_hex.upper()}"
                            code_decimal = hash(code_hex) & 0xFFFFFFFF
                        
                        # Get surrounding context
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        surrounding = lines[start:end]
                        
                        finding = ErrorCodeFinding(
                            file_path=str(filepath.relative_to(self.repo_root)),
                            line_number=i + 1,
                            code_hex=code_hex,
                            code_decimal=code_decimal,
                            context_line=line.strip(),
                            surrounding_lines=surrounding,
                            classification=self._classify(code_hex, code_decimal, line),
                            source_subsystem=self._identify_subsystem(code_hex, line, filepath),
                            is_runtime_log=is_runtime_log,
                        )
                        
                        # Try to extract camera_id and stage from context
                        finding.camera_id = self._extract_camera_id(line, surrounding)
                        finding.stage = self._extract_stage(line, surrounding, filepath)
                        
                        self.findings.append(finding)
                        
        except Exception as e:
            logger.debug(f"Failed to scan {filepath}: {e}")
    
    def _classify(self, code_hex: str, code_decimal: int, context: str) -> str:
        """Classify the hex code or keyword."""
        context_lower = context.lower()
        
        # Check each classification
        for classification, patterns in self.CLASSIFICATION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, code_hex, re.IGNORECASE) or re.search(pattern, context, re.IGNORECASE):
                    return classification
        
        # Special handling for known error code ranges
        if code_hex.startswith("0x"):
            if code_decimal & 0x80000000:  # High bit = error in HRESULT
                return "ERROR_CODE"
            if 0xC0000000 <= code_decimal <= 0xFFFFFFFF:
                return "ERROR_CODE"  # NTSTATUS
            if code_decimal <= 0xFFFF:
                return "NORMAL_CONSTANT"
        
        if "ERROR" in context.upper() or "FAIL" in context.upper():
            return "ERROR_CODE"
        
        return "UNKNOWN"
    
    def _identify_subsystem(self, code_hex: str, context: str, filepath: Path) -> str:
        """Identify which subsystem the error code belongs to."""
        context_lower = context.lower()
        filepath_str = str(filepath).lower()
        
        for subsystem, patterns in self.SUBSYSTEM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, context, re.IGNORECASE) or re.search(pattern, filepath_str, re.IGNORECASE):
                    return subsystem
        
        # Check file path for clues
        if "nvenc" in filepath_str or "encoder" in filepath_str:
            return "NVENC"
        if "nvdec" in filepath_str or "decoder" in filepath_str:
            return "NVDEC"
        if "cuda" in filepath_str:
            return "CUDA"
        if "pyav" in filepath_str or "ffmpeg" in filepath_str:
            return "FFmpeg/PyAV"
        if "mediamtx" in filepath_str:
            return "MediaMTX"
        
        return "UNKNOWN"
    
    def _extract_camera_id(self, line: str, surrounding: List[str]) -> Optional[str]:
        """Extract camera ID from context."""
        all_text = " ".join([line] + surrounding)
        for cam in ["CAM1", "CAM2", "Cam1", "Cam2", "cam1", "cam2"]:
            if cam in all_text:
                return cam.upper()
        return None
    
    def _extract_stage(self, line: str, surrounding: List[str], filepath: Path) -> Optional[str]:
        """Extract pipeline stage from context."""
        all_text = " ".join([line] + surrounding).lower()
        filepath_str = str(filepath).lower()
        
        stages = {
            "input": ["input", "rtsp", "source", "ingestion", "capture"],
            "decode": ["decode", "nvdec", "demux", "avframe"],
            "preprocess": ["preprocess", "preprocess", "letterbox", "resize", "normalize"],
            "ai": ["inference", "detect", "detector", "model", "onnx", "tensorrt"],
            "annotation": ["annotate", "annotation", "overlay", "render"],
            "contract": ["contract", "frame_contract", "gpu_frame_contract"],
            "encode": ["encode", "nvenc", "encoder", "packet"],
            "publish": ["publish", "publisher", "bridge", "rtsp", "mediamtx"],
            "output": ["output", "hls", "stream", "consumer"],
        }
        
        for stage, keywords in stages.items():
            if any(kw in all_text or kw in filepath_str for kw in keywords):
                return stage
        
        return None
    
    def correlate_findings(self) -> Dict[str, ErrorCodeCorrelation]:
        """Correlate findings by error code."""
        correlations: Dict[str, ErrorCodeCorrelation] = {}
        
        for finding in self.findings:
            key = finding.code_hex
            
            if key not in correlations:
                correlations[key] = ErrorCodeCorrelation(
                    code_hex=finding.code_hex,
                    code_decimal=finding.code_decimal,
                    total_occurrences=0,
                    source_files=[],
                    runtime_logs=[],
                    classification=finding.classification,
                    source_subsystem=finding.source_subsystem,
                    first_seen="",
                    last_seen="",
                    status="UNKNOWN",
                )
            
            corr = correlations[key]
            corr.total_occurrences += 1
            
            if finding.file_path not in corr.source_files:
                corr.source_files.append(finding.file_path)
            
            if finding.is_runtime_log and finding.file_path not in corr.runtime_logs:
                corr.runtime_logs.append(finding.file_path)
            
            if finding.camera_id:
                corr.cameras_affected.add(finding.camera_id)
            if finding.stage:
                corr.stages_affected.add(finding.stage)
            
            # Extract trigger and recovery from context
            trigger = self._extract_trigger(finding.context_line, finding.surrounding_lines)
            if trigger and trigger not in corr.triggers:
                corr.triggers.append(trigger)
            
            recovery = self._extract_recovery(finding.context_line, finding.surrounding_lines)
            if recovery and recovery not in corr.recoveries:
                corr.recoveries.append(recovery)
        
        # Determine status for each correlation
        for corr in correlations.values():
            corr.status = self._determine_status(corr)
        
        self.correlations = correlations
        logger.info(f"[AUDIT] Correlated into {len(correlations)} unique error codes")
        return correlations
    
    def _extract_trigger(self, line: str, surrounding: List[str]) -> Optional[str]:
        """Extract trigger description from context."""
        all_text = " ".join([line] + surrounding).lower()
        triggers = [
            "connect", "connection", "timeout", "retry", "reconnect",
            "open", "initialize", "create", "alloc", "memory",
            "decode", "encode", "frame", "packet", "stream",
        ]
        for trigger in triggers:
            if trigger in all_text:
                return trigger
        return None
    
    def _extract_recovery(self, line: str, surrounding: List[str]) -> Optional[str]:
        """Extract recovery action from context."""
        all_text = " ".join([line] + surrounding).lower()
        recoveries = [
            "retry", "reconnect", "restart", "reset", "recover",
            "fallback", "continue", "skip", "ignore", "handle",
        ]
        for recovery in recoveries:
            if recovery in all_text:
                return recovery
        return None
    
    def _determine_status(self, corr: ErrorCodeCorrelation) -> str:
        """Determine error code status."""
        if corr.total_occurrences == 0:
            return "UNKNOWN"
        
        # If found in runtime logs recently, it's ACTIVE
        if corr.runtime_logs:
            return "ACTIVE"
        
        # If only in source code with handling, likely RESOLVED
        if corr.source_files and not corr.runtime_logs:
            # Check if there's error handling code
            handled = any("try" in f or "except" in f or "catch" in f 
                         for f in corr.source_files)
            if handled:
                return "RESOLVED"
            return "PRE_EXISTING"
        
        return "UNKNOWN"
    
    def generate_report(self, output_path: Path) -> Dict:
        """Generate comprehensive error code audit report."""
        self.audit_repository()
        self.audit_runtime_logs()
        self.correlate_findings()
        
        report = {
            "audit_metadata": {
                "timestamp": self._get_timestamp(),
                "repo_root": str(self.repo_root),
                "log_dirs": [str(d) for d in self.log_dirs],
                "total_findings": len(self.findings),
                "unique_codes": len(self.correlations),
            },
            "findings_by_classification": self._group_by_classification(),
            "findings_by_subsystem": self._group_by_subsystem(),
            "correlations": {
                code: {
                    "code_hex": corr.code_hex,
                    "code_decimal": corr.code_decimal,
                    "total_occurrences": corr.total_occurrences,
                    "classification": corr.classification,
                    "source_subsystem": corr.source_subsystem,
                    "status": corr.status,
                    "source_files": corr.source_files[:20],
                    "runtime_logs": corr.runtime_logs[:10],
                    "cameras_affected": list(corr.cameras_affected),
                    "stages_affected": list(corr.stages_affected),
                    "triggers": corr.triggers[:10],
                    "recoveries": corr.recoveries[:10],
                }
                for code, corr in self.correlations.items()
            },
            "critical_codes": self._identify_critical_codes(),
            "pyav_ffmpeg_errors": self._extract_pyav_ffmpeg_errors(),
        }
        
        import json
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"[AUDIT] Error code audit report saved to {output_path}")
        return report
    
    def _get_timestamp(self) -> str:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    def _group_by_classification(self) -> Dict[str, int]:
        groups = {}
        for f in self.findings:
            groups[f.classification] = groups.get(f.classification, 0) + 1
        return groups
    
    def _group_by_subsystem(self) -> Dict[str, int]:
        groups = {}
        for f in self.findings:
            groups[f.source_subsystem] = groups.get(f.source_subsystem, 0) + 1
        return groups
    
    def _identify_critical_codes(self) -> List[Dict]:
        """Identify critical error codes that need attention."""
        critical = []
        for code, corr in self.correlations.items():
            if corr.status in ("ACTIVE", "INTERMITTENT", "UNKNOWN"):
                if corr.classification == "ERROR_CODE":
                    if corr.source_subsystem in ("CUDA", "NVENC", "NVDEC", "FFmpeg/PyAV"):
                        critical.append({
                            "code_hex": code,
                            "subsystem": corr.source_subsystem,
                            "status": corr.status,
                            "occurrences": corr.total_occurrences,
                            "cameras": list(corr.cameras_affected),
                            "stages": list(corr.stages_affected),
                            "triggers": corr.triggers[:5],
                        })
        return critical
    
    def _extract_pyav_ffmpeg_errors(self) -> List[Dict]:
        """Extract PyAV/FFmpeg specific errors."""
        errors = []
        for finding in self.findings:
            if finding.source_subsystem == "FFmpeg/PyAV" or "pyav" in finding.file_path.lower() or "ffmpeg" in finding.file_path.lower():
                if finding.classification == "ERROR_CODE" or "ERROR" in finding.context_line.upper():
                    errors.append({
                        "file": finding.file_path,
                        "line": finding.line_number,
                        "code": finding.code_hex,
                        "context": finding.context_line,
                        "stage": finding.stage,
                        "camera": finding.camera_id,
                    })
        return errors


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 11.3 Error Code Forensic Audit")
    parser.add_argument("--repo-root", type=Path, help="Repository root path")
    parser.add_argument("--log-dirs", nargs="+", type=Path, help="Log directories to scan")
    parser.add_argument("--output", type=Path, help="Output report path")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    auditor = ErrorCodeAuditor(
        repo_root=args.repo_root,
        log_dirs=args.log_dirs,
    )
    
    output_path = args.output or REPO_ROOT / "artifacts" / "phase11" / "forensics" / f"error_code_audit_{time.strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    report = auditor.generate_report(output_path)
    
    # Print summary
    print("\n" + "=" * 80)
    print("PHASE 11.3 ERROR CODE FORENSIC AUDIT SUMMARY")
    print("=" * 80)
    
    print(f"\nTotal Findings: {report['audit_metadata']['total_findings']}")
    print(f"Unique Error Codes: {report['audit_metadata']['unique_codes']}")
    
    print("\nBy Classification:")
    for cls, count in sorted(report['findings_by_classification'].items(), key=lambda x: -x[1]):
        print(f"  {cls:20s}: {count}")
    
    print("\nBy Subsystem:")
    for subsys, count in sorted(report['findings_by_subsystem'].items(), key=lambda x: -x[1]):
        print(f"  {subsys:20s}: {count}")
    
    print(f"\nCritical Codes Requiring Attention: {len(report['critical_codes'])}")
    for crit in report['critical_codes'][:10]:
        print(f"  {crit['code_hex']:12s} | {crit['subsystem']:15s} | {crit['status']:12s} | Occ: {crit['occurrences']:3d} | Cams: {crit['cameras']} | Stages: {crit['stages']}")
    
    print(f"\nPyAV/FFmpeg Errors: {len(report['pyav_ffmpeg_errors'])}")
    for err in report['pyav_ffmpeg_errors'][:10]:
        print(f"  {err['file']:50s}:{err['line']:4d} | {err['code']:12s} | Stage: {err['stage'] or 'N/A':12s} | Cam: {err['camera'] or 'N/A'}")
    
    print("\n" + "=" * 80)
    print(f"Full report saved to: {output_path}")
    print("=" * 80)


if __name__ == "__main__":
    import time
    main()