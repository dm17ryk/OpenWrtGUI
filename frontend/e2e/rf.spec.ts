import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('RF live shows the station, both charts and what the driver does not report', async ({ page }) => {
  await open(page, '/routers/ap1/rf')
  await expect(page.getByRole('heading', { name: 'RX at AP' })).toBeVisible()
  await expect(page.getByText('f4:12:fa:f3:57:68').first()).toBeVisible()
  await expect(page.locator('.rf-chart canvas')).toHaveCount(2)
  await expect(page.getByRole('region', { name: 'Noise floor' })).toContainText('not reported')
  await noHorizontalScroll(page)
})

test('recording writes a CSV and says where', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project records')
  await open(page, '/routers/ap1/rf')
  await page.getByRole('button', { name: 'Record to CSV', exact: true }).click()
  await expect(page.getByText(/Recording to .*rf-ap1-radio0-.*\.csv/)).toBeVisible()
  await page.getByRole('button', { name: 'Stop recording', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Record to CSV', exact: true })).toBeVisible()
})

test('channel analysis scans and draws the networks', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project scans the simulated router')
  await open(page, '/routers/ap1/rf')
  const card = page.getByRole('region', { name: 'Channel analysis' })
  await card.getByRole('button', { name: 'Scan…', exact: true }).click()
  await expect(card.getByRole('region', { name: 'Command preview' })).toContainText('scan ap-force passive')
  await card.getByRole('button', { name: 'Scan now', exact: true }).click()
  await expect(card.getByRole('table', { name: 'Networks heard' })).toContainText('net-01')
  await expect(card.getByRole('img', { name: /13 channels, 7 networks heard/ })).toBeVisible()
  await noHorizontalScroll(page)
})

test('frame analysis starts, shows a window and stops', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project adds a monitor on the simulated router')
  await open(page, '/routers/ap1/rf')
  const card = page.getByRole('region', { name: 'Frame analysis' })
  await card.getByRole('button', { name: 'Frame analysis…', exact: true }).click()
  await expect(card.getByText(/Costs router CPU/)).toBeVisible()
  await card.getByRole('button', { name: 'Start frame analysis', exact: true }).click()
  await expect(card.getByText(/window \d+ · 3 s of every 5 s/)).toBeVisible({ timeout: 8_000 })
  await expect(card.getByRole('list', { name: 'Rate mix RX at AP, last window' })).toBeVisible({ timeout: 8_000 })
  await card.getByRole('button', { name: 'Stop frame analysis', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Frame analysis…', exact: true })).toBeVisible()
})
