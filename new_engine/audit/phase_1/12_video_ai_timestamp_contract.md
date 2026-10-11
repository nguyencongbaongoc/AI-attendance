# Gate F — Video & AI Metadata Synchronization Design

**Date:** 2026-10-04  
**Phase:** 1  
**Gate:** F  
**Status:** DESIGN PHASE  

---

## 1. Objective

Define timestamp contract for synchronizing original video playback with AI metadata overlay. No annotated video stream — Canvas overlay on original video.

---

## 2. Video Delivery Path Analysis

### 2.1 Current Architecture

**Video Path (Independent):**
```
Camera RTSP → MediaMTX (RTMP ingest) → HLS/WebRTC → UI Video Player
```

**AI Path (Independent):**
```
Camera RTSP → RTSPSource → Pipeline → AI Metadata → Worker → Backend → UI (WebSocket/SSE)
```

### 2.2 MediaMTX Output Formats

From `app/config/settings.py:CamerasConfig`:
- RTSP output: `rtsp://localhost:8554/live/cam1` (and cam2)
- MediaMTX supports HLS and WebRTC output

### 2.3 UI Video Player

From `app/main.py`: Static mount `/recordings` for MP4 files
- Live playback likely via HLS or WebRTC from MediaMTX
- Replay via `/recordings/{camera_id}/{timestamp}.mp4`

---

## 3. Timestamp Contract

### 3.1 Required Timestamp Mapping

| Timeline | Source | Fields | Notes |
|----------|--------|--------|-------|
| **Camera PTS** | RTSP packet | `pts`, `time_base` (num/den) | Native stream timeline |
| **Stream Epoch** | RTSPSource | `stream_epoch` (int) | Increments on reconnect |
| **Capture Timestamp** | Pipeline | `capture_timestamp` (unix float) | Wall-clock at frame capture |
| **Relay Timestamp** | MediaMTX | TBD | If MediaMTX exposes |
| **Browser Playback** | Video element | `currentTime` (seconds) | HLS segment-based |
| **AI Inference** | Pipeline | `processing_timestamp` (unix float) | Wall-clock at AI complete |
| **Metadata Delivery** | Worker | `delivery_timestamp` (unix float) | When sent to UI |

### 3.2 Synchronization Strategy

**For Live Playback (HLS):**
1. HLS segments have `#EXTINF` duration and program date time (`#EXT-X-PROGRAM-DATE-TIME`)
2. Map `capture_timestamp` → HLS segment + offset
3. UI player reports `currentTime` → map to segment → find AI metadata

**For Replay (MP4):**
1. MP4 has PTS/time_base in container
2. `video.currentTime` maps directly to PTS
3. AI metadata has same PTS → direct correlation

**For WebRTC:**
1. RTP timestamps map to NTP via RTCP SR
2. More complex — need MediaMTX WebRTC timing info

---

## 4. AI Metadata Overlay Design

### 4.1 Metadata Schema (per frame)

```typescript
interface AIFrameMetadata {
  camera_id: string;
  stream_epoch: number;
  frame_sequence: number;
  pts: number;
  time_base: { num: number; den: number };
  capture_timestamp: number;
  processing_timestamp: number;
  detections: AIDetection[];
  tracks: AITrack[];
  crossing_line: { p1: {x,y}, p2: {x,y} };
  camera_status: "healthy" | "degraded" | "unhealthy";
  ai_health: "healthy" | "degraded" | "unhealthy";
}

interface AIDetection {
  detection_id: string;
  type: "face" | "person";
  bbox: {x1, y1, x2, y2};  // Original frame coordinates
  confidence: number;
  landmarks?: {x,y}[];       // 5-point for face
}

interface AITrack {
  track_id: number;
  bbox: {x1, y1, x2, y2};
  person_id?: string;
  person_name?: string;
  identity_confidence: number;
  identity_source: "face_recognition" | "reid" | "unknown";
  state: "new" | "active" | "lost";
}
```

### 4.2 Delivery to UI

**Options:**
1. **WebSocket** — Real-time push from Backend (existing `websocket_router`)
2. **SSE** — Server-sent events (existing SSE endpoint)
3. **Polling** — REST API for metadata by time range

**Recommended:** WebSocket for live, REST for replay

### 4.3 Canvas Overlay Rendering

```javascript
// On video timeupdate event:
function renderOverlay(video, metadata) {
  const ctx = canvas.getContext('2d');
  // Match video.displayWidth/Height to canvas
  // Scale coordinates from original frame → display
  // Account for: letterboxing, aspect ratio, CSS transforms
  
  metadata.detections.forEach(det => {
    const scaled = scaleBBox(det.bbox, video, canvas);
    drawRect(ctx, scaled, color);
    if (det.landmarks) drawLandmarks(ctx, det.landmarks);
  });
  
  metadata.tracks.forEach(track => {
    drawTrackId(ctx, track);
    if (track.person_id) drawName(ctx, track);
  });
  
  drawCrossingLine(ctx, metadata.crossing_line);
}
```

### 4.4 Coordinate Transformation

**Original Frame → Display:**
```
original: 3840×2160
display:  video.videoWidth × video.videoHeight (may differ)
CSS:      canvas.width × canvas.height (may differ)

scaleX = canvas.width / video.videoWidth
scaleY = canvas.height / video.videoHeight
// Account for object-fit: contain (letterboxing)
```

---

## 5. Implementation Requirements

### 5.1 Backend API for Metadata

**New endpoint needed:** `GET /api/v1/ai/metadata/{camera_id}?start_pts=&end_pts=` or WebSocket subscription

### 5.2 Worker Metadata Publication

Worker should publish metadata via:
- Health client (already sends camera states)
- New metadata channel (WebSocket broadcast)

### 5.3 Frontend Integration

- Connect to WebSocket/SSE for live metadata
- On video `timeupdate`, find nearest metadata frame
- Render Canvas overlay

---

## 6. Gate F Tests

| Test | Description |
|------|-------------|
| T1 | Live HLS: `video.currentTime` maps to AI metadata |
| T2 | Replay MP4: `video.currentTime` maps to AI metadata |
| T3 | Canvas overlay renders at correct positions |
| T4 | Coordinate scaling handles letterboxing |
| T5 | Metadata expires after frame too old |
| T6 | Stream reconnect handled (stream_epoch) |
| T7 | Seeking updates overlay correctly |
| T8 | Camera status reflected in overlay |

---

## 7. Gate F Verdict

**DESIGN COMPLETE** — Timestamp contract defined, overlay approach specified.

**Requires Implementation:**
1. Backend metadata API endpoint
2. Worker metadata publishing (WebSocket)
3. Frontend Canvas overlay component
4. Timestamp mapping for HLS/WebRTC/MP4

**Blocked By:** Running video pipeline for timestamp correlation analysis.

**Ready for Gate G** — Dual-Camera Qualification