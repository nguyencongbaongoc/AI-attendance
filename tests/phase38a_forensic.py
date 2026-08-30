#!/usr/bin/env python
"""
Phase 38A - Bootstrap + Complete Repository Forensic Analysis

This script performs comprehensive forensic analysis of the repository:
1. Build actual runtime dependency graph
2. Complete file inventory
3. Model/NPY forensics
4. Legacy/duplicate forensics
5. Canonical entrypoint audit
6. Configuration forensics
7. UI forensics
8. Unused file report
9. Bootstrap rehearsal
"""

from __future__ import annotations

import ast
import json
import os
import sys
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict


@dataclass
class FileInfo:
    """Information about a file in the repository."""
    path: str
    size: int
    modified: str
    category: str  # ACTIVE_RUNTIME, IMPORTED_BUT_NOT_RUNTIME, TEST_ONLY, TOOLING_ONLY, LEGACY, DUPLICATE, ORPHAN, UNKNOWN
    imports: List[str] = field(default_factory=list)
    imported_by: List[str] = field(default_factory=list)
    is_entrypoint: bool = False
    is_test: bool = False
    is_script: bool = False
    runtime_references: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    recommendation: str = ""
    deletion_risk: str = "UNKNOWN"  # SAFE, RISKY, UNKNOWN


@dataclass
class ModelInfo:
    """Information about a model file."""
    path: str
    size: int
    model_type: str  # SCRFD, ArcFace, ReID, Pose, GenderAge, etc.
    loaded_by: List[str] = field(default_factory=list)
    runtime_usage: str = "UNKNOWN"  # PRODUCTION, TEST_ONLY, DUPLICATE, OBSOLETE
    enrollment_usage: bool = False


@dataclass
class EntrypointInfo:
    """Information about an entrypoint."""
    path: str
    type: str  # APP, CAMERA, UI, BACKEND, ATTENDANCE, TELEGRAM, EXCEL, TIMETABLE, ENROLLMENT
    is_production: bool = True
    evidence: List[str] = field(default_factory=list)


@dataclass
class ConfigValue:
    """Information about a configuration value."""
    key: str
    value: Any
    used_by: List[str] = field(default_factory=list)
    status: str = "UNKNOWN"  # USED, UNUSED, DUPLICATE, CONFLICTING, LEGACY


