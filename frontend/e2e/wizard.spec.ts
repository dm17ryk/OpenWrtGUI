import { expect, test } from '@playwright/test'
import { open, removeRouterAt } from './helpers'

const HOST = '192.168.1.4'

test('add a router through the wizard', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'adds a router; one run is enough')
  await removeRouterAt(request, baseURL ?? '', HOST)
  await open(page, `/add?host=${HOST}`)
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  await page.getByRole('button', { name: 'Accept and pin', exact: true }).click()
  await expect(page.getByLabel('User')).toHaveValue('root')
  await page.getByLabel('Password', { exact: true }).fill('sim-password')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()
  await expect(page.getByText(/grep -qxF/)).toBeVisible()
  await page.getByRole('button', { name: 'Install key', exact: true }).click()
  await expect(page.getByText('app key installed and working')).toBeVisible()
  await page.getByRole('button', { name: 'Continue', exact: true }).click()
  await expect(page.getByLabel('Label for internal port 0')).toHaveValue('LAN4')
  await page.getByLabel('Name').fill('AP4 · test')
  await page.getByRole('button', { name: 'Save port map', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('AP4 · test')
  await page.getByRole('link', { name: 'Dashboard' }).click()
  await expect(page.getByRole('article')).toHaveCount(4)
  await removeRouterAt(request, baseURL ?? '', HOST)
})

test('a router that still has root / root logs in by itself', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'adds a router; one run is enough')
  const factory = '192.168.1.5'
  await removeRouterAt(request, baseURL ?? '', factory)
  await open(page, `/add?host=${factory}`)
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  await page.getByRole('button', { name: 'Accept and pin', exact: true }).click()
  await expect(page.getByText(/Logged in with the default root \/ root/)).toBeVisible()
  await expect(page.getByLabel('Password', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Install key', exact: true }).click()
  await expect(page.getByText('app key installed and working')).toBeVisible()
  await removeRouterAt(request, baseURL ?? '', factory)
})
