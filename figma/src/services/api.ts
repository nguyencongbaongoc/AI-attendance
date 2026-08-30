// API Service Layer - Connects Figma frontend to existing backend
// Uses actual backend contracts from app/api/health.py, app/api/websocket.py

import type {
  SystemHealthResponse,
  CameraHealthResponse,
  GPUStatusResponse,
  MetricsResponse,
  QueueMetricsResponse,
  AlertResponse,
  HealthSnapshot,
  ConnectionStats,
  AttendanceRecord,
  AttendanceSummary,
  AttendanceQueryParams,
  AttendanceQueryResult,
  Person,
  PersonSearchParams,
  PersonSearchResult,
  TimetableEntry,
  Timetable,
  EnrollmentPerson,
  EnrollmentStats,
  QualityCheckResult,
  DailyExportRequest,
  DailyExportResult,
  Parent,
  NotificationQueueStats,
  APIError as APIErrorType,
  APIResponse,
} from '@/types/backend';

// ============================================
// Configuration
// ============================================

// Use environment variables for dynamic port configuration
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000';

// Local APIError class for internal use
class APIError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public endpoint: string
  ) {
    super(`API Error (${status}): ${detail} [${endpoint}]`);
    this.name = 'APIError';
  }
}

async function handleResponse<T>(response: Response, endpoint: string): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errorData = await response.json();
      detail = errorData.detail || detail;
    } catch {
      // Ignore JSON parse errors
    }
    throw new APIError(response.status, detail, endpoint);
  }
  return response.json();
}

// ============================================
// Health Monitoring API
// ============================================

export async function fetchSystemHealth(): Promise<SystemHealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/system`);
  return handleResponse<SystemHealthResponse>(response, '/api/v1/health/system');
}

export async function fetchCameraHealth(): Promise<Record<string, CameraHealthResponse>> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras`);
  return handleResponse<Record<string, CameraHealthResponse>>(response, '/api/v1/health/cameras');
}

export async function fetchCameraHealthById(cameraId: string): Promise<CameraHealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras/${cameraId}`);
  return handleResponse<CameraHealthResponse>(response, `/api/v1/health/cameras/${cameraId}`);
}

export async function fetchGPUStatus(): Promise<GPUStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/gpu`);
  return handleResponse<GPUStatusResponse>(response, '/api/v1/health/gpu');
}

export async function fetchMetrics(): Promise<MetricsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/metrics`);
  return handleResponse<MetricsResponse>(response, '/api/v1/health/metrics');
}

export async function fetchQueueMetrics(): Promise<QueueMetricsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/queue/metrics`);
  return handleResponse<QueueMetricsResponse>(response, '/api/v1/health/queue/metrics');
}

export async function fetchQueueAlerts(): Promise<AlertResponse[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/queue/alerts`);
  return handleResponse<AlertResponse[]>(response, '/api/v1/health/queue/alerts');
}

export async function fetchQueueStats(): Promise<Record<string, number>> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/queue/stats`);
  return handleResponse<Record<string, number>>(response, '/api/v1/health/queue/stats');
}

export async function fetchHealthSnapshot(): Promise<HealthSnapshot> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/snapshot`);
  return handleResponse<HealthSnapshot>(response, '/api/v1/health/snapshot');
}

export async function fetchConnectionStats(): Promise<ConnectionStats> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/connections`);
  return handleResponse<ConnectionStats>(response, '/api/v1/health/connections');
}

// ============================================
// Camera Frame Reporting (for streaming pipeline)
// ============================================

export interface FrameReportParams {
  frame_index: number;
  timestamp: number;
  frame_size?: number;
  resolution?: [number, number];
  fps?: number;
  codec?: string;
}

export async function reportFrameReceived(cameraId: string, params: FrameReportParams): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras/${cameraId}/frame`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  return handleResponse<{ status: string }>(response, `/api/v1/health/cameras/${cameraId}/frame`);
}

export async function reportCameraError(cameraId: string, error: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras/${cameraId}/error`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ error }),
  });
  return handleResponse<{ status: string }>(response, `/api/v1/health/cameras/${cameraId}/error`);
}

export async function reportReconnectAttempt(cameraId: string, attempt: number): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras/${cameraId}/reconnect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attempt }),
  });
  return handleResponse<{ status: string }>(response, `/api/v1/health/cameras/${cameraId}/reconnect`);
}

