# Legacy Backend API Inventory

## Base URL
**Legacy Backend**: `http://localhost:{dynamic_port}` (port discovered at startup)
**UI Config**: `window.__API_BASE_URL__ || 'http://localhost:8000'`
**WebSocket**: `ws://localhost:{port}/api/v1/health/ws`

## API Prefix
All endpoints under `/api/v1/`

---

## Health Endpoints (`/api/v1/health`)

| Endpoint | Method | Response Model | Description |
|----------|--------|----------------|-------------|
| `/live` | GET | `{"status": "alive"}` | Liveness probe |
| `/ready` | GET | `{status, checks}` | Readiness probe (DBs, dirs) |
| `/system` | GET | `SystemHealthResponse` | Comprehensive system health |
| `/cameras` | GET | `Dict[str, CameraHealthResponse]` | All camera health |
| `/cameras/{camera_id}` | GET | `CameraHealthResponse` | Specific camera health |
| `/gpu` | GET | `GPUStatusResponse` | GPU/CUDA/NVDEC status |
| `/metrics` | GET | `MetricsResponse` | System metrics |
| `/queue/metrics` | GET | `QueueMetricsResponse` | Detailed queue metrics |
| `/queue/alerts` | GET | `List[AlertResponse]` | Current queue alerts |
| `/queue/stats` | GET | `Dict[str, int]` | Basic queue statistics |

### Camera Health Reporting (Ingestion → Backend)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/cameras/{camera_id}/frame` | POST | Report frame received |
| `/cameras/{camera_id}/error` | POST | Report camera error |
| `/cameras/{camera_id}/reconnect` | POST | Report reconnect attempt |
| `/cameras/{camera_id}/reconnect/success` | POST | Report successful reconnect |
| `/cameras/{camera_id}/reconnect/failed` | POST | Report failed reconnect |

---

## Attendance Endpoints (`/api/v1/attendance`)

| Endpoint | Method | Response Model | Description |
|----------|--------|----------------|-------------|
| `/summary` | GET | `AttendanceSummaryResponse` | Today's attendance summary |
| `/records` | GET | `AttendanceQueryResultResponse` | Query attendance records |
| `/records/{record_id}` | GET | `AttendanceRecordResponse` | Specific record by ID |
| `/person/{person_id}` | GET | `AttendanceQueryResultResponse` | Records for a person |
| `/timeline` | GET | `{timeline, count}` | Attendance timeline |
| `/daily-counts` | GET | `{daily_counts}` | Daily counts for N days |
| `/track-history` | GET | `{history}` | Track state history |
| `/stats` | GET | `Dict` | Repository statistics |

### Query Parameters (for `/records`, `/person/{person_id}`)
- `camera_id`, `track_id`, `global_observation_id`
- `direction`, `identity_certainty`, `identity_candidate`
- `start_time`, `end_time` (unix timestamp)
- `limit` (1-1000), `offset`, `order_by`, `desc`

---

## Geometry Endpoints (`/api/v1/geometry`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/lines` | GET | List all line geometries |
| `/lines/{camera_id}` | GET | Get line for camera |
| `/lines/{camera_id}` | PUT | Update line geometry |

### Line Geometry Schema
```json
{
  "camera_id": "cam1",
  "line_start": [x1, y1],
  "line_end": [x2, y2],
  "direction_semantics": "side_a_to_b_in"
}
```

---

## Enrollment Endpoints (`/api/v1/enrollment`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/detect` | POST | Face detection in uploaded image |
| `/embedding` | POST | Generate ArcFace embedding |
| `/save` | POST | Save enrollment to NPY |
| `/list` | GET | List enrolled persons |

---

## Replay Endpoints (`/api/v1/replay`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/segments` | GET | List video segments for camera/date |
| `/stream` | GET | HLS manifest for replay |

---

## Person Endpoints (`/api/v1/persons`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | List all persons |
| `/{person_id}` | GET | Get person details |
| `/{person_id}` | PUT | Update person |
| `/{person_id}` | DELETE | Delete person |

---

## Timetable Endpoints (`/api/v1/timetable`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | List timetables |
| `/{timetable_id}` | GET | Get timetable |
| `/` | POST | Create timetable |
| `/{timetable_id}` | PUT | Update timetable |
| `/{timetable_id}` | DELETE | Delete timetable |

---

