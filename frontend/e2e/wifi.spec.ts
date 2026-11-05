import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('the Wi-Fi screen fits the window', async ({ page }) => {
  await open(page, '/routers/ap2/wifi')
  await expect(page.getByRole('heading', { name: 'Wi-Fi', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Modes' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Channels' })).toBeVisible()
  await noHorizontalScroll(page)
})

test('n20 on channel 6 goes on air, proven, then parks again', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  await open(page, '/routers/ap2/wifi')
  const modes = page.getByRole('region', { name: 'Modes' })
  const channels = page.getByRole('region', { name: 'Channels' })
  const apply = page.getByRole('button', { name: 'Apply to AP2', exact: true })
  await expect(page.getByText('parked', { exact: true })).toBeVisible()

  await modes.getByRole('button', { name: /802\.11n · 20 MHz/ }).click()
  await channels.getByRole('button', { name: 'Channel 6, 2437 MHz' }).click()
  await expect(page.getByRole('region', { name: 'Command preview' })).toContainText("uci set wireless.radio0.htmode='HT20'")
  await apply.click()
  await expect(page.getByText('Applied and proven on air')).toBeVisible()
  await expect(page.getByText('on air · ch 6 · HT20')).toBeVisible()

  // leave the simulated router as it was: Auto modes, radio parked
  await modes.getByRole('button', { name: 'Auto', exact: true }).click()
  await channels.getByRole('button', { name: 'None', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Command preview' })).toContainText("uci set wireless.radio0.disabled='1'")
  await apply.click()
  await expect(page.getByText('parked', { exact: true })).toBeVisible()
})
