<template>
  <div class="camera-card" :class="[`status-${feed.status}`, { 'active': isActive }]">
    <!-- Camera Header -->
    <div class="camera-header">
      <div class="camera-title">
        <span class="camera-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2l-3.09 6.26L2 9.27l5 4.87L5.82 21 12 17.27 18.18 21l-1.18-6.86L22 9.27l-5-4.87L12 2z"/>
          </svg>
        </span>
        <span class="camera-label">{{ cameraId }}</span>
      </div>
      <div class="camera-status">
        <span class="status-dot" :class="feed.status"></span>
        <span class="status-text">{{ feed.status.toUpperCase() }}</span>
      </div>
    </div>
    
    <!-- Camera Feed -->
    <div class="camera-feed" @click="onFeedClick">
      <div v-if="feed.status === 'loading'" class="loading-state">
        <div class="loading-spinner"></div>
        <span class="loading-text">Loading camera feed...</span>
      </div>
      
      <div v-else-if="feed.status === 'offline'" class="error-state">
        <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 2l-3.09 6.26L2 9.27l5 4.87L5.82 21 12 17.27 18.18 21l-1.18-6.86L22 9.27l-5-4.87L12 2z"/>
          <line x1="12" y1="11" x2="12" y2="13"/>
          <line x1="12" y1="15" x2="12" y2="17"/>
        </svg>
        <h3 class="error-title">Camera Offline</h3>
        <p class="error-message">Connection to {{ cameraId }} unavailable</p>
        <button class="btn btn-secondary btn-sm" @click.stop="retryConnection">
          <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.5 2v6h-6"/>
            <path d="M2.5 22v-6h6"/>
            <path d="M22 11.5a10 10 0 0 1-10 10 10 10 0 0 1-10-10 10 10 0 0 1 10-10"/>
          </svg>
          Retry
        </button>
      </div>
      
      <div v-else-if="feed.status === 'degraded'" class="error-state">
        <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 2l-3.09 6.26L2 9.27l5 4.87L5.82 21 12 17.27 18.18 21l-1.18-6.86L22 9.27l-5-4.87L12 2z"/>
          <path d="M12 11.5v5"/>
          <path d="M12 17.5l.01.01"/>
        </svg>
        <h3 class="error-title">Degraded Performance</h3>
        <p class="error-message">Camera {{ cameraId }} is operating with reduced quality</p>
      </div>
      
      <div v-else class="feed-container">
        <!-- Video Feed -->
        <div class="video-container">
          <img
            v-if="feed.currentFrame"
            :src="feed.currentFrame"
            alt="Live camera feed"
            class="video-frame"
            @load="onFrameLoad"
          />
          <div v-else class="skeleton skeleton-camera"></div>
        </div>
        
        <!-- Person Tracks -->
        <div class="person-tracks">
          <div
            v-for="track in feed.tracks"
            :key="track.localTrackId"
            class="person-track"
            :class="[`certainty-${track.identityCertainty}`, { 'selected': isTrackSelected(track) }]"
            :style="getTrackStyle(track)"
            @click.stop="onPersonClick(track)"
          >
            <!-- AI Bounding Box -->
            <div class="ai-bounding-box">
              <div class="corner top-left"></div>
              <div class="corner top-right"></div>
              <div class="corner bottom-left"></div>
              <div class="corner bottom-right"></div>
            </div>
            
            <!-- Identity Label -->
            <div class="identity-label" :class="`certainty-${track.identityCertainty}`">
              <div class="identity-text">
                <span class="person-id">{{ track.identityCandidate || 'UNKNOWN' }}</span>
                <span class="certainty-badge" :class="`badge-${track.identityCertainty}`">
                  {{ track.identityCertainty.toUpperCase() }}
                </span>
              </div>
              <div class="confidence-text" v-if="track.identityConfidence">
                {{ formatConfidence(track.identityConfidence) }}%
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Camera Footer -->
    <div class="camera-footer">
      <div class="track-info" v-if="selectedTrack">
        <span class="track-id mono">Track {{ selectedTrack.localTrackId }}</span>
        <span class="track-certainty" :class="`certainty-${selectedTrack.identityCertainty}`">
          {{ selectedTrack.identityCertainty.toUpperCase() }}
        </span>
        <span class="track-confidence mono" v-if="selectedTrack.identityConfidence">
          {{ formatConfidence(selectedTrack.identityConfidence) }}%
        </span>
      </div>
      <div class="track-info" v-else>
        <span class="track-id mono">{{ feed.tracks.length }} active tracks</span>
      </div>
      <div class="last-update mono">
        {{ formatLastUpdate(feed.lastUpdate) }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useAppStore } from '@/stores/app'

