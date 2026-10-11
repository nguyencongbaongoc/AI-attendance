# UI Video Metadata Alignment

## Current UI Implementation

### Video Player (UI/index.html)
- **hls.js** loaded from CDN for HLS playback
- **Static image placeholders** currently used (not live video)
- **Canvas overlay** for line drawing tool
- **No AI metadata rendering** implemented

### Video Element Structure
```html
<div id="wrap1" class="relative aspect-[16/9] bg-black overflow-hidden video-grid">
  <img id="video1" src="https://images.unsplash.com/..." class="w-full h-full object-cover opacity-80">
  <canvas id="canvas1" class="absolute inset-0 w-full h-full cursor-crosshair"></canvas>
  <div id="bboxLayer1" class="absolute inset-0 pointer-events-none"></div>
  <div id="drawHint1" class="absolute top-2 left-1/2 -translate-x-1/2 ... hidden">Đang vẽ...</div>
</div>
```

**Current**: Static `<img>` + `<canvas>` for drawing
**Required**: `<video>` element with hls.js + `<canvas>` for AI overlay

## Video Source URLs (Architecture A)

### Raw Camera Streams (Video Path)
| Camera | HLS URL | WebRTC URL |
|--------|---------|------------|
| Camera 1 | `http://localhost:8888/live/cam1/index.m3u8` | `webrtc://localhost:8889/live/cam1` |
| Camera 2 | `http://localhost:8888/live/cam2/index.m3u8` | `webrtc://localhost:8889/live/cam2` |

### AI Annotated Streams (Not Used in Architecture A)
| Camera | HLS URL | WebRTC URL |
|--------|---------|------------|
| Camera 1 AI | `http://localhost:8888/live/cam1-ai/index.m3u8` | `webrtc://localhost:8889/live/cam1-ai` |
| Camera 2 AI | `http://localhost:8888/live/cam2-ai/index.m3u8` | `webrtc://localhost:8889/live/cam2-ai` |

## Required UI Changes for Architecture A

### 1. Replace Static Image with Video Element
```html
<!-- Current -->
<img id="video1" src="..." class="w-full h-full object-cover opacity-80">
<canvas id="canvas1" class="absolute inset-0 w-full h-full cursor-crosshair"></canvas>

<!-- Required -->
<video id="video1" class="w-full h-full object-cover" muted playsinline></video>
<canvas id="overlay1" class="absolute inset-0 w-full h-full pointer-events-none"></canvas>
```

### 2. hls.js Integration
```javascript
// Initialize hls.js for each camera
function initHlsPlayer(videoElement, hlsUrl) {
  if (Hls.isSupported()) {
    const hls = new Hls({
      lowLatencyMode: true,
      enableWorker: true,
      maxBufferLength: 30,
      maxMaxBufferLength: 60,
    });
    
    hls.loadSource(hlsUrl);
    hls.attachMedia(videoElement);
    
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      videoElement.play().catch(() => {});
    });
    
    hls.on(Hls.Events.ERROR, (event, data) => {
      if (data.fatal) {
        console.error('HLS error:', data);
        // Attempt recovery
      }
    });
    
    return hls;
  } else if (videoElement.canPlayType('application/vnd.apple.mpegurl')) {
    videoElement.src = hlsUrl;
    videoElement.addEventListener('loadedmetadata', () => {
      videoElement.play().catch(() => {});
    });
  }
}
```

