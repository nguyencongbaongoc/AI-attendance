# Timestamp Synchronization Design

## Problem Statement

The UI displays video from MediaMTX (HLS/WebRTC) while receiving AI metadata (attendance events, track positions) via WebSocket from Legacy Backend. These two streams must be synchronized so that bounding boxes, labels, and crossing events appear at the correct time and position on the video.

**Core Challenge**: HLS/WebRTC playback timeline ≠ RTSP PTS timeline ≠ Wall-clock timestamps

## Timestamp Sources

### 1. RTSP Stream (Camera → MediaMTX → AI Worker)
| Timestamp | Source | Description |
|-----------|--------|-------------|
| `frame_pts` | RTSP packet | Presentation timestamp (90kHz clock typically) |
| `frame_dts` | RTSP packet | Decode timestamp |
| `time_base` | RTSP stream | e.g., 1/90000 (90kHz) or 1/1000 (1kHz) |
| `capture_timestamp` | AI Worker | `time.time()` when frame acquired |
| `stream_epoch` | AI Worker | Integer incremented on RTSP reconnect |

### 2. Video Playback (MediaMTX → UI)
| Timestamp | Source | Description |
|-----------|--------|-------------|
| `video.currentTime` | HTML5 Video | Seconds from stream start (HLS) or connection (WebRTC) |
| HLS Segment | MediaMTX | Segment index × segment duration |
| WebRTC NTP | WebRTC | NTP-synchronized timestamps |

### 3. AI Processing (AI Worker)
| Timestamp | Source | Description |
|-----------|--------|-------------|
| `processing_timestamp` | AI Worker | `time.time()` after inference complete |
| `frame_index` | AI Worker | Monotonic frame counter |
| `track_id` | Tracker | Local track identifier |

### 4. Attendance Events (Legacy Backend → UI)
| Timestamp | Source | Description |
|-----------|--------|-------------|
| `event_timestamp` | AttendanceRecord | Wall-clock from crossing detection |
| `frame_index` | AttendanceRecord | Frame when crossing occurred |
| `received_timestamp` | UI | When WebSocket message received |

## Synchronization Challenges

### Challenge 1: Clock Domain Mismatch
```
Camera Clock (PTS)     ──► 90kHz PTS
    │
    ▼
AI Worker              ──► Wall-clock (time.time())
    │
    ▼
Legacy Backend         ──► Wall-clock (time.time())
    │
    ▼
UI WebSocket           ──► Wall-clock + network latency
    │
    ▼
Video Player           ──► video.currentTime (HLS segment time)
```

### Challenge 2: HLS Latency & Segmentation
- HLS lowLatency: 1s segments, 200ms parts
- Typical latency: 2-4 seconds behind live
- `video.currentTime` jumps at segment boundaries
- No direct PTS access in browser

### Challenge 3: Stream Reconnects
- RTSP reconnect → PTS reset or jump
- `stream_epoch` tracks reconnect generation
- AI Worker must signal epoch changes

### Challenge 4: Processing Latency Variance
- Decode: 5-15ms
- Inference: 20-40ms
- Tracking: 1-5ms
- Attendance: 1-2ms
- Total: ~30-60ms variable latency
- Network + queue adds 10-100ms

## Proposed Synchronization Contract

### Metadata Per AI Frame (Sent with Each Track/Event Update)

```json
{
  "camera_id": "cam1",
  "stream_epoch": 3,
  "frame_pts": 2700000,
  "time_base_num": 1,
  "time_base_den": 90000,
  "capture_timestamp": 1234567890.123,
  "processing_timestamp": 1234567890.265,
  "frame_index": 12345,
  "tracks": [...],
  "events": [...]
}
```

### Key Synchronization Fields

| Field | Type | Purpose |
|-------|------|---------|
| `stream_epoch` | integer | Reconnect generation (0, 1, 2...) |
| `frame_pts` | integer | RTSP presentation timestamp |
| `time_base_num` | integer | Time base numerator |
| `time_base_den` | integer | Time base denominator (typically 90000) |
| `capture_timestamp` | float | Wall-clock when frame captured (seconds since epoch) |
| `processing_timestamp` | float | Wall-clock after AI processing complete |
| `frame_index` | integer | Monotonic frame counter per epoch |

## UI Synchronization Algorithm

### Step 1: Establish Baseline Mapping
When stream starts or reconnects:
```javascript
// On first metadata frame for new stream_epoch
const baseline = {
  streamEpoch: metadata.stream_epoch,
  framePts: metadata.frame_pts,
  timeBase: metadata.time_base_num / metadata.time_base_den,
  captureWallClock: metadata.capture_timestamp,
  videoCurrentTime: video.currentTime,  // HLS playback position
  receivedWallClock: Date.now() / 1000
};
```

