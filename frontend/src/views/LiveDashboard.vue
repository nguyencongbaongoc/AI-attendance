<template>
  <div class="live-dashboard">
    <!-- Camera Hero Area -->
    <section class="camera-hero" aria-label="Live Camera Feeds">
      <div class="camera-grid">
        <CameraCard 
          v-for="cameraId in ['CAM1', 'CAM2']" 
          :key="cameraId"
          :camera-id="cameraId"
          :feed="cameraFeeds[cameraId]"
          @person-click="onPersonClick"
        />
      </div>
    </section>
    
    <!-- Attendance Summary & Live Events -->
    <section class="dashboard-grid">
      <!-- Attendance Summary -->
      <div class="attendance-section">
        <AttendanceSummary :summary="attendanceSummary" />
      </div>
      
      <!-- Live Events Timeline -->
      <div class="events-section">
        <LiveEventTimeline :events="recentEvents" @event-click="onEventClick" />
      </div>
    </section>
    
    <!-- Selected Person Detail / Evidence / Provenance / System Health -->
    <section class="detail-section">
      <div class="detail-tabs" role="tablist">
        <button 
          role="tab" 
          :class="{ active: activeDetailTab === 'person' }"
          @click="activeDetailTab = 'person'"
          :aria-selected="activeDetailTab === 'person'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
            <circle cx="12" cy="7" r="4"/>
          </svg>
          Person
        </button>
        <button 
          role="tab" 
          :class="{ active: activeDetailTab === 'health' }"
          @click="activeDetailTab = 'health'"
          :aria-selected="activeDetailTab === 'health'"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/>
            <path d="M12 6v6l4 2"/>
          </svg>
          System Health
        </button>
      </div>
      
      <!-- Person Detail Tab -->
      <div class="detail-tab-content" v-show="activeDetailTab === 'person'">
        <PersonDetailPanel 
          v-if="selectedPerson || selectedPersonDetail"
          :person="selectedPerson"
          :detail="selectedPersonDetail"
          @close="clearSelectedPerson"
          @replay="openReplay"
          @provenance="openProvenance"
        />
        <div v-else class="empty-state glass">
          <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
            <path d="M8 14c0 2.5 2 4 4 4s4-1.5 4-4"/>
          </svg>
          <h3 class="empty-state-title">No Person Selected</h3>
          <p class="empty-state-message">
            Click on a person in the camera feed or event timeline to view detailed information, 
            appearance history, and video evidence.
          </p>
        </div>
      </div>
      
      <!-- System Health Tab -->
      <div class="detail-tab-content" v-show="activeDetailTab === 'health'">
        <SystemHealthPanel />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import CameraCard from '@/components/CameraCard.vue'
import AttendanceSummary from '@/components/AttendanceSummary.vue'
import LiveEventTimeline from '@/components/LiveEventTimeline.vue'
import PersonDetailPanel from '@/components/PersonDetailPanel.vue'
import SystemHealthPanel from '@/components/SystemHealthPanel.vue'

const store = useAppStore()

const cameraFeeds = computed(() => store.cameraFeeds)
const attendanceSummary = computed(() => store.attendanceSummary)
const recentEvents = computed(() => store.recentEvents)
const selectedPerson = computed(() => store.selectedPerson)
const selectedPersonDetail = computed(() => store.selectedPersonDetail)

const activeDetailTab = ref('person')

const onPersonClick = (person) => {
  store.selectPerson(person)
  activeDetailTab.value = 'person'
  // In real implementation, fetch person detail from API
  store.setSelectedPersonDetail({
    ...person,
    name: getPersonName(person.identityCandidate),
    appearanceHistory: getMockAppearanceHistory(person.identityCandidate)
  })
}

const onEventClick = (event) => {
  // Find person in camera feed
  const cameraFeed = store.cameraFeeds[event.cameraId]
  if (cameraFeed) {
    const person = cameraFeed.tracks.find(t => t.localTrackId === event.trackId)
    if (person) {
      onPersonClick(person)
    }
  }
}

const clearSelectedPerson = () => {
  store.clearSelectedPerson()
}

const openReplay = (appearance) => {
  store.openReplay(appearance)
}

const openProvenance = (data) => {
  store.openProvenance(data)
}

function getPersonName(candidate) {
  const names = {
    'HS001': 'Nguyễn Văn A',
    'HS004': 'Trần Thị B',
    'HS017': 'Lê Văn C',
    'HS008': 'Phạm Thị D'
  }
  return names[candidate] || 'Unknown Person'
}

