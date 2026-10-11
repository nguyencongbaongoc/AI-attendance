# UI Integration Audit

## UI Implementation (`UI/index.html`)

**Status: IMPLEMENTED (Single HTML file with embedded JS/CSS)**

### Architecture
- Single-file HTML + Tailwind CSS + vanilla JavaScript
- No build step, no framework (React/Vue)
- hls.js for HLS video playback
- WebSocket for real-time health updates
- Direct REST calls to Legacy Backend (port 8000)

### Configuration
```javascript
const API_CONFIG = {
    get baseURL() {
        return window.__API_BASE_URL__ || 'http://localhost:8000';
    },
    get wsURL() {
        const base = this.baseURL.replace(/^http/, 'ws');
        return `${base}/api/v1/health/ws`;
    },
    endpoints: {
        health: '/api/v1/health',
        attendance: '/api/v1/attendance',
        enrollment: '/api/v1/enrollment',
        replay: '/api/v1/replay',
        geometry: '/api/v1/geometry',
    }
};
```

### Pages/Views
| Page | Route | Features |
|------|-------|----------|
| Dashboard | `#page-dashboard` | Stats cards, live preview thumbnails, recent attendance |
| Live Monitoring | `#page-live` | Dual 4K video, line drawing tool, camera switch, annotation toggle |
| ArcFace/NPY | `#page-arcface` | Image upload, face detect/crop, embedding generation, NPY creation |
| Video Review | `#page-video` | Placeholder |
| Backend Health | `#page-health` | Placeholder |
| Records | `#page-records` | Placeholder |

### Video Playback
```html
<!-- Live Monitoring uses static images as placeholders -->
<img id="video1" src="https://images.unsplash.com/...">
<canvas id="canvas1" class="absolute inset-0 w-full h-full cursor-crosshair"></canvas>

<!-- hls.js loaded but not used in current implementation -->
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest/dist/hls.min.js"></script>
```

**Current**: Static image placeholders with canvas overlay for line drawing
**Required**: hls.js playing `http://localhost:8888/live/cam1-ai/index.m3u8`

### Line Drawing Tool
- Canvas-based drawing on video overlay
- Click-drag to create line (start→end)
- Save → sends to WebSocket `/api/line`
- Loads line config from geometry API

### Real-time Updates
```javascript
class HealthWebSocket {
    connect() → WebSocket to API_CONFIG.wsURL
    Handles: health_update, health_event, sync_response, pong
    Auto-reconnect with exponential backoff
}
```

### Data Flow (Current)
```
UI (localhost:5173 or file://)
    │
    ├── REST → Legacy Backend (localhost:8000)
    │   ├── /api/v1/health/*
    │   ├── /api/v1/attendance/*
    │   ├── /api/v1/enrollment/*
    │   ├── /api/v1/geometry/*
    │   └── /api/v1/replay/*
    │
    └── WebSocket → Legacy Backend (localhost:8000/api/v1/health/ws)
        ├── health_update (periodic)
        ├── health_event (attendance events)
        └── pong (heartbeat)
```

### MediaMTX Integration
| Stream | Protocol | URL | UI Usage |
|--------|----------|-----|----------|
| cam1 (raw) | RTSP | `rtsp://localhost:8554/live/cam1` | Not used |
| cam2 (raw) | RTSP | `rtsp://localhost:8554/live/cam2` | Not used |
| cam1-ai | HLS | `http://localhost:8888/live/cam1-ai/index.m3u8` | Should use hls.js |
| cam2-ai | HLS | `http://localhost:8888/live/cam2-ai/index.m3u8` | Should use hls.js |
| cam1-ai | WebRTC | `webrtc://localhost:8889/live/cam1-ai` | Alternative |
| cam2-ai | WebRTC | `webrtc://localhost:8889/live/cam2-ai` | Alternative |

---

## Integration with PipelineEngine Backend

### Current State
- **UI calls Legacy Backend (port 8000)** for all APIs
- **PipelineEngine Backend (port dynamic)** is NOT used by UI
- PipelineEngine Backend has duplicate endpoints that UI doesn't call

### PipelineEngine Backend Endpoints (Unused by UI)
| Endpoint | UI Equivalent (Legacy Backend) |
|----------|-------------------------------|
| `/api/v1/health/system` | `/api/v1/health` |
| `/api/v1/cameras/*` | `/api/v1/cameras/*` |
| `/api/v1/attendance/*` | `/api/v1/attendance/*` |
| `/api/v1/geometry/lines/*` | `/api/v1/geometry/*` |
| `/api/v1/video/streams` | Not used |
| `/api/v1/ws` | `/api/v1/health/ws` |

### Conflict
- Two backends exposing similar APIs
- UI hardcoded to Legacy Backend (port 8000)
- PipelineEngine Backend has no consumers

---

