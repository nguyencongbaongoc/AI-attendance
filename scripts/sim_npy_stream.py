"""
STREAM 2: Simulated .NPY Embedding & Tensor Stream (100% Camera-Free).

1. Runs SCRFDDetector + ArcFaceRecognizer on exact face crops from
   artifacts/sim_human_cam1.mp4 and artifacts/sim_human_cam2.mp4.
2. Persists L2-normalized (512,) float32 embeddings and tensor artifacts:
   - artifacts/sim_npy/student_01_bao_ngoc.npy
   - artifacts/sim_npy/student_02_minh_quan.npy
   - artifacts/sim_npy/gallery_matrix_512d.npy
   - artifacts/sim_npy/sample_nv12_frame.npy
3. Seeds simulated students into app/data/school.db and updates data/embeddings.npy
   + data/embeddings.npy.metadata.json, then verifies ArcFaceRecognizer hot-reload
   and Rust attendance_core.GalleryIndexRs matching (>= 0.60 cosine similarity).
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "artifacts"
SIM_NPY_DIR = ARTIFACTS / "sim_npy"
SCHOOL_DB = ROOT / "app" / "data" / "school.db"
APP_EMBED_DIR = ROOT / "app" / "data" / "embeddings"
DATA_EMBED_NPY = ROOT / "data" / "embeddings.npy"
DATA_EMBED_META = ROOT / "data" / "embeddings.npy.metadata.json"

SIM_STUDENTS = [
    {
        "student_id": "SIM_HS_01",
        "full_name": "Nguyễn Công Bảo Ngọc",
        "class_id": "10A1",
        "gender": "FEMALE",
        "npy_name": "student_01_bao_ngoc.npy",
        "video_path": ARTIFACTS / "sim_human_cam1.mp4",
    },
    {
        "student_id": "SIM_HS_02",
        "full_name": "Trần Minh Quân",
        "class_id": "10A1",
        "gender": "MALE",
        "npy_name": "student_02_minh_quan.npy",
        "video_path": ARTIFACTS / "sim_human_cam2.mp4",
    },
]


def _verify_npy_vector(path: pathlib.Path, expected_shape: Tuple[int, ...]) -> np.ndarray:
    arr = np.load(str(path))
    assert arr.shape == expected_shape, f"{path}: shape {arr.shape} != {expected_shape}"
    assert arr.dtype == np.float32, f"{path}: dtype {arr.dtype} != float32"
    assert not np.isnan(arr).any() and not np.isinf(arr).any(), f"{path}: contains NaN/Inf"
    if len(expected_shape) == 1:
        norm = float(np.linalg.norm(arr))
        assert abs(norm - 1.0) < 1e-4, f"{path}: L2 norm {norm} != 1.0"
    return arr


def generate_npy_artifacts() -> Dict[str, Any]:
    """Extract ArcFace 512D embeddings from simulated videos & persist .npy artifacts."""
    from pipeline_engine.inference import create_scrfd_detector, create_arcface_recognizer
    from pipeline_engine.memory.gpu_frame import GPUFrame, CUDAContext, bgr_to_nv12_cuda, nv12_to_bgr_cuda

    SIM_NPY_DIR.mkdir(parents=True, exist_ok=True)
    APP_EMBED_DIR.mkdir(parents=True, exist_ok=True)

    scrfd = create_scrfd_detector(str(ROOT / "models/scrfd/scrfd_10g_bnkps_fp16.engine"))
    arcface = create_arcface_recognizer(str(ROOT / "models/arcface/glintr100_fp16.engine"))
    assert scrfd.initialize(), "Failed to initialize SCRFDDetector"
    assert arcface.initialize(), "Failed to initialize ArcFaceRecognizer"

    ctx = CUDAContext.current(0)
    vectors: List[np.ndarray] = []
    nv12_saved = False
    extracted: Dict[str, Dict[str, Any]] = {}

    for stu in SIM_STUDENTS:
        vpath = stu["video_path"]
        assert vpath.exists(), f"Missing video for Stream 2: {vpath}"
        cap = cv2.VideoCapture(str(vpath))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 15)
        ok, frame = cap.read()
        cap.release()
        assert ok and frame is not None, f"Failed to read frame from {vpath}"

        h, w = frame.shape[:2]
        t = torch.from_numpy(frame).cuda()
        y, uv = bgr_to_nv12_cuda(t)

        if not nv12_saved:
            y_cpu = y.detach().cpu().numpy()
            uv_cpu = uv.detach().cpu().numpy().reshape(h // 2, w)
            nv12_tensor = np.vstack([y_cpu, uv_cpu]).astype(np.uint8)
            np.save(str(SIM_NPY_DIR / "sample_nv12_frame.npy"), nv12_tensor)
            nv12_saved = True

        gf = GPUFrame(
            camera_id=stu["student_id"],
            frame_id=15,
            width=w,
            height=h,
            cuda_context=ctx,
            y_tensor=y,
            uv_tensor=uv,
        )
        faces = scrfd.detect(gf)
        assert faces, f"No face detected by SCRFD in {vpath}"
        fx1, fy1, fx2, fy2 = [max(0, int(v)) for v in faces[0].bbox]
        bgr = nv12_to_bgr_cuda(y, uv)
        face_crop = bgr[fy1:fy2, fx1:fx2]

        emb_res = arcface.infer_embedding(face_crop)
        vec = emb_res.to_numpy().astype(np.float32).reshape(-1)
        vec = vec / max(float(np.linalg.norm(vec)), 1e-12)
        vec = vec.astype(np.float32)

        out_path = SIM_NPY_DIR / stu["npy_name"]
        np.save(str(out_path), vec)
        _verify_npy_vector(out_path, (512,))

        # Also copy to app/data/embeddings/<student_id>.npy for DB-backed gallery loading
        shutil.copy2(out_path, APP_EMBED_DIR / f"{stu['student_id']}.npy")
        vectors.append(vec)
        extracted[stu["student_id"]] = {
            "full_name": stu["full_name"],
            "npy_path": str(out_path),
            "norm": float(np.linalg.norm(vec)),
            "face_bbox": [fx1, fy1, fx2, fy2],
            "face_conf": round(float(faces[0].confidence), 4),
        }

    # Build (N, 512) gallery tensor
    gallery_mat = np.ascontiguousarray(np.stack(vectors, axis=0), dtype=np.float32)
    gallery_path = SIM_NPY_DIR / "gallery_matrix_512d.npy"
    np.save(str(gallery_path), gallery_mat)
    _verify_npy_vector(gallery_path, (len(vectors), 512))

    # Verify sample_nv12_frame.npy
    nv12_arr = np.load(str(SIM_NPY_DIR / "sample_nv12_frame.npy"))
    assert nv12_arr.dtype == np.uint8 and nv12_arr.ndim == 2

    print(f"[STREAM 2] Generated .npy artifacts in {SIM_NPY_DIR} (gallery shape={gallery_mat.shape})")
    return {
        "students": extracted,
        "gallery_shape": list(gallery_mat.shape),
        "nv12_shape": list(nv12_arr.shape),
        "cross_cosine": float(np.dot(vectors[0], vectors[1])),
    }


def seed_database_and_hot_reload_files() -> None:
    """Seed simulated students into app/data/school.db and update data/embeddings.npy for AIWorker watch."""
    assert SCHOOL_DB.exists(), f"Database not found: {SCHOOL_DB}"
    with sqlite3.connect(str(SCHOOL_DB), timeout=15.0) as conn:
        cur = conn.cursor()
        # Ensure class 10A1 exists
        cur.execute("SELECT class_id FROM classes WHERE class_id='10A1'")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO classes (class_id, class_name, grade_level, academic_year, is_active) "
                "VALUES ('10A1', 'Lớp 10A1', '10', '2026-2027', 1)"
            )
        for stu in SIM_STUDENTS:
            emb_rel = f"app/data/embeddings/{stu['student_id']}.npy"
            cur.execute(
                """
                INSERT INTO students (student_id, full_name, class_id, gender, embedding_path, enrollment_status, is_active)
                VALUES (?, ?, ?, ?, ?, 'ENROLLED', 1)
                ON CONFLICT(student_id) DO UPDATE SET
                    full_name=excluded.full_name,
                    class_id=excluded.class_id,
                    gender=excluded.gender,
                    embedding_path=excluded.embedding_path,
                    enrollment_status='ENROLLED',
                    is_active=1
                """,
                (stu["student_id"], stu["full_name"], stu["class_id"], stu["gender"], emb_rel),
            )
        conn.commit()

    # Also write data/embeddings.npy + data/embeddings.npy.metadata.json so AIWorker._enrollment_watch_loop picks up names
    vecs = []
    person_ids = []
    provenance = []
    for stu in SIM_STUDENTS:
        v = np.load(str(SIM_NPY_DIR / stu["npy_name"])).astype(np.float32)
        vecs.append(v)
        person_ids.append(stu["student_id"])
        provenance.append({
            "person_id": stu["student_id"],
            "name": stu["full_name"],
            "class_id": stu["class_id"],
            "sample_index": 0,
            "quality": 0.99,
        })
    np.save(str(DATA_EMBED_NPY), np.ascontiguousarray(np.stack(vecs, axis=0), dtype=np.float32))
    meta_doc = {
        "schema_version": "1.0",
        "embedding_dimension": 512,
        "dtype": "float32",
        "normalization": "L2",
        "embedding_count": len(person_ids),
        "person_ids": person_ids,
        "sample_provenance": provenance,
        "creation_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    DATA_EMBED_META.write_text(json.dumps(meta_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[STREAM 2] Seeded SIM_HS_01 & SIM_HS_02 into school.db and data/embeddings.npy")


def verify_rust_gallery_and_arcface_reload() -> Dict[str, Any]:
    """Hot-reload ArcFaceRecognizer and verify Rust GalleryIndexRs matching >= 0.60."""
    from attendance_core import GalleryIndexRs
    from pipeline_engine.inference import create_arcface_recognizer

    arcface = create_arcface_recognizer(str(ROOT / "models/arcface/glintr100_fp16.engine"))
    assert arcface.initialize(), "Failed to initialize ArcFaceRecognizer"
    reload_res = arcface.reload_gallery()
    assert reload_res.get("enrolled_count", 0) >= 2, f"Unexpected reload result: {reload_res}"

    # Verify both ArcFace GPU identify() and Rust GalleryIndexRs.search_top1()
    rust_gal = GalleryIndexRs()
    mat_np = np.ascontiguousarray(arcface.embeddings_matrix.detach().cpu().numpy(), dtype=np.float32)
    rust_gal.update_gallery(mat_np)
    assert rust_gal.len() == len(arcface.identities)

    scores: Dict[str, Any] = {}
    for stu in SIM_STUDENTS:
        q = np.load(str(SIM_NPY_DIR / stu["npy_name"])).astype(np.float32)
        q_gpu = torch.from_numpy(q).cuda()

        gpu_matches = arcface.identify(q_gpu, top_k=1)
        assert gpu_matches, f"ArcFace GPU identify returned empty for {stu['student_id']}"
        matched_id, gpu_sim = gpu_matches[0]
        matched_name = arcface.metadata_lookup.get(matched_id, {}).get("name", "")
        assert matched_id == stu["student_id"], f"Expected {stu['student_id']}, got {matched_id}"
        assert matched_name == stu["full_name"], f"Expected {stu['full_name']}, got {matched_name}"
        assert gpu_sim >= 0.60, f"Cosine similarity {gpu_sim} < 0.60"

        rust_match = arcface.identify_top1_cpu(q, threshold=0.60)
        assert rust_match is not None, f"Rust GalleryIndexRs returned None for {stu['student_id']}"
        rust_id, rust_sim = rust_match
        assert rust_id == stu["student_id"] and rust_sim >= 0.60

        scores[stu["student_id"]] = {
            "matched_name": matched_name,
            "gpu_cosine": round(float(gpu_sim), 4),
            "rust_cosine": round(float(rust_sim), 4),
        }

    print(f"[STREAM 2 VERIFY] Rust GalleryIndexRs + ArcFace hot-reload verified: {scores}")
    return {"reload": reload_res, "scores": scores}


def main() -> int:
    info = generate_npy_artifacts()
    seed_database_and_hot_reload_files()
    rel = verify_rust_gallery_and_hot_reload() if False else verify_rust_gallery_and_arcface_reload()
    print(json.dumps({"npy_artifacts": info, "gallery_verification": rel}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
