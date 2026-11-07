import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'
import type { CaptureView, FaultsState, Settings } from '../../api/types'
import { AP1 } from '../../testing/fixtures'
import {
  AP1_FAULTS,
  AP2_FAULTS,
  ARMED,
  ARMED_RESULT,
  blockPlan,
  CAPTURED,
  CAPTURING,
  CLEAR_PLAN,
  CLEARED_DURING_RUN,
  PANEL,
  WIRED,
} from '../../testing/faults'
import { FaultsScreen } from './FaultsScreen'

const calls: Array<{ path: string; body: unknown }> = []
let faults: FaultsState = AP1_FAULTS
let captures: CaptureView[] = []
let settings: Settings

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  const respond = async (path: string, body?: unknown): Promise<unknown> => {
    calls.push({ path, body })
    if (path === '/api/routers/ap1') return AP1
    if (path === '/api/routers/ap1/faults') return faults
    if (path === '/api/routers/ap1/luci/pages') return []
    if (path === '/api/settings') {
      if (body) settings = body as Settings
      return settings
    }
    if (path === '/api/routers/ap1/faults/preview') return blockPlan((body as { hold_s: number | null }).hold_s !== null)
    if (path === '/api/routers/ap1/faults/apply') return ARMED_RESULT
    if (path === '/api/routers/ap1/faults/clear/preview') return CLEAR_PLAN
    if (path === '/api/routers/ap1/faults/clear/apply') return CLEARED_DURING_RUN
    if (path === '/api/routers/ap1/captures/devices') return { devices: ['br-lan', 'phy0-ap0', 'mon0'], wireshark: false }
    if (path === '/api/routers/ap1/captures') {
      if (body) {
        captures = [CAPTURING]
        return CAPTURING
      }
      return captures
    }
    if (path === '/api/routers/ap1/captures/c1/stop') {
      captures = [CAPTURED]
      return CAPTURED
    }
    throw new Error(`unexpected ${path}`)
  }
  return {
    ...actual,
    apiFetch: vi.fn((path: string) => respond(path)),
    postJson: vi.fn((path: string, body?: unknown) => respond(path, body ?? {})),
    putJson: vi.fn((path: string, body?: unknown) => respond(path, body)),
  }
})

beforeEach(() => {
  calls.length = 0
  faults = AP1_FAULTS
  captures = []
  settings = { theme: 'light', known_devices: [] } as unknown as Settings
})

function renderFaults() {
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/routers/ap1/faults']}>
        <Routes>
          <Route path="/routers/:id/faults" element={<FaultsScreen />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return user
}

const lastFault = (): unknown => calls.filter((c) => c.path.endsWith('/faults/preview')).at(-1)?.body
const card = (name: string) => screen.getByRole('article', { name })

async function pickPanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^panel · 192\.168\.1\.30/ }))
}

