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

score_outputs = [outputs[0], outputs[1], outputs[2]]
bbox_outputs = [outputs[3], outputs[4], outputs[5]]
kps_outputs = [outputs[6], outputs[7], outputs[8]]

for level_idx in range(3):
    scores = score_outputs[level_idx].squeeze()
    bboxes = bbox_outputs[level_idx].squeeze(0) if bbox_outputs[level_idx].ndim > 2 else bbox_outputs[level_idx]
    keypoints = kps_outputs[level_idx].squeeze(0) if kps_outputs[level_idx].ndim > 2 else kps_outputs[level_idx]
    
    print(f'Level {level_idx}: scores={scores.shape}, bboxes={bboxes.shape}, kps={keypoints.shape}')
    high_conf = np.where(scores > 0.55)[0]
    print(f'  high conf: {len(high_conf)}')
    for i in high_conf[:3]:
        conf = float(scores[i])
        bbox_model = bboxes[i]
        kps_model = keypoints[i].reshape(5, 2)
        x1, y1, x2, y2 = bbox_model
        x1 = (x1 - pad_left) / scale_factor
        y1 = (y1 - pad_top) / scale_factor
        x2 = (x2 - pad_left) / scale_factor
        y2 = (y2 - pad_top) / scale_factor
        print(f'  det {i}: conf={conf:.4f}, bbox_model={bbox_model}, converted=({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f}), valid={x1<x2 and y1<y2 and np.isfinite([x1,y1,x2,y2]).all()}')