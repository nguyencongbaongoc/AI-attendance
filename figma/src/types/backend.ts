// Backend API Types - Generated from actual backend contracts
// Source: app/api/health.py, app/api/websocket.py

// ============================================
// Health Monitoring Types
// ============================================

export interface CameraHealthResponse {
  camera_id: string;
  state: 'live' | 'degraded' | 'stale' | 'offline';
  timestamp: string;
  message: string;
  frames_received: number;
  frames_dropped: number;
  total_errors: number;
  uptime_seconds: number;
  current_resolution?: [number, number];
  current_fps?: number;
  current_codec?: string;
  last_frame_time?: number;
  reconnect_count: number;
  consecutive_failures: number;
}

// Camera type for UI components (simplified from CameraHealthResponse)
export interface Camera {
  id: string;
  name: string;
  location: string;
  status: 'live' | 'degraded' | 'stale' | 'recording' | 'alert' | 'offline';
  persons: number;
  fps: number;
  resolution: string;
  lastEvent: string;
}

export interface GPUStatusResponse {
  gpu_name: string;
  driver_version: string;
  cuda_runtime_version: string;
  cuda_toolkit_version: string;
  cudnn_version: string;
  pytorch_version: string;
  pytorch_cuda_version: string;
  torch_cuda_available: boolean;
  onnxruntime_version: string;
  cuda_ep_registered: boolean;
  nvdec_available: boolean;
  model_availability: Record<string, string>;
}

export interface SystemComponentHealth {
  component: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
  message: string;
  details: Record<string, unknown>;
}

export interface SystemHealthResponse {
  timestamp: string;
  overall_status: 'healthy' | 'degraded' | 'unhealthy';
  components: SystemComponentHealth[];
  cameras: Record<string, CameraHealthResponse>;
  gpu: GPUStatusResponse;
  runtime: {
    python_version: string;
    platform: string;
    architecture: string;
    venv_active: boolean;
  };
}

export interface CameraMetrics {
  state: string;
  frames_received: number;
  frames_dropped: number;
  total_errors: number;
  uptime_seconds: number;
  current_fps?: number;
  current_resolution?: [number, number];
  current_codec?: string;
}

export interface QueueMetrics {
  queue_stats: Record<string, number>;
  total_pending: number;
  total_sent: number;
  total_failed: number;
}

export interface AttendanceMetrics {
  total_students: number;
  present_today: number;
  absent_today: number;
  late_today: number;
  left_early_today: number;
}

export interface PolicyMetrics {
  morning_absence_events: number;
  long_exit_events: number;
  missing_checkout_events: number;
  short_exit_events: number;
  deduplicated_events: number;
}

export interface TelegramMetrics {
  worker_running: boolean;
  messages_sent: number;
  messages_failed: number;
  last_send_time: string | null;
}

export interface DatabaseMetrics {
  parent_registry?: {
    total_parents: number;
    parents_with_chat_id: number;
  };
  exit_sessions?: Record<string, unknown>;
  error?: string;
}

export interface MetricsResponse {
  timestamp: string;
  camera_metrics: Record<string, CameraMetrics>;
  queue_metrics: QueueMetrics;
  attendance_metrics: AttendanceMetrics;
  policy_metrics: PolicyMetrics;
  telegram_metrics: TelegramMetrics;
  database_metrics: DatabaseMetrics;
}

// ============================================
// Queue Types
// ============================================

export interface QueueMetricsResponse {
  queue_stats: Record<string, number>;
  enqueue_rate_1h: number;
  dequeue_rate_1h: number;
  avg_latency_seconds: number;
  p95_latency_seconds: number;
  oldest_pending_age_seconds: number;
  retry_count: number;
  failed_count: number;
  rate_limited_count: number;
  queue_depth: number;
  max_queue_size: number;
  queue_utilization_percent: number;
  // Aliases for backward compatibility
  total_pending: number;
  total_sent: number;
  total_failed: number;
}

export interface AlertResponse {
  severity: string;
  type: string;
  message: string;
  metric: string;
  value: number;
  threshold: number;
}

