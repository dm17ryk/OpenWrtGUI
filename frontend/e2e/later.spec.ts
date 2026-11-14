import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// ap4 (v1.0a2 D7): a router whose image has what the bench image lacks; this server seeds it (OPENWRTGUI_SIM_SEED)
test('a later image lists its own LuCI pages', async ({ page }) => {
  await open(page, '/routers/ap4')
  const card = page.getByRole('region', { name: 'LuCI pages on AP4' })
  await expect(card.getByText('SQM QoS').first()).toBeVisible()
  await noHorizontalScroll(page)
})
