import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('the Ports screen fits the window', async ({ page }) => {
  await open(page, '/routers/ap2/ports')
  await expect(page.getByRole('heading', { name: 'Ports, VLANs, mirroring', level: 1 })).toBeVisible()
  for (const name of ['Front panel', 'VLANs', 'Mirroring']) await expect(page.getByRole('region', { name })).toBeVisible()
  await noHorizontalScroll(page)
})

test('LAN1 is locked; LAN2 goes off and Enable all ports brings it back', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  await open(page, '/routers/ap2/ports')
  const panel = page.getByRole('region', { name: 'Front panel' })
  const lan2 = panel.getByRole('group', { name: 'LAN2' })
  const apply = panel.getByRole('button', { name: 'Apply', exact: true })

  await expect(panel.getByRole('group', { name: 'LAN1' })).toContainText("carries this app's SSH")
  await expect(panel.getByRole('group', { name: 'LAN1' }).getByRole('switch')).toHaveCount(0)

  await lan2.getByRole('switch', { name: 'Enable LAN2' }).click()
  await expect(panel.getByRole('region', { name: 'Command preview' })).toContainText('swconfig dev switch0 port 2 set enable 0')
  await apply.click()
  await expect(lan2.getByRole('switch', { name: 'Enable LAN2' })).toHaveAttribute('aria-checked', 'false')
  await expect(lan2).toContainText('off')

  await panel.getByRole('button', { name: 'Enable all ports' }).click()
  await expect(panel.getByRole('region', { name: 'Command preview' })).toContainText('swconfig dev switch0 port 2 set enable 1')
  await apply.click()
  await expect(lan2.getByRole('switch', { name: 'Enable LAN2' })).toHaveAttribute('aria-checked', 'true')
})

test('a VLAN cell click shows the new member list in the preview', async ({ page }) => {
  await open(page, '/routers/ap2/ports')
  const vlans = page.getByRole('region', { name: 'VLANs' })
  await vlans.getByRole('button', { name: 'VLAN 1 LAN4 untagged' }).click()
  await expect(vlans.getByRole('region', { name: 'Command preview' })).toContainText("ports='0t 1 2 3 6t'")
  await expect(vlans.getByText(/60 s rollback/).first()).toBeVisible()
})
