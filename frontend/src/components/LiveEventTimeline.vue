<template>
  <div class="live-event-timeline">
    <div class="timeline-header">
      <h3 class="timeline-title">Live Events</h3>
      <div class="timeline-actions">
        <button class="icon-btn glass-btn" aria-label="Filter">
          <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>
          </svg>
        </button>
        <button class="icon-btn glass-btn" aria-label="Clear">
          <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 4H8l-7 8 7 8h13a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2z"/>
            <line x1="18" y1="9" x2="12" y2="15"/>
            <line x1="12" y1="9" x2="18" y2="15"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="timeline-body">
      <div v-if="events.length === 0" class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
        </svg>
        <h3 class="empty-state-title">No Events Yet</h3>
        <p class="empty-state-message">Live events will appear here as they occur</p>
      </div>

      <div v-else class="timeline-container">
        <div
          v-for="(event, index) in events"
          :key="event.id"
          class="timeline-event"
          :class="[`direction-${event.direction}`, `certainty-${event.certainty}`, { 'selected': isSelected(event) }]"
          @click="onEventClick(event)"
        >
          <div class="event-time">
            <span class="time-text">{{ formatTime(event.timestamp) }}</span>
          </div>

          <div class="event-connector" v-if="index < events.length - 1"></div>

          <div class="event-content">
            <div class="event-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path v-if="event.direction === 'in'" d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
                <path v-else-if="event.direction === 'out'" d="M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/>
                <path v-else d="M12 2v20"/>
              </svg>
            </div>

            <div class="event-details">
              <div class="event-direction" :class="`badge-${event.direction}`">
                {{ event.direction.toUpperCase() }}
              </div>
              <div class="event-person">
                <span class="person-id">{{ event.personId || 'UNKNOWN' }}</span>
                <span class="person-certainty" :class="`badge-${event.certainty}`">
                  {{ event.certainty.toUpperCase() }}
                </span>
              </div>
              <div class="event-meta">
                <span class="event-camera mono">{{ event.cameraId }}</span>
                <span class="event-track mono">Track {{ event.trackId }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  events: {
    type: Array,
    required: true,
    default: () => []
  }
})

const emit = defineEmits(['event-click'])

const onEventClick = (event) => {
  emit('event-click', event)
}

const isSelected = (event) => {
  // In real implementation, check if this event is selected
  return false
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
</script>

<style scoped>
.live-event-timeline {
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

.live-event-timeline:hover {
  border-color: var(--glass-border-hover);
  box-shadow: var(--shadow-lg);
}

/* Timeline Header */
.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.timeline-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.timeline-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* Timeline Body */
.timeline-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3) 0;
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
  text-align: center;
}

/* Timeline Container */
.timeline-container {
  position: relative;
  padding: var(--space-2) var(--space-4);
}

/* Timeline Event */
.timeline-event {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  cursor: pointer;
  transition: all var(--transition-fast);
  border-radius: var(--radius-md);
}

.timeline-event:hover {
  background: var(--glass-bg-hover);
}

.timeline-event.selected {
  background: var(--glass-bg-active);
  border-left: 2px solid var(--accent-primary);
}

.event-time {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  width: 60px;
  flex-shrink: 0;
}

.time-text {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-tertiary);
  text-align: center;
}

.event-connector {
  position: absolute;
  left: 30px;
  top: 32px;
  bottom: -8px;
  width: 1px;
  background: var(--glass-border);
  z-index: 1;
}

.event-content {
  flex: 1;
  min-width: 0;
  display: flex;
  gap: var(--space-3);
}

.event-icon {
  width: 20px;
  height: 20px;
  color: var(--text-tertiary);
  flex-shrink: 0;
  margin-top: 2px;
}

.event-details {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.event-direction {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  width: fit-content;
}

.event-direction.badge-in { background: var(--success-bg); color: var(--success); }
.event-direction.badge-out { background: var(--error-bg); color: var(--error); }
.event-direction.badge-crossing { background: var(--warning-bg); color: var(--warning); }

.event-person {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
}

.person-id {
  color: var(--text-primary);
}

.person-certainty {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.person-certainty.badge-known { background: var(--success-bg); color: var(--success); }
.person-certainty.badge-unknown { background: var(--glass-bg); color: var(--text-tertiary); }
.person-certainty.badge-ambiguous { background: var(--warning-bg); color: var(--warning); }
.person-certainty.badge-insufficient { background: var(--error-bg); color: var(--error); }

.event-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

/* Certainty Colors */
.timeline-event.certainty-known .event-icon { color: var(--certainty-known); }
.timeline-event.certainty-unknown .event-icon { color: var(--certainty-unknown); }
.timeline-event.certainty-ambiguous .event-icon { color: var(--certainty-ambiguous); }
.timeline-event.certainty-insufficient .event-icon { color: var(--certainty-insufficient); }

/* Direction Colors */
.timeline-event.direction-in .event-icon { color: var(--event-in); }
.timeline-event.direction-out .event-icon { color: var(--event-out); }

/* Responsive */
@media (max-width: 1024px) {
  .event-time {
    width: 50px;
  }

  .event-connector {
    left: 25px;
  }
}

@media (max-width: 768px) {
  .timeline-header {
    padding: var(--space-2) var(--space-3);
  }

  .timeline-title {
    font-size: var(--text-md);
  }

  .timeline-body {
    padding: var(--space-2) 0;
  }

  .timeline-container {
    padding: var(--space-2) var(--space-3);
  }

  .event-time {
    width: 45px;
  }

  .event-connector {
    left: 22px;
  }
}
</style>