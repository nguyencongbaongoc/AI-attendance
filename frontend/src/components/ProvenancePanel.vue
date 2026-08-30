<template>
  <div class="provenance-panel">
    <div class="panel-header">
      <h3 class="panel-title">Provenance</h3>
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
        <span class="loading-text">Loading provenance...</span>
      </div>

      <div v-else-if="!data" class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2z"/>
          <path d="M12 6v6l4 2"/>
        </svg>
        <h3 class="empty-state-title">No Provenance Data</h3>
        <p class="empty-state-message">Select an event or person to view provenance chain</p>
      </div>

      <div v-else class="provenance-content">
        <!-- Provenance Chain -->
        <div class="provenance-chain">
          <div
            v-for="(item, index) in provenanceItems"
            :key="item.id"
            class="provenance-item"
            :class="{ 'expanded': expandedItems.has(item.id) }"
            @click="toggleExpand(item.id)"
          >
            <div class="item-header">
              <div class="item-indicator">
                <span class="item-number">{{ index + 1 }}</span>
                <div class="item-line" v-if="index < provenanceItems.length - 1"></div>
              </div>
              
              <div class="item-content">
                <div class="item-title-row">
                  <h4 class="item-title">{{ item.title }}</h4>
                  <span class="item-type mono">{{ item.type }}</span>
                </div>
                
                <div class="item-summary" v-if="item.summary">
                  {{ item.summary }}
                </div>
              </div>
              
              <div class="item-expand">
                <svg class="expand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </div>
            </div>
            
            <div class="item-details" v-show="expandedItems.has(item.id)">
              <div class="detail-grid">
                <div class="detail-row" v-for="(value, key) in item.details" :key="key">
                  <span class="detail-key mono">{{ formatKey(key) }}</span>
                  <span class="detail-value mono">{{ formatValue(value) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  data: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close'])

const loading = ref(false)
const expandedItems = ref(new Set())

const onClose = () => {
  emit('close')
}

const toggleExpand = (id) => {
  if (expandedItems.value.has(id)) {
    expandedItems.value.delete(id)
  } else {
    expandedItems.value.add(id)
  }
}

const provenanceItems = computed(() => {
  if (!props.data) return []
  
  const items = []
  const d = props.data
  
  // Source Video
  if (d.sourceVideoId) {
    items.push({
      id: 'source-video',
      title: 'Source Video',
      type: 'VIDEO',
      summary: `${d.sourceVideoId} • ${d.cameraId || 'Unknown Camera'}`,
      details: {
        sourceVideoId: d.sourceVideoId,
        cameraId: d.cameraId,
        width: d.width,
        height: d.height,
        fps: d.fps,
        duration: d.durationSeconds ? `${d.durationSeconds}s` : undefined,
        codec: d.codec
      }
    })
  }
  
  // Frame
  if (d.sourceFrameIndex !== undefined) {
    items.push({
      id: 'frame',
      title: 'Frame',
      type: 'FRAME',
      summary: `Frame ${d.sourceFrameIndex} @ ${d.sourceTimestamp ? formatTimestamp(d.sourceTimestamp) : 'Unknown time'}`,
      details: {
        frameIndex: d.sourceFrameIndex,
        timestamp: d.sourceTimestamp ? formatTimestamp(d.sourceTimestamp) : undefined,
        timestampSource: d.timestampSource
      }
    })
  }
  
  // Track
  if (d.localTrackId) {
    items.push({
      id: 'track',
      title: 'Local Track',
      type: 'TRACK',
      summary: `${d.localTrackId} on ${d.cameraId}`,
      details: {
        localTrackId: d.localTrackId,
        cameraId: d.cameraId,
        detectionId: d.detectionId,
        detectionConfidence: d.detectionConfidence ? `${(d.detectionConfidence * 100).toFixed(1)}%` : undefined
      }
    })
  }
  
  // Global Observation
  if (d.globalObservationId) {
    items.push({
      id: 'global-observation',
      title: 'Global Observation',
      type: 'GLOBAL_OBS',
      summary: `${d.globalObservationId} • ${d.associationState || 'Unknown'}`,
      details: {
        globalObservationId: d.globalObservationId,
        associationState: d.associationState,
        cameraIds: d.cameraIds?.join(', '),
        localTrackIds: d.localTrackIds?.join(', '),
        temporalStart: d.temporalStart ? formatTimestamp(d.temporalStart) : undefined,
        temporalEnd: d.temporalEnd ? formatTimestamp(d.temporalEnd) : undefined,
        temporalSpan: d.temporalSpan ? `${d.temporalSpan}s` : undefined,
        primaryIdentityCandidate: d.primaryIdentityCandidate,
        identityConfidence: d.identityConfidence ? `${(d.identityConfidence * 100).toFixed(1)}%` : undefined
      }
    })
  }
  
  // Crossing Event
  if (d.crossingEventId) {
    items.push({
      id: 'crossing-event',
      title: 'Crossing Event',
      type: 'CROSSING',
      summary: `${d.crossingEventId} • ${d.crossingDirection || 'Unknown'}`,
      details: {
        crossingEventId: d.crossingEventId,
        crossingDirection: d.crossingDirection,
        geometryVersion: d.geometryVersion,
        geometryConfigHash: d.geometryConfigHash
      }
    })
  }
  
  // Raw IN/OUT Event
  if (d.rawEventId) {
    items.push({
      id: 'raw-event',
      title: 'Raw IN/OUT Event',
      type: 'RAW_EVENT',
      summary: `${d.rawEventId} • ${d.direction || 'Unknown'}`,
      details: {
        rawEventId: d.rawEventId,
        direction: d.direction,
        timestamp: d.timestamp ? formatTimestamp(d.timestamp) : undefined
      }
    })
  }
  
  // Resolved Transition
  if (d.resolutionId) {
    items.push({
      id: 'resolution',
      title: 'Resolved Transition',
      type: 'RESOLUTION',
      summary: `${d.resolutionId} • ${d.previousState || '?'} → ${d.newState || '?'}`,
      details: {
        resolutionId: d.resolutionId,
        previousState: d.previousState,
        newState: d.newState,
        resolverVersion: d.resolverVersion,
        resolverConfigHash: d.resolverConfigHash
      }
    })
  }
  
  // Attendance Decision
  if (d.attendanceDecisionId) {
    items.push({
      id: 'attendance-decision',
      title: 'Attendance Decision',
      type: 'ATTENDANCE',
      summary: `${d.attendanceDecisionId} • ${d.attendanceState || 'Unknown'}`,
      details: {
        attendanceDecisionId: d.attendanceDecisionId,
        attendanceState: d.attendanceState,
        decisionReason: d.decisionReason,
        timetableId: d.timetableId,
        sessionId: d.sessionId,
        day: d.day,
        attendancePolicyId: d.attendancePolicyId,
        attendancePolicyVersion: d.attendancePolicyVersion
      }
    })
  }
  
  return items
})

const formatTimestamp = (ts) => {
  if (!ts) return 'N/A'
  const date = new Date(ts * 1000)
  return date.toISOString().replace('T', ' ').substring(0, 19) + 'Z'
}

const formatKey = (key) => {
  return key
    .replace(/([A-Z])/g, ' $1')
    .replace(/^./, str => str.toUpperCase())
    .trim()
}

const formatValue = (value) => {
  if (value === undefined || value === null) return 'N/A'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

// Watch for data changes
watch(() => props.data, (newData) => {
  if (newData) {
    loading.value = true
    setTimeout(() => {
      loading.value = false
      // Auto-expand first item
      if (provenanceItems.value.length > 0) {
        expandedItems.value.add(provenanceItems.value[0].id)
      }
    }, 500)
  } else {
    expandedItems.value.clear()
  }
}, { immediate: true })
</script>

<style scoped>
.provenance-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 420px;
  max-width: 100vw;
  z-index: var(--z-modal);
  background: var(--glass-bg);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
  border-left: 1px solid var(--glass-border);
  box-shadow: var(--shadow-xl);
  display: flex;
  flex-direction: column;
  animation: slideInRight var(--transition-morph);
}

@keyframes slideInRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

/* Panel Header */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  flex-shrink: 0;
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
  animation: spin 1s linear infinite.
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

/* Provenance Content */
.provenance-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* Provenance Chain */
.provenance-chain {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.provenance-item {
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  background: var(--glass-bg);
  overflow: hidden;
  transition: all var(--transition-fast);
}

.provenance-item:first-child {
  border-top-left-radius: var(--radius-lg);
  border-top-right-radius: var(--radius-lg);
}

.provenance-item:last-child {
  border-bottom-left-radius: var(--radius-lg);
  border-bottom-right-radius: var(--radius-lg);
}

.provenance-item:hover {
  background: var(--glass-bg-hover);
}

.item-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  cursor: pointer;
}

.item-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  width: 24px;
}

.item-number {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--accent-primary);
  color: var(--text-inverse);
  font-size: var(--text-xs);
  font-weight: var(--font-bold);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
}

