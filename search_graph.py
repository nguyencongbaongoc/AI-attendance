import json
data = json.load(open('graphify-out/.graphify_analysis.json'))
for n in data.get('nodes', []):
    name = n.get('name', '')
    if any(kw in name for kw in ['DecoderBackendFactory','PyNvVideoCodecBackend','PyAVNVDECBackend','GPUFrameContract','PyNvVideoCodecFrameAdapter','CameraRuntimeManager','ingestion_worker','supervised_rtsp_source','DetectionPipeline','Tracker','Identity','Crossing','Attendance']):
        print(f'{n.get("id")}: {name} ({n.get("type")})')