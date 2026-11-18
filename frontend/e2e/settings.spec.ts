import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open, TOKEN } from './helpers'

const AUTH = { Authorization: `Bearer ${TOKEN}` }

test('rotating the app key moves every simulated router', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project rotates the simulated routers\' key')
  await open(page, '/settings')
  const card = page.getByRole('region', { name: 'App SSH key' })
  const fingerprint = card.locator('dd.mono').first()
  await expect(fingerprint).toHaveText(/^SHA256:/)
  const before = (await fingerprint.textContent())?.trim()
  await card.getByRole('button', { name: 'Rotate key…', exact: true }).click()
  const preview = card.getByRole('region', { name: 'Rotation preview' })
  await expect(preview).toContainText('AP2 · office (192.168.1.2): moves to the new key')
  await preview.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(card.getByText('Rotated: every router logs in with the new key. The old private key is deleted.')).toBeVisible()
  await expect(fingerprint).not.toHaveText(before ?? '')
  await expect(fingerprint).toHaveText(/^SHA256:/)
  await noHorizontalScroll(page)
  // AP2 still answers, now on the new key: Probe again connects afresh
  const probed = await request.post(`${baseURL}/api/routers/ap2/describe`, { headers: AUTH })
  expect(probed.ok()).toBe(true)
})
