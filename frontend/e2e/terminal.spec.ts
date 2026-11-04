import { expect, test } from '@playwright/test'
import { open } from './helpers'

test('line-mode terminal runs a command on the simulated router', async ({ page }) => {
  await open(page, '/terminal/ap2')
  await page.getByLabel('Command').fill('cat /etc/board.json')
  await page.getByRole('button', { name: 'Run' }).click()
  await expect(page.getByText(/dwr-921-c3-uboot/).first()).toBeVisible()
  await expect(page.getByText('[exit 0]')).toBeVisible()
})
