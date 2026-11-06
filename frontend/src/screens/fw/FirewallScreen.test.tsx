import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { FirewallState, NetApplyResult } from '../../api/types'
import { AP1 } from '../../testing/fixtures'
import { AP1_FW, LAN_BLOCK_PLAN, NOT_FW4, WAN_ALLOW_PLAN, ZONE_PLAN } from '../../testing/fw'
import { AP2_NET } from '../../testing/net'
import { FirewallScreen } from './FirewallScreen'

const calls: Array<{ path: string; body: unknown }> = []
let fw: FirewallState = AP1_FW
let guardLive = false
let modelApplies = 0
const CONFIRMED: NetApplyResult = { router_id: 'ap1', applied: true, verified: true, error: null, host: null, checks: [{ name: 'confirmed', ok: true, detail: 'the router keeps the change' }] }
const NOT_APPLIED: NetApplyResult = { router_id: 'ap1', applied: false, verified: false, error: 'The router restored its previous firewall.', host: null, checks: [{ name: 'restored', ok: true, detail: 'as before' }] }

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap1') return AP1
    if (path === '/api/routers/ap1/firewall') return fw
    if (path === '/api/routers/ap1/network') return AP2_NET
    if (path === '/api/routers/ap1/luci/pages') return []
    if (path === '/api/routers/ap1/firewall/model/preview') {
      const cells = (body as { cells: Record<string, string> }).cells
      return 'lan.input' in cells ? LAN_BLOCK_PLAN : WAN_ALLOW_PLAN
    }
    if (path === '/api/routers/ap1/firewall/model/apply') {
      if (guardLive) throw new actual.ApiError(423, 'dima_night.py started 21:04 (PID 18244)', {})
      modelApplies += 1
      return modelApplies === 1 ? NOT_APPLIED : new Promise(() => {}) // the second one is still waiting
    }
    if (path === '/api/routers/ap1/firewall/zones/preview') return ZONE_PLAN
    if (path === '/api/routers/ap1/firewall/zones/apply') return CONFIRMED
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
  fw = AP1_FW
  guardLive = false
  modelApplies = 0
})

