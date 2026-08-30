import sys
sys.path.insert(0, 'C:/Users/Nguyen Cong Thong/Desktop/AI attendance')
import onnxruntime as ort

model_path = 'C:/Users/Nguyen Cong Thong/Desktop/AI attendance/models/scrfd/scrfd_10g_bnkps.onnx'
session = ort.InferenceSession(model_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
print('Inputs:')
for inp in session.get_inputs():
    print(f'  {inp.name}: {inp.shape} {inp.type}')
print('Outputs:')
for out in session.get_outputs():
    print(f'  {out.name}: {out.shape} {out.type}')