// Global State Store using Zustand
// Replaces Pinia store from existing frontend, adapted for React

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  SystemHealthResponse,
  CameraHealthResponse,
  GPUStatusResponse,
  MetricsResponse,
  HealthSnapshot,
  AttendanceRecord,
  AttendanceSummary,
  Person,
  PersonSearchParams,
  PersonSearchResult,
  TimetableEntry,
  Timetable,
  EnrollmentPerson,
  EnrollmentStats,
  Parent,
  NotificationQueueStats,
} from '@/types/backend';

// ============================================
// System Health State
// ============================================

interface HealthState {
  systemHealth: SystemHealthResponse | null;
  cameraHealth: Record<string, CameraHealthResponse> | null;
  gpuStatus: GPUStatusResponse | null;
  metrics: MetricsResponse | null;
  healthSnapshot: HealthSnapshot | null;
  realtimeConnected: boolean;
  realtimeError: Event | null;
  lastHealthUpdate: number | null;

  setSystemHealth: (health: SystemHealthResponse) => void;
  setCameraHealth: (health: Record<string, CameraHealthResponse>) => void;
  setGPUStatus: (status: GPUStatusResponse) => void;
  setMetrics: (metrics: MetricsResponse) => void;
  setHealthSnapshot: (snapshot: HealthSnapshot) => void;
  setRealtimeConnected: (connected: boolean) => void;
  setRealtimeError: (error: Event | null) => void;
  updateCameraFrame: (cameraId: string, data: Partial<CameraHealthResponse>) => void;
}

export const useHealthStore = create<HealthState>()(
  persist(
    (set) => ({
      systemHealth: null,
      cameraHealth: null,
      gpuStatus: null,
      metrics: null,
      healthSnapshot: null,
      realtimeConnected: false,
      realtimeError: null,
      lastHealthUpdate: null,

      setSystemHealth: (health) => set({ systemHealth: health, lastHealthUpdate: Date.now() }),
      setCameraHealth: (health) => set({ cameraHealth: health, lastHealthUpdate: Date.now() }),
      setGPUStatus: (status) => set({ gpuStatus: status, lastHealthUpdate: Date.now() }),
      setMetrics: (metrics) => set({ metrics, lastHealthUpdate: Date.now() }),
      setHealthSnapshot: (snapshot) => set({ healthSnapshot: snapshot, lastHealthUpdate: Date.now() }),
      setRealtimeConnected: (connected) => set({ realtimeConnected: connected }),
      setRealtimeError: (error) => set({ realtimeError: error }),
      updateCameraFrame: (cameraId, data) => set((state) => ({
        cameraHealth: state.cameraHealth
          ? { ...state.cameraHealth, [cameraId]: { ...state.cameraHealth[cameraId], ...data } }
          : null,
        lastHealthUpdate: Date.now(),
      })),
    }),
    {
      name: 'health-store',
      partialize: (state) => ({
        // Don't persist realtime connection state
        systemHealth: state.systemHealth,
        cameraHealth: state.cameraHealth,
        gpuStatus: state.gpuStatus,
        metrics: state.metrics,
      }),
    }
  )
);

// ============================================
// Attendance State
// ============================================

interface AttendanceState {
  attendanceSummary: AttendanceSummary | null;
  liveEvents: AttendanceRecord[];
  selectedPerson: Person | null;
  selectedPersonDetail: AttendanceRecord | null;
  searchQuery: string;
  searchFilter: string;
  searchResults: Person[];
  searchLoading: boolean;
  maxEvents: number;

  setAttendanceSummary: (summary: AttendanceSummary) => void;
  addLiveEvent: (event: AttendanceRecord) => void;
  setLiveEvents: (events: AttendanceRecord[]) => void;
  selectPerson: (person: Person | null) => void;
  setSelectedPersonDetail: (detail: AttendanceRecord | null) => void;
  clearSelectedPerson: () => void;
  setSearchQuery: (query: string) => void;
  setSearchFilter: (filter: string) => void;
  setSearchResults: (results: Person[]) => void;
  setSearchLoading: (loading: boolean) => void;
}