const props = defineProps({
  cameraId: {
    type: String,
    required: true
  },
  feed: {
    type: Object,
    required: true
  }
})

const emit = defineEmits(['person-click'])

const store = useAppStore()
const selectedTrack = ref(null)

const isActive = computed(() => {
  return store.selectedPerson && store.selectedPerson.localTrackId === selectedTrack.value?.localTrackId
})

const onPersonClick = (track) => {
  selectedTrack.value = track
  emit('person-click', track)
}

const isTrackSelected = (track) => {
  return selectedTrack.value?.localTrackId === track.localTrackId
}

const getTrackStyle = (track) => {
  if (!track.bbox) return {}

  return {
    left: `${track.bbox.x}%`,
    top: `${track.bbox.y}%`,
    width: `${track.bbox.width}%`,
    height: `${track.bbox.height}%`
  }
}

const formatConfidence = (confidence) => {
  return Math.round(confidence * 100)
}

const formatLastUpdate = (timestamp) => {
  if (!timestamp) return 'Never updated'

  const now = Date.now()
  const diff = now - timestamp

  if (diff < 60000) return 'Updated just now'
  if (diff < 120000) return 'Updated 1 min ago'
  if (diff < 3600000) return `Updated ${Math.floor(diff / 60000)} mins ago`
  return `Updated ${Math.floor(diff / 3600000)} hours ago`
}

const retryConnection = () => {
  // In real implementation, this would reconnect to the camera
  store.setCameraStatus(props.cameraId, 'loading')
  setTimeout(() => {
    store.setCameraStatus(props.cameraId, 'live')
  }, 2000)
}

const onFeedClick = () => {
  selectedTrack.value = null
  store.clearSelectedPerson()
}

const onFrameLoad = () => {
  // Handle frame load if needed
}
</script>

<style scoped>
.camera-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  border-radius: var(--radius-2xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  overflow: hidden;
  transition: all var(--transition-normal);
  position: relative;
  box-shadow: var(--shadow-md);
}

.camera-card:hover {
  border-color: var(--glass-border-hover);
  box-shadow: var(--shadow-lg);
}

.camera-card.active {
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.2);
}

/* Camera Header */
.camera-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.camera-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.camera-icon {
  width: 18px;
  height: 18px;
  color: var(--accent-primary);
}

.camera-label {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.camera-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
  animation: pulse 2s infinite;
}

.status-dot.live {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
}

.status-dot.loading {
  background: var(--warning);
  box-shadow: 0 0 8px var(--warning);
  animation: pulse 1s infinite;
}

.status-dot.degraded {
  background: var(--warning);
  box-shadow: 0 0 8px var(--warning);
}

.status-dot.offline {
  background: var(--error);
  box-shadow: 0 0 8px var(--error);
  animation: none;
}

