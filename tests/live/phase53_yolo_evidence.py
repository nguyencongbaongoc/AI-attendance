#!/usr/bin/env python3
"""Phase 53 evidence: YOLO produces person detections on a synthetic person-like image."""
import sys
import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import cv2  # type: ignore
from app.vision.yolo_person_detector import get_person_detector, YOLOPersonDetector
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat


def draw_person(img, cx, cy, scale=1.0):
    # Head
    cv2.circle(img, (cx, int(cy - 80 * scale)), int(30 * scale), (190, 200, 220), -1)
    # Body
    cv2.rectangle(img,
                  (int(cx - 40 * scale), int(cy - 50 * scale)),
                  (int(cx + 40 * scale), int(cy + 120 * scale)),
                  (130, 130, 180), -1)
    # Legs
    cv2.rectangle(img,
                  (int(cx - 30 * scale), int(cy + 120 * scale)),
                  (int(cx - 5 * scale), int(cy + 240 * scale)),
                  (60, 60, 90), -1)
    cv2.rectangle(img,
                  (int(cx + 5 * scale), int(cy + 120 * scale)),
                  (int(cx + 30 * scale), int(cy + 240 * scale)),
                  (60, 60, 90), -1)


def main():
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    img[:] = (40, 40, 50)
    # Background gradient
    for y in range(1080):
        img[y, :] = (int(40 + y * 0.05), int(40 + y * 0.05), int(50 + y * 0.05))

    # Place 3 people across the frame
    draw_person(img, 480, 540, scale=1.4)
    draw_person(img, 960, 540, scale=1.2)
    draw_person(img, 1440, 540, scale=1.5)

    meta = FrameMetadata(
        source_type=SourceType.SYNTHETIC,
        source_id="phase53_evidence",
        frame_index=1,
        original_width=1920,
        original_height=1080,
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
        extra={"test": "phase53_persons"},
    )
    frame = CanonicalFrame(data=img, metadata=meta)

    det = get_person_detector(model_id="yolo_person", allow_fallback=True)
    print(f"Detector: {type(det).__name__}")
    print(f"Is YOLOPersonDetector: {isinstance(det, YOLOPersonDetector)}")
    persons = det.detect(frame)
    print(f"Detections: {len(persons)}")
    for i, p in enumerate(persons):
        print(f"  [{i}] bbox={p.bbox} conf={p.confidence:.3f} coord={p.coordinate_space} model={p.model_id}")
        print(f"      metadata.source={p.metadata.get('source')} metadata.frame_index={p.metadata.get('frame_index')}")


if __name__ == "__main__":
    main()
