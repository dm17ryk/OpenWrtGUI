import { expect, test } from '@playwright/test'
import { open } from './helpers'

test('a harness run makes everything read-only', async ({ page }) => {
  await open(page)
  await expect(page.getByRole('status')).toContainText('dima_night.py started 21:04 (PID 18244)')
  await expect(page.getByText('dima_night.py running · read-only')).toBeVisible()
  await page.goto('/#/add?host=192.168.1.4')
  await page.getByRole('button', { name: 'Connect' }).click()
  await page.getByRole('button', { name: 'Accept and pin' }).click()
  await page.getByLabel('Root password').fill('sim-password')
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.getByRole('button', { name: 'Install key' }).click()
  await expect(page.getByRole('alert')).toContainText('dima_night.py started 21:04 (PID 18244)')
})

test('the terminal refuses writes during a run', async ({ page }) => {
  await open(page, '/terminal/ap2')
  await expect(page.getByText('Read-only mode: a harness run is in progress.')).toBeVisible()
  await page.getByLabel('Command').fill('reboot')
  await page.getByRole('button', { name: 'Run' }).click()
  await expect(page.getByText(/only read-only commands run during a harness run/).last()).toBeVisible()
})
