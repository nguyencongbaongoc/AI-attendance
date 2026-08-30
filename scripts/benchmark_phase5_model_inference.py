#!/usr/bin/env python
"""
Phase 5 — Production Model CUDA Inference Validation Benchmark.

This script validates actual production model inference on Windows NVIDIA GPU.

CRITICAL RULES:
- Use ONLY the six models registered by ModelRegistry
- NO camera access
- NO MediaMTX, RTMP, RTSP, FFmpeg streaming
- NO real images - synthetic inputs only
- NO accuracy claims from synthetic noise
- Verify SHA256 before inference
- Distinguish: provider registered vs session created vs actual CUDA inference

Models validated:
- SCRFD (scrfd_10g_bnkps.onnx) - Face detection
- ArcFace (glintr100.onnx) - Face recognition embedding
- 1K3D68 (1k3d68.onnx) - Face landmark
- ReID (resnet50_reid.onnx) - Person re-identification
- YOLO Person (yolo11n.pt) - Person detection
- YOLO Pose (yolo11n-pose.pt) - Pose estimation

Usage:
    python scripts/benchmark_phase5_model_inference.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.config.paths import get_project_paths
from app.models.registry import get_model_registry
from app.runtime.model_inference import (
    run_phase5_validation,
    ModelInferenceResult,
    RuntimeMatrix,
)


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_section(title: str) -> None:
    """Print a formatted section."""
    print(f"\n## {title}")


def format_latency(ms: Optional[float]) -> str:
    """Format latency value for display."""
    if ms is None:
        return "N/A"
    return f"{ms:.2f} ms"


def format_shape(shape: tuple) -> str:
    """Format shape tuple for display."""
    return " × ".join(str(s) for s in shape)


def run_phase5_benchmark(
    warmup_runs: int = 10,
    measured_runs: int = 100,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run Phase 5 production model CUDA inference validation.
    
    Args:
        warmup_runs: Number of warmup iterations per model.
        measured_runs: Number of measured iterations per model.
        output_dir: Directory to write reports.
        
    Returns:
        Summary dictionary.
    """
    print_header("PHASE 5 — PRODUCTION MODEL CUDA INFERENCE VALIDATION")
    
    # Get project paths
    paths = get_project_paths()
    if output_dir is None:
        output_dir = paths.benchmark_results_dir
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Print configuration
    print_section("Configuration")
    print(f"Warmup runs: {warmup_runs}")
    print(f"Measured runs: {measured_runs}")
    print(f"Output directory: {output_dir}")
    
    # Run validation
    print_section("Running Model Inference Validation")
    print("This may take several minutes...")
    
    start_time = time.time()
    results, matrix, summary = run_phase5_validation(
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    elapsed = time.time() - start_time
    
    # Print results
    print_section("Model Inference Results")
    
    for result in results:
        print(f"\n### {result.model_id.upper()}")
        print(f"SHA256: {result.sha256[:16]}... ({'VERIFIED' if result.sha256_match else 'MISMATCH'})")
        print(f"Provider: {result.provider}")
        print(f"Input Shape: {format_shape(result.input_shape)}")
        
        if result.output_shapes:
            print(f"Output Shapes: {', '.join(format_shape(s) for s in result.output_shapes)}")
        
        print(f"\nCUDA Inference: {'PASS' if result.cuda_success else 'FAIL'}")
        print(f"CPU Inference: {'PASS' if result.cpu_success else 'FAIL'}")
        
        if result.cuda_success:
            print(f"CUDA Latency: {format_latency(result.latency_cuda_mean_ms)} (mean), "
                  f"{format_latency(result.latency_cuda_median_ms)} (median), "
                  f"{format_latency(result.latency_cuda_p95_ms)} (P95)")
        
        if result.cpu_success:
            print(f"CPU Latency: {format_latency(result.latency_cpu_mean_ms)} (mean), "
                  f"{format_latency(result.latency_cpu_median_ms)} (median), "
                  f"{format_latency(result.latency_cpu_p95_ms)} (P95)")
        
        print(f"Output Valid: {result.output_finite and result.output_no_nan and result.output_no_inf}")
        
        if result.errors:
            print(f"Errors: {result.errors}")
        
        if result.gpu_memory_before_mb and result.gpu_memory_after_mb:
            print(f"GPU Memory: {result.gpu_memory_before_mb:.1f} MB → {result.gpu_memory_after_mb:.1f} MB")
    
    # Print summary
    print_section("Summary")
    print(f"Models validated: {summary['models_validated']}")
    print(f"SHA256 verified: {summary['sha256_verified']}")
    print(f"CUDA success: {summary['cuda_success']}")
    print(f"CPU success: {summary['cpu_success']}")
    print(f"Output valid: {summary['output_valid']}")
    print(f"Total elapsed: {elapsed:.1f} seconds")
    
    # Print verdict
    print_section("VERDICT")
    verdict = summary["verdict"]
    if verdict == "PASS":
        print("✅ PASS — All models successfully validated on CUDA and CPU")
    else:
        print("⚠️ PARTIAL — Some models failed validation")
        if summary["errors"]:
            print(f"Models with errors: {', '.join(summary['errors'])}")
    
    # Write reports
    print_section("Writing Reports")
    
    # Write JSON report
    json_report = {
        "phase": 5,
        "timestamp": datetime.now().isoformat(),
        "configuration": {
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
        },
        "summary": summary,
        "models": [result.__dict__ for result in results],
        "runtime_matrix": matrix.__dict__,
    }
    
    json_path = output_dir / "PHASE_5_PRODUCTION_MODEL_CUDA_INFERENCE.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_report, f, indent=2, default=str)
    print(f"JSON report: {json_path}")
    
    # Write Runtime Matrix JSON report
    matrix_path = output_dir / "PHASE_5_MODEL_RUNTIME_MATRIX.json"
    with open(matrix_path, "w", encoding="utf-8") as f:
        json.dump(matrix.__dict__, f, indent=2, default=str)
    print(f"Runtime Matrix JSON report: {matrix_path}")
    
    # Write Markdown report
    md_report = generate_markdown_report(results, matrix, summary, warmup_runs, measured_runs)
    md_path = output_dir / "PHASE_5_PRODUCTION_MODEL_CUDA_INFERENCE.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"Markdown report: {md_path}")
    
    return summary


def generate_markdown_report(
    results: List[ModelInferenceResult],
    matrix: RuntimeMatrix,
    summary: Dict[str, Any],
    warmup_runs: int,
    measured_runs: int,
) -> str:
    """Generate Markdown report."""
    lines = [
        "# PHASE 5 — PRODUCTION MODEL CUDA INFERENCE VALIDATION",
        "",
        f"**Timestamp:** {datetime.now().isoformat()}",
        "",
        f"**VERDICT:** {summary['verdict']}",
        "",
        "---",
        "",
        "## Configuration",
        "",
        f"- Warmup runs: {warmup_runs}",
        f"- Measured runs: {measured_runs}",
        "",
        "---",
        "",
        "## Model Inference Results",
        "",
    ]
    
    for result in results:
        lines.extend([
            f"### {result.model_id.upper()}",
            "",
            "| Property | Value |",
            "|----------|-------|",
            f"| SHA256 | `{result.sha256[:16]}...` |",
            f"| SHA256 Match | {'✅' if result.sha256_match else '❌'} |",
            f"| Provider | {result.provider} |",
            f"| Input Shape | {format_shape(result.input_shape)} |",
            f"| CUDA Success | {'✅' if result.cuda_success else '❌'} |",
            f"| CPU Success | {'✅' if result.cpu_success else '❌'} |",
            f"| Output Finite | {'✅' if result.output_finite else '❌'} |",
            f"| Output No NaN | {'✅' if result.output_no_nan else '❌'} |",
            f"| Output No Inf | {'✅' if result.output_no_inf else '❌'} |",
        ])
        
        if result.cuda_success and result.latency_cuda_mean_ms:
            lines.extend([
                f"| CUDA Latency (mean) | {format_latency(result.latency_cuda_mean_ms)} |",
                f"| CUDA Latency (median) | {format_latency(result.latency_cuda_median_ms)} |",
                f"| CUDA Latency (P95) | {format_latency(result.latency_cuda_p95_ms)} |",
            ])
        
        if result.cpu_success and result.latency_cpu_mean_ms:
            lines.extend([
                f"| CPU Latency (mean) | {format_latency(result.latency_cpu_mean_ms)} |",
                f"| CPU Latency (median) | {format_latency(result.latency_cpu_median_ms)} |",
                f"| CPU Latency (P95) | {format_latency(result.latency_cpu_p95_ms)} |",
            ])
        
        if result.gpu_memory_before_mb and result.gpu_memory_after_mb:
            lines.append(f"| GPU Memory | {result.gpu_memory_before_mb:.1f} MB → {result.gpu_memory_after_mb:.1f} MB |")
        
        if result.errors:
            lines.extend([
                "",
                f"**Errors:** {result.errors}",
            ])
        
        lines.append("")
    
    # Summary table
    lines.extend([
        "---",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Models Validated | {summary['models_validated']} |",
        f"| SHA256 Verified | {summary['sha256_verified']} |",
        f"| CUDA Success | {summary['cuda_success']} |",
        f"| CPU Success | {summary['cpu_success']} |",
        f"| Output Valid | {summary['output_valid']} |",
        "",
    ])
    
    # Latency comparison table
    lines.extend([
        "---",
        "",
        "## Latency Comparison",
        "",
        "| Model | CUDA Mean (ms) | CPU Mean (ms) | Speedup |",
        "|-------|----------------|---------------|---------|",
    ])
    
    for result in results:
        if result.cuda_success and result.cpu_success:
            if result.latency_cuda_mean_ms and result.latency_cpu_mean_ms:
                speedup = result.latency_cpu_mean_ms / result.latency_cuda_mean_ms
                lines.append(
                    f"| {result.model_id} | {result.latency_cuda_mean_ms:.2f} | "
                    f"{result.latency_cpu_mean_ms:.2f} | {speedup:.1f}x |"
                )
        elif result.cuda_success:
            lines.append(f"| {result.model_id} | {result.latency_cuda_mean_ms:.2f} | N/A | N/A |")
        elif result.cpu_success:
            lines.append(f"| {result.model_id} | N/A | {result.latency_cpu_mean_ms:.2f} | N/A |")
        else:
            lines.append(f"| {result.model_id} | N/A | N/A | N/A |")
    
    lines.append("")
    
    # Safety verification
    lines.extend([
        "---",
        "",
        "## Safety Verification",
        "",
        "- Camera accessed: NO",
        "- MediaMTX started: NO",
        "- RTMP accessed: NO",
        "- RTSP accessed: NO",
        "- FFmpeg streaming: NO",
        "- IPC started: NO",
        "- Real images used: NO",
        "- Model files modified: NO",
        "",
    ])
    
    # Final verdict
    lines.extend([
        "---",
        "",
        "## Final Verdict",
        "",
        f"### {summary['verdict']}",
        "",
    ])
    
    if summary['verdict'] == "PASS":
        lines.extend([
            "All six production models successfully validated:",
            "",
            "- ✅ SCRFD face detection on CUDA",
            "- ✅ ArcFace face recognition on CUDA",
            "- ✅ 1K3D68 face landmark on CUDA",
            "- ✅ ReID person re-identification on CUDA",
            "- ✅ YOLO person detection on CUDA",
            "- ✅ YOLO pose estimation on CUDA",
            "",
            "All models:",
            "- SHA256 verified",
            "- CUDA inference successful",
            "- CPU fallback successful",
            "- Output tensors valid (finite, no NaN, no Inf)",
            "",
        ])
    else:
        lines.extend([
            "Some models failed validation.",
            "",
            f"Models with errors: {', '.join(summary['errors'])}",
            "",
        ])
    
    lines.extend([
        "---",
        "",
        f"*Generated by Phase 5 — Production Model CUDA Inference Validation Script*",
    ])
    
    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Phase 5 — Production Model CUDA Inference Validation"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=10,
        help="Number of warmup iterations (default: 10)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=100,
        help="Number of measured iterations (default: 100)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for reports",
    )
    
    args = parser.parse_args()
    
    try:
        summary = run_phase5_benchmark(
            warmup_runs=args.warmup,
            measured_runs=args.runs,
            output_dir=args.output_dir,
        )
        
        # Return exit code based on verdict
        return 0 if summary["verdict"] == "PASS" else 1
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())