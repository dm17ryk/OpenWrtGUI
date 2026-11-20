import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Connections, NetApplyResult, NetPlan, SipAlg, SipAlgZones } from '../../api/types'
import { ConnectionsTab } from './ConnectionsTab'

const calls: string[] = []
const posts: Array<[string, unknown]> = []
let table: Connections
let sip: SipAlg
let zones: SipAlgZones

const TEN = ['amanda', 'RAS', 'Q.931', 'irc', 'netbios-ns', 'pptp', 'sane', 'sip', 'snmp', 'tftp']
const ROLLBACK = 'AP1 rolls the firewall back by itself in 60 s unless the app confirms the change.'
const KEEP = 'Connections set up before the change keep their helper until they end.'
const OFF_PLAN: NetPlan = {
  router_id: 'ap1',
  screen: 'Firewall',
  lines: ["uci set firewall.cfg02dc81.auto_helper='0'", "uci add_list firewall.cfg02dc81.helper='amanda'"],
  warnings: [KEEP, ROLLBACK],
  rollback: true,
  target_host: '192.168.1.1',
  digest: '5115115115115115',
}
const OFF_RESULT: NetApplyResult = {
  router_id: 'ap1',
  applied: true,
  verified: true,
  error: null,
  host: '192.168.1.1',
  checks: [
    { name: 'confirmed', ok: true, detail: 'the app reached the router' },
    { name: 'SIP ALG zone lan', ok: true, detail: "off in fw4's ruleset" },
    { name: 'other helpers zone lan', ok: true, detail: '9 kept' },
  ],
}

vi.mock('../../api/client', async (orig) => {
  const actual = await orig<typeof import('../../api/client')>()
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string) => {
      calls.push(path)
      if (path === '/api/routers/ap1/system/connections') return table
      if (path === '/api/routers/ap1/system/sip-alg') return sip
      if (path === '/api/routers/ap1/firewall/sip-alg') return zones
      throw new Error(`unexpected ${path}`)
    }),
    postJson: vi.fn(async (path: string, body: unknown) => {
      posts.push([path, body])
      if (path === '/api/routers/ap1/firewall/sip-alg/preview') return OFF_PLAN
      if (path === '/api/routers/ap1/firewall/sip-alg/apply') {
        zones = { state: 'off', available: TEN, zones: [{ zone: 'lan', section: 'cfg02dc81', sip: false, helpers: TEN.filter((h) => h !== 'sip') }] }
        sip = { state: 'off', zones: [], ports: [] }
        return OFF_RESULT
      }
      throw new Error(`unexpected ${path}`)
    }),
  }
})

const ROWS: Connections['rows'] = [
  { proto: 'udp', src: '192.168.1.30', dst: '192.168.1.1', sport: 5060, dport: 5060, state: null, bytes: 12300, helper: 'sip' },
  { proto: 'tcp', src: '192.168.1.10', dst: '192.168.1.2', sport: 53498, dport: 22, state: 'ESTABLISHED', bytes: 10000, helper: null },
  { proto: 'udp', src: '192.168.1.2', dst: '10.64.12.1', sport: 5353, dport: 53, state: null, bytes: 60, helper: null },
]

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  calls.length = 0
  posts.length = 0
  table = { rows: ROWS, note: null, total: 3, limit: 16384 }
  sip = { state: 'on', zones: ['lan'], ports: [5060] }
  zones = { state: 'on', available: TEN, zones: [{ zone: 'lan', section: 'cfg02dc81', sip: true, helpers: TEN }] }
})

afterEach(() => {
  vi.useRealTimers()
})

function show() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ConnectionsTab routerId="ap1" />
    </QueryClientProvider>,
  )
  return user
}

test('the summary, the SIP ALG badge and a Helper column', async () => {
  show()
  expect(await screen.findByText('3 connections of 16384')).toBeInTheDocument()
  expect(await screen.findByText('SIP ALG on: zone lan, UDP port 5060')).toBeInTheDocument()
  const t = screen.getByRole('table', { name: 'Connections' })
  expect(within(t).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
    'Protocol',
    'Source',
    'Destination',
    'State',
    'Bytes',
    'Helper',
  ])
  expect(within(t).getAllByRole('row')).toHaveLength(4)
  expect(screen.getByText('udp 2 · tcp 1')).toBeInTheDocument()
})

test('a count read a moment after the table does not claim the table was cut', async () => {
  table = { ...table, total: 5 }
  show()
  expect(await screen.findByText('5 connections of 16384')).toBeInTheDocument()
})

