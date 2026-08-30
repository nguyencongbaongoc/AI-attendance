<template>
  <div class="timetable-management">
    <div class="page-header">
      <h2 class="page-title">Thời Khóa Biểu</h2>
      <p class="page-subtitle">Quản lý thời khóa biểu các lớp học</p>
    </div>

    <!-- Class Selector & Filters -->
    <div class="toolbar glass-panel">
      <div class="toolbar-group">
        <label class="input-label" for="class-filter">Lớp học</label>
        <select id="class-filter" class="input-field" v-model="selectedClass" @change="loadTimetable">
          <option value="">Tất cả các lớp</option>
          <option v-for="cls in classes" :key="cls" :value="cls">{{ cls }}</option>
        </select>
      </div>
      
      <div class="toolbar-group">
        <label class="input-label" for="day-filter">Thứ</label>
        <select id="day-filter" class="input-field" v-model="selectedDay" @change="loadTimetable">
          <option value="">Tất cả các thứ</option>
          <option value="0">Thứ 2</option>
          <option value="1">Thứ 3</option>
          <option value="2">Thứ 4</option>
          <option value="3">Thứ 5</option>
          <option value="4">Thứ 6</option>
          <option value="5">Thứ 7</option>
          <option value="6">Chủ Nhật</option>
        </select>
      </div>

      <div class="toolbar-group">
        <button class="btn btn-primary" @click="showCreateModal = true">
          <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          Thêm mới
        </button>
      </div>

      <div class="toolbar-group">
        <button class="btn btn-secondary" @click="importFromExcel">
          <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          Import Excel
        </button>
      </div>
    </div>

    <!-- Timetable Grid -->
    <div class="timetable-container glass-panel">
      <div v-if="loading" class="loading-state">
        <div class="loading-spinner"></div>
        <span class="loading-text">Đang tải thời khóa biểu...</span>
      </div>

      <div v-else-if="timetableEntries.length === 0" class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/>
          <line x1="3" y1="10" x2="21" y2="10"/>
        </svg>
        <h3 class="empty-state-title">Chưa có thời khóa biểu</h3>
        <p class="empty-state-message">Nhấn "Thêm mới" để tạo thời khóa biểu cho lớp học</p>
      </div>

      <div v-else class="timetable-grid">
        <!-- Header Row -->
        <div class="timetable-header">
          <div class="time-column header-cell">Tiết / Thứ</div>
          <div v-for="day in daysOfWeek" :key="day.value" class="day-column header-cell">
            <span class="day-name">{{ day.label }}</span>
            <span class="day-number">{{ day.value }}</span>
          </div>
        </div>

        <!-- Period Rows -->
        <div v-for="period in periods" :key="period" class="timetable-row">
          <div class="time-column period-cell">
            <span class="period-number">Tiết {{ period }}</span>
            <span class="period-time">{{ getPeriodTime(period) }}</span>
          </div>
          <div v-for="day in daysOfWeek" :key="day.value" class="day-column">
            <div class="cell-content">
              <TimetableCell
                v-for="entry in getEntriesForSlot(day.value, period)"
                :key="entry.entry_id"
                :entry="entry"
                :is-editing="editingEntry?.entry_id === entry.entry_id"
                @edit="startEdit"
                @delete="confirmDelete"
                @save="saveEntry"
                @cancel="cancelEdit"
              />
              <button 
                v-if="getEntriesForSlot(day.value, period).length === 0 && !isEditingAny"
                class="add-cell-btn"
                @click="createEntryForSlot(day.value, period)"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"/>
                  <line x1="5" y1="12" x2="19" y2="12"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Validation Errors Panel -->
    <div v-if="validationErrors.length > 0" class="validation-panel glass-panel error">
      <div class="validation-header">
        <svg class="validation-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span class="validation-title">{{ validationErrors.length }} lỗi xác thực</span>
      </div>
      <ul class="validation-list">
        <li v-for="error in validationErrors" :key="error.id" class="validation-item">
          <span class="validation-message">{{ error.message }}</span>
          <button class="validation-action" @click="focusEntry(error.entry_id)">Sửa</button>
        </li>
      </ul>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showCreateModal || editingEntry" class="modal-overlay" @click.self="closeModal">
      <div class="modal glass-panel">
        <div class="modal-header">
          <h3 class="modal-title">{{ editingEntry ? 'Sửa thời khóa biểu' : 'Thêm thời khóa biểu mới' }}</h3>
          <button class="modal-close" @click="closeModal" aria-label="Đóng">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <form class="modal-form" @submit.prevent="submitForm">
          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-class">Lớp học <span class="required">*</span></label>
              <select id="modal-class" class="input-field" v-model="formData.class_name" required>
                <option value="">Chọn lớp học</option>
                <option v-for="cls in classes" :key="cls" :value="cls">{{ cls }}</option>
              </select>
            </div>
            
            <div class="form-group">
              <label class="input-label" for="modal-day">Thứ <span class="required">*</span></label>
              <select id="modal-day" class="input-field" v-model="formData.day" required>
                <option value="">Chọn thứ</option>
                <option value="0">Thứ 2</option>
                <option value="1">Thứ 3</option>
                <option value="2">Thứ 4</option>
                <option value="3">Thứ 5</option>
                <option value="4">Thứ 6</option>
                <option value="5">Thứ 7</option>
                <option value="6">Chủ Nhật</option>
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-period">Tiết <span class="required">*</span></label>
              <select id="modal-period" class="input-field" v-model="formData.period" required>
                <option value="">Chọn tiết</option>
                <option v-for="p in periods" :key="p" :value="p">Tiết {{ p }} ({{ getPeriodTime(p) }})</option>
              </select>
            </div>

            <div class="form-group">
              <label class="input-label" for="modal-session-type">Loại buổi <span class="required">*</span></label>
              <select id="modal-session-type" class="input-field" v-model="formData.session_type" required>
                <option value="CLASSROOM">Lớp học (CLASSROOM)</option>
                <option value="BREAK">Nghỉ giải lao (BREAK)</option>
                <option value="OUTSIDE_LESSON">Buổi ngoài (OUTSIDE_LESSON)</option>
                <option value="LAB">Thí nghiệm (LAB)</option>
                <option value="OTHER">Khác (OTHER)</option>
                <!-- Legacy compatibility -->
                <option value="FULL_DAY">Cả ngày (FULL_DAY)</option>
                <option value="MORNING">Buổi sáng (MORNING)</option>
                <option value="AFTERNOON">Buổi chiều (AFTERNOON)</option>
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-subject">Môn học <span class="required">*</span></label>
              <input id="modal-subject" class="input-field" v-model="formData.subject" required placeholder="VD: Toán, Văn, GDTC..." />
            </div>

            <div class="form-group">
              <label class="input-label" for="modal-location">Địa điểm</label>
              <input id="modal-location" class="input-field" v-model="formData.location" placeholder="VD: Phòng 101, Sân thể dục..." />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-expected-location">Địa điểm mong đợi (cho buổi ngoài)</label>
              <input id="modal-expected-location" class="input-field" v-model="formData.expected_location" placeholder="VD: Sân thể dục, Phòng thí nghiệm..." />
            </div>

            <div class="form-group">
              <label class="input-label" for="modal-outside-allowed">Cho phép ra ngoài lớp</label>
              <div class="checkbox-wrapper">
                <input id="modal-outside-allowed" type="checkbox" v-model="formData.outside_allowed" />
                <span class="checkbox-label">Học sinh được phép ra khỏi lớp trong buổi này</span>
              </div>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-start-time">Giờ bắt đầu <span class="required">*</span></label>
              <input id="modal-start-time" type="time" class="input-field" v-model="formData.start_time" required />
            </div>

            <div class="form-group">
              <label class="input-label" for="modal-end-time">Giờ kết thúc <span class="required">*</span></label>
              <input id="modal-end-time" type="time" class="input-field" v-model="formData.end_time" required />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-entry-window-start">Cho phép vào sớm nhất (phút trước giờ)</label>
              <input id="modal-entry-window-start" type="number" class="input-field" v-model="formData.entry_window_start" min="0" max="60" />
            </div>

            <div class="form-group">
              <label class="input-label" for="modal-entry-window-end">Cho phép vào muộn nhất (phút sau giờ)</label>
              <input id="modal-entry-window-end" type="number" class="input-field" v-model="formData.entry_window_end" min="0" max="120" />
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="input-label" for="modal-late-tolerance">Dung trễ (phút)</label>
              <input id="modal-late-tolerance" type="number" class="input-field" v-model="formData.late_tolerance" min="0" max="60" />
            </div>

            <div class="form-group">
              <label class="input-label" for="modal-exit-window-start">Cho phép ra sớm nhất (phút trước giờ)</label>
              <input id="modal-exit-window-start" type="number" class="input-field" v-model="formData.exit_window_start" min="0" max="60" />
            </div>
          </div>

          <div class="form-group">
            <label class="input-label" for="modal-exit-window-end">Cho phép ra muộn nhất (phút sau giờ)</label>
            <input id="modal-exit-window-end" type="number" class="input-field" v-model="formData.exit_window_end" min="0" max="120" />
          </div>

          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" @click="closeModal">Hủy</button>
            <button type="submit" class="btn btn-primary" :disabled="submitting">
              <span v-if="submitting" class="btn-loading"></span>
              {{ editingEntry ? 'Cập nhật' : 'Tạo mới' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="deleteConfirmEntry" class="modal-overlay" @click.self="cancelDelete">
      <div class="modal modal-sm glass-panel">
        <div class="modal-header">
          <h3 class="modal-title">Xác nhận xóa</h3>
        </div>
        <p class="modal-message">Bạn có chắc chắn muốn xóa mục "{{ deleteConfirmEntry.subject }}" (Tiết {{ deleteConfirmEntry.period }}, Thứ {{ getDayLabel(deleteConfirmEntry.day) }})?</p>
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="cancelDelete">Hủy</button>
          <button class="btn btn-danger" @click="executeDelete">Xóa</button>
        </div>
      </div>
    </div>

    <!-- Excel Import Modal -->
    <div v-if="showImportModal" class="modal-overlay" @click.self="closeImportModal">
      <div class="modal glass-panel">
        <div class="modal-header">
          <h3 class="modal-title">Import thời khóa biểu từ Excel</h3>
          <button class="modal-close" @click="closeImportModal" aria-label="Đóng">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <div class="modal-body">
          <div class="import-dropzone" @dragover.prevent @drop.prevent="handleFileDrop" @click="triggerFileInput">
            <input type="file" ref="fileInput" accept=".xlsx,.xls" @change="handleFileSelect" style="display: none" />
            <svg class="dropzone-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            <p class="dropzone-text">Kéo thả file Excel vào đây hoặc nhấn để chọn</p>
            <p class="dropzone-hint">Hỗ trợ: .xlsx, .xls</p>
          </div>

          <div v-if="importPreview" class="import-preview">
            <h4>Xem trước dữ liệu ({{ importPreview.length }} dòng)</h4>
            <div class="preview-table-wrapper">
              <table class="preview-table">
                <thead>
                  <tr>
                    <th>Lớp</th>
                    <th>Thứ</th>
                    <th>Tiết</th>
                    <th>Môn học</th>
                    <th>Giờ bắt đầu</th>
                    <th>Giờ kết thúc</th>
                    <th>Địa điểm</th>
                    <th>Loại buổi</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, idx) in importPreview.slice(0, 10)" :key="idx">
                    <td>{{ row.class_name }}</td>
                    <td>{{ getDayLabel(row.day) }}</td>
                    <td>Tiết {{ row.period }}</td>
                    <td>{{ row.subject }}</td>
                    <td>{{ row.start_time }}</td>
                    <td>{{ row.end_time }}</td>
                    <td>{{ row.location || '-' }}</td>
                    <td>{{ row.session_type }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="importPreview.length > 10" class="preview-more">... và {{ importPreview.length - 10 }} dòng khác</p>
          </div>

          <div v-if="importErrors.length > 0" class="import-errors">
            <h4>Lỗi xác thực ({{ importErrors.length }})</h4>
            <ul>
              <li v-for="(err, idx) in importErrors" :key="idx" class="error-item">
                Dòng {{ err.row }}: {{ err.message }}
              </li>
            </ul>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn btn-secondary" @click="closeImportModal">Hủy</button>
          <button class="btn btn-primary" @click="confirmImport" :disabled="!importPreview || importErrors.length > 0 || importing">
            <span v-if="importing" class="btn-loading"></span>
            {{ importing ? 'Đang import...' : 'Xác nhận import' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useAppStore } from '@/stores/app'
import TimetableCell from '@/components/TimetableCell.vue'

const store = useAppStore()

// State
const loading = ref(false)
const timetableEntries = ref([])
const classes = ref([])
const selectedClass = ref('')
const selectedDay = ref('')
const validationErrors = ref([])

const showCreateModal = ref(false)
const editingEntry = ref(null)
const deleteConfirmEntry = ref(null)
const submitting = ref(false)

const showImportModal = ref(false)
const importPreview = ref(null)
const importErrors = ref([])
const importing = ref(false)

// Form data
const formData = ref({
  entry_id: '',
  class_name: '',
  day: '',
  period: '',
  session_type: 'FULL_DAY',
  subject: '',
  location: '',
  expected_location: '',
  outside_allowed: false,
  start_time: '',
  end_time: '',
  entry_window_start: 0,
  entry_window_end: 15,
  late_tolerance: 10,
  exit_window_start: 0,
  exit_window_end: 15,
})

// Constants
const daysOfWeek = [
  { value: 0, label: 'Thứ 2' },
  { value: 1, label: 'Thứ 3' },
  { value: 2, label: 'Thứ 4' },
  { value: 3, label: 'Thứ 5' },
  { value: 4, label: 'Thứ 6' },
  { value: 5, label: 'Thứ 7' },
  { value: 6, label: 'CN' },
]

const periods = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

const periodTimes = {
  1: '07:00-07:45',
  2: '07:50-08:35',
  3: '08:40-09:25',
  4: '09:35-10:20',
  5: '10:25-11:10',
  6: '11:15-12:00',
  7: '13:00-13:45',
  8: '13:50-14:35',
  9: '14:40-15:25',
  10: '15:30-16:15',
  11: '16:20-17:05',
  12: '17:10-17:55',
}

const isEditingAny = computed(() => !!editingEntry.value)

// Computed
const getPeriodTime = (period) => periodTimes[period] || '--:--'

const getDayLabel = (day) => {
  const d = daysOfWeek.find(d => d.value === day)
  return d ? d.label : day
}

const getEntriesForSlot = (day, period) => {
  return timetableEntries.value.filter(e => e.day == day && e.period == period)
}

// Methods
const loadTimetable = async () => {
  loading.value = true
  try {
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 500))
    
    // Mock data - in real implementation, fetch from API
    const mockEntries = getMockTimetableEntries()
    let filtered = mockEntries
    
    if (selectedClass.value) {
      filtered = filtered.filter(e => e.class_name === selectedClass.value)
    }
    if (selectedDay.value !== '') {
      filtered = filtered.filter(e => e.day == selectedDay.value)
    }
    
    timetableEntries.value = filtered
    classes.value = [...new Set(mockEntries.map(e => e.class_name))].sort()
  } catch (error) {
    console.error('Failed to load timetable:', error)
  } finally {
    loading.value = false
  }
}

const validateEntry = (entry) => {
  const errors = []
  
  if (!entry.class_name) errors.push({ field: 'class_name', message: 'Lớp học là bắt buộc' })
  if (entry.day === '' || entry.day === null) errors.push({ field: 'day', message: 'Thứ là bắt buộc' })
  if (!entry.period) errors.push({ field: 'period', message: 'Tiết là bắt buộc' })
  if (!entry.subject) errors.push({ field: 'subject', message: 'Môn học là bắt buộc' })
  if (!entry.start_time) errors.push({ field: 'start_time', message: 'Giờ bắt đầu là bắt buộc' })
  if (!entry.end_time) errors.push({ field: 'end_time', message: 'Giờ kết thúc là bắt buộc' })
  
  if (entry.start_time && entry.end_time && entry.start_time >= entry.end_time) {
    errors.push({ field: 'time', message: 'Giờ kết thúc phải sau giờ bắt đầu' })
  }
  
  // Check for conflicts
  const conflict = timetableEntries.value.find(e => 
    e.entry_id !== entry.entry_id &&
    e.class_name === entry.class_name &&
    e.day == entry.day &&
    e.period == entry.period
  )
  if (conflict) {
    errors.push({ field: 'conflict', message: `Trùng lịch với "${conflict.subject}" (${conflict.entry_id})` })
  }
  
  return errors
}

const startEdit = (entry) => {
  editingEntry.value = { ...entry }
  formData.value = { ...entry }
  showCreateModal.value = true
}

const cancelEdit = () => {
  editingEntry.value = null
  resetForm()
  showCreateModal.value = false
}

const createEntryForSlot = (day, period) => {
  editingEntry.value = null
  formData.value = {
    ...formData.value,
    day: day.toString(),
    period: period.toString(),
    start_time: getPeriodTime(period).split('-')[0],
    end_time: getPeriodTime(period).split('-')[1],
  }
  showCreateModal.value = true
}

const submitForm = async () => {
  const errors = validateEntry(formData.value)
  if (errors.length > 0) {
    validationErrors.value = errors.map(e => ({ id: Date.now() + Math.random(), ...e, entry_id: formData.value.entry_id }))
    return
  }
  
  submitting.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 500))
    
    if (editingEntry.value) {
      // Update existing
      const idx = timetableEntries.value.findIndex(e => e.entry_id === editingEntry.value.entry_id)
      if (idx !== -1) {
        timetableEntries.value[idx] = { ...formData.value }
      }
    } else {
      // Create new
      const newEntry = {
        ...formData.value,
        entry_id: `ENTRY-${Date.now()}`,
        person_id: '',
        person_name: '',
        session_id: `${formData.value.class_name}_${getDayLabel(formData.value.day).toUpperCase()}_T${formData.value.period}`,
      }
      timetableEntries.value.push(newEntry)
    }
    
    closeModal()
    await validateAll()
  } catch (error) {
    console.error('Failed to save entry:', error)
  } finally {
    submitting.value = false
  }
}

