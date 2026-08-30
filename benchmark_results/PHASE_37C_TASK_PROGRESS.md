# Phase 37C — Production Hardening + Monitoring + Operational Tooling + UI Integration Foundation

## Task Progress Checklist

### Pre-flight & Audit
- [x] Read Phase 37B report and verify current state
- [x] Audit existing UI components (LiveDashboard, SearchView, ReplayView)
- [x] Audit existing backend APIs and transport
- [x] Audit existing health monitoring and logging
- [x] Run current regression suite before modifications

### Timetable Management UI (Integrated into Existing Frontend)
- [x] Create TimetableManagement view/component
- [x] Add timetable CRUD API endpoints
- [x] Implement timetable validation
- [x] Add Excel import for timetable
- [x] Integrate into existing router/navigation

### Live Monitoring Integration
- [x] Connect LiveDashboard to canonical runtime state
- [x] Expose camera health, FPS, AI FPS, GPU status
- [x] Add WebSocket/SSE real-time transport
- [x] Implement reconnect and stale-event handling

### Telegram Production Hardening
- [x] Add startup validation for TELEGRAM_BOT_TOKEN
- [x] Create controlled live test mechanism (TELEGRAM_LIVE_TEST)
- [x] Secure token handling (never in logs/source)
- [x] Verify async non-blocking architecture

### Parent Registry Persistence (SQLite - Production Ready)
- [x] Evaluate current SQLite schema
- [x] Implement production-grade parent registry (SQLite with WAL mode)
- [x] Ensure restart-safe, durable, transactional, auditable

### Exit Session Persistence
- [x] Design persistent exit session storage
- [x] Implement exit session recovery on restart
- [x] Prove restart doesn't lose active >30-min exit sessions

### Notification Queue Observability
- [x] Expose queue metrics (depth, rates, latency, P95, oldest pending)
- [x] Add alerts for queue growth, failures, worker stopped
- [x] Ensure alerts don't block AI pipeline

### System Observability
- [x] Implement structured logging for CAMERA, AI, ATTENDANCE, POLICY, TELEGRAM
- [x] Add metrics collection
- [x] Ensure no secrets in logs

### Health Dashboard
- [x] Extend LiveDashboard with system health panel
- [x] Show CAM1/CAM2 status, GPU, CUDA EP, NVDEC
- [x] Show attendance/policy/telegram/database health

### Operational CLI/Tools
- [x] health command
- [x] status command
- [x] telegram-test command
- [x] timetable-validate command
- [x] parent-validate command
- [x] notification-status command
- [x] notification-retry command
- [x] database-check command

### Configuration Validation
- [x] Startup validation for all critical components
- [x] Clear diagnostics for missing/invalid config
- [x] No silent fallbacks for production-critical components

### Load Testing
- [ ] Test with 1,000 students, 100+ parents
- [ ] Test notification bursts, duplicate events
- [ ] Verify bounded memory, bounded queue, no duplicates

### Failure/Recovery Tests
- [ ] Telegram unavailable → attendance continues
- [ ] Database temporarily unavailable → correct failure state → recovery
- [ ] Notification worker restart → pending records recover
- [ ] Application restart during active exit → exit session recovered
- [ ] UI disconnect → AI continues
- [ ] WebSocket/SSE reconnect → no event corruption
- [ ] Camera temporarily unavailable → health state changes → no false attendance

### Security Audit
- [x] No secrets committed
- [x] Token environment-based
- [x] Chat IDs not unnecessarily exposed
- [x] Authorization for admin operations
- [x] Link codes protected
- [x] Input validation, SQL parameterization
- [x] Safe Excel/timetable import

### Regression Testing
- [x] Run Phase 23, 24, 26, 30, 30A, 36T, 36R5, 37A, 37B tests
- [ ] Run new Phase 37C tests
- [ ] Classify failures accurately

### Reports
- [x] Create PHASE_37C_PRODUCTION_HARDENING.json
- [x] Create PHASE_37C_PRODUCTION_HARDENING.md
- [x] Document remaining limitations
- [x] Document Phase 37D handoff requirements