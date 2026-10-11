#!/usr/bin/env python
"""
Phase 30A — ArcFace Enrollment Database CLI.

Builds the canonical ArcFace enrollment database from source images.
Reuses Phase 13 enrollment pipeline, Phase 17 quality assessment, Phase 19 matching.

This module does NOT implement attendance logic.
This module does NOT access cameras.
This module does NOT implement live enrollment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config.paths import get_project_paths
from app.vision.enrollment import (
    DEFAULT_DUPLICATE_THRESHOLD,
    DEFAULT_QUALITY_THRESHOLDS,
    EnrollmentConfig,
    build_enrollment_database,
    enroll_from_sources,
    load_enrollment_database,
    process_image_enrollment,
)
from app.vision.enrollment_contract import (
    EnrollmentDatabaseMetadata,
    EnrollmentInputContract,
    EnrollmentResult,
    SourceType,
    create_enrollment_input,
    validate_enrollment_database,
)
from app.vision.face_quality import (
    DEFAULT_QUALITY_THRESHOLDS as FACE_QUALITY_THRESHOLDS,
    FaceQualityAssessor,
    QualityClass,
    create_quality_assessor,
)
from app.vision.matching import (
    load_matching_database,
    match_identity,
    match_identity_from_database_dir,
)
from app.vision.matching_contract import MatchingConfig, MatchStatus


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class RejectionRecord:
    """Record of a rejected enrollment image."""
    person_id: str
    source_image: str
    status: str  # "REJECTED"
    reason: str
    detection_confidence: Optional[float] = None
    bbox: Optional[List[float]] = None
    face_count: int = 0


@dataclass
class EnrollmentReport:
    """Complete enrollment report."""
    total_persons: int = 0
    total_source_images: int = 0
    accepted_images: int = 0
    rejected_images: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=dict)
    embeddings_generated: int = 0
    embedding_dimension: int = 512
    database_version: str = "1.0"
    model_identifier: str = "arcface/glintr100.onnx"
    preprocessing_version: str = "1.0"
    source_dataset: str = ""
    generation_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    rejections: List[RejectionRecord] = field(default_factory=list)
    person_embedding_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class DatabaseInspection:
    """Database inspection result."""
    embeddings_path: str
    metadata_path: str
    embeddings_shape: Tuple[int, int]
    embeddings_dtype: str
    embeddings_finite: bool
    embeddings_normalized: bool
    metadata: EnrollmentDatabaseMetadata
    person_counts: Dict[str, int]
    validation_passed: bool
    validation_error: Optional[str] = None


# =============================================================================
# DATASET DISCOVERY
# =============================================================================

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def discover_enrollment_dataset(dataset_root: Path) -> List[EnrollmentInputContract]:
    """
    Discover enrollment images from person-based directory structure.
    
    Expected structure:
        dataset_root/
            PERSON_ID_1/
                image1.jpg
                image2.jpg
            PERSON_ID_2/
                image1.png
                ...
    
    Args:
        dataset_root: Root directory containing person subdirectories
        
    Returns:
        List of EnrollmentInputContract for each valid image
    """
    contracts = []
    
    if not dataset_root.exists():
        raise ValueError(f"Dataset root does not exist: {dataset_root}")
    
    if not dataset_root.is_dir():
        raise ValueError(f"Dataset root is not a directory: {dataset_root}")
    
    # Get person directories (sorted for determinism)
    person_dirs = sorted([d for d in dataset_root.iterdir() if d.is_dir()])
    
    for person_dir in person_dirs:
        person_id = person_dir.name
        
        # Validate person_id format (non-empty, no special chars that could cause issues)
        if not person_id or not person_id.strip():
            continue
        
        # Find image files (sorted for determinism)
        image_files = sorted([
            f for f in person_dir.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ])
        
        for image_file in image_files:
            contract = create_enrollment_input(
                person_id=person_id,
                source_type=SourceType.IMAGE,
                source=str(image_file),
                timestamp=datetime.utcnow().isoformat() + "Z",
            )
            contracts.append(contract)
    
    return contracts


# =============================================================================
# ENROLLMENT PIPELINE
# =============================================================================

def create_enrollment_config(
    quality_thresholds: Optional[Dict[str, float]] = None,
    duplicate_threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    face_detector_confidence: float = 0.5,
    face_detector_nms: float = 0.4,
    arcface_providers: Tuple[str, ...] = ("CUDAExecutionProvider", "CPUExecutionProvider"),
) -> EnrollmentConfig:
    """Create enrollment configuration with custom thresholds."""
    thresholds = DEFAULT_QUALITY_THRESHOLDS.copy()
    if quality_thresholds:
        thresholds.update(quality_thresholds)
    
    return EnrollmentConfig(
        face_detector_confidence_threshold=face_detector_confidence,
        face_detector_nms_threshold=face_detector_nms,
        quality_thresholds=thresholds,
        duplicate_threshold=duplicate_threshold,
        arcface_providers=arcface_providers,
    )


def run_enrollment(
    contracts: List[EnrollmentInputContract],
    config: EnrollmentConfig,
    output_dir: Path,
    use_quality_assessor: bool = True,
) -> Tuple[Path, Path, EnrollmentReport]:
    """
    Run enrollment pipeline and generate report.
    
    Args:
        contracts: List of enrollment input contracts
        config: Enrollment configuration
        output_dir: Output directory for database
        use_quality_assessor: Whether to use Phase 17 FaceQualityAssessor
        
    Returns:
        Tuple of (embeddings_path, metadata_path, report)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize quality assessor if requested
    quality_assessor = None
    if use_quality_assessor:
        quality_assessor = create_quality_assessor(FACE_QUALITY_THRESHOLDS)
    
    # Run enrollment
    results = []
    report = EnrollmentReport()
    report.source_dataset = str(output_dir.parent)  # Will be updated
    
    # Group contracts by person for reporting
    person_images: Dict[str, List[EnrollmentInputContract]] = {}
    for contract in contracts:
        if contract.person_id not in person_images:
            person_images[contract.person_id] = []
        person_images[contract.person_id].append(contract)
    
    report.total_persons = len(person_images)
    report.total_source_images = len(contracts)
    
    # Process each contract
    for contract in contracts:
        result = process_image_enrollment(
            image_path=contract.source,
            person_id=contract.person_id,
            config=config,
            timestamp=contract.timestamp,
        )
        results.append(result)
        
        # Update report
        report.accepted_images += result.get_accepted_count()
        report.rejected_images += result.get_rejected_count()
        
        # Track rejections
        for rejected in result.rejected_samples:
            reason = rejected.get("rejection_reason", "unknown")
            report.rejection_reasons[reason] = report.rejection_reasons.get(reason, 0) + 1
            
            rejection_record = RejectionRecord(
                person_id=contract.person_id,
                source_image=contract.source,
                status="REJECTED",
                reason=reason,
                detection_confidence=rejected.get("detection_confidence"),
                bbox=rejected.get("bbox"),
                face_count=rejected.get("face_count", 0),
            )
            report.rejections.append(rejection_record)
    
    # Build database
    model_sha256 = config.arcface_inference.model_def.expected_sha256
    embeddings_path, metadata_path = build_enrollment_database(
        results, str(output_dir), model_sha256
    )
    
    # Load metadata for report
    embeddings, metadata = load_enrollment_database(str(output_dir))
    report.embeddings_generated = metadata.embedding_count
    report.embedding_dimension = metadata.embedding_dimension
    report.database_version = metadata.schema_version
    report.model_identifier = f"{metadata.model_id}/{metadata.model_filename}"
    report.preprocessing_version = metadata.enrollment_contract_version
    
    # Count embeddings per person
    for person_id in metadata.person_ids:
        count = sum(1 for p in metadata.sample_provenance if p.get("person_id") == person_id)
        report.person_embedding_counts[person_id] = count
    
    return embeddings_path, metadata_path, report