// ============================================
// WebSocket/SSE Types
// ============================================

export interface HealthSnapshot {
  type: 'health_update' | 'sync_response' | 'reconnect_response' | 'error' | 'ping' | 'pong';
  timestamp: string;
  overall_status: 'healthy' | 'degraded' | 'unhealthy';
  components: SystemComponentHealth[];
  cameras: Record<string, CameraHealthResponse>;
  gpu: GPUStatusResponse;
  queue_metrics: QueueMetrics;
  database_metrics: DatabaseMetrics;
  runtime: {
    python_version: string;
    platform: string;
    architecture: string;
    venv_active: boolean;
  };
  seq?: number;
  connection_id?: string;
  missed_events?: number;
}

export interface WSMessage {
  type: 'ping' | 'pong' | 'sync' | 'ack' | 'subscribe';
  seq?: number;
  events?: string[];
}

export interface ConnectionStats {
  total_connections: number;
  connections: Array<{
    connection_id: string;
    connected_duration_seconds: number;
    last_event_seq: number;
    missed_events: number;
    latency_ms: number | null;
    is_healthy: boolean;
    reconnect_attempts: number;
  }>;
}

// ============================================
// Attendance Types (to be implemented)
// ============================================

export interface AttendanceRecord {
  attendanceRecordId: string;
  sourceResolutionId: string;
  personId: string;
  personName: string;
  cameraId: string;
  localTrackId: string;
  globalObservationId: string;
  direction: 'in' | 'out';
  identityCertainty: 'known' | 'ambiguous' | 'unknown';
  identityCandidate: string | null;
  identityConfidence: number;
  timestamp: number;
  day: string;
  sessionId: string | null;
  sessionType: string | null;
  attendanceState: 'present' | 'late' | 'absent' | 'excused' | 'left_early';
  inState: 'on_time' | 'late' | 'outside_window' | 'not_applicable';
  outState: 'on_time' | 'early' | 'outside_window' | 'not_applicable';
  decisionReason: string;
  createdAt: string;
  persistedAt: string;
}

// AttendanceEvent for UI components (simplified from AttendanceRecord)
export interface AttendanceEvent {
  id: string;
  personId: string;
  personName: string;
  cameraId: string;
  trackId: string;
  type: 'enter' | 'exit' | 'unknown';
  confidence: number;
  timestamp: string;
  observationId: string;
}

export interface AttendanceSummary {
  present: number;
  late: number;
  left_early: number;
  absent: number;
  total: number;
}

export interface AttendanceQueryParams {
  camera_id?: string;
  track_id?: string;
  global_observation_id?: string;
  direction?: 'in' | 'out';
  identity_certainty?: 'known' | 'ambiguous' | 'unknown';
  identity_candidate?: string;
  start_time?: number;
  end_time?: number;
  limit?: number;
  offset?: number;
  order_by?: string;
  desc?: boolean;
}

export interface AttendanceQueryResult {
  records: AttendanceRecord[];
  total: number;
  limit: number;
  offset: number;
}

// ============================================
// Student/Person Types (to be implemented)
// ============================================

export interface Person {
  person_id: string;
  name: string;
  role: 'student' | 'staff' | 'visitor' | 'unknown';
  enrollment_date: string;
  last_seen: string;
  last_camera: string;
  attendance_state: 'present' | 'absent' | 'late' | 'excused';
  face_quality: number;
  track_count: number;
}

export interface PersonSearchParams {
  query?: string;
  filter?: 'all' | 'present' | 'absent' | 'late' | 'student' | 'staff';
  limit?: number;
  offset?: number;
}

export interface PersonSearchResult {
  persons: Person[];
  total: number;
}

// ============================================
// Timetable Types (to be implemented)
// ============================================

