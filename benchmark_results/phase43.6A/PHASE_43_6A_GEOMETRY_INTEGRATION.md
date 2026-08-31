# Phase 43.6A — Geometry Integration Report

**Status**: ✅ COMPLETED  
**Timestamp**: 2026-08-31T16:35:00+07:00  
**Phase**: 43.6A

---

## Executive Summary

Backend geometry contracts audited and REST API implemented. All existing models reused without modification. New API provides CRUD operations for CameraGeometryConfig with versioned persistence.

---

## Backend Geometry Audit

### Existing Models (Verified in `app/geometry/contract.py`)

| Model | Status | Key Fields |
|-------|--------|------------|
| `Point2D` | ✅ | `x`, `y`, arithmetic ops, cross/dot product |
| `LineGeometry` | ✅ | `p1`, `p2`, `direction_semantics`, `side_of_point()`, `distance_to_line()` |
| `ZoneGeometry` | ✅ | `vertices[]`, `direction_semantics`, `point_in_polygon()`, `distance_to_boundary()` |
| `CrossingPolicyConfig` | ✅ | `min_crossing_distance`, `temporal_debounce_seconds`, `side_confirmation_frames`, `max_trajectory_gap_frames` |
| `CameraGeometryConfig` | ✅ | `camera_id`, `frame_width/height`, `geometry_type`, `line/zone`, `crossing_policy`, `version`, `config_hash` |
| `GeometryConfigSnapshot` | ✅ | Immutable snapshot for provenance |

### Factory Functions (Verified)

| Function | Purpose |
|----------|---------|
| `create_line_geometry()` | Creates LINE CameraGeometryConfig |
| `create_zone_geometry()` | Creates ZONE CameraGeometryConfig |
| `load_geometry_config()` | Loads from JSON file |
| `save_geometry_config()` | Saves to JSON file |

### Direction Semantics (Preserved)

| Enum | Value | Meaning |
|------|-------|---------|
| `SIDE_A_TO_B_IN` | `side_a_to_b_in` | Left→Right of p1→p2 = IN |
| `SIDE_B_TO_A_IN` | `side_b_to_a_in` | Right→Left of p1→p2 = IN |
| `OUTSIDE_TO_INSIDE_IN` | `outside_to_inside_in` | Entering zone = IN |
| `INSIDE_TO_OUTSIDE_IN` | `inside_to_outside_in` | Exiting zone = IN |

### Coordinate Space

**Canonical**: `ORIGINAL_FRAME` (3840 × 2160) — enforced by `CameraGeometryConfig.__post_init__()`

---

## Geometry REST API Implementation

### New File: `app/api/geometry.py`

**Endpoints** (8 total):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/geometry/{camera_id}` | Get current config (memory → file → default) |
| POST | `/api/v1/geometry/{camera_id}` | Create/update full config |
| PUT | `/api/v1/geometry/{camera_id}/line` | Update line only |
| PUT | `/api/v1/geometry/{camera_id}/zone` | Update zone only |
| PUT | `/api/v1/geometry/{camera_id}/policy` | Update crossing policy |
| DELETE | `/api/v1/geometry/{camera_id}` | Remove from memory |
| GET | `/api/v1/geometry/{camera_id}/versions` | List version history |
| GET | `/api/v1/geometry/{camera_id}/versions/{version}` | Get specific version |

### Request/Response Models (Pydantic)

```python
class LineGeometryRequest(BaseModel):
    p1: Dict[str, float]
    p2: Dict[str, float]
    direction_semantics: str = "side_a_to_b_in"

class ZoneGeometryRequest(BaseModel):
    vertices: List[Dict[str, float]]
    direction_semantics: str = "outside_to_inside_in"

class CrossingPolicyRequest(BaseModel):
    min_crossing_distance: float = 5.0
    temporal_debounce_seconds: float = 1.0
    side_confirmation_frames: int = 2
    max_trajectory_gap_frames: int = 5
    crossing_policy: str = "strict"

class GeometryConfigRequest(BaseModel):
    frame_width: int = 3840
    frame_height: int = 2160
    geometry_type: str = "line"
    line: Optional[LineGeometryRequest]
    zone: Optional[ZoneGeometryRequest]
    crossing_policy: Optional[CrossingPolicyRequest]
    description: str = ""
    tags: List[str] = []
