import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { DiscoveryState } from '../../api/types'
import { AP1_DISCOVERY, AP2_FIRMWARE, FLASH_PLAN, MINI_PROFILE, NEWER_PROFILE } from '../../testing/discovery'
import { AP1, ROUTERS } from '../../testing/fixtures'
import { DiscoveryScreen } from './DiscoveryScreen'

const calls: Array<{ path: string; body?: unknown }> = []
let discovery: DiscoveryState = AP1_DISCOVERY
let firmwareError: ApiError | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers') return ROUTERS
    if (path === '/api/guard') return { live: false, reasons: [], checked_at: '2026-11-08T12:00:00' }
    if (path === '/api/tools/dlink%2Cdwr-921-c3-uboot') return []
    if (path === '/api/routers/ap1') return AP1
    if (path === '/api/routers/ap1/discovery') return discovery
    if (path === '/api/routers/ap1/luci/pages') return []
    if (path === '/api/routers/ap1/discovery/firmware') {
      if (firmwareError) throw firmwareError
      return AP2_FIRMWARE
    }
    if (path === '/api/routers/ap1/images/rom') return {}
    if (path === '/api/images') return [MINI_PROFILE, NEWER_PROFILE]
    if (path === '/api/routers/ap1/flash') return null
    if (path === '/api/routers/ap1/flash/preview') return FLASH_PLAN
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
  discovery = AP1_DISCOVERY
  firmwareError = null
})

function renderDiscovery() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap1/discovery']}>
        <Routes>
          <Route path="/routers/:id/discovery" element={<DiscoveryScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

test('shows the matched image and checks the firmware on demand', async () => {
  const user = renderDiscovery()
  expect(await screen.findByText('dlink,dwr-921-c3-uboot r35692-b8bffeefdf')).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Check firmware' }))
  expect(await screen.findByText('The firmware matches mini-r35692.bin')).toBeVisible()
})

test('shows the refusal of the firmware check, not a crash', async () => {
  firmwareError = new ApiError(422, 'The firmware check reads 11 MB of flash; not while dima_night.py runs', null)
  const user = renderDiscovery()
  await user.click(await screen.findByRole('button', { name: 'Check firmware' }))
  expect(await screen.findByText(/not while dima_night\.py runs/)).toBeVisible()
})

test('shows the no-match note with both ways out', async () => {
  discovery = { ...AP1_DISCOVERY, profile: null, match_note: 'No imported image for dlink,dwr-921-c3-uboot r35692-b8bffeefdf.' }
  const user = renderDiscovery()
  expect(await screen.findByText(/No imported image for/)).toBeVisible()
  expect(screen.getByLabelText('Import image…')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Build from this router’s /rom' }))
  expect(calls.some((c) => c.path === '/api/routers/ap1/images/rom')).toBe(true)
})

test('lists what changed since flashing once an image matches', async () => {
  renderDiscovery()
  expect(await screen.findByRole('heading', { name: 'Added after flashing' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Config changed' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Your custom packages' })).toBeVisible()
})

test('no change lists without a matched image', async () => {
  discovery = { ...AP1_DISCOVERY, profile: null, match_note: 'No imported image for dlink,dwr-921-c3-uboot r35692-b8bffeefdf.' }
  renderDiscovery()
  expect(await screen.findByText(/No imported image for/)).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'Added after flashing' })).not.toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Config changed' })).not.toBeInTheDocument()
})

test('Flash an image opens the flash dialog for this router', async () => {
  const user = renderDiscovery()
  await user.click(await screen.findByRole('button', { name: 'Flash an image…' }))
  expect(await screen.findByRole('heading', { name: 'Flash AP1 · bench' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('heading', { name: 'Flash AP1 · bench' })).not.toBeInTheDocument()
})

test('adds Discovery to the router sections, after Overview', async () => {
  renderDiscovery()
  const nav = await screen.findByRole('navigation', { name: /sections/ })
  const links = Array.from(nav.querySelectorAll('a')).map((a) => a.textContent)
  expect(links.slice(0, 2)).toEqual(['Overview', 'Discovery'])
})
