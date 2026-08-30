# Phase 40A — Figma Forensic Audit Report

**Timestamp:** 2026-08-29T03:30:00Z  
**Directory:** `figma/`

---

## Framework & Build System

| Property | Value |
|----------|-------|
| **Framework** | React 19 + TypeScript + Vite |
| **Package Manager** | pnpm |
| **Build System** | Vite 8.0.5 |
| **Entry Point** | `src/main.tsx` → `src/App.tsx` |
| **Styling** | Tailwind CSS 4.0 + custom CSS variables |
| **Design System** | Liquid-glass visual language, morph transitions, dark mode |

---

## Application Structure

### Routes (6 screens)
1. **command** — Live Command Center (Dashboard)
2. **search** — Person Search
3. **person** — Person Detail
4. **replay** — Annotated Replay
5. **provenance** — Provenance Chain
6. **enrollment** — Enrollment / ArcFace DB

### Components (18)
- `Badge`, `StatusDot`, `ConfidenceBar`, `Skeleton`
- `MonoLabel`, `MonoValue`, `SectionTitle`
- `GlassButton`, `GlassInput`
- `CameraCard`, `EventRow`
- `CommandCenter`, `PersonSearch`, `PersonCard`, `PersonDetail`
- `AnnotatedReplay`, `ProvenanceChain`, `EnrollmentDB`

### State Management
- **React `useState`/`useEffect` only** — no external store (Redux, Pinia, Zustand, etc.)
- All state local to `App.tsx` (1554 lines)

### API Clients
- **None** — all data is hardcoded mock data in `App.tsx`

### WebSocket/SSE Clients
- **None** — no realtime integration implemented

---

## Mock Data (Hardcoded in App.tsx)

| Dataset | Count | Details |
|---------|-------|---------|
| `CAMERAS` | 6 | CAM-001 to CAM-006 (Main Entrance, Corridor East, Canteen Entry, Library Gate, Lab 3 Door, Admin Block) |
| `EVENTS` | 7 | Attendance events with personId, cameraId, trackId, type, confidence, timestamp, observationId |
| `PERSONS` | 8 | Students (STU-10042, STU-10087, STU-10033, STU-10019, STU-10057, STU-10099, STU-10104) + Staff (STF-00012) |

---

## Environment Configuration

| Config | Value |
|--------|-------|
| `FIGMA_PUBLIC_URL` | Used for `base` in Vite config |
| `PORT` | Defaults to **8443** (dev & preview) |
| `vite.config.ts` | Includes Figma-specific plugins: `figmaSiteConfiguration`, `figmaErrorOverlayReplay`, `figmaReactRefreshBoundaryFallback`, `figmaMakeKitPlugin` |

---

## Commands

| Command | Description |
|---------|-------------|
| `pnpm dev` | Development server on 0.0.0.0:8443 |
| `pnpm build` | Production build |
| `pnpm preview` | Preview production build on 0.0.0.0:8443 |
| `pnpm format` | Format with oxfmt |

---

## Key Findings

### Critical Gaps
1. **Complete mock data** — No real API integration whatsoever
2. **No WebSocket/SSE client** — No realtime capability
3. **No authentication/authorization** — No auth implementation
4. **No environment-based API configuration** — No API base URL, no service layer
5. **Single-file architecture** — All 1554 lines in `App.tsx`, no component separation
6. **No TypeScript interfaces for backend contracts** — Types are local mock types only
7. **Port conflict** — Figma dev server uses 8443, backend uses 8000
8. **Figma-specific Vite plugins** — `figma-make-kit`, error overlay replay, etc. (dev-only)

### Architecture Issues
- All components defined in single `App.tsx` file
- No separation of concerns (UI, data fetching, state management)
- No API service layer or data fetching hooks
- No error boundaries, loading states, or retry logic
- No pagination, infinite scroll, or virtualization for lists

---

## FIGMA UI COMPONENT → BACKEND API Mapping

| Figma UI Component | Existing Backend API / Service | Data Contract | Real-time Source |
|--------------------|--------------------------------|---------------|------------------|
| **Dashboard** (`CommandCenter`) | `/api/v1/health/system`, `/api/v1/health/cameras`, `/api/v1/health/metrics` | `SystemHealthResponse`, `CameraHealthResponse`, `MetricsResponse` | WebSocket `/api/v1/health/ws` or SSE `/api/v1/health/stream` |
| **Cameras** (`CameraCard`) | `/api/v1/health/cameras`, `/api/v1/health/cameras/{camera_id}` | `CameraHealthResponse` | WebSocket health updates |
| **Attendance** (`EventRow`, `PersonCard`, `PersonDetail`) | **MISSING** — no attendance API endpoints exist | **MISSING** | **MISSING** |
| **Students** (`PersonSearch`, `PersonCard`, `PersonDetail`, `EnrollmentDB`) | **MISSING** — no student/enrollment API endpoints exist | **MISSING** | **MISSING** |
| **Timetable** | **MISSING** — no timetable UI in Figma | **MISSING** — no timetable API endpoints exist | **MISSING** |
| **Parent/Telegram** | `/api/v1/health/queue/stats`, `/api/v1/health/queue/metrics`, `/api/v1/health/queue/alerts` | `QueueMetricsResponse`, `AlertResponse` | WebSocket health updates |
| **Excel** | **MISSING** — no Excel UI in Figma | **MISSING** — no Excel export API endpoints exist | **MISSING** |
| **System Health** (panel in `CommandCenter`, `ProvenanceChain`) | `/api/v1/health/system`, `/api/v1/health/gpu`, `/api/v1/health/metrics` | `SystemHealthResponse`, `GPUStatusResponse`, `MetricsResponse` | WebSocket `/api/v1/health/ws` or SSE `/api/v1/health/stream` |

---

## Missing Backend APIs Required for Figma Integration

1. **Attendance API** — Query attendance records, events, summaries
2. **Student/Person API** — Search, list, detail, enrollment management
3. **Timetable API** — CRUD for timetable entries, session management
4. **Excel Export API** — Trigger daily attendance exports, download reports
5. **Enrollment/ArcFace DB API** — Manage enrolled persons, face vectors, quality checks

---

## Recommendation

**STOP condition not triggered** — Framework is safely determined (React 19 + TypeScript + Vite). Proceed to Phase 40B for reconciliation with existing frontend.