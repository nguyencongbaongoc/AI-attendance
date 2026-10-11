import numpy as np
import cv2
from app.models.registry import get_model_registry

registry = get_model_registry()
model = registry.get('scrfd')
print(f'SCRFD model path: {registry.get_model_path("scrfd")}')
print(f'Model exists: {registry.get_model_path("scrfd").exists()}')
print(f'Expected SHA256: {model.expected_sha256}')
print(f'Thresholds: confidence={model.thresholds.confidence_threshold}, nms={model.thresholds.nms_threshold}')
print(f'Input size: {model.preprocessing.input_height}x{model.preprocessing.input_width}')