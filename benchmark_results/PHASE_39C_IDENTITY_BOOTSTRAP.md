# PHASE 39C — CANONICAL DATA + IDENTITY BOOTSTRAP REPORT

**Timestamp:** 2026-08-28T15:07:04Z
**Status:** PASS

## Enrollment Database

| Item | Value |
|------|-------|
| Path | `data/enrollment_db/` |
| Embeddings File | `embeddings.npy` |
| Metadata File | `embeddings.npy.metadata.json` |

## Embeddings Verification

| Property | Value |
|----------|-------|
| Shape | (9, 512) |
| Dtype | float32 |
| Dimensions | 512 |
| Embedding Count | 9 |
| Normalization | L2 |
| Model ID | arcface |
| Model Filename | glintr100.onnx |
| Model SHA256 | 4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf |

## Person IDs (Current Production Dataset)

- HS001
- HS002
- HS003

**Note:** Do not modify this production dataset.

## Metadata Consistency

| Check | Result |
|-------|--------|
| Schema Version | 1.0 |
| Embedding Dimension | 512 |
| Embedding Count | 9 |
| Person IDs Match | YES |
| Sample Provenance Count | 9 |
| Creation Timestamp | 2026-08-23T14:01:36.441284Z |

## Enrollment UI Verification

- **Canonical Mechanism:** YES - Enrollment UI is the canonical mechanism for adding future students
- **Future Student Flow:** HS004 -> enrollment -> ArcFace -> embedding -> metadata -> embeddings.npy
- **Embedding Array Index:** NOT the business identity (person_id is the business key)

## Verification Results

- [x] embeddings.npy exists and loads correctly
- [x] Shape: (9, 512) - 9 embeddings, 512 dimensions each
- [x] Dtype: float32
- [x] Normalization: L2
- [x] Model: ArcFace (glintr100.onnx)
- [x] Person IDs: HS001, HS002, HS003 (3 persons, 3 samples each)
- [x] Metadata consistent with embeddings
- [x] Sample provenance complete (9 samples with full traceability)
- [x] Enrollment UI is canonical mechanism
- [x] Embedding array index is NOT business identity

## Conclusion

Identity chain verified: student_id -> person_id -> enrollment metadata -> embedding index -> embeddings.npy -> identity matching -> attendance. Production dataset intact and ready.