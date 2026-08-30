import os
torch_lib = r'C:\Users\Nguyen Cong Thong\Desktop\AI attendance\.venv\Lib\site-packages\torch\lib'
os.environ['PATH'] = torch_lib + ';' + os.environ['PATH']
os.add_dll_directory(torch_lib)

import onnxruntime as ort
import numpy as np

print('ORT:', ort.__version__)
print('Providers:', ort.get_available_providers())

# Test SCRFD model
scrfd_path = r'models\scrfd\scrfd_10g_bnkps.onnx'
try:
    sess = ort.InferenceSession(scrfd_path, providers=['CUDAExecutionProvider'])
    print('SCRFD CUDA Session created successfully')
    print('SCRFD Input:', sess.get_inputs()[0].name, sess.get_inputs()[0].shape)
    print('SCRFD Outputs:', [o.name for o in sess.get_outputs()])
    
    input_data = np.random.randn(1, 3, 960, 960).astype(np.float32)
    output = sess.run(None, {sess.get_inputs()[0].name: input_data})
    print('SCRFD CUDA Inference successful, outputs:', [o.shape for o in output])
    print('SCRFD Output finite:', [np.all(np.isfinite(o)) for o in output])
except Exception as e:
    print('SCRFD CUDA Error:', e)

try:
    sess = ort.InferenceSession(scrfd_path, providers=['CPUExecutionProvider'])
    print('SCRFD CPU Session created successfully')
    input_data = np.random.randn(1, 3, 960, 960).astype(np.float32)
    output = sess.run(None, {sess.get_inputs()[0].name: input_data})
    print('SCRFD CPU Inference successful, outputs:', [o.shape for o in output])
    print('SCRFD Output finite:', [np.all(np.isfinite(o)) for o in output])
except Exception as e:
    print('SCRFD CPU Error:', e)

# Test 1K3D68 model
landmark_path = r'models\landmark\1k3d68.onnx'
try:
    sess = ort.InferenceSession(landmark_path, providers=['CUDAExecutionProvider'])
    print('1K3D68 CUDA Session created successfully')
    print('1K3D68 Input:', sess.get_inputs()[0].name, sess.get_inputs()[0].shape)
    print('1K3D68 Outputs:', [o.name for o in sess.get_outputs()])
    
    input_data = np.random.randn(1, 3, 192, 192).astype(np.float32)
    output = sess.run(None, {sess.get_inputs()[0].name: input_data})
    print('1K3D68 CUDA Inference successful, outputs:', [o.shape for o in output])
    print('1K3D68 Output finite:', [np.all(np.isfinite(o)) for o in output])
except Exception as e:
    print('1K3D68 CUDA Error:', e)

try:
    sess = ort.InferenceSession(landmark_path, providers=['CPUExecutionProvider'])
    print('1K3D68 CPU Session created successfully')
    input_data = np.random.randn(1, 3, 192, 192).astype(np.float32)
    output = sess.run(None, {sess.get_inputs()[0].name: input_data})
    print('1K3D68 CPU Inference successful, outputs:', [o.shape for o in output])
    print('1K3D68 Output finite:', [np.all(np.isfinite(o)) for o in output])
except Exception as e:
    print('1K3D68 CPU Error:', e)