export async function reportReconnectSuccess(cameraId: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras/${cameraId}/reconnect/success`, {
    method: 'POST',
  });
  return handleResponse<{ status: string }>(response, `/api/v1/health/cameras/${cameraId}/reconnect/success`);
}

export async function reportReconnectFailed(cameraId: string, reason: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/health/cameras/${cameraId}/reconnect/failed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
  return handleResponse<{ status: string }>(response, `/api/v1/health/cameras/${cameraId}/reconnect/failed`);
}

// ============================================
// Attendance API (to be implemented on backend)
// ============================================

export async function fetchAttendanceSummary(): Promise<AttendanceSummary> {
  const response = await fetch(`${API_BASE_URL}/api/v1/attendance/summary`);
  return handleResponse<AttendanceSummary>(response, '/api/v1/attendance/summary');
}

export async function fetchAttendanceRecords(params: AttendanceQueryParams = {}): Promise<AttendanceQueryResult> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  });
  const response = await fetch(`${API_BASE_URL}/api/v1/attendance/records?${searchParams.toString()}`);
  return handleResponse<AttendanceQueryResult>(response, '/api/v1/attendance/records');
}

export async function fetchAttendanceRecord(recordId: string): Promise<AttendanceRecord> {
  const response = await fetch(`${API_BASE_URL}/api/v1/attendance/records/${recordId}`);
  return handleResponse<AttendanceRecord>(response, `/api/v1/attendance/records/${recordId}`);
}

export async function fetchPersonAttendance(personId: string, params: AttendanceQueryParams = {}): Promise<AttendanceQueryResult> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  });
  const response = await fetch(`${API_BASE_URL}/api/v1/attendance/person/${personId}?${searchParams.toString()}`);
  return handleResponse<AttendanceQueryResult>(response, `/api/v1/attendance/person/${personId}`);
}

// ============================================
// Student/Person API (to be implemented on backend)
// ============================================

export async function fetchPersons(params: PersonSearchParams = {}): Promise<PersonSearchResult> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  });
  const response = await fetch(`${API_BASE_URL}/api/v1/persons?${searchParams.toString()}`);
  return handleResponse<PersonSearchResult>(response, '/api/v1/persons');
}

export async function fetchPerson(personId: string): Promise<Person> {
  const response = await fetch(`${API_BASE_URL}/api/v1/persons/${personId}`);
  return handleResponse<Person>(response, `/api/v1/persons/${personId}`);
}

export async function fetchPersonAppearanceHistory(personId: string): Promise<AttendanceQueryResult> {
  const response = await fetch(`${API_BASE_URL}/api/v1/persons/${personId}/appearances`);
  return handleResponse<AttendanceQueryResult>(response, `/api/v1/persons/${personId}/appearances`);
}

// ============================================
// Timetable API (to be implemented on backend)
// ============================================

export async function fetchTimetable(): Promise<Timetable> {
  const response = await fetch(`${API_BASE_URL}/api/v1/timetable`);
  return handleResponse<Timetable>(response, '/api/v1/timetable');
}

export async function fetchTimetableEntries(personId?: string): Promise<TimetableEntry[]> {
  const searchParams = personId ? `?person_id=${personId}` : '';
  const response = await fetch(`${API_BASE_URL}/api/v1/timetable/entries${searchParams}`);
  return handleResponse<TimetableEntry[]>(response, '/api/v1/timetable/entries');
}

export async function createTimetableEntry(entry: Omit<TimetableEntry, 'entry_id' | 'created_at' | 'updated_at'>): Promise<TimetableEntry> {
  const response = await fetch(`${API_BASE_URL}/api/v1/timetable/entries`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  });
  return handleResponse<TimetableEntry>(response, '/api/v1/timetable/entries');
}

export async function updateTimetableEntry(entryId: string, entry: Partial<TimetableEntry>): Promise<TimetableEntry> {
  const response = await fetch(`${API_BASE_URL}/api/v1/timetable/entries/${entryId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  });
  return handleResponse<TimetableEntry>(response, `/api/v1/timetable/entries/${entryId}`);
}

export async function deleteTimetableEntry(entryId: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/timetable/entries/${entryId}`, {
    method: 'DELETE',
  });
  return handleResponse<{ success: boolean }>(response, `/api/v1/timetable/entries/${entryId}`);
}

export async function importTimetableFromExcel(file: File): Promise<{ success: boolean; errors: string[] }> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${API_BASE_URL}/api/v1/timetable/import`, {
    method: 'POST',
    body: formData,
  });
  return handleResponse<{ success: boolean; errors: string[] }>(response, '/api/v1/timetable/import');
}

