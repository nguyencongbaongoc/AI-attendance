# Phase 40B — Existing Frontend + Figma Reconciliation Report

**Timestamp:** 2026-08-29T03:35:00Z

---

## Frontend Comparison

| Property | Existing Frontend (`frontend/`) | Figma Frontend (`figma/`) |
|----------|--------------------------------|---------------------------|
| **Framework** | Vue 3 + TypeScript + Vite | React 19 + TypeScript + Vite |
| **Package Manager** | npm | pnpm |
| **Build System** | Vite 8.2.0 | Vite 8.0.5 |
| **Entry Point** | `src/main.js` | `src/main.tsx` |
| **Router** | vue-router 4.6.4 | None (manual screen switching via state) |
| **State Management** | Pinia 4.0.3 | React `useState`/`useEffect` only |
| **Styling** | CSS custom properties + CSS variables | Tailwind CSS 4.0 + custom CSS variables |
| **Design System** | Glassmorphism with ambient lighting | Liquid-glass, morph transitions, dark mode |

---

## Functionality Comparison

### Dashboard
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | `LiveDashboard.vue` with CameraCard, AttendanceSummary, LiveEventTimeline, PersonDetailPanel, SystemHealthPanel | `CommandCenter` with CameraCard, EventRow, stats pills, attendance progress bar, alert panel, system health panel |
| **Missing in Figma** | Camera stream display, real-time annotations on camera feed | — |
| **Missing in Existing** | — | Liquid-glass design, morph transitions, attendance coverage progress bar, alert panel with actions |

### Cameras
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | CameraCard component with live feed placeholder, status, annotations, tracks | CameraCard in CommandCenter grid with simulated feed, person silhouettes, detection boxes, status dots |
| **Missing in Figma** | Actual video stream integration, WebRTC/HLS player | — |
| **Missing in Existing** | — | Simulated feed visualization, person count badges, corner crosshairs |

### Attendance
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | AttendanceSummary component, LiveEventTimeline, query via AttendanceQueryBuilder, daily Excel export | EventRow in CommandCenter, PersonDetail timeline, AttendanceEvent mock data |
| **Missing in Figma** | Attendance summary cards, query builder, Excel export, daily resolver integration | — |
| **Missing in Existing** | — | EventRow component, attendance coverage visualization, confidence bars |

### Students/People
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | SearchView.vue with person search, PersonDetailPanel with appearance history, replay, provenance | PersonSearch with filters, PersonCard grid, PersonDetail with timeline, camera frequency heatmap |
| **Missing in Figma** | Replay integration, provenance panel integration, appearance history with global observation IDs | — |
| **Missing in Existing** | — | PersonCard grid layout, filter pills, camera frequency heatmap, face quality visualization |

### Timetable
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | TimetableManagement.vue with full CRUD, Excel import, validation, session types, outside allowed | **MISSING** - no timetable UI in Figma |
| **Missing in Figma** | Entire timetable management functionality | — |
| **Missing in Existing** | N/A - existing has complete timetable management | — |

### Replay
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | ReplayView.vue with video player, track selection, playback controls, speed control | AnnotatedReplay with simulated video viewport, detection boxes, annotations timeline, track details |
| **Missing in Figma** | Actual video player integration, HLS/WebRTC stream | — |
| **Missing in Existing** | — | Annotation markers on progress bar, detection box visualization, track confidence bars |

### Provenance
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | ProvenancePanel component with chain visualization, integrity report, raw attestation | ProvenanceChain with node visualization, integrity report, raw attestation JSON |
| **Missing in Figma** | Integration with actual attendance records | — |
| **Missing in Existing** | — | Liquid-glass styling, animated chain visualization |

### Enrollment
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | **MISSING** - no enrollment UI | EnrollmentDB with enrolled persons table, new enrollment wizard (4 steps), quality checks, DB stats |
| **Missing in Figma** | Integration with actual ArcFace database | — |
| **Missing in Existing** | Entire enrollment management functionality | — |

### Parent/Telegram
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | **MISSING** | **MISSING** |
| **Missing in Both** | Entire parent/telegram functionality | Entire parent/telegram functionality |

### Excel
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | DailyExcelExporter integration, export from TimetableManagement | **MISSING** - no Excel UI in Figma |
| **Missing in Figma** | Entire Excel export functionality | — |
| **Missing in Existing** | N/A - existing has Excel export | — |

