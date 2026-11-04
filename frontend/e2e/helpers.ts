import { expect, type APIRequestContext, type Page } from '@playwright/test'

export const TOKEN = 'e2e'

/** Open the app the way the launcher does (token in the hash), then go to a screen. */
export async function open(page: Page, hashPath = '/'): Promise<void> {
  await page.goto(`/#token=${TOKEN}`)
  await expect(page.getByRole('navigation', { name: 'Screens' })).toBeVisible()
  if (hashPath !== '/') await page.goto(`/#${hashPath}`)
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
