<template>
  <div class="search-view">
    <div class="search-header">
      <h2 class="search-title">Person Search</h2>
      <p class="search-subtitle">Search for a person by ID to view their attendance history and video evidence</p>
    </div>

    <div class="search-form">
      <div class="input-wrapper">
        <label class="input-label" for="person-search">Person ID</label>
        <input
          id="person-search"
          type="text"
          class="input-field"
          v-model="searchQuery"
          @keyup.enter="performSearch"
          placeholder="Enter person ID (e.g., HS001)"
          :disabled="searchLoading"
        />
        <div class="input-suffix">
          <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
        </div>
      </div>
      
      <button 
        class="btn btn-primary" 
        @click="performSearch"
        :disabled="searchLoading || !searchQuery.trim()"
      >
        <span v-if="searchLoading" class="btn-loading"></span>
        <svg v-else class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
        </svg>
        <span>{{ searchLoading ? 'Searching...' : 'Search' }}</span>
      </button>
    </div>

    <div class="search-results" v-if="searchResults.length > 0 || searchLoading">
      <div v-if="searchLoading" class="loading-state">
        <div class="loading-spinner"></div>
        <span class="loading-text">Searching...</span>
      </div>

      <div v-else-if="searchResults.length === 0" class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        <h3 class="empty-state-title">No Results Found</h3>
        <p class="empty-state-message">No person found with ID "{{ searchQuery }}"</p>
      </div>

      <div v-else class="results-list">
        <div
          v-for="result in searchResults"
          :key="result.personId"
          class="result-card"
          @click="selectResult(result)"
        >
          <div class="result-avatar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
              <circle cx="12" cy="7" r="4"/>
            </svg>
          </div>
          
          <div class="result-info">
            <h4 class="result-name">{{ result.name || 'Unknown Person' }}</h4>
            <div class="result-meta">
              <span class="result-id mono">{{ result.personId }}</span>
              <span class="result-certainty" :class="`badge-${result.identityCertainty}`">
                {{ result.identityCertainty.toUpperCase() }}
              </span>
              <span class="result-appearances mono">{{ result.appearances?.length || 0 }} appearances</span>
            </div>
          </div>
          
          <div class="result-action">
            <svg class="chevron-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </div>
        </div>
      </div>
    </div>

    <div class="recent-searches" v-if="!searchLoading && searchResults.length === 0 && !searchQuery">
      <h3 class="section-title">Recent Searches</h3>
      <div class="recent-list" v-if="recentSearches.length > 0">
        <button
          v-for="recent in recentSearches"
          :key="recent"
          class="recent-item"
          @click="searchQuery = recent; performSearch()"
        >
          <svg class="recent-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/>
            <path d="M21 21l-4.35-4.35"/>
          </svg>
          <span class="recent-text mono">{{ recent }}</span>
        </button>
      </div>
      <div v-else class="empty-state">
        <p class="empty-state-message">No recent searches</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()

const searchQuery = ref('')
const searchLoading = ref(false)
const searchResults = ref([])
const recentSearches = ref([])

const performSearch = async () => {
  if (!searchQuery.value.trim()) return
  
  searchLoading.value = true
  store.setSearchLoading(true)
  store.setSearchQuery(searchQuery.value)
  
  try {
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 800))
    
    // Mock search results
    const mockResults = getMockSearchResults(searchQuery.value)
    searchResults.value = mockResults
    store.setSearchResults(mockResults)
    
    // Add to recent searches
    if (!recentSearches.value.includes(searchQuery.value)) {
      recentSearches.value.unshift(searchQuery.value)
      if (recentSearches.value.length > 5) {
        recentSearches.value.pop()
      }
    }
  } catch (error) {
    console.error('Search failed:', error)
    searchResults.value = []
    store.setSearchResults([])
  } finally {
    searchLoading.value = false
    store.setSearchLoading(false)
  }
}

const selectResult = (result) => {
  // In real implementation, navigate to person detail or open panel
  console.log('Select result:', result)
}

