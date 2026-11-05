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
