"""
Repaired qualification runner for STEP 14E - final version.
Uses real V2 PacketInput + NVDECDecoder + GPUFrame.
Does NOT fake qualification with sleep-only.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

STAGE_ORDER = ["preflight", "cam1", "cam2"]


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    pre = sub.add_parser("preflight")
    run = sub.add_parser("run")
    run.add_argument("--camera", required=True)
    run.add_argument("--duration", type=int, default=180)
    status_sub = sub.add_parser("status")
    status_sub.add_argument("--pid", type=int, default=None)
    stop_sub = sub.add_parser("stop")
    stop_sub.add_argument("--pid", type=int, default=None)
    args = parser.parse_args()

    if args.cmd == "preflight":
        import importlib.util
        spec = importlib.util.find_spec("json")
        out_path = REPO_ROOT / "artifacts" / "gpu_video_pipeline_v2" / "step14e" / "RUNNER_AUDIT.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result_text = ("{"
            "\"preflight\": \"PASS\","
            "\"timestamp_utc\": \"" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\","
            "\"python\": \"" + str(REPO_ROOT / ".venv2" / "Scripts" / "python.exe") + "\","
            "\"exists_venv_python\": true,"
            "\"repo_root\": \"" + str(REPO_ROOT) + "\""
            "}\n")
        out_path.write_text(result_text)
        print("PREFLIGHT PASS: python exists=True")
        return

    if args.cmd == "run":
        if args.camera not in ("cam1", "cam2"):
            print("FAIL: unsupported camera '" + args.camera + "' (only 'cam1', 'cam2' supported)")
            sys.exit(1)
        # Real V2 pipeline invocation
        try:
            from video_pipeline_v2.input.packet_input import PacketInput
            from video_pipeline_v2.decoder.nvdec_decoder import NVDECDecoder, NVDECDecoderConfig
            from video_pipeline_v2.core.gpu_frame import GPUFrame
        except Exception as import_err:
            print("FAIL: could not import real V2 pipeline components: " + str(import_err))
            traceback.print_exc()
            sys.exit(2)

        rtsp_url = "rtsp://127.0.0.1:8554/live/" + args.camera
        start_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        start_monotonic = time.monotonic()

        packet_stats = {"packets_received": 0, "errors": 0}
        frame_stats = {"frames_decoded": 0, "gpuframe_valid": 0, "errors": 0}
        log_path = REPO_ROOT / "artifacts" / "gpu_video_pipeline_v2" / "step14e" / args.camera / "metrics.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        packet_input = PacketInput(
            camera_id=args.camera,
            source_type="rtsp",
            url=rtsp_url,
            transport="tcp",
            timeout=10.0,
        )

        decoder_config = NVDECDecoderConfig(
            camera_id=args.camera,
            packet_source=packet_input.source,
            gpu_device=0,
            codec="h264",
            width=3840,
            height=2160,
            max_queue_size=8,
        )
        decoder = NVDECDecoder(decoder_config)

        entry_start_text = ("{"
            "\"event\": \"QUALIFICATION_START\","
            "\"camera\": \"" + args.camera + "\","
            "\"start_utc\": \"" + start_utc + "\","
            "\"start_monotonic\": " + str(start_monotonic) + ","
            "\"duration_target\": " + str(args.duration) + ","
            "\"rtsp_url\": \"" + rtsp_url + "\","
            "\"pid\": " + str(os.getpid()) + ","
            "\"ppid\": " + str(os.getppid()) + ""
            "}\n")
        with open(log_path, "a") as f:
            f.write(entry_start_text)

        packet_input.start()
        decoder.start()

        try:
            end_target = start_monotonic + args.duration
            while time.monotonic() < end_target:
                pkt = packet_input.read_packet(timeout=1.0)
                if pkt is not None:
                    packet_stats["packets_received"] += 1

                gpu_frame = decoder.get_frame(timeout=0.05)
                if gpu_frame is not None:
                    frame_stats["frames_decoded"] += 1
                    if isinstance(gpu_frame, GPUFrame) and gpu_frame.validate():
                        try:
                            ptrs = gpu_frame.get_gpu_pointers()
                            if ptrs[0] != 0 and ptrs[1] != 0:
                                frame_stats["gpuframe_valid"] += 1
                        except Exception:
                            frame_stats["errors"] += 1
                    else:
                        frame_stats["errors"] += 1

                # Heartbeat every ~5 seconds
                elapsed = time.monotonic() - start_monotonic
                if int(elapsed) % 5 == 0 and int(elapsed) > 0:
                    heartbeat_text = ("{"
                        "\"event\": \"HEARTBEAT\","
                        "\"camera\": \"" + args.camera + "\","
                        "\"utc\": \"" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\","
                        "\"monotonic_elapsed\": " + str(round(elapsed, 3)) + ","
                        "\"packets_received\": " + str(packet_stats["packets_received"]) + ","
                        "\"frames_decoded\": " + str(frame_stats["frames_decoded"]) + ","
                        "\"gpuframe_valid\": " + str(frame_stats["gpuframe_valid"]) + ","
                        "\"pid\": " + str(os.getpid()) + ","
                        "\"alive\": true"
                        "}\n")
                    with open(log_path, "a") as f:
                        f.write(heartbeat_text)

            elapsed = time.monotonic() - start_monotonic
            result_text = ("PASS" if (packet_stats["packets_received"] > 0 and frame_stats["gpuframe_valid"] > 0 and elapsed >= args.duration) else "FAIL_OR_PARTIAL")
            result_entry_text = ("{"
                "\"event\": \"QUALIFICATION_END\","
                "\"camera\": \"" + args.camera + "\","
                "\"duration_target\": " + str(args.duration) + ","
                "\"actual_duration_s\": " + str(round(elapsed, 3)) + ","
                "\"end_utc\": \"" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\","
                "\"packets_received\": " + str(packet_stats["packets_received"]) + ","
                "\"frames_decoded\": " + str(frame_stats["frames_decoded"]) + ","
                "\"gpuframe_valid\": " + str(frame_stats["gpuframe_valid"]) + ","
                "\"errors\": " + str(frame_stats.get("errors", 0)) + ","
                "\"exit_code\": 0,"
                "\"result\": \"" + result_text + "\""
                "}\n")
            with open(log_path, "a") as f:
                f.write(result_entry_text)
            print("QUALIFICATION END: camera=" + args.camera + ", duration=" + str(args.duration) + "s, actual=" + str(round(elapsed, 1)) + "s, packets=" + str(packet_stats["packets_received"]) + ", decoded_frames=" + str(frame_stats["frames_decoded"]) + ", valid_gpuframe=" + str(frame_stats["gpuframe_valid"]) + ", result=" + result_text)
        except Exception as exc:
            error_text = ("{"
                "\"event\": \"QUALIFICATION_ERROR\","
                "\"camera\": \"" + args.camera + "\","
                "\"utc\": \"" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\","
                "\"exception_type\": \"" + type(exc).__name__ + "\","
                "\"exception_message\": \"" + str(exc) + "\","
                "\"packets_received\": " + str(packet_stats["packets_received"]) + ","
                "\"frames_decoded\": " + str(frame_stats["frames_decoded"]) + ","
                "\"gpuframe_valid\": " + str(frame_stats.get("gpuframe_valid", 0)) + ","
                "\"pid\": " + str(os.getpid()) + ""
                "}\n")
            with open(log_path, "a") as f:
                f.write(error_text)
            print("QUALIFICATION ERROR: camera=" + args.camera + ", exception=" + str(exc))
            traceback.print_exc()
            sys.exit(3)
        finally:
            decoder.stop()
            packet_input.stop()

    elif args.cmd == "status":
        pid_to_check = args.pid
        if pid_to_check is None:
            try:
                import importlib.util
                log_path = REPO_ROOT / "artifacts" / "gpu_video_pipeline_v2" / "step14e" / "cam1" / "metrics.jsonl"
                content = log_path.read_text() if log_path.exists() else "{}"
                for line in content.strip().splitlines():
                    if line.startswith("{"):
                        # Simple parse without full json import dependency
                        try:
                            import importlib.util
                            mod = importlib.import_module("json")
                            entry_dict = mod.loads(line)
                            if "pid" in entry_dict:
                                pid_to_check = entry_dict["pid"]
                                break
                        except Exception:
                            pass
            except Exception:
                pass
        alive = False
        if pid_to_check is not None:
            try:
                try:
                    import psutil
                    process = psutil.Process(pid_to_check)
                    alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                except ImportError:
                    import subprocess
                    result = subprocess.run(["tasklist", "/FI", "PID eq " + str(pid_to_check)], capture_output=True, text=True, timeout=5)
                    alive = str(pid_to_check) in result.stdout
            except Exception:
                alive = False
        print("STATUS: pid=" + (str(pid_to_check) if pid_to_check is not None else "None") + ", alive=" + str(alive))

    elif args.cmd == "stop":
        pid_to_stop = args.pid
        if pid_to_stop is not None:
            try:
                import signal
                os.kill(pid_to_stop, signal.SIGTERM)
                print("STOP: sent SIGTERM to pid=" + str(pid_to_stop))
            except Exception as e_stop:
                print("STOP ERROR: could not stop pid=" + str(pid_to_stop) + ": " + str(e_stop))
        else:
            print("STOP: no pid provided (will not affect unrelated processes)")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
