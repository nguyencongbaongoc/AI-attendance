import json

with open('benchmark_results/PHASE_36R_LONG_DURATION_SOAK_20260825_134847.json') as f:
    data = json.load(f)

print('=== PHASE 36-R1 FINAL REAL 30-MINUTE SOAK SUMMARY ===')
print()
print('Verdict:', data['verdict'])
print('Actual Soak Duration: {:.2f} minutes'.format(data['actual_duration_minutes']))
print('Startup Duration: {:.2f} seconds'.format(data['startup_duration_seconds']))
print('Warm-up Duration: {:.2f} seconds'.format(data['warmup_duration_seconds']))
print('Soak Duration: {:.2f} seconds'.format(data['soak_duration_seconds']))
print('Soak Completed:', data['soak_completed'])
print()
print('CAM1 Results:')
cam1_soak = data['cam1']['soak']
print('  Soak Frames:', cam1_soak['frame_continuity']['total_frames'])
print('  Discontinuities:', cam1_soak['frame_continuity']['discontinuities'])
print('  Max Gap:', cam1_soak['frame_continuity']['max_gap'])
print('  Timestamp Regressions:', cam1_soak['timestamp_monotonicity']['regressions_count'])
print('  Processing FPS: {:.2f}'.format(cam1_soak['processing_fps']['mean']))
print('  Source FPS: {:.2f}'.format(cam1_soak['source_fps']['mean']))
print('  Inference Latency Mean: {:.2f}ms'.format(cam1_soak['inference_latency']['mean']))
print('  Inference Latency P95: {:.2f}ms'.format(cam1_soak['inference_latency']['p95']))
print('  Inference Latency P99: {:.2f}ms'.format(cam1_soak['inference_latency']['p99']))
print()
print('CAM2 Results:')
cam2_soak = data['cam2']['soak']
print('  Soak Frames:', cam2_soak['frame_continuity']['total_frames'])
print('  Discontinuities:', cam2_soak['frame_continuity']['discontinuities'])
print('  Max Gap:', cam2_soak['frame_continuity']['max_gap'])
print('  Timestamp Regressions:', cam2_soak['timestamp_monotonicity']['regressions_count'])
print('  Processing FPS: {:.2f}'.format(cam2_soak['processing_fps']['mean']))
print('  Source FPS: {:.2f}'.format(cam2_soak['source_fps']['mean']))
print('  Inference Latency Mean: {:.2f}ms'.format(cam2_soak['inference_latency']['mean']))
print('  Inference Latency P95: {:.2f}ms'.format(cam2_soak['inference_latency']['p95']))
print('  Inference Latency P99: {:.2f}ms'.format(cam2_soak['inference_latency']['p99']))
print()
print('System Resources (SOAK phase):')
soak_mem = data['system_resources']['by_phase']['soak']
print('  Memory Growth: {:.2f}%'.format(soak_mem['percentage_growth']))
print('  Mean CPU: {:.2f}%'.format(soak_mem['mean_cpu_percent']))
print('  Max GPU Memory: {:.2f} MB'.format(data['system_resources']['overall']['max_gpu_memory_mb']))
print('  Mean GPU Utilization: {:.2f}%'.format(data['system_resources']['overall']['mean_gpu_utilization']))
print()
print('Verification Classification (SOAK):')
vc = data['verification_classification']
for key, val in vc.items():
    if isinstance(val, dict):
        print('  {}:'.format(key))
        for k, v in val.items():
            print('    {}: {}'.format(k, v))
    else:
        print('  {}: {}'.format(key, val))
print()
print('Regression Tests:')
for name, result in data['regression']['details'].items():
    status = 'PASS' if result.get('passed', False) else 'FAIL'
    print('  {}: {}'.format(name, status))
print()
print('Known Limitations:')
for lim in data['known_limitations']:
    print('  - {}'.format(lim))
if not data['known_limitations']:
    print('  None')