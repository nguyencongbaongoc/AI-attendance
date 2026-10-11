import json
from pathlib import Path

data_path = Path("benchmark_results/surfaces_experiment/experiment_raw_data.json")
with open(data_path, "r", encoding="utf-8") as f:
    d = json.load(f)

print("=== ENVIRONMENT ===")
for k, v in d["env_info"].items():
    print(f"  {k}: {v}")

print("\n=== STAGE 1, 2, 3: CAM1 30-SECOND TRIALS ===")
print(f"{'Config':<15} | {'Run':<4} | {'av.open':<8} | {'Open Time':<10} | {'1st Frame':<10} | {'1st Time':<10} | {'Frames':<8} | {'FPS':<6} | {'Peak VRAM':<11} | {'Delta VRAM':<11} | {'Status':<12}")
print("-" * 115)
for t in d["trials"]:
    open_str = "PASS" if t["stage1_open_success"] else "FAIL"
    open_time = f"{t['stage1_open_time_s']*1000:.1f}ms"
    first_str = "PASS" if t["stage2_first_frame_success"] else "FAIL"
    first_time = f"{t['stage2_first_frame_time_s']*1000:.1f}ms" if t["stage2_first_frame_success"] else "N/A"
    status = "PASS" if t["stage_sustained_success"] else "FAIL"
    print(f"{t['config_name']:<15} | R{t['run_index']:<3} | {open_str:<8} | {open_time:<10} | {first_str:<10} | {first_time:<10} | {t['frames_decoded']:<8} | {t['decode_fps']:<6.2f} | {t['vram_peak_mb']:<9.1f}MB | {t['vram_delta_mb']:<+9.1f}MB | {status:<12}")

print("\n=== STAGE 4: CAM1 180-SECOND QUALIFICATION ===")
print(f"{'Config':<15} | {'av.open':<8} | {'Open Time':<10} | {'1st Frame':<10} | {'Frames':<8} | {'FPS':<6} | {'Peak VRAM':<11} | {'Delta VRAM':<11} | {'Status':<12}")
print("-" * 105)
for t in d["qualification_180s"]:
    open_str = "PASS" if t["stage1_open_success"] else "FAIL"
    open_time = f"{t['stage1_open_time_s']*1000:.1f}ms"
    first_str = "PASS" if t["stage2_first_frame_success"] else "FAIL"
    status = "PASS" if t["stage_sustained_success"] else "FAIL"
    print(f"{t['config_name']:<15} | {open_str:<8} | {open_time:<10} | {first_str:<10} | {t['frames_decoded']:<8} | {t['decode_fps']:<6.2f} | {t['vram_peak_mb']:<9.1f}MB | {t['vram_delta_mb']:<+9.1f}MB | {status:<12}")

print("\n=== STAGE 5A: CAM2 30-SECOND INDEPENDENT QUALIFICATION ===")
print(f"{'Config':<15} | {'av.open':<8} | {'Open Time':<10} | {'1st Frame':<10} | {'Frames':<8} | {'FPS':<6} | {'Peak VRAM':<11} | {'Delta VRAM':<11} | {'Status':<12}")
print("-" * 105)
for t in d["cam2_trials"]:
    open_str = "PASS" if t["stage1_open_success"] else "FAIL"
    open_time = f"{t['stage1_open_time_s']*1000:.1f}ms"
    first_str = "PASS" if t["stage2_first_frame_success"] else "FAIL"
    status = "PASS" if t["stage_sustained_success"] else "FAIL"
    print(f"{t['config_name']:<15} | {open_str:<8} | {open_time:<10} | {first_str:<10} | {t['frames_decoded']:<8} | {t['decode_fps']:<6.2f} | {t['vram_peak_mb']:<9.1f}MB | {t['vram_delta_mb']:<+9.1f}MB | {status:<12}")

print("\n=== STAGE 5B: DUAL-CAMERA CONCURRENT (CAM1 + CAM2, 30s) ===")
print(f"{'Config':<15} | {'Duration':<9} | {'CAM1 Frames':<12} | {'CAM1 FPS':<9} | {'CAM2 Frames':<12} | {'CAM2 FPS':<9} | {'Total FPS':<10} | {'Peak VRAM':<11} | {'Delta VRAM':<11}")
print("-" * 115)
for t in d["dual_concurrent"]:
    print(f"{t['config_name']:<15} | {t['duration_s']:<7.1f}s | {t['cam1_frames']:<12} | {t['cam1_fps']:<9.1f} | {t['cam2_frames']:<12} | {t['cam2_fps']:<9.1f} | {t['total_fps']:<10.1f} | {t['vram_peak_mb']:<9.1f}MB | {t['vram_delta_mb']:<+9.1f}MB")

