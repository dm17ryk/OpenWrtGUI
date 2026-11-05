import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { BridgeView, GuardOut, UciChange } from '../../api/types'
import { AP2 } from '../../testing/fixtures'
import { DHCP_BRIDGE, LEASE_CHANGE, LUCI_PAGES } from '../../testing/luci'
import { LuciPage } from './LuciPage'

const calls: Array<{ path: string; body: unknown }> = []
let bridge: BridgeView = DHCP_BRIDGE
let changes: UciChange[] = []

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap2') return AP2
    if (path === '/api/guard') return { live: false, reasons: [], checked_at: 'x' }
    if (path === '/api/routers/ap2/luci/pages') return LUCI_PAGES
    if (path === '/api/routers/ap2/luci/open') return bridge
    if (path === '/api/routers/ap2/luci/bridges/b1/changes') return changes
    if (path === '/api/routers/ap2/luci/bridges/b1/close') return { id: 'b1', changes }
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
  bridge = DHCP_BRIDGE
  changes = []
})

function renderLuci(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/routers/ap2/luci?page=admin%2Fnetwork%2Fdhcp']}>
        <Routes>
          <Route path="/routers/:id/luci" element={<LuciPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const closes = () => calls.filter((c) => c.path.endsWith('/close'))

test('opens the page on mount and shows LuCI in a frame', async () => {
  renderLuci()
  const frame = await screen.findByTitle('LuCI page DHCP')
  expect(frame).toHaveAttribute('src', DHCP_BRIDGE.url)
  expect(frame).not.toHaveAttribute('sandbox')
  expect(calls.find((c) => c.path === '/api/routers/ap2/luci/open')?.body).toEqual({ path: 'admin/network/dhcp' })
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('DHCP')
  expect(screen.getByText(/AP2 · .*LuCI page · Network/)).toBeInTheDocument()
  const note = screen.getByRole('note')
  expect(note).toHaveTextContent("Changes made here skip the app's preview and its 60 s rollback")
  expect(within(note).getByText('can change: DHCP settings')).toBeInTheDocument()
  expect(within(note).getByText('session ends 5 min idle or on close')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Back to the router' })).toHaveAttribute('href', '/routers/ap2')
  expect(await screen.findByText(/Nothing yet\. Press Save & Apply/)).toBeInTheDocument()
})

test('a read-only session says so', async () => {
  bridge = { ...DHCP_BRIDGE, access: 'read' }
  renderLuci()
  await screen.findByTitle('LuCI page DHCP')
  const note = screen.getByRole('note')
  expect(note).toHaveTextContent('A harness run is in progress, so the session can only read')
  expect(within(note).getByText('read-only session')).toBeInTheDocument()
})

test('a run starting while the page is open turns it read-only and it stays so', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  renderLuci(client)
  await screen.findByTitle('LuCI page DHCP')
  const live: GuardOut = { live: true, reasons: [], checked_at: 'x' }
  client.setQueryData(['guard'], live)
  expect(await screen.findByText('read-only session')).toBeInTheDocument()
  client.setQueryData(['guard'], { ...live, live: false })
  expect(await screen.findByText('read-only session')).toBeInTheDocument()
  expect(screen.queryByText('can change: DHCP settings')).not.toBeInTheDocument()
})

test('closing ends the session once and shows what changed', async () => {
  const user = userEvent.setup()
  const view = renderLuci()
  await screen.findByTitle('LuCI page DHCP')
  changes = [LEASE_CHANGE]
  await user.click(screen.getByRole('button', { name: 'Close and end session' }))
  expect(await screen.findByText('Session ended')).toBeInTheDocument()
  const row = screen.getByRole('row', { name: /dhcp\.lan\.leasetime/ })
  expect(within(row).getByText('12h')).toBeInTheDocument()
  expect(within(row).getByText('2h')).toBeInTheDocument()
  expect(within(row).getByText('changed via LuCI')).toBeInTheDocument()
  expect(screen.queryByTitle('LuCI page DHCP')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Close and end session' })).toBeDisabled()
  view.unmount()
  expect(closes()).toHaveLength(1)
})

test('closing with no changes says nothing changed', async () => {
  const user = userEvent.setup()
  renderLuci()
  await screen.findByTitle('LuCI page DHCP')
  await user.click(screen.getByRole('button', { name: 'Close and end session' }))
  expect(await screen.findByText('Nothing changed.')).toBeInTheDocument()
  expect(screen.queryByText(/Press Save & Apply/)).not.toBeInTheDocument()
})

test('leaving the page without closing ends the session', async () => {
  const view = renderLuci()
  await screen.findByTitle('LuCI page DHCP')
  view.unmount()
  expect(closes().map((c) => c.path)).toEqual(['/api/routers/ap2/luci/bridges/b1/close'])
})