### 3. Canvas Overlay for AI Metadata
```javascript
// Coordinate transformation: Video (3840×2160) → Canvas (display size)
function videoToCanvas(videoRect, videoCoords) {
  const scaleX = videoRect.width / 3840;
  const scaleY = videoRect.height / 2160;
  return {
    x: videoCoords.x * scaleX,
    y: videoCoords.y * scaleY,
    width: videoCoords.width * scaleX,
    height: videoCoords.height * scaleY
  };
}

// Render AI metadata on canvas
function renderAIOverlay(ctx, videoRect, metadata) {
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  
  // Draw line
  if (metadata.geometry) {
    const lineStart = videoToCanvas(videoRect, { x: metadata.geometry.line_start[0], y: metadata.geometry.line_start[1] });
    const lineEnd = videoToCanvas(videoRect, { x: metadata.geometry.line_end[0], y: metadata.geometry.line_end[1] });
    ctx.strokeStyle = '#ffff00';
    ctx.lineWidth = 2;
    ctx.setLineDash([8, 4]);
    ctx.beginPath();
    ctx.moveTo(lineStart.x, lineStart.y);
    ctx.lineTo(lineEnd.x, lineEnd.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  
  // Draw tracks
  metadata.tracks?.forEach(track => {
    const bbox = videoToCanvas(videoRect, {
      x: track.bbox[0], y: track.bbox[1],
      width: track.bbox[2] - track.bbox[0],
      height: track.bbox[3] - track.bbox[1]
    });
    
    // Bounding box
    ctx.strokeStyle = track.identity?.certainty === 'KNOWN' ? '#00ff00' : '#ff0000';
    ctx.lineWidth = 2;
    ctx.strokeRect(bbox.x, bbox.y, bbox.width, bbox.height);
    
    // Label
    const label = `${track.identity?.person_name || 'Unknown'} ${track.identity?.confidence?.toFixed(2) || ''} ID:${track.track_id}`;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = '12px JetBrains Mono';
    ctx.fillText(label, bbox.x, bbox.y - 4);
    
    // Face bbox if available
    if (track.face_bbox) {
      const faceBox = videoToCanvas(videoRect, {
        x: track.face_bbox[0], y: track.face_bbox[1],
        width: track.face_bbox[2] - track.face_bbox[0],
        height: track.face_bbox[3] - track.face_bbox[1]
      });
      ctx.strokeStyle = '#0000ff';
      ctx.lineWidth = 1;
      ctx.strokeRect(faceBox.x, faceBox.y, faceBox.width, faceBox.height);
    }
  });
  
  // Draw attendance events (recent)
  metadata.events?.forEach(event => {
    const point = videoToCanvas(videoRect, { x: event.crossing_point[0], y: event.crossing_point[1] });
    ctx.fillStyle = event.direction === 'IN' ? '#00ff00' : '#ff0000';
    ctx.beginPath();
    ctx.arc(point.x, point.y, 8, 0, 2 * Math.PI);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = '10px JetBrains Mono';
    ctx.fillText(`${event.direction} ${event.identity?.person_name || ''}`, point.x + 10, point.y + 4);
  });
}
```

### 4. Metadata Synchronization (from timestamp sync design)
```javascript
class MetadataSynchronizer {
  constructor() {
    this.baseline = null;
    this.currentEpoch = -1;
    this.metadataQueue = [];
    this.eventQueue = [];
  }
  
  handleMetadata(metadata) {
    // Handle epoch change
    if (metadata.stream_epoch !== this.currentEpoch) {
      this.currentEpoch = metadata.stream_epoch;
      this.metadataQueue = [];
      this.eventQueue = [];
      this.baseline = null;
    }
    
    // Establish baseline on first frame of epoch
    if (!this.baseline) {
      this.baseline = {
        streamEpoch: metadata.stream_epoch,
        framePts: metadata.frame_pts,
        timeBase: metadata.time_base_num / metadata.time_base_den,
        captureWallClock: metadata.capture_timestamp,
        videoCurrentTime: this.video.currentTime,
        receivedWallClock: Date.now() / 1000
      };
    }
    
    // Calculate target video time
    const ptsSeconds = (metadata.frame_pts - this.baseline.framePts) * this.baseline.timeBase;
    const latency = metadata.processing_timestamp - metadata.capture_timestamp;
    const targetVideoTime = this.baseline.videoCurrentTime + ptsSeconds - latency;
    
    // Queue for rendering
    this.metadataQueue.push({
      targetVideoTime,
      data: metadata,
      receivedAt: Date.now() / 1000
    });
    
    // Queue events
    metadata.events?.forEach(event => {
      const eventVideoTime = event.capture_timestamp - this.baseline.captureWallClock + this.baseline.videoCurrentTime;
      this.eventQueue.push({
        targetVideoTime: eventVideoTime,
        event,
        duration: 3.0
      });
    });
  }
  
  render(currentTime) {
    // Find relevant metadata
    const relevant = this.metadataQueue.filter(m => 
      Math.abs(m.targetVideoTime - currentTime) < 0.1
    );
    
    // Render tracks, boxes, labels
    relevant.forEach(m => renderAIOverlay(this.ctx, this.videoRect, m.data));
    
    // Render events
    this.eventQueue = this.eventQueue.filter(e => 
      currentTime <= e.targetVideoTime + e.duration
    );
    this.eventQueue.forEach(e => {
      if (currentTime >= e.targetVideoTime) {
        renderCrossingIndicator(this.ctx, this.videoRect, e.event);
      }
    });
    
    // Cleanup old entries
    this.metadataQueue = this.metadataQueue.filter(m => m.targetVideoTime > currentTime - 1.0);
  }
}
```

