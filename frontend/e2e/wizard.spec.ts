import { expect, test } from '@playwright/test'
import { open, removeRouterAt } from './helpers'

const HOST = '192.168.1.4'

test('add a router through the wizard', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'adds a router; one run is enough')
  await removeRouterAt(request, baseURL ?? '', HOST)
  await open(page, `/add?host=${HOST}`)
  await page.getByRole('button', { name: 'Connect' }).click()
  await page.getByRole('button', { name: 'Accept and pin' }).click()
  await page.getByLabel('Root password').fill('sim-password')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByText(/grep -qxF/)).toBeVisible()
  await page.getByRole('button', { name: 'Install key' }).click()
  await expect(page.getByText('app key installed and working')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByLabel('Label for internal port 0')).toHaveValue('LAN4')
  await page.getByLabel('Name').fill('AP4 · test')
  await page.getByRole('button', { name: 'Save port map' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('AP4 · test')
  await page.getByRole('link', { name: 'Dashboard' }).click()
  await expect(page.getByRole('article')).toHaveCount(4)
  await removeRouterAt(request, baseURL ?? '', HOST)
})
