<template>
  <div class="layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <!-- Ambient lighting background -->
    <div class="ambient-lighting" :class="ambientClass"></div>
    
    <!-- Sidebar Navigation -->
    <aside class="sidebar glass-panel" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <div class="logo" :class="{ collapsed: sidebarCollapsed }">
          <svg v-if="!sidebarCollapsed" class="logo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
            <path d="M8 14c0 2.5 2 4 4 4s4-1.5 4-4"/>
          </svg>
          <span v-if="!sidebarCollapsed" class="logo-text">AI ATTENDANCE</span>
        </div>
        <button class="sidebar-toggle" @click="toggleSidebar" aria-label="Toggle sidebar">
          <svg class="toggle-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
        </button>
      </div>
      
      <nav class="sidebar-nav" role="navigation" aria-label="Main navigation">
        <ul class="nav-list">
          <li v-for="item in navItems" :key="item.path" class="nav-item">
            <router-link 
              :to="item.path" 
              class="nav-link glass-link"
              :class="{ active: isActive(item.path) }"
              @click="onNavClick"
            >
              <component :is="item.icon" class="nav-icon" />
              <span v-if="!sidebarCollapsed" class="nav-label">{{ item.label }}</span>
              <span v-if="sidebarCollapsed" class="nav-tooltip">{{ item.label }}</span>
            </router-link>
          </li>
        </ul>
      </nav>
      
      <div class="sidebar-divider"></div>
      
      <div class="sidebar-footer">
        <router-link to="/settings" class="nav-link glass-link settings-link">
          <component :is="SettingsIcon" class="nav-icon" />
          <span v-if="!sidebarCollapsed" class="nav-label">Settings</span>
          <span v-if="sidebarCollapsed" class="nav-tooltip">Settings</span>
        </router-link>
        
        <div v-if="!sidebarCollapsed" class="system-status-indicator">
          <span class="status-dot" :class="systemStatus"></span>
          <span class="status-text">{{ systemStatusText }}</span>
        </div>
      </div>
    </aside>
    
    <!-- Main Content Area -->
    <main class="main-content">
      <!-- Header -->
      <header class="header glass-panel">
        <div class="header-left">
          <h1 class="page-title">{{ pageTitle }}</h1>
          <span class="page-subtitle">{{ pageSubtitle }}</span>
        </div>
        
        <div class="header-center">
          <div class="system-health" :class="systemStatus">
            <span class="health-dot"></span>
            <span class="health-text">{{ systemStatusText }}</span>
            <span class="camera-count">{{ activeCamerasCount }} CAMERAS</span>
          </div>
        </div>
        
        <div class="header-right">
          <button class="icon-btn glass-btn" @click="toggleSidebar" aria-label="Toggle navigation">
            <component :is="MenuIcon" class="btn-icon" />
          </button>
          <button class="icon-btn glass-btn" aria-label="Notifications">
            <component :is="BellIcon" class="btn-icon" />
            <span class="notification-badge">3</span>
          </button>
          <button class="icon-btn glass-btn" aria-label="User menu">
            <component :is="UserIcon" class="btn-icon" />
          </button>
        </div>
      </header>
      
      <!-- Page Content -->
      <div class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>
    
    <!-- Replay Modal -->
    <ReplayModal v-if="replayState.isOpen" @close="closeReplay" />
    
    <!-- Provenance Panel -->
    <ProvenancePanel v-if="provenancePanel.isOpen" @close="closeProvenance" />
  </div>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { 
  LayoutDashboardIcon, 
  VideoIcon, 
  UsersIcon, 
  ActivityIcon, 
  SearchIcon, 
  RotateCcwIcon,
  CalendarIcon,
  SettingsIcon,
  MenuIcon,
  BellIcon,
  UserIcon
} from '@lucide/vue'
import ReplayModal from '@/components/ReplayModal.vue'
import ProvenancePanel from '@/components/ProvenancePanel.vue'

const router = useRouter()
const route = useRoute()
const store = useAppStore()

const sidebarCollapsed = computed({
  get: () => store.sidebarCollapsed,
  set: (val) => store.sidebarCollapsed = val
})

const systemStatus = computed(() => store.systemStatus)
const systemStatusText = computed(() => store.systemStatus.charAt(0).toUpperCase() + store.systemStatus.slice(1))
const activeCamerasCount = computed(() => store.activeCameras.length)

