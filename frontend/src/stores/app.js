import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAppStore = defineStore('app', () => {
  // System state
  const systemStatus = ref('online') // online, degraded, offline
  const cameraCount = ref(2)
  const activeCameras = ref(['CAM1', 'CAM2'])
  
  // Camera feeds
  const cameraFeeds = ref({
    CAM1: {
      id: 'CAM1',
      status: 'live',
      streamUrl: null,
      currentFrame: null,
      annotations: [],
      tracks: [],
      lastUpdate: null
    },
    CAM2: {
      id: 'CAM2',
      status: 'live',
      streamUrl: null,
      currentFrame: null,
      annotations: [],
      tracks: [],
      lastUpdate: null
    }
  })
  
  // Attendance summary
  const attendanceSummary = ref({
    present: 0,
    late: 0,
    left: 0,
    absent: 0,
    total: 0
  })
  
  // Live events timeline
  const liveEvents = ref([])
  const maxEvents = 100
  
  // Selected person
  const selectedPerson = ref(null)
  const selectedPersonDetail = ref(null)
  
  // Search
  const searchQuery = ref('')
  const searchResults = ref([])
  const searchLoading = ref(false)
  
  // Replay
  const replayState = ref({
    isOpen: false,
    loading: false,
    currentVideo: null,
    currentAppearance: null,
    playbackRate: 1.0
  })
  
  // Provenance panel
  const provenancePanel = ref({
    isOpen: false,
    data: null
  })
  
  // Loading states
  const loadingStates = ref({
    cameras: true,
    attendance: true,
    events: true,
    search: false,
    replay: false
  })
  
  // Error states
  const errors = ref({
    cameras: null,
    attendance: null,
    events: null,
    search: null,
    replay: null
  })
  
  // UI state
  const sidebarCollapsed = ref(false)
  const reducedMotion = ref(false)
  
  // Health monitoring state (Phase 37C)
  const systemHealth = ref({
    overall_status: 'unknown',
    timestamp: null,
    components: [],
    cameras: {},
    gpu: null,
    runtime: {}
  })
  
  const cameraHealth = ref({
    CAM1: { state: 'unknown', message: '', frames_received: 0, frames_dropped: 0, current_fps: null, current_resolution: null, uptime_seconds: 0 },
    CAM2: { state: 'unknown', message: '', frames_received: 0, frames_dropped: 0, current_fps: null, current_resolution: null, uptime_seconds: 0 }
  })
  
  const gpuStatus = ref({
    gpu_name: 'Unknown',
    driver_version: 'Unknown',
    cuda_runtime_version: 'Unknown',
    cuda_toolkit_version: 'Unknown',
    cudnn_version: 'Unknown',
    pytorch_version: 'Unknown',
    pytorch_cuda_version: 'Unknown',
    torch_cuda_available: false,
    onnxruntime_version: 'Unknown',
    cuda_ep_registered: false,
    nvdec_available: false,
    model_availability: {}
  })
  
  const systemMetrics = ref({
    timestamp: null,
    camera_metrics: {},
    queue_metrics: {},
    attendance_metrics: {},
    policy_metrics: {},
    telegram_metrics: {},
    database_metrics: {}
  })
  
  const healthLoading = ref(false)
  const healthError = ref(null)
  const lastHealthUpdate = ref(null)
  
  // Computed
  const isSystemHealthy = computed(() => systemStatus.value === 'online')
  const totalEvents = computed(() => liveEvents.value.length)
  const recentEvents = computed(() => liveEvents.value.slice(-20).reverse())
  const isSystemHealthyOverall = computed(() => systemHealth.value.overall_status === 'healthy')
  const healthyCameraCount = computed(() => {
    let count = 0
    for (const cam of Object.values(cameraHealth.value)) {
      if (cam.state === 'live') count++
    }
    return count
  })
  const totalCameraCount = computed(() => Object.keys(cameraHealth.value).length)
  
  // Actions
  function setSystemStatus(status) {
    systemStatus.value = status
  }
  
  function updateCameraFeed(cameraId, data) {
    if (cameraFeeds.value[cameraId]) {
      cameraFeeds.value[cameraId] = {
        ...cameraFeeds.value[cameraId],
        ...data,
        lastUpdate: Date.now()
      }
    }
  }
  
  function setCameraStatus(cameraId, status) {
    if (cameraFeeds.value[cameraId]) {
      cameraFeeds.value[cameraId].status = status
    }
  }
  
  function addLiveEvent(event) {
    liveEvents.value.unshift({
      ...event,
      id: event.id || `evt_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: event.timestamp || Date.now() / 1000
    })
    
    // Keep only maxEvents
    if (liveEvents.value.length > maxEvents) {
      liveEvents.value = liveEvents.value.slice(0, maxEvents)
    }
  }
  
  function updateAttendanceSummary(summary) {
    attendanceSummary.value = {
      ...attendanceSummary.value,
      ...summary,
      total: (summary.present || 0) + (summary.late || 0) + (summary.left || 0) + (summary.absent || 0)
    }
  }
  
  function selectPerson(person) {
    selectedPerson.value = person
  }
  
  function setSelectedPersonDetail(detail) {
    selectedPersonDetail.value = detail
  }
  
  function clearSelectedPerson() {
    selectedPerson.value = null
    selectedPersonDetail.value = null
  }
  
  function setSearchQuery(query) {
    searchQuery.value = query
  }
  
  function setSearchResults(results) {
    searchResults.value = results
  }
  
  function setSearchLoading(loading) {
    searchLoading.value = loading
  }
  
  function openReplay(appearance) {
    replayState.value = {
      isOpen: true,
      loading: true,
      currentVideo: null,
      currentAppearance: appearance,
      playbackRate: 1.0
    }
  }
  
  function closeReplay() {
    replayState.value = {
      isOpen: false,
      loading: false,
      currentVideo: null,
      currentAppearance: null,
      playbackRate: 1.0
    }
  }
  
  function setReplayVideo(videoUrl) {
    replayState.value.currentVideo = videoUrl
    replayState.value.loading = false
  }
  
  function setReplayLoading(loading) {
    replayState.value.loading = loading
  }
  
  function openProvenance(data) {
    provenancePanel.value = {
      isOpen: true,
      data
    }
  }
  
  function closeProvenance() {
    provenancePanel.value = {
      isOpen: false,
      data: null
    }
  }
  
  function setLoadingState(key, loading) {
    loadingStates.value[key] = loading
  }
  
  function setError(key, error) {
    errors.value[key] = error
  }
  
  function clearError(key) {
    errors.value[key] = null
  }
  
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
  
  function setReducedMotion(value) {
    reducedMotion.value = value
  }
  
  // Health monitoring actions (Phase 37C)
  async function fetchSystemHealth() {
    healthLoading.value = true
    healthError.value = null
    try {
      const response = await fetch('/api/v1/health/system')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      systemHealth.value = data
      cameraHealth.value = data.cameras
      gpuStatus.value = data.gpu
      lastHealthUpdate.value = Date.now()
    } catch (error) {
      healthError.value = error.message
      console.error('Failed to fetch system health:', error)
    } finally {
      healthLoading.value = false
    }
  }
  
  async function fetchCameraHealth() {
    try {
      const response = await fetch('/api/v1/health/cameras')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      cameraHealth.value = data
    } catch (error) {
      console.error('Failed to fetch camera health:', error)
    }
  }
  
  async function fetchGPUStatus() {
    try {
      const response = await fetch('/api/v1/health/gpu')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      gpuStatus.value = data
    } catch (error) {
      console.error('Failed to fetch GPU status:', error)
    }
  }
  
  async function fetchMetrics() {
    try {
      const response = await fetch('/api/v1/health/metrics')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      systemMetrics.value = data
    } catch (error) {
      console.error('Failed to fetch metrics:', error)
    }
  }
  
  async function refreshAllHealth() {
    await Promise.all([
      fetchSystemHealth(),
      fetchCameraHealth(),
      fetchGPUStatus(),
      fetchMetrics()
    ])
  }
  
  function startHealthPolling(intervalMs = 10000) {
    // Initial fetch
    refreshAllHealth()
    // Set up polling
    const intervalId = setInterval(() => {
      refreshAllHealth()
    }, intervalMs)
    return intervalId
  }
  
  // Initialize with mock data for development
  function initializeMockData() {
    // Mock camera feeds
    cameraFeeds.value.CAM1.status = 'live'
    cameraFeeds.value.CAM2.status = 'live'
    
    // Mock attendance
    attendanceSummary.value = {
      present: 128,
      late: 7,
      left: 94,
      absent: 12,
      total: 241
    }
    
    // Mock live events
    const mockEvents = [
      { direction: 'in', personId: 'HS001', cameraId: 'CAM1', timestamp: Date.now() / 1000 - 300, trackId: 'A17', certainty: 'known', confidence: 0.987 },
      { direction: 'in', personId: 'HS004', cameraId: 'CAM2', timestamp: Date.now() / 1000 - 180, trackId: 'B04', certainty: 'known', confidence: 0.956 },
      { direction: 'out', personId: 'HS017', cameraId: 'CAM1', timestamp: Date.now() / 1000 - 60, trackId: 'C02', certainty: 'known', confidence: 0.923 },
      { direction: 'in', personId: 'HS008', cameraId: 'CAM1', timestamp: Date.now() / 1000 - 10, trackId: 'A19', certainty: 'ambiguous', confidence: 0.612 },
    ]
    
    liveEvents.value = mockEvents.map((e, i) => ({
      ...e,
      id: `evt_${i}`,
      globalObservationId: `GO-${String(i).padStart(3, '0')}`
    }))
    
    loadingStates.value = {
      cameras: false,
      attendance: false,
      events: false,
      search: false,
      replay: false
    }
  }
  
  return {
    // State
    systemStatus,
    cameraCount,
    activeCameras,
    cameraFeeds,
    attendanceSummary,
    liveEvents,
    selectedPerson,
    selectedPersonDetail,
    searchQuery,
    searchResults,
    searchLoading,
    replayState,
    provenancePanel,
    loadingStates,
    errors,
    sidebarCollapsed,
    reducedMotion,
    // Health monitoring (Phase 37C)
    systemHealth,
    cameraHealth,
    gpuStatus,
    systemMetrics,
    healthLoading,
    healthError,
    lastHealthUpdate,
    
    // Computed
    isSystemHealthy,
    totalEvents,
    recentEvents,
    isSystemHealthyOverall,
    healthyCameraCount,
    totalCameraCount,
    
    // Actions
    setSystemStatus,
    updateCameraFeed,
    setCameraStatus,
    addLiveEvent,
    updateAttendanceSummary,
    selectPerson,
    setSelectedPersonDetail,
    clearSelectedPerson,
    setSearchQuery,
    setSearchResults,
    setSearchLoading,
    openReplay,
    closeReplay,
    setReplayVideo,
    setReplayLoading,
    openProvenance,
    closeProvenance,
    setLoadingState,
    setError,
    clearError,
    toggleSidebar,
    setReducedMotion,
    // Health actions (Phase 37C)
    fetchSystemHealth,
    fetchCameraHealth,
    fetchGPUStatus,
    fetchMetrics,
    refreshAllHealth,
    startHealthPolling,
    initializeMockData
  }
})
