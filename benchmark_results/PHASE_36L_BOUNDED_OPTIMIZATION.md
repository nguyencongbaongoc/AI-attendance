# Phase 36L: Bounded Optimization Loop Results

**Best Configuration:** I_Full_Optimized
**Best Latency:** 18.69ms (53.52 FPS)

## Results Summary

| Config | Median (ms) | Mean (ms) | P95 (ms) | FPS | Accuracy |
|--------|-------------|-----------|----------|-----|----------|
| B_IO_Binding_Reuse | 33.13 | 40.97 | 75.43 | 30.18 | PASS |
| G_Combined_AB | 33.49 | 40.05 | 70.02 | 29.86 | PASS |
| I_Full_Optimized | 18.69 | 19.52 | 25.42 | 53.52 | PASS |

## Detailed Results

### B_IO_Binding_Reuse

- **Median Latency:** 33.13ms
- **Mean Latency:** 40.97ms
- **P95 Latency:** 75.43ms
- **FPS:** 30.18
- **Accuracy:** PASS
- **Accuracy Details:** {'status': 'reference_established'}
- **CPU Memory:** 1374.30MB

### G_Combined_AB

- **Median Latency:** 33.49ms
- **Mean Latency:** 40.05ms
- **P95 Latency:** 70.02ms
- **FPS:** 29.86
- **Accuracy:** PASS
- **Accuracy Details:** {'max_diff': 0.0, 'tolerance': 0.0001}
- **CPU Memory:** 1557.01MB

### I_Full_Optimized

- **Median Latency:** 18.69ms
- **Mean Latency:** 19.52ms
- **P95 Latency:** 25.42ms
- **FPS:** 53.52
- **Accuracy:** PASS
- **Accuracy Details:** {'max_diff': 0.0, 'tolerance': 0.0001}
- **CPU Memory:** 1629.43MB

