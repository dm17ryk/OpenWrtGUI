import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// System › Plugins has no screen in the app yet (v1.0a2 brings it): it opens in LuCI.
test('a page with no screen here opens in LuCI and closes cleanly', async ({ page }) => {
  await open(page, '/routers/ap1')
  const card = page.getByRole('region', { name: 'LuCI pages on AP1' })
  await card.getByRole('link', { name: 'Open System › Plugins in LuCI' }).click()
  await expect(page.getByRole('heading', { name: 'Plugins', level: 1 })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('can change: Plugins settings')
  const frame = page.frameLocator('iframe[title="LuCI page Plugins"]')
  await expect(frame.getByText('LuCI (simulated): Plugins')).toBeVisible()
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
  await nav.getByRole('link', { name: 'System › Plugins', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Plugins', level: 1 })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'LuCI: System › Plugins' })).toHaveAttribute('aria-current', 'page')
})
