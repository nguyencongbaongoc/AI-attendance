# MediaMTX Runtime Verification

## MediaMTX Installation

**Executable Location**: `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\mediamtx\mediamtx.exe`
**Size**: 56,565,760 bytes (54 MB)
**Last Modified**: 2026-09-20 23:07

**Config Location**: `C:\Users\Nguyen Cong Thong\Documents\AI_ATTENDANCE_LAST_KNOWN_GOOD_PRE_NVENC_cb34db0a_SOURCE\mediamtx\mediamtx.yml`
**Size**: 28,596 bytes
**Last Modified**: 2026-09-23 20:18

**TLS Certificates**: 
- `auto.crt` (485 bytes)
- `auto.key` (227 bytes)

## MediaMTX Process Status

**Command**: `Get-Process mediamtx`
**Output**: (no process found)

**Command**: `netstat -an | Select-String "8554|8888|8889|9997|1935"`
**Output**: (no ports listening)

**Status**: ❌ NOT RUNNING - MediaMTX process not found, no listening ports

## MediaMTX Configuration Analysis

**Config File**: `mediamtx/mediamtx.yml` (719 lines)

### Global Settings
- **Log Level**: info
- **RTSP**: enabled (port 8554)
- **RTMP**: enabled (port 1935)
- **HLS**: enabled (port 8888, lowLatency variant)
- **WebRTC**: enabled (port 8889)
- **SRT**: enabled (port 8890)
- **API**: enabled (port 9997)
- **Auth Method**: internal (user `any` with publish/read permissions)

### Paths Configured

| Path | Source | Protocol | Purpose |
|------|--------|----------|---------|
| `live/cam1` | publisher | RTMP/RTSP | Camera 1 input |
| `live/cam2` | publisher | RTMP/RTSP | Camera 2 input |
| `live/cam1-ai` | publisher | RTSP | AI annotated output (PipelineEngine) |
| `live/cam2-ai` | publisher | RTSP | AI annotated output (PipelineEngine) |

### RTSP Settings
- **Protocols**: udp, multicast, tcp
- **Encryption**: no
- **RTSP Address**: :8554
- **Auth Methods**: basic

### Recording (Path Defaults)
- **Format**: fmp4
- **Path**: `./recordings/%path/%Y-%m-%d_%H-%M-%S-%f`
- **Segment Duration**: 1h
- **Part Duration**: 1s
- **Delete After**: 24h

## Camera Stream Paths

### Camera 1 Input (`live/cam1`)
```yaml
live/cam1:
  source: publisher
  rtspTransport: tcp
```
- **Expected RTMP Input**: `rtmp://localhost:1935/live/cam1` (stream key: cam1)
- **Expected RTSP Output**: `rtsp://localhost:8554/live/cam1`
- **HLS Output**: `http://localhost:8888/live/cam1/index.m3u8`
- **WebRTC**: Available on :8889

### Camera 2 Input (`live/cam2`)
```yaml
live/cam2:
  source: publisher
  rtspTransport: tcp
```
- **Expected RTMP Input**: `rtmp://localhost:1935/live/cam2` (stream key: cam2)
- **Expected RTSP Output**: `rtsp://localhost:8554/live/cam2`
- **HLS Output**: `http://localhost:8888/live/cam2/index.m3u8`

### AI Annotated Outputs
```yaml
live/cam1-ai:
  source: publisher
  rtspTransport: tcp

live/cam2-ai:
  source: publisher
  rtspTransport: tcp
```
- **PipelineEngine publishes to**: `rtsp://localhost:8554/live/cam1-ai` and `rtsp://localhost:8554/live/cam2-ai`
- **HLS for UI**: `http://localhost:8888/live/cam1-ai/index.m3u8` and `http://localhost:8888/live/cam2-ai/index.m3u8`

## Camera Publisher Status

**No camera publishers detected running** - no active connections to MediaMTX RTMP port (1935)

## Verification Commands Executed

| Check | Command | Result |
|-------|---------|--------|
| MediaMTX Process | `Get-Process mediamtx` | ❌ NOT RUNNING |
| RTSP Port (8554) | `netstat -an | Select-String "8554"` | ❌ NOT LISTENING |
| HLS Port (8888) | `netstat -an | Select-String "8888"` | ❌ NOT LISTENING |
| WebRTC Port (8889) | `netstat -an | Select-String "8889"` | ❌ NOT LISTENING |
| API Port (9997) | `netstat -an | Select-String "9997"` | ❌ NOT LISTENING |
| RTMP Port (1935) | `netstat -an | Select-String "1935"` | ❌ NOT LISTENING |

## Status Summary

| Component | Status | Evidence |
|-----------|--------|----------|
| MediaMTX Binary | ✅ EXISTS | `mediamtx/mediamtx.exe` (54 MB) |
| MediaMTX Config | ✅ EXISTS | `mediamtx/mediamtx.yml` (719 lines) |
| MediaMTX Process | ❌ NOT RUNNING | No process, no listening ports |
| Camera 1 Stream | ❌ NOT RUNNING | No RTMP publisher on :1935/live/cam1 |
| Camera 2 Stream | ❌ NOT RUNNING | No RTMP publisher on :1935/live/cam2 |
| AI Output Paths | ❌ NOT RUNNING | No publisher on live/cam1-ai, live/cam2-ai |
| Recording Path | ✅ CONFIGURED | `./recordings/%path/...` in config |

## Blocker Assessment

**CRITICAL BLOCKER**: MediaMTX is not running. Without MediaMTX:
- No RTSP streams available for ingestion
- No HLS/WebRTC streams for UI playback
- No recording capability
- PipelineEngine cannot start (requires RTSP sources)
- UI cannot display video

**Required to Unblock**: Start MediaMTX with `.\mediamtx.exe` from `mediamtx/` directory.

## Config vs Runtime Gap

| Aspect | Configured | Runtime |
|--------|------------|---------|
| RTSP Server | ✅ :8554 | ❌ Not listening |
| HLS Server | ✅ :8888 | ❌ Not listening |
| WebRTC Server | ✅ :8889 | ❌ Not listening |
| API | ✅ :9997 | ❌ Not listening |
| RTMP Ingest | ✅ :1935 | ❌ Not listening |
| Path live/cam1 | ✅ publisher | ❌ No publisher connected |
| Path live/cam2 | ✅ publisher | ❌ No publisher connected |
| Path live/cam1-ai | ✅ publisher | ❌ No publisher connected |
| Path live/cam2-ai | ✅ publisher | ❌ No publisher connected |

## Next Steps to Enable Runtime
1. Start MediaMTX: `.\mediamtx.exe` from `mediamtx/` directory
2. Verify ports listening: `netstat -an | findstr "8554 8888 8889 9997 1935"`
3. Start camera publishers (RTMP push to :1935/live/cam1, :1935/live/cam2)
4. Verify streams via API: `curl http://localhost:9997/v3/paths/list`
5. Test HLS playback: `http://localhost:8888/live/cam1/index.m3u8`

**Status**: MediaMTX installation verified, but runtime completely unavailable.