import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('the Faults screen fits the window', async ({ page }) => {
  await open(page, '/routers/ap1/faults')
  await expect(page.getByRole('heading', { name: 'Faults and capture', level: 1 })).toBeVisible()
  for (const name of ['Link down', 'Isolate', 'Block flows', 'Impair', 'Station and AP', 'Duration']) {
    await expect(page.getByRole('article', { name })).toBeVisible()
  }
  await expect(page.getByRole('region', { name: 'Capture' })).toBeVisible()
  await noHorizontalScroll(page)
})

test('a held rtp_in block on the panel arms, counts down, and Clear everything clears it', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  test.setTimeout(120_000)
  await open(page, '/routers/ap1/faults')
  await page.getByRole('button', { name: /^panel · 192\.168\.1\.30/ }).click()
  const l3 = page.getByRole('article', { name: 'Block flows' })
  await l3.getByRole('button', { name: 'rtp_in' }).click()
  await l3.getByRole('slider', { name: /Loss/ }).fill('30')
  const duration = page.getByRole('article', { name: 'Duration' })
  await duration.getByRole('button', { name: 'Hold, then clear' }).click()
  await duration.getByLabel('Hold for (s)').fill('60')
  const run = page.getByRole('region', { name: /Will run on AP1/ })
  await expect(run.getByRole('region', { name: 'Command preview' })).toContainText('numgen random mod 100 < 30')
  await expect(run.getByRole('region', { name: 'Command preview' })).toContainText('start-stop-daemon')
  await run.getByRole('button', { name: 'Arm', exact: true }).click()
  await expect(run.getByRole('status', { name: 'Apply result' })).toContainText('Armed and proven')

  const armed = page.getByRole('table', { name: 'Armed faults' })
  await expect(armed).toContainText('rtp_in')
  await expect(armed).toContainText(/clears in \d+ s/)
  await expect(page.getByText('1 armed')).toBeVisible()

  await page.getByRole('button', { name: 'Clear everything' }).click()
  const clear = page.getByRole('group', { name: 'Clear faults' })
  await expect(clear.getByRole('region', { name: 'Command preview' })).toContainText('benchfault')
  await clear.getByRole('button', { name: 'Clear', exact: true }).click()
  await expect(clear.getByRole('status', { name: 'Apply result' })).toContainText('Cleared')
  await expect(page.getByText('nothing armed')).toBeVisible()
})

test('a 3 s capture on br-lan saves a .pcap under captures', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project captures')
  await open(page, '/routers/ap1/faults')
  const cap = page.getByRole('region', { name: 'Capture' })
  await cap.getByLabel('Interface').selectOption('br-lan')
  await cap.getByLabel('Duration (s)').fill('3')
  await cap.getByRole('button', { name: 'Save .pcap' }).click()
  await expect(cap.getByRole('table', { name: 'Captures' })).toContainText(/captures[\\/].*\.pcap/, { timeout: 30_000 })
})
