import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import { AP2 } from '../../testing/fixtures'
import { AP2_NET, LAN_12_DONE, LAN_12_PLAN, LAN_OPTIONS } from '../../testing/net'
import { NetworkScreen } from './NetworkScreen'

const calls: Array<{ path: string; body: unknown }> = []
let refuse: { status: number; detail: string } | null = null

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap2') return AP2
    if (path === '/api/routers/ap2/network') return AP2_NET
    if (path === '/api/routers/ap2/luci/pages') return []
    if (path === '/api/routers/ap2/network/interfaces/lan/options') return LAN_OPTIONS
    if (path === '/api/routers/ap2/network/leases') return []
    if (path === '/api/routers/ap2/network/access') return { ssids: [], devices: [] }
    if (path === '/api/routers/ap2/network/routes/live') return { routes: [], rules: [], raw: null }
    if (path.endsWith('/preview')) {
      if (refuse) throw new actual.ApiError(refuse.status, refuse.detail, {})
      return LAN_12_PLAN
    }
    if (path === '/api/routers/ap2/network/interfaces/apply') {
      if (refuse) throw new actual.ApiError(refuse.status, refuse.detail, {})
      return LAN_12_DONE
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
  refuse = null
})

function renderNetwork() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap2/network']}>
        <Routes>
          <Route path="/routers/:id/network" element={<NetworkScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function editLan(address: string) {
  const user = userEvent.setup()
  renderNetwork()
  const table = await screen.findByRole('table', { name: 'Router addresses' })
  await user.click(within(table).getByRole('button', { name: 'Edit lan' }))
  const field = screen.getByRole('textbox', { name: 'Address (address/prefix)' })
  await user.clear(field)
  await user.type(field, address)
  return user
}

test('the screen lists the interfaces, marks this app\'s own, and offers help', async () => {
  renderNetwork()
  expect(await screen.findByRole('heading', { name: 'Network and DHCP', level: 1 })).toBeInTheDocument()
  const table = await screen.findByRole('table', { name: 'Router addresses' })
  expect(within(table).getByText("this app's connection")).toBeInTheDocument()
  expect(within(table).getByText('made by lte at run time')).toBeInTheDocument()
  expect(within(table).queryByRole('button', { name: 'Edit lte_4' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Help: Network and DHCP' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Router addresses' })).toBeInTheDocument()
})

test('editing lan previews the change with its rollback note', async () => {
  await editLan('192.168.1.12/24')
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("set network.lan.ipaddr='192.168.1.12/24'")
  expect(screen.getByText(/Applies with a 60 s rollback/)).toBeInTheDocument()
  expect(calls.find((c) => c.path.endsWith('/interfaces/preview'))?.body).toEqual({ name: 'lan', address: '192.168.1.12/24' })
})

test('Apply confirms and names the new address', async () => {
  const user = await editLan('192.168.1.12/24')
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Apply with rollback' }))
  expect(await screen.findByText('Applied and confirmed')).toBeInTheDocument()
  expect(screen.getByText(/AP2 · office is now at 192\.168\.1\.12/)).toBeInTheDocument()
  expect(calls.find((c) => c.path.endsWith('/interfaces/apply'))?.body).toEqual({
    name: 'lan',
    address: '192.168.1.12/24',
    digest: 'c0ffee0123456789',
  })
})

test('a refusal and a guard lock show their reasons', async () => {
  refuse = { status: 422, detail: 'Write the address with its prefix, e.g. 192.168.1.2/24 (a bare address becomes /32 on this image)' }
  await editLan('192.168.1.12')
  expect(await screen.findByRole('alert')).toHaveTextContent('Write the address with its prefix')
})

test('All options come from the router and feed the same preview', async () => {
  const user = await editLan('192.168.1.2/24')
  await user.click(screen.getByRole('button', { name: 'Show all options' }))
  await user.click(await screen.findByRole('button', { name: 'All' }))
  const ip6 = await screen.findByRole('textbox', { name: 'ip6addr' })
  await user.type(ip6, 'fd00::1/64')
  await screen.findByRole('region', { name: 'Command preview' })
  const body = calls.filter((c) => c.path.endsWith('/interfaces/preview')).at(-1)?.body
  expect(body).toEqual({ name: 'lan', edits: [{ section: 'lan', name: 'ip6addr', value: 'fd00::1/64' }] })
})
