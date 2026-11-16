"""
Cross-Layer Graphify Knowledge & Variable Contract Audit Tool (Phase 1 / Gate 1).

Performs AST + Regex Cross-Layer Graph Analysis spanning:
- pipeline_engine/ (core, inference, tracking, ingestion, attendance, vision, memory, integration, config)
- app/ (api, streaming, storage, db, schemas, middleware, config, attendance)
- frontend/index.html (DOM IDs, WebSocket URLs, CanvasOverlayRenderer lifecycle, payload keys)
- mediamtx/mediamtx.yml (stream paths)
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _iter_python_files(roots: List[Path]) -> List[Path]:
    files: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


def _resolve_internal_module(module_name: str) -> bool:
    """Verify whether an internal app.* or pipeline_engine.* module exists on disk."""
    parts = module_name.split(".")
    candidate_file = REPO_ROOT.joinpath(*parts).with_suffix(".py")
    candidate_pkg = REPO_ROOT.joinpath(*parts, "__init__.py")
    return candidate_file.exists() or candidate_pkg.exists()


def _check_python_ast(py_files: List[Path]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, ast.Module]]:
    syntax_errors: List[Dict[str, Any]] = []
    broken_imports: List[Dict[str, Any]] = []
    parsed: Dict[str, ast.Module] = {}

    for p in py_files:
        rel = p.relative_to(REPO_ROOT).as_posix()
        try:
            src = p.read_text(encoding="utf-8-sig")
            tree = ast.parse(src, filename=str(p))
            parsed[rel] = tree
        except SyntaxError as e:
            syntax_errors.append({"file": rel, "line": e.lineno, "error": str(e)})
            continue

        # Check internal imports (module-level and try-exempt optional guards respected)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("app.", "pipeline_engine.")):
                        if not _resolve_internal_module(alias.name):
                            broken_imports.append({
                                "file": rel,
                                "line": node.lineno,
                                "import": alias.name,
                            })
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(("app.", "pipeline_engine.")):
                    mod_ok = _resolve_internal_module(node.module)
                    if not mod_ok:
                        # Handle from app.pkg import submod where submod is a module inside app/pkg/
                        all_sub_ok = bool(node.names) and all(
                            _resolve_internal_module(f"{node.module}.{a.name}") for a in node.names
                        )
                        if not all_sub_ok:
                            broken_imports.append({
                                "file": rel,
                                "line": node.lineno,
                                "import": node.module,
                            })

    return syntax_errors, broken_imports, parsed


def _check_cross_layer_links(parsed: Dict[str, ast.Module]) -> List[Dict[str, Any]]:
    broken_links: List[Dict[str, Any]] = []

    # 1. Verify FastAPI routes & WebSocket paths exist
    broadcaster_path = REPO_ROOT / "app" / "streaming" / "metadata_broadcaster.py"
    broadcaster_src = broadcaster_path.read_text(encoding="utf-8") if broadcaster_path.exists() else ""
    if '@router.post("/metadata/ingest")' not in broadcaster_src:
        broken_links.append({"edge": "FastAPI -> /api/v1/stream/metadata/ingest", "issue": "Missing ingest route"})
    if '@router.websocket("/metadata/{camera_id}")' not in broadcaster_src:
        broken_links.append({"edge": "FastAPI -> /api/v1/stream/metadata/{camera_id}", "issue": "Missing WS route"})

    cam_mgr_path = REPO_ROOT / "pipeline_engine" / "ingestion" / "camera_manager.py"
    cam_mgr_src = cam_mgr_path.read_text(encoding="utf-8") if cam_mgr_path.exists() else ""
    if "/api/v1/stream/metadata/ingest" not in cam_mgr_src:
        broken_links.append({"edge": "CameraManager -> FastAPI ingest", "issue": "Mismatched ingest URL"})
    if "def _extract_aligned_face(" not in cam_mgr_src:
        broken_links.append({"edge": "CameraManager._inference_loop -> _extract_aligned_face", "issue": "Missing def _extract_aligned_face method signature"})

    # 2. Verify StageSynchronizer attribute consistency
    sync_path = REPO_ROOT / "pipeline_engine" / "memory" / "synchronization.py"
    sync_src = sync_path.read_text(encoding="utf-8") if sync_path.exists() else ""
    if "self.stage_names =" in sync_src and "self._stage_names" in sync_src:
        if "self._stage_names =" not in sync_src:
            broken_links.append({"edge": "StageSynchronizer.__init__ -> _stage_names", "issue": "_stage_names never initialized"})

    # 3. Verify SCRFDDetector._parse_outputs doesn't use undefined `frame.` or `cx`
    scrfd_tree = parsed.get("pipeline_engine/inference/face_detection.py")
    if scrfd_tree:
        for node in ast.walk(scrfd_tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_parse_outputs":
                arg_names = {a.arg for a in node.args.args}
                load_names = {
                    n.id for n in ast.walk(node)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                }
                for bad in ("frame", "cx", "cy"):
                    if bad in load_names and bad not in arg_names:
                        # Verify not locally assigned
                        assigned = {
                            t.id for n in ast.walk(node)
                            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                            for t in [n]
                        }
                        if bad not in assigned:
                            broken_links.append({
                                "edge": "SCRFDDetector._parse_outputs",
                                "issue": f"Undefined name '{bad}' referenced inside _parse_outputs",
                            })

    # 4. Verify AttendanceStorage SQL column count vs values count in insert & insert_many
    storage_path = REPO_ROOT / "app" / "attendance" / "storage.py"
    storage_src = storage_path.read_text(encoding="utf-8") if storage_path.exists() else ""
    for m in re.finditer(r"INSERT INTO attendance_records\s*\((.*?)\)\s*VALUES\s*\(([^)]+)\)", storage_src, re.S):
        cols_raw = re.sub(r"--[^\n]*", "", m.group(1))
        cols = [c.strip() for c in cols_raw.split(",") if c.strip()]
        placeholders = [p.strip() for p in m.group(2).split(",") if p.strip()]
        if len(cols) != len(placeholders):
            broken_links.append({
                "edge": "AttendanceStorage SQL INSERT",
                "issue": f"Column count ({len(cols)}) != placeholders ({len(placeholders)})",
            })

    # 5. Verify AttendanceStore WAL mode
    att_eng_path = REPO_ROOT / "pipeline_engine" / "attendance" / "attendance_engine.py"
    att_eng_src = att_eng_path.read_text(encoding="utf-8") if att_eng_path.exists() else ""
    if "PRAGMA journal_mode=WAL" not in att_eng_src or "busy_timeout" not in att_eng_src:
        broken_links.append({"edge": "AttendanceStore -> SQLite", "issue": "Missing WAL / busy_timeout configuration"})

    # 6. Verify pipeline.yaml and mediamtx.yml camera paths & crossing lines
    pipeline_yaml = REPO_ROOT / "pipeline_engine" / "config" / "pipeline.yaml"
    mediamtx_yaml = REPO_ROOT / "mediamtx" / "mediamtx.yml"
    if pipeline_yaml.exists() and mediamtx_yaml.exists():
        pdata = yaml.safe_load(pipeline_yaml.read_text(encoding="utf-8")) or {}
        mdata = yaml.safe_load(mediamtx_yaml.read_text(encoding="utf-8")) or {}
        mtx_paths = set((mdata.get("paths") or {}).keys())
        for cam_key, cam_cfg in (pdata.get("cameras") or {}).items():
            if cam_key != cam_key.lower():
                broken_links.append({"edge": f"pipeline.yaml:{cam_key}", "issue": "Camera key is not lowercase"})
            expected_path = f"live/{cam_key.lower()}"
            if expected_path not in mtx_paths:
                broken_links.append({"edge": f"pipeline.yaml:{cam_key} -> mediamtx.yml", "issue": f"Missing path {expected_path}"})
            geom = cam_cfg.get("geometry", {})
            p1, p2 = geom.get("line_start", [0, 0]), geom.get("line_end", [0, 0])
            if p1 == p2:
                broken_links.append({"edge": f"pipeline.yaml:{cam_key}.geometry", "issue": f"Degenerate zero-length line {p1} -> {p2}"})

    # 7. Verify stale backend port 19146 does not remain in worker/integration clients
    for rel in [
        "pipeline_engine/core/worker.py",
        "pipeline_engine/integration/control_client.py",
        "pipeline_engine/integration/event_client.py",
        "pipeline_engine/integration/health_client.py",
    ]:
        fpath = REPO_ROOT / rel
        if fpath.exists() and "19146" in fpath.read_text(encoding="utf-8"):
            broken_links.append({"edge": f"{rel} -> backend", "issue": "Stale default port 19146 instead of 8000"})

    # 8. Verify frontend CanvasOverlayRenderer per-canvas registration & route alignment
    html_path = REPO_ROOT / "frontend" / "index.html"
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    if "window.overlayRenderers[this.canvasId]" not in html:
        broken_links.append({"edge": "frontend -> CanvasOverlayRenderer", "issue": "Not keyed by canvasId (dashboard vs live collision)"})
    if "this._videoPauseHandler = () => this.stop()" in html:
        broken_links.append({"edge": "frontend -> _videoPauseHandler", "issue": "Video pause still destroys overlay renderer"})
    if "/api/v1/stream/metadata/${this.cameraId.toLowerCase()}" not in html:
        broken_links.append({"edge": "frontend -> MetadataWebSocket URL", "issue": "Missing canonical WS URL"})

    return broken_links


def _check_frontend_dom_ids() -> Tuple[List[str], List[str]]:
    html_path = REPO_ROOT / "frontend" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    defined_ids = set(re.findall(r'''\bid=["']([^"']+)["']''', html))

    static_lookups = set(re.findall(r'''getElementById\(["']([^"']+)["']\)''', html))
    orphan_ids = sorted(static_lookups - defined_ids)

    # Expand template lookups across camNum / cam in {1, 2}
    template_lookups = set(re.findall(r'''getElementById\(`([^`]+)`\)''', html))
    for tpl in template_lookups:
        for num in ("1", "2"):
            expanded = (
                tpl.replace("${camNum}", num)
                .replace("${cam === 'cam1' ? '1' : '2'}", num)
            )
            if "${" not in expanded and expanded not in defined_ids:
                orphan_ids.append(f"{tpl} -> {expanded}")

    return sorted(set(orphan_ids)), sorted(defined_ids)


def _check_canonical_variables() -> List[Dict[str, Any]]:
    mismatches: List[Dict[str, Any]] = []

    broadcaster_src = (REPO_ROOT / "app" / "streaming" / "metadata_broadcaster.py").read_text(encoding="utf-8")
    cam_mgr_src = (REPO_ROOT / "pipeline_engine" / "ingestion" / "camera_manager.py").read_text(encoding="utf-8")
    cameras_api_src = (REPO_ROOT / "app" / "api" / "cameras.py").read_text(encoding="utf-8")
    html_src = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    # Canonical fields required across producer -> broadcaster -> consumer
    required_person_keys = ["track_id", "bbox", "confidence", "identity_candidate", "identity_confidence", "state"]
    for key in required_person_keys:
        if f'"{key}"' not in cam_mgr_src:
            mismatches.append({"file": "pipeline_engine/ingestion/camera_manager.py", "issue": f"Missing canonical person key '{key}'"})
        if f'"{key}"' not in broadcaster_src and f"{key}:" not in broadcaster_src:
            mismatches.append({"file": "app/streaming/metadata_broadcaster.py", "issue": f"Missing canonical person key '{key}'"})

    for key in ["camera_id", "frame_sequence", "timestamp", "persons", "counts"]:
        if f'"{key}"' not in cam_mgr_src:
            mismatches.append({"file": "pipeline_engine/ingestion/camera_manager.py", "issue": f"Missing canonical envelope key '{key}'"})
        if f'"{key}"' not in broadcaster_src:
            mismatches.append({"file": "app/streaming/metadata_broadcaster.py", "issue": f"Missing canonical envelope key '{key}'"})

    if "AliasChoices" not in broadcaster_src or "AliasChoices" not in cameras_api_src:
        mismatches.append({"file": "app/", "issue": "Missing AliasChoices compatibility boundary for camera_id"})

    # Frontend legacy variable checks
    if "cam_id" in html_src:
        mismatches.append({"file": "frontend/index.html", "issue": "Found unmigrated legacy 'cam_id' reference"})
    if "r.conf " in html_src or "r.conf)" in html_src or "r.conf||" in html_src:
        mismatches.append({"file": "frontend/index.html", "issue": "Found unmigrated legacy 'r.conf' reference"})
    if "person.identity_candidate" not in html_src:
        mismatches.append({"file": "frontend/index.html", "issue": "drawPersonBox does not read 'identity_candidate'"})
    if re.search(r"new CanvasOverlayRenderer\([^)]*['\"]CAM[12]['\"]", html_src):
        mismatches.append({"file": "frontend/index.html", "issue": "Uppercase 'CAM1'/'CAM2' passed to CanvasOverlayRenderer"})

    return mismatches


def run_audit() -> Dict[str, Any]:
    py_files = _iter_python_files([REPO_ROOT / "pipeline_engine", REPO_ROOT / "app"])
    syntax_errors, broken_imports, parsed = _check_python_ast(py_files)
    broken_links = _check_cross_layer_links(parsed)
    orphan_dom_ids, defined_dom_ids = _check_frontend_dom_ids()
    legacy_mismatches = _check_canonical_variables()

    total_issues = (
        len(syntax_errors)
        + len(broken_imports)
        + len(broken_links)
        + len(orphan_dom_ids)
        + len(legacy_mismatches)
    )

    return {
        "summary": {
            "python_files_scanned": len(py_files),
            "dom_ids_defined": len(defined_dom_ids),
            "syntax_errors_count": len(syntax_errors),
            "broken_imports_count": len(broken_imports),
            "broken_links_count": len(broken_links),
            "orphan_dom_ids_count": len(orphan_dom_ids),
            "legacy_variable_mismatches_count": len(legacy_mismatches),
            "total_issues": total_issues,
            "passed": total_issues == 0,
        },
        "syntax_errors": syntax_errors,
        "broken_imports": broken_imports,
        "broken_links": broken_links,
        "orphan_dom_ids": orphan_dom_ids,
        "legacy_variable_mismatches": legacy_mismatches,
    }


def main() -> int:
    report = run_audit()
    out_dir = REPO_ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "graphify_audit_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(json.dumps(summary, indent=2))
    if not summary["passed"]:
        print("\nDetected issues:")
        for section in ("syntax_errors", "broken_imports", "broken_links", "orphan_dom_ids", "legacy_variable_mismatches"):
            if report[section]:
                print(f"  [{section}]: {report[section]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
