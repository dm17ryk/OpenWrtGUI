import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP2 } from '../../testing/fixtures'
import { AP2_NET_FULL, DHCP_ON_PLAN, DNS_PLAN, HOSTS_PLAN, LEASES, LIVE, ROUTE_PLAN } from '../../testing/net'
import { NetworkScreen } from './NetworkScreen'

const calls: Array<{ path: string; body: unknown }> = []
const refusals: Record<string, string> = {}
const PLANS: Record<string, unknown> = {
  dhcp: DHCP_ON_PLAN,
  hosts: HOSTS_PLAN,
  dns: DNS_PLAN,
  routes: ROUTE_PLAN,
}

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap2') return AP2
    if (path === '/api/routers/ap2/network') return AP2_NET_FULL
    if (path === '/api/routers/ap2/network/leases') return LEASES
    if (path === '/api/routers/ap2/network/routes/live') return LIVE
    if (path === '/api/routers/ap2/network/access') return { ssids: [], devices: [] }
    const preview = /^\/api\/routers\/ap2\/network\/(\w+)\/preview$/.exec(path)
    if (preview) {
      const card = preview[1]
      if (refusals[card]) throw new actual.ApiError(422, refusals[card], {})
      return PLANS[card]
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
  for (const key of Object.keys(refusals)) delete refusals[key]
})

function renderNetwork() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap2/network']}>
        <Routes>
          <Route path="/routers/:id/network" element={<NetworkScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

const lastBody = (card: string): unknown => calls.filter((c) => c.path.endsWith(`/network/${card}/preview`)).at(-1)?.body

test('turning the DHCP server on shows the conflict warning from the preview', async () => {
  const user = renderNetwork()
  const card = await screen.findByRole('region', { name: 'DHCP server' })
  await user.click(within(card).getByRole('switch', { name: 'DHCP server' }))
  expect(await within(card).findByText(/AP1 · bench already serves DHCP on 192\.168\.1\.0\/24/)).toBeInTheDocument()
  expect(lastBody('dhcp')).toEqual({ interface: 'lan', enabled: true })
})

test('Make fixed fills a fixed-address row from the lease', async () => {
  const user = renderNetwork()
  const leases = await screen.findByRole('table', { name: 'Active leases' })
  expect(await within(leases).findAllByText('59 min')).toHaveLength(2)
  expect(within(leases).queryByRole('button', { name: 'Make 192.168.1.10 fixed' })).toBeNull()
  await user.click(within(leases).getByRole('button', { name: 'Make 192.168.1.123 fixed' }))
  const hosts = screen.getByRole('region', { name: 'Fixed addresses by MAC' })
  expect(within(hosts).getByRole('textbox', { name: 'MAC of new address 1' })).toHaveValue('a4:83:e7:12:34:56')
  await within(hosts).findByRole('region', { name: 'Command preview' })
  expect(lastBody('hosts')).toEqual({
    upserts: [{ mac: 'a4:83:e7:12:34:56', name: 'phone', ip: '192.168.1.123', gets_address: true }],
    deletes: [],
  })
})

test('deleting two fixed addresses sends both in one preview', async () => {
  const user = renderNetwork()
  const hosts = await screen.findByRole('region', { name: 'Fixed addresses by MAC' })
  await user.click(await within(hosts).findByRole('button', { name: 'Delete bench-pc' }))
  await user.click(within(hosts).getByRole('button', { name: 'Delete sta-1' }))
  await within(hosts).findByRole('region', { name: 'Command preview' })
  expect(within(hosts).getAllByRole('region', { name: 'Command preview' })).toHaveLength(1)
  expect(lastBody('hosts')).toEqual({ upserts: [], deletes: ['cfg0bfb35', 'cfg0cfb35'] })
})

test('a refused DNS forwarder shows the reason', async () => {
  refusals.dns = '8.8.8.x is not a DNS server (IP, IP#port or /domain/IP)'
  const user = renderNetwork()
  const dns = await screen.findByRole('region', { name: 'DNS' })
  const forwarders = within(dns).getByRole('textbox', { name: 'Forwarders' })
  expect(forwarders).toHaveValue('1.1.1.1')
  await user.type(forwarders, ' 8.8.8.x')
  expect(await within(dns).findByRole('alert')).toHaveTextContent('8.8.8.x is not a DNS server')
  expect(lastBody('dns')).toEqual({ forwarders: ['1.1.1.1', '8.8.8.x'] })
})

test('adding a route previews it with the rollback warning', async () => {
  const user = renderNetwork()
  const card = await screen.findByRole('region', { name: 'Static routes and rules' })
  await user.click(within(card).getByRole('button', { name: '+ Route' }))
  await user.type(within(card).getByRole('textbox', { name: 'Target of new route 1' }), '10.8.0.0/24')
  expect(await within(card).findByText(/Applies with a 60 s rollback/)).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: 'Apply with rollback' })).toBeEnabled()
  expect(lastBody('routes')).toEqual({
    upserts: [{ kind: 'route', interface: 'lan', target: '10.8.0.0/24', disabled: false }],
    deletes: [],
    rule_upserts: [],
    rule_deletes: [],
  })
})

test('the live routing table shows the main table', async () => {
  renderNetwork()
  const card = await screen.findByRole('region', { name: 'Static routes and rules' })
  const live = await within(card).findByRole('table', { name: 'Live routing table' })
  const row = within(live).getByRole('row', { name: /192\.168\.1\.0\/24/ })
  expect(row).toHaveTextContent('br-lan')
  expect(within(live).queryByText('fd12:3456::/64')).toBeNull()
})
