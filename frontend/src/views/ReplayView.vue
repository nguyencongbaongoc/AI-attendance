<template>
  <div class="replay-view">
    <div class="replay-header">
      <h2 class="replay-title">Forensic Replay</h2>
      <p class="replay-subtitle">Browse and replay recorded video evidence from camera feeds</p>
    </div>

    <div class="replay-toolbar">
      <div class="toolbar-group">
        <label class="input-label" for="camera-filter">Camera</label>
        <select id="camera-filter" class="input-field" v-model="cameraFilter" @change="loadAppearances">
          <option value="">All Cameras</option>
          <option value="CAM1">CAM1</option>
          <option value="CAM2">CAM2</option>
        </select>
      </div>
      
      <div class="toolbar-group">
        <label class="input-label" for="date-filter">Date</label>
        <input
          id="date-filter"
          type="date"
          class="input-field"
          v-model="dateFilter"
          @change="loadAppearances"
        />
      </div>
      
      <div class="toolbar-group">
        <label class="input-label" for="person-filter">Person ID</label>
        <input
          id="person-filter"
          type="text"
          class="input-field"
          v-model="personFilter"
          @keyup.enter="loadAppearances"
          placeholder="Filter by person ID"
        />
      </div>
      
      <button class="btn btn-secondary" @click="loadAppearances">
        <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21.5 2v6h-6"/>
          <path d="M2.5 22v-6h6"/>
          <path d="M22 11.5a10 10 0 0 1-10 10 10 10 0 0 1-10-10 10 10 0 0 1 10-10"/>
        </svg>
        Refresh
      </button>
    </div>

    <div class="replay-content">
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span class="loading-text">Loading appearances...</span>
      </div>

      <div v-else-if="appearances.length === 0" class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <polygon points="5 3 19 12 5 21 5 3"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        <h3 class="empty-state-title">No Appearances Found</h3>
        <p class="empty-state-message">No video evidence matches the current filters</p>
      </div>

      <div v-else class="appearances-grid">
        <div
          v-for="appearance in appearances"
          :key="appearance.appearanceId"
          class="appearance-card"
          @click="openReplay(appearance)"
        >
          <div class="appearance-thumbnail">
            <div class="skeleton skeleton-camera"></div>
            <div class="thumbnail-overlay">
              <svg class="play-icon" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>
            </div>
            <div class="thumbnail-badge" :class="`badge-${appearance.identityCertainty}`">
              {{ appearance.identityCertainty.toUpperCase() }}
            </div>
          </div>
          
          <div class="appearance-info">
            <div class="appearance-header">
              <h4 class="appearance-person">{{ appearance.personId }}</h4>
              <span class="appearance-camera mono">{{ appearance.cameraId }}</span>
            </div>
            
            <div class="appearance-meta">
              <span class="appearance-time mono">{{ formatTime(appearance.startTimestamp) }}</span>
              <span class="appearance-duration mono">{{ formatDuration(appearance.durationSeconds) }}</span>
              <span class="appearance-track mono">Track {{ appearance.localTrackId }}</span>
            </div>
            
            <div class="appearance-provenance" v-if="appearance.globalObservationId">
              <svg class="provenance-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2z"/>
                <path d="M12 6v6l4 2"/>
              </svg>
              <span class="provenance-id mono">{{ appearance.globalObservationId }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="replay-pagination" v-if="totalPages > 1">
      <button class="btn btn-secondary btn-sm" @click="prevPage" :disabled="currentPage === 1">
        <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
        Previous
      </button>
      
      <div class="page-info">
        <span class="page-current mono">{{ currentPage }}</span>
        <span class="page-separator mono">/</span>
        <span class="page-total mono">{{ totalPages }}</span>
      </div>
      
      <button class="btn btn-secondary btn-sm" @click="nextPage" :disabled="currentPage === totalPages">
        Next
        <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()

const loading = ref(false)
const appearances = ref([])
const cameraFilter = ref('')
const dateFilter = ref('')
const personFilter = ref('')
const currentPage = ref(1)
const pageSize = 12
const totalPages = ref(1)

const openReplay = (appearance) => {
  store.openReplay(appearance)
}

const loadAppearances = async () => {
  loading.value = true
  currentPage.value = 1
  
  try {
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 600))
    
    // Mock appearances data
    const mockAppearances = getMockAppearances()
    appearances.value = mockAppearances
    totalPages.value = Math.ceil(mockAppearances.length / pageSize)
  } catch (error) {
    console.error('Failed to load appearances:', error)
    appearances.value = []
    totalPages.value = 1
  } finally {
    loading.value = false
  }
}

const prevPage = () => {
  if (currentPage.value > 1) {
    currentPage.value--
  }
}

const nextPage = () => {
  if (currentPage.value < totalPages.value) {
    currentPage.value++
  }
}

