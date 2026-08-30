<template>
  <div class="replay-modal">
    <div class="modal-backdrop" @click="onClose"></div>
    
    <div class="modal modal-full">
      <div class="modal-content">
        <!-- Modal Header -->
        <div class="modal-header">
          <div class="header-left">
            <h2 class="modal-title">Video Replay</h2>
            <div class="modal-subtitle" v-if="appearance">
              <span class="appearance-id mono">{{ appearance.appearanceId || appearance.id }}</span>
              <span class="appearance-person">{{ appearance.personId || 'Unknown' }}</span>
            </div>
          </div>
          
          <div class="header-right">
            <div class="playback-controls" v-if="videoUrl && !loading">
              <button class="icon-btn glass-btn" @click="togglePlay" aria-label="Play/Pause">
                <svg class="btn-icon" v-if="!playing" viewBox="0 0 24 24" fill="currentColor">
                  <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
                <svg class="btn-icon" v-else viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="4" width="4" height="16"/>
                  <rect x="14" y="4" width="4" height="16"/>
                </svg>
              </button>
              
              <div class="time-display">
                <span class="current-time mono">{{ formatTime(currentTime) }}</span>
                <span class="time-separator mono">/</span>
                <span class="duration mono">{{ formatTime(duration) }}</span>
              </div>
              
              <input 
                type="range" 
                class="progress-bar"
                :min="0"
                :max="duration"
                :value="currentTime"
                @input="onProgressChange"
                @change="onProgressCommit"
              />
              
              <button class="icon-btn glass-btn" @click="toggleMute" aria-label="Mute/Unmute">
                <svg class="btn-icon" v-if="!muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                  <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/>
                </svg>
                <svg class="btn-icon" v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                  <line x1="23" y1="9" x2="17" y2="15"/>
                  <line x1="17" y1="9" x2="23" y2="15"/>
                </svg>
              </button>
              
              <select class="speed-select" v-model="playbackRate" @change="onSpeedChange">
                <option value="0.25">0.25x</option>
                <option value="0.5">0.5x</option>
                <option value="1">1x</option>
                <option value="1.5">1.5x</option>
                <option value="2">2x</option>
              </select>
            </div>
            
            <button class="icon-btn glass-btn" @click="onClose" aria-label="Close">
              <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        </div>
        
        <!-- Modal Body -->
        <div class="modal-body replay-body">
          <div v-if="loading" class="loading-state">
            <div class="loading-spinner"></div>
            <span class="loading-text">Loading video...</span>
          </div>
          
          <div v-else-if="error" class="error-state">
            <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <h3 class="error-title">Unable to Load Video</h3>
            <p class="error-message">{{ error }}</p>
            <button class="btn btn-primary" @click="retryLoad">Retry</button>
          </div>
          
          <div v-else-if="videoUrl" class="video-wrapper">
            <video
              ref="videoRef"
              class="replay-video"
              :src="videoUrl"
              :playbackRate="playbackRate"
              :muted="muted"
              @loadedmetadata="onLoadedMetadata"
              @timeupdate="onTimeUpdate"
              @play="onPlay"
              @pause="onPause"
              @error="onVideoError"
              @waiting="onWaiting"
              @canplay="onCanPlay"
              playsinline
              webkit-playsinline
            ></video>
            
            <!-- Video Overlay -->
            <div class="video-overlay" v-show="showOverlay">
              <div class="overlay-content">
                <div class="overlay-title">Video Replay</div>
                <div class="overlay-subtitle" v-if="appearance">
                  {{ appearance.cameraId }} • Track {{ appearance.trackId }} • {{ formatTime(appearance.startTimestamp) }} - {{ formatTime(appearance.endTimestamp) }}
                </div>
                <div class="overlay-hint">Click to play/pause</div>
              </div>
            </div>
          </div>
          
          <div v-else class="empty-state">
            <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            <h3 class="empty-state-title">No Video Available</h3>
            <p class="empty-state-message">Select an appearance from the person detail panel to view replay</p>
          </div>
        </div>
        
        <!-- Modal Footer -->
        <div class="modal-footer">
          <div class="footer-left">
            <div class="provenance-info" v-if="appearance">
              <span class="info-label mono">Source:</span>
              <span class="info-value mono">{{ appearance.sourceVideoId }}</span>
              <span class="info-separator">•</span>
              <span class="info-label mono">Camera:</span>
              <span class="info-value mono">{{ appearance.cameraId }}</span>
              <span class="info-separator">•</span>
              <span class="info-label mono">Track:</span>
              <span class="info-value mono">{{ appearance.trackId }}</span>
            </div>
          </div>
          
          <div class="footer-right">
            <button class="btn btn-secondary" @click="downloadVideo" :disabled="!videoUrl || loading">
              <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              Download
            </button>
            <button class="btn btn-primary" @click="openProvenance" :disabled="!appearance">
              <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2z"/>
                <path d="M12 6v6l4 2"/>
              </svg>
              Provenance
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false
  },
  appearance: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['close', 'provenance'])

