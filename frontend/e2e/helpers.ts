import { readFileSync } from 'node:fs'
import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const TOKEN = 'e2e'
export const IMAGE_FIXTURES = '../tests/fixtures/images'
export const IMAGES = ['mini-r35692.bin', 'mini-r35700.bin']
const AUTH = { Authorization: `Bearer ${TOKEN}` }

export async function clearImages(request: APIRequestContext, baseURL: string): Promise<void> {
  const listed = (await (await request.get(`${baseURL}/api/images`, { headers: AUTH })).json()) as Array<{ key: { board: string }; folder: string }>
  for (const p of listed) {
    await request.delete(`${baseURL}/api/images/${encodeURIComponent(p.key.board)}/${encodeURIComponent(p.folder)}`, { headers: AUTH })
  }
}

/** Both mini images imported; one already there is fine ("already imported"). */
export async function ensureImages(request: APIRequestContext, baseURL: string): Promise<void> {
  for (const name of IMAGES) {
    const res = await request.post(`${baseURL}/api/images`, {
      headers: { ...AUTH, 'Content-Type': 'application/octet-stream', 'X-File-Name': name },
      data: readFileSync(`${IMAGE_FIXTURES}/${name}`),
    })
    if (!res.ok()) expect(await res.text()).toContain('already imported')
  }
}

/** Open the app the way the launcher does (token in the hash), then go to a screen. */
export async function open(page: Page, hashPath = '/'): Promise<void> {
  await page.goto(`/#token=${TOKEN}`)
  await expect(page.getByRole('navigation', { name: 'Screens' })).toBeVisible()
  if (hashPath !== '/') await page.goto(`/#${hashPath}`)
}

/**
 * Wait until the app's own step-through preview for a radio carries no warning. The one-radio-per-SSID rule (plan
 * D9) reads the routers' statuses the poller refreshes every 5 s: right after another router with the same SSID
 * parks (wifi.spec's n20 test parks AP2), the preview still says the SSID is on air there, the card asks for it
 * only once, and Start stays disabled (the 2026-11-13 gate flake, a 60 s click timeout under load).
 */
export async function stepThroughClear(request: APIRequestContext, routerId: string, body: object): Promise<void> {
  const warnings = async (): Promise<string[]> => {
    const res = await request.post(`/api/routers/${routerId}/wifi/step-through/preview`, { headers: AUTH, data: body })
    return ((await res.json()) as { warnings: string[] }).warnings
  }
  await expect.poll(warnings, { timeout: 30_000, intervals: [500, 1000] }).toEqual([])
}

export async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
}

export async function removeRouterAt(request: APIRequestContext, baseURL: string, host: string): Promise<void> {
  const headers = { Authorization: `Bearer ${TOKEN}` }
  const items = (await (await request.get(`${baseURL}/api/routers`, { headers })).json()) as Array<{ record: { id: string; host: string } }>
  for (const item of items.filter((i) => i.record.host === host)) {
    await request.delete(`${baseURL}/api/routers/${item.record.id}`, { headers })
  }
}