### Step 2: Compute Frame-to-Video Mapping
For each metadata frame:
```javascript
// Convert PTS to seconds since stream start
const ptsSeconds = (metadata.frame_pts - baseline.framePts) * baseline.timeBase;

// Account for processing latency
const latencySeconds = metadata.processing_timestamp - metadata.capture_timestamp;

// Estimated video time for this frame
const estimatedVideoTime = baseline.videoCurrentTime + ptsSeconds - latencySeconds;

// Or simpler: use capture_timestamp directly
const estimatedVideoTime = metadata.capture_timestamp - baseline.captureWallClock + baseline.videoCurrentTime;
```

### Step 3: Render Metadata at Correct Video Time
```javascript
// Store metadata with its target video time
metadataQueue.push({
  targetVideoTime: estimatedVideoTime,
  data: metadata,
  receivedAt: Date.now() / 1000
});

// In requestAnimationFrame loop:
function renderOverlay() {
  const now = video.currentTime;
  
  // Find metadata for current video time (± tolerance)
  const relevant = metadataQueue.filter(m => 
    Math.abs(m.targetVideoTime - now) < 0.1  // 100ms window
  );
  
  // Render boxes, labels, lines
  relevant.forEach(renderMetadata);
  
  // Clean old metadata
  metadataQueue = metadataQueue.filter(m => m.targetVideoTime > now - 1.0);
}
```

### Step 4: Handle Stream Reconnect (Epoch Change)
```javascript
if (metadata.stream_epoch !== currentEpoch) {
  // New epoch - reset baseline
  currentEpoch = metadata.stream_epoch;
  baseline = null;  // Will be re-established on next frame
  
  // Clear stale metadata
  metadataQueue = [];
}
```

### Step 5: Handle Attendance Events (Sparse)
```javascript
// Events have their own timestamp
function handleAttendanceEvent(event) {
  const eventVideoTime = event.capture_timestamp - baseline.captureWallClock + baseline.videoCurrentTime;
  
  // Schedule visual indicator at eventVideoTime
  eventQueue.push({
    targetVideoTime: eventVideoTime,
    event: event,
    duration: 3.0  // Show for 3 seconds
  });
}

// In render loop:
eventQueue.forEach(e => {
  if (video.currentTime >= e.targetVideoTime && video.currentTime <= e.targetVideoTime + e.duration) {
    renderCrossingIndicator(e.event);
  }
});
```

## Handling Clock Drift

### Drift Sources
1. Camera clock vs system clock
2. HLS segment timing inaccuracies
3. Network latency variation
4. Processing latency variation

### Drift Correction
```javascript
// Periodically re-sync using known sync points
// Sync point: Keyframe / IDR frame (PTS known, video frame visible)

function correctDrift(metadata) {
  // If we have a reliable sync point (e.g., every 30 frames @ 30fps = 1s)
  if (metadata.frame_pts % (30 * 90000) === 0) {  // Every 30 frames at 90kHz
    const expectedVideoTime = computeExpectedVideoTime(metadata);
    const actualVideoTime = video.currentTime;
    const drift = actualVideoTime - expectedVideoTime;
    
    if (Math.abs(drift) > 0.5) {  // > 500ms drift
      // Adjust baseline
      baseline.videoCurrentTime += drift;
      console.log(`Drift corrected: ${drift.toFixed(3)}s`);
    }
  }
}
```

## Stream Epoch Design

### Epoch Definition
- `stream_epoch = 0` on initial connection
- Increment on each RTSP reconnect
- AI Worker signals epoch change in metadata

### Epoch in Metadata
```json
{
  "stream_epoch": 3,
  "frame_pts": 123456,
  "time_base_num": 1,
  "time_base_den": 90000
}
```

### Epoch in Attendance Events
```json
{
  "event_id": "ATT-...",
  "stream_epoch": 3,
  "frame_pts": 2700000,
  "capture_timestamp": 1234567890.123
}
```

### UI Epoch Handling
```javascript
let currentEpoch = -1;

function handleMetadata(metadata) {
  if (metadata.stream_epoch !== currentEpoch) {
    console.log(`Stream epoch changed: ${currentEpoch} → ${metadata.stream_epoch}`);
    currentEpoch = metadata.stream_epoch;
    metadataQueue = [];  // Clear stale metadata
    eventQueue = [];     // Clear stale events
    baseline = null;     // Force re-sync
  }
  // ... process metadata
}
```

