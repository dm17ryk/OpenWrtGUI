/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:8765'
const here = (path: string): string => fileURLToPath(new URL(path, import.meta.url))

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    // The in-app help bundles the user manual from ../docs/manual (src/help/manual.ts).
    fs: { allow: [here('.'), here('../docs/manual')] },
    proxy: {
      '/api': api,
      '/ws': { target: api.replace('http', 'ws'), ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    // Typing through the wizard takes ~3 s on a busy bench PC; 5 s (the default) flakes there.
    testTimeout: 15_000,
    // The module cache keys src/help/manual.ts by its own text, so a new docs/manual page behind its
    // import.meta.glob stays invisible to the tests until the cache is cleared.
    fsModuleCache: false,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