### System Health
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | SystemHealthPanel with camera health, GPU status, metrics, polling + WebSocket/SSE | System health panel in CommandCenter, ProvenanceChain integrity report, GPU status in bottom bar |
| **Missing in Figma** | Detailed camera health, GPU details, queue metrics, database metrics, polling/SSE integration | — |
| **Missing in Existing** | — | Liquid-glass styling, animated status dots, compact health pills |

### Realtime
| | Existing | Figma |
|---|----------|-------|
| **Implementation** | WebSocket (`/api/v1/health/ws`) + SSE (`/api/v1/health/stream`) with reconnect, sequence numbers, heartbeat | **NONE** - no realtime implementation |
| **Missing in Figma** | Complete realtime architecture | — |
| **Missing in Existing** | N/A - existing has complete realtime | — |

---

## API Integration Differences

### Existing Frontend
- Pinia store with `fetchSystemHealth`, `fetchCameraHealth`, `fetchGPUStatus`, `fetchMetrics`, `startHealthPolling`
- WebSocket/SSE connection manager with reconnect logic

### Figma Frontend
- **No API integration** - all mock data hardcoded in `App.tsx`

### Backend APIs Available (Health Monitoring)
```
/api/v1/health/system
/api/v1/health/cameras
/api/v1/health/cameras/{camera_id}
/api/v1/health/gpu
/api/v1/health/metrics
/api/v1/health/queue/stats
/api/v1/health/queue/metrics
/api/v1/health/queue/alerts
/api/v1/health/ws (WebSocket)
/api/v1/health/stream (SSE)
/api/v1/health/snapshot
```

### Backend APIs Missing for Figma Integration
1. Attendance query API
2. Student/Person search & detail API
3. Timetable CRUD API
4. Excel export API
5. Enrollment/ArcFace DB API
6. Parent/Telegram API

---

## WebSocket/SSE Differences

| | Existing | Figma |
|---|----------|-------|
| **Implementation** | Full: ConnectionManager, sequence numbers, heartbeat, stale detection, reconnect handling, ack/sync messages | None |
| **Reusable** | Existing WebSocket/SSE implementation can be adapted for React with minimal changes | — |

---

## Migration Matrix

### Canonical Final Architecture
**React (Figma) + TypeScript + Vite + Tailwind CSS**

**Reason:** Figma is designated as canonical new UI per Phase 40 requirements.

### Components to Migrate from Existing Frontend
- API service layer (health, attendance, student, timetable, excel, enrollment)
- WebSocket/SSE client with reconnect logic
- Pinia store patterns → React Context + hooks or Zustand
- Attendance query builder logic
- Daily resolver integration
- Excel export integration
- Timetable management logic

### Components to Keep from Figma
- All UI components (design system, liquid-glass styling)
- CommandCenter dashboard layout
- PersonSearch with filters
- PersonDetail with timeline & heatmap
- AnnotatedReplay with annotations
- ProvenanceChain visualization
- EnrollmentDB wizard

### Components to Build
- API service layer (TypeScript)
- WebSocket/SSE React hooks
- React state management (Context/Zustand)
- Attendance API integration
- Student/Person API integration
- Timetable API integration
- Excel export API integration
- Enrollment API integration
- Parent/Telegram UI
- Excel UI

---

## Duplicate Routes

| Route | Existing | Figma |
|-------|----------|-------|
| Dashboard | `/` (LiveDashboard) | `command` (CommandCenter) |
| Replay | `/replay` (ReplayView) | `replay` (AnnotatedReplay) |
| Search | `/search` (SearchView) | `search` (PersonSearch) |
| Timetable | `/timetable` (TimetableManagement) | **MISSING** |
| Enrollment | **MISSING** | `enrollment` (EnrollmentDB) |
| Provenance | ProvenancePanel (modal) | `provenance` (ProvenanceChain) |

---

## Recommendation

**Migrate existing frontend's API integration, WebSocket/SSE, and business logic into Figma's React architecture. Keep Figma's design system and UI components. Build missing UI for timetable, parent/telegram, and Excel in Figma's design language.**

**DO NOT maintain two competing production frontends.** The Figma React frontend will be the canonical production UI.