test('the screen has its heading, the armed count and help', async () => {
  renderFaults()
  expect(await screen.findByRole('heading', { name: 'Faults and capture', level: 1 })).toBeInTheDocument()
  expect(await screen.findByText('nothing armed')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Help: Faults and capture' })).toBeInTheDocument()
  expect(screen.getByText(/Ethernet and Wi-Fi MACs are unrelated/)).toBeInTheDocument()
})

test('a Wi-Fi target greys Link down with the reason', async () => {
  const user = renderFaults()
  await pickPanel(user)
  const l1 = card('Link down')
  expect(within(l1).getByText('A switch port cannot disconnect a Wi-Fi station. For Wi-Fi use Deauth or AP down.')).toBeInTheDocument()
  expect(within(l1).getByRole('button', { name: 'Take the port down' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: /^panel-eth/ }))
  expect(within(card('Link down')).queryByText(/cannot disconnect a Wi-Fi station/)).toBeNull()
})

test('rtp_in at 30 % previews the numgen line', async () => {
  const user = renderFaults()
  await pickPanel(user)
  const l3 = card('Block flows')
  await user.click(within(l3).getByRole('button', { name: 'rtp_in' }))
  fireEvent.change(within(l3).getByRole('slider', { name: /Loss/ }), { target: { value: '30' } })
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('numgen random mod 100 < 30')
  await vi.waitFor(() => expect(lastFault()).toEqual({ kind: 'block', target: { mac: PANEL.mac, ip: PANEL.ip }, flow: 'rtp_in', loss: 30, hold_s: null }))
})

test('Hold 60 s adds the router timer', async () => {
  const user = renderFaults()
  await pickPanel(user)
  await user.click(within(card('Block flows')).getByRole('button', { name: 'all_in' }))
  const duration = card('Duration')
  expect(within(duration).getByText(/cleared by a timer on the router itself/)).toBeInTheDocument()
  await user.click(within(duration).getByRole('button', { name: 'Hold, then clear' }))
  const seconds = within(duration).getByLabelText('Hold for (s)')
  await user.clear(seconds)
  await user.type(seconds, '60')
  await vi.waitFor(() => expect(lastFault()).toMatchObject({ kind: 'block', flow: 'all_in', hold_s: 60 }))
  expect(await screen.findByRole('region', { name: 'Command preview' })).toHaveTextContent('start-stop-daemon -S -b -m -p /tmp/owg/fault-a1b2c3.pid')
})

test('Arm shows what the router proved', async () => {
  const user = renderFaults()
  await pickPanel(user)
  await user.click(within(card('Block flows')).getByRole('button', { name: 'rtp_in' }))
  await screen.findByRole('region', { name: 'Command preview' })
  await user.click(screen.getByRole('button', { name: 'Arm' }))
  const result = await screen.findByRole('status', { name: 'Apply result' })
  expect(within(result).getByText('Armed and proven')).toBeInTheDocument()
  expect(within(result).getByText('fault a1b2c3')).toBeInTheDocument()
})

test('Clear everything previews and works while Bench Guard is live', async () => {
  faults = { ...AP1_FAULTS, armed: [ARMED] }
  const user = renderFaults()
  expect(await screen.findByText('1 armed')).toBeInTheDocument()
  const armed = screen.getByRole('table', { name: 'Armed faults' })
  expect(within(armed).getByText(ARMED.summary)).toBeInTheDocument()
  expect(within(armed).getByText('until cleared')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Clear everything' }))
  const clear = screen.getByRole('group', { name: 'Clear faults' })
  expect(await within(clear).findByRole('region', { name: 'Command preview' })).toHaveTextContent('nft delete table netdev benchfault')
  expect(calls.filter((c) => c.path.endsWith('/faults/clear/preview')).at(-1)?.body).toEqual({ ids: null })
  await user.click(within(clear).getByRole('button', { name: 'Clear' }))
  expect(await within(clear).findByText(/Cleared although Bench Guard is live/)).toBeInTheDocument()
})

test('Clear on one row clears that fault only', async () => {
  faults = { ...AP1_FAULTS, armed: [ARMED] }
  const user = renderFaults()
  const armed = await screen.findByRole('table', { name: 'Armed faults' })
  await user.click(within(armed).getByRole('button', { name: 'Clear' }))
  await vi.waitFor(() => expect(calls.filter((c) => c.path.endsWith('/faults/clear/preview')).at(-1)?.body).toEqual({ ids: ['a1b2c3'] }))
})

test('normal is greyed on a router without the distribution table', async () => {
  faults = AP2_FAULTS
  const user = renderFaults()
  await pickPanel(user)
  const netem = card('Impair')
  expect(within(netem).getByRole('option', { name: 'normal · no table on this router' })).toBeDisabled()
  expect(within(netem).getByRole('option', { name: 'uniform' })).not.toBeDisabled()
})

test('without prio or ets netem works only from the target', async () => {
  faults = { ...AP1_FAULTS, caps: { ...AP1_FAULTS.caps, band: null } }
  const user = renderFaults()
  await pickPanel(user)
  const netem = card('Impair')
  expect(within(netem).getByRole('option', { name: 'to target · no prio or ets qdisc on this router' })).toBeDisabled()
  expect(within(netem).getByRole('option', { name: 'both · no prio or ets qdisc on this router' })).toBeDisabled()
  expect(within(netem).getByRole('option', { name: 'from target' })).not.toBeDisabled()
  expect(within(netem).getByLabelText('Direction')).toHaveValue('from')
})

test('netem sends its parameters', async () => {
  const user = renderFaults()
  await pickPanel(user)
  const netem = card('Impair')
  await user.type(within(netem).getByLabelText('Delay ms'), '120')
  await user.selectOptions(within(netem).getByLabelText('Direction'), 'both')
  await user.click(within(netem).getByRole('button', { name: 'Impair target' }))
  await vi.waitFor(() =>
    expect(lastFault()).toMatchObject({ kind: 'netem', netem: { delay_ms: 120, jitter_ms: 0, distribution: 'uniform', loss_pct: 0, reorder_pct: 0, duplicate_pct: 0, direction: 'both' } }),
  )
})

test('another IP / MAC fills a target, and Remember as saves it as a known device', async () => {
  const user = renderFaults()
  await user.click(await screen.findByRole('button', { name: 'other IP / MAC…' }))
  await user.type(screen.getByLabelText('MAC'), WIRED.mac)
  await user.click(within(card('Isolate')).getByRole('button', { name: 'Isolate target' }))
  await vi.waitFor(() => expect(lastFault()).toEqual({ kind: 'isolate', target: { mac: WIRED.mac, ip: null }, hold_s: null }))
  await user.type(screen.getByLabelText('Remember as'), 'panel')
  await user.click(screen.getByRole('button', { name: 'Remember' }))
  await vi.waitFor(() => expect(settings.known_devices).toEqual([{ name: 'panel', macs: [WIRED.mac] }]))
})

test('a capture saves a .pcap and shows its path after Stop', async () => {
  const user = renderFaults()
  const cap = await screen.findByRole('region', { name: 'Capture' })
  await user.selectOptions(await within(cap).findByLabelText('Interface'), 'br-lan')
  await user.type(within(cap).getByLabelText('Filter'), 'udp')
  expect(within(cap).queryByRole('button', { name: 'Live in Wireshark' })).toBeNull()
  await user.click(within(cap).getByRole('button', { name: 'Save .pcap' }))
  expect(calls.find((c) => c.path === '/api/routers/ap1/captures' && c.body && Object.keys(c.body as object).length)?.body).toEqual({
    device: 'br-lan',
    filter: 'udp',
    duration_s: 60,
    output: 'file',
  })
  await user.click(await within(cap).findByRole('button', { name: 'Stop' }))
  expect(await within(cap).findByText(CAPTURED.path as string)).toBeInTheDocument()
})
