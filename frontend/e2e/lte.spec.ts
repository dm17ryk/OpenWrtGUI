import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('the LTE screen shows the operator, the labelled signal and four charts', async ({ page }) => {
  await open(page, '/routers/ap1/lte')
  await expect(page.getByRole('heading', { name: 'LTE', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Status' })).toContainText('Partner')
  await expect(page.getByRole('region', { name: 'RSRP' })).toContainText(/excellent|good|fair|poor/)
  await expect(page.locator('.rf-chart canvas')).toHaveCount(4)
  await expect(page.getByRole('region', { name: 'Modem' })).toContainText('BM806C')
  await noHorizontalScroll(page)
})

test('an AT query, then disconnect and connect in the simulator', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulator')
  await open(page, '/routers/ap1/lte')
  await page.getByRole('textbox', { name: 'AT command' }).fill('AT+CSQ')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  await expect(page.getByRole('log', { name: 'AT console output' })).toContainText('+CSQ: 20,99')
  const actions = page.getByRole('group', { name: 'LTE action' })
  await actions.getByRole('button', { name: 'Disconnect', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Command preview' })).toContainText('ifdown lte')
  await page.getByRole('button', { name: 'Run: Disconnect' }).click()
  await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')
  await actions.getByRole('button', { name: 'Connect', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Command preview' })).toContainText('ifup lte')
  await page.getByRole('button', { name: 'Run: Connect' }).click()
  await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('lte up')
  await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')
})