function renderFirewall(at = '/routers/ap1/firewall') {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/routers/:id/firewall" element={<FirewallScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

const cell = (name: string) => screen.findByRole('group', { name })
const lastModel = (): unknown => calls.filter((c) => c.path.endsWith('/model/preview')).at(-1)?.body

test('the grid shows each zone and direction, and the own zone carries the badge', async () => {
  renderFirewall()
  expect(await screen.findByRole('heading', { name: 'Firewall', level: 1 })).toBeInTheDocument()
  expect(screen.getByText('nftables · fw4')).toBeInTheDocument()
  const grid = await screen.findByRole('table', { name: 'Filtering model' })
  const lan = within(grid).getByRole('row', { name: /^lan/ })
  expect(within(lan).getByText("carries this app's SSH")).toBeInTheDocument()
  expect(within(within(grid).getByRole('row', { name: /^wan/ })).queryByText("carries this app's SSH")).toBeNull()
  expect(within(await cell('wan To this router')).getByRole('button', { name: 'Block all' })).toHaveAttribute('aria-pressed', 'true')
  expect(within(await cell('lan Through the router')).getByRole('button', { name: 'Allow all' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByText(/Kept open by the app/)).toBeNull()
})

test('lan input to Block all shows the pins and a preview with the SSH pin and the rollback', async () => {
  const user = renderFirewall()
  await user.click(within(await cell('lan To this router')).getByRole('button', { name: 'Block all' }))
  expect(screen.getByText('Kept open by the app on lan, so it cannot lock itself out')).toBeInTheDocument()
  expect(screen.getByText('Allow SSH from this PC')).toBeInTheDocument()
  expect(screen.getByText('Allow DHCP and DNS')).toBeInTheDocument()
  const preview = await screen.findByRole('region', { name: 'Command preview' })
  expect(preview).toHaveTextContent("set firewall.owg_pin_ssh='rule'")
  expect(screen.getByText(/Applies with a 60 s rollback/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Apply with rollback' })).toBeInTheDocument()
  expect(lastModel()).toEqual({ cells: { 'lan.input': 'REJECT' }, pins_removed: [] })
})

test('Remove… warns first; Remove anyway sends the pin, Put back takes it back', async () => {
  const user = renderFirewall()
  await user.click(within(await cell('lan To this router')).getByRole('button', { name: 'Block all' }))
  const [removeSsh] = screen.getAllByRole('button', { name: 'Remove…' })
  await user.click(removeSsh)
  expect(screen.getByText('Without this rule the app loses AP1 · bench as soon as the change applies. The 60 s rollback then restores the old firewall by itself.')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Keep it' }))
  expect(screen.queryByText(/Without this rule the app loses/)).toBeNull()
  await user.click(screen.getAllByRole('button', { name: 'Remove…' })[0])
  await user.click(screen.getByRole('button', { name: 'Remove anyway' }))
  expect(screen.getByText('removed')).toBeInTheDocument()
  await vi.waitFor(() => expect(lastModel()).toEqual({ cells: { 'lan.input': 'REJECT' }, pins_removed: ['ssh'] }))
  await user.click(screen.getByRole('button', { name: 'Put back' }))
  await vi.waitFor(() => expect(lastModel()).toEqual({ cells: { 'lan.input': 'REJECT' }, pins_removed: [] }))
})

test('Dropped makes every blocked cell DROP', async () => {
  const user = renderFirewall()
  await screen.findByRole('table', { name: 'Filtering model' })
  await user.click(screen.getByRole('button', { name: 'Dropped · silent' }))
  await vi.waitFor(() => expect(lastModel()).toEqual({ cells: { 'wan.input': 'DROP', 'wan.forward': 'DROP' }, pins_removed: [] }))
  expect(within(screen.getByRole('table', { name: 'Filtering model' })).getAllByText('rules allow · rest dropped')).toHaveLength(2)
})

test('the rules table flags Allow-Ping when wan input becomes Allow all', async () => {
  const user = renderFirewall()
  const rules = await screen.findByRole('table', { name: 'Your rules in this model' })
  const ping = within(rules).getByRole('row', { name: /Allow-Ping/ })
  expect(within(ping).getByText('allows')).toBeInTheDocument()
  expect(within(ping).getByText('12')).toBeInTheDocument()
  expect(screen.queryByText(/no longer do anything/)).toBeNull()
  await user.click(within(await cell('wan To this router')).getByRole('button', { name: 'Allow all' }))
  expect(within(ping).getByText('no effect · zone already allows this')).toBeInTheDocument()
  expect(ping).toHaveClass('flag')
  expect(screen.getByText(/^3 rules no longer do anything in this model\./)).toBeInTheDocument()
})

test('a 423 on apply shows the guard reason', async () => {
  guardLive = true
  const user = renderFirewall()
  await user.click(within(await cell('wan To this router')).getByRole('button', { name: 'Allow all' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Apply with rollback' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('dima_night.py started 21:04 (PID 18244)')
})

test('the zones table lists policies, masquerade and forwardings, and Edit previews a zone', async () => {
  const user = renderFirewall()
  const zones = await screen.findByRole('table', { name: 'Zones' })
  const wan = within(zones).getByRole('row', { name: /^wan/ })
  expect(within(wan).getByText('wan, wan6, lte')).toBeInTheDocument()
  expect(within(within(zones).getByRole('row', { name: /^lan/ })).getByText('wan')).toBeInTheDocument()
  await user.click(within(wan).getByRole('button', { name: 'Edit' }))
  const editor = screen.getByRole('group', { name: 'Zone wan' })
  await user.click(within(editor).getByRole('checkbox', { name: 'Masquerade' }))
  await screen.findByRole('region', { name: 'Command preview' })
  const body = calls.filter((c) => c.path.endsWith('/zones/preview')).at(-1)?.body as { upserts: Array<Record<string, unknown>> }
  expect(body.upserts[0]).toMatchObject({ section: 'cfg03dc81', name: 'wan', masq: false, mtu_fix: true, networks: ['wan', 'wan6', 'lte'] })
})

test('tabs live in the URL', async () => {
  renderFirewall('/routers/ap1/firewall?tab=zones')
  expect(await screen.findByRole('tab', { name: 'Zones and model' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tab', { name: 'Raw ruleset' })).toHaveAttribute('aria-selected', 'false')
})

test('a router without fw4 says so and offers LuCI', async () => {
  fw = NOT_FW4
  renderFirewall()
  expect(await screen.findByText('This router does not run fw4 (firewall4); its firewall is not managed here.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Open LuCI's firewall/ })).toHaveAttribute('href', '/routers/ap1/luci?page=admin%2Fnetwork%2Ffirewall%2Fzones')
  expect(screen.queryByRole('table', { name: 'Filtering model' })).toBeNull()
})

test('help buttons are next to the heading and the cards', async () => {
  renderFirewall()
  await screen.findByRole('table', { name: 'Filtering model' })
  for (const name of ['Help: Firewall', 'Help: Filtering model', 'Help: Zones']) {
    expect(screen.getByRole('button', { name })).toBeInTheDocument()
  }
})

test('a zone edit Apply shows its result after the editor closes', async () => {
  const user = renderFirewall()
  const zones = await screen.findByRole('table', { name: 'Zones' })
  await user.click(within(within(zones).getByRole('row', { name: /^wan/ })).getByRole('button', { name: 'Edit' }))
  await user.click(within(screen.getByRole('group', { name: 'Zone wan' })).getByRole('checkbox', { name: 'Masquerade' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: /^Apply/ }))
  await vi.waitFor(() => expect(screen.queryByRole('group', { name: 'Zone wan' })).toBeNull())
  expect(screen.getByText('Applied and confirmed')).toBeInTheDocument()
})

test('a new Apply hides the last result while it runs', async () => {
  const user = renderFirewall()
  await user.click(within(await cell('wan To this router')).getByRole('button', { name: 'Allow all' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Apply with rollback' }))
  expect(await screen.findByText(/^Not applied/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Apply with rollback' }))
  expect(screen.queryByText(/^Not applied/)).toBeNull()
  expect(screen.getByRole('button', { name: 'Applying…' })).toBeDisabled()
})