.status-text {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Camera Feed */
.camera-feed {
  flex: 1;
  min-height: 0;
  position: relative;
  background: var(--bg-tertiary);
  cursor: pointer;
  overflow: hidden;
}

.feed-container {
  position: relative;
  width: 100%;
  height: 100%;
}

.video-container {
  position: relative;
  width: 100%;
  height: 100%;
  background: #000;
}

.video-frame {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* Person Tracks */
.person-tracks {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.person-track {
  position: absolute;
  pointer-events: auto;
  cursor: pointer;
  transition: all var(--transition-fast);
  z-index: 10;
}

.person-track:hover {
  transform: scale(1.02);
  z-index: 20;
}

.person-track.selected {
  z-index: 30;
  box-shadow: 0 0 0 2px var(--accent-primary);
}

/* AI Bounding Box */
.ai-bounding-box {
  position: absolute;
  inset: 0;
  border: 2px solid var(--accent-quaternary);
  border-radius: var(--radius-sm);
  pointer-events: none;
}

.corner {
  position: absolute;
  width: 8px;
  height: 8px;
  border: 2px solid var(--accent-quaternary);
}

.top-left {
  top: -2px;
  left: -2px;
  border-right: none;
  border-bottom: none;
}

.top-right {
  top: -2px;
  right: -2px;
  border-left: none;
  border-bottom: none;
}

.bottom-left {
  bottom: -2px;
  left: -2px;
  border-right: none;
  border-top: none;
}

.bottom-right {
  bottom: -2px;
  right: -2px;
  border-left: none;
  border-top: none;
}

/* Identity Label */
.identity-label {
  position: absolute;
  bottom: -32px;
  left: 0;
  right: 0;
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: all var(--transition-fast);
  z-index: 15;
}

.person-track:hover .identity-label {
  transform: translateY(-100%);
}

.identity-text {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  margin-bottom: var(--space-1);
}

.person-id {
  font-weight: var(--font-semibold);
}

.confidence-text {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-weight: var(--font-medium);
}

/* Certainty Colors */
.person-track.certainty-known .ai-bounding-box,
.person-track.certainty-known .corner {
  border-color: var(--certainty-known);
}

.person-track.certainty-unknown .ai-bounding-box,
.person-track.certainty-unknown .corner {
  border-color: var(--certainty-unknown);
}

.person-track.certainty-ambiguous .ai-bounding-box,
.person-track.certainty-ambiguous .corner {
  border-color: var(--certainty-ambiguous);
}

.person-track.certainty-insufficient .ai-bounding-box,
.person-track.certainty-insufficient .corner {
  border-color: var(--certainty-insufficient);
}

.identity-label.certainty-known {
  border-color: var(--certainty-known);
}

.identity-label.certainty-unknown {
  border-color: var(--certainty-unknown);
}

.identity-label.certainty-ambiguous {
  border-color: var(--certainty-ambiguous);
}

.identity-label.certainty-insufficient {
  border-color: var(--certainty-insufficient);
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

/* Error State */
.error-state {
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

.error-icon {
  width: 48px;
  height: 48px;
  color: var(--text-muted);
  opacity: 0.6;
}

.error-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  margin: 0 0 var(--space-2) 0;
}

.error-message {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0 0 var(--space-4) 0;
  max-width: 240px;
}

/* Camera Footer */
.camera-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  font-size: var(--text-xs);
}

.track-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.track-id {
  color: var(--text-secondary);
}

.track-certainty {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  text-transform: uppercase;
}

.track-certainty.known { background: var(--success-bg); color: var(--success); }
.track-certainty.unknown { background: var(--glass-bg); color: var(--text-tertiary); }
.track-certainty.ambiguous { background: var(--warning-bg); color: var(--warning); }
.track-certainty.insufficient { background: var(--error-bg); color: var(--error); }

.track-confidence {
  color: var(--text-tertiary);
}

.last-update {
  color: var(--text-tertiary);
}

/* Responsive */
@media (max-width: 1024px) {
  .camera-card {
    min-height: 300px;
  }
}

@media (max-width: 768px) {
  .camera-header {
    padding: var(--space-2) var(--space-3);
  }

  .camera-label {
    font-size: var(--text-md);
  }

  .camera-footer {
    padding: var(--space-2) var(--space-3);
  }
}
</style>