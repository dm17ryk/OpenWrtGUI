import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { SystemMessage, SystemOverview } from '../../api/types'
import { AP2 } from '../../testing/fixtures'
import { AP2_CONNECTIONS, AP2_SYSTEM } from '../../testing/system'
import { SystemScreen } from './SystemScreen'

vi.mock('uplot', () => ({
  default: class {
    setData(): void {}
    setSize(): void {}
    destroy(): void {}
  },
}))

let overview: SystemOverview = AP2_SYSTEM

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      if (path === '/api/routers/ap2') return AP2
      if (path === '/api/routers/ap2/system') return overview
      if (path === '/api/routers/ap2/system/connections') return AP2_CONNECTIONS
      if (path === '/api/guard') return { live: false, reasons: [], checked_at: '2026-11-09T12:00:00' }
      if (path === '/api/routers/ap2/luci/pages') return []
      throw new Error(`unexpected ${path}`)
    }),
  }
})

class FakeSocket {
  static last: FakeSocket | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.last = this
  }
  send(): void {}
  close(): void {}
  emit(msg: SystemMessage): void {
    act(() => this.onmessage?.({ data: JSON.stringify(msg) }))
  }
}

beforeEach(() => {
  overview = AP2_SYSTEM
  vi.stubGlobal('WebSocket', FakeSocket)
})
afterEach(() => vi.unstubAllGlobals())

function renderSystem(entry = '/routers/ap2/system') {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/routers/:id/system" element={<SystemScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('status shows the model, firmware, uptime, load and memory', async () => {
  renderSystem()
  expect(await screen.findByRole('heading', { name: 'System', level: 1 })).toBeInTheDocument()
  const card = await screen.findByRole('region', { name: 'Overview' })
  expect(card).toHaveTextContent('D-Link DWR-921 C3 (U-Boot)')
  expect(card).toHaveTextContent('OpenWrt SNAPSHOT r35692-b8bffeefdf')
  expect(card).toHaveTextContent('1 d 0 h')
  expect(card).toHaveTextContent('0.16 / 0.03 / 0.01')
  expect(card).toHaveTextContent('7.3 MiB free of 53.8 MiB')
  expect(screen.getByRole('tab', { name: 'Status' })).toHaveAttribute('aria-selected', 'true')
  for (const name of ['System', 'Overview', 'Live load, bandwidth and connections']) {
    expect(screen.getByRole('button', { name: `Help: ${name}` })).toBeInTheDocument()
  }
})

test('live samples draw the charts; an idle message shows its reason', async () => {
  renderSystem()
  await screen.findByRole('region', { name: 'Overview' })
  expect(FakeSocket.last?.url).toContain('/ws/system/ap2')
  FakeSocket.last?.emit({ type: 'system-idle', reason: 'No answer from the router' })
  expect(screen.getByRole('status')).toHaveTextContent('No answer from the router')
  FakeSocket.last?.emit({
    type: 'system',
    sample: { t: 1_793_707_203, load1: 0.2, load5: 0.1, load15: 0.05, connections: 12, rates: { 'br-lan': [12000, 30000], eth0: [1, 2] } },
  })
  expect(screen.queryByText('No answer from the router')).not.toBeInTheDocument()
  for (const chart of ['Load', 'Bandwidth', 'Connections']) {
    expect(screen.getByRole('figure', { name: chart })).toBeInTheDocument()
  }
  const picker = screen.getByRole('combobox', { name: 'Interface' })
  expect(within(picker).getAllByRole('option').map((o) => o.textContent)).toEqual(['br-lan', 'eth0'])
})

test('parts that did not answer are named', async () => {
  overview = { ...AP2_SYSTEM, missing: ['board'] }
  renderSystem()
  expect(await screen.findByText('No answer from the router for: board')).toBeInTheDocument()
})

test('the connection table opens on request', async () => {
  const user = userEvent.setup()
  renderSystem()
  await user.click(await screen.findByRole('button', { name: 'Show connections' }))
  const table = await screen.findByRole('table', { name: 'Connections' })
  expect(within(table).getAllByRole('row')).toHaveLength(AP2_CONNECTIONS.rows.length + 1)
  expect(table).toHaveTextContent('ESTABLISHED')
})