const videoRef = ref(null)
const videoUrl = ref(null)
const loading = ref(false)
const error = ref(null)
const playing = ref(false)
const muted = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const playbackRate = ref(1.0)
const showOverlay = ref(true)
const showControls = ref(true)

const onClose = () => {
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
  videoUrl.value = null
  loading.value = false
  error.value = null
  playing.value = false
  currentTime.value = 0
  duration.value = 0
  showOverlay.value = true
  emit('close')
}

const onLoadedMetadata = () => {
  if (videoRef.value) {
    duration.value = videoRef.value.duration
  }
}

const onTimeUpdate = () => {
  if (videoRef.value) {
    currentTime.value = videoRef.value.currentTime
  }
}

const onPlay = () => {
  playing.value = true
  showOverlay.value = false
}

const onPause = () => {
  playing.value = false
  showOverlay.value = true
}

const onVideoError = (e) => {
  error.value = 'Failed to load video. The source may be unavailable.'
  loading.value = false
  console.error('Video error:', e)
}

const onWaiting = () => {
  loading.value = true
}

const onCanPlay = () => {
  loading.value = false
}

const togglePlay = () => {
  if (videoRef.value) {
    if (playing.value) {
      videoRef.value.pause()
    } else {
      videoRef.value.play()
    }
  }
}

const toggleMute = () => {
  if (videoRef.value) {
    muted.value = !muted.value
    videoRef.value.muted = muted.value
  }
}

const onProgressChange = (e) => {
  currentTime.value = parseFloat(e.target.value)
}

const onProgressCommit = (e) => {
  if (videoRef.value) {
    videoRef.value.currentTime = parseFloat(e.target.value)
  }
}

const onSpeedChange = () => {
  if (videoRef.value) {
    videoRef.value.playbackRate = playbackRate.value
  }
}

const retryLoad = () => {
  loadVideo()
}

const loadVideo = async () => {
  if (!props.appearance) return
  
  loading.value = true
  error.value = null
  
  try {
    // In real implementation, this would call the backend API to get video segment
    // For now, we'll simulate with a placeholder
    await new Promise(resolve => setTimeout(resolve, 1500))
    
    // Mock video URL - in real implementation, this would come from the backend
    videoUrl.value = 'https://www.w3schools.com/html/mov_bbb.mp4'
    loading.value = false
  } catch (err) {
    error.value = 'Failed to load video segment'
    loading.value = false
  }
}

const downloadVideo = () => {
  if (videoUrl.value) {
    const a = document.createElement('a')
    a.href = videoUrl.value
    a.download = `replay-${props.appearance?.appearanceId || 'video'}.mp4`
    a.click()
  }
}

const openProvenance = () => {
  if (props.appearance) {
    emit('provenance', props.appearance)
  }
}

const formatTime = (seconds) => {
  if (!seconds || isNaN(seconds)) return '00:00:00'
  
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  
  return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

// Watch for appearance changes
watch(() => props.appearance, (newAppearance) => {
  if (newAppearance) {
    loadVideo()
  } else {
    onClose()
  }
}, { immediate: true })

// Keyboard shortcuts
const handleKeydown = (e) => {
  if (!props.isOpen) return
  
  if (e.code === 'Space' && videoRef.value) {
    e.preventDefault()
    togglePlay()
  }
  
  if (e.code === 'ArrowLeft' && videoRef.value) {
    e.preventDefault()
    videoRef.value.currentTime = Math.max(0, videoRef.value.currentTime - 5)
  }
  
  if (e.code === 'ArrowRight' && videoRef.value) {
    e.preventDefault()
    videoRef.value.currentTime = Math.min(duration.value, videoRef.value.currentTime + 5)
  }
  
  if (e.code === 'Escape') {
    onClose()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.src = ''
  }
})
</script>

