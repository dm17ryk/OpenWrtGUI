import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// v1.0a2 D9: every page of the bench image has a screen here, so the fallback is shown on ap4, a later image
// whose menu brings luci-app-sqm's Network › SQM QoS (the later-* projects' server seeds ap4).
test('a page with no screen here opens in LuCI and closes cleanly', async ({ page }) => {
  await open(page, '/routers/ap4')
  const card = page.getByRole('region', { name: 'LuCI pages on AP4' })
  await card.getByRole('link', { name: 'Open Network › SQM QoS in LuCI' }).click()
  await expect(page.getByRole('heading', { name: 'SQM QoS', level: 1 })).toBeVisible()
  await expect(page.getByRole('note')).toContainText('can change: SQM QoS settings')
  const frame = page.frameLocator('iframe[title="LuCI page SQM QoS"]')
  await expect(frame.getByText('LuCI (simulated): SQM QoS')).toBeVisible()
  await expect(frame.getByText(/session sim-\d+/)).toBeVisible()
  await noHorizontalScroll(page)
  await page.getByRole('button', { name: 'Close and end session', exact: true }).click()
  await expect(page.getByText('Session ended')).toBeVisible()
  await expect(page.getByText('Nothing changed.')).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('the LuCI pages fold into one list on router screens', async ({ page }) => {
  await open(page, '/routers/ap4/wifi')
  const nav = page.getByRole('navigation', { name: 'AP4 sections' })
  await nav.getByText(/LuCI pages \(\d+\)/).click()
  await nav.getByRole('link', { name: 'Network › SQM QoS', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'SQM QoS', level: 1 })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'LuCI: Network › SQM QoS' })).toHaveAttribute('aria-current', 'page')
})
