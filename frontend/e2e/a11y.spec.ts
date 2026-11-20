import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Locator, type Page } from '@playwright/test'
import { open } from './helpers'

/**
 * Every screen of the app, each checked once its main heading and one piece of its loaded content are visible
 * (the 1.x proposal's D6; the content wait from the v1.1a final review: a heading alone can show before the
 * cards' own reads answer).
 */
const SCREENS: Array<[path: string, heading: string | RegExp, loaded: (page: Page) => Locator]> = [
  ['/', /router/, (p) => p.getByRole('article', { name: 'AP1 · bench' })],
  ['/routers/ap1', 'AP1 · bench', (p) => p.getByRole('button', { name: 'Remove from the app' })],
  ['/routers/ap1/wifi', 'Wi-Fi', (p) => p.getByRole('region', { name: 'Modes' })],
  ['/routers/ap1/rf', 'RF live', (p) => p.getByRole('region', { name: 'Channel analysis' })],
  ['/routers/ap1/network', 'Network and DHCP', (p) => p.getByRole('region', { name: 'DNS' })],
  ['/routers/ap1/ports', 'Ports, VLANs, mirroring', (p) => p.getByRole('region', { name: 'VLANs' })],
  ['/routers/ap1/firewall', 'Firewall', (p) => p.getByRole('group', { name: 'wan To this router' })],
  ['/routers/ap1/faults', 'Faults and capture', (p) => p.getByRole('article', { name: 'Duration' })],
  ['/routers/ap1/discovery', 'Discovery', (p) => p.getByRole('region', { name: 'Image', exact: true })],
  ['/routers/ap2/lte', 'LTE', (p) => p.getByRole('region', { name: 'Modem' })],
  ['/routers/ap1/system', 'System', (p) => p.getByRole('region', { name: 'Overview' })],
  ['/routers/ap1/tools/port-stats', 'Tools', (p) => p.getByRole('columnheader', { name: 'Rx rate' })],
  ['/routers/ap1/tools/connections', 'Tools', (p) => p.getByRole('table', { name: 'Connections' })],
  ['/routers/ap1/tools/throughput', 'Tools', (p) => p.getByRole('combobox', { name: 'The router' })],
  ['/routers/ap1/tools/traffic', 'Tools', (p) => p.getByRole('region', { name: 'Send' })],
  ['/routers/ap1/tools/stations', 'Tools', (p) => p.getByRole('region', { name: 'OpenWrt (phy0-ap0, channel 1)' })],
  ['/terminal/ap1', 'AP1 · bench', (p) => p.getByRole('navigation', { name: 'Routers' })],
  ['/audit', 'Audit log', (p) => p.getByRole('combobox', { name: 'Router' })],
  ['/settings', 'Settings', (p) => p.getByRole('region', { name: 'Image library' })],
]

const BLOCKING = new Set(['serious', 'critical'])

async function blocking(page: Page): Promise<{ report: string[]; others: Array<{ id: string; impact: string; nodes: number }> }> {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const report = results.violations
    .filter((v) => BLOCKING.has(v.impact ?? ''))
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
  const others = results.violations
    .filter((v) => !BLOCKING.has(v.impact ?? ''))
    .map((v) => ({ id: v.id, impact: v.impact ?? 'unknown', nodes: v.nodes.length }))
  return { report, others }
}

test('the check fails on a real serious violation', async ({ page }, info) => {
  test.skip(info.project.name.startsWith('mobile'), 'the desktop projects run the check')
  await page.setContent('<!doctype html><html lang="en"><title>t</title><main><input type="text"></main></html>')
  const { report } = await blocking(page)
  expect(report.some((line) => line.startsWith('label '))).toBe(true)
})

for (const [path, heading, loaded] of SCREENS) {
  test(`no serious or critical accessibility violation on ${path}`, async ({ page }, info) => {
    test.skip(info.project.name.startsWith('mobile'), 'the desktop projects check both themes; mobile repeats them')
    await open(page, path)
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    await expect(loaded(page).first()).toBeVisible()
    const { report, others } = await blocking(page)
    for (const v of others) {
      info.annotations.push({ type: `axe ${v.impact}`, description: `${v.id}: ${v.nodes} node(s) on ${path}` })
    }
    expect(report, `serious or critical violations on ${path}`).toEqual([])
  })
}