```

### Persistence Strategy

- **In-memory**: `_geometry_store: Dict[str, CameraGeometryConfig]` for fast access
- **File-based**: `GeometryVersionManager` for versioned JSON storage
- **Auto-load**: GET checks memory first, then loads latest from version manager
- **Auto-save**: All mutations persist via `vm.save_version(config)`

### Validation Rules

1. Geometry type must match provided geometry (LINE requires `line`, ZONE requires `zone`)
2. Coordinates validated within frame bounds (0 ≤ x ≤ width, 0 ≤ y ≤ height)
3. Line must have non-zero length (p1 ≠ p2)
4. Zone must have ≥3 vertices, no duplicate consecutive vertices
4. Crossing policy values validated (non-negative, ≥1 for frame counts)

---

## Frontend Integration

### API Service (`figma/src/services/api.ts`)

```typescript
// Geometry CRUD
fetchGeometry(cameraId: string): Promise<CameraGeometryConfig>
createOrUpdateGeometry(cameraId: string, request: CreateGeometryRequest): Promise<CameraGeometryConfig>
updateLineGeometry(cameraId: string, request: UpdateLineRequest): Promise<CameraGeometryConfig>
updateZoneGeometry(cameraId: string, request: UpdateZoneRequest): Promise<CameraGeometryConfig>
updateCrossingPolicy(cameraId: string, request: UpdatePolicyRequest): Promise<CameraGeometryConfig>
deleteGeometry(cameraId: string): Promise<{ status: string; camera_id: string }>
```

### Type Definitions (`figma/src/types/backend.ts`)

```typescript
interface CameraGeometryConfig {
  camera_id: string;
  frame_width: number;
  frame_height: number;
  coordinate_space: 'original_frame';
  geometry_type: 'line' | 'zone';
  line: LineOverlayItem | null;
  zone: RegionOverlayItem | null;
  crossing_policy: { ... };
  version: number;
  config_hash: string;
  created_at: string;
  updated_at: string;
  description: string;
  tags: string[];
}
```

---

## Integration Verification

### Backend Startup
```
[INFO] Starting Backend API...
[INFO]   Port: 19897
[INFO] Backend started (PID: 168908)
[OK]   Backend health check passed: http://localhost:19897/api/v1/health/system
```

### API Registration
```python
# app/main.py
from app.api.geometry import router as geometry_router
# ...
for router in [..., geometry_router]:
    for route in router.routes:
        app.router.routes.append(route)
```

### Endpoint Accessibility
- `GET /api/v1/geometry/CAM1` → Returns default config (no saved geometry)
- `POST /api/v1/geometry/CAM1` → Creates new config, persists to file
- `PUT /api/v1/geometry/CAM1/line` → Updates line, increments version
- `GET /api/v1/geometry/CAM1/versions` → Lists saved versions

---

## Acceptance Matrix

| Check | Status | Evidence |
|-------|--------|----------|
| Existing backend geometry audited | ✅ | `app/geometry/contract.py` fully inspected |
| No duplicate geometry models | ✅ | API uses existing `CameraGeometryConfig` etc. |
| Geometry API created (not duplicated) | ✅ | New endpoints only where missing |
| ORIGINAL_FRAME coordinates enforced | ✅ | `coordinate_space` validation in model |
| Line semantics preserved | ✅ | Uses `DirectionSemantics` enum |
| Zone semantics preserved | ✅ | Uses `DirectionSemantics` enum |
| Crossing policy configurable | ✅ | PUT /policy endpoint |
| Versioning functional | ✅ | `GeometryVersionManager` integration |
| File persistence works | ✅ | JSON files created in data dir |
| Frontend types match backend | ✅ | Shared snake_case→camelCase transform |
| CORS enabled for frontend | ✅ | `allow_origins=["*"]` in main.py |

---

## Files Created/Modified

| File | Type | Description |
|------|------|-------------|
| `app/api/geometry.py` | New | Geometry REST API (8 endpoints) |
| `app/main.py` | Modified | Registered geometry router |
| `figma/src/services/api.ts` | Modified | Added geometry API client |
| `figma/src/types/backend.ts` | Modified | Added CameraGeometryConfig type |

---

## Limitations

1. **In-memory store** — Geometry lost on backend restart (but loads from version manager on first GET)
2. **No authentication** — API open (consistent with other endpoints)
3. **Single geometry per camera** — Either LINE or ZONE, not both (by design per `CameraGeometryConfig`)
4. **No real-time geometry updates** — Frontend must poll or refresh (WebSocket not extended for geometry changes)

---

## Conclusion

**Geometry integration complete and verified.** Backend contracts fully reused, REST API provides required CRUD operations with versioned persistence, frontend types and API client implemented. Ready for Phase 44 geometry editing UI.