## Attendance Event Display

### Dashboard (Recent Attendance)
```javascript
// Hardcoded mock data in HTML
<div class="flex items-center gap-3 p-2.5 rounded-xl bg-white text-black">
    <img src="https://i.pravatar.cc/100?img=15">
    <div>Trần Anh Tuấn</div>
    <div>ID 1042 • CAM-01 • IN</div>
    <div>08:42:11</div>
    <div>CONF 0.94</div>
</div>
```

### Live Monitoring (Line Crossing Counts)
```html
<!-- Mock counters -->
<span>AI Tracking • 3 persons • IN: 12 / OUT: 4</span>
<span>AI Tracking • 2 persons • IN: 8 / OUT: 7</span>
```

### Real-time Gap
- WebSocket receives `health_event` with attendance data
- **No handler** to update dashboard/live counters
- Counters are static HTML

---

## ArcFace/NPY Enrollment Page

### Features
1. **Image Upload** - Drag-drop or file picker
2. **Face Detection** - Calls `/api/v1/enrollment/detect` (not implemented)
3. **Face Crop** - 112×112 aligned crop display
4. **Embedding Generation** - Calls `/api/v1/enrollment/embedding` (not implemented)
5. **NPY Creation** - Form for name/ID/department, saves to `embeddings.npy`

### API Calls (Not Implemented)
```javascript
// Detect face in uploaded image
await api.post('/api/v1/enrollment/detect', { image: base64 })

// Generate embedding
await api.post('/api/v1/enrollment/embedding', { crop: base64 })

// Save NPY
await api.post('/api/v1/enrollment/save', { 
    name, id, department, camera, embedding 
})
```

### Current Implementation
- Frontend only (no backend integration)
- `createNpy()` function creates NPY client-side (not possible without backend)
- Embedding display shows placeholder

---

## Video Review Page

### Status
- Placeholder page (`#page-video`)
- No implementation
- Would need: replay API, timeline, event filtering, video player

---

## Backend Health Page

### Status
- Placeholder page (`#page-health`)
- No implementation
- Would show: system metrics, camera health, GPU usage, pipeline status

---

## Records Page

### Status
- Placeholder page (`#page-records`)
- No implementation
- Would show: attendance history, filters, export

---

## Missing UI Features for Architecture A

### 1. Live Video Playback
```javascript
// Required: hls.js integration
const video = document.getElementById('videoElement');
if (Hls.isSupported()) {
    const hls = new Hls();
    hls.loadSource('http://localhost:8888/live/cam1-ai/index.m3u8');
    hls.attachMedia(video);
}
```

### 2. Real-time Attendance Updates
```javascript
healthWS.on('health_event', (event) => {
    if (event.type === 'attendance') {
        updateAttendanceCounters(event.data);
        addToRecentAttendanceList(event.data);
    }
});
```

### 3. AI Metadata Overlay
- Current: Canvas drawing for line tool only
- Required: Bounding boxes, track IDs, names from WebSocket metadata
- Options:
  a) Canvas overlay on video (current approach)
  b) CSS overlay with transformed coordinates
  c) Server-side annotation (current PipelineEngine approach)

### 4. Camera Switching
- Current: Buttons exist but only show/hide static images
- Required: Switch hls.js source, update canvas overlay

### 5. Configuration Management
- Line geometry: Save to Legacy Backend via API
- Camera config: Not exposed in UI
- Model thresholds: Not exposed in UI

---

## Architecture A Evaluation: UI

### Current Architecture (PipelineEngine)
```
Camera → PipelineEngine (decode+AI+annotate+encode) → MediaMTX → HLS → UI
                                    │
                                    └── Annotated video with baked-in boxes/lines
```

### Architecture A (Proposed)
```
Camera → MediaMTX (passthrough) → HLS → UI (raw video)
Camera → PyAV → Decode → AI → Metadata → Backend → WebSocket → UI (overlay)
```

### UI Changes Required for Architecture A

| Feature | Current | Architecture A | Effort |
|---------|---------|----------------|--------|
| Video Source | `cam1-ai` (annotated) | `cam1` (raw) | Low |
| Annotations | Baked in video | Canvas overlay from WebSocket | High |
| Line Drawing | Canvas on static image | Canvas on live video | Medium |
| Attendance Events | Static mock | Real-time WebSocket | Medium |
| Geometry Config | Save to WS `/api/line` | Save to Legacy Backend REST | Low |
| Enrollment | Client-side mock | Backend API integration | High |

### Overlay Implementation Options

#### Option A: Canvas Overlay (Current Approach)
```javascript
// On each video frame (requestAnimationFrame):
ctx.clearRect(0, 0, canvas.width, canvas.height);
// Draw boxes, labels, lines from latest metadata
metadata.tracks.forEach(track => {
    drawBox(ctx, track.bbox);
    drawLabel(ctx, track);
});
drawLine(ctx, geometry.line);
```
**Pros**: Full control, GPU accelerated via canvas
**Cons**: Must sync with video frames, coordinate transformation

