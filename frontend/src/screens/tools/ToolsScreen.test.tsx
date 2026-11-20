import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { expect, test, vi } from 'vitest'
import { AP1 } from '../../testing/fixtures'
import { ToolsScreen } from './ToolsScreen'

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string): Promise<unknown> => {
    if (path === '/api/routers/ap1') return AP1
    if (path === '/api/routers/ap1/luci/pages') return []
    throw new Error(`unexpected ${path}`)
  }
  return { ...actual, apiFetch: vi.fn((path: string) => respond(path)) }
})

vi.mock('./PortStatsTab', () => ({ PortStatsTab: () => <p>port stats tab</p> }))
vi.mock('./ConnectionsTab', () => ({ ConnectionsTab: () => <p>connections tab</p> }))
vi.mock('./ThroughputTab', () => ({ ThroughputTab: () => <p>throughput tab</p> }))
vi.mock('./TrafficTab', () => ({ TrafficTab: () => <p>traffic tab</p> }))
vi.mock('./StationsTab', () => ({ StationsTab: () => <p>stations tab</p> }))

const TABS = ['Port statistics', 'Connections', 'Throughput', 'Traffic generator', 'Station management']

function Where() {
  return <output aria-label="path">{useLocation().pathname}</output>
}

function show(entry: string) {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/routers/:id/tools" element={<ToolsScreen />} />
          <Route path="/routers/:id/tools/:tool" element={<ToolsScreen />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

test('Tools is its own section with a tab per tool page', async () => {
  show('/routers/ap1/tools/port-stats')
  expect(await screen.findByRole('link', { name: 'Tools' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(TABS)
  expect(screen.getByRole('tab', { name: 'Port statistics' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByText('port stats tab')).toBeInTheDocument()
})

test('the bare screen lands on Port statistics', async () => {
  show('/routers/ap1/tools')
  expect(await screen.findByText('port stats tab')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'path' })).toHaveTextContent('/routers/ap1/tools/port-stats')
})

test('a tab opens its page', async () => {
  const user = show('/routers/ap1/tools/port-stats')
  await user.click(await screen.findByRole('tab', { name: 'Connections' }))
  expect(screen.getByText('connections tab')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'path' })).toHaveTextContent('/routers/ap1/tools/connections')
})

test('an unknown tool page says so and keeps the tabs', async () => {
  show('/routers/ap1/tools/nope')
  expect(await screen.findByText('No tool page called nope.')).toBeInTheDocument()
  expect(screen.getAllByRole('tab')).toHaveLength(TABS.length)
})

test('the active pages have their own tabs (v1.2b)', async () => {
  const user = show('/routers/ap1/tools/throughput')
  expect(await screen.findByText('throughput tab')).toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: 'Traffic generator' }))
  expect(screen.getByText('traffic tab')).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'path' })).toHaveTextContent('/routers/ap1/tools/traffic')
  await user.click(screen.getByRole('tab', { name: 'Station management' }))
  expect(screen.getByText('stations tab')).toBeInTheDocument()
})
