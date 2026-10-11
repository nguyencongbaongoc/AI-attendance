import numpy as np
from app.runtime.cuda import get_ort_session
from app.models.registry import get_model_registry
from app.data.preprocessing import UnifiedPreprocessor
from app.data.frame import CanonicalFrame, FrameMetadata, PixelFormat, SourceType
from app.vision.detection import FaceDetector

frame_data = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
metadata = FrameMetadata(source_type=SourceType.IMAGE, source_id='test', frame_index=0, timestamp=0.0, original_width=1280, original_height=720, pixel_format=PixelFormat.RGB, dtype='uint8')
frame = CanonicalFrame(data=frame_data, metadata=metadata)

detector = FaceDetector(confidence_threshold=0.55, nms_threshold=0.45, providers=['CPUExecutionProvider'])

prep_result = detector.preprocessor.preprocess(frame)
print('Prep:', prep_result.tensor.shape, prep_result.scale_factor, prep_result.padding_applied)

outputs = detector.session.run(detector.output_names, {detector.input_name: prep_result.tensor})

scale_factor = prep_result.scale_factor or 1.0
padding = prep_result.padding_applied or (0, 0, 0, 0)
pad_top, pad_bottom, pad_left, pad_right = padding

input_height = detector.contract.input_height
input_width = detector.contract.input_width

valid_x1 = pad_left
valid_y1 = pad_top
valid_x2 = input_width - pad_right
valid_y2 = input_height - pad_bottom

print(f'Valid region: x=[{valid_x1}, {valid_x2}], y=[{valid_y1}, {valid_y2}]')

score_outputs = [outputs[0], outputs[1], outputs[2]]
bbox_outputs = [outputs[3], outputs[4], outputs[5]]
kps_outputs = [outputs[6], outputs[7], outputs[8]]

scores = score_outputs[0].squeeze()
bboxes = bbox_outputs[0]
if bboxes.ndim > 2:
    bboxes = bboxes.squeeze(0)
keypoints = kps_outputs[0]
if keypoints.ndim > 2:
    keypoints = keypoints.squeeze(0)

high_conf = np.where(scores > 0.55)[0]
print(f'High conf indices: {high_conf[:5]}')

# Generate anchors to check anchor centers
from app.vision.detection import FaceDetector
anchors, anchor_scales = detector._generate_anchors(8, input_height, input_width)

for i in high_conf[:3]:
    conf = float(scores[i])
    dx, dy, dw, dh = bboxes[i]
    anchor_cx, anchor_cy = anchors[i]
    anchor_scale = anchor_scales[i]
    
    # Decode bbox
    cx = anchor_cx + dx * 8
    cy = anchor_cy + dy * 8
    w = np.exp(dw) * anchor_scale
    h = np.exp(dh) * anchor_scale
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2
    
    print(f'  det {i}: conf={conf:.4f}, anchor=({anchor_cx:.1f},{anchor_cy:.1f}), scale={anchor_scale:.1f}')
    print(f'    bbox_model=({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f})')
    print(f'    overlaps_valid: x2>{valid_x1}={x2>valid_x1}, x1<{valid_x2}={x1<valid_x2}, y2>{valid_y1}={y2>valid_y1}, y1<{valid_y2}={y1<valid_y2}')