function getMockAppearanceHistory(candidate) {
  const baseTime = Date.now() / 1000 - 3600
  const histories = {
    'HS001': [
      { timestamp: baseTime + 12, cameraId: 'CAM1', trackId: 'A17', globalObservationId: 'GO-001' },
      { timestamp: baseTime + 344, cameraId: 'CAM2', trackId: 'B04', globalObservationId: 'GO-001' },
      { timestamp: baseTime + 723, cameraId: 'CAM1', trackId: 'C02', globalObservationId: 'GO-001' }
    ],
    'HS004': [
      { timestamp: baseTime + 180, cameraId: 'CAM2', trackId: 'B04', globalObservationId: 'GO-002' },
      { timestamp: baseTime + 540, cameraId: 'CAM1', trackId: 'A19', globalObservationId: 'GO-002' }
    ],
    'HS017': [
      { timestamp: baseTime + 60, cameraId: 'CAM1', trackId: 'C02', globalObservationId: 'GO-003' }
    ],
    'HS008': [
      { timestamp: baseTime + 10, cameraId: 'CAM1', trackId: 'A19', globalObservationId: 'GO-004' }
    ]
  }
  return histories[candidate] || []
}

onMounted(() => {
  // Simulate live updates
  startLiveSimulation()
})

function startLiveSimulation() {
  // Simulate camera feed updates
  setInterval(() => {
    // Update camera feed timestamps
    Object.keys(store.cameraFeeds).forEach(cameraId => {
      store.updateCameraFeed(cameraId, {
        lastUpdate: Date.now()
      })
    })
  }, 5000)
  
  // Simulate new events occasionally
  setInterval(() => {
    if (Math.random() < 0.3) {
      const directions = ['in', 'out']
      const cameras = ['CAM1', 'CAM2']
      const certainties = ['known', 'ambiguous', 'unknown']
      const candidates = ['HS001', 'HS004', 'HS017', 'HS008', 'HS023', 'HS042']
      
      store.addLiveEvent({
        direction: directions[Math.floor(Math.random() * directions.length)],
        personId: candidates[Math.floor(Math.random() * candidates.length)],
        cameraId: cameras[Math.floor(Math.random() * cameras.length)],
        trackId: `T${Math.floor(Math.random() * 100).toString().padStart(2, '0')}`,
        certainty: certainties[Math.floor(Math.random() * certainties.length)],
        confidence: 0.5 + Math.random() * 0.5
      })
    }
  }, 15000)
}

<style scoped>
.live-dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  height: 100%;
  overflow: hidden;
}

/* Camera Hero Area - 40% visual weight */
.camera-hero {
  flex: 0 0 55%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.camera-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-4);
  height: 100%;
  min-height: 0;
}

@media (max-width: 1024px) {
  .camera-grid {
    grid-template-columns: 1fr;
  }
  
  .camera-hero {
    flex: 0 0 50%;
  }
}

@media (max-width: 768px) {
  .camera-hero {
    flex: 0 0 45%;
  }
}

/* Dashboard Grid - Attendance (25%) + Events (15%) */
.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
  flex: 0 0 30%;
  min-height: 0;
}

@media (max-width: 1024px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
    flex: 0 0 35%;
  }
}

@media (max-width: 768px) {
  .dashboard-grid {
    flex: 0 0 40%;
  }
}

.attendance-section {
  min-height: 0;
}

.events-section {
  min-height: 0;
}

/* Detail Section - 10% visual weight */
.detail-section {
  flex: 0 0 15%;
  min-height: 0;
  min-height: 200px;
}

@media (max-width: 1024px) {
  .detail-section {
    flex: 0 0 15%;
    min-height: 180px;
  }
}

@media (max-width: 768px) {
  .detail-section {
    flex: 0 0 15%;
    min-height: 160px;
  }
}

/* Empty State in Detail Section */
.detail-section .empty-state {
  height: 100%;
  border-radius: var(--radius-xl);
  border: 1px solid var(--glass-border);
}

.detail-section .empty-state-icon {
  width: 48px;
  height: 48px;
}

.detail-section .empty-state-title {
  font-size: var(--text-base);
}

.detail-section .empty-state-message {
  font-size: var(--text-xs);
  max-width: 240px;
}

/* Detail Tabs */
.detail-section {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.detail-tabs {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-1);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-3);
}

.detail-tabs button {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 500;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex: 1;
  justify-content: center;
}

.detail-tabs button:hover {
  background: var(--glass-border);
  color: var(--text-primary);
}

.detail-tabs button.active {
  background: var(--accent-primary);
  color: white;
}

.detail-tabs button svg {
  width: 16px;
  height: 16px;
}

.detail-tab-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.detail-tab-content > * {
  height: 100%;
}