function getMockSearchResults(query) {
  const mockData = {
    'HS001': { personId: 'HS001', name: 'Nguyễn Văn A', identityCertainty: 'known', appearances: [{}, {}, {}] },
    'HS004': { personId: 'HS004', name: 'Trần Thị B', identityCertainty: 'known', appearances: [{}, {}] },
    'HS017': { personId: 'HS017', name: 'Lê Văn C', identityCertainty: 'known', appearances: [{}] },
    'HS008': { personId: 'HS008', name: 'Phạm Thị D', identityCertainty: 'ambiguous', appearances: [{}] },
    'HS023': { personId: 'HS023', name: 'Hoàng Văn E', identityCertainty: 'unknown', appearances: [{}] },
    'HS042': { personId: 'HS042', name: 'Vũ Thị F', identityCertainty: 'insufficient', appearances: [{}] }
  }
  
  const exact = mockData[query.toUpperCase()]
  if (exact) return [exact]
  
  // Fuzzy search
  return Object.values(mockData).filter(p => 
    p.personId.toLowerCase().includes(query.toLowerCase()) ||
    p.name.toLowerCase().includes(query.toLowerCase())
  )
}

onMounted(() => {
  // Load recent searches from localStorage
  const saved = localStorage.getItem('recentSearches')
  if (saved) {
    try {
      recentSearches.value = JSON.parse(saved)
    } catch (e) {
      recentSearches.value = []
    }
  }
})

// Watch for recent searches changes
import { watch } from 'vue'
watch(recentSearches, (newVal) => {
  localStorage.setItem('recentSearches', JSON.stringify(newVal))
}, { deep: true })
</script>

<style scoped>
.search-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-2) 0;
}

.search-header {
  text-align: center;
}

.search-title {
  font-size: var(--text-2xl);
  font-weight: var(--font-bold);
  color: var(--text-primary);
  margin: 0 0 var(--space-2) 0;
}

.search-subtitle {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
}

.search-form {
  display: flex;
  gap: var(--space-3);
  align-items: flex-end;
}

.search-form .input-wrapper {
  flex: 1;
}

.search-form .input-field {
  padding-right: 44px;
}

.search-icon {
  width: 20px;
  height: 20px;
  color: var(--text-tertiary);
}

.search-results {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.results-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.result-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.result-card:hover {
  background: var(--glass-bg-hover);
  border-color: var(--glass-border-hover);
  transform: translateX(4px);
}

.result-avatar {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.result-avatar svg {
  width: 22px;
  height: 22px;
  color: var(--text-tertiary);
}

.result-info {
  flex: 1;
  min-width: 0;
}

.result-name {
  font-size: var(--text-md);
  font-weight: var(--font-semibold);
  color: var(--text-primary);
  margin: 0 0 var(--space-1) 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.result-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
}

.result-id {
  color: var(--text-secondary);
}

.result-certainty {
  font-size: var(--text-xs);
  font-weight: var(--font-semibold);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-full);
  text-transform: uppercase;
}

.result-certainty.badge-known { background: var(--success-bg); color: var(--success); }
.result-certainty.badge-unknown { background: var(--glass-bg); color: var(--text-tertiary); }
.result-certainty.badge-ambiguous { background: var(--warning-bg); color: var(--warning); }
.result-certainty.badge-insufficient { background: var(--error-bg); color: var(--error); }

.result-appearances {
  color: var(--text-tertiary);
}

.result-action {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.result-card:hover .result-action {
  background: var(--glass-bg-hover);
  color: var(--accent-primary);
  border-color: var(--accent-primary);
}

.chevron-icon {
  width: 16px;
  height: 16px;
}

.recent-searches {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.section-title {
  font-size: var(--text-sm);
  font-weight: var(--font-semibold);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.recent-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-lg);
  background: var(--glass-bg);
  border: 1px solid var(--glass-border);
  cursor: pointer;
  transition: all var(--transition-fast);
  text-align: left;
  width: 100%;
}

.recent-item:hover {
  background: var(--glass-bg-hover);
  border-color: var(--glass-border-hover);
}

.recent-icon {
  width: 20px;
  height: 20px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.recent-text {
  font-size: var(--text-sm);
  font-weight: var(--font-medium);
  color: var(--text-primary);
}

/* Responsive */
@media (max-width: 768px) {
  .search-view {
    padding: var(--space-1) 0;
  }
  
  .search-form {
    flex-direction: column;
    align-items: stretch;
  }
  
  .search-form .btn {
    width: 100%;
    justify-content: center;
  }
  
  .search-title {
    font-size: var(--text-xl);
  }
}
</style>