# =============================================================================
# DATABASE VALIDATION
# =============================================================================

def validate_database(database_dir: Path) -> DatabaseInspection:
    """
    Validate enrollment database integrity.
    
    Args:
        database_dir: Directory containing embeddings.npy and metadata.json
        
    Returns:
        DatabaseInspection with validation results
    """
    embeddings_path = database_dir / "embeddings.npy"
    metadata_path = database_dir / "embeddings.npy.metadata.json"
    
    inspection = DatabaseInspection(
        embeddings_path=str(embeddings_path),
        metadata_path=str(metadata_path),
        embeddings_shape=(0, 0),
        embeddings_dtype="",
        embeddings_finite=False,
        embeddings_normalized=False,
        metadata=None,
        person_counts={},
        validation_passed=False,
    )
    
    try:
        # Load and validate
        embeddings, metadata = load_enrollment_database(str(database_dir))
        
        inspection.embeddings_shape = embeddings.shape
        inspection.embeddings_dtype = str(embeddings.dtype)
        inspection.embeddings_finite = np.isfinite(embeddings).all()
        
        # Check L2 normalization
        norms = np.linalg.norm(embeddings, axis=1)
        inspection.embeddings_normalized = np.allclose(norms, 1.0, atol=1e-5)
        
        inspection.metadata = metadata
        
        # Count embeddings per person
        for person_id in metadata.person_ids:
            count = sum(1 for p in metadata.sample_provenance if p.get("person_id") == person_id)
            inspection.person_counts[person_id] = count
        
        # Final validation
        is_valid, error = validate_enrollment_database(embeddings, metadata)
        inspection.validation_passed = is_valid
        inspection.validation_error = error
        
    except Exception as e:
        inspection.validation_passed = False
        inspection.validation_error = str(e)
    
    return inspection


