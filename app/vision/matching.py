"""
Phase 14 — ArcFace Identity Matching Implementation.

Implements offline identity matching against a Phase 13 enrollment database.
Reuses Phase 12 ArcFace inference and Phase 13 database validation.

This module does NOT access cameras.
This module does NOT implement detection, tracking, attendance, or hard-pose correction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.vision.enrollment import load_enrollment_database
from app.vision.enrollment_contract import EnrollmentDatabaseMetadata
from app.vision.matching_contract import (
    CandidateMatch,
    IdentityMatchResult,
    MatchStatus,
    MatchingConfig,
    PersonLevelMatch,
    QueryEmbeddingContract,
    compute_cosine_similarity,
    validate_database_for_matching,
    validate_query_embedding,
)


@dataclass
class MatchingContext:
    """Context for matching operations."""
    database_embeddings: np.ndarray
    database_metadata: EnrollmentDatabaseMetadata
    config: MatchingConfig


def load_matching_database(database_dir: str) -> MatchingContext:
    """
    Load and validate enrollment database for matching.
    
    Args:
        database_dir: Directory containing embeddings.npy and embeddings.npy.metadata.json
        
    Returns:
        MatchingContext with validated database
        
    Raises:
        ValueError: If database is invalid or missing
    """
    embeddings, metadata = load_enrollment_database(database_dir)
    
    # Additional validation for matching
    is_valid, error = validate_database_for_matching(embeddings, metadata)
    if not is_valid:
        raise ValueError(f"Database validation failed for matching: {error}")
    
    config = MatchingConfig()
    
    return MatchingContext(
        database_embeddings=embeddings,
        database_metadata=metadata,
        config=config,
    )


def aggregate_person_matches(
    candidate_matches: List[CandidateMatch],
    policy: str = "best_sample",
) -> List[PersonLevelMatch]:
    """
    Aggregate sample-level matches to person-level matches.
    
    Args:
        candidate_matches: List of candidate matches (sample-level)
        policy: Aggregation policy ("best_sample" or "average")
        
    Returns:
        List of person-level matches sorted by best similarity (descending)
    """
    # Group by person_id
    person_groups: Dict[str, List[CandidateMatch]] = {}
    for match in candidate_matches:
        if match.person_id not in person_groups:
            person_groups[match.person_id] = []
        person_groups[match.person_id].append(match)
    
    person_matches = []
    
    for person_id, matches in person_groups.items():
        if policy == "best_sample":
            # Use best sample per person
            best_match = max(matches, key=lambda m: m.similarity)
            person_match = PersonLevelMatch(
                person_id=person_id,
                best_sample_id=best_match.sample_id,
                best_similarity=best_match.similarity,
                sample_count=len(matches),
                all_similarities=[m.similarity for m in matches],
            )
        elif policy == "average":
            # Average similarity across samples
            avg_similarity = sum(m.similarity for m in matches) / len(matches)
            best_match = max(matches, key=lambda m: m.similarity)
            person_match = PersonLevelMatch(
                person_id=person_id,
                best_sample_id=best_match.sample_id,
                best_similarity=avg_similarity,
                sample_count=len(matches),
                all_similarities=[m.similarity for m in matches],
            )
        else:
            raise ValueError(f"Unknown person_aggregation_policy: {policy}")
        
        person_matches.append(person_match)
    
    # Sort by best similarity descending
    person_matches.sort(key=lambda p: p.best_similarity, reverse=True)
    
    return person_matches


def match_identity(
    query_embedding: np.ndarray,
    context: MatchingContext,
    query_provenance: Optional[Dict[str, Any]] = None,
) -> IdentityMatchResult:
    """
    Perform identity matching against enrollment database.
    
    Args:
        query_embedding: 512D float32 L2-normalized query embedding
        context: MatchingContext with validated database
        query_provenance: Optional provenance for the query
        
    Returns:
        IdentityMatchResult with match decision
    """
    start_time = time.perf_counter()
    
    # Validate query embedding
    is_valid, error = validate_query_embedding(query_embedding)
    if not is_valid:
        raise ValueError(f"Query embedding validation failed: {error}")
    
    # Compute cosine similarities
    similarities = compute_cosine_similarity(query_embedding, context.database_embeddings)
    
    # Build candidate matches
    candidate_matches = []
    sample_provenance_list = context.database_metadata.sample_provenance
    
    for i, sim in enumerate(similarities):
        if i < len(sample_provenance_list):
            prov = sample_provenance_list[i]
            candidate_matches.append(CandidateMatch(
                sample_id=prov.get("sample_id", f"sample_{i}"),
                person_id=prov.get("person_id", "unknown"),
                similarity=float(sim),
                sample_provenance=prov,
            ))
    
    # Aggregate to person level
    person_matches = aggregate_person_matches(
        candidate_matches,
        policy=context.config.person_aggregation_policy,
    )
    
    # Determine match status
    candidate_count = len(candidate_matches)
    threshold = context.config.match_threshold
    ambiguity_margin = context.config.ambiguity_margin
    
    if len(person_matches) == 0:
        # No candidates in database
        return IdentityMatchResult(
            status=MatchStatus.UNKNOWN,
            person_id=None,
            similarity=0.0,
            matched_sample_id=None,
            candidate_count=candidate_count,
            threshold=threshold,
            ambiguity_margin=ambiguity_margin,
            database_schema_version=context.database_metadata.schema_version,
            model_identity=f"{context.database_metadata.model_id}/{context.database_metadata.model_filename}",
            provenance={
                "query_provenance": query_provenance,
                "database_model_id": context.database_metadata.model_id,
                "database_model_filename": context.database_metadata.model_filename,
                "database_model_sha256": context.database_metadata.model_sha256,
                "database_schema_version": context.database_metadata.schema_version,
                "matching_time_ms": (time.perf_counter() - start_time) * 1000,
                "person_aggregation_policy": context.config.person_aggregation_policy,
                "decision": "no_candidates",
            },
        )
    
    best_person = person_matches[0]
    best_similarity = best_person.best_similarity
    
    # Clamp similarity to [0, 1] for numerical stability
    best_similarity = float(np.clip(best_similarity, 0.0, 1.0))
    
    # Check UNKNOWN threshold
    if best_similarity < threshold:
        return IdentityMatchResult(
            status=MatchStatus.UNKNOWN,
            person_id=None,
            similarity=best_similarity,
            matched_sample_id=None,
            candidate_count=candidate_count,
            threshold=threshold,
            ambiguity_margin=ambiguity_margin,
            database_schema_version=context.database_metadata.schema_version,
            model_identity=f"{context.database_metadata.model_id}/{context.database_metadata.model_filename}",
            provenance={
                "query_provenance": query_provenance,
                "database_model_id": context.database_metadata.model_id,
                "database_model_filename": context.database_metadata.model_filename,
                "database_model_sha256": context.database_metadata.model_sha256,
                "database_schema_version": context.database_metadata.schema_version,
                "matching_time_ms": (time.perf_counter() - start_time) * 1000,
                "person_aggregation_policy": context.config.person_aggregation_policy,
                "decision": "below_threshold",
                "best_person_id": best_person.person_id,
                "best_person_similarity": best_similarity,
                "all_person_matches": [
                    {
                        "person_id": p.person_id,
                        "best_sample_id": p.best_sample_id,
                        "best_similarity": float(np.clip(p.best_similarity, 0.0, 1.0)),
                        "sample_count": p.sample_count,
                    }
                    for p in person_matches[:5]  # Top 5 for provenance
                ],
            },
        )
    
    # Check ambiguity
    if len(person_matches) >= 2:
        second_best_person = person_matches[1]
        second_best_similarity = float(np.clip(second_best_person.best_similarity, 0.0, 1.0))
        
        if (best_similarity - second_best_similarity) < ambiguity_margin:
            return IdentityMatchResult(
                status=MatchStatus.AMBIGUOUS,
                person_id=None,
                similarity=best_similarity,
                matched_sample_id=None,
                candidate_count=candidate_count,
                threshold=threshold,
                ambiguity_margin=ambiguity_margin,
                database_schema_version=context.database_metadata.schema_version,
                model_identity=f"{context.database_metadata.model_id}/{context.database_metadata.model_filename}",
                provenance={
                    "query_provenance": query_provenance,
                    "database_model_id": context.database_metadata.model_id,
                    "database_model_filename": context.database_metadata.model_filename,
                    "database_model_sha256": context.database_metadata.model_sha256,
                    "database_schema_version": context.database_metadata.schema_version,
                    "matching_time_ms": (time.perf_counter() - start_time) * 1000,
                    "person_aggregation_policy": context.config.person_aggregation_policy,
                    "decision": "ambiguous",
                    "best_person_id": best_person.person_id,
                    "best_person_similarity": best_similarity,
                    "second_best_person_id": second_best_person.person_id,
                    "second_best_person_similarity": second_best_similarity,
                    "margin": best_similarity - second_best_similarity,
                    "all_person_matches": [
                        {
                            "person_id": p.person_id,
                            "best_sample_id": p.best_sample_id,
                            "best_similarity": float(np.clip(p.best_similarity, 0.0, 1.0)),
                            "sample_count": p.sample_count,
                        }
                        for p in person_matches[:5]
                    ],
                },
            )
    
    # MATCH
    # Clamp similarity to [0, 1] for numerical stability
    clamped_similarity = float(np.clip(best_similarity, 0.0, 1.0))
    return IdentityMatchResult(
        status=MatchStatus.MATCH,
        person_id=best_person.person_id,
        similarity=clamped_similarity,
        matched_sample_id=best_person.best_sample_id,
        candidate_count=candidate_count,
        threshold=threshold,
        ambiguity_margin=ambiguity_margin,
        database_schema_version=context.database_metadata.schema_version,
        model_identity=f"{context.database_metadata.model_id}/{context.database_metadata.model_filename}",
        provenance={
            "query_provenance": query_provenance,
            "database_model_id": context.database_metadata.model_id,
            "database_model_filename": context.database_metadata.model_filename,
            "database_model_sha256": context.database_metadata.model_sha256,
            "database_schema_version": context.database_metadata.schema_version,
            "matching_time_ms": (time.perf_counter() - start_time) * 1000,
            "person_aggregation_policy": context.config.person_aggregation_policy,
            "decision": "match",
            "matched_person_id": best_person.person_id,
            "matched_sample_id": best_person.best_sample_id,
            "matched_similarity": clamped_similarity,
            "sample_count_for_person": best_person.sample_count,
            "all_person_matches": [
                {
                    "person_id": p.person_id,
                    "best_sample_id": p.best_sample_id,
                    "best_similarity": float(np.clip(p.best_similarity, 0.0, 1.0)),
                    "sample_count": p.sample_count,
                }
                for p in person_matches[:5]
            ],
        },
    )


def match_identity_from_database_dir(
    query_embedding: np.ndarray,
    database_dir: str,
    config: Optional[MatchingConfig] = None,
    query_provenance: Optional[Dict[str, Any]] = None,
) -> IdentityMatchResult:
    """
    Convenience function to match identity directly from database directory.
    
    Args:
        query_embedding: 512D float32 L2-normalized query embedding
        database_dir: Directory containing embeddings.npy and embeddings.npy.metadata.json
        config: Optional matching configuration
        query_provenance: Optional provenance for the query
        
    Returns:
        IdentityMatchResult with match decision
    """
    context = load_matching_database(database_dir)
    
    if config is not None:
        context.config = config
    
    return match_identity(query_embedding, context, query_provenance)