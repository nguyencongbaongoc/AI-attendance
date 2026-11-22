"""
Phase 4 Parity & Benchmark Suite: Rust (attendance_core) vs Python Reference.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import attendance_core


def py_batch_iou_and_match(b1: np.ndarray, b2: np.ndarray, iou_thresh: float):
    b1_e = b1[:, None, :]
    b2_e = b2[None, :, :]
    ix1 = np.maximum(b1_e[..., 0], b2_e[..., 0])
    iy1 = np.maximum(b1_e[..., 1], b2_e[..., 1])
    ix2 = np.minimum(b1_e[..., 2], b2_e[..., 2])
    iy2 = np.minimum(b1_e[..., 3], b2_e[..., 3])
    inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
    a1 = np.maximum(0.0, b1_e[..., 2] - b1_e[..., 0]) * np.maximum(0.0, b1_e[..., 3] - b1_e[..., 1])
    a2 = np.maximum(0.0, b2_e[..., 2] - b2_e[..., 0]) * np.maximum(0.0, b2_e[..., 3] - b2_e[..., 1])
    union = a1 + a2 - inter
    iou = np.where(union > 0.0, inter / np.maximum(union, 1e-12), 0.0).astype(np.float32)

    n, m = iou.shape
    det_assigned = [False] * m
    track_assigned = [False] * n
    matches = []
    for i in range(n):
        best_j = -1
        best_iou = iou_thresh
        for j in range(m):
            if det_assigned[j]:
                continue
            val = float(iou[i, j])
            if val >= iou_thresh and (best_j == -1 or val > best_iou):
                best_iou = val
                best_j = j
        if best_j >= 0:
            det_assigned[best_j] = True
            track_assigned[i] = True
            matches.append((i, best_j))
    ut = [i for i in range(n) if not track_assigned[i]]
    ud = [j for j in range(m) if not det_assigned[j]]
    return iou, matches, ut, ud


def py_batch_line_crossing(prev_pts: np.ndarray, curr_pts: np.ndarray, p1, p2) -> np.ndarray:
    lx1, ly1 = p1
    lx2, ly2 = p2
    ldx, ldy = lx2 - lx1, ly2 - ly1
    out = np.zeros((len(prev_pts),), dtype=np.int8)
    for i in range(len(prev_pts)):
        px, py_ = float(prev_pts[i, 0]), float(prev_pts[i, 1])
        cx, cy = float(curr_pts[i, 0]), float(curr_pts[i, 1])
        cp = ldx * (py_ - ly1) - ldy * (px - lx1)
        cc = ldx * (cy - ly1) - ldy * (cx - lx1)
        if cp * cc < 0.0:
            tdx, tdy = cx - px, cy - py_
            d1 = tdx * (ly1 - py_) - tdy * (lx1 - px)
            d2 = tdx * (ly2 - py_) - tdy * (lx2 - px)
            if d1 * d2 <= 0.0:
                out[i] = 1 if cp > 0.0 else -1
    return out


def py_fast_nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float):
    order = np.argsort(-scores, kind="mergesort").tolist()
    suppressed = [False] * len(boxes)
    keep = []
    for pos, i in enumerate(order):
        if suppressed[i]:
            continue
        keep.append(i)
        x1, y1, x2, y2 = boxes[i]
        ai = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        for j in order[pos + 1:]:
            if suppressed[j]:
                continue
            bx1, by1, bx2, by2 = boxes[j]
            ix1, iy1 = max(x1, bx1), max(y1, by1)
            ix2, iy2 = min(x2, bx2), min(y2, by2)
            inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
            if inter > 0.0:
                aj = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
                if inter / (ai + aj - inter) > iou_thresh:
                    suppressed[j] = True
    return keep


def py_gallery_search(mat: np.ndarray, q: np.ndarray, thresh: float):
    q_n = q / max(float(np.linalg.norm(q)), 1e-12)
    sims = mat @ q_n
    idx = int(np.argmax(sims))
    sim = float(sims[idx])
    return (idx, sim) if sim >= thresh else (-1, sim)


def run_parity_and_benchmarks():
    rng = np.random.default_rng(12345)
    timings = []

    # 1. batch_iou_and_match_rs (60 tracks x 80 dets in 4K space)
    t_boxes = rng.uniform(0, 3500, size=(60, 2)).astype(np.float32)
    t_boxes = np.hstack([t_boxes, t_boxes + rng.uniform(40, 250, size=(60, 2)).astype(np.float32)])
    d_boxes = t_boxes[:50].copy() + rng.normal(0, 8, size=(50, 4)).astype(np.float32)
    extra = rng.uniform(0, 3500, size=(30, 2)).astype(np.float32)
    extra = np.hstack([extra, extra + rng.uniform(40, 250, size=(30, 2)).astype(np.float32)])
    d_boxes = np.vstack([d_boxes, extra]).astype(np.float32)

    py_iou, py_m, py_ut, py_ud = py_batch_iou_and_match(t_boxes, d_boxes, 0.3)
    rs_iou, rs_m, rs_ut, rs_ud = attendance_core.batch_iou_and_match_rs(t_boxes, d_boxes, 0.3)
    assert np.allclose(py_iou, rs_iou, atol=1e-5), "IoU matrix mismatch"
    assert py_m == rs_m and py_ut == rs_ut and py_ud == rs_ud, "Matching mismatch"

    iters = 200
    t0 = time.perf_counter()
    for _ in range(iters):
        py_batch_iou_and_match(t_boxes, d_boxes, 0.3)
    py_ms = (time.perf_counter() - t0) * 1000.0 / iters

    t0 = time.perf_counter()
    for _ in range(iters):
        attendance_core.batch_iou_and_match_rs(t_boxes, d_boxes, 0.3)
    rs_ms = (time.perf_counter() - t0) * 1000.0 / iters
    timings.append(("batch_iou_and_match (60x80)", py_ms, rs_ms))

    # 2. batch_line_crossing_rs (500 tracks)
    prev_pts = rng.uniform([100, 800], [3700, 1400], size=(500, 2)).astype(np.float32)
    curr_pts = rng.uniform([100, 800], [3700, 1400], size=(500, 2)).astype(np.float32)
    line_p1, line_p2 = (0.0, 1080.0), (3840.0, 1080.0)
    py_cross = py_batch_line_crossing(prev_pts, curr_pts, line_p1, line_p2)
    rs_cross = attendance_core.batch_line_crossing_rs(prev_pts, curr_pts, line_p1, line_p2)
    assert np.array_equal(py_cross, rs_cross), "Line crossing parity mismatch"

    t0 = time.perf_counter()
    for _ in range(iters):
        py_batch_line_crossing(prev_pts, curr_pts, line_p1, line_p2)
    py_ms = (time.perf_counter() - t0) * 1000.0 / iters
    t0 = time.perf_counter()
    for _ in range(iters):
        attendance_core.batch_line_crossing_rs(prev_pts, curr_pts, line_p1, line_p2)
    rs_ms = (time.perf_counter() - t0) * 1000.0 / iters
    timings.append(("batch_line_crossing (500)", py_ms, rs_ms))

    # 3. fast_nms_rs (300 boxes)
    nms_xy = rng.uniform(0, 3500, size=(300, 2)).astype(np.float32)
    nms_boxes = np.hstack([nms_xy, nms_xy + rng.uniform(30, 300, size=(300, 2)).astype(np.float32)])
    nms_scores = rng.uniform(0.1, 0.99, size=(300,)).astype(np.float32)
    py_keep = py_fast_nms(nms_boxes, nms_scores, 0.45)
    rs_keep = attendance_core.fast_nms_rs(nms_boxes, nms_scores, 0.45)
    assert py_keep == rs_keep, f"NMS parity mismatch: {len(py_keep)} vs {len(rs_keep)}"

    t0 = time.perf_counter()
    for _ in range(iters):
        py_fast_nms(nms_boxes, nms_scores, 0.45)
    py_ms = (time.perf_counter() - t0) * 1000.0 / iters
    t0 = time.perf_counter()
    for _ in range(iters):
        attendance_core.fast_nms_rs(nms_boxes, nms_scores, 0.45)
    rs_ms = (time.perf_counter() - t0) * 1000.0 / iters
    timings.append(("fast_nms (300 boxes)", py_ms, rs_ms))

    # 4. GalleryIndexRs (2000 x 512) + concurrent hot-reload stress
    gal_raw = rng.standard_normal((2000, 512)).astype(np.float32)
    gal_norm = gal_raw / np.linalg.norm(gal_raw, axis=1, keepdims=True)
    q_vec = (gal_norm[777] + rng.normal(0, 0.02, size=(512,))).astype(np.float32)

    gal_rs = attendance_core.GalleryIndexRs()
    assert gal_rs.update_gallery(gal_raw) == 2000
    py_idx, py_sim = py_gallery_search(gal_norm, q_vec, 0.5)
    rs_idx, rs_sim = gal_rs.search_top1(q_vec, 0.5)
    assert py_idx == rs_idx and abs(py_sim - rs_sim) < 1e-5, f"Gallery parity mismatch: {(py_idx, py_sim)} vs {(rs_idx, rs_sim)}"

    # Concurrent hot-reload stress
    errors = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                idx, sim = gal_rs.search_top1(q_vec, 0.5)
                assert idx >= 0 and sim > 0.9
            except Exception as exc:
                errors.append(repr(exc))

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for _ in range(30):
        gal_rs.update_gallery(gal_raw)
        time.sleep(0.001)
    stop.set()
    for t in threads:
        t.join(timeout=2.0)
    assert not errors, f"GalleryIndexRs concurrent stress failed: {errors}"

    t0 = time.perf_counter()
    for _ in range(iters):
        py_gallery_search(gal_norm, q_vec, 0.5)
    py_ms = (time.perf_counter() - t0) * 1000.0 / iters
    t0 = time.perf_counter()
    for _ in range(iters):
        gal_rs.search_top1(q_vec, 0.5)
    rs_ms = (time.perf_counter() - t0) * 1000.0 / iters
    timings.append(("GalleryIndex search (2000x512)", py_ms, rs_ms))

    # 5. scan_expired_files_rs
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        old_ts = time.time() - 7200.0
        for i in range(100):
            p = base / f"sub_{i % 5}" / f"file_{i}.jpg"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * 128)
            if i % 2 == 0:
                os.utime(p, (old_ts, old_ts))

        t0 = time.perf_counter()
        cutoff = time.time() - 3600.0
        py_expired = [str(p) for p in base.rglob("*") if p.is_file() and p.stat().st_mtime < cutoff]
        py_scan_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        rs_expired, total_bytes = attendance_core.scan_expired_files_rs(str(base), 3600.0)
        rs_scan_ms = (time.perf_counter() - t0) * 1000.0

        assert len(py_expired) == len(rs_expired) == 50
        assert total_bytes == 50 * 128
        timings.append(("scan_expired_files (100 files)", py_scan_ms, rs_scan_ms))

    print("\n=== PYTHON vs RUST (attendance_core) PARITY & LATENCY BENCHMARK ===")
    print(f"{'Kernel':<34} | {'Python (ms)':>11} | {'Rust (ms)':>10} | {'Speedup':>8}")
    print("-" * 72)
    for name, p_ms, r_ms in timings:
        speedup = p_ms / max(r_ms, 1e-6)
        print(f"{name:<34} | {p_ms:>11.4f} | {r_ms:>10.4f} | {speedup:>7.2f}x")
    print("[PASS] All Rust vs Python parity checks (atol=1e-5) & concurrent stress passed!\n")


if __name__ == "__main__":
    run_parity_and_benchmarks()
