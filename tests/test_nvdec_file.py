import subprocess
import os
import time

# Test FFmpeg command with hwdownload to nv12 then format to bgr24 - file output
cmd = [
    'ffmpeg',
    '-hide_banner', '-loglevel', 'info',
    '-rtsp_transport', 'tcp',
    '-hwaccel', 'cuda',
    '-hwaccel_output_format', 'cuda',
    '-c:v', 'h264_cuvid',
    '-gpu', '0',
    '-i', 'rtsp://127.0.0.1:8554/live/cam1',
    '-an',
    '-vf', 'hwdownload,format=nv12,format=bgr24',
    '-f', 'rawvideo',
    '-pix_fmt', 'bgr24',
    '-t', '5',
    'test_output.raw'
]
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
time.sleep(8)
stdout, stderr = proc.communicate(timeout=15)
print(f'Return code: {proc.returncode}')
print(f'Stderr: {stderr.decode()}')
if os.path.exists('test_output.raw'):
    print(f'File size: {os.path.getsize("test_output.raw")} bytes')
    os.remove('test_output.raw')