<style scoped>
.replay-modal {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn var(--transition-normal);
}

.modal-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(10, 14, 20, 0.95);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  animation: fadeIn var(--transition-normal);
}

.modal-full {
  width: 95vw;
  height: 95vh;
  max-width: none;
  max-height: none;
}

.modal-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--glass-bg);
  backdrop-filter: blur(30px);
  -webkit-backdrop-filter: blur(30px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-2xl);
  overflow: hidden;
}

/* Modal Header */
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-5);
  border-bottom: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.modal-title {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.modal-subtitle {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.appearance-id {
  background: var(--bg-tertiary);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
}

.appearance-person {
  color: var(--accent-primary);
  font-weight: var(--font-medium);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* Playback Controls */
.playback-controls {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
}

.time-display {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  min-width: 120px;
}

.time-separator {
  color: var(--text-tertiary);
}

.progress-bar {
  width: 200px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--glass-border);
  border-radius: var(--radius-full);
  outline: none;
  cursor: pointer;
}

.progress-bar::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--accent-primary);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
}

.progress-bar::-moz-range-thumb {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--accent-primary);
  border: none;
  cursor: pointer;
}

.speed-select {
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  outline: none;
}

.speed-select:focus {
  border-color: var(--accent-primary);
}

/* Modal Body */
.replay-body {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: #000;
}

.video-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
}

.replay-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
}

.video-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(10, 14, 20, 0.8);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  cursor: pointer;
  transition: opacity var(--transition-fast);
  z-index: 10;
}

.overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  text-align: center;
  padding: var(--space-6);
  color: var(--text-primary);
}

.overlay-title {
  font-size: var(--text-2xl);
  font-weight: var(--font-semibold);
}

.overlay-subtitle {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  max-width: 400px;
}

.overlay-hint {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  animation: pulse 2s infinite;
}

/* Loading State */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  color: var(--text-tertiary);
}

.loading-spinner {
  width: 48px;
  height: 48px;
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
  gap: var(--space-4);
  padding: var(--space-8);
  text-align: center;
  max-width: 400px;
}

.error-icon {
  width: 56px;
  height: 56px;
  color: var(--error);
}

.error-title {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--error);
  margin: 0 0 var(--space-2) 0;
}

.error-message {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin: 0 0 var(--space-4) 0;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  color: var(--text-tertiary);
  padding: var(--space-8);
  text-align: center;
}

.empty-state-icon {
  width: 64px;
  height: 64px;
  color: var(--text-muted);
  opacity: 0.5;
}

.empty-state-title {
  font-size: var(--text-xl);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  margin: 0 0 var(--space-2) 0.
}

.empty-state-message {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
  max-width: 320px;
}

/* Modal Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-5);
  border-top: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  flex-shrink: 0;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.provenance-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.info-label {
  font-weight: var(--font-medium);
}

.info-value {
  color: var(--text-secondary);
}

.info-separator {
  color: var(--text-muted);
}

.footer-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* Responsive */
@media (max-width: 1024px) {
  .modal-full {
    width: 100vw;
    height: 100vh;
    border-radius: 0;
  }
  
  .progress-bar {
    width: 150px;
  }
}

@media (max-width: 768px) {
  .modal-header {
    padding: var(--space-2) var(--space-3);
  }
  
  .modal-title {
    font-size: var(--text-lg);
  }
  
  .modal-subtitle {
    display: none;
  }
  
  .playback-controls {
    gap: var(--space-1);
  }
  
  .time-display {
    min-width: 100px;
  }
  
  .progress-bar {
    width: 100px;
  }
  
  .speed-select {
    padding: var(--space-1);
  }
  
  .modal-footer {
    padding: var(--space-2) var(--space-3);
    flex-direction: column;
    gap: var(--space-3);
    align-items: stretch;
  }
  
  .footer-left {
    justify-content: center;
  }
  
  .provenance-info {
    flex-wrap: wrap;
    justify-content: center;
  }
  
  .footer-right {
    justify-content: center;
  }
}
</style>