test('a table cut at 500 entries says so', async () => {
  table = { ...table, rows: Array.from({ length: 500 }, () => ROWS[1]), total: 1200 }
  show()
  expect(await screen.findByText('1200 connections of 16384, showing the first 500')).toBeInTheDocument()
})

test('SIP ALG off and unknown', async () => {
  sip = { state: 'off', zones: [], ports: [] }
  show()
  expect(await screen.findByText('SIP ALG off')).toBeInTheDocument()
})

test('SIP ALG unknown', async () => {
  sip = { state: 'unknown', zones: [], ports: [] }
  show()
  expect(await screen.findByText('SIP ALG unknown: this router has no fw4 ruleset')).toBeInTheDocument()
})

test('filters run in the page', async () => {
  const user = show()
  const t = await screen.findByRole('table', { name: 'Connections' })
  await user.click(screen.getByRole('checkbox', { name: 'SIP only' }))
  expect(within(t).getAllByRole('row')).toHaveLength(2)
  await user.click(screen.getByRole('checkbox', { name: 'SIP only' }))
  await user.type(screen.getByPlaceholderText('Address or port'), '53')
  expect(within(t).getAllByRole('row')).toHaveLength(3) // 53498 and 53
  await user.clear(screen.getByPlaceholderText('Address or port'))
  await user.selectOptions(screen.getByRole('combobox', { name: 'Protocol' }), 'tcp')
  expect(within(t).getAllByRole('row')).toHaveLength(2)
})

test('the rows refresh every 5 s; the SIP ALG state only on Refresh', async () => {
  const user = show()
  await screen.findByText('SIP ALG on: zone lan, UDP port 5060')
  const count = (path: string): number => calls.filter((c) => c === path).length
  expect(count('/api/routers/ap1/system/connections')).toBe(1)
  await act(() => vi.advanceTimersByTimeAsync(5000))
  expect(count('/api/routers/ap1/system/connections')).toBe(2)
  expect(count('/api/routers/ap1/system/sip-alg')).toBe(1)
  sip = { state: 'off', zones: [], ports: [] }
  await user.click(screen.getByRole('button', { name: 'Refresh' }))
  expect(await screen.findByText('SIP ALG off')).toBeInTheDocument()
  expect(count('/api/routers/ap1/system/sip-alg')).toBe(2)
})

test('each zone with helpers is a row with its switch (v1.2b R7)', async () => {
  show()
  const switches = await screen.findByRole('region', { name: 'Switch SIP ALG' })
  expect(within(switches).getByText('Zone lan · SIP ALG on')).toBeInTheDocument()
  expect(within(switches).getByRole('button', { name: 'Turn SIP ALG off in zone lan' })).toBeInTheDocument()
})

test('the switch previews with both warnings, applies, and reads again', async () => {
  const user = show()
  await user.click(await screen.findByRole('button', { name: 'Turn SIP ALG off in zone lan' }))
  expect(await screen.findByText(KEEP)).toBeInTheDocument()
  expect(screen.getByText(ROLLBACK)).toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Command preview' })).toHaveTextContent("uci set firewall.cfg02dc81.auto_helper='0'")
  await user.click(screen.getByRole('button', { name: 'Apply with rollback' }))
  expect(posts).toContainEqual(['/api/routers/ap1/firewall/sip-alg/apply', { zone: 'lan', on: false, digest: '5115115115115115' }])
  const result = await screen.findByRole('status', { name: 'Apply result' })
  expect(within(result).getByText("off in fw4's ruleset")).toBeInTheDocument()
  expect(within(result).getByText('9 kept')).toBeInTheDocument()
  expect(await screen.findByText('Zone lan · SIP ALG off')).toBeInTheDocument()
  expect(await screen.findByText('SIP ALG off')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Turn SIP ALG on in zone lan' })).toBeInTheDocument()
})

test('a router without fw4 has no switch', async () => {
  zones = { state: 'unknown', available: [], zones: [] }
  sip = { state: 'unknown', zones: [], ports: [] }
  show()
  await screen.findByText('SIP ALG unknown: this router has no fw4 ruleset')
  expect(screen.queryByRole('button', { name: /Turn SIP ALG/ })).toBeNull()
})

test('a note instead of the table', async () => {
  table = { rows: [], note: 'The connection table is not available: nf_conntrack is not loaded', total: null, limit: null }
  show()
  expect(await screen.findByText('The connection table is not available: nf_conntrack is not loaded')).toBeInTheDocument()
  expect(screen.queryByRole('table')).toBeNull()
})
