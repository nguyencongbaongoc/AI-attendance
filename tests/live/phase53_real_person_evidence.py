#!/usr/bin/env python3
"""Phase 53 — Real-person YOLO inference evidence.

Downloads a small person JPEG from a stable public source and runs the
YOLOPersonDetector on it. Reports whether real person detections are produced
and confirms CUDA usage.
"""
import sys
import urllib.request
import tempfile
import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import cv2  # type: ignore
import torch
from app.vision.yolo_person_detector import get_person_detector, YOLOPersonDetector
from app.data.frame import CanonicalFrame, FrameMetadata, SourceType, PixelFormat


def fetch_image(url: str) -> Path:
    tmp = Path(tempfile.gettempdir()) / "phase53_person.jpg"
    if not tmp.exists():
        urllib.request.urlretrieve(url, tmp)
    return tmp


def main():
    url = (
        "https://ultralytics.com/images/bus.jpg"  # contains persons; multi-class
    )
    img_path = fetch_image(url)
    bgr = cv2.imread(str(img_path))
    assert bgr is not None, f"failed to read {img_path}"
    print(f"Loaded image: {bgr.shape} dtype={bgr.dtype} file={img_path.name}")

    meta = FrameMetadata(
        source_type=SourceType.WEBCAM,
        source_id="phase53_evidence_bus",
        frame_index=1,
        original_width=bgr.shape[1],
        original_height=bgr.shape[0],
        pixel_format=PixelFormat.BGR,
        dtype="uint8",
        extra={"source": "phase53_evidence", "frame_index": 1},
    )
    frame = CanonicalFrame(data=bgr, metadata=meta)

    print(f"torch.cuda.is_available() = {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  device name = {torch.cuda.get_device_name(0)}")

    det = get_person_detector(model_id="yolo_person", allow_fallback=True)
    print(f"Detector: {type(det).__name__}")
    assert isinstance(det, YOLOPersonDetector)

    persons = det.detect(frame)
    print(f"Person detections: {len(persons)}")
    for i, p in enumerate(persons):
        print(f"  [{i}] bbox={tuple(round(v, 2) for v in p.bbox)} conf={p.confidence:.3f} coord={p.coordinate_space} model={p.model_id}")
        if p.provenance is not None:
            print(f"      prov.source_id={p.provenance.source_id} prov.frame_index={p.provenance.frame_index} prov.model_sha256_short={p.provenance.detector_model_sha256[:16]}")
        print(f"      top-level: source_id={p.source_id} frame_index={p.frame_index}")


if __name__ == "__main__":
    main()
