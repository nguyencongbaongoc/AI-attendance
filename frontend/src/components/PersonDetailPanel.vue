<template>
  <div class="person-detail-panel" :class="{ 'loading': loading }">
    <div class="panel-header">
      <h3 class="panel-title">Person Detail</h3>
      <button class="panel-close" @click="onClose" aria-label="Close">
        <svg class="close-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <div class="panel-body">
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span class="loading-text">Loading person details...</span>
      </div>

      <div v-else-if="!person && !detail" class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
        <h3 class="empty-state-title">No Person Selected</h3>
        <p class="empty-state-message">Select a person from the camera feed or event timeline</p>
      </div>

      <div v-else class="person-content">
        <!-- Person Identity -->
        <div class="person-identity">
          <div class="identity-header">
            <div class="identity-avatar">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
            </div>
            <div class="identity-info">
              <h4 class="person-name">{{ detail.name || person.identityCandidate || 'Unknown Person' }}</h4>
              <div class="person-id">
                <span class="id-text">{{ person.identityCandidate || 'UNKNOWN' }}</span>
                <span class="id-certainty" :class="`badge-${person.identityCertainty}`">
                  {{ person.identityCertainty.toUpperCase() }}
                </span>
              </div>
            </div>
          </div>

          <div class="identity-status">
            <div class="status-item">
              <span class="status-label">Attendance</span>
              <span class="status-value" :class="`attendance-${detail.attendanceState || 'unknown'}`">
                {{ (detail.attendanceState || 'unknown').toUpperCase() }}
              </span>
            </div>
            <div class="status-item">
              <span class="status-label">Time</span>
              <span class="status-value mono">{{ formatTime(detail.attendanceTime) }}</span>
            </div>
          </div>
        </div>

        <!-- Identity Metrics -->
        <div class="identity-metrics">
          <div class="metric-item">
            <span class="metric-label">Identity</span>
            <span class="metric-value" :class="`certainty-${person.identityCertainty}`">
              {{ formatConfidence(person.identityConfidence) }}%
            </span>
          </div>
          <div class="metric-item">
            <span class="metric-label">Quality</span>
            <span class="metric-value mono">GOOD</span>
          </div>
        </div>

        <!-- Technical Metadata -->
        <div class="technical-metadata">
          <div class="metadata-item">
            <span class="metadata-label">Camera</span>
            <span class="metadata-value mono">{{ person.cameraId }}</span>
          </div>
          <div class="metadata-item">
            <span class="metadata-label">Track</span>
            <span class="metadata-value mono">{{ person.localTrackId }}</span>
          </div>
          <div class="metadata-item">
            <span class="metadata-label">Global Observation</span>
            <span class="metadata-value mono">{{ person.globalObservationId || 'N/A' }}</span>
          </div>
        </div>

        <!-- Divider -->
        <div class="panel-divider"></div>

        <!-- Appearance History -->
        <div class="appearance-section">
          <div class="section-header">
            <h4 class="section-title">Appearance History</h4>
            <span class="section-count">{{ detail.appearanceHistory?.length || 0 }} appearances</span>
          </div>

          <div class="appearance-list">
            <div
              v-for="(appearance, index) in detail.appearanceHistory"
              :key="`${appearance.cameraId}-${appearance.trackId}-${appearance.timestamp}`"
              class="appearance-item"
              @click="onReplayClick(appearance)"
            >
              <div class="appearance-time">
                <span class="time-text">{{ formatTime(appearance.timestamp) }}</span>
              </div>

              <div class="appearance-details">
                <div class="appearance-camera">
                  <span class="camera-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M12 2l-3.09 6.26L2 9.27l5 4.87L5.82 21 12 17.27 18.18 21l-1.18-6.86L22 9.27l-5-4.87L12 2z"/>
                    </svg>
                  </span>
                  <span class="camera-text mono">{{ appearance.cameraId }}</span>
                </div>
                <div class="appearance-track mono">Track {{ appearance.trackId }}</div>
              </div>

              <div class="appearance-actions">
                <button class="btn btn-secondary btn-sm" @click.stop="onReplayClick(appearance)">
                  <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                  </svg>
                  View Replay
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="panel-footer">
      <button class="btn btn-secondary" @click="onProvenanceClick">
        <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2z"/>
          <path d="M12 6v6l4 2"/>
        </svg>
        Provenance
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  person: {
    type: Object,
    default: null
  },
  detail: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close', 'replay', 'provenance'])

const loading = ref(false)

const onClose = () => {
  emit('close')
}

const onReplayClick = (appearance) => {
  emit('replay', appearance)
}

const onProvenanceClick = () => {
  emit('provenance', {
    person: props.person,
    detail: props.detail
  })
}

const formatConfidence = (confidence) => {
  if (confidence === undefined || confidence === null) return '0'
  return Math.round(confidence * 100)
}

