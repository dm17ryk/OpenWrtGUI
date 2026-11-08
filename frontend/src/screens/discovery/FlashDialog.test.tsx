import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import type { FlashJob } from '../../api/types'
import { AP2_CHECKLIST, FLASH_PLAN, MINI_PROFILE, NEWER_PROFILE } from '../../testing/discovery'
import { FlashDialog } from './FlashDialog'

const calls: Array<{ path: string; body?: unknown }> = []
const START = '2026-11-08T12:00:00'
const job = (phase: FlashJob['phase'], extra: Partial<FlashJob> = {}): FlashJob => ({
  router_id: 'ap2',
  phase,
  sent: phase === 'upload' ? 32920 : 65840,
  total: 65840,
  started_at: START,
  ...extra,
})
let current: FlashJob | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/images') return [MINI_PROFILE, NEWER_PROFILE]
    if (path === '/api/routers/ap2/flash/preview') return FLASH_PLAN
    if (path === '/api/routers/ap2/flash/start') return job('upload', { sent: 0 })
    if (path === '/api/routers/ap2/flash') return current
    if (path === '/api/routers/ap2/discovery/checklists') return [AP2_CHECKLIST]
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body ?? {})),
  }
})

beforeEach(() => {
  calls.length = 0
  current = null
})

function renderFlash() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <FlashDialog routerId="ap2" routerName="AP2 · office" board="dlink,dwr-921-c3-uboot" revision="r35692-b8bffeefdf" pollMs={20} onClose={vi.fn()} />
    </QueryClientProvider>,
  )
  return user
}

async function typeName(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Type the router’s name to flash it'), 'AP2')
}

test('offers the newer image and needs the router name typed before Flash', async () => {
  const user = renderFlash()
  expect(await screen.findByRole('combobox', { name: 'Image' })).toHaveValue(NEWER_PROFILE.folder)
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('sysupgrade -T /tmp/owg/fw-06988f7bb216.bin')
  expect(screen.getByText(FLASH_PLAN.warnings[0])).toBeVisible()
  const flash = screen.getByRole('button', { name: 'Flash' })
  expect(flash).toBeDisabled()
  await typeName(user)
  expect(flash).toBeEnabled()
  expect(calls.find((c) => c.path.endsWith('/flash/preview'))?.body).toEqual({
    board: 'dlink,dwr-921-c3-uboot',
    revision: 'r35700-0c0ffee000',
    sha256: NEWER_PROFILE.key.sha256,
    keep_settings: true,
    isolated: false,
  })
})

test('needs the isolation tick without keep settings', async () => {
  const user = renderFlash()
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('checkbox', { name: 'Keep settings' }))
  expect(screen.queryByRole('region', { name: 'Command preview' })).not.toBeInTheDocument()
  expect(screen.getByText(/comes back as 192\.168\.1\.1 with no password/)).toBeVisible()
  await user.click(screen.getByRole('checkbox', { name: 'I have isolated AP2 · office from the bench LAN' }))
  expect(await screen.findByRole('region', { name: 'Command preview' })).toBeVisible()
  const previews = calls.filter((c) => c.path.endsWith('/flash/preview')).map((c) => c.body as { keep_settings: boolean; isolated: boolean })
  expect(previews.at(-1)).toMatchObject({ keep_settings: false, isolated: true })
})

test('shows upload progress and the phases until done', async () => {
  const user = renderFlash()
  await screen.findByRole('region', { name: 'Command preview' })
  await typeName(user)
  current = job('upload')
  await user.click(screen.getByRole('button', { name: 'Flash' }))
  expect(calls.find((c) => c.path.endsWith('/flash/start'))?.body).toMatchObject({ digest: FLASH_PLAN.digest, keep_settings: true })
  expect(await screen.findByText('Sending the image: 50 %')).toBeVisible()
  expect(screen.getByRole('progressbar', { name: 'Upload' })).toBeVisible()
  current = job('wait')
  expect(await screen.findByText(/Waiting for AP2 · office to come back \(\d+:\d\d\)/)).toBeVisible()
  current = job('done', { detail: 'Flashed AP2 · office with r35700-0c0ffee000 in 0 min 21 s' })
  expect(await screen.findByText('Flashed AP2 · office with r35700-0c0ffee000 in 0 min 21 s')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Flash' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Copy back lost files' }))
  expect(await screen.findByRole('checkbox', { name: AP2_CHECKLIST.restorable[0] })).toBeChecked()
})

test('a done flash from before can be followed by another', async () => {
  current = job('done', { detail: 'Flashed AP2 · office with r35700-0c0ffee000 in 0 min 21 s' })
  const user = renderFlash()
  expect(await screen.findByText('Flashed AP2 · office with r35700-0c0ffee000 in 0 min 21 s')).toBeVisible()
  expect(screen.queryByRole('combobox', { name: 'Image' })).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Flash again' }))
  expect(await screen.findByRole('combobox', { name: 'Image' })).toBeVisible()
  expect(screen.queryByText(/Flashed AP2/)).not.toBeInTheDocument()
})

test('shows a failed flash with its reason and no Copy back', async () => {
  const user = renderFlash()
  await screen.findByRole('region', { name: 'Command preview' })
  await typeName(user)
  current = job('failed', { error: 'sysupgrade -T: Image check failed' })
  await user.click(screen.getByRole('button', { name: 'Flash' }))
  expect(await screen.findByText('sysupgrade -T: Image check failed')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Copy back lost files' })).not.toBeInTheDocument()
})
