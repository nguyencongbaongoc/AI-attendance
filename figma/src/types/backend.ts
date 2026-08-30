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
  attendance_record_id: string;
  source_resolution_id: string;
  person_id: string;
  person_name: string;
  camera_id: string;
  local_track_id: string;
  global_observation_id: string;
  direction: 'in' | 'out';
  identity_certainty: 'known' | 'ambiguous' | 'unknown';
  identity_candidate: string | null;
  identity_confidence: number;
  timestamp: number;
  day: string;
  session_id: string | null;
  session_type: string | null;
  attendance_state: 'present' | 'late' | 'absent' | 'excused' | 'left_early';
  in_state: 'on_time' | 'late' | 'outside_window' | 'not_applicable';
  out_state: 'on_time' | 'early' | 'outside_window' | 'not_applicable';
  decision_reason: string;
  created_at: string;
  persisted_at: string;
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