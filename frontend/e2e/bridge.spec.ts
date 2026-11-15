import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// ap5 (v1.0a3 D5): a simulated DSA router; this server seeds it with ap4 (OPENWRTGUI_SIM_SEED)
test('a DSA router previews a bridge VLAN change with the rollback', async ({ page }) => {
  await open(page, '/routers/ap5/ports')
  const card = page.getByRole('region', { name: 'VLANs · switch' })
  await expect(card.getByRole('table', { name: 'Bridge VLAN membership' })).toBeVisible()
  await card.getByRole('button', { name: 'VLAN 10 lan2 not a member' }).click()
  await card.getByRole('button', { name: 'VLAN 10 lan2 untagged' }).click() // on through U to T: VLAN 1 keeps lan2
  await expect(card.getByRole('button', { name: 'VLAN 1 lan2 untagged' })).toBeVisible()
  const preview = card.getByRole('region', { name: 'Command preview' })
  await expect(preview).toContainText("add_list network.cfg050f15.ports='lan2:t'")
  await expect(preview).not.toContainText('cfg040f15')
  await expect(card.getByText(/60 s rollback/).first()).toBeVisible()
  await noHorizontalScroll(page)
})

test('a new VLAN is applied, confirmed and shown', async ({ page }, info) => {
  test.skip(info.project.name !== 'later-desktop-light', 'one project changes the simulated router')
  await open(page, '/routers/ap5/ports')
  const card = page.getByRole('region', { name: 'VLANs · switch' })
  await card.getByRole('button', { name: '+ Add VLAN' }).click()
  await card.getByRole('button', { name: 'VLAN 2 lan4 not a member' }).click()
  // the change lists VLAN 1 (lan4 moved out of it) first, so the new section is the second one: $b2
  await expect(card.getByRole('region', { name: 'Command preview' })).toContainText("add_list network.$b2.ports='lan4'")
  await card.getByRole('button', { name: 'Apply with rollback' }).click()
  // the router confirmed it over a new connection, then the card follows the router's state again
  await expect(card.getByText('Applied and confirmed')).toBeVisible({ timeout: 30_000 })
  await expect(card.getByLabel('Number of new VLAN')).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'VLAN 2 lan4 untagged' })).toBeVisible()
  await expect(card.getByRole('button', { name: 'VLAN 1 lan4 not a member' })).toBeVisible()
})