const pageTitle = computed(() => route.meta.title || 'Live Dashboard')
const pageSubtitle = computed(() => {
  const subtitles = {
    'Live Dashboard': 'Live Monitoring',
    'Replay': 'Forensic Replay',
    'Search': 'Person Search',
    'Timetable Management': 'Quản lý thời khóa biểu'
  }
  return subtitles[route.meta.title] || ''
})

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboardIcon },
  { path: '/cameras', label: 'Cameras', icon: VideoIcon },
  { path: '/attendance', label: 'Attendance', icon: UsersIcon },
  { path: '/events', label: 'Events', icon: ActivityIcon },
  { path: '/people', label: 'People', icon: SearchIcon },
  { path: '/replay', label: 'Replay', icon: RotateCcwIcon },
  { path: '/timetable', label: 'Timetable', icon: CalendarIcon }
]

const isActive = (path) => route.path === path || (path !== '/' && route.path.startsWith(path))

const onNavClick = () => {
  if (sidebarCollapsed.value) {
    sidebarCollapsed.value = false
  }
}

const toggleSidebar = () => {
  store.toggleSidebar()
}

const replayState = computed(() => store.replayState)
const provenancePanel = computed(() => store.provenancePanel)

const closeReplay = () => store.closeReplay()
const closeProvenance = () => store.closeProvenance()

const ambientClass = computed(() => {
  const status = store.systemStatus
  if (status === 'degraded') return 'ambient-warning'
  if (status === 'offline') return 'ambient-error'
  return 'ambient-normal'
})

// Initialize mock data on mount
onMounted(() => {
  store.initializeMockData()
  
  // Check for reduced motion preference
  const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  store.setReducedMotion(mediaQuery.matches)
  
  mediaQuery.addEventListener('change', (e) => {
    store.setReducedMotion(e.matches)
  })
})
</script>

<style scoped>
/* Layout */
.layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  grid-template-rows: auto 1fr;
  min-height: 100vh;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font-primary);
  transition: grid-template-columns 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.layout.sidebar-collapsed {
  grid-template-columns: 72px 1fr;
}

/* Ambient Lighting */
.ambient-lighting {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background: 
    radial-gradient(ellipse 80% 50% at 20% 20%, rgba(6, 182, 212, 0.08) 0%, transparent 70%),
    radial-gradient(ellipse 60% 40% at 80% 30%, rgba(139, 92, 246, 0.06) 0%, transparent 70%),
    radial-gradient(ellipse 100% 100% at 50% 100%, rgba(234, 179, 8, 0.04) 0%, transparent 50%);
  opacity: 0.6;
  transition: opacity 0.5s ease, background 1s ease;
}

.ambient-lighting.ambient-warning {
  background: 
    radial-gradient(ellipse 80% 50% at 20% 20%, rgba(234, 179, 8, 0.1) 0%, transparent 70%),
    radial-gradient(ellipse 60% 40% at 80% 30%, rgba(249, 115, 22, 0.08) 0%, transparent 70%);
}

.ambient-lighting.ambient-error {
  background: 
    radial-gradient(ellipse 80% 50% at 20% 20%, rgba(239, 68, 68, 0.1) 0%, transparent 70%),
    radial-gradient(ellipse 60% 40% at 80% 30%, rgba(220, 38, 38, 0.08) 0%, transparent 70%);
}

/* Sidebar */
.sidebar {
  position: relative;
  z-index: 10;
  display: flex;
  flex-direction: column;
  height: 100vh;
  border-right: 1px solid var(--border-primary);
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.sidebar.collapsed {
  width: 72px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-3);
  min-height: 64px;
  border-bottom: 1px solid var(--border-primary);
}

.logo {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  transition: opacity 0.2s ease, width 0.2s ease;
}

.logo.collapsed {
  justify-content: center;
}

.logo-icon {
  width: 28px;
  height: 28px;
  color: var(--accent-primary);
  flex-shrink: 0;
}

.logo-text {
  font-size: var(--text-xl);
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-primary) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.sidebar-toggle {
  display: none;
  padding: var(--space-2);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.sidebar-toggle:hover {
  background: var(--glass-bg-hover);
  color: var(--text-primary);
}

.sidebar-toggle:focus-visible {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

.sidebar.collapsed .sidebar-toggle {
  display: flex;
}

.toggle-icon {
  width: 20px;
  height: 20px;
  transition: transform 0.3s ease;
}

.sidebar.collapsed .toggle-icon {
  transform: rotate(180deg);
}

/* Navigation */
.sidebar-nav {
  flex: 1;
  padding: var(--space-4) var(--space-2);
  overflow-y: auto;
}

.nav-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.nav-item {
  position: relative;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-lg);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: var(--text-sm);
  font-weight: 500;
  white-space: nowrap;
  transition: all var(--transition-fast);
  position: relative;
  overflow: hidden;
}

.nav-link::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary));
  opacity: 0;
  transition: opacity var(--transition-normal);
  border-radius: var(--radius-lg);
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--glass-bg-hover);
}

