import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    watch: {
      // 编辑器原子写产生的 *.tmpdir 临时目录会让 chokidar 在 Windows 上
      // EBUSY 崩溃整个 dev 服务器，直接忽略这类目录
      ignored: ['**/*.tmpdir/**', '**/.vite/**'],
    },
    fs: {
      allow: ['..'], // 允许前端访问项目根目录下的 resources/（提取产物）
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1600,
  },
})