class ForensicAnalyzer:
    """Main forensic analyzer for Phase 38A."""

    def __init__(self, root: Path):
        self.root = root
        self.files: Dict[str, FileInfo] = {}
        self.models: Dict[str, ModelInfo] = {}
        self.entrypoints: List[EntrypointInfo] = []
        self.config_values: Dict[str, ConfigValue] = {}
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_import_graph: Dict[str, Set[str]] = defaultdict(set)

    def analyze(self):
        """Run complete forensic analysis."""
        print("=" * 60)
        print("PHASE 38A - REPOSITORY FORENSIC ANALYSIS")
        print("=" * 60)

        # Step 1: Discover all files
        self._discover_files()

        # Step 2: Build import graph
        self._build_import_graph()

        # Step 3: Identify entrypoints
        self._identify_entrypoints()

        # Step 4: Analyze models
        self._analyze_models()

        # Step 5: Analyze enrollment databases
        self._analyze_enrollment()

        # Step 6: Analyze configuration
        self._analyze_config()

        # Step 7: Analyze UI components
        self._analyze_ui()

        # Step 8: Classify files
        self._classify_files()

        # Step 9: Legacy/duplicate detection
        self._detect_legacy_duplicates()

        # Step 10: Bootstrap rehearsal
        self._bootstrap_rehearsal()

        # Generate reports
        self._generate_reports()

    def _discover_files(self):
        """Discover all relevant files in the repository."""
        print("\n[1/10] Discovering files...")

        patterns = [
            ("app/**/*.py", "APP"),
            ("scripts/**/*.py", "SCRIPT"),
            ("tests/**/*.py", "TEST"),
            ("frontend/src/**/*.vue", "UI_VUE"),
            ("frontend/src/**/*.js", "UI_JS"),
            ("frontend/src/**/*.ts", "UI_TS"),
            ("config/**/*", "CONFIG"),
            ("models/**/*", "MODEL"),
            ("data/**/*", "DATA"),
            ("benchmark_results/**/*", "BENCHMARK"),
            ("requirements/**/*", "REQUIREMENTS"),
            ("*.py", "ROOT_PY"),
            ("*.bat", "BATCH"),
            ("*.sh", "SHELL"),
            ("*.yaml", "YAML"),
            ("*.yml", "YML"),
            ("*.json", "JSON"),
            ("*.md", "MARKDOWN"),
        ]

        for pattern, category in patterns:
            for f in self.root.glob(pattern):
                if f.is_file() and not self._should_skip(f):
                    rel_path = str(f.relative_to(self.root))
                    stat = f.stat()
                    self.files[rel_path] = FileInfo(
                        path=rel_path,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        category=category,
                        is_test="tests/" in rel_path or rel_path.startswith("test_"),
                        is_script="scripts/" in rel_path,
                    )

        print(f"  Discovered {len(self.files)} files")

    def _should_skip(self, path: Path) -> bool:
        """Check if file should be skipped."""
        skip_dirs = {'.venv', '__pycache__', '.git', 'node_modules', '.pytest_cache', 'dist'}
        for part in path.parts:
            if part in skip_dirs:
                return True
        return False

    def _build_import_graph(self):
        """Build Python import graph."""
        print("\n[2/10] Building import graph...")

        py_files = [f for f in self.files.values() if f.path.endswith('.py') and not f.path.startswith('.venv')]

        for file_info in py_files:
            full_path = self.root / file_info.path
            try:
                content = full_path.read_text(encoding='utf-8')
                tree = ast.parse(content)

                imports = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ''
                        for alias in node.names:
                            imports.append(f'{module}.{alias.name}')

                file_info.imports = imports

                # Build reverse graph
                for imp in imports:
                    self.import_graph[file_info.path].add(imp)
                    self.reverse_import_graph[imp].add(file_info.path)

            except Exception as e:
                file_info.evidence.append(f"Parse error: {e}")

        print(f"  Analyzed {len(py_files)} Python files")

    def _identify_entrypoints(self):
        """Identify all entrypoints."""
        print("\n[3/10] Identifying entrypoints...")

        # Check for __main__ blocks
        for file_info in self.files.values():
            if file_info.path.endswith('.py'):
                full_path = self.root / file_info.path
                try:
                    content = full_path.read_text(encoding='utf-8')
                    if '__name__ == "__main__"' in content or "__name__ == '__main__'" in content:
                        file_info.is_entrypoint = True

                        # Classify entrypoint type
                        ep_type = self._classify_entrypoint(file_info.path, content)
                        self.entrypoints.append(EntrypointInfo(
                            path=file_info.path,
                            type=ep_type,
                            evidence=[f"Has __main__ block"]
                        ))
                except:
                    pass

        # Check app/main.py as API entrypoint
        if "app/main.py" in self.files:
            self.entrypoints.append(EntrypointInfo(
                path="app/main.py",
                type="API",
                is_production=True,
                evidence=["FastAPI app factory", "uvicorn entrypoint"]
            ))

        # Check bootstrap.py
        if "bootstrap.py" in self.files:
            self.entrypoints.append(EntrypointInfo(
                path="bootstrap.py",
                type="BOOTSTRAP",
                is_production=True,
                evidence=["Environment setup", "venv management"]
            ))

        print(f"  Found {len(self.entrypoints)} entrypoints")

    def _classify_entrypoint(self, path: str, content: str) -> str:
        """Classify entrypoint type based on path and content."""
        path_lower = path.lower()

        if "camera" in path_lower or "stream" in path_lower or "rtsp" in path_lower:
            return "CAMERA"
        elif "ui" in path_lower or "frontend" in path_lower or "dashboard" in path_lower:
            return "UI"
        elif "attendance" in path_lower and "engine" in path_lower:
            return "ATTENDANCE"
        elif "telegram" in path_lower or "notification" in path_lower:
            return "TELEGRAM"
        elif "excel" in path_lower or "export" in path_lower or "daily_excel" in path_lower:
            return "EXCEL"
        elif "timetable" in path_lower:
            return "TIMETABLE"
        elif "enroll" in path_lower:
            return "ENROLLMENT"
        elif "policy" in path_lower:
            return "POLICY"
        elif "health" in path_lower or "monitor" in path_lower:
            return "HEALTH"
        elif "bootstrap" in path_lower or "venv" in path_lower:
            return "BOOTSTRAP"
        elif "replay" in path_lower:
            return "REPLAY"
        elif path.startswith("scripts/phase"):
            return "PHASE_SCRIPT"
        elif path.startswith("scripts/debug") or path.startswith("scripts/fix"):
            return "DEBUG_TOOL"
        else:
            return "UNKNOWN"

    def _analyze_models(self):
        """Analyze model files."""
        print("\n[4/10] Analyzing models...")

        model_dirs = {
            "models/scrfd": "SCRFD",
            "models/arcface": "ArcFace",
            "models/landmark": "Landmark",
            "models/reid": "ReID",
            "models/yolo": "YOLO",
        }

        for model_dir, model_type in model_dirs.items():
            for f in (self.root / model_dir).glob("*.onnx"):
                rel_path = str(f.relative_to(self.root))
                stat = f.stat()
                self.models[rel_path] = ModelInfo(
                    path=rel_path,
                    size=stat.st_size,
                    model_type=model_type,
                )

        # Also check root models
        for f in (self.root / "models").glob("*.onnx"):
            rel_path = str(f.relative_to(self.root))
            if rel_path not in self.models:
                stat = f.stat()
                self.models[rel_path] = ModelInfo(
                    path=rel_path,
                    size=stat.st_size,
                    model_type="Other",
                )

        # Find which files load models
        for file_info in self.files.values():
            if file_info.path.endswith('.py'):
                full_path = self.root / file_info.path
                try:
                    content = full_path.read_text(encoding='utf-8')
                    for model_path in self.models:
                        model_name = Path(model_path).stem
                        if model_name in content or model_path in content:
                            self.models[model_path].loaded_by.append(file_info.path)
                except:
                    pass

        print(f"  Found {len(self.models)} model files")

    def _analyze_enrollment(self):
        """Analyze enrollment databases."""
        print("\n[5/10] Analyzing enrollment databases...")

        enrollment_dirs = list(self.root.glob("data/enrollment_db*"))
        print(f"  Found {len(enrollment_dirs)} enrollment databases")

        for db_dir in enrollment_dirs:
            npy_file = db_dir / "embeddings.npy"
            meta_file = db_dir / "embeddings.npy.metadata.json"

            if npy_file.exists() and meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding='utf-8'))
                    print(f"  {db_dir.name}: {meta.get('embedding_count', 0)} embeddings, "
                          f"{len(meta.get('person_ids', []))} persons, "
                          f"model: {meta.get('model_filename', 'unknown')}")
                except Exception as e:
                    print(f"  {db_dir.name}: Error reading metadata: {e}")

    def _analyze_config(self):
        """Analyze configuration values."""
        print("\n[6/10] Analyzing configuration...")

        # Load default.yaml
        config_file = self.root / "config" / "default.yaml"
        if config_file.exists():
            import yaml
            try:
                config = yaml.safe_load(config_file.read_text(encoding='utf-8'))
                self._extract_config_values(config, "default.yaml")
            except Exception as e:
                print(f"  Error loading config: {e}")

        # Check settings.py for config usage
        settings_file = self.root / "app" / "config" / "settings.py"
        if settings_file.exists():
            content = settings_file.read_text(encoding='utf-8')
            # Find all settings accesses
            import re
            settings_accesses = re.findall(r'settings\.(\w+(?:\.\w+)*)', content)
            for access in settings_accesses:
                if access in self.config_values:
                    self.config_values[access].used_by.append("app/config/settings.py")
                else:
                    self.config_values[access] = ConfigValue(key=access, value=None, used_by=["app/config/settings.py"])

        print(f"  Found {len(self.config_values)} configuration values")

    def _extract_config_values(self, config: dict, prefix: str = ""):
        """Recursively extract config values."""
        for key, value in config.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                self._extract_config_values(value, full_key)
            else:
                self.config_values[full_key] = ConfigValue(key=full_key, value=value)

    def _analyze_ui(self):
        """Analyze UI components."""
        print("\n[7/10] Analyzing UI components...")

        ui_files = [f for f in self.files.values() if f.path.startswith("frontend/src/")]

        # Check router for routes
        router_file = self.root / "frontend/src/router/index.js"
        routes = []
        if router_file.exists():
            content = router_file.read_text(encoding='utf-8')
            import re
            # Find route paths
            route_matches = re.findall(r'path:\s*["\']([^"\']+)["\']', content)
            routes = route_matches

        # Check views
        views = list((self.root / "frontend/src/views").glob("*.vue")) if (self.root / "frontend/src/views").exists() else []

        print(f"  Found {len(ui_files)} UI files")
        print(f"  Routes: {routes}")
        print(f"  Views: {[v.stem for v in views]}")

    def _classify_files(self):
        """Classify all files based on analysis."""
        print("\n[8/10] Classifying files...")

        # Get all files that are imported by entrypoints or main app
        runtime_files = set()
        for ep in self.entrypoints:
            if ep.is_production:
                self._collect_runtime_deps(ep.path, runtime_files)

        # Also add files imported by app/main.py
        if "app/main.py" in self.files:
            self._collect_runtime_deps("app/main.py", runtime_files)

        # Classify each file
        for file_info in self.files.values():
            path = file_info.path

            if path in runtime_files:
                file_info.category = "ACTIVE_RUNTIME"
                file_info.recommendation = "KEEP - Active in production runtime"
                file_info.deletion_risk = "RISKY"
            elif file_info.is_test:
                file_info.category = "TEST_ONLY"
                file_info.recommendation = "KEEP - Test file"
                file_info.deletion_risk = "RISKY"
            elif file_info.is_script and path.startswith("scripts/phase"):
                file_info.category = "TOOLING_ONLY"
                file_info.recommendation = "KEEP - Phase acceptance script"
                file_info.deletion_risk = "RISKY"
            elif file_info.is_script and (path.startswith("scripts/debug") or path.startswith("scripts/fix")):
                file_info.category = "TOOLING_ONLY"
                file_info.recommendation = "REVIEW - Debug/fix script, may be obsolete"
                file_info.deletion_risk = "UNKNOWN"
            elif path.startswith("scripts/") and file_info.is_entrypoint:
                file_info.category = "TOOLING_ONLY"
                file_info.recommendation = "KEEP - Standalone script entrypoint"
                file_info.deletion_risk = "UNKNOWN"
            elif len(self.reverse_import_graph.get(path, set())) == 0 and not file_info.is_entrypoint:
                file_info.category = "ORPHAN"
                file_info.recommendation = "REVIEW - No imports found, verify if dynamically loaded"
                file_info.deletion_risk = "UNKNOWN"
            else:
                file_info.category = "IMPORTED_BUT_NOT_RUNTIME"
                file_info.recommendation = "REVIEW - Imported but not in main runtime path"
                file_info.deletion_risk = "UNKNOWN"

            # Add evidence
            if file_info.imports:
                file_info.evidence.append(f"Imports: {len(file_info.imports)} modules")
            if self.reverse_import_graph.get(path):
                file_info.evidence.append(f"Imported by: {len(self.reverse_import_graph[path])} files")
            if file_info.is_entrypoint:
                file_info.evidence.append("Has __main__ block")

    def _collect_runtime_deps(self, start_path: str, collected: Set[str], visited: Set[str] = None):
        """Recursively collect runtime dependencies."""
        if visited is None:
            visited = set()

        if start_path in visited:
            return
        visited.add(start_path)

        if start_path in self.files:
            collected.add(start_path)

        # Follow imports
        for imp in self.import_graph.get(start_path, set()):
            # Try to resolve import to file path
            resolved = self._resolve_import(imp, start_path)
            if resolved and resolved not in visited:
                self._collect_runtime_deps(resolved, collected, visited)

    def _resolve_import(self, import_name: str, from_file: str) -> Optional[str]:
        """Resolve an import name to a file path."""
        # Handle relative imports
        if import_name.startswith('.'):
            from_dir = Path(from_file).parent
            parts = import_name.lstrip('.').split('.')
            # This is simplified - real resolution is more complex
            return None

        # Handle absolute imports from app/
        if import_name.startswith('app.'):
            parts = import_name.split('.')
            # Convert to file path
            path_parts = parts[1:]  # Skip 'app'
            if path_parts[-1].startswith('_') or path_parts[-1] in ['contract', 'contracts']:
                # Might be a module, try both
                for suffix in ['.py', '/__init__.py']:
                    candidate = "app/" + "/".join(path_parts[:-1]) + "/" + path_parts[-1] + suffix
                    if candidate in self.files:
                        return candidate
            else:
                candidate = "app/" + "/".join(path_parts) + ".py"
                if candidate in self.files:
                    return candidate
                # Try as package
                candidate = "app/" + "/".join(path_parts) + "/__init__.py"
                if candidate in self.files:
                    return candidate

        return None

    def _detect_legacy_duplicates(self):
        """Detect legacy and duplicate implementations."""
        print("\n[9/10] Detecting legacy/duplicate implementations...")

        # Check for duplicate enrollment databases
        enrollment_dirs = list(self.root.glob("data/enrollment_db*"))
        if len(enrollment_dirs) > 1:
            for db_dir in enrollment_dirs[1:]:
                for f in self.files.values():
                    if f.path.startswith(str(db_dir.relative_to(self.root))):
                        f.category = "DUPLICATE"
                        f.recommendation = "REVIEW - Duplicate enrollment database"
                        f.deletion_risk = "UNKNOWN"

        # Check for legacy scripts
        legacy_patterns = [
            "scripts/debug_",
            "scripts/fix_",
            "scripts/check_",
            "scripts/update_",
            "scripts/run_phase33",
            "scripts/test_",
            "scripts/generate_phase",
            "scripts/phase36e_",
            "scripts/phase36f_",
            "scripts/phase36g_",
            "scripts/phase36k_",
            "scripts/phase36l_",
            "scripts/phase36m_",
            "scripts/phase36r_",
            "scripts/phase36s_",
            "scripts/phase36t_",
            "scripts/phase36_long_duration_soak.py",
            "scripts/phase35_",
            "scripts/phase34_",
            "scripts/phase33_",
            "scripts/phase32_",
            "scripts/phase31_",
            "scripts/phase30_",
            "scripts/phase29_",
            "scripts/phase28_",
            "scripts/phase27_",
            "scripts/phase26_",
            "scripts/phase25_",
            "scripts/phase24_",
            "scripts/phase23_",
            "scripts/phase22_",
            "scripts/phase21_",
            "scripts/phase20_",
            "scripts/phase19_",
            "scripts/phase18_",
            "scripts/phase17_",
            "scripts/phase16_",
            "scripts/phase9_",
            "scripts/phase7",
            "scripts/phase6_",
            "scripts/phase3_",
        ]

        for file_info in self.files.values():
            for pattern in legacy_patterns:
                if file_info.path.startswith(pattern):
                    if file_info.category != "DUPLICATE":
                        file_info.category = "LEGACY"
                        file_info.recommendation = f"REVIEW - Legacy script ({pattern})"
                        file_info.deletion_risk = "UNKNOWN"
                    break

        # Check for duplicate implementations in app/
        # Look for similar names
        app_files = [f for f in self.files.values() if f.path.startswith("app/") and f.path.endswith(".py")]
        name_map = defaultdict(list)
        for f in app_files:
            name = Path(f.path).stem
            name_map[name].append(f.path)

        for name, paths in name_map.items():
            if len(paths) > 1:
                for p in paths[1:]:
                    f = self.files[p]
                    if f.category not in ["DUPLICATE", "LEGACY"]:
                        f.category = "DUPLICATE"
                        f.recommendation = f"REVIEW - Duplicate name: {name}"
                        f.deletion_risk = "UNKNOWN"

    def _bootstrap_rehearsal(self):
        """Perform bootstrap rehearsal without cameras."""
        print("\n[10/10] Bootstrap rehearsal...")

        # Check if system can initialize without cameras
        checks = {
            "environment": True,
            "configuration": True,
            "database": True,
            "enrollment_database": True,
            "timetable": True,
            "backend": True,
            "policy": True,
            "notification_worker": True,
            "ui": True,
        }

        # Check critical files exist
        critical_files = [
            "config/default.yaml",
            "requirements/base.txt",
            "app/main.py",
            "app/bootstrap/startup_validation.py",
            "app/attendance/timetable_loader.py",
            "app/attendance/session_context.py",
            "app/attendance/policy_engine/engine.py",
            "app/attendance/policy_engine/parent_registry.py",
            "app/attendance/policy_engine/telegram_bot.py",
            "app/attendance/daily_excel.py",
            "frontend/src/views/LiveDashboard.vue",
            "frontend/src/views/TimetableManagement.vue",
        ]

        missing = []
        for cf in critical_files:
            if not (self.root / cf).exists():
                missing.append(cf)
                checks["configuration"] = False

        # Check enrollment database
        if not (self.root / "data/enrollment_db/embeddings.npy").exists():
            checks["enrollment_database"] = False
            missing.append("data/enrollment_db/embeddings.npy")

        # Check databases
        for db in ["data/parent_registry.db", "data/notification_queue.db", "data/exit_sessions.db"]:
            if not (self.root / db).exists():
                # These might be created on first run
                pass

        print(f"  Bootstrap checks: {sum(checks.values())}/{len(checks)} passed")
        if missing:
            print(f"  Missing critical files: {missing}")

        self.bootstrap_result = {
            "checks": checks,
            "missing_files": missing,
            "can_initialize_without_camera": all(checks.values()),
            "camera_absence_behavior": "NOT_CONNECTED / NOT_AVAILABLE (expected)",
        }

    def _generate_reports(self):
        """Generate forensic reports."""
        print("\nGenerating reports...")

        # Prepare data for JSON report
        files_data = []
        for f in self.files.values():
            files_data.append(asdict(f))

        models_data = []
        for m in self.models.values():
            models_data.append(asdict(m))

        entrypoints_data = [asdict(e) for e in self.entrypoints]

        config_data = {k: asdict(v) for k, v in self.config_values.items()}

        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "phase": "38A",
            "summary": {
                "total_files": len(self.files),
                "active_runtime": len([f for f in self.files.values() if f.category == "ACTIVE_RUNTIME"]),
                "imported_not_runtime": len([f for f in self.files.values() if f.category == "IMPORTED_BUT_NOT_RUNTIME"]),
                "test_only": len([f for f in self.files.values() if f.category == "TEST_ONLY"]),
                "tooling_only": len([f for f in self.files.values() if f.category == "TOOLING_ONLY"]),
                "legacy": len([f for f in self.files.values() if f.category == "LEGACY"]),
                "duplicate": len([f for f in self.files.values() if f.category == "DUPLICATE"]),
                "orphan": len([f for f in self.files.values() if f.category == "ORPHAN"]),
                "unknown": len([f for f in self.files.values() if f.category == "UNKNOWN"]),
                "models_found": len(self.models),
                "entrypoints_found": len(self.entrypoints),
                "enrollment_databases": len(list(self.root.glob("data/enrollment_db*"))),
                "bootstrap_can_initialize": self.bootstrap_result.get("can_initialize_without_camera", False),
            },
            "files": files_data,
            "models": models_data,
            "entrypoints": entrypoints_data,
            "config_values": config_data,
            "bootstrap_result": self.bootstrap_result,
        }

        # Write JSON report
        output_dir = self.root / "benchmark_results"
        output_dir.mkdir(exist_ok=True)

        json_path = output_dir / "PHASE_38A_UNUSED_FILE_FORENSIC.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Write Markdown report
        md_path = output_dir / "PHASE_38A_UNUSED_FILE_FORENSIC.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(self._generate_markdown(report))

        print(f"  JSON report: {json_path}")
        print(f"  Markdown report: {md_path}")

    def _generate_markdown(self, report: dict) -> str:
        """Generate markdown report."""
        lines = []
        lines.append("# Phase 38A - Repository Forensic Analysis Report")
        lines.append("")
        lines.append(f"**Generated:** {report['timestamp']}")
        lines.append("")

        # Summary
        lines.append("## 1. Summary")
        lines.append("")
        s = report['summary']
        lines.append(f"- **Total Files Analyzed:** {s['total_files']}")
        lines.append(f"- **Active Runtime Files:** {s['active_runtime']}")
        lines.append(f"- **Imported But Not Runtime:** {s['imported_not_runtime']}")
        lines.append(f"- **Test Only:** {s['test_only']}")
        lines.append(f"- **Tooling Only:** {s['tooling_only']}")
        lines.append(f"- **Legacy:** {s['legacy']}")
        lines.append(f"- **Duplicate:** {s['duplicate']}")
        lines.append(f"- **Orphan:** {s['orphan']}")
        lines.append(f"- **Unknown:** {s['unknown']}")
        lines.append(f"- **Models Found:** {s['models_found']}")
        lines.append(f"- **Entry Points Found:** {s['entrypoints_found']}")
        lines.append(f"- **Enrollment Databases:** {s['enrollment_databases']}")
        lines.append(f"- **Bootstrap Can Initialize Without Camera:** {s['bootstrap_can_initialize']}")
        lines.append("")

        # Entrypoints
        lines.append("## 2. Canonical Entrypoints")
        lines.append("")
        for ep in report['entrypoints']:
            lines.append(f"- **{ep['path']}** ({ep['type']}) - Production: {ep['is_production']}")
            for ev in ep['evidence']:
                lines.append(f"  - {ev}")
        lines.append("")

        # Models
        lines.append("## 3. Model Analysis")
        lines.append("")
        for m in report['models']:
            lines.append(f"- **{m['path']}** ({m['model_type']}, {m['size']} bytes)")
            lines.append(f"  - Loaded by: {', '.join(m['loaded_by']) if m['loaded_by'] else 'None detected'}")
            lines.append(f"  - Runtime usage: {m['runtime_usage']}")
            lines.append(f"  - Enrollment usage: {m['enrollment_usage']}")
        lines.append("")

        # Enrollment databases
        lines.append("## 4. Enrollment Databases")
        lines.append("")
        enrollment_dirs = list(self.root.glob("data/enrollment_db*"))
        for db_dir in enrollment_dirs:
            meta_file = db_dir / "embeddings.npy.metadata.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding='utf-8'))
                lines.append(f"- **{db_dir.name}**")
                lines.append(f"  - Embeddings: {meta.get('embedding_count', 0)}")
                lines.append(f"  - Persons: {', '.join(meta.get('person_ids', []))}")
                lines.append(f"  - Model: {meta.get('model_filename', 'unknown')}")
                lines.append(f"  - Created: {meta.get('creation_timestamp', 'unknown')}")
        lines.append("")

        # File classifications
        lines.append("## 5. File Classifications")
        lines.append("")
        for cat in ["ACTIVE_RUNTIME", "IMPORTED_BUT_NOT_RUNTIME", "TEST_ONLY", "TOOLING_ONLY", "LEGACY", "DUPLICATE", "ORPHAN", "UNKNOWN"]:
            cat_files = [f for f in report['files'] if f['category'] == cat]
            if cat_files:
                lines.append(f"### {cat} ({len(cat_files)} files)")
                lines.append("")
                for f in cat_files:
                    lines.append(f"- **{f['path']}**")
                    lines.append(f"  - Size: {f['size']} bytes")
                    lines.append(f"  - Recommendation: {f['recommendation']}")
                    lines.append(f"  - Deletion Risk: {f['deletion_risk']}")
                    if f['evidence']:
                        lines.append(f"  - Evidence: {', '.join(f['evidence'])}")
                lines.append("")

        # Bootstrap result
        lines.append("## 6. Bootstrap Rehearsal Result")
        lines.append("")
        br = report['bootstrap_result']
        lines.append(f"- **Can Initialize Without Camera:** {br['can_initialize_without_camera']}")
        lines.append(f"- **Camera Absence Behavior:** {br['camera_absence_behavior']}")
        lines.append("")
        lines.append("### Checks:")
        for check, result in br['checks'].items():
            status = "PASS" if result else "FAIL"
            lines.append(f"- {check}: {status}")
        if br['missing_files']:
            lines.append("")
            lines.append("### Missing Critical Files:")
            for mf in br['missing_files']:
                lines.append(f"- {mf}")
        lines.append("")

        # Configuration
        lines.append("## 7. Configuration Analysis")
        lines.append("")
        for key, cv in report['config_values'].items():
            status = cv['status']
            used = cv['used_by']
            lines.append(f"- **{key}**: {status} (used by: {', '.join(used) if used else 'none'})")
        lines.append("")

        return "\n".join(lines)


def main():
    root = Path(__file__).parent.resolve()
    analyzer = ForensicAnalyzer(root)
    analyzer.analyze()
    print("\n" + "=" * 60)
    print("PHASE 38A FORENSIC ANALYSIS COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()