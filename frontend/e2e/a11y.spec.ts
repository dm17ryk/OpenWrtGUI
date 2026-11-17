import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { open } from './helpers'

/** Every screen of the app, each checked once it shows its main heading (the 1.x proposal's D6). */
const SCREENS: Array<[path: string, heading: string | RegExp]> = [
  ['/', /router/],
  ['/routers/ap1', 'AP1 · bench'],
  ['/routers/ap1/wifi', 'Wi-Fi'],
  ['/routers/ap1/rf', 'RF live'],
  ['/routers/ap1/network', 'Network and DHCP'],
  ['/routers/ap1/ports', 'Ports, VLANs, mirroring'],
  ['/routers/ap1/firewall', 'Firewall'],
  ['/routers/ap1/faults', 'Faults and capture'],
  ['/routers/ap1/discovery', 'Discovery'],
  ['/routers/ap2/lte', 'LTE'],
  ['/routers/ap1/system', 'System'],
  ['/terminal/ap1', 'AP1 · bench'],
  ['/audit', 'Audit log'],
  ['/settings', 'Settings'],
]

const BLOCKING = new Set(['serious', 'critical'])

for (const [path, heading] of SCREENS) {
  test(`no serious or critical accessibility violation on ${path}`, async ({ page }, info) => {
    test.skip(info.project.name.startsWith('mobile'), 'the desktop projects check both themes; mobile repeats them')
    await open(page, path)
    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const blocking = results.violations.filter((v) => BLOCKING.has(v.impact ?? ''))
    for (const v of results.violations.filter((x) => !BLOCKING.has(x.impact ?? ''))) {
      info.annotations.push({ type: `axe ${v.impact}`, description: `${v.id}: ${v.nodes.length} node(s) on ${path}` })
    }
    const report = blocking.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
    expect(report, `serious or critical violations on ${path}`).toEqual([])
  })
}
