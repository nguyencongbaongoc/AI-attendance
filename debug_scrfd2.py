import numpy as np
import cv2
from app.data.preprocessing import UnifiedPreprocessor
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType

preprocessor = UnifiedPreprocessor(model_id='scrfd')

img = cv2.imread('realistic_test_face.jpg')
print(f'Image shape: {img.shape}')

metadata = FrameMetadata(
    source_type=SourceType.IMAGE,
    source_id='test',
    frame_index=0,
    timestamp=0,
    original_width=img.shape[1],
    original_height=img.shape[0],
    pixel_format=PixelFormat.BGR,
    dtype='uint8'
)
frame = CanonicalFrame(data=img, metadata=metadata)

result = preprocessor.preprocess(frame)
print(f'Preprocessed tensor shape: {result.tensor.shape}')
print(f'Scale factor: {result.scale_factor}')
print(f'Padding: {result.padding_applied}')
print(f'Input shape: {result.tensor.shape}')
print(f'Tensor range: {result.tensor.min():.4f}-{result.tensor.max():.4f}')

import onnxruntime as ort
session = ort.InferenceSession('models/scrfd/scrfd_10g_bnkps.onnx', providers=['CPUExecutionProvider'])
outputs = session.run(None, {'input.1': result.tensor})

print('Outputs:')
for i, out in enumerate(outputs):
    print(f'  [{i}] {out.shape}: min={out.min():.6f}, max={out.max():.6f}, mean={out.mean():.6f}')

# Check scores
scores_8, scores_16, scores_32 = outputs[0], outputs[1], outputs[2]
print(f'Max scores: {scores_8.max():.4f}, {scores_16.max():.4f}, {scores_32.max():.4f}')
print(f'Scores > 0.3: {(scores_8 > 0.3).sum()}, {(scores_16 > 0.3).sum()}, {(scores_32 > 0.3).sum()}')
print(f'Scores > 0.55: {(scores_8 > 0.55).sum()}, {(scores_16 > 0.55).sum()}, {(scores_32 > 0.55).sum()}')