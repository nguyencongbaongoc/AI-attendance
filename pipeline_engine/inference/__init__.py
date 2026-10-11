"""
Pipeline Engine Inference Module

Exports factory functions for creating detector/recognizer instances.
"""

from pipeline_engine.inference.face_detection import (
    SCRFDDetector,
    FaceDetection,
    SCRFDConfig,
    create_scrfd_detector,
)

from pipeline_engine.inference.face_recognition import (
    ArcFaceRecognizer,
    FaceEmbedding,
    ArcFaceConfig,
    create_arcface_recognizer,
)

from pipeline_engine.inference.person_detection import (
    YOLOPersonDetector,
    PersonDetection,
    YOLOConfig,
    create_yolo_detector,
)

from pipeline_engine.inference.body_reid import (
    ReIDDetector,
    BodyEmbedding,
    ReIDConfig,
    create_reid_detector,
)

from pipeline_engine.inference.tensorrt_engine import (
    TensorRTExecutor,
    TensorRTBinding,
    create_tensorrt_executor,
)

__all__ = [
    # Face Detection
    "SCRFDDetector",
    "FaceDetection", 
    "SCRFDConfig",
    "create_scrfd_detector",
    # Face Recognition
    "ArcFaceRecognizer",
    "FaceEmbedding",
    "ArcFaceConfig", 
    "create_arcface_recognizer",
    # Person Detection
    "YOLOPersonDetector",
    "PersonDetection",
    "YOLOConfig",
    "create_yolo_detector",
    # Body ReID
    "ReIDDetector",
    "BodyEmbedding",
    "ReIDConfig",
    "create_reid_detector",
    # TensorRT Engine
    "TensorRTExecutor",
    "TensorRTBinding",
    "create_tensorrt_executor",
]