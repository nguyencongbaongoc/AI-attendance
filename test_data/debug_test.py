import sys
sys.path.insert(0, '.')
import traceback
import numpy as np
from scripts.phase17_adaptive_face_quality import (
    create_synthetic_4k_image,
    create_adaptive_face_crop,
    create_quality_assessor,
    create_sharp_face_crop,
    PoseState,
    QualityClass,
    crop_person_from_frame,
    DEFAULT_PERSON_PADDING
)

# Replicate the test step by step
frame = create_synthetic_4k_image()
print("Frame shape:", frame.shape)

assessor = create_quality_assessor()

# Person with very small face (far away)
person_bbox = (1000.0, 1000.0, 1100.0, 1200.0)  # 100x200 person
person_crop_img, person_crop_bbox, (pw, ph) = crop_person_from_frame(
    frame=frame,
    person_bbox=person_bbox,
    frame_width=3840,
    frame_height=2160,
    padding_policy=DEFAULT_PERSON_PADDING,
)

print("Person crop:", pw, "x", ph)
print("Person crop bbox:", person_crop_bbox)
print("pw > 0 and ph > 0:", pw > 0 and ph > 0)

# Tiny face within person
tiny_face_bbox = (1040.0, 1020.0, 1060.0, 1040.0)  # 20x20 face
face_crop = create_adaptive_face_crop(
    frame=frame,
    face_bbox_original=tiny_face_bbox,
    person_crop_id="person_crop_001",
    person_detection_id="person_det_001",
    person_detection_confidence=0.95,
)
face_crop.data = create_sharp_face_crop(width=28, height=28)  # With padding

print("Face crop created:", face_crop.crop_width, "x", face_crop.crop_height)

# Quality assessment - face is UNUSABLE but person track remains
result = assessor.assess(
    face_crop=face_crop,
    detection_confidence=0.88,
    pose_state=PoseState.NORMAL,
)

print("Quality class:", result.quality_class)
print("Evidence eligible:", result.evidence_eligible)
print("Reasons:", result.reasons)

# Check assertions
print("\n--- Verification ---")
print(f"Quality class == UNUSABLE: {result.quality_class == QualityClass.UNUSABLE}")
print(f"Evidence eligible == False: {result.evidence_eligible is False}")
print(f"'face_area_too_small' in reasons: {'face_area_too_small' in result.reasons}")
print(f"'face_too_narrow' in reasons: {'face_too_narrow' in result.reasons}")
print(f"Person crop shape == (ph, pw): {person_crop_img.shape[:2] == (ph, pw)}")

print("\nAll checks completed!")