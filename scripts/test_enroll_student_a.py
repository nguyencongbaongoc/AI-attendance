#!/usr/bin/env python3
"""
End-to-end test: Enroll student "Nguyễn Văn A" (HS2026_10A1_99)
Validates embedding file, DB upsert, ArcFace hot-reload, and inference matching.
"""

import sys
import os
import numpy as np
import torch
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import init_database, get_db_session, get_session_factory, create_tables
from app.models.student import Student, Class, EnrollmentStatusEnum, upsert_student, get_or_create_class
from pipeline_engine.inference.face_recognition import create_arcface_recognizer, ArcFaceConfig
from sqlalchemy import select


def stage1_generate_embedding():
    """Stage 1: Generate canonical embedding file."""
    print("\n" + "="*60)
    print("STAGE 1: Generate Canonical Embedding File")
    print("="*60)
    
    student_id = "HS2026_10A1_99"
    embeddings_dir = Path("app/data/embeddings")
    embeddings_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate synthetic 512D vector (FP32)
    np.random.seed(42)  # Deterministic for testing
    vec = np.random.randn(512).astype(np.float32)
    
    # Strict L2 normalization
    norm = np.linalg.norm(vec)
    vec = vec / norm
    
    # Save to file
    npy_path = embeddings_dir / f"{student_id}.npy"
    np.save(str(npy_path), vec)
    
    # Verify
    loaded = np.load(str(npy_path))
    loaded_norm = np.linalg.norm(loaded)
    shape_ok = loaded.shape == (512,)
    norm_ok = abs(loaded_norm - 1.0) < 1e-6
    
    print(f"  File: {npy_path}")
    print(f"  Shape: {loaded.shape} (expected: (512,)) - {'PASS' if shape_ok else 'FAIL'}")
    print(f"  L2-norm: {loaded_norm:.6f} (expected: 1.000000) - {'PASS' if norm_ok else 'FAIL'}")
    
    return shape_ok and norm_ok, vec


async def stage2_database_upsert():
    """Stage 2: Database upsert."""
    print("\n" + "="*60)
    print("STAGE 2: Database Upsert")
    print("="*60)
    
    await init_database()
    await create_tables()
    
    student_id = "HS2026_10A1_99"
    full_name = "Nguyen Van A"
    class_id = "10A1"
    embedding_path = f"app/data/embeddings/{student_id}.npy"
    
    async with get_db_session() as session:
        # Ensure class exists
        class_obj = await get_or_create_class(session, class_id, class_id)
        print(f"  Class: {class_obj.class_id} - {'EXISTS' if class_obj else 'CREATED'}")
        
        # Upsert student
        student = await upsert_student(
            session=session,
            student_id=student_id,
            full_name=full_name,
            class_id=class_id,
            embedding_path=embedding_path,
        )
        
        # Set enrollment status
        student.enrollment_status = EnrollmentStatusEnum.ENROLLED
        student.is_active = True
        await session.flush()
        
        # Verify by querying
        result = await session.execute(
            select(Student).where(Student.student_id == student_id)
        )
        queried = result.scalar_one_or_none()
        
        if not queried:
            print("  FAIL: Student not found after upsert")
            return False
        
        checks = [
            ("student_id", queried.student_id == student_id),
            ("full_name", queried.full_name == full_name),
            ("class_id", queried.class_id == class_id),
            ("embedding_path", queried.embedding_path == embedding_path),
            ("enrollment_status", queried.enrollment_status == EnrollmentStatusEnum.ENROLLED),
            ("is_active", queried.is_active == True),
        ]
        
        all_pass = True
        for name, check in checks:
            status = "PASS" if check else "FAIL"
            print(f"  {name}: {getattr(queried, name, 'N/A')} - {status}")
            if not check:
                all_pass = False
        
        return all_pass


