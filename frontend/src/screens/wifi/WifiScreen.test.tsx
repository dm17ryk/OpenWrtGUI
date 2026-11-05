import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { WifiState } from '../../api/types'
import { AP2 } from '../../testing/fixtures'
import { AP2_RADIO, AP2_WIFI, N20_CH6_PLAN, OPTIONS, PANEL, PROVEN } from '../../testing/wifi'
import { WifiScreen } from './WifiScreen'

const calls: Array<{ path: string; body: unknown }> = []
let wifi: WifiState = AP2_WIFI
let applyFails = false

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap2') return AP2
    if (path === '/api/routers/ap2/wifi') return wifi
    if (path === '/api/routers/ap2/wifi/stations') return [PANEL]
    if (path.startsWith('/api/routers/ap2/wifi/options?')) return OPTIONS
    if (path === '/api/routers/ap2/luci/pages') return []
    if (path === '/api/routers/ap2/wifi/preview') return N20_CH6_PLAN
    if (path === '/api/routers/ap2/wifi/apply') {
      if (applyFails) throw new actual.ApiError(423, 'dima_night.py started 21:04 (PID 18244)', {})
      return PROVEN
    }
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body)),
  }
})

beforeEach(() => {
  calls.length = 0
  wifi = AP2_WIFI
  applyFails = false
})

function renderWifi() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap2/wifi']}>
        <Routes>
          <Route path="/routers/:id/wifi" element={<WifiScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function tickN20Ch6() {
  const user = userEvent.setup()
  renderWifi()
  await user.click(await screen.findByRole('button', { name: /802\.11n · 20 MHz/ }))
  await user.click(screen.getByRole('button', { name: 'Channel 6, 2437 MHz' }))
  return user
}

test('the screen and its sections offer help from the manual', async () => {
  renderWifi()
  expect(await screen.findByRole('heading', { name: 'Wi-Fi', level: 1 })).toBeInTheDocument()
  expect(await screen.findByText('parked')).toBeInTheDocument()
  for (const name of ['Wi-Fi', 'Modes', 'Channels', 'TX power', 'SSID and security', 'Apply and proof on air', 'Stations', 'Who may join', 'All options']) {
    expect(screen.getByRole('button', { name: `Help: ${name}` })).toBeInTheDocument()
  }
  expect(screen.getByText('parked')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: '2.4 GHz · radio0' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: '5 GHz · no radio on this router' })).toBeDisabled()
})

test('ticking modes and a channel previews the exact commands', async () => {
  await tickN20Ch6()
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview.textContent).toBe(N20_CH6_PLAN.lines.join('\n'))
  const sent = calls.filter((c) => c.path.endsWith('/preview')).at(-1)?.body
  expect(sent).toEqual({ radio: 'radio0', modes: { kind: 'set', modes: ['n20'] }, channels: { kind: 'set', channels: [6] } })
  expect(screen.getByText(/already on air on AP1/)).toBeInTheDocument()
  expect(screen.getByText('Only n20')).toBeInTheDocument()
  expect(screen.getByText('Fixed · ch 6')).toBeInTheDocument()
})

test('Apply shows what was proven on air', async () => {
  const user = await tickN20Ch6()
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Apply to AP2' }))
  expect(await screen.findByText('Applied and proven on air')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'Apply result' })).toHaveTextContent('6.0 Mb/s ×5')
})

test('a harness run refuses Apply with its reason', async () => {
  applyFails = true
  const user = await tickN20Ch6()
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Apply to AP2' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('dima_night.py started 21:04 (PID 18244)')
})

test('shows the mask-missing note', async () => {
  wifi = { ...AP2_WIFI, radios: [{ ...AP2_RADIO, up: true, modes: { kind: 'set', modes: ['n20'] }, mask: 'missing' }] }
  renderWifi()
  expect(await screen.findByText(/TX mask not active: the radio was reloaded since the last Apply/)).toBeInTheDocument()
})

test('the key is a password field and never part of the screen', async () => {
  const user = userEvent.setup()
  renderWifi()
  const key = await screen.findByLabelText('Key for OpenWrt')
  expect(key).toHaveAttribute('type', 'password')
  await user.type(key, 'new-lab-key')
  await screen.findByRole('region', { name: 'Command preview' })
  expect(document.body.textContent).not.toContain('new-lab-key')
})

test('stations are listed with their actions', async () => {
  renderWifi()
  const table = await screen.findByRole('table', { name: 'Stations' })
  const row = within(table).getByRole('row', { name: /f4:12:fa:f3:57:68/ })
  expect(row).toHaveTextContent('panel · 192.168.1.30')
  expect(row).toHaveTextContent('−52 dBm')
  expect(within(row).getByRole('link', { name: 'RF' })).toHaveAttribute('href', '/routers/ap2/rf?station=f4%3A12%3Afa%3Af3%3A57%3A68')
  expect(within(row).getByRole('button', { name: 'Block' })).toBeInTheDocument()
  expect(within(row).getByRole('button', { name: 'Deauth' })).toBeInTheDocument()
})

test('All options shows the router options with their writer and control', async () => {
  const user = userEvent.setup()
  renderWifi()
  await user.click(await screen.findByRole('button', { name: 'Show all options' }))
  const table = await screen.findByRole('table', { name: 'All options' })
  expect(within(table).getByRole('row', { name: /cell_density/ })).toHaveTextContent('set by dima_night')
  expect(within(table).getByRole('row', { name: /htmode/ })).toHaveTextContent('set above: Modes')
})
