<template>
  <div class="attendance-summary">
    <div class="summary-header">
      <h3 class="summary-title">Attendance Summary</h3>
      <div class="summary-actions">
        <button class="icon-btn glass-btn" aria-label="Refresh">
          <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.5 2v6h-6"/>
            <path d="M2.5 22v-6h6"/>
            <path d="M22 11.5a10 10 0 0 1-10 10 10 10 0 0 1-10-10 10 10 0 0 1 10-10"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-card" v-for="card in summaryCards" :key="card.key">
        <div class="card-value" :class="`attendance-${card.key}`">
          {{ summary[card.key] || 0 }}
        </div>
        <div class="card-label">{{ card.label }}</div>
        <div class="card-icon">
          <component :is="card.icon" />
        </div>
      </div>
    </div>

    <div class="summary-footer">
      <div class="total-attendance">
        <span class="total-label">Total</span>
        <span class="total-value">{{ summary.total || 0 }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { UsersIcon, UserCheckIcon, ClockIcon, UserMinusIcon, UserXIcon } from '@lucide/vue'

const props = defineProps({
  summary: {
    type: Object,
    required: true,
    default: () => ({
      present: 0,
      late: 0,
      left: 0,
      absent: 0,
      total: 0
    })
  }
})

const summaryCards = [
  { key: 'present', label: 'Present', icon: UserCheckIcon },
  { key: 'late', label: 'Late', icon: ClockIcon },
  { key: 'left', label: 'Left', icon: UserMinusIcon },
  { key: 'absent', label: 'Absent', icon: UserXIcon }
]

const formatNumber = (value) => {
  return value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}
</script>

<style scoped>
.attendance-summary {
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

.attendance-summary:hover {
  border-color: var(--glass-border-hover);
  box-shadow: var(--shadow-lg);
}

/* Summary Header */
.summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.summary-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.summary-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* Summary Grid */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
  padding: var(--space-4);
  flex: 1;
  min-height: 0;
}

.summary-card {
  position: relative;
  padding: var(--space-4);
  border-radius: var(--radius-xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  overflow: hidden;
  transition: all var(--transition-normal);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.summary-card:hover {
  border-color: var(--glass-border-hover);
  transform: translateY(-2px);
}

.card-value {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  line-height: 1;
}

.card-value.attendance-present { color: var(--attendance-present); }
.card-value.attendance-late { color: var(--attendance-late); }
.card-value.attendance-left { color: var(--attendance-left); }
.card-value.attendance-absent { color: var(--attendance-absent); }

.card-label {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.card-icon {
  position: absolute;
  top: var(--space-3);
  right: var(--space-3);
  width: 24px;
  height: 24px;
  color: var(--text-tertiary);
  opacity: 0.3;
}

/* Summary Footer */
.summary-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: var(--space-3) var(--space-4);
  border-top: 1px solid var(--glass-border);
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.total-attendance {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.total-label {
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.total-value {
  font-size: var(--text-xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
}

/* Responsive */
@media (max-width: 1024px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .summary-header {
    padding: var(--space-2) var(--space-3);
  }

  .summary-title {
    font-size: var(--text-md);
  }

  .card-value {
    font-size: var(--text-xl);
  }

  .summary-footer {
    padding: var(--space-2) var(--space-3);
  }

  .total-value {
    font-size: var(--text-lg);
  }
}
</style>