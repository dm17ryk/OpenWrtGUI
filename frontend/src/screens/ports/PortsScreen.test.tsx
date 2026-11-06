import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { PortsState } from '../../api/types'
import { AP2 } from '../../testing/fixtures'
import { AP2_PORTS, LAN2_OFF_PLAN, UNMANAGED, VLAN1_PLAN } from '../../testing/ports'
import { PortsScreen } from './PortsScreen'

const calls: Array<{ path: string; body: unknown }> = []
let ports: PortsState = AP2_PORTS

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap2') return AP2
    if (path === '/api/routers/ap2/ports') return ports
    if (path === '/api/routers/ap2/luci/pages') return []
    if (path === '/api/routers/ap2/ports/enable/preview') return LAN2_OFF_PLAN
    if (path === '/api/routers/ap2/ports/vlans/preview') return VLAN1_PLAN
    if (path === '/api/routers/ap2/ports/mirror/preview') throw new actual.ApiError(422, 'LAN2 is the monitor port; it cannot also be a source.', {})
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
  ports = AP2_PORTS
})

function renderPorts() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap2/ports']}>
        <Routes>
          <Route path="/routers/:id/ports" element={<PortsScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

const lastBody = (what: string): unknown => calls.filter((c) => c.path.endsWith(`/ports/${what}/preview`)).at(-1)?.body

test('the own port shows its lock and no switch', async () => {
  renderPorts()
  expect(await screen.findByRole('heading', { name: 'Ports, VLANs, mirroring', level: 1 })).toBeInTheDocument()
  const lan1 = await screen.findByRole('group', { name: 'LAN1' })
  expect(within(lan1).getByText("carries this app's SSH")).toBeInTheDocument()
  expect(within(lan1).getByText('port 3')).toBeInTheDocument()
  expect(within(lan1).getByText(/100 Mb\/s/)).toBeInTheDocument()
  expect(within(lan1).queryByRole('switch')).toBeNull()
  expect(within(screen.getByRole('group', { name: 'LAN2' })).getByRole('switch', { name: 'Enable LAN2' })).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByRole('button', { name: 'Help: Ports, VLANs, mirroring' })).toBeInTheDocument()
})

test('turning LAN2 off previews the one swconfig line', async () => {
  const user = renderPorts()
  await user.click(await screen.findByRole('switch', { name: 'Enable LAN2' }))
  const panel = screen.getByRole('region', { name: 'Front panel' })
  expect(await within(panel).findByRole('region', { name: 'Command preview' })).toHaveTextContent('swconfig dev switch0 port 2 set enable 0')
  expect(within(panel).getByText(/Disabled until the next reboot or network reload/)).toBeInTheDocument()
  expect(lastBody('enable')).toEqual({ port: 2, on: false })
})

test('a VLAN cell click previews the new member list with the rollback', async () => {
  const user = renderPorts()
  const matrix = await screen.findByRole('table', { name: 'VLAN membership' })
  expect(within(matrix).getByRole('columnheader', { name: 'CPU · 6' })).toBeInTheDocument()
  await user.click(within(matrix).getByRole('button', { name: 'VLAN 1 LAN4 untagged' }))
  expect(within(matrix).getByRole('button', { name: 'VLAN 1 LAN4 tagged' })).toBeInTheDocument()
  const vlans = screen.getByRole('region', { name: 'VLANs' })
  expect(await within(vlans).findByRole('region', { name: 'Command preview' })).toHaveTextContent("ports='0t 1 2 3 6t'")
  expect(within(vlans).getByRole('button', { name: 'Apply with rollback' })).toBeEnabled()
  expect(lastBody('vlans')).toEqual({ upserts: [{ section: 'cfg071ec7', vlan: 1, members: { 0: 't', 1: 'u', 2: 'u', 3: 'u', 6: 't' } }], deletes: [] })
})

test('mirroring the monitor port to itself shows the refusal', async () => {
  const user = renderPorts()
  const mirror = await screen.findByRole('region', { name: 'Mirroring' })
  await user.selectOptions(within(mirror).getByRole('combobox', { name: 'Monitor port' }), '2')
  await user.click(within(mirror).getByRole('checkbox', { name: 'LAN2 RX' }))
  expect(await within(mirror).findByRole('alert')).toHaveTextContent('LAN2 is the monitor port; it cannot also be a source.')
  expect(lastBody('mirror')).toEqual({ monitor: 2, sources: [{ port: 2, rx: true, tx: false }] })
  expect(within(mirror).getByText(/promiscuous/)).toBeInTheDocument()
})

test.each([
  [{ present: true, running: true }, 'present · running'],
  [{ present: true, running: false }, 'stopped'],
  [{ present: false, running: null }, 'not on this router'],
])('the Wi-Fi mirror says what the router has (%o)', async (wifi_mirror, text) => {
  ports = { ...AP2_PORTS, wifi_mirror }
  renderPorts()
  const mirror = await screen.findByRole('region', { name: 'Mirroring' })
  expect(within(mirror).getByText(text)).toBeInTheDocument()
  expect(within(mirror).getByText('Stop and restart come with image import (v0.5).')).toBeInTheDocument()
})

test('a router without a managed switch says why', async () => {
  ports = UNMANAGED
  renderPorts()
  expect(await screen.findByText(/not managed by swconfig/)).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'Front panel' })).toBeNull()
})
