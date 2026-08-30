<template>
  <div class="timetable-cell" :class="{ editing: isEditing }">
    <div v-if="!isEditing" class="cell-view" @click="$emit('edit', entry)">
      <div class="cell-subject">{{ entry.subject }}</div>
      <div class="cell-meta">
        <span class="cell-location" v-if="entry.location">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="meta-icon">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
            <circle cx="12" cy="10" r="3"/>
          </svg>
          {{ entry.location }}
        </span>
        <span class="cell-session-type" v-if="entry.session_type !== 'FULL_DAY'>
          {{ getSessionTypeLabel(entry.session_type) }}
        </span>
      </div>
      <div class="cell-actions">
        <button class="action-btn edit-btn" @click.stop="$emit('edit', entry)" aria-label="Sửa">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
        <button class="action-btn delete-btn" @click.stop="$emit('delete', entry)" aria-label="Xóa">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
          </svg>
        </button>
      </div>
    </div>

    <div v-else class="cell-edit">
      <div class="edit-field">
        <input 
          type="text" 
          class="edit-input" 
          v-model="editData.subject" 
          placeholder="Môn học"
          @keydown.enter="save"
          @keydown.escape="cancel"
        />
      </div>
      <div class="edit-actions">
        <button class="action-btn save-btn" @click="save" aria-label="Lưu">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <polyline points="7 3 7 8 15 8"/>
          </svg>
        </button>
        <button class="action-btn cancel-btn" @click="cancel" aria-label="Hủy">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  entry: {
    type: Object,
    required: true
  },
  isEditing: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['edit', 'delete', 'save', 'cancel'])

const editData = ref({ subject: '' })

const getSessionTypeLabel = (type) => {
  const labels = {
    'MORNING': 'Sáng',
    'AFTERNOON': 'Chiều',
    'FULL_DAY': 'Cả ngày'
  }
  return labels[type] || type
}

const save = () => {
  if (editData.value.subject.trim()) {
    emit('save', { ...props.entry, subject: editData.value.subject.trim() })
  }
}

const cancel = () => {
  editData.value.subject = props.entry.subject
  emit('cancel')
}

// Sync editData when entry changes
import { watch } from 'vue'
watch(() => props.entry, (newEntry) => {
  if (newEntry) {
    editData.value.subject = newEntry.subject
  }
}, { immediate: true })
</script>

<style scoped>
.timetable-cell {
  width: 100%;
  height: 100%;
  min-height: 60px;
  border-radius: var(--radius-md);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  transition: all var(--transition-fast);
  position: relative;
}

.timetable-cell:hover {
  border-color: var(--accent-primary);
  box-shadow: var(--shadow-sm);
}

.timetable-cell.editing {
  border-color: var(--accent-primary);
  background: rgba(6, 182, 212, 0.05);
}

.cell-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--space-2);
  gap: var(--space-1);
}

.cell-subject {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.cell-location {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.meta-icon {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
}

.cell-session-type {
  padding: var(--space-1) var(--space-2);
  background: var(--bg-tertiary);
  border-radius: var(--radius-sm);
  border: 1px solid var(--glass-border);
  font-weight: var(--font-medium);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}

.cell-actions {
  display: flex;
  gap: var(--space-1);
  margin-top: auto;
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.timetable-cell:hover .cell-actions {
  opacity: 1;
}

.action-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.action-btn:hover {
  color: var(--text-primary);
  background: var(--glass-bg-hover);
}

.action-btn svg {
  width: 14px;
  height: 14px;
}

.edit-btn:hover {
  color: var(--accent-primary);
  background: rgba(6, 182, 212, 0.1);
}

.delete-btn:hover {
  color: var(--error);
  background: var(--error-bg);
}

/* Edit Mode */
.cell-edit {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: var(--space-2);
  gap: var(--space-2);
}

.edit-field {
  flex: 1;
}

.edit-input {
  width: 100%;
  height: 100%;
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--accent-primary);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  outline: none;
}

.edit-input:focus {
  box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.2);
}

.edit-actions {
  display: flex;
  gap: var(--space-1);
  justify-content: center;
}

.save-btn:hover {
  color: var(--success);
  background: var(--success-bg);
}

.cancel-btn:hover {
  color: var(--error);
  background: var(--error-bg);
}

/* Responsive */
@media (max-width: 768px) {
  .cell-actions {
    opacity: 1;
  }
  
  .action-btn {
    width: 28px;
    height: 28px;
  }
}
</style>