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

test('Recover on a working modem says there is nothing to do', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project starts LTE jobs in the simulator')
  await open(page, '/routers/ap1/lte')
  await page.getByRole('button', { name: 'Recover', exact: true }).click()
  const preview = page.getByRole('region', { name: 'Recover preview' })
  await expect(preview).toContainText('# only if LTE does not work after the step before')
  await preview.getByRole('button', { name: 'Start' }).click()
  await expect(page.getByRole('region', { name: 'Recover', exact: true })).toContainText('LTE works; nothing to do.')
})

test('the Recover preview fits the screen', async ({ page }) => {
  // PR #82 review: the long uqmi lines must scroll inside their box, not widen the page at 375 px
  await open(page, '/routers/ap1/lte')
  await page.getByRole('button', { name: 'Recover', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Recover preview' })).toContainText('--set-autoconnect disabled')
  await noHorizontalScroll(page)
})

test('Save good setup, then Reconfigure from it changes nothing', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project saves setups in the simulator')
  await open(page, '/routers/ap1/lte')
  page.on('dialog', (dialog) => void dialog.accept()) // a setup saved by an earlier run is replaced
  await page.getByRole('button', { name: 'Save good setup' }).click()
  const source = page.getByRole('combobox', { name: 'Reconfigure from' })
  await expect(source.getByRole('option', { name: /This router's good setup/ })).toHaveCount(1)
  await source.selectOption('ap1')
  await expect(page.getByText('Nothing to apply: the router already has these settings.')).toBeVisible()
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
