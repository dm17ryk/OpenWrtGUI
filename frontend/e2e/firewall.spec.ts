import { expect, type Locator, type Page, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

const TABS = ['Zones and model', 'Traffic rules', 'Port forwards', 'NAT rules', 'IP sets', 'Custom rules', 'All nftables tables', 'Raw ruleset']

/** Apply the change a card previews, then wait until the preview is gone and the result is in. */
async function applyIn(card: Locator, label = 'Apply with rollback'): Promise<Locator> {
  await expect(card.getByRole('region', { name: 'Command preview' })).toBeVisible()
  await card.getByRole('button', { name: label, exact: true }).click()
  const result = card.getByRole('status', { name: 'Apply result' })
  await expect(result).toBeVisible({ timeout: 120_000 })
  return result
}

const lanInput = (page: Page): Locator => page.getByRole('group', { name: 'lan To this router' })

test('the Firewall screen and each of its tabs fit the window', async ({ page }) => {
  await open(page, '/routers/ap1/firewall')
  await expect(page.getByRole('heading', { name: 'Firewall', level: 1 })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Filtering model' })).toBeVisible()
  await noHorizontalScroll(page)
  for (const tab of TABS) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('main section.card').first()).toBeVisible()
    await noHorizontalScroll(page)
  }
})

test('lan Block all keeps the pins and is confirmed; without the SSH pin the router rolls back', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  test.setTimeout(300_000)
  await open(page, '/routers/ap1/firewall')
  const model = page.getByRole('region', { name: 'Filtering model' })

  await lanInput(page).getByRole('button', { name: 'Block all' }).click()
  await expect(model.getByText('Kept open by the app on lan, so it cannot lock itself out')).toBeVisible()
  await expect(model.getByRole('region', { name: 'Command preview' })).toContainText('owg_pin_ssh')
  await expect(await applyIn(model)).toContainText('Applied and confirmed')
  await expect(model.getByRole('region', { name: 'Command preview' })).toHaveCount(0)

  // the pins are in the config now; removing the SSH one cuts the app off, so the router restores itself
  await model.getByRole('button', { name: 'Remove…' }).first().click()
  await expect(model.getByText(/Without this rule the app loses AP1/)).toBeVisible()
  await model.getByRole('button', { name: 'Remove anyway' }).click()
  await expect(model.getByRole('region', { name: 'Command preview' })).toContainText('delete firewall.owg_pin_ssh')
  const rolledBack = await applyIn(model)
  await expect(rolledBack).toContainText('Not applied')
  await expect(rolledBack).toContainText('restored')

  // back to Allow all (the pins stay)
  await model.getByRole('button', { name: 'Put back' }).click()
  await lanInput(page).getByRole('button', { name: 'Allow all' }).click()
  await expect(await applyIn(model)).toContainText('Applied and confirmed')
  await expect(lanInput(page).getByRole('button', { name: 'Allow all' })).toHaveAttribute('aria-pressed', 'true')
})

test('a new traffic rule lists with its packets', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  test.setTimeout(180_000)
  await open(page, '/routers/ap1/firewall?tab=rules')
  const card = page.getByRole('region', { name: 'Traffic rules' })
  await card.getByRole('button', { name: '+ Rule' }).click()
  const editor = card.getByRole('group', { name: 'New rule' })
  await editor.getByLabel('Name').fill('e2e-drop-ping')
  await editor.getByLabel('Source zone').selectOption('lan')
  await editor.getByLabel('Protocol').fill('icmp')
  await editor.getByLabel('Source address').fill('192.168.1.99')
  await editor.getByLabel('Action').selectOption('DROP')
  await expect(card.getByRole('region', { name: 'Command preview' })).toContainText('add firewall rule')
  await expect(await applyIn(card)).toContainText('Applied and confirmed')
  const row = card.getByRole('table', { name: 'Traffic rules' }).getByRole('row', { name: /e2e-drop-ping/ })
  await expect(row).toContainText('drop')
  await expect(row.getByRole('cell').nth(4)).toHaveText(/^\d+$/)

  await row.getByRole('button', { name: 'Edit' }).click()
  await card.getByRole('group', { name: 'Rule e2e-drop-ping' }).getByRole('button', { name: 'Delete rule' }).click()
  await expect(await applyIn(card)).toContainText('Applied and confirmed')
  await expect(card.getByRole('row', { name: /e2e-drop-ping/ })).toHaveCount(0)
})

test('voipdscp unlocks, an edited rule applies with the override, and it locks again', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  test.setTimeout(180_000)
  await open(page, '/routers/ap1/firewall?tab=tables')
  const card = page.getByRole('region', { name: /All nftables tables/ })
  const row = card.getByRole('table', { name: 'nftables tables' }).getByRole('row', { name: /bridge voipdscp/ })
  await row.getByRole('button', { name: 'Unlock…' }).click()
  const ask = card.getByRole('group', { name: 'Unlock bridge voipdscp?' })
  await expect(ask).toContainText('voip_chain')
  await ask.getByRole('button', { name: 'Unlock', exact: true }).click()

  const editor = card.getByRole('group', { name: 'Table bridge voipdscp' })
  const edit = async (body: string): Promise<void> => {
    await editor.getByRole('row').nth(1).getByRole('button', { name: 'Edit' }).click()
    await editor.getByRole('textbox', { name: 'post rule 1' }).fill(body)
    await expect(card.getByRole('region', { name: 'Command preview' })).toContainText('nft -c -f /dev/stdin')
    await expect(await applyIn(card)).toContainText('Applied and confirmed')
  }
  await edit('udp dport 5006 ip dscp set ef counter')
  await expect(editor.getByRole('row').nth(1)).toContainText('5006')
  await edit('udp dport 5004 ip dscp set ef counter')

  await row.getByRole('button', { name: 'Lock' }).click()
  await expect(card.getByRole('group', { name: 'Table bridge voipdscp' })).toHaveCount(0)
})