function getMockAppearances() {
  const baseTime = Date.now() / 1000 - 7200
  const allAppearances = [
    { appearanceId: 'APP-001', personId: 'HS001', identityCertainty: 'known', cameraId: 'CAM1', localTrackId: 'A17', globalObservationId: 'GO-001', startTimestamp: baseTime + 12, endTimestamp: baseTime + 112, durationSeconds: 100 },
    { appearanceId: 'APP-002', personId: 'HS001', identityCertainty: 'known', cameraId: 'CAM2', localTrackId: 'B04', globalObservationId: 'GO-001', startTimestamp: baseTime + 344, endTimestamp: baseTime + 444, durationSeconds: 100 },
    { appearanceId: 'APP-003', personId: 'HS001', identityCertainty: 'known', cameraId: 'CAM1', localTrackId: 'C02', globalObservationId: 'GO-001', startTimestamp: baseTime + 723, endTimestamp: baseTime + 823, durationSeconds: 100 },
    { appearanceId: 'APP-004', personId: 'HS004', identityCertainty: 'known', cameraId: 'CAM2', localTrackId: 'B04', globalObservationId: 'GO-002', startTimestamp: baseTime + 180, endTimestamp: baseTime + 280, durationSeconds: 100 },
    { appearanceId: 'APP-005', personId: 'HS004', identityCertainty: 'known', cameraId: 'CAM1', localTrackId: 'A19', globalObservationId: 'GO-002', startTimestamp: baseTime + 540, endTimestamp: baseTime + 640, durationSeconds: 100 },
    { appearanceId: 'APP-006', personId: 'HS017', identityCertainty: 'known', cameraId: 'CAM1', localTrackId: 'C02', globalObservationId: 'GO-003', startTimestamp: baseTime + 60, endTimestamp: baseTime + 160, durationSeconds: 100 },
    { appearanceId: 'APP-007', personId: 'HS008', identityCertainty: 'ambiguous', cameraId: 'CAM1', localTrackId: 'A19', globalObservationId: 'GO-004', startTimestamp: baseTime + 10, endTimestamp: baseTime + 110, durationSeconds: 100 },
    { appearanceId: 'APP-008', personId: 'HS023', identityCertainty: 'unknown', cameraId: 'CAM2', localTrackId: 'B07', globalObservationId: null, startTimestamp: baseTime + 450, endTimestamp: baseTime + 550, durationSeconds: 100 },
    { appearanceId: 'APP-009', personId: 'HS042', identityCertainty: 'insufficient', cameraId: 'CAM1', localTrackId: 'A25', globalObservationId: null, startTimestamp: baseTime + 600, endTimestamp: baseTime + 700, durationSeconds: 100 },
  ]
  
  let filtered = allAppearances
  
  if (cameraFilter.value) {
    filtered = filtered.filter(a => a.cameraId === cameraFilter.value)
  }
  
  if (personFilter.value) {
    filtered = filtered.filter(a => a.personId.toLowerCase().includes(personFilter.value.toLowerCase()))
  }
  
  // Date filter would be applied here in real implementation
  
  return filtered
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

const formatDuration = (seconds) => {
  if (!seconds) return '0s'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  if (mins > 0) {
    return `${mins}m ${secs}s`
  }
  return `${secs}s`
}

onMounted(() => {
  loadAppearances()
})

watch([cameraFilter, dateFilter, personFilter], () => {
  loadAppearances()
})
</script>

<style scoped>
.replay-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-2) 0;
}

.replay-header {
  text-align: center;
}

.replay-title {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  margin: 0 0 var(--space-2) 0;
}

.replay-subtitle {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
}

.replay-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
  padding: var(--space-4);
  border-radius: var(--radius-xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
}

.toolbar-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 140px;
}

.toolbar-group:last-child {
  margin-left: auto;
}

.replay-content {
  min-height: 400px;
}

.appearances-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.appearance-card {
  display: flex;
  flex-direction: column;
  border-radius: var(--radius-xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--transition-normal);
}

.appearance-card:hover {
  border-color: var(--accent-primary);
  box-shadow: var(--shadow-lg);
  transform: translateY(-4px);
}

.appearance-thumbnail {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--bg-tertiary);
  overflow: hidden;
}

.thumbnail-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(10, 14, 20, 0.6);
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.appearance-card:hover .thumbnail-overlay {
  opacity: 1;
}

.play-icon {
  width: 48px;
  height: 48px;
  color: var(--text-primary);
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.3));
}

.thumbnail-badge {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.thumbnail-badge.badge-known { background: var(--success-bg); color: var(--success); border: 1px solid var(--success-border); }
.thumbnail-badge.badge-unknown { background: var(--glass-bg); color: var(--text-tertiary); border: 1px solid var(--glass-border); }
.thumbnail-badge.badge-ambiguous { background: var(--warning-bg); color: var(--warning); border: 1px solid var(--warning-border); }
.thumbnail-badge.badge-insufficient { background: var(--error-bg); color: var(--error); border: 1px solid var(--error-border); }

.appearance-info {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.appearance-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.appearance-person {
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.appearance-camera {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  background: var(--bg-tertiary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
}

.appearance-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  flex-wrap: wrap;
}

.appearance-time {
  font-weight: var(--font-medium);
  color: var(--text-secondary);
}

.appearance-duration {
  background: var(--bg-tertiary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
}

.appearance-track {
  background: var(--bg-tertiary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
}

.appearance-provenance {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--accent-primary);
  padding: var(--space-1) var(--space-2);
  background: rgba(6, 182, 212, 0.1);
  border: 1px solid rgba(6, 182, 212, 0.2);
  border-radius: var(--radius-sm);
}

.provenance-icon {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.replay-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  padding: var(--space-4);
}

.page-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.page-separator {
  color: var(--text-tertiary);
}

/* Responsive */
@media (max-width: 768px) {
  .replay-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  
  .toolbar-group {
    min-width: 100%;
  }
  
  .toolbar-group:last-child {
    margin-left: 0;
  }
  
  .appearances-grid {
    grid-template-columns: 1fr;
  }
  
  .replay-title {
    font-size: var(--text-xl);
  }
}
</style>