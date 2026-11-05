import { expect, test } from '@playwright/test'
import { open } from './helpers'

test('a harness run makes everything read-only', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('status')).toContainText('dima_night.py started 21:04 (PID 18244)')
  await expect(page.getByText('dima_night.py running · read-only')).toBeVisible()
  await page.goto('/#/add?host=192.168.1.4')
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  await page.getByRole('button', { name: 'Accept and pin', exact: true }).click()
  await page.getByLabel('Password', { exact: true }).fill('sim-password')
  await page.getByRole('button', { name: 'Log in', exact: true }).click()
  await page.getByRole('button', { name: 'Install key', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('dima_night.py started 21:04 (PID 18244)')
})

test('Wi-Fi Apply is refused during a run and nothing changes', async ({ page }) => {
  await open(page, '/routers/ap2/wifi')
  await expect(page.getByText('parked', { exact: true })).toBeVisible()
  await page.getByRole('region', { name: 'Modes' }).getByRole('button', { name: /802\.11n · 20 MHz/ }).click()
  await page.getByRole('region', { name: 'Channels' }).getByRole('button', { name: 'Channel 6, 2437 MHz' }).click()
  await page.getByRole('button', { name: 'Apply to AP2', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'dima_night.py' })).toContainText('dima_night.py started 21:04 (PID 18244)')
  await expect(page.getByText('parked', { exact: true })).toBeVisible()
  await expect(page.getByText('Applied and proven on air')).toHaveCount(0)
})

test('a LuCI page opens read-only during a run', async ({ page }) => {
  await open(page, '/routers/ap1/luci?page=admin%2Fnetwork%2Fdhcp')
  await expect(page.getByRole('note')).toContainText('A harness run is in progress, so the session can only read')
  await expect(page.getByText('read-only session')).toBeVisible()
  await page.getByRole('button', { name: 'Close and end session', exact: true }).click()
  await expect(page.getByText('Session ended')).toBeVisible()
})

test('the terminal refuses writes during a run', async ({ page }) => {
  await open(page, '/terminal/ap2')
  await expect(page.getByText('Read-only mode: a harness run is in progress.')).toBeVisible()
  await page.getByLabel('Command').fill('reboot')
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(page.getByText(/only read-only commands run during a harness run/).last()).toBeVisible()
})
