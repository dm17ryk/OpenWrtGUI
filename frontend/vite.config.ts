/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:8765'

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': api,
      '/ws': { target: api.replace('http', 'ws'), ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