#### Option B: CSS Overlay
```html
<div class="video-container">
    <video id="video"></video>
    <div class="overlay" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none">
        <div class="bbox" style="position:absolute;left:10%;top:20%;width:15%;height:30%"></div>
    </div>
</div>
```
**Pros**: Browser handles layout, easier coordinates
**Cons**: Transform needed (video coords → CSS %), performance at 4K

#### Option C: Server-side Annotation (Current PipelineEngine)
- Keep NVENC annotation, UI just plays video
- **Not Architecture A**

### Recommended for Architecture A: Option A (Canvas)
- Matches existing line drawing tool
- Can reuse canvas/context
- Coordinate mapping: video (3840×2160) → canvas (display size)

---

## Coordinate Transformation

### Video → Display Mapping
```
Video: 3840 × 2160 (source)
Display: CSS size (e.g., 1280 × 720)

scale_x = display_width / 3840
scale_y = display_height / 2160

bbox_display = {
    x: bbox_video.x * scale_x,
    y: bbox_video.y * scale_y,
    width: bbox_video.width * scale_x,
    height: bbox_video.height * scale_y
}
```

### Required Metadata Schema (WebSocket)
```json
{
    "type": "ai_metadata",
    "camera_id": "cam1",
    "frame_id": 12345,
    "timestamp": 1234567890.123,
    "tracks": [
        {
            "track_id": 42,
            "bbox": [1000, 500, 1200, 900],
            "person_id": "NV001",
            "person_name": "John Doe",
            "confidence": 0.94,
            "face_bbox": [1050, 550, 1150, 650]
        }
    ],
    "geometry": {
        "line_start": [0, 1080],
        "line_end": [3840, 1080]
    }
}
```

---

## Legacy Backend API Requirements for UI

### Required Endpoints (Legacy Backend must provide)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/health/live` | GET | Liveness |
| `/api/v1/health/ws` | WS | Real-time health + attendance |
| `/api/v1/cameras` | GET | Camera list with stream URLs |
| `/api/v1/cameras/{id}` | GET | Camera details |
| `/api/v1/attendance/events` | GET | Filtered attendance events |
| `/api/v1/attendance/daily/{date}` | GET | Daily summary |
| `/api/v1/attendance/recent` | GET | Recent events for dashboard |
| `/api/v1/geometry/lines` | GET | All line configs |
| `/api/v1/geometry/lines/{id}` | GET/PUT | Line config per camera |
| `/api/v1/enrollment/list` | GET | Enrolled persons |
| `/api/v1/enrollment/detect` | POST | Face detect in image |
| `/api/v1/enrollment/embedding` | POST | Generate embedding |
| `/api/v1/enrollment/save` | POST | Save to NPY |
| `/api/v1/replay/segments` | GET | Video segments for date/camera |
| `/api/v1/replay/stream` | GET | HLS manifest for replay |

---

## UI Technology Stack Assessment

| Aspect | Current | Assessment |
|--------|---------|------------|
| Framework | Vanilla JS + Tailwind | Lightweight, no build, but manual DOM management |
| State Management | Global variables + DOM | Error-prone at scale |
| Real-time | WebSocket (custom class) | Works but no reconnection UI |
| Video | hls.js (loaded, unused) | Standard, good browser support |
| Canvas Drawing | Manual | Works for line tool, needs extension for boxes |
| Responsive | Tailwind CSS | Good |
| TypeScript | No | Would help maintenance |
| Testing | None | Need integration tests |

### Recommendation
- **Keep vanilla JS** for Architecture A (simple, no build)
- Add **simple state management** (pub/sub or signals)
- Implement **hls.js playback** for live streams
- Extend **canvas overlay** for AI metadata
- Add **WebSocket message handlers** for attendance events

---

## Runtime Verification

**UI: PARTIALLY VERIFIED**

- ✅ Static pages render correctly
- ✅ Line drawing tool works on canvas
- ✅ Tailwind styling renders
- ❌ No live video playback (hls.js not connected)
- ❌ No real-time data (WebSocket to Legacy Backend not tested)
- ❌ No attendance events displayed dynamically
- ❌ ArcFace/NPY enrollment not functional (no backend)
- ❌ Video review, health, records pages not implemented

### Test Procedure
1. Start Legacy Backend on port 8000
2. Start MediaMTX with streams on `live/cam1-ai`, `live/cam2-ai`
3. Open `UI/index.html` via HTTP server (not file:// for CORS)
4. Verify WebSocket connects to `ws://localhost:8000/api/v1/health/ws`
5. Verify hls.js plays streams
6. Verify attendance events appear in real-time