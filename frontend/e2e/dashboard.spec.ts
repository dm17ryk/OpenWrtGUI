import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('dashboard shows the three simulated routers', async ({ page }) => {
  await open(page)
  const ap1 = page.getByRole('article', { name: 'AP1 · bench' })
  const ap2 = page.getByRole('article', { name: 'AP2 · office' })
  const ap3 = page.getByRole('article', { name: 'AP3 · QA stands' })
  await expect(ap1.getByText('on air')).toBeVisible()
  await expect(ap1.getByText(/1 station/)).toBeVisible()
  await expect(ap2.getByText('parked', { exact: true })).toBeVisible()
  await expect(ap3.getByText('needs app key')).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('3 routers · 1 radio on air · 1 station')
  await expect(page.getByRole('region', { name: '2.4 GHz air' })).toBeVisible()
  await noHorizontalScroll(page)
})

test('router overview lists what the router says about itself', async ({ page }) => {
  await open(page, '/routers/ap2')
  await expect(page.getByRole('article', { name: 'network.wireless get_validate' })).toContainText('radio 155 · SSID 289')
  await expect(page.getByText('5 LuCI packages, 62 menu entries')).toBeVisible()
  await noHorizontalScroll(page)
})
