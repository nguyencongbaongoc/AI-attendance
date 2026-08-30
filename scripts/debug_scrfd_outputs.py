import os
torch_lib = r'C:\Users\Nguyen Cong Thong\Desktop\AI attendance\.venv\Lib\site-packages\torch\lib'
os.environ['PATH'] = torch_lib + ';' + os.environ['PATH']
os.add_dll_directory(torch_lib)

import onnxruntime as ort
import numpy as np

scrfd_path = r'models\scrfd\scrfd_10g_bnkps.onnx'
sess = ort.InferenceSession(scrfd_path, providers=['CUDAExecutionProvider'])

print('Input:', sess.get_inputs()[0].name, sess.get_inputs()[0].shape)
print('Outputs:')
for o in sess.get_outputs():
    print(f'  {o.name}: {o.shape}')

# Test with 960x960 input (what the model expects)
input_data = np.random.randn(1, 3, 960, 960).astype(np.float32)
output = sess.run(None, {sess.get_inputs()[0].name: input_data})

print()
print('Output shapes:')
output_names = [o.name for o in sess.get_outputs()]
for i, o in enumerate(output):
    print(f'  outputs[{i}] ({output_names[i]}): {o.shape}')