### 5. Line Drawing Tool (Existing - Needs Video Integration)
```javascript
// Current implementation draws on canvas over static image
// Required: Draw on canvas over live video
// Coordinate transform must account for video aspect ratio

function handleCanvasMouseDown(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = 3840 / rect.width;
  const scaleY = 2160 / rect.height;
  const videoX = (e.clientX - rect.left) * scaleX;
  const videoY = (e.clientY - rect.top) * scaleY;
  // Start line at video coordinates
}
```

## Camera Switching
```javascript
// Current: Buttons show/hide static images
// Required: Switch hls.js source and canvas context

let currentHls = null;
let currentVideo = null;
let currentCanvas = null;

function switchCamera(camId) {
  // Stop current hls
  if (currentHls) {
    currentHls.destroy();
  }
  
  // Show/hide video elements
  document.getElementById('wrap1').style.display = camId === 'cam1' ? 'block' : 'none';
  document.getElementById('wrap2').style.display = camId === 'cam2' ? 'block' : 'none';
  
  // Initialize new hls if needed
  if (camId === 'cam1') {
    currentVideo = document.getElementById('video1');
    currentCanvas = document.getElementById('overlay1');
    currentHls = initHlsPlayer(currentVideo, 'http://localhost:8888/live/cam1/index.m3u8');
  } else {
    currentVideo = document.getElementById('video2');
    currentCanvas = document.getElementById('overlay2');
    currentHls = initHlsPlayer(currentVideo, 'http://localhost:8888/live/cam2/index.m3u8');
  }
}
```

## WebSocket Integration for AI Metadata

### Current Health WebSocket
```javascript
// Already implemented in UI/index.html
const healthWS = new HealthWebSocket();
healthWS.on('health_update', (data) => { ... });
healthWS.on('health_event', (event) => { ... });
```

### Required AI Metadata Channel
```javascript
// Option A: Extend existing health WebSocket
healthWS.on('ai_metadata', (metadata) => {
  metadataSynchronizer.handleMetadata(metadata);
});

// Option B: Separate WebSocket for AI metadata
const aiWS = new WebSocket('ws://localhost:8000/api/v1/ai/metadata');
aiWS.onmessage = (event) => {
  const metadata = JSON.parse(event.data);
  metadataSynchronizer.handleMetadata(metadata);
};
```

## Render Loop Integration

```javascript
let animationFrameId = null;
let lastRenderTime = 0;

function renderLoop() {
  const currentTime = performance.now();
  const videoTime = currentVideo ? currentVideo.currentTime : 0;
  
  // Render AI overlay
  if (currentVideo && currentCanvas) {
    metadataSynchronizer.render(videoTime);
  }
  
  // Update FPS display
  const fps = 1000 / (currentTime - lastRenderTime);
  document.getElementById('fpsLive').textContent = fps.toFixed(1);
  lastRenderTime = currentTime;
  
  animationFrameId = requestAnimationFrame(renderLoop);
}

// Start when video playing
currentVideo.addEventListener('play', () => {
  if (!animationFrameId) {
    renderLoop();
  }
});

currentVideo.addEventListener('pause', () => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId);
    animationFrameId = null;
  }
});
```