// ============================================
// Enrollment/ArcFace DB API (to be implemented on backend)
// ============================================

export async function fetchEnrolledPersons(): Promise<EnrollmentPerson[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/enrollment/persons`);
  return handleResponse<EnrollmentPerson[]>(response, '/api/v1/enrollment/persons');
}

export async function fetchEnrollmentStats(): Promise<EnrollmentStats> {
  const response = await fetch(`${API_BASE_URL}/api/v1/enrollment/stats`);
  return handleResponse<EnrollmentStats>(response, '/api/v1/enrollment/stats');
}

export async function enrollPerson(data: {
  person_id: string;
  name: string;
  role: 'student' | 'staff' | 'visitor';
  face_embedding: number[];
  face_quality: number;
}): Promise<EnrollmentPerson> {
  const response = await fetch(`${API_BASE_URL}/api/v1/enrollment/persons`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return handleResponse<EnrollmentPerson>(response, '/api/v1/enrollment/persons');
}

export async function deleteEnrolledPerson(personId: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/enrollment/persons/${personId}`, {
    method: 'DELETE',
  });
  return handleResponse<{ success: boolean }>(response, `/api/v1/enrollment/persons/${personId}`);
}

export async function runQualityCheck(personId: string): Promise<QualityCheckResult[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/enrollment/persons/${personId}/quality-check`, {
    method: 'POST',
  });
  return handleResponse<QualityCheckResult[]>(response, `/api/v1/enrollment/persons/${personId}/quality-check`);
}

// ============================================
// Excel Export API (to be implemented on backend)
// ============================================

export async function exportDailyAttendance(request: DailyExportRequest): Promise<DailyExportResult> {
  const response = await fetch(`${API_BASE_URL}/api/v1/excel/export/daily`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  return handleResponse<DailyExportResult>(response, '/api/v1/excel/export/daily');
}

export async function downloadExcelExport(exportId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/v1/excel/export/${exportId}/download`);
  if (!response.ok) {
    throw new APIError(response.status, 'Failed to download export', `/api/v1/excel/export/${exportId}/download`);
  }
  return response.blob();
}

export async function listExcelExports(): Promise<DailyExportResult[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/excel/exports`);
  return handleResponse<DailyExportResult[]>(response, '/api/v1/excel/exports');
}

// ============================================
// Parent/Telegram API (to be implemented on backend)
// ============================================

export async function fetchParents(): Promise<Parent[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/parents`);
  return handleResponse<Parent[]>(response, '/api/v1/parents');
}

export async function fetchParent(parentId: string): Promise<Parent> {
  const response = await fetch(`${API_BASE_URL}/api/v1/parents/${parentId}`);
  return handleResponse<Parent>(response, `/api/v1/parents/${parentId}`);
}

export async function createParent(parent: Omit<Parent, 'parent_id' | 'created_at'>): Promise<Parent> {
  const response = await fetch(`${API_BASE_URL}/api/v1/parents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(parent),
  });
  return handleResponse<Parent>(response, '/api/v1/parents');
}

export async function updateParent(parentId: string, parent: Partial<Parent>): Promise<Parent> {
  const response = await fetch(`${API_BASE_URL}/api/v1/parents/${parentId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(parent),
  });
  return handleResponse<Parent>(response, `/api/v1/parents/${parentId}`);
}