export interface TimetableEntry {
  entry_id: string;
  person_id: string;
  session_id: string;
  day: string;
  entry_time: number;
  exit_time: number;
  entry_window_seconds: number;
  exit_window_seconds: number;
  late_tolerance_seconds: number;
  session_type: 'CLASSROOM' | 'BREAK' | 'OUTSIDE_LESSON' | 'LAB' | 'OTHER';
  subject: string;
  location: string;
  expected_location: string;
  outside_allowed: boolean;
  created_at: string;
  updated_at: string;
}

export interface Timetable {
  timetable_id: string;
  version: string;
  entries: TimetableEntry[];
  created_at: string;
  updated_at: string;
}

// ============================================
// Enrollment Types (to be implemented)
// ============================================

export interface EnrollmentPerson {
  person_id: string;
  name: string;
  role: 'student' | 'staff' | 'visitor';
  face_quality: number;
  vector_count: number;
  last_seen: string;
  enrollment_date: string;
}

export interface EnrollmentStats {
  total_enrolled: number;
  students: number;
  staff: number;
  avg_quality: number;
  model: string;
  threshold: string;
  last_updated: string;
}

export interface QualityCheckResult {
  label: string;
  value: string;
  ok: boolean;
}

// ============================================
// Excel Export Types (to be implemented)
// ============================================

export interface DailyExportRequest {
  date: string;
  timezone?: string;
  export_version?: string;
  include_events_sheet?: boolean;
  include_provenance_sheet?: boolean;
  include_summary_sheet?: boolean;
}

export interface DailyExportResult {
  export_id: string;
  file_path: string;
  sheets_created: string[];
  record_count: number;
  success: boolean;
  error?: string;
  created_at: string;
}

// ============================================
// Parent/Telegram Types (to be implemented)
// ============================================

export interface Parent {
  parent_id: string;
  student_id: string;
  name: string;
  phone: string;
  telegram_chat_id: string | null;
  link_code: string | null;
  linked_at: string | null;
  created_at: string;
}

export interface NotificationQueueStats {
  pending: number;
  sent: number;
  failed: number;
}

// ============================================
// Geometry Types (Frontend)
// ============================================

export interface Point2D {
  x: number;
  y: number;
}

export interface LineOverlayItem {
  id: string;
  camera_id: string;
  type: 'entry' | 'exit';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  enabled: boolean;
  direction_semantics: 'side_a_to_b_in' | 'side_b_to_a_in';
}

export interface RegionOverlayItem {
  id: string;
  camera_id: string;
  type: string;
  points: [number, number][];
  enabled: boolean;
  direction_semantics: 'outside_to_inside_in' | 'inside_to_outside_in';
}

export interface DetectionOverlayItem {
  bbox: [number, number, number, number];  // x1, y1, x2, y2 in SOURCE coordinates
  track_id: string;
  person_id?: string;  // global_observation_id
  label: string;  // "Person TRK-441" or "John Doe"
  confidence: number;
  identity_certainty: 'known' | 'unknown' | 'ambiguous';
  identity_confidence: number;
}

export interface DetectionSnapshot {
  type: 'detection_snapshot';
  camera_id: string;
  frame_index: number;
  timestamp: string;
  frame_dimensions: {
    width: number;
    height: number;
  };
  detections: DetectionOverlayItem[];
  lines: LineOverlayItem[];
  regions: RegionOverlayItem[];
}

export interface CameraGeometryConfig {
  camera_id: string;
  frame_width: number;
  frame_height: number;
  coordinate_space: 'original_frame';
  geometry_type: 'line' | 'zone';
  line: LineOverlayItem | null;
  zone: RegionOverlayItem | null;
  crossing_policy: {
    min_crossing_distance: number;
    temporal_debounce_seconds: number;
    side_confirmation_frames: number;
    max_trajectory_gap_frames: number;
    crossing_policy: 'strict' | 'touch_allowed';
  };
  version: number;
  config_hash: string;
  created_at: string;
  updated_at: string;
  description: string;
  tags: string[];
}

// ============================================
// API Error Types
// ============================================

export interface APIError {
  detail: string;
  status_code: number;
}

export interface APIResponse<T> {
  data: T | null;
  error: APIError | null;
  loading: boolean;
}
