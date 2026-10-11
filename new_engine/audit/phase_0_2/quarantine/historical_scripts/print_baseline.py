import json

with open('benchmark_results/PHASE_36K_MAX_PERFORMANCE_FORENSIC_BASELINE.json') as f:
    data = json.load(f)

print('BASELINE SUMMARY:')
for k, v in data['benchmarks'].items():
    if 'error' not in v:
        print(f'  {k}: {v["fps"]:.2f} FPS, avg_latency={v["avg_latency_ms"]:.1f}ms')

print()
print('STAGE BREAKDOWN (Benchmark B):')
meta = data['benchmarks']['B_gpu_face_detector_only']['metadata']
for k, v in meta.items():
    if k.startswith('avg_') and k.endswith('_ms'):
        print(f'  {k}: {v:.1f}ms')