export const useAttendanceStore = create<AttendanceState>()(
  persist(
    (set) => ({
      attendanceSummary: null,
      liveEvents: [],
      selectedPerson: null,
      selectedPersonDetail: null,
      searchQuery: '',
      searchFilter: 'all',
      searchResults: [],
      searchLoading: false,
      maxEvents: 100,

      setAttendanceSummary: (summary) => set({ attendanceSummary: summary }),
      addLiveEvent: (event) => set((state) => ({
        liveEvents: [event, ...state.liveEvents].slice(0, state.maxEvents),
      })),
      setLiveEvents: (events) => set({ liveEvents: events }),
      selectPerson: (person) => set({ selectedPerson: person }),
      setSelectedPersonDetail: (detail) => set({ selectedPersonDetail: detail }),
      clearSelectedPerson: () => set({ selectedPerson: null, selectedPersonDetail: null }),
      setSearchQuery: (query) => set({ searchQuery: query }),
      setSearchFilter: (filter) => set({ searchFilter: filter }),
      setSearchResults: (results) => set({ searchResults: results }),
      setSearchLoading: (loading) => set({ searchLoading: loading }),
    }),
    {
      name: 'attendance-store',
      partialize: (state) => ({
        attendanceSummary: state.attendanceSummary,
        searchQuery: state.searchQuery,
        searchFilter: state.searchFilter,
      }),
    }
  )
);

// ============================================
// Replay State
// ============================================

interface ReplayState {
  isOpen: boolean;
  loading: boolean;
  currentVideo: string | null;
  currentAppearance: AttendanceRecord | null;
  playbackRate: number;

  openReplay: (appearance: AttendanceRecord) => void;
  closeReplay: () => void;
  setReplayVideo: (videoUrl: string) => void;
  setReplayLoading: (loading: boolean) => void;
  setPlaybackRate: (rate: number) => void;
}

export const useReplayStore = create<ReplayState>((set) => ({
  isOpen: false,
  loading: false,
  currentVideo: null,
  currentAppearance: null,
  playbackRate: 1.0,

  openReplay: (appearance) => set({
    isOpen: true,
    loading: true,
    currentVideo: null,
    currentAppearance: appearance,
    playbackRate: 1.0,
  }),
  closeReplay: () => set({
    isOpen: false,
    loading: false,
    currentVideo: null,
    currentAppearance: null,
    playbackRate: 1.0,
  }),
  setReplayVideo: (videoUrl) => set({ currentVideo: videoUrl, loading: false }),
  setReplayLoading: (loading) => set({ loading }),
  setPlaybackRate: (rate) => set({ playbackRate: rate }),
}));

// ============================================
// Provenance State
// ============================================

interface ProvenanceState {
  isOpen: boolean;
  data: HealthSnapshot | null;

  openProvenance: (data: HealthSnapshot) => void;
  closeProvenance: () => void;
}

export const useProvenanceStore = create<ProvenanceState>((set) => ({
  isOpen: false,
  data: null,

  openProvenance: (data) => set({ isOpen: true, data }),
  closeProvenance: () => set({ isOpen: false, data: null }),
}));

// ============================================
// UI State
// ============================================

interface UIState {
  sidebarCollapsed: boolean;
  reducedMotion: boolean;
  activeScreen: string;
  detailPersonId: string | null;
  loadingStates: Record<string, boolean>;
  errors: Record<string, Error | null>;

  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setReducedMotion: (value: boolean) => void;
  setActiveScreen: (screen: string) => void;
  setDetailPersonId: (id: string | null) => void;
  setLoadingState: (key: string, loading: boolean) => void;
  setError: (key: string, error: Error | null) => void;
  clearError: (key: string) => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      reducedMotion: false,
      activeScreen: 'command',
      detailPersonId: null,
      loadingStates: {
        cameras: true,
        attendance: true,
        events: true,
        search: false,
        replay: false,
        provenance: false,
        enrollment: false,
        timetable: false,
      },
      errors: {},

      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      setReducedMotion: (value) => set({ reducedMotion: value }),
      setActiveScreen: (screen) => set({ activeScreen: screen }),
      setDetailPersonId: (id) => set({ detailPersonId: id }),
      setLoadingState: (key, loading) => set((state) => ({
        loadingStates: { ...state.loadingStates, [key]: loading },
      })),
      setError: (key, error) => set((state) => ({
        errors: { ...state.errors, [key]: error },
      })),
      clearError: (key) => set((state) => {
        const newErrors = { ...state.errors };
        delete newErrors[key];
        return { errors: newErrors };
      }),
    }),
    {
      name: 'ui-store',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        reducedMotion: state.reducedMotion,
      }),
    }
  )
);