## Excel Export Endpoints (`/api/v1/excel`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/export` | GET | Export attendance to Excel |
| `/export/daily` | GET | Export daily report |

---

## Parent/Telegram Endpoints (`/api/v1/parent-telegram`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/parents` | GET | List parents |
| `/notifications/send` | POST | Send notification |
| `/queue` | GET | Notification queue status |

---

## Provenance Endpoints (`/api/v1/provenance`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chain/{attendance_record_id}` | GET | Full provenance chain |

---

## WebSocket Endpoints (`/api/v1/health`)

| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `/ws` | WebSocket | Real-time health with reconnect |
| `/stream` | SSE | Server-Sent Events fallback |
| `/snapshot` | GET | Single health snapshot (polling) |
| `/connections` | GET | Connection statistics |
| `/ws/reconnect` | POST | Explicit reconnect handling |

### WebSocket Message Types

#### Client → Server
```json
{"type": "ping"}                    // Heartbeat response
{"type": "pong"}                    // Response to server ping
{"type": "sync"}                    // Full state sync request
{"type": "ack", "seq": 123}         // Acknowledge event receipt
{"type": "subscribe", "events": [...]}  // Subscribe to event types
```

#### Server → Client
```json
{"type": "health_update", "seq": 1, "timestamp": "...", "overall_status": "...", "components": [...], "cameras": {...}, "gpu": {...}, ...}
{"type": "health_event", "event": {...}, "seq": 1, "timestamp": "..."}
{"type": "ping", "seq": 1, "timestamp": "..."}
{"type": "pong", "seq": 1, "timestamp": "..."}
{"type": "sync_response", "seq": 1, "timestamp": "..."}
{"type": "reconnect_response", "seq": 1, "missed_events": 5, ...}
{"type": "subscribed", "events": [...], "timestamp": "..."}
{"type": "error", "message": "..."}
```

---

## Recording Access
**Static Mount**: `/recordings/*` → `settings.paths.recordings_dir`
**Format**: `recordings/<camera_id>/<YYYY-MM-DD_HH-MM-SS>.mp4` (fMP4 from MediaMTX)

---

## Root Endpoint
**GET** `/` → Service info with links to docs, health

---

## Missing Endpoints (for Architecture A)

### Required but NOT FOUND in Legacy Backend
1. **AI Worker Event Ingestion** - `POST /api/v1/ai/events` (receive attendance events from AI worker)
2. **AI Worker Health** - `GET /api/v1/ai/health` (AI worker status)
3. **Geometry Push from AI** - `PUT /api/v1/geometry/lines/{camera_id}` (already exists but for UI)
4. **NPY Reload Notification** - `POST /api/v1/enrollment/reload` (notify backend of NPY changes)

### Currently Stubbed in PipelineEngine Backend
PipelineEngine's `backend/app.py` has these endpoints returning empty:
- `/api/v1/attendance/events` → `[]`
- `/api/v1/attendance/daily/{date}` → `{"date": date, "records": []}`
- `/api/v1/attendance/export` → Not implemented

---

## API Versioning
- All endpoints under `/api/v1/`
- No versioning in path for WebSocket (`/api/v1/health/ws`)

---

## Authentication
**Current**: NONE
- CORS: `allow_origins=["*"]`
- No JWT, API keys, or sessions
- Assumes internal trusted network

---

## Evidence Summary

| Router | File | Lines | Verification |
|--------|------|-------|--------------|
| health | `app/api/health.py` | 560 | ✅ SOURCE-VERIFIED |
| attendance | `app/api/attendance.py` | 369 | ✅ SOURCE-VERIFIED |
| websocket | `app/api/websocket.py` | 602 | ✅ SOURCE-VERIFIED |
| geometry | `app/api/geometry.py` | - | ⚠️ NOT READ |
| enrollment | `app/api/enrollment.py` | - | ⚠️ NOT READ |
| replay | `app/api/replay.py` | - | ⚠️ NOT READ |
| persons | `app/api/persons.py` | - | ⚠️ NOT READ |
| timetable | `app/api/timetable.py` | - | ⚠️ NOT READ |
| excel | `app/api/excel.py` | - | ⚠️ NOT READ |
| parent_telegram | `app/api/parent_telegram.py` | - | ⚠️ NOT READ |
| provenance | `app/api/provenance.py` | - | ⚠️ NOT READ |

**Runtime Status**: NOT RUNNING - No FastAPI process on any port