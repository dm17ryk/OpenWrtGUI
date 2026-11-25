import { expect, test } from '@playwright/test'
import { ensureImages, noHorizontalScroll, open } from './helpers'

test('Discovery shows the capabilities, and a chip opens its Tools page', async ({ page, request, baseURL }) => {
  await ensureImages(request, baseURL ?? '')
  await open(page, '/routers/ap1/discovery')
  const caps = page.getByRole('region', { name: 'Capabilities' })
  await expect(caps.getByText('Switch · in image')).toBeVisible()
  await caps.getByRole('link', { name: 'Port statistics · in image' }).click()
  await expect(page).toHaveURL(/#\/routers\/ap1\/tools\/port-stats$/)
  await expect(page.getByRole('tab', { name: 'Port statistics' })).toHaveAttribute('aria-selected', 'true')
})

test('the Air survey chip lands on RF live with the channel analysis in view', async ({ page, request, baseURL }) => {
  await ensureImages(request, baseURL ?? '')
  await open(page, '/routers/ap1/discovery')
  await page.getByRole('region', { name: 'Capabilities' }).getByRole('link', { name: /^Air survey/ }).click()
  await expect(page).toHaveURL(/#\/routers\/ap1\/rf#channel-analysis$/)
  await expect(page.getByRole('heading', { name: 'RX at AP' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Channel analysis' })).toBeInViewport()
})

test('Port statistics: a linked port has a rate after the second read', async ({ page }) => {
  await open(page, '/routers/ap1/tools/port-stats')
  const table = page.getByRole('table')
  await expect(table.getByRole('columnheader', { name: 'Rx rate' })).toBeVisible()
  const linked = table.getByRole('row').filter({ hasText: 'Mbit/s' }).first()
  await expect(linked.getByRole('cell').nth(8)).toHaveText(/\d bit\/s|\d\.\d (k|M)bit\/s/, { timeout: 15_000 })
  await noHorizontalScroll(page)
})

test('Throughput: a 10 s TCP run ends with its totals (v1.2b)', async ({ page }) => {
  await open(page, '/routers/ap1/tools/throughput')
  await page.getByLabel('Host').fill('192.168.1.10')
  await expect(page.getByRole('region', { name: 'Command preview' })).toContainText('iperf3 -c 192.168.1.10 -p 5201 -t 10')
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(page.getByText(/^Sent 94\.2 Mb\/s · received 94\.0 Mb\/s · router CPU \d+ %$/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('table', { name: 'Throughput' }).getByRole('row')).toHaveCount(11)
  await noHorizontalScroll(page)
})

test('Traffic generator: a listen shows its peer, and a send to port 1 is refused', async ({ page }) => {
  await open(page, '/routers/ap1/tools/traffic')
  const listen = page.getByRole('region', { name: 'Listen' })
  await expect(listen.getByRole('region', { name: 'Command preview' })).toContainText('socat TCP-LISTEN:9100')
  await listen.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(listen.getByRole('table', { name: 'Peers' })).toContainText('192.168.1.10:51515', { timeout: 15_000 })
  const send = page.getByRole('region', { name: 'Send' })
  await send.getByLabel('Host').fill('192.168.1.10')
  await send.getByLabel('Port').fill('1')
  await expect(send.getByRole('region', { name: 'Command preview' })).toContainText('TCP:192.168.1.10:1,')
  await send.getByRole('button', { name: 'Send', exact: true }).click()
  await expect(send.getByRole('alert')).toContainText('Connection refused')
  await noHorizontalScroll(page)
})

test('Connections: SIP ALG off, then on again, on AP1 lan (v1.2b R7)', async ({ page }) => {
  await open(page, '/routers/ap1/tools/connections')
  const switches = page.getByRole('region', { name: 'Switch SIP ALG' })
  await switches.getByRole('button', { name: 'Turn SIP ALG off in zone lan' }).click()
  await switches.getByRole('button', { name: 'Apply with rollback' }).click()
  await expect(switches.getByRole('status', { name: 'Apply result' })).toContainText('Switched and proven', { timeout: 60_000 })
  await expect(switches.getByText('Zone lan · SIP ALG off')).toBeVisible()
  await switches.getByRole('button', { name: 'Turn SIP ALG on in zone lan' }).click()
  await switches.getByRole('button', { name: 'Apply with rollback' }).click()
  await expect(switches.getByText('Zone lan · SIP ALG on')).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('SIP ALG on: zone lan, UDP port 5060')).toBeVisible()
})

test('Station management: a beacon report request shows the report (v1.2b R8)', async ({ page }) => {
  await open(page, '/routers/ap1/tools/stations')
  const ap = page.getByRole('region', { name: 'OpenWrt (phy0-ap0, channel 1)' })
  await ap.getByRole('button', { name: /^Beacon report request to / }).click()
  await expect(ap.getByRole('region', { name: 'Command preview' })).toContainText('rrm_beacon_req')
  await ap.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(ap.getByRole('table', { name: 'Beacon report' }).getByRole('row')).toHaveCount(2, { timeout: 30_000 })
  await noHorizontalScroll(page)
})

test('Connections: SIP only leaves the SIP entry', async ({ page }) => {
  await open(page, '/routers/ap1/tools/connections')
  await expect(page.getByText('SIP ALG on: zone lan, UDP port 5060')).toBeVisible()
  const table = page.getByRole('table', { name: 'Connections' })
  await expect(table.getByRole('row')).not.toHaveCount(2)
  await page.getByRole('checkbox', { name: 'SIP only' }).check()
  await expect(table.getByRole('row')).toHaveCount(2)
  await expect(table.getByRole('row').nth(1)).toContainText('sip')
  await noHorizontalScroll(page)
})
