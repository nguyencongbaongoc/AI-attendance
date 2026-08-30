import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/components/Layout.vue'

const routes = [
  {
    path: '/',
    component: Layout,
    children: [
      {
        path: '',
        name: 'LiveDashboard',
        component: () => import('@/views/LiveDashboard.vue'),
        meta: { title: 'Live Dashboard' }
      },
      {
        path: 'replay',
        name: 'Replay',
        component: () => import('@/views/ReplayView.vue'),
        meta: { title: 'Replay' }
      },
      {
        path: 'search',
        name: 'Search',
        component: () => import('@/views/SearchView.vue'),
        meta: { title: 'Person Search' }
      },
      {
        path: 'timetable',
        name: 'Timetable',
        component: () => import('@/views/TimetableManagement.vue'),
        meta: { title: 'Timetable Management' }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title || 'AI Attendance'} - Live Dashboard`
  next()
})

export default router