## Diagnostic Overlay (Existing in UI)
```javascript
// Current UI shows:
// - FPS, AI latency, GPU memory
// - Line config JSON
// - Attendance counters

// Required: Add AI-specific diagnostics
// - Stream epoch
// - Frame PTS / time base
// - Capture / processing timestamps
// - Queue depth
// - Sync offset (metadata target vs video.currentTime)
```

## Camera Configuration in UI

### Current (Static)
```javascript
// Hardcoded in UI/index.html
'rtsp://192.168.1.21:8554/cam1'
'rtsp://192.168.1.22:8554/cam2'
```

### Required (Dynamic from Legacy Backend)
```javascript
async function loadCameraConfig() {
  const response = await fetch('/api/v1/cameras');
  const { cameras } = await response.json();
  
  cameras.forEach(cam => {
    // Get stream URLs from camera config
    const hlsUrl = `http://localhost:8888/live/${cam.path}/index.m3u8`;
    // Initialize player
  });
}
```

## Verification Checklist

| Feature | Current | Required | Effort |
|---------|---------|----------|--------|
| Video Playback | ❌ Static images | ✅ hls.js + `<video>` | Medium |
| Canvas Overlay | ✅ Line drawing only | ✅ Full AI overlay | Medium |
| Coordinate Transform | ✅ Static image | ✅ Video coordinates | Low |
| Camera Switching | ✅ Show/hide images | ✅ Switch hls.js source | Low |
| Line Drawing Tool | ✅ Canvas | ✅ Canvas on video | Low |
| Metadata Sync | ❌ None | ✅ Timestamp alignment | High |
| WebSocket AI Channel | ❌ None | ✅ New handler | Medium |
| Render Loop | ❌ None | ✅ requestAnimationFrame | Medium |
| Diagnostic Overlay | Partial | Full AI diagnostics | Low |

## Effort Estimate
- **Video + hls.js integration**: 1-2 days
- **Canvas overlay + coordinate transform**: 1 day
- **Metadata synchronization**: 2-3 days
- **WebSocket integration**: 1 day
- **Render loop + cleanup**: 1 day
- **Testing & polish**: 2 days
- **Total**: ~8-10 days

## Evidence References

| Source | File | Relevant |
|--------|------|----------|
| UI Video Player | `UI/index.html` | Lines 591-603, 624-632 |
| Line Drawing Tool | `UI/index.html` | Lines 564-575, 595-601 |
| hls.js Script | `UI/index.html` | Line 8 |
| Health WebSocket | `UI/index.html` | Lines 127-274 |
| Camera Config | `UI/index.html` | Lines 582-583, 615-616 |
| PipelineEngine Camera Config | `pipeline_engine/config/pipeline.yaml` | Lines 36-185 |
| MediaMTX HLS Config | `mediamtx/mediamtx.yml` | Lines 308, 318, 324 |

## Verification Status

| Component | Source Verified | Runtime Verified |
|-----------|-----------------|------------------|
| Static UI Layout | ✅ | ❌ (no live video) |
| hls.js Integration | ✅ (loaded) | ❌ (not used) |
| Canvas Drawing | ✅ | ❌ (static only) |
| WebSocket Health | ✅ | ❌ (no backend) |
| AI Metadata Channel | ❌ | ❌ |
| Coordinate Transform | ✅ | ❌ |
| Timestamp Sync | ❌ DESIGN | ❌ |

## Blocker
**All UI video/metadata integration BLOCKED** by:
1. MediaMTX not running (no HLS streams)
2. Legacy Backend not running (no WebSocket)
3. AI Worker not running (no metadata)