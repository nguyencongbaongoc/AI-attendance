<template>
  <div class="system-health-panel glass">
    <div class="panel-header">
      <h3 class="panel-title">
        <svg class="title-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/>
          <path d="M12 6v6l4 2"/>
        </svg>
        System Health
      </h3>
      <div class="header-actions">
        <span class="status-badge" :class="overallStatusClass">
          {{ overallStatusLabel }}
        </span>
        <button 
          class="refresh-btn" 
          @click="refreshHealth"
          :disabled="healthLoading"
          title="Refresh health data"
        >
          <svg v-if="!healthLoading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M23 4v6h-6"/>
            <path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
          </svg>
          <svg v-else class="spinning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10" stroke-opacity="0.25"/>
            <path d="M12 2a10 10 0 0110 10" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    </div>
    
    <div v-if="healthError" class="health-error">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <span>{{ healthError }}</span>
    </div>
    
    <!-- Overall Status Summary -->
    <div class="status-summary">
      <div class="status-item" :class="getComponentStatusClass('cameras')">
        <div class="status-indicator"></div>
        <div class="status-info">
          <span class="status-label">Cameras</span>
          <span class="status-value">{{ healthyCameraCount }} / {{ totalCameraCount }} Healthy</span>
        </div>
      </div>
      <div class="status-item" :class="getComponentStatusClass('gpu')">
        <div class="status-indicator"></div>
        <div class="status-info">
          <span class="status-label">GPU / CUDA</span>
          <span class="status-value">{{ gpuStatusLabel }}</span>
        </div>
      </div>
      <div class="status-item" :class="getComponentStatusClass('telegram')">
        <div class="status-indicator"></div>
        <div class="status-info">
          <span class="status-label">Telegram</span>
          <span class="status-value">{{ telegramStatusLabel }}</span>
        </div>
      </div>
      <div class="status-item" :class="getComponentStatusClass('database')">
        <div class="status-indicator"></div>
        <div class="status-info">
          <span class="status-label">Databases</span>
          <span class="status-value">{{ databaseStatusLabel }}</span>
        </div>
      </div>
    </div>
    
    <!-- Camera Health Details -->
    <div class="health-section">
      <h4 class="section-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/>
          <circle cx="12" cy="12" r="4"/>
        </svg>
        Camera Streams
      </h4>
      <div class="camera-health-grid">
        <div 
          v-for="(cam, camId) in cameraHealth" 
          :key="camId"
          class="camera-health-card"
          :class="cam.state"
        >
          <div class="camera-header">
            <span class="camera-id">{{ camId }}</span>
            <span class="camera-state" :class="cam.state">{{ formatState(cam.state) }}</span>
          </div>
          <div class="camera-message">{{ cam.message }}</div>
          <div class="camera-metrics">
            <div class="metric">
              <span class="metric-label">FPS</span>
              <span class="metric-value">{{ cam.current_fps ? cam.current_fps.toFixed(1) : 'N/A' }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Frames</span>
              <span class="metric-value">{{ cam.frames_received }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Dropped</span>
              <span class="metric-value">{{ cam.frames_dropped }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Uptime</span>
              <span class="metric-value">{{ formatUptime(cam.uptime_seconds) }}</span>
            </div>
            <div class="metric" v-if="cam.current_resolution">
              <span class="metric-label">Resolution</span>
              <span class="metric-value">{{ cam.current_resolution.join('x') }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- GPU Status Details -->
    <div class="health-section">
      <h4 class="section-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <path d="M8 21h8"/>
          <path d="M12 17v4"/>
        </svg>
        GPU / CUDA / NVDEC
      </h4>
      <div class="gpu-details">
        <div class="detail-row">
          <span class="detail-label">GPU</span>
          <span class="detail-value">{{ gpuStatus.gpu_name }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Driver</span>
          <span class="detail-value">{{ gpuStatus.driver_version }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">CUDA Runtime</span>
          <span class="detail-value">{{ gpuStatus.cuda_runtime_version }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">CUDA Toolkit</span>
          <span class="detail-value">{{ gpuStatus.cuda_toolkit_version }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">cuDNN</span>
          <span class="detail-value">{{ gpuStatus.cudnn_version }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">PyTorch</span>
          <span class="detail-value">{{ gpuStatus.pytorch_version }} (CUDA {{ gpuStatus.pytorch_cuda_version }})</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">ONNX Runtime</span>
          <span class="detail-value">{{ gpuStatus.onnxruntime_version }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">CUDA EP</span>
          <span class="detail-value" :class="gpuStatus.cuda_ep_registered ? 'status-ok' : 'status-warn'">
            {{ gpuStatus.cuda_ep_registered ? 'Registered' : 'Not Registered' }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">NVDEC</span>
          <span class="detail-value" :class="gpuStatus.nvdec_available ? 'status-ok' : 'status-warn'">
            {{ gpuStatus.nvdec_available ? 'Available' : 'Not Available' }}
          </span>
        </div>
        <div class="detail-row">
          <span class="detail-label">Torch CUDA</span>
          <span class="detail-value" :class="gpuStatus.torch_cuda_available ? 'status-ok' : 'status-warn'">
            {{ gpuStatus.torch_cuda_available ? 'Available' : 'Not Available' }}
          </span>
        </div>
      </div>
      
      <!-- Model Availability -->
      <div class="model-availability" v-if="gpuStatus.model_availability && Object.keys(gpuStatus.model_availability).length > 0">
        <h5>Model Availability</h5>
        <div class="model-grid">
          <div 
            v-for="(status, model) in gpuStatus.model_availability" 
            :key="model"
            class="model-item"
            :class="status.toLowerCase()"
          >
            <span class="model-name">{{ formatModelName(model) }}</span>
            <span class="model-status">{{ status }}</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Component Health Details -->
    <div class="health-section">
      <h4 class="section-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <path d="M8 21h8"/>
          <path d="M12 17v4"/>
        </svg>
        Component Health
      </h4>
      <div class="component-list">
        <div 
          v-for="component in systemHealth.components" 
          :key="component.component"
          class="component-item"
          :class="component.status"
        >
          <div class="component-info">
            <span class="component-name">{{ formatComponentName(component.component) }}</span>
            <span class="component-message">{{ component.message }}</span>
          </div>
          <span class="component-status" :class="component.status">{{ component.status }}</span>
        </div>
      </div>
    </div>
    
    <!-- Metrics Summary -->
    <div class="health-section">
      <h4 class="section-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <line x1="18" y1="20" x2="18" y2="10"/>
          <line x1="12" y1="20" x2="12" y2="4"/>
          <line x1="6" y1="20" x2="6" y2="14"/>
        </svg>
        Metrics Summary
      </h4>
      <div class="metrics-grid">
        <div class="metric-card">
          <span class="metric-card-label">Queue Pending</span>
          <span class="metric-card-value">{{ systemMetrics.queue_metrics.total_pending || 0 }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">Queue Sent</span>
          <span class="metric-card-value">{{ systemMetrics.queue_metrics.total_sent || 0 }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">Queue Failed</span>
          <span class="metric-card-value">{{ systemMetrics.queue_metrics.total_failed || 0 }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">Parents</span>
          <span class="metric-card-value">{{ systemMetrics.database_metrics.parent_registry?.total_parents || 0 }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">Exit Sessions</span>
          <span class="metric-card-value">{{ getExitSessionCount() }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">Last Update</span>
          <span class="metric-card-value">{{ formatLastUpdate }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()

// Computed
const cameraHealth = computed(() => store.cameraHealth)
const gpuStatus = computed(() => store.gpuStatus)
const systemHealth = computed(() => store.systemHealth)
const systemMetrics = computed(() => store.systemMetrics)
const healthLoading = computed(() => store.healthLoading)
const healthError = computed(() => store.healthError)
const healthyCameraCount = computed(() => store.healthyCameraCount)
const totalCameraCount = computed(() => store.totalCameraCount)

const overallStatus = computed(() => systemHealth.value.overall_status || 'unknown')

const overallStatusClass = computed(() => {
  switch (overallStatus.value) {
    case 'healthy': return 'status-healthy'
    case 'degraded': return 'status-degraded'
    case 'unhealthy': return 'status-unhealthy'
    default: return 'status-unknown'
  }
})

const overallStatusLabel = computed(() => {
  switch (overallStatus.value) {
    case 'healthy': return 'HEALTHY'
    case 'degraded': return 'DEGRADED'
    case 'unhealthy': return 'UNHEALTHY'
    default: return 'UNKNOWN'
  }
})

const gpuStatusLabel = computed(() => {
  if (gpuStatus.value.torch_cuda_available && gpuStatus.value.cuda_ep_registered) {
    return 'Fully Operational'
  } else if (gpuStatus.value.torch_cuda_available || gpuStatus.value.cuda_ep_registered) {
    return 'Partially Available'
  }
  return 'Not Available'
})

const telegramStatusLabel = computed(() => {
  const tgComponent = systemHealth.value.components.find(c => c.component === 'telegram')
  return tgComponent ? (tgComponent.status === 'healthy' ? 'Configured' : 'Not Configured') : 'Unknown'
})

const databaseStatusLabel = computed(() => {
  const dbComponents = systemHealth.value.components.filter(c => c.component.startsWith('database.'))
  const healthy = dbComponents.filter(c => c.status === 'healthy').length
  return `${healthy} / ${dbComponents.length} Healthy`
})

const formatLastUpdate = computed(() => {
  if (!store.lastHealthUpdate) return 'Never'
  const diff = Date.now() - store.lastHealthUpdate
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  return `${Math.floor(diff / 3600000)}h ago`
})

function getComponentStatusClass(componentPrefix) {
  const component = systemHealth.value.components.find(c => c.component.startsWith(componentPrefix))
  if (!component) return 'status-unknown'
  return `status-${component.status}`
}

function formatState(state) {
  const labels = {
    'live': 'LIVE',
    'degraded': 'DEGRADED',
    'offline': 'OFFLINE',
    'connecting': 'CONNECTING',
    'reconnecting': 'RECONNECTING',
    'error': 'ERROR',
    'unknown': 'UNKNOWN'
  }
  return labels[state] || state.toUpperCase()
}

function formatUptime(seconds) {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function formatComponentName(name) {
  return name.split('.').map(part => 
    part.charAt(0).toUpperCase() + part.slice(1)
  ).join(' / ')
}

function formatModelName(name) {
  const names = {
    'scrfd': 'SCRFD (Face Detection)',
    'arcface': 'ArcFace (Recognition)',
    'landmark_1k3d68': 'Landmark 1K3D68',
    'reid': 'ReID (Person Re-identification)',
    'yolo_person': 'YOLO Person',
    'yolo_pose': 'YOLO Pose'
  }
  return names[name] || name
}

function getExitSessionCount() {
  const exitSessions = systemMetrics.value.database_metrics?.exit_sessions
  if (!exitSessions) return 0
  let total = 0
  for (const [key, value] of Object.entries(exitSessions)) {
    if (typeof value === 'number') total += value
  }
  return total
}

function refreshHealth() {
  store.refreshAllHealth()
}

onMounted(() => {
  store.refreshAllHealth()
  // Start polling every 10 seconds
  store.startHealthPolling(10000)
})
</script>

<style scoped>
.system-health-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-height: 0;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.title-icon {
  width: 20px;
  height: 20px;
  color: var(--accent-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.status-badge.status-healthy {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
}

.status-badge.status-degraded {
  background: rgba(234, 179, 8, 0.15);
  color: var(--warning);
}

.status-badge.status-unhealthy {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error);
}

.status-badge.status-unknown {
  background: rgba(100, 116, 139, 0.15);
  color: var(--text-muted);
}

.refresh-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.refresh-btn:hover:not(:disabled) {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: white;
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.refresh-btn svg {
  width: 18px;
  height: 18px;
}

.refresh-btn .spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.health-error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--radius-lg);
  color: var(--error);
  font-size: var(--text-sm);
}

.health-error svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.status-summary {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}

@media (min-width: 768px) {
  .status-summary {
    grid-template-columns: repeat(4, 1fr);
  }
}

.status-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  transition: all var(--transition-fast);
}

.status-item.status-healthy {
  border-color: rgba(34, 197, 94, 0.3);
}

.status-item.status-degraded {
  border-color: rgba(234, 179, 8, 0.3);
}

.status-item.status-unhealthy {
  border-color: rgba(239, 68, 68, 0.3);
}

.status-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-item.status-healthy .status-indicator {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}

.status-item.status-degraded .status-indicator {
  background: var(--warning);
  box-shadow: 0 0 8px var(--warning);
}

.status-item.status-unhealthy .status-indicator {
  background: var(--error);
  box-shadow: 0 0 8px var(--error);
}

.status-item.status-unknown .status-indicator {
  background: var(--text-muted);
}

.status-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.status-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.status-value {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.health-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.section-title svg {
  width: 16px;
  height: 16px;
  color: var(--accent-primary);
}

.camera-health-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-3);
}

@media (min-width: 640px) {
  .camera-health-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.camera-health-card {
  padding: var(--space-3);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  transition: all var(--transition-fast);
}

.camera-health-card.live {
  border-color: rgba(34, 197, 94, 0.3);
}

.camera-health-card.degraded {
  border-color: rgba(234, 179, 8, 0.3);
}

.camera-health-card.offline,
.camera-health-card.error {
  border-color: rgba(239, 68, 68, 0.3);
}

.camera-health-card.connecting,
.camera-health-card.reconnecting {
  border-color: rgba(59, 130, 246, 0.3);
}

.camera-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.camera-id {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.camera-state {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.camera-state.live {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
}

.camera-state.degraded {
  background: rgba(234, 179, 8, 0.15);
  color: var(--warning);
}

.camera-state.offline,
.camera-state.error {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error);
}

.camera-state.connecting,
.camera-state.reconnecting {
  background: rgba(59, 130, 246, 0.15);
  color: var(--accent-primary);
}

.camera-state.unknown {
  background: rgba(100, 116, 139, 0.15);
  color: var(--text-muted);
}

.camera-message {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: var(--space-3);
}

.camera-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-2);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-value {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
}

.gpu-details,
.component-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.detail-row,
.component-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
}

.detail-label,
.component-name {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.detail-value,
.component-message {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
}

.detail-value.status-ok {
  color: var(--success);
}

.detail-value.status-warn {
  color: var(--warning);
}

.component-status {
  font-size: var(--text-xs);
  font-weight: 600;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.component-status.healthy {
  background: rgba(34, 197, 94, 0.15);
  color: var(--success);
}

.component-status.degraded {
  background: rgba(234, 179, 8, 0.15);
  color: var(--warning);
}

.component-status.unhealthy {
  background: rgba(239, 68, 68, 0.15);
  color: var(--error);
}

.model-availability {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--glass-border);
}

.model-availability h5 {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 var(--space-2) 0;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-2);
}

@media (min-width: 640px) {
  .model-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

.model-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
}

.model-name {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.model-status {
  font-size: var(--text-sm);
  font-weight: 500;
}

.model-status.available {
  color: var(--success);
}

.model-status.unavailable,
.model-status.missing {
  color: var(--error);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
}

@media (min-width: 768px) {
  .metrics-grid {
    grid-template-columns: repeat(6, 1fr);
  }
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-3);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  text-align: center;
}

.metric-card-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-card-value {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}
</style>