def stage3_arcface_hot_reload():
    """Stage 3: ArcFace hot-reload and gallery verification."""
    print("\n" + "="*60)
    print("STAGE 3: ArcFace Hot-Reload & Gallery Verification")
    print("="*60)
    
    recognizer = create_arcface_recognizer()
    if not recognizer.initialize():
        print("  FAIL: Recognizer initialization failed")
        return False, None
    
    session_factory = get_session_factory()
    loaded_count = recognizer.load_from_student_db_sync(session_factory)
    
    print(f"  Loaded identities: {loaded_count}")
    print(f"  Gallery shape: {recognizer.embeddings_matrix.shape}")
    print(f"  Identities list: {recognizer.identities}")
    
    student_id = "HS2026_10A1_99"
    expected_name = "Nguyễn Văn A"
    
    # Check identity presence
    identity_present = student_id in recognizer.identities
    print(f"  Identity '{student_id}' in gallery: {'PASS' if identity_present else 'FAIL'}")
    
    # Check metadata
    meta = recognizer.metadata_lookup.get(student_id, {})
    name_match = meta.get("name") == "Nguyen Van A"
    print(f"  Metadata name: {meta.get('name', 'N/A')} (expected: Nguyen Van A) - {'PASS' if name_match else 'FAIL'}")
    
    # Check matrix shape
    matrix_ok = recognizer.embeddings_matrix is not None and recognizer.embeddings_matrix.shape[1] == 512
    print(f"  Matrix shape valid (N, 512): {'PASS' if matrix_ok else 'FAIL'}")
    
    all_pass = identity_present and name_match and matrix_ok
    return all_pass, recognizer


def stage4_inference_matching(recognizer, original_vec):
    """Stage 4: Cosine similarity matching test."""
    print("\n" + "="*60)
    print("STAGE 4: Inference Matching Test")
    print("="*60)
    
    student_id = "HS2026_10A1_99"
    
    # Test 1: Exact vector match
    test_emb = torch.from_numpy(original_vec).to(recognizer.device).float()
    matches = recognizer.identify(test_emb, top_k=3)
    
    print(f"  Exact vector matches: {matches}")
    
    if not matches:
        print("  FAIL: No matches found for exact vector")
        return False
    
    top_id, top_score = matches[0]
    exact_match = top_id == student_id
    exact_score = top_score > 0.95
    print(f"  Top match: {top_id} (score: {top_score:.6f})")
    print(f"  Identity match: {'PASS' if exact_match else 'FAIL'}")
    print(f"  Confidence > 0.95: {'PASS' if exact_score else 'FAIL'}")
    
    # Test 2: Noisy vector (add 2% noise, re-normalize)
    # 2% noise is more realistic for similar face captures
    noise = np.random.randn(512).astype(np.float32) * 0.02
    noisy_vec = original_vec + noise
    noisy_norm = np.linalg.norm(noisy_vec)
    noisy_vec = noisy_vec / noisy_norm
    
    test_emb_noisy = torch.from_numpy(noisy_vec).to(recognizer.device).float()
    matches_noisy = recognizer.identify(test_emb_noisy, top_k=3)
    
    print(f"  Noisy vector matches: {matches_noisy}")
    
    if not matches_noisy:
        print("  FAIL: No matches found for noisy vector")
        return False
    
    top_id_noisy, top_score_noisy = matches_noisy[0]
    noisy_match = top_id_noisy == student_id
    noisy_score = top_score_noisy > 0.85  # Realistic threshold for noisy vector
    print(f"  Top match (noisy): {top_id_noisy} (score: {top_score_noisy:.6f})")
    print(f"  Identity match (noisy): {'PASS' if noisy_match else 'FAIL'}")
    print(f"  Confidence > 0.85 (noisy): {'PASS' if noisy_score else 'FAIL'}")
    
    return exact_match and exact_score and noisy_match and noisy_score


async def main():
    """Run all test stages."""
    print("\n" + "#"*60)
    print("# END-TO-END TEST: Enroll 'Nguyen Van A' (HS2026_10A1_99)")
    print("#"*60)
    
    results = {}
    
    # Stage 1
    stage1_ok, original_vec = stage1_generate_embedding()
    results["Stage 1 (Embedding File)"] = stage1_ok
    
    # Stage 2
    stage2_ok = await stage2_database_upsert()
    results["Stage 2 (Database Upsert)"] = stage2_ok
    
    # Stage 3
    stage3_ok, recognizer = stage3_arcface_hot_reload()
    results["Stage 3 (ArcFace Hot-Reload)"] = stage3_ok
    
    # Stage 4
    stage4_ok = False
    if recognizer and stage1_ok and stage3_ok:
        stage4_ok = stage4_inference_matching(recognizer, original_vec)
    results["Stage 4 (Inference Matching)"] = stage4_ok
    
    # Summary Report
    print("\n" + "#"*60)
    print("# TEST SUMMARY REPORT")
    print("#"*60)
    
    for stage, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {stage}")
    
    overall = all(results.values())
    print(f"\n{'='*60}")
    print(f"OVERALL: {'ALL TESTS PASSED' if overall else 'SOME TESTS FAILED'}")
    print(f"{'='*60}\n")
    
    return overall


if __name__ == "__main__":
    import asyncio
    success = asyncio.run(main())
    sys.exit(0 if success else 1)