const confirmDelete = (entry) => {
  deleteConfirmEntry.value = entry
}

const cancelDelete = () => {
  deleteConfirmEntry.value = null
}

const executeDelete = async () => {
  if (!deleteConfirmEntry.value) return
  
  try {
    await new Promise(resolve => setTimeout(resolve, 300))
    timetableEntries.value = timetableEntries.value.filter(e => e.entry_id !== deleteConfirmEntry.value.entry_id)
    cancelDelete()
    await validateAll()
  } catch (error) {
    console.error('Failed to delete entry:', error)
  }
}

const validateAll = async () => {
  validationErrors.value = []
  for (const entry of timetableEntries.value) {
    const errors = validateEntry(entry)
    for (const err of errors) {
      validationErrors.value.push({ id: Date.now() + Math.random(), ...err, entry_id: entry.entry_id })
    }
  }
}

const focusEntry = (entryId) => {
  const entry = timetableEntries.value.find(e => e.entry_id === entryId)
  if (entry) {
    startEdit(entry)
  }
}

const closeModal = () => {
  showCreateModal.value = false
  editingEntry.value = null
  resetForm()
}

const resetForm = () => {
  formData.value = {
    entry_id: '',
    class_name: '',
    day: '',
    period: '',
    session_type: 'FULL_DAY',
    subject: '',
    location: '',
    expected_location: '',
    outside_allowed: false,
    start_time: '',
    end_time: '',
    entry_window_start: 0,
    entry_window_end: 15,
    late_tolerance: 10,
    exit_window_start: 0,
    exit_window_end: 15,
  }
}

