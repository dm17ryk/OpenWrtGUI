import { expect, test } from '@playwright/test'
import { ensureImages, noHorizontalScroll, open } from './helpers'

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
