import { expect, test, type TestInfo } from '@playwright/test'
import { ensureImages, noHorizontalScroll, open, shot, stepThroughClear } from './helpers'

const SCREENS: ReadonlyArray<readonly [string, string, string]> = [
  ['dashboard', '/', 'AP1 · bench'],
  ['add-router', '/add', 'Where is the router?'],
  ['router-overview', '/routers/ap2', 'What AP2 says about itself'],
  ['discovery', '/routers/ap1/discovery', 'Added after flashing'],
  ['wifi', '/routers/ap1/wifi', 'Modes'],
  ['rf-live', '/routers/ap1/rf', 'RX at AP'],
  ['network', '/routers/ap1/network', 'Router addresses'],
  ['lte', '/routers/ap1/lte', 'Signal quality'],
  ['ports', '/routers/ap1/ports', 'Front panel'],
  ['firewall', '/routers/ap1/firewall', 'Filtering model'],
  ['faults', '/routers/ap1/faults', 'Faults and capture'],
  ['system', '/routers/ap1/system', 'Overview'],
  ['system-access', '/routers/ap1/system?tab=access', 'Router password'],
  ['tools-port-stats', '/routers/ap1/tools/port-stats', 'Rx rate'],
  ['tools-connections', '/routers/ap1/tools/connections', 'SIP ALG on'],
  ['tools-throughput', '/routers/ap1/tools/throughput', 'connects to a host'],
  ['tools-traffic', '/routers/ap1/tools/traffic', 'Duration (s)'],
  ['tools-stations', '/routers/ap1/tools/stations', 'Neighbour report'],
  ['luci-page', '/routers/ap1/luci?page=admin%2Fnetwork%2Fdiagnostics', 'Changed via LuCI since you opened this page'],
  ['terminal', '/terminal/ap2', 'Command'],
  ['audit-log', '/audit', 'Audit log'],
  ['settings', '/settings', 'Updates'],
]

for (const [name, path, ready] of SCREENS) {
  test(`screenshot ${name}`, async ({ page, request, baseURL }, info) => {
    if (name === 'discovery') await ensureImages(request, baseURL ?? '')
    await open(page, path)
    await expect(page.getByText(ready).first()).toBeVisible()
    await page.waitForTimeout(300)
    await noHorizontalScroll(page)
    await page.screenshot({ path: `e2e-screenshots/${info.project.name}/${name}.png`, fullPage: true })
  })
}

// Screens in the middle of an action (v1.0d D5). Desktop only; each one ends where the next project starts clean.
function desktopOnly(info: TestInfo): void {
  test.skip(!info.project.name.startsWith('desktop'), 'the wiki publishes the desktop screenshots')
}

test.describe('action screenshots', () => {
  test('screenshot step-through', async ({ page, request }, info) => {
    desktopOnly(info)
    const body = { radio: 'radio0', modes: ['g', 'n20'], channels: [1, 6], advance: 'manual' }
    await stepThroughClear(request, 'ap1', body)
    await open(page, '/routers/ap1/wifi')
    const card = page.getByRole('region', { name: 'Step-through' })
    await card.getByRole('button', { name: 'Step mode g', exact: true }).click()
    await card.getByRole('button', { name: 'Step mode n20', exact: true }).click()
    await card.getByRole('button', { name: 'Step channel 1', exact: true }).click()
    await card.getByRole('button', { name: 'Step channel 6', exact: true }).click()
    await card.getByRole('group', { name: 'Advance' }).getByRole('button', { name: 'Manual', exact: true }).click()
    await expect(card.getByText(/Step-through preview: 4 steps/)).toBeVisible()
    await card.scrollIntoViewIfNeeded()
    await shot(page, info.project.name, 'step-through')
  })

  test('screenshot channel-analysis', async ({ page }, info) => {
    desktopOnly(info)
    await open(page, '/routers/ap1/rf')
    const card = page.getByRole('region', { name: 'Channel analysis' })
    await card.getByRole('button', { name: 'Scan…', exact: true }).click()
    await card.getByRole('button', { name: 'Scan now', exact: true }).click()
    await expect(card.getByRole('table', { name: 'Networks heard' })).toContainText('net-01')
    await card.scrollIntoViewIfNeeded()
    await shot(page, info.project.name, 'channel-analysis')
  })

  test('screenshot frame-analysis', async ({ page }, info) => {
    desktopOnly(info)
    await open(page, '/routers/ap1/rf')
    const card = page.getByRole('region', { name: 'Frame analysis' })
    await card.getByRole('button', { name: 'Frame analysis…', exact: true }).click()
    await card.getByRole('button', { name: 'Start frame analysis', exact: true }).click()
    await expect(card.getByRole('list', { name: 'Rate mix RX at AP, last window' })).toBeVisible({ timeout: 8_000 })
    await card.scrollIntoViewIfNeeded()
    await shot(page, info.project.name, 'frame-analysis')
    await card.getByRole('button', { name: 'Stop frame analysis', exact: true }).click()
    await expect(card.getByRole('button', { name: 'Frame analysis…', exact: true })).toBeVisible()
  })

  test('screenshot flash-dialog', async ({ page, request, baseURL }, info) => {
    desktopOnly(info)
    await ensureImages(request, baseURL ?? '')
    await open(page, '/routers/ap2/discovery')
    await page.getByRole('button', { name: 'Flash an image…' }).click()
    const dialog = page.getByRole('region', { name: 'Flash AP2 · office' })
    const preview = dialog.getByRole('region', { name: 'Command preview' })
    // discovery.spec flashes AP2 earlier in a full run: the dialog then opens on that finished flash
    const again = dialog.getByRole('button', { name: 'Flash again', exact: true })
    await expect(preview.or(again)).toBeVisible()
    if (await again.isVisible()) await again.click()
    await expect(preview).toContainText('sysupgrade -T')
    await dialog.scrollIntoViewIfNeeded()
    await shot(page, info.project.name, 'flash-dialog')
  })
})
