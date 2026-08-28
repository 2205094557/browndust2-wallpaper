import { defineConfig } from 'vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// 与 SRC 一致，从本文件位置推导 templates/，不再硬编码机器绝对路径
const FRONTEND = path.dirname(fileURLToPath(import.meta.url))
const TEMPLATES = path.join(FRONTEND, '..', 'templates')
const NM = path.join(FRONTEND, 'node_modules')
// 权威源固定指向 templates/live2d_app_src.js（不要再依赖 cwd 下的旧拷贝）。
const SRC = path.join(FRONTEND, '..', 'templates', 'live2d_app_src.js')

export default defineConfig({
  root: process.cwd(),
  // entry 位于 templates/，无法向上找到 frontend/node_modules，
  // 显式把库导入指到 frontend/node_modules 下的绝对路径。
  resolve: {
    alias: [
      { find: 'pixi-live2d-display/cubism4', replacement: path.join(NM, 'pixi-live2d-display/dist/cubism4.es.js') },
      { find: 'pixi-live2d-display', replacement: path.join(NM, 'pixi-live2d-display/dist/index.es.js') },
      { find: '@pixi', replacement: path.join(NM, '@pixi') },
    ],
  },
  build: {
    lib: {
      entry: SRC,
      name: 'L2DApp',
      formats: ['iife'],
    },
    outDir: TEMPLATES,
    emptyOutDir: false,
    minify: false,
    rollupOptions: {
      output: { entryFileNames: 'live2d-app.js' },
    },
    target: 'es2018',
  },
})