const formatTime = (timestamp) => {
  if (!timestamp) return '--:--:--'

  const date = new Date(timestamp * 1000)
  return date.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

// Watch for person changes to simulate loading
watch(() => props.person, (newVal) => {
  if (newVal) {
    loading.value = true
    setTimeout(() => {
      loading.value = false
    }, 800)
  }
}, { immediate: true })
</script>

<style scoped>
.person-detail-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  border-radius: var(--radius-2xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  overflow: hidden;
  box-shadow: var(--shadow-md);
  transition: all var(--transition-normal);
}

.person-detail-panel:hover {
  border-color: var(--glass-border-hover);
  box-shadow: var(--shadow-lg);
}

.person-detail-panel.loading {
  opacity: 0.8;
  pointer-events: none;
}

/* Panel Header */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.panel-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.panel-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.panel-close:hover {
  background: var(--glass-bg-hover);
  color: var(--text-primary);
}

.close-icon {
  width: 20px;
  height: 20px;
}

/* Panel Body */
.panel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}

/* Loading State */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--space-4);
  color: var(--text-tertiary);
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--glass-border);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-text {
  font-size: var(--text-sm);
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--space-4);
  color: var(--text-tertiary);
  padding: var(--space-6);
  text-align: center;
}

.empty-state-icon {
  width: 48px;
  height: 48px;
  color: var(--text-muted);
  opacity: 0.5;
}

.empty-state-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  margin: 0 0 var(--space-2) 0;
}

.empty-state-message {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
  max-width: 240px;
}

/* Person Content */
.person-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Person Identity */
.person-identity {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.identity-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.identity-avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-full);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.identity-avatar svg {
  width: 24px;
  height: 24px;
  color: var(--text-tertiary);
}

.identity-info {
  flex: 1;
  min-width: 0;
}

.person-name {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0 0 var(--space-1) 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.person-id {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.id-text {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
}

.id-certainty {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.id-certainty.badge-known { background: var(--success-bg); color: var(--success); }
.id-certainty.badge-unknown { background: var(--glass-bg); color: var(--text-tertiary); }
.id-certainty.badge-ambiguous { background: var(--warning-bg); color: var(--warning); }
.id-certainty.badge-insufficient { background: var(--error-bg); color: var(--error); }

.identity-status {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.status-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.status-label {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.status-value {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}

.status-value.attendance-present { color: var(--attendance-present); }
.status-value.attendance-late { color: var(--attendance-late); }
.status-value.attendance-left { color: var(--attendance-left); }
.status-value.attendance-absent { color: var(--attendance-absent); }
.status-value.attendance-unknown { color: var(--text-tertiary); }

/* Identity Metrics */
.identity-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.metric-label {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-value {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}

.metric-value.certainty-known { color: var(--certainty-known); }
.metric-value.certainty-unknown { color: var(--certainty-unknown); }
.metric-value.certainty-ambiguous { color: var(--certainty-ambiguous); }
.metric-value.certainty-insufficient { color: var(--certainty-insufficient); }

/* Technical Metadata */
.technical-metadata {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: var(--space-3);
  font-size: var(--text-xs);
}

.metadata-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.metadata-label {
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metadata-value {
  color: var(--text-primary);
  font-weight: var(--font-medium);
}

/* Panel Divider */
.panel-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--glass-border), transparent);
  margin: var(--space-3) 0;
}

/* Appearance Section */
.appearance-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.section-count {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--glass-bg);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  border: 1px solid var(--glass-border);
}

.appearance-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.appearance-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-lg);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.appearance-item:hover {
  background: var(--glass-bg-hover);
  border-color: var(--glass-border-hover);
  transform: translateY(-1px);
}

.appearance-time {
  width: 60px;
  flex-shrink: 0;
}

.time-text {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-tertiary);
}

.appearance-details {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.appearance-camera {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.camera-icon {
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
}

.camera-text {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
}

.appearance-track {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.appearance-actions {
  display: flex;
  gap: var(--space-2);
}

/* Panel Footer */
.panel-footer {
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

/* Responsive */
@media (max-width: 1024px) {
  .identity-status {
    grid-template-columns: 1fr;
  }

  .identity-metrics {
    grid-template-columns: 1fr 1fr;
  }

  .technical-metadata {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 768px) {
  .panel-header {
    padding: var(--space-2) var(--space-3);
  }

  .panel-title {
    font-size: var(--text-md);
  }

  .panel-body {
    padding: var(--space-3);
  }

  .person-name {
    font-size: var(--text-lg);
  }

  .identity-status {
    grid-template-columns: 1fr;
  }

  .identity-metrics {
    grid-template-columns: 1fr;
  }

  .technical-metadata {
    grid-template-columns: 1fr;
  }

  .panel-footer {
    padding: var(--space-2) var(--space-3);
  }
}
</style>