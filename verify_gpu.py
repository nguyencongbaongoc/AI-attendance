import torch
import onnxruntime as ort
import numpy as np

print('=== PyTorch CUDA ===')
print(f'Version: {torch.__version__}')
print(f'CUDA compiled: {torch.version.cuda}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'Device count: {torch.cuda.device_count()}')
    print(f'Device name: {torch.cuda.get_device_name(0)}')
    props = torch.cuda.get_device_properties(0)
    print(f'Compute capability: {props.major}.{props.minor}')
    print(f'Total memory: {props.total_memory // (1024*1024)} MB')
    # Test operation
    x = torch.randn(100, 100).cuda()
    y = torch.randn(100, 100).cuda()
    z = torch.matmul(x, y)
    print(f'Matmul test: {z.shape}')

print()
print('=== ONNX Runtime ===')
print(f'Version: {ort.__version__}')
providers = ort.get_available_providers()
print(f'Available providers: {providers}')
print(f'CUDA EP registered: {"CUDAExecutionProvider" in providers}')

print()
print('=== cuDNN ===')
try:
    if torch.backends.cudnn.is_available():
        cudnn_ver = torch.backends.cudnn.version()
        major = cudnn_ver // 1000
        minor = cudnn_ver % 1000
        print(f'cuDNN: {major}.{minor} (bundled with torch)')
    else:
        print('cuDNN: not available')
except:
    print('cuDNN: error checking')

print()
print('=== NVDEC (via ffmpeg) ===')
import shutil
ffmpeg = shutil.which('ffmpeg')
if ffmpeg:
    import subprocess
    result = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        print(f'ffmpeg: {result.stdout.splitlines()[0]}')
else:
    print('ffmpeg: not found')