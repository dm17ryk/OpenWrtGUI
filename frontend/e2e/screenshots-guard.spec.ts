import { expect, test } from '@playwright/test'
import { open, shot } from './helpers'

// The guard project runs the app with a live harness run; the wiki publishes this one from the light folder (v1.0d D5).
test('screenshot guard-banner', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('status')).toContainText('dima_night.py started 21:04 (PID 18244)')
  await expect(page.getByText('dima_night.py running · read-only').first()).toBeVisible()
  await shot(page, 'desktop-light', 'guard-banner')
})
