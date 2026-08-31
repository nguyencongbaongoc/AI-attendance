import onnxruntime as ort
import onnx
from onnx import helper, TensorProto
import tempfile
import os
import numpy as np

# Test CUDA EP session creation and inference
X = helper.make_tensor_value_info('X', TensorProto.FLOAT, [1, 3, 3])
W = helper.make_tensor_value_info('W', TensorProto.FLOAT, [1, 3, 3])
Y = helper.make_tensor_value_info('Y', TensorProto.FLOAT, [1, 3, 3])
node = helper.make_node('MatMul', ['X', 'W'], ['Y'])
graph = helper.make_graph([node], 'test', [X, W], [Y])
model = helper.make_model(graph, producer_name='test')
model.opset_import[0].version = 9

# Use a fixed path instead of tempfile
test_model_path = os.path.join(tempfile.gettempdir(), 'test_cuda_ep.onnx')
onnx.save(model, test_model_path)

try:
    session = ort.InferenceSession(test_model_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    print('Session providers:', session.get_providers())
    
    x = np.random.randn(1, 3, 3).astype(np.float32)
    w = np.random.randn(1, 3, 3).astype(np.float32)
    result = session.run(None, {'X': x, 'W': w})
    print('Inference result shape:', result[0].shape)
    print('CUDA EP inference: SUCCESS')
except Exception as e:
    print('CUDA EP session creation failed:', e)
finally:
    try:
        os.unlink(test_model_path)
    except:
        pass