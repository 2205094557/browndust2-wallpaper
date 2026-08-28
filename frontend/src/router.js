import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/gallery' },
  { path: '/gallery', component: () => import('./features/gallery/GalleryView.vue') },
  { path: '/preview/:shipId', component: () => import('./features/preview/PreviewView.vue') },
  { path: '/settings', component: () => import('./features/settings/SettingsView.vue') },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})