# =============================================================================
# PHASE 19 INTEGRATION TEST
# =============================================================================

def run_phase19_integration_test(
    database_dir: Path,
    test_images: List[Tuple[str, str]],  # (person_id, image_path)
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """
    Test Phase 19 matching with the generated database.
    
    Args:
        database_dir: Directory containing enrollment database
        test_images: List of (expected_person_id, image_path) for testing
        threshold: Matching threshold
        
    Returns:
        Dictionary with test results
    """
    results = {
        "database_loaded": False,
        "matching_tests": [],
        "overall_pass": False,
    }
    
    try:
        # Load database for matching
        context = load_matching_database(str(database_dir))
        context.config = MatchingConfig(match_threshold=threshold, ambiguity_margin=0.05)
        results["database_loaded"] = True
        
        # Test each image
        correct_matches = 0
        total_tests = 0
        
        for expected_person_id, image_path in test_images:
            total_tests += 1
            
            # Process image to get embedding
            config = create_enrollment_config()
            result = process_image_enrollment(
                image_path=image_path,
                person_id=expected_person_id,  # Not used for matching, just for processing
                config=config,
            )
            
            if result.get_accepted_count() == 0:
                results["matching_tests"].append({
                    "image": image_path,
                    "expected_person": expected_person_id,
                    "status": "NO_FACE_DETECTED",
                    "match": False,
                })
                continue
            
            # Use first accepted embedding as query
            query_embedding = result.accepted_samples[0].embedding
            
            # Match against database
            match_result = match_identity(query_embedding, context)
            
            matched = (match_result.status == MatchStatus.MATCH and 
                      match_result.person_id == expected_person_id)
            
            if matched:
                correct_matches += 1
            
            results["matching_tests"].append({
                "image": image_path,
                "expected_person": expected_person_id,
                "matched_person": match_result.person_id,
                "similarity": match_result.similarity,
                "status": match_result.status.value,
                "match": matched,
            })
        
        results["overall_pass"] = (correct_matches == total_tests and total_tests > 0)
        results["correct_matches"] = correct_matches
        results["total_tests"] = total_tests
        
    except Exception as e:
        results["error"] = str(e)
        results["overall_pass"] = False
    
    return results


# =============================================================================
# DETERMINISTIC REGENERATION TEST
# =============================================================================

def run_deterministic_regeneration_test(
    contracts: List[EnrollmentInputContract],
    config: EnrollmentConfig,
    output_dir1: Path,
    output_dir2: Path,
) -> Dict[str, Any]:
    """
    Test that identical inputs produce identical database.
    
    Args:
        contracts: Enrollment contracts
        config: Enrollment configuration
        output_dir1: First output directory
        output_dir2: Second output directory
        
    Returns:
        Dictionary with comparison results
    """
    results = {
        "embeddings_identical": False,
        "metadata_identical": False,
        "embeddings_shape_match": False,
        "person_ids_match": False,
        "sample_order_match": False,
    }
    
    try:
        # First generation
        embeddings_path1, metadata_path1, _ = run_enrollment(
            contracts, config, output_dir1
        )
        
        # Second generation
        embeddings_path2, metadata_path2, _ = run_enrollment(
            contracts, config, output_dir2
        )
        
        # Load both
        embeddings1, metadata1 = load_enrollment_database(str(output_dir1))
        embeddings2, metadata2 = load_enrollment_database(str(output_dir2))
        
        # Compare embeddings
        results["embeddings_shape_match"] = (embeddings1.shape == embeddings2.shape)
        
        if results["embeddings_shape_match"]:
            results["embeddings_identical"] = np.allclose(embeddings1, embeddings2, atol=1e-6)
        
        # Compare metadata (excluding timestamps)
        meta1_dict = metadata1.to_dict()
        meta2_dict = metadata2.to_dict()
        
        # Remove timestamps for comparison
        meta1_dict.pop("creation_timestamp", None)
        meta2_dict.pop("creation_timestamp", None)
        
        # Also remove per-sample timestamps from provenance
        for prov in meta1_dict.get("sample_provenance", []):
            prov.pop("timestamp", None)
            # Remove time fields from nested objects
            if "face_detection" in prov and isinstance(prov["face_detection"], dict):
                prov["face_detection"].pop("detection_time_ms", None)
            if "preprocessing" in prov and isinstance(prov["preprocessing"], dict):
                prov["preprocessing"].pop("preprocessing_time_ms", None)
            if "arcface_model" in prov and isinstance(prov["arcface_model"], dict):
                prov["arcface_model"].pop("inference_time_ms", None)
        for prov in meta2_dict.get("sample_provenance", []):
            prov.pop("timestamp", None)
            if "face_detection" in prov and isinstance(prov["face_detection"], dict):
                prov["face_detection"].pop("detection_time_ms", None)
            if "preprocessing" in prov and isinstance(prov["preprocessing"], dict):
                prov["preprocessing"].pop("preprocessing_time_ms", None)
            if "arcface_model" in prov and isinstance(prov["arcface_model"], dict):
                prov["arcface_model"].pop("inference_time_ms", None)
        
        results["metadata_identical"] = (meta1_dict == meta2_dict)
        results["person_ids_match"] = (metadata1.person_ids == metadata2.person_ids)
        
        # Check sample order (by provenance)
        prov1 = [p.get("sample_id", "") for p in metadata1.sample_provenance]
        prov2 = [p.get("sample_id", "") for p in metadata2.sample_provenance]
        results["sample_order_match"] = (prov1 == prov2)
        
    except Exception as e:
        results["error"] = str(e)
    
    return results


# =============================================================================
# REPORT GENERATION
# =============================================================================

def generate_report_json(report: EnrollmentReport, output_path: Path) -> None:
    """Generate JSON report."""
    report_dict = {
        "summary": {
            "total_persons": report.total_persons,
            "total_source_images": report.total_source_images,
            "accepted_images": report.accepted_images,
            "rejected_images": report.rejected_images,
            "embeddings_generated": report.embeddings_generated,
            "embedding_dimension": report.embedding_dimension,
            "database_version": report.database_version,
            "model_identifier": report.model_identifier,
            "preprocessing_version": report.preprocessing_version,
            "source_dataset": report.source_dataset,
            "generation_timestamp": report.generation_timestamp,
        },
        "rejection_reasons": report.rejection_reasons,
        "person_embedding_counts": report.person_embedding_counts,
        "rejections": [
            {
                "person_id": r.person_id,
                "source_image": r.source_image,
                "status": r.status,
                "reason": r.reason,
                "detection_confidence": r.detection_confidence,
                "bbox": r.bbox,
                "face_count": r.face_count,
            }
            for r in report.rejections
        ],
    }
    
    with open(output_path, "w") as f:
        json.dump(report_dict, f, indent=2)


def generate_report_markdown(report: EnrollmentReport, output_path: Path) -> None:
    """Generate Markdown report."""
    lines = [
        "# Phase 30A Enrollment Report",
        "",
        f"**Generated:** {report.generation_timestamp}",
        f"**Source Dataset:** {report.source_dataset}",
        "",
        "## Summary",
        "",
        f"- **Total Persons:** {report.total_persons}",
        f"- **Total Source Images:** {report.total_source_images}",
        f"- **Accepted Images:** {report.accepted_images}",
        f"- **Rejected Images:** {report.rejected_images}",
        f"- **Embeddings Generated:** {report.embeddings_generated}",
        f"- **Embedding Dimension:** {report.embedding_dimension}",
        f"- **Database Version:** {report.database_version}",
        f"- **Model:** {report.model_identifier}",
        f"- **Preprocessing Version:** {report.preprocessing_version}",
        "",
        "## Rejection Reasons",
        "",
    ]
    
    for reason, count in sorted(report.rejection_reasons.items()):
        lines.append(f"- {reason}: {count}")
    
    lines.extend([
        "",
        "## Person Embedding Counts",
        "",
    ])
    
    for person_id, count in sorted(report.person_embedding_counts.items()):
        lines.append(f"- **{person_id}**: {count} embeddings")
    
    lines.extend([
        "",
        "## Rejected Images",
        "",
        "| Person ID | Source Image | Reason | Confidence | Face Count |",
        "|-----------|--------------|--------|------------|------------|",
    ])
    
    for r in report.rejections:
        source_name = Path(r.source_image).name
        confidence = f"{r.detection_confidence:.3f}" if r.detection_confidence else "N/A"
        lines.append(f"| {r.person_id} | {source_name} | {r.reason} | {confidence} | {r.face_count} |")
    
    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def generate_inspection_report(inspection: DatabaseInspection, output_path: Path) -> None:
    """Generate database inspection report."""
    lines = [
        "# Phase 30A Database Inspection",
        "",
        f"**Database:** {inspection.embeddings_path}",
        "",
        "## Embeddings",
        "",
        f"- **Shape:** {inspection.embeddings_shape}",
        f"- **Dtype:** {inspection.embeddings_dtype}",
        f"- **All Finite:** {inspection.embeddings_finite}",
        f"- **L2 Normalized:** {inspection.embeddings_normalized}",
        "",
        "## Metadata",
        "",
    ]
    
    if inspection.metadata:
        lines.extend([
            f"- **Schema Version:** {inspection.metadata.schema_version}",
            f"- **Embedding Dimension:** {inspection.metadata.embedding_dimension}",
            f"- **Dtype:** {inspection.metadata.dtype}",
            f"- **Normalization:** {inspection.metadata.normalization}",
            f"- **Model ID:** {inspection.metadata.model_id}",
            f"- **Model Filename:** {inspection.metadata.model_filename}",
            f"- **Model SHA256:** {inspection.metadata.model_sha256[:16]}...",
            f"- **Contract Version:** {inspection.metadata.enrollment_contract_version}",
            f"- **Embedding Count:** {inspection.metadata.embedding_count}",
            f"- **Person IDs:** {', '.join(inspection.metadata.person_ids)}",
            f"- **Creation Timestamp:** {inspection.metadata.creation_timestamp}",
            "",
        ])
    
    lines.extend([
        "## Person Counts",
        "",
    ])
    
    for person_id, count in sorted(inspection.person_counts.items()):
        lines.append(f"- **{person_id}**: {count} embeddings")
    
    lines.extend([
        "",
        "## Validation",
        "",
        f"- **Passed:** {inspection.validation_passed}",
    ])
    
    if inspection.validation_error:
        lines.append(f"- **Error:** {inspection.validation_error}")
    
    with open(output_path, "w") as f:
        f.write("\n".join(lines))


# =============================================================================
# CLI COMMANDS
# =============================================================================

def cmd_build(args: argparse.Namespace) -> int:
    """Build enrollment database from dataset."""
    dataset_root = Path(args.dataset)
    output_dir = Path(args.output)
    
    print(f"Discovering enrollment dataset: {dataset_root}")
    contracts = discover_enrollment_dataset(dataset_root)
    
    if not contracts:
        print("ERROR: No valid enrollment images found")
        return 1
    
    print(f"Found {len(contracts)} images for {len(set(c.person_id for c in contracts))} persons")
    
    config = create_enrollment_config(
        quality_thresholds=json.loads(args.quality_thresholds) if args.quality_thresholds else None,
        duplicate_threshold=args.duplicate_threshold,
        face_detector_confidence=args.detector_confidence,
        face_detector_nms=args.detector_nms,
    )
    
    print("Running enrollment pipeline...")
    start_time = time.perf_counter()
    
    embeddings_path, metadata_path, report = run_enrollment(
        contracts, config, output_dir, use_quality_assessor=not args.no_quality
    )
    
    elapsed = time.perf_counter() - start_time
    print(f"Enrollment completed in {elapsed:.2f}s")
    print(f"  Accepted: {report.accepted_images}")
    print(f"  Rejected: {report.rejected_images}")
    print(f"  Embeddings: {report.embeddings_generated}")
    print(f"  Database: {embeddings_path}")
    print(f"  Metadata: {metadata_path}")
    
    # Generate reports
    if args.report:
        report_dir = Path(args.report)
        report_dir.mkdir(parents=True, exist_ok=True)
        
        json_path = report_dir / "enrollment_report.json"
        md_path = report_dir / "enrollment_report.md"
        
        generate_report_json(report, json_path)
        generate_report_markdown(report, md_path)
        
        print(f"Reports: {json_path}, {md_path}")
    
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate enrollment database."""
    database_dir = Path(args.database)
    
    print(f"Validating database: {database_dir}")
    inspection = validate_database(database_dir)
    
    print(f"  Embeddings shape: {inspection.embeddings_shape}")
    print(f"  Dtype: {inspection.embeddings_dtype}")
    print(f"  All finite: {inspection.embeddings_finite}")
    print(f"  L2 normalized: {inspection.embeddings_normalized}")
    print(f"  Validation passed: {inspection.validation_passed}")
    
    if inspection.validation_error:
        print(f"  Validation error: {inspection.validation_error}")
    
    if inspection.metadata:
        print(f"  Persons: {len(inspection.metadata.person_ids)}")
        print(f"  Total embeddings: {inspection.metadata.embedding_count}")
        for person_id, count in sorted(inspection.person_counts.items()):
            print(f"    {person_id}: {count}")
    
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        generate_inspection_report(inspection, report_path)
        print(f"Inspection report: {report_path}")
    
    return 0 if inspection.validation_passed else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    """Inspect enrollment database."""
    database_dir = Path(args.database)
    
    print(f"Inspecting database: {database_dir}")
    inspection = validate_database(database_dir)
    
    print("\n" + "=" * 50)
    print("ENROLLMENT DATABASE INSPECTION")
    print("=" * 50)
    print(f"Embeddings: {inspection.embeddings_shape[0]} x {inspection.embeddings_shape[1]}")
    print(f"Dtype: {inspection.embeddings_dtype}")
    print(f"Finite: {inspection.embeddings_finite}")
    print(f"L2 Normalized: {inspection.embeddings_normalized}")
    print(f"Validation: {'PASS' if inspection.validation_passed else 'FAIL'}")
    
    if inspection.metadata:
        print(f"\nSchema Version: {inspection.metadata.schema_version}")
        print(f"Model: {inspection.metadata.model_id}/{inspection.metadata.model_filename}")
        print(f"Contract Version: {inspection.metadata.enrollment_contract_version}")
        print(f"Embedding Count: {inspection.metadata.embedding_count}")
        print(f"Persons: {len(inspection.metadata.person_ids)}")
        print(f"Created: {inspection.metadata.creation_timestamp}")
    
    print("\nPerson Embedding Counts:")
    for person_id, count in sorted(inspection.person_counts.items()):
        print(f"  {person_id}: {count}")
    
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        generate_inspection_report(inspection, report_path)
        print(f"\nReport saved: {report_path}")
    
    return 0 if inspection.validation_passed else 1


def cmd_test_phase19(args: argparse.Namespace) -> int:
    """Test Phase 19 integration with enrollment database."""
    database_dir = Path(args.database)
    test_dataset = Path(args.test_dataset) if args.test_dataset else None
    
    print(f"Testing Phase 19 integration with: {database_dir}")
    
    # Collect test images
    test_images = []
    if test_dataset and test_dataset.exists():
        for person_dir in sorted(test_dataset.iterdir()):
            if person_dir.is_dir():
                person_id = person_dir.name
                for img_file in sorted(person_dir.iterdir()):
                    if img_file.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
                        test_images.append((person_id, str(img_file)))
    
    if not test_images:
        print("WARNING: No test images provided, skipping matching tests")
        return 0
    
    print(f"Running {len(test_images)} matching tests...")
    results = run_phase19_integration_test(database_dir, test_images, args.threshold)
    
    print(f"Database loaded: {results['database_loaded']}")
    print(f"Correct matches: {results.get('correct_matches', 0)}/{results.get('total_tests', 0)}")
    print(f"Overall: {'PASS' if results['overall_pass'] else 'FAIL'}")
    
    for test in results.get("matching_tests", []):
        status = "✓" if test["match"] else "✗"
        print(f"  {status} {Path(test['image']).name}: expected={test['expected_person']}, "
              f"got={test['matched_person']}, sim={test['similarity']:.4f}, status={test['status']}")
    
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Test report: {report_path}")
    
    return 0 if results["overall_pass"] else 1


def cmd_determinism(args: argparse.Namespace) -> int:
    """Test deterministic regeneration."""
    dataset_root = Path(args.dataset)
    output_dir1 = Path(args.output1)
    output_dir2 = Path(args.output2)
    
    print(f"Testing deterministic regeneration from: {dataset_root}")
    contracts = discover_enrollment_dataset(dataset_root)
    
    if not contracts:
        print("ERROR: No valid enrollment images found")
        return 1
    
    config = create_enrollment_config()
    
    print("Running first generation...")
    results = run_deterministic_regeneration_test(contracts, config, output_dir1, output_dir2)
    
    print(f"Embeddings identical: {results['embeddings_identical']}")
    print(f"Metadata identical: {results['metadata_identical']}")
    print(f"Shape match: {results['embeddings_shape_match']}")
    print(f"Person IDs match: {results['person_ids_match']}")
    print(f"Sample order match: {results['sample_order_match']}")
    
    overall = all([
        results["embeddings_identical"],
        results["metadata_identical"],
        results["embeddings_shape_match"],
        results["person_ids_match"],
        results["sample_order_match"],
    ])
    
    print(f"Overall: {'PASS' if overall else 'FAIL'}")
    
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Report: {report_path}")
    
    return 0 if overall else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 30A — ArcFace Enrollment Database CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build enrollment database from person-based dataset
  python scripts/phase30a_enrollment.py build --dataset data/enrollment --output data/enrollment_db --report reports/enrollment
  
  # Validate existing database
  python scripts/phase30a_enrollment.py validate --database data/enrollment_db --report reports/inspection
  
  # Inspect database
  python scripts/phase30a_enrollment.py inspect --database data/enrollment_db
  
  # Test Phase 19 integration
  python scripts/phase30a_enrollment.py test-phase19 --database data/enrollment_db --test-dataset data/enrollment_test
  
  # Test deterministic regeneration
  python scripts/phase30a_enrollment.py determinism --dataset data/enrollment --output1 data/enrollment_db_1 --output2 data/enrollment_db_2
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Build command
    build_parser = subparsers.add_parser("build", help="Build enrollment database from dataset")
    build_parser.add_argument("--dataset", required=True, help="Root directory with person subdirectories")
    build_parser.add_argument("--output", required=True, help="Output directory for database")
    build_parser.add_argument("--report", help="Directory for report output")
    build_parser.add_argument("--quality-thresholds", help="JSON string with custom quality thresholds")
    build_parser.add_argument("--duplicate-threshold", type=float, default=DEFAULT_DUPLICATE_THRESHOLD)
    build_parser.add_argument("--detector-confidence", type=float, default=0.5)
    build_parser.add_argument("--detector-nms", type=float, default=0.4)
    build_parser.add_argument("--no-quality", action="store_true", help="Disable Phase 17 quality assessor")
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate enrollment database")
    validate_parser.add_argument("--database", required=True, help="Database directory")
    validate_parser.add_argument("--report", help="Output report path")
    
    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect enrollment database")
    inspect_parser.add_argument("--database", required=True, help="Database directory")
    inspect_parser.add_argument("--report", help="Output report path")
    
    # Test Phase 19 command
    test_parser = subparsers.add_parser("test-phase19", help="Test Phase 19 matching integration")
    test_parser.add_argument("--database", required=True, help="Database directory")
    test_parser.add_argument("--test-dataset", help="Test dataset directory (same structure as enrollment)")
    test_parser.add_argument("--threshold", type=float, default=0.5, help="Matching threshold")
    test_parser.add_argument("--report", help="Output report path")
    
    # Determinism command
    det_parser = subparsers.add_parser("determinism", help="Test deterministic regeneration")
    det_parser.add_argument("--dataset", required=True, help="Root directory with person subdirectories")
    det_parser.add_argument("--output1", required=True, help="First output directory")
    det_parser.add_argument("--output2", required=True, help="Second output directory")
    det_parser.add_argument("--report", help="Output report path")
    
    args = parser.parse_args()
    
    if args.command == "build":
        return cmd_build(args)
    elif args.command == "validate":
        return cmd_validate(args)
    elif args.command == "inspect":
        return cmd_inspect(args)
    elif args.command == "test-phase19":
        return cmd_test_phase19(args)
    elif args.command == "determinism":
        return cmd_determinism(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())