.nav-link:hover::before {
  opacity: 0.08;
}

.nav-link.active {
  color: var(--accent-primary);
  background: var(--glass-bg-active);
}

.nav-link.active::before {
  opacity: 0.15;
}

.nav-link:focus-visible {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

.nav-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  transition: transform var(--transition-fast);
}

.nav-link:hover .nav-icon {
  transform: scale(1.1);
}

.nav-label {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.sidebar.collapsed .nav-label {
  display: none;
}

.nav-tooltip {
  display: none;
  position: absolute;
  left: 100%;
  top: 50%;
  transform: translateY(-50%);
  margin-left: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  white-space: nowrap;
  z-index: 100;
  box-shadow: var(--shadow-lg);
}

.sidebar.collapsed .nav-link:hover .nav-tooltip {
  display: block;
  animation: tooltipIn 0.2s ease;
}

@keyframes tooltipIn {
  from { opacity: 0; transform: translateY(-50%) translateX(-4px); }
  to { opacity: 1; transform: translateY(-50%) translateX(0); }
}

/* Sidebar Divider */
.sidebar-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-primary), transparent);
  margin: var(--space-2) var(--space-4);
}

/* Sidebar Footer */
.sidebar-footer {
  padding: var(--space-3) var(--space-2);
  border-top: 1px solid var(--border-primary);
}

.settings-link {
  color: var(--text-secondary);
}

.settings-link:hover {
  color: var(--text-primary);
}

.system-status-indicator {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  margin-top: var(--space-2);
  border-radius: var(--radius-md);
  background: var(--glass-bg);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
  animation: pulse 2s infinite;
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

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Main Content */
.main-content {
  position: relative;
  z-index: 5;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  overflow: hidden;
}

/* Header */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-6);
  height: 72px;
  border-bottom: 1px solid var(--border-primary);
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  z-index: 20;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.page-title {
  font-size: var(--text-2xl);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  font-weight: 400;
}

.header-center {
  display: flex;
  align-items: center;
}

.system-health {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  background: var(--glass-bg);
  border: 1px solid var(--border-primary);
}

.system-health.online .health-dot {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
  animation: pulse 2s infinite;
}

.system-health.degraded .health-dot {
  background: var(--warning);
  box-shadow: 0 0 8px var(--warning);
}

.system-health.offline .health-dot {
  background: var(--error);
  box-shadow: 0 0 8px var(--error);
  animation: none;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.health-text {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.camera-count {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-tertiary);
  padding: var(--space-1) var(--space-2);
  background: var(--bg-tertiary);
  border-radius: var(--radius-full);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  background: var(--glass-bg);
  border: 1px solid var(--border-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
}

.icon-btn:hover {
  color: var(--text-primary);
  background: var(--glass-bg-hover);
  border-color: var(--border-secondary);
}

.icon-btn:focus-visible {
  outline: 2px solid var(--accent-primary);
  outline-offset: 2px;
}

.btn-icon {
  width: 20px;
  height: 20px;
}

.notification-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  min-width: 18px;
  height: 18px;
  padding: 0 var(--space-1);
  border-radius: var(--radius-full);
  background: var(--error);
  color: white;
  font-size: var(--text-xs);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Page Content */
.page-content {
  flex: 1;
  padding: var(--space-6);
  overflow-y: auto;
  position: relative;
  z-index: 1;
}

/* Page Transitions */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* Responsive */
@media (max-width: 1024px) {
  .layout {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr;
  }
  
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    transform: translateX(-100%);
    box-shadow: var(--shadow-xl);
    border-right: none;
  }
  
  .sidebar:not(.collapsed) {
    transform: translateX(0);
  }
  
  .sidebar.collapsed {
    width: 280px;
    transform: translateX(-100%);
  }
  
  .sidebar-toggle {
    display: flex !important;
  }
  
  .header {
    padding: var(--space-3) var(--space-4);
  }
  
  .page-content {
    padding: var(--space-4);
  }
}

@media (max-width: 768px) {
  .header-center {
    display: none;
  }
  
  .page-title {
    font-size: var(--text-xl);
  }
}

/* Glass Panel Base */
.glass-panel {
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--border-primary);
}

.glass-link {
  background: transparent;
  border: none;
}

.glass-btn {
  background: var(--glass-bg);
  border: 1px solid var(--border-primary);
}

.glass-bg-hover {
  background: rgba(255, 255, 255, 0.03);
}

.glass-bg-active {
  background: rgba(6, 182, 212, 0.1);
}
</style>