export async function linkParentTelegram(parentId: string, linkCode: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/parents/${parentId}/link`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ link_code: linkCode }),
  });
  return handleResponse<{ success: boolean }>(response, `/api/v1/parents/${parentId}/link`);
}

export async function fetchNotificationQueueStats(): Promise<NotificationQueueStats> {
  const response = await fetch(`${API_BASE_URL}/api/v1/telegram/queue/stats`);
  return handleResponse<NotificationQueueStats>(response, '/api/v1/telegram/queue/stats');
}

// ============================================
// WebSocket/SSE Connection
// ============================================

export type HealthWebSocketHandler = (snapshot: HealthSnapshot) => void;
export type HealthWebSocketErrorHandler = (error: Event) => void;
export type HealthWebSocketCloseHandler = (event: CloseEvent) => void;

export class HealthWebSocketClient {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private lastSeq = 0;
  private connectionId: string | null = null;
  private handlers: Set<HealthWebSocketHandler> = new Set();
  private errorHandlers: Set<HealthWebSocketErrorHandler> = new Set();
  private closeHandlers: Set<HealthWebSocketCloseHandler> = new Set();
  private isIntentionalClose = false;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.isIntentionalClose = false;
    this.ws = new WebSocket(`${WS_BASE_URL}/api/v1/health/ws`);

    this.ws.onopen = () => {
      console.log('[HealthWS] Connected');
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      try {
        const snapshot: HealthSnapshot = JSON.parse(event.data);

        // Handle pong
        if (snapshot.type === 'pong') {
          return;
        }

        // Track sequence for reconnect sync
        if (snapshot.seq !== undefined) {
          this.lastSeq = snapshot.seq;
        }

        // Store connection ID
        if (snapshot.connection_id) {
          this.connectionId = snapshot.connection_id;
        }

        // Notify handlers
        this.handlers.forEach(handler => handler(snapshot));
      } catch (error) {
        console.error('[HealthWS] Failed to parse message:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('[HealthWS] Error:', error);
      this.errorHandlers.forEach(handler => handler(error));
    };

    this.ws.onclose = (event) => {
      console.log('[HealthWS] Closed:', event.code, event.reason);
      this.stopHeartbeat();
      this.closeHandlers.forEach(handler => handler(event));

      if (!this.isIntentionalClose && this.reconnectAttempts < this.maxReconnectAttempts) {
        this.scheduleReconnect();
      }
    };
  }

  private startHeartbeat(): void {
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping', seq: this.lastSeq }));
      }
    }, 10000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++;
    const delay = Math.min(this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);
    console.log(`[HealthWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    setTimeout(() => this.connect(), delay);
  }

  disconnect(): void {
    this.isIntentionalClose = true;
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close(1000, 'Intentional close');
      this.ws = null;
    }
  }

  send(message: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  requestSync(): void {
    this.send({ type: 'sync', seq: this.lastSeq });
  }

  acknowledge(seq: number): void {
    this.send({ type: 'ack', seq });
  }

  subscribe(events: string[]): void {
    this.send({ type: 'subscribe', events });
  }

  onMessage(handler: HealthWebSocketHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onError(handler: HealthWebSocketErrorHandler): () => void {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  onClose(handler: HealthWebSocketCloseHandler): () => void {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  getConnectionId(): string | null {
    return this.connectionId;
  }

  getLastSeq(): number {
    return this.lastSeq;
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// SSE Client for fallback
export class HealthSSEClient {
  private eventSource: EventSource | null = null;
  private lastSeq = 0;
  private handlers: Set<HealthWebSocketHandler> = new Set();
  private errorHandlers: Set<EventListener> = new Set();
  private isIntentionalClose = false;

  connect(): void {
    if (this.eventSource) return;

    this.isIntentionalClose = false;
    this.eventSource = new EventSource(`${API_BASE_URL}/api/v1/health/stream?last_seq=${this.lastSeq}`);

    this.eventSource.onmessage = (event) => {
      try {
        const snapshot: HealthSnapshot = JSON.parse(event.data);
        if (snapshot.seq !== undefined) {
          this.lastSeq = snapshot.seq;
        }
        this.handlers.forEach(handler => handler(snapshot));
      } catch (error) {
        console.error('[HealthSSE] Failed to parse message:', error);
      }
    };

    this.eventSource.onerror = (error) => {
      console.error('[HealthSSE] Error:', error);
      this.errorHandlers.forEach(handler => handler(error));

      if (!this.isIntentionalClose) {
        // EventSource auto-reconnects, but we can force a reconnect with last_seq
        this.disconnect();
        setTimeout(() => this.connect(), 5000);
      }
    };
  }

  disconnect(): void {
    this.isIntentionalClose = true;
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  onMessage(handler: HealthWebSocketHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onError(handler: EventListener): () => void {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  isConnected(): boolean {
    return this.eventSource?.readyState === EventSource.OPEN;
  }
}

// Singleton instances
export const healthWS = new HealthWebSocketClient();
export const healthSSE = new HealthSSEClient();

// ============================================
// Utility: API Response Wrapper
// ============================================

export async function apiCall<T>(
  fn: () => Promise<T>,
  onError?: (error: APIError) => void
): Promise<APIResponse<T>> {
  try {
    const data = await fn();
    return { data, error: null, loading: false };
  } catch (error) {
    if (error instanceof APIError) {
      onError?.(error);
      return { data: null, error: error as unknown as APIErrorType, loading: false };
    }
    const apiError = new APIError(0, String(error), 'unknown');
    onError?.(apiError);
    return { data: null, error: apiError as unknown as APIErrorType, loading: false };
  }
}