const importFromExcel = () => {
  showImportModal.value = true
  importPreview.value = null
  importErrors.value = []
}

const closeImportModal = () => {
  showImportModal.value = false
  importPreview.value = null
  importErrors.value = []
}

const triggerFileInput = () => {
  document.querySelector('#fileInput')?.click()
}

const handleFileSelect = (event) => {
  const file = event.target.files[0]
  if (file) processExcelFile(file)
}

const handleFileDrop = (event) => {
  const file = event.dataTransfer.files[0]
  if (file) processExcelFile(file)
}

const processExcelFile = (file) => {
  // In real implementation, use xlsx library to parse
  // For now, simulate parsing
  importPreview.value = getMockImportData()
  importErrors.value = []
}

const confirmImport = async () => {
  if (!importPreview.value || importErrors.value.length > 0) return
  
  importing.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 1000))
    
    for (const row of importPreview.value) {
      const newEntry = {
        entry_id: `ENTRY-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
        class_name: row.class_name,
        day: row.day,
        period: row.period,
        session_type: row.session_type,
        subject: row.subject,
        location: row.location,
        start_time: row.start_time,
        end_time: row.end_time,
        entry_window_start: 0,
        entry_window_end: 15,
        late_tolerance: 10,
        exit_window_start: 0,
        exit_window_end: 15,
        person_id: '',
        person_name: '',
        session_id: `${row.class_name}_${getDayLabel(row.day).toUpperCase()}_T${row.period}`,
      }
      timetableEntries.value.push(newEntry)
    }
    
    closeImportModal()
    await validateAll()
  } catch (error) {
    console.error('Import failed:', error)
  } finally {
    importing.value = false
  }
}

function getMockTimetableEntries() {
  return [
    { entry_id: 'ENTRY-001', class_name: '12A1', day: 0, period: 1, session_type: 'FULL_DAY', subject: 'Toán', location: 'Phòng 101', start_time: '07:00', end_time: '07:45', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A1_THU2_T1' },
    { entry_id: 'ENTRY-002', class_name: '12A1', day: 0, period: 2, session_type: 'FULL_DAY', subject: 'Văn', location: 'Phòng 101', start_time: '07:50', end_time: '08:35', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A1_THU2_T2' },
    { entry_id: 'ENTRY-003', class_name: '12A1', day: 0, period: 3, session_type: 'FULL_DAY', subject: 'Anh', location: 'Phòng 102', start_time: '08:40', end_time: '09:25', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A1_THU2_T3' },
    { entry_id: 'ENTRY-004', class_name: '12A1', day: 0, period: 4, session_type: 'FULL_DAY', subject: 'GDTC', location: 'Sân thể dục', start_time: '09:35', end_time: '10:20', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A1_THU2_T4' },
    { entry_id: 'ENTRY-005', class_name: '12A1', day: 1, period: 1, session_type: 'FULL_DAY', subject: 'Lý', location: 'Phòng Lab 1', start_time: '07:00', end_time: '07:45', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A1_THU3_T1' },
    { entry_id: 'ENTRY-006', class_name: '12A1', day: 1, period: 2, session_type: 'FULL_DAY', subject: 'Hóa', location: 'Phòng Lab 2', start_time: '07:50', end_time: '08:35', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A1_THU3_T2' },
    { entry_id: 'ENTRY-007', class_name: '12A2', day: 0, period: 1, session_type: 'FULL_DAY', subject: 'Toán', location: 'Phòng 201', start_time: '07:00', end_time: '07:45', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A2_THU2_T1' },
    { entry_id: 'ENTRY-008', class_name: '12A2', day: 0, period: 2, session_type: 'FULL_DAY', subject: 'Văn', location: 'Phòng 201', start_time: '07:50', end_time: '08:35', entry_window_start: 0, entry_window_end: 15, late_tolerance: 10, exit_window_start: 0, exit_window_end: 15, person_id: '', person_name: '', session_id: '12A2_THU2_T2' },
  ]
}

function getMockImportData() {
  return [
    { class_name: '12A1', day: 2, period: 1, session_type: 'FULL_DAY', subject: 'Sinh', location: 'Phòng Lab 3', start_time: '07:00', end_time: '07:45' },
    { class_name: '12A1', day: 2, period: 2, session_type: 'FULL_DAY', subject: 'Sử', location: 'Phòng 103', start_time: '07:50', end_time: '08:35' },
    { class_name: '12A1', day: 2, period: 3, session_type: 'FULL_DAY', subject: 'Địa', location: 'Phòng 103', start_time: '08:40', end_time: '09:25' },
    { class_name: '12A1', day: 3, period: 1, session_type: 'FULL_DAY', subject: 'Tin', location: 'Phòng máy 1', start_time: '07:00', end_time: '07:45' },
    { class_name: '12A1', day: 3, period: 2, session_type: 'FULL_DAY', subject: 'Công nghệ', location: 'Phòng thực hành', start_time: '07:50', end_time: '08:35' },
  ]
}

onMounted(() => {
  loadTimetable()
})

watch([selectedClass, selectedDay], () => {
  loadTimetable()
})
</script>

<style scoped>
.timetable-management {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.page-header {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.page-title {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
}

/* Toolbar */
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-4);
  padding: var(--space-4);
  border-radius: var(--radius-xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
}

.toolbar-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 180px;
}

.toolbar-group:last-child {
  margin-left: auto;
}

.input-label {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.input-field {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  border: 1px solid var(--glass-border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: var(--text-sm);
  transition: all var(--transition-fast);
}

.input-field:focus {
  outline: none;
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 3px rgba(6, 182, 212, 0.2);
}

.required {
  color: var(--error);
  margin-left: 2px;
}

/* Timetable Container */
.timetable-container {
  border-radius: var(--radius-xl);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg);
  overflow: hidden;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12);
  gap: var(--space-4);
  color: var(--text-tertiary);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--glass-border);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-state-icon {
  width: 64px;
  height: 64px;
  color: var(--text-tertiary);
}

.empty-state-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  margin: 0;
}

.empty-state-message {
  font-size: var(--text-sm);
  margin: 0;
  text-align: center;
  max-width: 300px;
}

/* Timetable Grid */
.timetable-grid {
  overflow-x: auto;
}

.timetable-header {
  display: grid;
  grid-template-columns: 140px repeat(7, 1fr);
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-secondary);
  border-bottom: 2px solid var(--glass-border);
}

.timetable-row {
  display: grid;
  grid-template-columns: 140px repeat(7, 1fr);
  border-bottom: 1px solid var(--glass-border);
  transition: background var(--transition-fast);
}

.timetable-row:hover {
  background: var(--glass-bg-hover);
}

.header-cell,
.period-cell,
.day-column {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
}

.header-cell {
  font-size: var(--text-xs);
  font-weight: var(--font-bold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.day-name {
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.day-number {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.period-cell {
  background: var(--bg-secondary);
  border-right: 1px solid var(--glass-border);
  font-size: var(--text-sm);
}

.period-number {
  font-weight: var(--font-semibold);
  color: var(--text-primary);
}

.period-time {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
}

.day-column {
  min-height: 80px;
  position: relative;
}

.cell-content {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-1);
}

.add-cell-btn {
  width: 100%;
  height: 100%;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed var(--glass-border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.add-cell-btn:hover {
  border-color: var(--accent-primary);
  color: var(--accent-primary);
  background: rgba(6, 182, 212, 0.05);
}

.add-cell-btn svg {
  width: 24px;
  height: 24px;
}

/* Validation Panel */
.validation-panel {
  border-radius: var(--radius-xl);
  border: 1px solid var(--glass-border);
  background: var(--glass-bg);
  padding: var(--space-4);
}

.validation-panel.error {
  border-color: var(--error-border);
  background: var(--error-bg);
}

.validation-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.validation-icon {
  width: 20px;
  height: 20px;
  color: var(--error);
}

.validation-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--error);
}

.validation-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.validation-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
}

.validation-message {
  color: var(--text-primary);
  flex: 1;
}

.validation-action {
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--font-medium);
  color: var(--accent-primary);
  background: transparent;
  border: 1px solid var(--accent-primary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.validation-action:hover {
  background: var(--accent-primary);
  color: white;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  background: rgba(10, 14, 20, 0.8);
  backdrop-filter: blur(4px);
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal {
  width: 100%;
  max-width: 600px;
  max-height: 90vh;
  overflow-y: auto;
  border-radius: var(--radius-xl);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-xl);
  animation: slideUp 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.modal-sm {
  max-width: 400px;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--glass-border);
}

.modal-title {
  font-size: var(--text-lg);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0;
}

.modal-close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.modal-close:hover {
  color: var(--text-primary);
  background: var(--glass-bg-hover);
}

.modal-close svg {
  width: 20px;
  height: 20px;
}

.modal-form {
  padding: var(--space-6);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-group:last-child {
  margin-bottom: 0;
}

.modal-body {
  padding: var(--space-6);
}

.modal-message {
  padding: var(--space-4) var(--space-6);
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  line-height: 1.5;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--glass-border);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
  border: none;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  color: white;
  background: var(--accent-primary);
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-primary-hover);
}

.btn-secondary {
  color: var(--text-secondary);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
}

.btn-secondary:hover:not(:disabled) {
  color: var(--text-primary);
  background: var(--glass-bg-hover);
}

.btn-danger {
  color: white;
  background: var(--error);
}

.btn-danger:hover:not(:disabled) {
  background: var(--error-hover);
}

.btn-icon {
  width: 16px;
  height: 16px;
}

.btn-loading {
  width: 16px;
  height: 16px;
  border: 2px solid transparent;
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* Import Modal */
.import-dropzone {
  border: 2px dashed var(--glass-border);
  border-radius: var(--radius-xl);
  padding: var(--space-8);
  text-align: center;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.import-dropzone:hover {
  border-color: var(--accent-primary);
  background: rgba(6, 182, 212, 0.05);
}

.dropzone-icon {
  width: 48px;
  height: 48px;
  color: var(--text-tertiary);
  margin-bottom: var(--space-3);
}

.dropzone-text {
  font-size: var(--text-md);
  font-weight: var(--font-medium);
  color: var(--text-primary);
  margin: 0 0 var(--space-1) 0;
}

.dropzone-hint {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
}

.import-preview {
  margin-top: var(--space-6);
}

.import-preview h4 {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  margin: 0 0 var(--space-3) 0;
}

.preview-table-wrapper {
  overflow-x: auto;
  border-radius: var(--radius-md);
  border: 1px solid var(--glass-border);
}

.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-xs);
}

.preview-table th,
.preview-table td {
  padding: var(--space-2) var(--space-3);
  text-align: left;
  border-bottom: 1px solid var(--glass-border);
}

.preview-table th {
  background: var(--bg-secondary);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.preview-table td {
  color: var(--text-primary);
}

.preview-table tr:last-child td {
  border-bottom: none;
}

.preview-more {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  margin: var(--space-2) 0 0 0;
  text-align: center;
}

.import-errors {
  margin-top: var(--space-6);
  padding: var(--space-4);
  background: var(--error-bg);
  border: 1px solid var(--error-border);
  border-radius: var(--radius-md);
}

.import-errors h4 {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--error);
  margin: 0 0 var(--space-2) 0;
}

.import-errors ul {
  margin: 0;
  padding-left: var(--space-4);
}

.error-item {
  font-size: var(--text-xs);
  color: var(--error);
  margin-bottom: var(--space-1);
}

/* Checkbox wrapper */
.checkbox-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  cursor: pointer;
}

.checkbox-wrapper input[type="checkbox"] {
  width: 18px;
  height: 18px;
  accent-color: var(--accent-primary);
  cursor: pointer;
}

.checkbox-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  user-select: none;
}

/* Responsive */
@media (max-width: 1024px) {
  .timetable-header,
  .timetable-row {
    grid-template-columns: 120px repeat(7, minmax(120px, 1fr));
  }
  
  .form-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  
  .toolbar-group {
    min-width: 100%;
  }
  
  .toolbar-group:last-child {
    margin-left: 0;
  }
  
  .modal {
    margin: var(--space-2);
    max-height: calc(100vh - var(--space-4));
  }
}
</style>