# Phase 1.V4 Unknown Identity Tests

**Date**: 2026-10-04
**Phase**: 1.V4 - End-to-End Attendance Proof

---

## 1. Unknown Identity Handling

### ArcFace Recognition Behavior
```python
# In ArcFaceRecognizer.identify()
def identify(self, embedding, top_k=5):
    if not self._enrollment_embeddings:
        return []  # Empty list if no enrollment
    
    # Compute similarities
    similarities = torch.matmul(enrollment_stack, embedding)
    
    # Filter by threshold
    results = []
    for val, idx in zip(top_values, top_indices):
        similarity = float(val)
        if similarity >= self.arcface_config.similarity_threshold:  # 0.6
            results.append((person_id, similarity))
    
    return results  # Empty if no match above threshold
```

### CrossingEvent Identity Fields
```python
@dataclass
class CrossingEvent:
    person_id: Optional[str] = None          # None if unknown
    person_name: Optional[str] = None        # None if unknown
    identity_confidence: float = 0.0         # 0.0 if unknown
```

### Backend Identity Handling (Phase 23)
```python
# In raw_event.py - extract_identity_info()
def extract_identity_info(crossing_event):
    return {
        "identity_certainty": IdentityCertainty.UNKNOWN,
        "identity_candidate": None,
        "identity_confidence": 0.0,
        "identity_evidence_ref": crossing_event.global_observation_id,
    }
```

---

## 2. Unknown Identity Test Scenarios

### Scenario 1: No Enrollment Database
| Condition | Expected |
|-----------|----------|
| No embeddings.npy | ArcFace returns empty list |
| CrossingEvent.person_id | None |
| CrossingEvent.identity_confidence | 0.0 |
| Backend RawInOutEvent.identity_certainty | UNKNOWN |
| AttendanceRecord.identity_certainty | UNKNOWN |

### Scenario 2: Enrollment Exists But No Match
| Condition | Expected |
|-----------|----------|
| Face detected, embedding generated | ArcFace runs |
| Similarity < 0.6 | Empty match list |
| CrossingEvent.person_id | None |
| identity_confidence | 0.0 |
| Backend identity_certainty | UNKNOWN |

### Scenario 3: Low Confidence Match
| Condition | Expected |
|-----------|----------|
| Similarity = 0.55 (< 0.6) | No match returned |
| CrossingEvent.person_id | None |
| identity_confidence | 0.0 (not set to 0.55) |

### Scenario 4: Multiple Matches (Ambiguous)
| Condition | Expected |
|-----------|----------|
| Two enrolled people > 0.6 | Both returned |
| Backend identity_certainty | AMBIGUOUS |
| AttendanceRecord.identity_certainty | AMBIGUOUS |

---

## 2. Test Scenarios

### Test 1: No Enrollment
| Step | Action | Verify |
|------|--------|--------|
| 1 | Remove embeddings.npy | - |
| 2 | Reload enrollment | Success (empty) |
| 3 | Generate crossing event | person_id=None, confidence=0.0 |
| 4 | Backend receives event | identity_certainty=UNKNOWN |

### Test 2: Face Below Threshold
| Step | Action | Verify |
|------|--------|--------|
| 1 | Have unknown person cross line | Face detected |
| 2 | ArcFace embedding generated | No match (similarity < 0.6) |
| 3 | CrossingEvent generated | person_id=None, confidence=0.0 |
| 4 | Backend processes | identity_certainty=UNKNOWN |

### Test 3: Ambiguous Match
| Step | Action | Verify |
|------|--------|--------|
| 1 | Enroll two similar-looking people | Both enrolled |
| 2 | Have one cross line | Both match > 0.6 |
| 3 | CrossingEvent | identity_confidence = max similarity |
| 4 | Backend | identity_certainty = AMBIGUOUS |

### Test 4: Known Identity
| Step | Action | Verify |
|------|--------|--------|
| 1 | Enroll TEST-001 | Enrolled |
| 2 | TEST-001 crosses line | Face detected, matched |
| 4 | CrossingEvent | person_id=TEST-001, confidence≥0.6 |
| 5 | Backend | identity_certainty=KNOWN |

---

## 3. Test Status

### Status: READY FOR EXECUTION
- Test cases defined
- ArcFace threshold behavior verified (0.6)
- Backend identity_certainty enum: KNOWN, UNKNOWN, AMBIGUOUS, INSUFFICIENT

### Pending: Live Execution
- Need person to cross line
- Verify UNKNOWN for unenrolled
- Verify KNOWN for enrolled
- Verify AMBIGUOUS for multiple matches

---

## 4. Evidence

### Code Locations
- `pipeline_engine/inference/face_recognition.py:336-369` - identify() method
- `pipeline_engine/attendance/attendance_engine.py:386-388` - person_id in CrossingEvent
- `app/in_out/raw_event.py:47-64` - extract_identity_info()
- `app/in_out/contract.py:33-39` - IdentityCertainty enum

### ArcFace Threshold
```python
# In ArcFaceConfig
similarity_threshold: float = 0.6
```

---

## 5. Next Steps

1. Execute with unenrolled person crossing line
2. Verify UNKNOWN identity_certainty in backend
2. Test with enrolled person
2. Verify KNOWN identity_certainty
2. Test ambiguous case (if possible)
2. Document results in V4 verdict