// ============================================
// Enrollment State
// ============================================

interface EnrollmentState {
  enrolledPersons: EnrollmentPerson[];
  enrollmentStats: EnrollmentStats | null;
  enrollStep: number;
  captureState: 'idle' | 'capturing' | 'done';
  quality: number;
  loading: boolean;
  error: Error | null;

  setEnrolledPersons: (persons: EnrollmentPerson[]) => void;
  setEnrollmentStats: (stats: EnrollmentStats) => void;
  setEnrollStep: (step: number) => void;
  setCaptureState: (state: 'idle' | 'capturing' | 'done') => void;
  setQuality: (quality: number) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: Error | null) => void;
  resetEnrollment: () => void;
}

export const useEnrollmentStore = create<EnrollmentState>((set) => ({
  enrolledPersons: [],
  enrollmentStats: null,
  enrollStep: 0,
  captureState: 'idle',
  quality: 0,
  loading: false,
  error: null,

  setEnrolledPersons: (persons) => set({ enrolledPersons: persons }),
  setEnrollmentStats: (stats) => set({ enrollmentStats: stats }),
  setEnrollStep: (step) => set({ enrollStep: step }),
  setCaptureState: (state) => set({ captureState: state }),
  setQuality: (quality) => set({ quality }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  resetEnrollment: () => set({
    enrollStep: 0,
    captureState: 'idle',
    quality: 0,
    loading: false,
    error: null,
  }),
}));

// ============================================
// Timetable State
// ============================================

interface TimetableState {
  timetable: Timetable | null;
  entries: TimetableEntry[];
  loading: boolean;
  error: Error | null;

  setTimetable: (timetable: Timetable) => void;
  setEntries: (entries: TimetableEntry[]) => void;
  addEntry: (entry: TimetableEntry) => void;
  updateEntry: (entryId: string, entry: Partial<TimetableEntry>) => void;
  deleteEntry: (entryId: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: Error | null) => void;
}

export const useTimetableStore = create<TimetableState>((set) => ({
  timetable: null,
  entries: [],
  loading: false,
  error: null,

  setTimetable: (timetable) => set({ timetable }),
  setEntries: (entries) => set({ entries }),
  addEntry: (entry) => set((state) => ({ entries: [...state.entries, entry] })),
  updateEntry: (entryId, entry) => set((state) => ({
    entries: state.entries.map(e => e.entry_id === entryId ? { ...e, ...entry } : e),
  })),
  deleteEntry: (entryId) => set((state) => ({
    entries: state.entries.filter(e => e.entry_id !== entryId),
  })),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));

// ============================================
// Parent/Telegram State
// ============================================

interface ParentState {
  parents: Parent[];
  queueStats: NotificationQueueStats | null;
  loading: boolean;
  error: Error | null;

  setParents: (parents: Parent[]) => void;
  setQueueStats: (stats: NotificationQueueStats) => void;
  addParent: (parent: Parent) => void;
  updateParent: (parentId: string, parent: Partial<Parent>) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: Error | null) => void;
}

export const useParentStore = create<ParentState>((set) => ({
  parents: [],
  queueStats: null,
  loading: false,
  error: null,

  setParents: (parents) => set({ parents }),
  setQueueStats: (stats) => set({ queueStats: stats }),
  addParent: (parent) => set((state) => ({ parents: [...state.parents, parent] })),
  updateParent: (parentId, parent) => set((state) => ({
    parents: state.parents.map(p => p.parent_id === parentId ? { ...p, ...parent } : p),
  })),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));

// ============================================
// Excel Export State
// ============================================

interface ExcelState {
  exports: Array<{
    export_id: string;
    file_path: string;
    sheets_created: string[];
    record_count: number;
    success: boolean;
    error?: string;
    created_at: string;
  }>;
  loading: boolean;
  error: Error | null;

  setExports: (exports: ExcelState['exports']) => void;
  addExport: (exportItem: ExcelState['exports'][0]) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: Error | null) => void;
}

export const useExcelStore = create<ExcelState>((set) => ({
  exports: [],
  loading: false,
  error: null,

  setExports: (exports) => set({ exports }),
  addExport: (exportItem) => set((state) => ({ exports: [exportItem, ...state.exports] })),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));

// ============================================
// Combined Store Hooks
// ============================================

export function useStores() {
  return {
    health: useHealthStore(),
    attendance: useAttendanceStore(),
    replay: useReplayStore(),
    provenance: useProvenanceStore(),
    ui: useUIStore(),
    enrollment: useEnrollmentStore(),
    timetable: useTimetableStore(),
    parent: useParentStore(),
    excel: useExcelStore(),
  };
}

// Initialize stores with mock data for development
export function initializeMockData() {
  const health = useHealthStore.getState();
  const attendance = useAttendanceStore.getState();
  const ui = useUIStore.getState();

  // Mock camera health
  health.setCameraHealth({
    CAM1: {
      camera_id: 'CAM1',
      state: 'live',
      timestamp: new Date().toISOString(),
      message: 'Camera operating normally',
      frames_received: 15420,
      frames_dropped: 3,
      total_errors: 0,
      uptime_seconds: 3600,
      current_resolution: [1920, 1080],
      current_fps: 30,
      current_codec: 'h264',
      last_frame_time: Date.now() / 1000,
      reconnect_count: 0,
      consecutive_failures: 0,
    },
    CAM2: {
      camera_id: 'CAM2',
      state: 'live',
      timestamp: new Date().toISOString(),
      message: 'Camera operating normally',
      frames_received: 14890,
      frames_dropped: 1,
      total_errors: 0,
      uptime_seconds: 3600,
      current_resolution: [1920, 1080],
      current_fps: 30,
      current_codec: 'h264',
      last_frame_time: Date.now() / 1000,
      reconnect_count: 0,
      consecutive_failures: 0,
    },
  });

  // Mock attendance summary
  attendance.setAttendanceSummary({
    present: 128,
    late: 7,
    left_early: 94,
    absent: 12,
    total: 241,
  });

  // Mock live events
  attendance.setLiveEvents([
    {
      attendanceRecordId: 'evt_0',
      sourceResolutionId: 'RES-001',
      personId: 'HS001',
      personName: 'Nguyễn Văn A',
      cameraId: 'CAM1',
      localTrackId: 'A17',
      globalObservationId: 'GO-001',
      direction: 'in',
      identityCertainty: 'known',
      identityCandidate: 'HS001',
      identityConfidence: 0.987,
      timestamp: Date.now() / 1000 - 300,
      day: '2026-08-23',
      sessionId: 'MORNING',
      sessionType: 'CLASSROOM',
      attendanceState: 'present',
      inState: 'on_time',
      outState: 'not_applicable',
      decisionReason: 'Matched known identity within entry window',
      createdAt: new Date().toISOString(),
      persistedAt: new Date().toISOString(),
    },
    {
      attendanceRecordId: 'evt_1',
      sourceResolutionId: 'RES-002',
      personId: 'HS004',
      personName: 'Trần Thị B',
      cameraId: 'CAM2',
      localTrackId: 'B04',
      globalObservationId: 'GO-002',
      direction: 'in',
      identityCertainty: 'known',
      identityCandidate: 'HS004',
      identityConfidence: 0.956,
      timestamp: Date.now() / 1000 - 180,
      day: '2026-08-23',
      sessionId: 'MORNING',
      sessionType: 'CLASSROOM',
      attendanceState: 'present',
      inState: 'on_time',
      outState: 'not_applicable',
      decisionReason: 'Matched known identity within entry window',
      createdAt: new Date().toISOString(),
      persistedAt: new Date().toISOString(),
    },
  ]);

  // Set loading states to false
  ui.setLoadingState('cameras', false);
  ui.setLoadingState('attendance', false);
  ui.setLoadingState('events', false);
}