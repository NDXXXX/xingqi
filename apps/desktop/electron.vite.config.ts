import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  main: {
    build: {
      rollupOptions: {
        input: { index: 'main/main.ts' },
      },
    },
  },
  preload: {
    build: {
      rollupOptions: {
        input: { index: 'preload/preload.ts' },
      },
    },
  },
  renderer: {
    root: '.',
    build: {
      rollupOptions: {
        input: 'index.html',
      },
    },
    plugins: [react(), tailwindcss()],
  },
})
