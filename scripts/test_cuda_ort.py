import os
# Must set PATH and add_dll_directory BEFORE importing onnxruntime
torch_lib = r'C:\Users\Nguyen Cong Thong\AppData\Local\Programs\Python\Python312\Lib\site-packages\torch\lib'
os.environ['PATH'] = torch_lib + ';' + os.environ['PATH']
os.add_dll_directory(torch_lib)

import onnxruntime as ort
import numpy as np
import onnx
from onnx import helper, TensorProto
import tempfile

print('ORT:', ort.__version__)
print('Providers:', ort.get_available_providers())

X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [1, 3, 224, 224])
Y = helper.make_tensor_value_info('Y', TensorProto.FLOAT, [1, 3, 224, 224])
node = helper.make_node('Identity', ['X'], ['Y'])
graph = helper.make_graph([node], 'test', [X], [Y])
model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 9)], ir_version=9)

with tempfile.NamedTemporaryFile(suffix='.onnx', delete=False) as f:
    onnx.save(model, f.name)
    model_path = f.name

try:
    sess = ort.InferenceSession(model_path, providers=['CUDAExecutionProvider'])
    print('CUDA Session created successfully')
    input_data = np.random.randn(1, 3, 224, 224).astype(np.float32)
    output = sess.run(None, {'X': input_data})
    print('CUDA Inference successful, output shape:', output[0].shape)
    print('Output finite:', np.all(np.isfinite(output[0])))
except Exception as e:
    print('CUDA Error:', e)

try:
    sess = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    print('CPU Session created successfully')
    input_data = np.random.randn(1, 3, 224, 224).astype(np.float32)
    output = sess.run(None, {'X': input_data})
    print('CPU Inference successful, output shape:', output[0].shape)
    print('Output finite:', np.all(np.isfinite(output[0])))
except Exception as e:
    print('CPU Error:', e)

os.unlink(model_path)