.item-line {
  width: 2px;
  height: 100%;
  min-height: 20px;
  background: var(--glass-border);
  position: relative;
  z-index: 0;
}

.item-content {
  flex: 1;
  min-width: 0;
}

.item-title-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
}

.item-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.item-type {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-tertiary);
  background: var(--bg-tertiary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
}

.item-summary {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-normal);
}

.item-expand {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  color: var(--text-tertiary);
  flex-shrink: 0;
  transition: transform var(--transition-fast);
}

.provenance-item.expanded .item-expand .expand-icon {
  transform: rotate(180deg);
}

.expand-icon {
  width: 16px;
  height: 16px;
  transition: transform var(--transition-fast);
}

/* Item Details */
.item-details {
  padding: 0 var(--space-3) var(--space-3);
  border-top: 1px solid var(--glass-border);
  background: var(--bg-secondary);
  animation: slideDown var(--transition-fast);
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}

.detail-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.detail-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--glass-border);
}

.detail-row:last-child {
  border-bottom: none;
}

.detail-key {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  min-width: 120px;
  flex-shrink: 0;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.detail-value {
  font-size: var(--text-xs);
  color: var(--text-primary);
  font-weight: var(--font-medium);
  word-break: break-all;
  flex: 1;
}

/* Responsive */
@media (max-width: 768px) {
  .provenance-panel {
    width: 100vw;
    border-left: none;
    border-top: 1px solid var(--glass-border);
    border-radius: var(--radius-2xl) var(--radius-2xl) 0 0;
    animation: slideUp var(--transition-morph);
  }
  
  @keyframes slideUp {
    from { transform: translateY(100%); }
    to { transform: translateY(0); }
  }
  
  .panel-header {
    padding: var(--space-2) var(--space-3);
  }
  
  .panel-title {
    font-size: var(--text-md);
  }
  
  .panel-body {
    padding: var(--space-3);
  }
  
  .item-header {
    padding: var(--space-2) var(--space-3);
  }
  
  .item-details {
    padding: 0 var(--space-3) var(--space-2);
  }
  
  .detail-row {
    flex-direction: column;
    gap: var(--space-1);
  }
  
  .detail-key {
    min-width: auto;
  }
}
</style>
