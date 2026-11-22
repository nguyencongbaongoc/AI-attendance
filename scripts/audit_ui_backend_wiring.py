"""
Static & OpenAPI UI-to-Backend Contract Auditor for ATTENDANCE OS.

Extracts all REST/WebSocket calls, payloads, query params, response key accesses,
and interactive DOM handlers from frontend/index.html and cross-checks them against
live FastAPI routes and app.openapi() schemas from app.main:app.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "test")

from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from app.main import app


ENDPOINT_MAP = {
    "health": "/api/v1/health",
    "attendance": "/api/v1/attendance",
    "enrollment": "/api/v1/enrollment",
    "replay": "/api/v1/replay",
    "geometry": "/api/v1/geometry",
    "students": "/api/v1/students",
    "excel": "/api/v1/excel",
    "ai_worker": "/api/v1/ai-worker",
    "cameras": "/api/v1/cameras",
    "pipeline": "/api/v1/pipeline",
    "recordings": "/api/v1/recordings",
}


def normalize_url_expr(expr: str) -> Tuple[str, List[str]]:
    """Normalize a JS template literal or string URL into a FastAPI path and query keys."""
    s = expr.strip().strip("`'\"")
    for k, v in ENDPOINT_MAP.items():
        s = s.replace(f"${{API_CONFIG.endpoints.{k}}}", v)
    s = re.sub(r"^\$\{API_CONFIG\.(baseURL|wsBaseURL)\}", "", s)

    query_keys: List[str] = []
    if "?" in s:
        path_part, query_part = s.split("?", 1)
        for qm in re.finditer(r"([A-Za-z0-9_]+)=", query_part):
            query_keys.append(qm.group(1))
    else:
        path_part = s

    # Normalize JS template placeholders like ${cid}, ${studentId}, ${recId}, ${action}
    path_part = re.sub(r"\$\{[^}]+\}", "{param}", path_part)
    path_part = re.sub(r"//+", "/", path_part)
    return path_part, query_keys


def route_pattern_to_regex(route_path: str) -> re.Pattern[str]:
    escaped = re.escape(route_path)
    regex_str = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", escaped)
    return re.compile(f"^{regex_str}$")


def match_path(fe_path: str, registered_paths: List[str]) -> Optional[str]:
    if fe_path in registered_paths:
        return fe_path
    # Compare structurally by replacing {anything} with {param}
    fe_norm = re.sub(r"\{[^}]+\}", "{param}", fe_path)
    for rp in registered_paths:
        rp_norm = re.sub(r"\{[^}]+\}", "{param}", rp)
        if fe_norm == rp_norm:
            return rp
        if route_pattern_to_regex(rp).match(fe_path.replace("{param}", "sample")):
            return rp
    return None


def extract_frontend_calls(html: str) -> Dict[str, Any]:
    lines = html.splitlines()
    script_idx = html.rfind("<script>")
    dom_part = html[:script_idx] if script_idx != -1 else html
    js_part = html[script_idx:] if script_idx != -1 else ""
    script_start_line = html[:script_idx].count("\n") + 1 if script_idx != -1 else 1

    # Extract API calls, bounded ternaries, and URLSearchParams usage
    http_calls: List[Dict[str, Any]] = []
    # Match api.get/post/put/patch/delete(...)
    api_pat = re.compile(r"\bapi\.(get|post|put|patch|delete)\(\s*([`'\"])(.*?)\2", re.DOTALL)
    for m in api_pat.finditer(js_part):
        line_no = script_start_line + js_part[: m.start()].count("\n")
        method = m.group(1).upper()
        raw_url = m.group(3)
        path, qkeys = normalize_url_expr(raw_url)

        # Detect nearby URLSearchParams / filter helper usage if query uses ${queryParams}
        ctx_before = "\n".join(lines[max(0, line_no - 20) : line_no])
        if "${queryParams}" in raw_url or "${query.toString()}" in raw_url:
            for qm in re.finditer(r"(?:params|query)\.set\(['\"]([^'\"]+)['\"]", ctx_before):
                qkeys.append(qm.group(1))
            for qm in re.finditer(r"\bparams\.([A-Za-z0-9_]+)\s*=", ctx_before):
                qkeys.append(qm.group(1))
            for qm in re.finditer(r"^\s*([A-Za-z0-9_]+)\s*:", ctx_before, re.M):
                if qm.group(1) not in ("limit", "offset", "order_by", "desc"):
                    qkeys.append(qm.group(1))
        if path == "/api/v1/students" and method == "GET":
            # Include filterStudents() parameters sent to loadStudents(params)
            fs_m = re.search(r"function filterStudents\(\)\s*\{(.*?)\}", js_part, re.DOTALL)
            if fs_m:
                for qm in re.finditer(r"\bparams\.([A-Za-z0-9_]+)\s*=", fs_m.group(1)):
                    qkeys.append(qm.group(1))

        # Expand bounded ternaries such as ${pipelineAction} -> start | stop
        expanded_paths = [path]
        if "${pipelineAction}" in raw_url:
            m_act = re.search(r"const pipelineAction\s*=\s*[^?]+\?\s*['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]+)['\"]", ctx_before)
            if m_act:
                expanded_paths = [path.rsplit("/{param}", 1)[0] + f"/{act}" for act in m_act.groups()]

        ctx_after = "\n".join(lines[line_no - 1 : min(len(lines), line_no + 22)])
        for ep in expanded_paths:
            http_calls.append(
                {
                    "line": line_no,
                    "client": f"api.{method.lower()}",
                    "method": method,
                    "raw_url": raw_url,
                    "path": ep,
                    "query_keys": sorted(set(qkeys)),
                    "body_encoding": "application/json" if method in ("POST", "PUT", "PATCH") else None,
                    "has_api_key": True,
                    "context_snippet": "\n".join(lines[max(0, line_no - 2) : min(len(lines), line_no + 8)]),
                    "post_snippet": ctx_after,
                }
            )

    # Match raw fetch(...) except internal APIClient wrapper line `fetch(url, config)`
    fetch_pat = re.compile(r"\bfetch\(\s*([`'\"])(.*?)\1\s*(?:,\s*\{(.*?)\}\s*)?\)", re.DOTALL)
    for m in fetch_pat.finditer(js_part):
        line_no = script_start_line + js_part[: m.start()].count("\n")
        raw_url = m.group(2)
        opts = m.group(3) or ""
        path, qkeys = normalize_url_expr(raw_url)
        mm = re.search(r"method\s*:\s*['\"]([A-Za-z]+)['\"]", opts)
        method = mm.group(1).upper() if mm else "GET"

        ctx_before = "\n".join(lines[max(0, line_no - 25) : line_no + 6])
        if "${query.toString()}" in raw_url or "${queryParams}" in raw_url:
            for qm in re.finditer(r"(?:params|query)\.set\(['\"]([^'\"]+)['\"]", ctx_before):
                qkeys.append(qm.group(1))

        if "JSON.stringify(" in opts:
            body_enc = "application/json"
        elif "body:" in opts and ("formData" in opts or "FormData" in ctx_before):
            body_enc = "multipart/form-data"
        elif method in ("POST", "PUT", "PATCH"):
            body_enc = "unknown"
        else:
            body_enc = None

        has_key = ("X-API-Key" in opts) or ("API_CONFIG.getApiKey" in ctx_before)
        form_fields = sorted(set(re.findall(r"formData\.append\(\s*['\"]([^'\"]+)['\"]", ctx_before)))
        http_calls.append(
            {
                "line": line_no,
                "client": "fetch",
                "method": method,
                "raw_url": raw_url,
                "path": path,
                "query_keys": sorted(set(qkeys)),
                "body_encoding": body_enc,
                "form_fields": form_fields,
                "has_api_key": has_key,
                "context_snippet": ctx_before,
                "post_snippet": "\n".join(lines[line_no - 1 : min(len(lines), line_no + 25)]),
            }
        )

    # Extract WebSocket URL getters & usages
    ws_urls: List[Dict[str, Any]] = []
    for i, l in enumerate(lines, 1):
        if "${API_CONFIG.wsBaseURL}/api/v1/" in l:
            m = re.search(r"([`'\"]\$\{API_CONFIG\.wsBaseURL\}[^`'\"]+)", l)
            if m:
                path, _ = normalize_url_expr(m.group(1))
                ws_urls.append({"line": i, "path": path, "raw": m.group(1)})

    # Extract DOM onclicks and JS function definitions
    onclicks = sorted(set(re.findall(r'onclick="([^"]+)"', dom_part)))
    defined_fns = set(re.findall(r"(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(", js_part))
    defined_fns |= set(re.findall(r"window\.([A-Za-z0-9_]+)\s*=", js_part))
    pages = set(re.findall(r'id="(page-[^"]+)"', dom_part))
    navs = re.findall(r'data-page="([^"]+)"', dom_part)

    return {
        "http_calls": http_calls,
        "ws_urls": ws_urls,
        "onclicks": onclicks,
        "defined_fns": sorted(defined_fns),
        "pages": sorted(pages),
        "navs": navs,
        "dom_html": dom_part,
        "js_code": js_part,
    }


def resolve_schema(openapi: Dict[str, Any], schema_obj: Dict[str, Any]) -> Dict[str, Any]:
    if not schema_obj:
        return {}
    if "$ref" in schema_obj:
        ref_name = schema_obj["$ref"].split("/")[-1]
        return resolve_schema(openapi, openapi.get("components", {}).get("schemas", {}).get(ref_name, {}))
    if schema_obj.get("type") == "array" and "items" in schema_obj:
        return resolve_schema(openapi, schema_obj["items"])
    return schema_obj


def run_audit() -> Dict[str, Any]:
    html_path = ROOT / "frontend" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    fe = extract_frontend_calls(html)
    openapi = app.openapi()
    openapi_paths: Dict[str, Any] = openapi.get("paths", {})
    registered_http_paths = list(openapi_paths.keys())
    registered_ws_paths = [r.path for r in app.routes if isinstance(r, APIWebSocketRoute)]

    unmatched_routes: List[Dict[str, Any]] = []
    method_mismatches: List[Dict[str, Any]] = []
    schema_mismatches: List[Dict[str, Any]] = []
    dead_handlers: List[Dict[str, Any]] = []
    verified_calls: List[Dict[str, Any]] = []

    client = TestClient(app)

    for call in fe["http_calls"]:
        fe_path = call["path"]
        matched_path = match_path(fe_path, registered_http_paths)
        if not matched_path:
            unmatched_routes.append({"line": call["line"], "method": call["method"], "path": fe_path, "raw": call["raw_url"]})
            continue

        methods_spec = openapi_paths[matched_path]
        method_lower = call["method"].lower()
        if method_lower not in methods_spec:
            method_mismatches.append(
                {
                    "line": call["line"],
                    "path": matched_path,
                    "frontend_method": call["method"],
                    "allowed_methods": [m.upper() for m in methods_spec.keys()],
                }
            )
            continue

        spec = methods_spec[method_lower]
        params = spec.get("parameters", [])
        backend_query_params = {p["name"] for p in params if p.get("in") == "query"}
        backend_header_params = {p["name"]: p.get("required", False) for p in params if p.get("in") == "header"}

        # 1. Check query parameter mismatches (ignore common pagination or known search filter checks)
        for qk in call["query_keys"]:
            if qk not in backend_query_params:
                schema_mismatches.append(
                    {
                        "type": "unsupported_query_param",
                        "line": call["line"],
                        "path": matched_path,
                        "method": call["method"],
                        "query_param": qk,
                        "backend_query_params": sorted(backend_query_params),
                    }
                )

        # 2. Check request body content-type (e.g., JSON sent to multipart/form-data endpoint)
        req_body_content = spec.get("requestBody", {}).get("content", {})
        if req_body_content:
            expected_ctypes = list(req_body_content.keys())
            fe_enc = call.get("body_encoding")
            if fe_enc and fe_enc != "unknown" and fe_enc not in expected_ctypes:
                schema_mismatches.append(
                    {
                        "type": "request_content_type_mismatch",
                        "line": call["line"],
                        "path": matched_path,
                        "method": call["method"],
                        "frontend_encoding": fe_enc,
                        "expected_encodings": expected_ctypes,
                    }
                )
            if "multipart/form-data" in expected_ctypes and fe_enc == "multipart/form-data":
                mp_schema = resolve_schema(openapi, req_body_content["multipart/form-data"].get("schema", {}))
                req_fields = mp_schema.get("required", [])
                for rf in req_fields:
                    if rf not in call.get("form_fields", []):
                        schema_mismatches.append(
                            {
                                "type": "missing_multipart_field",
                                "line": call["line"],
                                "path": matched_path,
                                "missing_field": rf,
                                "frontend_fields": call.get("form_fields", []),
                            }
                        )

        # 3. Check required API Key headers on raw fetch() or key compatibility
        if backend_header_params.get("X-API-Key") and not call["has_api_key"]:
            schema_mismatches.append(
                {
                    "type": "missing_required_api_key_header",
                    "line": call["line"],
                    "path": matched_path,
                    "method": call["method"],
                }
            )

        # 4. Response schema field checks for explicit response accesses in context
        resp_200 = spec.get("responses", {}).get("200") or spec.get("responses", {}).get("201") or {}
        resp_schema_raw = resp_200.get("content", {}).get("application/json", {}).get("schema", {})
        resp_schema = resolve_schema(openapi, resp_schema_raw)
        resp_props = set(resp_schema.get("properties", {}).keys())

        # Specific field usage verification for known endpoints
        if matched_path == "/api/v1/pipeline/reload-gallery":
            if "res.gallery_size" in call["post_snippet"] and "res.count" not in call["post_snippet"]:
                schema_mismatches.append(
                    {
                        "type": "response_field_mismatch",
                        "line": call["line"],
                        "path": matched_path,
                        "frontend_field": "gallery_size",
                        "note": "Backend returns 'count' (pipeline.py); UI reads 'res.gallery_size' without fallback.",
                    }
                )

        if matched_path == "/api/v1/attendance/records" and "openEvidenceModal" in html:
            rec_item_schema = resolve_schema(openapi, resp_schema.get("properties", {}).get("records", {}))
            rec_item_props = set(rec_item_schema.get("properties", {}).keys())
            ev_block_m = re.search(r"function openEvidenceModal\(record\)\s*\{.*?\n\}", html, re.DOTALL)
            if ev_block_m and "snapshot_face_url" in ev_block_m.group(0):
                if rec_item_props and "snapshot_face_url" not in rec_item_props:
                    schema_mismatches.append(
                        {
                            "type": "response_field_mismatch",
                            "line": html[: ev_block_m.start()].count("\n") + 1,
                            "path": matched_path,
                            "frontend_field": "snapshot_face_url / snapshot_scene_url",
                            "backend_fields": sorted(rec_item_props),
                            "note": "AttendanceRecordResponse lacks snapshot_face_url / snapshot_scene_url.",
                        }
                    )

        # 5. Live TestClient API key check for unparameterized GET endpoints and key-guarded paths
        if call["method"] == "GET" and "{" not in matched_path:
            r = client.get(matched_path, headers={"X-API-Key": "dev_admin_key_2026"})
            if r.status_code in (401, 403, 404, 405, 422):
                schema_mismatches.append(
                    {
                        "type": "live_probe_failure",
                        "line": call["line"],
                        "path": matched_path,
                        "status_code": r.status_code,
                        "detail": r.text[:200],
                    }
                )
        elif matched_path == "/api/v1/health/ai-worker/{worker_id}":
            r = client.get("/api/v1/health/ai-worker/pipeline-engine-1", headers={"X-API-Key": "dev_admin_key_2026"})
            if r.status_code != 200:
                schema_mismatches.append(
                    {
                        "type": "auth_or_probe_failure",
                        "line": call["line"],
                        "path": matched_path,
                        "status_code": r.status_code,
                        "detail": r.text[:200],
                    }
                )

        verified_calls.append(
            {
                "line": call["line"],
                "method": call["method"],
                "frontend_path": fe_path,
                "matched_backend_path": matched_path,
                "query_keys": call["query_keys"],
            }
        )

    # Check WebSocket routes
    ws_verified: List[Dict[str, Any]] = []
    for ws in fe["ws_urls"]:
        matched_ws = match_path(ws["path"], registered_ws_paths)
        if not matched_ws:
            unmatched_routes.append({"line": ws["line"], "method": "WS", "path": ws["path"], "raw": ws["raw"]})
        else:
            ws_verified.append({"line": ws["line"], "frontend_path": ws["path"], "matched_ws_path": matched_ws})

    # Check DOM onclick handlers & data-page switches
    for oc in fe["onclicks"]:
        if oc.startswith("document."):
            continue
        m = re.match(r"^([A-Za-z0-9_]+)\s*\(", oc.strip())
        if not m:
            dead_handlers.append({"type": "unparseable_onclick", "handler": oc})
            continue
        fn_name = m.group(1)
        if fn_name not in fe["defined_fns"]:
            dead_handlers.append({"type": "missing_js_function", "function": fn_name, "handler": oc})

    for nav in fe["navs"]:
        target_id = "page-review" if nav == "video" else f"page-{nav}"
        if target_id not in fe["pages"]:
            dead_handlers.append({"type": "missing_page_section", "nav": nav, "expected_id": target_id})

    # Check Evidence button presence in #recordsBody renderer if openEvidenceModal exists
    if "function openEvidenceModal" in html:
        body_part = html.split("function openEvidenceModal")[0]
        if "openEvidenceModal(" not in body_part:
            dead_handlers.append(
                {
                    "type": "unwired_modal",
                    "function": "openEvidenceModal",
                    "note": "openEvidenceModal is defined but never wired to records table rows/buttons.",
                }
            )

    summary = {
        "total_http_calls": len(fe["http_calls"]),
        "total_ws_calls": len(fe["ws_urls"]),
        "total_dom_onclicks": len(fe["onclicks"]),
        "unmatched_routes": len(unmatched_routes),
        "method_mismatches": len(method_mismatches),
        "schema_mismatches": len(schema_mismatches),
        "dead_handlers": len(dead_handlers),
    }

    report = {
        "summary": summary,
        "unmatched_routes": unmatched_routes,
        "method_mismatches": method_mismatches,
        "schema_mismatches": schema_mismatches,
        "dead_handlers": dead_handlers,
        "verified_http_calls": verified_calls,
        "verified_ws_calls": ws_verified,
    }

    report_path = ROOT / "artifacts" / "ui_backend_contract_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run_audit()
    print(json.dumps(rep["summary"], indent=2))
    if rep["unmatched_routes"] or rep["method_mismatches"] or rep["schema_mismatches"] or rep["dead_handlers"]:
        print("\n--- FINDINGS ---")
        for section in ("unmatched_routes", "method_mismatches", "schema_mismatches", "dead_handlers"):
            if rep[section]:
                print(f"[{section}]")
                for item in rep[section]:
                    print(" ", item)
        sys.exit(1)
    print("ALL UI-TO-BACKEND CONTRACTS VERIFIED (0 MISMATCHES).")
    sys.exit(0)
