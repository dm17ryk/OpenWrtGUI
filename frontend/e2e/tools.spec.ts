import { expect, test } from '@playwright/test'
import { ensureImages, noHorizontalScroll, open } from './helpers'

test('Discovery shows the capabilities, and a chip opens its Tools page', async ({ page, request, baseURL }) => {
  await ensureImages(request, baseURL ?? '')
  await open(page, '/routers/ap1/discovery')
  const caps = page.getByRole('region', { name: 'Capabilities' })
  await expect(caps.getByText('Switch · in image')).toBeVisible()
  await caps.getByRole('link', { name: 'Port statistics · in image' }).click()
  await expect(page).toHaveURL(/#\/routers\/ap1\/tools\/port-stats$/)
  await expect(page.getByRole('tab', { name: 'Port statistics' })).toHaveAttribute('aria-selected', 'true')
})

test('the Air survey chip lands on RF live with the channel analysis in view', async ({ page, request, baseURL }) => {
  await ensureImages(request, baseURL ?? '')
  await open(page, '/routers/ap1/discovery')
  await page.getByRole('region', { name: 'Capabilities' }).getByRole('link', { name: /^Air survey/ }).click()
  await expect(page).toHaveURL(/#\/routers\/ap1\/rf#channel-analysis$/)
  await expect(page.getByRole('region', { name: 'Channel analysis' })).toBeInViewport()
})

test('Port statistics: a linked port has a rate after the second read', async ({ page }) => {
  await open(page, '/routers/ap1/tools/port-stats')
  const table = page.getByRole('table')
  await expect(table.getByRole('columnheader', { name: 'Rx rate' })).toBeVisible()
  const linked = table.getByRole('row').filter({ hasText: 'Mbit/s' }).first()
  await expect(linked.getByRole('cell').nth(8)).toHaveText(/\d bit\/s|\d\.\d (k|M)bit\/s/, { timeout: 15_000 })
  await noHorizontalScroll(page)
})

test('Connections: SIP only leaves the SIP entry', async ({ page }) => {
  await open(page, '/routers/ap1/tools/connections')
  await expect(page.getByText('SIP ALG on: zone lan, UDP port 5060')).toBeVisible()
  const table = page.getByRole('table', { name: 'Connections' })
  await expect(table.getByRole('row')).not.toHaveCount(2)
  await page.getByRole('checkbox', { name: 'SIP only' }).check()
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(table.getByRole('row').nth(1)).toContainText('sip')
  await noHorizontalScroll(page)
})
