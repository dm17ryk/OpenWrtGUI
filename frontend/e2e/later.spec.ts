import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// ap4 (v1.0a2 D7): a router whose image has what the bench image lacks; this server seeds it (OPENWRTGUI_SIM_SEED)
test('a later image lists its own LuCI pages', async ({ page }) => {
  await open(page, '/routers/ap4')
  const card = page.getByRole('region', { name: 'LuCI pages on AP4' })
  await expect(card.getByText('SQM QoS').first()).toBeVisible()
  await noHorizontalScroll(page)
})

test('mount points are edited on a router with block-mount', async ({ page }) => {
  await open(page, '/routers/ap4/system?tab=mounts')
  await expect(page.getByRole('table', { name: 'fstab entries' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Unmount /mnt/usb' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Unmount /overlay' })).toHaveCount(0)
  await page.getByLabel('Enabled').first().uncheck()
  const preview = page.getByRole('region', { name: 'Command preview' })
  await expect(preview).toContainText("uci set fstab.cfg02a7f1.enabled='0'")
  await expect(preview).toContainText('/sbin/block mount')
  await noHorizontalScroll(page)
})