## Time Base Handling

### Common Time Bases
| Stream Type | Time Base | PTS per Second |
|-------------|-----------|----------------|
| RTSP (H.264) | 1/90000 | 90,000 |
| RTSP (MPEG-TS) | 1/90000 | 90,000 |
| MP4 | 1/1000 or 1/90000 | Varies |
| WebRTC | 1/1000000 (RTP) | 1,000,000 |

### Conversion to Seconds
```javascript
function ptsToSeconds(pts, timeBaseNum, timeBaseDen) {
  return (pts * timeBaseNum) / timeBaseDen;
}

// Example: PTS 2700000 at 1/90000 = 30.0 seconds
const seconds = ptsToSeconds(2700000, 1, 90000);  // 30.0
```

## Latency Budget

| Stage | Typical Latency | Max Latency |
|-------|----------------|-------------|
| Camera encode | 10-50ms | 100ms |
| Network (RTMP) | 10-50ms | 200ms |
| MediaMTX processing | 5-20ms | 50ms |
| HLS segmentation | 1000-3000ms | 5000ms |
| Network (HLS) | 10-100ms | 500ms |
| HLS buffer (3 segments) | 2000-6000ms | 10000ms |
| **Total Video Path** | **3-9 seconds** | **15 seconds** |
| AI Processing | 30-60ms | 100ms |
| Event POST | 10-50ms | 200ms |
| WebSocket delivery | 5-20ms | 100ms |
| **Total AI Path** | **50-130ms** | **500ms** |

### Implication
AI metadata arrives ~3-9 seconds BEFORE corresponding video frame in UI.
UI must buffer metadata and render when `video.currentTime` matches.

## Synchronization Contract Summary

### Required Fields in All AI Metadata
```typescript
interface AIMetadata {
  camera_id: string;
  stream_epoch: number;
  frame_pts: number;
  time_base_num: number;
  time_base_den: number;
  capture_timestamp: number;      // seconds since epoch (float)
  processing_timestamp: number;   // seconds since epoch (float)
  frame_index: number;
  tracks: Track[];
  events: AttendanceEvent[];
}
```

### Required Fields in Attendance Events
```typescript
interface AttendanceEvent {
  event_id: string;
  camera_id: string;
  stream_epoch: number;
  frame_pts: number;
  time_base_num: number;
  time_base_den: number;
  capture_timestamp: number;
  track_id: string;
  direction: "IN" | "OUT";
  crossing_point: [number, number];
  identity: { person_id, person_name, confidence, certainty };
  geometry: { version, config_hash, line_start, line_end };
  resolver: { version, config_hash, previous_state, new_state };
}
```

## Unresolved Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| HLS `video.currentTime` not monotonic | HIGH | Use segment timing, not just currentTime |
| PTS discontinuity on reconnect | HIGH | `stream_epoch` + baseline reset |
| Camera clock drift vs NTP | MEDIUM | Periodic re-sync at keyframes |
| WebRTC vs HLS timeline difference | MEDIUM | Separate sync per protocol |
| Browser `video.currentTime` precision | LOW | Accept ~100ms tolerance |
| Metadata queue memory growth | LOW | TTL-based cleanup |

## Evidence References

| Source | File | Relevant Lines |
|--------|------|----------------|
| PipelineEngine GPUFrame | `pipeline_engine/memory/gpu_frame.py` | 125-130 (pts, dts, time_base) |
| PipelineEngine CameraManager | `pipeline_engine/ingestion/camera_manager.py` | 515-520 (stream_epoch) |
| Legacy Backend AttendanceRecord | `app/attendance/contract.py` | 52 (event_timestamp) |
| MediaMTX Config | `mediamtx/mediamtx.yml` | HLS segment/part duration |
| UI Video Player | `UI/index.html` | hls.js usage, video.currentTime |

## Verification Plan

1. **Unit Test**: Metadata timestamp conversion functions
2. **Integration Test**: Simulated stream with known PTS, verify UI overlay timing
3. **Runtime Test**: 
   - Start stream, measure video.currentTime vs metadata capture_timestamp
   - Trigger reconnect, verify epoch handling
   - Measure end-to-end latency (event → UI render)
4. **Drift Test**: Run 1 hour, measure accumulated drift

## Status

**DESIGN COMPLETE** - Ready for implementation in Phase 1

**Blockers for Verification**:
- MediaMTX not running
- No HLS stream to test `video.currentTime` behavior
- No AI Worker producing metadata
- No WebSocket connection to Legacy Backend