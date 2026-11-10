import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// System › LED Configuration has no screen in the app until v0.6c (Diagnostics has the System screen since v0.6b).
test('a page with no screen here opens in LuCI and closes cleanly', async ({ page }) => {
  await open(page, '/routers/ap1')
  const card = page.getByRole('region', { name: 'LuCI pages on AP1' })
  await card.getByRole('link', { name: 'Open System › LED Configuration in LuCI' }).click()
  await expect(page.getByRole('heading', { name: 'LED Configuration', level: 1 })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('can change: LED Configuration settings')
  const frame = page.frameLocator('iframe[title="LuCI page LED Configuration"]')
  await expect(frame.getByText('LuCI (simulated): LED Configuration')).toBeVisible()
  await expect(frame.getByText(/session sim-\d+/)).toBeVisible()
  await noHorizontalScroll(page)
  await page.getByRole('button', { name: 'Close and end session', exact: true }).click()
  await expect(page.getByText('Session ended')).toBeVisible()
  await expect(page.getByText('Nothing changed.')).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('the LuCI pages fold into one list on router screens', async ({ page }) => {
  await open(page, '/routers/ap1/wifi')
  const nav = page.getByRole('navigation', { name: 'AP1 sections' })
  await nav.getByText(/LuCI pages \(\d+\)/).click()
  await nav.getByRole('link', { name: 'System › LED Configuration', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'LED Configuration', level: 1 })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'LuCI: System › LED Configuration' })).toHaveAttribute('aria-current', 'page')
})
