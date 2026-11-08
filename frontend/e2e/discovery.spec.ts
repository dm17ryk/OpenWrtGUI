import { expect, test } from '@playwright/test'
import { IMAGES, IMAGE_FIXTURES as FIXTURES, TOKEN, clearImages, ensureImages, noHorizontalScroll, open } from './helpers'

const BOARD = 'dlink,dwr-921-c3-uboot'
const OLD = `${BOARD} r35692-b8bffeefdf`
const NEW_FOLDER = 'r35700-0c0ffee000-06988f7bb216'
const headers = { Authorization: `Bearer ${TOKEN}` }

test('Settings imports sysupgrade images', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the image store')
  await clearImages(request, baseURL ?? '')
  await open(page, '/settings')
  const images = page.getByRole('region', { name: 'Images' })
  for (const name of IMAGES) await page.getByLabel('Import image…').first().setInputFiles(`${FIXTURES}/${name}`)
  await expect(images.getByText(OLD).first()).toBeVisible()
  await expect(images.getByText(`${BOARD} r35700-0c0ffee000`).first()).toBeVisible()
})

test('Discovery shows what AP1 changed since flashing and fits the window', async ({ page, request, baseURL }) => {
  await ensureImages(request, baseURL ?? '')
  await open(page, '/routers/ap1/discovery')
  await expect(page.getByText(OLD).first()).toBeVisible()
  for (const name of ['Added after flashing', 'Config changed', 'Your custom packages', 'Programs added after flashing', 'Custom services']) {
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  }
  await expect(page.getByText('/usr/sbin/wifi-mirror').first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Ports screen' })).toBeVisible()
  await noHorizontalScroll(page)
})

test('promote wifi-mirror and run its read-only status', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the tool cards')
  await ensureImages(request, baseURL ?? '')
  await request.delete(`${baseURL}/api/tools/${encodeURIComponent(BOARD)}?path=${encodeURIComponent('/usr/sbin/wifi-mirror')}`, { headers })
  await open(page, '/routers/ap1/discovery')
  const row = page.getByRole('listitem').filter({ has: page.getByText('/usr/sbin/wifi-mirror', { exact: true }) }).last()
  await row.getByRole('button', { name: 'Promote' }).click()
  const dialog = page.getByRole('region', { name: 'Promote wifi-mirror to a card' })
  await expect(dialog.getByRole('textbox', { name: 'Command label' })).toHaveCount(3)
  const status = dialog.locator('fieldset').filter({ has: page.locator('input[value="status"]') })
  await status.getByRole('checkbox', { name: 'Changes the router' }).uncheck()
  await dialog.getByRole('button', { name: 'Save card' }).click()
  const card = page.getByRole('region', { name: 'Card wifi-mirror' })
  await card.getByRole('button', { name: 'status' }).click()
  await expect(card.getByRole('region', { name: 'Command preview' })).toContainText('/usr/sbin/wifi-mirror status')
  await card.getByRole('button', { name: 'Run' }).click()
  await expect(card.locator('pre')).toBeVisible()
})

test('flash AP2 with r35700 keeping settings', async ({ page, request, baseURL }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project flashes the simulated router')
  test.setTimeout(150_000)
  await ensureImages(request, baseURL ?? '')
  await open(page, '/routers/ap2/discovery')
  await page.getByRole('button', { name: 'Flash an image…' }).click()
  const dialog = page.getByRole('region', { name: 'Flash AP2 · office' })
  await dialog.getByRole('combobox', { name: 'Image' }).selectOption(NEW_FOLDER)
  await expect(dialog.getByRole('region', { name: 'Command preview' })).toContainText('sysupgrade -T')
  await dialog.getByLabel('Type the router’s name to flash it').fill('AP2')
  await dialog.getByRole('button', { name: 'Flash', exact: true }).click()
  await expect(dialog.getByText(/Flashed AP2 · office with r35700-0c0ffee000/)).toBeVisible({ timeout: 120_000 })
  await expect(dialog.getByRole('button', { name: 'Copy back lost files' })).toBeVisible()
})
