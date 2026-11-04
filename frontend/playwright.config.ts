import { defineConfig, devices } from '@playwright/test'

const app = (port: number, data: string): string =>
  `uv run --project .. python -m openwrtgui --simulator ../tests/fixtures/sim --port ${port} --token e2e --no-window --web-dir dist --data-dir ../build/${data}`

const desktop = { viewport: { width: 1440, height: 900 } }
const mobile = { viewport: { width: 375, height: 812 }, isMobile: false }

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: { baseURL: 'http://127.0.0.1:8765', ...devices['Desktop Chrome'] },
  webServer: [
    { command: app(8765, 'e2e-data'), url: 'http://127.0.0.1:8765/api/health', timeout: 120_000, reuseExistingServer: !process.env.CI },
    {
      command: app(8766, 'e2e-guard'),
      url: 'http://127.0.0.1:8766/api/health',
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { OPENWRTGUI_SIM_GUARD: 'live' },
    },
  ],
  projects: [
    { name: 'desktop-light', testIgnore: /guard\.spec/, use: { ...desktop, colorScheme: 'light' } },
    { name: 'desktop-dark', testIgnore: /guard\.spec/, use: { ...desktop, colorScheme: 'dark' } },
    { name: 'mobile-light', testIgnore: /guard\.spec/, use: { ...mobile, colorScheme: 'light' } },
    { name: 'mobile-dark', testIgnore: /guard\.spec/, use: { ...mobile, colorScheme: 'dark' } },
    { name: 'guard', testMatch: /guard\.spec/, use: { ...desktop, colorScheme: 'light', baseURL: 'http://127.0.0.1:8766' } },
  ],
})
